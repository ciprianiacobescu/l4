"""`l4 yolo review --worktree`: review the working tree before the push (review-resolution design D5, tasks 2.4 and
2.5). Contract only: the body comes in wave 2."""

from collections.abc import Sequence

from l4.context import AppContext
from l4.exitcodes import ExitCode


def run_review_worktree(app: AppContext, *, plan: str, fresh: Sequence[str], record: bool, no_run: bool) -> ExitCode:
    raise NotImplementedError
