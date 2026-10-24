from pathlib import Path

from l4.config.schema import L4Config
from l4.provision.runner import Paths, find_tool, harness_path, resolve_self_provision, scrub_env


def test_harness_path_order_and_find_tool(paths, env, install_fake, tmp_path):
    sysbin = tmp_path / "sysbin"
    parts = harness_path(paths, f"{sysbin}:relative/bin::").split(":")
    assert parts == [
        str(paths.home / ".local/bin"),
        str(paths.l4_home / "node/bin"),
        str(paths.l4_home / "npm/node_modules/.bin"),
        str(paths.home / ".opencode/bin"),
        str(sysbin),
    ]  # relative and empty entries are dropped
    install_fake("tool", sysbin)
    assert find_tool("tool", paths, env) == sysbin / "tool"
    local = install_fake("tool")
    assert find_tool("tool", paths, env) == local  # user-local installs win over the inherited PATH
    assert find_tool("absent", paths, env) is None


def test_a_checkout_on_path_is_never_searched(paths, env, install_fake, tmp_path):
    repo = tmp_path / "repo"
    install_fake("planted", repo / "bin")
    assert find_tool("planted", paths, {**env, "PATH": str(repo / "bin")}, forbid=(repo,)) is None


def test_from_env_defaults(tmp_path):
    p = Paths.from_env({"HOME": str(tmp_path)})
    assert p.local_bin == tmp_path / ".local/bin"
    assert p.l4_home == tmp_path / ".local/share/l4"
    assert p.l4_cache == tmp_path / ".cache/l4"
    assert p.npm_prefix == p.l4_home / "npm"
    assert Paths.from_env({"HOME": str(tmp_path), "XDG_CACHE_HOME": str(tmp_path / "x")}).l4_cache == tmp_path / "x/l4"


def cfg(value) -> L4Config:
    return L4Config.model_validate({"ci": {"self_provision": value}})


def test_auto_resolution_matrix():
    assert resolve_self_provision(cfg("auto"), {}) is True  # a persistent shell runner, or a local run
    assert resolve_self_provision(cfg("auto"), {"GITLAB_CI": "true"}) is True
    assert resolve_self_provision(cfg("auto"), {"CI_DISPOSABLE_ENVIRONMENT": "true"}) is False
    assert resolve_self_provision(cfg("auto"), {"RUNNER_ENVIRONMENT": "github-hosted"}) is False
    assert resolve_self_provision(cfg("auto"), {"RUNNER_ENVIRONMENT": "self-hosted"}) is True
    assert resolve_self_provision(cfg(True), {"CI_DISPOSABLE_ENVIRONMENT": "true"}) is True
    assert resolve_self_provision(cfg(False), {}) is False
    assert L4Config().ci.self_provision == "auto"


def test_env_override_beats_the_config_setting():
    hosted = {"RUNNER_ENVIRONMENT": "github-hosted"}
    assert resolve_self_provision(cfg("auto"), {**hosted, "L4_SELF_PROVISION": "true"}) is True
    assert resolve_self_provision(cfg("auto"), {**hosted, "L4_SELF_PROVISION": "TRUE"}) is True
    assert resolve_self_provision(cfg(True), {"L4_SELF_PROVISION": "false"}) is False
    assert resolve_self_provision(cfg(False), {"L4_SELF_PROVISION": "auto"}) is True  # auto: the usual rule
    assert resolve_self_provision(cfg(True), {**hosted, "L4_SELF_PROVISION": "auto"}) is False
    for ignored in ("", "yes", "1", "garbage"):
        assert resolve_self_provision(cfg(False), {"L4_SELF_PROVISION": ignored}) is False
        assert resolve_self_provision(cfg(True), {"L4_SELF_PROVISION": ignored}) is True
        assert resolve_self_provision(cfg("auto"), {**hosted, "L4_SELF_PROVISION": ignored}) is False


def test_forge_and_agent_secrets_never_reach_installer(paths):
    env = {
        "HOME": "/h", "LANG": "C", "LC_ALL": "C", "TMPDIR": "/t", "HTTPS_PROXY": "http://proxy:3128",
        "SSL_CERT_FILE": "/ca.pem", "NODE_EXTRA_CA_CERTS": "/ca2.pem", "PATH": "/usr/bin:rel",
        "L4_FORGE_TOKEN": "glpat-" + "x" * 20, "ANTHROPIC_API_KEY": "sk-ant-fake", "CODEX_API_KEY": "fake",
        "CLAUDE_CODE_OAUTH_TOKEN": "fake", "KIRO_API_KEY": "ksk_fake", "OPENROUTER_API_KEY": "fake",
        "L4_GITHUB_APP_KEY": "fake", "GITLAB_USER_TOKEN": "fake", "npm_config_cache": "/elsewhere",
    }  # fmt: skip
    clean = scrub_env(env, paths)
    assert set(clean) == {
        "HOME", "LANG", "LC_ALL", "TMPDIR", "HTTPS_PROXY", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "PATH",
        "npm_config_cache", "DISABLE_AUTOUPDATER",
    }  # fmt: skip
    assert clean["npm_config_cache"] == str(paths.l4_cache / "npm")
    assert clean["PATH"].split(":")[-1] == "/usr/bin"
    assert Path(clean["PATH"].split(":")[0]) == paths.local_bin


def test_an_installer_env_keeps_the_updater_off_and_claude_install_on(paths):  # SCN-PRV-122
    for host in ({}, {"DISABLE_UPDATES": "1"}, {"DISABLE_AUTOUPDATER": "0", "DISABLE_UPDATES": "1"}):
        clean = scrub_env({"HOME": "/h", "PATH": "/usr/bin", **host}, paths)
        assert clean["DISABLE_AUTOUPDATER"] == "1" and "DISABLE_UPDATES" not in clean


def test_the_opencode2_prefix_is_apart_and_never_on_the_harness_path(paths):  # L4-OCV-002
    assert paths.npm_prefix_opencode2 == paths.l4_home / "npm-opencode2"
    parts = harness_path(paths, "").split(":")
    assert not any("npm-opencode2" in part for part in parts)
    assert str(paths.l4_home / "npm/node_modules/.bin") in parts  # the v1 prefix still is
    assert not any("npm-opencode2" in part for part in scrub_env({"PATH": "/usr/bin"}, paths)["PATH"].split(":"))
