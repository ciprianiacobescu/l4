"""implementer-2, the reason for L4-SEC-036 (SCN-SEC-89): `uv sync --frozen`, what `gates.setup` runs, leaves a `.pth`
and a `sitecustomize.py` that no distribution owns, so only the harness can remove them. Ported from the review's
repro_impl2_uv_sync.sh; skipped without uv; offline."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from l4.implementer import envguard

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")


def test_plants_that_survive_uv_sync_are_removed(tmp_path: Path):
    project = tmp_path / "demo"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\nrequires-python = ">=3.10"\ndependencies = []\n'
    )
    env = {**os.environ, "UV_OFFLINE": "1", "UV_CACHE_DIR": str(tmp_path / "uvcache"), "UV_PYTHON_DOWNLOADS": "never"}

    def uv(*args: str) -> None:
        subprocess.run(["uv", *args], cwd=project, env=env, check=True, capture_output=True)

    uv("lock", "-q")
    uv("sync", "--frozen", "-q")
    manifest = envguard.take_manifest(project)
    site = next((project / ".venv" / "lib").glob("python*/site-packages"))
    (site / "zz_planted.pth").write_text('import os; os.environ["L4_PLANTED"] = "pth"\n')
    (site / "sitecustomize.py").write_text('import os\nos.environ["L4_SITECUSTOMIZE"] = "yes"\n')
    uv("sync", "--frozen", "-q")
    assert (site / "zz_planted.pth").exists() and (site / "sitecustomize.py").exists()  # why the harness must act
    diff = envguard.diff_manifest(manifest, envguard.take_manifest(project))
    found = envguard.planted(project, diff, changed_files=[])
    rel = site.relative_to(project).as_posix()
    assert {f"{rel}/zz_planted.pth", f"{rel}/sitecustomize.py"} <= set(found)
    envguard.remove_env_dir(project / ".venv")
    uv("sync", "--frozen", "-q")
    code = 'import os; print(os.environ.get("L4_PLANTED"), os.environ.get("L4_SITECUSTOMIZE"))'
    done = subprocess.run([str(project / ".venv/bin/python"), "-c", code], capture_output=True, text=True, env=env)
    assert done.stdout.split() == ["None", "None"]
