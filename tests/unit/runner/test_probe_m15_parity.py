"""M15-G2: the sandbox argv that `scripts/runner/ci-probe-m15.sh` measures Chromium, Serena and Laya in must be the
one BwrapSandbox builds, for the gate kind (no adapter, no network) and for the agent kind. The bash functions between
the markers are run here and diffed, as tests/unit/sandbox/test_probe_parity.py does for sandbox-probe.sh."""

import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from l4.config.defaults import CREDENTIAL_PATHS
from l4.config.schema import L4Config
from l4.sandbox.base import SandboxSpec, expand_credential_paths
from l4.sandbox.bwrap import BwrapSandbox
from l4.sandbox.caches import mount_caches
from l4.sandbox.env import build_agent_env, build_gate_env
from l4.sandbox.envdirs import read_only_mounts

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "runner" / "ci-probe-m15.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def functions() -> str:
    match = re.search(r"^# --- m0-profile begin.*?^# --- m0-profile end ---$", SCRIPT.read_text(), re.S | re.M)
    assert match, "the m0-profile markers are missing from ci-probe-m15.sh"
    return match.group(0)


def run_bash(tmp_path: Path, home: Path, env: dict[str, str], call: str, *args: str) -> list[str]:
    lib = tmp_path / "lib.sh"
    lib.write_text(functions())
    done = subprocess.run(
        [BASH, "-c", f'source "$1"; shift; {call} "$@"', "_", str(lib), *args],
        env={"HOME": str(home), "TERM": "dumb", **env}, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout.split("\n")[:-1]


@pytest.fixture
def world(tmp_path: Path):
    home = tmp_path / "home dir"
    for sub in (".codex", ".claude", ".local/share/opencode"):
        (home / sub).mkdir(parents=True)
    (home / ".claude.json").write_text("{}")
    for sub in ("main/.git", "wt dir", "res"):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "builds" / "p.tmp").mkdir(parents=True)
    # the environment of a gate that builds nothing (L4-SEC-035)
    for sub in (".venv/lib", "node_modules/.vite/deps", "node_modules/.vite-temp"):
        (tmp_path / "wt dir" / sub).mkdir(parents=True)
    read_only, empty = read_only_mounts(tmp_path / "wt dir", ())
    creds = expand_credential_paths({k: list(v) for k, v in CREDENTIAL_PATHS.items()}, home)
    (tmp_path / "cache root" / "shared" / "ms-playwright").mkdir(parents=True)
    tools = (home / ".local" / "bin dir", home / ".local" / "share" / "l4")  # L4-SEC-032, one with a space
    for tool in tools:
        tool.mkdir(parents=True)
    caches = mount_caches(L4Config().sandbox.caches, tmp_path / "cache root", "openspec:add-x", "proj-0123456789")

    def spec(adapter: str | None) -> SandboxSpec:
        return SandboxSpec(
            kind="agent" if adapter else "gate", worktree=tmp_path / "wt dir", git_common_dir=tmp_path / "main/.git",
            tmp_dir=tmp_path / "res", home=home, credential_paths=creds, adapter=adapter, caches=caches,
            network=bool(adapter), runner_tmp=(tmp_path / "builds" / "p.tmp", tmp_path / "missing.tmp"),
            cache_root=tmp_path / "cache root", tool_paths=tools,
            read_only=() if adapter else read_only, empty_dirs=() if adapter else empty,
        )  # fmt: skip

    return home, spec


def bash_argv(tmp_path: Path, home: Path, spec: SandboxSpec, env: dict[str, str], cmd: list[str]) -> list[str]:
    caches = [f"{'rocache' if c.read_only else 'cache'}:{c.path}" for c in spec.caches]
    caches += [f"hide:{p}" for p in spec.runner_tmp]
    caches += [f"root:{spec.cache_root}", *(f"tool:{p}" for p in spec.tool_paths)]
    caches += [f"ro:{p}" for p in spec.read_only] + [f"empty:{p}" for p in spec.empty_dirs]
    net = {"M0_NET": "share" if spec.network else "unshare"}
    return run_bash(
        tmp_path, home, {"PATH": "/usr/bin:/bin", **net}, "m0_argv",
        spec.adapter or "", str(spec.worktree), str(spec.git_common_dir), str(spec.tmp_dir), *caches,
        *[f"{k}={v}" for k, v in env.items()], "--", *cmd,
    )  # fmt: skip


def test_the_gate_argv_is_the_one_the_gate_sandbox_builds(tmp_path, world):
    home, make_spec = world
    spec = make_spec(None)
    host = {"PATH": "/usr/local/bin:/usr/bin", "HOME": str(home), "USER": "runner", "LANG": "C.UTF-8"}
    env = build_gate_env(host, spec)
    cmd = ["./launch.sh"]
    expected = BwrapSandbox("bwrap").build_argv(cmd, spec, env)
    assert "--unshare-net" in expected and "--share-net" not in expected
    wt = spec.worktree
    assert ["--ro-bind", str(wt / ".venv"), str(wt / ".venv")] == expected[
        expected.index(str(wt / ".venv")) - 1 : expected.index(str(wt / ".venv")) + 2
    ]
    assert ["--tmpfs", str(wt / "node_modules" / ".vite")] == expected[
        expected.index(str(wt / "node_modules" / ".vite")) - 1 : expected.index(str(wt / "node_modules" / ".vite")) + 1
    ]
    modules, temp = wt / "node_modules", wt / "node_modules" / ".vite-temp"  # Vite's config temp folder (L4-SEC-035)
    tmpfs_at = next(i for i, a in enumerate(expected) if a == "--tmpfs" and expected[i + 1] == str(temp))
    bind_at = next(i for i, a in enumerate(expected) if a == "--ro-bind" and expected[i + 1] == str(modules))
    assert tmpfs_at > bind_at
    assert bash_argv(tmp_path, home, spec, env, cmd) == expected


def test_the_gate_environment_is_build_gate_env(tmp_path, world):
    home, make_spec = world
    spec = make_spec(None)
    host = {"USER": "runner", "LANG": "en_US.UTF-8", "TERM": "xterm", "HOME": str(home), "PATH": "/usr/bin::.:rel/bin"}
    expected = [f"{k}={v}" for k, v in build_gate_env(host, spec).items()]
    caches = [f"{c.env}={c.path}" for c in spec.caches]
    got = run_bash(tmp_path, home, host, "m0_gate_env", str(spec.tmp_dir), *caches)
    assert got == expected


@pytest.mark.parametrize(
    "ci",
    [
        {"CI": "true", "GITHUB_ACTIONS": "true", "GITLAB_CI": "/tmp/x", "FORCE_COLOR": "1"},
        {"CI": "true", "GITHUB_ACTIONS": "true\n", "NO_COLOR": "1"},
        {"GITLAB_CI": "true", "CI": "x" * 17},
        {"CI": "true", "GITHUB_ACTIONS": "1.0", "GITLAB_CI": "yes-it_is"},
        {"CLICOLOR": "1", "FORCE_COLOR": "1", "GITHUB_ACTIONS": "1"},
    ],
)
def test_the_gate_environment_with_a_ci_host_is_build_gate_env(tmp_path, world, ci):
    """L4-SEC-040: the shell twin passes the same CI variables, in the same place, and refuses the same values."""
    home, make_spec = world
    spec = make_spec(None)
    host = {"USER": "runner", "LANG": "en_US.UTF-8", "TERM": "xterm", "HOME": str(home), "PATH": "/usr/bin", **ci}
    expected = [f"{k}={v}" for k, v in build_gate_env(host, spec).items()]
    caches = [f"{c.env}={c.path}" for c in spec.caches]
    assert run_bash(tmp_path, home, host, "m0_gate_env", str(spec.tmp_dir), *caches) == expected


@pytest.mark.parametrize("adapter", ["codex", "claude-code"])
def test_the_agent_argv_is_the_one_the_agent_sandbox_builds(tmp_path, world, adapter):
    home, make_spec = world
    spec = make_spec(adapter)
    host = {"PATH": "/usr/local/bin:/usr/bin", "HOME": str(home), "USER": "runner", "LANG": "C.UTF-8"}
    env = build_agent_env(host, spec, extra={c.env: str(c.path) for c in spec.caches} | {"CI": "true"})
    cmd = ["serena", "start-mcp-server", "--project", "a b"]
    assert bash_argv(tmp_path, home, spec, env, cmd) == BwrapSandbox("bwrap").build_argv(cmd, spec, env)


def test_without_an_adapter_every_login_is_hidden(tmp_path, world):
    home, make_spec = world
    spec = replace(make_spec(None), runner_tmp=())
    argv = bash_argv(tmp_path, home, spec, {}, ["true"])
    for hidden in (".codex", ".claude", ".local/share/opencode"):
        at = argv.index(str(home / hidden))
        assert argv[at - 1] == "--tmpfs"
    assert "--bind" not in argv[: argv.index(str(spec.worktree)) - 1]  # no login of any adapter is mounted


@pytest.mark.parametrize("net", [True, False])
def test_the_daemon_socket_masks_match_on_a_host_with_run(tmp_path, world, net):
    """HB-1: /run is a tmpfs for both kinds; only the resolver file comes back."""
    home, make_spec = world
    spec = make_spec("codex" if net else None)
    root = tmp_path / "host root"
    (root / "run" / "systemd" / "resolve").mkdir(parents=True)
    (root / "var").mkdir()
    (root / "etc").mkdir()
    (root / "var" / "run").symlink_to("../run")
    (root / "etc" / "resolv.conf").symlink_to("../run/systemd/resolve/stub-resolv.conf")
    host = {"PATH": "/usr/bin", "HOME": str(home)}
    env = build_agent_env(host, spec) if net else build_gate_env(host, spec)
    expected = BwrapSandbox("bwrap", host_root=root).build_argv(["t"], spec, env)
    assert "/run" in expected and "--ro-bind-try" in expected
    caches = [f"{'rocache' if c.read_only else 'cache'}:{c.path}" for c in spec.caches]
    caches += [f"hide:{p}" for p in spec.runner_tmp]
    caches += [f"root:{spec.cache_root}", *(f"tool:{p}" for p in spec.tool_paths)]
    caches += [f"ro:{p}" for p in spec.read_only] + [f"empty:{p}" for p in spec.empty_dirs]
    got = run_bash(
        tmp_path, home, {"PATH": "/usr/bin:/bin", "M0_NET": "share" if net else "unshare", "L4_HOST_ROOT": str(root)},
        "m0_argv", spec.adapter or "", str(spec.worktree), str(spec.git_common_dir), str(spec.tmp_dir), *caches,
        *[f"{k}={v}" for k, v in env.items()], "--", "t",
    )  # fmt: skip
    assert got == expected
