from pathlib import Path

import pytest

from l4.vcs.names import UnitNames


def test_names_for_openspec_unit(tmp_path: Path):
    names = UnitNames.for_unit("openspec:add-login", branch_prefix="l4/", cache=tmp_path / "c")
    assert names.unit_id == "openspec:add-login"
    assert names.branch == "l4/openspec/add-login"
    assert names.wip_branch == "l4-wip/openspec/add-login"
    assert names.lock_ref == "refs/l4/locks/openspec/add-login"
    assert names.lock_branch == "l4-lock/openspec/add-login"
    assert names.worktree == tmp_path / "c" / "worktrees" / "openspec" / "add-login"
    assert names.flock_path == tmp_path / "c" / "locks" / "openspec" / "add-login.lock"


@pytest.mark.parametrize("unit", ["add-login", "openspec:", "openspec:../x", "openspec:a/b", "git:x", "openspec:-x"])
def test_bad_unit_ids_are_refused(unit, tmp_path: Path):
    with pytest.raises(ValueError):
        UnitNames.for_unit(unit, branch_prefix="l4/", cache=tmp_path)


@pytest.mark.parametrize("prefix", ["-l4/", "l4//", "/l4/", "l4/../", "l4 x/", "l4/.lock/"])
def test_bad_branch_prefixes_are_refused(prefix, tmp_path: Path):
    with pytest.raises(ValueError, match="branch"):
        UnitNames.for_unit("openspec:x", branch_prefix=prefix, cache=tmp_path)
