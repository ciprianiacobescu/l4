"""P5: a forge host in a committed file is private information of the project's owner. The placeholder `<forge>` stands
for it in everything the harness commits; the console, the JSONL mirror and `outcome.json` keep the real link."""

from l4.config.schema import L4Config
from l4.forge.urls import PLACEHOLDER, ForgeUrls, forge_urls

GITLAB = {
    "GITLAB_CI": "true", "CI_SERVER_URL": "https://gitlab.corp.example", "CI_API_V4_URL": "https://gitlab.corp.example/api/v4",
}  # fmt: skip
MR = "https://gitlab.corp.example/group/project/-/merge_requests/7"


def cfg(**observability: object) -> L4Config:
    return L4Config.model_validate({"observability": observability})


def test_forge_hosts_become_the_placeholder_and_others_stay():
    urls = forge_urls(cfg(), GITLAB, "git@gitlab.corp.example:group/project.git")
    assert (
        urls.scrub(MR)
        == "<forge>/group/project/-/merge_requests/7"
        == f"{PLACEHOLDER}/group/project/-/merge_requests/7"
    )
    text = f"see {MR} and https://other.example/x and https://gitlab.corp.example.evil/y, api https://gitlab.corp.example/api/v4/jobs"
    assert urls.scrub(text) == (
        "see <forge>/group/project/-/merge_requests/7 and https://other.example/x and "
        "https://gitlab.corp.example.evil/y, api <forge>/api/v4/jobs"
    )
    assert urls.scrub("no link here") == "no link here" and urls.scrub("") == ""
    # the host named only by the origin remote, or by forge.gitlab.api_url, counts too
    only_origin = forge_urls(cfg(), {}, "https://token@git.example.test:8443/a/b.git")
    assert only_origin.scrub("https://git.example.test:8443/a/b") == "<forge>/a/b"
    configured = L4Config.model_validate(
        {"forge": {"gitlab": {"api_url": "https://gl.internal/api/v4", "project": "a/b"}}}
    )
    assert forge_urls(configured, {}, None).scrub("https://gl.internal/a/b") == "<forge>/a/b"
    github = forge_urls(
        cfg(),
        {"GITHUB_SERVER_URL": "https://github.corp.example", "GITHUB_API_URL": "https://github.corp.example/api/v3"},
        None,
    )
    assert github.scrub("https://github.corp.example/o/r/pull/3") == "<forge>/o/r/pull/3"


def test_expand_restores_the_web_base():
    urls = forge_urls(cfg(), GITLAB, None)
    assert urls.expand("<forge>/group/project/-/merge_requests/7") == MR
    assert urls.expand("a <forge>/x and <forge>") == "a https://gitlab.corp.example/x and https://gitlab.corp.example"
    assert urls.expand(MR) == MR and urls.expand("<forgery>/x") == "<forgery>/x"
    # a host that is not known has no web base: the placeholder stays, and scrubbing is a no-op
    unknown = forge_urls(cfg(), {}, "/local/path")
    assert unknown.expand("<forge>/a/b") == "<forge>/a/b" and unknown.scrub(MR) == MR
    # the web base of GitHub is not its API host
    gh = forge_urls(
        cfg(), {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_API_URL": "https://api.github.com"}, None
    )
    assert gh.expand("<forge>/o/r/pull/3") == "https://github.com/o/r/pull/3"
    assert gh.scrub("https://api.github.com/repos/o/r") == "<forge>/repos/o/r"


def test_canonical_matches_old_and_new_forms():
    urls = forge_urls(cfg(), GITLAB, None)
    old, new = MR, "<forge>/group/project/-/merge_requests/7"
    assert urls.canonical(old) == urls.canonical(new) == new
    assert urls.canonical(old) != urls.canonical("<forge>/group/project/-/merge_requests/8")
    assert urls.canonical("https://elsewhere.example/a") == "https://elsewhere.example/a"
    gh = forge_urls(cfg(), {"GITHUB_SERVER_URL": "https://github.com"}, None)  # a GitHub pull request is `/pull/N`
    assert (
        gh.canonical("https://github.com/o/r/pull/22") == gh.canonical("<forge>/o/r/pull/22") == "<forge>/o/r/pull/22"
    )
    assert gh.canonical("https://github.com/o/r/pull/22") != gh.canonical("<forge>/o/r/pull/23")


def test_off_scrubs_nothing_and_expands_nothing():
    urls = forge_urls(cfg(redact_forge_urls=False), GITLAB, None)
    assert urls.scrub(MR) == MR and urls.expand("<forge>/x") == "<forge>/x" and urls.canonical(MR) == MR
    assert ForgeUrls(frozenset(), None).scrub(MR) == MR


def test_a_link_with_credentials_or_the_other_scheme_is_scrubbed_too():
    """A job log tail is committed (`ci.failed`, the step-0 finding, a fix unit's proposal): pip prints its index as
    `https://__token__:****@<host>/...` and a redirect may say `http://`. The host goes either way."""
    urls = forge_urls(cfg(), GITLAB, None)
    log = (
        "Looking in indexes: https://__token__:****@gitlab.corp.example/api/v4/projects/1/packages/pypi/simple\n"
        "Redirecting to http://GITLAB.corp.example/group/project\n"
        "Cloning https://gitlab-ci-token:[MASKED]@gitlab.corp.example/group/project.git"
    )
    scrubbed = urls.scrub(log)
    assert "gitlab.corp.example" not in scrubbed.lower(), scrubbed
    assert scrubbed.splitlines() == [
        "Looking in indexes: <forge>/api/v4/projects/1/packages/pypi/simple",
        "Redirecting to <forge>/group/project",
        "Cloning <forge>/group/project.git",
    ]
    assert urls.scrub("https://user@gitlab.corp.example.evil/x") == "https://user@gitlab.corp.example.evil/x"
