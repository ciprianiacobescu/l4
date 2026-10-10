"""The per-project uv seed (SPEC L4-SEC-005, M1.11 W10).

A unit's first `gates.setup` downloaded the same wheels as the unit before it (live wave A: 8 to 11 minutes each).
L4-SEC-005 gives every unit its own cache, so that agent-written code cannot poison another unit's, which rules out a
shared read-write cache. The seed is the answer: one cache per project and runner, filled by the unmodified setup on the
base branch's head (member-written content, no agent has run there), and copied, never shared, into each new unit
cache. A copy shares no inode with the seed, so nothing a unit's code does reaches it or another unit.

Layout: `$L4_CACHE/seed/<sha256(origin URL without credentials)[:16]>/uv` is the cache, and `seed.json` next to it
records the key (lock and setup commands) the fill ran for. A seed with no record, or with another key, is incomplete.
"""

import hashlib
import json
import os
import shutil
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit

from l4.fsutil import atomic_write_bytes

RECORD = "seed.json"
SEED_NAME = "uv"


def _normalised(origin_url: str) -> str:
    """`host/path` of an https, ssh or scp-style URL without userinfo, `.git` or a trailing slash; the text as it is for
    anything else (a local path). A credential in the URL must never reach the key."""
    from l4.forge.base import parse_remote_url

    remote = parse_remote_url(origin_url)
    if remote is not None:
        return f"{remote.host}/{remote.path}"
    parts = urlsplit(origin_url.strip())
    return f"{parts.hostname or ''}{parts.path}".rstrip("/") if parts.scheme else origin_url.strip().rstrip("/")


def seed_dir(cache_root: Path, origin_url: str) -> Path:
    """The uv seed of the project whose origin is `origin_url`: per project, because `$L4_CACHE` is shared by every
    project on the runner and one project's members must not fill another's cache."""
    digest = hashlib.sha256(_normalised(origin_url).encode("utf-8")).hexdigest()[:16]
    return cache_root / "seed" / digest / SEED_NAME


def seed_key(uv_lock: bytes, setup_commands: Sequence[str]) -> str:
    """What a fill is valid for: the lock file and the setup commands."""
    body = hashlib.sha256(uv_lock).hexdigest() + "\0" + "\0".join(setup_commands)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _record(seed: Path) -> Path:
    return seed.parent / RECORD


def write_seed_record(seed: Path, key: str, *, seconds: float) -> None:
    """Mark the fill of `seed` as complete for `key`; the record is written last, atomically."""
    body = {"key": key, "seconds": round(seconds, 1), "bytes": tree_bytes(seed)}
    atomic_write_bytes(_record(seed), (json.dumps(body, sort_keys=True) + "\n").encode("utf-8"))


def read_seed_record(seed: Path) -> dict[str, object] | None:
    try:
        data = json.loads(_record(seed).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def seed_complete(seed: Path, key: str) -> bool:
    record = read_seed_record(seed)
    return record is not None and record.get("key") == key and seed.is_dir() and any(seed.iterdir())


def tree_bytes(root: Path) -> int:
    """The size of the regular files under `root` (symlinks are not followed)."""
    total = 0
    for base, _, names in os.walk(root):
        for name in names:
            path = Path(base) / name
            if not path.is_symlink():
                total += path.stat().st_size
    return total


def is_new(target: Path) -> bool:
    """A unit cache with nothing in it yet (absent, or created empty by `mount_caches`)."""
    return not target.exists() or (target.is_dir() and not any(target.iterdir()))


def copy_seed(seed: Path, target: Path, key: str) -> bool:
    """Copy a complete seed into a unit cache that is new (absent or empty), and say whether it was copied. A cache
    that already has content is never touched, and neither is the target when the seed is incomplete for `key`.
    Symlinks are copied as links, and an absolute one that points into the seed is re-pointed into the copy [U: uv's
    layout may not have any]."""
    if not seed_complete(seed, key) or not is_new(target):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(exist_ok=True)
    for entry in sorted(seed.iterdir()):
        destination = target / entry.name
        if entry.is_symlink():
            shutil.copy2(entry, destination, follow_symlinks=False)
        elif entry.is_dir():
            shutil.copytree(entry, destination, symlinks=True)
        else:
            shutil.copy2(entry, destination)
    _repoint(seed, target)
    return True


def _repoint(seed: Path, target: Path) -> None:
    resolved_seed = os.fspath(seed)
    for base, dirs, names in os.walk(target):
        for name in (*dirs, *names):
            link = Path(base) / name
            if not link.is_symlink():
                continue
            destination = os.readlink(link)
            if os.path.isabs(destination) and (
                destination == resolved_seed or destination.startswith(resolved_seed + os.sep)
            ):
                link.unlink()
                link.symlink_to(os.fspath(target) + destination[len(resolved_seed) :])
