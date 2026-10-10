"""Verdict questions and answers (verifier 1.17, 5.8, 5.9; SPEC L4-VER-013, L4-QMD-004)."""

import dataclasses

import pytest

from l4.redact import Redactor
from l4.specs.base import Criterion, Framework
from l4.specs.questions import QuestionKind, QuestionsFile, QuestionStatus
from l4.state.ledger import LedgerEvent
from l4.verifier.evidence import stored_finding
from l4.verifier.types import CriterionEvidence, CriterionOutcome, Finding, HumanVerdict, Severity, TracingTest
from l4.verifier.verdicts import (
    apply_finding_verdicts,
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


def ask(tmp_path, ledger, *, outcomes, findings=(), existing=None, consumed=(), criteria=None):
    return raise_verdict_questions(
        tmp_path, "add-thing", outcomes=outcomes, criteria=criteria or [crit(A), crit(B)], trace=[], findings=findings,
        existing=existing, consumed=consumed, ledger=ledger, round_no=1, redactor=Redactor({}),
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
    assert verdict_status(file).ready == ("Q-001",)
    assert consume_verdicts(file, sink.events, sink, [crit(A)]) == ["Q-001"]
    [verdict] = [e for e in sink.events if e.type == "human.verdict"]
    assert (
        verdict.data["decision"] == "accept" and verdict.data["target"] == A and verdict.data["reason"] == "fine as is"
    )
    assert verdict.data["text_sha256"] == text_sha256(crit(A))
    assert consume_verdicts(file, sink.events, sink, [crit(A)]) == []  # not recorded twice
    assert verdict_status(file, consumed={"Q-001"}).any is False


def test_answer_without_accept_or_reject_not_consumed(tmp_path):
    sink = Sink()
    ask(tmp_path, sink, outcomes=[outcome(A)])
    file = answer(tmp_path / "questions.md", "Q-001", "yes")
    status = verdict_status(file)
    assert status.invalid == ("Q-001",) and not status.ready and not status.open
    assert consume_verdicts(file, sink.events, sink, [crit(A)]) == []
    assert not [e for e in sink.events if e.type == "human.verdict"]


def test_a_draft_under_status_open_is_still_open(tmp_path):
    sink = Sink()
    ask(tmp_path, sink, outcomes=[outcome(A)])
    file = answer(tmp_path / "questions.md", "Q-001", "accept", status="open")
    assert verdict_status(file).open == ("Q-001",)


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
    assert legacy_round(_state(), file) is None
    assert legacy_round(_state(verdicts_consumed=["Q-001"]), file) == 2  # answered and consumed, nothing is waiting


def test_a_verdict_question_event_carries_its_title(tmp_path):
    sink = Sink()
    finding = Finding(Severity.MAJOR, "Rounding is wrong", "half-up not half-even", "judge", criterion=A)
    ids = ask(tmp_path, sink, outcomes=[outcome(A)], findings=[finding])
    file = QuestionsFile.load(tmp_path / "questions.md")
    raised = [e for e in sink.events if e.type == "question.raised"]
    assert [e.data["id"] for e in raised] == ids
    assert [e.data["title"] for e in raised] == [file.get(i).title for i in ids]  # the title of the file, redacted
    assert all(e.data["title"] and e.data["title"] != "None" for e in raised)
