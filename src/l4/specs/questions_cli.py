"""`l4 questions [list]|show|accept|answer` (L4-QMD-007, L4-QMD-008): the handler named in `commands.HANDLERS`.

Reading never touches the work tree: `questions.md` is read from the fetched unit branch with `git ls-tree` and
`cat-file`, to at most `MAX_QUESTIONS_BYTES`, and a symlink is not read. The edits of `accept` and `answer` are pure
functions over `QuestionsFile` (`edit_accept`, `edit_answer`) and their checks (`check_question`, `check_text`,
`round_trip`); the commit and the push are `write_edit`.
"""

import difflib
import json
import logging
import re
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import click

from l4.actor import actor
from l4.config.defaults import cache_root
from l4.config.redaction import load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import fetch_auth_config, make_forge
from l4.forge.gitlab import push_auth_config
from l4.forge.pushfail import explain_push_failure, push_platform
from l4.forge.urls import origin_url
from l4.implementer.guards import IGNORE_FILE_GLOBS, tracked_files
from l4.implementer.unfreeze import MAX_PATHS_PER_QUESTION, names_path
from l4.redact import Redactor
from l4.security.protected import glob_match
from l4.specs.providers import providers_for
from l4.specs.questions import (
    _FENCE,
    _FIELD,
    _STRUCTURAL,
    _SUBHEADING,
    MAX_QUESTIONS_BYTES,
    QUESTIONS_FILENAME,
    Question,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    accept_text,
    effective_answer,
    harness_decision,
    option_suggestion,
    unescape_text,
)
from l4.state.ledger import MAX_LEDGER_FILE_BYTES, LedgerCorrupt, LedgerEvent, parse_ledger_files
from l4.state.lifecycle import Phase
from l4.state.liveness import LazyForge, ended_why
from l4.state.pending import live_run, merge_ledgers, read_pending
from l4.state.retry import fetch_unit_refs, how_to_start, start_run_line
from l4.state.status import _activity, discover
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.names import lock_ref, unit_branch
from l4.vcs.push import PushRejected
from l4.vcs.tree import regular_blobs
from l4.verifier.verdicts import _DECISION, SPEC_GAP_NOTE, parse_answer
from l4.yolo.accept import target_full_config
from l4.yolo.state import parse_time

SCHEMA = "l4/questions@1"
REMOTE = "origin"
CONFIG_PATH = ".l4/config.yaml"
log = logging.getLogger("l4.questions")
_QID = re.compile(r"Q-\d+")
MAX_TEXT_CHARS = 20_000  # [G] a chosen limit: an answer is read into the next prompt
_FIX_NAME = re.compile(r"(?P<parent>.+)-fix-\d+")


@dataclass(frozen=True)
class Refusal:
    """Why a command refuses (exit 2): the cause, and what clears it (`questions: <cause>`, then `Fix: <fix>`)."""

    message: str
    fix: str

    def exit(self) -> L4Exit:
        return L4Exit(ExitCode.USAGE_ERROR, f"questions: {self.message}\nFix: {self.fix}")


_REPLACEABLE = (QuestionStatus.ANSWERED, QuestionStatus.ACCEPTED)  # a verdict answer `answer --replace` may replace


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


def folder_from_worktree(
    git: Git, worktree: Path, unit: str, unit_rel: str, ledger_rel: str, branch: str, phase: str, fix: str | None
) -> Folder:
    """The folder of a unit as the run's own worktree holds it at `HEAD` (the delegate's edit core, L4-DLG-006): the
    same `Folder` that `load_folders` builds from the fetched branch, read with `read_questions_at`, with `head` the
    commit the run stands on. `unit` is the id shown (a fix unit's own for a fix), `unit_rel` the folder that holds
    `questions.md` and `ledger_rel` the folder of the ledger (the parent unit's for a fix unit)."""
    here = git.at(worktree)
    head = here.rev_parse("HEAD")
    if head is None:
        raise Refusal(f"{worktree} has no commit", "the run's worktree starts at the unit branch").exit()
    file, problem = read_questions_at(here, head, f"{unit_rel}/{QUESTIONS_FILENAME}", branch)
    match = _FIX_NAME.fullmatch(unit.partition(":")[2]) if fix is not None else None
    parent = f"{unit.partition(':')[0]}:{match.group('parent')}" if match else unit
    return Folder(unit, parent, branch, head, unit_rel, ledger_rel, phase, fix, file, problem)


def _fix_folders(git: Git, head: str, rel: str) -> list[str]:
    """The names of the fix unit folders `<unit folder>-fix-<n>` that sit beside the unit's folder on the branch."""
    path = PurePosixPath(rel)
    listing = git.run_bytes(
        "ls-tree", "-z", "-d", "--name-only", "--full-name", head, f"{path.parent.as_posix()}/", check=False
    )
    pattern = re.compile(re.escape(path.name) + r"-fix-\d+")
    names = [PurePosixPath(p.decode("utf-8", "surrogateescape")).name for p in listing.split(b"\0") if p]
    return sorted(name for name in names if pattern.fullmatch(name))


def _holds_fix_folder(git: Git, row: tuple, prefix: str, name: str) -> bool:
    """Whether the parent's branch on `origin` holds the folder of the fix unit `name` beside its own."""
    provider, snapshot = row
    head = git.rev_parse(f"refs/remotes/{REMOTE}/{unit_branch(snapshot.ref.id, prefix)}")
    if head is None:
        return False
    rel = provider.unit_dir(snapshot.ref).resolve().relative_to(git.repo.resolve()).as_posix()
    return name in _fix_folders(git, head, rel)


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
    match = _FIX_NAME.fullmatch(unit.partition(":")[2]) if unit is not None else None
    parent = f"{unit.partition(':')[0]}:{match.group('parent')}" if unit is not None and match else ""
    if unit is None:
        chosen = [snapshot.ref.id for _, snapshot in rows]
    elif unit in by_id and git.rev_parse(f"refs/remotes/{REMOTE}/{unit_branch(unit, prefix)}") is not None:
        chosen = [unit]  # a unit with a branch of its own
    elif parent in by_id and _holds_fix_folder(git, by_id[parent], prefix, unit.partition(":")[2]):
        chosen, wanted_fix = [parent], unit.partition(":")[2]  # a fix unit has no branch: its folder is its parent's
    elif unit in by_id:
        chosen = [unit]  # a unit that merely is named like a fix unit and has no branch yet: the usual warning
    else:
        raise Refusal(f"no unit {unit}", "l4 status lists the units").exit()
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
    hint = _delegate_hint(app, cfg, folders)
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
            "delegate_hint": hint,
        }  # fmt: skip
        _echo(app, json.dumps(document, indent=2, ensure_ascii=False))
        return ExitCode.OK
    out = [f"warning: {w}" for w in warnings]
    out += [f"{u} {q.id} {'draft' if _is_draft(q) else _kind(q)} {_blocking(q)} {q.title}" for u, q in rows]
    out.append(f"Next: {follow}" if follow else "no open question")
    out += [hint] if hint else []
    _echo(app, "\n".join(out))
    return ExitCode.OK


def _delegate_hint(app: AppContext, cfg: L4Config, folders: Sequence[Folder]) -> str | None:
    """The `Hint:` line of L4-DLG-021, once: the first listed folder that waits on a question the delegate could
    answer. The base branch and the plans are read only when some folder is open and waiting."""
    from l4.delegate.due import escalations
    from l4.delegate.hint import HintReader

    git = Git(app.repo, environ=app.environ)
    reader = HintReader(git, cfg)
    for folder in folders:
        if folder.file is None:
            continue
        open_qs = [q for q in folder.file.questions if q.status is QuestionStatus.OPEN]
        if open_qs:  # one the delegate escalated for its current raise is final: it would never ask again
            events, _warning = folder_events(git, folder)
            prefix = f"{folder.fix}/" if folder.fix else ""
            gone = {key for key, _, _ in escalations(events, [f"{prefix}{q.id}" for q in open_qs])}
            open_qs = [q for q in open_qs if f"{prefix}{q.id}" not in gone]
        kinds = [_kind(q) for q in open_qs]
        if hint := reader.hint(folder.parent, folder.phase, kinds, fix_of=folder.parent if folder.fix else None):
            return hint
    return None


# --- what the ledger and the project's rules say about a question -----------------------------------------------


def folder_events(git: Git, folder: Folder) -> tuple[list[LedgerEvent], str | None]:
    """The events of the unit's ledger at the folder's head, with the pending ledger of its lock ref (a fix unit's
    events are in the parent's ledger). A ledger that does not read gives no events and a warning."""
    try:
        blobs = regular_blobs(git, folder.head, f"{folder.ledger_rel}/.l4/ledger/", MAX_LEDGER_FILE_BYTES)
        files = {
            blob.path.rsplit("/", 1)[-1]: git.run_bytes("cat-file", "blob", blob.oid)
            for blob in blobs
            if blob.path.endswith(".jsonl")
        }
        read = merge_ledgers(parse_ledger_files(files), read_pending(git, lock_ref(folder.parent)))
    except LedgerCorrupt as exc:
        return [], f"{folder.unit}: the ledger cannot be read ({exc}): no frozen path is shown"
    return list(read.events), None


def frozen_paths(events: Sequence[LedgerEvent], tasks: Sequence[str], fix: str | None) -> dict[str, tuple[str, ...]]:
    """Per held task, the `frozen` paths of its latest `task.red_ok` (of the fix unit's own context for a fix unit)."""
    found: dict[str, tuple[str, ...]] = {}
    for event in events:
        task = event.data.get("task")
        if event.type == "task.red_ok" and task in tasks and (event.data.get("fix_unit") or None) == fix:
            found[str(task)] = tuple(str(f) for f in event.data.get("frozen") or [])
    return found


def existing_tests(
    git: Git, folder: "Folder", cfg: L4Config, question: Question, frozen: Mapping[str, Sequence[str]]
) -> dict[str, tuple[str, ...]]:
    """Per held task that has a red commit, the tracked test files at the folder's head that the question or its answer
    names and that its frozen list does not hold: a pre-existing test that red did not touch, which an answer that
    names it opens for green (`implementer.unfreeze.unfrozen`)."""
    tasks = [t for t in question.blocking_tasks if t in frozen]
    if not tasks or not folder.head:
        return {}
    text = "\n".join(
        unescape_text(part)
        for part in (question.title, question.context_text, question.options_text, question.suggestion_text)
    )
    text += "\n" + (effective_answer(question) or "")
    try:
        listed = tracked_files(git.run_bytes("ls-tree", "-r", "-z", folder.head))
    except GitError:
        return {}
    globs = cfg.tdd.test_globs
    support = (*cfg.tdd.test_support_globs, *IGNORE_FILE_GLOBS)
    named = sorted(
        p
        for p, regular in listed
        if regular and p in text and any(glob_match(g, p) for g in globs) and not any(glob_match(g, p) for g in support)
    )
    return {t: tuple(p for p in named if p not in frozen[t]) for t in tasks}


@dataclass(frozen=True)
class PathEffect:
    """What an accepted suggestion does to one frozen path of a held task (design D7)."""

    task: str
    path: str
    unfreezes: bool
    why: str  # when it stays frozen: the reason
    existing: bool = False  # a pre-existing test of the repository, not a file of the task's red step


def _is_ignore_file(path: str) -> bool:
    return any(glob_match(glob, path) for glob in IGNORE_FILE_GLOBS)


def suggestion_effects(
    question: Question, frozen: Mapping[str, Sequence[str]], existing: Mapping[str, Sequence[str]] | None = None
) -> list[PathEffect]:
    """The frozen paths of the held tasks that the suggestion names, and whether an accepted suggestion unfreezes each
    (the rule of `implementer.unfreeze.unfrozen` for an `accepted` question): a support or test file that the question
    itself (title, Context, Options) names too opens, an ignore file stays frozen, at most
    `MAX_PATHS_PER_QUESTION` per question. A verdict question unfreezes nothing. `existing`: per task, the
    pre-existing tracked test files (`existing_tests`), which open the same way. The suggestion is what `accept` takes
    (`accept_text`, L4-QMD-008): the written block, else option 1 of an open technical question."""
    text = accept_text(question)
    if question.kind is QuestionKind.VERDICT or not text:
        return []
    old = existing or {}
    frozen = {t: (*frozen[t], *old.get(t, ())) for t in frozen}
    asked = "\n".join((question.title, unescape_text(question.context_text), unescape_text(question.options_text)))
    tasks = [t for t in question.blocking_tasks if t in frozen]
    named = sorted({p for t in tasks for p in frozen[t] if names_path(text, p)})
    verdict: dict[str, tuple[bool, str]] = {}
    opened = 0
    for path in named:
        if _is_ignore_file(path):
            verdict[path] = (False, "an ignore file")
        elif not names_path(asked, path):
            verdict[path] = (False, "the question does not name it")
        elif opened >= MAX_PATHS_PER_QUESTION:
            verdict[path] = (False, f"more than {MAX_PATHS_PER_QUESTION} paths named")
        else:
            opened += 1
            verdict[path] = (True, "")
    return [
        PathEffect(t, p, *verdict[p], existing=p in old.get(t, ()))
        for t in tasks
        for p in sorted(frozen[t])
        if p in verdict
    ]


@dataclass(frozen=True)
class ClarifierRules:
    """`clarifier.auto_accept_kinds` and `clarifier.answer_by_agents`, as the base branch has them (D11)."""

    auto_accept_kinds: tuple[str, ...] = ("technical",)
    answer_by_agents: bool = False


def clarifier_rules(git: Git, base: str) -> ClarifierRules:
    """Both keys from `.l4/config.yaml` at `refs/remotes/origin/<base>`, never from the unit branch (an agent cannot
    set them there). The defaults apply when the file is absent or is not a valid config (the reason is logged)."""
    full = target_full_config(git, f"refs/remotes/{REMOTE}/{base}")
    if full is None:
        return ClarifierRules()
    return ClarifierRules(tuple(full.clarifier.auto_accept_kinds), full.clarifier.answer_by_agents)


AGENT_FIX = (
    "a person runs the command, or set clarifier.answer_by_agents: true in .l4/config.yaml on {base} "
    "(a pushed change a person can see)"
)


def agent_reason(
    question: Question, effective: str | None, frozen: Mapping[str, Sequence[str]], rules: ClarifierRules
) -> str | None:
    """Why an agent may not write `question` (design D11, L4-QMD-009), or None. `effective` is the text it would
    write: the suggestion for `accept`, the `--text` for `answer`; None skips the check of frozen paths."""
    if rules.answer_by_agents:
        return None
    if question.kind is QuestionKind.VERDICT:
        return "a verdict answer is a person's decision"
    if question.kind is QuestionKind.HARNESS:
        return "a harness override is a person's decision"
    kind = question.kind.value if question.kind is not None else question.kind_text or "unknown"
    if kind not in rules.auto_accept_kinds:
        return f"its kind is {kind}, and clarifier.auto_accept_kinds is [{', '.join(rules.auto_accept_kinds)}]"
    if effective is not None:
        for task in question.blocking_tasks:
            for path in frozen.get(task, ()):
                if names_path(effective, path):
                    noun = "suggestion" if effective == accept_text(question) else "text"
                    return f"the {noun} names the frozen path {path} of task {task}"
    return None


def check_agent(
    form: str,
    question: Question,
    effective: str | None,
    frozen: Mapping[str, Sequence[str]],
    rules: ClarifierRules,
    base: str,
) -> Refusal | None:
    """R11: the agent rule as a refusal."""
    why = agent_reason(question, effective, frozen, rules)
    return Refusal(f"an agent may not {form} {question.id}: {why}", AGENT_FIX.format(base=base)) if why else None


# --- show -------------------------------------------------------------------------------------------------------


def _section(question: Question, file: QuestionsFile) -> str:
    raw = file.data[question.section.start : question.section.end]
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n").strip("\n")


def find_question(folders: Sequence[Folder], unit: str, qid: str, warnings: Sequence[str]) -> tuple[Folder, Question]:
    """The folder and the question to act on (R2, R3, R13), or the refusal that says why there is none."""
    if not folders:
        raise Refusal(
            next((w for w in warnings if "has no branch" in w), f"{unit} has no branch on {REMOTE}"),
            "the next run creates it",
        ).exit()
    folder = folders[0]
    here = f"l4 questions --unit {folder.unit}"
    if folder.problem:
        raise Refusal(folder.problem, f"fix the file on {folder.branch} by hand").exit()
    if folder.file is None:
        raise Refusal(f"{folder.unit} has no {QUESTIONS_FILENAME} on {folder.branch}", here).exit()
    question = folder.file.get(qid)
    if question is None:
        raise Refusal(f"no {qid} in {folder.path}", here).exit()
    if qid in folder.file.unreadable_ids:
        raise Refusal(f"the section of {qid} in {folder.path} cannot be read", here).exit()
    return folder, question


def _qid(words: Sequence[str], form: str) -> str:
    if len(words) != 1:
        raise _usage(f"{form} takes one question id (Q-NNN)")
    if not _QID.fullmatch(words[0]):
        raise _usage(f"{words[0]!r} is not a question id (Q-NNN)")
    return words[0]


def run_show(app: AppContext, *, question: str, unit: str | None, as_json: bool) -> ExitCode:
    if unit is None:
        raise _usage("show needs --unit", "l4 questions show Q-NNN --unit <unit>")
    app, cfg = load_app_config(app)
    git = Git(app.repo, environ=app.environ)
    folders, warnings = load_folders(app, cfg, git, unit)
    folder, q = find_question(folders, unit, question, warnings)
    assert folder.file is not None
    events, warning = folder_events(git, folder)
    warnings += [warning] if warning else []
    frozen = frozen_paths(events, q.blocking_tasks, folder.fix)
    old = existing_tests(git, folder, cfg, q, frozen)
    frozen = {t: (*paths, *old.get(t, ())) for t, paths in frozen.items()}  # an agent may not name them either
    hidden = option_hidden(q, app.redactor)  # accept refuses it: show promises nothing (L4-QMD-008)
    effects = suggestion_effects(q, frozen, old) if q.status is QuestionStatus.OPEN and not hidden else []
    takes = None if hidden else accept_text(q) or None
    derived = takes is not None and option_suggestion(q) is not None  # option 1: the question has no suggestion block
    who, marker = actor(app.environ, sys.stdin.isatty())
    rules = clarifier_rules(git, cfg.forge.base_branch)
    accept_why = answer_why = None
    if who == "agent":
        accept_why = agent_reason(q, takes, frozen, rules)
        answer_why = agent_reason(q, None, frozen, rules)
    is_open = q.status is QuestionStatus.OPEN
    verdict = q.kind is QuestionKind.VERDICT
    harness = q.kind is QuestionKind.HARNESS
    commands: list[str] = []
    if is_open and not q.answer_text:
        if takes and not verdict and not harness:
            commands.append(f"l4 questions accept {q.id} --unit {folder.unit}")
        if harness:
            unsaved = any(
                e.type == "question.raised" and e.data.get("id") == q.id and e.data.get("saved") is False
                for e in events
            )  # its step could not be saved (L4-IMP-065): only `retry` is offered
            commands += [
                *([] if unsaved else [f'l4 questions answer {q.id} --unit {folder.unit} --text "accept: <why>"']),
                f'l4 questions answer {q.id} --unit {folder.unit} --text "retry: <note>"',
            ]
        else:
            commands.append(f"l4 questions answer {q.id} --unit {folder.unit} --text TEXT")
    else:
        commands.append(f"l4 questions --unit {folder.unit}")
    section = _section(q, folder.file)
    if as_json:
        document = {
            "schema": SCHEMA, "unit": folder.unit, "id": q.id, "status": q.status.value, "kind": _kind(q),
            "blocking": list(q.blocking_tasks), "title": q.title, "branch": folder.branch, "section": section,
            "accept": {"takes": takes}
            | ({"from": "option 1"} if derived else {})
            | ({"refused": option_hidden_message(q.id)} if hidden else {}),
            "frozen": [
                {"task": e.task, "path": e.path, "unfreezes": e.unfreezes, "why": e.why}
                | ({"existing": True} if e.existing else {})  # the key is there only for a pre-existing test
                for e in effects
            ],
            "caller": {"actor": who, "marker": marker, "accept": accept_why, "answer": answer_why},
            "warnings": warnings, "next": commands,
        }  # fmt: skip
        _echo(app, json.dumps(document, indent=2, ensure_ascii=False))
        return ExitCode.OK
    out = [f"warning: {w}" for w in warnings] + [section, ""]
    if not is_open:
        out.append(f"{q.id} is {q.status.value}: it takes no accept or answer")
    elif q.answer_text:
        out.append(f"{q.id} has a draft answer under Status open: submit it on {folder.branch} or remove it")
    else:
        if verdict:
            out.append(
                f'answer with: l4 questions answer {q.id} --unit {folder.unit} --text "accept <reason>"'
                ' (or "reject <reason>")'
            )
        elif harness:
            out.append("answer with one of:")
            out.extend(f"  {command}" for command in commands)
        else:
            out.append(
                f"accept: {option_hidden_message(q.id)}: answer it with --text"
                if hidden
                else f"accept takes: {takes}"
                + (" (option 1: the question has no clarifier suggestion)" if derived else "")
                if takes
                else "accept takes: no clarifier suggestion: answer it with --text"
            )
        for e in effects:
            kind = "the pre-existing test " if e.existing else ""
            out.append(
                f"an accepted suggestion unfreezes {kind}{e.path} for the next green of {e.task}"
                if e.unfreezes
                else f"an accepted suggestion leaves {e.path} frozen for {e.task} ({e.why})"
            )
        if who == "person":
            out.append("caller: person: may accept and answer")
        else:
            out.append(f"caller: agent ({marker or 'no terminal on stdin'})")
            out.append("accept: " + (f"refused: {accept_why}" if accept_why else "may"))
            out.append(
                "answer: "
                + (
                    f"refused: {answer_why}"
                    if answer_why
                    else "may, when its text names no frozen path"
                    if frozen
                    else "may"
                )
            )
    out += [f"Next: {c}" for c in commands]
    _echo(app, "\n".join(out))
    return ExitCode.OK


# --- the edit and its checks: pure (design D9 steps 3 and 4, D10) -----------------------------------------------


def check_text(text: str, redactor: Redactor) -> Refusal | None:
    """R10: a text the file would not hold as an answer. Empty, too long, a line that is structure (`_STRUCTURAL`, a
    field, a subsection heading or a fence, named by its number: the parser would read it as part of the file's own
    grammar), an HTML comment (it would hide text or forge a marker), or a value the redactor changes."""
    if not text.strip():
        return Refusal("the text is empty", "give the answer with --text TEXT")
    if len(text) > MAX_TEXT_CHARS:
        return Refusal(f"the text has {len(text)} characters: the limit is {MAX_TEXT_CHARS}", "shorten it")
    for number, line in enumerate(re.split(r"\r\n|\r|\n", text), 1):
        raw = line.encode("utf-8")
        if _STRUCTURAL.match(line) or _FIELD.match(raw) or _SUBHEADING.match(raw) or _FENCE.match(raw):
            shown = line if len(line) <= 60 else line[:57] + "..."
            return Refusal(
                f"line {number} would be read as structure of the file: {shown}", f"remove or reword line {number}"
            )
    if "<!--" in text:
        return Refusal("the text holds an HTML comment", "remove the comment")
    kinds = redactor.kinds_in(text)
    if kinds or redactor.redact_text(text) != text:
        return Refusal(
            f"the text holds a secret-like value ({', '.join(kinds) or 'redacted'})",
            "remove the secret; rotate it if it was real",
        )
    return None


def is_finding_question(question: Question) -> bool:
    """The verdict question of a finding of the judge (`Finding F-…`)."""
    return question.kind is QuestionKind.VERDICT and question.title.startswith("Finding ")


def cites_criterion(question: Question) -> bool:
    """Whether a finding's question names a criterion: the question writer's first paragraph holds ` (criterion …)`.
    A finding that cites none leaves a reject nothing to check against but its own `WHEN ... THEN ...` (L4-VER-059,
    L4-DLG-023); `bare_gap_reject` and the delegate's reply check read it here."""
    first = " ".join(question.context_text.strip().split("\n\n", 1)[0].split())
    return " (criterion " in first


def bare_gap_reject(question: Question, text: str, unit: str) -> Refusal | None:
    """L4-VER-060: a `reject` with no reason on the verdict question of a spec-gap finding says nothing to fix against
    (the planner would check the fix against a criterion that may already pass), so the command asks for one. The
    question is a spec gap's when it is a `Finding F-…` question whose first paragraph holds the question writer's
    note."""
    parsed = parse_answer(text)
    if not (parsed and parsed[0] == "reject" and not parsed[1].strip()):
        return None
    if not is_finding_question(question):
        return None
    # the question writer's note is in the first paragraph; the judge's own text follows it
    first = " ".join(question.context_text.strip().split("\n\n", 1)[0].split())
    if SPEC_GAP_NOTE.strip() not in first:
        return None
    if not cites_criterion(question):  # the finding cites no criterion: a reason alone leaves nothing to check against
        return Refusal(
            "a spec gap that cites no criterion needs a WHEN ... THEN ...",
            f'l4 questions answer {question.id} --unit {unit} --text "reject: <reason>, then WHEN ... THEN ..."',
        )
    return Refusal(
        "a spec gap's reject needs a reason or a WHEN ... THEN ...",
        f'l4 questions answer {question.id} --unit {unit} --text "reject: <reason>[, then WHEN ... THEN ...]"',
    )


def option_hidden(question: Question, redactor: Redactor) -> bool:
    """Option 1 is what `accept` would write (`option_suggestion`) and the redactor would change it: the block would not
    be the edit the agent asked for, so `accept` does not take it (L4-QMD-008)."""
    text = option_suggestion(question)
    return text is not None and redactor.redact_text(text) != text


def option_hidden_message(qid: str) -> str:
    return f"option 1 of {qid} holds a value the redactor hides, so accept cannot take it as written"


def check_question(
    file: QuestionsFile,
    qid: str,
    form: str,
    text: str | None,
    *,
    unit: str,
    branch: str,
    redactor: Redactor | None = None,
    replace: bool = False,
) -> Refusal | None:
    """R3 to R5 and R7 to R10 for `form` (`accept` or `answer`) on `qid`; None when the edit may be made. `text` is
    the answer's text (None for `accept`). `replace` (L4-QMD-010): replace the answer of an answered verdict question;
    every other question is refused."""
    question = file.get(qid)
    if question is None or qid in file.unreadable_ids:
        return Refusal(f"no {qid} in {QUESTIONS_FILENAME}", f"l4 questions --unit {unit}")
    verdict = question.kind is QuestionKind.VERDICT
    if replace and form != "answer":
        return Refusal("--replace is for answer", f"l4 questions answer {qid} --unit {unit} --text TEXT --replace")
    if question.status is not QuestionStatus.OPEN:
        if question.status is QuestionStatus.SUPERSEDED and question.superseded_by:
            successor = question.superseded_by
            return Refusal(
                f"{qid} is superseded by {successor}",
                f"answer {successor}: l4 questions show {successor} --unit {unit}",
            )
        if verdict and question.status in _REPLACEABLE and not replace:
            return Refusal(
                f"{qid} is answered",
                f"to replace the answer on purpose: l4 questions answer {qid} --unit {unit} "
                f'--text "accept <reason>" --replace (or "reject <reason>"); the previous answer stays in the section',
            )
        if not (replace and verdict and question.status in _REPLACEABLE):
            if replace and not verdict:
                return Refusal(
                    f"{qid} is not a verdict question: --replace is for an answered verdict question",
                    f"a clarification answer is changed by hand on {branch}; an answer a run already used becomes a "
                    f'fix unit "apply clarification {qid}" (L4-QMD-006)',
                )
            return Refusal(
                f"{qid} is {question.status.value}",
                f"to change an answer, edit its section on {branch} by hand; an answer a run already used becomes a "
                f'fix unit "apply clarification {qid}" (L4-QMD-006)',
            )
    elif replace:
        if not verdict:
            return Refusal(
                f"{qid} is not a verdict question: --replace is for an answered verdict question",
                f"a clarification answer is changed by hand on {branch} (L4-QMD-006); answer it without --replace",
            )
        return Refusal(
            f"{qid} is open: there is no answer to replace",
            f"answer it without --replace: l4 questions answer {qid} --unit {unit} --text TEXT",
        )
    if question.answer_text and not replace:
        return Refusal(
            f"{qid} has a draft answer under Status open",
            f"submit it on {branch} (set Status to answered) or remove it, then run the command again",
        )
    verdict = question.kind is QuestionKind.VERDICT
    harness = question.kind is QuestionKind.HARNESS
    harness_fix = f'l4 questions answer {qid} --unit {unit} --text "accept: <why>" (or "retry: <note>")'
    if harness and form == "accept":
        return Refusal("a harness question is answered with accept or retry", harness_fix)
    if form == "accept":
        if verdict:
            return Refusal(
                f"{qid} is a verdict question: accept is not an answer to it",
                f'l4 questions answer {qid} --unit {unit} --text "accept <reason>" (or "reject <reason>")',
            )
        if not accept_text(question):
            return Refusal(
                f"{qid} has no clarifier suggestion to accept", f"l4 questions answer {qid} --unit {unit} --text TEXT"
            )
        if option_hidden(question, redactor or Redactor({})):
            return Refusal(option_hidden_message(qid), f"l4 questions answer {qid} --unit {unit} --text TEXT")
        return None
    if text is None:
        return Refusal("answer needs --text", f"l4 questions answer {qid} --unit {unit} --text TEXT")
    return (
        check_text(text, redactor or Redactor({}))
        or (
            Refusal(
                "a verdict answer starts with accept or reject",
                'the same command with the first word fixed: --text "accept <reason>" (or "reject <reason>")',
            )
            if verdict and not _DECISION.match(text)
            else None
        )
        or (bare_gap_reject(question, text, unit) if verdict else None)
        or (
            Refusal("a harness question is answered with accept or retry", harness_fix)
            if harness and harness_decision(text) is None
            else None
        )
        or (
            Refusal(f"the text is not different from the answer of {qid}", "give the answer that replaces it")
            if replace and _flat(text) == _flat(question.answer_text)
            else None
        )
    )


def edit_accept(file: QuestionsFile, qid: str) -> QuestionsFile:
    """`accept`: only the Status value and the index row change."""
    return file.set_status(qid, QuestionStatus.ACCEPTED)


def edit_answer(file: QuestionsFile, qid: str, text: str) -> QuestionsFile:
    """`answer`: the Answer body, the Status value and the index row."""
    return file.set_answer(qid, text).set_status(qid, QuestionStatus.ANSWERED)


def _flat(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def round_trip(
    before: QuestionsFile, after: QuestionsFile, qid: str, status: QuestionStatus, text: str | None,
    takes: str | None = None,
) -> str | None:  # fmt: skip
    """D9 step 4: what the edited bytes read back as, or None when it is what was asked. The question has the new
    Status (and, for `answer`, an answer text equal to `text`, stripped); every other question has the same id, Status,
    blocking tasks and effective answer as before; the parse has no issue that the old one did not have. `takes`
    (form `accept`, L4-QMD-008): the effective answer of the question is that text, the one `accept` was asked to take
    (the written suggestion, or option 1 of a question that had none)."""
    mine = after.get(qid)
    if mine is None:
        return f"{qid} is no longer read from the edited file"
    if mine.status is not status:
        return f"the Status of {qid} reads {mine.status.value}, not {status.value}"
    if text is not None and _flat(mine.answer_text) != _flat(text):
        return f"the answer of {qid} reads back differently from the text given"
    if takes is not None and effective_answer(mine) != takes:
        return f"the answer of {qid} reads back differently from the suggestion it takes"
    old = {q.id: q for q in before.questions if q.id != qid}
    new = {q.id: q for q in after.questions if q.id != qid}
    if list(old) != list(new):
        lost = sorted(set(old) ^ set(new))
        return f"the questions {', '.join(lost)} are not read as before"
    for other, was in old.items():
        now = new[other]
        if (now.status, now.blocking_tasks, effective_answer(now)) != (
            was.status, was.blocking_tasks, effective_answer(was),
        ):  # fmt: skip
            return f"{other} reads differently after the edit (Status, Blocking tasks or answer)"
    known = {(i.kind, i.question_id, i.detail) for i in before.issues}
    fresh = [i for i in after.issues if (i.kind, i.question_id, i.detail) not in known]
    if fresh:
        return f"the edit adds a parse issue: {fresh[0].kind} on {fresh[0].question_id}"
    return None


@dataclass(frozen=True)
class Edit:
    """A checked edit of one question: `new` is the whole file (the only change is in `question`'s spans and index
    row), `status` the Status it writes. The commit and the push are the caller's (4.5)."""

    form: str
    folder: Folder
    question: Question
    status: QuestionStatus
    text: str | None
    old: QuestionsFile
    new: QuestionsFile
    replaced: bool = False  # `answer --replace`: the previous answer is kept in a comment (L4-QMD-010)


def build_edit(
    form: str,
    folder: Folder,
    qid: str,
    text: str | None,
    *,
    redactor: Redactor,
    replace: bool = False,
    who: str = "",
    on: str = "",
) -> Edit:
    """The checks of D10 that need only the file (R3 to R5, R7 to R10), the edit, and its round trip. Raises the
    refusal (exit 2). The agent rule (R11), a finished unit or a live run (R6) and a moved branch (R12) are not here.

    `accept` of an open technical question with no suggestion block takes option 1 (L4-QMD-008): the edit is made on
    the file with the block added (`with_option_suggestion`), the bytes on the branch stay `Edit.old`, and the read-back
    checks that the question's effective answer is that text."""
    assert folder.file is not None
    found = check_question(
        folder.file, qid, form, text, unit=folder.unit, branch=folder.branch, redactor=redactor, replace=replace
    )  # on the file as it is: `option_hidden` reads option 1 of a question that has no block yet
    if found is not None:
        raise found.exit()
    base = folder.file.with_option_suggestion(qid, redactor=redactor) if form == "accept" else folder.file
    question = base.get(qid)
    assert question is not None
    status = QuestionStatus.ACCEPTED if form == "accept" else QuestionStatus.ANSWERED
    if replace:
        new = base.replace_answer(qid, text or "", who=who, on=on)
    else:
        new = edit_accept(base, qid) if form == "accept" else edit_answer(base, qid, text or "")
    original = folder.file.get(qid)
    assert original is not None
    takes = accept_text(original) if form == "accept" else None
    if (why := round_trip(folder.file, new, qid, status, text if form == "answer" else None, takes)) is not None:
        raise Refusal(
            f"the edited {QUESTIONS_FILENAME} does not read back as asked: {why}",
            f"edit the section of {qid} on {folder.branch} by hand",
        ).exit()
    return Edit(form, folder, question, status, text, folder.file, new, replace)


FINISHED = (Phase.MERGED, Phase.ARCHIVED, Phase.ABANDONED)


def unit_refusal(git: Git, folder: Folder) -> Refusal | None:
    """R6: the unit is finished (an answer changes nothing), or a run is working on it now (the lock ref's pending
    ledger has a `run.started` with no `run.finished`, the rule of `l4 restart`). In every other phase the next run
    takes the answer, also while the unit runs other tasks."""
    if folder.phase in FINISHED:
        return Refusal(
            f"{folder.parent} does not wait for an answer: it is {folder.phase}", "an answer changes nothing"
        )
    live = live_run(read_pending(git, lock_ref(folder.parent)).events)
    if live is not None:
        return Refusal(f"a run is working on {folder.parent} (run {live})", "try again when it ends: l4 ci watch")
    return None


def agent_refusal(app: AppContext, git: Git, cfg: L4Config, edit: Edit) -> Refusal | None:
    """R11: a caller that is an agent (a marker is set, or standard input is no terminal) may write only what the
    base branch's `clarifier` keys allow (design D11). The effective answer is the suggestion for `accept` and the
    text for `answer`."""
    who, _ = actor(app.environ, sys.stdin.isatty())
    if who == "person":
        return None
    events, _warning = folder_events(git, edit.folder)
    frozen = frozen_paths(events, edit.question.blocking_tasks, edit.folder.fix)
    old = existing_tests(git, edit.folder, cfg, edit.question, frozen)
    frozen = {t: (*paths, *old.get(t, ())) for t, paths in frozen.items()}
    effective = accept_text(edit.question) if edit.form == "accept" else edit.text
    rules = clarifier_rules(git, cfg.forge.base_branch)
    return check_agent(edit.form, edit.question, effective, frozen, rules, cfg.forge.base_branch)


def _read_text(text: str | None) -> str | None:
    return sys.stdin.read() if text == "-" else text


def _prepare(
    app: AppContext, form: str, question: str, unit: str | None, text: str | None, replace: bool = False
) -> tuple[AppContext, L4Config, Git, Edit]:
    if unit is None:
        raise _usage(f"{form} needs --unit", f"l4 questions {form} Q-NNN --unit <unit>")
    app, cfg = load_app_config(app)
    git = Git(app.repo, environ=app.environ)
    folders, warnings = load_folders(app, cfg, git, unit)
    if folders:
        waits = unit_refusal(git, folders[0])
        if waits is not None:
            raise waits.exit()
    folder, _ = find_question(folders, unit, question, warnings)
    who = author_name(git) if replace else ""
    on = datetime.now(UTC).date().isoformat() if replace else ""
    edit = build_edit(form, folder, question, text, redactor=app.redactor, replace=replace, who=who, on=on)
    refused = agent_refusal(app, git, cfg, edit)
    if refused is not None:
        raise refused.exit()
    return app, cfg, git, edit


# --- the write: one commit by plumbing, one push without force (design D9 steps 5 and 6) ------------------------


def remote_head(git: Git, config: Sequence[tuple[str, str]], branch: str) -> str | None:
    """The sha of `refs/heads/<branch>` on `origin` now, or None when the branch is not there."""
    out = git.run("ls-remote", REMOTE, f"refs/heads/{branch}", config=config).stdout
    for line in out.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == f"refs/heads/{branch}":
            return fields[0]
    return None


_IDENT = re.compile(r"(?P<name>.*) <(?P<email>[^>]*)> \d+ [+-]\d{4}\s*")


def author_name(git: Git) -> str:
    """The operator's own git identity (what `commit-tree` will write), or the refusal to set one."""
    done = git.run("var", "GIT_AUTHOR_IDENT", check=False)
    found = _IDENT.fullmatch(done.stdout) if done.returncode == 0 else None
    if found is None or not found.group("name").strip():
        raise Refusal(
            "git has no identity to author the commit with",
            'git config user.name "Your Name"; git config user.email you@example',
        ).exit()
    return found.group("name").strip()


@dataclass(frozen=True)
class DelegateMark:
    """Who the delegate was for one answer: its model, the CLI that ran it and the profile (L4-DLG-006)."""

    model: str
    cli: str
    profile: str


def commit_message(edit: Edit, name: str, who: str, marker: str | None, *, mark: DelegateMark | None = None) -> str:
    """The message of design D9: no `L4-` trailer, and a `[skip ci]` line: the push starts neither the unit branch's
    own workflow copy (it can pin an older harness) nor the repository's CI on a mid-TDD branch; the command starts
    the run."""
    unit = edit.folder.unit.partition(":")[2] or edit.folder.unit
    title = " ".join(edit.question.title.split())[:60].rstrip() + (" (answer replaced)" if edit.replaced else "")
    replaced = "Replaced: yes\n" if edit.replaced else ""
    via = "l4 questions"
    if who == "delegate":
        assert mark is not None, "a delegate commit names its model, CLI and profile"
        by, via = f"delegate ({mark.model} via {mark.cli}; profile {mark.profile})", "l4 delegate"
    else:
        by = f"{name} (person)" if who == "person" else f"{name} (agent: {marker or 'no terminal on stdin'})"
    return (
        f"{edit.form} {edit.question.id} ({unit}): {title}\n\n"
        f"Status: {edit.status.value}\n{replaced}By: {by}\nVia: {via}\n[skip ci]\n"
    )


def make_commit(git: Git, edit: Edit, message: str) -> str:
    """The new `questions.md` on top of the head that was read, as a commit that no ref, index or work tree knows:
    a private index file, `read-tree`, `update-index --cacheinfo` with the old mode, `write-tree`, `commit-tree`."""
    head, path = edit.folder.head, edit.folder.path
    listing = git.run("ls-tree", head, "--", path).stdout.split()
    mode = listing[0] if listing else "100644"
    base = cache_root(git.env, repo=git.repo) / "questions-index"
    base.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="idx-", dir=base))
    try:
        private = git.at(git.repo)
        private.env = {**private.env, "GIT_INDEX_FILE": str(scratch / "index")}
        (scratch / "questions.md").write_bytes(edit.new.data)
        blob = private.run("hash-object", "-w", "--no-filters", str(scratch / "questions.md")).stdout.strip()
        private.run("read-tree", head)
        private.run("update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}")
        tree = private.run("write-tree").stdout.strip()
        sha = private.run("commit-tree", tree, "-p", head, "-m", message).stdout.strip()
        git.history.extend(private.history)
        return sha
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _moved(branch: str, now: str | None) -> L4Exit:
    shown = now[:10] if now else "gone"
    return Refusal(f"{branch} moved since the fetch (now {shown})", "run the command again: it fetches first").exit()


def _checked_out(git: Git, branch: str) -> bool:
    listing = git.run("worktree", "list", "--porcelain", check=False).stdout
    return f"branch refs/heads/{branch}" in listing.splitlines()


def _dry_run(edit: Edit, message: str) -> str:
    old = edit.old.data.decode("utf-8", errors="replace").splitlines(keepends=True)
    new = edit.new.data.decode("utf-8", errors="replace").splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(old, new, f"a/{edit.folder.path}", f"b/{edit.folder.path}", n=3))
    return f"{diff.rstrip(chr(10))}\n\n{message.rstrip(chr(10))}\n\nnothing written (--no-push)"


def _now() -> datetime:
    return datetime.now(UTC)


def _working_run_line(app: AppContext, cfg: L4Config, git: Git, folder: Folder) -> str | None:
    """L4-QMD-011: when the unit branch's ledger shows a run that started and has no end, and the liveness rule
    (`l4.state.liveness.ended_why`: the age against its job timeout, then the forge's state of its CI run) does not
    call it ended, the line that says which run takes this answer. Information only: nothing is refused for it, and a
    ledger or a forge that cannot be read gives no line."""
    try:
        _, run = _activity(folder_events(git, folder)[0])
        started = parse_time(run.started) if run is not None else None
        if run is None or started is None:
            return None
        at = _now()
        forge = LazyForge(lambda: make_forge(cfg, app.environ, repo=app.repo))
        if ended_why(cfg, run, forge, at)[0] is not None:
            return None
    except Exception as exc:  # noqa: BLE001 - a hint: when it cannot be read there is nothing to say
        log.info("questions: the open run was not read (%s)", type(exc).__name__)
        return None
    minutes = max(0, int((at - started).total_seconds() // 60))
    return (
        f"[l4] questions: run {run.run_id} works on {folder.parent} (started {minutes} min ago): "
        "it takes this answer at its next push, or the next run does"
    )


def write_edit(
    app: AppContext, cfg: L4Config, git: Git, edit: Edit, *, no_push: bool, no_run: bool = False
) -> ExitCode:
    """Make the commit and push it to the unit branch, or with `no_push` print what would be pushed. Nothing is made
    before every refusal has been checked."""
    folder, branch = edit.folder, edit.folder.branch
    who, marker = actor(app.environ, sys.stdin.isatty())
    message = commit_message(edit, author_name(git), who, marker)
    if no_push:
        _echo(app, _dry_run(edit, message))
        return ExitCode.OK
    push_config = push_auth_config(cfg, app.environ, origin_url(app.repo, app.environ))
    fetch_config = fetch_auth_config(cfg, app.environ, origin_url(app.repo, app.environ))

    def failed(exc: GitError) -> L4Exit:
        return explain_push_failure(
            exc, branch=branch, token_env=cfg.forge.token_env, environ=app.environ,
            redact=app.redactor.redact_text, platform=push_platform(cfg, app.environ, git.repo),
        )  # fmt: skip

    try:
        now = remote_head(git, fetch_config, branch)
    except GitError as exc:
        raise failed(exc) from None
    if now != folder.head:
        raise _moved(branch, now)
    sha = make_commit(git, edit, message)
    try:
        git.push(REMOTE, [f"{sha}:refs/heads/{branch}"], config=push_config)
    except PushRejected:
        try:
            now = remote_head(git, fetch_config, branch)
        except GitError:
            now = None
        raise _moved(branch, now) from None
    except GitError as exc:
        raise failed(exc) from None
    git.run("update-ref", f"refs/remotes/{REMOTE}/{branch}", sha)
    out = [f"pushed {sha[:10]} to {branch}: the push starts no run ([skip ci])"]
    if (working := _working_run_line(app, cfg, git, folder)) is not None:
        out.append(working)
    if _checked_out(git, branch):
        out.append(f"your checkout of {branch} is behind: git pull")
    if no_run:
        base = cfg.forge.base_branch
        out.append(f"no run started (--no-run): start one on {base} ({how_to_start(app, cfg, base)})")
    else:
        out.append(
            start_run_line(app, cfg)
        )  # a unit branch runs its own, possibly older, workflow copy: start on the base
    out.append(f"Next: l4 status --unit {folder.unit}")
    _echo(app, "\n".join(out))
    return ExitCode.OK


def run_accept(
    app: AppContext, *, question: str, unit: str | None, no_push: bool = False, no_run: bool = False
) -> ExitCode:
    """`l4 questions accept Q-NNN --unit U [--no-push] [--no-run]`."""
    app, cfg, git, edit = _prepare(app, "accept", question, unit, None)
    return write_edit(app, cfg, git, edit, no_push=no_push, no_run=no_run)


def run_answer(
    app: AppContext,
    *,
    question: str,
    unit: str | None,
    text: str | None,
    no_push: bool = False,
    no_run: bool = False,
    replace: bool = False,
) -> ExitCode:
    """`l4 questions answer Q-NNN --unit U --text T [--replace] [--no-push]` (`--text -` reads standard input)."""
    app, cfg, git, edit = _prepare(app, "answer", question, unit, _read_text(text), replace)
    return write_edit(app, cfg, git, edit, no_push=no_push, no_run=no_run)


# --- the handler ------------------------------------------------------------------------------------------------


def run_questions(
    app: AppContext,
    *,
    words: Sequence[str] = (),
    unit: str | None = None,
    text: str | None = None,
    as_json: bool = False,
    no_push: bool = False,
    no_run: bool = False,
    replace: bool = False,
) -> ExitCode:
    """`l4 questions [list] | show Q | accept Q | answer Q --text T`, with `--unit`, `--json`,
    `--no-push`, `--no-run` and `--replace`."""
    form, rest = (words[0] if words else "list"), tuple(words[1:])
    if form == "list" and not rest:
        return run_list(app, unit=unit, as_json=as_json)
    if form == "show":
        return run_show(app, question=_qid(rest, form), unit=unit, as_json=as_json)
    if form == "accept":
        return run_accept(app, question=_qid(rest, form), unit=unit, no_push=no_push, no_run=no_run)
    if form == "answer":
        return run_answer(
            app, question=_qid(rest, form), unit=unit, text=text, no_push=no_push, no_run=no_run, replace=replace
        )
    if replace:
        raise _usage("--replace is for answer", "l4 questions answer Q-NNN --unit U --text TEXT --replace")
    raise _usage(f"unknown form: {' '.join(words)}")
