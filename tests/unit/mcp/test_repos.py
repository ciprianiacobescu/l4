"""An instance serves the repositories it was started for (L4-MCP-005, SCN-MCP-10..12)."""

from pathlib import Path

import pytest

from l4.mcp.repos import NoRepository, Refused, RepoError, Repos, resolve_root


def test_a_path_resolves_to_the_git_root_with_an_l4_config(repo_factory):
    root = repo_factory("mint-mory")
    (root / "sub").mkdir()
    assert resolve_root(root) == root
    assert resolve_root(root / "sub") == root  # a folder inside resolves to the root


def test_a_folder_that_is_not_a_git_repository_is_refused(tmp_path):
    with pytest.raises(RepoError, match="not a git repository"):
        resolve_root(tmp_path)


def test_a_git_repository_without_l4_config_is_refused(repo_factory):
    with pytest.raises(RepoError, match=r"\.l4/config\.yaml"):
        resolve_root(repo_factory("plain", l4=False))


def test_a_missing_path_is_refused(tmp_path):
    with pytest.raises(RepoError, match="does not exist"):
        resolve_root(tmp_path / "nope")


def test_one_repository_serves_without_a_repo_argument_and_accepts_its_name_or_path(repo_factory):
    root = repo_factory("mint-mory")
    repos = Repos.from_paths([root], cwd=Path("/"))
    assert not repos.needs_repo_argument
    assert repos.select(None) == root
    assert repos.select("mint-mory") == root
    assert repos.select(str(root)) == root


def test_one_repository_refuses_a_repo_argument_that_names_another(repo_factory, tmp_path):
    root = repo_factory("mint-mory")
    other = repo_factory("mintkey")
    repos = Repos.from_paths([root], cwd=Path("/"))
    for bad in ("mintkey", str(other), "/etc"):
        with pytest.raises(Refused) as exc:
            repos.select(bad)
        assert str(root) in str(exc.value)  # the refusal lists what is served


def test_several_repositories_need_a_repo_argument(repo_factory):  # SCN-MCP-11
    a, b = repo_factory("mint-mory"), repo_factory("mintkey")
    repos = Repos.from_paths([a, b], cwd=Path("/"))
    assert repos.needs_repo_argument
    assert repos.select("mintkey") == b
    assert repos.select(str(a)) == a
    with pytest.raises(Refused, match="repo"):
        repos.select(None)
    for bad in ("/etc", "other", "", "mint"):
        with pytest.raises(Refused) as exc:
            repos.select(bad)
        assert str(a) in str(exc.value) and str(b) in str(exc.value)


def test_a_path_is_compared_after_resolving_symlinks(repo_factory, tmp_path):
    a, b = repo_factory("mint-mory"), repo_factory("mintkey")
    link = tmp_path / "link"
    link.symlink_to(a)
    repos = Repos.from_paths([a, b], cwd=Path("/"))
    assert repos.select(str(link)) == a


def test_a_symlink_to_a_served_repository_does_not_make_a_second_one(repo_factory, tmp_path):
    a = repo_factory("mint-mory")
    link = tmp_path / "link"
    link.symlink_to(a)
    assert Repos.from_paths([a, link], cwd=Path("/")).roots == (a,)


def test_two_repositories_with_the_same_folder_name_are_refused_at_start(repo_factory):
    a = repo_factory("same")
    b = repo_factory("other/same")
    with pytest.raises(RepoError, match="same folder name"):
        Repos.from_paths([a, b], cwd=Path("/"))


def test_without_repo_the_working_directory_serves_when_it_is_a_repository(repo_factory):
    root = repo_factory("here")
    repos = Repos.from_paths([], cwd=root)
    assert repos.select(None) == root


def test_without_repo_a_folder_that_is_not_a_repository_answers_an_error_naming_repo(tmp_path):  # SCN-MCP-12
    repos = Repos.from_paths([], cwd=tmp_path)
    with pytest.raises(NoRepository, match="--repo PATH"):
        repos.select(None)
    with pytest.raises(NoRepository, match="--repo PATH"):
        repos.select("anything")
