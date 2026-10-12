"""scripts/dev/release_commit.py builds the slim release commit (L4-ACT-006, SCN-ACT-11)."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dev" / "release_commit.py"

SOURCE_FILES = {
    "src/l4/__init__.py": "__version__ = '0.1'\n",
    "src/l4/deep/mod.py": "x = 1\n",
    "pyproject.toml": "[project]\nname='l4'\n",
    "uv.lock": "lock\n",
    "README.md": "readme\n",
    ".github/actions/l4/action.yml": "name: l4\n",
    ".github/workflows/checks.yml": "name: checks\n",  # not shipped
    "docs/live/huge.txt": "27 MB\n",  # not shipped
    "tests/test_x.py": "def test_x(): pass\n",  # not shipped
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key, value in {
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path),
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }.items():  # fmt: skip
        monkeypatch.setenv(key, value)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def commit_all(repo: Path, files: dict[str, str | None], message: str) -> str:
    for name, text in files.items():
        path = repo / name
        if text is None:
            path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, env: None) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    commit_all(path, SOURCE_FILES, "source one")
    return path


def load():
    spec = importlib.util.spec_from_file_location("release_commit", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["release_commit"] = module
    spec.loader.exec_module(module)
    return module


def files_of(repo: Path, rev: str) -> list[str]:
    return git(repo, "ls-tree", "-r", "--name-only", rev).splitlines()


def test_first_release_has_no_parent_only_the_listed_paths_and_a_named_message(repo: Path):
    rc = load()
    source = git(repo, "rev-parse", "HEAD")
    sha = rc.build(repo, source, "0.3.0")
    assert git(repo, "rev-parse", "release") == sha
    assert git(repo, "rev-list", "--parents", "-n1", sha) == sha  # no parent
    assert git(repo, "log", "-1", "--format=%s", sha) == f"release v0.3.0 from {source}"
    assert files_of(repo, sha) == [
        ".github/actions/l4/action.yml", "README.md", "pyproject.toml",
        "src/l4/__init__.py", "src/l4/deep/mod.py", "uv.lock",
    ]  # fmt: skip


def test_second_release_parent_is_the_first(repo: Path):
    rc = load()
    first = rc.build(repo, git(repo, "rev-parse", "HEAD"), "0.3.0")
    changes = {"src/l4/deep/mod.py": "x = 2\n", "LICENSE": "MIT\n", "skills/l4/SKILL.md": "s\n"}
    second_source = commit_all(repo, changes, "two")
    second = rc.build(repo, second_source, "0.3.1")
    assert git(repo, "rev-parse", f"{second}^") == first
    assert git(repo, "rev-parse", "release") == second
    shipped = files_of(repo, second)
    assert "LICENSE" in shipped and "skills/l4/SKILL.md" in shipped
    assert not any(f.startswith(("docs/", "tests/", ".github/workflows/")) for f in shipped)
    assert git(repo, "show", f"{second}:src/l4/deep/mod.py") == "x = 2"


def test_the_working_tree_and_the_current_branch_are_untouched(repo: Path):
    rc = load()
    (repo / "scratch.txt").write_text("uncommitted\n")
    head = git(repo, "rev-parse", "HEAD")
    rc.build(repo, head, "0.3.0")
    assert git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "branch", "--show-current") == "main"
    assert (repo / "scratch.txt").read_text() == "uncommitted\n"
    assert git(repo, "status", "--porcelain") == "?? scratch.txt"


def test_the_check_catches_a_tampered_tree(repo: Path):
    rc = load()
    source = git(repo, "rev-parse", "HEAD")
    good = rc.build(repo, source, "0.3.0")
    rc.verify(repo, good, source)  # passes
    # A commit whose tree has an extra file and one changed file.
    git(repo, "checkout", "-q", "--orphan", "evil")
    git(repo, "rm", "-rq", "--cached", ".")
    (repo / "extra.txt").write_text("smuggled\n")
    git(repo, "add", "extra.txt", "pyproject.toml", "uv.lock", "README.md", "src", ".github/actions")
    git(repo, "commit", "-q", "-m", "evil")
    evil = git(repo, "rev-parse", "HEAD")
    with pytest.raises(rc.ReleaseError, match="differs"):
        rc.verify(repo, evil, source)
    # a changed byte in a shipped file is caught too
    (repo / "uv.lock").write_text("tampered\n")
    git(repo, "add", "uv.lock")
    git(repo, "rm", "-q", "--cached", "extra.txt")
    git(repo, "commit", "-q", "-m", "evil2")
    with pytest.raises(rc.ReleaseError, match="differs"):
        rc.verify(repo, git(repo, "rev-parse", "HEAD"), source)


def test_a_failed_verification_does_not_move_the_branch(repo: Path, monkeypatch: pytest.MonkeyPatch):
    rc = load()
    source = git(repo, "rev-parse", "HEAD")
    first = rc.build(repo, source, "0.3.0")

    def boom(*args, **kwargs):
        raise rc.ReleaseError("tree differs (forced)")

    monkeypatch.setattr(rc, "verify", boom)
    with pytest.raises(rc.ReleaseError):
        rc.build(repo, source, "0.3.1")
    assert git(repo, "rev-parse", "release") == first


@pytest.mark.parametrize("version", ["v0.3.0", "0.3", "0.3.0-rc1", "", "../x"])
def test_bad_versions_are_refused(repo: Path, version: str):
    rc = load()
    with pytest.raises(rc.ReleaseError, match="version"):
        rc.build(repo, git(repo, "rev-parse", "HEAD"), version)


def test_a_source_without_src_is_refused(repo: Path):
    rc = load()
    bare = commit_all(repo, {"src/l4/__init__.py": None, "src/l4/deep/mod.py": None}, "no src")
    with pytest.raises(rc.ReleaseError, match="src"):
        rc.build(repo, bare, "0.3.0")


def test_cli_prints_the_sha(repo: Path):
    source = git(repo, "rev-parse", "HEAD")
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--source", source, "--version", "0.3.0"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert done.stdout.strip() == git(repo, "rev-parse", "release")
