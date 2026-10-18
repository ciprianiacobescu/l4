"""SANDBOX-003 (L4-SEC-038): canaries in the home, in another unit's step directory and in the lock directory are run
through the real gate and agent argv; a readable one fails closed. A fake runner stands in for bwrap, except in the
live test (skipped where bwrap is absent)."""

import os
import shutil
from collections.abc import Sequence
from pathlib import Path

from l4.config.schema import L4Config
from l4.doctor import checks_sandbox as sb
from l4.doctor.context import CmdResult, DoctorContext, system_context
from l4.doctor.registry import Check, Registry, run_checks

from ..sandbox.bwrap_live import requires_bwrap


class FakeBwrap:
    """Reads the canaries it was asked to read (the trailing arguments of the probe command) and answers like a
    sandbox would: `readable` is the {call index: canary index} it reports as readable; call 0 is the gate kind, call 1
    the agent kind."""

    def __init__(self, readable: dict[int, int] | None = None, done: bool = True) -> None:
        self.readable, self.done, self.calls, self.contents = readable or {}, done, [], []

    def run(self, argv: Sequence[str], timeout: float = 10.0, env=None) -> CmdResult:
        self.calls.append(list(argv))
        canaries = argv[argv.index("sh") + 1 :] if "sh" in argv else []
        self.contents += [Path(c).read_text() for c in canaries if Path(c).is_file()]
        index = len(self.calls) - 1
        lines = [f"L4-READ:{canaries[self.readable[index]]}"] if index in self.readable else []
        if self.done:
            lines.append("L4-CANARY-DONE")
        return CmdResult(0, "\n".join(lines) + "\n", "" if self.done else "bwrap: no namespace\n")


def check(tmp_path: Path, fake: FakeBwrap, cfg: L4Config | None = None, tools=None):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"HOME": str(home), "L4_CACHE": str(tmp_path / "runner-cache"), "PATH": "/usr/bin"}
    which = (lambda name: f"/fake/bin/{name}") if tools is None else tools.get
    ctx = DoctorContext(tmp_path / "repo", cfg or L4Config(), env, which, fake.run, (3, 12, 1))
    registry = Registry()
    registry.register(Check("SANDBOX-003", "the home is hidden", "error", sb._sandbox_003))
    (result,) = run_checks(ctx, registry=registry)
    return result, home, tmp_path / "runner-cache"


def leftovers(home: Path, cache: Path) -> list[Path]:
    return [*home.glob(".l4-canary-*"), *cache.rglob("*l4-canary-*"), *cache.glob("doctor/sandbox-003-*")]


def test_a_readable_canary_fails_and_nothing_is_left(tmp_path):  # SCN-SEC-96
    (tmp_path / "repo").mkdir()
    fake = FakeBwrap(readable={1: 0})  # the agent sandbox reads the first canary, the one in the home
    result, home, cache = check(tmp_path, fake)
    assert result.status == "fail" and (result.severity or "error") == "error"
    assert "agent" in result.message and ".l4-canary-" in result.message and str(home) in result.message
    assert fake.contents and all(c not in result.message for c in fake.contents)  # no canary content in the text
    assert len(fake.calls) == 2 and leftovers(home, cache) == []


def test_a_gate_kind_that_reads_the_unit_canary_fails_naming_the_gate(tmp_path):
    (tmp_path / "repo").mkdir()
    result, home, cache = check(tmp_path, FakeBwrap(readable={0: 1}))
    assert result.status == "fail" and "gate" in result.message and "credential" in result.message
    assert leftovers(home, cache) == []


def test_hidden_canaries_pass_and_the_probe_covers_all_three_places(tmp_path):
    (tmp_path / "repo").mkdir()
    fake = FakeBwrap()
    result, home, cache = check(tmp_path, fake)
    assert result.status == "pass" and leftovers(home, cache) == []
    canaries = fake.calls[0][fake.calls[0].index("sh") + 1 :]
    assert len(canaries) == 3
    assert any(Path(c).parent == home for c in canaries)
    assert any(c.endswith("/agent-tmp/credential") and cache in Path(c).parents for c in canaries)
    assert any(c.endswith(".lock") and cache / "locks" in Path(c).parents for c in canaries)
    argv = fake.calls[0]
    assert argv.count("--tmpfs") >= 3 and str(home) in argv and str(cache) in argv  # the real argv, covers both


def test_a_probe_that_does_not_finish_fails_closed(tmp_path):
    (tmp_path / "repo").mkdir()
    result, home, cache = check(tmp_path, FakeBwrap(done=False))
    assert result.status == "fail" and "namespace" in result.message and leftovers(home, cache) == []


def test_skipped_without_a_bwrap_sandbox(tmp_path):  # SCN-SEC-98
    (tmp_path / "repo").mkdir()
    none = L4Config.model_validate({"sandbox": {"mode": "none", "allow_none": True}})
    result, *_ = check(tmp_path, FakeBwrap(), cfg=none)
    assert result.status == "skip" and "none" in result.message
    result, *_ = check(tmp_path, FakeBwrap(), tools={"python3": "x"})
    assert result.status == "skip" and "bwrap" in result.message


@requires_bwrap
def test_the_real_argv_passes(var_tmp_dir):  # SCN-SEC-97
    (var_tmp_dir / "home").mkdir()
    (var_tmp_dir / "repo").mkdir()
    env = {"HOME": str(var_tmp_dir / "home"), "L4_CACHE": str(var_tmp_dir / "cache"), "PATH": os.environ["PATH"]}
    ctx = system_context(var_tmp_dir / "repo", L4Config(), env)
    registry = Registry()
    registry.register(Check("SANDBOX-003", "the home is hidden", "error", sb._sandbox_003))
    (result,) = run_checks(ctx, registry=registry)
    assert result.status == "pass", result.message
    assert leftovers(var_tmp_dir / "home", var_tmp_dir / "cache") == []
    assert shutil.which("bwrap")


def test_setup_paths_is_a_warning_row_whenever_it_is_set(tmp_path):  # SCN-PRV-105 (owner decision Q1)
    from l4.doctor.registry import exit_code

    def run(cfg: L4Config):
        ctx = DoctorContext(tmp_path, cfg, {"HOME": str(tmp_path)}, lambda name: None, FakeBwrap().run, (3, 12, 1))
        registry = Registry()
        registry.register(Check("SANDBOX-004", "setup_paths", "warn", sb._sandbox_004))
        (result,) = run_checks(ctx, registry=registry)
        return result

    quiet = run(L4Config())
    assert quiet.status == "pass"
    loud = run(L4Config.model_validate({"sandbox": {"setup_paths": ["~/.npmrc"]}}))
    assert loud.status == "fail" and loud.severity == "warn" and "setup code" in loud.message
    assert ".npmrc" not in loud.message  # the path is not echoed
    assert int(exit_code([loud])) == 0  # a warning never fails the run
