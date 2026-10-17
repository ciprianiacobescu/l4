"""sandbox-security-6 (owner decision Q3): the login lock files and the unit lock files are not readable inside the gate
and the agent sandboxes. SCN-SEC-99. The paths come from the harness's own code (`lock_root`, `UnitNames`), never a
literal; the argv half uses the mount model of `mountsim`, the live half (test_bwrap_live_home.py) a real bwrap."""

import pwd
from types import SimpleNamespace

import pytest

from l4.agents.gate import ConcurrencyGate, lock_root
from l4.config.defaults import CREDENTIAL_PATHS
from l4.sandbox.base import expand_credential_paths
from l4.sandbox.bwrap import BwrapSandbox
from l4.sandbox.env import build_agent_env, build_gate_env
from l4.vcs.names import UnitNames
from l4.vcs.repokey import key_of_common_dir

from .bwrap_live import make_world
from .mountsim import visible


def lock_paths(world, wb, monkeypatch):
    """(login lock file, unit lock file) as the harness derives them for this world's runner user."""
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(world.home)))
    monkeypatch.delenv("L4_LOCK_DIR", raising=False)
    gate = ConcurrencyGate(locks_dir=lock_root(world.host_env))
    login = gate._path("codex", "deadbeefdeadbeef", 0)
    key = key_of_common_dir(wb.git_common_dir, world.host_env)
    unit = UnitNames.for_unit("openspec:add-search", branch_prefix="l4/", cache=wb.cache_root, repo_key=key).flock_path
    return login, unit


@pytest.mark.parametrize("outside_home", [False, True])
@pytest.mark.parametrize("adapter", ["codex", "claude-code", "opencode", "kiro-cli"])
def test_the_lock_files_are_not_visible_in_either_sandbox_kind(
    tmp_path, monkeypatch, adapter, outside_home
):  # SCN-SEC-99
    cache = tmp_path / "runner-cache"
    if outside_home:
        cache.mkdir()
    world = make_world(tmp_path, l4_cache=cache if outside_home else None)
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", adapter)
    login, unit = lock_paths(world, wb, monkeypatch)
    for path in (login, unit):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    # the login lock dir is no adapter's credential path: the agent kind's bind of its own login never re-exposes it
    logins = expand_credential_paths({k: list(v) for k, v in CREDENTIAL_PATHS.items()}, world.home)
    overlaps = [
        p for ps in logins.values() for p in ps if p == login.parent or p in login.parents or login.parent in p.parents
    ]
    assert not overlaps
    sandbox = BwrapSandbox("/usr/bin/bwrap")
    gate_spec = wb.gate_spec(network=True)
    agent_spec = wb.agent_spec()
    gate_argv = sandbox.build_argv(["true"], gate_spec, build_gate_env(world.host_env, gate_spec))
    agent_argv = sandbox.build_argv(["true"], agent_spec, build_agent_env(world.host_env, agent_spec))
    for argv in (gate_argv, agent_argv):
        assert not visible(argv, login), "the login lock file is readable"
        assert not visible(argv, unit), "the unit lock file is readable"
        assert visible(argv, wb.worktree)  # the model does show what a step is meant to see
    assert visible(agent_argv, wb.agent_tmp / "result.json")
