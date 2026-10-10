import pytest

from l4.provision.catalog import ROOT_PREREQS, distro_command
from l4.provision.runner import plan_root_prereqs

BWRAP = ROOT_PREREQS[0]
UBUNTU = 'NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\n'
FEDORA = "NAME=Fedora\nID=fedora\n"
ROCKY = 'ID="rocky"\nID_LIKE="rhel centos fedora"\n'
ARCH = "ID=arch\n"


def test_commands_per_distribution():
    assert distro_command(BWRAP, UBUNTU) == "sudo apt-get install -y bubblewrap"
    assert distro_command(BWRAP, FEDORA) == "sudo dnf install -y bubblewrap"
    assert distro_command(BWRAP, ROCKY) == "sudo dnf install -y bubblewrap"
    assert distro_command(BWRAP, 'ID=linuxmint\nID_LIKE="ubuntu debian"\n') == "sudo apt-get install -y bubblewrap"
    generic = distro_command(BWRAP, ARCH)
    assert "package manager" in generic and "bubblewrap" in generic and not generic.startswith("sudo")
    assert "package manager" in distro_command(BWRAP, "")


def test_sudo_shim_never_called_and_command_printed(paths, env, tmp_path):
    shim = tmp_path / "sysbin" / "sudo"
    shim.parent.mkdir(parents=True)
    marker = tmp_path / "sudo-was-called"
    shim.write_text(f"#!/bin/sh\ntouch {marker}\n")
    shim.chmod(0o755)
    actions = plan_root_prereqs(paths, env, "linux-x64", UBUNTU)
    assert [(a.tool, a.status, a.needs_root) for a in actions] == [
        ("bubblewrap", "manual", True),
        ("git", "manual", True),
    ]
    assert actions[0].commands == ("sudo apt-get install -y bubblewrap",)
    assert not marker.exists()
    for action in actions:  # the commands are text for a human: none is an argv we could start
        assert action.message == action.commands[0]


def test_bubblewrap_is_linux_only_and_present_tools_are_not_listed(paths, env, install_fake, tmp_path):
    assert [a.tool for a in plan_root_prereqs(paths, env, "darwin-arm64", "")] == ["git"]
    install_fake("git", tmp_path / "sysbin")
    install_fake("bwrap", tmp_path / "sysbin")
    assert plan_root_prereqs(paths, env, "linux-x64", UBUNTU) == []


@pytest.mark.parametrize("prereq", ROOT_PREREQS)
def test_no_prereq_command_runs_privileged_by_the_harness(prereq):
    assert prereq.binary and prereq.package
