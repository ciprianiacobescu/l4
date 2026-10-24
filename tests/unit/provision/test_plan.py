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


def plan(cfg, paths, env, runner, openspec_active=True, platform="linux-x64", **kw):
    """The user-space actions by tool; the root-only `manual` ones have their own test."""
    actions = plan_fixes(cfg, paths, env, platform, openspec_active=openspec_active, run=runner, **kw)
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


def test_profile_in_any_role_chain_counts_and_kiro_is_pinned(paths, env):
    cfg = config(roles={"implementer": ["impl", "kiro"], "judges": ["judge"]})
    actions = plan(cfg, paths, env, FakeRunner(), openspec_active=False)
    assert "kiro-cli" in actions and "codex" not in actions
    command = actions["kiro-cli"].commands[0]
    assert "https://prod.download.cli.kiro.dev/stable/2.32.0/kirocli-" in command and "sha256sum -c" in command


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


# --- exact in CI, the floor rule elsewhere (L4-PRV-043, design D5), Kiro and the override (D4, D8, D9) ---


def solo(adapter: str, *, min_version: str | None = None, versions: dict[str, str] | None = None) -> L4Config:
    profile = {"adapter": adapter, **({"min_version": min_version} if min_version else {})}
    return L4Config.model_validate(
        {
            "profiles": {"p": profile, "judge": {"adapter": "fake"}},
            "roles": {"implementer": ["p"], "judges": ["judge"]},
            "ci": {"cli_versions": versions or {}},
        }
    )


def agent_plan(cfg, tool, paths, env, install_fake, found, **kw):
    install_fake(tool)
    return plan(cfg, paths, env, FakeRunner({tool: found}), openspec_active=False, **kw)[tool]


def test_ci_plans_a_cli_of_another_version(paths, env, install_fake):  # SCN-PRV-119
    action = agent_plan(solo("codex"), "codex", paths, env, install_fake, "codex-cli 0.161.0", replace_present=True)
    assert action.status == "planned" and action.reason == "found 0.161.0, pinned 0.160.0"
    assert "@openai/codex@0.160.0" in action.commands[0]
    same = agent_plan(solo("codex"), "codex", paths, env, install_fake, "codex-cli 0.160.0", replace_present=True)
    assert same.status == "already present"


def test_local_keeps_a_cli_of_another_version(paths, env, install_fake):  # SCN-PRV-120
    action = agent_plan(solo("codex"), "codex", paths, env, install_fake, "codex-cli 0.161.0")
    assert action.status == "already present" and action.commands == ()


def test_local_below_the_floor_installs_the_pin(paths, env, install_fake):  # SCN-PRV-120
    cfg = solo("codex", min_version="0.160.0")
    action = agent_plan(cfg, "codex", paths, env, install_fake, "codex-cli 0.150.0")
    assert action.status == "planned" and action.reason == "found 0.150.0, need 0.160.0"


def test_local_kiro_below_the_floor_is_planned(paths, env, install_fake):
    cfg = solo("kiro-cli", min_version="2.32.0")
    action = agent_plan(cfg, "kiro-cli", paths, env, install_fake, "kiro-cli 2.27.1")
    assert action.status == "planned" and action.reason == "found 2.27.1, need 2.32.0"


def test_local_kiro_of_another_major_is_manual(paths, env, install_fake):  # SCN-OCG-13
    runner_calls = FakeRunner({"kiro-cli": "kiro-cli 3.0.0"})
    install_fake("kiro-cli")
    action = plan(solo("kiro-cli"), paths, env, runner_calls, openspec_active=False)["kiro-cli"]
    assert action.status == "manual"
    assert action.reason == "found 3.0.0 (Kiro CLI 3), need kiro-cli 2.x (pinned 2.32.0)"
    assert action.reason in action.message and "sha256sum -c" in action.commands[0]


def test_ci_kiro_of_another_major_is_planned(paths, env, install_fake):  # SCN-OCG-13
    action = agent_plan(solo("kiro-cli"), "kiro-cli", paths, env, install_fake, "kiro-cli 3.0.0", replace_present=True)
    assert action.status == "planned"
    assert action.reason == "found 3.0.0 (Kiro CLI 3), need kiro-cli 2.x (pinned 2.32.0)"


def test_a_kiro_override_without_digests_is_manual(paths, env):  # SCN-PRV-127
    runner = FakeRunner()
    action = plan(solo("kiro-cli", versions={"kiro-cli": "2.31.1"}), paths, env, runner, openspec_active=False)[
        "kiro-cli"
    ]
    assert action.status == "manual"
    assert "kiro-cli 2.31.1 (ci.cli_versions) has no sha256 in this harness (it holds 2.27.1, 2.28.0, 2.32.0)" in (
        action.message
    )
    assert "install it yourself and keep it, or hold one of those" in action.message


def test_kiro_on_macos_is_manual(paths, env, install_fake):  # SCN-PRV-117
    cfg = solo("kiro-cli", min_version="2.32.0")
    missing = plan(cfg, paths, env, FakeRunner(), openspec_active=False, platform="darwin-arm64")["kiro-cli"]
    install_fake("kiro-cli")
    old = plan(
        cfg, paths, env, FakeRunner({"kiro-cli": "kiro-cli 2.27.1"}), openspec_active=False, platform="darwin-arm64"
    )
    for action in (missing, old["kiro-cli"]):
        assert action.status == "manual"
        assert "stable/2.32.0/Kiro%20CLI.dmg" in action.message
        assert "88721f97dbe98c9e4f84a46e8a2584a8dd29289b81264d96ee2987dd2c014e3c" in action.message


def test_an_override_is_the_target(paths, env, install_fake):  # SCN-PRV-125
    cfg = solo("kiro-cli", versions={"kiro-cli": "2.28.0"})
    action = agent_plan(cfg, "kiro-cli", paths, env, install_fake, "kiro-cli 2.32.0", replace_present=True)
    assert action.status == "planned" and action.reason == "found 2.32.0, pinned 2.28.0 (ci.cli_versions)"
    codex = solo("codex", versions={"codex": "0.150.0"})
    other = agent_plan(codex, "codex", paths, env, install_fake, "codex-cli 0.160.0", replace_present=True)
    assert other.reason.endswith("(ci.cli_versions)") and "@openai/codex@0.150.0" in other.commands[0]


def test_an_override_below_the_floor_is_skipped(paths, env, install_fake):
    cfg = solo("kiro-cli", min_version="2.32.0", versions={"kiro-cli": "2.28.0"})
    action = agent_plan(cfg, "kiro-cli", paths, env, install_fake, "kiro-cli 2.27.1", replace_present=True)
    assert action.status == "skipped"
    assert action.message == "min_version 2.32.0 is above the pinned 2.28.0; not installing"


def test_self_provision_false_still_skips_in_ci(paths, env, install_fake):
    action = agent_plan(
        solo("codex"), "codex", paths, env, install_fake, "codex-cli 0.161.0", replace_present=True, allow_install=False
    )
    assert action.status == "skipped" and "self_provision" in action.message


def test_ci_holds_only_agent_clis_to_the_exact_pin(paths, env, install_fake):
    """Node keeps its floor rule in CI (a node at least NODE_MIN is left alone): only agents are exact."""
    install_fake("node")
    actions = plan(
        solo("codex"), paths, env, FakeRunner({"node": "v22.10.0"}), openspec_active=False, replace_present=True
    )
    assert actions["node"].status == "already present"


# --- Copilot CLI (L4-PRV-047, L4-OCG-006) ---

COPILOT_2 = "GitHub Copilot CLI 2.0.0.\nRun 'copilot update' to check for updates."
COPILOT_REASON = "found 2.0.0 (Copilot CLI 2), need copilot 1.x (pinned 1.0.102)"


def test_scn_prv_133_a_copilot_version_without_a_digest_is_manual_and_the_pin_is_planned(paths, env):
    unheld = solo("copilot-cli", versions={"copilot-cli": "1.0.103"})
    action = plan(unheld, paths, env, FakeRunner(), openspec_active=False)["copilot"]
    assert action.status == "manual" and "copilot 1.0.103 (ci.cli_versions) has no sha256 in this harness" in (
        action.message
    )
    assert "(it holds 1.0.102): install it yourself and keep it, or hold one of those" in action.message
    held = plan(solo("copilot-cli"), paths, env, FakeRunner(), openspec_active=False)["copilot"]
    assert held.status == "planned" and held.reason == "missing"
    assert "copilot-linux-x64.tar.gz" in held.commands[0] and "sha256sum -c" in held.commands[0]


def test_scn_ocg_16_ci_replaces_a_copilot_cli_2_and_a_persons_fix_leaves_it(paths, env, install_fake):
    ci = agent_plan(solo("copilot-cli"), "copilot", paths, env, install_fake, COPILOT_2, replace_present=True)
    assert ci.status == "planned" and ci.reason == COPILOT_REASON
    person = agent_plan(solo("copilot-cli"), "copilot", paths, env, install_fake, COPILOT_2)
    assert person.status == "manual" and person.reason == COPILOT_REASON
    assert COPILOT_REASON in person.message and "sha256sum -c" in person.commands[0]


def test_a_copilot_plan_on_darwin_arm64_installs_with_no_manual_step(paths, env, install_fake):
    missing = plan(solo("copilot-cli"), paths, env, FakeRunner(), openspec_active=False, platform="darwin-arm64")
    assert missing["copilot"].status == "planned" and "copilot-darwin-arm64.tar.gz" in missing["copilot"].commands[0]
    assert "shasum -a 256 -c -" in missing["copilot"].commands[0]
    old = agent_plan(
        solo("copilot-cli", min_version="1.0.102"), "copilot", paths, env, install_fake, "GitHub Copilot CLI 1.0.100.",
        platform="darwin-arm64",
    )  # fmt: skip
    assert old.status == "planned" and old.reason == "found 1.0.100, need 1.0.102"


def test_a_copilot_unsupported_platform_stays_manual(paths, env):
    action = plan(solo("copilot-cli"), paths, env, FakeRunner(), openspec_active=False, platform="windows-x64")[
        "copilot"
    ]
    assert action.status == "manual"


# --- OpenCode 2 is planned under its own name and gate key (L4-OCV-002, amendment E2) ---


def v2_config(**kw) -> L4Config:
    profiles = {"oc2": {"adapter": "opencode", "model": "m", "vendor": "unknown", "options": {"cli_major": 2}}}
    return L4Config.model_validate({"profiles": profiles, "roles": {"implementer": ["oc2"], "judges": []}, **kw})


def test_a_v2_profile_plans_opencode2_with_its_prefix_in_the_manual_command(paths, env, install_fake):  # SCN-OCV-04
    actions = plan(v2_config(), paths, env, FakeRunner(), openspec_active=False)
    assert list(actions) == ["uv", "node", "opencode2"]  # npm-installed: Node comes along; never `opencode`
    assert actions["opencode2"].status == "planned" and actions["opencode2"].reason == "missing"
    command = actions["opencode2"].commands[0]
    assert f"--prefix {paths.l4_home}/npm-opencode2 " in command and "@opencode/cli@2.0.32" in command


def test_a_v1_named_opencode2_is_planned_for_the_v2_pin_with_a_named_reason(paths, env, install_fake):
    install_fake("opencode2")
    actions = plan(v2_config(), paths, env, FakeRunner({"opencode2": "1.18.34"}), openspec_active=False)
    assert actions["opencode2"].status == "planned"
    assert actions["opencode2"].reason == "found 1.18.34 (OpenCode v1), need @opencode/cli 2.x (pinned 2.0.32)"
    ok = plan(v2_config(), paths, env, FakeRunner({"opencode2": "opencode v2.0.32"}), openspec_active=False)
    assert ok["opencode2"].status == "already present"


def test_ci_replaces_an_opencode2_other_than_its_effective_pin(paths, env, install_fake):  # L4-PRV-043
    install_fake("opencode2")
    config = v2_config(ci={"cli_versions": {"opencode2": "2.0.33"}})
    runner = FakeRunner({"opencode2": "opencode v2.0.32"})
    action = plan(config, paths, env, runner, openspec_active=False, replace_present=True)["opencode2"]
    assert action.status == "planned" and action.reason == "found 2.0.32, pinned 2.0.33 (ci.cli_versions)"
    assert "@opencode/cli@2.0.33" in action.commands[0]
