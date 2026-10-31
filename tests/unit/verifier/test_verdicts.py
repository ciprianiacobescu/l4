"""Verdict questions and answers (verifier 1.17, 5.8, 5.9; SPEC L4-VER-013, L4-QMD-004)."""

import dataclasses

import pytest

from l4.redact import Redactor
from l4.specs.base import Criterion, Framework
from l4.specs.questions import QuestionKind, QuestionsFile, QuestionStatus
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent
from l4.verifier.evidence import stored_finding
from l4.verifier.fixunit import when_then
from l4.verifier.notes import VERDICT_HINT, verdict_hints
from l4.verifier.types import CriterionEvidence, CriterionOutcome, Finding, HumanVerdict, Severity, TracingTest
from l4.verifier.verdicts import (
    MAX_VERDICT_REASON_CHARS,
    apply_finding_verdicts,
    bounded_reason,
    carry_rejects,
    consume_verdicts,
    effective_verdicts,
    parse_answer,
    raise_verdict_questions,
    regressions,
    text_sha256,
    verdict_status,
)

from ._integrity_helpers import STAMP, UNIT

A, B = "C-aaaaaaaa", "C-bbbbbbbb"


def crit(cid: str, text: str = "WHEN x THEN y") -> Criterion:
    return Criterion(cid, f"cap › req › {cid}", Framework.OPENSPEC, "cap", "req", cid, text, "specs/cap/spec.md", 1)


class Sink:
    def __init__(self) -> None:
        self.events: list[LedgerEvent] = []

    def append(self, event_type: str, /, **data) -> None:
        self.events.append(LedgerEvent(STAMP, "r-1", UNIT, len(self.events) + 1, event_type, data))


def outcome(cid: str, result: str = "needs_human") -> CriterionOutcome:
    return CriterionOutcome(cid, "alias", result, "pass", "uncovered: no adequate discriminating test traces it")  # type: ignore[arg-type]


def raised_of(ledger) -> list[str]:
    """The verdict question ids that the ledger's `question.raised` events name (what the orchestrator folds)."""
    return fold(ledger.events, UNIT).verdicts_raised


def ask(tmp_path, ledger, *, outcomes, findings=(), existing=None, consumed=(), criteria=None):
    return raise_verdict_questions(
        tmp_path, "add-thing", outcomes=outcomes, criteria=criteria or [crit(A), crit(B)], trace=[], findings=findings,
        existing=existing, consumed=consumed, raised=raised_of(ledger), ledger=ledger, round_no=1,
        redactor=Redactor({}),
    )  # fmt: skip


def answer(path, qid: str, text: str, status: str = "answered") -> QuestionsFile:
    file = QuestionsFile.load(path)
    q = file.get(qid)
    marker = "<!-- write below this line -->"
    data = file.data.decode().replace(f"## {qid}: {q.title}", f"## {qid}: {q.title}", 1)
    start = data.index(marker, data.index(f"## {qid}:")) + len(marker)
    data = data[:start] + "\n" + text + data[start:]
    parsed = QuestionsFile.parse(data)
    out = parsed.set_status(qid, QuestionStatus(status))
    out.save(path)
    return QuestionsFile.load(path)


def test_one_question_per_affected_criterion_and_judge_only_finding(tmp_path):
    sink = Sink()
    finding = Finding(Severity.MAJOR, "Rounding is wrong", "half-up not half-even", "judge", criterion=A)
    minor = Finding(Severity.MINOR, "nit", "d", "judge")
    deterministic = Finding(Severity.MAJOR, "lint", "d", "deterministic")
    ids = ask(
        tmp_path,
        sink,
        outcomes=[outcome(A), outcome(B, "pass"), outcome(B, "disputed")],
        findings=[finding, minor, deterministic],
    )
    assert ids == ["Q-001", "Q-002", "Q-003"]  # A, B (disputed), the judge-only major
    file = QuestionsFile.load(tmp_path / "questions.md")
    assert all(
        q.kind is QuestionKind.VERDICT and q.blocking_tasks == () and q.blocking_readable for q in file.questions
    )
    assert "| none |" in file.data.decode() and "**Blocking tasks:** none" in file.data.decode()
    raised = [e for e in sink.events if e.type == "question.raised"]
    assert [(e.data["id"], e.data["kind"], e.data["target"]) for e in raised] == [
        ("Q-001", "verdict", A), ("Q-002", "verdict", B), ("Q-003", "verdict", finding.id),
    ]  # fmt: skip
    assert raised[0].data["text_sha256"] == text_sha256(crit(A))


def test_an_open_question_for_a_target_is_not_asked_twice_but_a_consumed_one_can_be(tmp_path):
    sink = Sink()
    assert ask(tmp_path, sink, outcomes=[outcome(A)]) == ["Q-001"]
    file = QuestionsFile.load(tmp_path / "questions.md")
    assert ask(tmp_path, sink, outcomes=[outcome(A)], existing=file) == []
    file = answer(tmp_path / "questions.md", "Q-001", "accept: fine")
    assert ask(tmp_path, sink, outcomes=[outcome(A)], existing=file) == []  # answered, not consumed yet
    assert ask(tmp_path, sink, outcomes=[outcome(A)], existing=file, consumed={"Q-001"}) == ["Q-002"]


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("accept", ("accept", "")),
        ("Accept: the rounding is intended", ("accept", "the rounding is intended")),
        ("REJECT - wrong, WHEN a THEN b", ("reject", "wrong, WHEN a THEN b")),
        ("`accept`, fine", ("accept", "fine")),
        ("accepted", None),
        ("yes", None),
        ("I accept", None),
        ("", None),
    ],
)
def test_the_first_word_must_be_accept_or_reject(text, parsed):
    assert parse_answer(text) == parsed


def test_accept_recorded_and_not_reasked(tmp_path):
    sink = Sink()
    ask(tmp_path, sink, outcomes=[outcome(A)])
    path = tmp_path / "questions.md"
    file = answer(path, "Q-001", "accept: fine as is")
    assert verdict_status(file, raised=raised_of(sink)).ready == ("Q-001",)
    assert consume_verdicts(file, sink.events, sink, [crit(A)]) == ["Q-001"]
    [verdict] = [e for e in sink.events if e.type == "human.verdict"]
    assert (
        verdict.data["decision"] == "accept" and verdict.data["target"] == A and verdict.data["reason"] == "fine as is"
    )
    assert verdict.data["text_sha256"] == text_sha256(crit(A))
    assert consume_verdicts(file, sink.events, sink, [crit(A)]) == []  # not recorded twice
    assert verdict_status(file, consumed={"Q-001"}, raised=raised_of(sink)).any is False


def test_answer_without_accept_or_reject_not_consumed(tmp_path):
    sink = Sink()
    ask(tmp_path, sink, outcomes=[outcome(A)])
    file = answer(tmp_path / "questions.md", "Q-001", "yes")
    status = verdict_status(file, raised=raised_of(sink))
    assert status.invalid == ("Q-001",) and not status.ready and not status.open
    assert consume_verdicts(file, sink.events, sink, [crit(A)]) == []
    assert not [e for e in sink.events if e.type == "human.verdict"]


def test_a_draft_under_status_open_is_still_open(tmp_path):
    sink = Sink()
    ask(tmp_path, sink, outcomes=[outcome(A)])
    file = answer(tmp_path / "questions.md", "Q-001", "accept", status="open")
    assert verdict_status(file, raised=raised_of(sink)).open == ("Q-001",)


def test_a_dismissed_verdict_question_reads_as_open_and_is_named(tmp_path):  # L4-OPS-009
    sink = Sink()
    ask(tmp_path, sink, outcomes=[outcome(A), outcome(B)])
    file = answer(tmp_path / "questions.md", "Q-001", "", status="dismissed")
    status = verdict_status(file, raised=raised_of(sink))
    assert status.open == ("Q-001", "Q-002") and status.dismissed == ("Q-001",)
    assert not status.ready and not status.invalid and status.any
    assert consume_verdicts(file, sink.events, sink, [crit(A), crit(B)]) == []
    assert verdict_status(file, consumed={"Q-001"}, raised=raised_of(sink)).dismissed == ()
    assert verdict_hints(status) == [
        VERDICT_HINT,
        "Q-001: a verdict question cannot be dismissed: start the answer with accept or reject",
    ]


def verdict_event(seq: int, question: str, target: str, decision: str, sha: str) -> LedgerEvent:
    data = {
        "question": question,
        "target": target,
        "decision": decision,
        "by": "ana",
        "reason": "r",
        "text_sha256": sha,
    }
    return LedgerEvent(STAMP, "r-1", UNIT, seq, "human.verdict", data)


def test_effective_verdicts_follow_the_latest_answer_and_void_an_accept_when_the_text_changes():
    old = text_sha256(crit(A))
    events = [verdict_event(1, "Q-001", A, "accept", old)]
    assert effective_verdicts(events, {A: old})[A].decision == "accept"
    assert effective_verdicts(events, {A: text_sha256(crit(A, "WHEN x THEN z"))}) == {}  # the text changed
    assert effective_verdicts(events, {}) == {}  # the criterion is gone
    flipped = [*events, verdict_event(2, "Q-002", A, "reject", old)]
    assert effective_verdicts(flipped, {A: old})[A].decision == "reject"


def test_accepted_criterion_that_regresses_fails():
    sha = text_sha256(crit(A))
    events = [verdict_event(1, "Q-001", A, "accept", sha)]
    effective = effective_verdicts(events, {A: sha})
    failing = CriterionEvidence(A, "a", "fail", (TracingTest("t::a", "failed", "zero_value"),))
    assert [v.question for v in regressions(effective, [failing])] == ["Q-001"]
    voided = [*events, LedgerEvent(STAMP, "r-1", UNIT, 2, "human.void", {"question": "Q-001", "target": A})]
    assert effective_verdicts(voided, {A: sha}) == {}  # a regression voids the accept for good
    fine = CriterionEvidence(A, "a", "covered", (TracingTest("t::a", "passed", "zero_value"),))
    assert regressions(effective, [fine]) == []


def test_a_reject_is_consumed_by_the_fix_unit_that_took_it():
    sha = text_sha256(crit(A))
    events = [verdict_event(1, "Q-001", A, "reject", sha)]
    assert effective_verdicts(events, {A: sha})[A].decision == "reject"
    spawned = LedgerEvent(STAMP, "r-1", UNIT, 2, "fix.spawned", {"consumed": ["Q-001"]})
    assert effective_verdicts([*events, spawned], {A: sha}) == {}


def _spawn(seq: int, **data) -> LedgerEvent:
    return LedgerEvent(STAMP, "r-1", UNIT, seq, "fix.spawned", {"parent": UNIT, "fix_unit": "u-fix-1", **data})


def test_a_reject_before_a_feedback_only_spawn_is_consumed():
    """SCN-VER-64 (L4-VER-016): 0.4.5 wrote `consumed: []` for such a spawn, so the order of the ledger decides."""
    sha = text_sha256(crit(A))
    reject = verdict_event(1, "Q-004", A, "reject", sha)
    assert effective_verdicts([reject, _spawn(2, feedback_only=True, consumed=[])], {A: sha}) == {}
    assert effective_verdicts([reject, _spawn(2, feedback_only=True, consumed=["Q-004"])], {A: sha}) == {}


def test_a_reject_after_a_feedback_only_spawn_and_before_another_kind_of_spawn_stays():
    """SCN-VER-65 (L4-VER-016)."""
    sha = text_sha256(crit(A))
    reject = verdict_event(2, "Q-004", A, "reject", sha)
    after = [_spawn(1, feedback_only=True, consumed=[]), reject]
    assert effective_verdicts(after, {A: sha})[A].decision == "reject"
    plain = [verdict_event(1, "Q-004", A, "reject", sha), _spawn(2, consumed=[]), _spawn(3, adopted=True)]
    assert effective_verdicts(plain, {A: sha})[A].decision == "reject"


def test_a_spawn_that_lists_its_unconverted_rejects_consumes_only_those():
    """L4-VER-016: a feedback-only spawn written by 0.4.6 and later names the rejects it consumes; an earlier reject it
    does not name (one a task could be derived from, left waiting) stays in force."""
    sha_a, sha_b = text_sha256(crit(A)), text_sha256(crit(B))
    events = [
        verdict_event(1, "Q-004", A, "reject", sha_a),
        verdict_event(2, "Q-005", B, "reject", sha_b),
        _spawn(3, feedback_only=True, lists_unconverted=True, consumed=["Q-004"]),
    ]
    got = effective_verdicts(events, {A: sha_a, B: sha_b})
    assert A not in got and got[B].decision == "reject"


def test_a_feedback_only_spawn_leaves_an_accept_and_a_newer_reject_alone():
    sha = text_sha256(crit(A))
    accept = verdict_event(1, "Q-001", A, "accept", sha)
    events = [accept, _spawn(2, feedback_only=True, consumed=[])]
    assert effective_verdicts(events, {A: sha})[A].decision == "accept"
    flipped = [
        verdict_event(1, "Q-001", A, "reject", sha),
        _spawn(2, feedback_only=True),
        verdict_event(3, "Q-002", A, "accept", sha),
    ]
    assert effective_verdicts(flipped, {A: sha})[A].decision == "accept"


def test_finding_verdicts_waive_or_confirm_judge_only_findings():
    finding = Finding(Severity.MAJOR, "Rounding", "d", "judge")
    other = Finding(Severity.BLOCKER, "Other", "d", "judge")
    accept = HumanVerdict("Q-1", finding.id, "accept", "ana", "intended", "")
    reject = HumanVerdict("Q-2", other.id, "reject", "ana", "wrong", "")
    waived, confirmed = apply_finding_verdicts([finding, other], {finding.id: accept, other.id: reject})
    assert waived.severity is Severity.MINOR and "waived by ana: intended" in waived.detail and waived.id == finding.id
    assert confirmed.source == "human" and confirmed.blocking and "rejected by ana" in confirmed.detail


def _asked(qid: str, target: str, round_no: int = 1) -> LedgerEvent:
    data = {"id": qid, "kind": "verdict", "source": "verifier", "target": target, "round": round_no}
    return LedgerEvent(STAMP, "r-1", UNIT, 1, "question.raised", data)


def test_a_reject_moves_to_the_finding_of_the_same_title_that_the_fresh_judge_tied_to_a_criterion():
    old = Finding(Severity.MAJOR, "VAT ignores the discount", "d1", "judge")
    tied = Finding(Severity.MAJOR, "VAT ignores the discount", "d2, reworded", "judge", A)
    assert tied.id != old.id  # the id hashes title and criterion
    reject = HumanVerdict("Q-002", old.id, "reject", "ana", "WHEN x THEN y", "")
    stored = {(1, old.id): old}
    findings, kept = carry_rejects([tied], {old.id: reject}, [_asked("Q-002", old.id)], lambda n, t: stored.get((n, t)))
    assert findings == [tied] and kept[tied.id].target == tied.id and kept[tied.id].question == "Q-002"
    [failed] = apply_finding_verdicts(findings, kept)
    assert failed.source == "human" and failed.id == tied.id


def test_a_reject_whose_finding_is_not_raised_again_brings_the_stored_finding_back_as_the_human_s():
    old = Finding(Severity.MAJOR, "VAT ignores the discount", "d1", "judge")
    minor = Finding(Severity.MINOR, "Case", "d", "judge")
    reject = HumanVerdict("Q-002", old.id, "reject", "ana", "WHEN x THEN y", "")
    events = [_asked("Q-002", old.id)]

    def asked(n: int, t: str) -> Finding | None:
        return old if (n, t) == (1, old.id) else None

    findings, kept = carry_rejects([minor], {old.id: reject}, events, asked)
    assert findings == [minor, old] and kept == {old.id: reject}
    assert apply_finding_verdicts(findings, kept)[1].source == "human"
    # nothing to carry: no record of the finding, an accept, a hold, or a finding this round already holds
    assert carry_rejects([minor], {old.id: reject}, events, lambda n, t: None) == ([minor], {old.id: reject})
    accept = dataclasses.replace(reject, decision="accept")
    assert carry_rejects([minor], {old.id: accept}, events, lambda n, t: old)[0] == [minor]
    hold = HumanVerdict("Q-002", "H-12345678", "reject", "ana", "", "")
    assert carry_rejects([minor], {hold.target: hold}, [_asked("Q-002", hold.target)], lambda n, t: old)[0] == [minor]
    assert carry_rejects([old], {old.id: reject}, events, lambda n, t: old)[0] == [old]
    # a question the ledger does not know (never raised, or another kind) carries nothing
    assert carry_rejects([minor], {old.id: reject}, [], lambda n, t: old)[0] == [minor]


def test_a_stored_finding_is_read_by_id_and_a_broken_entry_is_skipped():
    old = Finding(Severity.MAJOR, "VAT ignores the discount", "d1", "judge")
    record = {"findings": [{"title": "no severity"}, "junk", {**dataclasses.asdict(old), "severity": "major"}]}
    assert stored_finding(record, old.id) == old
    assert stored_finding(record, "F-00000000") is None
    assert stored_finding({"findings": "not a list"}, old.id) is None and stored_finding(None, old.id) is None


def test_an_answered_question_the_harness_never_raised_is_not_a_human_verdict(tmp_path):
    forged_dir = tmp_path / "forged"
    forged_dir.mkdir()
    ask(forged_dir, Sink(), outcomes=[outcome(A)])  # a questions.md written by something other than this ledger
    file = answer(forged_dir / "questions.md", "Q-001", "accept: fine")
    sink = Sink()  # the ledger of the run has no `question.raised` for it
    assert consume_verdicts(file, sink.events, sink, [crit(A)]) == []
    assert not [e for e in sink.events if e.type == "human.verdict"]


# --- a round an older harness left without verdict questions (L4-VER-013, SCN-VER-47) ------------------------------


def _state(**over):
    from l4.state.fold import LastVerdict, UnitState

    last = LastVerdict(round=2, verdict="NEEDS_HUMAN", findings=1)
    base = {"unit": "openspec:x", "phase": "awaiting_human", "last_verdict": last}
    return UnitState(**{**base, **over})


def test_legacy_round_is_a_needs_human_round_nobody_asked_about():
    from l4.verifier.verdicts import legacy_round

    assert legacy_round(_state(), None) == 2
    assert legacy_round(_state(verdict_asked_round=1), None) == 2  # the questions were for an earlier round
    assert legacy_round(_state(verdict_asked_round=2), None) is None  # asked: whatever their state, not legacy
    assert legacy_round(_state(phase="verifying"), None) is None
    from l4.state.fold import LastVerdict

    assert legacy_round(_state(last_verdict=LastVerdict(round=2, verdict="FAIL", findings=1)), None) is None
    assert legacy_round(_state(last_verdict=None), None) is None


def test_a_verdict_question_waiting_in_questions_md_is_not_a_legacy_round(tmp_path):
    from l4.verifier.verdicts import legacy_round

    ask(tmp_path, Sink(), outcomes=[outcome(A)])
    file = QuestionsFile.load(tmp_path / "questions.md")
    assert legacy_round(_state(verdicts_raised=["Q-001"]), file) is None
    # answered and consumed, nothing is waiting
    assert legacy_round(_state(verdicts_raised=["Q-001"], verdicts_consumed=["Q-001"]), file) == 2
    # no ledger event names it (a restart carried it over): stale, so nothing is waiting either (L4-VER-070)
    assert legacy_round(_state(), file) == 2


def test_a_verdict_question_event_carries_its_title(tmp_path):
    sink = Sink()
    finding = Finding(Severity.MAJOR, "Rounding is wrong", "half-up not half-even", "judge", criterion=A)
    ids = ask(tmp_path, sink, outcomes=[outcome(A)], findings=[finding])
    file = QuestionsFile.load(tmp_path / "questions.md")
    raised = [e for e in sink.events if e.type == "question.raised"]
    assert [e.data["id"] for e in raised] == ids
    assert [e.data["title"] for e in raised] == [file.get(i).title for i in ids]  # the title of the file, redacted
    assert all(e.data["title"] and e.data["title"] != "None" for e in raised)


def test_the_question_names_the_fix_for_the_cap(tmp_path):
    """L4-VER-055, SCN-VER-185: a criterion that only the cap left uncovered says so and names the way out."""
    why = (
        "uncovered: the judge passed it, and only the per-test cap left it uncovered: t::missing traces 7 criteria, "
        "more than verifier.max_criteria_per_test (3); the judge did not confirm it for this criterion"
    )
    capped = CriterionOutcome(A, "alias", "needs_human", "pass", why)  # type: ignore[arg-type]
    ask(tmp_path, Sink(), outcomes=[capped])
    text = QuestionsFile.load(tmp_path / "questions.md").data.decode()
    fix = (
        "Fix: answer accept if t::missing checks this criterion as its scenario says; or reject: give it its own test "
        "of at most 3 ids (a reject fails the criterion and spends a fix round)."
    )
    assert f"Why: {why}" in text and fix in text
    assert text.index(fix) < text.index("Answer `accept` if the criterion is satisfied as it stands")
    spaced = tmp_path / "spaced"  # a test id from a JUnit name can hold spaces (a name-tagged runner)
    spaced.mkdir()
    name = 'it("C-aaaaaaaa C-bbbbbbbb: flow")'
    ask(spaced, Sink(), outcomes=[CriterionOutcome(A, "alias", "needs_human", "pass", why.replace("t::missing", name))])  # type: ignore[arg-type]
    assert (
        f"Fix: answer accept if {name} checks this criterion"
        in QuestionsFile.load(spaced / "questions.md").data.decode()
    )
    other = tmp_path / "other"
    other.mkdir()
    ask(other, Sink(), outcomes=[outcome(A)])
    assert "Fix: answer accept if" not in QuestionsFile.load(other / "questions.md").data.decode()


# --- a verdict question counts only in the attempt that raised it (L4-VER-070) ----------------------------------------


def carried_over(tmp_path):
    """Q-001 answered `accept: fine` in `questions.md`, and a ledger that no `question.raised` of names it: the state a
    restart (or a hand-written file) leaves."""
    first = Sink()
    ask(tmp_path, first, outcomes=[outcome(A)])
    file = answer(tmp_path / "questions.md", "Q-001", "accept: fine")
    return file, Sink()  # the new attempt's ledger is empty


def test_a_verdict_question_no_ledger_event_names_is_stale_not_ready(tmp_path):
    file, ledger = carried_over(tmp_path)
    status = verdict_status(file, raised=raised_of(ledger))
    assert status.stale == ("Q-001",)
    assert not (status.open or status.ready or status.invalid or status.dismissed or status.any)
    assert verdict_status(file, raised={"Q-001"}).ready == ("Q-001",)  # named: as before
    assert verdict_status(file, raised={"Q-001"}).stale == ()


@pytest.mark.parametrize("status", ["open", "answered", "dismissed"])
def test_a_stale_question_is_stale_in_every_status_but_a_superseded_or_consumed_one_is_left_out(tmp_path, status):
    sink = Sink()
    ask(tmp_path, sink, outcomes=[outcome(A)])
    file = answer(tmp_path / "questions.md", "Q-001", "" if status == "dismissed" else "reject: no", status=status)
    assert verdict_status(file, raised=()).stale == ("Q-001",)
    assert verdict_status(file, {"Q-001"}, raised=()).stale == ()  # consumed
    superseded = file.supersede_by_restart("Q-001")
    assert verdict_status(superseded, raised=()).stale == ()


def test_the_target_of_a_stale_question_is_asked_again_and_the_new_question_is_this_attempt_s(tmp_path):
    file, ledger = carried_over(tmp_path)
    assert ask(tmp_path, ledger, outcomes=[outcome(A)], existing=file) == ["Q-002"]  # not "still waiting"
    reloaded = QuestionsFile.load(tmp_path / "questions.md")
    status = verdict_status(reloaded, raised=raised_of(ledger))
    assert (status.open, status.stale, status.ready) == (("Q-002",), (), ())  # Q-001 is superseded by Q-002
    assert ask(tmp_path, ledger, outcomes=[outcome(A)], existing=reloaded) == []  # Q-002 now waits as usual


def test_a_stale_answer_is_not_consumed_and_a_named_one_is(tmp_path):  # consume_verdicts keeps its rule
    file, ledger = carried_over(tmp_path)
    assert consume_verdicts(file, ledger.events, ledger, [crit(A)]) == []
    ask(tmp_path, ledger, outcomes=[outcome(A)], existing=file)
    file = answer(tmp_path / "questions.md", "Q-002", "reject: no")
    assert consume_verdicts(file, ledger.events, ledger, [crit(A)]) == ["Q-002"]
    assert verdict_status(file, {"Q-002"}, raised=raised_of(ledger)).any is False


def test_asking_the_target_again_supersedes_the_stale_question_by_the_new_one(tmp_path):
    file, ledger = carried_over(tmp_path)
    assert ask(tmp_path, ledger, outcomes=[outcome(A)], existing=file) == ["Q-002"]
    after = QuestionsFile.load(tmp_path / "questions.md")
    old = after.get("Q-001")
    assert (old.status, old.superseded_by) == (QuestionStatus.SUPERSEDED, "Q-002")
    assert "| Q-001 | superseded |" in after.data.decode() and "| Q-002 | open |" in after.data.decode()
    assert verdict_status(after, raised=raised_of(ledger)).stale == ()  # nothing stale is left to list
    assert "accept: fine" in after.data.decode()  # the answer stays as history


def test_only_the_stale_questions_of_the_targets_asked_again_are_superseded(tmp_path):
    first = Sink()
    ask(tmp_path, first, outcomes=[outcome(A), outcome(B)])
    answer(tmp_path / "questions.md", "Q-001", "accept: fine")
    file = answer(tmp_path / "questions.md", "Q-002", "reject: no")
    new = Sink()  # the new attempt's ledger: empty, so Q-001 (A) and Q-002 (B) are stale
    assert ask(tmp_path, new, outcomes=[outcome(A)], existing=file) == ["Q-003"]  # only A is asked again
    after = QuestionsFile.load(tmp_path / "questions.md")
    assert (after.get("Q-001").status, after.get("Q-001").superseded_by) == (QuestionStatus.SUPERSEDED, "Q-003")
    assert after.get("Q-002").status is QuestionStatus.ANSWERED  # B was not asked: its question stays, stale
    assert verdict_status(after, raised=raised_of(new)).stale == ("Q-002",)


def test_a_waiting_question_keeps_its_target_from_being_asked_and_nothing_is_superseded(tmp_path):
    file, ledger = carried_over(tmp_path)
    ask(tmp_path, ledger, outcomes=[outcome(A)], existing=file)  # Q-002 is open and named
    reloaded = QuestionsFile.load(tmp_path / "questions.md")
    before = reloaded.data
    assert ask(tmp_path, ledger, outcomes=[outcome(A)], existing=reloaded) == []
    assert QuestionsFile.load(tmp_path / "questions.md").data == before


# --- a reject's scenario survives the reason's cut (verdict-reason-scenario 1.1; L4-VER-059) -------------------------

CONSUMER_SENTENCE = (
    "WHEN after seedTwoTenants(db) the owner inserts tenant_c THEN a test asserts that [...DEFAULT_ROLES].sort() "
    'deep-equals ["approver", "auditor", "author", "tenant_admin"] and that the roles of tenant_a are unchanged'
)


def test_a_reason_within_the_limit_is_kept_whole_scn_ver_263():
    reason = "the roles seed is wrong. " * 40 + CONSUMER_SENTENCE  # the consumer's 1,207 characters, about
    assert 1000 < len(reason) <= MAX_VERDICT_REASON_CHARS
    assert bounded_reason(reason) == reason
    assert bounded_reason("x" * MAX_VERDICT_REASON_CHARS) == "x" * MAX_VERDICT_REASON_CHARS


def test_a_long_reason_keeps_its_last_sentence_whole_and_cuts_before_it_scn_ver_262():
    reason = "WHEN old THEN first scenario. " + "the seed is wrong. " * 260 + CONSUMER_SENTENCE
    assert len(reason) > 4500
    cut = bounded_reason(reason)
    assert len(cut) <= MAX_VERDICT_REASON_CHARS
    assert cut.endswith(CONSUMER_SENTENCE) and " … " + CONSUMER_SENTENCE in cut
    assert cut.startswith("WHEN old THEN first scenario.")  # the head is the start of the reason
    assert len(cut) - len(CONSUMER_SENTENCE) >= 197  # the head keeps at least 197 characters


def test_a_long_reason_without_a_sentence_is_cut_at_the_limit_scn_ver_263():
    reason = "the seed is wrong, no scenario here. " * 140
    assert len(reason) > 5000
    assert bounded_reason(reason) == reason[:MAX_VERDICT_REASON_CHARS]


def test_a_sentence_longer_than_the_limit_is_cut_at_its_end_as_before_scn_ver_263():
    sentence = "WHEN x THEN " + "a" * 3900
    reason = "the seed is wrong. " * 100 + sentence
    assert len(reason) > 5000 and len(sentence) > MAX_VERDICT_REASON_CHARS - 200
    assert bounded_reason(reason) == reason[:MAX_VERDICT_REASON_CHARS]


def test_a_recorded_long_reject_ends_with_the_whole_then_and_the_fix_unit_reads_it_scn_ver_262(tmp_path):
    sink = Sink()
    ask(tmp_path, sink, outcomes=[outcome(A)])
    sentence = 'WHEN x THEN a test asserts that [...DEFAULT_ROLES].sort() deep-equals ["approver", "auditor"]'
    answer_text = "reject: " + "the roles are wrong. " * 220 + sentence
    assert len(answer_text) > 4500
    file = answer(tmp_path / "questions.md", "Q-001", answer_text)
    assert consume_verdicts(file, sink.events, sink, [crit(A)]) == ["Q-001"]
    [verdict] = [e for e in sink.events if e.type == "human.verdict"]
    reason = verdict.data["reason"]
    assert len(reason) <= MAX_VERDICT_REASON_CHARS and reason.endswith(sentence)
    assert when_then(reason) == (
        '- **WHEN** x\n- **THEN** a test asserts that [...DEFAULT_ROLES].sort() deep-equals ["approver", "auditor"]'
    )
