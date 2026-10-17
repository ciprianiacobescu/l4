"""A hold is a human decision like a verdict (m1.x fix F1, F2; live M1.6 jobs 5541 and 5543).

F1: a rejected hold is not asked again. The round is a FAIL with a deterministic finding that carries the human's
text, and the M1.3 fix-unit path acts on it. F2: a judge finding about a hold's file or function is asked once, as
part of the hold's question, and the one answer settles both."""

import pytest

from l4.redact import Redactor
from l4.specs.questions import QuestionsFile, QuestionStatus
from l4.state.ledger import LedgerEvent
from l4.verifier.fixunit import plan_fix_unit
from l4.verifier.types import Finding, HumanVerdict, Severity, Verdict, VerifyResult
from l4.verifier.verdicts import (
    JUDGE_VIEW_REJECTED_TITLE,
    LEGACY_LENGTH_HOLD,
    hold_covers,
    hold_id,
    hold_kind,
    hold_subjects,
    raise_verdict_questions,
    rejection_note,
    settle_holds,
    subsumed_findings,
    unresolved_holds,
)

from ._integrity_helpers import STAMP, UNIT

SCOPE = "scope: `src/inventory/stock.py` changes module `inventory`, which the spec does not name"
COVERAGE = (
    "diff coverage: changed code not run by any test: `src/pricing/receipt.py::<module>`, "
    "`src/pricing/receipt.py::format_line`, `src/pricing/receipt.py::format_receipt`"
)
NOT_MEASURED = "diff coverage: not measured: the coverage plugin wrote no status"


def verdict(hold: str, decision: str, reason: str = "", question: str = "Q-004") -> HumanVerdict:
    return HumanVerdict(question, hold_id(hold), decision, "human", reason, "x")  # type: ignore[arg-type]


def judge(title: str, detail: str, fix: str = "") -> Finding:
    return Finding(Severity.MAJOR, title, detail, "judge", suggested_fix=fix)


STOCK = judge(
    "Unrelated change to LOW_STOCK_THRESHOLD (5 -> 3)",
    "The change lowers the threshold in src/inventory/stock.py. No part of the proposal mentions this.",
    "Revert the change to src/inventory/stock.py",
)
RECEIPT = judge(
    "Out-of-scope, untested new module src/pricing/receipt.py", "A 77-line receipt formatter was added, with no tests."
)


def test_a_hold_is_classified_and_names_its_subjects():
    assert hold_kind(SCOPE) == "scope" and hold_subjects(SCOPE) == ("src/inventory/stock.py",)
    assert hold_kind(COVERAGE) == "coverage"
    assert hold_subjects(COVERAGE) == (
        "src/pricing/receipt.py::<module>",
        "src/pricing/receipt.py::format_line",
        "src/pricing/receipt.py::format_receipt",
    )
    for other in (NOT_MEASURED, "scope: the spec declares no path or module; the changed modules are `a`, `b`", "x"):
        assert hold_kind(other) == "other" and hold_subjects(other) == ()


def test_an_accepted_or_rejected_hold_is_not_asked_again_and_an_unanswered_one_is():
    answered = {hold_id(SCOPE): verdict(SCOPE, "reject", "no"), hold_id(COVERAGE): verdict(COVERAGE, "accept")}
    assert unresolved_holds([SCOPE, COVERAGE, NOT_MEASURED], answered) == [NOT_MEASURED]


def test_a_rejected_scope_hold_becomes_a_deterministic_blocker_that_carries_the_human_s_text():
    v = verdict(SCOPE, "reject", "inventory is not part of bulk discounts")
    [finding] = settle_holds([], [SCOPE], {v.target: v})
    assert finding.id == hold_id(SCOPE) and finding.source == "deterministic" and finding.blocking
    assert finding.criterion is None
    assert "Remove or relocate" in finding.detail and "src/inventory/stock.py" in finding.detail
    assert finding.detail.endswith(rejection_note(v)) and "inventory is not part of bulk discounts" in finding.detail
    assert settle_holds([], [SCOPE], {}) == [] and settle_holds([], [SCOPE], {v.target: verdict(SCOPE, "accept")}) == []


def test_a_rejected_coverage_hold_asks_for_tests_of_the_named_functions():
    v = verdict(COVERAGE, "reject", "the receipt helper needs tests now", "Q-005")
    [finding] = settle_holds([], [COVERAGE], {v.target: v})
    assert finding.source == "deterministic" and finding.blocking
    assert "Add tests" in finding.detail and "src/pricing/receipt.py::format_line" in finding.detail


@pytest.mark.parametrize(
    ("hold", "reason"),
    [(SCOPE, ""), (SCOPE, "   "), (NOT_MEASURED, "install coverage"), ("unsafe path name: a\\x01b", "rename it")],
)
def test_a_reject_with_nothing_to_act_on_keeps_the_unusable_answer_path(hold, reason):
    """No reason, or a hold no task can be derived from: the finding is the human's (FAIL), and the fix planner lists
    it as not converted, so the round escalates instead of asking or spawning forever."""
    v = verdict(hold, "reject", reason)
    [finding] = settle_holds([], [hold], {v.target: v})
    assert finding.source == "human" and finding.blocking and finding.id == hold_id(hold)
    r = VerifyResult(UNIT, 2, Verdict.FAIL, "b", "h")
    r.findings = [finding]
    plan = plan_fix_unit([], r, [v], ordinal=1, fix_minor=False)
    assert plan.groups == [] and plan.consumed == [] and len(plan.not_converted) == 1


def test_the_fix_unit_of_a_rejected_scope_hold_puts_the_decision_first_and_consumes_the_question():
    v = verdict(SCOPE, "reject", "inventory is not part of bulk discounts")
    findings = settle_holds([], [SCOPE], {v.target: v})
    r = VerifyResult(UNIT, 2, Verdict.FAIL, "b", "h")
    r.findings = findings
    plan = plan_fix_unit([], r, [v], ordinal=1, fix_minor=False)
    [group] = plan.groups
    assert plan.consumed == ["Q-004"] and group.chore and group.criteria == ()
    assert group.detail.startswith("Decided by human in Q-004: inventory is not part of bulk discounts. ")
    assert "Remove or relocate" in group.detail and "src/inventory/stock.py" in group.detail
    assert "src/inventory/stock.py" in group.title


def test_a_judge_finding_on_the_file_of_a_hold_is_subsumed_by_it():
    found = [STOCK, RECEIPT, judge("Rounding is wrong", "half-up not half-even")]
    assert subsumed_findings(found, [SCOPE, COVERAGE]) == {STOCK.id: SCOPE, RECEIPT.id: COVERAGE}
    assert subsumed_findings(found, []) == {}
    by_function = judge("format_line prints no currency", "the line total has no symbol")
    assert subsumed_findings([by_function], [COVERAGE]) == {by_function.id: COVERAGE}
    assert subsumed_findings([by_function], [SCOPE]) == {}
    minor = Finding(Severity.MINOR, "nit in src/inventory/stock.py", "d", "judge")
    assert subsumed_findings([minor], [SCOPE]) == {}  # only blocking judge findings are asked about


def test_one_answer_settles_the_hold_and_the_judge_finding_it_subsumes():
    accepted = {hold_id(SCOPE): verdict(SCOPE, "accept", "fine")}
    out = settle_holds([STOCK], [SCOPE], accepted, {"Q-004": {STOCK.id}})
    [settled] = out
    assert settled.id == STOCK.id and settled.severity is Severity.MINOR and settled.source == "judge"
    assert "settled with hold" in settled.detail and "fine" in settled.detail
    assert settle_holds([STOCK], [SCOPE], {}) == [STOCK]  # unanswered: nothing is settled


def test_a_rejected_hold_quotes_its_judge_finding_in_one_task_and_not_in_a_second_one():
    v = verdict(SCOPE, "reject", "inventory is not part of bulk discounts")
    out = settle_holds([STOCK], [SCOPE], {v.target: v}, {"Q-004": {STOCK.id}})
    blocking = [f for f in out if f.blocking]
    assert [f.id for f in blocking] == [hold_id(SCOPE)]  # the judge finding no longer blocks: one task, not two
    assert "Unrelated change to LOW_STOCK_THRESHOLD" in blocking[0].detail


def test_a_judge_finding_with_an_answer_of_its_own_keeps_it():
    own = HumanVerdict("Q-002", STOCK.id, "reject", "human", "revert it", "x")
    out = settle_holds(
        [STOCK], [SCOPE], {own.target: own, hold_id(SCOPE): verdict(SCOPE, "accept")}, {"Q-004": {STOCK.id}}
    )
    assert out == [STOCK]  # `apply_finding_verdicts` decides it by its own verdict


def test_the_question_of_a_hold_quotes_the_judge_finding_and_there_is_one_question_not_two(tmp_path):
    class Sink:
        def __init__(self) -> None:
            self.events: list[LedgerEvent] = []

        def append(self, event_type: str, /, **data) -> None:
            self.events.append(LedgerEvent(STAMP, "r-1", UNIT, len(self.events) + 1, event_type, data))

    sink = Sink()
    ids = raise_verdict_questions(
        tmp_path, "add-bulk-discount", outcomes=[], criteria=[], trace=[], findings=[STOCK, RECEIPT],
        existing=None, consumed=(), ledger=sink, round_no=1, redactor=Redactor({}), holds=[SCOPE, COVERAGE],
    )  # fmt: skip
    assert ids == ["Q-001", "Q-002"]  # the two holds; no question for either judge finding
    assert [e.data["target"] for e in sink.events if e.type == "question.raised"] == [
        hold_id(SCOPE), hold_id(COVERAGE),
    ]  # fmt: skip
    file = QuestionsFile.load(tmp_path / "questions.md")
    first = file.get("Q-001")
    assert first is not None
    text = file.data.decode()
    assert "Unrelated change to LOW_STOCK_THRESHOLD" in text and "Revert the change to src/inventory/stock.py" in text
    assert "One answer settles both" in text
    assert "no deterministic check confirms it" not in text


def test_a_judge_finding_on_another_subject_is_still_asked_on_its_own(tmp_path):
    class Sink:
        def append(self, event_type: str, /, **data) -> None:
            pass

    other = judge("Rounding is wrong", "half-up not half-even")
    ids = raise_verdict_questions(
        tmp_path, "add-bulk-discount", outcomes=[], criteria=[], trace=[], findings=[other, STOCK],
        existing=None, consumed=(), ledger=Sink(), round_no=1, redactor=Redactor({}), holds=[SCOPE],
    )  # fmt: skip
    assert len(ids) == 2  # the hold (quoting STOCK) and the unrelated finding


# -- review of F2: an answer settles only what its question showed, and a coverage hold is about its functions


LOAD_ROWS = judge(
    "SQL injection in load_rows",
    "src/pricing/receipt.py builds the query of load_rows with an f-string from the request.",
)


def test_an_answer_settles_only_the_findings_its_question_quoted():
    """An accept is permanent while the hold's text is stable: a judge finding of a later, freshly judged round that
    names the hold's file was never shown to the human, so the old answer must not settle it."""
    accepted = {hold_id(SCOPE): verdict(SCOPE, "accept", "fine", "Q-004")}
    later = judge("Stock can go negative", "src/inventory/stock.py lets remove() take more than is on hand.")
    out = settle_holds([STOCK, later], [SCOPE], accepted, {"Q-004": {STOCK.id}})
    assert [(f.id, f.blocking) for f in out] == [(STOCK.id, False), (later.id, True)]
    assert settle_holds([later], [SCOPE], accepted) == [later]  # a question that quoted nothing settles nothing


def test_a_rejected_hold_quotes_only_the_findings_its_question_showed():
    v = verdict(SCOPE, "reject", "inventory is not part of bulk discounts", "Q-004")
    later = judge("Stock can go negative", "src/inventory/stock.py lets remove() take more than is on hand.")
    out = settle_holds([STOCK, later], [SCOPE], {v.target: v}, {"Q-004": {STOCK.id}})
    by_id = {f.id: f for f in out}
    assert by_id[later.id] == later and by_id[STOCK.id].severity is Severity.MINOR
    assert "LOW_STOCK_THRESHOLD" in by_id[hold_id(SCOPE)].detail and "negative" not in by_id[hold_id(SCOPE)].detail


class _Sink:
    def __init__(self) -> None:
        self.events: list[LedgerEvent] = []

    def append(self, event_type: str, /, **data) -> None:
        self.events.append(LedgerEvent(STAMP, "r-1", UNIT, len(self.events) + 1, event_type, data))


def test_the_hold_question_records_the_findings_it_quoted(tmp_path):
    sink = _Sink()
    raise_verdict_questions(
        tmp_path, "add-bulk-discount", outcomes=[], criteria=[], trace=[], findings=[STOCK],
        existing=None, consumed=(), ledger=sink, round_no=1, redactor=Redactor({}), holds=[SCOPE],
    )  # fmt: skip
    [raised] = [e for e in sink.events if e.type == "question.raised"]
    assert raised.data["covers"] == [STOCK.id]
    assert hold_covers(sink.events) == {"Q-001": frozenset({STOCK.id})}


def test_a_finding_raised_after_its_hold_was_asked_is_asked_on_its_own(tmp_path):
    """The hold's question is still waiting, so it is not asked again and cannot quote a finding it never saw."""
    sink = _Sink()
    raise_verdict_questions(
        tmp_path, "add-bulk-discount", outcomes=[], criteria=[], trace=[], findings=[STOCK],
        existing=None, consumed=(), ledger=sink, round_no=1, redactor=Redactor({}), holds=[SCOPE],
    )  # fmt: skip
    later = judge("Stock can go negative", "src/inventory/stock.py lets remove() take more than is on hand.")
    ids = raise_verdict_questions(
        tmp_path, "add-bulk-discount", outcomes=[], criteria=[], trace=[], findings=[STOCK, later],
        existing=QuestionsFile.load(tmp_path / "questions.md"), consumed=(), ledger=sink, round_no=2,
        redactor=Redactor({}), holds=[SCOPE], covers=hold_covers(sink.events),
    )  # fmt: skip
    assert ids == ["Q-002"]  # the new finding alone: STOCK is quoted by the waiting Q-001
    assert sink.events[-1].data["target"] == later.id


def test_a_coverage_hold_is_about_its_functions_not_every_function_of_their_file():
    only_format_line = "diff coverage: changed code not run by any test: `src/pricing/receipt.py::format_line`"
    assert subsumed_findings([LOAD_ROWS], [only_format_line]) == {}  # another function of the same file
    by_function = judge("format_line prints no currency", "the line total has no symbol")
    assert subsumed_findings([by_function], [only_format_line]) == {by_function.id: only_format_line}
    # module-level code has no name: a hold that names `<module>` is about the file (live job 5541, Q-003 and Q-005)
    assert subsumed_findings([RECEIPT, LOAD_ROWS], [COVERAGE]) == {RECEIPT.id: COVERAGE, LOAD_ROWS.id: COVERAGE}


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("src/webapp.py crashes", False),
        ("app.pyx is compiled", False),
        ("see app.py.", True),
        ("see ./app.py:12", True),
        ("`app.py` changed", True),
    ],
)
def test_a_file_is_named_as_a_whole_path_not_as_part_of_another(text, hit):
    hold = "scope: `app.py` changes module `app`, which the spec does not name"
    finding = judge("a bug", text)
    assert (subsumed_findings([finding], [hold]) != {}) is hit


# -- a rejected hold of any kind with a WHEN ... THEN ... reason is a behaviour finding (live: a long diff)

LONG_DIFF = "the diff is longer than 120000 characters: the judge saw only the start"
SCENARIO_REASON = (
    "Split the unit in two and raise judge.max_diff_chars. WHEN the diff is longer than 120000 characters "
    "THEN the judge SHALL be shown every file, not only the start"
)


def _plan(hold: str, reason: str):
    from l4.specs.base import Criterion, Framework

    v = verdict(hold, "reject", reason)
    [finding] = settle_holds([], [hold], {v.target: v})
    family = [
        Criterion(
            "C-00000001", "greeting > Greet > Named", Framework.OPENSPEC, "greeting", "Greet", "Named", "WHEN x THEN y",
            "specs/greeting/spec.md", 1,
        )
    ]  # fmt: skip
    r = VerifyResult(UNIT, 2, Verdict.FAIL, "b", "h")
    r.findings = [finding]
    return finding, v, plan_fix_unit(family, r, [v], ordinal=1, fix_minor=False)


COVERAGE_REASON = (
    "Install the coverage plugin in the project. WHEN the coverage plugin is not installed "
    "THEN the gate SHALL report the missing plugin, not only that coverage was not measured"
)


def test_a_rejected_hold_of_another_kind_with_a_scenario_becomes_a_fix_task():
    finding, v, plan = _plan(NOT_MEASURED, COVERAGE_REASON)
    assert finding.source == "deterministic" and finding.blocking and finding.id == hold_id(NOT_MEASURED)
    [group] = plan.groups
    assert plan.consumed == [v.question] and plan.not_converted == [] and not group.chore
    assert group.ids == (finding.id,) and "Decided by human in Q-004" in group.detail
    assert plan.delta is not None
    [scenario] = plan.delta.requirements[0].scenarios
    assert scenario.text.startswith("- **WHEN** the coverage plugin is not installed\n- **THEN** the gate SHALL")


def test_a_rejected_hold_of_another_kind_without_a_scenario_still_escalates():
    finding, _, plan = _plan(NOT_MEASURED, "install coverage in CI")
    assert finding.source == "human"
    assert plan.groups == [] and plan.consumed == [] and len(plan.not_converted) == 1


def test_a_rejected_scope_hold_is_unchanged_by_a_scenario_in_its_reason():
    finding, _, plan = _plan(SCOPE, "inventory is not part of bulk discounts")
    assert finding.source == "deterministic" and "Remove or relocate" in finding.detail
    assert plan.groups[0].chore  # the harness's own fix
    with_scenario, _, _ = _plan(SCOPE, SCENARIO_REASON)
    assert with_scenario.source == "deterministic" and "Remove or relocate" in with_scenario.detail


def _question_text(tmp_path, hold: str) -> str:
    class Sink:
        def append(self, event_type: str, /, **data) -> None:
            pass

    raise_verdict_questions(
        tmp_path, "u", outcomes=[], criteria=[], trace=[], findings=[], existing=None, consumed=(), ledger=Sink(),
        round_no=1, redactor=Redactor({}), holds=[hold],
    )  # fmt: skip
    return " ".join((tmp_path / "questions.md").read_text().split())


@pytest.mark.parametrize("hold", [SCOPE, COVERAGE])
def test_the_question_of_a_scope_or_coverage_hold_promises_a_fix_unit(tmp_path, hold):
    assert "a rejected hold is fixed by a fix unit" in _question_text(tmp_path, hold)


@pytest.mark.parametrize("hold", [NOT_MEASURED])
def test_the_question_of_any_other_hold_asks_for_a_scenario_and_promises_nothing(tmp_path, hold):
    text = _question_text(tmp_path, hold)
    assert "fixed by a fix unit" not in text
    assert (
        "or `reject` and say why; end the reason with a sentence WHEN ... THEN ... so that a fix unit can be made"
        in text
    )


def _feedback_finding() -> Finding:
    from l4.verifier.types import FeedbackRef

    ref = FeedbackRef(
        "FB-001", "behaviour", "Split the diff", "Please.", "Ana, 2026-10-12T15:04:00Z", (), None,
        "the diff is longer than 120000 characters", "the judge SHALL see every file", "", "a" * 64,
    )  # fmt: skip
    return Finding(Severity.MAJOR, "Feedback FB-001 (behaviour): Split the diff", "Please.", "feedback", feedback=ref)


def test_a_feedback_only_plan_consumes_the_rejects_it_could_not_convert():
    """SCN-VER-66 (L4-VER-016): the human finding is listed as not converted and its question is consumed."""
    v = verdict(LONG_DIFF, "reject", "split the unit in two")
    [human] = settle_holds([], [LONG_DIFF], {v.target: v})
    assert human.source == "human"
    r = VerifyResult(UNIT, 3, Verdict.FAIL, "b", "h")
    r.findings = [human, _feedback_finding()]
    plan = plan_fix_unit([], r, [v], ordinal=1, fix_minor=False)
    assert plan.feedback_only and len(plan.not_converted) == 1
    assert plan.consumed == ["Q-004"]


def test_a_plan_that_is_not_feedback_only_keeps_its_consumed_list():
    v = verdict(LONG_DIFF, "reject", "split the unit in two")
    [human] = settle_holds([], [LONG_DIFF], {v.target: v})
    r = VerifyResult(UNIT, 3, Verdict.FAIL, "b", "h")
    r.findings = [human]
    plan = plan_fix_unit([], r, [v], ordinal=1, fix_minor=False)
    assert plan.groups == [] and plan.consumed == []


def test_a_hold_raised_again_after_a_feedback_only_spawn_is_asked_as_a_new_question(tmp_path):
    """SCN-VER-67 (L4-VER-016): no verdict in force, no human finding, a new hold question; Q-004 is consumed."""
    from l4.state.fold import fold
    from l4.verifier.verdicts import effective_verdicts, finding_sha256

    class Sink:
        def __init__(self) -> None:
            self.events: list[LedgerEvent] = []

        def append(self, event_type: str, /, **data) -> None:
            self.events.append(LedgerEvent(STAMP, "r-1", UNIT, len(self.events) + 1, event_type, data))

    sink = Sink()
    hid = hold_id(LONG_DIFF)
    ask = dict(outcomes=[], criteria=[], trace=[], findings=[], ledger=sink, redactor=Redactor({}), holds=[LONG_DIFF])
    assert raise_verdict_questions(tmp_path, "u", existing=None, consumed=(), round_no=3, **ask) == ["Q-001"]
    path = tmp_path / "questions.md"
    file = QuestionsFile.load(path)
    text = file.data.decode().replace(
        "<!-- write below this line -->", "<!-- write below this line -->\nreject too long"
    )
    file = QuestionsFile.parse(text).set_status("Q-001", QuestionStatus.ANSWERED)
    file.save(path)
    events = [
        *sink.events,
        LedgerEvent(STAMP, "r-1", UNIT, 10, "human.verdict", {
            "question": "Q-001", "target": hid, "decision": "reject", "by": "human", "reason": "too long",
            "text_sha256": finding_sha256(hid),
        }),
        LedgerEvent(
            STAMP, "r-1", UNIT, 11, "fix.spawned", {"fix_unit": "u-fix-1", "feedback_only": True, "consumed": []}
        ),
    ]  # fmt: skip
    effective = effective_verdicts(events, {hid: finding_sha256(hid)})
    assert effective == {}
    assert settle_holds([], [LONG_DIFF], effective) == []
    assert unresolved_holds([LONG_DIFF], effective) == [LONG_DIFF]
    consumed = fold(events, UNIT).verdicts_consumed
    again = raise_verdict_questions(
        tmp_path, "u", existing=QuestionsFile.load(path), consumed=consumed, round_no=4, **ask
    )
    assert again == ["Q-002"]


def test_a_replaced_reject_becomes_an_accept_that_clears_the_fail(tmp_path):
    """SCN-QMD-28 (L4-QMD-010): `consume_verdicts` records the changed answer as a second `human.verdict`, the latest
    one per target wins, and the hold raises no finding and is not asked again."""
    from l4.verifier.verdicts import consume_verdicts, effective_verdicts, finding_sha256

    class Sink:
        def __init__(self) -> None:
            self.events: list[LedgerEvent] = []

        def append(self, event_type: str, /, **data) -> None:
            self.events.append(LedgerEvent(STAMP, "r-1", UNIT, len(self.events) + 1, event_type, data))

    sink, path, hid = Sink(), tmp_path / "questions.md", hold_id(LONG_DIFF)
    raise_verdict_questions(
        tmp_path, "u", outcomes=[], criteria=[], trace=[], findings=[], existing=None, consumed=(), ledger=sink,
        round_no=3, redactor=Redactor({}), holds=[LONG_DIFF],
    )  # fmt: skip
    file = QuestionsFile.load(path)
    assert file is not None
    file = file.set_answer("Q-001", "reject split the unit in two").set_status("Q-001", QuestionStatus.ANSWERED)
    file.save(path)
    assert consume_verdicts(file, sink.events, sink, []) == ["Q-001"]
    current = {hid: finding_sha256(hid)}
    rejected = effective_verdicts(sink.events, current)
    assert rejected[hid].decision == "reject"
    assert [f.source for f in settle_holds([], [LONG_DIFF], rejected)] == ["human"]  # the FAIL of the loop
    file = file.replace_answer("Q-001", "accept the fix is in", who="Ana", on="2026-10-16")
    file.save(path)
    assert consume_verdicts(file, sink.events, sink, []) == ["Q-001"]
    assert [e.data["decision"] for e in sink.events if e.type == "human.verdict"] == ["reject", "accept"]
    accepted = effective_verdicts(sink.events, current)
    assert accepted[hid].decision == "accept" and accepted[hid].reason == "the fix is in"
    assert settle_holds([], [LONG_DIFF], accepted) == [] and unresolved_holds([LONG_DIFF], accepted) == []


# ---- holds on the judge's view (L4-VER-043, L4-VER-044) ---------------------------------------------------------

CUT_FILE = (
    "judge view: the diff of `data/seed.json` is longer than one part (120000 characters): the judge saw only its start"
)
UNSEEN = "judge view: the diff needs more than 8 parts of 120000 characters: the judge did not see `a.py`, `b.py`"
WHEN_THEN_REASON = "WHEN the diff is long THEN the judge SHALL see every file"


def test_the_0_4_14_length_text_is_the_legacy_judge_view_hold():
    assert LEGACY_LENGTH_HOLD == LONG_DIFF


@pytest.mark.parametrize("hold", [CUT_FILE, UNSEEN, LONG_DIFF])
def test_scn_ver_137_a_hold_on_the_judge_view_has_its_own_kind(hold):
    assert hold_kind(hold) == "judge_view"


def test_the_subjects_of_a_judge_view_hold_are_its_backticked_paths():
    assert hold_subjects(CUT_FILE) == ("data/seed.json",)
    assert hold_subjects(UNSEEN) == ("a.py", "b.py")
    assert hold_subjects(LONG_DIFF) == ()


@pytest.mark.parametrize("hold", [CUT_FILE, UNSEEN, LONG_DIFF])
def test_scn_ver_137_the_question_of_a_judge_view_hold_says_what_accept_and_reject_do(tmp_path, hold):
    text = _question_text(tmp_path, hold)
    assert "checked those files yourself" in text and "A fix unit cannot shrink the diff" in text
    assert "judge_view_rejected" in text and "split the change into smaller units" in text
    assert "WHEN" not in text and "fixed by a fix unit" not in text and "a fix unit can be made" not in text


@pytest.mark.parametrize("hold", [CUT_FILE, LONG_DIFF])
def test_scn_ver_138_scn_ver_139_a_rejected_judge_view_hold_is_a_human_finding_no_task_comes_from(hold):
    from l4.verifier.fixloop import _no_task_cause

    finding, v, plan = _plan(hold, WHEN_THEN_REASON)
    assert finding.source == "human" and finding.severity is Severity.MAJOR and finding.id == hold_id(hold)
    assert finding.title == JUDGE_VIEW_REJECTED_TITLE == "Rejected hold: the judge could not see all of the diff"
    assert "A fix unit cannot shrink the diff" in finding.detail and WHEN_THEN_REASON in finding.detail
    assert plan.groups == [] and plan.delta is None and plan.consumed == []
    assert len(plan.not_converted) == 1 and "a fix unit cannot shrink the diff" in plan.not_converted[0]
    assert _no_task_cause([finding]) == (
        "a person rejected a hold on the judge's view of the diff: a fix unit cannot shrink the diff",
        "judge_view_rejected",
    )


def test_a_finding_of_another_title_keeps_the_no_convertible_finding_cause():
    from l4.verifier.fixloop import _no_task_cause

    other = Finding(Severity.MAJOR, "Rejected hold: something else", "d", "human", id="H-1")
    assert _no_task_cause([other]) == (
        "no finding of this round can be converted into a fix task",
        "no_convertible_finding",
    )
    assert _no_task_cause([]) == ("no finding of this round can be converted into a fix task", "no_convertible_finding")


def test_a_rejected_judge_view_hold_without_a_reason_is_the_same_human_finding():
    finding, _, plan = _plan(CUT_FILE, "")
    assert finding.source == "human" and finding.title == JUDGE_VIEW_REJECTED_TITLE and plan.groups == []


def test_a_feedback_only_plan_consumes_the_rejected_judge_view_question():
    v = verdict(CUT_FILE, "reject", WHEN_THEN_REASON)
    [human] = settle_holds([], [CUT_FILE], {v.target: v})
    r = VerifyResult(UNIT, 3, Verdict.FAIL, "b", "h")
    r.findings = [human, _feedback_finding()]
    plan = plan_fix_unit([], r, [v], ordinal=1, fix_minor=False)
    assert plan.feedback_only and len(plan.not_converted) == 1 and plan.consumed == ["Q-004"]
