"""Scoring a data set with any System-One profile (M16-G13): `l4 s1 score`.

One request per row: every question of the row, and for each choice question the same question with the options in
the opposite order (id `<qid>__rev`), so a canonical and an averaged answer can both be reported (eval-framework 6.3).
The output is an `l4/s1-scores@1` file: a header and one line per row. It is read only by `report`; nothing in the
training path reads it. The Jev key and the Laya endpoint come from the profile, and are never written.
"""

import hashlib
import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l4.config.schema import L4Config
from l4.llm.s1_checkpoint import checkpoint_identity, is_checkpoint_path
from l4.llm.system_one import (
    Question,
    SystemOneBackend,
    SystemOneBadAnswer,
    SystemOneUnavailable,
    open_s1_profile,
    parse_typed,
)
from l4.redact import Redactor

SCORES_SCHEMA = "l4/s1-scores@1"
REV = "__rev"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(dataset: Path) -> dict[str, Any] | None:
    """The `manifest.json` beside `dataset`: None when there is none, `ValueError` when it is there but unreadable or
    not a manifest (a damaged manifest must not pass for an absent one: it would lift the gate order)."""
    path = dataset.with_name("manifest.json")
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(
            f"{path.name} beside {dataset.name} is unreadable or not JSON: export the data set again"
        ) from None
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise ValueError(f"{path.name} beside {dataset.name} is not an `l4 s1 export` manifest: export it again")
    return manifest


def exported_split(dataset: Path) -> str | None:
    """`calib` or `test` when `dataset` is that file of an `l4 s1 export` (its manifest.json lists it), else None."""
    manifest = read_manifest(dataset)
    files = manifest["files"] if manifest else {}
    return dataset.stem if dataset.name in files and dataset.stem in ("calib", "test") else None


def read_rows(dataset: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in dataset.read_text(encoding="utf-8").splitlines() if line.strip()]


def row_questions(row: Mapping[str, Any]) -> dict[str, Question]:
    """The row's questions, plus each choice question again with its options reversed under `<qid>__rev`."""
    out: dict[str, Question] = {}
    for qid, spec in row["questions"].items():
        out[qid] = Question(spec["type"], spec["instructions"], spec.get("criteria"))
        if spec["type"] == "choice" and isinstance(spec.get("criteria"), dict):
            out[qid + REV] = Question("choice", spec["instructions"], dict(reversed(list(spec["criteria"].items()))))
    return out


@dataclass
class ScoreSummary:
    asked: int = 0
    errors: int = 0
    skipped: int = 0  # rows not asked because of the request cap or a dead server


def score_dataset(
    backend: SystemOneBackend,
    rows: Sequence[Mapping[str, Any]],
    out: Path,
    *,
    profile: str,
    dataset_sha256: str,
    max_requests: int | None = None,
    identity: Mapping[str, Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> ScoreSummary:
    """The backend has to be started by the caller. Stops at `max_requests` and after the first transport error."""
    summary = ScoreSummary()
    out.parent.mkdir(parents=True, exist_ok=True)
    header = {"schema": SCORES_SCHEMA, "kind": "header", "profile": profile, "engine": backend.engine,
              "model": backend.model, "dataset_sha256": dataset_sha256, **(identity or {})}  # fmt: skip
    lines = [json.dumps(header)]
    down = False
    for index, row in enumerate(rows):
        if down or (max_requests is not None and summary.asked >= max_requests):
            summary.skipped += 1
            continue
        questions = row_questions(row)
        line: dict[str, Any] = {"schema": SCORES_SCHEMA, "kind": "row", "row": index,
                                "state_sha256": hashlib.sha256(row["state"].encode("utf-8")).hexdigest()}  # fmt: skip
        began = clock()
        summary.asked += 1
        try:
            reply = backend.query(row["state"], questions)
            answers = parse_typed(reply, questions)
            line.update(model=reply.model, answers={q: a.to_json() for q, a in answers.items()})
        except SystemOneBadAnswer as exc:
            line["error"], summary.errors = str(exc), summary.errors + 1
        except Exception as exc:  # noqa: BLE001 - a transport error of any type: record it and stop asking
            line["error"] = str(exc) if isinstance(exc, SystemOneUnavailable) else type(exc).__name__
            summary.errors, down = summary.errors + 1, True
        line["latency_ms"] = round((clock() - began) * 1000)
        lines.append(json.dumps(line, ensure_ascii=False))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def run_score(
    cfg: L4Config,
    profile: str,
    dataset: Path,
    out: Path,
    *,
    redactor: Redactor,
    environ: Mapping[str, str] | None = None,
    max_requests: int | None = None,
    opener: Callable[..., SystemOneBackend] = open_s1_profile,
) -> ScoreSummary:
    """The one place a checkpoint whose gate failed may be loaded: scoring it is how the report compares it."""
    rows = read_rows(dataset)
    backend = opener(cfg, profile, environ=environ, redactor=redactor, allow_failed_gate=True)
    model = cfg.profiles[profile].model
    identity = checkpoint_identity(model) if is_checkpoint_path(model) else None  # opener verified it is gated
    with backend:
        return score_dataset(
            backend, rows, out, profile=profile, dataset_sha256=file_sha256(dataset), max_requests=max_requests,
            identity=identity,
        )  # fmt: skip
