"""The delegate's sandbox mounts the worktree read-only and leaves the private directory writable (L4-DLG-004,
SCN-DLG-14)."""

import logging
import subprocess
from dataclasses import replace
from pathlib import Path

from l4.sandbox.base import SandboxSpec
from l4.sandbox.bwrap import BwrapSandbox
from l4.sandbox.env import build_agent_env
from l4.sandbox.none import READ_ONLY_WARNING, NoSandbox

from .bwrap_live import make_world, requires_bwrap

EMPTY_ROOT = Path("/nonexistent-l4-host-root")
ENV = {"PATH": "/usr/bin", "HOME": "/h"}


def build(spec: SandboxSpec) -> list[str]:
    return BwrapSandbox("/usr/bin/bwrap", host_root=EMPTY_ROOT).build_argv(["true"], spec, ENV)


def triples(argv: list[str], flag: str) -> list[tuple[str, str]]:
    return [(argv[i + 1], argv[i + 2]) for i, a in enumerate(argv) if a == flag]


def test_ro_bind_when_the_spec_asks(make_spec):
    spec = make_spec("agent", "claude-code", worktree_read_only=True)
    argv = build(spec)
    wt, tmp = str(spec.worktree), str(spec.tmp_dir)
    assert (wt, wt) in triples(argv, "--ro-bind") and (wt, wt) not in triples(argv, "--bind")
    assert (tmp, tmp) in triples(argv, "--bind")


def test_the_guidance_masks_follow_the_read_only_bind(make_spec):
    spec = make_spec("agent", "claude-code", worktree_read_only=True)
    (spec.worktree / ".claude").mkdir()
    argv = build(spec)
    mask = argv.index(str(spec.worktree / ".claude"))
    ro = [i for i, a in enumerate(argv[:-1]) if a == "--ro-bind" and argv[i + 1] == str(spec.worktree)]
    assert ro and mask > ro[0] and argv[mask - 1] == "--tmpfs"


def test_the_default_stays_writable(make_spec):
    spec = make_spec("agent", "claude-code")
    assert spec.worktree_read_only is False
    argv = build(spec)
    wt = str(spec.worktree)
    assert (wt, wt) in triples(argv, "--bind") and (wt, wt) not in triples(argv, "--ro-bind")


def test_no_sandbox_warns_once_that_the_worktree_stays_writable(make_spec, caplog):
    spec = make_spec("agent", "claude-code", worktree_read_only=True)
    sandbox = NoSandbox(allow_none=True)
    with caplog.at_level(logging.WARNING, logger="l4.sandbox"):
        sandbox.wrap(["true"], spec, ENV)
        sandbox.wrap(["true"], spec, ENV)
    assert [r.getMessage() for r in caplog.records] == [READ_ONLY_WARNING]
    with caplog.at_level(logging.WARNING, logger="l4.sandbox"):
        caplog.clear()
        NoSandbox(allow_none=True).wrap(["true"], make_spec("agent", "claude-code"), ENV)
    assert caplog.records == []


@requires_bwrap
def test_a_write_fails_and_the_result_is_written(var_tmp_dir):  # SCN-DLG-14
    world = make_world(var_tmp_dir)
    wb = world.bench("add-login", "r-20261017T1201Z-cccc", "claude-code")
    spec = replace(wb.agent_spec(), worktree_read_only=True)
    wb.agent_tmp.mkdir(parents=True, exist_ok=True)
    script = (
        f"{{ echo x > '{wb.worktree}/planted.txt'; }} 2>&1 || echo DENIED; "
        f"echo ok > '{wb.agent_tmp}/result.json' && echo WRITTEN"
    )
    cmd = world.bwrap.wrap(["/bin/sh", "-c", script], spec, build_agent_env(world.host_env, spec))
    done = subprocess.run(cmd.argv, env=cmd.env, capture_output=True, text=True, timeout=60)
    assert "DENIED" in done.stdout and "WRITTEN" in done.stdout, done.stderr
    assert "Read-only file system" in done.stdout
    assert not (wb.worktree / "planted.txt").exists()
    assert (wb.agent_tmp / "result.json").read_text() == "ok\n"
