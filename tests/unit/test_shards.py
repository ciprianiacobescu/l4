"""scripts/dev/shards.py splits the unit test files into deterministic shards (L4-ACT-007, SCN-ACT-12)."""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dev" / "shards.py"


def load():
    spec = importlib.util.spec_from_file_location("shards", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["shards"] = module
    spec.loader.exec_module(module)
    return module


def make_tree(root: Path, counts: dict[str, int]) -> None:
    for name, n in counts.items():
        path = root / "tests" / "unit" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"def test_{i}():\n    pass\n" for i in range(n)))


def test_every_real_test_file_is_in_exactly_one_shard():
    shards = load()
    files = shards.test_files(ROOT)
    assert files, "no unit test files found"
    seen: list[str] = []
    for k in range(1, 9):
        seen += shards.shard(ROOT, k, 8)
    assert sorted(seen) == sorted(files)
    assert len(seen) == len(set(seen))


def test_n_one_gives_every_file():
    shards = load()
    assert sorted(shards.shard(ROOT, 1, 1)) == sorted(shards.test_files(ROOT))


def test_stable_across_runs_and_processes():
    shards = load()
    first = [shards.shard(ROOT, k, 8) for k in range(1, 9)]
    assert first == [shards.shard(ROOT, k, 8) for k in range(1, 9)]
    cli = subprocess.run(
        [sys.executable, str(SCRIPT), "--shard", "3", "--of", "8"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert cli.stdout.split() == first[2]


def test_a_new_file_lands_in_exactly_one_shard_and_does_not_move_others_wildly(tmp_path: Path):
    shards = load()
    make_tree(tmp_path, {"a/test_a.py": 5, "b/test_b.py": 3, "test_c.py": 1})
    before = {k: shards.shard(tmp_path, k, 2) for k in (1, 2)}
    make_tree(tmp_path, {"c/test_new.py": 2})
    after = {k: shards.shard(tmp_path, k, 2) for k in (1, 2)}
    homes = [k for k in (1, 2) if "tests/unit/c/test_new.py" in after[k]]
    assert len(homes) == 1
    assert sum(len(v) for v in after.values()) == sum(len(v) for v in before.values()) + 1


def test_balanced_by_test_function_count(tmp_path: Path):
    shards = load()
    make_tree(tmp_path, {"test_big.py": 10, "test_m1.py": 5, "test_m2.py": 5, "test_s.py": 1, "test_t.py": 1})
    sizes = [sum(shards.weight(tmp_path / f) for f in shards.shard(tmp_path, k, 2)) for k in (1, 2)]
    assert max(sizes) - min(sizes) <= 1


def test_nested_files_only_and_non_test_files_ignored(tmp_path: Path):
    shards = load()
    make_tree(tmp_path, {"test_x.py": 1, "helper.py": 1, "d/test_y.py": 1, "d/_util.py": 1})
    assert shards.test_files(tmp_path) == ["tests/unit/d/test_y.py", "tests/unit/test_x.py"]


@pytest.mark.parametrize(
    "args",
    [["--shard", "0", "--of", "8"], ["--shard", "9", "--of", "8"], ["--shard", "1", "--of", "0"]],
)
def test_bad_arguments_exit_2(args):
    done = subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 2
