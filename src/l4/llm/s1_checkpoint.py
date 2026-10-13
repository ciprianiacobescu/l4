"""A tuned Laya checkpoint as a System-One profile (M16-G20, plan D10).

`profiles.<p>.model` may be an absolute path under `$L4_CACHE/s1/checkpoints/<id>/`. It is usable only when its
`l4-train.json` says the gate ran and passed, every file under the directory is recorded there with the sha256 it
still has (a file added or swapped after the gate is refused), and only safetensors are present (a pickle in the
directory is refused, nothing is unpickled). The gate flag is bound to the gate document: `l4-train.json` stores the
sha256 of the `gate.json` that sits in the directory, and the flag must equal that document's `passed` (a boolean
flipped by hand is refused). `l4 s1 score` alone may load a checkpoint whose gate ran and failed
(`require_passed=False`): comparing a failed gate's checkpoint with Jev is the point of the report.

Probe T1 (docs/runner/probe-t1-*.txt): `laya-serve` takes registry names in `LAYA_MODELS`, never a path, so the
checkpoint is served as `typed-decisions` out of a private Hugging Face home that links to the directory.
"""

import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from l4.availability.errors import RoleUnavailable
from l4.config.defaults import cache_root
from l4.exitcodes import ExitCode

BUNDLE_DIR = "models--convaiinnovations--laya"
PICKLE_SUFFIXES = (".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt")
RECORD_NAME = "l4-train.json"
GATE_NAME = "gate.json"  # a copy of the gate document, bound to the record by its sha256
REQUIRED_FILES = ("model.safetensors", "rl_agent_config.json")
GATE_NOT_PASSED = "the checkpoint has not passed the laya-evals gate"
GATE_NOT_RUN = "the checkpoint has not been through the laya-evals gate"
GATE_PROBLEMS = (GATE_NOT_PASSED, GATE_NOT_RUN)


class CheckpointGateFailed(RoleUnavailable):
    """A checkpoint whose gate failed or never ran. Still a `RoleUnavailable`, so that the optional S1 roles and the
    shadow degrade as before, but it exits 2 when nothing catches it: waiting (exit 12) would be retried and the
    answer would not change."""

    def __init__(self, role: str, reason: str) -> None:
        super().__init__(role, reason)
        self.code = ExitCode.USAGE_ERROR


def is_checkpoint_path(model: str | None) -> bool:
    return bool(model) and Path(model).is_absolute()  # type: ignore[arg-type]


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:  # chunked: the weights are hundreds of megabytes
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _record(model: str) -> dict[str, Any]:
    return json.loads((Path(model) / RECORD_NAME).read_text(encoding="utf-8"))


def checkpoint_identity(model: str) -> dict[str, Any]:
    """Who a gated checkpoint is, from its `l4-train.json` (`checkpoint_problem` has verified the files against it):
    written into score headers so that a tuned engine's answers can never pass for base Laya's."""
    record = _record(model)
    return {
        "checkpoint_id": Path(model).name,
        "checkpoint_sha256": record["files"]["model.safetensors"],
        "checkpoint_dataset_sha256": record.get("dataset_sha256") or "",
        "gate_passed": (record.get("gate") or {}).get("passed") is True,
    }


def _gate_problem(path: Path, record: Mapping[str, Any]) -> str:
    """The recorded gate flag against the gate document it names: "" when they agree and the document is this
    checkpoint's. The flag alone is a boolean anyone could flip."""
    gate = record.get("gate") or {}
    want = gate.get("document_sha256")
    target = path / GATE_NAME
    if not want:
        return f"l4-train.json records no sha256 for {GATE_NAME}: gate the checkpoint again"
    if target.is_symlink() or not target.is_file() or _sha256(target) != want:
        return f"{GATE_NAME} does not match the sha256 in l4-train.json"
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f"{GATE_NAME} is unreadable"
    if not isinstance(document, dict) or not isinstance(document.get("passed"), bool):
        return f"{GATE_NAME} is not a gate document"
    if document["passed"] is not gate.get("passed"):
        return f"the gate result in l4-train.json differs from {GATE_NAME}"
    if document.get("checkpoint_sha256") != (record.get("files") or {}).get("model.safetensors"):
        return f"{GATE_NAME} gated another checkpoint"
    return ""


def checkpoint_problem(model: str, environ: Mapping[str, str], *, require_passed: bool = True) -> str:
    """Why the directory cannot be served, or "" when it is gated and intact. `require_passed=False` accepts a gate
    that ran and failed (only `l4 s1 score` asks for that); a gate that never ran is refused either way."""
    root = cache_root(environ) / "s1" / "checkpoints"
    path = Path(model)
    if ".." in path.parts or path.parent.resolve() != root.resolve() or path.is_symlink() or not path.is_dir():
        return f"a checkpoint must be a directory directly under {root}"
    try:
        record = _record(model)
    except (OSError, ValueError):
        return "l4-train.json is missing or unreadable"
    gate = record.get("gate") or {}
    if not gate.get("ran"):
        return GATE_NOT_RUN
    if require_passed and gate.get("passed") is not True:
        return GATE_NOT_PASSED
    try:
        if problem := _gate_problem(path, record):
            return problem
        recorded = record.get("files") or {}
        if missing := [n for n in REQUIRED_FILES if n not in recorded]:
            return f"l4-train.json records no sha256 for {missing[0]}"
        on_disk = sorted(p for p in path.rglob("*") if p.is_symlink() or p.is_file())
        if any(p.is_symlink() for p in on_disk):
            return "a checkpoint holds only regular files (found a symlink)"
        if any(p.suffix in PICKLE_SUFFIXES for p in on_disk):
            return "only safetensors checkpoints are loaded (found a pickle-format file)"
        extra = {p.relative_to(path).as_posix() for p in on_disk} - set(recorded) - {RECORD_NAME, GATE_NAME}
        if extra:
            return f"{sorted(extra)[0]} is in the checkpoint but not in l4-train.json"
        for name, want in sorted(recorded.items()):
            target = path / name
            if ".." in Path(name).parts or not target.is_file() or _sha256(target) != want:
                return f"{name} does not match the sha256 in l4-train.json"
    except OSError as exc:  # an unreadable file is a reason, not a crash of the caller
        return f"the checkpoint cannot be read ({type(exc).__name__})"
    return ""


def overlay_home(model: str, environ: Mapping[str, str]) -> Path:
    """A private HF_HOME whose `typed-decisions` is the checkpoint, under the l4 cache and named by the weights' sha256
    (taken from the verified record, so the weights are not read again). Built beside it and renamed into place, so
    two jobs sharing the cache never see a half-built home; an existing one is reused."""
    path = Path(model)
    digest = checkpoint_identity(model)["checkpoint_sha256"]
    root = cache_root(environ) / "s1" / "overlays"
    home = root / f"{path.name}-{digest[:16]}"
    link = home / "hub" / BUNDLE_DIR / "snapshots" / digest[:40] / "typed-decisions"
    if link.is_symlink() and link.resolve() == path.resolve():
        return home
    root.mkdir(parents=True, exist_ok=True)
    build = Path(tempfile.mkdtemp(prefix=".build-", dir=root))
    try:
        bundle = build / "hub" / BUNDLE_DIR
        snapshot = bundle / "snapshots" / digest[:40]
        snapshot.mkdir(parents=True)
        (bundle / "refs").mkdir()
        (bundle / "refs" / "main").write_text(snapshot.name, encoding="utf-8")
        (snapshot / "typed-decisions").symlink_to(path.resolve(), target_is_directory=True)
        try:
            build.rename(home)
        except OSError:
            if not (link.is_symlink() and link.resolve() == path.resolve()):
                raise
    finally:
        shutil.rmtree(build, ignore_errors=True)
    return home
