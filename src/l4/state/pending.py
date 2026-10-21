"""The pending ledger (SPEC L4-STA-004, M1.1 lines 27 and 28): what a run writes after the hand-off commit H.

The unit branch must stay at H, so the run's ledger file goes into a commit on the unit's lock ref
`refs/l4/locks/<fw>/<name>`, as `ledger-pending/<run-id>.jsonl`. The commit has the L4-LCK-001 message (so that M2's
lease can take the ref over), carries `[skip ci]` and `L4-Run`, and is never a pull request head. The state fold reads
the unit branch plus these files (`merge_ledgers`).

The commit is built with plumbing only and pushed straight to the remote under a lease; the local ref is written after
the push succeeded. G8 fetches `+refs/l4/locks/*` with `--prune`, which deletes a local lock ref the remote does not
have: a ref written before the push would be lost by the next fetch.

Reduced form: no lease acquire, heartbeat, fencing or takeover (state-vcs-locks 2.2-2.17), and the pending files are
never dropped here (M1: state-vcs-locks 5.6 folds them into the archive commit of forge-and-ci 1.33).
"""

import json
import logging
import os
import re
import secrets
import shutil
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import read_regular_file
from l4.state.ledger import (
    MAX_LEDGER_FILE_BYTES,
    RUN_ID,
    LedgerCorrupt,
    LedgerEvent,
    LedgerRead,
    parse_ledger_files,
)
from l4.vcs.git import BOT_IDENTITY, Git, Identity
from l4.vcs.names import UNPUBLISHED_DIR as UNPUBLISHED_DIR  # re-exported: the constant lives with the names
from l4.vcs.push import PushRejected
from l4.vcs.tree import regular_blobs

PENDING_DIR = "ledger-pending"
MAX_ATTEMPTS = 3  # a lease that is stale this often means the ref is being written by someone in a loop
_ENTRY = re.compile(rf"^{RUN_ID.pattern[1:-1]}\.jsonl$")
_TS = "%Y-%m-%dT%H:%M:%SZ"
log = logging.getLogger("l4.pending")


class PendingNotPublished(L4Exit):
    def __init__(self, message: str) -> None:
        super().__init__(ExitCode.INTERNAL_ERROR, message)


@dataclass(frozen=True)
class LockCommit:
    sha: str
    expected: str  # the value of the lock ref on the remote that the commit was built on ('' = no ref)


def _now() -> datetime:
    return datetime.now(UTC)


def live_run(events: Sequence[LedgerEvent]) -> str | None:
    """The run id of a run that is working on the unit: a `run.started` with no `run.finished` in the lock ref's pending
    ledger. It may be a run on another machine, or one that died without a line; its pending file then ends a run that
    never ends, and the operator waits or removes it by hand. `l4 restart` and `l4 questions` both refuse on it."""
    finished = {e.run_id for e in events if e.type == "run.finished"}
    return next((e.run_id for e in events if e.type == "run.started" and e.run_id not in finished), None)


def read_pending_files(git: Git, lock_ref: str) -> dict[str, bytes]:
    """`<run-id>.jsonl` -> bytes of the pending files in the local lock ref; none when the ref does not exist."""
    if git.rev_parse(lock_ref) is None:
        return {}
    blobs = regular_blobs(git, lock_ref, f"{PENDING_DIR}/", MAX_LEDGER_FILE_BYTES)
    return {
        name: git.run_bytes("cat-file", "blob", blob.oid)
        for blob in blobs
        if _ENTRY.match(name := blob.path.rsplit("/", 1)[-1])
    }


def keep_unpublished(directory: Path, run_file: Path) -> Path:
    """Copy a run file that could not be published out of the worktree, which the next run deletes. It is published
    (and the copy dropped) by the next run of the unit, before that run folds the unit's state. `directory` is the
    unit's keyed `UnitNames.unpublished_dir` (L4-SEC-034)."""
    target = directory / f"{run_file.stem}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(run_file, target)
    return target


def unpublished_files(directory: Path) -> dict[str, Path]:
    """`<run-id>` -> the kept copy, for every regular file of `directory` that is named like a run file."""
    if not directory.is_dir():
        return {}
    return {
        path.stem: path
        for path in sorted(directory.iterdir())
        if _ENTRY.match(path.name) and path.is_file() and not path.is_symlink()
    }


def _run_started(path: Path) -> dict[str, Any]:
    """The first line of a run file when it is a `run.started`, else {}."""
    try:
        first = read_regular_file(path, limit=MAX_LEDGER_FILE_BYTES).split(b"\n", 1)[0]
        body = json.loads(first)
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) and body.get("type") == "run.started" else {}


_CI_PROJECT = re.compile(r"^https?://[^/]+/(?P<path>.+?)/(?:-/|actions/)")


def belongs_to(path: Path, *, repo_key: str, repo_path: str | None) -> bool:
    """Whether a run file of the earlier layout was written for this repository (L4-SEC-034). A file records the
    repository key in its `run.started` (since 0.4.18); an older one is proven only by the project path of its CI link
    (`https://<forge>/group/project/-/pipelines/N` or `.../actions/runs/N`; the host is scrubbed in the file) equal to
    the path of this repository's `origin`. The commits a file names prove nothing: every clone has the history."""
    body = _run_started(path)
    recorded = body.get("repository_key")
    if isinstance(recorded, str):
        return recorded == repo_key
    link = body.get("ci_url")
    match = _CI_PROJECT.match(link) if isinstance(link, str) else None
    return bool(match and repo_path and match.group("path") == repo_path)


def adopt_legacy(legacy_dir: Path, keyed_dir: Path, *, repo_key: str, repo_path: str | None) -> list[Path]:
    """The run files of the earlier, unkeyed layout (`pending-unpublished/<fw>/<name>`) that belong to this repository
    (`belongs_to`) move to `keyed_dir`. Any other stays where it is (it may be another project's) and is named in one
    warning, never by content. Returns the files moved, at their new place (L4-SEC-034)."""
    if not legacy_dir.is_dir():
        return []
    moved: list[Path] = []
    left = 0
    for path in unpublished_files(legacy_dir).values():
        if belongs_to(path, repo_key=repo_key, repo_path=repo_path):
            keyed_dir.mkdir(parents=True, exist_ok=True)
            target = keyed_dir / path.name
            if target.exists():  # the keyed copy of the same run is the one this repository wrote
                path.unlink()
            else:
                shutil.move(str(path), target)
            moved.append(target)
        else:
            left += 1
    if left:
        log.warning(
            "%d unpublished run files of the earlier layout in %s belong to no repository we can prove is this one; "
            "they are kept and never published",
            left, legacy_dir,
        )  # fmt: skip
    return moved


def read_pending(git: Git, lock_ref: str) -> LedgerRead:
    return parse_ledger_files(read_pending_files(git, lock_ref))


def _same(a: LedgerEvent, b: LedgerEvent) -> bool:
    return (a.ts, a.type, dict(a.data)) == (b.ts, b.type, dict(b.data))


def merge_ledgers(branch: LedgerRead, pending: LedgerRead) -> LedgerRead:
    """Events by `(run_id, seq)`: a pending file extends the branch copy of its run (the lines both hold are kept
    once), and a different payload under the same key means one of the two was edited: `LedgerCorrupt`."""
    seen = {(e.run_id, e.seq): e for e in branch.events}
    merged = list(branch.events)
    for event in pending.events:
        known = seen.get((event.run_id, event.seq))
        if known is None:
            merged.append(event)
        elif not _same(known, event):
            raise LedgerCorrupt(
                f"{event.run_id}.jsonl:{event.seq} differs between the unit branch and the pending ledger"
            )
    merged.sort(key=lambda e: (e.ts, e.run_id, e.seq))
    return LedgerRead(merged, sorted({*branch.torn, *pending.torn}))


class PendingLedger:
    """Publishes one run's ledger file to the lock ref of its unit."""

    def __init__(
        self,
        git: Git,
        *,
        lock_ref: str,
        unit: str,
        run_id: str,
        remote: str = "origin",
        fetch_config: Sequence[tuple[str, str]] = (),
        push_config: Sequence[tuple[str, str]] = (),
        holder: str | None = None,
        clock: Callable[[], datetime] = _now,
        identity: Identity = BOT_IDENTITY,
    ) -> None:
        self._git = git
        self._ref = lock_ref
        self._unit = unit
        self._run_id = run_id
        self._remote = remote
        self._fetch_config = fetch_config
        self._push_config = push_config
        self._holder = holder or f"{socket.gethostname()}:{os.getpid()}"
        self._clock = clock
        self._identity = identity

    def publish(self, run_file: Path) -> str:
        """The whole run file goes in, so the lines that H already holds fold away and no cut point is tracked.
        A lease the server refuses means another run wrote the ref: the commit is built again on its value."""
        for _ in range(MAX_ATTEMPTS):
            built = self.build(run_file)
            try:
                self.push(built)
            except PushRejected:  # only a lost lease is one (`Git.push_lease`); any other refusal is a `GitError`
                log.info("the lock ref %s moved while the pending ledger was built: building it again", self._ref)
                continue
            return built.sha
        raise PendingNotPublished(
            f"the pending ledger of {self._run_id} was not published: {self._ref} changed {MAX_ATTEMPTS} times "
            "while it was being written"
        )

    def build(self, run_file: Path) -> LockCommit:
        """The lock commit, as objects only: no ref names it yet. Its parent is the remote's current lock commit,
        whose pending files it keeps."""
        data = read_regular_file(run_file, limit=MAX_LEDGER_FILE_BYTES)
        expected = self._remote_value()
        git = self._git
        entries = self._kept_entries(expected) if expected else []
        blob = git.write_blob(data)
        entries.append(f"100644 blob {blob}\t{self._run_id}.jsonl\0")
        subtree = git.run("mktree", "-z", input="".join(entries)).stdout.strip()
        tree = git.run("mktree", "-z", input=f"040000 tree {subtree}\t{PENDING_DIR}\0").stdout.strip()
        parent = ["-p", expected] if expected else []
        config = (("user.name", self._identity.name), ("user.email", self._identity.email))
        sha = git.run("commit-tree", tree, *parent, "-F", "-", input=self._message(), config=config).stdout.strip()
        return LockCommit(sha, expected)

    def push(self, built: LockCommit) -> None:
        """Under the lease `<ref>:<expected>`; the local ref follows only when the server took the commit."""
        self._git.push_lease(self._remote, built.sha, self._ref, built.expected, config=self._push_config)
        self._git.run("update-ref", self._ref, built.sha)

    # --- internals ------------------------------------------------------------------------------------------

    def _remote_value(self) -> str:
        """What the remote holds now, asked of the remote: the local ref is only as fresh as the last fetch. The
        objects behind it are fetched when this clone has not got them (another runner wrote it)."""
        out = self._git.run("ls-remote", self._remote, self._ref, config=self._fetch_config).stdout
        found = ""
        for line in out.splitlines():
            sha, _, name = line.partition("\t")
            if name == self._ref:
                found = sha
        if found and self._git.run("cat-file", "-e", f"{found}^{{commit}}", check=False).returncode != 0:
            self._git.run("fetch", "--quiet", self._remote, self._ref, config=self._fetch_config)
        return found

    def _kept_entries(self, commit: str) -> list[str]:
        """The previous pending files, except this run's own (it is written again), as `mktree -z` input."""
        done = self._git.run("ls-tree", "-z", f"{commit}:{PENDING_DIR}", check=False)
        kept = []
        for record in filter(None, done.stdout.split("\0")):
            meta, _, name = record.partition("\t")
            mode, kind, _ = meta.split(" ", 2)
            if mode == "100644" and kind == "blob" and _ENTRY.match(name) and name != f"{self._run_id}.jsonl":
                kept.append(record + "\0")
        return kept

    def _message(self) -> str:
        """L4-LCK-001's JSON on the first line. Nothing holds a lease here, so the commit is born expired."""
        stamp = self._clock().strftime(_TS)
        fields = {
            "unit": self._unit, "run_id": self._run_id, "holder": self._holder, "acquired_at": stamp,
            "expires_at": stamp, "nonce": secrets.token_hex(8),
        }  # fmt: skip
        for value in (self._unit, self._run_id):
            if "\n" in value or "\r" in value:
                raise ValueError("a lock commit trailer must be one line")
        return f"{json.dumps(fields)}\n\n[skip ci]\n\nL4-Unit: {self._unit}\nL4-Run: {self._run_id}\n"
