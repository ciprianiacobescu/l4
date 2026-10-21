"""Scenarios run the whole `l4 run` on the fixture repository (a bare `origin`, a venv launcher instead of `uv sync`)
with a scripted fake agent and one `FakeClock` for every run of a test."""

from collections.abc import Callable

import pytest

from l4 import services
from l4.agents.factory import ADAPTERS
from l4.agents.fake import FakeAdapter
from l4.cli import main

from ..unit.conftest import UNIT, TddRepo, git_environ, raw, tdd_repo  # noqa: F401, F811
from ..unit.orchestrator.conftest import Run, fake_clock  # noqa: F401
from ..unit.verifier.conftest import valid_spec  # noqa: F401


@pytest.fixture
def scenario(
    tdd_repo: TddRepo,  # noqa: F811
    raw: Callable[..., str],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    fake_clock,  # noqa: F811
    valid_spec,  # noqa: F811
) -> Callable[..., Run]:
    """`scenario(adapter, *flags, verify=False, unit=True, **config)`: one `l4 run` (or `l4 <via>`)."""

    def run(
        adapter: FakeAdapter, *flags: str, verify: bool = False, unit: bool = True, via: str = "run", **config: object
    ) -> Run:
        if not verify:
            monkeypatch.setitem(services.HOOKS, "verify", "l4_test_no_verifier:verify_hook")
        tdd_repo.write_config(**config)  # type: ignore[arg-type]
        monkeypatch.setitem(ADAPTERS, "fake", lambda: adapter)
        argv = [via, *(["--unit", UNIT] if unit else []), *flags, "--repo", str(tdd_repo.repo)]
        return Run(main(argv, environ=tdd_repo.environ), adapter, tdd_repo, raw)

    return run
