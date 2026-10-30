"""The texts of the verdict questions (L4-VER-060; SCN-VER-211 to SCN-VER-214)."""

from l4.redact import Redactor
from l4.specs.base import Criterion, Framework
from l4.verifier.types import CriterionOutcome, Finding, Severity
from l4.verifier.verdicts import (
    CHECK_WITH_CRITERION,
    CHECK_WITHOUT_CRITERION,
    REJECT_OPTION,
    SPEC_GAP_NOTE,
    SUGGESTION_IS_THE_CODE,
    raise_verdict_questions,
)

CID = "C-00000001"
CRITERION = Criterion(
    CID, "greeting > Greet > Unknown", Framework.OPENSPEC, "greeting", "Greet", "Unknown",
    "WHEN the id is unknown THEN the command exits 1", "specs/greeting/spec.md", 1,
)  # fmt: skip
FIX = "WHEN the id is unknown THEN the command exits 2"


class Sink:
    def append(self, event_type: str, /, **data) -> None:
        pass


def flat(text: str) -> str:
    return " ".join(text.split())


def ask(tmp_path, *, findings=(), outcomes=()) -> str:
    raise_verdict_questions(
        tmp_path, "u", outcomes=list(outcomes), criteria=[CRITERION], trace=[], findings=list(findings), existing=None,
        consumed=(), raised=(), ledger=Sink(), round_no=1, redactor=Redactor({}),
    )  # fmt: skip
    return flat((tmp_path / "questions.md").read_text())


def finding(criterion: str | None = CID, **over) -> Finding:
    kw = {"spec_gap": False, "suggested_fix": "", **over}
    return Finding(Severity.MAJOR, "Unknown id exits 2", "the code exits 2", "judge", criterion, **kw)


def test_a_finding_question_says_how_to_set_the_check(tmp_path):  # SCN-VER-211
    text = ask(tmp_path, findings=[finding()])
    assert "your reason comes first in it" in text
    assert flat(CHECK_WITH_CRITERION.format(target=f"criterion {CID}")) in text
    assert f"Without one, the fix is checked against criterion {CID} as it is written." in text
    assert REJECT_OPTION in text and "a reject does not use it" not in text


def test_a_spec_gap_question_says_the_suggestion_is_the_code_as_it_is(tmp_path):  # SCN-VER-212
    text = ask(tmp_path, findings=[finding(spec_gap=True, suggested_fix=FIX)])
    assert SPEC_GAP_NOTE.strip() in text
    assert text.index(f"Suggested fix: {FIX}") < text.index(SUGGESTION_IS_THE_CODE)


def test_a_spec_gap_without_a_suggested_fix_or_with_advice_gets_no_such_sentence(tmp_path):
    assert SUGGESTION_IS_THE_CODE not in ask(tmp_path, findings=[finding(spec_gap=True)])
    other = tmp_path / "advice"
    other.mkdir()
    advice = "Clarify in the spec whether an unknown id exits 1 or 2"
    text = ask(other, findings=[finding(spec_gap=True, suggested_fix=advice)])
    assert f"Suggested fix: {advice}" in text and SUGGESTION_IS_THE_CODE not in text


def test_a_finding_question_with_no_criterion_says_the_sentence_is_needed(tmp_path):  # SCN-VER-213
    text = ask(tmp_path, findings=[finding(None)])
    assert CHECK_WITHOUT_CRITERION in text and "Without one, the fix is checked against" not in text


def test_a_criterion_question_says_the_same_of_its_scenario(tmp_path):  # SCN-VER-214
    outcome = CriterionOutcome(CID, "alias", "needs_human", None, "no test traces it")
    text = ask(tmp_path, outcomes=[outcome])
    assert "Without one, the fix is checked against the scenario above as it is written." in text
    assert REJECT_OPTION in text and "If the code is right and the scenarios are incomplete" not in text
