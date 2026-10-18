"""A gate's report path with a link in it (L4-SEC-020/021, SCN-SEC-43): no report is removed or read through a link."""

from pathlib import Path

import pytest

from l4.gates.runner import GateSpec, run_gate
from l4.redact import Redactor
from l4.sandbox.base import SandboxSpec
from l4.sandbox.none import NoSandbox

HOST = {"PATH": "/usr/bin:/bin", "HOME": "/home/u"}
REPORT = ".l4-out/junit.xml"


@pytest.fixture
def work(tmp_path: Path):
    (tmp_path / "wt").mkdir()
    (tmp_path / "tmp").mkdir()
    spec = SandboxSpec("gate", tmp_path / "wt", tmp_path / "git", tmp_path / "tmp", tmp_path / "home")
    outside = tmp_path / "outside"
    outside.mkdir()
    return tmp_path, spec, outside


def go(work, command: str):
    tmp, sandbox_spec, _ = work
    spec = GateSpec("test", command, (REPORT,), timeout_s=30)
    return run_gate(
        spec, worktree=tmp / "wt", sandbox=NoSandbox(allow_none=True), sandbox_spec=sandbox_spec, host_env=HOST,
        log_path=tmp / "logs" / "test.log", redactor=Redactor({}),
    )  # fmt: skip


def test_a_linked_report_directory_fails_the_gate_before_the_command_runs(work):
    tmp, _, outside = work
    (outside / "junit.xml").write_text("<testsuite/>")
    (tmp / "wt" / ".l4-out").symlink_to(outside)
    marker = tmp / "ran"
    result = go(work, f"sh -c 'touch {marker}'")
    assert result.status == "fail"
    assert result.reason == "report path .l4-out/junit.xml has a symbolic link at .l4-out"
    assert not marker.exists()  # the command never ran
    assert (outside / "junit.xml").read_text() == "<testsuite/>"  # and the earlier report was not removed


def test_a_link_planted_by_the_command_fails_the_gate_and_reads_nothing_through_it(work):
    tmp, _, outside = work
    (outside / "junit.xml").write_text("this is not xml")
    result = go(work, f"sh -c 'rm -rf .l4-out; ln -s {outside} .l4-out'")
    assert result.status == "fail"
    assert result.reason == "report path .l4-out/junit.xml has a symbolic link at .l4-out"
    assert "unreadable" not in result.reason  # the outside file was never parsed
    assert (outside / "junit.xml").read_text() == "this is not xml"


def test_a_real_report_directory_is_unaffected(work):
    tmp, _, _ = work
    (tmp / "wt" / ".l4-out").mkdir()
    (tmp / "wt" / ".l4-out" / "junit.xml").write_text("stale")
    result = go(work, "sh -c 'true'")
    assert "symbolic link" not in result.reason and not (tmp / "wt" / REPORT).exists()
