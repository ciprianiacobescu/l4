"""M1.13 lines 15, 17 and 20 (W-C2, SPEC L4-IMP-013, SCN-RES-02/03): an escalated unit resumes with a fix-round
extension, runs verification again, and is bounded: one more round per extension, never a loop.

Damage line: a resume of an escalated unit must not be a way around `max_fix_rounds`."""

import pytest

from l4.cli import main

from ..conftest import UNIT
from ..orchestrator.conftest import UNIT_DIR
from .test_ladder_fix import chore_fix, judge, noqa_green, red_step, with_verifier  # noqa: F401 (fixture)


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """Overrides the verifier suite's switch: these tests are about the fix loop."""


def still_bad(n: int):
    step = chore_fix()
    step.writes = {"src/pytdd/pricing.py": step.writes["src/pytdd/pricing.py"] + f"\nUNUSED = {n}  # noqa: E501\n"}
    return step


def resume(tdd_repo, *flags: str) -> int:
    argv = ["resume", "--unit", UNIT, "--reason", "one more try", *flags, "--repo", str(tdd_repo.repo)]
    return main(argv, environ=tdd_repo.environ)


@pytest.fixture
def escalated(run_l4, valid_spec, with_verifier):  # noqa: F811
    with_verifier(max_fix_rounds=1)
    first = run_l4([red_step(), noqa_green(), still_bad(1)])
    assert first.code == 13 and first.outcome["units"][0]["phase_after"] == "escalated"
    return first


def phases(run) -> list[str]:
    return [e["to"] for e in run.ledger() if e["type"] == "phase.changed"]


def test_resume_of_an_escalated_unit_with_all_rounds_used_is_refused_without_an_extension(escalated, tdd_repo, capsys):
    assert resume(tdd_repo) == 2
    err = capsys.readouterr().err
    assert "max_fix_rounds" in err and "--extend-fix-rounds" in err
    assert not any(e["type"] in ("unit.resumed", "budget.extended") for e in escalated.ledger())


def test_an_extension_of_one_round_takes_the_unit_back_to_verifying_and_allows_one_more_fix_unit(
    escalated, run_l4, tdd_repo
):
    assert resume(tdd_repo, "--extend-fix-rounds", "1") == 0
    second = run_l4([chore_fix(), judge()])
    log = second.ledger()
    [extended] = [e for e in log if e["type"] == "budget.extended"]
    assert extended["fix_rounds"] == 1
    assert [e["type"] for e in log if e["type"] in ("unit.resumed", "budget.extended")] == [
        "budget.extended", "unit.resumed"
    ]  # fmt: skip
    resumed = [e for e in log if e["type"] == "phase.changed" and e["trigger"] == "resumed"]
    assert [(e["from"], e["to"]) for e in resumed] == [("escalated", "verifying")]
    assert [e["fix_unit"] for e in second.events("fix.spawned")] == [
        "add-discount-codes-fix-1", "add-discount-codes-fix-2"
    ]  # fmt: skip
    assert second.code == 0, second.adapter.requests[-1].prompt[-600:]
    assert second.triggers()[-1] == "verify_pass"


def test_a_still_failing_second_round_escalates_again_and_one_more_extension_gives_exactly_one_more(
    escalated, run_l4, tdd_repo
):
    assert resume(tdd_repo, "--extend-fix-rounds", "1") == 0
    again = run_l4([still_bad(2)])
    assert again.code == 13 and again.outcome["units"][0]["phase_after"] == "escalated"
    # the same finding as the round before, every gate passing: `same_failure` (D7) ends it before the limit would
    assert "failed the same way as round 3" in again.pushed(f"{UNIT_DIR}/verification.md")
    assert resume(tdd_repo) == 2  # the rounds are used up again, and the extension is not carried over
    assert resume(tdd_repo, "--extend-fix-rounds", "1") == 0
    third = run_l4([chore_fix(), judge()])
    assert third.code == 0 and len(third.events("fix.spawned")) == 3


def test_extending_a_unit_that_is_not_escalated_or_halted_is_refused(run_l4, valid_spec, tdd_repo, capsys):
    ran = run_l4([red_step(), noqa_green(), chore_fix(), judge()])
    assert ran.code == 0
    assert resume(tdd_repo, "--extend-fix-rounds", "1") == 2
    assert "not halted or escalated" in capsys.readouterr().err
