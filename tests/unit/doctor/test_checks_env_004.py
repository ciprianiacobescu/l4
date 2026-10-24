import pytest

from l4.config.schema import L4Config
from l4.doctor import checks_env as env
from l4.doctor.registry import Check, Registry, exit_code, run_checks

PROFILES = {
    "impl": {"adapter": "claude-code", "min_version": "2.1.0"},
    "fb": {"adapter": "codex"},
    "judge": {"adapter": "codex"},
    "fake": {"adapter": "fake"},
}
ROLES = {"implementer": ["impl", "fb"], "judges": ["judge"], "clarifier": ["fake"]}


def config(**roles) -> L4Config:
    return L4Config.model_validate({"profiles": PROFILES, "roles": {**ROLES, **roles}})


def outcome(ctx):
    registry = Registry()
    registry.register(Check("ENV-004", "agent binaries", "error", env._env_004))
    (result,) = run_checks(ctx, registry=registry)
    return result, exit_code([result])


def test_env_004_head_missing_is_error_fallback_missing_is_warn(make_ctx):
    tools = {"claude": "2.1.288 (Claude Code)", "codex": "codex-cli 0.160.0"}
    ctx, _ = make_ctx(tools=tools, cfg=config())
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("pass", "error") and int(code) == 0

    ctx, _ = make_ctx(tools={"claude": "2.1.288"}, cfg=config())  # codex is the judge head and the fallback
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "error") and int(code) == 3
    assert "judges head `judge`" in result.message

    ctx, _ = make_ctx(tools={"claude": "2.1.288"}, cfg=config(judges=["judge"], implementer=["impl"]))
    result, code = outcome(ctx)  # a required chain whose only profile is unusable
    assert (result.status, result.severity) == ("fail", "error") and "no usable profile" in result.message

    ctx, _ = make_ctx(tools={"codex": "codex-cli 0.160.0"}, cfg=config())  # implementer head missing, `fb` usable
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "warn") and int(code) == 0
    assert "implementer head `impl`" in result.message and "usable fallback `fb`" in result.message

    fallback_only = config(implementer=["fb", "impl"], judges=["fb"])
    ctx, _ = make_ctx(tools={"codex": "codex-cli 0.160.0"}, cfg=fallback_only)  # only the fallback claude is missing
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "warn") and int(code) == 0
    assert "fallback `impl`" in result.message and "impl" in result.message


def test_env_004_checks_min_version_with_the_shared_comparison(make_ctx):
    tools = {"claude": "2.0.5 (Claude Code)", "codex": "codex-cli 0.160.0"}
    ctx, _ = make_ctx(tools=tools, cfg=config(implementer=["impl"]))
    result, _ = outcome(ctx)
    assert result.status == "fail" and result.severity == "error"
    assert "2.0.5" in result.message and "2.1.0" in result.message
    ctx, _ = make_ctx(tools={"claude": "no version here", "codex": "x"}, cfg=config())
    result, _ = outcome(ctx)
    assert result.status == "fail" and "version" in result.message


def test_env_004_skips_when_no_profile_has_a_cli(make_ctx):
    cfg = L4Config.model_validate({"profiles": {"f": {"adapter": "fake"}}, "roles": {"implementer": ["f"]}})
    ctx, _ = make_ctx(cfg=cfg)
    result, _ = outcome(ctx)
    assert result.status == "skip"


def test_env_004_is_registered():
    from l4.doctor.registry import REGISTRY

    assert "ENV-004" in {c.id for c in REGISTRY.checks()} and env.ENV_004.severity == "error"


def test_env_004_failing_chain_head_is_a_warning_when_a_later_profile_passes(make_ctx):
    profiles = {
        **PROFILES,
        "claude-judge": {"adapter": "claude-code", "min_version": "99.0.0"},
        "opencode-free": {"adapter": "codex"},
    }
    cfg = L4Config.model_validate(
        {"profiles": profiles, "roles": {"implementer": ["fb"], "judges": ["claude-judge", "opencode-free"]}}
    )
    ctx, _ = make_ctx(tools={"claude": "2.1.288 (Claude Code)", "codex": "codex-cli 0.160.0"}, cfg=cfg)
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "warn") and int(code) == 0
    assert "judges head `claude-judge`" in result.message and "99.0.0" in result.message
    assert "usable fallback `opencode-free`" in result.message


def test_env_004_head_is_an_error_when_no_profile_of_a_required_chain_passes(make_ctx):
    profiles = {**PROFILES, "claude-judge": {"adapter": "claude-code", "min_version": "99.0.0"}}
    cfg = L4Config.model_validate(
        {"profiles": profiles, "roles": {"implementer": ["fb"], "judges": ["claude-judge", "judge"]}}
    )
    ctx, _ = make_ctx(tools={"claude": "2.1.288 (Claude Code)", "codex": "codex-cli 0.160.0"}, cfg=cfg)
    assert outcome(ctx)[0].severity == "warn"  # `judge` (codex) passes: still a warning
    ctx, _ = make_ctx(tools={"claude": "2.1.288 (Claude Code)"}, cfg=cfg)  # codex gone: nothing usable
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "error") and int(code) == 3
    assert "no usable profile in the judges chain" in result.message


def test_env_004_an_optional_role_with_no_usable_profile_is_only_a_warning(make_ctx):
    cfg_only_clarifier = L4Config.model_validate(
        {"profiles": PROFILES, "roles": {"implementer": ["impl"], "judges": ["impl"], "clarifier": ["fb"]}}
    )
    ctx, _ = make_ctx(tools={"claude": "2.1.288 (Claude Code)"}, cfg=cfg_only_clarifier)
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "warn") and int(code) == 0
    assert "no usable profile in the clarifier chain" in result.message


V2_REASON = (
    "opencode 2.0.32 is OpenCode v2; this profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.34 "
    "(l4 doctor --fix installs it user-locally) or set options.cli_major: 2 to run OpenCode 2 (experimental)"
)


def opencode_config(*chain: str) -> L4Config:
    profiles = {
        "oc": {"adapter": "opencode", "model": "m", "vendor": "unknown"},  # no min_version
        "fb": {"adapter": "codex"},
    }
    return L4Config.model_validate({"profiles": profiles, "roles": {"implementer": list(chain), "judges": ["fb"]}})


def test_env_004_fails_a_v2_opencode_without_min_version(make_ctx):  # SCN-OCG-04, SCN-OCG-02
    tools = {"opencode": "opencode v2.0.32", "codex": "codex-cli 0.160.0"}
    ctx, _ = make_ctx(tools=tools, cfg=opencode_config("oc"))
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "error") and int(code) == 3
    assert V2_REASON in result.message and "`oc`" in result.message


def test_env_004_names_the_usable_fallback_for_a_v2_head(make_ctx):  # the existing chain rule
    tools = {"opencode": "opencode v2.0.32", "codex": "codex-cli 0.160.0"}
    ctx, _ = make_ctx(tools=tools, cfg=opencode_config("oc", "fb"))
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "warn") and int(code) == 0
    assert V2_REASON in result.message and "usable fallback `fb`" in result.message


def test_env_004_passes_a_v1_opencode_without_min_version(make_ctx):
    tools = {"opencode": "1.18.34", "codex": "codex-cli 0.160.0"}
    ctx, _ = make_ctx(tools=tools, cfg=opencode_config("oc"))
    result, _ = outcome(ctx)
    assert result.status == "pass"


@pytest.mark.parametrize("printed", ["ver2.0.1", "opencode_2.0.32"])
def test_env_004_fails_a_v2_behind_a_word_character(make_ctx, printed):
    tools = {"opencode": printed, "codex": "codex-cli 0.160.0"}
    ctx, _ = make_ctx(tools=tools, cfg=opencode_config("oc"))
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "error") and int(code) == 3
    assert "is OpenCode v2; this profile runs v1" in result.message


def test_env_004_passes_a_v1_behind_a_word_character(make_ctx):
    ctx, _ = make_ctx(tools={"opencode": "x1.2.3", "codex": "codex-cli 0.160.0"}, cfg=opencode_config("oc"))
    result, _ = outcome(ctx)
    assert result.status == "pass"


def test_env_004_fails_closed_when_a_gated_cli_reports_no_version(make_ctx):
    ctx, _ = make_ctx(
        tools={"opencode": "opencode (dev build)", "codex": "codex-cli 0.160.0"}, cfg=opencode_config("oc")
    )
    result, code = outcome(ctx)
    assert result.status == "fail" and "oc" in result.message and "reports no version" in result.message


def test_claude_version_reads_turn_the_updater_off(make_ctx):  # SCN-PRV-122, L4-PRV-044
    import dataclasses

    ctx, fake = make_ctx(tools={"claude": "2.1.288 (Claude Code)", "codex": "codex-cli 0.160.0"}, cfg=config(),
                         DISABLE_UPDATES="1")  # fmt: skip
    seen: list[tuple[str, dict | None]] = []

    def recording(argv, timeout=10.0, env=None):
        seen.append((argv[0], None if env is None else dict(env)))
        return fake.run(argv, timeout, env)

    ctx = dataclasses.replace(ctx, run=recording)
    assert env._cli_problem(ctx, "claude", "2.1.0", "claude-code") is None
    ((_, claude_env),) = [c for c in seen if c[0].endswith("claude")]
    assert claude_env is not None and claude_env["DISABLE_AUTOUPDATER"] == "1"
    assert "DISABLE_UPDATES" not in claude_env  # it would block `claude install`
    seen.clear()
    env._cli_problem(ctx, "codex", "0.1.0", "codex")
    assert all(e is None or "DISABLE_AUTOUPDATER" not in e for _, e in seen)


def v2_config() -> L4Config:
    profiles = {"oc2": {"adapter": "opencode", "model": "m", "vendor": "unknown", "options": {"cli_major": 2}}}
    return L4Config.model_validate({"profiles": profiles, "roles": {"implementer": ["oc2"], "judges": ["oc2"]}})


V2_PROFILE_REASON = (
    "opencode2 1.18.34 is OpenCode v1; this profile runs v2 (options.cli_major: 2, @opencode/cli 2.x): install "
    "@opencode/cli@2.0.32 (l4 doctor --fix installs it user-locally) or remove options.cli_major"
)


def test_env_004_runs_opencode2_for_a_v2_profile_and_gates_it_by_the_v2_key(make_ctx):  # amendment E2
    ctx, _ = make_ctx(tools={"opencode": "opencode v2.0.32", "opencode2": "1.18.34"}, cfg=v2_config())
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "error") and int(code) == 3
    assert V2_PROFILE_REASON in result.message and "`oc2`" in result.message

    ctx, _ = make_ctx(tools={"opencode2": "opencode v2.0.32"}, cfg=v2_config())
    assert outcome(ctx)[0].status == "pass"

    ctx, _ = make_ctx(tools={"opencode": "1.18.34"}, cfg=v2_config())  # a v1 binary named opencode is not opencode2
    result, _ = outcome(ctx)
    assert result.status == "fail" and "opencode2 not found" in result.message


def test_env_004_fails_closed_when_opencode2_reports_no_version(make_ctx):
    ctx, _ = make_ctx(tools={"opencode2": "opencode (dev build)"}, cfg=v2_config())
    result, _ = outcome(ctx)
    assert result.status == "fail" and "opencode2 reports no version" in result.message


def test_env_004_names_the_held_opencode2_pin_in_its_reason(make_ctx):  # L4-OCV-002: one source of pins
    held = L4Config.model_validate(
        {
            "profiles": {
                "oc2": {"adapter": "opencode", "model": "m", "vendor": "unknown", "options": {"cli_major": 2}}
            },
            "roles": {"implementer": ["oc2"], "judges": ["oc2"]},
            "ci": {"cli_versions": {"opencode2": "2.0.33"}},
        }
    )
    ctx, _ = make_ctx(tools={"opencode2": "1.18.34"}, cfg=held)
    result, _ = outcome(ctx)
    assert result.status == "fail" and "install @opencode/cli@2.0.33 (" in result.message


def test_env_004_checks_each_profiles_own_cli_when_both_majors_are_in_use(make_ctx):  # SCN-OCV-04
    both = L4Config.model_validate(
        {
            "profiles": {
                "oc1": {"adapter": "opencode", "model": "m", "vendor": "unknown"},
                "oc2": {"adapter": "opencode", "model": "m", "vendor": "unknown", "options": {"cli_major": 2}},
            },
            "roles": {"implementer": ["oc1"], "judges": ["oc2"]},
        }
    )
    ctx, _ = make_ctx(tools={"opencode": "1.18.34", "opencode2": "opencode v2.0.32"}, cfg=both)
    assert outcome(ctx)[0].status == "pass"
    ctx, _ = make_ctx(tools={"opencode": "opencode v2.0.32", "opencode2": "opencode v2.0.32"}, cfg=both)
    result, _ = outcome(ctx)
    assert result.status == "fail" and "`oc1`" in result.message and "`oc2`" not in result.message
