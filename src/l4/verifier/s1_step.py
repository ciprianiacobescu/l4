"""Step 8's glue (SPEC 10.2 step 8, L4-VER-008), kept apart from the ladder: the evidence handed to System One per
criterion, the call with every failure turned into "unavailable" (SCN-VER-24: S1 is corroborating only, so a server that
is missing or down never stops a round), and the calibration rows.

The rows are written after step 9, because a row pairs `p` with the deterministic state and the judge's word of the same
criterion. Nothing here reads `p` to decide anything (D8).
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from l4.agents.factory import RoleUnavailable
from l4.config.schema import L4Config
from l4.llm.system_one import SystemOneBackend, SystemOneUnavailable
from l4.specs.base import Criterion
from l4.verifier.s1 import CalibrationContext, Evidence, S1Outcome, effective_budget, record_calibration, run_s1
from l4.verifier.types import CriterionEvidence, S1Record

MAX_EXCERPT_CHARS = 1_500
_WORD = re.compile(r"[a-z0-9]{4,}")


@dataclass(frozen=True)
class S1Wiring:
    open: Callable[[], SystemOneBackend]  # `RoleUnavailable` when no profile of `roles.s1_judge` is usable
    cache_file: Path  # $L4_CACHE/s1-calibration.jsonl


@dataclass
class S1Step:
    status: Literal["ok", "unavailable"]  # "ok": at least one criterion was judged
    note: str = ""
    records: list[S1Record] = field(default_factory=list)
    outcome: S1Outcome | None = None
    engine: str = ""
    model: str = ""
    server_version: str = ""


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def excerpt_for(criterion: Criterion, diff: str) -> str:
    """The file chunk of the diff that shares the most words (four letters or more) with the criterion; "" when none
    shares any. The selection is the best a deterministic rule can do: it only has to be reproducible."""
    wanted = _words(criterion.text)
    best, best_score = "", 0
    for chunk in re.split(r"(?m)^(?=diff --git )", diff):
        score = len(wanted & _words(chunk))
        if chunk.strip() and score > best_score:
            best, best_score = chunk, score
    return best[:MAX_EXCERPT_CHARS]


def evidence_for(
    criteria: Sequence[Criterion], trace: Sequence[CriterionEvidence], diff: str
) -> dict[str, Evidence]:
    tests = {e.criterion: tuple((t.id, t.status) for t in e.tests) for e in trace}
    return {c.id: Evidence(tests.get(c.id, ()), excerpt_for(c, diff)) for c in criteria}


def run_step(
    wiring: S1Wiring, cfg: L4Config, criteria: Sequence[Criterion], evidence: Mapping[str, Evidence]
) -> S1Step:
    try:
        backend = wiring.open()
    except RoleUnavailable as exc:
        return S1Step("unavailable", str(exc))
    engine = backend.engine
    try:
        with backend:  # laya-local starts `laya-serve` here and stops it on the way out
            outcome = run_s1(backend, criteria, evidence, budget=effective_budget(cfg, engine))
    except SystemOneUnavailable as exc:
        return S1Step("unavailable", f"{engine}: {exc}", engine=engine, model=backend.model)
    records = [
        S1Record(c.criterion, c.status, c.p, c.served_model, engine, c.reason, c.truncated, c.evidence)
        for c in outcome.criteria
    ]
    judged = sum(r.status == "ok" for r in records)
    first = next((r.reason for r in records if r.status == "unavailable"), "")
    note = f"{judged}/{len(records)} criteria judged by {engine}" + (f"; {first}" if first else "")
    status = "ok" if judged else "unavailable"
    return S1Step(status, note, records, outcome, engine, backend.model, backend.server_version)


def record_rows(
    step: S1Step,
    wiring: S1Wiring,
    *,
    run_file: Path,
    unit: str,
    run_id: str,
    round_no: int,
    deterministic: Mapping[str, str],
    judge: Mapping[str, str | None],
) -> int:
    """Appends one row per judged criterion to the runner's cache file and to this run's copy; the number of rows."""
    if step.outcome is None:
        return 0
    context = CalibrationContext(wiring.cache_file, run_file, unit, run_id, round_no)
    return record_calibration(
        step.outcome, context, model=step.model, deterministic=deterministic, judge=judge, engine=step.engine,
        server_version=step.server_version,
    )
