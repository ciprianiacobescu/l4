"""Review F1 (R3) at workbench level: an agent step works in a private scratch cache that is discarded, and the
verifier builds from a cache of its own that no implementer step touched."""

import dataclasses
import logging
import os
import stat
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.gates.runner import GateSpec
from l4.implementer import workbench as wbmod
from l4.implementer.tdd import agent_step
from l4.sandbox.caches import SCRATCH_DIR, VERIFY_SCOPE, verifier_caches

from ._env_helpers import TASK
from .conftest import result


def test_an_agent_step_works_in_a_private_scratch_cache_that_is_discarded(make_bench):  # SCN-PRV-110
    bench = make_bench([Step(structured=result("green"))])
    wb = bench.wb
    shared = next(c.path for c in wb.caches if c.env == "UV_CACHE_DIR")
    (shared / "archive-v0" / "abc").mkdir(parents=True)  # what the harness's setup built
    seen: dict[str, object] = {}
    real = bench.adapter.run

    def run(req):
        scratch = Path(req.env["UV_CACHE_DIR"])
        seen["scratch"] = scratch
        (scratch / "archive-v0" / "abc").mkdir(parents=True)  # the reviewer's plant, written where the agent can write
        (scratch / "archive-v0" / "abc" / "zz_marker.pth").write_text("import os\n")
        return real(req)

    bench.adapter.run = run  # type: ignore[method-assign]
    mounts = {c.env: c for c in wb.agent_spec().caches}
    assert mounts["UV_CACHE_DIR"].read_only and mounts["UV_CACHE_DIR"].path == shared
    agent_step(wb, "green", TASK, 1, None)
    scratch = seen["scratch"]
    assert isinstance(scratch, Path) and scratch != shared and wb.agent_tmp in scratch.parents
    assert not (shared / "archive-v0" / "abc" / "zz_marker.pth").exists()  # the shared cache never saw the plant
    assert not (wb.agent_tmp / SCRATCH_DIR).exists()  # discarded after the step


def test_the_verifier_builds_from_a_cache_of_its_own_emptied_each_round(make_bench):  # SCN-PRV-111
    wb = make_bench([]).wb
    mine = {c.env: c.path for c in wb.caches if not c.read_only}
    first = verifier_caches(wb.cfg.sandbox.caches, wb.cache_root, wb.ref.id, wb.repo_key)
    theirs = {c.env: c.path for c in first if not c.read_only}
    assert theirs.keys() == mine.keys()
    for env, path in theirs.items():
        assert path != mine[env] and VERIFY_SCOPE in path.parts and wb.repo_key in path.parts
        assert not (path == mine[env] or mine[env] in path.parents or path in mine[env].parents)
    (theirs["UV_CACHE_DIR"] / "archive-v0").mkdir()
    (theirs["UV_CACHE_DIR"] / "archive-v0" / "stale").write_text("from the last round")
    second = verifier_caches(wb.cfg.sandbox.caches, wb.cache_root, wb.ref.id, wb.repo_key)
    assert list(next(c.path for c in second if c.env == "UV_CACHE_DIR").iterdir()) == []  # emptied
    assert dataclasses.replace(wb, caches=second).caches == second  # a workbench takes them as its own


def go_filled(scratch: Path) -> Path:
    """What a step's Go commands leave in a scratch cache: module directories with mode 0o555 holding files 0o444."""
    module = scratch / "github.com" / "x" / "y@v1.0.0"
    module.mkdir(parents=True)
    (module / "go.mod").write_text("module github.com/x/y\n")
    (module / "go.mod").chmod(0o444)
    for directory in (module, module.parent, module.parent.parent):
        directory.chmod(0o555)
    return module


@pytest.fixture
def writable_after(tmp_path: Path):
    """So pytest can remove what a failing test leaves."""
    yield
    for current, dirs, _files in os.walk(tmp_path):
        os.chmod(current, 0o700)
        dirs[:] = [d for d in dirs if not Path(current, d).is_symlink()]


def test_the_agent_temp_is_reset_after_go_filled_the_last_scratch(make_bench, writable_after):  # SCN-PRV-141
    wb = make_bench([]).wb
    wb.reset_agent_tmp()
    go_filled(wb.agent_tmp / SCRATCH_DIR / "GOMODCACHE")
    go_filled(wb.agent_tmp / "go-elsewhere")  # whatever else the step left in its temp directory
    wb.reset_agent_tmp()  # today: the Go trees stay, and mkdir on the scratch raises FileExistsError
    scratch = wb.agent_tmp / SCRATCH_DIR / "GOMODCACHE"
    assert scratch.is_dir() and list(scratch.iterdir()) == []
    assert not (wb.agent_tmp / "go-elsewhere").exists()
    assert stat.S_IMODE(wb.agent_tmp.stat().st_mode) == 0o700


def test_discard_scratch_removes_what_go_made_read_only(make_bench, writable_after):
    wb = make_bench([]).wb
    wb.reset_agent_tmp()
    go_filled(wb.agent_tmp / SCRATCH_DIR / "GOMODCACHE")
    wb.discard_scratch()
    assert not (wb.agent_tmp / SCRATCH_DIR).exists()


def test_a_failed_removal_at_the_end_of_a_step_is_a_warning(make_bench, monkeypatch, caplog):  # SCN-PRV-141
    wb = make_bench([]).wb
    wb.reset_agent_tmp()

    def refuse(path: Path) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(wbmod, "remove_tree", refuse)
    with caplog.at_level(logging.WARNING, logger="l4.implementer"):
        wb.discard_scratch()  # does not raise
    assert str(wb.agent_tmp / SCRATCH_DIR) in caplog.text and "could not remove" in caplog.text


def test_a_failed_removal_at_the_start_of_a_step_raises(make_bench, monkeypatch):
    wb = make_bench([]).wb

    def refuse(path: Path) -> None:
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(wbmod, "remove_tree", refuse)
    with pytest.raises(PermissionError, match=str(wb.agent_tmp)):
        wb.reset_agent_tmp()


def test_a_gates_scratch_caches_go_with_the_gate_also_when_go_made_them_read_only(make_bench, writable_after):
    wb = make_bench([]).wb
    script = (
        'mkdir -p "$GOCACHE/m/n" && echo x > "$GOCACHE/m/n/f" && chmod 444 "$GOCACHE/m/n/f" && chmod 555 "$GOCACHE/m/n"'
    )
    command = f"sh -c '{script}'"
    result = wb.run_gate_spec(GateSpec("lint", command, timeout_s=60), network=False)
    assert result.status == "pass", result.reason
    assert not (wb.unit_cache / "gate-tmp" / SCRATCH_DIR).exists()


def test_a_failed_removal_after_a_gate_is_a_warning(make_bench, monkeypatch, caplog):
    wb = make_bench([]).wb
    real = wbmod.remove_tree

    def refuse(path: Path) -> None:
        if path.name == SCRATCH_DIR:
            raise PermissionError(13, "Permission denied", str(path))
        real(path)

    monkeypatch.setattr(wbmod, "remove_tree", refuse)
    with caplog.at_level(logging.WARNING, logger="l4.implementer"):
        result = wb.run_gate_spec(GateSpec("lint", "true", timeout_s=60), network=False)
    assert result.status == "pass"
    assert str(wb.unit_cache / "gate-tmp" / SCRATCH_DIR) in caplog.text
