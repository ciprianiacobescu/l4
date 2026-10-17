import subprocess
from pathlib import Path

import pytest


def make_repo(path: Path, *, l4: bool = True) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    if l4:
        (path / ".l4").mkdir()
        (path / ".l4" / "config.yaml").write_text("version: 1\n", encoding="utf-8")
    return path.resolve()


@pytest.fixture
def repo_factory(tmp_path: Path):
    def make(name: str, *, l4: bool = True) -> Path:
        return make_repo(tmp_path / "work" / name, l4=l4)

    return make
