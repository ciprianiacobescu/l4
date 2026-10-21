"""L4-EVAL-003: the designed defect of add-late-fee is real and deterministic, not left to a judge's reading."""

import shutil
import subprocess
import sys
from pathlib import Path

from l4.eval.seeds import load_seed_set

ROOT = Path(__file__).resolve().parents[2] / "eval" / "seeds"


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(cwd), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=cwd, env=env, capture_output=True, text=True,
    )  # fmt: skip


def test_the_reference_green_passes_its_tests_and_fails_the_hidden_check(tmp_path: Path) -> None:
    unit = load_seed_set(ROOT).unit("add-late-fee")
    root = tmp_path / "proj"
    shutil.copytree(ROOT / "base", root, ignore=shutil.ignore_patterns("__pycache__"))
    for files in (unit.reference_red, unit.reference_green):
        for rel, data in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_bytes(data)
    assert _run(root).returncode == 0  # the gates are green: the tests do not see the defect
    assert unit.hidden_check is not None
    hidden = root / "hidden_check.py"  # copied here only for this run; never into a worktree
    shutil.copy(unit.hidden_check, hidden)
    done = _run(root, "hidden_check.py")
    assert done.returncode != 0
    assert "2 failed" in done.stdout  # both: the fee ignores the balance, and a negative balance is not rejected


def test_the_defect_unit_expects_a_held_back_verdict() -> None:
    unit = load_seed_set(ROOT).unit("add-late-fee")
    assert unit.expected["judge"] == {"verdict": "NEEDS_HUMAN", "min_findings": 1, "designed_defect": True}
    assert unit.judge_only


def test_the_hidden_check_is_not_part_of_any_reference_step() -> None:
    for unit in load_seed_set(ROOT).units:
        for files in (unit.reference_red, unit.reference_green):
            assert not any("hidden_check" in rel for rel in files)
