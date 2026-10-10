"""The seam between checks and the machine: tests inject `which` and `run`; no check calls subprocess."""

import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from l4.config.defaults import resolve_executable
from l4.config.schema import L4Config


class CmdResult(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


Which = Callable[[str], str | None]
Run = Callable[..., CmdResult]  # (argv, timeout=10.0, env=None) -> CmdResult


@dataclass(frozen=True)
class DoctorContext:
    repo: Path
    cfg: L4Config
    env: Mapping[str, str]
    which: Which
    run: Run
    python_version: tuple[int, int, int]
    unit: str | None = None  # set for unit-aware checks under `--unit ID`


def system_context(repo: Path, cfg: L4Config, environ: Mapping[str, str]) -> DoctorContext:
    """Checks look for tools where `doctor --fix` installs them: the user-local directories come first on PATH."""
    from l4.provision.runner import (  # imported here: provision.runner imports CmdResult from this module
        Paths,
        harness_path,
    )

    environ = {**environ, "PATH": harness_path(Paths.from_env(environ), environ.get("PATH", ""), forbid=(repo,))}

    def which(name: str) -> str | None:
        return resolve_executable(name, environ, forbid=(repo,))

    def run(argv: Sequence[str], timeout: float = 10.0, env: Mapping[str, str] | None = None) -> CmdResult:
        try:
            done = subprocess.run(  # argv list, never a shell
                list(argv),
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                env=dict(environ if env is None else env),
                check=False,
            )
        except subprocess.TimeoutExpired:
            return CmdResult(124, "", "timed out")
        except OSError as exc:
            return CmdResult(127, "", type(exc).__name__)
        return CmdResult(done.returncode, done.stdout, done.stderr)

    version = sys.version_info
    return DoctorContext(repo, cfg, environ, which, run, (version.major, version.minor, version.micro))
