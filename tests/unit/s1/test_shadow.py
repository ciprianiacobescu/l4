import json
from pathlib import Path

import httpx

from l4.config.schema import L4Config
from l4.llm.system_one import SystemOneBackend
from l4.redact import Redactor
from l4.s1 import questions as q
from l4.s1.shadow import run_shadow, select_items

from ._make import make_item


class FakeServe:
    """Stands in for LayaServe: fails the test if a second server is alive at the same time."""

    alive = 0
    log: list[str] = []

    def __init__(self, name: str) -> None:
        self.name = name

    def __enter__(self) -> str:
        assert FakeServe.alive == 0, "a second laya-serve was started"
        FakeServe.alive += 1
        FakeServe.log.append(f"start {self.name}")
        return "http://laya.test"

    def stop(self) -> None:
        if FakeServe.alive:
            FakeServe.alive -= 1
            FakeServe.log.append(f"stop {self.name}")


def reply_for(body: dict, p: float) -> dict:
    answers = {}
    for qid, spec in body["questions"].items():
        if spec["type"] == "noul":
            answers[qid] = {"type": "noul", "noul": p}
        elif spec["type"] == "choice":
            options = list(spec["criteria"])
            probs = {o: (0.8 if o == "implemented" else 0.1) for o in options}
            answers[qid] = {"type": "choice", "choice": "implemented", "confidence": 0.7, "probabilities": probs}
        else:
            n = len(spec["criteria"])
            answers[qid] = {"type": "score", "score": 1.0, "probabilities": {str(i): 1 / n for i in range(n)}}
    return {"model": "served-model", "answers": answers, "usage": {}}


def test_engines_run_one_at_a_time_with_identical_states_and_failures_recorded(tmp_path: Path):
    FakeServe.alive, FakeServe.log = 0, []
    seen: dict[str, list[dict]] = {"laya-tuned": [], "laya-base": [], "jev": [], "mac": []}

    def handler_for(name: str, fail: str | None = None, p: float = 0.9):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen[name].append(body)
            if fail == "500":
                return httpx.Response(500)
            if fail == "bad" and len(seen[name]) == 2:
                return httpx.Response(200, json={"model": "m", "answers": {"all_passed": {"type": "choice"}}})
            return httpx.Response(200, json=reply_for(body, p))

        return handler

    def backend(name: str, engine: str, **kw) -> SystemOneBackend:
        base = {"redactor": Redactor({}), "transport": httpx.MockTransport(handler_for(name, kw.pop("fail", None)))}
        if engine == "laya-local":
            return SystemOneBackend("laya-local", model=name, serve=FakeServe(name), **base)  # type: ignore[arg-type]
        return SystemOneBackend(engine, model=name, base_url="http://s1.test", api_key="k" * 12, **base)  # type: ignore[arg-type]

    made = {
        "laya-tuned": backend("laya-tuned", "laya-local"),
        "laya-base": backend("laya-base", "laya-local", fail="bad"),
        "jev": backend("jev", "jev", fail="500"),
        "mac": backend("mac", "remote"),
    }

    def opener(cfg, name, **kwargs):
        return made[name]

    cfg = L4Config.model_validate({
        "profiles": {n: {"backend": "system-one", "engine": "remote", "base_url": "http://x"} for n in made},
        "roles": {"s1_judge": ["laya-tuned"]},
        "verifier": {"s1": {"shadow": ["laya-base", "jev", "mac", "laya-tuned"], "max_items": 3}},
    })  # fmt: skip
    items = [make_item(f"k{n}", truth={"tests_ok": True}, state=f"state {n}") for n in range(5)]
    run = run_shadow(cfg, items, redactor=Redactor({}), opener=opener)

    assert FakeServe.log == ["start laya-tuned", "stop laya-tuned", "start laya-base", "stop laya-base"]
    assert [e.profile for e in run.engines] == ["laya-tuned", "laya-base", "jev", "mac"]  # primary once, then shadow
    assert len(run.items) == 5 and len(run.asked) == 3  # max_items caps what is asked, never what is kept
    states = {n: [b["state"] for b in bodies] for n, bodies in seen.items() if bodies}
    assert states["laya-tuned"] == states["mac"]  # identical states, in the same order
    assert states["laya-base"] == states["laya-tuned"][:2] + states["laya-tuned"][2:]  # the bad reply was still sent
    assert all(len(b["questions"]) == 1 for bodies in seen.values() for b in bodies)
    by_engine = {e.profile: e for e in run.engines}
    assert (by_engine["laya-tuned"].asked, by_engine["mac"].asked) == (3, 3)
    assert by_engine["jev"].status == "unavailable" and by_engine["jev"].failed == 3
    assert by_engine["laya-base"].failed == 1 and by_engine["laya-base"].status == "ok"
    errors = [a for a in run.answers if a.error]
    assert {a.profile for a in errors} == {"jev", "laya-base"} and len(errors) == 4
    assert [a.error for a in errors if a.profile == "jev"][1].startswith("not asked:")  # no more waiting on a dead one
    ok = [a for a in run.answers if not a.error]
    assert len(ok) == 3 + 2 + 3 and all(a.model == "served-model" for a in ok)
    assert ok[0].answers["all_passed"] == {"kind": "noul", "p_true": 0.9}


def test_choice_in_both_orders_is_one_request_and_unusable_engines_do_not_block(tmp_path: Path):
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json=reply_for(body, 0.5))

    jev = SystemOneBackend("jev", model="jev-latest", base_url="http://j.test", api_key="k" * 12,
                           transport=httpx.MockTransport(handler), redactor=Redactor({}))  # fmt: skip

    def opener(cfg, name, **kwargs):
        if name == "jev":
            return jev
        from l4.agents.factory import RoleUnavailable

        raise RoleUnavailable(f"s1:{name}", "laya-serve is not on PATH")

    cfg = L4Config.model_validate({
        "profiles": {n: {"backend": "system-one", "engine": "jev", "api_key_env": "K"} for n in ("laya", "jev")},
        "roles": {"s1_judge": ["laya"]}, "verifier": {"s1": {"shadow": ["jev"]}},
    })  # fmt: skip
    item = make_item("c1", set_name=q.CRITERION, truth={"satisfied": True})
    run = run_shadow(cfg, [item], redactor=Redactor({}), opener=opener)
    (body,) = bodies
    assert set(body["questions"]) == {"satisfied", "status_fwd", "status_rev"}
    assert run.engines[0].status == "unavailable" and "laya-serve is not on PATH" in run.engines[0].reason
    assert [a.profile for a in run.answers if not a.error] == ["jev"]
    assert len(run.items) == 1


def test_items_are_returned_when_every_engine_is_down_or_s1_is_off():
    cfg = L4Config.model_validate({"verifier": {"s1": {"enabled": False}}})
    items = [make_item("a"), make_item("b")]
    run = run_shadow(cfg, items, redactor=Redactor({}), opener=lambda *a, **k: 1 / 0)
    assert run.items == items and run.answers == [] and run.engines == []
    assert [i.item_key for i in select_items(items, 1)] == [i.item_key for i in select_items(items[::-1], 1)]


def test_any_error_from_an_engine_is_recorded_and_never_blocks_the_others():
    class Exploding(SystemOneBackend):
        def __init__(self, where: str) -> None:
            super().__init__("jev", model="boom", base_url="http://s1.test", api_key="k" * 12, redactor=Redactor({}))
            self.where = where

        def start(self) -> None:
            if self.where == "start":
                raise PermissionError("secret path /home/x/model.safetensors")

        def query(self, state, questions):
            raise RuntimeError("not an httpx error")

        def stop(self) -> None:
            raise OSError("cannot stop")

    good = SystemOneBackend(
        "remote", model="good", base_url="http://s1.test", redactor=Redactor({}),
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=reply_for(json.loads(r.content), 0.9))),
    )  # fmt: skip

    def opener(cfg, name, **kwargs):
        if name == "opens-badly":
            raise PermissionError("secret path /home/x/model.safetensors")
        return {"start-fails": Exploding("start"), "query-fails": Exploding("query"), "good": good}[name]

    names = ["opens-badly", "start-fails", "query-fails", "good"]
    cfg = L4Config.model_validate({
        "profiles": {n: {"backend": "system-one", "engine": "remote", "base_url": "http://x"} for n in names},
        "roles": {"s1_judge": ["opens-badly"]},
        "verifier": {"s1": {"shadow": names[1:], "max_items": 2}},
    })  # fmt: skip
    items = [make_item(f"k{n}", truth={"tests_ok": True}, state=f"s{n}") for n in range(2)]
    run = run_shadow(cfg, items, redactor=Redactor({}), opener=opener)
    status = {e.profile: e.status for e in run.engines}
    assert status == {n: "unavailable" for n in names[:3]} | {"good": "ok"}
    assert len(run.items) == 2 and sum(1 for a in run.answers if a.profile == "good" and not a.error) == 2
    assert "secret" not in " ".join(a.error or "" for a in run.answers)  # only the exception type is recorded
    assert any("PermissionError while opening the profile" in (a.error or "") for a in run.answers)
