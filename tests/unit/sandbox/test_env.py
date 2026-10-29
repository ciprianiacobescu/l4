from pathlib import Path

from l4.sandbox.base import CacheMount
from l4.sandbox.env import build_agent_env, build_gate_env

HOST = {
    "PATH": "/usr/bin:/home/runner/.local/bin",
    "HOME": "/home/runner",
    "USER": "runner",
    "LANG": "en_US.UTF-8",
    "HTTPS_PROXY": "http://proxy:3128",
    "L4_FORGE_TOKEN": "forge-secret-value-1234",
    "L4_TRIGGER_TOKEN": "trigger-secret-1234",
    "ANTHROPIC_API_KEY": "sk-ant-aaaaaaaaaaaaaaaaaaaa",
    "OPENAI_API_KEY": "sk-bbbbbbbbbbbbbbbbbbbbbbbb",
    "CODEX_API_KEY": "codex-key-123456",
    "CLAUDE_CODE_OAUTH_TOKEN": "oauth-token-123456",
    "CLAUDE_CODE_RETRY_WATCHDOG": "1",
    "CLAUDECODE": "1",
    "GITHUB_OUTPUT": "/tmp/out",
    "CI_JOB_TOKEN": "job-token-123456",
}


def test_agent_env_has_no_forge_token_and_gate_env_has_no_credentials(make_spec):
    agent = build_agent_env(HOST, make_spec("agent", "codex"))
    gate = build_gate_env(HOST, make_spec("gate"))
    for env in (agent, gate):
        assert not [k for k in env if k.endswith(("_TOKEN", "_KEY")) or k.startswith(("CI_", "CLAUDE", "GITHUB"))]
        assert "forge-secret-value-1234" not in env.values()
    # M0: both profiles authenticate from files, so not even the agent's own credential variable is passed (it
    # would have to travel in bwrap's argv) -- M1: bootstrap-core 1.14 credential_env_names
    wanted = {"PATH", "HOME", "USER", "LANG", "TMPDIR", "L4_RESULT_PATH", "HTTPS_PROXY", "PYTHONDONTWRITEBYTECODE"}
    assert set(agent) == wanted


def test_agent_env_paths_point_at_the_private_dir(make_spec):
    spec = make_spec("agent", "codex")
    env = build_agent_env(HOST, spec)
    assert env["TMPDIR"] == str(spec.tmp_dir)
    assert env["L4_RESULT_PATH"] == str(spec.tmp_dir / "result.json")
    assert env["HOME"] == str(spec.home)


def test_extra_adapter_variables_are_part_of_the_allow_list(make_spec):
    env = build_agent_env(HOST, make_spec("agent", "claude-code"), extra={"CLAUDE_CODE_MAX_RETRIES": "1"})
    assert env["CLAUDE_CODE_MAX_RETRIES"] == "1" and "CLAUDE_CODE_RETRY_WATCHDOG" not in env


def test_path_drops_entries_inside_the_worktree_and_relative_ones(make_spec):
    spec = make_spec("agent", "codex")
    host = {**HOST, "PATH": f"/usr/bin::.:node_modules/.bin:{spec.worktree}/bin:/opt/tools"}
    assert build_agent_env(host, spec)["PATH"] == "/usr/bin:/opt/tools"


def test_gate_env_carries_cache_variables_and_no_result_path(make_spec):
    cache = make_spec.cache("uv")
    env = build_gate_env(HOST, make_spec("gate", caches=(cache,)))
    assert env["UV_CACHE"] == str(cache.path) and "L4_RESULT_PATH" not in env


def test_defaults_when_the_host_has_no_locale_or_user(make_spec):
    env = build_gate_env({"PATH": "/usr/bin"}, make_spec("gate"))
    assert env["LANG"] == "C.UTF-8" and env["USER"] == "l4" and isinstance(Path(env["HOME"]), Path)


def test_uv_link_mode_is_copy_when_a_uv_cache_is_mounted(make_spec):
    """W10: the cache and the worktree are separate binds, so a hard link fails and uv copies; it is told to."""
    with_uv = make_spec("gate", caches=(CacheMount(Path("/c/uv"), "UV_CACHE_DIR"),))
    assert build_gate_env(HOST, with_uv)["UV_LINK_MODE"] == "copy"
    other = make_spec("gate", caches=(make_spec.cache("pip"),))  # type: ignore[attr-defined]
    assert "UV_LINK_MODE" not in build_gate_env(HOST, other) and "UV_LINK_MODE" not in build_gate_env(
        HOST, make_spec("gate")
    )


def test_python_never_writes_bytecode_in_either_environment(make_spec):
    """SCN-VER-60 (L4-SEC-001): a stray `__pycache__` under the worktree would be a protected-path violation."""
    assert build_agent_env(HOST, make_spec("agent", "codex"))["PYTHONDONTWRITEBYTECODE"] == "1"
    assert build_gate_env(HOST, make_spec("gate"))["PYTHONDONTWRITEBYTECODE"] == "1"


def _cfg(**toolchains):
    from l4.config.schema import L4Config

    return L4Config.model_validate({"ci": {"toolchains": toolchains}})


def test_scn_ci_22_go_gates_run_with_the_local_toolchain_and_a_read_only_module_graph(make_spec):
    """SCN-CI-22 (+): GOTOOLCHAIN=local and GOFLAGS=-mod=readonly next to the per-unit GOMODCACHE and GOCACHE."""
    from l4.sandbox.env import toolchain_env

    caches = (CacheMount(Path("/c/go"), "GOMODCACHE"), CacheMount(Path("/c/gobuild"), "GOCACHE"))
    env = build_gate_env(HOST, make_spec("gate", caches=caches), extra=toolchain_env(_cfg(go={"version": "1.26"})))
    assert env["GOTOOLCHAIN"] == "local" and env["GOFLAGS"] == "-mod=readonly"
    assert env["GOMODCACHE"] == "/c/go" and env["GOCACHE"] == "/c/gobuild"


def test_scn_ci_22_without_ci_toolchains_go_the_gate_environment_has_no_go_settings(make_spec):
    from l4.sandbox.env import toolchain_env

    assert toolchain_env(_cfg()) == {} and toolchain_env(_cfg(node={"version": "22"})) == {}
    env = build_gate_env(HOST, make_spec("gate"), extra=toolchain_env(_cfg()))
    assert "GOTOOLCHAIN" not in env and "GOFLAGS" not in env


def test_scn_ci_22_a_gate_environment_that_sets_them_wins():
    from l4.gates.coverage import merge_pytest_env
    from l4.sandbox.env import toolchain_env

    merged = merge_pytest_env(toolchain_env(_cfg(go={"version": "1.26"})), {"GOFLAGS": "-mod=vendor"})
    assert merged == {"GOTOOLCHAIN": "local", "GOFLAGS": "-mod=vendor"}


def test_the_pnpm_store_is_visible_to_pnpm_9_to_11(make_spec):
    """pnpm 11 reads pnpm_config_store_dir and ignores npm_config_*; pnpm 9 and 10 read only npm_config_store_dir."""
    spec = make_spec("gate", caches=(CacheMount(Path("/c/pnpm"), "pnpm_config_store_dir"),))
    env = build_gate_env(HOST, spec)
    assert env["pnpm_config_store_dir"] == env["npm_config_store_dir"] == "/c/pnpm"


# --- the CI's identity variables in the gate environment (ci-evidence D7; L4-SEC-040) ---

JOB = {
    **HOST, "CI": "true", "GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": "/tmp/s", "GITHUB_TOKEN": "ghs_x",
    "RUNNER_TEMP": "/tmp/r", "FORCE_COLOR": "1",
}  # fmt: skip


def test_in_ci_the_gate_gets_the_ci_flags_and_the_agent_does_not(make_spec):
    """SCN-SEC-100: the two flags, none of the path or token variables, no colour variable; the agent gets neither."""
    gate = build_gate_env(JOB, make_spec("gate"))
    agent = build_agent_env(JOB, make_spec("agent", "codex"))
    assert gate["CI"] == "true" and gate["GITHUB_ACTIONS"] == "true"
    for name in ("GITHUB_OUTPUT", "GITHUB_STEP_SUMMARY", "GITHUB_TOKEN", "RUNNER_TEMP", "CI_JOB_TOKEN", "FORCE_COLOR"):
        assert name not in gate
    assert "CI" not in agent and "GITHUB_ACTIONS" not in agent
    assert build_gate_env(HOST, make_spec("gate")) == build_gate_env({**HOST, "FORCE_COLOR": "1"}, make_spec("gate"))


def test_gitlab_ci_and_no_colour_variable_is_passed(make_spec):
    colours = {
        "FORCE_COLOR": "1", "NO_COLOR": "1", "PY_COLORS": "1", "CLICOLOR": "0", "CLICOLOR_FORCE": "1",
        "TTY_COMPATIBLE": "1",
    }  # fmt: skip
    for host in ({**HOST, "GITLAB_CI": "true", **colours}, {**HOST, "CI": "true", **colours}):
        gate = build_gate_env(host, make_spec("gate"))
        assert not set(colours) & set(gate)
    assert build_gate_env({**HOST, "GITLAB_CI": "true"}, make_spec("gate"))["GITLAB_CI"] == "true"


def test_a_value_that_is_not_a_short_word_is_refused(make_spec):
    """SCN-SEC-102: `fullmatch`, so a trailing newline, a dot or a slash is refused; an empty value is no value."""
    from l4.sandbox.env import gate_ci_env, refused_ci_env

    bad = {"GITLAB_CI": "x" * 40, "GITHUB_ACTIONS": "/tmp/x"}
    host = {**HOST, "CI": "true", **bad}
    assert gate_ci_env(host) == {"CI": "true"} and refused_ci_env(host) == ("GITHUB_ACTIONS", "GITLAB_CI")
    for value in ("true\n", "1.0", "a b", "x" * 17):
        assert refused_ci_env({"CI": "true", "GITLAB_CI": value}) == ("GITLAB_CI",), repr(value)
    assert (
        gate_ci_env({"CI": "true", "GITLAB_CI": ""}) == {"CI": "true"}
        and refused_ci_env({"CI": "true", "GITLAB_CI": ""}) == ()
    )
    env = build_gate_env(host, make_spec("gate"))
    assert "GITLAB_CI" not in env and "GITHUB_ACTIONS" not in env and env["CI"] == "true"


def test_outside_ci_nothing_changes_and_ci_true_opts_in(make_spec):
    """SCN-SEC-103: a person's `CLICOLOR` and `FORCE_COLOR` never reach a gate; `CI=true` gives `CI` only."""
    from l4.sandbox.env import gate_ci_env, refused_ci_env

    shell = {**HOST, "CLICOLOR": "1", "FORCE_COLOR": "1"}
    assert build_gate_env(shell, make_spec("gate")) == build_gate_env(HOST, make_spec("gate"))
    assert gate_ci_env(shell) == {} and refused_ci_env({**shell, "GITLAB_CI": "x" * 40}) == ()
    opted = build_gate_env({**shell, "CI": "true"}, make_spec("gate"))
    assert opted["CI"] == "true" and "CLICOLOR" not in opted and "FORCE_COLOR" not in opted
    from l4.ci.detect import ci_like, in_ci_job

    assert ci_like({"CI": "true"}) and not in_ci_job({"CI": "true"})  # an opt-in (L4-CLI-004), not a job


def test_a_gates_own_setting_wins(make_spec):
    env = build_gate_env({**HOST, "CI": "true", "GITHUB_ACTIONS": "true"}, make_spec("gate"), extra={"CI": "0"})
    assert env["CI"] == "0" and env["GITHUB_ACTIONS"] == "true"
