"""What the repository's own CI says about the hand-off commit H, read one way for the sweep's CI duty and for the
guarded merge (L4-CI-012..015, L4-YOLO-042).

`read_handoff_ci` lists the jobs of H (check runs, workflow runs and commit statuses on GitHub, pipeline jobs on
GitLab), defers while one is unfinished, and calls H `not_run` when no job of the project ran on it (the harness's own
`l4` job does not count) or every one was skipped. CI that may not exist yet is not `not_run`: within `WINDOW` of the
hand-off, "no job" and a required check that H has not reported are `running`. Cancelled and held jobs are `blocked`
(neither green nor a fix round). Otherwise the red jobs are judged against the base head's
(`l4.ci.repo_ci.evaluate_ci`). Forge errors propagate: the caller decides whether an unreadable CI waits or is retried.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from l4.ci.github import WORKFLOW_RELPATH
from l4.ci.repo_ci import all_skipped, blocked_jobs, considered, evaluate_ci, red_jobs, resolve_twins, unfinished
from l4.forge.base import UNFINISHED, JobResult

WORKFLOW_FILE = WORKFLOW_RELPATH.rsplit("/", 1)[-1]  # `l4.yml`

HandoffStatus = Literal["running", "green", "failed", "preexisting", "not_run", "blocked", "unreported"]

MAX_NAMED = 5  # unfinished jobs named in a wait
MAX_SKEW = timedelta(
    minutes=5
)  # how far ahead of the read a `pr.ready` time may be and still be taken as the read time
REQUIRED_UNREADABLE = "the required checks of the base branch could not be read"
WINDOW = timedelta(minutes=10)  # how long after the hand-off "no CI yet" may still be CI that is being created (F2)

# L4-GHP-008: never green. A push made with the workflow's GITHUB_TOKEN starts no run.
NO_CHECK_RUN = (
    "no workflow ran on the hand-off commit; pushes made with GITHUB_TOKEN start no runs "
    "(use a token that does, or a GitHub App)"
)
ONLY_HARNESS_JOB = (
    "no workflow of the repository ran on the hand-off commit: its only check run is the harness's own l4 job"
)
NO_PIPELINE_JOB = "no pipeline of the project has a job on the hand-off commit"
ALL_SKIPPED = "every job of the repository on the hand-off commit was skipped"
NOT_CREATED_YET = "no CI of the repository is listed for it yet, and it was handed off less than 10 minutes ago"
BASE_RUNNING = "the base head's CI is unfinished"


class JobSource(Protocol):
    def list_pipeline_jobs(self, sha: str, *, settled: bool = False) -> Sequence[JobResult]: ...


@dataclass(frozen=True)
class HandoffCi:
    status: HandoffStatus
    head: str
    reason: str = ""  # `not_run`: which case; `running`: why (the base head's jobs, no CI yet, a required check)
    failed: tuple[JobResult, ...] = ()  # red on H, not on the base
    preexisting: tuple[JobResult, ...] = ()  # red on H and on the base
    blocked: tuple[JobResult, ...] = ()  # cancelled or held: re-run them
    warning: str = ""  # a limit of the read that the person should hear of (the required checks were unreadable)
    window_s: float | None = None  # `NOT_CREATED_YET` with no required check named: the seconds left of the window


def _unfinished_reason(jobs: Sequence[JobResult]) -> str:
    """The keys of the unfinished jobs, at most five, then `+K`: what the wait is for (m4)."""
    keys = sorted(j.key for j in considered(jobs) if j.status in UNFINISHED)
    shown = keys[:MAX_NAMED]
    more = f", +{len(keys) - MAX_NAMED}" if len(keys) > MAX_NAMED else ""
    return f"unfinished: {', '.join(shown)}{more}"


def window_remaining(ready_at: datetime | None, now: datetime) -> float | None:
    """The seconds until `WINDOW` after the hand-off ends (zero or less once it has). A time a little ahead of the read
    (a fast clock) is the read time; one far ahead (forged) is no time at all: the effect of a bad `pr.ready` is
    bounded."""
    if ready_at is None:
        return None
    if ready_at > now:
        if ready_at - now > MAX_SKEW:
            return None
        ready_at = now
    return (ready_at + WINDOW - now).total_seconds()


def _in_window(ready_at: datetime | None, now: datetime) -> bool:
    left = window_remaining(ready_at, now)
    return left is not None and left > 0


def _can_start_ci(forge: JobSource, base: str | None, required: list[str]) -> bool:
    """False only when GitHub shows that nothing can be on its way: no workflow but the harness's own, no check that the
    base branch requires, and no CI on the base head, as a workflow, an app's check run or a commit status (m7, X2).
    Anything unknown keeps the window."""
    files = getattr(forge, "workflow_files", None)
    if files is None or required:
        return True
    listed = files()
    if listed is None or any(f != WORKFLOW_FILE for f in listed):
        return True
    return bool(base and considered(forge.list_pipeline_jobs(base)))


def _required(forge: object, base_branch: str | None) -> tuple[list[str], bool]:
    ask = getattr(forge, "required_checks", None)
    return ask(base_branch) if ask is not None and base_branch is not None else ([], False)


def read_handoff_ci(
    forge: JobSource,
    head: str,
    base: str | None,
    platform: str,
    *,
    base_branch: str | None = None,
    ready_at: datetime | None = None,
    now: datetime | None = None,
) -> HandoffCi:
    """`ready_at` is the time of the recorded `pr.ready` (None: unknown, so no window); `base_branch` names the branch
    whose required checks GitHub lists (only a forge that has `required_checks` is asked). The base head's jobs are read
    only when H has a red job: that is the only time the comparison matters."""
    jobs = resolve_twins(list(forge.list_pipeline_jobs(head)))
    if unfinished(jobs):
        return HandoffCi("running", head, _unfinished_reason(jobs))
    now = now or datetime.now(UTC)
    window = _in_window(ready_at, now)
    if not considered(jobs) or all_skipped(jobs):
        if not considered(jobs):
            reason = NO_PIPELINE_JOB if platform != "github" else (ONLY_HARNESS_JOB if jobs else NO_CHECK_RUN)
        else:
            reason = ALL_SKIPPED
        names, unreadable = _required(forge, base_branch)
        warning = REQUIRED_UNREADABLE if unreadable else ""
        if window and _can_start_ci(forge, base, names):
            # a named required check ends `unreported` after the window, so there is nothing to wait for
            left = None if names else window_remaining(ready_at, now)
            return HandoffCi("running", head, NOT_CREATED_YET, warning=warning, window_s=left)
        if missing := ", ".join(n for n in names if n not in {j.name for j in jobs}):
            return HandoffCi("unreported", head, missing, warning=warning)  # a required check, and nothing reported
        return HandoffCi("not_run", head, reason, warning=warning)
    base_jobs = list(forge.list_pipeline_jobs(base, settled=True)) if base and red_jobs(jobs) else []
    verdict = evaluate_ci(jobs, base_jobs)
    if verdict.status == "running":
        return HandoffCi("running", head, BASE_RUNNING)
    if verdict.status == "failed":
        return HandoffCi("failed", head, "", verdict.failed, verdict.preexisting)
    names, unreadable = _required(forge, base_branch)
    warning = REQUIRED_UNREADABLE if unreadable else ""
    if held := blocked_jobs(jobs):
        return HandoffCi("blocked", head, "", blocked=tuple(held), preexisting=verdict.preexisting, warning=warning)
    reported = {j.name for j in jobs}
    if missing := ", ".join(n for n in names if n not in reported):
        if window:
            return HandoffCi(
                "running", head, f"the required check {missing} has not been reported on it yet", warning=warning
            )
        return HandoffCi("unreported", head, missing, warning=warning)
    return HandoffCi(verdict.status, head, "", (), verdict.preexisting, warning=warning)
