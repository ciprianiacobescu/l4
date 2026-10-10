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
