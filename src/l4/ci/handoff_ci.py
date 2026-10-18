"""What the repository's own CI says about the hand-off commit H, read one way for the sweep's CI duty and for the
guarded merge (L4-CI-012, L4-YOLO-042).

`read_handoff_ci` lists the jobs of H, defers while one is unfinished, calls H `not_run` when no job of the project ran
on it (the harness's own `l4` job does not count), and otherwise judges the red jobs against the base head's
(`l4.ci.repo_ci.evaluate_ci`). Forge errors propagate: the caller decides whether an unreadable CI waits or is retried.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from l4.ci.repo_ci import DEFAULT_IGNORE, evaluate_ci, unfinished
from l4.forge.base import JobResult

HandoffStatus = Literal["running", "green", "failed", "preexisting", "not_run"]

# L4-GHP-008: never green. A push made with the workflow's GITHUB_TOKEN starts no run.
NO_CHECK_RUN = (
    "no workflow ran on the hand-off commit; pushes made with GITHUB_TOKEN start no runs "
    "(use a token that does, or a GitHub App)"
)
ONLY_HARNESS_JOB = (
    "no workflow of the repository ran on the hand-off commit: its only check run is the harness's own l4 job"
)
NO_PIPELINE_JOB = "no pipeline of the project has a job on the hand-off commit"


class JobSource(Protocol):
    def list_pipeline_jobs(self, sha: str, *, settled: bool = False) -> Sequence[JobResult]: ...


@dataclass(frozen=True)
class HandoffCi:
    status: HandoffStatus
    head: str
    reason: str = (
        ""  # `not_run`: which case; `running`: "the base is" when the base head's jobs are the unfinished ones
    )
    failed: tuple[JobResult, ...] = ()  # red on H, not on the base
    preexisting: tuple[JobResult, ...] = ()  # red on H and on the base


def read_handoff_ci(forge: JobSource, head: str, base: str | None, platform: str) -> HandoffCi:
    jobs = list(forge.list_pipeline_jobs(head))
    if unfinished(jobs):
        return HandoffCi("running", head)
    if not [j for j in jobs if j.name not in DEFAULT_IGNORE]:
        reason = NO_PIPELINE_JOB if platform != "github" else (ONLY_HARNESS_JOB if jobs else NO_CHECK_RUN)
        return HandoffCi("not_run", head, reason)
    verdict = evaluate_ci(jobs, list(forge.list_pipeline_jobs(base, settled=True)) if base else [])
    if verdict.status == "running":
        return HandoffCi("running", head, "the base is")
    return HandoffCi(verdict.status, head, "", verdict.failed, verdict.preexisting)
