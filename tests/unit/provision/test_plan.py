from l4.config.schema import L4Config
from l4.provision.runner import detect_platform, plan_fixes

from .conftest import FakeRunner


def config(**kw) -> L4Config:
    base = {
        "profiles": {
            "impl": {"adapter": "claude-code", "auth": "subscription", "min_version": "2.1.0"},
            "fb": {"adapter": "codex"},
            "judge": {"adapter": "fake"},
            "kiro": {"adapter": "kiro-cli"},
            "unused": {"adapter": "opencode"},
        },
        "roles": {"implementer": ["impl", "fb"], "judges": ["judge"]},
    }
    return L4Config.model_validate({**base, **kw})


def plan(cfg, paths, env, runner, openspec_active=True, **kw):
    """The user-space actions by tool; the root-only `manual` ones have their own test."""
    actions = plan_fixes(cfg, paths, env, "linux-x64", openspec_active=openspec_active, run=runner, **kw)
    return {a.tool: a for a in actions if not a.needs_root}


def test_only_needed_tools_are_planned(paths, env):
    actions = plan(config(), paths, env, FakeRunner())
    assert list(actions) == [
        "uv",
        "node",
        "openspec",
        "claude",
        "codex",
    ]  # fallback codex included, opencode and kiro not
    assert {a.status for a in actions.values()} == {"planned"}
    assert "download" in actions["node"].commands[0] and "linux-x64" in actions["node"].commands[0]
    assert (
        "--prefix" in actions["openspec"].commands[0]
        and "@fission-ai/openspec@1.14.0" in actions["openspec"].commands[0]
    )
    assert actions["claude"].commands[0].endswith("| bash -s 2.1.288")
    no_spec = plan(config(), paths, env, FakeRunner(), openspec_active=False)
    assert list(no_spec) == ["uv", "node", "claude", "codex"]  # node stays: codex installs through npm
    only_claude = plan(
        config(roles={"implementer": ["impl"], "judges": ["judge"]}), paths, env, FakeRunner(), openspec_active=False
    )
    assert list(only_claude) == ["uv", "claude"]


def test_profile_in_any_role_chain_counts_and_kiro_is_unpinned(paths, env):
    cfg = config(roles={"implementer": ["impl"], "judges": ["judge"], "clarifier": ["kiro"]})
    actions = plan(cfg, paths, env, FakeRunner(), openspec_active=False)
    assert "kiro-cli" in actions and "codex" not in actions
    assert actions["kiro-cli"].commands[0] == "curl -fsSL https://cli.kiro.dev/install | bash"


def test_runner_like_fixture_is_already_present(paths, env, install_fake):
    for name in ("uv", "node", "claude", "codex"):
        install_fake(name)
    entry = paths.npm_prefix / "node_modules/@fission-ai/openspec/bin"
    entry.mkdir(parents=True)
    (entry / "openspec.js").write_text("//")
    runner = FakeRunner(
        {
            "uv": "uv 0.12.22",
            "node": "v22.23.0",
            "openspec": "1.14.0",
            "claude": "2.1.288 (Claude Code)",
            "codex": "codex-cli 0.160.0",
        }
    )
    actions = plan(config(), paths, env, runner)
    assert {a.status for a in actions.values()} == {"already present"}
    assert all(a.commands == () for a in actions.values())
    assert actions["node"].message == "node 22.23.0"


def test_too_old_tools_are_planned_with_both_versions_named(paths, env, install_fake):
    install_fake("node")
    install_fake("claude")
    runner = FakeRunner({"node": "v20.18.0", "claude": "2.0.9 (Claude Code)"})
    actions = plan(config(), paths, env, runner, openspec_active=False)
    assert actions["node"].status == "planned" and "found 20.18.0, need 20.19.0" in actions["node"].reason
    assert actions["claude"].status == "planned" and "found 2.0.9, need 2.1.0" in actions["claude"].reason


def test_openspec_with_the_wrong_version_is_planned(paths, env, install_fake):
    install_fake("node")
    entry = paths.npm_prefix / "node_modules/@fission-ai/openspec/bin"
    entry.mkdir(parents=True)
    (entry / "openspec.js").write_text("//")
    actions = plan(config(), paths, env, FakeRunner({"node": "v22.23.0", "openspec": "1.13.0"}))
    assert actions["openspec"].status == "planned"
    assert actions["node"].status == "already present"


def test_installs_switched_off_skip_missing_tools_but_not_present_ones(paths, env, install_fake):
    install_fake("uv")
    actions = plan(config(), paths, env, FakeRunner({"uv": "uv 0.12.22"}), allow_install=False)
    assert actions["uv"].status == "already present"
    assert actions["node"].status == "skipped" and "self_provision" in actions["node"].message


def test_a_present_tool_is_probed_from_the_harness_path_only(paths, env, install_fake):
    runner = FakeRunner({"uv": "uv 0.12.22"})
    install_fake("uv")
    plan(config(), paths, env, runner)
    assert runner.calls and all(call[0].startswith(str(paths.home)) for call in runner.calls)


def test_root_prerequisites_ride_along_as_manual_actions(paths, env, install_fake, tmp_path):
    os_release = 'ID=ubuntu\nID_LIKE=debian\nNAME="Ubuntu"\n'
    every = plan_fixes(
        config(), paths, env, "linux-x64", openspec_active=False, run=FakeRunner(), os_release=os_release
    )
    manual = [a for a in every if a.status == "manual"]
    assert [(a.tool, a.commands) for a in manual] == [
        ("bubblewrap", ("sudo apt-get install -y bubblewrap",)),
        ("git", ("sudo apt-get install -y git",)),
    ]
    install_fake("git", tmp_path / "sysbin")
    install_fake("bwrap", tmp_path / "sysbin")
    done = plan_fixes(config(), paths, env, "linux-x64", openspec_active=False, run=FakeRunner(), os_release=os_release)
    assert not [a for a in done if a.status == "manual"]


def test_detect_platform_has_the_catalog_shape():
    assert detect_platform().count("-") == 1


def _opencode_tool():
    from l4.provision.catalog import required_tools

    cfg = config(roles={"implementer": ["unused"], "judges": ["judge"]})
    return next(t for t in required_tools(cfg, openspec_active=False) if t.name == "opencode"), cfg


def test_an_opencode_of_another_major_is_not_satisfied(paths, env, install_fake):  # SCN-OCG-08
    from l4.provision.runner import is_satisfied

    tool, _ = _opencode_tool()
    assert tool.min_version is None  # no floor: the major alone decides
    assert not is_satisfied(tool, "2.0.32")
    assert is_satisfied(tool, "1.18.34")
    assert is_satisfied(tool, "1.19.3")


def test_a_v2_opencode_is_planned_for_the_pinned_v1_with_a_named_reason(paths, env, install_fake):  # SCN-OCG-08
    tool, cfg = _opencode_tool()
    install_fake("opencode")
    runner = FakeRunner({"opencode": "opencode v2.0.32"})
    actions = plan(cfg, paths, env, runner, openspec_active=False)
    assert actions["opencode"].status == "planned"
    assert actions["opencode"].reason == "found 2.0.32 (OpenCode v2), need opencode-ai 1.x (pinned 1.18.34)"
    install_fake("opencode")
    ok = plan(cfg, paths, env, FakeRunner({"opencode": "1.18.34"}), openspec_active=False)
    assert ok["opencode"].status == "already present"
