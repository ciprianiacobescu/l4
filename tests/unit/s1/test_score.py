import json
from pathlib import Path

import httpx

from l4.llm.system_one import SystemOneBackend
from l4.redact import Redactor
from l4.s1 import score as sc

ROW = {
    "state": "state", "language": "en", "expected": {"s": "implemented"}, "tags": [],
    "questions": {
        "n": {"type": "noul", "instructions": "ok?"},
        "s": {"type": "choice", "instructions": "state?", "criteria": {"implemented": "a", "contradicted": "c"}},
    },
}  # fmt: skip


def backend(handler) -> SystemOneBackend:
    return SystemOneBackend("jev", model="jev-latest", base_url="http://j.test", api_key="k" * 12,
                            transport=httpx.MockTransport(handler), redactor=Redactor({}))  # fmt: skip


def test_both_option_orders_in_one_request_cap_and_dead_server(tmp_path: Path):
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 3:
            return httpx.Response(503)
        probs = {k: 0.5 for k in body["questions"]["s"]["criteria"]}
        answers = {"n": {"type": "noul", "noul": 0.8}}
        for qid in ("s", "s__rev"):
            answers[qid] = {"type": "choice", "choice": next(iter(probs)), "probabilities": probs}
        return httpx.Response(200, json={"model": "served", "answers": answers})

    out = tmp_path / "answers.jsonl"
    with backend(handler) as b:
        summary = sc.score_dataset(b, [ROW] * 5, out, profile="jev", dataset_sha256="x" * 64, max_requests=4)
    assert (summary.asked, summary.errors, summary.skipped) == (3, 1, 2)  # the dead server ends the run early
    assert list(bodies[0]["questions"]) == ["n", "s", "s__rev"]
    fwd, rev = bodies[0]["questions"]["s"]["criteria"], bodies[0]["questions"]["s__rev"]["criteria"]
    assert list(fwd) == ["implemented", "contradicted"] and list(rev) == ["contradicted", "implemented"]
    lines = [json.loads(x) for x in out.read_text().splitlines()]
    assert lines[0]["kind"] == "header" and lines[0]["profile"] == "jev" and lines[0]["dataset_sha256"] == "x" * 64
    assert "k" * 12 not in out.read_text()
    assert [x.get("error") for x in lines[1:]] == [None, None, "the System-One server answered HTTP 503"]
    assert lines[1]["answers"]["s__rev"]["kind"] == "choice" and lines[1]["model"] == "served"


def test_an_unexpected_error_is_recorded_stops_the_run_and_counts_every_request(tmp_path: Path):
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(1)
        raise RuntimeError("secret detail")

    out = tmp_path / "answers.jsonl"
    with backend(handler) as b:
        summary = sc.score_dataset(b, [ROW] * 6, out, profile="jev", dataset_sha256="x" * 64, max_requests=4)
    assert (summary.asked, summary.errors, summary.skipped) == (1, 1, 5) and len(sent) == 1
    assert "secret detail" not in out.read_text() and "RuntimeError" in out.read_text()


def test_the_header_names_the_checkpoint_a_profile_serves(tmp_path: Path):
    out = tmp_path / "answers.jsonl"
    ident = {"checkpoint_id": "ck", "checkpoint_sha256": "a" * 64, "checkpoint_dataset_sha256": "b" * 64}
    with backend(lambda r: httpx.Response(200, json={"model": "m", "answers": {}})) as b:
        sc.score_dataset(b, [], out, profile="tuned", dataset_sha256="x" * 64, identity=ident)
    assert json.loads(out.read_text().splitlines()[0])["checkpoint_sha256"] == "a" * 64


def test_run_score_stamps_the_checkpoint_identity_into_the_header(tmp_path: Path):
    from l4.config.schema import L4Config

    ckpt = tmp_path / "cache" / "s1" / "checkpoints" / "ck1"
    ckpt.mkdir(parents=True)
    (ckpt / "l4-train.json").write_text(
        json.dumps({"files": {"model.safetensors": "a" * 64}, "dataset_sha256": "b" * 64})
    )
    dataset = tmp_path / "test.jsonl"
    dataset.write_text(json.dumps(ROW) + "\n")
    cfg = L4Config.model_validate({"profiles": {"tuned": {"backend": "system-one", "engine": "laya-local",
                                                          "model": str(ckpt)}}})  # fmt: skip
    opened = []

    def opener(config, profile, **kwargs):
        opened.append(profile)
        return backend(lambda r: httpx.Response(200, json={"model": "served", "answers": {}}))

    out = tmp_path / "answers.jsonl"
    summary = sc.run_score(cfg, "tuned", dataset, out, redactor=Redactor({}), opener=opener)
    header = json.loads(out.read_text().splitlines()[0])
    assert opened == ["tuned"] and summary.asked == 1
    assert (header["checkpoint_id"], header["checkpoint_sha256"], header["checkpoint_dataset_sha256"]) == (
        "ck1", "a" * 64, "b" * 64,
    )  # fmt: skip
    assert header["dataset_sha256"] == sc.file_sha256(dataset)
    # a hosted profile carries no checkpoint stamp
    plain = L4Config.model_validate(
        {"profiles": {"jev": {"backend": "system-one", "engine": "jev", "model": "jev-latest"}}}
    )
    sc.run_score(plain, "jev", dataset, out, redactor=Redactor({}), opener=opener)
    assert "checkpoint_id" not in json.loads(out.read_text().splitlines()[0])
