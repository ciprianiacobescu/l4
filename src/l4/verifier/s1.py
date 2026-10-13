"""Step 8 (SPEC 10.2, L4-VER-002 step 8, L4-VER-008): one System-One `noul` question per criterion over a compact
state, recorded for calibration and never used to decide (plan D8: a Laya `p` changes no verdict).

The state is the criterion text, the tests that trace it with their status, and an excerpt; only the excerpt is cut
to fit the budget. A state that does not fit without it makes that criterion `unavailable`, and so does a reply that is
not a usable answer; after the first transport or HTTP error the rest are not tried (each would wait out its own
timeout), and aggregation goes on (SCN-VER-24). Calibration lines carry the sha256 of the state as sent (redacted), not
the state: the full request is in the backend's own log.
M1: verifier 4.4 (the traceability-off judgment row), 4.3's human-outcome fill on merge.
"""

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from l4.clarifier.router import approx_tokens, trim_state
from l4.clarifier.s1_decisions import question_text
from l4.config.schema import L4Config
from l4.llm.system_one import Question, Reply, SystemOneBackend, SystemOneBadAnswer, SystemOneUnavailable
from l4.specs.base import Criterion

QUESTION = "Does this evidence show that the criterion is satisfied?"
QUESTION_ID = "p"
CHOICE_ID = "evidence"
QUESTION_SET = "criterion-s1@1"  # bump with any change to the questions below: thresholds belong to a version
QUESTIONS = {
    QUESTION_ID: Question(
        "noul", QUESTION,
        {"true": "A passing test that exercises this criterion's outcome, or code that plainly does it.",
         "false": "A failing, missing or unrelated test, or nothing that bears on the criterion."},
    ),
    CHOICE_ID: Question(
        "choice", "Which describes the evidence for the criterion?",
        {"implemented": "The evidence shows the criterion's outcome happening.",
         "contradicted": "The evidence shows something else happening, or a test of the outcome failing.",
         "not_implemented": "The evidence shows no sign of the behaviour.",
         "unrelated": "The evidence is about something other than this criterion."},
    ),
}  # fmt: skip
Status = Literal["ok", "unavailable"]


@dataclass(frozen=True)
class Evidence:
    tests: Sequence[tuple[str, str]] = ()  # (test id, status) of the tests that trace the criterion
    excerpt: str = ""  # the part of the diff or the source that bears on it


@dataclass(frozen=True)
class CriterionS1:
    criterion: str
    status: Status
    p: float | None = None
    reason: str = ""
    truncated: bool = False
    state_sha256: str = ""
    question: str = QUESTION
    evidence: dict[str, float] | None = None  # the 4-way choice's probabilities; recorded only, never used
    served_model: str = ""  # as the reply says (Jev answers `jev-1.13.0` to `jev-latest`)
    state_tokens: int | None = None  # the server's own count (Laya's `usage.state_tokens`)
    server_truncated: bool | None = None  # the server cut the state to its window (`usage.truncated`)


@dataclass
class S1Outcome:
    criteria: list[CriterionS1] = field(default_factory=list)

    @property
    def status(self) -> Status:
        return "ok" if all(c.status == "ok" for c in self.criteria) else "unavailable"


def _noul(reply: Reply, qid: str) -> float:
    answer = reply.answers.get(qid)
    value = answer.get("noul") if isinstance(answer, dict) and answer.get("type") == "noul" else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SystemOneBadAnswer(f"no noul answer for question {qid}")
    if not 0.0 <= float(value) <= 1.0:
        raise SystemOneBadAnswer(f"noul answer for question {qid} is outside 0..1")
    return float(value)


def _choice(reply: Reply, qid: str) -> dict[str, float] | None:
    """The choice's probabilities, or None: only `p` is needed for a criterion to count as judged."""
    answer = reply.answers.get(qid)
    odds = answer.get("probabilities") if isinstance(answer, dict) and answer.get("type") == "choice" else None
    numbers = [isinstance(v, int | float) and not isinstance(v, bool) for v in odds.values()] if odds else [False]
    if not isinstance(odds, dict) or not all(numbers):
        return None
    return {str(k): float(v) for k, v in odds.items()}


def _usage(reply: Reply, key: str, kind: type) -> Any:
    value = reply.usage.get(key)
    return value if isinstance(value, kind) and (kind is bool or not isinstance(value, bool)) else None


def effective_budget(cfg: L4Config, engine: str = "laya-local") -> int:
    """The state budget for the backend's engine (`SystemOneBackend.engine`): only Jev lifts the Laya window cap."""
    return cfg.verifier.s1.budget(engine)


def _render(criterion: Criterion, tests: Sequence[tuple[str, str]], excerpt: str) -> str:
    listed = "\n".join(f"{test_id}: {status}" for test_id, status in tests) or "(no test traces it)"
    text = f"Criterion {criterion.id}:\n{criterion.text.strip()}\n\nTests:\n{listed}"
    return f"{text}\n\nExcerpt:\n{excerpt}" if excerpt else text


def _renderer(criterion: Criterion, tests: Sequence[tuple[str, str]]) -> Callable[[Sequence[str]], str]:
    return lambda parts: _render(criterion, tests, parts[0])


def run_s1(
    backend: SystemOneBackend,
    criteria: Sequence[Criterion],
    evidence: Mapping[str, Evidence],
    *,
    budget: int,
) -> S1Outcome:
    """The backend has to be started by the caller (`with backend:`); not started counts as server trouble."""
    out = S1Outcome()
    down = ""
    reserve = question_text(QUESTIONS)  # the longest question of the request (the 4-way choice), not just `p`
    for criterion in criteria:
        seen = evidence.get(criterion.id, Evidence())
        if down:
            out.criteria.append(CriterionS1(criterion.id, "unavailable", reason=f"not asked: {down} earlier"))
            continue
        base = _render(criterion, seen.tests, "")
        if approx_tokens(base + reserve) > budget:
            reason = f"the state does not fit {budget} tokens even without the excerpt"
            out.criteria.append(CriterionS1(criterion.id, "unavailable", reason=reason))
            continue

        render = _renderer(criterion, seen.tests)
        state = trim_state(render, [seen.excerpt], instruction=reserve, max_tokens=budget)
        truncated = state != render([seen.excerpt])
        sha = hashlib.sha256(backend.wire_state(state).encode("utf-8")).hexdigest()  # what was sent
        try:
            reply = backend.query(state, QUESTIONS)
            p = _noul(reply, QUESTION_ID)
        except SystemOneBadAnswer as exc:  # the server works: only this criterion is lost
            out.criteria.append(CriterionS1(criterion.id, "unavailable", reason=str(exc), state_sha256=sha))
            continue
        except SystemOneUnavailable as exc:
            down = str(exc)
            out.criteria.append(CriterionS1(criterion.id, "unavailable", reason=down, state_sha256=sha))
            continue
        out.criteria.append(
            CriterionS1(
                criterion.id, "ok", p, truncated=truncated, state_sha256=sha, evidence=_choice(reply, CHOICE_ID),
                served_model=reply.model, state_tokens=_usage(reply, "state_tokens", int),
                server_truncated=_usage(reply, "truncated", bool),
            )
        )  # fmt: skip
    return out


@dataclass(frozen=True)
class CalibrationContext:
    cache_file: Path  # $L4_CACHE/s1-calibration.jsonl: every run of the runner
    run_file: Path  # .l4-out/s1/<run-id>.jsonl: this run's copy, uploaded as a CI artefact
    unit: str
    run_id: str
    round: int


def record_calibration(
    outcome: S1Outcome,
    context: CalibrationContext,
    *,
    model: str,
    deterministic: Mapping[str, str],
    judge: Mapping[str, str | None],
    engine: str = "",
    server_version: str = "",
) -> int:
    """One line per criterion that got a `p`, appended to both files; nothing for the unavailable ones, so a down
    server leaves no files. `deterministic` and `judge` are the other outcomes of the same criterion, which the
    calibration set pairs the `p` with. Returns the number of lines."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        json.dumps({
            "ts": now, "unit": context.unit, "run_id": context.run_id, "round": context.round,
            "criterion": c.criterion, "state_sha256": c.state_sha256, "question": c.question, "p": c.p,
            "question_set": QUESTION_SET, "evidence": c.evidence, "served_model": c.served_model, "engine": engine,
            "model": model, "server_version": server_version, "state_tokens": c.state_tokens,
            "server_truncated": c.server_truncated, "deterministic": deterministic.get(c.criterion),
            "judge": judge.get(c.criterion),
        }, ensure_ascii=False)
        for c in outcome.criteria
        if c.status == "ok"
    ]  # fmt: skip
    if lines:
        for path in (context.cache_file, context.run_file):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
    return len(lines)
