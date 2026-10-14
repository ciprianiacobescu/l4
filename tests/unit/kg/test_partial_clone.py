"""A partial clone never makes `l4 kg` fetch (review #1; L4-KG-001, L4-KG-004, SCN-KG-02).

In a `--filter=blob:none` clone git fetches a missing blob from the remote by itself when `cat-file` asks for it. The
graph runs git with `GIT_NO_LAZY_FETCH=1`, skips what it cannot read and says why (`partial_clone`).
"""

import dataclasses
import json
import socket
from pathlib import Path

import pytest

from l4.cli import main
from l4.kg import cli as kg_cli
from l4.kg.store import MANIFEST_FILE, index_dir


@pytest.fixture
def partial(kg_repo):
    kg_repo.unit(
        "openspec:a", where="archive",
        runs=[kg_repo.run(("task.attempt_failed", {"task": "1.1", "phase": "red", "attempt": 1, "reason": "x: y"}))],
        verdicts=[kg_repo.verdict(1, "FAIL", findings=[kg_repo.finding("lint is red")])],
    )  # fmt: skip
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(("task.red_ok", {"task": "1.1"}))])
    return kg_repo, kg_repo.partial_clone()


def object_counts(repo, clone: Path) -> str:
    return repo._raw(clone, "count-objects", "-v")


def test_the_fixture_is_a_partial_clone(partial):
    repo, clone = partial
    assert repo._raw(clone, "config", "--get", "remote.origin.promisor").strip() == "true"


@pytest.mark.parametrize(
    ("args", "expected"),
    [(("build",), 0), (("report",), 0), (("why", "openspec:a"), 2), (("propose", "--dry-run"), 0)],
)  # `why` exits 2: the unit's blobs are promised, so the unit is skipped and the index does not hold it
def test_no_command_fetches_in_a_partial_clone(partial, monkeypatch, args, expected, capsys):
    """SCN-KG-02 on a partial clone: the production git environment, a trace of every git process, no socket."""
    repo, clone = partial
    trace = repo.tmp / "trace.txt"
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    recording = []

    def make(path, environ=None):
        git = repo.recording_git().at(path)
        git.env.update({k: v for k, v in dict(environ or {}).items() if k.startswith(("GIT_NO_", "GIT_TRACE"))})
        recording.append(git)
        return git

    monkeypatch.setattr(kg_cli, "Git", make)
    before = object_counts(repo, clone)
    environ = {**repo.environ, "L4_CACHE": str(repo.cache), "GIT_TRACE": str(trace)}
    code = main(["kg", *args, "--repo", str(clone)], environ=environ)
    assert code == expected
    assert recording and "fetch" not in recording[0].subcommands
    lines = trace.read_text().splitlines() if trace.exists() else []
    assert [line for line in lines if " fetch " in line] == []
    assert object_counts(repo, clone) == before


def test_the_graph_runs_git_with_lazy_fetch_off(partial):
    repo, _ = partial
    assert kg_cli._git(repo.app()).env["GIT_NO_LAZY_FETCH"] == "1"


def test_missing_blobs_are_skipped_with_the_cause_and_one_warning(partial, capsys):
    repo, clone = partial
    environ = {**repo.environ, "L4_CACHE": str(repo.cache)}
    assert main(["kg", "build", "--repo", str(clone)], environ=environ) == 0
    out = capsys.readouterr()
    text = out.out + out.err
    assert "skipped: partial_clone" in text
    assert text.count("partial clone") == 1  # one warning, not one per blob
    app = dataclasses.replace(repo.app(), repo=clone)
    manifest = json.loads((index_dir(app) / MANIFEST_FILE).read_text())
    assert manifest["skipped"].get("partial_clone", 0) >= 1
    assert "error" not in manifest["skipped"]
