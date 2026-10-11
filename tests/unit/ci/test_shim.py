import os
import stat
import subprocess
from pathlib import Path

from l4.ci.render import render_shim


def make_shim(tmp_path: Path) -> Path:
    shim = tmp_path / "repo" / ".l4" / "bin" / "l4"
    shim.parent.mkdir(parents=True)
    shim.write_text(render_shim())
    shim.chmod(0o755)
    return shim


def stub_uv(home: Path) -> Path:
    uv = home / ".local" / "bin" / "uv"
    uv.parent.mkdir(parents=True)
    uv.write_text('#!/bin/sh\necho "$PWD|$@" > "$UV_LOG"\n')
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
    return uv


def test_shim_execs_uv_run_project_vendor_with_the_arguments(tmp_path: Path):
    shim = make_shim(tmp_path)
    home = tmp_path / "home"
    stub_uv(home)
    log = tmp_path / "uv.log"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "UV_LOG": str(log)}
    done = subprocess.run([str(shim), "run", "--unit", "openspec:x"], cwd=shim.parents[2], env=env, check=False)
    assert done.returncode == 0
    expected = "run --frozen --no-dev --python 3.12 --project .l4/vendor l4 run --unit openspec:x"
    assert log.read_text().strip() == f"{shim.parents[2].resolve()}|{expected}"


def test_user_local_bin_comes_first_on_path(tmp_path: Path):
    shim = make_shim(tmp_path)
    home = tmp_path / "home"
    stub_uv(home)
    other = tmp_path / "other"
    other.mkdir()
    (other / "uv").write_text('#!/bin/sh\necho wrong > "$UV_LOG"\n')
    (other / "uv").chmod(0o755)
    log = tmp_path / "uv.log"
    env = {"PATH": f"{other}:/usr/bin:/bin", "HOME": str(home), "UV_LOG": str(log)}
    subprocess.run([str(shim)], cwd=shim.parents[2], env=env, check=True)
    assert "wrong" not in log.read_text()


def test_a_missing_uv_is_exit_3_with_a_hint(tmp_path: Path):
    shim = make_shim(tmp_path)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "empty-home")}
    done = subprocess.run([str(shim), "doctor"], cwd=shim.parents[2], env=env, capture_output=True, text=True)
    assert done.returncode == 3 and "uv was not found" in done.stderr
    assert os.access(shim, os.X_OK)


def test_shim_pins_python():
    import re
    import tomllib

    from l4.ci.render import HARNESS_PYTHON

    root = Path(__file__).resolve().parents[3]
    assert f"--python {HARNESS_PYTHON} " in render_shim()
    requires = tomllib.loads((root / "pyproject.toml").read_text())["project"]["requires-python"]
    minimum = re.fullmatch(r">=\s*(\d+)\.(\d+)", requires)
    assert minimum, requires
    assert tuple(map(int, HARNESS_PYTHON.split("."))) >= (int(minimum[1]), int(minimum[2]))
    checks = (root / ".github/workflows/checks.yml").read_text()
    assert set(re.findall(r'python-version: "([\d.]+)"', checks)) == {HARNESS_PYTHON}
    prereqs = (root / "scripts/runner/prereqs.sh").read_text()
    assert re.search(r"^PYTHON_VERSION=\$\{PYTHON_VERSION:-([\d.]+)\}", prereqs, re.M)[1] == HARNESS_PYTHON
