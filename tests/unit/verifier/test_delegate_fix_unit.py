# ruff: noqa: F401, F811  (the fixtures are imported by name)
"""A blocked fix unit is a unit that waits for an answer (delegate-answers 9.2; L4-DLG-003): the parent stays `fixing`
with exit 11 and the pass takes the fix unit's questions, which are numbered from Q-001 in the fix unit's own file and
recorded under `<fix unit>/Q-001`."""

from l4.specs.questions import QuestionsFile

from ..delegate.conftest import delegate_run, no_hooks_but_the_delegate, publish_base, reply
from ..implementer.conftest import red_step
from .test_ladder_fix import FIX_DIR, FIX_UNIT, chore_fix, no_fix_loop, noqa_green, with_verifier

FIRST_LINE = {"ref": "src/pytdd/pricing.py:1", "quote": 'CODES = {"SAVE10": 10}', "claim": "the code table is here"}


def test_a_fix_units_questions_are_taken(delegate_run, valid_spec):
    asking = chore_fix(
        status="blocked",
        questions=[{"title": "Which flag?", "context": "two ways", "kind": "technical", "options": ["a", "b"]}],
    )
    run = delegate_run(
        [red_step(), noqa_green(), asking, reply("Q-001", text="Use the second option.", checked=[FIRST_LINE])]
    )
    assert run.code == 11 and run.outcome["units"][0]["phase_after"] == "fixing"
    (asked,) = run.events("delegate.asked")
    assert (asked["question"], asked["fix_unit"]) == (f"{FIX_UNIT}/Q-001", FIX_UNIT)
    fix_file = QuestionsFile.parse(run.pushed(f"{FIX_DIR}/questions.md").encode())
    assert fix_file.get("Q-001").status.value == "answered" and "Use the second option." in run.pushed(
        f"{FIX_DIR}/questions.md"
    )
    (answered,) = [e for e in run.events("question.answered") if e.get("fix_unit") == FIX_UNIT]
    assert (answered["id"], answered["by"], answered["profile"]) == ("Q-001", "delegate", "dlg")
    (result,) = run.events("delegate.result")
    assert (result["question"], result["status"]) == (f"{FIX_UNIT}/Q-001", "answered")
