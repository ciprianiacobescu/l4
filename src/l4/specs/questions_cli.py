"""`l4 questions [list]|show|accept|answer` (L4-QMD-007, L4-QMD-008): the handler named in `commands.HANDLERS`.

Reading never touches the work tree: `questions.md` is read from the fetched unit branch with `git ls-tree` and
`cat-file`, to at most `MAX_QUESTIONS_BYTES`, and a symlink is not read. The edits of `accept` and `answer` are pure
functions over `QuestionsFile` (`edit_accept`, `edit_answer`) and their checks (`check_question`, `check_text`,
`round_trip`); the commit and the push are `unfreeze-and-answer` 4.5.
"""

import json
import logging
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import click

from l4.config.loader import load_config
from l4.config.redaction import load_app_config
from l4.config.schema import ClarifierCfg, L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.implementer.guards import IGNORE_FILE_GLOBS
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
    effective_answer,
    unescape_text,
)
from l4.state.ledger import MAX_LEDGER_FILE_BYTES, LedgerCorrupt, LedgerEvent, parse_ledger_files
from l4.state.pending import merge_ledgers, read_pending
from l4.state.retry import fetch_unit_refs
from l4.state.status import discover
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.names import lock_ref, unit_branch
from l4.vcs.tree import regular_blobs
from l4.verifier.verdicts import _DECISION
from l4.yolo.accept import actor

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


@dataclass(frozen=True)
class PathEffect:
    """What an accepted suggestion does to one frozen path of a held task (design D7)."""

    task: str
    path: str
    unfreezes: bool
    why: str  # when it stays frozen: the reason


def _is_ignore_file(path: str) -> bool:
    return any(glob_match(glob, path) for glob in IGNORE_FILE_GLOBS)


def suggestion_effects(question: Question, frozen: Mapping[str, Sequence[str]]) -> list[PathEffect]:
    """The frozen paths of the held tasks that the suggestion names, and whether an accepted suggestion unfreezes each
    (the rule of `implementer.unfreeze.unfrozen` for an `accepted` question): a support or test file that the question
    itself (title, Context, Options) names too opens, an ignore file stays frozen, at most
    `MAX_PATHS_PER_QUESTION` per question. A verdict question unfreezes nothing."""
    if question.kind is QuestionKind.VERDICT or not question.suggestion_text:
        return []
    text = unescape_text(question.suggestion_text)
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
    return [PathEffect(t, p, *verdict[p]) for t in tasks for p in sorted(frozen[t]) if p in verdict]


@dataclass(frozen=True)
class ClarifierRules:
    """`clarifier.auto_accept_kinds` and `clarifier.answer_by_agents`, as the base branch has them (D11)."""

    auto_accept_kinds: tuple[str, ...] = ("technical",)
    answer_by_agents: bool = False


def clarifier_rules(git: Git, base: str) -> ClarifierRules:
    """Both keys from `.l4/config.yaml` at `refs/remotes/origin/<base>`, never from the unit branch (an agent cannot
    set them there). The defaults apply when the file is absent or is not a valid config."""
    ref = f"refs/remotes/{REMOTE}/{base}"
    try:
        shown = git.run("show", f"{ref}:{CONFIG_PATH}", check=False)
    except GitError as exc:
        log.warning("questions: cannot read %s at %s (%s): the default clarifier rules apply", CONFIG_PATH, ref, exc)
        return ClarifierRules()
    if shown.returncode != 0:
        return ClarifierRules()
    with tempfile.TemporaryDirectory(prefix="l4-questions-") as tmp:
        path = Path(tmp) / "config.yaml"
        path.write_text(shown.stdout, encoding="utf-8")
        try:
            cfg: ClarifierCfg = load_config(Path(tmp), config_path=path).clarifier
        except L4Exit as exc:
            log.warning(
                "questions: %s at %s is not a valid config (%s): the default clarifier rules apply",
                CONFIG_PATH,
                ref,
                exc,
            )
            return ClarifierRules()
    return ClarifierRules(tuple(cfg.auto_accept_kinds), bool(getattr(cfg, "answer_by_agents", False)))


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
    kind = question.kind.value if question.kind is not None else question.kind_text or "unknown"
    if kind not in rules.auto_accept_kinds:
        return f"its kind is {kind}, and clarifier.auto_accept_kinds is [{', '.join(rules.auto_accept_kinds)}]"
    if effective is not None:
        for task in question.blocking_tasks:
            for path in frozen.get(task, ()):
                if names_path(effective, path):
                    noun = "suggestion" if effective == unescape_text(question.suggestion_text) else "text"
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
    effects = suggestion_effects(q, frozen) if q.status is QuestionStatus.OPEN else []
    takes = unescape_text(q.suggestion_text) or None
    who, marker = actor(app.environ, sys.stdin.isatty())
    rules = clarifier_rules(git, cfg.forge.base_branch)
    accept_why = answer_why = None
    if who == "agent":
        accept_why = agent_reason(q, takes, frozen, rules)
        answer_why = agent_reason(q, None, frozen, rules)
    is_open = q.status is QuestionStatus.OPEN
    verdict = q.kind is QuestionKind.VERDICT
    commands: list[str] = []
    if is_open and not q.answer_text:
        if takes and not verdict:
            commands.append(f"l4 questions accept {q.id} --unit {folder.unit}")
        commands.append(f"l4 questions answer {q.id} --unit {folder.unit} --text TEXT")
    else:
        commands.append(f"l4 questions --unit {folder.unit}")
    section = _section(q, folder.file)
    if as_json:
        document = {
            "schema": SCHEMA, "unit": folder.unit, "id": q.id, "status": q.status.value, "kind": _kind(q),
            "blocking": list(q.blocking_tasks), "title": q.title, "branch": folder.branch, "section": section,
            "accept": {"takes": takes},
            "frozen": [
                {"task": e.task, "path": e.path, "unfreezes": e.unfreezes, "why": e.why} for e in effects
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
        else:
            out.append(
                f"accept takes: {takes}" if takes else "accept takes: no clarifier suggestion: answer it with --text"
            )
        for e in effects:
            out.append(
                f"an accepted suggestion unfreezes {e.path} for the next green of {e.task}"
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


def check_question(
    file: QuestionsFile,
    qid: str,
    form: str,
    text: str | None,
    *,
    unit: str,
    branch: str,
    redactor: Redactor | None = None,
) -> Refusal | None:
    """R3 to R5 and R7 to R10 for `form` (`accept` or `answer`) on `qid`; None when the edit may be made. `text` is
    the answer's text (None for `accept`)."""
    question = file.get(qid)
    if question is None or qid in file.unreadable_ids:
        return Refusal(f"no {qid} in {QUESTIONS_FILENAME}", f"l4 questions --unit {unit}")
    if question.status is not QuestionStatus.OPEN:
        if question.status is QuestionStatus.SUPERSEDED and question.superseded_by:
            successor = question.superseded_by
            return Refusal(
                f"{qid} is superseded by {successor}",
                f"answer {successor}: l4 questions show {successor} --unit {unit}",
            )
        return Refusal(
            f"{qid} is {question.status.value}",
            f"to change an answer, edit its section on {branch} by hand; an answer a run already used becomes a fix "
            f'unit "apply clarification {qid}" (L4-QMD-006)',
        )
    if question.answer_text:
        return Refusal(
            f"{qid} has a draft answer under Status open",
            f"submit it on {branch} (set Status to answered) or remove it, then run the command again",
        )
    verdict = question.kind is QuestionKind.VERDICT
    if form == "accept":
        if verdict:
            return Refusal(
                f"{qid} is a verdict question: accept is not an answer to it",
                f'l4 questions answer {qid} --unit {unit} --text "accept <reason>" (or "reject <reason>")',
            )
        if not question.suggestion_text:
            return Refusal(
                f"{qid} has no clarifier suggestion to accept", f"l4 questions answer {qid} --unit {unit} --text TEXT"
            )
        return None
    if text is None:
        return Refusal("answer needs --text", f"l4 questions answer {qid} --unit {unit} --text TEXT")
    return check_text(text, redactor or Redactor({})) or (
        Refusal(
            "a verdict answer starts with accept or reject",
            'the same command with the first word fixed: --text "accept <reason>" (or "reject <reason>")',
        )
        if verdict and not _DECISION.match(text)
        else None
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
    before: QuestionsFile, after: QuestionsFile, qid: str, status: QuestionStatus, text: str | None
) -> str | None:
    """D9 step 4: what the edited bytes read back as, or None when it is what was asked. The question has the new
    Status (and, for `answer`, an answer text equal to `text`, stripped); every other question has the same id, Status,
    blocking tasks and effective answer as before; the parse has no issue that the old one did not have."""
    mine = after.get(qid)
    if mine is None:
        return f"{qid} is no longer read from the edited file"
    if mine.status is not status:
        return f"the Status of {qid} reads {mine.status.value}, not {status.value}"
    if text is not None and _flat(mine.answer_text) != _flat(text):
        return f"the answer of {qid} reads back differently from the text given"
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


def build_edit(form: str, folder: Folder, qid: str, text: str | None, *, redactor: Redactor) -> Edit:
    """The checks of D10 that need only the file (R3 to R5, R7 to R10), the edit, and its round trip. Raises the
    refusal (exit 2). The agent rule (R11), a finished unit or a live run (R6) and a moved branch (R12) are not here."""
    assert folder.file is not None
    found = check_question(folder.file, qid, form, text, unit=folder.unit, branch=folder.branch, redactor=redactor)
    if found is not None:
        raise found.exit()
    question = folder.file.get(qid)
    assert question is not None
    status = QuestionStatus.ACCEPTED if form == "accept" else QuestionStatus.ANSWERED
    new = edit_accept(folder.file, qid) if form == "accept" else edit_answer(folder.file, qid, text or "")
    if (why := round_trip(folder.file, new, qid, status, text if form == "answer" else None)) is not None:
        raise Refusal(
            f"the edited {QUESTIONS_FILENAME} does not read back as asked: {why}",
            f"edit the section of {qid} on {folder.branch} by hand",
        ).exit()
    return Edit(form, folder, question, status, text, folder.file, new)


def _read_text(text: str | None) -> str | None:
    return sys.stdin.read() if text == "-" else text


def _prepare(
    app: AppContext, form: str, question: str, unit: str | None, text: str | None
) -> tuple[AppContext, L4Config, Git, Edit]:
    if unit is None:
        raise _usage(f"{form} needs --unit", f"l4 questions {form} Q-NNN --unit <unit>")
    app, cfg = load_app_config(app)
    git = Git(app.repo, environ=app.environ)
    folders, warnings = load_folders(app, cfg, git, unit)
    folder, _ = find_question(folders, unit, question, warnings)
    return app, cfg, git, build_edit(form, folder, question, text, redactor=app.redactor)


def run_accept(app: AppContext, *, question: str, unit: str | None, no_push: bool = False) -> ExitCode:
    """`l4 questions accept Q-NNN --unit U [--no-push]`: builds the checked edit; the write is task 4.5."""
    _prepare(app, "accept", question, unit, None)
    raise NotImplementedError("questions: the commit and the push are unfreeze-and-answer 4.5")


def run_answer(
    app: AppContext, *, question: str, unit: str | None, text: str | None, no_push: bool = False
) -> ExitCode:
    """`l4 questions answer Q-NNN --unit U --text T [--no-push]`: builds the checked edit; the write is task 4.5."""
    _prepare(app, "answer", question, unit, _read_text(text))
    raise NotImplementedError("questions: the commit and the push are unfreeze-and-answer 4.5")


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
    if form == "show":
        return run_show(app, question=_qid(rest, form), unit=unit, as_json=as_json)
    if form == "accept":
        return run_accept(app, question=_qid(rest, form), unit=unit, no_push=no_push)
    if form == "answer":
        return run_answer(app, question=_qid(rest, form), unit=unit, text=text, no_push=no_push)
    raise _usage(f"unknown form: {' '.join(words)}")
