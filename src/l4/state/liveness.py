"""Whether a run that the ledger shows open is still working (L4-IMP-073, L4-QMD-011).

A `run.started` with no `run.finished` is a run that works, or one that died without a line. The rule that tells them
apart is shared by `l4 yolo status` (a plan whose run ended without a record) and `l4 questions` (an answer given while
a run works): an open run with a CI link is called ended when it is older than its job timeout plus a grace for clock
skew, and, when the age does not decide, when the forge says its CI run is completed. A run held for a person's
approval is not an end. Everything the forge adds is best effort: when it cannot be asked, the age alone decides.
"""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from l4.config.schema import L4Config, duration_seconds
from l4.exitcodes import L4Exit
from l4.forge.base import ForgeUnavailable
from l4.yolo.state import parse_time

if TYPE_CHECKING:
    from l4.state.status import OpenRun

log = logging.getLogger("l4.liveness")

END_GRACE_S = 300  # clock skew allowed on top of the job timeout
DEFAULT_JOB_TIMEOUT_S = 180 * 60  # the templates' `timeout-minutes`
APPROVAL_WAIT = "waiting for approval"  # what `Forge.ci_run_state` says of a run held for approval (B-m3)


class LazyForge:
    """The forge, built when first needed (`build`); None without a token or when it cannot be built (the read is best
    effort)."""

    def __init__(self, build: Callable[[], Any]) -> None:
        self._build, self._built, self._forge = build, False, None

    def get(self) -> Any:
        if not self._built:
            self._built = True
            try:
                self._forge = self._build()
            except (ForgeUnavailable, L4Exit, OSError) as exc:
                log.info("the forge cannot be asked (%s)", type(exc).__name__)
        return self._forge


def ended_why(cfg: L4Config, run: "OpenRun", forge: LazyForge, at: datetime) -> tuple[str | None, bool]:
    """`(why, waits)`: why the open run is called ended without a record (older than its job timeout, only with a CI
    link, or the forge says its CI run completed, asked only when the age does not decide); `waits` is true when the
    forge says the CI run is held for a person's approval, which is not an end. `at` is the time to measure with."""
    started = parse_time(run.started)
    if run.ci_url and started is not None:
        assumed = False
        if run.job_timeout_s:
            timeout = run.job_timeout_s
        elif cfg.ci.time_budget != "auto":
            timeout = duration_seconds(cfg.ci.time_budget)
        else:
            timeout, assumed = DEFAULT_JOB_TIMEOUT_S, True
        if (at - started).total_seconds() > timeout + END_GRACE_S:
            note = ", assumed" if assumed else ""
            return f"older than its job timeout ({timeout // 60} min{note}): likely the CI timeout", False
    if run.ci_url:
        found = forge.get()
        if found is not None:
            try:
                state, text = found.ci_run_state(run.ci_url)
            except Exception as exc:  # noqa: BLE001 - best effort: any failure leaves the rule unused
                log.info("the CI run was not read (%s)", type(exc).__name__)
                return None, False
            if state == "completed":
                return "its CI run is completed" + (f" ({text})" if text and text != "completed" else ""), False
            if state == "running" and text == APPROVAL_WAIT:
                return None, True
    return None, False


def unlinked_run_aged_out(run: "OpenRun", at: datetime) -> bool:
    """Whether an open run with no CI link is older than its job timeout (the default one when the ledger names none)
    plus the grace. `ended_why` leaves such a run alone, as `l4 yolo status` always has; a line that says a run still
    works (L4-QMD-011) uses this too, so that a local run that died is not named for ever."""
    started = parse_time(run.started)
    if run.ci_url or started is None:
        return False
    return (at - started).total_seconds() > (run.job_timeout_s or DEFAULT_JOB_TIMEOUT_S) + END_GRACE_S
