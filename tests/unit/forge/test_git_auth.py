import subprocess
from pathlib import Path

import pytest

from l4.forge.gitlab import git_auth_config, strip_remote_credentials
from l4.vcs.git import Git

from .conftest import TOKEN


def test_the_helper_prints_the_password_from_the_environment(git_environ):
    helper = git_auth_config("L4_FORGE_TOKEN")[-1][1]
    env = {**git_environ, "L4_FORGE_TOKEN": TOKEN}
    asked = subprocess.run(["sh", "-c", f"{helper[1:]} get"], env=env, capture_output=True, text=True, check=True)
    assert asked.stdout.splitlines() == ["username=oauth2", f"password={TOKEN}"]
    stored = subprocess.run(["sh", "-c", f"{helper[1:]} store"], env=env, capture_output=True, text=True, check=True)
    assert stored.stdout == ""


def test_git_itself_gets_the_credentials_through_the_helper(tmp_path: Path, git_environ):
    git = Git(tmp_path, environ={**git_environ, "L4_FORGE_TOKEN": TOKEN})
    done = git.run(
        "credential", "fill", input="protocol=https\nhost=gitlab.example.test\n\n",
        config=git_auth_config("L4_FORGE_TOKEN"),
    )  # fmt: skip
    assert f"password={TOKEN}" in done.stdout and "username=oauth2" in done.stdout


def test_token_not_in_argv_or_git_config(tmp_path: Path, git_environ, raw):
    raw(tmp_path, "init", "-q")
    git = Git(tmp_path, environ={**git_environ, "L4_FORGE_TOKEN": TOKEN})
    git.run("credential", "fill", input="protocol=https\nhost=h.example\n\n", config=git_auth_config("L4_FORGE_TOKEN"))
    assert TOKEN not in " ".join(" ".join(argv) for argv in git.history)
    assert "L4_FORGE_TOKEN" in " ".join(git.history[-1])  # the NAME is there
    assert TOKEN not in (tmp_path / ".git" / "config").read_text()


def test_the_helper_list_is_reset_first():
    config = git_auth_config("L4_FORGE_TOKEN")
    assert config[0] == ("credential.helper", "") and len(config) == 2


@pytest.mark.parametrize("name", ["", "A B", "X;rm -rf /", "1X", "a$(id)", 'a"b'])
def test_a_token_env_name_that_could_inject_shell_text_is_refused(name: str):
    with pytest.raises(ValueError):
        git_auth_config(name)


def test_origin_url_loses_credentials_and_token_not_in_argv(tmp_path: Path, git_environ, raw):
    raw(tmp_path, "init", "-q")
    raw(tmp_path, "remote", "add", "origin", f"https://gitlab-ci-token:{TOKEN}@gitlab.example.test:8443/g/p.git")
    git = Git(tmp_path, environ=git_environ)
    assert strip_remote_credentials(git) is True
    assert raw(tmp_path, "config", "--get", "remote.origin.url").strip() == "https://gitlab.example.test:8443/g/p.git"
    assert TOKEN not in (tmp_path / ".git" / "config").read_text()
    assert strip_remote_credentials(git) is False  # nothing left to strip


@pytest.mark.parametrize(
    "url", ["git@gitlab.example.test:g/p.git", "ssh://git@gitlab.example.test/g/p.git", "/srv/p.git"]
)
def test_ssh_and_local_origins_are_left_alone(url: str, tmp_path: Path, git_environ, raw):
    raw(tmp_path, "init", "-q")
    raw(tmp_path, "remote", "add", "origin", url)
    assert strip_remote_credentials(Git(tmp_path, environ=git_environ)) is False
    assert raw(tmp_path, "config", "--get", "remote.origin.url").strip() == url


def test_no_origin_is_not_an_error(tmp_path: Path, git_environ, raw):
    raw(tmp_path, "init", "-q")
    assert strip_remote_credentials(Git(tmp_path, environ=git_environ)) is False


# --- adoption-lessons 1.1 (L4-ADO-003): a push outside CI without a token keeps the person's credentials ------------


def _cfg(forge_type: str = "github", token_env: str = "GITHUB_TOKEN"):
    from l4.config.schema import L4Config

    return L4Config.model_validate({"forge": {"type": forge_type, "token_env": token_env}})


def test_a_laptop_push_without_a_token_has_no_helper_pairs():  # SCN-ADO-07
    from l4.forge.base import fetch_auth_config
    from l4.forge.gitlab import push_auth_config

    config = _cfg()
    assert push_auth_config(config, {}) == fetch_auth_config(config, {}) == ()
    assert push_auth_config(config, {"GITHUB_TOKEN": ""}) == ()


def test_ci_keeps_the_token_helper():  # SCN-ADO-08
    from l4.forge.gitlab import push_auth_config

    pairs = push_auth_config(_cfg(), {"GITHUB_ACTIONS": "true", "GITHUB_TOKEN": "t"})
    assert pairs[0] == ("credential.helper", "") and "GITHUB_TOKEN" in pairs[1][1]


def test_ci_keeps_the_helper_even_when_the_variable_is_empty():
    from l4.forge.gitlab import push_auth_config

    assert len(push_auth_config(_cfg(), {"GITHUB_ACTIONS": "true"})) == 2


def test_a_token_set_on_a_laptop_is_used():  # SCN-ADO-09
    from l4.forge.gitlab import push_auth_config

    pairs = push_auth_config(_cfg(), {"GITHUB_TOKEN": "t"})
    assert pairs[0] == ("credential.helper", "") and "GITHUB_TOKEN" in pairs[1][1]


def test_the_gitlab_push_url_workaround_is_unchanged_in_ci():
    from l4.forge.gitlab import push_auth_config

    env = {"GITLAB_CI": "true", "CI_SERVER_URL": "https://gl.example.test", "CI_PROJECT_PATH": "g/p"}
    pairs = push_auth_config(_cfg("gitlab", "L4_FORGE_TOKEN"), env)
    assert ("remote.origin.pushurl", "https://oauth2@gl.example.test/g/p.git") in pairs
