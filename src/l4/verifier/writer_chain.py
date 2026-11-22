"""The `verifier_agent` role as a chain (L4-VER-091): a call that one profile cannot answer is asked of the next one.

Step 4a (the audit writer, its collection retry and its lint retry) and step 5 (the UI test writer) ask the role for a
structured reply. A reply that is `error` (the run stopped at its output limit, a tool call that the permission rules
refused, any other adapter error that the run's own retries did not cure) is discarded and the same call is asked of
the next usable profile that is independent of the implementers, in the same run, as the step-9 judges do (L4-VER-015,
L4-VER-075). A usage limit cools the profile down and moves on the same way. A failed profile is skipped for the rest of
the round. An `invalid` reply and a `timeout` keep their handling: the callers decide, and no other profile is asked.
When no profile is left the last result is returned with a detail that names each failure, so that step 4a waits for
capacity with it and step 5 records `writer_failed` with it.
"""

import dataclasses
from collections.abc import Callable, Sequence
from typing import Any

from l4.agents.base import RunResult, Usage
from l4.agents.factory import Selected, WaitingCapacity
from l4.llm.agent_judge import LLMBackend, Msg, StructuredResult

ROLE = "verifier_agent"
MAX_DETAIL = 300  # of the detail the ledger records for a discarded call
MAX_FAILURE = 120  # of each failure in the summary a unit waits with

# `kind` of `availability.judge_error` for the role
LENGTH, PERMISSION, ERROR, LIMIT = "length", "permission", "error", "limit"


def failure_kind(result: StructuredResult) -> str:
    """Why a call was discarded: its reply stopped at the output limit, a tool call was refused, or any other error."""
    if result.length_stop:
        return LENGTH
    if result.run is not None and result.run.status == "permission_blocked":
        return PERMISSION
    return ERROR


def first_line(text: str, limit: int) -> str:
    lines = text.strip().splitlines()
    return (lines[0] if lines else "")[:limit]


class WriterChain:
    """An `LLMBackend` that walks `roles.verifier_agent`. `select()` gives the next usable profile that is independent
    of the implementers, with `skip` (shared by the steps of a round) read at every selection and raising
    `WaitingCapacity` when none is left; `open_backend(selected)` builds the tool-less backend of a profile;
    `on_limit(selected, run)` cools a profile that hit a usage limit and selects the next one, or raises
    `WaitingCapacity`. `failures` collects `<profile>: <kind>: <detail>` for the round; `emit(type, **data)` records
    the ledger events; `step` (`4a` or `5`) and `role` (`audit`, `ui_tests`) say whose call it is."""

    def __init__(
        self,
        select: Callable[[], Selected],
        open_backend: Callable[[Selected], LLMBackend],
        on_limit: Callable[[Selected, RunResult], Selected],
        skip: set[str],
        failures: list[str],
        emit: Callable[..., Any],
        step: str,
        role: str,
        redact: Callable[[str], str] = lambda text: text,
    ) -> None:
        self._select, self._open, self._on_limit = select, open_backend, on_limit
        self.skip, self.failures, self._emit = skip, failures, emit
        self._step, self._role, self._redact = step, role, redact
        self.current: Selected | None = None
        self._backend: LLMBackend | None = None
        try:
            self._move_to(select())
        except WaitingCapacity:
            if not self.failures:  # nothing failed in this round: there is no independent verifier, as before
                raise
            # an earlier step of the round used up the chain: the first call returns its summary

    @property
    def profile(self) -> str | None:
        return self.current.profile_name if self.current is not None else None

    def _move_to(self, selected: Selected) -> None:
        self.current, self._backend = selected, self._open(selected)

    def summary(self) -> str:
        return f"no profile of roles.{ROLE} could answer: " + "; ".join(self.failures)

    def complete_structured(
        self,
        system: str,
        messages: Sequence[Msg],
        json_schema: dict[str, Any],
        *,
        effort: str | None = None,
        max_tokens: int = 0,
        timeout_s: int = 600,
    ) -> StructuredResult:
        if self._backend is None:
            return StructuredResult("error", detail=self.summary())
        while True:
            assert self.current is not None and self._backend is not None
            result = self._backend.complete_structured(
                system, messages, json_schema, effort=effort, max_tokens=max_tokens, timeout_s=timeout_s
            )
            if result.status == "error":
                kind = failure_kind(result)
            elif result.status == "limit" and result.run is not None:
                kind = LIMIT
            else:  # ok, an invalid reply, a timeout (the caller's handling), or a limit with no run to cool down
                return result
            name = self.current.profile_name
            detail = first_line(self._redact(result.detail), MAX_DETAIL)  # redacted whole, then one line, then cut
            if kind != LIMIT:
                self._emit(
                    "availability.judge_error", role=ROLE, profile=name, kind=kind, detail=detail, step=self._step
                )
            self._cost(result, name)
            self.failures.append(f"{name}: {kind}: {first_line(detail, MAX_FAILURE)}")
            self.skip.add(name)
            try:
                if kind == LIMIT:
                    assert result.run is not None
                    chosen = self._on_limit(self.current, result.run)
                    self._record_limit(result.run)  # a limit that ends the chain is recorded by the unit's parking
                    self._move_to(chosen)
                else:
                    self._move_to(self._select())
            except WaitingCapacity:
                self.current = self._backend = None
                # its cost is recorded above: the caller must not add it to the step's own cost a second time
                return dataclasses.replace(result, detail=self.summary(), usage=Usage())

    def _record_limit(self, run: RunResult) -> None:
        """`availability.limit` as the step-9 judges record it (`Factory.on_limit` records `availability.fallback`
        only), so that progress shows the usage limit. A limit that ends the chain is not recorded here: the caller
        raises `RoleLimit` with it and the orchestrator records it once when it parks the unit."""
        if (limit := run.limit) is not None:
            self._emit(
                "availability.limit", tool=limit.tool, kind=limit.kind, source=limit.source, excerpt=limit.raw_excerpt
            )

    def _cost(self, result: StructuredResult, profile: str) -> None:
        """`budget.cost` of a discarded call: it was metered and paid for, and the caller never sees it."""
        usage = result.usage
        if usage.cost_usd:
            self._emit("budget.cost", usd=usage.cost_usd, profile=profile, role=self._role)
        if usage.credits:
            self._emit(
                "budget.cost", credits=round(usage.credits, 6), credits_source=usage.credits_source,
                profile=profile, role=self._role,
            )  # fmt: skip
