"""The per-unit cache mounts of `sandbox.caches` (SPEC L4-SEC-005): `$L4_CACHE` and `{unit}` expanded, directories
created, so that agent-written code in one unit cannot poison another unit's cache."""

import re
import shutil
from collections.abc import Mapping
from pathlib import Path

from l4.config.schema import CacheCfg
from l4.sandbox.base import SCRATCH_DIR, CacheMount
from l4.specs.base import parse_unit_id

__all__ = ["SCRATCH_DIR", "VERIFY_SCOPE", "cache_dir", "mount_caches", "verifier_caches"]


def cache_dir(cfg: CacheCfg, root: Path, slug: str) -> Path:
    """The directory `cfg` names for the unit `slug`. ValueError (value-free) when it is not inside `root`."""
    path = Path(cfg.path.replace("$L4_CACHE", str(root)).replace("{unit}", slug))
    if not path.is_absolute() or ".." in path.parts or (root != path and root not in path.parents):
        raise ValueError("it must stay inside the runner cache")
    return path


VERIFY_SCOPE = "verify"  # the verifier's own namespace under the repository key (L4-SEC-039)


def mount_caches(
    caches: Mapping[str, CacheCfg], cache_root: Path, unit_id: str, repo_key: str, scope: str | None = None
) -> tuple[CacheMount, ...]:
    """`{unit}` becomes `<repository key>/<framework>/<name>` (the layout of the worktree path; a colon would be a bad
    path part), so two projects with a unit of the same name never share a cache (L4-SEC-034).
    A read-only cache is a shared one the operator provisions: when it is absent there is nothing to mount."""
    framework, name = parse_unit_id(unit_id)  # ValueError: the id comes from repo content
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", repo_key):
        raise ValueError(f"not a usable repository key: {repo_key!r}")
    slug = f"{repo_key}/{scope}/{framework.value}/{name}" if scope else f"{repo_key}/{framework.value}/{name}"
    root = cache_root.resolve()
    mounts: list[CacheMount] = []
    for cache_name, cfg in caches.items():
        try:
            path = cache_dir(cfg, root, slug)
        except ValueError:
            raise ValueError(f"sandbox.caches.{cache_name}: the path must stay inside the runner cache") from None
        if cfg.read_only and not path.is_dir():
            continue
        path.mkdir(parents=True, exist_ok=True)
        mounts.append(CacheMount(path, cfg.env, cfg.read_only))
    return tuple(mounts)


def verifier_caches(
    caches: Mapping[str, CacheCfg], cache_root: Path, unit_id: str, repo_key: str
) -> tuple[CacheMount, ...]:
    """The caches of the verifier's workbench: a namespace of their own (`<key>/verify/<fw>/<name>`), emptied here, so a
    verification round builds the project environment from a cache that no implementer step or gate has touched. Call it
    once at the start of each round (L4-SEC-039). The shared read-only caches (Playwright) are not emptied."""
    mounts = mount_caches(caches, cache_root, unit_id, repo_key, scope=VERIFY_SCOPE)
    for mount in mounts:
        if not mount.read_only:
            shutil.rmtree(mount.path, ignore_errors=True)
            mount.path.mkdir(parents=True)
    return mounts
