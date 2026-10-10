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
