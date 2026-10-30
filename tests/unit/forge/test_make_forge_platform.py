import subprocess

import httpx
import pytest

from l4.config.schema import L4Config
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import (
    fetch_auth_config,
    forge_platform,
    forge_wanted,
    make_forge,
    parse_remote_url,
    require_forge_target,
    require_token_in_ci,
)
from l4.forge.github import GitHubForge
from l4.forge.gitlab import git_auth_config, push_auth_config
from l4.forge.local import LocalForge

from ._github_helpers import TOKEN as GH_TOKEN
from .conftest import TOKEN


def cfg(forge: dict | None = None, ci: dict | None = None) -> L4Config:
    return L4Config.model_validate({"forge": forge or {}, "ci": ci or {}})


@pytest.mark.parametrize(
    ("forge_type", "ci_platform", "env", "origin", "expected"),
    [
        ("gitlab", "github", {}, None, "gitlab"),  # forge.type is the first word
        ("github", "gitlab", {"GITLAB_CI": "true"}, None, "github"),
        ("local", "github", {"GITHUB_ACTIONS": "true"}, "git@github.com:o/r.git", "local"),
        ("auto", "github", {"GITLAB_CI": "true"}, None, "github"),  # then ci.platform
        ("auto", "local", {}, None, "gitlab"),  # ci.platform: local is no forge: it must not open `local://` MRs
        ("auto", "local", {}, "git@gitlab.com:example-group/dummy-agentic.git", "gitlab"),
        ("auto", "local", {}, "git@github.com:o/r.git", "github"),
        ("auto", "local", {"GITHUB_ACTIONS": "true"}, None, "github"),
        ("auto", "auto", {"GITLAB_CI": "true"}, "git@github.com:o/r.git", "gitlab"),  # then the CI variables
        ("auto", "auto", {"GITHUB_ACTIONS": "true"}, None, "github"),
        ("auto", "auto", {}, "git@github.com:o/r.git", "github"),  # then the host of origin
        ("auto", "auto", {}, "https://github.com/o/r", "github"),
        ("auto", "auto", {}, "ssh://git@gitlab.example.com:2222/g/p.git", "gitlab"),
        ("auto", "auto", {}, "https://ghe.example.com/o/r.git", "gitlab"),  # an unknown host is GitLab, as in M0
        ("auto", "auto", {}, None, "gitlab"),
    ],
)
def test_platform_selection_matrix(forge_type, ci_platform, env, origin, expected):
    config = cfg({"type": forge_type}, {"platform": ci_platform})
    assert forge_platform(config, env, origin) == expected
    if origin is None:  # `forge_wanted` has no origin to look at
        assert forge_wanted(config, env) is (expected == "gitlab")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:acme/widgets.git", ("github.com", "acme/widgets")),
        ("ssh://git@gitlab.example.com:2222/group/sub/proj.git", ("gitlab.example.com", "group/sub/proj")),
        ("https://x-access-token:tok@github.com/acme/widgets.git", ("github.com", "acme/widgets")),
        ("http://gitlab.test/g/p/", ("gitlab.test", "g/p")),
        ("/srv/git/repo.git", None),
        ("", None),
        ("https://github.com/", None),
    ],
)
def test_parse_remote_url(url, expected):
    found = parse_remote_url(url)
    assert (found is None and expected is None) or (found.host, found.path) == expected


def test_local_forge_for_type_local():
    forge = make_forge(cfg({"type": "local"}), {})  # a local forge needs no token
    assert isinstance(forge, LocalForge)


def test_github_forge_from_the_actions_environment():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    env = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "acme/widgets", "GITHUB_API_URL": "https://api.github.test",
        "L4_FORGE_TOKEN": GH_TOKEN,
    }  # fmt: skip
    forge = make_forge(cfg(), env, transport=httpx.MockTransport(handler))
    assert isinstance(forge, GitHubForge)
    assert forge.find_pr("l4/openspec/x") is None
    [request] = seen
    assert request.url.host == "api.github.test" and request.url.path == "/repos/acme/widgets/pulls"
    assert request.headers["Authorization"] == f"Bearer {GH_TOKEN}"


def test_github_target_from_origin_outside_actions_and_enterprise_hosts():
    seen: list[str] = []
    transport = httpx.MockTransport(lambda r: seen.append(str(r.url)) or httpx.Response(200, json=[]))
    env = {"L4_FORGE_TOKEN": GH_TOKEN}
    forge = cfg({"type": "github"})
    make_forge(forge, env, transport=transport, origin_url="git@github.com:acme/widgets.git").find_pr("b")
    make_forge(forge, env, transport=transport, origin_url="https://ghe.example.com/o/r").find_pr("b")
    assert seen[0].startswith("https://api.github.com/repos/acme/widgets/pulls")
    assert seen[1].startswith("https://ghe.example.com/api/v3/repos/o/r/pulls")


def test_github_without_a_repository_is_a_config_error_and_without_a_token_unavailable():
    from l4.forge.base import ForgeUnavailable

    with pytest.raises(L4Exit) as err:
        make_forge(cfg({"type": "github"}), {"L4_FORGE_TOKEN": GH_TOKEN})
    assert err.value.code == ExitCode.USAGE_ERROR and "GITHUB_REPOSITORY" in str(err.value)
    assert GH_TOKEN not in str(err.value)
    with pytest.raises(ForgeUnavailable, match="L4_FORGE_TOKEN is not set"):
        make_forge(cfg({"type": "github"}), {"GITHUB_REPOSITORY": "acme/widgets"})
    with pytest.raises(L4Exit):
        require_forge_target(cfg({"type": "github"}), {"L4_FORGE_TOKEN": GH_TOKEN})
    require_forge_target(cfg({"type": "github"}), {"L4_FORGE_TOKEN": GH_TOKEN, "GITHUB_REPOSITORY": "a/b"})


def test_actions_without_the_token_fails_closed_with_exit_3():
    with pytest.raises(L4Exit) as err:
        require_token_in_ci(cfg(), {"GITHUB_ACTIONS": "true"})
    assert err.value.code == ExitCode.DOCTOR_FAILED
    assert "L4_FORGE_TOKEN" in str(err.value) and "GitHub" in str(err.value)
    require_token_in_ci(cfg(), {"GITHUB_ACTIONS": "true", "L4_FORGE_TOKEN": GH_TOKEN})
    require_token_in_ci(cfg({"type": "local"}), {"GITHUB_ACTIONS": "true"})
    require_token_in_ci(cfg(), {})


def test_a_gitlab_forge_in_a_github_job_still_needs_its_token():
    """L4-CLI-004: "in a CI job" is one rule, whichever forge `forge.type` names; `CI=true` alone is not a job."""
    with pytest.raises(L4Exit) as err:
        require_token_in_ci(cfg({"type": "gitlab"}), {"GITHUB_ACTIONS": "true"})
    assert err.value.code == ExitCode.DOCTOR_FAILED
    require_token_in_ci(cfg({"type": "gitlab"}), {"CI": "true"})


def test_the_missing_token_message_names_the_forge_not_the_job():
    """L4-CLI-004: a forge's token is required in any CI job, so the text says what the forge needs."""
    for forge, job, want, other in (
        ("gitlab", "GITHUB_ACTIONS", "the GitLab forge needs the project access token", "GitHub"),
        ("github", "GITLAB_CI", "the GitHub forge needs a token that can push", "GitLab"),
        ("gitlab", "GITLAB_CI", "the GitLab forge needs the project access token", "GitHub"),
        ("github", "GITHUB_ACTIONS", "the GitHub forge needs a token that can push", "GitLab"),
    ):
        with pytest.raises(L4Exit) as err:
            require_token_in_ci(cfg({"type": forge}), {job: "true"})
        text = str(err.value)
        assert want in text and "L4_FORGE_TOKEN is not set" in text and other not in text, (forge, job)
        assert "job needs" not in text


def test_the_git_username_follows_the_platform(git_environ):
    github = {"GITHUB_ACTIONS": "true", "L4_FORGE_TOKEN": GH_TOKEN, "GITHUB_REPOSITORY": "a/b"}
    for config, env, username in (
        (cfg(), {"L4_FORGE_TOKEN": TOKEN}, "oauth2"),
        (cfg(), github, "x-access-token"),
    ):
        pairs = fetch_auth_config(config, env)
        helper = pairs[-1][1]
        asked = subprocess.run(
            ["sh", "-c", f"{helper[1:]} get"], env={**git_environ, **env}, capture_output=True, text=True, check=True
        )
        assert asked.stdout.splitlines()[0] == f"username={username}"
        assert push_auth_config(config, env)[:2] == pairs
        assert GH_TOKEN not in repr(pairs) and TOKEN not in repr(pairs)
    assert "x-access-token" in git_auth_config("L4_FORGE_TOKEN", username="x-access-token")[1][1]
    with pytest.raises(ValueError):
        git_auth_config("L4_FORGE_TOKEN", username="a; rm -rf /")
    assert fetch_auth_config(cfg({"type": "local"}), {"L4_FORGE_TOKEN": TOKEN}) == ()
