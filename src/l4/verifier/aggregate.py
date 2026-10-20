"""Aggregation (SPEC 10.4, L4-VER-003) and pure: no I/O. Every row of the table but the S1 and panel columns.

A criterion rests on tracing evidence (step 4, L4-VER-009), the judge and a human verdict:
- a tracing test that fails at head, or a human `reject`, makes it `fail` (a regression always beats a human `accept`);
- a human `accept` passes it; the verdict an `accept` is void for is filtered out by the caller (`verdicts.py`);
- covered (at least one adequate, discriminating, passing test) with a judge `pass` is `pass`; with a judge `fail` it is
  `disputed` when the model-written counterexample reproduced (never in M1.3: counterexamples are not executed) and
  `needs_human` otherwise (insufficient evidence); any other judge answer, or none, is `needs_human` (fail closed);
- uncovered is `needs_human`. `sdd.require_traceability: false` would allow "pass (judgment)" only with an S1 `p` above
  the accept threshold, and S1 is not built, so the flag changes the reason and not the result.
M1: verifier S1 column (step 8), the panel and the tie-breaker (L4-VER-004).

Unit verdict: FAIL on a `fail` criterion or a deterministic (or human-rejected) blocker/major finding; else NEEDS_HUMAN
when a criterion is not a pass, a judge raised a blocker/major (no citation re-check exists, so every one counts) or
a hold is set; else PASS. LLM judgments alone never FAIL a unit (P7).
"""

from collections.abc import Collection, Sequence

from l4.verifier.judge import CriterionVerdict, JudgeVerdict
from l4.verifier.traceability import rescue_ceiling
from l4.verifier.types import (
    CounterexampleRun,
    CriterionEvidence,
    CriterionOutcome,
    Finding,
    HumanVerdict,
    Severity,
    Verdict,
)

_WORST_FIRST = ("fail", "not_verifiable", "insufficient_evidence", "pass")
CAP_ONLY = "uncovered: the judge passed it, and only the per-test cap left it uncovered"  # L4-VER-055


def _cap_reason(trace: CriterionEvidence, cap: int, unit_size: int) -> str:
    """L4-VER-055: the judge passed the criterion and the only tests that trace it are candidates over the cap that
    did not count. Names the candidate with the fewest criteria, and why no answer of the judge could count it, or that
    the judge did not confirm it for this criterion."""
    first, *rest = sorted(trace.capped, key=lambda t: (t.over_cap, t.id))
    why = "; the judge did not confirm it for this criterion"
    if unit_size and first.over_cap > (ceiling := rescue_ceiling(unit_size, cap)):
        why = f"; it traces more than {ceiling} of the unit's {unit_size} criteria, the most the judge can make count"
    more = f" (+{len(rest)} more)" if rest else ""
    return (
        f"{CAP_ONLY}: {first.id} traces {first.over_cap} criteria, more than "
        f"verifier.max_criteria_per_test ({cap}){why}{more}"
    )


def pick_verdicts(judge: JudgeVerdict) -> dict[str, CriterionVerdict]:
    """One verdict per criterion id. A judge that lists an id twice gets its worst answer counted."""
    picked: dict[str, CriterionVerdict] = {}
    for item in judge.criteria:
        current = picked.get(item.id)
        if current is None or _WORST_FIRST.index(item.verdict) < _WORST_FIRST.index(current.verdict):
            picked[item.id] = item
    return picked


def aggregate_criterion(
    criterion_id: str,
    alias: str,
    judge: CriterionVerdict | None,
    counterexample: CounterexampleRun | None,
    *,
    trace: CriterionEvidence | None = None,
    human: HumanVerdict | None = None,
    require_traceability: bool = True,
    cap: int = 3,
    unit_size: int = 0,
) -> CriterionOutcome:
    def outcome(result: str, reason: str) -> CriterionOutcome:
        word = judge.verdict if judge is not None else None
        return CriterionOutcome(criterion_id, alias, result, word, reason, counterexample)  # type: ignore[arg-type]

    failing = [t.id for t in trace.tests if t.status in ("failed", "error")] if trace else []
    if trace is not None and (trace.state == "fail" or failing):
        return outcome("fail", f"a tracing test fails at head: {', '.join(failing[:3]) or 'see the matrix'}")
    if human is not None:
        who = f"{human.by}: {human.reason}" if human.reason else human.by
        if human.decision == "reject":
            return outcome("fail", f"rejected by {who}")
        return outcome("pass", f"accepted by {who}")
    usable = [t for t in trace.tests if t.status == "passed" and t.adequate] if trace else []
    if not usable:
        why = "no adequate discriminating test traces it"
        if trace is not None and trace.tests:
            why = "the tests that trace it are inadequate or did not pass"
        full = f"uncovered: {why}"
        if trace is not None and trace.capped and judge is not None and judge.verdict == "pass":
            full = _cap_reason(trace, cap, unit_size)
        if not require_traceability:
            return outcome("needs_human", f"{full}; sdd.require_traceability is off but S1 is not available")
        return outcome("needs_human", full)
    if trace is not None and trace.held:
        return outcome("needs_human", trace.held)
    if judge is None:
        return outcome("needs_human", "the judge gave no verdict for this criterion")
    if judge.verdict == "pass":
        return outcome("pass", "the judge passed it and a discriminating test passes")
    if judge.verdict == "fail":
        if counterexample is not None and counterexample.status == "reproduced":
            return outcome("disputed", "disputed: judge counterexample reproduced")
        why = counterexample.note if counterexample is not None and counterexample.note else "no counterexample ran"
        status = counterexample.status if counterexample is not None else "absent"
        return outcome("needs_human", f"judge fail counted as insufficient_evidence: counterexample {status} ({why})")
    return outcome("needs_human", f"the judge answered {judge.verdict}")


def judge_findings(judge: JudgeVerdict, *, known: Collection[str]) -> list[Finding]:
    """The judge's findings as `Finding`s; a criterion id the unit does not have is dropped, the finding is kept."""
    return [
        Finding(
            Severity(f.severity),
            f.title,
            f.detail,
            "judge",
            criterion=f.criterion if f.criterion in known else None,
            spec_gap=f.spec_gap,
            suggested_fix=f.suggested_fix,
        )  # fmt: skip
        for f in judge.findings
    ]


def aggregate_unit(findings: Sequence[Finding], criteria: Sequence[CriterionOutcome], holds: Sequence[str]) -> Verdict:
    if any(f.blocking and f.source in ("deterministic", "human", "feedback") for f in findings):
        return Verdict.FAIL
    if any(c.result == "fail" for c in criteria):
        return Verdict.FAIL
    if holds or any(c.result in ("needs_human", "disputed") for c in criteria) or any(f.blocking for f in findings):
        return Verdict.NEEDS_HUMAN
    return Verdict.PASS
