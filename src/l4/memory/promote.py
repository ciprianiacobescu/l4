"""`l4 lessons promote ID`: a person moves one inbox proposal into `lessons.md` (L4-KG-013, design D11), the human
promotion of L4-MEM-002 origin `human_edit`. The lesson text is the person's; this module only checks, shows, writes and
commits it.

The order is fixed, and every refusal is exit 2 before anything is written: `memory.enabled`, the proposal
(`l4.memory.inbox`), the checkout (`check_checkout`), the lesson and its scope on screen, a confirmation (`--yes`, or a
terminal), then `apply_candidates`, then the commit. The checkout must be the base branch or a branch that is not under
`forge.branch_prefix` (a person's commit to `.serena/memories/harness/` on a unit branch is a protected-path blocker,
`verifier/integrity.py`), with nothing staged and a clean, parseable lessons file, so the commit holds the lessons paths
and nothing else. The commit carries the person's git identity (from the config or from `GIT_AUTHOR_*` and
`GIT_COMMITTER_*`; git never guesses one, and the command exits 2 when it would have to) and no `L4-*` trailer: the
trailers mark harness commits, and a person made this one. It is never signed and runs no hook (`Git` turns hooks off).
Git is used read-only, plus `add` and `commit`; the module never touches the network (L4-KG-001).
Imported only by `l4.memory.cli`.
"""

import contextlib
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import click

from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.memory.curate import LessonCandidate, apply_candidates
from l4.memory.inbox import find_proposal, parse_proposal
from l4.memory.inject import read_lessons_file
from l4.memory.lessons import Lesson, LessonsFile, parse_lessons, render_lessons
from l4.vcs.errors import GitError
from l4.vcs.git import Git

EVIDENCE_SUFFIX = ".evidence.md"
IDENTITY_VARS = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")
STRICT_IDENTITY = (("user.useConfigOnly", "true"),)  # git then fails instead of guessing a name from the host


@dataclass(frozen=True)
class Promoted:
    """`paths` are the repository-relative lessons paths that changed; `commit` is the new sha, or None with
    `--no-commit`; `proposal` is the inbox file (deleted after a commit)."""

    lesson_id: str
    action: str
    paths: tuple[str, ...]
    archived: tuple[str, ...]
    commit: str | None
    proposal: Path


def _refuse(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, message)


def _is_terminal() -> bool:
    return sys.stdin.isatty()


def person_git(app: AppContext, git: Git | None = None) -> Git:
    """`git` with the person's identity variables put back. `Git` scrubs `GIT_AUTHOR_*` and `GIT_COMMITTER_*` (the
    harness's commits are the bot's), but this commit is the person's: an identity that lives only in the
    environment must reach it, or git would guess one from the host (review #6)."""
    git = git if git is not None else Git(app.repo, environ=app.environ)
    git.env.update({name: app.environ[name] for name in IDENTITY_VARS if app.environ.get(name)})
    return git


def check_checkout(app: AppContext, cfg: L4Config, git: Git, *, commit: bool = True) -> None:
    """Exit 2 with the reason, having written nothing, unless the checkout can take a promote commit."""
    if not cfg.memory.enabled:
        raise _refuse("memory.enabled is false: no lesson is written")
    head = git.run("rev-parse", "--abbrev-ref", "HEAD", check=False)
    branch = head.stdout.strip()
    if head.returncode != 0:
        raise _refuse("the repository has no commit yet: promote on the base branch")
    if branch == "HEAD":
        raise _refuse("HEAD is detached: promote on the base branch")
    prefix = cfg.forge.branch_prefix
    if branch.startswith(prefix) and branch != cfg.forge.base_branch:  # a base branch may sit under it (`l4/main`)
        raise _refuse(
            f"HEAD is on the unit branch {branch}: a person's commit to .serena/memories/harness/ on a unit branch "
            f"is a protected-path blocker. Promote on the base branch ({cfg.forge.base_branch})"
        )
    staged = [name for name in git.run("diff", "--cached", "--name-only", "-z").stdout.split("\0") if name]
    if staged:
        raise _refuse(f"{len(staged)} file(s) are staged ({staged[0]}, ...): commit or unstage them first")
    relative = cfg.memory.lessons_file
    differs = git.run("diff", "--name-only", "HEAD", "--", relative, check=False).stdout.strip()
    untracked = git.run("ls-files", "--others", "--exclude-standard", "--", relative, check=False).stdout.strip()
    if differs or untracked:
        raise _refuse(f"{relative} has changes that are not committed: commit your own edit first")
    text, problem = read_lessons_file(app.repo, relative)
    refusal = problem or next(iter(parse_lessons(text).problems), None)
    if refusal is not None:
        raise _refuse(f"{relative} has a problem, run `l4 lessons lint`: {refusal.message}")
    if commit:
        git = person_git(app, git)
        for var in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
            if git.run("var", var, check=False, config=STRICT_IDENTITY).returncode != 0:
                raise _refuse(
                    "git has no identity to commit with (it would only guess one): set user.name and user.email, "
                    "or GIT_AUTHOR_* and GIT_COMMITTER_*, or use --no-commit"
                )


def _scope(lesson: Lesson) -> str:
    if lesson.scope_globs:
        return ", ".join(lesson.scope_globs)
    if lesson.scope_kinds:
        return "task kinds: " + ", ".join(lesson.scope_kinds)
    return "every task"


def _show(app: AppContext, lesson: Lesson) -> None:
    out = [render_lessons(LessonsFile([lesson])).split("\n", 1)[1].rstrip("\n"), "", f"scope: {_scope(lesson)}"]
    click.echo(app.redactor.redact_text("\n".join(out)))


def _commit_lines(lid: str, paths: tuple[str, ...], proposal: str) -> tuple[str, str]:
    add = "git add -- " + " ".join(paths)
    return add, f'git commit -m "chore(memory): lesson {lid} promoted [skip ci]" -m "Promoted-from: {proposal}"'


def promote(
    app: AppContext, cfg: L4Config, lid: str, *, from_dir: str | Path | None = None, yes: bool = False,
    commit: bool = True,
) -> Promoted:  # fmt: skip
    """See the module docstring. Exit 2 on every refusal (nothing written); exit 1 if the commit itself fails after
    the files were written (the files stay, and the two git lines are printed)."""
    if not cfg.memory.enabled:
        raise _refuse("memory.enabled is false: no lesson is written")
    proposal = find_proposal(app.repo, lid, from_dir)
    lesson = parse_proposal(proposal, lid)
    git = person_git(app)
    check_checkout(app, cfg, git, commit=commit)
    _show(app, lesson)
    if not yes:
        if not _is_terminal():
            raise _refuse("there is no terminal to ask on: pass --yes to promote this lesson")
        if not click.confirm("Write this lesson?", default=False):
            raise _refuse("not promoted: nothing was written")
    candidate = LessonCandidate(
        lesson.dedupe_key, lesson.title, lesson.scope_globs, lesson.scope_kinds, lesson.source, lesson.body,
        "human_edit",
    )  # fmt: skip
    applied = apply_candidates(app.repo, cfg.memory, [candidate], writer=None, today=date.today())
    if not applied.outcomes:
        raise _refuse("nothing was written: the lessons file was not used")
    paths = tuple(applied.paths)
    archived = tuple(x.id for outcome in applied.outcomes for x in outcome.archived)
    action = applied.outcomes[0].action
    click.echo(f"lesson {lesson.id} {action}")
    for archived_id in archived:
        click.echo(f"archived {archived_id}")
    inbox_path = proposal.relative_to(app.repo).as_posix()
    if not commit:
        for line in _commit_lines(lesson.id, paths, inbox_path):
            click.echo(line)
        return Promoted(lesson.id, action, paths, archived, None, proposal)
    sha = _commit(git, lesson.id, paths, inbox_path)
    _discard(proposal)
    click.echo(f"committed {sha[:10]} chore(memory): lesson {lesson.id} promoted")
    return Promoted(lesson.id, action, paths, archived, sha, proposal)


def _commit(git: Git, lid: str, paths: tuple[str, ...], inbox_path: str) -> str:
    try:
        git.run("add", "--", *paths)
        staged = {n for n in git.run("diff", "--cached", "--name-only", "-z").stdout.split("\0") if n}
        extra = sorted(staged - set(paths))
        if extra:  # cannot happen after check_checkout; never commit more than the lessons paths
            git.run("reset", "--quiet", "--", *paths)
            raise _refuse(f"other changes are staged, not committing: {', '.join(extra[:5])}")
        git.run(
            "commit", "--quiet", "--no-verify", "--no-gpg-sign",
            "-m", f"chore(memory): lesson {lid} promoted [skip ci]", "-m", f"Promoted-from: {inbox_path}",
            config=STRICT_IDENTITY,
        )  # fmt: skip
        return git.run("rev-parse", "HEAD").stdout.strip()
    except GitError as exc:
        lines = "\n".join(_commit_lines(lid, paths, inbox_path))
        raise L4Exit(
            ExitCode.INTERNAL_ERROR,
            f"the lesson was written but the commit failed ({exc}); the proposal is kept. Run:\n{lines}",
        ) from None


def _discard(proposal: Path) -> None:
    """Delete the proposal and its evidence file; an empty inbox folder goes with them."""
    evidence = proposal.with_name(proposal.name[: -len(".md")] + EVIDENCE_SUFFIX)
    for path in (proposal, evidence):
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    with contextlib.suppress(OSError):  # rmdir refuses a folder with other files
        proposal.parent.rmdir()
