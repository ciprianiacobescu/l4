import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from l4 import commands

FAKE_MODULE = "l4_test_handlers"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    return path


@pytest.fixture
def install_handler(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[dict[str, Any]]]:
    """Point HANDLERS[command] at a fake function; returns the list of (app, kwargs) calls it receives."""

    def install(command: str, fn: Callable[..., Any]) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []

        def recording(app: Any, **kwargs: Any) -> Any:
            calls.append({"app": app, "kwargs": kwargs})
            return fn(app, **kwargs)

        module = sys.modules.get(FAKE_MODULE) or types.ModuleType(FAKE_MODULE)
        attr = command.replace(" ", "_").replace("-", "_")
        setattr(module, attr, recording)
        monkeypatch.setitem(sys.modules, FAKE_MODULE, module)
        monkeypatch.setitem(commands.HANDLERS, command, f"{FAKE_MODULE}:{attr}")
        return calls

    return install


# the fixtures of the `l4 eval` tests (a scorecard comparison that runs first needs the seed set and a fake app)
from ..eval.conftest import make_app, no_sockets, profiles_file, seeds_root  # noqa: E402, F401
