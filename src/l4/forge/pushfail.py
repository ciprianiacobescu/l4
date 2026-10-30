"""A failed push as one explained error instead of a traceback (SPEC 2.2): a credential or permission problem is the
environment's (exit 3), anything else, a non-fast-forward included, exit 1. A refusal by the server's hooks
(`! [remote rejected]`: a protected branch, a push rule) is the forge's, never a non-fast-forward (G12)."""

from collections.abc import Callable, Mapping
from pathlib import Path

from l4.config.schema import L4Config
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.pushurl import runner_rewrites_urls
from l4.vcs.git import GitError
from l4.vcs.push import (
    BranchGone,
    BranchKeepsMoving,
    BranchMoved,
    BranchRewritten,
    PushRejected,
    is_permission_failure,
    is_transient_push_failure,
)

# the lines git prints when the server's hooks (pre-receive, GitLab's push rules and branch protection) refuse a ref
_HOOK_REFUSAL = ("[remote rejected]", "pre-receive hook declined")
_LINES = 3
_SHOWN = 5  # paths named in a message of a moved branch


class PushFailed(L4Exit):
    """The push of the unit branch did not land; the message says why and never carries a token. `refused`: the
    server's hooks (a push rule, a protected branch) said no, so a repeat fails the same way until the forge changes.
    `transient`: the forge failed on its side (a server or network error) and the harness's own tries did not cure it;
    a later push should work (L4-LCK-001)."""

    def __init__(self, code: ExitCode, message: str, *, refused: bool = False, transient: bool = False) -> None:
        super().__init__(code, message)
        self.refused = refused
        self.transient = transient


def is_hook_refusal(stderr: str) -> bool:
    low = stderr.lower()
    return any(marker in low for marker in _HOOK_REFUSAL)


def _unit_of(branch: str) -> str:
    """`openspec:x` for the branch `l4/openspec/x` (the last two segments are framework and name); `<unit>` when the
    branch is not shaped like that."""
    parts = branch.split("/")
    return f"{parts[-2]}:{parts[-1]}" if len(parts) >= 3 else "<unit>"


def _commits(n: int) -> str:
    return f"{n} commit{'' if n == 1 else 's'}"


def _paths(paths: tuple[str, ...]) -> str:
    return ", ".join(paths[:_SHOWN]) + (f" (+{len(paths) - _SHOWN} more)" if len(paths) > _SHOWN else "")


def _gone_hint(branch: str) -> str:
    return (
        "the unit branch was deleted or moved on the forge since this run last saw it; it is never recreated "
        "or overwritten (the harness never forces). A person decides: restore the branch, or start the unit over "
        f"from the base with `l4 restart --unit {_unit_of(branch)} --reason TEXT` (L4-OPS-009)"
    )


def _lease_hint(exc: PushRejected, branch: str) -> str | None:
    """What a refused lease of the unit branch means, told apart with `git ls-remote` (L4-RACE-001, design D4); None
    for a refusal that nobody classified. Only a deleted or a rewritten branch is a person's decision to `l4 restart`:
    one that moved forward is taken up by the next run, which starts from the forge's branch."""
    later = "this run's work since its last push is not pushed. The next run starts from the forge's branch"
    if isinstance(exc, BranchGone):
        return _gone_hint(branch)
    if isinstance(exc, BranchKeepsMoving):
        tried = f"; the harness tried {exc.tries} times" if exc.tries > 1 else ""
        return (
            "the unit branch keeps moving on the forge (a person's answers arrive faster than the run can merge "
            f"them){tried}. The answers stay on the forge and the next run takes them; {later}"
        )
    if isinstance(exc, BranchMoved) and exc.refused:
        return (
            f"a person pushed {_commits(exc.commits)} to {branch} during this run, and the harness could not merge "
            f"their answers: {exc.refused}; {later}"
        )
    if isinstance(exc, BranchMoved) and exc.conflicts:
        return (
            f"a person pushed {_commits(exc.commits)} to {branch} during this run, and the harness could not merge "
            f"their answers to {_paths(exc.conflicts)} with this run's changes; {later}"
        )
    if isinstance(exc, BranchMoved):
        return (
            f"a person pushed {_commits(exc.commits)} to {branch} during this run that change {_paths(exc.paths)}; "
            f"the harness merges only answers to this unit's `questions.md`, and never into a hand-off, so {later}"
        )
    if isinstance(exc, BranchRewritten):
        seen = (
            f"{branch} was rewritten on the forge (its head no longer contains this run's last push)"
            if exc.expected
            else f"{branch} exists on the forge, where this run expected none"
        )
        return (
            f"{seen}; the harness never forces. A person decides: restore the branch, or start the unit over from "
            f"the base with `l4 restart --unit {_unit_of(branch)} --reason TEXT` (L4-OPS-009)"
        )
    return None


def push_platform(cfg: L4Config, environ: Mapping[str, str], repo: Path) -> str:
    """The forge a push of `repo` goes to: `forge.type`, `ci.platform`, the CI variables, then the host of `origin`."""
    from l4.forge.base import forge_platform
    from l4.forge.urls import origin_url

    return forge_platform(cfg, environ, origin_url(repo, environ))


def explain_push_failure(
    exc: GitError,
    *,
    branch: str,
    token_env: str,
    environ: Mapping[str, str],
    redact: Callable[[str], str],
    platform: str | None = None,
) -> PushFailed:
    """`platform` names the forge that refused (`forge_platform`); a caller that does not know it gets GitHub inside
    GitHub Actions and GitLab elsewhere (L4-ADO-004)."""
    if platform is None:
        platform = "github" if environ.get("GITHUB_ACTIONS") == "true" else "gitlab"
    lines = [line.strip() for line in exc.stderr.strip().splitlines()[:_LINES]]
    reason = " | ".join(lines) or f"git exit {exc.returncode}"
    head = f"push of {branch} to origin failed: {reason}"
    if isinstance(exc, PushRejected) and (hint := _lease_hint(exc, branch)) is not None:
        return PushFailed(ExitCode.INTERNAL_ERROR, redact(f"{head}. {hint}"))
    if isinstance(exc, PushRejected) and "stale info" in exc.stderr:  # a lease refusal nobody classified
        return PushFailed(ExitCode.INTERNAL_ERROR, redact(f"{head}. {_gone_hint(branch)}"))
    if isinstance(exc, PushRejected):
        hint = (
            "the branch moved on the forge (non-fast-forward): a human pushed; the next run continues from it "
            "(the harness never forces)"
        )
        return PushFailed(ExitCode.INTERNAL_ERROR, redact(f"{head}. {hint}"))
    if is_transient_push_failure(exc.stderr):  # before the hook check: GitHub's server error is `[remote rejected]` too
        tried = f"; the harness tried {exc.tries} times" if exc.tries > 1 else ""
        hint = (
            f"The forge failed on its side (a server or network error, not a refusal){tried}. "
            "Nothing is wrong with the branch or the credential: a later push should work"
        )
        return PushFailed(ExitCode.INTERNAL_ERROR, redact(f"{head}. {hint}"), transient=True)
    if is_hook_refusal(exc.stderr):
        if not is_permission_failure(exc.stderr):
            # a push rule: the server's reason is in `head`
            return PushFailed(ExitCode.INTERNAL_ERROR, redact(head), refused=True)
        hint = (
            f"the forge refused the push (protected branch or push rule): the branch may be protected against the "
            f"role of {token_env}, or a rule of the project rejected it"
        )
        return PushFailed(ExitCode.DOCTOR_FAILED, redact(f"{head}. {hint}"), refused=True)
    if not is_permission_failure(exc.stderr):
        return PushFailed(ExitCode.INTERNAL_ERROR, redact(head))
    if platform == "github":
        hint = (
            f"the forge refused the credential: {token_env} must be a token that can push to the repository: "
            "`contents: write` and `pull-requests: write` (the workflow's `permissions`, or a fine-grained token "
            "with those), and the branch must not be protected against it"
        )
    else:
        hint = (
            f"the forge refused the credential: {token_env} must be a project access token with the "
            "write_repository (and api) scopes and the Developer role or higher, and the branch must not be "
            "protected against it"
        )
    if not environ.get(token_env):
        hint += f". {token_env} is not set"
        if environ.get("GITLAB_CI") == "true" and runner_rewrites_urls(environ):
            hint += ": the runner rewrites the origin URL to carry the job token, which cannot push"
    return PushFailed(ExitCode.DOCTOR_FAILED, redact(f"{head}. {hint}"))
