"""From a round's findings to the content of a fix unit (SPEC L4-VER-006, M1.3 lines 32 and 37, decisions D6 and D8).

`plan_fix_unit` is pure: it decides which findings become tasks (at most `MAX_FIX_TASKS`), which behaviours a regression
scenario pins, and which `reject`ed verdict questions the fix unit consumes. Writing the files is the provider's job
(`create_fix_unit`). The spec writer is deterministic: `roles.spec_writer` is unused.

On a FAIL the convertible findings are the deterministic (or human-rejected) blockers and majors, the `fail` criteria
and the rejected targets. On a PASS with `verifier.fix_minor_findings` they are the minor findings that cite a
criterion or carry a scenario. A spec gap becomes an ADDED scenario under `<requirement> — regression <n>`; its
`WHEN ... THEN ...` comes from the human's `reject` reason, else from the judge's `suggested_fix`, and a finding with
neither is listed and not converted. A finding without a criterion becomes a `[chore]` task (D8).

A feedback finding (source `"feedback"`, L4-FBK-005) is one task of its own, by the kind of the item, and is never
dropped for lacking a criterion: `refactor` and `duplication` are chores that keep behaviour (marker `refactors`),
`tests` is the test chore, `config` and `behaviour` are red/green against the scenarios built from the item (D4) in an
ADDED requirement `<title> \N{EM DASH} feedback FB-NNN`. An item past `MAX_FIX_TASKS` waits for the next round
(`FixPlan.waiting`); it is neither taken nor "not converted".
"""

import dataclasses
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from l4.memory.curate import UI_GAP_TITLE
from l4.specs.base import MAX_DECISION_CHARS, Criterion, DeltaRequirement, DeltaScenario, Finding, SpecDelta
from l4.specs.feedback import FeedbackItem
from l4.verifier.feedback import FeedbackScan, feedback_findings
from l4.verifier.types import FeedbackRef, HumanVerdict, Severity, Verdict, VerifyResult
from l4.verifier.types import Finding as VerifierFinding
from l4.verifier.verdicts import WHEN_THEN, is_coverage_hold_finding, rejection_note

MAX_FIX_TASKS = 5
MAX_TITLE_CHARS = 100
MAX_REQUEST_CHARS = 1200  # a feedback item's text, whole up to this (L4-FBK-005)
FEEDBACK_REQUIREMENT = "\N{EM DASH} feedback"
REFACTOR_KINDS = ("refactor", "duplication")
REGRESSION = "\N{EM DASH} regression"
_SUFFIX = re.compile(r"\s+\N{EM DASH}\s+regression\s+\d+\s*$")
_SEVERITY_ORDER = {Severity.BLOCKER: 0, Severity.MAJOR: 1, Severity.MINOR: 2}
# the title of a finding about tests: the word as a noun of its own, not `test-mode` or `latest` (M1.13, W-C1)
_ABOUT_TESTS = re.compile(r"(?<![\w-])(?:tests?|assertions?|mocks?|fixtures?)(?![\w-])", re.I)


@dataclass(frozen=True)
class FixPlan:
    groups: list[Finding]  # one task each
    delta: SpecDelta | None
    consumed: list[str]  # the verdict questions (rejects) this fix unit answers
    not_converted: list[str] = field(default_factory=list)  # "<id>: why", for the sticky note and the report
    taken: list[FeedbackRef] = field(default_factory=list)  # the feedback items that have a task in this fix unit
    waiting: list[str] = field(default_factory=list)  # FB ids that did not fit `MAX_FIX_TASKS`: next round

    @property
    def finding_ids(self) -> list[str]:
        return [i for g in self.groups for i in g.ids]

    @property
    def feedback_only(self) -> bool:
        """Every task answers a feedback item: a feedback fix unit, counted apart from `max_fix_rounds` (L4-FBK-006)."""
        return bool(self.groups) and all(g.item for g in self.groups)


@dataclass
class _Candidate:
    ids: list[str]
    title: str
    detail: str
    severity: Severity
    criterion: str | None
    # (finding id, finding title, `WHEN ... THEN ...` as one text): every finding of the criterion keeps its own
    # scenario, one per behaviour, in the one task of that criterion; a text two findings share is pinned once
    scenarios: list[tuple[str, str, str]] = field(default_factory=list)
    synthetic: bool = False  # made for a failing criterion no finding explains: its title is no name for a scenario
    consumed: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)  # "Q-002: <the human's reject reason>", one per reject
    decided_by: str = "human"
    tests: bool = False  # the finding is a rejected coverage hold: its task adds tests
    only_tests: bool = True  # every finding of the task is about the tests of a criterion that is satisfied (W-C1)
    feedback: FeedbackRef | None = None  # the task answers this item, and no other finding


def _about_satisfied_tests(
    f: VerifierFinding, criterion: str | None, scenario: str | None, satisfied: set[str]
) -> bool:
    """A judge's or a human's finding whose title speaks of tests, on a criterion the round found satisfied, with no
    regression scenario to pin: what is wrong is the test, not the code. Every other finding keeps its red/green
    task."""
    return (
        criterion is not None and criterion in satisfied and scenario is None
        and f.source in ("judge", "human") and _ABOUT_TESTS.search(f.title) is not None
    )  # fmt: skip


def _fit_detail(detail: str, decisions: Sequence[str], by: str, limit: int) -> str:
    """The human's decisions first, then the findings' details, cut to `limit`. The decision is never the part that is
    cut (up to MAX_DECISION_CHARS), the finding's own detail is: a decision cut off on its way into the fix unit (live
    add-vat, job 5487: "[reject...") leaves the implementer a finding that reads as an open question it must not
    decide."""
    if not decisions:
        return _flat(detail, limit)
    share = max(MAX_DECISION_CHARS // len(decisions), 100)  # together they stay under what the proposal keeps
    head = f"Decided by {by} in {'; '.join(_flat(d, share) for d in decisions)}. "
    return head + _flat(detail, max(limit - len(head), 80))


def when_then(text: str) -> str | None:
    """`- **WHEN** x\\n- **THEN** y` from a sentence that has both words in capitals and something between them."""
    match = WHEN_THEN.search(text)
    if not match:
        return None
    when, then = " ".join(match.group("when").split()), " ".join(match.group("then").split())
    return f"- **WHEN** {when}\n- **THEN** {then}" if when and then else None


def _when(scenario: str) -> str:
    """The WHEN clause of a scenario text: what a human would call it."""
    return scenario.splitlines()[0].removeprefix("- **WHEN** ")


def _flat(text: str, limit: int) -> str:
    one = " ".join(text.split())
    return one if len(one) <= limit else one[: limit - 3].rstrip() + "..."


def _synthetic(criterion: Criterion, reason: str) -> VerifierFinding:
    """A `fail` criterion that no finding explains still needs an id to cite."""
    return VerifierFinding(Severity.MAJOR, f"Criterion {criterion.alias} fails", reason, "deterministic", criterion.id)


def _candidates(
    family: Sequence[Criterion], result: VerifyResult, rejects: dict[str, HumanVerdict], fix_minor: bool
) -> tuple[list[_Candidate], list[str], list[str]]:
    by_id = {c.id: c for c in family}
    skipped: list[str] = []
    unconverted: list[str] = []  # the questions of the rejects whose human finding no task can be derived from
    picked: list[tuple[VerifierFinding, bool]] = []  # (finding, it is a minor on a PASS)
    synthetic: list[VerifierFinding] = []
    # satisfied: judged so, or accepted by a human, so the code is right (a finding about its tests asks for tests)
    satisfied = {o.id for o in result.criteria if o.result == "pass"}
    if result.verdict is Verdict.FAIL:
        picked += [
            (f, False) for f in result.findings if f.blocking and f.source in ("deterministic", "human", "feedback")
        ]  # fmt: skip
        cited = {f.criterion for f, _ in picked if f.criterion}
        synthetic = [
            _synthetic(by_id[o.id], o.reason)
            for o in result.criteria
            if o.result == "fail" and o.id in by_id and o.id not in cited
        ]
        picked += [(f, False) for f in synthetic]
    elif result.verdict is Verdict.PASS and fix_minor:
        # a UI gap that an accepted generated test closed is done: a fix unit would leave no PASS to curate its lesson
        closed = {o.criterion for o in result.generated if o.accepted}
        picked += [
            (f, True) for f in result.findings
            if f.severity is Severity.MINOR and not (f.title == UI_GAP_TITLE and f.criterion in closed)
        ]  # fmt: skip
    grouped: dict[str, _Candidate] = {}
    for f, minor in picked:
        if f.feedback is not None:  # one task per item, never shared and never dropped (L4-FBK-005)
            grouped[f.id] = _feedback_candidate(f, f.feedback)
            continue
        criterion = f.criterion if f.criterion in by_id else None
        verdict = rejects.get(f.id) or (rejects.get(criterion) if criterion else None)
        scenario = when_then(verdict.reason) if verdict else None
        if scenario is None and f.spec_gap:
            scenario = when_then(f.suggested_fix)
        if f.source == "human" and criterion is None and scenario is None:
            why = (
                "a rejected hold with no reason, or of a kind no fix can be derived from: the human decides it"
                if f.id.startswith("H-")
                else "rejected with no criterion and no WHEN ... THEN ...: answer again with a scenario"
            )
            skipped.append(f"{f.id}: {why}")
            if verdict is not None and verdict.question not in unconverted:
                unconverted.append(verdict.question)
            continue  # a chore runs without red, and only a deterministic finding may be exempted (D8)
        if minor and criterion is None and scenario is None:
            skipped.append(f"{f.id}: a minor finding with no criterion and no scenario")
            continue
        if minor and f.spec_gap and scenario is None:
            skipped.append(f"{f.id}: a spec gap with no WHEN ... THEN ... to pin (no reject reason, no suggested fix)")
            continue
        key = criterion or f.id
        detail = f.detail.removesuffix(rejection_note(verdict)) if verdict is not None else f.detail
        cand = grouped.get(key)
        if cand is None:
            cand = grouped[key] = _Candidate([], f.title, detail, f.severity, criterion, synthetic=f in synthetic)
        elif f.id not in cand.ids:
            cand.detail = f"{cand.detail} | {f.title}: {detail}" if detail else cand.detail
        cand.tests = cand.tests or is_coverage_hold_finding(f)
        # a finding about the tests of a criterion that is satisfied and asks for no new behaviour: no red test can
        # honestly fail, so the task adds tests (W-C1); one finding of another kind keeps the whole task red/green
        cand.only_tests = cand.only_tests and _about_satisfied_tests(f, criterion, scenario, satisfied)
        if verdict is not None:
            decision = f"{verdict.question}: {verdict.reason or 'rejected, no reason given'}"
            if decision not in cand.decisions:
                cand.decisions.append(decision)
                cand.decided_by = verdict.by
        if f.id not in cand.ids:
            cand.ids.append(f.id)
        cand.severity = min(cand.severity, f.severity, key=_SEVERITY_ORDER.__getitem__)
        if scenario is not None and scenario not in {text for _, _, text in cand.scenarios}:
            cand.scenarios.append((f.id, f.title, scenario))
        for target in (f.id, criterion):
            if target and (v := rejects.get(target)) and v.question not in cand.consumed:
                cand.consumed.append(v.question)
    return list(grouped.values()), skipped, unconverted


def feedback_scenarios(ref: FeedbackRef) -> list[str]:
    """The scenarios of a `config` or `behaviour` item (D4): the person's When/Then, else the two built from the
    variable and the first place. Other kinds need none."""
    if ref.kind == "behaviour":
        return [f"- **WHEN** {_flat(ref.when or '', 300)}\n- **THEN** {_flat(ref.then or '', 300)}"]
    if ref.kind != "config":
        return []
    env = ref.env or ""
    first = (
        f"- **WHEN** {_flat(ref.when, 300)}\n- **THEN** {_flat(ref.then or '', 300)}"
        if ref.when and ref.then
        else f"- **WHEN** the environment variable {env} is set\n- **THEN** the system SHALL use its value instead of "
        f"the value written at {ref.places[0] if ref.places else 'the place named in the request'}"
    )
    return [first, f"- **WHEN** {env} is not set\n- **THEN** the system SHALL CONTINUE TO behave as before this change"]


def _feedback_candidate(f: VerifierFinding, ref: FeedbackRef) -> _Candidate:
    scenarios = feedback_scenarios(ref)
    names = [_flat(ref.title, MAX_TITLE_CHARS)]
    if len(scenarios) == 2:
        names = [f"{ref.env} is set", f"{ref.env} is not set"]
    return _Candidate(
        [f.id], f.title, "", f.severity, None,
        scenarios=[(f.id, name, text) for name, text in zip(names, scenarios, strict=False)],
        tests=ref.kind == "tests", only_tests=False, feedback=ref,
    )  # fmt: skip


def request_of(ref: FeedbackRef) -> str:
    """ "Requested by <By> in FB-NNN (<kind>, <places>): <text>", the text whole up to 1,200 characters."""
    where = ", ".join((ref.kind, *ref.places))
    return f"Requested by {_flat(ref.by, 120)} in {ref.id} ({where}): {_flat(ref.text, MAX_REQUEST_CHARS)}"


def _requirement_for(
    cand: _Candidate, by_id: dict[str, Criterion], family: Sequence[Criterion], n: int
) -> tuple[str, str] | None:
    """(capability, requirement title) for a scenario. The cited criterion's requirement, else the parent's when it has
    exactly one; a requirement that is itself a regression of an earlier fix keeps the name of the original."""
    if cand.criterion:
        c = by_id[cand.criterion]
        return c.capability, f"{_SUFFIX.sub('', c.requirement)} {REGRESSION} {n}"
    originals = {(c.capability, _SUFFIX.sub("", c.requirement)) for c in family}
    if len(originals) == 1:
        capability, requirement = next(iter(originals))
        return capability, f"{requirement} {REGRESSION} {n}"
    return None


def _feedback_requirement(ref: FeedbackRef, family: Sequence[Criterion]) -> tuple[str, str]:
    """(capability, `<title> \N{EM DASH} feedback FB-NNN`): the parent's one capability, else the first by name, so
    that an item is never left without a home for its scenarios."""
    capabilities = sorted({c.capability for c in family})
    return (capabilities[0] if capabilities else "feedback"), f"{_flat(ref.title, 120)} {FEEDBACK_REQUIREMENT} {ref.id}"


def plan_fix_unit(
    family: Sequence[Criterion],
    result: VerifyResult,
    human: Sequence[HumanVerdict],
    *,
    ordinal: int,
    fix_minor: bool,
) -> FixPlan:
    """The tasks, the ADDED scenarios and the consumed rejects of fix unit `ordinal` (`<parent>-fix-<ordinal>`)."""
    rejects = {v.target: v for v in human if v.decision == "reject"}
    by_id = {c.id: c for c in family}
    candidates, skipped, unconverted = _candidates(family, result, rejects, fix_minor)
    candidates.sort(key=lambda c: _SEVERITY_ORDER[c.severity])  # stable: the report's order within a severity
    waiting: list[str] = []
    for dropped in candidates[MAX_FIX_TASKS:]:
        if dropped.feedback is not None:
            waiting.append(dropped.feedback.id)  # still takeable: the next round takes it
        else:
            skipped.append(f"{dropped.ids[0]}: more than {MAX_FIX_TASKS} tasks in one fix unit")
    groups: list[Finding] = []
    requirements: dict[tuple[str, str], list[DeltaScenario]] = {}
    consumed: list[str] = []
    taken: list[FeedbackRef] = []
    for cand in candidates[:MAX_FIX_TASKS]:
        if cand.feedback is not None:
            taken.append(cand.feedback)
        if cand.scenarios:
            target = _feedback_requirement(cand.feedback, family) if cand.feedback else _requirement_for(
                cand, by_id, family, ordinal
            )  # fmt: skip
            if target is None:
                skipped.append(f"{cand.ids[0]}: a scenario for it needs a requirement and the parent has several")
                continue
            scenarios = requirements.setdefault(target, [])
            for finding_id, finding_title, text in cand.scenarios:
                name = _flat(_when(text) if cand.synthetic else finding_title, MAX_TITLE_CHARS)
                if name in {s.name for s in scenarios}:
                    name = f"{name} ({len(scenarios) + 1})"
                scenarios.append(DeltaScenario(name, text, finding_id))
        title = cand.title if len(cand.ids) == 1 else f"{cand.title} (+{len(cand.ids) - 1} more)"
        if (ref := cand.feedback) is not None:
            groups.append(
                Finding(
                    tuple(cand.ids), _flat(title, MAX_TITLE_CHARS), "", cand.severity.value, (),
                    chore=ref.kind in (*REFACTOR_KINDS, "tests"), tests=ref.kind == "tests",
                    refactor=ref.kind in REFACTOR_KINDS, item=ref.id, request=request_of(ref), code=ref.code,
                    retake=ref.retake,
                )
            )  # fmt: skip
            continue
        groups.append(
            Finding(
                tuple(cand.ids), _flat(title, MAX_TITLE_CHARS),
                _fit_detail(cand.detail, cand.decisions, cand.decided_by, 600), cand.severity.value,
                (cand.criterion,) if cand.criterion else (),
                chore=(cand.criterion is None and not cand.scenarios) or cand.only_tests,
                tests=cand.tests or cand.only_tests,
            )
        )  # fmt: skip
        consumed += [q for q in cand.consumed if q not in consumed]
    delta = (
        SpecDelta(tuple(DeltaRequirement(cap, title, tuple(s)) for (cap, title), s in requirements.items()))
        if requirements
        else None
    )
    if groups and all(g.item for g in groups):  # feedback-only: the feedback is the concrete form of those rejects
        consumed += [q for q in unconverted if q not in consumed]  # L4-VER-016
    return FixPlan(groups, delta, consumed, skipped, taken, waiting)


def plan_follow_up(family: Sequence[Criterion], items: Sequence[FeedbackItem], *, ordinal: int) -> FixPlan:
    """The tasks and the ADDED scenarios of follow-up `ordinal` (`<parent>-followup-<ordinal>`, L4-FBK-010): the same
    one task per item by kind as a feedback fix unit has, from the parent's merged `feedback.md`. `family` is the
    parent's criteria: the capability an ADDED requirement goes under (none: no delta, the change `skip_specs`)."""
    result = VerifyResult("", 0, Verdict.FAIL, "", "", findings=feedback_findings(FeedbackScan(tuple(items))))
    return plan_fix_unit(family, result, (), ordinal=ordinal, fix_minor=False)


def redact_plan(plan: FixPlan, redact: Callable[[str], str]) -> FixPlan:
    """The plan with model- and human-written text redacted: the fix unit's files are committed and pushed."""
    groups = [
        dataclasses.replace(
            g, title=redact(g.title), detail=redact(g.detail), request=redact(g.request), code=redact(g.code)
        )
        for g in plan.groups
    ]
    delta = plan.delta and SpecDelta(
        tuple(
            DeltaRequirement(
                r.capability,
                redact(r.title),
                tuple(dataclasses.replace(s, name=redact(s.name), text=redact(s.text)) for s in r.scenarios),
            )
            for r in plan.delta.requirements
        )
    )
    return dataclasses.replace(plan, groups=groups, delta=delta)
