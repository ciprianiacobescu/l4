from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.doctor.context import CmdResult, DoctorContext


class FakeTools:
    """Injectable `which`/`run`: maps a tool name to the stdout of `<tool> --version`."""

    def __init__(self, tools: Mapping[str, str | None]) -> None:
        self.tools = dict(tools)
        self.calls: list[tuple[str, ...]] = []

    def which(self, name: str) -> str | None:
        return f"/fake/bin/{name}" if self.tools.get(name) is not None or name in self.tools else None

    def run(self, argv: Sequence[str], timeout: float = 10.0, env: Mapping[str, str] | None = None) -> CmdResult:
        self.calls.append(tuple(argv))
        name = Path(argv[0]).name
        out = self.tools.get(name)
        if out is None:
            return CmdResult(127, "", "not found")
        if any(str(a).endswith("openspec.js") for a in argv):
            return CmdResult(0, self.tools.get("openspec.js", "") + "\n", "")
        return CmdResult(0, out + "\n", "")


@pytest.fixture
def make_ctx(tmp_path: Path) -> Callable[..., tuple[DoctorContext, FakeTools]]:
    def make(tools: Mapping[str, str | None] | None = None, cfg: L4Config | None = None, **env: str):
        fake = FakeTools(
            tools
            if tools is not None
            else {"git": "git version 2.43.0", "uv": "uv 0.10.0", "node": "v20.19.0", "openspec.js": "1.14.0"}
        )
        repo = tmp_path / "repo"
        repo.mkdir(exist_ok=True)
        environ = {"HOME": str(tmp_path / "home"), "L4_HOME": str(tmp_path / "l4home"), **env}
        ctx = DoctorContext(
            repo=repo,
            cfg=cfg or L4Config(),
            env=environ,
            which=fake.which,
            run=fake.run,
            python_version=(3, 12, 1),
        )
        return ctx, fake

    return make
