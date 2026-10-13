"""The credential variable of an agent profile (L4-PRV-024): which one, how a probe gets it, how a run gets it.

A probe runs on the host, so the value goes into the probe child's environment. A run is sandboxed, and a value given to
bwrap with `--setenv` lands in bwrap's argv, readable by any local user (`l4.sandbox.env`): the value goes into a new
0600 file in the step's private directory instead, and a `/bin/sh` loader inside the sandbox reads it, deletes it,
exports the variable and execs the agent. The value is then in the agent process's own environment only
(`/proc/<pid>/environ`, same uid). Nothing here returns, raises or logs a value.
"""

import os
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path

from l4.agents.base import AdapterError, RunRequest

CREDENTIAL_FILE = "credential"
LOADER_NAME = "l4-credential"  # $0 of the loader
_VARIABLE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def credential_variable(adapter: str | None, auth: str | None) -> str | None:
    """The variable that carries `adapter`'s credential under `auth` (None means subscription), or None when the
    profile has none: codex on a subscription uses the ChatGPT file login only, never an API key."""
    mode = auth or "subscription"
    if adapter == "claude-code":
        return "ANTHROPIC_API_KEY" if mode == "api_key" else "CLAUDE_CODE_OAUTH_TOKEN"
    if adapter == "codex":
        return "CODEX_API_KEY" if mode == "api_key" else None
    if adapter == "kiro-cli":
        return "KIRO_API_KEY"  # the headless form of the Kiro account login, for both modes
    return None


def hosted_login_problem(adapter: str | None, auth: str | None) -> str | None:
    """Why a profile cannot log in on a GitHub-hosted runner, or None when it can. A hosted runner is a fresh machine
    with no stored login, so the credential must arrive as a CI secret, in `credential_variable`'s variable: codex on a
    subscription has none (its ChatGPT login is a file under ~/.codex), the others do."""
    if (auth or "subscription") == "subscription" and adapter == "codex":
        return (
            "its subscription login is a stored local file (~/.codex) that a GitHub-hosted runner does not have; "
            "use auth: api_key (the secret CODEX_API_KEY) or name another profile in the role"
        )
    return None


def credential_in(environ: Mapping[str, str], variable: str | None) -> str | None:
    """The value of `variable` in `environ`, or None when it is unset or blank."""
    value = (environ.get(variable) or "").strip() if variable else ""
    return value or None


def write_credential_file(directory: Path, value: str) -> Path:
    """The value in a new 0600 file (never an existing one, never a symlink). The caller removes it after the run."""
    path = directory / CREDENTIAL_FILE
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)
    return path


def loader_argv(variable: str, value_file: Path, argv: Sequence[str]) -> list[str]:
    """`argv` behind the loader: it reads `value_file`, removes it, exports `variable` and execs `argv`. The loader
    text holds the variable NAME only (checked against the shell's name syntax), the value stays in the file."""
    if not _VARIABLE.match(variable):
        raise AdapterError("the credential variable name is not a valid environment variable name")
    loader = f'v=$(cat -- "$1") || exit 97; rm -f -- "$1"; export {variable}="$v"; shift; exec "$@"'
    return ["/bin/sh", "-c", loader, LOADER_NAME, str(value_file), *argv]


@contextmanager
def credential_loader(req: RunRequest) -> Iterator[Callable[[list[str]], list[str]]]:
    """For one agent run: yields the function that puts the loader in front of the agent argv (the identity when the
    profile has no variable or the harness environment has none set). The value file lives only inside the block."""
    variable = credential_variable(req.profile.adapter, req.profile.auth)
    value = credential_in(req.host_env, variable)
    if variable is None or value is None:
        yield list
        return
    directory = req.result_path.parent
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CREDENTIAL_FILE).unlink(missing_ok=True)  # O_EXCL below: a leftover must not be reused
    path = write_credential_file(directory, value)
    try:
        yield lambda argv: loader_argv(variable, path, argv)
    finally:
        path.unlink(missing_ok=True)  # the credential does not outlive the step
