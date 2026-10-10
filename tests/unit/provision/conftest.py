from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from l4.doctor.context import CmdResult
from l4.provision.runner import Paths

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "provision"


class FakeRunner:
    """A `CommandRunner` that answers `<binary name> --version` from a table and records every argv."""

    def __init__(self, versions: Mapping[str, str] | None = None) -> None:
        self.versions = dict(versions or {})
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> CmdResult:
        self.calls.append(tuple(argv))
        key = "openspec" if any(a.endswith("openspec.js") for a in argv) else Path(argv[0]).name
        out = self.versions.get(key)
        return CmdResult(0, out + "\n", "") if out is not None else CmdResult(127, "", "")


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "HOME": str(tmp_path / "home"),
        "L4_HOME": str(tmp_path / "home" / ".local" / "share" / "l4"),
        "L4_CACHE": str(tmp_path / "cache"),
        "PATH": str(tmp_path / "sysbin"),
    }


@pytest.fixture
def paths(env: dict[str, str]) -> Paths:
    return Paths.from_env(env)


@pytest.fixture
def install_fake(paths: Paths, tmp_path: Path) -> Callable[..., Path]:
    """Create an executable file `name` in the directory the harness path searches first."""

    def make(name: str, where: Path | None = None) -> Path:
        directory = where or paths.local_bin
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        return path

    return make
