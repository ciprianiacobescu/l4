"""A person's answers pushed while a run works are merged, not lost (L4-RACE-001, SCN-IMP-22).

`Git.push_branch` leases the push of the unit branch on what the run last saw. When a person's `l4 questions` push
moved the branch (`BranchMoved`) and every file the new commits change is an answer file, `push_merging` merges the
remote head into HEAD with a harness commit, lets the caller scan the outgoing commits again, and pushes under a lease
on the fetched head: at most `PUSH_TRIES` pushes in all, `PUSH_WAITS` apart, then `BranchKeepsMoving`. A commit that
changes anything else is never merged (a person's code merged on the second parent would pass for the harness's own in
the walkers that follow the first parent): `BranchMoved` with the other files. Nothing is ever forced.
"""

import logging
import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

from l4 import cancel
from l4.vcs.git import PUSH_TRIES, PUSH_WAITS, Git, GitResult
from l4.vcs.merge import MergeRefused, Resolvers, merge_commit_into
from l4.vcs.push import BranchKeepsMoving, BranchMoved
from l4.vcs.trailers import CommitTrailers

log = logging.getLogger("l4.vcs")

# what `l4 questions answer|accept|dismiss` writes (`l4.specs.questions.QUESTIONS_FILENAME`, which specs own)
ANSWER_FILE = "questions.md"
_FIX_SUFFIX = re.compile(r"-fix-\d+")


@dataclass(frozen=True)
class AnswerMerge:
    """What `push_merging` needs from the caller. `unit_rel`: the unit's folder, relative to the repository (a fix
    unit's folder sits beside it as `<unit_rel>-fix-<n>`). `trailers`: those of the merge commit (a strict harness
    commit, no task, test or step key). `rescan` runs after a merge and before the push that follows (the secret scan
    of the outgoing commits) and raises to stop it. `merged(remote_head, commits, paths)` tells the caller what was
    merged, for the ledger. `keep_dirty` and `config` are those of `merge_commit_into`."""

    unit_rel: str
    trailers: CommitTrailers
    resolvers: Resolvers
    rescan: Callable[[], None]
    merged: Callable[[str, int, tuple[str, ...]], None] | None = None
    keep_dirty: Collection[str] = ()
    config: Sequence[tuple[str, str]] = ()


def is_answer_file(git: Git, unit_rel: str, path: str) -> bool:
    """The `questions.md` of the unit's folder, or of one of its fix-unit folders that this branch holds."""
    if path == f"{unit_rel}/{ANSWER_FILE}":
        return True
    folder, _, leaf = path.rpartition("/")
    if leaf != ANSWER_FILE or not folder.startswith(unit_rel) or not _FIX_SUFFIX.fullmatch(folder[len(unit_rel) :]):
        return False
    return git.run("cat-file", "-e", f"HEAD:{path}", check=False).returncode == 0


def _only_answers(git: Git, moved: BranchMoved, answers: AnswerMerge) -> None:
    others = [p for p in moved.paths if p in moved.irregular or not is_answer_file(git, answers.unit_rel, p)]
    if others:
        raise BranchMoved(moved, moved.remote_head, others, moved.commits, irregular=moved.irregular)


def _merge(git: Git, remote: str, branch: str, moved: BranchMoved, answers: AnswerMerge) -> None:
    n = moved.commits
    name = answers.trailers.unit.partition(":")[2] or answers.trailers.unit
    message = f"chore({name}): merge {n} answer commit{'' if n == 1 else 's'} from the forge [skip ci]"
    try:
        result = merge_commit_into(
            git, moved.remote_head, message=message, trailers=answers.trailers, resolvers=answers.resolvers,
            keep_dirty=answers.keep_dirty, config=answers.config, label="answer commits",
        )  # fmt: skip
    except MergeRefused as exc:  # an L4Exit: for the push it is a failed push, which `Orchestrator.push` explains
        raise BranchMoved(
            moved, moved.remote_head, moved.paths, moved.commits, irregular=moved.irregular, refused=str(exc)
        ) from None
    if result.kind == "conflict":
        raise BranchMoved(moved, moved.remote_head, moved.paths, moved.commits, result.files, moved.irregular)
    git.note_remote_head(remote, branch, moved.remote_head)  # the next lease: the head that was merged
    if result.kind == "merged" and answers.merged is not None:
        answers.merged(moved.remote_head, n, moved.paths)
    answers.rescan()


def push_merging(
    git: Git, remote: str, branch: str, answers: AnswerMerge, *, config: Sequence[tuple[str, str]] = ()
) -> GitResult:
    """See the module docstring. Every try but the last that finds the branch moved forward by answers waits, looks at
    the branch again (more answers may have come), merges and scans, then pushes."""
    tries = 0
    while True:
        tries += 1
        try:
            return git.push_branch_once(remote, branch, config=config)
        except BranchMoved as moved:
            _only_answers(git, moved, answers)
            if tries >= PUSH_TRIES:
                keeps = BranchKeepsMoving(moved, moved.remote_head, moved.paths, moved.commits)
                keeps.tries = tries  # the pushes made, not the inner count of the last one
                raise keeps from None
            wait = PUSH_WAITS[tries - 1]
            log.warning(
                "%s moved on the forge (%d commit%s of answers); merging them in %gs (try %d of %d)",
                branch, moved.commits, "" if moved.commits == 1 else "s", wait, tries + 1, PUSH_TRIES,
            )  # fmt: skip
            git.pause(wait)
            cancel.check()
            now = git.classify_lease(remote, branch, moved, config=config)
            if isinstance(now, BranchMoved):
                moved = now
                _only_answers(git, moved, answers)
            elif now is not moved:
                raise now from None  # gone or rewritten during the wait
            _merge(git, remote, branch, moved, answers)
