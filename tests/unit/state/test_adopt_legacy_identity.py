"""F3 of the review of sandbox-isolation: a run file of the earlier `pending-unpublished` layout is adopted by the
repository it belongs to, decided by the repository key the file records (or, in a file written before the key was
recorded, by the project path of its CI link), never by whether a commit it names exists here: any clone has the shared
history. Ported from the reviewer's adopt_test.py."""

import json
import subprocess
from pathlib import Path

from l4.state.pending import adopt_legacy

KEY = "proj-0123456789"
OTHER = "proj-9999999999"
PATH = "team-a/proj"


def run_file(directory: Path, run_id: str, **fields: object) -> Path:
    path = directory / f"{run_id}.jsonl"
    path.write_text(json.dumps({"type": "run.started", "run_id": run_id, **fields}) + "\n")
    return path


def test_a_clone_that_shares_the_commits_does_not_adopt_the_other_projects_file(tmp_path: Path):
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir()
    for args in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                                                 "--allow-empty", "-m", "base"]):  # fmt: skip
        subprocess.run(["git", "-C", str(a), *args], check=True, env=env, capture_output=True)
    shared = subprocess.run(
        ["git", "-C", str(a), "rev-parse", "HEAD"], check=True, env=env, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "clone", "-q", str(a), str(b)], check=True, env=env, capture_output=True)
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    # project A's file, written before the key was recorded: it names a commit every clone of A has
    mine = run_file(legacy, "r-20261010T1000Z-aaaa", base=shared, head=shared)
    keyed = tmp_path / "keyed"
    assert (
        adopt_legacy(legacy, keyed, repo_key=KEY, repo_path=None) == []
    )  # B has the commit and still must not adopt it
    assert mine.exists() and not keyed.exists()


def test_a_file_is_adopted_by_its_recorded_key_only(tmp_path: Path, caplog):  # SCN-SEC-84
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    ours = run_file(legacy, "r-20261010T1000Z-aaaa", repository_key=KEY)
    theirs = run_file(legacy, "r-20261010T1001Z-bbbb", repository_key=OTHER)
    unproven = run_file(legacy, "r-20261010T1002Z-cccc", base="a" * 40)
    keyed = tmp_path / "keyed"
    moved = adopt_legacy(legacy, keyed, repo_key=KEY, repo_path=PATH)
    assert [p.name for p in moved] == [ours.name] and (keyed / ours.name).is_file() and not ours.exists()
    assert theirs.exists() and unproven.exists()
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1 and warnings[0].startswith("2 ") and str(legacy) in warnings[0]


def test_a_file_before_the_key_was_recorded_is_adopted_by_the_project_path_of_its_ci_link(tmp_path: Path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    ours = run_file(legacy, "r-20261010T1000Z-aaaa", ci_url="https://<forge>/team-a/proj/-/pipelines/12")
    github = run_file(legacy, "r-20261010T1001Z-bbbb", ci_url="https://<forge>/team-a/proj/actions/runs/34")
    other = run_file(legacy, "r-20261010T1002Z-cccc", ci_url="https://<forge>/team-b/proj/-/pipelines/12")
    prefix = run_file(legacy, "r-20261010T1003Z-dddd", ci_url="https://<forge>/team-a/proj-fork/-/pipelines/1")
    moved = adopt_legacy(legacy, tmp_path / "keyed", repo_key=KEY, repo_path=PATH)
    assert sorted(p.name for p in moved) == sorted([ours.name, github.name])
    assert other.exists() and prefix.exists()
