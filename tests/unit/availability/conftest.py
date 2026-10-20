from collections.abc import Callable
from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx
from l4.doctor.context import CmdResult

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded"


class FakeRun:
    """Answers by the argv tail: the first rule whose key is a prefix of `argv[1:]` wins."""

    def __init__(self, rules: dict[tuple[str, ...], CmdResult]) -> None:
        self.rules, self.calls = rules, []

    def __call__(self, argv, cwd, env, timeout):
        self.calls.append((list(argv), cwd, dict(env), timeout))
        for key, result in self.rules.items():
            if tuple(argv[1 : 1 + len(key)]) == key:
                return result
        return CmdResult(127, "", "no rule")


@pytest.fixture
def make_ctx(tmp_path: Path) -> Callable[..., tuple[ProbeCtx, FakeRun]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("codex", "claude", "opencode", "kiro-cli"):
        (bin_dir / name).write_text("#!/bin/sh\n")
        (bin_dir / name).chmod(0o755)
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    def make(rules: dict[tuple[str, ...], CmdResult], *, path: str | None = None, **kw):
        run = kw.pop("run", None) or FakeRun(rules)
        environ = {
            "PATH": path if path is not None else str(bin_dir),
            "HOME": str(tmp_path / "h"),
            "L4_FORGE_TOKEN": "s3cret-token-123",
        }
        return ProbeCtx(environ=environ, cwd=scratch, run=run, **kw), run

    return make
