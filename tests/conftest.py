import os

import pytest

# fixture repositories and eval seeds hold their own tests; they run inside the tests that copy them
collect_ignore_glob = ["fixtures/*", "eval/seeds/*"]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("L4_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set L4_LIVE=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _private_login_lock_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """The login locks live in one per-user directory (`l4.agents.gate.lock_root`); a test must never write to the
    developer's real `~/.cache/l4/locks`, and a child process it starts inherits this one."""
    monkeypatch.setenv("L4_LOCK_DIR", str(tmp_path_factory.mktemp("login-locks") / "locks"))
