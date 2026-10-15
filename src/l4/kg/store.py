"""The index folder and its atomic write and read (L4-KG-002, L4-KG-003, L4-KG-011, design D2, SCN-KG-03, SCN-KG-05).

The index lives at `cache_root(environ, repo) / "kg" / <first 16 hex of sha256(resolved repository path)>`, in a
folder with mode 0700, and never inside the repository: `cache_root` refuses a root inside it with the L4-CFG-005
`L4Exit(USAGE_ERROR)`, and that passes through. Two repositories get two folders, and no function here takes another
repository's folder (L4-KG-011).

`write_index` writes `nodes.jsonl`, then `edges.jsonl`, then `manifest.json`, each through `atomic_write_bytes`. The
manifest (`l4/kg-manifest@1`) holds the harness version, the read refs with their shas (sorted), the counts, the skips
and the sha256 of the two data files, and the `inputs` (the config values and the forge hosts that decide what is read
and how it is scrubbed: a change makes the index stale, review #8); it holds no time, so the same refs, inputs and
harness version give the same bytes. A build that dies between the renames leaves a manifest whose hashes do not match
the files, so `read_index` says `incomplete` and never `ok` (a reader never takes a half-written index as complete).

`read_index(folder, current_refs)` returns one status: `missing` (nothing there), `incomplete` (a file is missing,
the manifest is unreadable or of another schema, a hash differs, or a line does not parse), `stale` (the refs the
build would read now differ from the manifest's: one moved, one is new or one is gone; or the harness version differs,
because only the same version promises the same bytes) or `ok` with the records loaded. The caller (`report`, `why`,
`propose`) rebuilds on anything but `ok`.
"""

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from l4 import __version__
from l4.config.defaults import cache_root
from l4.context import AppContext
from l4.fsutil import atomic_write_bytes
from l4.kg.model import Edge, Node, jsonl_bytes

MANIFEST_SCHEMA = "l4/kg-manifest@1"
NODES_FILE = "nodes.jsonl"
EDGES_FILE = "edges.jsonl"
MANIFEST_FILE = "manifest.json"
INDEX_MODE = 0o700

Status = Literal["ok", "missing", "incomplete", "stale"]


def repo_key(repo: Path) -> str:
    return hashlib.sha256(str(repo.resolve()).encode("utf-8")).hexdigest()[:16]


def index_dir(app: AppContext) -> Path:
    """The folder of this repository's index, created with mode 0700 (the parents get the default mode)."""
    kg_root = cache_root(app.environ, repo=app.repo) / "kg"
    kg_root.mkdir(parents=True, exist_ok=True)
    folder = kg_root / repo_key(app.repo)
    folder.mkdir(exist_ok=True)
    os.chmod(folder, INDEX_MODE)  # mkdir's mode is cut by the umask, and an older folder may be looser
    return folder


@dataclass(frozen=True)
class Manifest:
    harness_version: str
    refs: Mapping[str, str]
    counts: Mapping[str, Mapping[str, int]]
    skipped: Mapping[str, int]
    sha256: Mapping[str, str]
    inputs: Mapping[str, Any] = field(default_factory=dict)  # the config values that decide what is read and shown

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA, "harness_version": self.harness_version, "refs": dict(self.refs),
            "counts": {kind: dict(by_type) for kind, by_type in self.counts.items()}, "skipped": dict(self.skipped),
            "sha256": dict(self.sha256), "inputs": dict(self.inputs),
        }  # fmt: skip

    @classmethod
    def from_dict(cls, raw: Any) -> "Manifest":
        if not isinstance(raw, dict) or raw.get("schema") != MANIFEST_SCHEMA:
            raise ValueError("not an l4/kg-manifest@1 file")
        manifest = cls(
            harness_version=raw["harness_version"], refs=dict(raw["refs"]),
            counts={kind: dict(by_type) for kind, by_type in raw["counts"].items()}, skipped=dict(raw["skipped"]),
            sha256=dict(raw["sha256"]), inputs=dict(raw.get("inputs", {})),
        )  # fmt: skip
        if set(manifest.sha256) != {NODES_FILE, EDGES_FILE}:
            raise ValueError("the manifest does not hash exactly the two data files")
        return manifest


@dataclass(frozen=True)
class IndexState:
    status: Status
    manifest: Manifest | None = None
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    detail: str = ""


def _count_by_type(items: Iterable[Node | Edge]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.type] = counts.get(item.type, 0) + 1
    return dict(sorted(counts.items()))


def write_index(
    folder: Path,
    nodes: Iterable[Node],
    edges: Iterable[Edge],
    *,
    refs: Mapping[str, str],
    skipped: Mapping[str, int],
    inputs: Mapping[str, Any] | None = None,
    harness_version: str = __version__,
) -> Manifest:
    """Write the three files, the manifest last. Raises whatever the filesystem raises: the caller exits 1."""
    node_list, edge_list = list(nodes), list(edges)
    nodes_data, edges_data = jsonl_bytes(node_list), jsonl_bytes(edge_list)
    manifest = Manifest(
        harness_version=harness_version,
        refs=dict(sorted(refs.items())),
        counts={
            "edges": _count_by_type(set(edge_list)),
            "nodes": _count_by_type(set(node_list)),
        },
        skipped=dict(sorted((reason, n) for reason, n in skipped.items())),
        inputs=dict(sorted((inputs or {}).items())),
        sha256={
            EDGES_FILE: hashlib.sha256(edges_data).hexdigest(),
            NODES_FILE: hashlib.sha256(nodes_data).hexdigest(),
        },
    )
    folder.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(folder / NODES_FILE, nodes_data)
    atomic_write_bytes(folder / EDGES_FILE, edges_data)
    text = json.dumps(manifest.to_dict(), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    atomic_write_bytes(folder / MANIFEST_FILE, text.encode("utf-8"))
    return manifest


def _load_lines(data: bytes, parse: Any) -> list[Any]:
    return [parse(json.loads(line)) for line in data.decode("utf-8").split("\n") if line]


def read_index(
    folder: Path, current_refs: Mapping[str, str], current_inputs: Mapping[str, Any] | None = None
) -> IndexState:
    """The state of the index in `folder` against the refs a build would read now and, when given, the config values
    it would read them with (`stale` when either differs)."""
    manifest_path = folder / MANIFEST_FILE
    data_paths = (folder / NODES_FILE, folder / EDGES_FILE)
    if not manifest_path.is_file():
        present = any(path.exists() for path in data_paths)
        return IndexState("incomplete", detail="data files without a manifest") if present else IndexState("missing")
    try:
        manifest = Manifest.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
        nodes_data, edges_data = (path.read_bytes() for path in data_paths)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return IndexState("incomplete", detail=f"{type(exc).__name__}: {exc}")
    if (
        hashlib.sha256(nodes_data).hexdigest() != manifest.sha256[NODES_FILE]
        or hashlib.sha256(edges_data).hexdigest() != manifest.sha256[EDGES_FILE]
    ):
        return IndexState("incomplete", manifest, detail="a data file does not match its sha256")
    if manifest.harness_version != __version__ or dict(manifest.refs) != dict(current_refs):
        return IndexState("stale", manifest)
    if current_inputs is not None and dict(manifest.inputs) != dict(current_inputs):
        return IndexState("stale", manifest, detail="the config values that decide what is read changed")
    try:
        nodes = _load_lines(nodes_data, Node.from_dict)
        edges = _load_lines(edges_data, Edge.from_dict)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return IndexState("incomplete", manifest, detail=f"a record does not parse: {type(exc).__name__}: {exc}")
    return IndexState("ok", manifest, nodes, edges)
