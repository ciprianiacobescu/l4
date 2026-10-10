"""L4-EVAL-017: --idle-check gates every cell on a command's exit code (the runner is quiet or it is not)."""

import json
import sys
from pathlib import Path

from l4.eval.run import POLL_S, Deps, default_idle
from l4.exitcodes import ExitCode

from ._fakerun import ScriptedRunner
from ._go import go


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make_deps(runner, clock: Clock, idle) -> Deps:
    return Deps(runner=runner, sleep=clock.sleep, clock=clock.clock, idle=idle, version_of=lambda a: "1")


def test_exit_zero_starts_every_cell(make_app, seeds_root: Path, tmp_path: Path) -> None:
    clock, calls = Clock(), []
    scripted = ScriptedRunner()

    def idle(argv):
        calls.append(list(argv))
        return 0

    go(
        make_app(), seeds_root, impl=("p1",), ref_judge="j1", units=("add-shelf-code", "add-tip-amount"),
        out=tmp_path / "o", dry_run=False, idle_check="python3 /ops/idle.py --quiet",
        deps=make_deps(scripted, clock, idle),
    )  # fmt: skip
    assert calls == [["python3", "/ops/idle.py", "--quiet"]] * 2  # before each cell, split without a shell
    assert len(scripted.calls) == 2 and clock.slept == []


def test_a_busy_runner_waits_and_then_the_cell_starts(make_app, seeds_root: Path, tmp_path: Path) -> None:
    clock = Clock()
    answers = iter([1, 1, 0])
    scripted = ScriptedRunner()
    go(
        make_app(), seeds_root, impl=("p1",), ref_judge="j1", units=("add-shelf-code",), out=tmp_path / "o",
        dry_run=False, idle_check="idle", deps=make_deps(scripted, clock, lambda argv: next(answers)),
    )  # fmt: skip
    assert clock.slept == [POLL_S, POLL_S] and len(scripted.calls) == 1


def test_past_the_bound_the_cell_is_runner_busy_and_the_run_stops_with_exit_12(
    make_app, seeds_root: Path, tmp_path: Path
) -> None:
    clock, scripted, out = Clock(), ScriptedRunner(), tmp_path / "o"
    code = go(
        make_app(), seeds_root, impl=("p1",), ref_judge="j1", out=out, dry_run=False, idle_check="idle",
        idle_wait="2m", deps=make_deps(scripted, clock, lambda argv: 3),
    )  # fmt: skip
    assert code == ExitCode.WAITING_CAPACITY and scripted.calls == []
    assert clock.now >= 120.0
    results = [json.loads(p.read_text()) for p in (out / "cells").glob("*/result.json")]
    assert len(results) == 1  # the run stopped at the first cell: the others were not started
    assert results[0]["status"] == "invalid" and results[0]["invalid_reason"] == "runner_busy"
    card = json.loads((out / "scorecard.json").read_text())
    assert card["complete"] is False and len(card["cells"]) == 1


def test_the_hooks_output_never_reaches_the_scorecard(make_app, seeds_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "o"
    script = tmp_path / "idle.py"
    script.write_text(
        "import sys\nprint('HOOK-OUTPUT-MARKER'); print('HOOK-ERR-MARKER', file=sys.stderr)\nsys.exit(0)\n"
    )
    go(
        make_app(), seeds_root, judge=("j1",), units=("add-shelf-code",), out=out, dry_run=False,
        idle_check=f"{sys.executable} {script}", deps=Deps(runner=ScriptedRunner(), version_of=lambda a: "1"),
    )  # fmt: skip
    for path in out.rglob("*"):
        if path.is_file():
            assert "HOOK-" not in path.read_text(errors="replace")


def test_default_idle_runs_without_a_shell_and_returns_the_exit_code() -> None:
    assert default_idle([sys.executable, "-c", "raise SystemExit(0)"]) == 0
    assert default_idle([sys.executable, "-c", "raise SystemExit(7)"]) == 7
    assert default_idle(["/no/such/binary"]) != 0
    assert default_idle([sys.executable, "-c", "print(1); raise SystemExit(0) # ; touch /tmp/never"]) == 0


def test_an_empty_idle_check_is_a_usage_error(make_app, seeds_root: Path, tmp_path: Path) -> None:
    import pytest

    from l4.exitcodes import L4Exit

    with pytest.raises(L4Exit, match="--idle-check"):
        go(make_app(), seeds_root, judge=("j1",), out=tmp_path / "o", dry_run=False, idle_check="  ")
