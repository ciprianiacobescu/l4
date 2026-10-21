"""L4-EVAL-014: the matrix, run strictly one cell at a time, one directory per cell."""

import json
from pathlib import Path

from l4.eval.run import Deps
from l4.exitcodes import ExitCode

from ._fakerun import ScriptedRunner
from ._go import go

ALL = ["add-late-fee", "add-reorder-quantity", "add-shelf-code", "add-tip-amount"]
IMPL_UNITS = ["add-reorder-quantity", "add-shelf-code", "add-tip-amount"]


def matrix_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("cell ")]


def test_dry_run_prints_the_matrix_and_writes_nothing(make_app, seeds_root: Path, capsys, tmp_path: Path) -> None:
    out = tmp_path / "out"
    code = go(
        make_app(), seeds_root, impl=("p1", "p2"), judge=("j2",), ref_judge="j1", k=2, out=out, dry_run=True
    )  # fmt: skip
    assert code == ExitCode.OK and not out.exists()
    lines = matrix_lines(capsys.readouterr().out)
    # implementer cells first (profile x unit x k, judge-only units left out), then judge cells
    assert len(lines) == 2 * 3 * 2 + 1 * 4 * 2
    assert lines[0] == "cell implementer p1 add-reorder-quantity k0"
    assert lines[5] == "cell implementer p1 add-tip-amount k1"
    assert all(line.startswith("cell implementer") for line in lines[:12])
    assert lines[12] == "cell judge j2 add-late-fee k0" and lines[-1] == "cell judge j2 add-tip-amount k1"


def test_units_restrict_the_matrix(make_app, seeds_root: Path, capsys) -> None:
    go(make_app(), seeds_root, impl=("p1",), ref_judge="j1", units=("add-shelf-code", "add-late-fee"))
    assert matrix_lines(capsys.readouterr().out) == ["cell implementer p1 add-shelf-code k0"]


def test_a_run_writes_one_directory_per_cell_and_runs_them_one_at_a_time(
    make_app, seeds_root: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    in_flight = {"n": 0, "max": 0}
    scripted = ScriptedRunner()

    def runner(argv, env, cwd, timeout):
        in_flight["n"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["n"])
        try:
            return scripted(argv, env, cwd, timeout)
        finally:
            in_flight["n"] -= 1

    code = go(
        make_app(), seeds_root, impl=("p1",), ref_judge="j1", units=("add-shelf-code", "add-tip-amount"),
        out=out, dry_run=False, deps=Deps(runner=runner),
    )  # fmt: skip
    assert code == ExitCode.OK and in_flight["max"] == 1
    cells = sorted(p.name for p in (out / "cells").iterdir())
    assert cells == ["implementer-p1-add-shelf-code-k0", "implementer-p1-add-tip-amount-k0"]
    for name in cells:
        files = {p.name for p in (out / "cells" / name).iterdir()}
        assert {"cfg.yaml", "run.log", "ledger.jsonl", "result.json"} <= files
    result = json.loads((out / "cells" / cells[0] / "result.json").read_text())
    assert result["status"] == "pass" and result["cell_key"] == "implementer|p1|add-shelf-code|0"
    assert [c["profile"] for c in scripted.calls] == ["p1", "p1"]
