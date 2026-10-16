"""A new unit's uv cache starts as a copy of the project's seed (SPEC L4-SEC-005, M1.11 W10).

The first `gates.setup` of a unit downloaded the same ten wheels as the unit before it: 11m24s, 8m03s and 21s in live
wave A, for 52 packages. The unit's cache stays its own, per-unit and read-write, so that agent-written code cannot
poison another unit's (L4-SEC-005); what is shared is a seed that no agent ever runs against. The seed is filled by the
project's own `gates.setup`, unchanged, on a detached scratch checkout of the base branch's head (member-written
content, L4-SEC-003), under a lock, only when the base's `uv.lock` or the setup commands changed. It is copied into the
unit's cache when that is new, and is never mounted into a sandbox that runs an agent or agent-written code. Whatever
fails here is `cache.seed_failed`, and the unit downloads as it always did.
"""

import fcntl
import logging
import shlex
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from l4.config.schema import duration_seconds
from l4.gates.runner import GateSpec
from l4.implementer.workbench import Workbench
from l4.sandbox.base import CacheMount
from l4.sandbox.seed import copy_seed, is_new, seed_complete, seed_dir, seed_key, tree_bytes, write_seed_record

log = logging.getLogger("l4.implementer")
UV_LOCK = "uv.lock"


class SeedFailed(Exception):
    """The fill of the seed did not finish: the unit goes without it."""


def _uses_uv(command: str) -> bool:
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    return bool(words) and Path(words[0]).name == "uv"


def _base(wb: Workbench) -> str | None:
    branch = wb.cfg.forge.base_branch
    return wb.git.rev_parse(f"refs/remotes/origin/{branch}") or wb.git.rev_parse(branch)


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """One fill at a time per project, across runs: a second unit waits for the first one's fill and then copies it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def seeded_digest(event: dict) -> str | None:
    """The seed digest of a `cache.seeded` event's data: `digest`, or `key` in ledgers written before 0.4.2 (a field
    named `key` holding 64 hex characters reads as a credential to default secret scanners)."""
    value = event.get("digest", event.get("key"))
    return value if isinstance(value, str) else None


def ensure_uv_seed(wb: Workbench) -> None:
    """Copy the project's uv seed into this unit's uv cache when that cache is new, filling the seed first when it is
    absent or stale. Nothing happens without a read-write `UV_CACHE_DIR` mount, without `uv` as the first setup
    command, or without a `uv.lock` on the base branch."""
    mount = next((c for c in wb.caches if c.env == "UV_CACHE_DIR" and not c.read_only), None)
    setup = list(wb.cfg.gates.setup)
    if mount is None or not setup or not _uses_uv(setup[0]) or not is_new(mount.path):
        return
    try:
        base = _base(wb)
        shown = wb.git.run_bytes("show", f"{base}:{UV_LOCK}") if base else None
    except Exception:  # noqa: BLE001 - no lock file at the base: nothing to key a seed on
        shown = None
    if base is None or shown is None:
        return
    try:
        _seed_and_copy(wb, mount, base, seed_key(shown, setup), setup)
    except Exception as exc:  # noqa: BLE001 - whatever goes wrong, the unit downloads as it did before the seed
        reason = (str(exc).splitlines() or [type(exc).__name__])[0]
        reason = wb.redactor.redact_text(f"{type(exc).__name__}: {reason}")[:300]
        log.warning("%s: the uv seed is not used: %s", wb.ref.id, reason)
        wb.emit("cache.seed_failed", cache="uv", reason=reason)


def _seed_and_copy(wb: Workbench, mount: CacheMount, base: str, key: str, setup: list[str]) -> None:
    cache = wb.unit_cache.parent.parent.parent  # `$L4_CACHE/units/<framework>/<name>`
    origin = wb.git.run("config", "--get", "remote.origin.url", check=False).stdout.strip()
    seed = seed_dir(cache, origin)
    with _locked(seed.parent / ".lock"):
        if not seed_complete(seed, key):
            _fill(wb, seed, key, base, setup)
        started = time.monotonic()
        if copy_seed(seed, mount.path, key):
            wb.emit(
                "cache.seeded", cache="uv", digest=key, seconds=round(time.monotonic() - started, 1),
                bytes=tree_bytes(mount.path), via="copy",
            )  # fmt: skip


def _fill(wb: Workbench, seed: Path, key: str, base: str, setup: list[str]) -> None:
    """`gates.setup` unchanged, with the seed as `UV_CACHE_DIR`, on a detached scratch checkout of `base`: no file of
    the unit's worktree is in it. Its sandbox mounts the seed and nothing of the unit's caches."""
    shutil.rmtree(seed, ignore_errors=True)
    (seed.parent / "seed.json").unlink(missing_ok=True)
    seed.mkdir(parents=True)
    tree = seed.parent / "tree"
    wb.git.run("worktree", "prune", check=False)
    shutil.rmtree(tree, ignore_errors=True)
    wb.git.run("worktree", "add", "--detach", "--force", str(tree), base)
    started = time.monotonic()
    try:
        for command in setup:
            spec = GateSpec("seed", command, (), "junit", duration_seconds(wb.cfg.gates.timeout))
            result = wb.run_gate_spec(spec, network=True, tree=tree, caches=(CacheMount(seed, "UV_CACHE_DIR", False),))
            if result.status != "pass":
                raise SeedFailed(f"gates.setup failed on the base ({result.reason})")
    finally:
        wb.git.run("worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(tree, ignore_errors=True)
    seconds = time.monotonic() - started
    if not any(seed.iterdir()):
        raise SeedFailed("the setup left nothing in the uv cache")
    write_seed_record(seed, key, seconds=seconds)
    wb.emit("cache.seeded", cache="uv", digest=key, seconds=round(seconds, 1), bytes=tree_bytes(seed), via="setup")
