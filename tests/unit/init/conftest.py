from collections.abc import Callable
from pathlib import Path

import pytest

from l4 import __version__
from l4.context import AppContext
from l4.redact import Redactor

PYPROJECT = '[project]\nname = "l4harness"\nversion = "0.1.0"\nreadme = "README.md"\n'


@pytest.fixture
def harness_repo(tmp_path: Path, raw: Callable[..., str]) -> Path:
    """A harness checkout in git: the files vendoring takes, and the ones it must leave out."""
    root = tmp_path / "harness"
    files = {
        "src/l4/__init__.py": f'__version__ = "{__version__}"\n',
        "src/l4/cli.py": "def main(): ...\n",
        "src/l4/ci/templates/l4.gitlab-ci.yml": "l4-run: {}\n",
        "pyproject.toml": PYPROJECT,
        "uv.lock": "version = 1\n",
        "README.md": "# l4\n",
        "LICENSE": "MIT\n",
        "tests/unit/test_x.py": "def test_x(): ...\n",
        "docs/SPEC.md": "spec\n",
        "openspec/changes/x/proposal.md": "p\n",
        "scripts/run.sh": "#!/bin/sh\n",
        "src/l4/bin/tool.sh": "#!/bin/sh\n",
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "src/l4/bin/tool.sh").chmod(0o755)
    raw(root, "init", "-q")
    raw(root, "add", "-A")
    raw(root, "commit", "-q", "-m", "harness")
    return root


@pytest.fixture
def target(tmp_path: Path, raw: Callable[..., str]) -> Path:
    """A repository to adopt the harness in."""
    repo = tmp_path / "target"
    repo.mkdir()
    raw(repo, "init", "-q")
    (repo / "README.md").write_text("target\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "init")
    return repo


@pytest.fixture
def app_for(git_environ: dict[str, str]) -> Callable[[Path], AppContext]:
    def make(repo: Path) -> AppContext:
        return AppContext(
            repo=repo, config_path=None, log_format="human", verbosity=0, run_id="r-20261004T1000Z-0001",
            environ=git_environ, redactor=Redactor({}),
        )  # fmt: skip

    return make
