"""The fixture-repository builder of the experience graph tests (tasks 2.1; L4-KG-001, L4-KG-004), shared by every wave.

A test asks for the `kg_repo` fixture and gets a `KgRepo`: a real git repository (`root`) with a bare `origin`, one
commit on `main`, and a second clone (`stage`) that the builder uses to write what the harness would have pushed.
Nothing is faked below the file level: ledgers are written by the real `LedgerWriter` (so `run.started` and
`run.finished` are there and `seq` and `ts` rise), `verdict.json` by the real `verdict_json`, the lock ref by the real
`PendingLedger`, `lessons.md` by the real `render_lessons`. Time is a counter, so a fixture builds the same bytes
(apart from the harness commit id that `run.started` records) every time.

API (every method returns the commit sha it made, unless it says otherwise):

    kg_repo.unit(unit_id, *, where="base", date="2026-10-05", runs=(), verdicts=(), tasks=("1.1 first task",),
                 capability="cart", fix=None, files=None, push=True)
        Writes one unit folder and what the harness keeps in it, and commits it. `where` is
        - "base":      `openspec/changes/<name>/` (or `.kiro/specs/<name>/`) on `main`, an open unit;
        - "archive":   `openspec/changes/archive/<date>-<name>/` on `main` (OpenSpec only);
        - "branch":    the folder on the unit branch `l4/<fw>/<name>` (cut from `main` the first time);
        - "attempt:N": the folder on a side commit that `refs/l4/attempts/<fw>/<name>/N` names. `push=False` leaves
                       the ref on `origin` only, so it is not local (SCN-KG-09).
        `runs` are `Run` values (`kg_repo.run(...)`), `verdicts` are `Verdict` values (`kg_repo.verdict(...)`).
        `fix=N` writes the sibling folder `<name>-fix-N` instead of the unit folder. `files` adds raw files
        (`{path: str | bytes | Symlink(target) | None}`; `None` deletes), relative to the repository root.
    kg_repo.run(*events, run_id=None, exit_code=0)
        One run: `events` are `(type, data)` pairs written between `run.started` and `run.finished`.
    kg_repo.verdict(round, verdict="FAIL", *, findings=(), criteria=(), gates=(), judge_profile="",
                    implementer_profiles=())
        One `round-<round>/verdict.json`. `kg_repo.finding(title, ...)`, `kg_repo.criterion(alias, ...)` and
        `kg_repo.gate(name, ...)` build the rows with the real verifier types.
    kg_repo.pending(unit_id, *events, run_id=None)
        Publishes a run file to the lock ref `refs/l4/locks/<fw>/<name>` (local and on `origin`), as the harness
        does after the hand-off commit; the unit branch does not hold it.
    kg_repo.restart_event(unit_id, n, *, reason="restart")
        The `("unit.restarted", {...})` pair whose `attempt_ref` is `refs/l4/attempts/<fw>/<name>/<n>`.
    kg_repo.lessons(*lessons, archive=None, text=None, where="main")
        Writes `memory.lessons_file` (or `_archive/<archive>.md`) with the canonical writer, or `text` as it is.
    kg_repo.lesson(title, dedupe_key, *, body=..., scope=(), ...)
        A `Lesson` whose id is `lesson_id(dedupe_key)`.
    kg_repo.commit(branch, files, message)
        The raw primitive: `files` as in `unit`, committed on `branch` of `origin` (created from `main` when new).

State and views:
    kg_repo.root, .origin, .stage, .cache, .environ, .cfg (`L4Config()` defaults), .git (a real `Git` on root),
    kg_repo.app() (an `AppContext` whose environ holds `L4_CACHE=<cache>`, outside the repository),
    kg_repo.recording_git(allowed=READ_ONLY) (a `RecordingGit` on root), kg_repo.refs() (every ref and its sha),
    kg_repo.status() (`git status --porcelain`), kg_repo.sha(ref), kg_repo.unit_path(unit_id, where, ...).

`RecordingGit` keeps every argv like `Git`, and raises `AssertionError` on a subcommand outside `READ_ONLY`
(`rev-parse`, `for-each-ref`, `ls-tree`, `cat-file`, `log`, `diff --name-only`, `check-ignore`, `ls-files`, `var`),
so a test that runs a command through it also proves the command is read-only and never fetches (L4-KG-001).
`subcommands` lists the subcommands run, in order.
"""

import hashlib
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

import pytest

from l4.config.schema import L4Config
from l4.context import AppContext
from l4.memory.curate import ARCHIVE_DIR
from l4.memory.lessons import Lesson, LessonsFile, lesson_id, render_lessons
from l4.redact import Redactor
from l4.state.ledger import LedgerWriter
from l4.state.pending import PendingLedger
from l4.vcs.git import Git
from l4.verifier.report import verdict_json
from l4.verifier.types import CriterionOutcome, Finding, GateLine, Severity, Verdict, VerifyResult

READ_ONLY = frozenset({"rev-parse", "for-each-ref", "ls-tree", "cat-file", "log", "check-ignore", "ls-files", "var"})
_EPOCH = datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)
_IDENT = ("-c", "user.name=t", "-c", "user.email=t@example.invalid")


@dataclass(frozen=True)
class Symlink:
    """A file value for `commit`/`unit(files=...)`: the path is a symbolic link to `target`."""

    target: str


@dataclass(frozen=True)
class Run:
    events: tuple[tuple[str, dict], ...] = ()
    run_id: str | None = None
    exit_code: int = 0


@dataclass(frozen=True)
class VerdictRow:
    round: int
    verdict: str = "FAIL"
    findings: tuple[Finding, ...] = ()
    criteria: tuple[CriterionOutcome, ...] = ()
    gates: tuple[GateLine, ...] = ()
    judge_profile: str = ""
    implementer_profiles: tuple[str, ...] = ()
    raw: bytes | None = None  # written as it is, for a corrupt or foreign verdict file


class RecordingGit(Git):
    """`Git` that refuses what a read-only command must never run. `history` holds the full argv as in `Git`;
    `subcommands` holds only the subcommand of each call."""

    def __init__(self, repo: Path, *, environ: Mapping[str, str], allowed: frozenset[str] = READ_ONLY) -> None:
        super().__init__(repo, environ=environ)
        self.allowed = allowed
        self.subcommands: list[str] = []

    def at(self, repo: Path) -> "RecordingGit":
        other = RecordingGit(repo, environ=self.env, allowed=self.allowed)
        other.history, other.subcommands = self.history, self.subcommands
        return other

    def _argv(self, args: Sequence[str], config: Sequence[tuple[str, str]]) -> list[str]:
        sub = args[0] if args else ""
        if sub == "diff":
            if "--name-only" not in args:
                raise AssertionError(f"git diff without --name-only is not allowed here: {list(args)}")
        elif sub not in self.allowed:
            raise AssertionError(f"git {sub} is not allowed here: {list(args)}")
        self.subcommands.append(sub)
        return super()._argv(args, config)


class KgRepo:
    def __init__(self, tmp_path: Path, environ: dict[str, str], root: Path, origin: Path) -> None:
        self.root, self.origin, self.environ = root, origin, environ
        self.tmp = tmp_path
        self.cache = tmp_path / "kg-cache"
        self.cfg = L4Config()
        self.git = Git(root, environ=environ)
        self.stage = tmp_path / "stage"
        self._raw(tmp_path, "clone", "-q", str(origin), str(self.stage))
        self._ticks = 0
        self._runs = 0
        self._builds = 0
        self._built: dict[tuple, bytes] = {}
        self.base_branch = self.cfg.forge.base_branch
        self.prefix = self.cfg.forge.branch_prefix

    # --- plain git for setup (production code never does this; it uses Git) ---------------------------------------

    def _raw(self, cwd: Path, *args: str) -> str:
        done = subprocess.run(
            ["git", *_IDENT, "-c", "init.defaultBranch=main", *args],
            cwd=cwd, env=self.environ, capture_output=True, text=True, check=True,
        )  # fmt: skip
        return done.stdout

    def sha(self, ref: str) -> str:
        return self._raw(self.root, "rev-parse", ref).strip()

    def refs(self) -> dict[str, str]:
        out = self._raw(self.root, "for-each-ref", "--format=%(refname) %(objectname)")
        return dict(line.split(" ", 1) for line in out.splitlines())

    def status(self) -> str:
        return self._raw(self.root, "status", "--porcelain")

    def app(self, **environ: str) -> AppContext:
        return AppContext(
            repo=self.root, config_path=None, log_format="human", verbosity=0, run_id="r-20261001T0800Z-0000",
            environ={**self.environ, "L4_CACHE": str(self.cache), **environ}, redactor=Redactor({}),
        )  # fmt: skip

    def recording_git(self, allowed: frozenset[str] = READ_ONLY) -> RecordingGit:
        return RecordingGit(self.root, environ=self.environ, allowed=allowed)

    # --- rows -------------------------------------------------------------------------------------------------------

    def _clock(self) -> datetime:
        self._ticks += 1
        return _EPOCH + timedelta(seconds=self._ticks)

    def _run_id(self) -> str:
        self._runs += 1
        stamp = _EPOCH + timedelta(minutes=self._runs)
        return f"r-{stamp:%Y%m%dT%H%M}Z-{self._runs:04x}"

    @staticmethod
    def run(*events: tuple[str, dict], run_id: str | None = None, exit_code: int = 0) -> Run:
        return Run(tuple(events), run_id, exit_code)

    @staticmethod
    def finding(
        title: str,
        *,
        severity: str = "major",
        source: str = "deterministic",
        criterion: str | None = None,
        spec_gap: bool = False,
        detail: str = "detail",
    ) -> Finding:
        return Finding(Severity(severity), title, detail, source, criterion, spec_gap=spec_gap)  # type: ignore[arg-type]

    @staticmethod
    def criterion(alias: str, *, id: str | None = None, result: str = "fail", reason: str = "") -> CriterionOutcome:
        cid = id or "C-" + hashlib.sha256(alias.encode()).hexdigest()[:8]
        return CriterionOutcome(cid, alias, result, None, reason)  # type: ignore[arg-type]

    @staticmethod
    def gate(name: str, *, status: str = "fail", reason: str = "") -> GateLine:
        return GateLine(name, name, status, reason, None)  # type: ignore[arg-type]

    @staticmethod
    def verdict(
        round: int,
        verdict: str = "FAIL",
        *,
        findings: Sequence[Finding] = (),
        criteria: Sequence[CriterionOutcome] = (),
        gates: Sequence[GateLine] = (),
        judge_profile: str = "",
        implementer_profiles: Sequence[str] = (),
        raw: bytes | None = None,
    ) -> VerdictRow:
        return VerdictRow(
            round, verdict, tuple(findings), tuple(criteria), tuple(gates), judge_profile,
            tuple(implementer_profiles), raw,
        )  # fmt: skip

    @staticmethod
    def lesson(
        title: str,
        dedupe_key: str,
        *,
        body: str = "Use the helper.",
        scope: Sequence[str] = (),
        source: str = "verifier round 1",
        reinforced: int = 1,
    ) -> Lesson:
        return Lesson(
            lesson_id(dedupe_key), title, dedupe_key, body, tuple(scope), (), source, None, reinforced, None
        )  # fmt: skip

    def restart_event(self, unit_id: str, n: int, *, reason: str = "restart") -> tuple[str, dict]:
        framework, name = unit_id.split(":", 1)
        return (
            "unit.restarted",
            {"attempt": n, "previous_head": "0" * 40, "reason": reason,
             "attempt_ref": f"refs/l4/attempts/{framework}/{name}/{n}"},
        )  # fmt: skip

    # --- paths ------------------------------------------------------------------------------------------------------

    def unit_path(self, unit_id: str, where: str = "base", *, date: str = "2026-10-05", fix: int | None = None) -> str:
        """The unit folder, relative to the repository root, for a `where` of `unit`."""
        framework, name = unit_id.split(":", 1)
        folder = f"{name}-fix-{fix}" if fix else name
        if framework == "kiro":
            return f"{PurePosixPath(self.cfg.spec.kiro.root)}/{folder}"
        changes = f"{PurePosixPath(self.cfg.spec.openspec.root)}/changes"
        return f"{changes}/archive/{date}-{folder}" if where == "archive" else f"{changes}/{folder}"

    def branch_of(self, unit_id: str) -> str:
        framework, name = unit_id.split(":", 1)
        return f"{self.prefix}{framework}/{name}"

    # --- the builders -----------------------------------------------------------------------------------------------

    def _spec_files(self, unit_id: str, rel: str, tasks: Sequence[str], capability: str) -> dict[str, object]:
        body = "# Tasks\n\n" + "".join(f"- [ ] {t}\n" for t in tasks)
        files: dict[str, object] = {f"{rel}/tasks.md": body}
        if unit_id.startswith("kiro:"):
            files[f"{rel}/requirements.md"] = "# Requirements\n\n1.1 The cart shows a count.\n"
        else:
            files[f"{rel}/proposal.md"] = "## Why\n\nA reason.\n"
            files[f"{rel}/specs/{capability}/spec.md"] = (
                "## ADDED Requirements\n\n### Requirement: Cart\n\n#### Scenario: Shows count\n- **WHEN** a\n"
            )
        return files

    def _ledger_file(self, unit_id: str, rel: str, run: Run) -> tuple[str, bytes]:
        run_id = run.run_id or self._run_id()
        key = (unit_id, run_id, repr(run.events))
        if run.run_id is not None and key in self._built:  # the same run written to a second place: the same bytes
            return f"{rel}/.l4/ledger/{run_id}.jsonl", self._built[key]
        self._builds += 1
        work = self.tmp / "ledger-build" / f"{self._builds}-{run_id}"
        unit_dir = work / "unit"
        writer = LedgerWriter.open(unit_dir, unit_id, run_id, redactor=Redactor({}), clock=self._clock)
        for kind, data in run.events:
            writer.append(kind, **data)
        writer.finish(run.exit_code)
        assert writer.path is not None
        data = writer.path.read_bytes()
        self._built[key] = data
        return f"{rel}/.l4/ledger/{run_id}.jsonl", data

    @staticmethod
    def _verdict_file(rel: str, unit_id: str, v: VerdictRow) -> tuple[str, bytes]:
        path = f"{rel}/.l4/evidence/round-{v.round}/verdict.json"
        if v.raw is not None:
            return path, v.raw
        result = VerifyResult(
            unit_id, v.round, Verdict(v.verdict), "b" * 40, "c" * 40, gates=list(v.gates), criteria=list(v.criteria),
            findings=list(v.findings), judge_profile=v.judge_profile, implementer_profiles=list(v.implementer_profiles),
        )  # fmt: skip
        import json

        return path, (json.dumps(verdict_json(result), sort_keys=True) + "\n").encode()

    def commit(self, branch: str, files: Mapping[str, object], message: str = "fixture") -> str:
        """Commit `files` on `branch` of origin (created from the base branch when new), push, and fetch the heads."""
        stage = self.stage
        self._raw(stage, "fetch", "-q", "origin")
        start = f"origin/{branch}" if self._has_remote_branch(branch) else f"origin/{self.base_branch}"
        self._raw(stage, "checkout", "-q", "-B", branch, start)
        self._write(stage, files)
        self._raw(stage, "add", "-A")
        self._raw(stage, "commit", "-q", "--allow-empty", "-m", message)
        sha = self._raw(stage, "rev-parse", "HEAD").strip()
        self._raw(stage, "push", "-q", "--force", "origin", f"HEAD:refs/heads/{branch}")
        self._raw(self.root, "fetch", "-q", "origin")
        return sha

    def _has_remote_branch(self, branch: str) -> bool:
        out = self._raw(self.stage, "ls-remote", "--heads", "origin", branch)
        return bool(out.strip())

    @staticmethod
    def _write(base: Path, files: Mapping[str, object]) -> None:
        for path, value in files.items():
            target = base / path
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir() and not isinstance(value, Mapping):
                import shutil

                shutil.rmtree(target)
            if value is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(value, Symlink):
                os.symlink(value.target, target)
            elif isinstance(value, bytes):
                target.write_bytes(value)
            else:
                target.write_text(str(value), encoding="utf-8")

    def unit(
        self,
        unit_id: str,
        *,
        where: str = "base",
        date: str = "2026-10-05",
        runs: Sequence[Run] = (),
        verdicts: Sequence[VerdictRow] = (),
        tasks: Sequence[str] = ("1.1 first task",),
        capability: str = "cart",
        fix: int | None = None,
        files: Mapping[str, object] | None = None,
        push: bool = True,
    ) -> str:
        rel = self.unit_path(unit_id, where, date=date, fix=fix)
        built: dict[str, object] = self._spec_files(unit_id, rel, tasks, capability)
        for run in runs:
            path, data = self._ledger_file(unit_id, rel, run)
            built[path] = data
        for v in verdicts:
            path, data = self._verdict_file(rel, unit_id, v)
            built[path] = data
        built.update(files or {})
        message = f"unit {unit_id} ({where})"
        if where in ("base", "archive"):
            return self.commit(self.base_branch, built, message)
        if where == "branch":
            return self.commit(self.branch_of(unit_id), built, message)
        if where.startswith("attempt:"):
            return self._attempt(unit_id, int(where.split(":", 1)[1]), built, message, push=push)
        raise ValueError(f"unknown where: {where!r}")

    def _attempt(self, unit_id: str, n: int, files: Mapping[str, object], message: str, *, push: bool) -> str:
        framework, name = unit_id.split(":", 1)
        ref = f"refs/l4/attempts/{framework}/{name}/{n}"
        sha = self.commit(f"attempt-tmp/{framework}/{name}/{n}", files, message)
        self._raw(self.stage, "push", "-q", "--force", "origin", f"{sha}:{ref}")
        self._raw(self.stage, "push", "-q", "origin", f":refs/heads/attempt-tmp/{framework}/{name}/{n}")
        self._raw(self.root, "fetch", "-q", "--prune", "origin")
        if push:
            self._raw(self.root, "fetch", "-q", "origin", f"+{ref}:{ref}")
        return sha

    def pending(self, unit_id: str, *events: tuple[str, dict], run_id: str | None = None) -> str:
        """A run file in the lock ref of the unit, published by the real `PendingLedger`."""
        framework, name = unit_id.split(":", 1)
        rel = self.unit_path(unit_id)
        run = Run(tuple(events), run_id)
        path, data = self._ledger_file(unit_id, rel, run)
        out = self.tmp / "pending-build" / Path(path).name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        ledger = PendingLedger(
            self.git, lock_ref=f"refs/l4/locks/{framework}/{name}", unit=unit_id, run_id=Path(path).stem,
            holder="fixture",
        )  # fmt: skip
        return ledger.publish(out)

    def lessons(
        self, *lessons: Lesson, archive: str | None = None, text: str | None = None, where: str = "main"
    ) -> str:
        """`memory.lessons_file` (or `_archive/<archive>.md` beside it), on `where` (a branch of origin)."""
        lessons_file = self.cfg.memory.lessons_file
        path = (
            lessons_file if archive is None else str(PurePosixPath(lessons_file).parent / ARCHIVE_DIR / f"{archive}.md")
        )
        content = text if text is not None else render_lessons(LessonsFile(list(lessons)))
        return self.commit(where, {path: content}, f"lessons {archive or ''}".strip())


@pytest.fixture
def kg_repo(make_repo: Callable[..., Path], tmp_path: Path, git_environ: dict[str, str]) -> KgRepo:
    root = make_repo("kgrepo", remote=True)
    origin = tmp_path / "kgrepo-origin.git"
    return KgRepo(tmp_path, git_environ, root, origin)
