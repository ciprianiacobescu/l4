"""The argv half of L4-SEC-030..033 and L4-PRV-041: no bwrap needed. The live half is in test_bwrap_live_home.py."""

from dataclasses import replace
from pathlib import Path

import pytest

from l4.exitcodes import ExitCode
from l4.sandbox import home as homemod
from l4.sandbox.base import SandboxUnavailable, gate_sandbox_spec
from l4.sandbox.bwrap import BwrapSandbox

from .mountsim import visible

EMPTY_ROOT = Path("/nonexistent-l4-host-root")
ENV = {"PATH": "/usr/bin", "HOME": "/h"}


def build(spec, argv=("true",)) -> list[str]:
    return BwrapSandbox("/usr/bin/bwrap", host_root=EMPTY_ROOT).build_argv(list(argv), spec, ENV)


def tmpfs_at(argv: list[str], path: Path) -> int:
    return next(i for i, a in enumerate(argv) if a == "--tmpfs" and argv[i + 1] == str(path))


def bind_at(argv: list[str], path: Path, flag: str = "--bind") -> int:
    return next(i for i, a in enumerate(argv) if a == flag and argv[i + 1] == str(path) and argv[i + 2] == str(path))


@pytest.mark.parametrize("kind", ["agent", "gate"])
def test_the_home_tmpfs_comes_before_every_bind(tmp_path, make_spec, kind):  # SCN-SEC-72
    home = tmp_path / "home"
    paths = {n: home / n for n in ("wt", "res", "git", "cache")}
    for p in paths.values():
        p.mkdir()
    spec = make_spec(
        kind, worktree=paths["wt"], tmp_dir=paths["res"], git_common_dir=paths["git"],
        caches=(make_spec.cache("uv"),),
    )  # fmt: skip
    cache = paths["cache"]
    spec = replace(spec, caches=(replace(spec.caches[0], path=cache),))
    argv = build(spec)
    home_at = tmpfs_at(argv, home)
    assert argv[1:11] == [
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--unshare-pid",
    ]  # the base flags come first, then the home's tmpfs
    assert home_at < bind_at(argv, paths["wt"]) and home_at < bind_at(argv, paths["res"])
    assert home_at < bind_at(argv, cache) and home_at < bind_at(argv, paths["git"], "--ro-bind")
    assert all(home_at < i for i, a in enumerate(argv) if a in {"--bind", "--ro-bind"} and argv[i + 1] != "/")


@pytest.mark.parametrize("kind", ["agent", "gate"])
def test_a_home_of_root_is_refused(tmp_path, make_spec, kind):  # SCN-SEC-73
    for bad in (Path("/"), Path("relative/home"), tmp_path / "missing"):
        with pytest.raises(SandboxUnavailable, match="HOME") as caught:
            build(make_spec(kind, home=bad, credential_paths={}))
        assert caught.value.code == ExitCode.DOCTOR_FAILED


def test_a_runner_cache_outside_the_home_is_covered(tmp_path, make_spec):  # SCN-SEC-74
    cache = tmp_path / "var-cache-l4"
    cache.mkdir()
    spec = make_spec("gate", cache_root=cache, caches=(make_spec.cache("uv"),))
    spec = replace(spec, caches=(replace(spec.caches[0], path=cache / "units" / "k" / "uv"),))
    (cache / "units" / "k" / "uv").mkdir(parents=True)
    argv = build(spec)
    assert tmpfs_at(argv, cache) == tmpfs_at(argv, spec.home) + 2
    for path in (spec.worktree, spec.tmp_dir, spec.caches[0].path):
        assert bind_at(argv, path) > tmpfs_at(argv, cache)
    inside = make_spec("gate", cache_root=spec.home / ".cache" / "l4")
    (spec.home / ".cache" / "l4").mkdir(parents=True)
    assert [a for a in build(inside) if a == "--tmpfs"].count("--tmpfs") == build(make_spec("gate")).count("--tmpfs")


def tree(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    home = tmp_path / "home"
    uvbin = home / ".local" / "bin"
    claude_real = home / ".local" / "share" / "claude" / "versions" / "2.1.288"
    l4 = home / ".local" / "share" / "l4"
    for d in (uvbin, claude_real.parent, l4 / "npm" / "node_modules" / ".bin", home / ".local/share/uv/python",
              home / ".local/share/uv/credentials", home / ".local/share/uv/tools"):  # fmt: skip
        d.mkdir(parents=True, exist_ok=True)
    (uvbin / "uv").write_text("#!/bin/sh\n")
    claude_real.write_text("#!/bin/sh\n")
    (uvbin / "claude").symlink_to(claude_real)
    env = {"HOME": str(home), "PATH": f"{uvbin}:{l4}/npm/node_modules/.bin:/usr/bin"}
    return home, env


def test_user_local_tools_are_bound_read_only(tmp_path, make_spec):  # SCN-SEC-76
    home, env = tree(tmp_path)
    paths = homemod.tool_paths(env, home=home, cache_root=tmp_path / "runner-cache", kind="agent", forbid=())
    l4 = home / ".local" / "share" / "l4"
    assert home / ".local" / "bin" in paths
    assert home / ".local" / "share" / "claude" / "versions" in paths
    assert l4 in paths and home / ".local/share/uv/python" in paths and home / ".local/share/uv/tools" in paths
    assert home / ".local/share/uv" not in paths and home / ".local/share/uv/credentials" not in paths
    assert len(set(paths)) == len(paths) and not any(
        a != b and a in b.parents for a in paths for b in paths
    )  # no path twice, none inside another
    from l4.gates import coverage, trace

    for plugin in (trace.plugin_dir(), coverage.plugin_dir()):
        under_home = home in plugin.parents
        assert (plugin in paths) is under_home  # only a plugin under a hidden root needs a bind (a uvx run)
    spec = make_spec("agent", "codex", home=home, tool_paths=paths)
    argv = build(spec)
    for path in paths:
        assert argv.count(str(path)) == 2 and bind_at(argv, path, "--ro-bind")
    first_mask = min(
        i for i, a in enumerate(argv) if a == "--tmpfs" and argv[i + 1] != str(home) and argv[i + 1] != "/tmp"
    )
    assert all(bind_at(argv, p, "--ro-bind") < first_mask for p in paths)
    assert (home / ".serena" in paths) is False  # absent here
    (home / ".serena").mkdir()
    assert home / ".serena" in homemod.tool_paths(env, home=home, cache_root=tmp_path / "rc", kind="agent", forbid=())
    assert home / ".serena" not in homemod.tool_paths(
        env, home=home, cache_root=tmp_path / "rc", kind="gate", forbid=()
    )


def test_the_worktree_is_never_a_tool_path(tmp_path):
    home, env = tree(tmp_path)
    wt = home / "work" / "wt"
    (wt / "node_modules" / ".bin").mkdir(parents=True)
    env["PATH"] += f":{wt}/node_modules/.bin"
    paths = homemod.tool_paths(env, home=home, cache_root=tmp_path / "rc", kind="gate", forbid=(wt,))
    assert not any(p == wt or wt in p.parents for p in paths)


def test_a_tool_bind_never_re_exposes_a_login(tmp_path, make_spec):  # SCN-SEC-77
    home, env = tree(tmp_path)
    login_bin = home / ".local" / "share" / "opencode" / "bin"
    login_bin.mkdir(parents=True)
    env["PATH"] = f"{login_bin}:{env['PATH']}"
    paths = homemod.tool_paths(env, home=home, cache_root=tmp_path / "rc", kind="agent", forbid=())
    assert login_bin in paths
    argv = build(make_spec("agent", "codex", home=home, tool_paths=paths))
    assert bind_at(argv, login_bin, "--ro-bind") < tmpfs_at(argv, home / ".local" / "share" / "opencode")
    assert not visible(argv, login_bin / "anything")


def test_setup_paths_reach_only_a_setup_gate(tmp_path, make_spec):  # SCN-SEC-79
    home = tmp_path / "home"
    npmrc = home / ".npmrc"
    npmrc.write_text("//registry/:_authToken=x")
    setup = homemod.setup_paths(home=home, cache_root=tmp_path / "rc", configured=["~/.npmrc", "~/.missing"])
    assert setup == (npmrc,)
    common = dict(
        worktree=tmp_path / "work" / "wt", git_common_dir=tmp_path / "main" / ".git", tmp_dir=tmp_path / "res",
        home=home, configured_credential_paths={}, caches=(), network=True, cache_root=tmp_path / "rc", tool_paths=(),
    )  # fmt: skip
    on = build(gate_sandbox_spec(**common, setup_paths=setup, builds_env=True))
    off = build(gate_sandbox_spec(**common, setup_paths=setup, builds_env=False))
    assert visible(on, npmrc) and bind_at(on, npmrc, "--ro-bind")
    assert not visible(off, npmrc)
    from l4.config.schema import SandboxCfg

    cfg = SandboxCfg(setup_paths=["~/.npmrc"])
    kwargs = dict(home=home, cache_root=tmp_path / "rc", sandbox_cfg=cfg, credential_paths={}, forbid=(), host_env={})
    assert homemod.spec_paths(**kwargs, kind="gate", builds_env=True)[1] == (npmrc,)
    assert homemod.spec_paths(**kwargs, kind="gate", builds_env=False)[1] == ()
    assert homemod.spec_paths(**kwargs, kind="agent", builds_env=True)[1] == ()


def test_configured_paths_are_checked_where_the_environment_is_known(tmp_path):  # SCN-SEC-80, runtime half
    home = tmp_path / "home"
    cache = tmp_path / "runner-cache"
    cache.mkdir()
    for bad in ([str(tmp_path)], [str(cache)], ["/"], ["~"], ["~/.codex/bin"], ["~/.local/share"]):
        from l4.exitcodes import L4Exit

        with pytest.raises(L4Exit) as caught:
            homemod.tool_paths({"PATH": "/usr/bin"}, home=home, cache_root=cache, kind="gate", configured=bad)
        assert caught.value.code == ExitCode.USAGE_ERROR and "tool_paths" in str(caught.value)
        assert not any(b in str(caught.value) for b in bad if len(b) > 3)
    with pytest.raises(L4Exit, match="setup_paths"):
        homemod.setup_paths(home=home, cache_root=cache, configured=[str(cache)])
    ok = home / ".local" / "opt"
    ok.mkdir(parents=True)
    got = homemod.tool_paths(
        {"PATH": "/usr/bin"}, home=home, cache_root=cache, kind="gate", configured=["~/.local/opt"]
    )
    assert ok in got


def test_a_workbenchs_specs_carry_setup_paths_only_for_a_setup_gate(tmp_path):  # SCN-SEC-79, the wiring
    from l4.config.schema import L4Config, SandboxCfg

    from .bwrap_live import make_world

    cfg = L4Config(sandbox=SandboxCfg(setup_paths=["~/.npmrc"], tool_paths=["~/.local/opt"]))
    world = make_world(tmp_path, cfg=cfg)
    home = world.home
    (home / ".npmrc").write_text("//registry/:_authToken=x")
    (home / ".local" / "opt").mkdir(parents=True)
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    setup, test, agent = wb.gate_spec(network=True, builds_env=True), wb.gate_spec(network=True), wb.agent_spec()
    assert setup.setup_paths == (home / ".npmrc",) and test.setup_paths == () and agent.setup_paths == ()
    for spec in (setup, test, agent):
        assert home / ".local" / "opt" in spec.tool_paths  # sandbox.tool_paths reaches both kinds
        assert spec.cache_root == wb.cache_root and spec.home == home


def test_the_hello_key_directory_is_hidden(tmp_path, make_spec, monkeypatch):  # SCN-PRV-103
    import json
    import re
    import stat

    from l4.agents.base import ProbeCtx
    from l4.agents.opencode import OpenCodeAdapter
    from l4.config.schema import Profile
    from l4.doctor.context import CmdResult

    monkeypatch.setattr("l4.agents.opencode.reachable", lambda url: (True, ""))
    cache = tmp_path / "runner-cache"
    cache.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "opencode").write_text("#!/bin/sh\n")
    (bin_dir / "opencode").chmod(0o755)
    profile = Profile(
        adapter="opencode", model="magnitude/m", auth="api_key", vendor="x",
        options={
            "provider": {"id": "magnitude", "base_url": "http://192.0.2.10:1/v1", "api_key_env": "MK",
                         "models": {"m": {"context": 1000, "output": 100}}},
            "tools": ["read"],
        },
    )  # fmt: skip
    seen: dict[str, object] = {}

    def fake_run(argv, cwd, env, timeout):
        if "OPENCODE_CONFIG_CONTENT" in env:
            ref = json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"]["magnitude"]["options"]["apiKey"]
            key_file = Path(re.fullmatch(r"\{file:(.+)\}", ref).group(1))
            seen["file"], seen["dir_mode"] = key_file, stat.S_IMODE(key_file.parent.stat().st_mode)
            seen["scratch_mode"] = stat.S_IMODE(key_file.parent.parent.stat().st_mode)
            seen["file_mode"] = stat.S_IMODE(key_file.stat().st_mode)
            return CmdResult(0, "", "")
        return CmdResult(0, "1.18.34\n", "")

    ctx = ProbeCtx({"PATH": str(bin_dir), "HOME": str(tmp_path / "home"), "MK": "sk-secret"}, cache, fake_run)
    OpenCodeAdapter().probe(profile, "hello", ctx)
    key_file = seen["file"]
    assert isinstance(key_file, Path) and cache in key_file.parents
    assert seen["dir_mode"] == seen["scratch_mode"] == 0o700 and seen["file_mode"] == 0o600
    spec = make_spec("gate", cache_root=cache)
    argv = build(replace(spec, caches=()))
    assert tmpfs_at(argv, cache) > tmpfs_at(argv, spec.home)
    assert not visible(argv, key_file)
    bound = [Path(argv[i + 1]) for i, a in enumerate(argv) if a in {"--bind", "--ro-bind"} and argv[i + 1] != "/"]
    assert not any(b == key_file.parent or b in key_file.parents for b in bound)
