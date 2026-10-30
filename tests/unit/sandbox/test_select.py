import logging
from pathlib import Path

import pytest

from l4.config.schema import SandboxCfg
from l4.doctor.context import CmdResult
from l4.exitcodes import ExitCode, L4Exit
from l4.sandbox.base import SandboxUnavailable
from l4.sandbox.none import NoSandbox
from l4.sandbox.select import BWRAP_HINT, sandbox_refusal, select_sandbox


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
    spec = SandboxSpec("gate", Path("/w"), Path("/g"), Path("/t"), Path("/h"), cache_root=Path("/c"), tool_paths=())
    with pytest.raises(SandboxUnavailable, match="resume runs no agent or gate"):
        sandbox.wrap(["true"], spec, {})
    with pytest.raises(SandboxUnavailable, match="resume runs no agent or gate"):
        sandbox.available()


# --- sandbox_refusal: the local preflight (L4-SEC-041) ---------------------------------------------------------------


def test_a_usable_bwrap_is_no_refusal(tmp_path):
    fake_bwrap(tmp_path)
    assert sandbox_refusal(SandboxCfg(mode="auto"), env(tmp_path), tmp_path / "repo", runner=ok_runner) is None


def test_mode_none_with_allow_none_is_no_refusal_and_selects_nothing(tmp_path, caplog):
    """Design D2: the preflight does not warn or write `sandbox.disabled`; the run does that when it selects."""
    with caplog.at_level(logging.WARNING, logger="l4.sandbox"):
        assert sandbox_refusal(SandboxCfg(mode="none", allow_none=True), {}, tmp_path) is None
    assert "SANDBOX DISABLED" not in caplog.text


def test_mode_none_without_allow_none_is_refused_like_the_run_would(tmp_path):
    assert "allow_none" in (sandbox_refusal(SandboxCfg(mode="none"), {}, tmp_path) or "")


def test_linux_keeps_the_bwrap_hint(tmp_path):
    text = sandbox_refusal(SandboxCfg(mode="auto"), {"PATH": str(tmp_path)}, tmp_path / "repo", platform="linux")
    assert text is not None and text.startswith("bwrap was not found on PATH") and text.endswith(BWRAP_HINT)
    assert "l4 retry" not in text


def test_scn_sec_108_macos_names_the_ways_out(tmp_path):
    text = sandbox_refusal(SandboxCfg(mode="auto"), {"PATH": str(tmp_path)}, tmp_path / "repo", platform="darwin")
    assert text is not None and text.startswith("bwrap was not found on PATH")
    assert "no sandbox for `l4 run`" in text and "Linux machine or VM with bubblewrap" in text
    assert "`l4 ci start`" in text and "`l4 retry` for a halted or escalated unit" in text
    assert "`sandbox.mode: container`" in text
    assert "allow unprivileged user namespaces" not in text  # the Linux-only half of the hint is dropped


def test_the_macos_text_names_the_command_that_was_refused(tmp_path):
    text = sandbox_refusal(
        SandboxCfg(mode="auto"), {"PATH": str(tmp_path)}, tmp_path / "repo", platform="darwin", command="l4 verify"
    )
    assert text is not None and "no sandbox for `l4 verify`" in text and "no sandbox for `l4 run`" not in text


def test_a_failed_self_test_is_a_refusal_with_its_reason(tmp_path):
    fake_bwrap(tmp_path)
    text = sandbox_refusal(SandboxCfg(mode="bwrap"), env(tmp_path), tmp_path / "repo", runner=blocked_runner)
    assert text is not None and "No permissions to create new namespace" in text


@pytest.mark.parametrize("mode", ["user", "container"])
def test_a_mode_that_does_not_exist_yet_is_still_a_usage_error(tmp_path, mode):
    with pytest.raises(L4Exit) as err:
        sandbox_refusal(SandboxCfg(mode=mode), {}, tmp_path)
    assert err.value.code == ExitCode.USAGE_ERROR


def test_the_platform_defaults_to_this_machine(tmp_path, monkeypatch):
    import types

    monkeypatch.setattr("l4.sandbox.select.sys", types.SimpleNamespace(platform="darwin"))
    text = sandbox_refusal(SandboxCfg(mode="auto"), {"PATH": str(tmp_path)}, tmp_path / "repo")
    assert text is not None and "l4 ci start" in text
