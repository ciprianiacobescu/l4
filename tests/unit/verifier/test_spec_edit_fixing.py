"""L4-OPS-014, design D13 (SCN-OPS-25, SCN-OPS-26): a spec push made while the unit is `fixing` is not lost. No edge is
taken in `fixing`, and the fix unit's tasks then commit on top of the person's commit, so the run records
`spec.edit_seen{head, base, commits}` first; when the fix unit ends and the parent is `verifying` again, the run takes
`spec_edited` before the verifier runs (and a Kiro unit reopens the tasks that cite a changed criterion, diffed
between the recorded base and head). A push that changes no spec file records nothing."""

import pytest

from l4 import services
from l4.agents.fake import Step

from ..implementer.conftest import result
from ..orchestrator.test_kiro_unit import (
    BRANCH,
    DISCOUNT_DONE,
    REQUIREMENTS,
    SHOUT_ID,
    SPEC,
    TASKS,
    _events,
    _write_unit,
)
from ..orchestrator.test_spec_edit_reopen import ids_of, push_requirements
from .conftest import judge_reply
from .test_fixloop_kiro import judge_step, suppressed_script

CHORE = Step(writes={"src/pytdd/pricing.py": DISCOUNT_DONE}, structured=result("single"))  # the suppression goes
TRIMMED = DISCOUNT_DONE.replace("return name.upper()", "return name.strip().upper()")
REWORDED = REQUIREMENTS.replace(
    "THE Shop SHALL return it in capitals.", "THE Shop SHALL return it in capitals, without the spaces around it."
)


@pytest.fixture
def fixing(run_l4, tdd_repo, raw):
    """The first run: the round fails and the unit stops `fixing`, the fix unit written, no fix task run yet."""
    _write_unit(tdd_repo, raw, TASKS)
    first = run_l4([*suppressed_script(), judge_step()], "--unit", "kiro:discounts", unit=False)
    assert first.code == 10 and first.outcome["units"][0]["phase_after"] == "fixing"
    return first


@pytest.fixture
def fix_loop_on(monkeypatch):
    monkeypatch.setitem(services.HOOKS, "fix", "l4.verifier.fixloop:fix_hook")


def ledger(raw, tdd_repo) -> list[dict]:
    return sorted(_events(raw, tdd_repo), key=lambda e: (e["ts"], e["run_id"], e["seq"]))


def test_a_spec_push_while_fixing_is_recorded_and_taken_when_the_fix_unit_ends(
    fixing, fix_loop_on, run_l4, tdd_repo, raw
):
    """SCN-OPS-25: for Kiro the task that cites the reworded criterion is open again, and the edge comes before the
    verifier."""
    push_requirements(tdd_repo, raw, REWORDED, "reword")
    pushed = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    before = raw(tdd_repo.origin, "rev-parse", f"{pushed}^").strip()
    ids = ids_of(REWORDED)
    new_shout = ids["Req 2.1"]
    assert new_shout != SHOUT_ID
    trim_test = (
        f'import pytest\n\nfrom pytdd.pricing import shout\n\n\n@pytest.mark.l4("{new_shout}")\ndef test_trim():\n'
        '    assert shout(" ada ") == "ADA"\n'
    )
    red = Step(
        writes={"tests/test_trim.py": trim_test, "src/pytdd/pricing.py": DISCOUNT_DONE},
        structured=result(
            "red", task_ids=["2.1"], tests_added=["tests/test_trim.py::test_trim"], criteria_ids=[new_shout]
        ),
    )
    green = Step(writes={"src/pytdd/pricing.py": TRIMMED}, structured=result("green", task_ids=["2.1"]))
    judge = Step(structured=judge_reply([ids["Req 1.1"], new_shout]))
    second = run_l4([CHORE, red, green, judge], "--unit", "kiro:discounts", unit=False)

    assert second.code == 0, second.adapter.requests[-1].prompt[-600:]
    log = ledger(raw, tdd_repo)
    [seen] = [e for e in log if e["type"] == "spec.edit_seen"]
    assert (seen["head"], seen["commits"]) == (pushed, [pushed])
    assert seen["base"] == before  # the harness's last commit: what the spec looked like when it left the unit
    [retried] = [e for e in log if e["type"] == "unit.retried"]
    assert (retried["reason"], retried["signal"], retried["by"]) == ("spec edited", f"spec_edit:{pushed}", "push")
    kinds = [e["type"] for e in log]
    triggers = [e["trigger"] for e in log if e["type"] == "phase.changed"]
    at = triggers.index("spec_edited")
    assert triggers[at - 1] == "fix_unit_done" and triggers[at + 1 : at + 3] == [
        "all_leaves_done",
        "verification_started",
    ]
    assert kinds.index("spec.edit_seen") < kinds.index("fix.done") < kinds.index("unit.retried")
    assert (
        kinds.index("unit.retried")
        < kinds.index("tasks.reopened")
        < kinds.index("verify.verdict", kinds.index("unit.retried"))
    )
    [reopened] = [e for e in log if e["type"] == "tasks.reopened"]
    assert (reopened["tasks"], reopened["requirements"]) == (["2", "2.1"], ["2.1"])
    subjects = raw(tdd_repo.origin, "log", "--format=%s", f"main..{BRANCH}")
    assert "chore(discounts): reopen tasks 2, 2.1 for changed requirements 2.1 [skip ci]" in subjects
    assert [v["verdict"] for v in log if v["type"] == "verify.verdict"] == ["FAIL", "PASS"]
    assert "- [x] 2.1" in raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")
    # each head once: another run records and takes nothing more
    third = run_l4([], "--unit", "kiro:discounts", unit=False)
    assert third.code == 0
    again = ledger(raw, tdd_repo)
    assert [e["type"] for e in again].count("spec.edit_seen") == 1 and [e["type"] for e in again].count(
        "unit.retried"
    ) == 1


def test_a_code_only_push_while_fixing_records_nothing(fixing, fix_loop_on, run_l4, tdd_repo, raw):
    """SCN-OPS-26."""
    clone = tdd_repo.repo.parent / "human-code"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    (clone / "src" / "pytdd" / "extra.py").write_text("EXTRA = 1\n")
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "a helper")
    raw(clone, "push", "-q", "origin", BRANCH)
    second = run_l4([CHORE, judge_step()], "--unit", "kiro:discounts", unit=False)

    assert second.code == 0, second.adapter.requests[-1].prompt[-600:]
    kinds = [e["type"] for e in ledger(raw, tdd_repo)]
    assert "spec.edit_seen" not in kinds and "unit.retried" not in kinds
    assert "spec_edited" not in [e["trigger"] for e in ledger(raw, tdd_repo) if e["type"] == "phase.changed"]
