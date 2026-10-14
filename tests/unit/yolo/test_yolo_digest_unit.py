"""Input digests (design D3): SCN-YOLO-06, SCN-YOLO-07, OpenSpec and Kiro folders, deterministic empty set."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from l4.vcs.git import Git
from l4.yolo.digest import RevisionMissing, plan_digest, unit_digest

OPENSPEC = "openspec/changes/add-x"
KIRO = ".kiro/specs/feat"


def sh(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True
    )


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def commit(repo: Path) -> str:
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "c")
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()


def make_repo(tmp_path: Path) -> tuple[Path, Git]:
    repo = tmp_path / "r"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    write(repo, f"{OPENSPEC}/proposal.md", "why\n")
    write(repo, f"{OPENSPEC}/specs/x/spec.md", "### Requirement: R\nThe thing SHALL work.\n")
    write(repo, f"{OPENSPEC}/tasks.md", "## 1\n- [ ] 1.1 first\n  - [ ] 1.1.1 nested\n- [ ] 1.2 second\n")
    write(repo, f"{KIRO}/requirements.md", "# Req\nWHEN a THEN b\n")
    write(repo, f"{KIRO}/design.md", "design\n")
    write(repo, f"{KIRO}/tasks.md", "- [ ] 1. one\n- [ ] 2. two\n")
    write(repo, "src/other.py", "x = 1\n")
    return repo, Git(repo)


def test_digest_shape_is_sixteen_hex_chars(tmp_path):
    repo, git = make_repo(tmp_path)
    rev = commit(repo)
    digest = unit_digest(git, rev, OPENSPEC)
    assert len(digest) == 16 and int(digest, 16) >= 0
    assert digest == unit_digest(git, rev, OPENSPEC + "/")


def test_a_harness_tick_and_its_reports_keep_the_digest(tmp_path):  # SCN-YOLO-06
    repo, git = make_repo(tmp_path)
    before = unit_digest(git, commit(repo), OPENSPEC)
    write(repo, f"{OPENSPEC}/tasks.md", "## 1\n- [x] 1.1 first\n  - [~] 1.1.1 nested\n- [-] 1.2 second\n")
    write(repo, f"{OPENSPEC}/verification.md", "PASS\n")
    write(repo, f"{OPENSPEC}/questions.md", "Q?\n")
    write(repo, f"{OPENSPEC}/feedback.md", "fb\n")
    write(repo, f"{OPENSPEC}/.l4/ledger.jsonl", '{"e":1}\n')
    write(repo, f"{OPENSPEC}/specs/x/verification.md", "nested report\n")
    after = unit_digest(git, commit(repo), OPENSPEC)
    assert after == before


def test_capital_x_marker_is_normalised(tmp_path):
    repo, git = make_repo(tmp_path)
    before = unit_digest(git, commit(repo), KIRO)
    write(repo, f"{KIRO}/tasks.md", "- [X] 1. one\n- [ ] 2. two\n")
    assert unit_digest(git, commit(repo), KIRO) == before


def test_a_changed_requirement_changes_the_digest(tmp_path):  # SCN-YOLO-07
    repo, git = make_repo(tmp_path)
    before = unit_digest(git, commit(repo), KIRO)
    write(repo, f"{KIRO}/requirements.md", "# Req\nWHEN a THEN c\n")
    assert unit_digest(git, commit(repo), KIRO) != before


def test_a_changed_openspec_spec_task_text_or_new_file_changes_the_digest(tmp_path):
    repo, git = make_repo(tmp_path)
    base = unit_digest(git, commit(repo), OPENSPEC)
    write(repo, f"{OPENSPEC}/specs/x/spec.md", "### Requirement: R\nThe thing SHALL work well.\n")
    spec = unit_digest(git, commit(repo), OPENSPEC)
    write(repo, f"{OPENSPEC}/tasks.md", "## 1\n- [ ] 1.1 first!\n  - [ ] 1.1.1 nested\n- [ ] 1.2 second\n")
    task = unit_digest(git, commit(repo), OPENSPEC)
    write(repo, f"{OPENSPEC}/design.md", "new\n")
    added = unit_digest(git, commit(repo), OPENSPEC)
    assert len({base, spec, task, added}) == 4


def test_a_prose_checkbox_outside_tasks_md_is_content(tmp_path):
    repo, git = make_repo(tmp_path)
    write(repo, f"{OPENSPEC}/design.md", "- [ ] decide\n")
    before = unit_digest(git, commit(repo), OPENSPEC)
    write(repo, f"{OPENSPEC}/design.md", "- [x] decide\n")
    assert unit_digest(git, commit(repo), OPENSPEC) != before


def test_other_folders_do_not_change_it(tmp_path):
    repo, git = make_repo(tmp_path)
    before = unit_digest(git, commit(repo), OPENSPEC)
    write(repo, "src/other.py", "x = 2\n")
    write(repo, f"{KIRO}/design.md", "other unit\n")
    assert unit_digest(git, commit(repo), OPENSPEC) == before


def test_a_digest_is_taken_at_the_revision(tmp_path):
    repo, git = make_repo(tmp_path)
    first = commit(repo)
    before = unit_digest(git, first, OPENSPEC)
    write(repo, f"{OPENSPEC}/proposal.md", "changed\n")
    commit(repo)
    assert unit_digest(git, first, OPENSPEC) == before


def test_a_missing_folder_gives_the_empty_set_digest_and_a_missing_revision_raises(tmp_path):
    repo, git = make_repo(tmp_path)
    rev = commit(repo)
    empty = hashlib.sha256(b"").hexdigest()[:16]
    assert unit_digest(git, rev, "openspec/changes/absent") == empty
    with pytest.raises(RevisionMissing):  # R3: never the empty set for a revision that is not there
        unit_digest(git, "0" * 40, OPENSPEC)


def test_a_folder_of_only_excluded_files_is_the_empty_set(tmp_path):
    repo, git = make_repo(tmp_path)
    write(repo, "openspec/changes/y/verification.md", "x\n")
    write(repo, "openspec/changes/y/.l4/ledger.jsonl", "x\n")
    assert unit_digest(git, commit(repo), "openspec/changes/y") == hashlib.sha256(b"").hexdigest()[:16]


def test_plan_digest_is_over_the_bytes():
    assert plan_digest('{"a": 1}') == hashlib.sha256(b'{"a": 1}').hexdigest()[:16]
    assert plan_digest('{"a": 1}') == plan_digest(b'{"a": 1}')
    assert plan_digest("x") != plan_digest("y")
