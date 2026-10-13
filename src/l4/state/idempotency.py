"""Step identity (SPEC L4-STA-003): a step's key says whether its work already exists.

The key is the sha256 of the canonical JSON array of the seven inputs. A commit made by the step carries the key's first
12 hex digits as its `L4-Step` trailer, so a restarted run can tell "done" from "died halfway" (state-vcs-locks D1,
`reconcile`). M1: state-vcs-locks 1.23 puts it in the trailers.
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from l4.fsutil import read_regular_file

MAX_SPEC_FILE_BYTES = 2 * 1024 * 1024
TRAILER_DIGITS = 12


def step_key(
    unit: str,
    step: str,
    task: str | None,
    base_sha: str,
    spec_hash: str,
    template_version: str,
    profile: str,
) -> str:
    inputs = [unit, step, task, base_sha, spec_hash, template_version, profile]
    canonical = json.dumps(inputs, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def trailer_value(key: str) -> str:
    return key[:TRAILER_DIGITS]


def spec_files_hash(root: Path, names: Iterable[str]) -> str:
    """Hash of the named files under `root` (the unit's spec files): names and bytes, in name order, so renaming a
    file or editing one changes it and the machine's paths do not matter. A file that is absent hashes differently
    from an empty one; a symlink or an oversized file is refused (the path is repository content)."""
    digest = hashlib.sha256()
    for name in sorted(set(names)):
        try:
            content: bytes | None = read_regular_file(root / name, limit=MAX_SPEC_FILE_BYTES)
        except FileNotFoundError:
            content = None
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big") + encoded)
        digest.update(b"\x00" if content is None else b"\x01" + len(content).to_bytes(8, "big") + content)
    return digest.hexdigest()
