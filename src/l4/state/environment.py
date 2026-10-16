"""What `run.started` records of the machine the run is on (L4-STA-001, HB-10): the CI runner and the versions of
the tools whose behaviour a later reader of the ledger may need. Best effort and bounded: a missing tool or a hung
`--version` leaves its entry out and never stops a run."""

import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from typing import Any

from l4.versions import parse_version

TIMEOUT_S = 5
_TOOLS = ("git", "bwrap")
_HTTPS = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?(/[A-Za-z0-9._~/%+@=-]*)?$")  # no user part, no query
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_DIGITS = re.compile(r"^\d{1,12}$")


def ci_url(environ: Mapping[str, str]) -> str | None:
    """The link to the CI run or job that runs this, when every part is plain (D6); else None."""
    if environ.get("GITHUB_ACTIONS") == "true":
        server = environ.get("GITHUB_SERVER_URL", "").rstrip("/")
        repo, run_id = environ.get("GITHUB_REPOSITORY", ""), environ.get("GITHUB_RUN_ID", "")
        attempt = environ.get("GITHUB_RUN_ATTEMPT", "")
        if not (_HTTPS.match(server) and _REPO.match(repo) and ".." not in repo.split("/") and _DIGITS.match(run_id)):
            return None
        url = f"{server}/{repo}/actions/runs/{run_id}"
        if attempt:
            if not _DIGITS.match(attempt):
                return None
            if int(attempt) > 1:
                url += f"/attempts/{int(attempt)}"
        return url
    if environ.get("GITLAB_CI") == "true":
        job = environ.get("CI_JOB_URL", "")
        return job if _HTTPS.match(job) else None
    return None


def run_environment(
    environ: Mapping[str, str],
    *,
    which: Callable[..., str | None] = shutil.which,
    run: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    runner = {
        key: environ[var]
        for key, var in (("id", "CI_RUNNER_ID"), ("description", "CI_RUNNER_DESCRIPTION"))
        if environ.get(var)
    }
    if runner:
        facts["runner"] = runner
    tools: dict[str, str] = {"python": platform.python_version()}
    path = environ.get("PATH")
    for name in _TOOLS:
        exe = which(name, path=path)
        if exe is None:
            continue
        try:
            done = run([exe, "--version"], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        version = parse_version(done.stdout or "")
        if version is not None:
            tools[name] = ".".join(map(str, version))
    facts["tools"] = tools
    link = ci_url(environ)
    if link:
        facts["ci_url"] = link
    return facts
