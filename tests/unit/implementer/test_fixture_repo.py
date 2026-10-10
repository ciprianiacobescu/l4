import shutil
import subprocess
import sys
from pathlib import Path

from l4.specs.criteria import openspec_criteria
from l4.specs.openspec import parse_openspec_tasks

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "py_tdd"


def test_fixture_repo_baseline_is_green(tmp_path: Path):
    repo = tmp_path / "py_tdd"
    shutil.copytree(FIXTURE, repo)
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--junitxml=out.xml"],
        cwd=repo, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    assert "2 passed" in done.stdout


def test_fixture_repo_has_one_pending_task_and_its_criteria():
    change = FIXTURE / "openspec" / "changes" / "add-discount-codes"
    (task,) = parse_openspec_tasks((change / "tasks.md").read_bytes())
    assert (task.key, task.done) == ("1.1", False)
    assert [c.scenario for c in openspec_criteria(change)] == ["Known code", "Unknown code"]
