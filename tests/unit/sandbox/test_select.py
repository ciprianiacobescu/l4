import logging
from pathlib import Path

import pytest

from l4.config.schema import SandboxCfg
from l4.doctor.context import CmdResult
from l4.exitcodes import ExitCode, L4Exit
from l4.sandbox.base import SandboxUnavailable
from l4.sandbox.none import NoSandbox
from l4.sandbox.select import select_sandbox


class Events:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type, /, **data):
        self.events.append((event_type, data))


def fake_bwrap(tmp_path: Path, name: str = "bwrap") -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / name
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return bin_dir


def env(tmp_path: Path) -> dict[str, str]:
    return {"PATH": str(tmp_path / "bin")}


def ok_runner(argv, cwd, environ, timeout):
    return CmdResult(0, "", "")


def blocked_runner(argv, cwd, environ, timeout):
    return CmdResult(1, "", "bwrap: No permissions to create new namespace\n")


@pytest.mark.parametrize("mode", ["auto", "bwrap"])
def test_bwrap_modes_return_a_bwrap_sandbox_that_works(tmp_path, mode):
    fake_bwrap(tmp_path)
    sandbox = select_sandbox(SandboxCfg(mode=mode), env(tmp_path), repo=tmp_path / "repo", runner=ok_runner)
    assert sandbox.name == "bwrap"


def test_auto_without_bwrap_fails_closed(tmp_path):
    with pytest.raises(SandboxUnavailable) as err:
        select_sandbox(SandboxCfg(mode="auto"), {"PATH": str(tmp_path)}, repo=tmp_path / "repo", runner=ok_runner)
    assert err.value.code == ExitCode.DOCTOR_FAILED and "bubblewrap" in str(err.value)


def test_a_failed_self_test_fails_closed_with_the_reason(tmp_path):
    fake_bwrap(tmp_path)
    with pytest.raises(SandboxUnavailable, match="No permissions to create new namespace"):
        select_sandbox(SandboxCfg(mode="bwrap"), env(tmp_path), repo=tmp_path / "repo", runner=blocked_runner)


def test_auto_never_degrades_to_none_even_when_allowed(tmp_path):
    with pytest.raises(SandboxUnavailable):
        select_sandbox(
            SandboxCfg(mode="auto", allow_none=True), {"PATH": str(tmp_path)}, repo=tmp_path / "repo", runner=ok_runner
        )


def test_bwrap_inside_the_repository_is_not_run(tmp_path):
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    exe = repo / "bin" / "bwrap"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    with pytest.raises(SandboxUnavailable):
        select_sandbox(SandboxCfg(mode="auto"), {"PATH": str(repo / "bin")}, repo=repo, runner=ok_runner)


def test_none_requires_allow_none_and_emits_disabled_event(tmp_path, caplog):
    with pytest.raises(SandboxUnavailable, match="allow_none"):
        select_sandbox(SandboxCfg(mode="none"), {}, repo=tmp_path)
    events = Events()
    with caplog.at_level(logging.WARNING, logger="l4.sandbox"):
        sandbox = select_sandbox(SandboxCfg(mode="none", allow_none=True), {}, repo=tmp_path, events=events)
    assert isinstance(sandbox, NoSandbox) and sandbox.name == "none"
    assert events.events == [("sandbox.disabled", {"mode": "none", "by": "config"})]
    assert "SANDBOX DISABLED" in caplog.text


def test_no_sandbox_refuses_to_exist_without_allow_none():
    with pytest.raises(SandboxUnavailable):
        NoSandbox(allow_none=False)


def test_no_sandbox_passes_the_command_through(make_spec):
    wrapped = NoSandbox(allow_none=True).wrap(["echo", "hi"], make_spec("gate"), {"A": "1"})
    assert wrapped.argv == ["echo", "hi"] and wrapped.env == {"A": "1"}


@pytest.mark.parametrize("mode", ["user", "container"])
def test_modes_for_later_milestones_are_a_usage_error(tmp_path, mode):
    with pytest.raises(L4Exit) as err:
        select_sandbox(SandboxCfg(mode=mode), {}, repo=tmp_path)
    assert err.value.code == ExitCode.USAGE_ERROR and "not yet implemented" in str(err.value)


def test_no_sandbox_refuses_every_wrap():
    from l4.sandbox.base import SandboxSpec
    from l4.sandbox.none import AbsentSandbox

    sandbox = AbsentSandbox("resume runs no agent or gate")
    spec = SandboxSpec("gate", Path("/w"), Path("/g"), Path("/t"), Path("/h"))
    with pytest.raises(SandboxUnavailable, match="resume runs no agent or gate"):
        sandbox.wrap(["true"], spec, {})
    with pytest.raises(SandboxUnavailable, match="resume runs no agent or gate"):
        sandbox.available()
