"""The per-unit cache mounts of `sandbox.caches` (SPEC L4-SEC-005): `$L4_CACHE` and `{unit}` expanded, directories
created, so that agent-written code in one unit cannot poison another unit's cache."""

from collections.abc import Mapping
from pathlib import Path

from l4.config.schema import CacheCfg
from l4.sandbox.base import CacheMount
from l4.specs.base import parse_unit_id


def cache_dir(cfg: CacheCfg, root: Path, slug: str) -> Path:
    """The directory `cfg` names for the unit `slug`. ValueError (value-free) when it is not inside `root`."""
    path = Path(cfg.path.replace("$L4_CACHE", str(root)).replace("{unit}", slug))
    if not path.is_absolute() or ".." in path.parts or (root != path and root not in path.parents):
        raise ValueError("it must stay inside the runner cache")
    worktrees = root / "worktrees"
    if path in (root, worktrees) or worktrees in path.parents:
        # a writable mount must never cover a work tree, or the folder that holds one (the replay guard relies on it)
        raise ValueError("it must stay inside the runner cache, clear of its worktrees folder")
    return path


def mount_caches(caches: Mapping[str, CacheCfg], cache_root: Path, unit_id: str) -> tuple[CacheMount, ...]:
    """`{unit}` becomes `<framework>/<name>` (the layout of the worktree path; a colon would be a bad path part).
    A read-only cache is a shared one the operator provisions: when it is absent there is nothing to mount."""
    framework, name = parse_unit_id(unit_id)  # ValueError: the id comes from repo content
    slug = f"{framework.value}/{name}"
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
