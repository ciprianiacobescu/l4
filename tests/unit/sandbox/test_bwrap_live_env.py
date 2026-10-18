"""L4-SEC-035 under a real bubblewrap (SCN-SEC-85, SCN-SEC-86). Skipped where bwrap is absent."""

import os
import shutil
import subprocess

import pytest

from .bwrap_live import make_world, requires_bwrap

pytestmark = requires_bwrap


def test_a_test_gate_cannot_write_the_environment(var_tmp_dir):  # SCN-SEC-85
    world = make_world(var_tmp_dir)
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    site = wb.worktree / ".venv" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (wb.worktree / "node_modules" / "pkg").mkdir(parents=True)
    (wb.worktree / "node_modules" / "pkg" / "index.js").write_text("1")
    write = f"echo plant > '{site}/zz.pth'; echo 2 > '{wb.worktree}/node_modules/pkg/index.js'"
    done = world.run(wb, "gate", f"{write}; echo $?")
    assert done.stdout.split()[-1] != "0"  # the second write failed (the first did not end the script either)
    assert not (site / "zz.pth").exists() and (wb.worktree / "node_modules/pkg/index.js").read_text() == "1"
    again = world.run(wb, "gate", f"echo plant > '{site}/zz.pth' || echo DENIED")
    assert "DENIED" in again.stdout
    built = world.run(wb, "gate", write, builds_env=True)  # the setup gate of the same worktree can write both
    assert built.returncode == 0, built.stderr
    assert (site / "zz.pth").exists() and (wb.worktree / "node_modules/pkg/index.js").read_text() == "2\n"


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")
def test_uv_run_works_on_the_read_only_environment(var_tmp_dir):  # SCN-SEC-86
    world = make_world(var_tmp_dir)
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    (wb.worktree / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.10"\ndependencies = []\n'
    )
    env = {**os.environ, "UV_OFFLINE": "1", "UV_CACHE_DIR": str(var_tmp_dir / "uvc"), "UV_PYTHON_DOWNLOADS": "never"}
    subprocess.run(["uv", "lock", "-q"], cwd=wb.worktree, env=env, check=True, capture_output=True)
    prefix = "UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never "
    setup = world.run(wb, "gate", prefix + "uv sync --frozen -q", builds_env=True, path=os.environ["PATH"])
    assert setup.returncode == 0, setup.stderr
    for command in ("uv run --frozen python -c 'print(1)'", "uv run python -c 'print(1)'"):
        test = world.run(wb, "gate", prefix + command, path=os.environ["PATH"])
        assert test.returncode == 0 and test.stdout.split() == ["1"], (command, test.stderr)
    probe = world.run(wb, "gate", "echo x > .venv/probe 2>/dev/null && echo WRITABLE || echo READ-ONLY")
    assert probe.stdout.split() == ["READ-ONLY"]
