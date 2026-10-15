"""The plan ledger store: the ref `refs/l4/plans/<plan-id>` and its commit chain (design D4, L4-YOLO-006, L4-YOLO-015).

Each commit's tree holds `ledger.jsonl` (one `PlanEvent` per line, every event so far) and may hold `report.md` and
`receipts/<unit-name>.json` (the unit id with ':' replaced by '-'). Commits are made with git plumbing (`hash-object`,
`mktree`, `commit-tree`) in the repository, without a worktree or an index, with the harness bot identity.

`PlanStore.read()` fetches the ref and returns what it holds. `PlanStore.append()` makes one commit on top of the head
the caller read and pushes it with `git push --atomic --force-with-lease=<ref>:<expected>`: the git server checks the
lease, so two writers on different hosts cannot both win. A lost lease raises `PlanMoved`; the caller reads again and
decides again, and nothing is ever overwritten. A receipt is written once per `receipt_id` (D12).
"""

import json
import logging
import posixpath
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from l4 import cancel
from l4.forge.pushfail import explain_push_failure
from l4.vcs.errors import GitError
from l4.vcs.git import BOT_IDENTITY, Git
from l4.vcs.push import is_lost_lease
from l4.yolo.model import PLAN_ID, PLAN_REF_PREFIX, PlanEvent, PlanMoved

log = logging.getLogger("l4.yolo.store")

LEDGER_FILE = "ledger.jsonl"
REPORT_FILE = "report.md"
RECEIPTS_DIR = "receipts"
_MISSING_REF = "couldn't find remote ref"
_BLOB, _TREE = "100644", "040000"
_PART = re.compile(r"^[A-Za-z0-9._-]+$")


@dataclass(frozen=True)
class PlanRead:
    """What the plan ref holds. `head` is None when there is no ref yet. `files` are the tree's files other than the
    ledger (`report.md`, `receipts/<unit-name>.json`), path -> text."""

    head: str | None
    events: list[PlanEvent] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)


def plan_ref(plan_id: str) -> str:
    if not PLAN_ID.match(plan_id):
        raise ValueError(f"not a plan id: {plan_id!r}")
    return f"{PLAN_REF_PREFIX}{plan_id}"


def receipt_path(unit_id: str) -> str:
    """`receipts/<unit-name>.json`: the unit id with ':' replaced by '-'."""
    return f"{RECEIPTS_DIR}/{unit_id.replace(':', '-')}.json"


def list_plans(git: Git, config: Sequence[tuple[str, str]] = ()) -> list[str]:
    """The plan ids that have a ref on `origin`, sorted."""
    out = git.run("ls-remote", "origin", f"{PLAN_REF_PREFIX}*", config=config).stdout
    ids = set()
    for line in out.splitlines():
        _, _, ref = line.partition("\t")
        name = ref.strip().removeprefix(PLAN_REF_PREFIX)
        if PLAN_ID.match(name):
            ids.add(name)
    return sorted(ids)


def parse_ledger(text: str) -> list[PlanEvent]:
    """One event per non-empty line. A line that is not an event is an error, never skipped: the state is a fold of the
    whole ledger (L4-YOLO-006)."""
    events = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(PlanEvent.from_json(line))
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{LEDGER_FILE} line {number} is not a plan event: {exc}") from None
    return events


class PlanStore:
    """The ledger ref of one plan. `config` is the `git -c` pairs of the fetch (`fetch_auth_config`); `push_config`
    those of the push (`push_auth_config`), `config` when not given."""

    def __init__(
        self,
        git: Git,
        plan_id: str,
        config: Sequence[tuple[str, str]] = (),
        *,
        push_config: Sequence[tuple[str, str]] | None = None,
        token_env: str = "L4_FORGE_TOKEN",
        environ: Mapping[str, str] | None = None,
        redact: Callable[[str], str] = str,
    ) -> None:
        self.git = git
        self.plan_id = plan_id
        self.ref = plan_ref(plan_id)
        self.config = tuple(config)
        self.push_config = self.config if push_config is None else tuple(push_config)
        self._token_env, self._environ, self._redact = token_env, environ or {}, redact

    @staticmethod
    def list_plans(git: Git, config: Sequence[tuple[str, str]] = ()) -> list[str]:
        return list_plans(git, config)

    # --- read -------------------------------------------------------------------------------------------------------

    def read(self) -> PlanRead:
        """Fetch the ref from `origin` (a missing ref is an empty plan) and read the head's ledger and files."""
        head = self._fetch()
        if head is None:
            return PlanRead(None)
        files = self._files_at(head)
        ledger = files.pop(LEDGER_FILE, b"").decode("utf-8")
        return PlanRead(head, parse_ledger(ledger), {p: b.decode("utf-8", "replace") for p, b in files.items()})

    def read_local(self) -> PlanRead | None:
        """The ledger as the clone last fetched it, with no network call: None when the ref was never fetched. For a
        step that cannot reach the origin and only needs to know which plans were open."""
        head = self.git.rev_parse(self.ref)
        if head is None:
            return None
        ledger = self._files_at(head).get(LEDGER_FILE, b"").decode("utf-8")
        return PlanRead(head, parse_ledger(ledger), {})

    def _fetch(self) -> str | None:
        try:
            self.git.fetch("origin", refspecs=(f"+{self.ref}:{self.ref}",), config=self.config)
        except GitError as exc:
            if _MISSING_REF not in exc.stderr:
                raise
            return None
        return self.git.rev_parse(self.ref)

    def _files_at(self, commit: str) -> dict[str, bytes]:
        listing = self.git.run_bytes("ls-tree", "-r", "-z", commit).decode("utf-8", "replace")
        files = {}
        for entry in filter(None, listing.split("\0")):
            meta, _, path = entry.partition("\t")
            files[path] = self.git.run_bytes("cat-file", "blob", meta.split()[2])
        return files

    # --- write ------------------------------------------------------------------------------------------------------

    def append(
        self, events: Iterable[PlanEvent], *, files: Mapping[str, str | bytes] | None = None, expect: str | None
    ) -> str:
        """One commit on top of `expect` (a root commit when None) with `events` added to the ledger and `files` added
        to or replaced in the tree, pushed under a lease on `expect`. Returns the new head. `PlanMoved` when the ref
        is no longer at `expect`; the caller reads again."""
        new_events = list(events)
        extra = {_clean_path(p): d.encode("utf-8") if isinstance(d, str) else d for p, d in (files or {}).items()}
        if not new_events and not extra:
            raise ValueError("append: nothing to write")
        base: dict[str, bytes] = {}
        if expect is not None:
            self._have(expect)
            base = self._files_at(expect)
        ledger = base.get(LEDGER_FILE, b"")
        if ledger and not ledger.endswith(b"\n"):
            ledger += b"\n"
        ledger += "".join(e.to_json() + "\n" for e in new_events).encode("utf-8")
        tree = self._tree({**base, **extra, LEDGER_FILE: ledger})
        message = f"plan {self.plan_id}: " + (", ".join(dict.fromkeys(e.type for e in new_events)) or "files")
        args = ["commit-tree", tree, *(["-p", expect] if expect else []), "-m", message]
        sha = self.git.run(
            *args,
            config=(("user.name", BOT_IDENTITY.name), ("user.email", BOT_IDENTITY.email), ("commit.gpgsign", "false")),
        ).stdout.strip()
        self._push(sha, expect)
        # the fetch of the next read would do this; doing it here keeps `rev_parse(ref)` true to the remote
        self.git.run("update-ref", self.ref, sha)
        return sha

    def write_receipt(self, receipt: Mapping[str, Any], *, expect: str | None, events: Iterable[PlanEvent] = ()) -> str:
        """Write `receipts/<unit-name>.json` once per `receipt_id` (D12). When the file already holds this id nothing
        is committed for it (with `events`, only the events are). Returns the head after the call."""
        receipt_id, path = str(receipt["receipt_id"]), receipt_path(str(receipt["unit_id"]))
        pending = list(events)
        if expect is not None:
            self._have(expect)
            held = self._files_at(expect).get(path)
            if held is not None and _receipt_id(held) == receipt_id:
                return self.append(pending, expect=expect) if pending else expect
        body = json.dumps(dict(receipt), indent=2, sort_keys=True) + "\n"
        return self.append(pending, files={path: body}, expect=expect)

    # --- internals --------------------------------------------------------------------------------------------------

    def _have(self, commit: str) -> None:
        """`commit` must be in this repository to build on it; if not, the ref has moved on since it was read."""
        if self.git.run("cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode == 0:
            return
        if self._fetch() is None or self.git.run("cat-file", "-e", f"{commit}^{{commit}}", check=False).returncode != 0:
            raise PlanMoved(f"{self.ref} no longer holds {commit}")

    def _tree(self, files: Mapping[str, bytes]) -> str:
        return self._mktree({path: self.git.write_blob(data) for path, data in files.items()})

    def _mktree(self, blobs: Mapping[str, str]) -> str:
        """Nested paths become subtrees, deepest first."""
        entries: list[tuple[str, str, str]] = []
        dirs: dict[str, dict[str, str]] = {}
        for path, sha in blobs.items():
            head, sep, rest = path.partition("/")
            if sep:
                dirs.setdefault(head, {})[rest] = sha
            else:
                entries.append((_BLOB, "blob", sha + "\t" + head))
        for name, inner in dirs.items():
            entries.append((_TREE, "tree", self._mktree(inner) + "\t" + name))
        text = "".join(
            f"{mode} {kind} {rest}\n" for mode, kind, rest in sorted(entries, key=lambda e: e[2].split("\t")[1])
        )
        return self.git.run("mktree", input=text).stdout.strip()

    def _push(self, sha: str, expect: str | None) -> None:
        cancel.check()
        args = [
            "push",
            "--atomic",
            f"--force-with-lease={self.ref}:{expect or ''}",
            "--",
            "origin",
            f"{sha}:{self.ref}",
        ]
        try:
            self.git.run(*args, config=self.push_config)
        except GitError as exc:
            if is_lost_lease(exc.stderr):
                raise PlanMoved(f"{self.ref} moved since it was read: read again and decide again") from None
            raise explain_push_failure(
                exc, branch=self.ref, token_env=self._token_env, environ=self._environ, redact=self._redact
            ) from None


def _clean_path(path: str) -> str:
    norm = posixpath.normpath(path)
    parts = norm.split("/")
    if norm != path or norm == LEDGER_FILE or not all(_PART.match(p) and p not in (".", "..") for p in parts):
        raise ValueError(f"not a plan file path: {path!r}")
    return norm


def _receipt_id(data: bytes) -> str | None:
    try:
        value = json.loads(data.decode("utf-8"))
    except ValueError:
        return None
    return str(value.get("receipt_id")) if isinstance(value, dict) else None
