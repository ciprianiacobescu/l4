"""Every place the harness spawns an agent CLI takes the login lock (SPEC L4-FAC-008, SCN-FAC-12).

Two kinds of proof. The dynamic one injects a recording runner under each real adapter and asserts that, at the moment
the CLI would be spawned, this thread holds the login lock (`held_keys`): the probe ladder (`l4 probe`, selection,
`doctor --live`), the readiness probe (`doctor` PRV-001) and the adapter run. The static one lists every module that
spawns a process and fails when a new one appears without being classified, so a new spawn path cannot go unseen.
"""

import contextlib
import os
import re
import stat
from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx, RunRequest
from l4.agents.factory import Factory
from l4.agents.gate import held_keys
from l4.agents.proc import ProcOutcome, ProcRunner
from l4.availability.cooldown import AvailabilityStore
from l4.config.schema import L4Config, Profile, RolesCfg
from l4.doctor.context import CmdResult
from l4.provision.readiness import AdapterState, adapter_readiness

ADAPTERS = {
    "claude-code": Profile(adapter="claude-code", model="haiku", auth="subscription", vendor="anthropic"),
    "codex": Profile(adapter="codex", model="gpt-5", auth="subscription", vendor="openai"),
    "kiro-cli": Profile(adapter="kiro-cli", model="glm-5", auth="subscription", vendor="zhipu"),
    "opencode": Profile(adapter="opencode", model="anthropic/claude-sonnet", auth="subscription", vendor="anthropic"),
}
BINARY = {"claude-code": "claude", "codex": "codex", "kiro-cli": "kiro-cli", "opencode": "opencode"}


@pytest.fixture
def world(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in BINARY.values():
        exe = bin_dir / name
        exe.write_text("#!/bin/sh\n")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    spawns: list[tuple[str, tuple[str, ...], list[str]]] = []

    def run(argv, cwd, env, timeout):
        spawns.append(("run", tuple(argv), held_keys()))
        return CmdResult(0, "9.9.9\n", "")

    def rpc(argv, cwd, env, timeout, messages):
        spawns.append(("rpc", tuple(argv), held_keys()))
        return {}

    home = tmp_path / "home"
    home.mkdir()
    ctx = ProbeCtx(environ={"HOME": str(home), "PATH": str(bin_dir)}, cwd=tmp_path, run=run, rpc=rpc)
    return ctx, spawns


def factory_for(profile: Profile, ctx: ProbeCtx, tmp_path: Path) -> Factory:
    cfg = L4Config(profiles={"p": profile}, roles=RolesCfg(implementer=["p"], judges=["p"]))
    return Factory(cfg, ctx, availability=AvailabilityStore(tmp_path / "cache"))


@pytest.mark.parametrize("adapter", sorted(ADAPTERS))
def test_every_spawn_of_the_probe_ladder_holds_the_login_lock(adapter, world, tmp_path):
    ctx, spawns = world
    factory = factory_for(ADAPTERS[adapter], ctx, tmp_path)
    found = factory.probe_all(["p"], refresh=True)  # `l4 probe --no-cache`
    assert spawns, f"{adapter}: the ladder spawned nothing, so the test proves nothing"
    assert all(held == [f"{adapter}/{held[0].split('/')[1]}"] for _, _, held in spawns), spawns
    assert held_keys() == [] and found[0].profile == "p"  # and the lock is gone after it
    spawns.clear()
    with contextlib.suppress(Exception):  # the stub CLI fails its auth step; only the spawns matter here
        factory.for_role("implementer", "u")
    assert spawns and all(len(held) == 1 for _, _, held in spawns), spawns


@pytest.mark.parametrize("adapter", sorted(ADAPTERS))
def test_the_readiness_probe_holds_the_login_lock(adapter, world, tmp_path):
    ctx, spawns = world
    factory = factory_for(ADAPTERS[adapter], ctx, tmp_path)
    row = adapter_readiness("p", ADAPTERS[adapter], factory, ctx)
    assert row.state is not AdapterState.MISSING
    auth_spawns = [held for kind, argv, held in spawns if "--version" not in argv]
    assert auth_spawns and all(len(held) == 1 for held in auth_spawns), spawns  # `--version` reads no login


@pytest.mark.parametrize("adapter", sorted(ADAPTERS))
def test_the_adapter_run_holds_the_login_lock(adapter, world, tmp_path, monkeypatch):
    ctx, _ = world
    seen: list[list[str]] = []

    def run(self, argv, env, cwd, **kw):
        seen.append(held_keys())
        kw["stdout_path"].write_text("")
        return ProcOutcome(0)

    monkeypatch.setattr(ProcRunner, "run", run)
    profile = ADAPTERS[adapter]
    factory = factory_for(profile, ctx, tmp_path)
    impl = factory._gated(profile, factory.build(profile))
    work = tmp_path / "work"  # the checkout: a CLI found inside it is refused
    work.mkdir()
    request = RunRequest(
        profile=profile, role="implementer", cwd=work, prompt="p", result_path=tmp_path / "r.json",
        raw_events_path=tmp_path / "raw.jsonl", env=dict(ctx.environ), host_env={},
    )  # fmt: skip
    with contextlib.suppress(Exception):  # the stub writes no events; the spawn is what is under test
        impl.run(request)
    assert seen and all(len(held) == 1 for held in seen), seen
    assert held_keys() == []


# ---- every module that can spawn a process is classified ----------------------------------------

SPAWN = re.compile(
    r"subprocess\.(Popen|run|check_output|check_call|call)\b|ProcRunner\(|\brun_process\b|run_rpc_session|os\.exec"
    r"|create_subprocess|from subprocess import"
)
GATED = "agent CLI: spawned only inside the login lock (see the dynamic tests above)"
SEAM = "the spawn seam itself: callers decide, and the agent callers are the gated ones"
OTHER = "not an agent CLI"
CLASSIFIED = {
    # the adapters: `run` through GatedAdapter, probes through the gated ladder, readiness through holding_login
    "agents/claude_code.py": GATED, "agents/codex.py": GATED, "agents/kiro_cli.py": GATED,
    "agents/opencode.py": GATED, "agents/command.py": "a user-defined command, not a stored OAuth login",
    "agents/proc.py": SEAM, "proc.py": SEAM, "availability/rpc.py": SEAM,
    "availability/probes.py": GATED, "availability/quota.py": GATED,
    "availability/fallback.py": "the probe ladder runs under `_ladder_run`",
    "services.py": "wires `run_process` into the ProbeCtx of the Factory",
    "doctor/checks_agents.py": "LIVE-001 goes through Factory.for_role; LIVE-005 runs `--version` only",
    "doctor/checks_provision.py": "PRV-001 goes through adapter_readiness (holding_login)",
    "doctor/context.py": "doctor's run seam: versions of git, node, uv, the agent binaries (no login)",
    "sim/availability.py": "the simulator: fake adapters",
    "eval/cellrun.py": "starts `l4 run` as a child; that process takes the lock like any other",
    "eval/env.py": OTHER, "eval/run.py": "`uv sync` and a version probe", "eval/workspace.py": OTHER,
    "forge/local.py": "the test forge's squash merge runs git on its bare origin",
    "gates/dryrun.py": OTHER, "gates/e2e_launch.py": OTHER, "gates/runner.py": "the project's own test gates",
    "init/action.py": "`git ls-remote` for a harness ref (adoption-kit)",
    "llm/system_one.py": "the local System-One model server", "memory/serena.py": "the Serena MCP server",
    "s1/canary.py": OTHER, "sandbox/bwrap.py": OTHER, "sandbox/select.py": OTHER, "setup/gitlab.py": OTHER,
    "sim/runner.py": "starts the simulator child", "specs/openspec.py": OTHER, "state/environment.py": OTHER,
    "vcs/git.py": OTHER,
    "yolo/judge_sandbox.py": "hands `run_process` to a BwrapSandbox to probe bwrap only; no agent CLI",
    "yolo/readiness.py": "wires `run_process` into the Factory's ProbeCtx; the judge is the gated impl of `for_role`",
}  # fmt: skip


def test_every_module_that_spawns_a_process_is_classified():
    src = Path(__file__).resolve().parents[3] / "src" / "l4"
    found = {str(path.relative_to(src)) for path in src.rglob("*.py") if SPAWN.search(path.read_text(encoding="utf-8"))}
    assert found - CLASSIFIED.keys() == set(), (
        "a module that spawns a process is not classified: if it starts an agent CLI against a stored login it must "
        "run inside the login lock (l4.agents.gate), then add it here"
    )
    assert CLASSIFIED.keys() - found == set(), "classified modules that no longer spawn anything: remove them"
    assert os.path.isdir(src)
