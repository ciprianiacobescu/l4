import subprocess
import sys
from pathlib import Path

from ._multi import build_repo


def test_fixture_history_builds_and_tests_pass_at_every_unit_head(tmp_path: Path):
    repo = tmp_path / "repo"
    git, units = build_repo(repo)
    assert len(units) == 8
    for unit in units:
        git.run("checkout", "--quiet", "--detach", unit.head)
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=repo, capture_output=True, text=True
        )
        assert done.returncode == 0, (unit.name, done.stdout[-600:])
        trailer = git.run("log", "-1", "--format=%(trailers:key=L4-Unit,valueonly)", unit.head).stdout.strip()
        assert trailer == unit.id
        changed = git.run("diff", "--name-only", f"{unit.base}..{unit.head}").stdout.split()
        assert any(p.startswith("tests/") for p in changed) and any(p.startswith("src/") for p in changed)


def test_the_fixture_history_does_not_depend_on_the_clock(tmp_path: Path):
    first, _ = build_repo(tmp_path / "a")
    second, _ = build_repo(tmp_path / "b")
    assert first.rev_parse("HEAD") == second.rev_parse("HEAD")
