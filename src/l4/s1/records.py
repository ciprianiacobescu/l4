"""The records of `l4/s1-calibration@2` (M16-G9, plan D1): three kinds, one JSON object per line.

* `item`: the redacted state as sent, the question set and the expected labels with their label source;
* `answer`: what one engine said about one item (never read by the export);
* `label`: a later human label for an item.

m15's v1 lines (`record_calibration`, no `kind`) stay valid in the same files and are skipped, and counted, by every
reader here: they hold no state text, so they cannot be exported.
"""

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Literal

SCHEMA = "l4/s1-calibration@2"
Kind = Literal["item", "answer", "label"]
Origin = Literal["live", "canary"]


def unit_hash(project: str, unit: str) -> str:
    """The split key (D8): a canary item carries its source unit's hash."""
    return hashlib.sha256(f"{project}\0{unit}".encode()).hexdigest()


def item_key(project: str, unit: str, question_set: str, subject: str, state_sha256: str) -> str:
    """Stable per (project, unit, set, subject, state): the same item seen in two rounds is one item."""
    blob = "\0".join((project, unit, question_set, subject, state_sha256))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class ItemRecord:
    kind: ClassVar[Kind] = "item"
    item_key: str
    unit: str
    unit_hash: str
    project: str
    run_id: str
    round: int
    origin: Origin
    subject: str  # a path, `path::qualname`, `tests` or a criterion id
    state: str
    state_sha256: str
    question_set: str
    question_sha256: str
    expected: dict[str, Any]
    label_source: str | None  # `deterministic:<check>` or `human:<event>`; None when nothing labels the item
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AnswerRecord:
    kind: ClassVar[Kind] = "answer"
    item_key: str
    engine: str
    profile: str
    model: str
    answers: dict[str, dict[str, Any]]
    latency_ms: int
    error: str | None = None


@dataclass(frozen=True)
class LabelRecord:
    kind: ClassVar[Kind] = "label"
    item_key: str
    truth: dict[str, Any]  # the `expected_for` input of the item's set
    label: str  # the label's name for a reader of the file, for example `out_of_scope`
    source: str
    by: str
    ts: str


Record = ItemRecord | AnswerRecord | LabelRecord
_CLASSES: dict[str, type[Record]] = {"item": ItemRecord, "answer": AnswerRecord, "label": LabelRecord}


def to_line(record: Record) -> str:
    return json.dumps({"schema": SCHEMA, "kind": record.kind, **asdict(record)}, ensure_ascii=False)


def append_records(paths: Iterable[Path], records: Sequence[Record]) -> None:
    if not records:
        return
    text = "\n".join(to_line(r) for r in records) + "\n"
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)


def read_records(
    path: Path, kinds: Sequence[Kind] = ("item", "answer", "label"), stats: Counter[str] | None = None
) -> list[Record]:
    """The records of the wanted kinds. A line of another kind is not parsed into a record (an `answer` is never
    built when only `item` and `label` are wanted); v1 lines and unreadable lines are counted in `stats`."""
    out: list[Record] = []
    stats = stats if stats is not None else Counter()
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError:
            stats["unreadable"] += 1
            continue
        kind = data.get("kind") if isinstance(data, dict) else None
        if kind is None and isinstance(data, dict):
            stats["legacy_v1"] += 1
            continue
        if kind not in _CLASSES or data.get("schema") != SCHEMA:
            stats["unknown_kind"] += 1
            continue
        if kind not in kinds:
            continue
        cls = _CLASSES[kind]
        fields = {k: v for k, v in data.items() if k not in ("schema", "kind")}
        try:
            out.append(cls(**fields))
        except TypeError:
            stats["unreadable"] += 1
    return out
