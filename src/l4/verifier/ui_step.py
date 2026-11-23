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
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from l4.fsutil import UnsafeFile, read_regular_file
from l4.gates.junit import TestReport
from l4.implementer.test_locate import file_of_id
from l4.specs.base import Criterion
from l4.state.ledger import LedgerEvent
from l4.verifier.e2e_trace import e2e_coverage, trace_e2e
from l4.verifier.generate import ui_gap_finding
from l4.verifier.playwright import ui_facing_criteria, ui_files
from l4.verifier.traceability import PASS_TO_PASS, PROOF_AUDIT, PROOF_GENERATED
from l4.verifier.types import CriterionEvidence, Finding, GeneratedOutcome, Severity, TracingTest
from l4.verifier.verdicts import effective_verdicts, finding_sha256, hold_id, text_sha256

MAX_TEST_FILE_BYTES = 256 * 1024
_LEGACY_HOLD_TITLE = re.compile(r"^Hold (H-[0-9a-f]{8}): UI criterion (C-[0-9a-f]{8}) has no end-to-end test")


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


def gap_findings(
    gaps: Iterable[Criterion],
    unproved: Mapping[str, Sequence[str]] | None = None,
    waived: Mapping[str, str] | None = None,
    carried: Collection[str] = (),
) -> list[Finding]:
    return [
        ui_gap_finding(c, (unproved or {}).get(c.id, ()), (waived or {}).get(c.id, ""), c.id in carried) for c in gaps
    ]


def ui_hold_text(criterion_id: str) -> str:
    """The hold of a UI criterion that step 5 did not close. It names the criterion and nothing else: the generator's
    status (and the writer's reason) changes from round to round and stays in the generated tests table, while the
    hold's id, a hash of this text, must stay the same for a person's answer to be found again (L4-VER-067)."""
    return f"UI criterion {criterion_id} has no end-to-end test; see the generated UI tests table"


def _covers(t: TracingTest) -> bool:
    """A tracing test that covers a criterion with evidence a run showed (L4-VER-067): it passed, is adequate, is within
    the per-test cap, and is neither `pass_to_pass` nor a red record that no run proved (it carries a `note`)."""
    return t.status == "passed" and t.adequate and t.proof != PASS_TO_PASS and not t.note and t.over_cap == 0


def covered_by_step4(trace: Sequence[CriterionEvidence]) -> dict[str, tuple[str, ...]]:
    """criterion -> the sorted ids of the tests that cover it with evidence step 4 has (L4-VER-067): the criterion is
    `covered` and not `held` (no audit test failing at head), and a tracing test passed, is adequate, is within the
    per-test cap and has a proof that a run showed. `pass_to_pass` is not one (it is not discriminating, L4-VER-009:
    it says only that the criterion's text is unchanged from the base specs); nor is a test with a `note` (a red
    record that no run proved: `not applicable: no project code`, or an accept after an inconclusive check). A
    criterion with no such test is not in the map."""
    out = {}
    for e in trace:
        if e.state != "covered" or e.held:
            continue
        if ids := sorted(t.id for t in e.tests if _covers(t)):
            out[e.criterion] = tuple(ids)
    return out


def lost_notes(trace: Sequence[CriterionEvidence], outcomes: Iterable[GeneratedOutcome]) -> list[str]:
    """The criteria whose note step 5 took (`covered_by`) and whose basis step 9 has since removed while another test
    would still pass them (L4-VER-067): none of the `covered_by` tests still covers the criterion in `trace` (the
    trace after the judge's adequacy review), and the criterion has no failing tracing test and no `held` reason, and
    still has a passing adequate test, which is not one of them (a `pass_to_pass` test, or a red record that no run
    proved), so aggregation would pass it with no human asked. A criterion with no such test is `needs_human` through
    aggregation on its own (SCN-VER-303) and gets no hold from here."""
    evidence = {e.criterion: e for e in trace}
    lost = []
    for o in outcomes:
        e = evidence.get(o.criterion)
        if o.status != "not_testable" or not o.covered_by or e is None or e.state == "fail" or e.held:
            continue
        if any(t.status in ("failed", "error") for t in e.tests):
            continue
        if any(t.id in o.covered_by and _covers(t) for t in e.tests):
            continue
        if any(t.status == "passed" and t.adequate for t in e.tests):
            lost.append(o.criterion)
    return lost


def unclosed_holds(gaps: Iterable[Criterion], outcomes: Iterable[GeneratedOutcome]) -> list[str]:
    """A UI criterion that step 5 did not close (no writer, or the writer's test was not accepted, and not waived) is a
    hold: the unit waits for a human, who can accept it (a unit test may well be enough) and so waive the hold. A
    `not_testable` outcome with `covered_by` is a note, not a hold (L4-VER-067), and so is a criterion carried from the
    base (L4-VER-086)."""
    done = {o.criterion: o for o in outcomes}
    return [
        ui_hold_text(c.id)
        for c in gaps
        if (outcome := done.get(c.id)) is None
        or not (
            outcome.accepted
            or outcome.status in ("waived", "carried")
            or (outcome.status == "not_testable" and outcome.covered_by)
        )
    ]


def _holders(test_id: str, paths: Collection[str]) -> set[str]:
    """Every one of `paths` that the head of `test_id` (before its first `::`) could name: the path itself or its end,
    the path with dots for slashes (whole or its end), and the files of the dotted Python module (the longest prefix
    that is one, as `file_of_id` reads it, also below a directory the id does not name)."""
    head = test_id.split("::", 1)[0]
    if not head:
        return set()
    found = {
        p for p in paths if p == head or p.endswith("/" + head) or (d := p.replace("/", ".")) == head
        or d.endswith("." + head)
    }  # fmt: skip
    parts = head.split(".")
    for n in range(len(parts), 0, -1):
        module = "/".join(parts[:n]) + ".py"
        hits = {p for p in paths if p == module or p.endswith("/" + module)}
        if hits:
            return found | hits
    return found


def carry_file(test_id: str, walked: str | None, paths: Collection[str]) -> str | None:
    """The file that holds the test of `test_id` for the carry of L4-VER-086, or None when that is in any doubt. Two
    readings of the id are taken: `walked` (the dotted module found in the work tree, which reads
    `src.pricing.total.test.ts` as `src/pricing/total.py` when that lies beside the test) and `file_of_id` over
    `paths`. `file_of_id` must place the id, and no other of `paths` may be a file the id could name (a module of the
    same name under two roots). When the walk places it too, both must give the same file; when the walk finds nothing,
    the file of `file_of_id` stands if it is not a `.py` file (a TypeScript test is no Python module, so the walk has
    nothing to say about it). A walk that finds a file `file_of_id` does not give is the wrong-module case: refused."""
    found = file_of_id(test_id, paths)
    if found is None or len(_holders(test_id, paths)) != 1:
        return None
    if walked is None:
        return None if found.endswith(".py") else found
    return found if walked == found else None


def carried_from_base(
    gaps: Iterable[Criterion],
    trace: Sequence[CriterionEvidence],
    unchanged: Collection[str],
    file_of: Callable[[str], str | None],
    changed: Collection[str],
    rejected: Collection[str],
) -> dict[str, tuple[str, ...]]:
    """criterion -> the sorted ids of its tracing tests, for each gap that step 5 carries from the base instead of
    asking the writer (L4-VER-086). All four hold, and any doubt keeps the gap:
    1. the criterion is in `unchanged` (the pass-to-pass rule of L4-VER-009, read from step 4's own baseline);
    2. its evidence in `trace` is `covered` with no `held` reason; every tracing test passed with the proof
       `pass_to_pass`, no note, within the cap and adequate; every test listed as not evidence for it is a passing
       candidate over the cap (`capped`);
    3. the file of every such test, listed or ignored, is found (`file_of`) and is not one of the files the unit
       `changed` since its merge base;
    4. the criterion is not in `rejected` (`rejected_ui_criteria`)."""
    evidence = {e.criterion: e for e in trace}
    out: dict[str, tuple[str, ...]] = {}
    for c in gaps:
        e = evidence.get(c.id)
        if c.id not in unchanged or c.id in rejected or e is None or e.state != "covered" or e.held or not e.tests:
            continue
        if not all(
            t.status == "passed" and t.proof == PASS_TO_PASS and not t.note and t.over_cap == 0 and t.adequate
            for t in e.tests
        ):
            continue
        if not {test for test, _ in e.ignored} <= {t.id for t in e.capped}:
            continue
        ids = sorted(t.id for t in e.tests)
        files = [file_of(test) for test in (*ids, *sorted(test for test, _ in e.ignored))]
        if any(f is None or f in changed for f in files):
            continue
        out[c.id] = tuple(ids)
    return out


def rejected_ui_criteria(events: Iterable[LedgerEvent], criteria: Iterable[str]) -> frozenset[str]:
    """The criteria (among `criteria`) that a person ever rejected, consumed by a fix unit or not (L4-VER-086): a
    `human.verdict{decision: reject}` whose target is the criterion, a UI hold that a `question.raised{kind: verdict,
    criterion}` named (also one raised with the old text, found by its title), or the stable hold id of the criterion
    (`hold_id(ui_hold_text(...))`) whether or not an event named it. An accept is not a reject."""
    events = list(events)
    ids = set(criteria)
    targets = {hold_id(ui_hold_text(c)): c for c in ids} | {c: c for c in ids}
    for e in events:
        if e.type != "question.raised" or e.data.get("kind") != "verdict":
            continue
        target, bound = str(e.data.get("target", "")), e.data.get("criterion")
        old = _LEGACY_HOLD_TITLE.match(str(e.data.get("title") or ""))
        if isinstance(bound, str) and bound in ids and target.startswith("H-"):
            targets[target] = bound
        elif old is not None and old.group(1) == target and old.group(2) in ids:
            targets[target] = old.group(2)
    return frozenset(
        targets[str(e.data["target"])]
        for e in events
        if e.type == "human.verdict" and e.data.get("decision") == "reject" and str(e.data.get("target")) in targets
    )


def ui_hold_binding(criterion: Criterion, evidence: CriterionEvidence | None, blob_of: Callable[[str], str]) -> str:
    """What a person's accept of the criterion's UI hold is bound to: the hold, the criterion's text and the head
    blobs of the files of its tracing tests (`blob_of`: test id -> a string naming the file and its blob), the
    evidence the person saw. The tests step 4 accepted and the ones it listed as not evidence count; a test the
    harness wrote itself (an audit test, a generated one) is left out, since a round writes it after the accept."""
    tests = set()
    if evidence is not None:
        tests = {t.id for t in evidence.tests if t.proof not in (PROOF_AUDIT, PROOF_GENERATED)}
        tests |= {test for test, _ in evidence.ignored}
    covered = "\n".join(sorted({blob_of(test) for test in tests}))
    body = f"{ui_hold_text(criterion.id)}\0{text_sha256(criterion)}\0{covered}"
    return hashlib.sha256(body.encode()).hexdigest()


def ui_hold_views(
    holds: Iterable[str],
    criteria: Iterable[Criterion],
    trace: Sequence[CriterionEvidence],
    blob_of: Callable[[str], str],
) -> dict[str, dict[str, Any]]:
    """`VerifyResult.hold_views` of the UI holds among `holds`: the binding of their accept (no files to list)."""
    evidence = {e.criterion: e for e in trace}
    return {
        ui_hold_text(c.id): {"sha": ui_hold_binding(c, evidence.get(c.id), blob_of), "paths": []}
        for c in criteria
        if ui_hold_text(c.id) in holds
    }


def _failing(evidence: CriterionEvidence | None) -> bool:
    """A tracing test fails now (the rule of `verdicts.regressions`): an accept is void for good."""
    return evidence is not None and (
        evidence.state == "fail" or any(t.status in ("failed", "error") for t in evidence.tests)
    )


def ui_waivers(
    events: Sequence[LedgerEvent],
    criteria: Iterable[Criterion],
    trace: Sequence[CriterionEvidence],
    blob_of: Callable[[str], str],
) -> dict[str, str]:
    """criterion -> the answered question that waives its step 5 (L4-VER-067). Waived: an accept of the criterion
    itself in force (its text unchanged, not voided), or the latest accept of one of its UI holds in force, whose
    binding is the one the criterion has now (`ui_hold_binding`: the criterion's text and its tracing-test files
    unchanged); an accept recorded before the binding existed is found by the hold's title and counts as the
    accepts of that time did (it saw no files and no text to compare). Not waived: a later reject of either, a
    `human.void`, a tracing test that fails now."""
    criteria = list(criteria)
    evidence = {e.criterion: e for e in trace}
    holds: dict[str, set[str]] = {}  # criterion -> the targets of its UI holds raised in earlier rounds
    for e in events:
        if (
            e.type != "question.raised"
            or e.data.get("kind") != "verdict"
            or not str(e.data.get("target", "")).startswith("H-")
        ):
            continue
        target, bound = str(e.data["target"]), e.data.get("criterion")
        old = _LEGACY_HOLD_TITLE.match(str(e.data.get("title") or ""))
        if isinstance(bound, str):
            holds.setdefault(bound, set()).add(target)
        elif old is not None and old.group(1) == target:
            holds.setdefault(old.group(2), set()).add(target)
    placed = {str(e.data.get("question")): i for i, e in enumerate(events) if e.type == "human.verdict"}
    out = {}
    for c in criteria:
        if _failing(evidence.get(c.id)):
            continue
        stable = hold_id(ui_hold_text(c.id))
        current = {c.id: text_sha256(c)}
        for target in holds.get(c.id, ()):  # any other id is a hold of an older text: its accept hashes the id
            current[target] = (
                ui_hold_binding(c, evidence.get(c.id), blob_of) if target == stable else finding_sha256(target)
            )
        in_force = [v for t, v in effective_verdicts(events, current).items() if t in current]
        if any(v.target == c.id and v.decision == "reject" for v in in_force):
            continue  # the criterion's own verdict is a reject
        accepted = max(
            (v for v in in_force if v.decision == "accept"), key=lambda v: placed.get(v.question, -1), default=None
        )
        if accepted is None:
            continue
        since = placed.get(accepted.question, -1)
        if any(  # a reject after it ends it, also one that a fix unit consumed (`effective_verdicts` drops those)
            e.type == "human.verdict"
            and e.data.get("decision") == "reject"
            and e.data.get("target") in current
            and i > since
            for i, e in enumerate(events)
        ):
            continue
        out[c.id] = accepted.question
    return out


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
