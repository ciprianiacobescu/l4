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

from l4.ci.repo_ci import all_skipped, blocked_jobs, considered, evaluate_ci, unfinished
from l4.forge.base import JobResult

HandoffStatus = Literal["running", "green", "failed", "preexisting", "not_run", "blocked"]

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
    whose required checks GitHub's rules list (only a forge that has `required_checks` is asked)."""
    jobs = list(forge.list_pipeline_jobs(head))
    if unfinished(jobs):
        return HandoffCi("running", head)
    in_window = ready_at is not None and (now or datetime.now(UTC)) - ready_at < WINDOW
    if not considered(jobs) or all_skipped(jobs):
        if not considered(jobs):
            reason = NO_PIPELINE_JOB if platform != "github" else (ONLY_HARNESS_JOB if jobs else NO_CHECK_RUN)
        else:
            reason = ALL_SKIPPED
        return HandoffCi("running", head, NOT_CREATED_YET) if in_window else HandoffCi("not_run", head, reason)
    verdict = evaluate_ci(jobs, list(forge.list_pipeline_jobs(base, settled=True)) if base else [])
    if verdict.status == "running":
        return HandoffCi("running", head, BASE_RUNNING)
    if verdict.status == "failed":
        return HandoffCi("failed", head, "", verdict.failed, verdict.preexisting)
    if held := blocked_jobs(jobs):
        return HandoffCi("blocked", head, "", blocked=tuple(held), preexisting=verdict.preexisting)
    missing = _missing_required(forge, jobs, platform, base_branch)
    if missing:
        names = ", ".join(missing)
        if in_window:
            return HandoffCi("running", head, f"the required check {names} has not been reported on it yet")
        return HandoffCi("not_run", head, f"the required check {names} was never reported on it")
    return HandoffCi(verdict.status, head, "", (), verdict.preexisting)


def _missing_required(forge: object, jobs: Sequence[JobResult], platform: str, base_branch: str | None) -> list[str]:
    """The base branch's required status checks (GitHub) that H has reported neither as a check run nor as a status."""
    ask = getattr(forge, "required_checks", None)
    if platform != "github" or base_branch is None or ask is None:
        return []
    reported = {j.name for j in jobs}
    return [name for name in ask(base_branch) if name not in reported]
