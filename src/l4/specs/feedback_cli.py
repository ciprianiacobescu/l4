"""`l4 feedback add|list|show|submit|withdraw` (L4-FBK-003): the handlers named in `commands.HANDLERS`.

The commands write `feedback.md` and nothing else: no commit, no push, no forge call. The unit folder is found in
one place (`resolve_feedback_dir`).
"""

import json
import re
import shlex
import sys
from dataclasses import dataclass
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
from l4.specs.providers import providers_for
from l4.state.status import select_units
from l4.vcs.git import Git

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


def resolve_feedback_dir(app: AppContext, cfg: L4Config, unit: str | None) -> FeedbackTarget:
    """The unit folder `feedback.md` belongs to: `--unit`, else the unit of the checked-out branch, else exit 2 with
    the units listed. (A merged unit's archive folder is human-feedback 5.1.)"""
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
        raise _usage(str(exc)) from None
    return FeedbackTarget(ref.framework, ref.name, provider.unit_dir(ref))


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
    if ".l4" in parts or ".git" in parts:
        raise _usage(f"--at {spec!r}: .l4/ and .git/ are not code")
    for root in (cfg.spec.openspec.root, cfg.spec.kiro.root):
        root_parts = PurePosixPath(root).parts
        if root_parts and parts[: len(root_parts)] == root_parts:
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
    first = next((line for line in text.splitlines() if line.strip()), "")
    return " ".join(first.split())[:MAX_TITLE].rstrip()


def _by(app: AppContext) -> str:
    git = _git(app)
    name = git.run("config", "user.name", check=False).stdout.strip() if git is not None else ""
    return f"{name or 'unknown'}, {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"


def _as_options(found: tuple[str, ...]) -> list[str]:
    """The kind rules name fields (`config needs Env`); the person typed options (`--env`)."""
    return [re.sub(r"\b(Where|Env|When|Then)\b", lambda m: _OPTION_OF[m.group(1)], problem) for problem in found]


def _shell(message: str) -> str:
    return shlex.quote(message) if re.search(r'["$`\\!]', message) else f'"{message}"'


def _git_lines(app: AppContext, target: FeedbackTarget, message: str) -> list[str]:
    rel = (target.dir / FEEDBACK_FILENAME).relative_to(app.repo).as_posix()
    return [rel, f"git add {rel}", f"git commit -m {_shell(f'feedback({target.name}): {message}')}", "git push"]


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
    target = resolve_feedback_dir(app, cfg, unit)
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
    _echo(app, [f"{fid} {status.value}", *_git_lines(app, target, f"{fid} {shown_title}")])
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
    target = resolve_feedback_dir(app, cfg, unit)
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
    _echo(app, [f"{item.id} {status.value}", *_git_lines(app, target, f"{verb} {item.id} {item.title}")])
    return ExitCode.OK


def run_feedback_submit(app: AppContext, *, item: str, unit: str | None) -> ExitCode:
    return _set_status(app, unit, item, FeedbackStatus.SUBMITTED, "submit")


def run_feedback_withdraw(app: AppContext, *, item: str, unit: str | None) -> ExitCode:
    return _set_status(app, unit, item, FeedbackStatus.WITHDRAWN, "withdraw")
