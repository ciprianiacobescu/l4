"""`l4 feedback add|list|show|submit|withdraw` (L4-FBK-003): the handlers named in `commands.HANDLERS`.

The commands write `feedback.md` and nothing else: no commit, no push, no forge call. The unit folder is found in
one place (`resolve_feedback_dir`).
"""

import json
import re
import shlex
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import click

from l4.config.redaction import load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, read_regular_file, reject_symlinks
from l4.specs.base import Framework, UnknownUnit, parse_unit_id
from l4.specs.feedback import (
    FEEDBACK_FILENAME,
    MAX_PLACES,
    FeedbackFile,
    FeedbackItem,
    FeedbackKind,
    FeedbackStatus,
    NewFeedback,
    Place,
    Quote,
    append_item,
    content_sha256,
    new_problems,
    problems,
)
from l4.specs.fixmark import read_fix_marker
from l4.specs.followup import read_follow_up_marker
from l4.specs.providers import providers_for
from l4.state.fold import fold
from l4.state.ledger import LedgerCorrupt, LedgerRead, parse_ledger_files, read_ledger_files
from l4.state.lifecycle import Phase
from l4.state.pending import merge_ledgers, read_pending
from l4.state.status import select_units
from l4.vcs.git import Git
from l4.vcs.names import lock_ref

SCHEMA = "l4/feedback@1"
MAX_QUOTE_LINES = 40
MAX_QUOTE_BYTES = 4000
MAX_SOURCE_BYTES = 8 * 1024 * 1024
MAX_TITLE = 72
ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"
LANGUAGES = {
    ".py": "python", ".ts": "typescript", ".js": "javascript", ".cs": "csharp", ".go": "go", ".rs": "rust",
    ".java": "java", ".kt": "kotlin",
}  # fmt: skip
_AT = re.compile(r"(?P<path>.+?)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?")
_OPTION_OF = {"Where": "--at", "Env": "--env", "When": "--when", "Then": "--then"}


@dataclass(frozen=True)
class FeedbackTarget:
    framework: Framework
    name: str
    dir: Path  # the unit folder that holds (or will hold) feedback.md
    merged: bool = False  # the unit is `merged`: the file goes to the base branch (L4-FBK-010)
    push_to: str | None = None  # the unit branch, when HEAD is its head under another name or detached

    @property
    def id(self) -> str:
        return f"{self.framework.value}:{self.name}"


def _usage(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, f"feedback: {message}")


def _git(app: AppContext) -> Git | None:
    try:
        return Git(app.repo, environ=app.environ)
    except L4Exit:
        return None  # no git on a safe PATH: --unit still works, and By reads `unknown`


def _unit_of_branch(app: AppContext, cfg: L4Config) -> str | None:
    """`<framework>:<name>` of the checked-out `<branch_prefix><framework>/<name>`, else None."""
    git = _git(app)
    if git is None:
        return None
    branch = git.run("symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
    rest = branch.removeprefix(cfg.forge.branch_prefix) if branch.startswith(cfg.forge.branch_prefix) else ""
    framework, _, name = rest.partition("/")
    unit = f"{framework}:{name}"
    try:
        parse_unit_id(unit)
    except ValueError:
        return None
    return unit


def archive_folder(app: AppContext, cfg: L4Config, name: str) -> Path | None:
    """The newest `openspec/changes/archive/<date>-<name>/` of an archived change, else None."""
    archive = app.repo.joinpath(*PurePosixPath(cfg.spec.openspec.root).parts, "changes", "archive")
    if not archive.is_dir() or archive.is_symlink():
        return None
    dated = re.compile(rf"\d{{4}}-\d\d-\d\d-{re.escape(name)}")
    found = sorted(d for d in archive.iterdir() if d.is_dir() and not d.is_symlink() and dated.fullmatch(d.name))
    return found[-1] if found else None


def _local_phase(app: AppContext, folder: Path, unit_id: str) -> str | None:
    """The phase the unit's own ledger folds to, with the pending ledger of its lock ref (a merged Kiro unit's folder
    still reads `in_review`: the merge is only there). None when nothing says."""
    events: LedgerRead = parse_ledger_files(read_ledger_files(folder))
    git = _git(app)
    if git is not None:
        events = merge_ledgers(events, read_pending(git, lock_ref(unit_id)))
    return fold(events.events, unit_id).phase


def _after_merge(app: AppContext, cfg: L4Config, target: FeedbackTarget) -> FeedbackTarget:
    """L4-FBK-010: a `merged` unit's feedback goes to its folder on the base branch, which must be checked out. An
    `abandoned` unit takes none. Any other phase keeps the folder it was found in."""
    try:
        phase = _local_phase(app, target.dir, target.id)
    except LedgerCorrupt:
        return target
    if phase == Phase.ABANDONED.value:
        raise _usage(f"{target.id} is abandoned: it takes no feedback")
    if phase != Phase.MERGED.value:
        return target
    git = _git(app)
    branch = git.run("symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip() if git else ""
    base = cfg.forge.base_branch
    if branch != base:
        raise _usage(f"{target.id} is merged: check out {base} to add feedback to it (now on {branch or 'no branch'})")
    return replace(target, merged=True)


def _refuse_derived(target: FeedbackTarget) -> None:
    """Review #5: a follow-up and a fix unit judge their parent's items, so a `feedback.md` of their own is never read
    (it would be taken again every round). Writing commands send the person to the parent."""
    marker = read_follow_up_marker(target.dir) or read_fix_marker(target.dir)
    if marker is not None:
        kind = "follow-up" if read_follow_up_marker(target.dir) is not None else "fix unit"
        raise _usage(
            f"{target.id} is a {kind} of {marker.parent}: it takes no feedback of its own; give the feedback on the "
            f"parent ({marker.parent}), in its feedback.md"
        )


def _require_unit_branch(app: AppContext, cfg: L4Config, target: FeedbackTarget) -> FeedbackTarget:
    """Review #12: an open unit reads `feedback.md` from its own branch; a commit on the base is read only after the
    merge, as a follow-up. A merged unit's file goes to the base branch (`_after_merge`). The checkout is the unit's
    own branch, or any checkout (detached, or a local branch of another name) whose HEAD is the head of
    `origin/<unit branch>`: L4's worktree cache can hold the branch, so it cannot always be checked out. The commit
    then goes to the unit branch with `git push origin HEAD:<unit branch>`."""
    git = _git(app)
    if git is None or target.merged:
        return target
    branch = git.run("symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip()
    wanted = f"{cfg.forge.branch_prefix}{target.framework.value}/{target.name}"
    if branch == wanted:
        return target
    head = git.run("rev-parse", "--verify", "-q", "HEAD^{commit}", check=False).stdout.strip()
    remote = git.run("rev-parse", "--verify", "-q", f"refs/remotes/origin/{wanted}^{{commit}}", check=False)
    if head and remote.returncode == 0 and remote.stdout.strip() == head:
        return replace(target, push_to=wanted)
    now = f"on {branch}" if branch else "detached"
    raise _usage(
        f"{target.id} is not merged: its feedback goes on the unit branch {wanted}, and HEAD ({now}) is not at the "
        f"head of origin/{wanted}. Run: git fetch origin {wanted} && git switch {wanted}. If that branch is already "
        "checked out elsewhere (`git worktree list` shows where; L4's own cache is ~/.cache/l4/worktrees/...), run: "
        f"git switch --detach origin/{wanted}"
    )


def resolve_feedback_dir(app: AppContext, cfg: L4Config, unit: str | None, *, write: bool = False) -> FeedbackTarget:
    """The unit folder `feedback.md` belongs to: `--unit`, else the unit of the checked-out branch, else exit 2 with
    the units listed. A `merged` unit's folder is its archive folder (OpenSpec, when archived) or its spec folder on
    the base branch (L4-FBK-010). With `write` (add, submit, withdraw), a follow-up or a fix unit is refused
    and an open unit must be on its own branch."""
    target = _resolve(app, cfg, unit)
    if write:
        _refuse_derived(target)
        target = _require_unit_branch(app, cfg, target)
    return target


def _resolve(app: AppContext, cfg: L4Config, unit: str | None) -> FeedbackTarget:
    providers = providers_for(cfg, app.repo, app.environ)
    chosen = unit or _unit_of_branch(app, cfg)
    if chosen is None:
        ids = [ref.id for _, ref in select_units(providers, ())]
        listed = f"units: {', '.join(ids)}" if ids else "this repository has no units"
        raise _usage(
            f"no unit: pass --unit ID or check out a unit branch ({cfg.forge.branch_prefix}<framework>/<name>); "
            f"{listed}"
        )
    try:
        ((provider, ref),) = select_units(providers, (chosen,))
    except UnknownUnit as exc:
        framework, _, name = chosen.partition(":")
        archived = archive_folder(app, cfg, name) if framework == Framework.OPENSPEC.value else None
        if archived is None:
            raise _usage(str(exc)) from None
        return _after_merge(app, cfg, FeedbackTarget(Framework.OPENSPEC, name, archived, merged=True))
    return _after_merge(app, cfg, FeedbackTarget(ref.framework, ref.name, provider.unit_dir(ref)))


# --- --at ------------------------------------------------------------------------------------------------------


def _quote(place: Place, lines: list[str]) -> Quote:
    """At most 40 lines or 4,000 bytes of the named lines; a cut ends with an ellipsis line."""
    assert place.start is not None and place.end is not None
    wanted = lines[place.start - 1 : place.end]
    kept: list[str] = []
    size = 0
    for line in wanted:
        if len(kept) == MAX_QUOTE_LINES or size + len(line.encode()) + 1 > MAX_QUOTE_BYTES:
            break
        kept.append(line)
        size += len(line.encode()) + 1
    if not kept:  # one line longer than the limit: its first bytes
        kept = [wanted[0].encode()[:MAX_QUOTE_BYTES].decode(errors="ignore")]
    if len(kept) < len(wanted) or size > MAX_QUOTE_BYTES:
        kept.append(ELLIPSIS)
    return Quote(place.label, LANGUAGES.get(PurePosixPath(place.path).suffix.lower(), ""), "\n".join(kept))


def parse_at(app: AppContext, cfg: L4Config, spec: str) -> tuple[Place, Quote | None]:
    """One `--at PATH[:L[-L]]`: the place and the lines it names (None for a whole file). Exit 2 for anything that is
    not a text file of this repository's code that exists in the working tree."""
    match = _AT.fullmatch(spec)
    if match is None:
        raise _usage(f"--at {spec!r}: expected PATH[:L[-L]]")
    path = PurePosixPath(match["path"])
    parts = path.parts
    if path.is_absolute() or ".." in parts or "\\" in match["path"] or "`" in match["path"] or not parts:
        raise _usage(f"--at {spec!r}: give a path relative to the repository")
    folded = tuple(part.casefold() for part in parts)  # a case-insensitive file system opens `.L4/` as `.l4/`
    if ".l4" in folded or ".git" in folded:
        raise _usage(f"--at {spec!r}: .l4/ and .git/ are not code")
    for root in (cfg.spec.openspec.root, cfg.spec.kiro.root):
        root_parts = tuple(part.casefold() for part in PurePosixPath(root).parts)
        if root_parts and folded[: len(root_parts)] == root_parts:
            raise _usage(f"--at {spec!r}: {root}/ holds specs, not code")
    try:
        reject_symlinks(app.repo, *parts)
        data = read_regular_file(app.repo.joinpath(*parts), limit=MAX_SOURCE_BYTES)
    except (FileNotFoundError, NotADirectoryError):
        raise _usage(f"--at {spec!r}: no such file in the working tree") from None
    except UnsafeFile as exc:
        raise _usage(f"--at {spec!r}: {exc}") from None
    except OSError as exc:
        raise _usage(f"--at {spec!r}: {exc.strerror or exc}") from None
    if match["start"] is None:
        return Place(path.as_posix()), None
    if b"\0" in data:
        raise _usage(f"--at {spec!r}: not a text file")
    lines = data.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    start = int(match["start"])
    end = int(match["end"]) if match["end"] else start
    if start < 1 or end < start or end > len(lines):
        raise _usage(f"--at {spec!r}: lines {start}-{end} do not exist ({path.as_posix()} has {len(lines)} lines)")
    place = Place(path.as_posix(), start, end)
    return place, _quote(place, lines)


# --- add -------------------------------------------------------------------------------------------------------


def _read_text(text: str) -> str:
    return sys.stdin.read() if text == "-" else text


def _title(text: str) -> str:
    """The first line, at most MAX_TITLE characters, cut on a word when one ends in the second half (it also goes into
    the printed commit message, where a word cut in two reads as a typo)."""
    first = " ".join(next((line for line in text.splitlines() if line.strip()), "").split())
    if len(first) <= MAX_TITLE:
        return first
    cut = first.rfind(" ", 0, MAX_TITLE + 1)
    return (first[:cut] if cut >= MAX_TITLE // 2 else first[:MAX_TITLE]).rstrip()


def _by(app: AppContext) -> str:
    git = _git(app)
    name = git.run("config", "user.name", check=False).stdout.strip() if git is not None else ""
    return f"{name or 'unknown'}, {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"


def _as_options(found: tuple[str, ...]) -> list[str]:
    """The kind rules name fields (`config needs Env`); the person typed options (`--env`)."""
    return [re.sub(r"\b(Where|Env|When|Then)\b", lambda m: _OPTION_OF[m.group(1)], problem) for problem in found]


def _shell(message: str) -> str:
    return shlex.quote(message) if re.search(r'["$`\\!]', message) else f'"{message}"'


def _git_lines(app: AppContext, cfg: L4Config, target: FeedbackTarget, message: str) -> list[str]:
    rel = (target.dir / FEEDBACK_FILENAME).relative_to(app.repo).as_posix()
    base = cfg.forge.base_branch
    last = (
        f"then get the commit onto {base} by your usual route (a pull request or a push); the next {base} run "
        "creates a follow-up unit for it"
        if target.merged
        else (f"git push origin HEAD:{target.push_to}" if target.push_to else "git push")
    )
    return [rel, f"git add {rel}", f"git commit -m {_shell(f'feedback({target.name}): {message}')}", last]


def _echo(app: AppContext, lines: list[str]) -> None:
    click.echo(app.redactor.redact_text("\n".join(lines)))


def run_feedback_add(
    app: AppContext, *, kind: str, text: str, title: str | None, at: tuple[str, ...], env: str | None,
    when: str | None, then: str | None, lesson: bool, draft: bool, unit: str | None,
) -> ExitCode:  # fmt: skip
    body = _read_text(text)
    if not body.strip():
        raise _usage("--text is empty")
    if len(at) > MAX_PLACES:
        raise _usage(f"--at: at most {MAX_PLACES} places")
    app, cfg = load_app_config(app)
    target = resolve_feedback_dir(app, cfg, unit, write=True)
    parsed = [parse_at(app, cfg, spec) for spec in at]
    new = NewFeedback(
        kind=FeedbackKind(kind), title=title or _title(body), text=body, by=_by(app),
        places=tuple(place for place, _ in parsed), code=tuple(quote for _, quote in parsed if quote is not None),
        env=env, when=when, then=then, lesson=lesson, draft=draft,
    )  # fmt: skip
    if found := new_problems(new):
        raise _usage("; ".join(_as_options(found)))
    fid = append_item(target.dir, target.name, new, redactor=app.redactor)
    written = FeedbackFile.load(target.dir)
    item = written.get(fid) if written is not None else None
    shown_title = item.title if item is not None else new.title
    status = FeedbackStatus.DRAFT if draft else FeedbackStatus.SUBMITTED
    if target.push_to:
        click.echo(
            f"feedback goes to the unit branch {target.push_to} (HEAD is the head of origin/{target.push_to})", err=True
        )
    _echo(app, [f"{fid} {status.value}", *_git_lines(app, cfg, target, f"{fid} {shown_title}")])
    return ExitCode.OK


# --- list, show ------------------------------------------------------------------------------------------------


def item_json(item: FeedbackItem) -> dict[str, object]:
    return {
        "id": item.id, "title": item.title, "status": item.status.value,
        "kind": item.kind.value if item.kind else item.kind_text,
        "places": [{"path": p.path, "start": p.start, "end": p.end} for p in item.places],
        "env": item.env, "when": item.when, "then": item.then, "lesson": item.lesson, "by": item.by,
        "code": item.code, "text": item.text, "outcome": item.outcome,
        "problems": list(problems(item)), "content_sha256": content_sha256(item),
    }  # fmt: skip


def _load(target: FeedbackTarget) -> FeedbackFile | None:
    return FeedbackFile.load(target.dir)


def _find(file: FeedbackFile | None, fid: str, target: FeedbackTarget) -> FeedbackItem:
    item = file.get(fid) if file is not None else None
    if item is None:
        raise _usage(f"{target.id} has no {fid}" if file is not None else f"{target.id} has no {FEEDBACK_FILENAME}")
    return item


def run_feedback_list(app: AppContext, *, unit: str | None, as_json: bool) -> ExitCode:
    app, cfg = load_app_config(app)
    target = resolve_feedback_dir(app, cfg, unit)
    file = _load(target)
    items = file.items if file is not None else ()
    if as_json:
        text = json.dumps(
            {"schema": SCHEMA, "unit": target.id, "items": [item_json(i) for i in items]}, indent=2, ensure_ascii=False
        )
    elif not items:
        text = "no feedback"
    else:
        rows = []
        for item in items:
            first = item.places[0] if item.places else None
            place = (f"{first.path}:{first.start}" if first.start is not None else first.path) if first else ""
            kind = item.kind.value if item.kind else item.kind_text
            row = f"{item.id}  {item.status.value}  {kind}  {place}  {item.title}"
            found = problems(item)
            rows.append(f"{row}  [invalid: {'; '.join(found)}]" if found else row)
        text = "\n".join(rows)
    click.echo(app.redactor.redact_text(text))
    return ExitCode.OK


def run_feedback_show(app: AppContext, *, item: str, unit: str | None, as_json: bool) -> ExitCode:
    app, cfg = load_app_config(app)
    target = resolve_feedback_dir(app, cfg, unit)
    file = _load(target)
    found = _find(file, item, target)
    if as_json:
        text = json.dumps({"schema": SCHEMA, "unit": target.id, "item": item_json(found)}, indent=2, ensure_ascii=False)
    else:
        assert file is not None
        text = file.data[found.section.start : found.section.end].decode("utf-8", errors="replace")
        if reasons := problems(found):
            text += f"\n\ninvalid: {'; '.join(reasons)}"
    click.echo(app.redactor.redact_text(text))
    return ExitCode.OK


# --- submit, withdraw ------------------------------------------------------------------------------------------


def _set_status(app: AppContext, unit: str | None, fid: str, status: FeedbackStatus, verb: str) -> ExitCode:
    app, cfg = load_app_config(app)
    target = resolve_feedback_dir(app, cfg, unit, write=True)
    file = _load(target)
    item = _find(file, fid, target)
    assert file is not None
    if item.status is status:
        click.echo(app.redactor.redact_text(f"{item.id} is already {status.value}"))
        return ExitCode.OK
    if status is FeedbackStatus.SUBMITTED:
        if item.status is not FeedbackStatus.DRAFT:
            raise _usage(f"{item.id} is {item.status.value}: only a draft is submitted (add a new item instead)")
        if found := problems(item):
            raise _usage(f"{item.id} cannot be submitted: {'; '.join(found)}")
    elif item.status is FeedbackStatus.ADDRESSED:
        raise _usage(f"{item.id} is already addressed")
    file.set_status(item.id, status).save()
    _echo(app, [f"{item.id} {status.value}", *_git_lines(app, cfg, target, f"{verb} {item.id} {item.title}")])
    return ExitCode.OK


def run_feedback_submit(app: AppContext, *, item: str, unit: str | None) -> ExitCode:
    return _set_status(app, unit, item, FeedbackStatus.SUBMITTED, "submit")


def run_feedback_withdraw(app: AppContext, *, item: str, unit: str | None) -> ExitCode:
    return _set_status(app, unit, item, FeedbackStatus.WITHDRAWN, "withdraw")
