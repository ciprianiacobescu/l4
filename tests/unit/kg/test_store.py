"""The index folder and its atomic read and write (L4-KG-002, L4-KG-003, L4-KG-011; SCN-KG-03, SCN-KG-05, SCN-KG-23)."""

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from l4 import __version__
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.kg import store
from l4.kg.model import Edge, Node
from l4.redact import Redactor

REFS = {"refs/remotes/origin/amaster": "a" * 40, "refs/remotes/origin/l4/openspec/a": "b" * 40}
NODES = [Node("openspec:a", "unit", {"name": "a"}), Node("L-09421538", "lesson"), Node("openspec:b", "unit")]
EDGES = [
    Edge("INJECTED", "r-1", "L-09421538", "aaaaaaaaaa:.l4/ledger/r-1.jsonl#2", "2026-10-05T08:16:00Z", {"task": "1.1"})
]


def make_app(repo: Path, cache: Path) -> AppContext:
    repo.mkdir(parents=True, exist_ok=True)
    return AppContext(
        repo=repo, config_path=None, log_format="human", verbosity=0, run_id="r-20261004T1000Z-0001",
        environ={"PATH": "/usr/bin", "L4_CACHE": str(cache)}, redactor=Redactor({}),
    )  # fmt: skip


def test_index_dir_is_under_the_cache_root_keyed_by_the_resolved_repository(tmp_path):
    app = make_app(tmp_path / "repo", tmp_path / "cache")
    folder = store.index_dir(app)
    key = hashlib.sha256(str((tmp_path / "repo").resolve()).encode()).hexdigest()[:16]
    assert folder == tmp_path / "cache" / "kg" / key and folder.is_dir()
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert store.index_dir(app) == folder  # a second call finds it


def test_index_dir_keeps_mode_0700_under_a_loose_umask(tmp_path):
    old = os.umask(0o000)
    try:
        folder = store.index_dir(make_app(tmp_path / "repo", tmp_path / "cache"))
    finally:
        os.umask(old)
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_two_repositories_get_two_folders_under_one_cache_root(tmp_path):
    a = store.index_dir(make_app(tmp_path / "a", tmp_path / "cache"))
    b = store.index_dir(make_app(tmp_path / "b", tmp_path / "cache"))
    assert a != b and a.parent == b.parent == tmp_path / "cache" / "kg"


def test_a_symlinked_repository_path_gives_the_folder_of_its_target(tmp_path):
    real = make_app(tmp_path / "real", tmp_path / "cache")
    (tmp_path / "link").symlink_to(tmp_path / "real")
    via = make_app(tmp_path / "link", tmp_path / "cache")
    assert store.index_dir(via) == store.index_dir(real)


def test_a_cache_root_inside_the_repository_is_refused_and_nothing_is_written(tmp_path):
    repo = tmp_path / "repo"
    app = make_app(repo, repo / ".cache")
    with pytest.raises(L4Exit) as err:
        store.index_dir(app)
    assert err.value.code == ExitCode.USAGE_ERROR and "outside the repository" in str(err.value)
    assert not (repo / ".cache").exists()


def test_write_then_read_gives_the_same_records(tmp_path):
    folder = store.index_dir(make_app(tmp_path / "repo", tmp_path / "cache"))
    manifest = store.write_index(folder, NODES, EDGES, refs=REFS, skipped={"ledger_corrupt": 1})
    state = store.read_index(folder, REFS)
    assert state.status == "ok" and state.manifest == manifest
    assert sorted(state.nodes, key=lambda n: n.id) == sorted(NODES, key=lambda n: n.id)
    assert state.edges == EDGES
    assert manifest.counts == {"edges": {"INJECTED": 1}, "nodes": {"lesson": 1, "unit": 2}}
    assert manifest.skipped == {"ledger_corrupt": 1} and manifest.harness_version == __version__


def test_the_manifest_has_the_schema_the_refs_the_counts_and_the_hashes_and_no_time(tmp_path):
    folder = store.index_dir(make_app(tmp_path / "repo", tmp_path / "cache"))
    store.write_index(folder, NODES, EDGES, refs=REFS, skipped={})
    raw = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert raw["schema"] == "l4/kg-manifest@1" and raw["harness_version"] == __version__
    assert raw["refs"] == REFS and list(raw["refs"]) == sorted(raw["refs"])
    assert raw["sha256"] == {
        "edges.jsonl": hashlib.sha256((folder / "edges.jsonl").read_bytes()).hexdigest(),
        "nodes.jsonl": hashlib.sha256((folder / "nodes.jsonl").read_bytes()).hexdigest(),
    }
    assert set(raw) == {"schema", "harness_version", "refs", "counts", "skipped", "sha256", "inputs"}


def test_a_rebuild_after_deleting_the_folder_is_byte_identical(tmp_path):
    folder = store.index_dir(make_app(tmp_path / "repo", tmp_path / "cache"))
    store.write_index(folder, NODES, EDGES, refs=REFS, skipped={})
    first = {p.name: p.read_bytes() for p in folder.iterdir()}
    assert set(first) == {"nodes.jsonl", "edges.jsonl", "manifest.json"}
    for p in folder.iterdir():
        p.unlink()
    store.write_index(folder, list(reversed(NODES)), EDGES, refs=dict(reversed(REFS.items())), skipped={})
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == first


def test_an_empty_folder_is_missing(tmp_path):
    state = store.read_index(tmp_path / "nowhere", REFS)
    assert state.status == "missing" and state.manifest is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert store.read_index(empty, REFS).status == "missing"


def test_a_moved_ref_a_new_ref_or_a_gone_ref_is_stale(tmp_path):
    folder = tmp_path / "idx"
    store.write_index(folder, NODES, EDGES, refs=REFS, skipped={})
    assert store.read_index(folder, REFS).status == "ok"
    moved = {**REFS, "refs/remotes/origin/amaster": "c" * 40}
    assert store.read_index(folder, moved).status == "stale"
    assert store.read_index(folder, {**REFS, "refs/l4/locks/openspec/a": "d" * 40}).status == "stale"
    assert store.read_index(folder, {"refs/remotes/origin/amaster": "a" * 40}).status == "stale"


def test_an_index_of_another_harness_version_is_stale(tmp_path):
    folder = tmp_path / "idx"
    store.write_index(folder, NODES, EDGES, refs=REFS, skipped={}, harness_version="0.0.1")
    assert store.read_index(folder, REFS).status == "stale"


def test_a_data_file_that_changed_is_incomplete(tmp_path):
    folder = tmp_path / "idx"
    store.write_index(folder, NODES, EDGES, refs=REFS, skipped={})
    (folder / "edges.jsonl").write_bytes(b"")
    assert store.read_index(folder, REFS).status == "incomplete"


@pytest.mark.parametrize("victim", ["nodes.jsonl", "edges.jsonl", "manifest.json"])
def test_a_missing_file_or_a_broken_manifest_is_incomplete(tmp_path, victim):
    folder = tmp_path / "idx"
    store.write_index(folder, NODES, EDGES, refs=REFS, skipped={})
    (folder / victim).unlink()
    assert store.read_index(folder, REFS).status == "incomplete"
    store.write_index(folder, NODES, EDGES, refs=REFS, skipped={})
    (folder / "manifest.json").write_text("{not json", encoding="utf-8")
    assert store.read_index(folder, REFS).status == "incomplete"


def test_a_manifest_of_another_schema_is_incomplete(tmp_path):
    folder = tmp_path / "idx"
    store.write_index(folder, NODES, EDGES, refs=REFS, skipped={})
    raw = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    raw["schema"] = "l4/kg-manifest@2"
    (folder / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    assert store.read_index(folder, REFS).status == "incomplete"


def test_a_data_line_that_does_not_parse_is_incomplete_not_an_exception(tmp_path):
    folder = tmp_path / "idx"
    store.write_index(folder, NODES, EDGES, refs=REFS, skipped={})
    bad = b'{"type":"unit"}\n'
    (folder / "nodes.jsonl").write_bytes(bad)
    raw = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    raw["sha256"]["nodes.jsonl"] = hashlib.sha256(bad).hexdigest()
    (folder / "manifest.json").write_text(json.dumps(raw), encoding="utf-8")
    assert store.read_index(folder, REFS).status == "incomplete"


def test_a_fault_between_the_renames_leaves_an_index_no_reader_takes_as_complete(tmp_path, monkeypatch):
    """SCN-KG-03: the old build is complete; a new build dies after `nodes.jsonl` was renamed."""
    folder = tmp_path / "idx"
    old_refs = {"refs/remotes/origin/amaster": "1" * 40}
    store.write_index(folder, NODES[:1], [], refs=old_refs, skipped={})
    assert store.read_index(folder, old_refs).status == "ok"

    real = store.atomic_write_bytes
    calls: list[str] = []

    def failing(path, data):
        calls.append(Path(path).name)
        if len(calls) == 2:
            raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(store, "atomic_write_bytes", failing)
    with pytest.raises(OSError, match="disk full"):
        store.write_index(folder, NODES, EDGES, refs=REFS, skipped={})
    assert calls[:2] == ["nodes.jsonl", "edges.jsonl"]
    # nodes.jsonl is the new one, edges.jsonl and manifest.json are the old ones: neither refs match nor hashes
    assert store.read_index(folder, old_refs).status == "incomplete"
    assert store.read_index(folder, REFS).status == "incomplete"
    monkeypatch.setattr(store, "atomic_write_bytes", real)
    store.write_index(folder, NODES, EDGES, refs=REFS, skipped={})
    assert store.read_index(folder, REFS).status == "ok"


def test_the_manifest_is_written_last(tmp_path, monkeypatch):
    order: list[str] = []
    real = store.atomic_write_bytes
    monkeypatch.setattr(store, "atomic_write_bytes", lambda p, d: (order.append(Path(p).name), real(p, d)))
    store.write_index(tmp_path / "idx", NODES, EDGES, refs=REFS, skipped={})
    assert order[-1] == "manifest.json" and set(order) == {"nodes.jsonl", "edges.jsonl", "manifest.json"}


def test_an_input_that_differs_makes_the_index_stale(tmp_path):
    """Review #8: the config values that decide what is read are in the manifest."""
    refs = {"refs/remotes/origin/main": "a" * 40}
    manifest = store.write_index(
        tmp_path, [], [], refs=refs, skipped={}, inputs={"memory.lessons_file": ".serena/memories/harness/lessons.md"}
    )
    assert manifest.inputs == {"memory.lessons_file": ".serena/memories/harness/lessons.md"}
    assert store.read_index(tmp_path, refs, dict(manifest.inputs)).status == "ok"
    assert store.read_index(tmp_path, refs, {"memory.lessons_file": "docs/lessons.md"}).status == "stale"
    assert store.read_index(tmp_path, refs).status == "ok"  # no inputs asked: refs only
