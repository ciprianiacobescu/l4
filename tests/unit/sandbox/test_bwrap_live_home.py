"""sandbox-security-2 and -4 (L4-SEC-030..032, L4-PRV-040) under a real bubblewrap, ported from the review's
live_bwrap.py parts r2 and r4. Skipped where bwrap is absent; the argv half is in test_bwrap_home.py."""

import stat
from pathlib import Path

import pytest

from l4.agents.credentials import write_credential_file
from l4.agents.opencode_provider import write_key_file

from .bwrap_live import SECRETS, make_world, requires_bwrap

pytestmark = requires_bwrap


def _plant(home: Path) -> None:
    for rel, text in SECRETS.items():
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        (home / rel).write_text(text)
        (home / rel).chmod(0o600)


def test_a_gate_reads_no_credential_of_the_home(var_tmp_dir):  # SCN-SEC-70
    world = make_world(var_tmp_dir)
    _plant(world.home)
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    seen = world.read(wb, "gate", [world.home / rel for rel in SECRETS])
    assert not any(seen.values()), seen


def test_an_agent_sees_its_own_login_and_nothing_else(var_tmp_dir):  # SCN-SEC-71
    world = make_world(var_tmp_dir)
    _plant(world.home)
    (world.home / ".claude.json").write_text("{}")
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    seen = world.read(wb, "agent", [world.home / ".claude.json", *[world.home / rel for rel in SECRETS]])
    assert seen.pop(str(world.home / ".claude.json")) is True
    assert not any(seen.values()), seen


def test_another_units_step_files_and_locks_are_hidden(var_tmp_dir):  # SCN-SEC-75
    cache = var_tmp_dir / "runner-cache"
    cache.mkdir()
    world = make_world(var_tmp_dir, l4_cache=cache)
    wa = world.bench("add-login", "r-20261017T1200Z-aaaa", "opencode")
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    other_tmp = wa.agent_tmp / "note"
    other_tmp.write_text("a")
    other_tree = cache / "worktrees" / "other-0123456789" / "openspec" / "x" / "f"
    other_tree.parent.mkdir(parents=True)
    other_tree.write_text("b")
    lock = cache / "locks" / "unit.lock"
    lock.parent.mkdir()
    lock.write_text("c")
    own_cache = next(c.path for c in wb.caches if c.env == "UV_CACHE_DIR") / "mine"
    own_cache.write_text("d")
    own_tree = wb.agent_tmp / "mine"
    own_tree.write_text("e")
    for kind in ("gate", "agent"):
        seen = world.read(wb, kind, [other_tmp, other_tree, lock, own_cache])
        assert [seen[str(p)] for p in (other_tmp, other_tree, lock)] == [False] * 3
        assert seen[str(own_cache)] is True
    assert world.read(wb, "agent", [own_tree])[str(own_tree)] is True


def test_tools_under_the_home_run_in_both_kinds(var_tmp_dir):  # SCN-SEC-78
    world = make_world(var_tmp_dir)
    home = world.home
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "share" / "l4-test" / "versions" / "1").mkdir(parents=True)
    tool_a = home / ".local" / "bin" / "l4-tool-a"
    tool_a.write_text("#!/bin/sh\necho a\n")
    real_b = home / ".local" / "share" / "l4-test" / "versions" / "1" / "tool-b"
    real_b.write_text("#!/bin/sh\necho b\n")
    for tool in (tool_a, real_b):
        tool.chmod(stat.S_IRWXU)
    (home / ".local" / "bin" / "l4-tool-b").symlink_to(real_b)
    path = f"{home}/.local/bin:/usr/local/bin:/usr/bin:/bin"
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    for kind in ("gate", "agent"):
        done = world.run(wb, kind, "l4-tool-a && l4-tool-b", path=path)
        assert done.returncode == 0, done.stderr
        assert done.stdout.split() == ["a", "b"]


@pytest.mark.parametrize("outside_home", [False, True])
def test_a_units_key_files_are_hidden_from_another_unit(var_tmp_dir, outside_home):  # SCN-PRV-100
    cache = var_tmp_dir / "runner-cache"
    if outside_home:
        cache.mkdir()
    world = make_world(var_tmp_dir, l4_cache=cache if outside_home else None)
    wa = world.bench("add-login", "r-20261017T1200Z-aaaa", "opencode")
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    (wa.agent_tmp / "opencode-config").mkdir(mode=0o700, exist_ok=True)
    key = write_key_file(wa.agent_tmp / "opencode-config", "sk-PROFILE-A-PROVIDER-KEY")
    cred = write_credential_file(wa.agent_tmp, "sk-PROFILE-A-LOADER-VALUE")
    for kind in ("gate", "agent"):
        seen = world.read(wb, kind, [key, cred])
        assert not any(seen.values()), seen
    assert "PROVIDER-KEY" in key.read_text() and "LOADER-VALUE" in cred.read_text()


@pytest.mark.parametrize("outside_home", [False, True])
def test_login_and_unit_lock_files_are_not_readable(var_tmp_dir, monkeypatch, outside_home):  # SCN-SEC-99
    import pwd
    from types import SimpleNamespace

    from l4.agents.gate import ConcurrencyGate, lock_root
    from l4.vcs.names import UnitNames
    from l4.vcs.repokey import key_of_common_dir

    cache = var_tmp_dir / "runner-cache"
    if outside_home:
        cache.mkdir()
    world = make_world(var_tmp_dir, l4_cache=cache if outside_home else None)
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(world.home)))
    monkeypatch.delenv("L4_LOCK_DIR", raising=False)
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    login = ConcurrencyGate(locks_dir=lock_root(world.host_env))._path("codex", "deadbeefdeadbeef", 0)
    key = key_of_common_dir(wb.git_common_dir, world.host_env)
    unit = UnitNames.for_unit("openspec:add-search", branch_prefix="l4/", cache=wb.cache_root, repo_key=key).flock_path
    for path in (login, unit):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    for kind in ("gate", "agent"):
        seen = world.read(wb, kind, [login, unit])
        assert not any(seen.values()), seen
