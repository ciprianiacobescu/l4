"""Live failure (job 5420): the runner writes `url.https://gitlab-ci-token:<JOB_TOKEN>@host.insteadOf=https://host` into
the checkout's config, so a push to the origin carried the JOB token and never asked the credential helper. The harness
pushes to `https://oauth2@host/<project>.git` instead: that string does not start with the rewritten prefix."""

import subprocess
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.forge.gitlab import git_auth_config
from l4.forge.pushurl import push_url, runner_rewrites_urls
from l4.vcs.git import Git, GitError

from .conftest import TOKEN

HOST = "https://gitlab.example.com"
JOB_TOKEN = "glcbt-FAKEJOBTOKEN0123"


def cfg(api_url: str | None = None, project: str | None = None) -> L4Config:
    return L4Config.model_validate({"version": 1, "forge": {"gitlab": {"api_url": api_url, "project": project}}})


def ci(server: str, path: str, **more: str) -> dict[str, str]:
    return {"GITLAB_CI": "true", "CI_SERVER_URL": server, "CI_PROJECT_PATH": path, **more}


def test_ci_url_is_built_from_the_server_url_and_project_path():
    got = push_url(cfg(), ci(HOST, "example-group/dummy-agentic"))
    assert got == "https://oauth2@gitlab.example.com/example-group/dummy-agentic.git"


@pytest.mark.parametrize(
    ("server", "path", "want"),
    [
        ("https://gl.example:8443", "g/p", "https://oauth2@gl.example:8443/g/p.git"),  # port
        ("https://gl.example/", "a/b/c/d", "https://oauth2@gl.example/a/b/c/d.git"),  # subgroups, trailing slash
        ("https://gl.example/gitlab", "g/p", "https://oauth2@gl.example/gitlab/g/p.git"),  # relative url root
        ("http://localhost:8080", "g/p", "http://oauth2@localhost:8080/g/p.git"),
        ("https://[::1]:8443", "g/p", "https://oauth2@[::1]:8443/g/p.git"),
        ("https://gl.example", "g/p.git", "https://oauth2@gl.example/g/p.git"),  # no double suffix
        ("https://gl.example", "g/my project", "https://oauth2@gl.example/g/my%20project.git"),
        ("https://job:secret@gl.example", "g/p", "https://oauth2@gl.example/g/p.git"),  # userinfo never carried over
    ],
)
def test_url_shapes(server, path, want):
    assert push_url(cfg(), ci(server, path)) == want


@pytest.mark.parametrize("path", ["", "/", "g/../x", "g//p", "../p", "g/p?x=1", "g/p#f"])
def test_a_project_path_that_is_not_a_path_gives_no_url(path):
    assert push_url(cfg(), ci(HOST, path)) is None


@pytest.mark.parametrize("server", ["", "ftp://gl.example", "gl.example", "ssh://git@gl.example"])
def test_a_server_url_that_is_not_http_gives_no_url(server):
    assert push_url(cfg(), ci(server, "g/p")) is None


def test_outside_ci_it_comes_from_the_forge_config():
    config = cfg("https://gl.example:8443/api/v4", "grp/sub/proj")
    assert push_url(config, {}) == "https://oauth2@gl.example:8443/grp/sub/proj.git"
    assert push_url(cfg("https://gl.example/gitlab/api/v4", "g/p"), {}) == "https://oauth2@gl.example/gitlab/g/p.git"


def test_outside_ci_a_numeric_project_or_a_missing_key_gives_no_url():
    assert push_url(cfg("https://gl.example/api/v4", "118"), {}) is None
    assert push_url(cfg("https://gl.example/api/v4", None), {}) is None
    assert push_url(cfg(None, "g/p"), {}) is None


def test_in_ci_a_gap_falls_back_to_the_config():
    env = {"GITLAB_CI": "true"}
    assert push_url(cfg("https://gl.example/api/v4", "g/p"), env) == "https://oauth2@gl.example/g/p.git"
    assert push_url(cfg(), env) is None


def test_outside_ci_the_ci_variables_are_ignored():
    assert push_url(cfg(), {"CI_SERVER_URL": HOST, "CI_PROJECT_PATH": "g/p"}) is None


def _runner_conf(tmp_path: Path, token: str = JOB_TOKEN) -> dict[str, str]:
    project = tmp_path / "builds" / "example-group" / "dummy-agentic"
    project.mkdir(parents=True)
    ext = Path(f"{project}.tmp") / ".gitlab-runner.ext.conf"
    ext.parent.mkdir()
    ext.write_text(
        f'[http]\n\textraheader = X-Gitaly-Correlation-ID: 01ABC\n[url "https://gitlab-ci-token:{token}@gitlab-host.x"]\n'
        f"\tinsteadOf = https://gitlab-host.x\n"
    )
    return {"GITLAB_CI": "true", "CI_PROJECT_DIR": str(project)}


def test_the_runner_rule_is_detected_without_reading_its_values_into_a_message(tmp_path):
    assert runner_rewrites_urls(_runner_conf(tmp_path)) is True
    assert runner_rewrites_urls({"GITLAB_CI": "true", "CI_PROJECT_DIR": str(tmp_path / "none")}) is False
    assert runner_rewrites_urls({}) is False


def test_the_rule_does_not_match_the_push_url_but_does_match_the_origin(tmp_path, raw):
    """Real git, no network: `remote get-url --push` applies the same rewriting a push does."""
    repo = tmp_path / "repo"
    raw(tmp_path, "init", "-q", str(repo))
    raw(repo, "remote", "add", "origin", f"{HOST}/example-group/dummy-agentic.git")
    raw(repo, "config", f"url.https://gitlab-ci-token:{JOB_TOKEN}@gitlab.example.com.insteadOf", HOST)
    full = f"url.https://gitlab-ci-token:{JOB_TOKEN}@gitlab.example.com/example-group/dummy-agentic.git.insteadOf"
    raw(repo, "config", full, f"{HOST}/example-group/dummy-agentic.git")
    assert JOB_TOKEN in raw(repo, "remote", "get-url", "--push", "origin")  # the bug: the job token wins
    url = push_url(cfg(), ci(HOST, "example-group/dummy-agentic"))
    assert url is not None
    pushed = raw(repo, "-c", f"remote.origin.pushurl={url}", "remote", "get-url", "--push", "origin").strip()
    assert pushed == url and JOB_TOKEN not in pushed
    fetched = raw(repo, "-c", f"remote.origin.pushurl={url}", "remote", "get-url", "origin").strip()
    assert JOB_TOKEN in fetched  # fetches keep the job token (it can read)


def test_a_push_through_pushurl_escapes_a_rewrite_and_updates_the_tracking_ref(tmp_path, raw, git_environ, make_repo):
    """origin is rewritten to a dead target by an insteadOf rule; the push still lands in the real origin and
    refs/remotes/origin/* follows, and the credential never reaches argv."""
    repo = make_repo(remote=True)
    origin = tmp_path / "repo-origin.git"
    dead = tmp_path / "dead" / "readonly.git"
    raw(repo, "config", f"url.{dead}.insteadOf", str(origin))  # what the runner's rule does to the origin
    git = Git(repo, environ={**git_environ, "L4_FORGE_TOKEN": TOKEN})
    git.run("checkout", "-q", "-b", "l4/openspec/x")
    (repo / "a.txt").write_text("a\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q", "-m", "one")
    with pytest.raises(GitError):  # without pushurl the rewrite wins and the push goes nowhere
        git.push("origin", ["HEAD:refs/heads/l4/openspec/x"])
    config = (*git_auth_config("L4_FORGE_TOKEN"), ("remote.origin.pushurl", f"file://localhost{origin}"))
    git.push("origin", ["HEAD:refs/heads/l4/openspec/x"], config=config)
    head = raw(repo, "rev-parse", "HEAD").strip()
    assert raw(origin.parent, "--git-dir", str(origin), "rev-parse", "refs/heads/l4/openspec/x").strip() == head
    assert raw(repo, "rev-parse", "refs/remotes/origin/l4/openspec/x").strip() == head
    assert TOKEN not in " ".join(" ".join(argv) for argv in git.history)
    assert not subprocess.run(["grep", "-r", TOKEN, str(repo / ".git")], capture_output=True).stdout


def test_the_missing_token_message_explains_the_403_when_the_runner_rewrites_urls(tmp_path):
    from l4.exitcodes import L4Exit
    from l4.forge.base import require_token_in_ci

    with pytest.raises(L4Exit) as plain:
        require_token_in_ci(cfg(), {"GITLAB_CI": "true"})
    assert "job token" not in str(plain.value)
    with pytest.raises(L4Exit) as rewritten:
        require_token_in_ci(cfg(), _runner_conf(tmp_path))
    message = str(rewritten.value)
    assert "job token" in message and "403" in message and JOB_TOKEN not in message
