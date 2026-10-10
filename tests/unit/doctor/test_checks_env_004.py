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
