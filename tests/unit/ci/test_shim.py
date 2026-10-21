import os
import stat
import subprocess
from pathlib import Path

import pytest

from l4.ci.render import render_fetched_shim, render_shim


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


SHA = "0123456789abcdef0123456789abcdef01234567"


def fetched_shim(tmp_path: Path, config: str) -> Path:
    shim = tmp_path / "repo" / ".l4" / "bin" / "l4"
    shim.parent.mkdir(parents=True)
    shim.write_text(render_fetched_shim())
    shim.chmod(0o755)
    (shim.parents[1] / "config.yaml").write_text(config)
    return shim


def stub_uvx(home: Path) -> None:
    uvx = home / ".local" / "bin" / "uvx"
    uvx.parent.mkdir(parents=True)
    uvx.write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done > "$UV_LOG"\n')
    uvx.chmod(0o755)


def run_fetched(tmp_path: Path, config: str, *args: str, with_uvx: bool = True):
    shim = fetched_shim(tmp_path, config)
    home = tmp_path / "home"
    if with_uvx:
        stub_uvx(home)
    log = tmp_path / "uvx.log"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "UV_LOG": str(log)}
    done = subprocess.run(
        ["sh", str(shim), *args], cwd=shim.parents[2], env=env, capture_output=True, text=True, check=False
    )
    return done, log


def test_fetched_shim_execs_uvx_with_the_pinned_commit(tmp_path: Path):
    config = (
        f"version: 1\nharness:\n  version: 0.1.0\n  commit: {SHA}\n  repository: https://github.com/o/harness.git\n"
    )
    done, log = run_fetched(tmp_path, config, "run", "--unit", "openspec:x")
    assert done.returncode == 0, done.stderr
    assert log.read_text().split("\n")[:-1] == [
        "--python",
        "3.12",
        "--from",
        f"git+https://github.com/o/harness.git@{SHA}",
        "l4",
        "run",
        "--unit",
        "openspec:x",
    ]


@pytest.mark.parametrize(
    "commit", ["abc1234", SHA.upper(), SHA + "0", SHA[:-1] + "g", '""', "main"], ids=lambda c: c[:12] or "empty"
)
def test_fetched_shim_refuses_a_commit_that_is_not_40_lowercase_hex(tmp_path: Path, commit: str):
    config = f"harness:\n  commit: {commit}\n  repository: https://h.example/o/r.git\n"
    done, log = run_fetched(tmp_path, config)
    assert done.returncode == 3 and not log.exists()
    assert ".l4/config.yaml harness.commit" in done.stderr


def test_fetched_shim_refuses_an_empty_or_missing_repository(tmp_path: Path):
    done, log = run_fetched(tmp_path, f"harness:\n  commit: {SHA}\n  repository: ''\n")
    assert done.returncode == 3 and not log.exists()
    assert "harness.repository" in done.stderr
    done, _ = run_fetched(tmp_path / "b", f"harness:\n  commit: {SHA}\n")
    assert done.returncode == 3 and "harness.repository" in done.stderr


def test_fetched_shim_reads_quoted_and_commented_values(tmp_path: Path):
    config = (
        "# top comment\nharness:   # the pins\n"
        f'  commit: "{SHA}"   # pinned\n'
        "  repository: 'ssh://git@github.com/o/harness.git'  # private\n"
    )
    done, log = run_fetched(tmp_path, config)
    assert done.returncode == 0, done.stderr
    assert f"git+ssh://git@github.com/o/harness.git@{SHA}" in log.read_text().split("\n")


def test_fetched_shim_reads_only_the_harness_block(tmp_path: Path):
    other = "b" * 40
    config = (
        f"gates:\n  commit: {other}\n  repository: https://wrong.example/x.git\n"
        f"harness:\n  commit: {SHA}\n  repository: https://right.example/o/r.git\n"
        f"ci:\n  commit: {other}\n  repository: https://wrong.example/y.git\n"
    )
    done, log = run_fetched(tmp_path, config)
    assert done.returncode == 0, done.stderr
    assert f"git+https://right.example/o/r.git@{SHA}" in log.read_text().split("\n")
    only_elsewhere = f"harness:\n  version: 1\ngates:\n  commit: {SHA}\n  repository: https://w.example/x.git\n"
    done, _ = run_fetched(tmp_path / "c", only_elsewhere)
    assert done.returncode == 3


def test_fetched_shim_without_uvx_is_exit_3_with_a_hint(tmp_path: Path):
    config = f"harness:\n  commit: {SHA}\n  repository: https://h.example/o/r.git\n"
    done, _ = run_fetched(tmp_path, config, with_uvx=False)
    assert done.returncode == 3 and "install uv first" in done.stderr


def test_the_vendored_shim_is_unchanged_by_the_fetched_one():
    assert "--project .l4/vendor" in render_shim() and "uvx" not in render_shim()
    assert "uvx" in render_fetched_shim() and ".l4/vendor" not in render_fetched_shim()
