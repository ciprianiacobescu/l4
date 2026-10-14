"""Input digests of delivery plans (yolo-mode design D3, requirement L4-YOLO-003).

`unit_digest` hashes the files of a unit folder at a revision, so a plan can freeze what a person reviewed and notice
when the inputs change. What the harness writes itself must not count as a change: the `.l4` folder, `verification.md`,
`questions.md` and `feedback.md` (at any depth, `is_excluded`, which the readiness review shares so the judge reads
what the digest covers) are left out, and in every `tasks.md` the checkbox marker of a task line is read as `[ ]`
whatever it says (R4). A task line is what the harness's own tick writer accepts (`l4.specs.tasks_merge`, Kiro and
OpenSpec): a bullet `-`, `*`, `+` or a number with `.` or `)`, an optional space, a BOM on the line and NBSP
indentation, so a ticked task is not an amendment in any form the providers parse. A change to a spec, requirement,
design or task text does change the digest.

`current_unit_digest` is the digest a unit has now (D3, R3): on `refs/remotes/origin/<unit branch>` when that ref
exists, else on the target. A revision that does not exist raises `RevisionMissing`; it never gives the digest of the
empty set, which would read as "every input was deleted". `plan_digest` is the same kind of hash over the plan file's
bytes.
"""

import hashlib
import re
from collections.abc import Sequence

from l4.config.schema import L4Config
from l4.vcs.git import Git
from l4.vcs.names import unit_branch

DIGEST_CHARS = 16
EXCLUDED_DIRS = frozenset({".l4"})
EXCLUDED_FILES = frozenset({"verification.md", "questions.md", "feedback.md"})
# The marker of a task line, as `tasks_merge` reads it (its `_LEAD`; the Kiro marker set includes OpenSpec's)
_MARKER = re.compile(rb"(?m)^((?:\xef\xbb\xbf)?[ \t\xc2\xa0]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]*\[)[ xX\-~](\])")


class RevisionMissing(RuntimeError):
    """The revision a digest is asked for is not in the repository (an unfetched tracking ref, a wrong sha)."""


def _short(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:DIGEST_CHARS]


def plan_digest(text: str | bytes) -> str:
    """The digest of a plan file (sha256, 16 hex characters) over its bytes."""
    return _short(text if isinstance(text, bytes) else text.encode("utf-8"))


def is_excluded(parts: Sequence[str]) -> bool:
    """True for a path (its parts relative to the unit folder) that the harness or a person writes: any `.l4` folder
    above the file, or a file named `verification.md`, `questions.md` or `feedback.md`, at any depth (R4)."""
    return any(p in EXCLUDED_DIRS for p in parts[:-1]) or parts[-1] in EXCLUDED_FILES


def _normalise(name: str, content: bytes) -> bytes:
    return _MARKER.sub(rb"\1 \2", content) if name == "tasks.md" else content


def unit_digest(git: Git, rev: str, folder: str) -> str:
    """The digest of `folder` at `rev` (sha256, 16 hex characters): every file but the excluded ones, sorted by path
    relative to the folder, hashed as `path\\0content\\0`. A folder that is not in the revision gives the digest of
    the empty set, which is the same every time; a revision that is not there raises `RevisionMissing` (R3)."""
    if not rev or git.rev_parse(rev) is None:
        raise RevisionMissing(f"the revision {rev!r} does not exist in this repository (fetch it first)")
    root = folder.strip("/")
    prefix = f"{root}/" if root else ""
    listing = git.run_bytes("ls-tree", "-r", "-z", "--full-tree", rev, "--", root or ".")
    entries: list[tuple[str, str]] = []  # (path relative to the folder, blob id)
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        meta, _, path_bytes = raw.partition(b"\t")
        mode, kind, sha = meta.decode("ascii", "replace").split(" ")
        path = path_bytes.decode("utf-8", "surrogateescape")
        if kind != "blob" or not path.startswith(prefix):
            continue  # a submodule is not content of the folder
        rel = path[len(prefix) :]
        if is_excluded(rel.split("/")):
            continue
        entries.append((rel, sha))
    h = hashlib.sha256()
    for rel, sha in sorted(entries, key=lambda e: e[0].encode("utf-8", "surrogateescape")):
        content = _normalise(rel.rsplit("/", 1)[-1], git.run_bytes("cat-file", "blob", sha))
        h.update(rel.encode("utf-8", "surrogateescape") + b"\0" + content + b"\0")
    return h.hexdigest()[:DIGEST_CHARS]


def current_unit_ref(git: Git, cfg: L4Config, unit_id: str, target_ref: str) -> str:
    """The revision a unit is read on now (D3, R3): `refs/remotes/origin/<unit branch>` when that ref exists, else
    `target_ref`. Raises `RevisionMissing` when `target_ref` is needed and does not exist."""
    branch = f"refs/remotes/origin/{unit_branch(unit_id, cfg.forge.branch_prefix)}"
    if git.rev_parse(branch) is not None:
        return branch
    if not target_ref or git.rev_parse(target_ref) is None:
        raise RevisionMissing(f"the target revision {target_ref!r} does not exist in this repository (fetch it first)")
    return target_ref


def current_unit_digest(git: Git, cfg: L4Config, unit_id: str, folder: str, target_ref: str) -> str:
    """The digest of `folder` on the revision `current_unit_ref` names. The review, the activation and the
    `inputs_changed` check all use it, so they cannot disagree about what a unit is now (R3)."""
    return unit_digest(git, current_unit_ref(git, cfg, unit_id, target_ref), folder)
