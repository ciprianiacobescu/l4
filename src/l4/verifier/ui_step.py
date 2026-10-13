"""Step 5's glue (SPEC 10.2 step 5, L4-VER-014), kept apart from the ladder: which criteria still need a generated
UI test, which generated tests of earlier rounds stand, and how an accepted one enters the evidence.

A UI criterion is a gap when no PROVED test of the END-TO-END report traces it, however many unit tests do (D2: a
criterion covered only by a unit test still gets a browser test). An e2e test the implementer wrote is not proved: the
red gate runs `gates.test` only, so nothing showed that it fails without the change, and step 4 lists it as "not
evidence" (live M1.5 P3, job 5528). It must not suppress step 5, which generates one that fails at the merge base and
passes at head. A generated test that an earlier round accepted is recognised by the ledger (`verify.generated`:
criterion, test ids, sha256 of the file as written) and by the file at head still having that digest; a file someone has
edited since is judged like any other test of the report and reported.
"""

import dataclasses
import hashlib
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from l4.fsutil import UnsafeFile, read_regular_file
from l4.gates.junit import TestReport
from l4.specs.base import Criterion
from l4.state.ledger import LedgerEvent
from l4.verifier.e2e_trace import e2e_coverage, trace_e2e
from l4.verifier.generate import ui_gap_finding
from l4.verifier.playwright import ui_facing_criteria, ui_files
from l4.verifier.traceability import PROOF_GENERATED
from l4.verifier.types import CriterionEvidence, Finding, GeneratedOutcome, Severity, TracingTest

MAX_TEST_FILE_BYTES = 256 * 1024


@dataclass(frozen=True)
class UiPlan:
    gaps: list[Criterion]
    skipped: str = ""  # why there is nothing to generate for, when that is not because every criterion is covered
    unproved: Mapping[str, tuple[str, ...]] = field(default_factory=dict)  # gap -> e2e tests that trace it, unproved


def plan_generation(
    criteria: Sequence[Criterion],
    e2e: TestReport | None,
    changed: Iterable[str],
    ui_paths: Sequence[str],
    proven: Mapping[str, Collection[str]] | None = None,
) -> UiPlan:
    """`proven`: criterion -> the ids of the tests step 4 accepted as evidence for it (the trace). With it, an e2e test
    that traces a criterion closes the gap only when it is among them; the criterion's other e2e tests are listed in
    `UiPlan.unproved`. Without it every e2e test that traces a criterion closes the gap."""
    changed = list(changed)
    if not ui_files(changed, ui_paths):
        return UiPlan([], "the unit changed no file under verifier.playwright.ui_paths")
    ui = ui_facing_criteria(criteria, changed, ui_paths)
    if proven is None:
        return UiPlan(trace_e2e(ui, e2e))
    traced = e2e_coverage(ui, e2e)
    gaps, unproved = [], {}
    for criterion in ui:
        ids = traced.get(criterion.id, [])
        if any(i in proven.get(criterion.id, ()) for i in ids):
            continue
        gaps.append(criterion)
        if ids:
            unproved[criterion.id] = tuple(sorted(ids))
    return UiPlan(gaps, unproved=unproved)


def previously_generated(
    events: Iterable[LedgerEvent], worktree: Path, e2e: TestReport | None
) -> tuple[dict[str, list[str]], list[str]]:
    """(criterion -> ids of the generated tests still in the report, criteria whose generated file was edited)."""
    found: dict[str, list[str]] = {}
    edited: list[str] = []
    for event in events:
        data = event.data
        if event.type != "verify.generated" or data.get("status") != "accepted" or not data.get("sha256"):
            continue
        criterion, path = str(data.get("criterion")), str(data.get("test") or "")
        try:
            body = read_regular_file(worktree / path, limit=MAX_TEST_FILE_BYTES)
        except (FileNotFoundError, UnsafeFile, OSError):
            continue  # removed: its tests are not in the report either
        if hashlib.sha256(body).hexdigest() != data["sha256"]:
            if criterion not in edited:
                edited.append(criterion)
            continue
        present = [str(t) for t in data.get("tests") or [] if e2e is not None and str(t) in e2e.tests]
        if present:
            found.setdefault(criterion, []).extend(i for i in present if i not in found.get(criterion, []))
    return found, edited


def with_generated(trace: Sequence[CriterionEvidence], outcomes: Iterable[GeneratedOutcome]) -> list[CriterionEvidence]:
    """Step 5's accepted tests join the criterion's evidence as `generated`, passing (they passed at head in the
    run that accepted them). A criterion that already `fail`s stays failing."""
    accepted = {o.criterion: o for o in outcomes if o.accepted}
    out = []
    for e in trace:
        done = accepted.get(e.criterion)
        if done is not None:
            have = {t.id for t in e.tests}
            added = tuple(TracingTest(i, "passed", PROOF_GENERATED) for i in done.tests if i not in have)
            e = dataclasses.replace(e, state="fail" if e.state == "fail" else "covered", tests=(*e.tests, *added))
        out.append(e)
    return out


def gap_findings(gaps: Iterable[Criterion], unproved: Mapping[str, Sequence[str]] | None = None) -> list[Finding]:
    return [ui_gap_finding(c, (unproved or {}).get(c.id, ())) for c in gaps]


def unclosed_holds(gaps: Iterable[Criterion], outcomes: Iterable[GeneratedOutcome]) -> list[str]:
    """A UI criterion that step 5 did not close (no writer, or the writer's test was not accepted) is a hold: the unit
    waits for a human, who can accept it (a unit test may well be enough) and so waive the hold. The text is stable
    across rounds (status only, never the writer's reason), because a verdict is keyed by a hash of it."""
    done = {o.criterion: o for o in outcomes}
    holds = []
    for c in gaps:
        outcome = done.get(c.id)
        if outcome is not None and outcome.accepted:
            continue
        why = outcome.status if outcome is not None else "not attempted"
        holds.append(f"UI criterion {c.id} has no end-to-end test ({why}); see the generated UI tests table")
    return holds


def edited_findings(criteria: Iterable[str]) -> list[Finding]:
    return [
        Finding(
            Severity.MINOR,
            "a generated UI test was edited after it was accepted",
            "its file no longer has the digest recorded when the harness accepted it, so it is judged like any "
            "other test",
            "deterministic",
            criterion=c,
        )  # fmt: skip
        for c in criteria
    ]
