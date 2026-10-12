import os
import re
import shutil
import tempfile
from pathlib import Path

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


# Variables a CI runner sets and the code under test reads (the forge identity fallback, the sandbox binds, the
# provisioning flag, the doctor checks). A test that needs one sets it itself; none leaks in from the machine.
_AMBIENT_CI = re.compile(
    r"^(CI|CI_.*|GITHUB_.*|RUNNER_.*|ACTIONS_.*|ImageOS|ImageVersion|GITLAB_CI|L4_SELF_PROVISION)$"
)
_GIT_HOME: Path | None = None


def pytest_configure(config: pytest.Config) -> None:
    """One git configuration for the whole session, whatever the machine has: an identity and a default branch in a
    private global file, no system file. It is the lowest layer: repository-local config (the bot identities some
    tests set) still wins, which `GIT_AUTHOR_*` variables would not allow."""
    global _GIT_HOME
    if hasattr(config, "workerinput"):  # an xdist worker: the controller's file is inherited through the environment
        return
    _GIT_HOME = Path(tempfile.mkdtemp(prefix="l4-test-git-"))
    gitconfig = _GIT_HOME / "gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = L4 Test\n\temail = l4-test@example.invalid\n[init]\n\tdefaultBranch = main\n",
        encoding="utf-8",
    )
    os.environ["GIT_CONFIG_GLOBAL"] = str(gitconfig)
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"


def pytest_unconfigure(config: pytest.Config) -> None:
    if _GIT_HOME is not None:
        shutil.rmtree(_GIT_HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_ambient_ci_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unit suite passes the same on a developer machine and on a CI runner: the CI and forge variables of the
    machine are removed for every test."""
    for name in [n for n in os.environ if _AMBIENT_CI.match(n)]:
        monkeypatch.delenv(name, raising=False)
