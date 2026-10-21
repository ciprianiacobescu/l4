"""M1.6b round 4: a checkpoint whose gate FAILED can still be scored, so that the report compares it with the hosted
engine whether the gate passed or failed (plan: the three-way comparison). Only `l4 s1 score` may load it."""

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from l4.llm.s1_checkpoint import CheckpointGateFailed
from l4.llm.system_one import SystemOneBackend, open_s1_profile
from l4.redact import Redactor
from l4.s1 import export as ex
from l4.s1 import records as rec
from l4.s1 import report as rp
from l4.s1 import score as sc

from ..llm.test_system_one_checkpoint import cfg_for, env_for, sha
from ._make import make_item
from ._tune import load

tune = load("laya_tune")


def exported(tmp_path: Path) -> tuple[Path, dict]:
    items = [make_item(f"k{n:030d}", unit=f"openspec:u{n}", truth={"tests_ok": n % 2 == 0}) for n in range(30)]
    cal = tmp_path / "cal.jsonl"
    rec.append_records([cal], items)
    out = tmp_path / "ds"
    manifest = ex.write_dataset(ex.ground_truth_rows([cal]), out, seed=5)
    return out, manifest


def trained_stub(cache: Path, manifest: dict) -> tuple[Path, dict]:
    """What `laya_tune.py train` leaves: weights, config, and a record whose gate has not run."""
    ckpt = cache / "s1" / "checkpoints" / "stub"
    ckpt.mkdir(parents=True)
    (ckpt / "model.safetensors").write_bytes(b"weights")
    (ckpt / "rl_agent_config.json").write_text('{"temperature": [1, 1, 1]}')
    record = {
        "schema": "l4/s1-train@1", "dataset_sha256": manifest["dataset_sha256"],
        "files": tune.checkpoint_files(ckpt), "gate": {"passed": False, "ran": False},
    }  # fmt: skip
    tune.write_atomic(ckpt / tune.RECORD_NAME, json.dumps(record))
    return ckpt, record


def test_train_stub_failed_gate_score_report(tmp_path: Path):
    out, manifest = exported(tmp_path)
    test = out / "test.jsonl"
    ckpt, record = trained_stub(tmp_path / "cache", manifest)
    rows = sc.read_rows(test)
    accuracy = sum(r["expected"]["all_passed"] is True for r in rows) / len(rows)  # the stub answers p=0.9 always
    document = {
        "schema": "l4/s1-gate@1", "passed": False, "failures": ["tuned noul accuracy 0.5 does not beat base"],
        "dataset_sha256": manifest["dataset_sha256"], "checkpoint_id": ckpt.name,
        "checkpoint_sha256": record["files"]["model.safetensors"], "test_sha256": sc.file_sha256(test),
        "tuned": {"slices": {"qid": {"all_passed": {"noul_accuracy": accuracy}}}},
    }  # fmt: skip
    tune.record_gate(ckpt, record, document, tmp_path / "gate-out.json")
    assert (ckpt / "gate.json").read_bytes() == (tmp_path / "gate-out.json").read_bytes()
    assert tune.checkpoint_drift(ckpt, json.loads((ckpt / "l4-train.json").read_text())) == []  # gate.json is no drift

    cfg = cfg_for(str(ckpt))
    env = env_for(tmp_path)
    with pytest.raises(CheckpointGateFailed):  # shadow, role probes and a plain open refuse it
        open_s1_profile(cfg, "tuned", environ=env, redactor=Redactor({}))

    def reply(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={"model": "typed-decisions", "answers": {q: {"type": "noul", "noul": 0.9} for q in body["questions"]}},
        )

    opened = []

    def opener(config, name, **kwargs):
        opened.append(kwargs.get("allow_failed_gate"))
        open_s1_profile(config, name, environ=env, redactor=Redactor({}), allow_failed_gate=kwargs["allow_failed_gate"])
        return SystemOneBackend("remote", model="typed-decisions", base_url="http://stub.test",
                                transport=httpx.MockTransport(reply), redactor=Redactor({}))  # fmt: skip

    answers = tmp_path / "answers.jsonl"
    summary = sc.run_score(cfg, "tuned", test, answers, redactor=Redactor({}), environ=env, opener=opener)
    assert opened == [True] and summary.asked == len(rows) and summary.errors == 0
    header = json.loads(answers.read_text().splitlines()[0])
    assert header["gate_passed"] is False and header["checkpoint_sha256"] == record["files"]["model.safetensors"]

    report = rp.build_report([answers], test, gate=ckpt / "gate.json")
    assert report["gate"]["passed"] is False and report["gate"]["cross_check"] == "ok"
    assert report["engines"]["tuned"]["gate_passed"] is False
    text = rp.render_markdown(report)
    assert "GATE FAILED" in "\n".join(text.splitlines()[:6])  # prominent, before any table
    assert "not deployable" in text.lower()

    # the score file says the gate failed: a gate.json that says it passed does not go with it
    passing = json.loads((ckpt / "gate.json").read_text()) | {"passed": True}
    other = tmp_path / "passing.json"
    other.write_text(json.dumps(passing))
    with pytest.raises(ValueError, match="gate_passed"):
        rp.build_report([answers], test, gate=other)


def test_a_passing_gate_is_stamped_and_reported_as_passed(tmp_path: Path):
    out, manifest = exported(tmp_path)
    test = out / "test.jsonl"
    ckpt, record = trained_stub(tmp_path / "cache", manifest)
    rows = sc.read_rows(test)
    accuracy = sum(r["expected"]["all_passed"] is True for r in rows) / len(rows)
    document = {
        "schema": "l4/s1-gate@1", "passed": True, "failures": [], "dataset_sha256": manifest["dataset_sha256"],
        "checkpoint_sha256": record["files"]["model.safetensors"], "test_sha256": sc.file_sha256(test),
        "tuned": {"slices": {"qid": {"all_passed": {"noul_accuracy": accuracy}}}},
    }  # fmt: skip
    tune.record_gate(ckpt, record, document, tmp_path / "g.json")
    assert open_s1_profile(cfg_for(str(ckpt)), "tuned", environ=env_for(tmp_path), redactor=Redactor({})) is not None
    assert sc.checkpoint_identity(str(ckpt))["gate_passed"] is True
    assert hashlib.sha256((ckpt / "gate.json").read_bytes()).hexdigest() == sha(ckpt / "gate.json")
