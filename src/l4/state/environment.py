"""What `run.started` records of the machine the run is on (L4-STA-001, HB-10): the CI runner and the versions of
the tools whose behaviour a later reader of the ledger may need. Best effort and bounded: a missing tool or a hung
`--version` leaves its entry out and never stops a run."""

import platform
import shutil
import subprocess
from collections.abc import Callable, Mapping
from typing import Any

from l4.versions import parse_version

TIMEOUT_S = 5
_TOOLS = ("git", "bwrap")


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
    return facts
