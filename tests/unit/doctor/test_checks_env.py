from pathlib import Path

from l4.config.defaults import openspec_entrypoint
from l4.config.schema import L4Config
from l4.doctor import checks_env as env


def install_openspec(ctx) -> Path:
    js = openspec_entrypoint(ctx.env)
    js.parent.mkdir(parents=True, exist_ok=True)
    js.write_text("// fake", encoding="utf-8")
    return js


def with_openspec_dir(ctx) -> None:
    (ctx.repo / "openspec").mkdir(exist_ok=True)


def test_toolchain_present_passes(make_ctx):
    ctx, fake = make_ctx()
    with_openspec_dir(ctx)
    js = install_openspec(ctx)
    for check in (env.ENV_001, env.ENV_002, env.ENV_003):
        result = check.run(ctx)
        assert result.status == "pass", (check.id, result.message)
    # OpenSpec runs as [<absolute node>, <openspec.js>, ...]: the node the provider will use, no shim, no npx
    node_calls = [c for c in fake.calls if c[0] == "/fake/bin/node"]
    assert ("/fake/bin/node", "--version") in node_calls
    assert ("/fake/bin/node", str(js), "--version") in node_calls
    assert all("npx" not in part and ".bin" not in part for call in fake.calls for part in call)


def test_old_git_and_missing_openspec_fail(make_ctx):
    ctx, _ = make_ctx(tools={"git": "git version 2.33.1", "uv": "uv 0.10.0", "node": "v22.1.0"})
    with_openspec_dir(ctx)
    git = env.ENV_002.run(ctx)
    assert git.status == "fail" and "2.33" in git.message and "2.34" in git.message
    spec = env.ENV_003.run(ctx)
    assert spec.status == "fail"
    assert str(openspec_entrypoint(ctx.env)) in spec.message
    assert env.ENV_002.severity == env.ENV_003.severity == env.ENV_001.severity == "error"


def test_missing_uv_fails_env_001(make_ctx):
    ctx, _ = make_ctx(tools={"git": "git version 2.43.0"})
    result = env.ENV_001.run(ctx)
    assert result.status == "fail" and "uv" in result.message


def test_python_too_old_fails_env_001(make_ctx):
    ctx, _ = make_ctx()
    object.__setattr__(ctx, "python_version", (3, 10, 9))
    assert env.ENV_001.run(ctx).status == "fail"


def test_git_missing_or_unparsable_fails(make_ctx):
    ctx, _ = make_ctx(tools={"uv": "uv 1"})
    assert env.ENV_002.run(ctx).status == "fail"
    ctx, _ = make_ctx(tools={"git": "what is this"})
    result = env.ENV_002.run(ctx)
    assert result.status == "fail" and "parse" in result.message


def test_openspec_check_skipped_when_inactive(make_ctx):
    ctx, _ = make_ctx()  # frameworks auto, no openspec/ directory
    assert env.ENV_003.run(ctx).status == "skip"
    kiro, _ = make_ctx(cfg=L4Config.model_validate({"spec": {"frameworks": ["kiro"]}}))
    (kiro.repo / "openspec").mkdir()
    assert env.ENV_003.run(kiro).status == "skip"


def test_openspec_active_when_listed_even_without_directory(make_ctx):
    ctx, _ = make_ctx(cfg=L4Config.model_validate({"spec": {"frameworks": ["openspec"]}}))
    assert env.ENV_003.run(ctx).status == "fail"


def test_openspec_root_follows_config(make_ctx):
    ctx, _ = make_ctx(cfg=L4Config.model_validate({"spec": {"openspec": {"root": "specs"}}}))
    (ctx.repo / "openspec").mkdir(exist_ok=True)
    assert env.ENV_003.run(ctx).status == "skip"
    (ctx.repo / "specs").mkdir()
    assert env.ENV_003.run(ctx).status == "fail"  # now active, and not installed


def test_old_node_and_wrong_openspec_version_fail(make_ctx):
    ctx, _ = make_ctx(tools={"git": "git version 2.43.0", "uv": "u", "node": "v18.20.0", "openspec.js": "1.14.0"})
    with_openspec_dir(ctx)
    install_openspec(ctx)
    result = env.ENV_003.run(ctx)
    assert result.status == "fail" and "20.19" in result.message
    ctx, _ = make_ctx(tools={"git": "git version 2.43.0", "uv": "u", "node": "v22.1.0", "openspec.js": "1.13.0"})
    with_openspec_dir(ctx)
    install_openspec(ctx)
    result = env.ENV_003.run(ctx)
    assert result.status == "fail" and "1.13.0" in result.message and "1.14.0" in result.message


def test_missing_node_fails(make_ctx):
    ctx, _ = make_ctx(tools={"git": "git version 2.43.0", "uv": "u"})
    with_openspec_dir(ctx)
    result = env.ENV_003.run(ctx)
    assert result.status == "fail" and "node" in result.message


def test_node_version_boundary(make_ctx):
    for version, expected in (("v20.18.9", "fail"), ("v20.19.0", "pass"), ("v21.0.0", "pass")):
        ctx, _ = make_ctx(tools={"git": "g", "uv": "u", "node": version, "openspec.js": "1.14.0"})
        with_openspec_dir(ctx)
        install_openspec(ctx)
        assert env.ENV_003.run(ctx).status == expected, version


def test_openspec_version_probe_runs_in_the_harness_owned_environment(make_ctx):
    import dataclasses

    from l4.config.defaults import openspec_env

    ctx, fake = make_ctx(HOME="/h", PATH="/usr/bin", GIT_DIR="/leak", OPENAI_API_KEY="sk-leak")
    with_openspec_dir(ctx)
    js = install_openspec(ctx)
    envs: list = []

    def recording(argv, timeout=10.0, env=None):
        if str(js) in argv:
            envs.append(env)
        return fake.run(argv, timeout, env)

    result = env._env_003(dataclasses.replace(ctx, run=recording))
    assert result.status == "pass"
    assert envs == [openspec_env(ctx.env, forbid=(ctx.repo,))]
    assert "OPENAI_API_KEY" not in envs[0] and "GIT_DIR" not in envs[0]


# --- ENV-004 for Kiro (L4-OCG-005, SCN-OCG-12) ---

KIRO_3 = (
    "kiro-cli 3.0.0 is Kiro CLI 3; L4 runs Kiro CLI 2: install kiro-cli {pin} (in CI l4 doctor --ci --fix installs "
    "it; l4 doctor prints the command for this machine); Kiro CLI 3 support comes in a later L4 release"
)


def kiro_config(**ci) -> L4Config:
    return L4Config.model_validate(
        {
            "profiles": {"kiro": {"adapter": "kiro-cli", "model": "auto"}},  # no min_version
            "roles": {"implementer": ["kiro"], "judges": ["kiro"]},
            "ci": ci,
        }
    )


def env_004(ctx):
    from l4.doctor.registry import Check, Registry, run_checks

    registry = Registry()
    registry.register(Check("ENV-004", "agent binaries", "error", env._env_004))
    (result,) = run_checks(ctx, registry=registry)
    return result


def test_env_004_fails_a_kiro_cli_3_without_min_version(make_ctx):  # SCN-OCG-12
    ctx, _ = make_ctx(tools={"kiro-cli": "kiro-cli 3.0.0"}, cfg=kiro_config())
    result = env_004(ctx)
    assert (result.status, result.severity) == ("fail", "error")
    assert KIRO_3.format(pin="2.32.0") in result.message and "`kiro`" in result.message
    held, _ = make_ctx(tools={"kiro-cli": "kiro-cli 3.0.0"}, cfg=kiro_config(cli_versions={"kiro-cli": "2.28.0"}))
    assert KIRO_3.format(pin="2.28.0") in env_004(held).message  # the effective pin, not the catalog's
    ok, _ = make_ctx(tools={"kiro-cli": "kiro-cli 2.33.0"}, cfg=kiro_config())
    assert env_004(ok).status == "pass"  # a drift is ENV-015's, not ENV-004's


def test_env_004_fails_closed_on_a_kiro_cli_without_a_version(make_ctx):  # SCN-OCG-12
    ctx, _ = make_ctx(tools={"kiro-cli": "kiro-cli (dev build)"}, cfg=kiro_config())
    result = env_004(ctx)
    assert result.status == "fail" and "kiro-cli reports no version, so its Kiro CLI major cannot be checked" in (
        result.message
    )
    from tests.unit.doctor.test_checks_env_004 import opencode_config

    tools = {"opencode": "opencode (dev build)", "codex": "codex-cli 0.160.0"}
    oc, _ = make_ctx(tools=tools, cfg=opencode_config("oc"))
    assert "opencode reports no version, so its OpenCode major cannot be checked" in env_004(oc).message
