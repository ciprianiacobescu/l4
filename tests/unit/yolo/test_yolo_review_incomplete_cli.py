# ruff: noqa: F811
"""`l4 yolo review --local` and `--worktree` with a review that does not finish (L4-YOLO-099, SCN-YOLO-281) and with a
chain of judges (L4-YOLO-096, SCN-YOLO-269, SCN-YOLO-277). The judges are scripted `FakeAdapter`s, one per adapter
name, behind the real `review_plan_costed`."""

import yaml

from l4.agents.base import ProbeResult
from l4.agents.fake import FakeAdapter, Step
from l4.yolo.readiness import review_plan_costed

from .test_yolo_review_worktree import cache_lines, push_edit, ready_world
from .yolo_cmd_world import A, B, forge, world  # noqa: F401

READY = {"verdict": "READY", "findings": [], "assumptions": [], "missing": []}
REFUSED = {"hello": ProbeResult("hello", False, reason="hello refused")}


def ok(**kw):
    return Step(structured=READY, **kw)


def configure(world, judges, *, sandbox=None, review=None):
    config = yaml.safe_load(world.app.config_path.read_text(encoding="utf-8"))
    config["profiles"]["j1"] = {"adapter": "claude-code", "vendor": "anthropic"}
    config["profiles"]["j2"] = {"adapter": "codex", "vendor": "openai"}
    config["roles"]["judges"] = list(judges)
    if sandbox:
        config["sandbox"] = sandbox
    if review:
        config["yolo"] = {"review": review}
    world.app.config_path.write_text(yaml.safe_dump(config), encoding="utf-8")


def judges(monkeypatch, j1, j2, *, module="review_worktree"):
    real = review_plan_costed
    monkeypatch.setattr(
        f"l4.yolo.{module}.review_plan_costed",
        lambda *a, **kw: real(*a, adapters={"claude-code": j1, "codex": j2}, **kw),
    )


def failing_pair(monkeypatch, *, module="review_worktree"):
    """SCN-YOLO-278: j1's hello fails, j2 answers A and B and ends `error` on the batch."""
    j2 = FakeAdapter([ok(cost_usd=0.1), ok(cost_usd=0.1), Step(status="error", detail="boom", cost_usd=0.1)])
    judges(monkeypatch, FakeAdapter([], probes=REFUSED), j2, module=module)
    return j2


def test_scn_yolo_281_local_records_the_incomplete_review_and_exits_12(world, monkeypatch, capsys):
    ready_world(world)
    configure(world, ["j1", "j2"])
    failing_pair(monkeypatch, module="commands")
    assert world.l4("review", "p1", "--local") == 12
    captured = capsys.readouterr()
    assert world.kinds() == ["plan.admitted", "plan.review_incomplete", "plan.charged"]
    event = world.events()[1].data
    assert (event["source"], event["by"], event["reason"]) == ("local", "alex@example.com", "no_judge")
    assert set(event["answered"]) == {A, B} and event["left"] == ["batch:b1"] and event["cost_usd"] == 0.3
    assert world.events()[2].data["cost_usd"] == 0.3
    assert "j1: selection: unusable: " in captured.out and "j2: batch:b1: error: boom" in captured.out
    assert "the review is incomplete (no_judge): 2 answered and kept, 1 left" in captured.out
    assert "fix: fix the judges named" in captured.out
    assert "the review is incomplete (no_judge)" in captured.err


def test_scn_yolo_281_a_dry_run_keeps_the_answers_locally_and_leaves_the_ref(world, monkeypatch, capsys):
    ready_world(world)
    configure(world, ["j1", "j2"])
    failing_pair(monkeypatch)
    before = world.clone.run("rev-parse", "HEAD").stdout
    assert world.l4("review", "p1", "--worktree") == 12
    out = capsys.readouterr().out
    assert world.store().read().head is None and world.clone.run("rev-parse", "HEAD").stdout == before
    assert "j2: batch:b1: error: boom" in out and "2 answered and kept in the local cache, 1 left" in out
    assert {line["subject"]: line["kind"] for line in cache_lines(world)} == {A: "unit", B: "unit"}
    j2 = FakeAdapter([ok()])
    judges(monkeypatch, FakeAdapter([], probes=REFUSED), j2)
    assert world.l4("review", "p1", "--worktree") in (0, 2)  # finished: only the batch was asked
    assert len(j2.requests) == 1 and "(reused)" in capsys.readouterr().out
    assert world.store().read().head is None


def test_scn_yolo_281_record_records_the_event_with_the_source_worktree(world, monkeypatch, capsys):
    ready_world(world)
    push_edit(world)
    configure(world, ["j1", "j2"])
    failing_pair(monkeypatch)
    assert world.l4("review", "p1", "--worktree", "--record") == 12
    assert world.kinds() == ["plan.admitted", "plan.review_incomplete", "plan.charged"]
    assert world.events()[1].data["source"] == "worktree" and world.events()[1].data["by"] == "alex@example.com"
    capsys.readouterr()
    j2 = FakeAdapter([ok(cost_usd=0.1)])
    judges(monkeypatch, FakeAdapter([], probes=REFUSED), j2)
    assert world.l4("review", "p1", "--worktree", "--record") == 0
    assert len(j2.requests) == 1  # the ledger holds the other two answers
    reviewed = world.events()[-2].data if world.events()[-1].type == "plan.charged" else world.events()[-1].data
    assert reviewed["judge"] == "j2" and reviewed["judges"] == ["j2"]
    assert [f["kind"] for f in reviewed["failures"]] == ["unusable"]
    assert reviewed["batches"]["b1"]["judge"] == "j2" and reviewed["batches"]["b1"]["sandbox"] == "none"


def test_scn_yolo_269_a_judge_that_cannot_be_sandboxed_here_is_skipped(world, monkeypatch, capsys):
    ready_world(world)
    monkeypatch.setattr("l4.yolo.judge_sandbox.resolve_tool", lambda *a, **k: None)  # no bwrap on PATH
    configure(world, ["j2", "j1"], sandbox={"mode": "auto"})  # codex keeps a read-only shell; claude-code is tool-less
    j1 = FakeAdapter([ok(), ok(), ok()])
    judges(monkeypatch, j1, FakeAdapter([]))
    assert world.l4("review", "p1", "--worktree") == 0
    out = capsys.readouterr().out
    assert "j2: selection: sandbox: " in out and "the codex judge keeps a read-only shell" in out
    assert len(j1.requests) == 3


def test_scn_yolo_269_a_chain_of_only_such_judges_exits_3_with_the_refusal(world, monkeypatch, capsys):
    ready_world(world)
    monkeypatch.setattr("l4.yolo.judge_sandbox.resolve_tool", lambda *a, **k: None)
    configure(world, ["j2"], sandbox={"mode": "auto"})
    judges(monkeypatch, FakeAdapter([]), FakeAdapter([]))
    assert world.l4("review", "p1", "--worktree") == 3
    assert "the codex judge keeps a read-only shell" in capsys.readouterr().err


def test_scn_yolo_277_fresh_asks_every_part_of_a_batch_again(world, monkeypatch, capsys):
    ready_world(world)
    configure(world, ["j1"], review={"max_batch_chars": 100})
    first = FakeAdapter([ok() for _ in range(5)])  # A, B, the parts of A and B, the summary
    judges(monkeypatch, first, FakeAdapter([]))
    assert world.l4("review", "p1", "--worktree") == 0
    assert len(first.requests) == 5
    assert {line["kind"] for line in cache_lines(world)} == {"unit", "batch", "batch-part"}
    again = FakeAdapter([ok() for _ in range(3)])
    judges(monkeypatch, again, FakeAdapter([]))
    assert world.l4("review", "p1", "--worktree", "--fresh", "batch:b1") == 0
    assert len(again.requests) == 3 and all("read in part" in r.prompt for r in again.requests)


def test_record_writes_judge_and_sandbox_per_entry_from_the_judge_that_answered_it(world, monkeypatch, capsys):
    ready_world(world)
    push_edit(world)
    configure(world, ["j1", "j2"])
    j1 = FakeAdapter([ok(), Step(status="error", detail="boom")])
    j2 = FakeAdapter([ok(), ok()])
    judges(monkeypatch, j1, j2)
    assert world.l4("review", "p1", "--worktree", "--record") == 0
    data = next(e for e in world.events() if e.type == "plan.reviewed").data
    assert (data["units"][A]["judge"], data["units"][B]["judge"], data["batches"]["b1"]["judge"]) == ("j1", "j2", "j2")
    assert data["judges"] == ["j1", "j2"] and data["judge"] == "j1"
    assert all(e["sandbox"] == "none" for e in (data["units"][A], data["units"][B], data["batches"]["b1"]))
    assert [(f["profile"], f["subject"], f["kind"]) for f in data["failures"]] == [("j1", B, "error")]
