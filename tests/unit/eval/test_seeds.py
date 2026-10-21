import json
import re
import shutil
from pathlib import Path

import pytest

from l4.eval.seeds import SeedError, load_seed_set, seed_set_sha256
from l4.specs.openspec import parse_openspec_tasks

UNITS = ["add-late-fee", "add-reorder-quantity", "add-shelf-code", "add-tip-amount"]


def test_the_seed_set_has_the_base_and_four_units(seeds_root: Path) -> None:
    seeds = load_seed_set(seeds_root)
    assert (seeds.base / "pyproject.toml").is_file()
    assert [u.id for u in seeds.units] == UNITS
    for unit in seeds.units:
        assert (unit.path / "proposal.md").is_file()
        assert len(parse_openspec_tasks((unit.path / "tasks.md").read_bytes())) == 1
        assert len(unit.criteria) == 2
        whens = re.findall(r"\*\*WHEN\*\* (.+)", "\n".join(c.text for c in unit.criteria))
        assert len(whens) == 2 and len(set(whens)) == 2
        assert (unit.path / "expected.json").is_file()
        assert unit.reference_red and unit.reference_green


def test_the_free_run_units_are_the_recorded_ones(seeds_root: Path) -> None:
    free = Path(__file__).resolve().parents[3] / "docs" / "live" / "free" / "seeds"
    for name in ("add-shelf-code", "add-tip-amount", "add-reorder-quantity"):
        for rel in ("proposal.md", "tasks.md", ".openspec.yaml"):
            assert (seeds_root / "units" / name / rel).read_bytes() == (free / name / rel).read_bytes()
        spec = next((free / name / "specs").glob("*/spec.md"))
        assert (seeds_root / "units" / name / "specs" / spec.parent.name / "spec.md").read_bytes() == spec.read_bytes()


def test_the_designed_defect_unit_is_judge_only(seeds_root: Path) -> None:
    seeds = load_seed_set(seeds_root)
    by_id = {u.id: u for u in seeds.units}
    assert by_id["add-late-fee"].judge_only
    assert by_id["add-late-fee"].expected["judge"]["verdict"] == "NEEDS_HUMAN"
    assert not by_id["add-shelf-code"].judge_only
    assert by_id["add-shelf-code"].expected["implementer"] == {"outcome": "pass"}


def test_reference_paths_are_relative_and_inside_the_project(seeds_root: Path) -> None:
    for unit in load_seed_set(seeds_root).units:
        for files in (unit.reference_red, unit.reference_green):
            for rel in files:
                assert not Path(rel).is_absolute() and ".." not in Path(rel).parts


def test_a_unit_without_a_reference_is_refused(seeds_root: Path, tmp_path: Path) -> None:
    copy = tmp_path / "seeds"
    shutil.copytree(seeds_root, copy)
    shutil.rmtree(copy / "units" / "add-tip-amount" / "reference" / "green")
    with pytest.raises(SeedError, match="add-tip-amount"):
        load_seed_set(copy)


def test_a_missing_directory_is_a_seed_error(tmp_path: Path) -> None:
    with pytest.raises(SeedError):
        load_seed_set(tmp_path / "nope")


def test_expected_json_is_valid_json(seeds_root: Path) -> None:
    for unit in load_seed_set(seeds_root).units:
        assert json.loads((unit.path / "expected.json").read_text()) == unit.expected


def test_seed_set_sha256_follows_the_bytes_not_the_place(seeds_root: Path, tmp_path: Path) -> None:
    first = seed_set_sha256(seeds_root)
    assert re.fullmatch(r"[0-9a-f]{64}", first)
    copy = tmp_path / "elsewhere"
    shutil.copytree(seeds_root, copy)
    assert seed_set_sha256(copy) == first
    (copy / "units" / "add-shelf-code" / "__pycache__").mkdir()
    (copy / "units" / "add-shelf-code" / "__pycache__" / "x.pyc").write_bytes(b"junk")
    assert seed_set_sha256(copy) == first  # caches are not seeds
    path = copy / "units" / "add-shelf-code" / "expected.json"
    path.write_text(path.read_text().replace("PASS", "FAIL"))
    assert seed_set_sha256(copy) != first


def test_seed_set_sha256_depends_on_a_rename(seeds_root: Path, tmp_path: Path) -> None:
    copy = tmp_path / "c"
    shutil.copytree(seeds_root, copy)
    first = seed_set_sha256(copy)
    (copy / "base" / "README.md").rename(copy / "base" / "README2.md")
    assert seed_set_sha256(copy) != first


def test_a_finder_file_is_not_a_seed(seeds_root: Path, tmp_path: Path) -> None:
    """Review of M1.14: macOS writes `.DS_Store` into a folder opened in Finder. It must not change the seed set's
    hash (the gate would refuse a Mac scorecard against a runner one as "different seed sets") nor become a reference
    file."""
    copy = tmp_path / "c"
    shutil.copytree(seeds_root, copy)
    first = seed_set_sha256(copy)
    for folder in (copy, copy / "base", copy / "units" / "add-shelf-code" / "reference" / "red"):
        (folder / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
    assert seed_set_sha256(copy) == first
    unit = load_seed_set(copy).unit("add-shelf-code")
    assert not any(".DS_Store" in rel for rel in (*unit.reference_red, *unit.reference_green))
