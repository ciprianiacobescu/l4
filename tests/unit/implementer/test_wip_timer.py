"""`Workbench.wip_snapshots`: a snapshot while the agent runs, `step.started`/`step.finished` around it (M14-G5)."""

import time

import pytest

from l4.agents.base import RunResult
from l4.agents.fake import FakeAdapter, Step
from l4.implementer.tdd import agent_step
from l4.specs.base import Task
from l4.vcs.wip import restore_wip, wip_ref

from .conftest import UNIT, Bench, red_step

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)


class WriteThenSleep:
    """Writes a file, keeps working for `seconds`, then answers: the shape of a real agent mid-task."""

    name = "fake"

    def __init__(self, seconds: float, fail: bool = False) -> None:
        self.seconds, self.fail = seconds, fail

    def capabilities(self):  # the prompt asks for the schema mode (M1.2 prompt-contract adapters)
        return FakeAdapter([]).capabilities()

    def run(self, req) -> RunResult:
        (req.cwd / "src" / "pytdd" / "partial.py").write_text("PARTIAL = True\n")
        time.sleep(self.seconds)
        if self.fail:
            raise RuntimeError("the agent crashed")
        return FakeAdapter([Step(structured={"status": "done", "phase": "red", "task_ids": ["1.1"]})]).run(req)


def events(bench: Bench, *types: str) -> list[dict]:
    lines = (bench.wb.ref.path / ".l4" / "ledger").glob("*.jsonl")
    import json

    out = [json.loads(line) for f in lines for line in f.read_text().splitlines()]
    return [e for e in out if e["type"] in types]


def branch_commits(bench: Bench) -> list[str]:
    return bench.wb.git.run("log", "--format=%H", "origin/main..HEAD").stdout.split()


def test_slow_agent_step_leaves_a_local_snapshot_and_no_branch_commit(make_bench):
    bench = make_bench([], implementer={"wip_snapshot_interval": "1s"})
    wb = bench.wb
    wb.selected.impl = WriteThenSleep(1.6)  # type: ignore[misc]
    head, index = wb.head(), wb.git.run("write-tree").stdout
    agent_step(wb, "red", TASK, 1, None)
    ref = wip_ref(UNIT)
    snapshot = wb.git.rev_parse(ref)
    assert snapshot is not None and wb.git.rev_parse(f"{snapshot}^") == head  # on top of the unit branch's head
    assert wb.git.run("show", f"{snapshot}:src/pytdd/partial.py").stdout == "PARTIAL = True\n"
    assert branch_commits(bench) == [] and wb.head() == head  # no commit on the unit branch
    assert wb.git.run("write-tree").stdout == index  # the real index is untouched
    [taken] = events(bench, "wip.snapshot")
    assert snapshot in taken["shas"] and len(taken["shas"]) >= 1
    assert (taken["task"], taken["phase"], taken["attempt"]) == ("1.1", "red", 1)


def test_the_snapshot_is_restorable_on_the_same_head(make_bench):
    bench = make_bench([], implementer={"wip_snapshot_interval": "1s"})
    wb = bench.wb
    wb.selected.impl = WriteThenSleep(0.1)  # type: ignore[misc]
    agent_step(wb, "red", TASK, 1, None)  # the final snapshot, taken when the agent returns
    snapshot = wb.git.rev_parse(wip_ref(UNIT))
    wb.discard_changes()  # a crash does not discard, so it does not drop the ref either: put it back
    wb.git.run("update-ref", wip_ref(UNIT), snapshot)
    assert not (wb.worktree / "src" / "pytdd" / "partial.py").exists()
    restore_wip(wb.git, snapshot)
    assert (wb.worktree / "src" / "pytdd" / "partial.py").read_text() == "PARTIAL = True\n"


def test_step_finished_follows_every_step_started(make_bench):
    bench = make_bench([red_step()])
    agent_step(bench.wb, "red", TASK, 1, None)
    kinds = [e["type"] for e in events(bench, "step.started", "step.finished")]
    assert kinds == ["step.started", "step.finished"]
    started, finished = events(bench, "step.started")[0], events(bench, "step.finished")[0]
    assert (started["task"], started["phase"], started["attempt"]) == ("1.1", "red", 1)
    assert (finished["task"], finished["phase"], finished["attempt"], finished["status"]) == ("1.1", "red", 1, "ok")
    assert events(bench, "step.started")[0]["seq"] < events(bench, "step.finished")[0]["seq"]


def test_a_crashing_agent_still_gets_its_step_finished_and_its_snapshot(make_bench):
    bench = make_bench([], implementer={"wip_snapshot_interval": "1s"})
    bench.wb.selected.impl = WriteThenSleep(0.1, fail=True)  # type: ignore[misc]
    with pytest.raises(RuntimeError, match="crashed"):
        agent_step(bench.wb, "red", TASK, 1, None)
    [finished] = events(bench, "step.finished")
    assert finished["status"] == "error"
    assert bench.wb.git.rev_parse(wip_ref(UNIT)) is not None  # the partial work is kept


def test_the_snapshot_carries_the_run_ledger_and_names_its_step(make_bench):
    """The ledger file of a run is uncommitted until a step commits, so it travels in the snapshot: restoring it
    brings back `step.started` for the step that was interrupted."""
    bench = make_bench([Step(structured={"status": "done", "phase": "red", "task_ids": ["1.1"]})])
    agent_step(bench.wb, "red", TASK, 1, None)
    sha = bench.wb.git.rev_parse(wip_ref(UNIT))
    assert sha is not None
    ledger = bench.wb.git.run("show", f"{sha}:{bench.wb.ledger_rel}").stdout
    assert '"type":"step.started"' in ledger.replace(" ", "")
    assert "L4-Step: 1.1/red/1" in bench.wb.git.run("log", "-1", "--format=%B", sha).stdout


@pytest.mark.parametrize(
    ("status", "kind"), [("rate_limited", "rate_limit"), ("quota", "usage_limit"), ("auth", "auth")]
)
def test_a_limited_step_finishes_with_its_own_status_not_ok(make_bench, status, kind):
    from l4.agents.base import LimitSignal
    from l4.implementer.tdd import RoleLimit

    limit = LimitSignal("kiro-cli", None, kind, None, "kiro.run_error", "throttled")
    bench = make_bench([Step(status=status, limit=limit)])
    with pytest.raises(RoleLimit):
        agent_step(bench.wb, "red", TASK, 1, None)
    [finished] = events(bench, "step.finished")
    assert finished["status"] == status


def test_a_step_that_ended_in_an_error_status_is_not_recorded_as_ok(make_bench):
    bench = make_bench([Step(status="error")])
    agent_step(bench.wb, "red", TASK, 1, None)
    [finished] = events(bench, "step.finished")
    assert finished["status"] == "error"
