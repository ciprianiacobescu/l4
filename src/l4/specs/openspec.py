"""The OpenSpec provider (SPEC 4.4): file-based unit listing and task parsing, plus the pinned CLI for validation."""

import json
import os
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l4.config.defaults import cache_root, openspec_entrypoint, openspec_env, resolve_executable
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, read_regular_file, reject_symlinks
from l4.proc import Runner, run_process
from l4.specs.base import (
    MAX_DECISION_CHARS,
    ArchiveFailed,
    ArchiveRefused,
    ArchiveReport,
    Criterion,
    DeltaRequirement,
    Finding,
    FixUnitExists,
    FixUnitInvalid,
    Framework,
    GateReport,
    Marker,
    MarkerNotAllowed,
    OpenSpecCommandError,
    OpenSpecUnavailable,
    SpecDelta,
    SpecError,
    Task,
    Unit,
    UnitRef,
    ValidationIssue,
    ValidationReport,
)
from l4.specs.criteria import criterion_id, openspec_criteria
from l4.specs.fixmark import FixMarker, fix_name, write_fix_marker
from l4.specs.markers import MAX_TASKS_BYTES, split_lines, write_marker

CLI_TIMEOUT_SECONDS = 60.0
CHANGE_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")  # OpenSpec's own kebab-case rule
ARCHIVE_REFUSAL = "Archive would refuse this delta:"  # an INFO that L4-OSP-006 turns into an error

# OpenSpec 1.14.0 task grammar, an exact port (spikes/04): JavaScript's \s includes U+FEFF and U+00A0, `.` stops at
# \n \r U+2028 U+2029, digits are ASCII, and JavaScript's trim strips the same whitespace class.
_JS_WS = "\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_JS_TRIM = _JS_WS.replace("\u2000-\u200a", "".join(chr(c) for c in range(0x2000, 0x200B)))
_S = f"[{_JS_WS}]"
_DOT = "[^\n\r\u2028\u2029]"
OPENSPEC_TASK_RE = re.compile(
    rf"^{_S}*(?:[-*+]|[0-9]{{1,9}}[.)]){_S}*\[(?:{_S}*([^\]{_JS_WS}]?){_S}*\](?![(\[])|{_S}+\]){_S}*({_DOT}*)"
)
_TASK_NUMBER_RE = re.compile(rf"^([0-9]+(?:\.[0-9]+)+(?:[A-Za-z]+)?)(?={_S}|$)")


def _indent(text: str) -> int:
    body = text.removeprefix("\ufeff")
    return len(body) - len(body.lstrip(_JS_TRIM))


def parse_openspec_tasks(data: bytes) -> list[Task]:
    """Every checkbox line the OpenSpec CLI counts, in document order.

    Checkboxes inside code fences and HTML comments count, as in OpenSpec. A checkbox with no text is returned with
    an empty title: it is in the CLI's `progress` but not in its `tasks[]`.
    """
    tasks: list[Task] = []
    for line in split_lines(data):
        match = OPENSPEC_TASK_RE.match(line.text)
        if not match:
            continue
        title = match.group(2).strip(_JS_TRIM)
        number_match = _TASK_NUMBER_RE.match(title)
        number = number_match.group(1) if number_match else None
        bracket = line.text.index("[")  # the first "[" is the checkbox: the bullet cannot contain one
        interior = line.text[bracket + 1 : line.text.index("]", bracket)]
        tasks.append(
            Task(
                key=number or f"L{line.number}",
                number=number,
                title=title,
                done=(match.group(1) or "").lower() == "x",
                marker_char=interior,
                depth=_indent(line.text),
                line=line.number,
                marker_offset=line.offset_of(bracket + 1) if len(interior) == 1 else None,
            )
        )
    return tasks


@dataclass(frozen=True)
class CliResult:
    argv: tuple[str, ...]  # the arguments after `node openspec.js`
    returncode: int
    data: dict[str, Any]


class OpenSpecCli:
    """The pinned OpenSpec CLI (L4-OSP-001): `<node> <prefix>/node_modules/@fission-ai/openspec/bin/openspec.js ...`.

    Never the `.bin` shim, `npx` or a PATH lookup of `openspec`: a package planted in the repository would run.
    M1: spec-providers 1.14 (ensure_installed), 1.15 (argv allow-list), 1.17 (verify_root).
    """

    def __init__(self, repo: Path, environ: Mapping[str, str], *, runner: Runner = run_process) -> None:
        self._repo = repo
        self._environ = environ
        self._runner = runner

    def _command(self) -> list[str]:
        cache_root(self._environ, repo=self._repo)  # exit 2 if $L4_CACHE is inside the repo: the XDG dirs live there
        node = resolve_executable("node", self._environ, forbid=(self._repo,))
        if node is None:
            raise OpenSpecUnavailable("node was not found on PATH; run `l4 doctor`")
        entry = openspec_entrypoint(self._environ)
        if not entry.is_file():
            raise OpenSpecUnavailable(f"the pinned OpenSpec is not installed ({entry} is missing); run `l4 doctor`")
        repo = self._repo.resolve()
        if repo == entry.resolve() or repo in entry.resolve().parents:
            raise OpenSpecUnavailable(f"the OpenSpec install ({entry}) is inside the repository; refusing to run it")
        return [node, str(entry)]

    def run_json(self, *args: str) -> CliResult:
        """Run one command and parse stdout as the single JSON document every `--json` call prints."""
        argv = [*self._command(), *args]
        env = openspec_env(self._environ, forbid=(self._repo,))
        done = self._runner(argv, self._repo.resolve(), env, CLI_TIMEOUT_SECONDS)
        try:
            data = json.loads(done.stdout)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            detail = done.stderr.strip().splitlines()[:1]
            raise OpenSpecCommandError(
                f"`openspec {' '.join(args)}` printed output that is not JSON (exit {done.returncode})"
                + (f": {detail[0][:200]}" if detail else "")
            )
        return CliResult(tuple(args), done.returncode, data)


class OpenSpecProvider:
    """OpenSpec units of one repository checkout (the main repo or a unit worktree).

    Units are listed from `openspec/changes/*` on disk and loaded from files; only `validate` starts the CLI.
    M1: spec-providers 1.19 (archived units, verify_root), 1.20 (progress_agreement), 1.23 (the validation of each
    capability after the archive, L4-OSP-003).
    """

    framework = Framework.OPENSPEC

    def __init__(
        self, repo: Path, environ: Mapping[str, str], *, cli: OpenSpecCli | None = None, root: str = "openspec"
    ) -> None:
        relative = Path(root)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise L4Exit(
                ExitCode.USAGE_ERROR, f"spec.openspec.root must be a relative path inside the repo, got {root!r}"
            )
        self._repo = repo
        self._changes_parts = (*relative.parts, "changes")
        self._changes = repo.joinpath(*self._changes_parts)
        self._cli = cli or OpenSpecCli(repo, environ)

    def list_units(self) -> list[UnitRef]:
        try:
            reject_symlinks(self._repo, *self._changes_parts)
        except UnsafeFile:
            return []  # a symlinked `openspec/` or `changes/` would list units from outside the repository
        if not self._changes.is_dir():
            return []
        return [
            UnitRef(Framework.OPENSPEC, entry.name, entry)
            for entry in sorted(self._changes.iterdir(), key=lambda p: p.name)
            if entry.is_dir() and not entry.is_symlink() and entry.name != "archive" and CHANGE_NAME.match(entry.name)
        ]

    def unit_dir(self, unit: UnitRef) -> Path:
        try:
            reject_symlinks(self._repo, *self._changes_parts, unit.name)
        except UnsafeFile as exc:
            raise SpecError(str(exc)) from None
        return self._changes / unit.name

    def tasks(self, unit: UnitRef) -> list[Task]:
        try:
            data = read_regular_file(self.unit_dir(unit) / "tasks.md", limit=MAX_TASKS_BYTES)
        except FileNotFoundError:
            return []
        except UnsafeFile as exc:
            raise SpecError(str(exc)) from None
        return parse_openspec_tasks(data)

    def criteria(self, unit: UnitRef) -> list[Criterion]:
        return openspec_criteria(self.unit_dir(unit))

    def load(self, unit: UnitRef) -> Unit:
        return Unit(unit, tuple(self.tasks(unit)), tuple(self.criteria(unit)))

    def set_marker(self, unit: UnitRef, task_key: str, marker: Marker) -> None:
        """Tick `[ ]` -> `[x]`. OpenSpec has no in-progress or queued marker, and no other change is written."""
        if marker is not Marker.DONE:
            raise MarkerNotAllowed(f"OpenSpec tasks can only be marked done, not {marker.name.lower()}")
        matches = [t for t in self.tasks(unit) if t.key == task_key]
        if not matches:
            raise SpecError(f"{unit.id} has no task {task_key}")
        if len(matches) > 1:
            raise MarkerNotAllowed(f"task id {task_key} is ambiguous in {unit.id} ({len(matches)} checkboxes)")
        (task,) = matches
        if task.marker_char != " " or task.marker_offset is None:
            why = (
                "already ticked or not an unchecked box"
                if task.marker_offset is not None
                else ("its brackets do not hold a single byte")
            )
            raise MarkerNotAllowed(f"task {task_key} of {unit.id} cannot be ticked: {why}")
        path = self.unit_dir(unit) / "tasks.md"
        line = split_lines(read_regular_file(path, limit=MAX_TASKS_BYTES))[task.line - 1].text
        bracket = line.index("[")
        ticked = OPENSPEC_TASK_RE.match(f"{line[: bracket + 1]}x{line[bracket + 2 :]}")
        if not ticked or ticked.group(1) != "x":  # e.g. `- [ ](url) text`: `[x](url)` is no checkbox to OpenSpec
            raise MarkerNotAllowed(f"task {task_key} of {unit.id} would stop being a checkbox once ticked")
        write_marker(path, task.marker_offset, b" ", b"x")

    def done_gate(self, unit: UnitRef) -> GateReport:
        """Every checkbox done. `archive --yes` archives with open tasks and says nothing about them in `--json`
        (spikes/04), so this is the only barrier (L4-OSP-003)."""
        tasks = self.tasks(unit)
        if not tasks:
            return GateReport(False, ("the unit has no tasks",))
        return GateReport(
            all(t.done for t in tasks),
            tuple(f"task {t.key} is not done ({t.title or 'no text'})" for t in tasks if not t.done),
        )

    def create_fix_unit(
        self, parent: UnitRef, round: int, findings: Sequence[Finding], spec_delta: SpecDelta | None
    ) -> UnitRef:
        """`<parent>-fix-<round>` (L4-OSP-005, L4-VER-006): `openspec new change`, then the scaffold the CLI does not
        write, then `validate --strict`. Whatever the CLI created outside the change (it writes `openspec/config.yaml`
        when the repository has none) is removed again, and so is the whole folder when it does not validate. The task
        lines cite the finding ids and the criteria: the existing ones and the ones the delta adds."""
        name = fix_name(parent.name, round)
        if not CHANGE_NAME.match(name):
            raise SpecError(f"{name!r} is not a valid change name")
        ref = UnitRef(Framework.OPENSPEC, name, self._changes / name)
        folder = self.unit_dir(ref)
        if folder.exists():
            raise FixUnitExists(f"{ref.id} exists; a fix unit is never overwritten")
        if not findings:
            raise SpecError("a fix unit needs at least one finding")
        root = self._changes.parent
        before = set(os.listdir(root)) if root.is_dir() else set()
        try:
            self._new_change(name, folder)
            self._scaffold(parent, ref, round, findings, spec_delta)
            report = self.validate(ref, strict=True)
            if not report.valid:
                errors = [i for i in report.issues if i.level == "ERROR"] or list(report.issues)
                shown = "; ".join(f"{i.path}: {i.message}"[:200] for i in errors[:3])
                raise FixUnitInvalid(f"{ref.id} does not validate --strict: {shown or 'no detail from openspec'}")
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        finally:
            self._remove_strays(root, before)
        return ref

    @staticmethod
    def _remove_strays(root: Path, before: set[str]) -> None:
        """The CLI's own side effects: entries it added next to `changes/` and `specs/`."""
        for extra in (set(os.listdir(root)) - before) if root.is_dir() else ():
            path = root / extra
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    def _new_change(self, name: str, folder: Path) -> None:
        args = ("new", "change", name, "--json")
        reply = self._cli.run_json(*args)
        change = reply.data.get("change")
        if reply.returncode != 0 or not isinstance(change, dict) or change.get("id") != name:
            failure = next(iter(reply.data.get("status") or []), {})
            why = failure.get("message", "no change was created")
            raise OpenSpecCommandError(f"`openspec {' '.join(args)}`: {why}")
        if not (folder / ".openspec.yaml").is_file():
            raise OpenSpecCommandError(f"`openspec {' '.join(args)}` wrote no .openspec.yaml for {name}")

    def _scaffold(
        self, parent: UnitRef, ref: UnitRef, round: int, findings: Sequence[Finding], delta: SpecDelta | None
    ) -> None:
        folder = ref.path
        meta = folder / ".openspec.yaml"
        if delta is None:  # without it a change with no delta fails `validate --strict` [V, 1.14.0]
            text = meta.read_text(encoding="utf-8")
            meta.write_text(text + ("" if text.endswith("\n") or not text else "\n") + "skip_specs: true\n")
        new_criteria = self._write_delta(parent, folder, delta) if delta is not None else {}
        (folder / "proposal.md").write_text(_proposal(parent, round, findings), encoding="utf-8")
        (folder / "tasks.md").write_text(_tasks(findings, new_criteria), encoding="utf-8")
        write_fix_marker(
            folder,
            FixMarker(
                parent.id, round, tuple(i for f in findings for i in f.ids),
                tuple(i for f in findings if f.chore for i in f.ids),
                tuple(i for f in findings if f.chore and f.tests for i in f.ids),
            ),
        )  # fmt: skip

    def _write_delta(self, parent: UnitRef, folder: Path, delta: SpecDelta) -> dict[str, list[str]]:
        """`specs/<capability>/spec.md` per capability. Returns finding id -> the ids of the criteria it added."""
        added: dict[str, list[str]] = {}
        for capability in dict.fromkeys(r.capability for r in delta.requirements):
            target = folder / "specs" / capability
            target.mkdir(parents=True, exist_ok=True)
            blocks = [_requirement(r) for r in delta.requirements if r.capability == capability]
            text = f"# Spec Delta\n\n## Purpose\n{self._purpose(parent, capability)}\n\n## ADDED Requirements\n\n"
            (target / "spec.md").write_text(text + "\n".join(blocks), encoding="utf-8")
            for r in (r for r in delta.requirements if r.capability == capability):
                for s in r.scenarios:
                    cid = criterion_id(Framework.OPENSPEC.value, capability, _flat(r.title), _flat(s.name))
                    added.setdefault(s.finding, []).append(cid)
        return added

    def _purpose(self, parent: UnitRef, capability: str) -> str:
        """The parent's own `## Purpose` for the capability: a capability that is new when the parent is archived needs
        one of at least 50 characters, or the archive writes a `TBD` that fails strict validation (L4-OSP-007)."""
        try:
            raw = read_regular_file(self.unit_dir(parent) / "specs" / capability / "spec.md", limit=MAX_PURPOSE_BYTES)
        except (FileNotFoundError, UnsafeFile, SpecError):
            raw = b""
        match = re.search(r"^## Purpose[ \t]*\n(.*?)(?=^## |\Z)", raw.decode("utf-8", "replace"), re.M | re.S)
        purpose = _flat(match.group(1), 1500) if match else ""
        if len(purpose) >= MIN_PURPOSE_CHARS:
            return purpose
        return f"Regression scenarios for the {capability} capability, found by the verifier in {parent.name}."

    def archive(self, unit: UnitRef) -> ArchiveReport:
        """The done-gate and a strict validation first; only then `archive <id> --yes --json` (TZ=UTC is in the
        environment of every call). Whatever the CLI does not refuse, the caller checks in git."""
        gate = self.done_gate(unit)
        if not gate.passed:
            raise ArchiveRefused(f"{unit.id} is not done: {'; '.join(gate.reasons)}")
        report = self.validate(unit, strict=True)
        if not report.valid:
            first = next((i for i in report.issues if i.level == "ERROR"), report.issues[0] if report.issues else None)
            raise ArchiveRefused(
                f"{unit.id} fails strict validation" + (f": {first.path}: {first.message}" if first else "")
            )
        args = ["archive", unit.name, "--yes", "--json"]
        reply = self._cli.run_json(*args)
        archived = reply.data.get("archive")
        if reply.returncode != 0 or not isinstance(archived, dict):
            failure = next(iter(reply.data.get("status") or []), {})
            raise ArchiveFailed(str(failure.get("code", "unknown")), str(failure.get("message", "no reason given")))
        name = archived.get("archivedAs")
        if not isinstance(name, str) or not re.fullmatch(rf"\d{{4}}-\d{{2}}-\d{{2}}-{re.escape(unit.name)}", name):
            raise ArchiveFailed("archive_reply", f"archivedAs is not the dated folder of {unit.name}: {name!r}")
        return ArchiveReport(name, archived.get("specsUpdated") is True)

    def validate(self, unit: UnitRef, strict: bool = True) -> ValidationReport:
        args = ["validate", unit.name, *(["--strict"] if strict else []), "--json"]
        reply = self._cli.run_json(*args).data
        for failure in reply.get("status") or []:  # {"status":[{severity, code, message}]}: unknown item and the like
            raise OpenSpecCommandError(f"`openspec {' '.join(args)}`: {failure.get('code')}: {failure.get('message')}")
        item = next((i for i in reply.get("items") or [] if i.get("id") == unit.name), None)
        if item is None:
            raise OpenSpecCommandError(f"`openspec {' '.join(args)}` returned no result for {unit.name}")
        issues = tuple(_issue(raw) for raw in item.get("issues") or [])
        return ValidationReport(bool(item.get("valid")) and not any(i.level == "ERROR" for i in issues), issues)


MAX_PURPOSE_BYTES = 256 * 1024
MIN_PURPOSE_CHARS = 50
MAX_TITLE_CHARS = 160
MAX_DETAIL_CHARS = 600


def _flat(text: str, limit: int = MAX_TITLE_CHARS) -> str:
    """One line of plain text for a heading, a task or a proposal: text from findings is model-written and must not
    open a heading, a list or a checkbox of its own."""
    one = " ".join(text.split()).lstrip("#>*-+ ")
    return one if len(one) <= limit else one[: limit - 3].rstrip() + "..."


def _requirement(r: DeltaRequirement) -> str:
    lines = [f"### Requirement: {_flat(r.title)}", "The behaviour pinned by the scenarios below SHALL hold.", ""]
    for s in r.scenarios:
        lines += [f"#### Scenario: {_flat(s.name)}", s.text.strip(), ""]
    return "\n".join(lines)


def _proposal(parent: UnitRef, round: int, findings: Sequence[Finding]) -> str:
    cites = "\n".join(
        f"- {', '.join(f.ids)} ({f.severity}): {_flat(f.title)}"
        + (f": {_flat(f.detail, MAX_DETAIL_CHARS + MAX_DECISION_CHARS + 400)}" if f.detail else "")
        for f in findings
    )
    return (
        f"# Proposal: fix {round} for {parent.name}\n\n## Why\n"
        f"The verifier found problems in `{parent.name}` that this change fixes. The findings are listed below with "
        f"their ids; each task of this change names the ones it answers.\n\n## What Changes\n{cites}\n\n"
        f"## Impact\nThe code and the tests of `{parent.name}`.\n"
    )


def _tasks(findings: Sequence[Finding], added: Mapping[str, Sequence[str]]) -> str:
    lines = ["# Tasks", "", "## 1. Fix", ""]
    for number, f in enumerate(findings, 1):
        criteria = [*f.criteria, *(c for i in f.ids for c in added.get(i, ()))]
        cites = "; ".join([", ".join(f.ids), *([", ".join(dict.fromkeys(criteria))] if criteria else [])])
        lines.append(f"- [ ] 1.{number} {_flat(f.title)} ({cites})")
    return "\n".join(lines) + "\n"


def _issue(raw: Mapping[str, Any]) -> ValidationIssue:
    level = str(raw.get("level", "")).upper()
    message = str(raw.get("message", ""))
    if level not in ("ERROR", "WARNING", "INFO") or message.startswith(ARCHIVE_REFUSAL):
        level = "ERROR"
    line = raw.get("line")
    return ValidationIssue(level, str(raw.get("path", "")), message, line if isinstance(line, int) else None)  # type: ignore[arg-type]
