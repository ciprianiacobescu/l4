"""sandbox-security-1 (L4-SEC-034), the unpublished run files: another project's file is never published into this
project's lock ref, and a file of the earlier layout is adopted only by the repository whose commits it names."""

import json
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace

from l4.state.pending import adopt_legacy, keep_unpublished, unpublished_files
from l4.vcs.git import Git
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


def _repo(tmp_path: Path) -> tuple[Git, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    for args in (
        ["init", "-q", "-b", "main"],
        ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)
    git = Git(repo, environ=env)
    return git, git.run("rev-parse", "HEAD").stdout.strip()


def _run_file(directory: Path, run_id: str, base: str) -> Path:
    path = directory / f"{run_id}.jsonl"
    line = {"ts": "2026-10-17T12:00:00Z", "run_id": run_id, "unit": UNIT, "seq": 1, "type": "run.started", "base": base}
    path.write_text(json.dumps(line) + "\n")
    return path


def test_a_legacy_run_file_is_adopted_only_by_its_repository(tmp_path: Path, caplog):  # SCN-SEC-84
    git, head = _repo(tmp_path)
    legacy = tmp_path / "cache" / "pending-unpublished" / "openspec" / "add-login"
    legacy.mkdir(parents=True)
    mine = _run_file(legacy, "r-20261017T1200Z-aaaa", head)
    other = _run_file(legacy, "r-20261017T1201Z-bbbb", "0123456789abcdef0123456789abcdef01234567")
    keyed = tmp_path / "cache" / "pending-unpublished" / "proj-0123456789" / "openspec" / "add-login"
    with caplog.at_level(logging.WARNING, logger="l4.pending"):
        moved = adopt_legacy(legacy, keyed, git)
    assert [p.name for p in moved] == [mine.name]
    assert (keyed / mine.name).is_file() and not mine.exists()
    assert other.is_file() and not (keyed / other.name).exists()
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and str(legacy) in warnings[0] and warnings[0].startswith("1 ")
    assert "0123456789abcdef" not in warnings[0]
