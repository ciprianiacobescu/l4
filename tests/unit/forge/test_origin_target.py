"""operator-commands 3.1 (L4-OPS-011, SCN-OPS-18): the forge target comes from the `origin` remote when neither the
environment nor the configuration names it; configured values win."""

import subprocess

import httpx
import pytest

from l4.config.schema import L4Config
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import fetch_auth_config, make_forge, require_forge_target
from l4.forge.github import GitHubForge
from l4.forge.gitlab import GitLabForge, push_auth_config

from ._github_helpers import TOKEN as GH_TOKEN
from .conftest import TOKEN


def cfg(forge: dict | None = None, ci: dict | None = None) -> L4Config:
    return L4Config.model_validate({"forge": forge or {}, "ci": ci or {}})


def seen_urls(forge_config: L4Config, env: dict, **kw) -> list[str]:
    seen: list[str] = []
    transport = httpx.MockTransport(lambda r: seen.append(str(r.url)) or httpx.Response(200, json=[]))
    make_forge(forge_config, env, transport=transport, **kw).find_pr("b")
    return seen


@pytest.mark.parametrize("origin", ["git@github.com:o/n.git", "https://github.com/o/n.git", "ssh://git@github.com/o/n"])
def test_github_target_from_a_github_origin_outside_ci(origin):
    env = {"L4_FORGE_TOKEN": GH_TOKEN}
    for config in (cfg(), cfg({"type": "github"})):  # `auto` with a github.com origin is GitHub outside CI too
        [url] = seen_urls(config, env, origin_url=origin)
        assert url.startswith("https://api.github.com/repos/o/n/pulls")
        require_forge_target(config, env, origin)


def test_github_repository_wins_over_origin():
    [url] = seen_urls(
        cfg(), {"L4_FORGE_TOKEN": GH_TOKEN, "GITHUB_REPOSITORY": "x/y"}, origin_url="git@github.com:o/n.git"
    )
    assert "/repos/x/y/pulls" in url


@pytest.mark.parametrize(
    ("origin", "api_prefix"),
    [
        ("git@gitlab.example.com:g/p.git", "https://gitlab.example.com/api/v4/projects/g%2Fp/"),
        ("https://gitlab.example.com/g/sub/p.git", "https://gitlab.example.com/api/v4/projects/g%2Fsub%2Fp/"),
        (
            "ssh://git@gitlab.example.com:2222/g/sub/deep/p.git",
            "https://gitlab.example.com/api/v4/projects/g%2Fsub%2Fdeep%2Fp/",
        ),
    ],
)
def test_gitlab_target_from_origin_keeps_nested_groups(origin, api_prefix):
    env = {"L4_FORGE_TOKEN": TOKEN}
    [url] = seen_urls(cfg({"type": "gitlab"}), env, origin_url=origin)
    assert url.startswith(api_prefix + "merge_requests")
    require_forge_target(cfg({"type": "gitlab"}), env, origin)


def test_configured_gitlab_values_win_over_origin():
    config = cfg({"type": "gitlab", "gitlab": {"api_url": "https://cfg.example.com/api/v4", "project": "77"}})
    [url] = seen_urls(config, {"L4_FORGE_TOKEN": TOKEN}, origin_url="git@gitlab.example.com:g/p.git")
    assert url.startswith("https://cfg.example.com/api/v4/projects/77/")


def test_each_gitlab_value_falls_back_on_its_own():
    config = cfg({"type": "gitlab", "gitlab": {"project": "77"}})
    [url] = seen_urls(config, {"L4_FORGE_TOKEN": TOKEN}, origin_url="git@gitlab.example.com:g/p.git")
    assert url.startswith("https://gitlab.example.com/api/v4/projects/77/")


def test_an_origin_that_names_no_host_is_still_a_config_error():
    for origin in (None, "/srv/git/repo.git"):
        with pytest.raises(L4Exit) as err:
            require_forge_target(cfg({"type": "gitlab"}), {"L4_FORGE_TOKEN": TOKEN}, origin)
        assert err.value.code == ExitCode.USAGE_ERROR


def test_make_forge_reads_origin_from_the_repo_when_given_one(tmp_path, git_environ):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", "git@github.com:o/n.git"], check=True)
    env = {**git_environ, "L4_FORGE_TOKEN": GH_TOKEN}
    forge = make_forge(cfg(), env, repo=tmp_path)
    assert isinstance(forge, GitHubForge)
    with pytest.raises(L4Exit):  # no origin: the same error as before
        make_forge(cfg({"type": "github"}), env, repo=tmp_path / "missing")


def test_the_git_username_follows_the_origin(tmp_path):
    env = {"L4_FORGE_TOKEN": GH_TOKEN}
    github, gitlab = "git@github.com:o/n.git", "git@gitlab.example.com:g/p.git"
    assert fetch_auth_config(cfg(), env, github) == fetch_auth_config(cfg({"type": "github"}), env)
    assert fetch_auth_config(cfg(), env, gitlab) == fetch_auth_config(cfg({"type": "gitlab"}), env)
    assert push_auth_config(cfg(), env, github)[:2] == fetch_auth_config(cfg({"type": "github"}), env)
    assert isinstance(make_forge(cfg({"type": "gitlab"}), env, origin_url=gitlab), GitLabForge)
