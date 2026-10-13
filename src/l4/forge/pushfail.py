"""A failed push as one explained error instead of a traceback (SPEC 2.2): a credential or permission problem is the
environment's (exit 3), anything else, a non-fast-forward included, exit 1. A refusal by the server's hooks
(`! [remote rejected]`: a protected branch, a push rule) is the forge's, never a non-fast-forward (G12)."""

from collections.abc import Callable, Mapping

from l4.exitcodes import ExitCode, L4Exit
from l4.forge.pushurl import runner_rewrites_urls
from l4.vcs.git import GitError
from l4.vcs.push import PushRejected

# what git and GitLab say when the credential is missing, wrong or too weak (matched on lowercased stderr)
_DENIED = (
    "not allowed to push", "authentication failed", "http basic: access denied", "could not read username",
    "could not read password", "permission denied", "the requested url returned error: 401",
    "the requested url returned error: 403", "insufficient_scope", "you don't have permission",
    "protected branch",
)  # fmt: skip
# the lines git prints when the server's hooks (pre-receive, GitLab's push rules and branch protection) refuse a ref
_HOOK_REFUSAL = ("[remote rejected]", "pre-receive hook declined")
_LINES = 3


class PushFailed(L4Exit):
    """The push of the unit branch did not land; the message says why and never carries a token. `refused`: the
    server's hooks (a push rule, a protected branch) said no, so a repeat fails the same way until the forge changes."""

    def __init__(self, code: ExitCode, message: str, *, refused: bool = False) -> None:
        super().__init__(code, message)
        self.refused = refused


def is_permission_failure(stderr: str) -> bool:
    low = stderr.lower()
    return any(marker in low for marker in _DENIED)


def is_hook_refusal(stderr: str) -> bool:
    low = stderr.lower()
    return any(marker in low for marker in _HOOK_REFUSAL)


def explain_push_failure(
    exc: GitError, *, branch: str, token_env: str, environ: Mapping[str, str], redact: Callable[[str], str]
) -> PushFailed:
    lines = [line.strip() for line in exc.stderr.strip().splitlines()[:_LINES]]
    reason = " | ".join(lines) or f"git exit {exc.returncode}"
    head = f"push of {branch} to origin failed: {reason}"
    if isinstance(exc, PushRejected) and "stale info" in exc.stderr:
        hint = (
            "the unit branch was deleted or moved on the forge since this run last saw it; it is never recreated "
            "or overwritten (the harness never forces). A person decides: restore the branch or rerun the unit"
        )
        return PushFailed(ExitCode.INTERNAL_ERROR, redact(f"{head}. {hint}"))
    if isinstance(exc, PushRejected):
        hint = (
            "the branch moved on the forge (non-fast-forward): a human pushed; the next run continues from it "
            "(the harness never forces)"
        )
        return PushFailed(ExitCode.INTERNAL_ERROR, redact(f"{head}. {hint}"))
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
    hint = (
        f"the forge refused the credential: {token_env} must be a project access token with the "
        "write_repository (and api) scopes and the Developer role or higher, and the branch must not be protected "
        "against it"
    )
    if environ.get("GITLAB_CI") == "true" and not environ.get(token_env):
        hint += f". {token_env} is not set"
        if runner_rewrites_urls(environ):
            hint += ": the runner rewrites the origin URL to carry the job token, which cannot push"
    return PushFailed(ExitCode.DOCTOR_FAILED, redact(f"{head}. {hint}"))
