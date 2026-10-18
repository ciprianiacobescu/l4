"""Human verdicts (SPEC L4-VER-013, L4-QMD-004): the questions the verifier asks and the answers it consumes.

Round n ends NEEDS_HUMAN with one `Kind: verdict` question per criterion that is `needs_human` or `disputed` and per
judge-only blocker or major finding (identified by `F-` and a hash of its title, `Finding.id`). The question holds no
task (`Blocking tasks: none`). The human answers with a first word `accept` or `reject` (any case), then a reason;
for a spec gap `reject` carries the WHEN/THEN of the missing scenario (D6). `consume_verdicts` records
`human.verdict{question, target, decision, by, reason, text_sha256, answer_sha256}` once per answer. An answer that
starts with anything else is invalid: it is not consumed, and the sticky note asks for a fix.

Which verdict applies in a round (`effective_verdicts`, D3): the latest one per target, with an `accept` void once the
criterion's text changed or a deterministic check later failed for it (`human.void`), and a `reject` consumed once a
fix unit took it (`fix.spawned{consumed}`), after which the target is judged afresh.
A hold (scope, diff coverage, ...) is asked about like a finding, and its answer is a human decision like any other: an
`accept` waives it, and a `reject` turns it into a deterministic finding that carries the human's text (`settle_holds`),
so the round is a FAIL and the fix-unit path acts on it. Neither answer is asked again. A judge finding about the file
or the function of a hold is part of the hold's question, and the one answer settles both (`subsumed_findings`), but
only the findings that question quoted (`question.raised{covers}`, `hold_covers`): an answer never settles what it never
showed.
This module imports nothing from the ladder or the orchestrator: the planner and the orchestrator read it too.
"""

import dataclasses
import hashlib
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from l4.clarifier.actor import Actor
from l4.config.schema import L4Config
from l4.redact import Redactor
from l4.specs.base import Criterion
from l4.specs.criteria import normalise
from l4.specs.questions import (
    QUESTIONS_FILENAME,
    NewQuestion,
    Question,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    effective_answer,
    is_answered,
    question_titles,
    raise_questions,
)
from l4.state.fold import UnitState
from l4.state.ledger import LedgerEvent
from l4.verifier.types import CriterionEvidence, CriterionOutcome, Finding, HumanVerdict, Severity

_DECISION = re.compile(r"\s*[`*_\"']*(accept|reject)[`*_\"']*(?![A-Za-z0-9])[\s:,.;\-–—)]*(.*)", re.I | re.S)
_TARGET = re.compile(r"\b([CFH]-[0-9a-f]{8})\b")
MAX_SUMMARY_CHARS = 700


class EventSink(Protocol):
    def append(self, event_type: str, /, **data: Any) -> Any: ...


def text_sha256(criterion: Criterion) -> str:
    return hashlib.sha256(normalise(criterion.text).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HoldView:
    """What a `judge view:` hold covers: `sha` binds a person's accept to the head blob of every file the hold covers
    and to the full list of files the judge did not see (the hold's text names at most five), `paths` is that list.
    The hold's id stays the hash of its text; the accept is void when this content changes (review M1)."""

    sha: str
    paths: tuple[str, ...]


QUESTION_MAX_PATHS = 100  # the unseen files a hold's question lists; the rest are in verdict.json


def hold_id(text: str) -> str:
    """The target of a hold's verdict question: `H-` and eight hex digits of the hold's text."""
    return "H-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def unresolved_holds(holds: Sequence[str], effective: Mapping[str, HumanVerdict]) -> list[str]:
    """The holds no human has answered: an `accept` waives the hold (a dispute cannot loop, L4-VER-013) and a `reject`
    is a decision too, so it is not asked again; `settle_holds` turns it into a finding."""
    return [h for h in holds if hold_id(h) not in effective]


_BACKTICKED = re.compile(r"`([^`]+)`")
_SCOPE_HOLD = re.compile(r"^scope: `[^`]+` changes module `[^`]+`")
_COVERAGE_HOLD = "diff coverage: changed code not run by any test: "
_SPEC_VIEW_HOLD = re.compile(r"the spec file .+: the judge (?:saw only|did not see) ")  # L4-KSP-014
JUDGE_VIEW_PREFIX = "judge view: "  # the holds on what the judge could not see of the diff (L4-VER-043)
LEGACY_LENGTH_HOLD = "the diff is longer than 120000 characters: the judge saw only the start"  # the 0.4.14 text
JUDGE_VIEW_REJECTED_TITLE = "Rejected hold: the judge could not see all of the diff"
HoldKind = Literal["scope", "coverage", "judge_view", "other"]


def hold_kind(text: str) -> HoldKind:
    """What a hold is about, from its text (the texts are fixed by `evidence/scope.py`, `evidence/diffcov.py` and the
    judge step): the two kinds a fix task can be derived from, `judge_view` (what the judge could not see of the diff:
    a person's decision, never a fix task), else `other` (not measured, unsafe path, no scope declared, a UI criterion
    without an e2e test, a judge reply that was discarded...)."""
    if _SCOPE_HOLD.match(text):
        return "scope"
    if text.startswith(JUDGE_VIEW_PREFIX) or text == LEGACY_LENGTH_HOLD or _SPEC_VIEW_HOLD.match(text):
        return "judge_view"
    return "coverage" if text.startswith(_COVERAGE_HOLD) else "other"


def hold_subjects(text: str) -> tuple[str, ...]:
    """The files (scope), `path::qualname` functions (coverage) or files the judge did not see (judge view) a hold
    names; none for another kind."""
    kind = hold_kind(text)
    if kind == "scope":
        return (_BACKTICKED.findall(text)[0],)
    return tuple(_BACKTICKED.findall(text)) if kind in ("coverage", "judge_view") else ()


def _names(subject: str) -> tuple[str, str | None]:
    path, _, qualname = subject.partition("::")
    return path, (qualname.rsplit(".", 1)[-1] if qualname and not qualname.startswith("<") else None)


MIN_FUNCTION_NAME = 4  # a shorter name (`get`, `run`) is in too many sentences to say a finding is about it


def _names_path(path: str, text: str) -> bool:
    """`path` as a whole path in `text`: not `app.py` inside `webapp.py` or `app.pyx`; a leading `./` is allowed."""
    return re.search(rf"(?:(?<=\./)|(?<![\w./-])){re.escape(path)}(?![\w/-]|\.\w)", text) is not None


def _is_about(subject: str, text: str) -> bool:
    """A subject with a function name (`path::qualname`) is named by that name, as a whole word of at least
    MIN_FUNCTION_NAME characters: another function of the same file is another subject. A subject without one (a
    scope hold's file, a coverage hold's `path::<module>`, whose module-level code has no name) is named by its path."""
    path, name = _names(subject)
    if name is None:
        return _names_path(path, text)
    word = rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])"
    return len(name) >= MIN_FUNCTION_NAME and re.search(word, text) is not None


def subsumed_findings(findings: Sequence[Finding], holds: Sequence[str]) -> dict[str, str]:
    """finding id -> the hold it is about. A blocking judge finding is about a hold when its title, detail or suggested
    fix names one of the hold's subjects (`_is_about`): the file of a scope hold, a function of a coverage hold, or the
    file of a coverage hold that names its module-level code. The first hold in the given order wins. Deterministic and
    auditable: nothing here asks a model."""
    found: dict[str, str] = {}
    for f in findings:
        if f.source != "judge" or not f.blocking:
            continue
        text = f"{f.title}\n{f.detail}\n{f.suggested_fix}"
        hold = next((h for h in holds if any(_is_about(s, text) for s in hold_subjects(h))), None)
        if hold is not None:
            found[f.id] = hold
    return found


def hold_covers(events: Iterable[LedgerEvent]) -> dict[str, frozenset[str]]:
    """question id -> the judge findings a hold's question quoted (`question.raised{kind: verdict, covers}`): the only
    findings its answer settles. A question raised without `covers` quoted none."""
    return {
        str(e.data.get("id")): frozenset(str(c) for c in e.data["covers"])
        for e in events
        if e.type == "question.raised" and e.data.get("kind") == "verdict" and e.data.get("covers")
    }


def _quote(finding: Finding) -> str:
    fix = f" Suggested fix: {_flat(finding.suggested_fix, 300)}" if finding.suggested_fix else ""
    return f"The judge's finding on the same subject: {_flat(finding.title, 160)}: {_flat(finding.detail, 400)}.{fix}"


COVERAGE_FIX = "Add tests that run the changed code the hold names"  # a rejected coverage hold's finding starts so


def is_coverage_hold_finding(finding: Finding) -> bool:
    """A rejected coverage hold's finding (`_hold_finding`): its id is the hold's, and its detail starts with the
    harness's own sentence, never with a human's text (the reason is appended after it)."""
    deterministic = finding.id.startswith("H-") and finding.source == "deterministic"
    return deterministic and finding.detail.startswith(COVERAGE_FIX)


WHEN_THEN = re.compile(r"\bWHEN\b(?P<when>.+?)\bTHEN\b(?P<then>.+)", re.S)


def ends_with_scenario(reason: str) -> bool:
    """A reason with a `WHEN ... THEN ...` sentence (both words in capitals, text between and after them): the
    scenario a fix unit pins (`fixunit.when_then` builds it from the same pattern)."""
    match = WHEN_THEN.search(reason)
    return bool(match and match.group("when").strip() and match.group("then").strip())


def _hold_finding(hold: str, verdict: HumanVerdict, quoted: Sequence[Finding]) -> Finding:
    """What a rejected hold becomes. A hold of the two kinds a task can be derived from, rejected with a reason, is a
    deterministic major finding: the reject applies the `fail` policy of the check that raised the hold (the finding a
    `fail` mode would have raised), so the fix unit plans a chore for it (D8). Any other reject has nothing to act on:
    it is the human's finding, which the planner lists as not converted, and the round escalates (the answer of a
    verdict that cannot be turned into a fix, never a new question). A hold of any other kind, rejected with a reason
    that holds a `WHEN ... THEN ...` sentence, is a behaviour finding like a rejected judge finding with no criterion:
    the scenario is the task. A hold on the judge's view (`judge_view`) is always the human's finding, whatever the
    reason says (L4-VER-044)."""
    kind, subjects = hold_kind(hold), hold_subjects(hold)
    reason = verdict.reason.strip()
    context = " ".join(_quote(f) for f in quoted)
    if kind == "judge_view":  # a fix unit cannot shrink the diff: whatever the reason says, no task comes from it
        what = (
            "A fix unit cannot shrink the diff: split the change, or accept the hold once a person checked the files."
        )
        detail = f"{what} Hold: {_flat(hold, 400)} {context}".rstrip() + rejection_note(verdict)
        return Finding(Severity.MAJOR, JUDGE_VIEW_REJECTED_TITLE, detail, "human", id=hold_id(hold))
    if kind == "scope" and reason:
        what = (
            f"Remove or relocate the change to `{subjects[0]}`: the spec does not name its module. Revert it from "
            "this change, or move it to its own change."
        )
        title = f"Out-of-scope change: {subjects[0]}"
    elif kind == "coverage" and reason:
        named = ", ".join(f"`{s}`" for s in subjects[:8]) + (
            f" (+{len(subjects) - 8} more)" if len(subjects) > 8 else ""
        )
        what = f"{COVERAGE_FIX}: {named}."
        title = "Changed code that no test runs"
    else:
        what, title = (
            "A hold the human rejected without a fix the harness can derive."
            if not ends_with_scenario(reason)
            else "Change the behaviour the hold names as the human's reason says; the reason ends with the scenario "
            "to pin.",
            f"Rejected hold: {_flat(hold, 90)}",
        )
    detail = f"{what} Hold: {_flat(hold, 400)} {context}".rstrip() + rejection_note(verdict)
    usable = bool(reason) and (kind != "other" or ends_with_scenario(reason))
    return Finding(Severity.MAJOR, title, detail, "deterministic" if usable else "human", id=hold_id(hold))


def settle_holds(
    findings: Sequence[Finding],
    holds: Sequence[str],
    effective: Mapping[str, HumanVerdict],
    covers: Mapping[str, Collection[str]] | None = None,
) -> list[Finding]:
    """The findings of a round once its holds are answered (L4-VER-013): a rejected hold is added as a blocking finding
    (`_hold_finding`), and a judge finding that a hold subsumes (`subsumed_findings`), that has no answer of its own and
    that the answered question quoted (`covers`: question id -> finding ids, `hold_covers`) is settled by the hold's
    answer: it becomes a minor, noted with the hold and the human's reason. The rejected hold's finding quotes it, so
    the fix unit has one task for the subject, not two. A finding the question did not quote (a later round judged
    afresh raised it, while the accept of a hold with the same text stays in force) is left as it is, and asked on its
    own."""
    subsumed = subsumed_findings(findings, holds)
    covers = covers or {}

    def settled_by(f: Finding) -> tuple[str, HumanVerdict] | None:
        hold = subsumed.get(f.id)
        verdict = effective.get(hold_id(hold)) if hold is not None else None
        if hold is None or verdict is None or f.id in effective or f.id not in covers.get(verdict.question, ()):
            return None
        return hold, verdict

    out = []
    for f in findings:
        if (settled := settled_by(f)) is None:
            out.append(f)
            continue
        hold, verdict = settled
        why = f": {verdict.reason}" if verdict.reason else ""
        note = f"settled with hold {hold_id(hold)}, {verdict.decision}ed by {verdict.label}{why}"
        out.append(dataclasses.replace(f, severity=Severity.MINOR, detail=f"{f.detail} ({note})"))
    known = {f.id for f in out}
    for hold in holds:
        verdict = effective.get(hold_id(hold))
        if verdict is not None and verdict.decision == "reject" and hold_id(hold) not in known:
            quoted = [f for f in findings if (settled := settled_by(f)) is not None and settled[0] == hold]
            out.append(_hold_finding(hold, verdict, quoted))
    return out


def hold_sha256(hold: str, views: Mapping[str, Mapping[str, Any]] | None = None) -> str:
    """The hash a person's accept of `hold` is bound to: the content hash of a `judge view:` hold (`HoldView.sha`), else
    the hash of the hold's id as before."""
    view = (views or {}).get(hold)
    return str(view["sha"]) if view else finding_sha256(hold_id(hold))


def finding_sha256(finding_id: str) -> str:
    return hashlib.sha256(finding_id.encode("utf-8")).hexdigest()


def parse_answer(text: str) -> tuple[str, str] | None:
    """(decision, reason) when the first word is `accept` or `reject`; None for anything else."""
    match = _DECISION.match(text)
    return (match.group(1).lower(), match.group(2).strip()) if match else None


def target_of(question: Question) -> str | None:
    match = _TARGET.search(question.title)
    return match.group(1) if match else None


def _verdict_questions(file: QuestionsFile | None) -> list[Question]:
    return [q for q in file.questions if q.kind is QuestionKind.VERDICT] if file else []


def legacy_round(state: UnitState, file: QuestionsFile | None) -> int | None:
    """The round of a unit that waits for a human since an older harness: it is `awaiting_human`, its last round ended
    NEEDS_HUMAN, no verdict question was ever raised for that round (the ledger names none) and none is waiting in
    `questions.md`. Nobody can answer a question that does not exist, so the next run raises them (L4-VER-013)."""
    last = state.last_verdict
    if state.phase != "awaiting_human" or last is None or last.verdict != "NEEDS_HUMAN":
        return None
    if state.verdict_asked_round is not None and state.verdict_asked_round >= last.round:
        return None
    return None if verdict_status(file, state.verdicts_consumed).any else last.round


@dataclass(frozen=True)
class VerdictQuestions:
    open: tuple[str, ...] = ()  # asked, not answered
    ready: tuple[str, ...] = ()  # answered with `accept` or `reject`, not yet consumed
    invalid: tuple[str, ...] = ()  # answered, but the first word is neither
    dismissed: tuple[str, ...] = ()  # Status `dismissed`: refused, read as open (L4-OPS-009); also in `open`

    @property
    def any(self) -> bool:
        return bool(self.open or self.ready or self.invalid)


def verdict_status(file: QuestionsFile | None, consumed: Collection[str] = ()) -> VerdictQuestions:
    """The verdict questions that still matter: consumed and superseded ones are left out. A verdict question cannot be
    dismissed (the harness needs an accept or a reject): a `dismissed` one reads as open and is named in `dismissed`."""
    open_, ready, invalid, dismissed = [], [], [], []
    for q in _verdict_questions(file):
        if q.id in consumed or q.status is QuestionStatus.SUPERSEDED:
            continue
        if q.status is QuestionStatus.DISMISSED:
            open_.append(q.id)
            dismissed.append(q.id)
            continue
        answer = effective_answer(q) if is_answered(q) else None
        if answer is None:
            open_.append(q.id)
        elif parse_answer(answer) is None:
            invalid.append(q.id)
        else:
            ready.append(q.id)
    return VerdictQuestions(tuple(open_), tuple(ready), tuple(invalid), tuple(dismissed))


def _raised(events: Iterable[LedgerEvent]) -> dict[str, Mapping[str, Any]]:
    return {
        str(e.data["id"]): e.data for e in events if e.type == "question.raised" and e.data.get("kind") == "verdict"
    }


def consume_verdicts(
    file: QuestionsFile | None,
    events: Sequence[LedgerEvent],
    ledger: EventSink,
    criteria: Sequence[Criterion],
    actor_of: Callable[[Question], Actor] | None = None,
) -> list[str]:
    """Record `human.verdict` for every validly answered verdict question whose answer is new (or changed since it was
    recorded), and return the question ids it recorded. The text hash is the one the question was raised on; a question
    the ledger does not know is judged on the criterion's text now. `by` (and `marker`, `profile`, `model`) is the real
    actor of the answer (`actor_of`, L4-QMD-009); a caller that passes none records a person's, as every ledger before
    0.4.18 did."""
    raised = _raised(events)
    done = {str(e.data.get("question")): e.data.get("answer_sha256") for e in events if e.type == "human.verdict"}
    current = {c.id: text_sha256(c) for c in criteria}
    recorded = []
    for q in _verdict_questions(file):
        answer = effective_answer(q) if is_answered(q) else None
        parsed = parse_answer(answer) if answer is not None else None
        if answer is None or parsed is None:
            continue
        digest = hashlib.sha256(answer.encode("utf-8")).hexdigest()
        if done.get(q.id) == digest:
            continue
        known = raised.get(q.id)
        if known is None:  # a question the harness never raised is not one a human answered
            continue
        target = str(known.get("target") or target_of(q) or "")
        if not target:
            continue
        sha = str(known.get("text_sha256") or current.get(target) or finding_sha256(target))
        actor = actor_of(q) if actor_of is not None else Actor("human")
        ledger.append(
            "human.verdict", question=q.id, target=target, decision=parsed[0], by=actor.by, reason=parsed[1][:1000],
            text_sha256=sha, answer_sha256=digest, **actor.fields(),
        )  # fmt: skip
        recorded.append(q.id)
    return recorded


def effective_verdicts(events: Sequence[LedgerEvent], current: Mapping[str, str]) -> dict[str, HumanVerdict]:
    """target -> the verdict that applies now. `current`: target -> its text hash today (a criterion's text, or a
    finding's id hash); a target not in it is gone. The latest `human.verdict` per target wins. A `reject` is consumed
    by the fix unit that took it (its question in `fix.spawned.consumed`; a feedback-only fix unit lists there the
    human rejects its round could not convert, L4-VER-016). A feedback-only spawn written before that list existed
    (0.4.5 and older: no `lists_unconverted`) consumes every reject recorded before it: such a spawn happens only when
    no finding of its round could be converted, so the rejects in force were human ones, and the feedback is their
    concrete form."""
    voided = {str(e.data.get("question")) for e in events if e.type == "human.void"}
    consumed = {str(q) for e in events if e.type == "fix.spawned" for q in e.data.get("consumed") or []}
    last_feedback_spawn = max(
        (
            i
            for i, e in enumerate(events)
            if e.type == "fix.spawned"
            and e.data.get("feedback_only") is True
            and e.data.get("lists_unconverted") is not True
        ),
        default=-1,
    )
    latest: dict[str, tuple[int, HumanVerdict]] = {}
    for position, e in enumerate(events):
        if e.type != "human.verdict":
            continue
        d = e.data
        decision = d.get("decision")
        if decision not in ("accept", "reject"):
            continue
        latest[str(d.get("target"))] = (
            position,
            HumanVerdict(
                str(d.get("question")),
                str(d.get("target")),
                decision,
                str(d.get("by", "human")),
                str(d.get("reason", "")),
                str(d.get("text_sha256", "")),
                str(d.get("marker") or ""),
                str(d.get("model") or ""),
                str(d.get("cli") or ""),
            ),  # fmt: skip
        )
    keep = {}
    for target, (position, verdict) in latest.items():
        if verdict.decision == "reject" and (verdict.question in consumed or position < last_feedback_spawn):
            continue
        if verdict.decision == "accept" and (verdict.question in voided or current.get(target) != verdict.text_sha256):
            continue
        keep[target] = verdict
    return keep


def regressions(effective: Mapping[str, HumanVerdict], trace: Sequence[CriterionEvidence]) -> list[HumanVerdict]:
    """The accepted verdicts of criteria whose tracing evidence fails now: they are void for good (D3)."""
    failing = {t.criterion for t in trace if t.state == "fail" or any(x.status in ("failed", "error") for x in t.tests)}
    return [v for target, v in effective.items() if v.decision == "accept" and target in failing]


def carry_rejects(
    findings: Sequence[Finding],
    effective: Mapping[str, HumanVerdict],
    events: Sequence[LedgerEvent],
    asked: Callable[[int, str], Finding | None],
) -> tuple[list[Finding], dict[str, HumanVerdict]]:
    """A `reject` of a judge finding that this round does not hold is not dropped (L4-VER-013: no dispute loops). A
    round judged afresh (no reuse: an older harness's record, or a subject the human moved, such as a merge of the base)
    can raise the same finding under another id, since the id hashes title and criterion and the judge tied it to a
    criterion; or it can rename it, or not raise it. The reject then moves to this round's judge finding of the same
    title that has no verdict of its own; else the finding the question asked about comes back from its round's stored
    record (`asked(round, target)`). Either way it aggregates as the human's finding: a FAIL and a fix unit."""
    out, kept = list(findings), dict(effective)
    rounds = {
        str(e.data.get("id")): e.data.get("round")
        for e in events
        if e.type == "question.raised" and e.data.get("kind") == QuestionKind.VERDICT.value
    }
    for target, verdict in effective.items():
        if verdict.decision != "reject" or not target.startswith("F-") or target in {f.id for f in out}:
            continue
        round_no = rounds.get(verdict.question)
        origin = asked(round_no, target) if isinstance(round_no, int) else None
        if origin is None or origin.source != "judge" or not origin.blocking:
            continue  # nothing to carry: the question's round left no readable record of a judge-only blocker
        twin = next(
            (f for f in out if f.source == "judge" and f.blocking and f.title == origin.title and f.id not in kept),
            None,
        )
        if twin is not None:
            kept[twin.id] = dataclasses.replace(verdict, target=twin.id)
        else:
            out.append(origin)
    return out, kept


def apply_finding_verdicts(findings: Sequence[Finding], effective: Mapping[str, HumanVerdict]) -> list[Finding]:
    """An accepted judge-only finding is waived (listed as minor), a rejected one becomes the human's finding and so
    a deterministic FAIL (L4-VER-013)."""
    out = []
    for f in findings:
        verdict = effective.get(f.id) if f.source == "judge" and f.blocking else None
        if verdict is None:
            out.append(f)
        elif verdict.decision == "accept":
            note = f"waived by {verdict.label}" + (f": {verdict.reason}" if verdict.reason else "")
            out.append(dataclasses.replace(f, severity=Severity.MINOR, detail=f"{f.detail} ({note})"))
        else:
            out.append(dataclasses.replace(f, source="human", detail=f"{f.detail}{rejection_note(verdict)}"))
    return out


def rejection_note(verdict: HumanVerdict) -> str:
    """What `apply_finding_verdicts` appends to a rejected finding's detail."""
    reason = f" ({verdict.reason})" if verdict.reason else ""
    return f" [rejected by {verdict.label}{reason}]"


# --- asking -----------------------------------------------------------------------------------------------------------


def _flat(text: object, limit: int = MAX_SUMMARY_CHARS) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= limit else one[: limit - 3] + "..."


def _criterion_question(
    outcome: CriterionOutcome, criterion: Criterion, evidence: CriterionEvidence | None, round_no: int
) -> NewQuestion:
    tests = (
        "; ".join(
            f"{t.id} ({t.status}, {t.proof}{', ' + t.note if t.note else ''}{'' if t.adequate else ', inadequate'})"
            for t in evidence.tests
        )
        if evidence and evidence.tests
        else "none"
    )
    ignored = "; ".join(f"{t} ({why})" for t, why in evidence.ignored) if evidence and evidence.ignored else "none"
    context = "\n".join(
        [
            f"Criterion {criterion.id} ({criterion.alias}) is {outcome.result.replace('_', ' ')} "
            f"after round {round_no}.",
            "",
            "Scenario:",
            criterion.text,
            "",
            f"Why: {outcome.reason}",
            f"Judge: {outcome.judge or 'no verdict'}",
            f"Tracing tests: {tests}",
            f"Ignored tests: {ignored}",
            "",
            "Answer `accept` if the criterion is satisfied as it stands, or `reject` and say why.",
            "If the code is right and the scenarios are incomplete, `reject` with a scenario: WHEN ... THEN ...",
        ]
    )
    return NewQuestion(
        f"Criterion {criterion.id} ({criterion.alias}): accept as satisfied?", QuestionKind.VERDICT, (), context,
        f"round {round_no}, verifier", ("accept", "reject: <reason>, or WHEN ... THEN ... for a spec gap"),
        (criterion,),
    )  # fmt: skip


def _finding_question(finding: Finding, round_no: int) -> NewQuestion:
    where = f" (criterion {finding.criterion})" if finding.criterion else ""
    gap = " It reports behaviour that no scenario pins down." if finding.spec_gap else ""
    fix = f"\nSuggested fix: {_flat(finding.suggested_fix)}" if finding.suggested_fix else ""
    context = "\n".join(
        [
            f"The judge raised a {finding.severity.value} finding in round {round_no}, and no deterministic check "
            f"confirms it{where}.{gap}",
            "",
            f"Title: {_flat(finding.title, 200)}",
            f"Detail: {_flat(finding.detail)}{fix}",
            "",
            "Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.",
        ]
    )
    return NewQuestion(
        f"Finding {finding.id}: {_flat(finding.title, 120)}", QuestionKind.VERDICT, (), context,
        f"round {round_no}, verifier", ("accept", "reject: <reason>"),
    )  # fmt: skip


def _hold_question(hold: str, round_no: int, quoted: Sequence[Finding] = (), paths: Sequence[str] = ()) -> NewQuestion:
    judged = [
        line
        for f in quoted
        for line in (
            "",
            f"The judge also raised a {f.severity.value} finding on the same subject, {f.id}:",
            f"Title: {_flat(f.title, 200)}",
            f"Detail: {_flat(f.detail)}" + (f"\nSuggested fix: {_flat(f.suggested_fix)}" if f.suggested_fix else ""),
        )
    ]
    kind = hold_kind(hold)
    if kind == "judge_view":
        answer = (
            "The judge could not see all of the diff, so it could not judge the files this hold names. Answer "
            "`accept` if you checked those files yourself and the unit can go on as it stands. A fix unit cannot "
            "shrink the diff, so `reject` stops the unit (escalated with judge_view_rejected): then split the change "
            "into smaller units."
        )
    else:
        answer = "Answer `accept` if the unit can go on as it stands, " + (
            "or `reject` and say why: a rejected hold is fixed by a fix unit."
            if kind != "other"
            else "or `reject` and say why; end the reason with a sentence WHEN ... THEN ... so that a fix unit "
            "can be made."
        )
    listed = []
    if paths:
        shown = [f"- {p}" for p in paths[:QUESTION_MAX_PATHS]]
        more = len(paths) - QUESTION_MAX_PATHS
        tail = [f"- and {more} more unseen files: see verdict.json"] if more > 0 else []
        listed = ["", f"The files the judge did not see ({len(paths)}):", *shown, *tail]
    context = "\n".join(
        [
            f"After round {round_no} the verifier cannot decide on its own: {_flat(hold)}",
            *listed,
            *judged,
            "",
            answer + (" One answer settles both the hold and the judge's finding." if judged else ""),
        ]
    )
    return NewQuestion(
        f"Hold {hold_id(hold)}: {_flat(hold, 120)}", QuestionKind.VERDICT, (), context,
        f"round {round_no}, verifier", ("accept", "reject: <reason>"),
    )  # fmt: skip


def raise_verdict_questions(
    unit_dir: Path,
    unit_name: str,
    *,
    outcomes: Sequence[CriterionOutcome],
    criteria: Sequence[Criterion],
    trace: Sequence[CriterionEvidence],
    findings: Sequence[Finding],
    existing: QuestionsFile | None,
    consumed: Collection[str],
    ledger: EventSink,
    round_no: int,
    redactor: Redactor,
    holds: Sequence[str] = (),
    covers: Mapping[str, Collection[str]] | None = None,
    hold_views: Mapping[str, Mapping[str, Any]] | None = None,
    judges: Sequence[Mapping[str, Any]] | None = None,
) -> list[str]:
    """One question per criterion that is `needs_human` or `disputed`, per judge-only blocker or major finding and
    per hold,
    except where a verdict question for the same target is still waiting (open or invalidly answered). Returns the new
    question ids; each gets a `question.raised{kind: verdict}` so the mirror sets `l4:needs-answers`. `judges` (from
    `round_judges`) is recorded on each, so the delegate is never a mind that judged the round (L4-DLG-002)."""
    status = verdict_status(existing, consumed)
    unsettled = {*status.open, *status.invalid, *status.ready}
    waiting_q = {t: q.id for q in _verdict_questions(existing) if (t := target_of(q)) and q.id in unsettled}
    waiting = set(waiting_q)
    covers = covers or {}
    # asked as part of the hold's question, not on their own: the question raised now quotes it, or the hold's
    # waiting question already did (`covers`); a waiting question cannot quote a finding it never saw: asked alone
    subsumed = {
        f: h
        for f, h in subsumed_findings(findings, holds).items()
        if (q := waiting_q.get(hold_id(h))) is None or f in covers.get(q, ())
    }
    by_id = {c.id: c for c in criteria}
    evidence = {e.criterion: e for e in trace}
    batch: list[NewQuestion] = []
    targets: list[tuple[str, str, list[str]]] = []  # (target, text hash, the findings a hold's question quotes)
    for outcome in outcomes:
        if outcome.result in ("needs_human", "disputed") and outcome.id in by_id and outcome.id not in waiting:
            batch.append(_criterion_question(outcome, by_id[outcome.id], evidence.get(outcome.id), round_no))
            targets.append((outcome.id, text_sha256(by_id[outcome.id]), []))
    for finding in findings:
        if finding.source == "judge" and finding.blocking and finding.id not in waiting and finding.id not in subsumed:
            batch.append(_finding_question(finding, round_no))
            targets.append((finding.id, finding_sha256(finding.id), []))
    for hold in holds:
        if hold_id(hold) not in waiting:
            quoted = [f for f in findings if subsumed.get(f.id) == hold]
            view = (hold_views or {}).get(hold)
            batch.append(_hold_question(hold, round_no, quoted, tuple(view["paths"]) if view else ()))
            targets.append((hold_id(hold), hold_sha256(hold, hold_views), [f.id for f in quoted]))
    ids = raise_questions(unit_dir, unit_name, batch, redactor=redactor)
    titles = question_titles(unit_dir) if ids else {}
    for qid, (target, sha, quoted_ids) in zip(ids, targets, strict=True):
        ledger.append(
            "question.raised", id=qid, kind="verdict", source="verifier", target=target, text_sha256=sha,
            round=round_no, title=titles.get(qid, ""), **({"covers": quoted_ids} if quoted_ids else {}),
            **({"judges": [dict(j) for j in judges]} if judges is not None else {}),
        )  # fmt: skip
    return ids


def round_judges(events: Iterable[LedgerEvent], round_no: int, cfg: L4Config) -> list[dict[str, Any]]:
    """Who judged round `round_no`: each distinct `{profile, model}` of its `verify.judge` events, a panel's parts and a
    fallback judge included. A round that reused an earlier round's judge made no call of its own: the latest earlier
    round that judged is the one whose mind decided it. The model is the one that served the call, else the profile's
    configured model, else None."""
    calls = [e for e in events if e.type == "verify.judge" and isinstance(e.data.get("profile"), str)]
    rounds = [r for e in calls if isinstance(r := e.data.get("round"), int) and r <= round_no]
    out: list[dict[str, Any]] = []
    for e in calls:
        if not rounds or e.data.get("round") != max(rounds):
            continue
        profile = e.data["profile"]
        configured = cfg.profiles.get(profile)
        entry = {"profile": profile, "model": e.data.get("model") or (configured.model if configured else None)}
        if entry not in out:
            out.append(entry)
    return out


def verdict_targets(
    outcomes: Sequence[CriterionOutcome], findings: Sequence[Finding], holds: Sequence[str] = ()
) -> list[str]:
    """The targets a NEEDS_HUMAN round asks a person about: the criteria that are `needs_human` or `disputed`, the
    judge-only blocking findings and the holds (the ones `raise_verdict_questions` makes questions of)."""
    return [
        *(o.id for o in outcomes if o.result in ("needs_human", "disputed")),
        *(f.id for f in findings if f.source == "judge" and f.blocking),
        *(hold_id(h) for h in holds),
    ]


def supersede_stale_verdicts(
    unit_dir: Path,
    *,
    existing: QuestionsFile | None,
    consumed: Collection[str],
    events: Iterable[LedgerEvent],
    ledger: EventSink,
    round_no: int,
    current: Collection[str] = (),
) -> list[str]:
    """A verification round ends (any verdict): every verdict question of an EARLIER round that is still `open`
    (asked and not answered, or a draft under `open`) becomes `superseded by round <n>` (L4-OPS-014: a person fixed
    the spec instead of answering, and this round judged the new subject). `question.superseded{ids, round}` takes the
    ids out of `questions.open`, so `l4:needs-answers` and the "Waiting for you" note go. Untouched: an answered or
    consumed question (its answer was used), a question of this round, a `dismissed` one, a question the harness never
    raised, any non-verdict question, and a question whose target is in `current` (this round asks it again, and
    `raise_verdict_questions` kept the waiting one). Returns the ids."""
    if existing is None:
        return []
    raised = _raised(events)
    ids = [
        q.id
        for q in _verdict_questions(existing)
        if q.status is QuestionStatus.OPEN
        and q.status_value is not None
        and q.id not in consumed
        and isinstance(round_ := raised.get(q.id, {}).get("round"), int)
        and not isinstance(round_, bool)
        and round_ < round_no
        and target_of(q) not in current
    ]
    if not ids:
        return []
    file = existing
    for qid in ids:
        file = file.supersede_by_round(qid, round_no)
    file.save(unit_dir / QUESTIONS_FILENAME)
    ledger.append("question.superseded", ids=ids, round=round_no)
    return ids
