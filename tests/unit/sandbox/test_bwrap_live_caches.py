"""Review F1 under a real bubblewrap: the per-unit cache is read-only in the gate and agent sandboxes, each works in a
private scratch cache, and only a `gates.setup` command writes the shared cache. Skipped where bwrap is absent."""

from .bwrap_live import make_world, requires_bwrap

pytestmark = requires_bwrap


def test_only_a_setup_gate_writes_the_shared_cache(var_tmp_dir):  # SCN-PRV-109, live
    world = make_world(var_tmp_dir)
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    shared = next(c.path for c in wb.caches if c.env == "UV_CACHE_DIR")
    probe = (
        f'echo plant > "{shared}/zz_marker.pth" 2>/dev/null && echo SHARED-WRITABLE || echo SHARED-READ-ONLY; '
        'test "$UV_CACHE_DIR" != "' + str(shared) + '" && echo SCRATCH-ELSEWHERE; '
        'echo scratch > "$UV_CACHE_DIR/ok" && echo SCRATCH-WRITABLE'
    )
    done = world.run(wb, "gate", probe)
    lines = done.stdout.split()
    assert "SHARED-READ-ONLY" in lines and "SCRATCH-ELSEWHERE" in lines and "SCRATCH-WRITABLE" in lines, done
    assert not (shared / "zz_marker.pth").exists()
    setup = world.run(wb, "gate", f'echo ok > "{shared}/from-setup" && echo SHARED-WRITABLE', builds_env=True)
    assert setup.stdout.split() == ["SHARED-WRITABLE"] and (shared / "from-setup").is_file()


def test_the_agent_sandbox_mounts_the_shared_cache_read_only(var_tmp_dir):  # SCN-PRV-110, live
    import subprocess

    from l4.sandbox.env import build_agent_env, cache_env

    world = make_world(var_tmp_dir)
    wb = world.bench("add-search", "r-20261017T1201Z-bbbb", "claude-code")
    shared = next(c.path for c in wb.caches if c.env == "UV_CACHE_DIR")
    spec = wb.agent_spec()
    wb.reset_agent_tmp()
    env = build_agent_env(world.host_env, spec, extra=cache_env(spec))
    script = (
        f'echo plant > "{shared}/zz_marker.pth" 2>/dev/null && echo SHARED-WRITABLE || echo SHARED-READ-ONLY; '
        'echo scratch > "$UV_CACHE_DIR/ok" && echo SCRATCH-WRITABLE'
    )
    cmd = world.bwrap.wrap(["/bin/sh", "-c", script], spec, env)
    done = subprocess.run(cmd.argv, env=cmd.env, capture_output=True, text=True, timeout=60)
    assert done.stdout.split() == ["SHARED-READ-ONLY", "SCRATCH-WRITABLE"], done.stderr
    assert env["UV_CACHE_DIR"] != str(shared) and (wb.agent_tmp / "scratch-cache" / "UV_CACHE_DIR" / "ok").is_file()
    wb.discard_scratch()
    assert not (wb.agent_tmp / "scratch-cache").exists() and not (shared / "zz_marker.pth").exists()
