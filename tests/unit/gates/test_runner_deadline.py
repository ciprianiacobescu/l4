"""A gate running at the soft deadline is stopped and says so (L4-IMP-068, SCN-IMP-340)."""

import contextlib
import os
import sys
from pathlib import Path

import pytest

from l4.gates.runner import GateSpec, run_gate
from l4.redact import Redactor
from l4.sandbox.base import SandboxSpec
from l4.sandbox.none import NoSandbox

from ..conftest import fire_on_marker

HOST = {"PATH": os.environ["PATH"], "HOME": "/home/u"}


def marker_script(tmp_path: Path) -> tuple[Path, Path]:
    """A gate command that writes `pid` and then `marker` and sleeps for a minute."""
    marker, pid = tmp_path / "marker", tmp_path / "pid"
    script = tmp_path / "gate.py"
    script.write_text(
        "import os, sys, time\n"
        f"open({str(pid)!r}, 'w').write(str(os.getpid()))\n"
        f"open({str(marker)!r}, 'w').close()\n"
        "time.sleep(60)\n"
    )
    return script, marker


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.fixture
def work(tmp_path: Path):
    (tmp_path / "wt").mkdir()
    (tmp_path / "tmp").mkdir()
    spec = SandboxSpec(
        "gate", tmp_path / "wt", tmp_path / "git", tmp_path / "tmp", tmp_path / "home",
        cache_root=tmp_path / "cache", tool_paths=(),
    )  # fmt: skip
    return tmp_path, spec


def test_a_gate_stopped_by_the_deadline_says_so(work, armed_deadline):
    tmp, sandbox_spec = work
    script, marker = marker_script(tmp)
    dl = armed_deadline()
    fire_on_marker(dl, marker, within_s=10)
    gate = GateSpec("test", f"{sys.executable} {script}", timeout_s=300)
    try:
        result = run_gate(
            gate, worktree=tmp / "wt", sandbox=NoSandbox(allow_none=True), sandbox_spec=sandbox_spec, host_env=HOST,
            log_path=tmp / "logs" / "test.log", redactor=Redactor({}),
        )  # fmt: skip
        assert result.deadline and result.status == "fail" and not result.timed_out
        assert result.reason == "stopped at the soft deadline"
        assert not alive(int((tmp / "pid").read_text()))
    finally:
        if (tmp / "pid").exists():
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(int((tmp / "pid").read_text()), 9)


def test_a_gate_without_a_deadline_has_deadline_false(work):
    tmp, sandbox_spec = work
    result = run_gate(
        GateSpec("setup", "true"), worktree=tmp / "wt", sandbox=NoSandbox(allow_none=True), sandbox_spec=sandbox_spec,
        host_env=HOST, log_path=tmp / "logs" / "setup.log", redactor=Redactor({}),
    )  # fmt: skip
    assert result.status == "pass" and result.deadline is False
