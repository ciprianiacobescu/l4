"""The reviewer's R3 reproduction (review F1): `zz_marker.pth` written into `UV_CACHE_DIR/archive-v0/<id>/` survives
`rm -rf .venv; uv sync --frozen` into site-packages, because uv links the cached archive. Real uv, offline, a wheel
found by `find-links`. The control shows the risk; the rest shows the harness never lets a step write the cache a later
build reads, and that the verifier builds from a cache nobody wrote."""

import base64
import hashlib
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.implementer.tdd import agent_step
from l4.sandbox.caches import verifier_caches

from ._env_helpers import TASK
from .conftest import result

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")


def wheel(directory: Path) -> None:
    directory.mkdir(parents=True)
    files = {
        "stubpkg/__init__.py": b"VALUE = 1\n",
        "stubpkg-1.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: stubpkg\nVersion: 1.0\n",
        "stubpkg-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }

    def h(b: bytes) -> str:
        return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(b).digest()).rstrip(b"=").decode()

    record = "".join(f"{p},{h(b)},{len(b)}\n" for p, b in files.items()) + "stubpkg-1.0.dist-info/RECORD,,\n"
    with zipfile.ZipFile(directory / "stubpkg-1.0-py3-none-any.whl", "w") as z:
        for p, b in files.items():
            z.writestr(p, b)
        z.writestr("stubpkg-1.0.dist-info/RECORD", record)


def project(tmp_path: Path) -> Path:
    wheel(tmp_path / "wheels")
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.10"\ndependencies = ["stubpkg"]\n\n'
        f'[tool.uv]\nfind-links = ["{tmp_path / "wheels"}"]\n'
    )
    return proj


def uv(proj: Path, cache: Path, *args: str) -> None:
    env = {**os.environ, "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never", "UV_LINK_MODE": "copy",
           "UV_CACHE_DIR": str(cache)}  # fmt: skip
    subprocess.run(["uv", *args], cwd=proj, env=env, check=True, capture_output=True)


def marker(proj: Path) -> list[Path]:
    return list((proj / ".venv").glob("lib/python*/site-packages/zz_marker.pth"))


def test_a_planted_cache_survives_a_rebuild_unless_the_cache_is_fresh(tmp_path):  # SCN-PRV-112 (the control)
    proj = project(tmp_path)
    poisoned = tmp_path / "cacheA"
    uv(proj, poisoned, "lock", "-q")
    uv(proj, poisoned, "sync", "--frozen", "-q")
    (next((poisoned / "archive-v0").iterdir()) / "zz_marker.pth").write_text("import os\n")
    shutil.rmtree(proj / ".venv")
    uv(proj, poisoned, "sync", "--frozen", "-q")
    assert marker(proj)  # the reproduction: the plant is in the rebuilt environment
    shutil.rmtree(proj / ".venv")
    uv(proj, tmp_path / "cacheB", "sync", "--frozen", "-q")  # a cache nobody wrote
    assert marker(proj) == []


def test_no_step_can_write_the_cache_a_later_build_reads(make_bench, tmp_path):  # SCN-PRV-112
    bench = make_bench([Step(structured=result("green"))])
    wb = bench.wb
    proj = project(tmp_path)
    shared = next(c.path for c in wb.caches if c.env == "UV_CACHE_DIR")
    uv(proj, shared, "lock", "-q")
    uv(proj, shared, "sync", "--frozen", "-q")  # the harness's setup
    real = bench.adapter.run

    def run(req):  # the agent plants into the cache directory its environment names
        archive_root = Path(req.env["UV_CACHE_DIR"]) / "archive-v0"
        archive_root.mkdir(parents=True, exist_ok=True)
        target = next(archive_root.iterdir(), archive_root / "x")
        target.mkdir(parents=True, exist_ok=True)
        (target / "zz_marker.pth").write_text("import os\n")
        return real(req)

    bench.adapter.run = run  # type: ignore[method-assign]
    agent_step(wb, "green", TASK, 1, None)
    shutil.rmtree(proj / ".venv")
    uv(proj, shared, "sync", "--frozen", "-q")  # the next build from the unit's cache
    assert marker(proj) == []
    fresh = next(c.path for c in verifier_caches(wb.cfg.sandbox.caches, wb.cache_root, wb.ref.id, wb.repo_key)
                 if c.env == "UV_CACHE_DIR")  # fmt: skip
    shutil.rmtree(proj / ".venv")
    uv(proj, fresh, "sync", "--frozen", "-q")  # the verifier's rebuild, offline from the wheel directory
    assert marker(proj) == [] and (proj / ".venv").is_dir()
