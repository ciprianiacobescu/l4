"""The way out of a unit escalated with `skipped_tests_rejected` (L4-VER-093, SCN-VER-384)."""

from l4.planner import UnitFacts
from l4.state.next_step import SKIPPED_TESTS_REJECTED, next_step, skipped_way_out, way_out

QPATH = "openspec/changes/x/questions.md"
BRANCH = "l4/openspec/x"
UNIT = "openspec:x"


def step(**over) -> str:
    base = {"unit": UNIT, "framework": "openspec", "phase": "escalated", "tasks_done": 1, "tasks_total": 2}
    return next_step(UnitFacts(**{**base, **over}), branch=BRANCH, questions_path=QPATH)


def test_the_code_and_its_way_out():
    assert SKIPPED_TESTS_REJECTED == "skipped_tests_rejected"
    assert way_out(UNIT, SKIPPED_TESTS_REJECTED) == skipped_way_out(UNIT)


def test_the_way_out_names_the_persons_commit_the_retry_and_the_replaced_accept():
    got = skipped_way_out(UNIT)
    assert "a fix unit cannot change test files" in got
    assert "your own commit" in got and "remove the skip" in got
    assert f"l4 retry --unit {UNIT} --reason TEXT" in got
    assert f'l4 questions answer Q-NNN --unit {UNIT} --text "accept ..." --replace' in got
    assert got.index("your own commit") < got.index("l4 retry --unit")


def test_status_says_it():
    got = step(halt_reason=SKIPPED_TESTS_REJECTED)
    assert got == skipped_way_out(UNIT)
    assert "l4 feedback add" not in got and "a retry alone repeats" not in got


def test_the_sticky_note_of_the_merge_request_says_it():
    from l4.ci.resume_label import halted_section

    text = halted_section(
        "escalated", "a person rejected a skipped-test hold", UNIT, "l4:retry", reason_code=SKIPPED_TESTS_REJECTED
    )
    assert text.endswith(f"To go on: {skipped_way_out(UNIT)}.") and "### Escalated:" in text
