"""A merged unit's history ends with an archive commit (`L4-Phase: archived`) that moves the change directory under
`openspec/changes/archive/`. The unit's head is the commit before it: the scope is read at the base, where the archive
path does not exist, so a head on the archive commit gave every file no label and the unit no items (live, 9 merged
units of a real repository, all `baseline_failed`)."""

from pathlib import Path

from l4.s1 import canary as c
from l4.vcs.trailers import CommitTrailers

from ..evidence._multi import RUN_ID, build_repo


def test_the_head_of_an_archived_unit_is_the_commit_before_its_archive_commit(tmp_path: Path):
    git, units = build_repo(tmp_path / "repo", units=1)
    [unit] = units
    archive = tmp_path / "repo" / "openspec" / "changes" / "archive" / f"2026-10-04-{unit.name}"
    archive.parent.mkdir(parents=True)
    git.run("mv", unit.spec_dir, str(archive.relative_to(tmp_path / "repo")))
    git.commit(f"archive {unit.name}", CommitTrailers(unit.id, RUN_ID, 2, "archived"))
    [found] = c.find_source_units(git)
    assert found.head == unit.head and found.base == unit.base
    assert found.spec_dir == unit.spec_dir
