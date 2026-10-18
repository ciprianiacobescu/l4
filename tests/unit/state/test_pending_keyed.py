"""sandbox-security-1 (L4-SEC-034), the unpublished run files: another project's file is never published into this
project's lock ref, and a file of the earlier layout is adopted only by the repository whose commits it names."""

import json
import logging
from pathlib import Path
from types import SimpleNamespace

from l4.state.pending import adopt_legacy, keep_unpublished, unpublished_files
from l4.vcs.names import UnitNames

UNIT = "openspec:add-login"


def _names(cache: Path, key: str) -> UnitNames:
    return UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=cache, repo_key=key)


def test_another_projects_unpublished_file_is_not_published(tmp_path: Path):  # SCN-SEC-83
    cache = tmp_path / "cache"
    a, b = _names(cache, "proja-0123456789"), _names(cache, "projb-0123456789")
    run_file = tmp_path / "r-20261017T1200Z-aaaa.jsonl"
    run_file.write_text('{"type":"run.started","unit":"openspec:add-login"}\n')
    keep_unpublished(a.unpublished_dir, run_file)
    assert unpublished_files(b.unpublished_dir) == {}
    assert list(unpublished_files(a.unpublished_dir)) == ["r-20261017T1200Z-aaaa"]

    from l4.orchestrator import Orchestrator

    seen = Orchestrator._unpublished(SimpleNamespace(services=SimpleNamespace(names=b)))  # type: ignore[arg-type]
    assert seen == {}
    seen = Orchestrator._unpublished(SimpleNamespace(services=SimpleNamespace(names=a)))  # type: ignore[arg-type]
    assert list(seen) == ["r-20261017T1200Z-aaaa"]


def _run_file(directory: Path, run_id: str, **fields: object) -> Path:
    path = directory / f"{run_id}.jsonl"
    path.write_text(json.dumps({"type": "run.started", "run_id": run_id, "seq": 1, **fields}) + "\n")
    return path


def test_a_legacy_run_file_is_adopted_only_by_its_repository(tmp_path: Path, caplog):  # SCN-SEC-84
    """Changed with L4-SEC-034 (review F3): the file's recorded repository key decides, not the commits it names."""
    legacy = tmp_path / "cache" / "pending-unpublished" / "openspec" / "add-login"
    legacy.mkdir(parents=True)
    mine = _run_file(legacy, "r-20261017T1200Z-aaaa", repository_key="proj-0123456789", base="a" * 40)
    other = _run_file(legacy, "r-20261017T1201Z-bbbb", repository_key="other-9999999999", base="a" * 40)
    keyed = tmp_path / "cache" / "pending-unpublished" / "proj-0123456789" / "openspec" / "add-login"
    with caplog.at_level(logging.WARNING, logger="l4.pending"):
        moved = adopt_legacy(legacy, keyed, repo_key="proj-0123456789", repo_path=None)
    assert [p.name for p in moved] == [mine.name]
    assert (keyed / mine.name).is_file() and not mine.exists()
    assert other.is_file() and not (keyed / other.name).exists()
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and str(legacy) in warnings[0] and warnings[0].startswith("1 ")
    assert "a" * 40 not in warnings[0]
