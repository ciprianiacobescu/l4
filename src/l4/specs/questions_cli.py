"""`l4 questions [list]|show|accept|answer` (L4-QMD-007, L4-QMD-008): the handler named in `commands.HANDLERS`.

Reading never touches the work tree: `questions.md` is read from the fetched unit branch with `git ls-tree` and
`cat-file`, to at most `MAX_QUESTIONS_BYTES`, and a symlink is not read. The edits of `accept` and `answer` are pure
functions over `QuestionsFile` (`edit_accept`, `edit_answer`) and their checks (`check_question`, `check_text`,
`round_trip`); the commit and the push are `unfreeze-and-answer` 4.5.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath

import click

from l4.config.redaction import load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.specs.providers import providers_for
from l4.specs.questions import MAX_QUESTIONS_BYTES, QUESTIONS_FILENAME, Question, QuestionsFile, QuestionStatus
from l4.state.retry import fetch_unit_refs
from l4.state.status import discover
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.names import unit_branch

SCHEMA = "l4/questions@1"
REMOTE = "origin"
_QID = re.compile(r"Q-\d+")
_FIX_NAME = re.compile(r"(?P<parent>.+)-fix-\d+")


@dataclass(frozen=True)
class Refusal:
    """Why a command refuses (exit 2): the cause, and what clears it (`questions: <cause>`, then `Fix: <fix>`)."""

    message: str
    fix: str

    def exit(self) -> L4Exit:
        return L4Exit(ExitCode.USAGE_ERROR, f"questions: {self.message}\nFix: {self.fix}")


def _usage(message: str, fix: str = "l4 questions --help") -> L4Exit:
    return Refusal(message, fix).exit()


# --- reading: the unit branch, never the work tree (D8) ---------------------------------------------------------


@dataclass(frozen=True)
class Folder:
    """One `questions.md` folder as it is at the head of a unit branch: the unit's own, or a fix unit's."""

    unit: str  # the id shown and taken by `--unit`: the unit's, or the fix unit's (`openspec:a-fix-1`)
    parent: str  # the unit whose branch holds the folder
    branch: str
    head: str  # the commit read
    rel: str  # the folder, relative to the repository
    ledger_rel: str  # the folder of the ledger that holds this unit's events (the parent's, for a fix unit)
    phase: str
    fix: str | None  # the fix unit's name; None for the unit itself
    file: QuestionsFile | None
    problem: str | None  # why the file was not read: `questions.md is a symlink on <branch>`, ...

    @property
    def path(self) -> str:
        return f"{self.rel}/{QUESTIONS_FILENAME}"


def read_questions_at(git: Git, ref: str, path: str, branch: str) -> tuple[QuestionsFile | None, str | None]:
    """`questions.md` at `ref`: (file, None); (None, None) when the commit has none; (None, why) for a symlink or any
    entry that is not a regular file, and for one over `MAX_QUESTIONS_BYTES`. A symlink is never read."""
    listing = git.run_bytes("ls-tree", "-z", "-l", ref, "--", path, check=False)
    for record in filter(None, listing.split(b"\0")):
        meta, _, name = record.partition(b"\t")
        fields = meta.split()
        if len(fields) != 4 or name.decode("utf-8", "surrogateescape") != path:
            continue
        mode, kind, oid, size = fields
        if mode == b"120000":
            return None, f"{QUESTIONS_FILENAME} is a symlink on {branch}"
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            return None, f"{QUESTIONS_FILENAME} on {branch} is not a regular file"
        if int(size) > MAX_QUESTIONS_BYTES:
            return None, f"{QUESTIONS_FILENAME} is larger than {MAX_QUESTIONS_BYTES // (1024 * 1024)} MiB on {branch}"
        return QuestionsFile.parse(git.run_bytes("cat-file", "blob", oid.decode())), None
    return None, None


def _fix_folders(git: Git, head: str, rel: str) -> list[str]:
    """The names of the fix unit folders `<unit folder>-fix-<n>` that sit beside the unit's folder on the branch."""
    path = PurePosixPath(rel)
    listing = git.run_bytes(
        "ls-tree", "-z", "-d", "--name-only", "--full-name", head, f"{path.parent.as_posix()}/", check=False
    )
    pattern = re.compile(re.escape(path.name) + r"-fix-\d+")
    names = [PurePosixPath(p.decode("utf-8", "surrogateescape")).name for p in listing.split(b"\0") if p]
    return sorted(name for name in names if pattern.fullmatch(name))


def load_folders(
    app: AppContext, cfg: L4Config, git: Git, unit: str | None, *, fetch: bool = True
) -> tuple[list[Folder], list[str]]:
    """The folders to read and the warnings. Fetches the base branch and the unit refs first (a failure is a warning:
    the tracking refs that exist are read). With `unit`: the unit and its fix units, or one fix unit by its own id.
    Without: every unit that has a branch on `origin`. An unknown unit is a refusal (R1)."""
    warnings: list[str] = []
    if fetch:
        try:
            fetch_unit_refs(app, cfg, git)
        except GitError as exc:
            first = exc.stderr.strip().splitlines()[:1]
            warnings.append(f"not fetched ({first[0] if first else exc}): the questions may be old")
    prefix = cfg.forge.branch_prefix
    rows = [
        (provider, snapshot)
        for provider, snapshot in discover(cfg, git, providers_for(cfg, app.repo, app.environ))
        if snapshot.source != "archive"
    ]
    by_id = {snapshot.ref.id: (provider, snapshot) for provider, snapshot in rows}
    wanted_fix: str | None = None
    if unit is None:
        chosen = [snapshot.ref.id for _, snapshot in rows]
    elif unit in by_id:
        chosen = [unit]
    else:
        match = _FIX_NAME.fullmatch(unit.partition(":")[2])
        parent = f"{unit.partition(':')[0]}:{match.group('parent')}" if match else ""
        if parent not in by_id:
            raise Refusal(f"no unit {unit}", "l4 status lists the units").exit()
        chosen, wanted_fix = [parent], unit.partition(":")[2]
    folders: list[Folder] = []
    for unit_id in chosen:
        provider, snapshot = by_id[unit_id]
        branch = unit_branch(unit_id, prefix)
        head = git.rev_parse(f"refs/remotes/{REMOTE}/{branch}")
        if head is None:
            if unit is not None:
                warnings.append(f"{unit_id} has no branch on {REMOTE}: no question was asked yet")
            continue
        rel = provider.unit_dir(snapshot.ref).resolve().relative_to(git.repo.resolve()).as_posix()
        siblings = _fix_folders(git, head, rel)
        if wanted_fix is not None and wanted_fix not in siblings:
            raise Refusal(f"no unit {unit}", "l4 status lists the units").exit()
        entries = [(None, rel)] if wanted_fix is None else []
        entries += [
            (name, f"{PurePosixPath(rel).parent.as_posix()}/{name}") for name in siblings if wanted_fix in (None, name)
        ]
        for fix, folder in entries:
            file, problem = read_questions_at(git, head, f"{folder}/{QUESTIONS_FILENAME}", branch)
            shown = unit_id if fix is None else f"{unit_id.partition(':')[0]}:{fix}"
            folders.append(Folder(shown, unit_id, branch, head, folder, rel, snapshot.state.phase, fix, file, problem))
    return folders, warnings


# --- list -------------------------------------------------------------------------------------------------------


def _kind(q: Question) -> str:
    return q.kind.value if q.kind is not None else (q.kind_text or "unknown")


def _is_draft(q: Question) -> bool:
    return q.status is QuestionStatus.OPEN and bool(q.answer_text)


def _blocking(q: Question) -> str:
    return ",".join(q.blocking_tasks) or "none"


def _echo(app: AppContext, text: str) -> None:
    click.echo(app.redactor.redact_text(text))


def _folder_warnings(folders: Sequence[Folder]) -> list[str]:
    found = [f"{f.unit}: {f.problem}" for f in folders if f.problem]
    for folder in folders:
        if folder.file is not None:
            found += [
                f"{folder.unit} {qid}: the section cannot be read: it holds every pending task"
                for qid in folder.file.unreadable_ids
            ]
    return found


def run_list(app: AppContext, *, unit: str | None, as_json: bool) -> ExitCode:
    app, cfg = load_app_config(app)
    folders, warnings = load_folders(app, cfg, Git(app.repo, environ=app.environ), unit)
    warnings += _folder_warnings(folders)
    rows = [
        (folder.unit, q)
        for folder in folders
        if folder.file is not None
        for q in folder.file.questions
        if q.status is QuestionStatus.OPEN
    ]
    follow = f"l4 questions show {rows[0][1].id} --unit {rows[0][0]}" if rows else None
    if as_json:
        document = {
            "schema": SCHEMA,
            "questions": [
                {
                    "unit": u, "id": q.id, "kind": _kind(q), "draft": _is_draft(q),
                    "blocking": list(q.blocking_tasks), "title": q.title,
                }
                for u, q in rows
            ],
            "warnings": warnings,
            "next": follow,
        }  # fmt: skip
        _echo(app, json.dumps(document, indent=2, ensure_ascii=False))
        return ExitCode.OK
    out = [f"warning: {w}" for w in warnings]
    out += [f"{u} {q.id} {'draft' if _is_draft(q) else _kind(q)} {_blocking(q)} {q.title}" for u, q in rows]
    out.append(f"Next: {follow}" if follow else "no open question")
    _echo(app, "\n".join(out))
    return ExitCode.OK


# --- the handler ------------------------------------------------------------------------------------------------


def run_questions(
    app: AppContext,
    *,
    words: Sequence[str] = (),
    unit: str | None = None,
    text: str | None = None,
    as_json: bool = False,
    no_push: bool = False,
) -> ExitCode:
    """`l4 questions [list] | show Q | accept Q | answer Q --text T`, with `--unit`, `--json` and `--no-push`."""
    form, rest = (words[0] if words else "list"), tuple(words[1:])
    if form == "list" and not rest:
        return run_list(app, unit=unit, as_json=as_json)
    raise _usage(f"unknown form: {' '.join(words)}")
