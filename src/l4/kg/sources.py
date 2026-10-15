"""What the experience graph reads, out of committed git objects only (design D3; L4-KG-004, L4-KG-002, L4-KG-001).

`collect` walks four places and returns plain records. It does not build nodes or edges (that is `extract`'s job), and
it calls no model, no forge and no network. Its git calls are `for-each-ref`, `rev-parse`, `ls-tree`, `cat-file` and
`log`, so a test can run it through a `Git` that refuses everything else. Nothing is read from the work tree, and
nothing is fetched.

The places (D3):

1. The base ref, `refs/remotes/origin/<forge.base_branch>`, else `HEAD` with a warning: OpenSpec
   `changes/<name>/`, every `changes/archive/<date>-<name>/` (one walk of its own, because `list_units` skips
   `archive/` and `archive_folders` keeps only the newest folder per name), and the Kiro folders
   `<spec.kiro.root>/<name>/`.
2. The unit branches `refs/remotes/origin/<branch_prefix><fw>/<name>`, with the unit folder and its `<name>-fix-<n>`
   siblings.
3. The local lock refs `refs/l4/locks/<fw>/<name>`, whose `ledger-pending/<run>.jsonl` files extend the branch copy.
4. The local attempts refs `refs/l4/attempts/<fw>/<name>/<n>` (and `<n>-locks`), each one read as attempt `n`. The
   current branch and the base folders are attempt 0.

A unit that several places hold is one `UnitRecord`; its events are the union by `(run_id, seq)`, and each event keeps
the first place that held it (`Origin`), so that `SourcedEvent.src` is `<sha10>:<path>#<seq>` and
`VerdictFile.src("/round")` is `<sha10>:<path>#/round` (L4-KG-005). A fix-unit folder `<name>-fix-<n>` belongs to its
parent unit when the parent is read.

Containment (L4-KG-002): a corrupt, oversized, unreadable or non-regular input is skipped and counted by reason
(`SKIP_REASONS`), and never fails the build. An exception inside one unit skips that unit (`error`). A
`unit.restarted` whose `attempt_ref` is not a local ref is counted as `attempt_not_local`, listed in
`Collected.not_local`, and never fetched; `FETCH_ATTEMPTS` is the command the report prints.

The values are as committed. Redaction (L4-KG-011) is applied by the caller before anything is stored or shown.
"""

import json
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from l4.config.schema import L4Config
from l4.memory.lessons import Lesson, parse_lessons
from l4.specs.base import parse_unit_id
from l4.state.ledger import MAX_LEDGER_FILE_BYTES, LedgerCorrupt, LedgerEvent, LedgerRead, parse_ledger_files
from l4.vcs.errors import GitError
from l4.vcs.git import Git

log = logging.getLogger("l4.kg")

REMOTE = "origin"
SKIP_REASONS = (
    "ledger_corrupt", "verdict_unreadable", "oversize", "not_regular", "lessons_problem", "attempt_not_local",
    "partial_clone", "error",
)  # fmt: skip
FETCH_ATTEMPTS = "git fetch origin 'refs/l4/attempts/*:refs/l4/attempts/*'"
VERDICT_SCHEMA = "l4/verdict@1"  # `l4.verifier.report.VERDICT_SCHEMA_ID`, which a test compares
MAX_VERDICT_BYTES = 4 * 1024 * 1024
MAX_LESSONS_BYTES = 1024 * 1024
PENDING_DIR = "ledger-pending"
PLACES = ("base", "archive", "branch", "lock", "attempt")

_RUN_FILE = re.compile(r"^r-\d{8}T\d{4}Z-[0-9a-f]{4}\.jsonl$")
_ROUND = re.compile(r"^round-(\d+)$")
_DATED = re.compile(r"^\d{4}-\d\d-\d\d-(?P<name>.+)$")
_FIX = re.compile(r"^(?P<parent>.+)-fix-\d+$")
_ATTEMPT_REF = re.compile(r"^refs/l4/attempts/(?P<fw>openspec|kiro)/(?P<name>[^/]+)/(?P<n>\d+)(?P<locks>-locks)?$")
_LOCK_REF = re.compile(r"^refs/l4/locks/(?P<fw>openspec|kiro)/(?P<name>[^/]+)$")
_REGULAR = ("100644", "100755")
# where a place's data wins when two places hold the same event: the branch is the freshest copy
_PRIORITY = {"branch": 0, "attempt": 0, "lock": 1, "attempt_lock": 1, "base": 2, "archive": 3}


@dataclass(frozen=True)
class Origin:
    """A committed file: the commit it was read at, and its path in that commit."""

    kind: str  # base | archive | branch | lock | attempt | attempt_lock
    ref: str
    sha: str
    path: str

    @property
    def pointer(self) -> str:
        return f"{self.sha[:10]}:{self.path}"

    @property
    def place(self) -> str:
        return "attempt" if self.kind.startswith("attempt") else self.kind


@dataclass(frozen=True)
class SourcedEvent:
    event: LedgerEvent
    origin: Origin

    @property
    def src(self) -> str:
        return f"{self.origin.pointer}#{self.event.seq}"


@dataclass(frozen=True)
class VerdictFile:
    folder: str  # the unit folder or fix-unit folder the round belongs to
    round: int
    origin: Origin
    data: dict[str, Any]

    def src(self, pointer: str = "") -> str:
        """`<sha10>:<path>#<json pointer>` (the pointer starts with `/`; empty is the whole file)."""
        return f"{self.origin.pointer}#{pointer}"


@dataclass(frozen=True)
class Skip:
    reason: str
    where: str
    detail: str = ""


@dataclass
class UnitRecord:
    unit_id: str
    framework: str
    name: str
    attempt: int  # 0: the current branch and the base folders; n: `refs/l4/attempts/<fw>/<name>/<n>`
    places: tuple[str, ...]  # a subset of `PLACES`, in that order
    folders: tuple[str, ...]  # the folder names read: the unit's and its fix units'
    events: list[SourcedEvent]  # sorted by (ts, run_id, seq)
    verdicts: list[VerdictFile]  # sorted by (folder, round)


@dataclass(frozen=True)
class LessonRecord:
    lesson: Lesson
    origin: Origin
    archived: bool


@dataclass
class Collected:
    base_ref: str = ""
    base_sha: str | None = None
    base_date: str | None = None
    refs: dict[str, str] = field(default_factory=dict)  # every ref read -> its commit; the manifest's `refs`
    units: list[UnitRecord] = field(default_factory=list)  # sorted by (unit_id, attempt)
    lessons: list[LessonRecord] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)  # reason -> count
    skips: list[Skip] = field(default_factory=list)
    not_local: list[str] = field(default_factory=list)  # attempt refs a `unit.restarted` names that are not local
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Entry:
    mode: str
    kind: str
    oid: str
    size: int
    name: str  # the last path component


@dataclass
class _Slice:
    """What one place holds of one folder, before the places are merged."""

    unit_id: str
    attempt: int
    kind: str
    folder: str
    events: list[SourcedEvent] = field(default_factory=list)
    verdicts: list[VerdictFile] = field(default_factory=list)


def _ls(git: Git, sha: str, path: str) -> list[_Entry]:
    """The entries of a directory (`path` ends in `/`) or the one entry of a file, at commit `sha`."""
    raw = git.run_bytes("ls-tree", "-z", "-l", "--full-tree", sha, "--", path, check=False)
    found = []
    for record in filter(None, raw.split(b"\0")):
        meta, _, name = record.partition(b"\t")
        fields = meta.split()
        if len(fields) != 4:
            continue
        size = int(fields[3]) if fields[3].isdigit() else 0
        text = name.decode("utf-8", "surrogateescape")
        found.append(_Entry(fields[0].decode(), fields[1].decode(), fields[2].decode(), size, text.rsplit("/", 1)[-1]))
    return found


def is_partial_clone(git: Git) -> bool:
    """Whether the repository promises objects it does not hold (`extensions.partialClone` or a promisor remote)."""
    done = git.run("config", "--get-regexp", r"^(extensions\.partialclone|remote\..*\.promisor)$", check=False)
    return any(line.partition(" ")[2].strip() not in ("", "false") for line in done.stdout.splitlines())


def _is_tree(entry: _Entry | None) -> bool:
    return entry is not None and entry.kind == "tree" and entry.mode == "040000"


def _dirs(git: Git, sha: str, path: str) -> list[str]:
    return sorted(e.name for e in _ls(git, sha, f"{path}/") if _is_tree(e))


class _Run:
    """One `collect`: the git handle, the config, and the skips so far."""

    def __init__(self, git: Git, cfg: L4Config) -> None:
        self.git, self.cfg = git, cfg
        self.partial = is_partial_clone(git)  # a blob that is not local is skipped, never fetched
        self.skips: list[Skip] = []
        self.failed: set[str] = set()

    def skip(self, reason: str, where: str, detail: str = "") -> None:
        self.skips.append(Skip(reason, where, detail))

    def failure_reason(self, exc: Exception) -> str:
        """`partial_clone` when git failed in a partial clone (the object is promised, not local, and the lazy fetch
        is off), else `error`."""
        return "partial_clone" if self.partial and isinstance(exc, GitError) else "error"

    # --- one folder ---------------------------------------------------------------------------------------------

    def _blob_ok(self, entry: _Entry, where: str, limit: int) -> bool:
        if entry.mode not in _REGULAR or entry.kind != "blob":
            self.skip("not_regular", where)
            return False
        if entry.size > limit:
            self.skip("oversize", where, f"{entry.size} bytes")
            return False
        return True

    def _ledger_dir(self, sli: _Slice, origin_kind: str, ref: str, sha: str, directory: str) -> None:
        for entry in _ls(self.git, sha, f"{directory}/"):
            if not _RUN_FILE.match(entry.name):
                continue
            path = f"{directory}/{entry.name}"
            if not self._blob_ok(entry, path, MAX_LEDGER_FILE_BYTES):
                continue
            try:
                read = _read_ledger_file(self.git, entry.oid, path, entry.name)
            except LedgerCorrupt as exc:
                self.skip("ledger_corrupt", path, str(exc).removeprefix("ledger corrupt: "))
                continue
            origin = Origin(origin_kind, ref, sha, path)
            sli.events.extend(SourcedEvent(event, origin) for event in read.events)

    def _evidence(self, sli: _Slice, origin_kind: str, ref: str, sha: str, directory: str) -> None:
        for entry in _ls(self.git, sha, f"{directory}/"):
            match = _ROUND.match(entry.name)
            if match is None:
                continue
            where = f"{directory}/{entry.name}"
            if not _is_tree(entry):
                self.skip("not_regular", where)
                continue
            files = [e for e in _ls(self.git, sha, f"{where}/") if e.name == "verdict.json"]
            if not files:
                continue
            path = f"{where}/verdict.json"
            if not self._blob_ok(files[0], path, MAX_VERDICT_BYTES):
                continue
            number = int(match.group(1))
            data = _read_verdict(self.git, files[0].oid, number)
            if data is None:
                self.skip("verdict_unreadable", path)
                continue
            sli.verdicts.append(VerdictFile(sli.folder, number, Origin(origin_kind, ref, sha, path), data))

    def read_folder(self, sli: _Slice, ref: str, sha: str, rel: str) -> None:
        entries = {e.name: e for e in _ls(self.git, sha, f"{rel}/")}
        dot = entries.get(".l4")
        if dot is None:
            return
        if not _is_tree(dot):
            self.skip("not_regular", f"{rel}/.l4")
            return
        inner = {e.name: e for e in _ls(self.git, sha, f"{rel}/.l4/")}
        for name, reader in (("ledger", self._ledger_dir), ("evidence", self._evidence)):
            found = inner.get(name)
            if found is None:
                continue
            if not _is_tree(found):
                self.skip("not_regular", f"{rel}/.l4/{name}")
                continue
            reader(sli, sli.kind, ref, sha, f"{rel}/.l4/{name}")

    def read_pending(self, sli: _Slice, ref: str, sha: str) -> None:
        top = {e.name: e for e in _ls(self.git, sha, f"{PENDING_DIR}/")}
        if top:
            self._ledger_dir(sli, sli.kind, ref, sha, PENDING_DIR)

    # --- the places ---------------------------------------------------------------------------------------------

    def _guarded(self, unit_id: str, make: Callable[..., list[_Slice]], *args: Any) -> list[_Slice]:
        mark = len(self.skips)
        try:
            return make(*args)
        except Exception as exc:  # one unit never fails the build (L4-KG-002)
            log.warning("kg: %s skipped: %s", unit_id, exc)
            del self.skips[mark:]
            self.failed.add(unit_id)
            self.skip(self.failure_reason(exc), unit_id, f"{type(exc).__name__}: {exc}")
            return []

    def _roots(self) -> tuple[str, str]:
        openspec = f"{PurePosixPath(self.cfg.spec.openspec.root)}/changes"
        return openspec, str(PurePosixPath(self.cfg.spec.kiro.root))

    def base_slices(self, ref: str, sha: str) -> list[_Slice]:
        changes, kiro = self._roots()
        found: list[tuple[str, str, str, str]] = []  # (kind, framework, folder name, relative path)
        for name in _dirs(self.git, sha, changes):
            if name != "archive":
                found.append(("base", "openspec", name, f"{changes}/{name}"))
        for dirname in _dirs(self.git, sha, f"{changes}/archive"):
            if (m := _DATED.match(dirname)) is not None:
                found.append(("archive", "openspec", m.group("name"), f"{changes}/archive/{dirname}"))
        for name in _dirs(self.git, sha, kiro):
            found.append(("base", "kiro", name, f"{kiro}/{name}"))
        out: list[_Slice] = []
        for kind, framework, name, rel in sorted(found, key=lambda f: (f[1], f[3])):
            try:
                unit_id = _unit_id(framework, name)
            except ValueError:
                continue
            out.extend(self._guarded(unit_id, self._folder_slice, unit_id, 0, kind, name, ref, sha, rel))
        return out

    def _folder_slice(
        self, unit_id: str, attempt: int, kind: str, name: str, ref: str, sha: str, rel: str
    ) -> list[_Slice]:
        sli = _Slice(unit_id, attempt, kind, name)
        self.read_folder(sli, ref, sha, rel)
        return [sli]

    def unit_slices(self, unit_id: str, attempt: int, kind: str, ref: str, sha: str) -> list[_Slice]:
        """The unit folder and its fix siblings at a branch or attempts commit."""
        framework, name = unit_id.split(":", 1)
        changes, kiro = self._roots()
        parent = kiro if framework == "kiro" else changes
        names = [name, *(n for n in _dirs(self.git, sha, parent) if n.startswith(f"{name}-fix-") and _FIX.match(n))]
        out: list[_Slice] = []
        for folder in names:
            folder_id = unit_id if folder == name else _unit_id(framework, folder)
            out.append(_Slice(folder_id, attempt, kind, folder))
            self.read_folder(out[-1], ref, sha, f"{parent}/{folder}")
        return out

    def lock_slice(self, unit_id: str, attempt: int, kind: str, ref: str, sha: str) -> list[_Slice]:
        sli = _Slice(unit_id, attempt, kind, unit_id.split(":", 1)[1])
        self.read_pending(sli, ref, sha)
        return [sli]

    # --- lessons ------------------------------------------------------------------------------------------------

    def lessons(self, ref: str, sha: str) -> list[LessonRecord]:
        path = self.cfg.memory.lessons_file
        files: list[tuple[str, _Entry, bool]] = [(path, e, False) for e in _ls(self.git, sha, path)]
        archive = f"{PurePosixPath(path).parent}/_archive"
        for entry in sorted(_ls(self.git, sha, f"{archive}/"), key=lambda e: e.name):
            if entry.name.endswith(".md"):
                files.append((f"{archive}/{entry.name}", entry, True))
        found: list[LessonRecord] = []
        for file_path, entry, archived in files:
            if not self._blob_ok(entry, file_path, MAX_LESSONS_BYTES):
                continue
            text = self.git.run_bytes("cat-file", "blob", entry.oid).decode("utf-8", "replace")
            parsed = parse_lessons(text)
            if parsed.problems:
                self.skip("lessons_problem", file_path, f"{len(parsed.problems)} problem(s)")
            origin = Origin("base", ref, sha, file_path)
            found.extend(LessonRecord(lesson, origin, archived) for lesson in parsed.file.lessons)
        return found


def _unit_id(framework: str, name: str) -> str:
    parse_unit_id(f"{framework}:{name}")  # ValueError for a name that is not safe
    return f"{framework}:{name}"


def _read_ledger_file(git: Git, oid: str, path: str, name: str) -> LedgerRead:
    return parse_ledger_files({name: git.run_bytes("cat-file", "blob", oid)})


def _read_verdict(git: Git, oid: str, number: int) -> dict[str, Any] | None:
    try:
        data = json.loads(git.run_bytes("cat-file", "blob", oid))
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") != VERDICT_SCHEMA or data.get("round") != number:
        return None
    return data


# --- the refs -------------------------------------------------------------------------------------------------------


def _base(git: Git, cfg: L4Config) -> tuple[str, str | None, bool]:
    """(ref name, its commit, whether it is the fallback)."""
    ref = f"refs/remotes/{REMOTE}/{cfg.forge.base_branch}"
    sha = git.rev_parse(ref)
    if sha is not None:
        return ref, sha, False
    return "HEAD", git.rev_parse("HEAD"), True


def ref_shas(git: Git, cfg: L4Config) -> dict[str, str]:
    """Every ref `collect` reads, with its commit, sorted by name: the base ref, the unit branches, the lock refs and
    the attempts refs. `store.read_index` compares it with the manifest's `refs` to say `stale`."""
    refs: dict[str, str] = {}
    name, sha, _ = _base(git, cfg)
    if sha is not None:
        refs[name] = sha
    prefix = f"refs/remotes/{REMOTE}/{cfg.forge.branch_prefix}"
    # `for-each-ref` matches a pattern up to a slash, and `*` does not cross one: a prefix such as `l4-` (the config
    # allows it) names no folder, so every `origin` ref is listed and the prefix is applied here (review #9)
    pattern = prefix if prefix.endswith("/") else f"refs/remotes/{REMOTE}/"
    format_ = "--format=%(refname) %(objectname) %(objecttype)"
    out = git.run("for-each-ref", format_, pattern, "refs/l4/locks/", "refs/l4/attempts/").stdout
    for line in out.splitlines():
        parts = line.split(" ")
        if len(parts) != 3 or parts[2] != "commit":
            continue
        if parts[0].startswith(f"refs/remotes/{REMOTE}/") and not parts[0].startswith(prefix):
            continue  # not a unit branch (the base ref is in `refs` already)
        refs[parts[0]] = parts[1]
    return dict(sorted(refs.items()))


# --- collect --------------------------------------------------------------------------------------------------------


def _merge(attempt: int, unit_id: str, slices: list[_Slice], skip: Any) -> UnitRecord:
    framework, name = unit_id.split(":", 1)
    events: dict[tuple[str, int], SourcedEvent] = {}
    verdicts: dict[tuple[str, int], VerdictFile] = {}
    for sli in sorted(slices, key=lambda s: (_PRIORITY[s.kind], s.folder)):
        for sourced in sli.events:
            key = (sourced.event.run_id, sourced.event.seq)
            known = events.get(key)
            if known is None:
                events[key] = sourced
            elif _payload(known.event) != _payload(sourced.event):
                skip("ledger_corrupt", sourced.origin.path, "the places disagree about this event")
        for verdict in sli.verdicts:
            verdicts.setdefault((verdict.folder, verdict.round), verdict)
    places = {("attempt" if s.kind.startswith("attempt") else s.kind) for s in slices}
    return UnitRecord(
        unit_id, framework, name, attempt,
        tuple(p for p in PLACES if p in places),
        tuple(sorted({s.folder for s in slices})),
        sorted(events.values(), key=lambda s: (s.event.ts, s.event.run_id, s.event.seq)),
        [verdicts[k] for k in sorted(verdicts)],
    )  # fmt: skip


def _payload(event: LedgerEvent) -> tuple[Any, ...]:
    return (event.ts, event.type, dict(event.data))


def _restart_refs(units: Iterable[UnitRecord]) -> list[str]:
    found = set()
    for unit in units:
        for sourced in unit.events:
            if sourced.event.type == "unit.restarted":
                ref = sourced.event.data.get("attempt_ref")
                if isinstance(ref, str) and _ATTEMPT_REF.match(ref) and not ref.endswith("-locks"):
                    found.add(ref)
    return sorted(found)


def collect(git: Git, cfg: L4Config) -> Collected:
    """Read every input once. See the module docstring for the places, the skips and the origins."""
    run = _Run(git, cfg)
    out = Collected()
    base_name, base_sha, fallback = _base(git, cfg)
    out.base_ref, out.base_sha = base_name, base_sha
    if base_sha is None:
        out.warnings.append("no base commit was found: only the unit branches, lock refs and attempts refs are read")
    else:
        if fallback:
            out.warnings.append(
                f"the base ref refs/remotes/{REMOTE}/{cfg.forge.base_branch} was not found: HEAD is read instead"
            )
        date = git.run("log", "-1", "--format=%cI", base_sha, check=False).stdout.strip()
        out.base_date = date or None
    if run.partial:
        out.warnings.append(
            "this repository is a partial clone: a unit whose blobs are not local is skipped (partial_clone), "
            "and nothing is fetched"
        )
    refs = ref_shas(git, cfg)
    out.refs = refs
    slices: list[_Slice] = []
    if base_sha is not None:
        slices.extend(run.base_slices(base_name, base_sha))
    branch_prefix = f"refs/remotes/{REMOTE}/{cfg.forge.branch_prefix}"
    for ref, sha in refs.items():
        if ref.startswith(branch_prefix):
            try:
                unit_id = _unit_id(*ref.removeprefix(branch_prefix).split("/", 1))
            except (ValueError, TypeError, IndexError, GitError):
                continue
            slices.extend(run._guarded(unit_id, run.unit_slices, unit_id, 0, "branch", ref, sha))
        elif (m := _LOCK_REF.match(ref)) is not None:
            try:
                unit_id = _unit_id(m.group("fw"), m.group("name"))
            except ValueError:
                continue
            slices.extend(run._guarded(unit_id, run.lock_slice, unit_id, 0, "lock", ref, sha))
        elif (m := _ATTEMPT_REF.match(ref)) is not None:
            try:
                unit_id = _unit_id(m.group("fw"), m.group("name"))
            except ValueError:
                continue
            n = int(m.group("n"))
            if m.group("locks"):
                slices.extend(run._guarded(unit_id, run.lock_slice, unit_id, n, "attempt_lock", ref, sha))
            else:
                slices.extend(run._guarded(unit_id, run.unit_slices, unit_id, n, "attempt", ref, sha))
    slices = [s for s in slices if s.unit_id not in run.failed]
    # a fix-unit folder belongs to its parent when the parent was read
    parents = {s.unit_id for s in slices if _FIX.match(s.unit_id) is None}
    groups: dict[tuple[str, int], list[_Slice]] = {}
    for sli in slices:
        m = _FIX.match(sli.unit_id)
        owner = m.group("parent") if m and m.group("parent") in parents else sli.unit_id
        groups.setdefault((owner, sli.attempt), []).append(sli)
    out.units = [_merge(attempt, uid, group, run.skip) for (uid, attempt), group in sorted(groups.items())]
    if base_sha is not None:
        try:
            out.lessons = sorted(run.lessons(base_name, base_sha), key=lambda r: (r.lesson.id, r.archived))
        except Exception as exc:  # the lessons are one input; the units are read without them
            log.warning("kg: the lessons were not read: %s", exc)
            run.skip(run.failure_reason(exc), cfg.memory.lessons_file, f"{type(exc).__name__}: {exc}")
    for ref in _restart_refs(out.units):
        if ref not in refs:
            out.not_local.append(ref)
            run.skip("attempt_not_local", ref)
    counts: dict[str, int] = {}
    for item in run.skips:
        counts[item.reason] = counts.get(item.reason, 0) + 1
    out.skipped = dict(sorted(counts.items()))
    out.skips = sorted(run.skips, key=lambda s: (s.reason, s.where, s.detail))
    return out
