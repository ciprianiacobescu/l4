"""What the project's own CI says about the hand-off commit H (forge-and-ci 2.44, L4-ARC-002 (d), SCN-ARC-14/19).

Pure. The jobs are `l4.forge.base.JobResult`s of the commit (GitLab's status words; GitHub's check runs are mapped
onto them). A job is told apart from the same job on the base by its `key`: on GitHub `<workflow file> / <job>`
(L4-CI-011), on GitLab its name. The harness's own job (`l4`) is ignored. A job is *red* when it failed and may not
fail. Anything still unfinished defers the decision: a running pipeline is not a failure. A job that is red on H and
on the base head is *pre-existing*, not this unit's; with no base pipeline, or none that has the job, it counts as new
(a unit should not hand off red; the cost is at most one fix round per H, which `max_fix_rounds` bounds). A job red on
H that has no finished attempt on the base head defers too; an earlier finished attempt there counts, so the base
pipeline the sweep itself runs in (the `l4` job starts at once, beside the project's jobs) does not hold the decision
back for ever.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from l4.forge.base import UNFINISHED, JobResult

DEFAULT_IGNORE = ("l4",)
CiStatus = Literal["running", "green", "failed", "preexisting"]


@dataclass(frozen=True)
class CiVerdict:
    status: CiStatus
    failed: tuple[JobResult, ...] = ()  # red on H, not on the base: the unit's to fix
    preexisting: tuple[JobResult, ...] = ()  # red on H and on the base


def _considered(jobs: Sequence[JobResult], ignore: Sequence[str]) -> list[JobResult]:
    return [j for j in jobs if j.name not in ignore]


def unfinished(jobs: Sequence[JobResult], ignore: Sequence[str] = DEFAULT_IGNORE) -> bool:
    return any(j.status in UNFINISHED for j in _considered(jobs, ignore))


def red_jobs(jobs: Sequence[JobResult], ignore: Sequence[str] = DEFAULT_IGNORE) -> list[JobResult]:
    """Failed and not `allow_failure`; `manual`, `skipped` and `canceled` are not red."""
    return [j for j in _considered(jobs, ignore) if j.status == "failed" and not j.allow_failure]


def evaluate_ci(
    head_jobs: Sequence[JobResult], base_jobs: Sequence[JobResult], ignore: Sequence[str] = DEFAULT_IGNORE
) -> CiVerdict:
    """The verdict on H's jobs against the base head's. `base_jobs` is only read when H has a red job, and only its
    jobs of the same names: one of them still unfinished defers (the caller passes the base head's newest finished
    attempt of each name, `list_pipeline_jobs(settled=True)`, so the pipeline the sweep runs in does not hide one)."""
    if unfinished(head_jobs, ignore):
        return CiVerdict("running")
    red = red_jobs(head_jobs, ignore)
    if not red:
        return CiVerdict("green")
    named = {j.key for j in red}  # only the base jobs H's red jobs name can say whether they are new
    if unfinished([j for j in base_jobs if j.key in named], ignore):
        return CiVerdict("running")
    base_red = {j.key for j in red_jobs(base_jobs, ignore)}
    failed = tuple(j for j in red if j.key not in base_red)
    preexisting = tuple(j for j in red if j.key in base_red)
    return CiVerdict("failed" if failed else "preexisting", failed, preexisting)
