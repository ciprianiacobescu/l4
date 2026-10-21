from pathlib import Path

import pytest

from l4.vcs.repokey import key_of_remote, normalize_remote, repository_key

SAME_GITLAB = [
    "https://gitlab-ci-token:X@host/team/l4-yolo-dummy.git",
    "git@host:team/l4-yolo-dummy.git",
    "https://host/team/l4-yolo-dummy",
    "https://HOST/team/l4-yolo-dummy/",
    "ssh://git@host:2222/team/l4-yolo-dummy.git",
]


def test_all_spellings_of_one_gitlab_project_are_one_key():
    assert {key_of_remote(u) for u in SAME_GITLAB} == {key_of_remote("https://host/team/l4-yolo-dummy")}
    assert {normalize_remote(u) for u in SAME_GITLAB} == {"host/team/l4-yolo-dummy"}


def test_a_github_token_in_the_url_does_not_change_the_key():
    assert key_of_remote("https://github.com/o/r") == key_of_remote("https://x-access-token:T@github.com/o/r")


def test_different_projects_have_different_keys():
    keys = {
        key_of_remote("https://host/team/l4-yolo-dummy"),
        key_of_remote("https://host/team/dummy-agentic"),
        key_of_remote("https://host/other/l4-yolo-dummy"),  # same last segment, another group
        key_of_remote("https://other-host/team/l4-yolo-dummy"),
    }
    assert len(keys) == 4


def test_the_key_is_a_short_readable_slug_and_a_hash():
    key = key_of_remote("https://host/team/l4-yolo-dummy.git")
    assert key.startswith("l4-yolo-dummy-") and len(key) == len("l4-yolo-dummy-") + 10
    assert "/" not in key and len(key_of_remote("https://h/g/" + "x" * 200)) <= 40


def test_two_clones_of_one_project_share_the_key(make_repo, git_environ, raw, tmp_path: Path):
    repo = make_repo(remote=True)
    clone = tmp_path / "builds" / "0" / "clone"
    raw(tmp_path, "clone", "-q", str(tmp_path / "repo-origin.git"), str(clone))
    assert repository_key(repo, git_environ) == repository_key(clone, git_environ)


def test_a_worktree_has_its_repositorys_key(make_repo, git_environ, raw, tmp_path: Path):
    repo = make_repo(remote=True)
    raw(repo, "worktree", "add", "-q", "--detach", str(tmp_path / "wt"))
    assert repository_key(tmp_path / "wt", git_environ) == repository_key(repo, git_environ)


def test_without_an_origin_the_key_comes_from_the_git_dir(make_repo, git_environ):
    one, two = make_repo("one"), make_repo("two")
    assert repository_key(one, git_environ) != repository_key(two, git_environ)
    assert repository_key(one, git_environ) == repository_key(one, git_environ)
    assert repository_key(one, git_environ).startswith("one-")


@pytest.mark.parametrize("url", ["", "   "])
def test_an_empty_url_still_gives_a_key(url):
    assert key_of_remote(url)
