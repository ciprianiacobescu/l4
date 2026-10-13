"""The complete child environment of an agent or gate process (SPEC L4-SEC-001): built, never inherited."""

from collections.abc import Mapping

from l4.safepath import safe_path
from l4.sandbox.base import SandboxSpec

# Locale, terminal and proxy settings only; nothing here can carry a credential of the harness.
ALLOWED_PASSTHROUGH = (
    "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
)  # fmt: skip
RESULT_FILE = "result.json"


def _base(host_env: Mapping[str, str], spec: SandboxSpec) -> dict[str, str]:
    env = {
        "PATH": safe_path(host_env, forbid=(spec.worktree, spec.git_common_dir.parent)),
        "HOME": str(spec.home),
        "USER": host_env.get("USER") or host_env.get("LOGNAME") or "l4",
        "LANG": host_env.get("LANG") or "C.UTF-8",
        "TMPDIR": str(spec.tmp_dir),
        "PYTHONDONTWRITEBYTECODE": "1",  # no .pyc under the worktree: a stray __pycache__ is a protected-path violation
    }
    env.update({name: host_env[name] for name in ALLOWED_PASSTHROUGH if host_env.get(name) and name not in env})
    return env


def build_agent_env(
    host_env: Mapping[str, str], spec: SandboxSpec, *, extra: Mapping[str, str] | None = None
) -> dict[str, str]:
    """No credential variable at all: a value set with `--setenv` lands in bwrap's argv, where any local user can read
    it, and both M0 profiles log in from files (M1: bootstrap-core 1.14 `credential_env_names`, passed some other way).
    `extra` is for adapter-set variables such as `CLAUDE_CODE_MAX_RETRIES`."""
    env = _base(host_env, spec)
    env["L4_RESULT_PATH"] = str(spec.tmp_dir / RESULT_FILE)
    env.update(extra or {})
    return env


def build_gate_env(
    host_env: Mapping[str, str], spec: SandboxSpec, *, extra: Mapping[str, str] | None = None
) -> dict[str, str]:
    env = _base(host_env, spec)
    env.update({cache.env: str(cache.path) for cache in spec.caches})
    if any(cache.env == "UV_CACHE_DIR" for cache in spec.caches):
        env["UV_LINK_MODE"] = "copy"  # the cache and the worktree are separate binds: a hard link fails (EXDEV) anyway
    env.update(extra or {})
    return env
