"""judge_sandbox.choose (review-resolution 1.11, L4-YOLO-026): SCN-YOLO-60 and SCN-YOLO-61 at function level."""

from pathlib import Path

import pytest

from l4.sandbox.base import SandboxUnavailable
from l4.sandbox.none import NoSandbox
from l4.yolo import judge_sandbox

from .yolo_review_world import make_cfg


def env(tmp_path: Path) -> dict[str, str]:
    empty = tmp_path / "bin"
    empty.mkdir(exist_ok=True)
    return {"PATH": str(empty), "HOME": str(tmp_path)}


def auto_cfg():
    return make_cfg(sandbox={"mode": "auto"})


@pytest.mark.parametrize("adapter", ["claude-code", "opencode", "fake"])
def test_scn_yolo_60_tool_less_judge_runs_unsandboxed_outside_ci(tmp_path: Path, adapter: str) -> None:
    sandbox, label = judge_sandbox.choose(auto_cfg(), env(tmp_path), tmp_path, adapter=adapter, in_ci=False)
    assert isinstance(sandbox, NoSandbox)
    assert label == "none"


def test_an_opencode_free_model_judge_is_not_tool_less_outside_ci(tmp_path: Path) -> None:
    """The free `opencode/` models leave read and bash at `ask` (agents/opencode.py), not at deny."""
    cfg = make_cfg(
        sandbox={"mode": "auto"},
        profiles={"free": {"adapter": "opencode", "model": "opencode/big-pickle"}},
        roles={"implementer": ["free"], "judges": ["free"]},
    )
    with pytest.raises(SandboxUnavailable) as err:
        judge_sandbox.choose(cfg, env(tmp_path), tmp_path, adapter="opencode", profile="free", in_ci=False)
    assert "opencode/" in str(err.value) and "claude-code" in str(err.value) and "api-key opencode" in str(err.value)


def test_an_opencode_judge_with_its_tools_disabled_stays_tool_less(tmp_path: Path) -> None:
    cfg = make_cfg(
        sandbox={"mode": "auto"},
        profiles={"paid": {"adapter": "opencode", "model": "opencode-go/deepseek-v4.1-flash"}},
        roles={"implementer": ["paid"], "judges": ["paid"]},
    )
    sandbox, label = judge_sandbox.choose(cfg, env(tmp_path), tmp_path, adapter="opencode", profile="paid", in_ci=False)
    assert isinstance(sandbox, NoSandbox) and label == "none"


def test_the_reason_is_available_to_the_caller(tmp_path: Path) -> None:
    assert judge_sandbox.unsandboxed_reason(env(tmp_path), tmp_path) == "bwrap was not found on PATH"


def test_scn_yolo_61_a_judge_with_a_shell_is_refused_outside_ci(tmp_path: Path) -> None:
    with pytest.raises(SandboxUnavailable) as err:
        judge_sandbox.choose(auto_cfg(), env(tmp_path), tmp_path, adapter="codex", in_ci=False)
    assert "the codex judge keeps a read-only shell" in str(err.value)
    assert "claude-code or opencode judge profile" in str(err.value)


@pytest.mark.parametrize("adapter", ["codex", "claude-code"])
def test_scn_yolo_61_in_ci_it_is_refused_as_today(tmp_path: Path, adapter: str) -> None:
    with pytest.raises(SandboxUnavailable) as err:
        judge_sandbox.choose(auto_cfg(), env(tmp_path), tmp_path, adapter=adapter, in_ci=True)
    assert "bwrap was not found on PATH" in str(err.value)
    assert "install bubblewrap" in str(err.value)


def test_mode_none_follows_allow_none(tmp_path: Path) -> None:
    ok = make_cfg(sandbox={"mode": "none", "allow_none": True})
    sandbox, label = judge_sandbox.choose(ok, env(tmp_path), tmp_path, adapter="codex", in_ci=True)
    assert isinstance(sandbox, NoSandbox) and label == "none"
    refused = make_cfg(sandbox={"mode": "none", "allow_none": False})
    with pytest.raises(SandboxUnavailable):
        judge_sandbox.choose(refused, env(tmp_path), tmp_path, adapter="claude-code", in_ci=False)


def test_a_usable_bwrap_is_chosen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from l4.sandbox.base import Availability
    from l4.sandbox.bwrap import BwrapSandbox

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "bwrap"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(BwrapSandbox, "available", lambda self: Availability(True))
    sandbox, label = judge_sandbox.choose(
        auto_cfg(), {"PATH": str(bin_dir), "HOME": str(tmp_path)}, tmp_path / "repo", adapter="codex", in_ci=False
    )
    assert isinstance(sandbox, BwrapSandbox) and label == "bwrap"


def test_bwrap_that_does_not_start_gives_its_own_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from l4.sandbox.base import Availability
    from l4.sandbox.bwrap import BwrapSandbox

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "bwrap"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr(BwrapSandbox, "available", lambda self: Availability(False, "no user namespaces"))
    environ = {"PATH": str(bin_dir), "HOME": str(tmp_path)}
    assert judge_sandbox.unsandboxed_reason(environ, tmp_path / "repo") == "no user namespaces"
    sandbox, label = judge_sandbox.choose(auto_cfg(), environ, tmp_path / "repo", adapter="opencode", in_ci=False)
    assert label == "none"
    with pytest.raises(SandboxUnavailable) as err:
        judge_sandbox.choose(auto_cfg(), environ, tmp_path / "repo", adapter="opencode", in_ci=True)
    assert "no user namespaces" in str(err.value)
