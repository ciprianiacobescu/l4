"""scripts/runner/sandbox-probe.sh (SANDBOX=m0) must build EXACTLY the argv BwrapSandbox builds for an agent, or the
runner proof says nothing about production. The bash functions between the markers are run here and diffed."""

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
from l4.sandbox.env import build_agent_env

SCRIPT = Path(__file__).parents[3] / "scripts" / "runner" / "sandbox-probe.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="needs bash")


def m0_functions() -> str:
    text = SCRIPT.read_text()
    match = re.search(r"^# --- m0-profile begin.*?^# --- m0-profile end ---$", text, re.S | re.M)
    assert match, "the m0-profile markers are missing from sandbox-probe.sh"
    return match.group(0)


def bash_argv(
    tmp_path: Path, home: Path, adapter: str, spec: SandboxSpec, env: dict[str, str], cmd: list[str],
    chdir: Path | None = None, host_root: Path | None = None,
):
    lib = tmp_path / "m0.sh"
    lib.write_text(m0_functions())
    pairs = [f"{k}={v}" for k, v in env.items()]
    caches = [f"{'rocache' if c.read_only else 'cache'}:{c.path}" for c in spec.caches]
    caches += [f"hide:{p}" for p in spec.runner_tmp]
    caches += [f"chdir:{chdir}"] if chdir else []
    done = subprocess.run(
        [BASH, "-c", 'source "$1"; shift; m0_argv "$@"', "_", str(lib), adapter, str(spec.worktree),
         str(spec.git_common_dir), str(spec.tmp_dir), *caches, *pairs, "--", *cmd],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", **({"L4_HOST_ROOT": str(host_root)} if host_root else {})},
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout.split("\n")[:-1]


def bash_env(tmp_path: Path, host: dict[str, str], tmp_dir: Path, extra: list[str]) -> list[str]:
    lib = tmp_path / "m0.sh"
    lib.write_text(m0_functions())
    done = subprocess.run(
        [BASH, "-c", 'source "$1"; shift; m0_env "$@"', "_", str(lib), str(tmp_dir), *extra],
        env=host, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout.split("\n")[:-1]


@pytest.fixture
def world(tmp_path: Path):
    home = tmp_path / "home dir"  # a space: tokens are lines, not words
    for sub in (".codex", ".claude", ".local/share/opencode", ".cache/opencode"):
        (home / sub).mkdir(parents=True)
    (home / ".claude.json").write_text("{}")  # a file; ~/.config/opencode, ~/.kiro, ~/.aws/sso/cache do not exist
    for sub in ("main/.git", "wt dir", "res"):
        (tmp_path / sub).mkdir(parents=True)
    # repo guidance in the worktree (HB-X1): present, absent (.hermes ...), a file, a symlink, and `.kiro/specs`
    for sub in (".claude/skills", ".agents/skills", ".codex", ".opencode", ".kiro/steering", ".kiro/specs/x"):
        (tmp_path / "wt dir" / sub).mkdir(parents=True)
    (tmp_path / "wt dir" / ".kiro" / "prompts").write_text("a file")
    (tmp_path / "wt dir" / ".kiro" / "hooks").symlink_to("/etc")
    creds = expand_credential_paths({k: list(v) for k, v in CREDENTIAL_PATHS.items()}, home)

    # the production default mounts (four read-write per-unit caches, the read-only shared one), a path with a space
    (tmp_path / "cache root" / "shared" / "ms-playwright").mkdir(parents=True, exist_ok=True)
    caches = mount_caches(L4Config().sandbox.caches, tmp_path / "cache root", "openspec:add-x", "proj-0123456789")
    assert len(caches) == 7 and any(c.read_only for c in caches)

    def spec(adapter: str) -> SandboxSpec:
        return SandboxSpec(
            kind="agent", worktree=tmp_path / "wt dir", git_common_dir=tmp_path / "main/.git",
            tmp_dir=tmp_path / "res", home=home, credential_paths=creds, adapter=adapter, caches=caches,
        )  # fmt: skip

    return home, spec


@pytest.mark.parametrize(("adapter", "extra"), [("codex", {}), ("claude-code", {"CLAUDE_CODE_MAX_RETRIES": "1"})])
def test_the_probe_builds_the_argv_the_sandbox_builds(tmp_path, world, adapter, extra):
    home, make_spec = world
    spec = make_spec(adapter)
    host = {"PATH": "/usr/local/bin:/usr/bin", "HOME": str(home), "USER": "runner", "LANG": "C.UTF-8"}
    env = build_agent_env(host, spec, extra={c.env: str(c.path) for c in spec.caches} | extra)
    cmd = ["tool", "--flag", "a b", "-"]
    assert any(c.env == "UV_CACHE_DIR" and str(c.path) in env.values() for c in spec.caches)
    expected = BwrapSandbox("bwrap").build_argv(cmd, spec, env)
    assert bash_argv(tmp_path, home, adapter, spec, env, cmd) == expected


# bash invents TERM=dumb when it starts without one, so every host sets it: that is also what the runner's sudo does
HOSTS = [
    {"USER": "runner", "LANG": "en_US.UTF-8", "TERM": "xterm"},
    {"LOGNAME": "ci", "TERM": "dumb", "TZ": "UTC", "HTTPS_PROXY": "http://proxy:3128", "no_proxy": "localhost"},
    {"TERM": "dumb"},  # no USER, LOGNAME or LANG: both sides fall back to l4 and C.UTF-8
]


@pytest.mark.parametrize("host", HOSTS)
@pytest.mark.parametrize(("adapter", "extra"), [("codex", {}), ("claude-code", {"CLAUDE_CODE_MAX_RETRIES": "1"})])
def test_the_probe_environment_is_the_one_build_agent_env_builds(tmp_path, world, host, adapter, extra):
    home, make_spec = world
    spec = make_spec(adapter)
    # a relative and an empty PATH entry: safe_path drops both, and so must the probe
    full = {**host, "HOME": str(home), "PATH": "/usr/bin::.:rel/bin:/usr/local/bin"}
    expected = build_agent_env(full, spec, extra=extra)
    got = bash_env(tmp_path, full, spec.tmp_dir, [f"{k}={v}" for k, v in extra.items()])
    assert got == [f"{k}={v}" for k, v in expected.items()]
    assert BwrapSandbox("bwrap").build_argv(["t"], spec, expected) == bash_argv(
        tmp_path, home, adapter, spec, dict(line.split("=", 1) for line in got), ["t"]
    )


@pytest.mark.parametrize("adapter", ["codex", "claude-code"])
def test_the_probe_hides_the_runner_tmp_dir_exactly_like_the_sandbox(tmp_path, world, adapter):
    home, make_spec = world
    runner_tmp = tmp_path / "builds dir" / "p.tmp"  # a space: tokens are lines, not words
    runner_tmp.mkdir(parents=True)
    spec = replace(make_spec(adapter), runner_tmp=(runner_tmp, tmp_path / "missing.tmp"))
    env = build_agent_env({"PATH": "/usr/bin", "HOME": str(home)}, spec)
    expected = BwrapSandbox("bwrap").build_argv(["t"], spec, env)
    at = expected.index(str(runner_tmp))
    assert expected[at - 1 : at + 1] == ["--tmpfs", str(runner_tmp)]
    assert str(tmp_path / "missing.tmp") not in expected
    assert bash_argv(tmp_path, home, adapter, spec, env, ["t"]) == expected


def test_the_argv_really_hides_the_other_logins_and_keeps_the_own(tmp_path, world):
    home, make_spec = world
    spec = make_spec("codex")
    env = build_agent_env({"PATH": "/usr/bin", "HOME": str(home)}, spec)
    argv = bash_argv(tmp_path, home, "codex", spec, env, ["true"])
    assert ["--bind", str(home / ".codex"), str(home / ".codex")] == argv[
        argv.index("--bind") : argv.index("--bind") + 3
    ]
    assert ["--tmpfs", str(home / ".claude")] == argv[
        argv.index(str(home / ".claude")) - 1 : argv.index(str(home / ".claude")) + 1
    ]
    assert ["--ro-bind", "/dev/null", str(home / ".claude.json")] in [argv[i : i + 3] for i in range(len(argv) - 2)]
    assert str(home / ".kiro") not in argv  # missing: nothing to hide


def test_bwrap_is_launched_with_path_only(world):
    """With --unshare-pid bwrap is PID 1, so /proc/1/environ is the environment bwrap itself was started with."""
    home, make_spec = world
    spec = make_spec("codex")
    env = build_agent_env({"PATH": "/usr/bin", "HOME": str(home), "L4_FORGE_TOKEN": "glpat-fake"}, spec)
    wrapped = BwrapSandbox("bwrap").wrap(["t"], spec, env)
    assert list(wrapped.env) == ["PATH"]


def test_opencode_m0_argv_matches(tmp_path, world):
    """G17: opencode's own state (`auth.json`, the models cache) is mounted for it, the per-step config dir lives in
    the private dir, and every other login is hidden, exactly as the runner proof builds it."""
    home, make_spec = world
    spec = make_spec("opencode")
    host = {"PATH": "/usr/local/bin:/usr/bin", "HOME": str(home), "USER": "runner", "LANG": "C.UTF-8", "TERM": "xterm"}
    xdg = spec.tmp_dir / "opencode-config"
    extra = {
        "XDG_CONFIG_HOME": str(xdg), "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_DISABLE_CLAUDE_CODE": "1",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_CONFIG_CONTENT": '{"snapshot":false,"share":"disabled"}',
    }  # fmt: skip
    env = build_agent_env(host, spec, extra=extra)
    cmd = ["opencode", "run", "--pure", "--format", "json", "-m", "opencode/big-pickle", "--dir", str(spec.worktree)]
    expected = BwrapSandbox("bwrap").build_argv(cmd, spec, env)
    got = bash_argv(tmp_path, home, "opencode", spec, env, cmd)
    assert got == expected
    cache = str(home / ".cache" / "opencode")
    at = expected.index(cache)
    assert expected[at - 1 : at + 2] == ["--bind", cache, cache]
    assert (["--tmpfs", str(home / ".codex")]) == expected[expected.index(str(home / ".codex")) - 1 :][:2]


def test_the_probe_launches_bwrap_with_that_same_environment():
    launches = [ln for ln in SCRIPT.read_text().splitlines() if '"${M0_ARGV[@]}"' in ln]
    assert len(launches) == 2
    assert all('env -i PATH="$PATH" "${M0_ARGV[@]}"' in ln for ln in launches)


def test_a_tool_less_call_chdir_matches(tmp_path, world):
    """The judge starts in an empty directory of the private dir; the probe's m0 profile must follow the same chdir."""
    home, make_spec = world
    spec = make_spec("claude-code")
    env = build_agent_env({"PATH": "/usr/bin", "HOME": str(home)}, spec)
    empty = spec.tmp_dir / "judge-cwd"
    expected = BwrapSandbox("bwrap").build_argv(["claude", "-p"], spec, env, empty)
    assert bash_argv(tmp_path, home, "claude-code", spec, env, ["claude", "-p"], chdir=empty) == expected
    assert expected[expected.index("--chdir") + 1] == str(empty)
    # no chdir option: the worktree, as before
    assert bash_argv(tmp_path, home, "claude-code", spec, env, ["claude", "-p"]) == BwrapSandbox("bwrap").build_argv(
        ["claude", "-p"], spec, env
    )


def fake_host(tmp_path: Path, name: str, *, var_run: str | None, resolv: str | None, run: bool = True) -> Path:
    root = tmp_path / name
    (root / "var").mkdir(parents=True)
    (root / "etc").mkdir()
    if run:
        (root / "run" / "systemd" / "resolve").mkdir(parents=True)
    if var_run == "dir":
        (root / "var" / "run").mkdir()
    elif var_run:
        (root / "var" / "run").symlink_to(var_run)
    if resolv:
        (root / "etc" / "resolv.conf").symlink_to(resolv)
    return root


@pytest.mark.parametrize(
    ("var_run", "resolv", "run"),
    [
        ("../run", "../run/systemd/resolve/stub-resolv.conf", True),  # Ubuntu
        ("dir", "../run/systemd/resolve/stub-resolv.conf", True),
        ("../srv/d", "/etc/../run/resolvconf/resolv.conf", True),  # `..` inside an absolute link
        ("../run", "/run/user/1000/resolv.conf", True),  # never put back
        ("../run", "/etc/real.conf", True),
        (None, None, False),  # no /run at all
    ],
)
@pytest.mark.parametrize("adapter", ["codex", "claude-code"])
def test_the_probe_masks_the_daemon_sockets_exactly_like_the_sandbox(tmp_path, world, adapter, var_run, resolv, run):
    """HB-1: /run is a tmpfs in the agent sandbox, and in the probe's copy of the argv."""
    home, make_spec = world
    spec = make_spec(adapter)
    root = fake_host(tmp_path, "host root", var_run=var_run, resolv=resolv, run=run)
    (root / "srv" / "d").mkdir(parents=True)
    env = build_agent_env({"PATH": "/usr/bin", "HOME": str(home)}, spec)
    expected = BwrapSandbox("bwrap", host_root=root).build_argv(["t"], spec, env)
    assert bash_argv(tmp_path, home, adapter, spec, env, ["t"], host_root=root) == expected
    assert ("/run" in expected) is run


def test_the_probe_masks_the_repo_guidance_directories_exactly_like_the_sandbox(tmp_path, world):
    """HB-X1: existing ones only (a file, a symlink and a missing one are skipped), `.kiro/specs` is never masked, and
    the masks come after every bind (the `.git` one is the last), just before `--clearenv`."""
    home, make_spec = world
    spec = make_spec("codex")
    env = build_agent_env({"PATH": "/usr/bin", "HOME": str(home)}, spec)
    expected = BwrapSandbox("bwrap").build_argv(["t"], spec, env)
    wt = spec.worktree
    masked = [expected[i + 1] for i, a in enumerate(expected) if a == "--tmpfs" and expected[i + 1].startswith(str(wt))]
    assert masked == [str(wt / d) for d in (".claude", ".agents", ".codex", ".opencode", ".kiro/steering")]
    at = expected.index(str(wt / ".claude"))
    last = expected.index(str(wt / ".kiro" / "steering"))
    assert expected[at - 4 : at - 1] == ["--ro-bind", str(spec.git_common_dir), str(spec.git_common_dir)]
    assert expected[last + 1] == "--clearenv"
    assert bash_argv(tmp_path, home, "codex", spec, env, ["t"]) == expected
