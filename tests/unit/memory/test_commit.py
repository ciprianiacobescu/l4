from datetime import date
from pathlib import Path

import pytest

from l4.config.schema import MemoryCfg
from l4.memory.commit import commit_memory_change
from l4.memory.curate import LessonCandidate, apply_candidates

LESSONS = ".serena/memories/harness/lessons.md"


def cand(key: str) -> LessonCandidate:
    return LessonCandidate(key, key, (), (), "src", "body", "verifier_finding_fixed")


def test_memory_change_is_own_commit_and_noop_when_unchanged(make_repo, git_for, raw):
    repo = make_repo()
    git = git_for(repo)
    paths = apply_candidates(repo, MemoryCfg(), [cand("one")], today=date(2026, 10, 4)).paths
    sha = commit_memory_change(git, paths, unit="openspec:x", run_id="r-20261004T1000Z-abcd", iteration=2,
                               detail="lesson L-1 created")  # fmt: skip
    assert sha is not None and raw(repo, "rev-parse", "HEAD").strip() == sha
    message = raw(repo, "log", "-1", "--format=%B").strip()
    assert message.startswith("chore(memory): lesson L-1 created [skip ci]")
    assert "L4-Phase: lessons" in message and "L4-Unit: openspec:x" in message and "Co-Authored" not in message
    assert raw(repo, "show", "--name-only", "--format=", "HEAD").split() == [LESSONS]
    # the same bytes again: nothing to commit
    again = commit_memory_change(git, [LESSONS], unit="openspec:x", run_id="r-20261004T1000Z-abcd", iteration=2,
                                 detail="nothing")  # fmt: skip
    assert again is None and raw(repo, "rev-parse", "HEAD").strip() == sha


def test_other_staged_work_is_never_swept_into_the_memory_commit(make_repo, git_for, raw):
    repo = make_repo()
    git = git_for(repo)
    (repo / "other.txt").write_text("x\n")
    raw(repo, "add", "other.txt")
    paths = apply_candidates(repo, MemoryCfg(), [cand("one")], today=date(2026, 10, 4)).paths
    with pytest.raises(ValueError, match="other.txt"):
        commit_memory_change(git, paths, unit="u", run_id="r-20261004T1000Z-abcd", iteration=1, detail="d")
    assert (Path(repo) / "other.txt").exists()
