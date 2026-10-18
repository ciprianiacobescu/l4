"""A gate run that plants a link in the worktree never makes the harness write through it (L4-SEC-020, L4-SEC-021).

The reproductions of the independent review (implementer-1), ported with their assertions inverted: a real Workbench
(`make_bench`), real gate runs, and a gate command that does what agent-written test code can do with a writable
worktree. Without a sandbox the gate only plants the link; the write outside would be the harness's own."""

import os
import shutil
import signal
from collections.abc import Iterator
from pathlib import Path

import pytest

from l4.implementer.discrimination import confirm_pre_satisfied, run_with_code_of, zeroed_run
from l4.implementer.tdd import run_setup

from ..conftest import TEST_COMMAND


@pytest.fixture(autouse=True)
def _alarm() -> Iterator[None]:
    """A restore that blocks on a FIFO must fail the test, not hang the suite."""

    def boom(*_: object) -> None:
        raise TimeoutError("the run blocked for 120 s")

    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(120)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def swap_cmd(outside: Path, condition: str = "true") -> str:
    """Replace src/pytdd by a link to `outside` (what a test may do), then run the tests."""
    return f"sh -c 'if {condition}; then rm -rf src/pytdd && ln -s {outside} src/pytdd; fi; exec {TEST_COMMAND}'"


def planted(bench, path: str) -> list[dict]:
    events = [e.get("data", e) for e in bench.events("guard.violation")]
    return [e for e in events if e.get("rule") == "planted link" and e.get("path") == path]


def nothing_in(outside: Path) -> bool:
    return not [p for p in outside.rglob("*") if p.suffix in (".py", ".pth", ".xml")]


def test_zeroed_run_restore_writes_nothing_through_a_linked_package_directory(make_bench, tmp_path):
    """SCN-SEC-40"""
    outside = tmp_path / "host-site-packages"
    outside.mkdir()
    bench = make_bench([], test={"command": swap_cmd(outside)})
    wb = bench.wb
    run_setup(wb)
    original = (wb.worktree / "src/pytdd/pricing.py").read_bytes()
    zeroed_run(wb, "test-zero", ["src/pytdd/pricing.py"], public=True)  # nothing is raised
    assert not (outside / "pricing.py").exists() and nothing_in(outside)
    package = wb.worktree / "src/pytdd"
    assert package.is_dir() and not package.is_symlink()
    assert (package / "pricing.py").read_bytes() == original
    (event,) = planted(bench, "src/pytdd")
    assert event["phase"] == "gate" and event["action"] == "removed"
    assert [u.link for u in wb.planted_links()] == ["src/pytdd"]


def test_run_with_code_of_puts_the_agents_file_nowhere_outside(make_bench, tmp_path):
    """SCN-SEC-42"""
    outside = tmp_path / "host-home"
    outside.mkdir()
    bench = make_bench([], test={"command": swap_cmd(outside)})
    wb = bench.wb
    run_setup(wb)
    red_sha = wb.head()
    payload = "import os; os.system('echo pwned')  # agent-written\n"
    (wb.worktree / "src/pytdd/evil.pth").write_text(payload)  # an agent step's production file, any name, any content
    run_with_code_of(wb, red_sha, None, name="test-at-red")
    assert not (outside / "evil.pth").exists() and nothing_in(outside)
    assert planted(bench, "src/pytdd")
    assert not (wb.worktree / "src/pytdd").is_symlink()


def plant_after_report(outside: Path) -> str:
    return f"sh -c '{TEST_COMMAND}; if [ -f MARK ]; then rm -rf .l4-out && ln -s {outside} .l4-out; fi'"


def test_a_report_restore_through_a_linked_l4_out_writes_outside_nothing(make_bench, tmp_path):
    """SCN-SEC-43, the restore half"""
    outside = tmp_path / "host-out"
    outside.mkdir()
    (outside / "junit.xml").write_text("not a report\n")
    cmd = plant_after_report(outside)
    bench = make_bench([], test={"command": cmd})
    wb = bench.wb
    run_setup(wb)
    wb.run_gate("test", cmd, reports=wb.cfg.gates.test.reports)  # run (a): a real report is kept
    kept = (wb.worktree / ".l4-out/junit.xml").read_bytes()
    (wb.worktree / "MARK").write_text("")  # from here on the gate command plants the link
    zeroed_run(wb, "test-zero", ["src/pytdd/pricing.py"], public=True)
    assert (outside / "junit.xml").read_text() == "not a report\n"
    assert sorted(p.name for p in outside.iterdir()) == ["junit.xml"]
    out = wb.worktree / ".l4-out"
    assert out.is_dir() and not out.is_symlink()
    assert (out / "junit.xml").read_bytes() == kept  # the report of run (a), put back in a real directory
    assert planted(bench, ".l4-out")


def test_a_linked_pycache_is_removed_and_no_outside_pyc_is_deleted(make_bench, tmp_path):
    """SCN-SEC-43, the bytecode half"""
    from l4.implementer.discrimination import _drop_bytecode

    outside = tmp_path / "host-cache"
    outside.mkdir()
    pyc = outside / "pricing.cpython-312.pyc"
    pyc.write_bytes(b"pyc")
    wb = make_bench([]).wb
    shutil.rmtree(wb.worktree / "src/pytdd/__pycache__", ignore_errors=True)
    (wb.worktree / "src/pytdd/__pycache__").symlink_to(outside)
    _drop_bytecode(wb.worktree, "src/pytdd/pricing.py")
    assert pyc.read_bytes() == b"pyc"
    assert not (wb.worktree / "src/pytdd/__pycache__").exists()
    assert not (wb.worktree / "src/pytdd/__pycache__").is_symlink()


def plant_after_tests(command: str) -> str:
    return f"sh -c '{TEST_COMMAND}; {command}'"


def test_a_hard_link_in_place_of_a_varied_file_gets_no_bytes(make_bench, tmp_path):
    """SCN-SEC-44, the hard link"""
    other = tmp_path / "other.py"
    other.write_text("outside file\n")
    cmd = plant_after_tests(f"rm src/pytdd/pricing.py && ln {other} src/pytdd/pricing.py")
    bench = make_bench([], test={"command": cmd})
    wb = bench.wb
    run_setup(wb)
    original = (wb.worktree / "src/pytdd/pricing.py").read_bytes()
    zeroed_run(wb, "test-zero", ["src/pytdd/pricing.py"], public=True)
    assert other.read_text() == "outside file\n"
    target = wb.worktree / "src/pytdd/pricing.py"
    assert target.is_file() and target.read_bytes() == original and target.stat().st_nlink == 1


def test_a_fifo_in_place_of_a_varied_file_does_not_hang_the_restore(make_bench, tmp_path):
    """SCN-SEC-44, the FIFO"""
    cmd = plant_after_tests("rm src/pytdd/pricing.py && mkfifo src/pytdd/pricing.py")
    bench = make_bench([], test={"command": cmd})
    wb = bench.wb
    run_setup(wb)
    original = (wb.worktree / "src/pytdd/pricing.py").read_bytes()
    zeroed_run(wb, "test-zero", ["src/pytdd/pricing.py"], public=True)  # returns: the suite would time out otherwise
    target = wb.worktree / "src/pytdd/pricing.py"
    assert target.is_file() and not target.is_symlink() and target.read_bytes() == original


def test_a_link_the_repository_commits_is_varied_through_its_real_path_and_put_back(make_bench, tmp_path):
    """SCN-SEC-48"""
    seen = tmp_path / "seen.py"
    cmd = f"sh -c 'cp lib/app/core.py {seen}; exec {TEST_COMMAND}'"
    bench = make_bench([], test={"command": cmd})
    wb = bench.wb
    (wb.worktree / "lib/app").mkdir(parents=True)
    (wb.worktree / "lib/app/core.py").write_text("def answer() -> int:\n    return 42\n")
    os.symlink("../lib/app", wb.worktree / "src/app")
    wb.git.run("add", "-A")
    wb.git.run("commit", "-q", "-m", "a package behind a committed link")
    run_setup(wb)
    original = (wb.worktree / "lib/app/core.py").read_bytes()
    gate = zeroed_run(wb, "test-zero", ["src/app/core.py"], public=True)
    assert gate is not None  # the module was varied, through its real path
    assert "return 0" in seen.read_text()
    assert (wb.worktree / "lib/app/core.py").read_bytes() == original
    assert (wb.worktree / "src/app").is_symlink() and wb.unsafe == []
    assert not bench.events("guard.violation")


def test_confirm_pre_satisfied_still_runs_on_a_package_behind_a_committed_link(make_bench):
    bench = make_bench([])
    wb = bench.wb
    (wb.worktree / "lib/app").mkdir(parents=True)
    (wb.worktree / "lib/app/core.py").write_text("def answer() -> int:\n    return 42\n")
    os.symlink("../lib/app", wb.worktree / "src/app")
    (wb.worktree / "tests/test_app.py").write_text(
        "from app.core import answer\n\n\ndef test_answer():\n    assert answer() == 42\n"
    )
    wb.git.run("add", "-A")
    wb.git.run("commit", "-q", "-m", "link and test")
    run_setup(wb)
    result = confirm_pre_satisfied(wb, {"C-1": ("tests.test_app::test_answer",)})
    assert result.confirmed == {"C-1": ("tests.test_app::test_answer",)}
    assert (wb.worktree / "lib/app/core.py").read_text().endswith("return 42\n") and wb.unsafe == []


def test_run_gate_spec_records_and_removes_a_linked_report_path_before_and_after_the_gate(make_bench, tmp_path):
    """SCN-SEC-43, the Workbench half"""
    outside = tmp_path / "host-out"
    outside.mkdir()
    (outside / "junit.xml").write_text("outside\n")
    bench = make_bench([], test={"command": plant_after_report(outside)})
    wb = bench.wb
    run_setup(wb)
    shutil.rmtree(wb.worktree / ".l4-out", ignore_errors=True)
    (wb.worktree / ".l4-out").symlink_to(outside)  # there before the gate
    wb.run_gate("test", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)
    assert (outside / "junit.xml").read_text() == "outside\n"
    assert not (wb.worktree / ".l4-out").is_symlink()
    assert len(planted(bench, ".l4-out")) == 1  # recorded once per attempt
    (wb.worktree / "MARK").write_text("")
    wb.unsafe.clear()
    wb.run_gate("test", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)  # the gate plants it this time
    assert (outside / "junit.xml").read_text() == "outside\n"
    assert not (wb.worktree / ".l4-out").is_symlink() and [u.link for u in wb.planted_links()] == [".l4-out"]


def test_a_leaf_symlink_planted_in_place_of_a_varied_file_is_recorded_and_the_outside_file_is_untouched(
    make_bench, tmp_path
):
    """SCN-SEC-40, the last component: a rename over a link replaces it silently, so the plant must be recorded"""
    other = tmp_path / "other.py"
    other.write_text("outside file\n")
    cmd = plant_after_tests(f"rm src/pytdd/pricing.py && ln -s {other} src/pytdd/pricing.py")
    bench = make_bench([], test={"command": cmd})
    wb = bench.wb
    run_setup(wb)
    original = (wb.worktree / "src/pytdd/pricing.py").read_bytes()
    zeroed_run(wb, "test-zero", ["src/pytdd/pricing.py"], public=True)
    assert other.read_text() == "outside file\n"
    target = wb.worktree / "src/pytdd/pricing.py"
    assert target.is_file() and not target.is_symlink() and target.read_bytes() == original
    assert [u.link for u in wb.planted_links()] == ["src/pytdd/pricing.py"]
    assert planted(bench, "src/pytdd/pricing.py")
