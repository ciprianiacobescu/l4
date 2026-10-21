"""L4-SEC-006: a git or node planted in the checkout is never the one that runs."""

import os
import stat
from pathlib import Path

import pytest

from l4.config.defaults import openspec_env, resolve_executable
from l4.exitcodes import ExitCode, L4Exit
from l4.safepath import safe_path
from l4.vcs.git import Git

PLANT = "#!/bin/sh\necho PLANTED >&2\ntouch PWNED\nexit 0\n"


def plant(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text(PLANT)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.mark.parametrize("prefix", ["", ".", "./", "./node_modules/.bin", "relative/dir"])
def test_empty_and_relative_entries_are_dropped(prefix, tmp_path):
    kept = tmp_path / "bin"
    path = os.pathsep.join([prefix, str(kept), ""])
    assert safe_path({"PATH": path}) == str(kept)


def test_entries_inside_a_forbidden_checkout_are_dropped(tmp_path):
    repo, other = tmp_path / "repo", tmp_path / "other"
    (repo / "bin").mkdir(parents=True)
    other.mkdir()
    link = tmp_path / "link"
    link.symlink_to(repo / "bin")
    path = os.pathsep.join([str(repo / "bin"), str(link), str(other)])
    assert safe_path({"PATH": path}, forbid=[repo]) == str(other)


def test_git_ignores_a_git_planted_in_the_repo(make_repo, git_environ):
    repo = make_repo()
    plant(repo, "git")
    for lead in ("", ".", "./", str(repo)):
        env = {**git_environ, "PATH": os.pathsep.join([lead, git_environ["PATH"]])}
        done = Git(repo, environ=env).run("status", "--short")
        assert "PLANTED" not in done.stderr
    assert not (repo / "PWNED").exists()


def test_git_with_nothing_safe_on_path_is_exit_3(make_repo, git_environ):
    repo = make_repo()
    plant(repo, "git")
    with pytest.raises(L4Exit) as caught:
        Git(repo, environ={**git_environ, "PATH": f"{os.pathsep}."})
    assert caught.value.code == ExitCode.DOCTOR_FAILED


def test_node_planted_in_the_repo_is_not_resolved(tmp_path):
    repo = tmp_path / "repo"
    (repo / "node_modules" / ".bin").mkdir(parents=True)
    plant(repo / "node_modules" / ".bin", "node")
    plant(repo, "node")
    for path in (f"{os.pathsep}/nonexistent{os.pathsep}", ".", "./node_modules/.bin", str(repo)):
        assert resolve_executable("node", {"PATH": path}, forbid=[repo]) is None


def test_a_symlink_from_a_safe_directory_into_the_repo_is_refused(tmp_path):
    repo, trusted = tmp_path / "repo", tmp_path / "trusted"
    repo.mkdir()
    trusted.mkdir()
    target = plant(repo, "node")
    (trusted / "node").symlink_to(target)
    with pytest.raises(L4Exit) as caught:
        resolve_executable("node", {"PATH": str(trusted)}, forbid=[repo])
    assert caught.value.code == ExitCode.DOCTOR_FAILED


def test_openspec_env_path_is_safe(tmp_path):
    env = openspec_env({"PATH": f"{os.pathsep}.{os.pathsep}/usr/bin", "HOME": str(tmp_path)})
    assert env["PATH"] == "/usr/bin"


def test_resolve_tool_returns_the_real_path_of_a_symlinked_executable(tmp_path):
    """macOS Codex looks for codex-code-mode-host next to the path it was invoked by: a symlink on PATH broke it."""
    from l4.safepath import resolve_tool

    real_dir, link_dir = tmp_path / "real", tmp_path / "bin"
    real_dir.mkdir()
    link_dir.mkdir()
    real = plant(real_dir, "codex")
    (link_dir / "codex").symlink_to(real)
    found = resolve_tool("codex", {"PATH": str(link_dir)})
    assert found == os.path.realpath(real) and not Path(found).is_symlink()
