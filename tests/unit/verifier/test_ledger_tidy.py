"""Live job 5482 seq 66 through `l4 run`: an agent step "tidies" the dirty run ledger the way codex did (`git status
--short`, then `git show HEAD:<ledger> > <ledger>`). The guard restores the ledger and its event says what happened
(SPEC L4-IMP-006, SCN-IMP-48)."""

import subprocess

import pytest

from l4.agents.fake import FakeAdapter, Step

from ..implementer.conftest import IMPL, red_step, result
from ..orchestrator.conftest import UNIT_DIR
from .conftest import judge_reply
from .test_ladder_fix import CRITERIA, FIX_UNIT, noqa_green

PARENT_LEDGER_DIR = f"{UNIT_DIR}/.l4/ledger"


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on, as in `test_ladder_fix`."""


@pytest.fixture
def tidy_on_call(monkeypatch):
    seen: dict[str, object] = {"calls": 0, "tidied": []}
    original = FakeAdapter.run

    def run(self, req):
        out = original(self, req)
        index = seen["calls"]
        seen["calls"] = index + 1
        if index == seen.get("at"):
            git = ["git", "-C", str(req.cwd)]
            status = subprocess.run([*git, "status", "--porcelain=v1"], capture_output=True, text=True, check=True)
            seen["status"] = status.stdout
            for line in status.stdout.splitlines():
                path = line[3:]
                if line.startswith(" M") and "/.l4/ledger/" in path:
                    blob = subprocess.run([*git, "show", f"HEAD:{path}"], capture_output=True, check=True).stdout
                    with (req.cwd / path).open("wb") as handle:  # shell `>`: O_TRUNC, same inode
                        handle.write(blob)
                    seen["tidied"].append(path)
        return out

    monkeypatch.setattr(FakeAdapter, "run", run)
    return seen


def test_a_fix_step_resetting_the_parent_run_ledger_to_head_is_restored_and_explained(run_l4, valid_spec, tidy_on_call):
    tidy_on_call["at"] = 2  # the third agent call: the fix unit's single (chore) step
    run = run_l4(
        [
            red_step(),
            noqa_green(),
            Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("single")),
            Step(structured=judge_reply(CRITERIA)),
        ]
    )
    violations = run.events("guard.violation")
    assert run.code == 0
    [tidied] = tidy_on_call["tidied"]
    assert tidied.startswith(PARENT_LEDGER_DIR + "/")  # the dirty file is the PARENT's run ledger
    assert [(v["path"], v["rule"], v["action"], v.get("fix_unit")) for v in violations] == [
        (tidied, "run ledger", "restored", FIX_UNIT)
    ]  # exactly one, from `Workbench.restore_ledger`; none from `revert_protected` (`<parent>/**`)
    seqs = [e["seq"] for e in run.ledger()]
    assert seqs == list(range(1, len(seqs) + 1)), "no gap: the writer's copy put the truncated lines back"
    assert IMPL in run.pushed("src/pytdd/pricing.py")  # the agent's real work was not reverted
    [event] = violations
    assert (event["kind"], event["foreign_lines"], event["phase"], event["attempt"]) == ("truncated", 0, "single", 1)
    assert event["removed_seqs"] and event["removed_count"] == len(event["removed_seqs"]) and event["task"]
    assert event["removed_seqs"] == sorted(event["removed_seqs"])
