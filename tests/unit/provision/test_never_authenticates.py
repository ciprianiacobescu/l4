from pathlib import Path

import pytest

from l4.provision.runner import GuardedCommandRunner, RefusedCommand

from .conftest import FakeRunner


def guarded():
    inner = FakeRunner({"claude": "2.1.288", "codex": "0.160.0", "kiro-cli": "1.0.0"})
    return GuardedCommandRunner(inner), inner


@pytest.mark.parametrize(
    "argv",
    [
        ["/x/codex", "login", "--device-auth"],
        ["/x/claude", "setup-token"],
        ["/x/opencode", "auth", "login"],
        ["/x/kiro-cli", "login"],
        ["sudo", "apt-get", "install", "-y", "bubblewrap"],
        ["/usr/bin/sudo", "true"],
        ["doas", "true"],
        ["su", "-c", "true"],
    ],
)
def test_no_login_argv_recorded(argv):
    runner, inner = guarded()
    with pytest.raises(RefusedCommand):
        runner(argv, Path("."), {}, 1.0)
    assert inner.calls == []


def test_version_probes_and_installs_pass_through():
    runner, inner = guarded()
    for argv in (["/x/codex", "--version"], ["npm", "install", "--prefix", "/p", "@openai/codex@0.160.0"],
                 ["bash", "/tmp/install.sh"], ["/x/claude", "auth", "status"]):  # fmt: skip
        assert runner(argv, Path("."), {}, 1.0).returncode in (0, 127)
    assert len(inner.calls) == 4
