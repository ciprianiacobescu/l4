"""Step 4 of the ladder (SPEC 10.2, L4-VER-009): `criterion -> tests -> status`, from the reports and the ledger.

A passing test is evidence for a criterion when it traces at most `verifier.max_criteria_per_test` criteria and it
carries a proof that it discriminates:
- `zero_value`, `pre_satisfied`, `red_assertion`: the implementer's red phase proved it (`task.red_ok.criteria`), and
  the criterion has at least one test that failed against the zero values (tests whose right answer is the zero value
  count together with such a sibling);
- `audit`: an audit test the verifier accepted in an earlier round (`verify.audit`, so a test cannot claim it by name);
- `generated`: a test of an extra report (M1.5's end-to-end tests), which M1.5 proved discriminating itself;
- `human` and `chore` (M1.11): a test that people wrote, or that a test chore added, which the verifier itself saw
  fail against the zero values or on the base's production code (`verify.extra_proof`, valid while its file's content is
  the one that was run);
- `pass_to_pass`: the criterion text is unchanged from the base specs.
A passing test over the cap that has such a proof stays ignored, and is kept as a candidate (`capped`): the judge's
reply can make it count for a criterion it passed and named the test for (L4-VER-054, `count_named`).
Anything else that carries the criterion id is ignored and listed as a minor finding. The synthetic baseline of
L4-VER-009 is not rebuilt: the red-phase proofs stand in for it (M1: verifier 3.3).
"""

import dataclasses
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from typing import Any

from l4.config.schema import L4Config
from l4.gates.junit import TestCase, TestReport, fold_subtest_id
from l4.specs.base import Criterion
from l4.specs.criteria import normalise, trace_ids
from l4.state.ledger import LedgerEvent
from l4.verifier.types import CriterionEvidence, Finding, Severity, TracingTest

__all__ = [
    "NO_PROOF", "PASS_TO_PASS", "PROOF_AUDIT", "PROOF_CHORE", "PROOF_GENERATED", "PROOF_HUMAN", "CriterionEvidence",
    "OVER_CAP_LABEL", "TracingTest", "apply_adequacy", "count_named", "extra_candidates", "extra_proofs",
    "ignored_findings", "inadequate_findings", "new_covered", "red_notes", "red_proofs", "rescue_ceiling",
    "trace_criteria",
]  # fmt: skip

PASS_TO_PASS = "pass_to_pass"
PROOF_AUDIT = "audit"
PROOF_GENERATED = "generated"
PROOF_HUMAN = "human"
PROOF_CHORE = "chore"
NO_PROOF = "no proof that it discriminates"  # the start of the reason of a test that carries a criterion and has none
_RED_PROOFS = ("zero_value", "pre_satisfied", "red_assertion")
NOT_APPLICABLE_NOTE = "not applicable: no project code"  # L4-IMP-062
UNPROVEN_VIA = (
    "not_applicable",
    "human_override",
    "agent_override",
    "delegate_override",
)  # proofs that no variant run showed (L4-VER-051)


def _unproven_note(info: Mapping[str, Any]) -> str:
    """The label of a red record that no run proved: `discrimination not applicable`, or a person's `accept` after an
    inconclusive check (L4-VER-051); empty for every other record."""
    if info.get("via") == "not_applicable":
        return NOT_APPLICABLE_NOTE
    if info.get("via") == "human_override":
        return f"accepted by {info.get('question') or 'a person'}: the check was inconclusive"
    if info.get("via") == "agent_override":  # the judge must be able to tell an agent's acceptance from a person's
        return f"accepted by an agent through {info.get('question') or 'a question'}: the check was inconclusive"
    if info.get("via") == "delegate_override":  # ... and the delegate's: with the model and the CLI that answered
        who = f" ({info['model']} via {info['cli']})" if info.get("model") and info.get("cli") else ""
        return (
            f"accepted by the delegate{who} through {info.get('question') or 'a question'}: the check was inconclusive"
        )
    return ""


def red_proofs(ledger: Iterable[LedgerEvent]) -> dict[str, dict[str, str]]:
    """criterion -> test id -> proof, from `task.red_ok` (red phase) and accepted `verify.audit` events. A criterion
    whose red record names no discriminating test has no proofs."""
    found: dict[str, dict[str, str]] = {}
    for event in ledger:
        if event.type == "task.red_ok" and isinstance(event.data.get("criteria"), Mapping):
            for criterion, info in event.data["criteria"].items():
                if not isinstance(info, Mapping) or not info.get("discriminating"):
                    continue
                proof = str(info.get("proof"))
                if proof in _RED_PROOFS:
                    # an unproven record of a step that added no test names the tests only as `discriminating`
                    tests = info.get("tests") or (info.get("discriminating") if info.get("via") in UNPROVEN_VIA else [])
                    for test in tests or []:
                        found.setdefault(str(criterion), {}).setdefault(fold_subtest_id(str(test)), proof)
        elif event.type == "verify.audit" and event.data.get("status") == "accepted":
            for test in event.data.get("tests") or []:
                found.setdefault(str(event.data.get("criterion")), {})[fold_subtest_id(str(test))] = PROOF_AUDIT
    return found


def red_notes(ledger: Iterable[LedgerEvent]) -> dict[tuple[str, str], str]:
    """(criterion, test id) -> the label of an unproven red record (`not applicable: no project code`, or `accepted by
    Q-NNN: the check was inconclusive`), for the judge and the report (L4-VER-051)."""
    found: dict[tuple[str, str], str] = {}
    for event in ledger:
        if event.type != "task.red_ok" or not isinstance(event.data.get("criteria"), Mapping):
            continue
        for criterion, info in event.data["criteria"].items():
            if isinstance(info, Mapping) and info.get("discriminating") and (note := _unproven_note(info)):
                tests = info.get("tests") or info.get("discriminating") or []
                found.update({(str(criterion), str(test)): note for test in tests})
    return found


def extra_proofs(ledger: Iterable[LedgerEvent], file_sha: Callable[[str], str | None]) -> dict[str, dict[str, str]]:
    """criterion -> test id -> `human` or `chore`, from the accepted `verify.extra_proof` events. An event holds only
    while every file it names still has the content that was run (`file_sha(path)` is its sha10 now): a test edited
    after the decision is decided again."""
    found: dict[str, dict[str, str]] = {}
    for event in ledger:
        if event.type != "verify.extra_proof":
            continue
        files, source = event.data.get("files"), str(event.data.get("source"))
        if source not in (PROOF_HUMAN, PROOF_CHORE) or not isinstance(files, Mapping) or not files:
            continue
        if any(file_sha(str(path)) != str(sha) for path, sha in files.items()):
            continue
        for test in event.data.get("tests") or []:
            found.setdefault(str(event.data.get("criterion")), {}).setdefault(fold_subtest_id(str(test)), source)
    return found


def extra_candidates(
    evidence: Sequence[CriterionEvidence],
    attribution: Mapping[str, str],
    chore_files: Collection[str],
    *,
    file_of: Callable[[str], str | None],
) -> dict[str, list[tuple[str, str]]]:
    """criterion -> [(test, source)]: the tests that carry a criterion and are ignored only for want of a proof, and
    whose file is a person's (`attribution`: file -> `human`, when every commit of the unit that touches it is not the
    harness's) or a test chore's (`chore_files`, from `task.tests_added`). Each is a candidate for a discrimination run;
    none is evidence until it has passed one (decision 8). A test ignored for any other reason is no candidate."""
    found: dict[str, list[tuple[str, str]]] = {}
    for item in evidence:
        for test, why in item.ignored:
            path = file_of(test) if why.startswith(NO_PROOF) else None
            if path is None:
                continue
            source = (
                PROOF_HUMAN if attribution.get(path) == PROOF_HUMAN else PROOF_CHORE if path in chore_files else None
            )
            if source is not None:
                found.setdefault(item.criterion, []).append((test, source))
    return found


def _unchanged(criteria: Sequence[Criterion], base: Sequence[Criterion]) -> frozenset[str]:
    before = {c.id: normalise(c.text) for c in base}
    return frozenset(c.id for c in criteria if before.get(c.id) == normalise(c.text))


def _traced(case: TestCase, known: frozenset[str]) -> frozenset[str]:
    return trace_ids(case) & known


def trace_criteria(
    criteria: Sequence[Criterion],
    report: TestReport,
    ledger: Sequence[LedgerEvent],
    cfg: L4Config,
    *,
    extra_reports: Sequence[TestReport] = (),
    generated: Mapping[str, Collection[str]] | None = None,
    base: Sequence[Criterion] = (),
    extra: Mapping[str, Mapping[str, str]] | None = None,
    reasons: Mapping[str, str] | None = None,
) -> list[CriterionEvidence]:
    """One `CriterionEvidence` per criterion. `base`: the archived specs' criteria (pass-to-pass for the unchanged
    ones). `extra_reports`: reports of further gates (the end-to-end report); their tests count as `generated`.
    `generated` (criterion -> accepted generated test ids) narrows that to the tests the generator's accept step
    named: any other test of an extra report is judged like a main-report test (red proof, or ignored). Without it
    the caller vouches that the extra reports hold accepted generated tests only (contract C8). `extra`: the proofs of
    `extra_proofs` (people's and chores' tests the verifier saw fail); `reasons`: test id -> why it is ignored, for a
    test whose discrimination run decided against it."""
    known = frozenset(c.id for c in criteria)
    limit = cfg.verifier.max_criteria_per_test
    proofs = red_proofs(ledger)
    notes = red_notes(ledger)
    for criterion_id, tests_proved in (extra or {}).items():
        for test_id, source in tests_proved.items():
            proofs.setdefault(criterion_id, {}).setdefault(test_id, source)
    unchanged = _unchanged(criteria, base)
    sources: list[tuple[TestReport, bool]] = [(report, False), *((extra, True) for extra in extra_reports)]
    out = []
    for criterion in criteria:
        tests: list[TracingTest] = []
        ignored: list[tuple[str, str]] = []
        capped: list[TracingTest] = []
        for source, extra in sources:
            for test_id, case in sorted(source.tests.items()):
                traced = _traced(case, known)
                if criterion.id not in traced:
                    continue
                proof = proofs.get(criterion.id, {}).get(test_id)
                accepted = extra and (generated is None or test_id in generated.get(criterion.id, ()))
                proof = proof or (PROOF_GENERATED if accepted else PASS_TO_PASS if criterion.id in unchanged else None)
                if len(traced) > limit:  # ignored whatever its proof; a proved, passing one stays a candidate
                    why = f"it traces {len(traced)} criteria (verifier.max_criteria_per_test={limit})"
                    ignored.append((test_id, why))
                    if proof is not None and case.status == "passed":
                        note = notes.get((criterion.id, test_id), "")
                        capped.append(TracingTest(test_id, case.status, proof, note=note, over_cap=len(traced)))
                    continue
                if proof is None:
                    why = (reasons or {}).get(test_id) or f"{NO_PROOF} (no red, audit or generated record)"
                    ignored.append((test_id, why))
                elif case.status == "skipped":
                    ignored.append((test_id, "it was skipped"))
                else:
                    tests.append(TracingTest(test_id, case.status, proof, note=notes.get((criterion.id, test_id), "")))
        state = "fail" if any(t.status != "passed" for t in tests) else "covered" if tests else "uncovered"
        out.append(
            CriterionEvidence(criterion.id, criterion.alias, state, tuple(tests), tuple(ignored), capped=tuple(capped))  # type: ignore[arg-type]
        )
    return out


OVER_CAP_LABEL = "over the per-test cap"  # the label of a test the judge named although it traces more than the cap


def rescue_ceiling(unit_size: int, cap: int) -> int:
    """The most criteria a test over the cap may trace and still count when the judge names it (L4-VER-054):
    half of the unit, and never more than three times the cap. Not configurable."""
    return min(unit_size // 2, 3 * cap)


def count_named(
    evidence: Sequence[CriterionEvidence],
    passed: Collection[str],
    named: Collection[tuple[str, str]],
    rejected: Collection[tuple[str, str]],
    cap: int = 3,
) -> list[CriterionEvidence]:
    """L4-VER-054: a candidate over the cap (`capped`) becomes a tracing test of its criterion when the judge passed
    the criterion, named the test for it (`named`: (test, criterion) of a `test_adequacy` entry that is adequate), no
    entry rejected it (`rejected`: (test, criterion), or (test, "") for the test everywhere), and it traces at most
    `rescue_ceiling` criteria. An uncovered criterion becomes covered; a failing one stays failing."""
    ceiling = rescue_ceiling(len(evidence), cap)
    out = []
    for item in evidence:
        moved = [
            dataclasses.replace(t, adequate=True)
            for t in item.capped
            if item.criterion in passed
            and (t.id, item.criterion) in named
            and (t.id, item.criterion) not in rejected
            and (t.id, "") not in rejected
            and t.over_cap <= ceiling
        ]
        if not moved:
            out.append(item)
            continue
        ids = {t.id for t in moved}
        state = "covered" if item.state == "uncovered" else item.state
        ignored = tuple((test, why) for test, why in item.ignored if test not in ids)
        out.append(dataclasses.replace(item, state=state, tests=(*item.tests, *moved), ignored=ignored))
    return out


def apply_adequacy(
    evidence: Sequence[CriterionEvidence], adequacy: Iterable[tuple[str, str, bool]]
) -> list[CriterionEvidence]:
    """The judge's `test_adequacy` as (test, criterion, adequate): a test it calls inadequate stops being evidence.
    An entry that names no criterion (or one the test does not trace) applies to the test everywhere."""
    rejected = [(test, criterion) for test, criterion, adequate in adequacy if not adequate]
    out = []
    for item in evidence:
        tests = tuple(
            dataclasses.replace(t, adequate=False)
            if any(t.id == test and criterion in (item.criterion, "") for test, criterion in rejected)
            else t
            for t in item.tests
        )
        out.append(dataclasses.replace(item, tests=tests))
    return out


def ignored_findings(evidence: Sequence[CriterionEvidence]) -> list[Finding]:
    """A minor finding for every test that carries a criterion id and is not evidence (L4-VER-009)."""
    return [
        Finding(Severity.MINOR, "a test is ignored as evidence", f"{test}: {why}", "deterministic", item.criterion)
        for item in evidence
        for test, why in item.ignored
    ]


def inadequate_findings(evidence: Sequence[CriterionEvidence]) -> list[Finding]:
    """A minor finding for every tracing test the judge called inadequate."""
    return [
        Finding(Severity.MINOR, "the judge called a test inadequate", t.id, "judge", item.criterion)
        for item in evidence
        for t in item.tests
        if not t.adequate
    ]


def new_covered(evidence: Sequence[CriterionEvidence]) -> list[CriterionEvidence]:
    """Covered criteria that rest on a new test (not pass-to-pass, not already audited): the audit sample's pool."""
    return [
        e for e in evidence
        if e.state == "covered"
        and not any(t.proof == PROOF_AUDIT and t.status == "passed" for t in e.tests)
        and any(t.proof != PASS_TO_PASS for t in e.tests)
    ]  # fmt: skip
