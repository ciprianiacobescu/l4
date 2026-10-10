"""From a round's findings to the content of a fix unit (SPEC L4-VER-006, M1.3 lines 32 and 37, decisions D6 and D8).

`plan_fix_unit` is pure: it decides which findings become tasks (at most `MAX_FIX_TASKS`), which behaviours a regression
scenario pins, and which `reject`ed verdict questions the fix unit consumes. Writing the files is the provider's job
(`create_fix_unit`). The spec writer is deterministic: `roles.spec_writer` is unused.

On a FAIL the convertible findings are the deterministic (or human-rejected) blockers and majors, the `fail` criteria
and the rejected targets. On a PASS with `verifier.fix_minor_findings` they are the minor findings that cite a
criterion or carry a scenario. A spec gap becomes an ADDED scenario under `<requirement> — regression <n>`; its
`WHEN ... THEN ...` comes from the human's `reject` reason, else from the judge's `suggested_fix`, and a finding with
neither is listed and not converted. A finding without a criterion becomes a `[chore]` task (D8).
"""

import dataclasses
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from l4.memory.curate import UI_GAP_TITLE
from l4.specs.base import MAX_DECISION_CHARS, Criterion, DeltaRequirement, DeltaScenario, Finding, SpecDelta
from l4.verifier.types import Finding as VerifierFinding
from l4.verifier.types import HumanVerdict, Severity, Verdict, VerifyResult
from l4.verifier.verdicts import is_coverage_hold_finding, rejection_note

MAX_FIX_TASKS = 5
MAX_TITLE_CHARS = 100
REGRESSION = "\N{EM DASH} regression"
_SUFFIX = re.compile(r"\s+\N{EM DASH}\s+regression\s+\d+\s*$")
_WHEN_THEN = re.compile(r"\bWHEN\b(?P<when>.+?)\bTHEN\b(?P<then>.+)", re.S)
_SEVERITY_ORDER = {Severity.BLOCKER: 0, Severity.MAJOR: 1, Severity.MINOR: 2}
# the title of a finding about tests: the word as a noun of its own, not `test-mode` or `latest` (M1.13, W-C1)
_ABOUT_TESTS = re.compile(r"(?<![\w-])(?:tests?|assertions?|mocks?|fixtures?)(?![\w-])", re.I)


@dataclass(frozen=True)
class FixPlan:
    groups: list[Finding]  # one task each
    delta: SpecDelta | None
    consumed: list[str]  # the verdict questions (rejects) this fix unit answers
    not_converted: list[str] = field(default_factory=list)  # "<id>: why", for the sticky note and the report

    @property
    def finding_ids(self) -> list[str]:
        return [i for g in self.groups for i in g.ids]


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
    match = _WHEN_THEN.search(text)
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
) -> tuple[list[_Candidate], list[str]]:
    by_id = {c.id: c for c in family}
    skipped: list[str] = []
    picked: list[tuple[VerifierFinding, bool]] = []  # (finding, it is a minor on a PASS)
    synthetic: list[VerifierFinding] = []
    # satisfied: judged so, or accepted by a human, so the code is right (a finding about its tests asks for tests)
    satisfied = {o.id for o in result.criteria if o.result == "pass"}
    if result.verdict is Verdict.FAIL:
        picked += [(f, False) for f in result.findings if f.blocking and f.source in ("deterministic", "human")]
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
    return list(grouped.values()), skipped


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
    candidates, skipped = _candidates(family, result, rejects, fix_minor)
    candidates.sort(key=lambda c: _SEVERITY_ORDER[c.severity])  # stable: the report's order within a severity
    for dropped in candidates[MAX_FIX_TASKS:]:
        skipped.append(f"{dropped.ids[0]}: more than {MAX_FIX_TASKS} tasks in one fix unit")
    groups: list[Finding] = []
    requirements: dict[tuple[str, str], list[DeltaScenario]] = {}
    consumed: list[str] = []
    for cand in candidates[:MAX_FIX_TASKS]:
        if cand.scenarios:
            target = _requirement_for(cand, by_id, family, ordinal)
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
    return FixPlan(groups, delta, consumed, skipped)


def redact_plan(plan: FixPlan, redact: Callable[[str], str]) -> FixPlan:
    """The plan with model- and human-written text redacted: the fix unit's files are committed and pushed."""
    groups = [dataclasses.replace(g, title=redact(g.title), detail=redact(g.detail)) for g in plan.groups]
    delta = plan.delta and SpecDelta(
        tuple(
            DeltaRequirement(
                r.capability,
                r.title,
                tuple(dataclasses.replace(s, name=redact(s.name), text=redact(s.text)) for s in r.scenarios),
            )
            for r in plan.delta.requirements
        )
    )
    return dataclasses.replace(plan, groups=groups, delta=delta)
