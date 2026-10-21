import json
from pathlib import Path

import pytest

from l4.eval import replay
from l4.eval.seeds import load_seed_set

PROMPT = "# Harness contract\n...\n# Task 1.1\n<l4:data>x</l4:data>\n\n# Phase: {phase} (words)\nbody\n"


def _reference(seeds_root: Path, tmp_path: Path, unit_id: str) -> Path:
    """The unit's reference directory as the cell has it: red/ and green/ files."""
    unit = load_seed_set(seeds_root).unit(unit_id)
    ref = tmp_path / "reference"
    for kind, files in (("red", unit.reference_red), ("green", unit.reference_green)):
        for rel, data in files.items():
            (ref / kind / rel).parent.mkdir(parents=True, exist_ok=True)
            (ref / kind / rel).write_bytes(data)
    return ref


def _run(tmp_path: Path, ref: Path, phase: str) -> tuple[int, dict, Path]:
    prompt = tmp_path / f"prompt-{phase}.md"
    prompt.write_text(PROMPT.format(phase=phase))
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    result = tmp_path / f"result-{phase}.json"
    code = replay.main(["--reference", str(ref), "--prompt", str(prompt), "--result", str(result)], cwd=work)
    return code, json.loads(result.read_text()) if result.exists() else {}, work


def test_the_red_step_writes_the_red_files_and_a_valid_result(seeds_root: Path, tmp_path: Path) -> None:
    ref = _reference(seeds_root, tmp_path, "add-shelf-code")
    code, result, work = _run(tmp_path, ref, "RED")
    assert code == 0
    assert (work / "src/inventory/shelf.py").read_text().strip().endswith("raise NotImplementedError")
    assert (work / "tests/test_shelf_code.py").is_file()
    assert result["status"] == "done" and result["phase"] == "red" and result["task_ids"] == ["1.1"]
    assert result["criteria_ids"] == ["C-7dc9fae5", "C-fa2e5d61"]
    assert result["tests_added"] == [
        "tests/test_shelf_code.py::test_an_aisle_below_one_is_rejected",
        "tests/test_shelf_code.py::test_the_code_is_zero_padded",
    ]
    assert sorted(result["files_changed"]) == ["src/inventory/shelf.py", "tests/test_shelf_code.py"]
    from l4.implementer.result import RESULT_SCHEMA
    from l4.schemacheck import validate

    assert validate(result, RESULT_SCHEMA) == []


def test_the_green_step_writes_only_the_green_files(seeds_root: Path, tmp_path: Path) -> None:
    ref = _reference(seeds_root, tmp_path, "add-shelf-code")
    _run(tmp_path, ref, "RED")
    code, result, work = _run(tmp_path, ref, "GREEN")
    assert code == 0
    assert 'f"A{aisle:02d}' in (work / "src/inventory/shelf.py").read_text()
    assert result["phase"] == "green" and result["files_changed"] == ["src/inventory/shelf.py"]
    assert "tests_added" not in result or result["tests_added"] == []


def test_a_phase_it_cannot_replay_is_an_error(seeds_root: Path, tmp_path: Path) -> None:
    ref = _reference(seeds_root, tmp_path, "add-shelf-code")
    code, result, _ = _run(tmp_path, ref, "SINGLE")
    assert code != 0 and result == {}


def test_a_prompt_without_a_phase_is_an_error(seeds_root: Path, tmp_path: Path) -> None:
    ref = _reference(seeds_root, tmp_path, "add-shelf-code")
    prompt = tmp_path / "p.md"
    prompt.write_text("no phase here")
    assert (
        replay.main(
            ["--reference", str(ref), "--prompt", str(prompt), "--result", str(tmp_path / "r.json")], cwd=tmp_path
        )
        != 0
    )


def test_a_symlink_in_the_reference_is_refused(tmp_path: Path) -> None:
    ref = tmp_path / "reference"
    (ref / "red").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("s")
    (ref / "red" / "link.py").symlink_to(tmp_path / "secret.txt")
    with pytest.raises(replay.ReplayError):
        replay.files_of(ref, "red")


def test_the_module_runs_as_a_script(seeds_root: Path, tmp_path: Path) -> None:
    import subprocess
    import sys

    ref = _reference(seeds_root, tmp_path, "add-tip-amount")
    prompt = tmp_path / "p.md"
    prompt.write_text(PROMPT.format(phase="RED"))
    work = tmp_path / "w"
    work.mkdir()
    done = subprocess.run(
        [sys.executable, "-m", "l4.eval.replay", "--reference", str(ref), "--prompt", str(prompt), "--result",
         str(tmp_path / "r.json")], cwd=work, capture_output=True, text=True,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert (work / "src/pricing/tips.py").is_file()
