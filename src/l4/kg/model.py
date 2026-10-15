"""Nodes, edges and the canonical JSONL form of the experience graph (L4-KG-003, L4-KG-005, design D4, SCN-KG-04).

A `Node` has an id, a type of design D4 and a small `attrs` mapping. An `Edge` has a type, the ids of both ends, `src`
(the committed place that states it: `<sha10>:<path>#<seq>` for a ledger event, `<sha10>:<path>#/<json pointer>` for a
`verdict.json` field, L4-KG-005) and `ts` (the time the record itself carries, never the build time, L4-KG-003). Both
are frozen and compare by value. `attrs` may hold lists and mappings, so the hash is taken from the canonical text.

The writer is canonical: sorted keys, no spaces, no ASCII escapes, one record per line, the lines sorted, LF, UTF-8.
A record that appears twice is one line (the file is a set), so the bytes depend on the set and not on the order a
build met it. NaN and infinity are refused, because JSON cannot hold them.
"""

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

NODE_TYPES = frozenset(
    {
        "unit", "attempt", "run", "round", "finding", "criterion", "capability", "lesson", "question", "stop",
        "profile", "failure_class", "recurrence_key", "gate", "blame",
    }
)  # fmt: skip
EDGE_TYPES = frozenset(
    {
        "HAS_ATTEMPT", "HAS_RUN", "HAS_ROUND", "VERDICT", "RAISED", "ABOUT", "IN_CAPABILITY", "KEYED", "GATE_FAILED",
        "INJECTED", "ATTEMPT_FAILED", "USED_PROFILE", "ASKED", "STOPPED", "RETRIED", "RESTARTED", "CLASSIFIED",
    }
)  # fmt: skip


def canonical_json(value: Any) -> str:
    """One JSON text with sorted keys, no spaces and no ASCII escapes: the same value always gives the same text."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Node:
    id: str
    type: str
    attrs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in NODE_TYPES:
            raise ValueError(f"unknown node type {self.type!r}")

    def __hash__(self) -> int:
        return hash(canonical_json(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {"attrs": dict(self.attrs), "id": self.id, "type": self.type}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Node":
        return cls(id=raw["id"], type=raw["type"], attrs=dict(raw.get("attrs") or {}))


@dataclass(frozen=True)
class Edge:
    type: str
    from_id: str
    to_id: str
    src: str
    ts: str
    attrs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in EDGE_TYPES:
            raise ValueError(f"unknown edge type {self.type!r}")

    def __hash__(self) -> int:
        return hash(canonical_json(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attrs": dict(self.attrs), "from": self.from_id, "src": self.src, "to": self.to_id, "ts": self.ts,
            "type": self.type,
        }  # fmt: skip

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Edge":
        return cls(
            type=raw["type"], from_id=raw["from"], to_id=raw["to"], src=raw["src"], ts=raw["ts"],
            attrs=dict(raw.get("attrs") or {}),
        )  # fmt: skip


def jsonl_bytes(items: Iterable[Node | Edge]) -> bytes:
    """The canonical file for a set of records: deduplicated, sorted lines, each ending in LF; empty for none."""
    lines = sorted({canonical_json(item.to_dict()) for item in items})
    return "".join(line + "\n" for line in lines).encode("utf-8")
