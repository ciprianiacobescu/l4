"""Input digests of delivery plans (yolo-mode design D3, requirement L4-YOLO-003).

`unit_digest` hashes the files of a unit folder at a revision, so a plan can freeze what a person reviewed and notice
when the inputs change. What the harness writes itself must not count as a change: the `.l4` folder, `verification.md`,
`questions.md` and `feedback.md` (at any depth) are left out, and in every `tasks.md` the checkbox markers
`- [ ]`, `- [x]`, `- [X]`, `- [~]` and `- [-]` are read as `- [ ]`, so a ticked task is not an amendment. A change to a
spec, requirement, design or task text does change the digest. `plan_digest` is the same kind of hash over the plan
file's bytes.
"""

import hashlib
import re

from l4.vcs.git import Git

DIGEST_CHARS = 16
EXCLUDED_DIRS = frozenset({".l4"})
EXCLUDED_FILES = frozenset({"verification.md", "questions.md", "feedback.md"})
_MARKER = re.compile(rb"(?m)^([ \t]*)- \[[ xX~-]\]")


def _short(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:DIGEST_CHARS]


def plan_digest(text: str | bytes) -> str:
    """The digest of a plan file (sha256, 16 hex characters) over its bytes."""
    return _short(text if isinstance(text, bytes) else text.encode("utf-8"))


def _excluded(parts: list[str]) -> bool:
    return any(p in EXCLUDED_DIRS for p in parts[:-1]) or parts[-1] in EXCLUDED_FILES


def _normalise(name: str, content: bytes) -> bytes:
    return _MARKER.sub(rb"\1- [ ]", content) if name == "tasks.md" else content


def unit_digest(git: Git, rev: str, folder: str) -> str:
    """The digest of `folder` at `rev` (sha256, 16 hex characters): every file but the excluded ones, sorted by path
    relative to the folder, hashed as `path\\0content\\0`. A folder (or revision) that is not there gives the digest of
    the empty set, which is the same every time."""
    root = folder.strip("/")
    prefix = f"{root}/" if root else ""
    listing = git.run_bytes("ls-tree", "-r", "-z", "--full-tree", rev, "--", root or ".", check=False)
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
        if _excluded(rel.split("/")):
            continue
        entries.append((rel, sha))
    h = hashlib.sha256()
    for rel, sha in sorted(entries, key=lambda e: e[0].encode("utf-8", "surrogateescape")):
        content = _normalise(rel.rsplit("/", 1)[-1], git.run_bytes("cat-file", "blob", sha))
        h.update(rel.encode("utf-8", "surrogateescape") + b"\0" + content + b"\0")
    return h.hexdigest()[:DIGEST_CHARS]
