from pathlib import Path

import pytest

from l4.config.defaults import cache_root, l4_home, openspec_entrypoint
from l4.exitcodes import ExitCode, L4Exit


def test_cache_root_precedence_and_never_in_repo(tmp_path: Path):
    home = tmp_path / "home"
    assert cache_root({"HOME": str(home)}) == home / ".cache" / "l4"
    assert cache_root({"HOME": str(home), "XDG_CACHE_HOME": "/srv/cache"}) == Path("/srv/cache/l4")
    both = {"HOME": str(home), "XDG_CACHE_HOME": "/srv/cache", "L4_CACHE": "/var/l4"}
    assert cache_root(both) == Path("/var/l4")
    assert cache_root({"HOME": str(home), "L4_CACHE": ""}) == home / ".cache" / "l4"

    repo = tmp_path / "repo"
    repo.mkdir()
    for inside in (repo / ".l4-cache", repo):
        with pytest.raises(L4Exit) as err:
            cache_root({"L4_CACHE": str(inside)}, repo=repo)
        assert err.value.code is ExitCode.USAGE_ERROR
        assert "L4_CACHE" in str(err.value) and str(repo.resolve()) in str(err.value)
    # a default that lands inside the repo (HOME == repo) is refused the same way
    with pytest.raises(L4Exit):
        cache_root({"HOME": str(repo)}, repo=repo)
    # a sibling whose name merely starts with the repo name is fine
    assert cache_root({"L4_CACHE": str(tmp_path / "repo-cache")}, repo=repo) == tmp_path / "repo-cache"


def test_relative_cache_is_a_usage_error():
    with pytest.raises(L4Exit) as err:
        cache_root({"L4_CACHE": "cache"})
    assert err.value.code is ExitCode.USAGE_ERROR


def test_cache_inside_repo_via_symlink_is_refused(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(repo / "sub")
    with pytest.raises(L4Exit):
        cache_root({"L4_CACHE": str(link)}, repo=repo)


def test_l4_home_and_openspec_entrypoint(tmp_path: Path):
    assert l4_home({"HOME": str(tmp_path)}) == tmp_path / ".local" / "share" / "l4"
    env = {"HOME": str(tmp_path), "L4_HOME": str(tmp_path / "h")}
    assert l4_home(env) == tmp_path / "h"
    assert openspec_entrypoint(env) == (
        tmp_path / "h" / "npm" / "node_modules" / "@fission-ai" / "openspec" / "bin" / "openspec.js"
    )


def test_resolve_executable_uses_the_given_path_and_returns_absolute(tmp_path: Path):
    from l4.config.defaults import resolve_executable

    tool = tmp_path / "bin" / "tool"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o755)
    assert resolve_executable("tool", {"PATH": str(tool.parent)}) == str(tool)
    assert resolve_executable("tool", {"PATH": str(tmp_path)}) is None
    assert resolve_executable("tool", {}) is None
