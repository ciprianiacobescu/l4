"""L4-EVAL-002: a seed cannot rot into an unsolvable unit. Every unit is a valid OpenSpec change, every criterion is
covered by a tagged test of the reference, and the base project's gate is green on the base and each reference green
and red on each reference red."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from l4.eval.seeds import SeedSet, SeedUnit, load_seed_set
from l4.schemacheck import validate
from l4.specs.detect import detect_frameworks
from l4.specs.openspec import parse_openspec_tasks

GATE = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x"]


@pytest.fixture(scope="module")
def seeds() -> SeedSet:
    return load_seed_set(Path(__file__).resolve().parents[2] / "eval" / "seeds")


def _project(seeds: SeedSet, tmp: Path, unit: SeedUnit | None, *, red: bool, green: bool) -> Path:
    root = tmp / "proj"
    shutil.copytree(seeds.base, root, ignore=shutil.ignore_patterns("__pycache__", ".venv", ".pytest_cache"))
    if unit is not None:
        for flag, files in ((red, unit.reference_red), (green, unit.reference_green)):
            if flag:
                for rel, data in files.items():
                    (root / rel).parent.mkdir(parents=True, exist_ok=True)
                    (root / rel).write_bytes(data)
    return root


def _gate(root: Path) -> int:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(root), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(GATE, cwd=root, env=env, capture_output=True, text=True).returncode


def test_every_unit_is_a_change_the_harness_detects(seeds: SeedSet, tmp_path: Path) -> None:
    for unit in seeds.units:
        repo = tmp_path / unit.id
        target = repo / "openspec" / "changes" / unit.id
        shutil.copytree(unit.path, target, ignore=shutil.ignore_patterns("reference", "expected.json"))
        assert detect_frameworks(repo).frameworks, unit.id
        tasks = parse_openspec_tasks((target / "tasks.md").read_bytes())
        assert len(tasks) == 1 and tasks[0].number == "1.1" and not tasks[0].done


def test_every_criterion_has_a_tagged_reference_test(seeds: SeedSet) -> None:
    for unit in seeds.units:
        tagged = set()
        for rel, data in unit.reference_red.items():
            if rel.startswith("tests/"):
                for call in re.findall(r"pytest\.mark\.l4\(([^)]*)\)", data.decode()):
                    tagged |= set(re.findall(r"C-[0-9a-f]{8}", call))
        assert tagged == {c.id for c in unit.criteria}, unit.id


def test_expected_json_matches_its_schema(seeds: SeedSet) -> None:
    import json
    from importlib import resources

    schema = json.loads(resources.files("l4.eval").joinpath("expected.schema.json").read_text(encoding="utf-8"))
    for unit in seeds.units:
        assert validate(unit.expected, schema) == [], unit.id
    assert validate({"implementer": {"outcome": "pass"}}, schema)  # a judge verdict is required
    assert validate({"judge": {"verdict": "MAYBE"}}, schema)
    assert validate({"judge": {"verdict": "PASS"}, "extra": 1}, schema)


def test_the_gate_is_green_on_the_base(seeds: SeedSet, tmp_path: Path) -> None:
    assert _gate(_project(seeds, tmp_path, None, red=False, green=False)) == 0


@pytest.mark.parametrize("unit_id", ["add-late-fee", "add-reorder-quantity", "add-shelf-code", "add-tip-amount"])
def test_the_gate_is_red_on_the_reference_red_and_green_on_the_reference_green(
    seeds: SeedSet, tmp_path: Path, unit_id: str
) -> None:
    unit = seeds.unit(unit_id)
    assert _gate(_project(seeds, tmp_path / "r", unit, red=True, green=False)) != 0
    assert _gate(_project(seeds, tmp_path / "g", unit, red=True, green=True)) == 0
