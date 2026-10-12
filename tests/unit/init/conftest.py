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


class HarnessRemote:
    """A bare repository standing for https://github.com/o/harness.git (git's `insteadOf`, no network): a lightweight
    tag `v0.3.0` at `old`, an annotated tag `v0.4.0` at `new` (its own object is a different sha), a branch `dev`."""

    URL = "https://github.com/o/harness.git"

    def __init__(self, bare: Path, environ: dict[str, str], old: str, new: str, tag_object: str) -> None:
        self.bare, self.old, self.new, self.tag_object = bare, old, new, tag_object
        self.environ = {
            **environ,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{bare}.insteadOf",
            "GIT_CONFIG_VALUE_0": self.URL,
        }


@pytest.fixture
def harness_remote(tmp_path: Path, raw: Callable[..., str], git_environ: dict[str, str]) -> HarnessRemote:
    work = tmp_path / "remote-work"
    work.mkdir()
    raw(work, "init", "-q", "-b", "main")
    (work / "a").write_text("1\n")
    raw(work, "add", "-A")
    raw(work, "commit", "-q", "-m", "one")
    old = raw(work, "rev-parse", "HEAD").strip()
    raw(work, "tag", "v0.3.0")
    (work / "a").write_text("2\n")
    raw(work, "commit", "-q", "-am", "two")
    new = raw(work, "rev-parse", "HEAD").strip()
    raw(work, "tag", "-a", "v0.4.0", "-m", "release 0.4.0")
    tag_object = raw(work, "rev-parse", "v0.4.0").strip()
    raw(work, "branch", "dev", old)
    bare = tmp_path / "remote.git"
    raw(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    return HarnessRemote(bare, git_environ, old, new, tag_object)


@pytest.fixture
def copy_harness(harness_repo: Path, raw: Callable[..., str]) -> Path:
    """The harness checkout of `harness_repo` with the setup action committed in it (what `--action-copy` copies)."""
    action = Path(__file__).resolve().parents[3] / ".github" / "actions" / "l4" / "action.yml"
    target = harness_repo / ".github" / "actions" / "l4" / "action.yml"
    target.parent.mkdir(parents=True)
    target.write_bytes(action.read_bytes())
    raw(harness_repo, "add", "-A")
    raw(harness_repo, "commit", "-q", "-m", "the action")
    return harness_repo
