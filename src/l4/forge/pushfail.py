"""A failed push as one explained error instead of a traceback (SPEC 2.2): a credential or permission problem is the
environment's (exit 3), anything else, a non-fast-forward included, exit 1. A refusal by the server's hooks
(`! [remote rejected]`: a protected branch, a push rule) is the forge's, never a non-fast-forward (G12)."""

from collections.abc import Callable, Mapping
from pathlib import Path

from l4.config.schema import L4Config
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.pushurl import runner_rewrites_urls
from l4.vcs.git import GitError
from l4.vcs.push import PushRejected, is_permission_failure, is_transient_push_failure

# the lines git prints when the server's hooks (pre-receive, GitLab's push rules and branch protection) refuse a ref
_HOOK_REFUSAL = ("[remote rejected]", "pre-receive hook declined")
_LINES = 3


class PushFailed(L4Exit):
    """The push of the unit branch did not land; the message says why and never carries a token. `refused`: the
    server's hooks (a push rule, a protected branch) said no, so a repeat fails the same way until the forge changes.
    `transient`: the forge failed on its side (a server or network error) and the harness's own tries did not cure it;
    the next run pushes again (L4-LCK-001)."""

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
    if isinstance(exc, PushRejected) and "stale info" in exc.stderr:
        hint = (
            "the unit branch was deleted or moved on the forge since this run last saw it; it is never recreated "
            "or overwritten (the harness never forces). A person decides: restore the branch, or start the unit over "
            f"from the base with `l4 restart --unit {_unit_of(branch)} --reason TEXT` (L4-OPS-009)"
        )
        return PushFailed(ExitCode.INTERNAL_ERROR, redact(f"{head}. {hint}"))
    if isinstance(exc, PushRejected):
        hint = (
            "the branch moved on the forge (non-fast-forward): a human pushed; the next run continues from it "
            "(the harness never forces)"
        )
        return PushFailed(ExitCode.INTERNAL_ERROR, redact(f"{head}. {hint}"))
    if is_transient_push_failure(exc.stderr):  # before the hook check: GitHub's server error is `[remote rejected]` too
        hint = (
            "The forge failed on its side (a server or network error, not a refusal); the harness tried again. "
            "Nothing is wrong with the branch or the credential: the next run pushes again"
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
