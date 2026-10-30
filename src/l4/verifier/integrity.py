"""Step 1 of the ladder, integrity (SPEC 10.2, L4-VER-002): the tests were not gamed.

`run_integrity` runs six sub-checks over `git diff <base> <head>`, the ledger and the commit graph, and returns one
row per sub-check plus the findings. A blocker or major finding stops the ladder with FAIL (all are deterministic).
Reduced for M1.3 (docs/plan/m13-plan.md): Python only; the protected-path check stands in for "no outstanding
`guard.violation`"; the red tests being present and passing at head is step 3's job (`must_contain`), because step 3
has the report; re-running the tests at the red commit is not done. Not built: the support-file AST rule (2.7),
test-only dependencies added in green (2.8), gate configuration and script entries (2.9), snapshots and the scope
check (2.11), the secret scan (2.12).
M1: verifier 2.7-2.9, 2.11, 2.12, 2.13 (the red re-run, verifier red commits, `pre_adoption`), other languages.
"""

import ast
import os
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from l4.config.loader import ConfigSchemaError, load_config_text
from l4.config.schema import L4Config
from l4.evidence.diffcov import CODE_SUFFIXES
from l4.gates.junit import fold_subtest_id
from l4.implementer.gateconfig import GateConfig, Kind, allowed_kinds
from l4.implementer.opened import check_opened, new_patches, unit_modules
from l4.implementer.tamper import Tampered, compare, facts_of, moved, names_test_id
from l4.security.protected import HumanChange, ProtectedSet, glob_match, protected_changes_by_human
from l4.security.pyencoding import COOKIE_PREFIX_BYTES, is_python_file, non_utf8, resolve_links
from l4.specs.base import Task
from l4.specs.feedback import FEEDBACK_FILENAME
from l4.specs.fixmark import task_marker
from l4.specs.followup import feedback_home, follow_up_problem
from l4.state.ledger import LedgerEvent
from l4.vcs.authorship import SHA, commit_records, is_harness
from l4.vcs.git import Git
from l4.verifier import scan
from l4.verifier.provenance import foreign_commits, foreign_memory_commits
from l4.verifier.scan import task_tags
from l4.verifier.types import Finding, IntegrityCheck, IntegrityReport, Severity

HARNESS_OWNED = (".serena/memories/harness/",)  # written by the harness after a PASS (M1.5), never by an agent: and
# only its own `L4-Phase: lessons` commits count as the harness writing (a planted file is a blocker)
_RUNNER_FILES = ("pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", "tox.ini", "setup.cfg")
MAX_LISTED = 5


@dataclass(frozen=True)
class IntegrityContext:
    git: Git  # runs in the worktree
    cfg: L4Config
    base_sha: str
    head_sha: str
    events: Sequence[LedgerEvent]
    tasks: Sequence[tuple[str, Task]]  # (unit id, task) of the unit and its fix units
    unit_dirs: Sequence[str]  # their directories, relative to the repository
    unit_id: str


@dataclass
class Outcome:
    findings: list[Finding] = field(default_factory=list)
    note: str = ""
    skipped: bool = False
    declared: list[str] = field(default_factory=list)
    human: list[HumanChange] = field(default_factory=list)  # allowed and listed, not findings (L4-SEC-004)
    human_tests: list[str] = field(default_factory=list)  # test changes only people's commits made: listed likewise
    unfrozen: list[str] = field(default_factory=list)  # frozen tests a human answer unfroze for green: listed likewise
    human_suppressions: list[str] = field(default_factory=list)  # inline suppressions a person's commit wrote: listed
    human_scan: list[str] = field(default_factory=list)  # content-scan hits only people's commits introduced: listed
    human_config: list[str] = field(default_factory=list)  # gate and runner configuration only people's commits changed
    allowed_tests: list[str] = field(default_factory=list)  # pre-existing test changes an allowance covers: listed
    mocked: list[str] = field(default_factory=list)  # patches of the unit's code a support fixture makes on request
    base_tests: dict[str, Any] | None = None  # the passed ids of the base's run (L4-VER-038), kept for later rounds
    listed: list[str] = field(default_factory=list)  # signs of a test run in production code, shown to the judge


def _human_tag(ctx: IntegrityContext, unit: str, title: str, tag: str) -> bool:
    """A person's `[tag]` on a task. A fix unit's task, and any task of a follow-up unit, was written by the harness
    from model-written findings: its tags exempt nothing (third review, M3)."""
    if tag not in task_tags(title):
        return False
    if unit != ctx.unit_id:
        return False  # a fix unit
    return not ctx.unit_dirs or task_marker(ctx.git.repo / ctx.unit_dirs[0]) is None


def _blocker(title: str, detail: str, severity: Severity = Severity.BLOCKER) -> Finding:
    return Finding(severity, title, detail, "deterministic")


def _matches(globs: Sequence[str], path: str) -> bool:
    return any(glob_match(glob, path) for glob in globs)


def _blob(git: Git, rev: str, path: str) -> bytes | None:
    if git.run("cat-file", "-e", f"{rev}:{path}", check=False).returncode != 0:
        return None
    return git.run_bytes("show", f"{rev}:{path}")


def _text(git: Git, rev: str, path: str) -> str:
    data = _blob(git, rev, path)
    return data.decode("utf-8", "replace") if data is not None else ""


def _changed(git: Git, base: str, head: str) -> dict[str, str]:
    """path -> status letter (A, M, D, T) of `git diff <base> <head>`."""
    fields = [f for f in git.run_bytes("diff", "--name-status", "-z", "--no-renames", base, head).split(b"\0") if f]
    return {
        path.decode("utf-8", "replace"): status.decode()[:1]
        for status, path in zip(fields[0::2], fields[1::2], strict=True)
    }


def _in_unit_dirs(ctx: IntegrityContext, path: str) -> bool:
    return any(path == d or path.startswith(d + "/") for d in ctx.unit_dirs)


def _suffix(path: str) -> str:
    return PurePosixPath(path).suffix.lower()


def _not_python(files: Sequence[str]) -> str:
    return f"not checked: python only; changed files outside it: {_listed(sorted(files))}"


def _listed(items: Sequence[str]) -> str:
    return ", ".join(items[:MAX_LISTED]) + (f" (+{len(items) - MAX_LISTED} more)" if len(items) > MAX_LISTED else "")


# --- 2.3 protected paths --------------------------------------------------------------------------------------------


def _follow_up_feedback(ctx: IntegrityContext) -> str | None:
    """A follow-up takes and judges the items of its parent's `feedback.md`: that one file of the parent's folder (on
    the follow-up's branch) is the harness's to write (L4-FBK-010), whatever else of the spec root is protected."""
    if not ctx.unit_dirs:
        return None
    root = ctx.git.repo
    folder = feedback_home(root / ctx.unit_dirs[0])  # the unit's own folder for a marker that does not validate
    if folder == root / ctx.unit_dirs[0]:
        return None
    try:
        return (folder / FEEDBACK_FILENAME).relative_to(root).as_posix()
    except ValueError:
        return None


def check_protected(ctx: IntegrityContext) -> Outcome:
    """A contract glob or an `odd.forbidden_paths` path that differs between base and head is a blocker. The unit
    directory and the harness's memory file are the harness's own, and so are the fix units' directories, but only
    through the harness's commits: a commit that touched a fix unit and is not one (bot author, `L4-Run` trailer) is
    a blocker, and so is a folder in the family's namespace (`<unit>-fix-*`) that is not one of its fix units. A
    protected path only people's commits changed (not the harness's) is listed in `Outcome.human`, not a finding."""
    parent = ctx.unit_dirs[0] if ctx.unit_dirs else None
    protected = ProtectedSet(
        tuple(ctx.cfg.odd.forbidden_paths), family_globs=(f"{parent}-fix-*",) if parent is not None else ()
    )
    hits, protected_paths = [], {}
    parents_file = _follow_up_feedback(ctx)
    if parent is not None and (why := follow_up_problem(ctx.git.repo / parent)) is not None:
        hits_invalid = [f"{parent}/.l4/followup.json ({why}; it exempts nothing)"]
    else:
        hits_invalid = []
    for path in sorted(_changed(ctx.git, ctx.base_sha, ctx.head_sha)):
        if _in_unit_dirs(ctx, path) or path.startswith(HARNESS_OWNED) or path == parents_file:
            continue
        if (rule := protected.match(path)) is not None:
            protected_paths[path] = rule
    # a protected path that only people's commits changed on the branch is allowed and listed (L4-SEC-004); one a
    # harness commit also touched, or that no commit in the range names, stays a blocker
    human = protected_changes_by_human(ctx.git, ctx.base_sha, ctx.head_sha, list(protected_paths))
    listed = {change.path for change in human}
    hits = [f"{path} ({rule})" for path, rule in protected_paths.items() if path not in listed] + hits_invalid
    for fix_dir in ctx.unit_dirs[1:]:
        if foreign := foreign_commits(ctx.git, ctx.base_sha, ctx.head_sha, fix_dir):
            hits.append(f"{fix_dir} (touched by non-harness commit {foreign[0][:10]})")
    for owned in HARNESS_OWNED:
        if foreign := foreign_memory_commits(ctx.git, ctx.base_sha, ctx.head_sha, owned.rstrip("/")):
            hits.append(f"{owned} (touched by non-harness commit {foreign[0][:10]})")
    extra = f" (+{len(human)} changed by humans, listed)" if human else ""
    if not hits:
        return Outcome(note=f"no protected path differs from the base{extra}", human=human)
    return Outcome(
        [_blocker("a protected path was changed", _listed(hits))],
        f"{len(hits)} protected path(s) changed{extra}",
        human=human,
    )


# --- 2.4 pre-existing tests -----------------------------------------------------------------------------------------


def _introducers(ctx: IntegrityContext, path: str, introduced: Callable[[str, str], bool]) -> list[list[str]]:
    """The commits of `base..head` that touch `path` and for which `introduced(text at the first parent, text at the
    commit)` holds: who made the change, one commit at a time."""
    found = []
    for record in commit_records(ctx.git, "--reverse", f"{ctx.base_sha}..{ctx.head_sha}", "--", f":(literal){path}"):
        if introduced(_text(ctx.git, f"{record[SHA]}^", path), _text(ctx.git, record[SHA], path)):
            found.append(record)
    return found


def _by_people(commits_: list[list[str]]) -> bool:
    """Only people's commits introduced it. Nobody found (the history cannot say) is not people: it stays a blocker."""
    return bool(commits_) and not any(is_harness(r) for r in commits_)


def _last_by_people(commits_: list[list[str]]) -> bool:
    """A person's commit was the last to change it. The last commit set the content the base-test run judges, so an
    earlier harness commit does not matter and a later one does. Nobody found is not people: it stays a blocker."""
    return bool(commits_) and not is_harness(commits_[-1])


def _superseded(ctx: IntegrityContext) -> list[str]:
    """The test ids (`classname::name`) of every `tests.superseded` event: stale tests a reopened task's red step
    replaced (L4-OPS-015). The harness writes them from the base report's traces; an agent cannot add one."""
    found: list[str] = []
    for e in ctx.events:
        if e.type == "tests.superseded" and isinstance(e.data.get("tests"), list):
            found += [fold_subtest_id(t) for t in e.data["tests"] if isinstance(t, str)]
    return found


def _named_by_task(ctx: IntegrityContext) -> dict[str, str]:
    """test id -> the source of the reviewed text, for the tests a `tests.superseded{reason: "named_by_task"}` event
    lists: existing tests that a red step changed in place because the task's text named them (L4-IMP-082)."""
    found: dict[str, str] = {}
    for e in ctx.events:
        if (
            e.type == "tests.superseded"
            and e.data.get("reason") == "named_by_task"
            and isinstance(e.data.get("tests"), list)
        ):
            found |= {
                fold_subtest_id(t): str(e.data.get("source") or "a reviewed text")
                for t in e.data["tests"] if isinstance(t, str)
            }  # fmt: skip
    return found


def _is_superseded(superseded: Sequence[str], path: str, name: str) -> bool:
    """A recorded id `tests.test_long::test_long` names the function `name` of the module `path` (a parametrised
    `name[x]` and a class between module and function count; the module must match, so a same-named test elsewhere
    stays protected)."""
    return any(names_test_id(test, path, name) for test in superseded)


def _introduced(name: str, kind: str) -> Callable[[str, str], bool]:
    """True for a commit (text at its first parent, text at the commit) that made this change to the test `name`."""

    def check(before: str, after: str) -> bool:
        was, now = facts_of(before) or {}, facts_of(after)
        if name not in was or not was[name].test:
            return False
        if kind == "deleted":
            return now is not None and name not in now
        if now is None or name not in now:
            return True
        old, new = was[name], now[name]
        return (old.parts, old.closure) != (new.parts, new.closure)

    return check


def _unfrozen_source(ctx: IntegrityContext, commit: "Commit", path: str) -> str | None:
    """What freed `path` for this commit's task: the source of a `task.unfrozen` of the same unit and task naming it."""
    for e in ctx.events:
        if (
            e.type == "task.unfrozen" and e.data.get("task") == commit.task and _unit_of(ctx, e) == commit.unit
            and path in [str(p) for p in e.data.get("paths") or []]
        ):  # fmt: skip
            named = e.data.get("reason") == "named_by_task"
            return str((e.data.get("source") if named else e.data.get("question")) or "a human answer")
    return None


def _allowance(ctx: IntegrityContext, who: list[list[str]], path: str, by_sha: Mapping[str, "Commit"]) -> str | None:
    """`(task <t>: [test-infra])` / `(task <t>: unfrozen by <source>)` when every harness commit in `who` is covered by
    an allowance (L4-VER-031), else None. A harness commit without an `L4-Task` is never covered."""
    infra = {(unit, t.key) for unit, t in ctx.tasks if _human_tag(ctx, unit, t.title, "test-infra")}
    reasons: list[str] = []
    for record in who:
        if not is_harness(record):
            continue
        commit = by_sha.get(record[SHA])
        if commit is None:
            return None
        if (commit.unit, commit.task) in infra:
            reasons.append(f"task {commit.task}: [test-infra]")
        elif (source := _unfrozen_source(ctx, commit, path)) is not None:
            reasons.append(f"task {commit.task}: unfrozen by {source}")
        else:
            return None
    return f"({'; '.join(dict.fromkeys(reasons))})" if reasons else None


def _skip_hidden(skipped: Sequence[str], path: str, name: str) -> bool:
    """A test that the skip check already blocks (its own marker, its class's, or the module's) is reported there."""
    keys = {f"{path}::{name}", f"{path}::<module>"}
    if "." in name:
        keys.add(f"{path}::{name.split('.', 1)[0]}")
    return bool(keys & set(skipped))


def check_tests(ctx: IntegrityContext) -> Outcome:
    """Every test that exists at the base in a changed test file is compared with head, per test on the AST by file and
    qualified name (L4-VER-030, `l4.implementer.tamper`): a test changed, bound again, unparsable or deleted (and not
    moved as the same definition to a new place) is a blocker, unless a `tests.superseded` event records it as stale
    (a spec edit changed the criterion it traced and the reopened task's red step replaced it, L4-OPS-015: listed in
    the note). A skip, skipif or xfail marker, or a `pytest.skip(` call, that head has and the base did not (new tests
    included) is a blocker too. Per commit (L4-SEC-004, M1.9): a change that only people's commits introduced is
    allowed and listed (`Outcome.human_tests`); one whose every harness commit belongs to a `[test-infra]` task, or
    changes a path a `task.unfrozen` of that task names, is allowed and listed (`Outcome.allowed_tests`, L4-VER-031);
    any other harness commit keeps it a blocker. A later red commit may not change a test an earlier step wrote
    (L4-VER-032)."""
    globs = ctx.cfg.tdd.test_globs
    changed = {p: s for p, s in _changed(ctx.git, ctx.base_sha, ctx.head_sha).items() if p.endswith(".py")}
    files = {p: s for p, s in changed.items() if _matches(globs, p) and not _in_unit_dirs(ctx, p)}
    others = sorted(
        p for p, s in _changed(ctx.git, ctx.base_sha, ctx.head_sha).items()
        if not p.endswith(".py") and _matches(globs, p) and not _in_unit_dirs(ctx, p) and s != "A"
    )  # fmt: skip
    elsewhere = f"{len(others)} other test file(s) are checked by the run of pre-existing tests"
    if not files and others:
        return Outcome(note=f"no Python test file changed; {elsewhere}", skipped=True)
    if not files:
        return Outcome(note="no test file changed", skipped=True)
    found: list[Tampered] = []
    gone: dict[tuple[str, str], str] = {}
    added: dict[tuple[str, str], str] = {}
    skipped, human, allowed, replaced, in_place = [], [], [], [], []
    for path, status in sorted(files.items()):
        before = _text(ctx.git, ctx.base_sha, path)
        after = None if status == "D" else _text(ctx.git, ctx.head_sha, path)
        was = facts_of(before) or {}
        for t in compare(path, before, after):
            found.append(t)
            if t.kind == "deleted":
                gone[path, t.name] = (was[t.name].definition, was[t.name].closure)
        if after is not None and (now := facts_of(after)):
            added |= {
                (path, n): (f.definition, f.closure)
                for n, f in now.items()
                if f.test and not (n in was and was[n].test)
            }
        markers = scan.skip_markers(after or "") - scan.skip_markers(before)
        for name in sorted(markers):
            who = _introducers(ctx, path, lambda b, a, n=name: scan.skip_markers(a)[n] > scan.skip_markers(b)[n])
            if _by_people(who):
                human.append(f"{path}::{name} skip marker added by {', '.join(r[SHA][:10] for r in who)}")
            else:
                skipped.append(f"{path}::{name}")
    recorded = _superseded(ctx)
    named = _named_by_task(ctx)
    by_sha = {c.sha: c for c in commits(ctx)}
    moved_away = moved(gone, added)
    changes, deletions = [], []
    for t in found:
        if (t.path, t.name) in moved_away or _skip_hidden(skipped, t.path, t.name):
            continue
        if hit := next((i for i in recorded if names_test_id(i, t.path, t.name)), None):
            if hit in named:
                in_place.append(f"{hit} (named by the task text, {named[hit]})")
            else:
                replaced.append(f"{t.path}::{t.name}")
            continue
        who = _introducers(ctx, t.path, _introduced(t.name, t.kind))
        word = "deleted" if t.kind == "deleted" else "changed"
        if _by_people(who):
            by = ", ".join(r[SHA][:10] for r in who)
            if f"{t.path}::{t.name} skip marker added by {by}" not in human:  # the skip entry already says it
                human.append(f"{t.path}::{t.name} {word} by {by}")
        elif (why := _allowance(ctx, who, t.path, by_sha)) is not None:
            allowed.append(f"{t.path}::{t.name} {word} {why}")
        elif t.kind == "deleted":
            deletions.append(f"{t.path}::{t.name}")
        else:
            changes.append(f"{t.path}::{t.name} ({t.why})")
    later = _later_red_changes(ctx)
    findings = []
    if deletions:
        findings.append(_blocker("a pre-existing test was deleted", _listed(deletions)))
    if changes:
        findings.append(_blocker("a pre-existing test was changed", _listed(changes)))
    if skipped:
        findings.append(_blocker("a skip or xfail marker was added", _listed(skipped)))
    if later:
        findings.append(_blocker("a red step changed a test that an earlier step wrote", _listed(later)))
    extra = f" (+{len(human)} by humans, listed)" if human else ""
    if others:
        extra += f"; {elsewhere}"
    if allowed:
        extra += f" (+{len(allowed)} allowed, listed)"
    if replaced:
        extra += f"; superseded by a changed criterion, not deleted: {_listed(replaced)}"
    if in_place:
        extra += f"; changed in place, named by the task text: {_listed(in_place)}"
    return Outcome(
        findings, f"{len(files)} test file(s) compared with the base{extra}", human_tests=human, allowed_tests=allowed
    )


def _later_red_changes(ctx: IntegrityContext) -> list[str]:
    """L4-VER-032: a test that exists at a red commit's parent and not at the base, that the commit changed, bound again
    or deleted (the base's own tests are judged by the comparison above)."""
    tdd = ctx.cfg.tdd
    steps = {c.sha: c for c in commits(ctx) if c.tdd in ("red", "already-satisfied")}
    infra = {(unit, t.key) for unit, t in ctx.tasks if _human_tag(ctx, unit, t.title, "test-infra")}
    recorded = _superseded(ctx)
    hits: list[str] = []
    for record in commit_records(ctx.git, "--reverse", f"{ctx.base_sha}..{ctx.head_sha}"):
        commit = steps.get(record[SHA])
        if commit is None or not is_harness(record) or not commit.parent or (commit.unit, commit.task) in infra:
            continue
        paths = sorted(
            p for p, s in _changed(ctx.git, commit.parent, commit.sha).items()
            if p.endswith(".py") and _matches(tdd.test_globs, p) and not _in_unit_dirs(ctx, p)
        )  # fmt: skip
        gone: dict[tuple[str, str], str] = {}
        added: dict[tuple[str, str], str] = {}
        found: list[Tampered] = []
        for path in paths:
            before = _text(ctx.git, commit.parent, path)
            now_blob = _blob(ctx.git, commit.sha, path)
            after = now_blob.decode("utf-8", "replace") if now_blob is not None else None
            was, at_base = facts_of(before) or {}, facts_of(_text(ctx.git, ctx.base_sha, path)) or {}
            for t in compare(path, before, after):
                if t.name in at_base and at_base[t.name].test:
                    continue
                found.append(t)
                if t.kind == "deleted":
                    gone[path, t.name] = (was[t.name].definition, was[t.name].closure)
            if after is not None and (now := facts_of(after)):
                added |= {
                    (path, n): (f.definition, f.closure)
                    for n, f in now.items()
                    if f.test and not (n in was and was[n].test)
                }
        away = moved(gone, added)
        hits += [
            f"{t.path}::{t.name} (task {commit.task}, red commit {commit.sha[:10]}: {t.why})"
            for t in found
            if (t.path, t.name) not in away and not any(names_test_id(i, t.path, t.name) for i in recorded)
        ]
    return hits


# --- 2.5 the red -> green freeze ------------------------------------------------------------------------------------


def _unit_of(ctx: IntegrityContext, event: LedgerEvent) -> str:
    fix = event.data.get("fix_unit")
    return f"{ctx.unit_id.split(':', 1)[0]}:{fix}" if isinstance(fix, str) and fix else ctx.unit_id


# contract C22: `task.red_ok` and `task.done` are written before their commits (they travel inside them) and name the
# step `base`; the sha follows in these events, or is derived from the commits when a kill lost the line
_COMMITTED = {"task.red_ok": "task.red_committed", "task.done": "task.green_committed"}
_STEP_KINDS = {
    "task.red_ok": ("red", "already-satisfied"),
    "task.done": ("green", "already-satisfied", "exempt", "already-done"),
}


def _sha(ctx: IntegrityContext, event: LedgerEvent) -> str | None:
    """The commit a `task.red_ok` or `task.done` stands for: its own `sha` (an event written after its commit), else
    the `sha` of the `task.red_committed` / `task.green_committed` with the same unit, task and base, else the unit's
    commit for the task (`L4-Unit`, `L4-Task`, a matching `L4-TDD`) whose first parent is that base."""
    sha = event.data.get("sha")
    if isinstance(sha, str) and sha:
        return sha
    base, task, unit = event.data.get("base"), event.data.get("task"), _unit_of(ctx, event)
    if not isinstance(base, str) or not base:
        return None
    for e in ctx.events:
        if (
            e.type == _COMMITTED.get(event.type) and e.data.get("task") == task and e.data.get("base") == base
            and _unit_of(ctx, e) == unit and isinstance(found := e.data.get("sha"), str) and found
        ):  # fmt: skip
            return found
    kinds = _STEP_KINDS.get(event.type, ())
    found = [c.sha for c in commits(ctx) if c.unit == unit and c.task == task and c.tdd in kinds and c.parent == base]
    return found[-1] if found else None


def _green_sha(ctx: IntegrityContext, red: LedgerEvent) -> str | None:
    """The commit of THIS red's green: the first `task.done` of the same unit and task after the red and before the
    next `task.red_ok` of that task. A task reopened by `tasks.reopened` has two red/green cycles; pairing a red with
    the last green would read the reopened red's rewrite of the test as a change between red and green (L4-VER)."""
    unit, task = _unit_of(ctx, red), red.data.get("task")
    key = (red.ts, red.run_id, red.seq)
    later = [
        e for e in ctx.events
        if e.type in ("task.done", "task.red_ok") and e.data.get("task") == task and _unit_of(ctx, e) == unit
        and (e.ts, e.run_id, e.seq) > key
    ]  # fmt: skip
    first = next((e for e in later if e.type == "task.done"), None)
    if first is None or any(
        e.type == "task.red_ok" and (e.ts, e.run_id, e.seq) < (first.ts, first.run_id, first.seq) for e in later
    ):
        return None
    sha = _sha(ctx, first)
    return sha if isinstance(sha, str) and sha != _sha(ctx, red) else None


def _unfrozen_paths(ctx: IntegrityContext, red: LedgerEvent, red_sha: str) -> dict[str, tuple[str, str]]:
    """path -> (reason, source), for the paths a `task.unfrozen` of this very red commit (same unit and task) freed. The
    harness wrote it before green's attempt. `reason` is `human_answer` (source: the question id; also the reading of
    an old event without a reason), `agent_answer` (a `human_answer` event with `by: agent`), `delegate_answer`
    (source: the question id and `delegate_override, <model>`) or `named_by_task` (source: `plan:<id>@<digest>` or
    `base:<sha>`)."""
    freed: dict[str, tuple[str, str]] = {}
    for e in ctx.events:
        if (
            e.type == "task.unfrozen" and e.data.get("task") == red.data.get("task")
            and e.data.get("red_sha") == red_sha and _unit_of(ctx, e) == _unit_of(ctx, red)
        ):  # fmt: skip
            named = e.data.get("reason") == "named_by_task"
            if named:
                reason = "named_by_task"
            elif e.data.get("reason") == "delegate_answer" or e.data.get("by") == "delegate":
                reason = "delegate_answer"
            elif e.data.get("by") == "agent":
                reason = "agent_answer"
            else:
                reason = "human_answer"
            source = str((e.data.get("source") if named else e.data.get("question")) or "a human answer")
            if reason == "delegate_answer":
                who = e.data.get("model") or e.data.get("profile") or "the delegate"
                source += f" (delegate_override, {who})"
            elif reason == "agent_answer":
                source += " (agent)"
            for path in e.data.get("paths") or []:
                freed[str(path)] = (reason, source)
    return freed


def check_freeze(ctx: IntegrityContext) -> Outcome:
    """For each task with a red commit and a green commit: the frozen files (the red tests and the test-support
    files, `task.red_ok.frozen`) are identical at both, and so is the runner configuration (`GateConfig`, L4-IMP-040):
    the pytest and coverage sections of the manifests, `pytest.ini`, `.coveragerc` and the like. A new pytest
    `markers` entry is no change (owner decision 5)."""
    git, findings, checked, listed, opened, people, others = ctx.git, [], 0, [], 0, 0, 0
    gc = GateConfig.of(ctx.cfg, git.repo)
    for red in (e for e in ctx.events if e.type == "task.red_ok"):
        red_sha, green = _sha(ctx, red), _green_sha(ctx, red)
        frozen = [str(p) for p in red.data.get("frozen") or []]
        if not isinstance(red_sha, str) or green is None or not frozen:
            continue
        checked += 1
        task = red.data.get("task")
        changed = _changed(git, red_sha, green)
        freed = _unfrozen_paths(ctx, red, red_sha)
        moved = sorted(p for p in frozen if p in changed and p not in freed)
        for p in sorted(freed):
            if p in frozen and p in changed:
                reason, source = freed[p]
                if reason == "named_by_task":
                    opened += 1
                    listed.append(f"{p} (task {task}, opened by its text, {source})")
                elif reason == "human_answer":
                    listed.append(f"{p} (task {task}, unfrozen by {source} (human))")
                    people += 1
                else:
                    listed.append(f"{p} (task {task}, unfrozen by {source})")
                    others += 1
        runner = sorted(
            p for p in changed
            if "runner" in gc.kinds(p)
            and gc.changed(p, _blob(git, red_sha, p), _blob(git, green, p)).get("runner")
        )  # fmt: skip
        if moved:
            findings.append(
                _blocker(
                    "a frozen test or support file changed between red and green", f"task {task}: {_listed(moved)}"
                )
            )
        if runner:
            findings.append(
                _blocker(
                    "the test runner configuration changed between red and green", f"task {task}: {_listed(runner)}"
                )
            )
    if not checked:
        return Outcome(note="no task with a red and a green commit", skipped=True)
    note = f"{checked} task(s): red and green compared"
    if people:
        note += f" (+{people} unfrozen by human answers)"
    if others:
        note += f" (+{others} unfrozen by a delegate or an agent)"
    if opened:
        note += f" (+{opened} opened by task text)"
    return Outcome(findings, note, unfrozen=listed)


# --- 2.5b the test-path freeze (L4-IMP-006 (7)) ---------------------------------------------------------------------


def _allowed_in_step(ctx: IntegrityContext, commit: "Commit") -> set[str]:
    """The test paths a green or exempt commit of the harness may change: those a `task.unfrozen` of the same unit and
    task names, and for an exempt commit those a `task.tests_added` of the same unit and task lists."""
    kinds = ("task.unfrozen", "task.tests_added") if commit.tdd == "exempt" else ("task.unfrozen",)
    allowed: set[str] = set()
    for e in ctx.events:
        if e.type in kinds and e.data.get("task") == commit.task and _unit_of(ctx, e) == commit.unit:
            allowed |= {str(p) for p in e.data.get("paths" if e.type == "task.unfrozen" else "files") or []}
    return allowed


def check_test_paths(ctx: IntegrityContext) -> Outcome:
    """A commit of the harness whose `L4-TDD` is `green` or `exempt` (a fix chore) may not add, change, delete or
    rename a path of `tdd.test_globs` or `tdd.test_support_globs`, except the paths a `task.unfrozen` of its unit and
    task names, those of the `task.tests_added` of an exempt commit, and anything a task with the human `[test-infra]`
    tag commits. People's commits are not walked (`check_tests` lists theirs)."""
    tdd = ctx.cfg.tdd
    globs = (*tdd.test_globs, *tdd.test_support_globs)
    steps = {c.sha: c for c in commits(ctx) if c.tdd in ("green", "exempt", "already-done")}
    infra = {(unit, t.key) for unit, t in ctx.tasks if _human_tag(ctx, unit, t.title, "test-infra")}
    hits, checked = [], 0
    for record in commit_records(ctx.git, "--reverse", f"{ctx.base_sha}..{ctx.head_sha}"):
        commit = steps.get(record[SHA])
        if commit is None or not is_harness(record) or not commit.parent:
            continue
        checked += 1
        if (commit.unit, commit.task) in infra:
            continue
        allowed = _allowed_in_step(ctx, commit)
        for path in sorted(_changed(ctx.git, commit.parent, commit.sha)):
            if _matches(globs, path) and not _in_unit_dirs(ctx, path) and path not in allowed:
                hits.append(f"{path} (task {commit.task}, {commit.tdd} commit {commit.sha[:10]})")
    if not checked:
        return Outcome(note="no green or fix-chore commit of the harness", skipped=True)
    note = f"{checked} harness step commit(s) checked"
    if not hits:
        return Outcome(note=note)
    return Outcome([_blocker("a test file changed in a step that may not change tests", _listed(hits))], note)


# --- 2.6 content scan -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Commit:
    sha: str
    unit: str
    task: str
    tdd: str
    parent: str = ""  # the first parent


def commits(ctx: IntegrityContext) -> list[Commit]:
    """The unit's harness commits `base..head` that carry an `L4-Task`, oldest first."""
    keys = ("Unit", "Task", "TDD")
    fmt = "%H%x01%P%x01" + "%x01".join(f"%(trailers:key=L4-{k},valueonly,separator=%x2c)" for k in keys) + "%x02"
    log = ctx.git.run("log", "--reverse", f"--format={fmt}", f"{ctx.base_sha}..{ctx.head_sha}").stdout
    found = []
    for record in filter(None, (r.strip("\n") for r in log.split("\x02"))):
        sha, parents, unit, task, tdd = (part.strip() for part in record.split("\x01"))
        if task:
            found.append(Commit(sha, unit, task, tdd, (parents.split() or [""])[0]))
    return found


def tagged_files(ctx: IntegrityContext, tag: str) -> frozenset[str]:
    """The files that commits of tasks carrying the human tag `[tag]` touched."""
    keys = {(unit, task.key) for unit, task in ctx.tasks if _human_tag(ctx, unit, task.title, tag)}
    files: set[str] = set()
    for commit in commits(ctx):
        if (commit.unit, commit.task) in keys:
            out = ctx.git.run_bytes(
                "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "-m", "--first-parent", commit.sha
            )
            files |= {p.decode("utf-8", "replace") for p in out.split(b"\0") if p}
    return frozenset(files)


def _unread_support(ctx: IntegrityContext, path: str) -> bool:
    """A changed test-support source file or runner config the scan cannot read: not Python, and not one of the
    pytest-family files whose `addopts` it does read."""
    if path.endswith(".py") or PurePosixPath(path).name in (*_RUNNER_FILES, "pyproject.toml"):
        return False
    tdd = ctx.cfg.tdd
    return (_matches(tdd.test_support_globs, path) and _suffix(path) in CODE_SUFFIXES) or _matches(
        tdd.runner_config_files, path
    )


def _opened_patches(ctx: IntegrityContext, changed: Mapping[str, str]) -> list[str]:
    """Rule 3 of `opened.check_opened` (design D5) on each changed `.py` path that a `task.unfrozen` of the unit names:
    a new patch or assignment of a symbol of a production module that the unit changed. The red version is the one the
    event records (`red_sha`), else the base."""
    units = {ctx.unit_id, *(unit for unit, _ in ctx.tasks)}
    named: dict[str, str] = {}
    for e in ctx.events:
        if e.type == "task.unfrozen" and _unit_of(ctx, e) in units:
            for path in e.data.get("paths") or []:
                named.setdefault(str(path), str(e.data.get("red_sha") or ctx.base_sha))
    modules = unit_modules((p for p, s in changed.items() if s != "D"), ctx.cfg)
    hits: list[str] = []
    for path in sorted(p for p in named if p.endswith(".py") and changed.get(p, "D") != "D"):
        red = named[path] if _blob(ctx.git, named[path], path) is not None else ctx.base_sha
        why = check_opened(
            _text(ctx.git, red, path), _text(ctx.git, ctx.head_sha, path), named_by_task=False, unit_modules=modules
        )
        if why:
            hits.append(f"{path}: an opened support file patches the unit's code ({why})")
    return hits


def _output_count(ctx: IntegrityContext, path: str, text: str) -> int:
    return sum(1 for why in awareness_lines(ctx, path, text).values() if why == "names the test output")


def _is_support(ctx: IntegrityContext, path: str, source: str) -> bool:
    """A test-support file for the scan: one of `tdd.test_support_globs`, or a `.py` file of `tdd.test_globs` that
    defines no test (a helper module under `tests/`, L4-VER-039; a file that does not parse counts too)."""
    if _matches(ctx.cfg.tdd.test_support_globs, path):
        return True
    if not _matches(ctx.cfg.tdd.test_globs, path):
        return False
    found = facts_of(source)
    return not found or not any(f.test for f in found.values())


def check_scan(ctx: IntegrityContext) -> Outcome:
    """Result-manipulating constructs in the unit's changed test-support and runner-config files, a mention of the
    coverage plugin or its output directory in any changed Python file (M1.6: such code can rewrite the diff-coverage
    evidence), and any new module that would be imported in place of a harness plugin (`l4_trace`, `l4_cov`) or of
    coverage.py (a top-level `coverage`). Only what head has and the base did not counts; a task tagged `[test-infra]`
    is exempt for the files its commits touched (not for a plugin module)."""
    tdd, git = ctx.cfg.tdd, ctx.git
    changed = {
        p: s for p, s in _changed(git, ctx.base_sha, ctx.head_sha).items() if s != "D" and not _in_unit_dirs(ctx, p)
    }
    exempt = tagged_files(ctx, "test-infra") if changed else frozenset()
    modules = unit_modules((p for p in changed), ctx.cfg)  # the production modules the unit changed (L4-VER-037)

    def found_in(path: str, before: str, after: str) -> list[str]:
        found: list[str] = []
        if path.endswith(".py") and _is_support(ctx, path, after):
            found = sorted(set(scan.result_hooks(after)) - set(scan.result_hooks(before)))
            found += [
                "names the test output (.l4-out or a report path) in a support file"
                for _ in range(max(0, _output_count(ctx, path, after) - _output_count(ctx, path, before)))
            ]
            found += [
                f"patches {target}, which the unit changed, for every test"
                for target, blocking in new_patches(before, after, modules)
                if blocking and modules
            ]
        elif _matches(tdd.runner_config_files, path):
            found = [f"adds the option {option}" for option in scan.addopts_added(before, after)]
        if path.endswith(".py") and (refs := sorted(set(scan.coverage_refs(after)) - set(scan.coverage_refs(before)))):
            found.append(f"names the coverage plugin or its output ({', '.join(refs)})")
        return found

    hits: list[str] = []
    human: list[str] = []
    allowed = _awareness_allow(ctx)
    allowed_refs: list[str] = []
    for path in sorted(changed):
        before, after = _text(git, ctx.base_sha, path), _text(git, ctx.head_sha, path)
        found = [what for what in found_in(path, before, after) if path not in exempt]
        if path.endswith(".py") and _matches([*tdd.test_globs, *tdd.test_support_globs], path):
            before_refs, after_refs = scan.harness_references(before), scan.harness_references(after)
            refs = [
                f"{why} (the harness's own plugin or report option)" for why in after_refs if why not in before_refs
            ]
            if refs and (glob := next((g for g in allowed if glob_match(g, path)), None)):
                allowed_refs += [f"{path}: {what} (allowed by `{glob}`)" for what in refs]  # L4 testing its own plugin
            else:
                found += refs
        if not found:
            continue
        # per commit (L4-SEC-004, W-D6): a file whose offending change only people's commits introduced is the owner's
        # edit, listed; any harness commit that introduced a hit in it too keeps the hits findings
        who = _introducers(ctx, path, lambda b, a, p=path: bool(found_in(p, b, a)))
        if _by_people(who):
            human += [f"{path}: {what} (added by {', '.join(r[SHA][:10] for r in who)})" for what in found]
        else:
            hits += [f"{path}: {what}" for what in found]
    hits += _opened_patches(ctx, _changed(git, ctx.base_sha, ctx.head_sha))
    mocked = [
        f"{path}: patches {target} in a fixture a test requests"
        for path in sorted(changed)
        if path.endswith(".py")
        and _is_support(ctx, path, _text(git, ctx.head_sha, path))
        and path not in exempt
        and modules
        for target, blocking in new_patches(_text(git, ctx.base_sha, path), _text(git, ctx.head_sha, path), modules)
        if not blocking
    ]
    tree = git.run_bytes("ls-tree", "-r", "--name-only", "-z", ctx.head_sha).split(b"\0")
    names = [p.decode("utf-8", "replace") for p in tree if p]
    base_names = set(
        git.run_bytes("ls-tree", "-r", "--name-only", "-z", ctx.base_sha).decode("utf-8", "replace").split("\0")
    )
    roots = ctx.cfg.verifier.evidence.module_roots
    hits += [
        f"{p}: a module named {plugin}"
        for p in names
        if (plugin := scan.plugin_module(p, roots)) is not None and p not in base_names
    ]
    extra = f" (+{len(human)} by humans, listed)" if human else ""
    unread = sorted(p for p in changed if _unread_support(ctx, p))
    if not hits and unread:  # a green row after reading none of the changed support files would say what it did not do
        return Outcome(note=_not_python(unread), skipped=True, human_scan=human, mocked=mocked)
    if mocked:
        extra += f" (+{len(mocked)} fixture patch(es) of the unit's code, listed)"
    if not hits:
        return Outcome(
            note=f"no result-manipulating construct in the changed support and runner files{extra}",
            human_scan=human,
            mocked=mocked,
            listed=allowed_refs,
        )
    return Outcome(
        [_blocker("a construct that can change what the tests report", _listed(hits))],
        f"{len(hits)} hit(s){extra}" + (f"; {_not_python(unread)}" if unread else ""),
        human_scan=human,
        mocked=mocked,
        listed=allowed_refs,
    )


# --- 2.10 suppressions ----------------------------------------------------------------------------------------------


def _declarations(events: Sequence[LedgerEvent]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for event in events:
        if event.type in ("task.red_ok", "task.done"):
            found += [d for d in event.data.get("suppressions") or [] if isinstance(d, Mapping)]
    return found


def _mark_count(text: str, key: tuple[str, str]) -> int:
    return sum(1 for line in text.splitlines() for mark in scan.suppressions_in(line) if (mark.kind, mark.text) == key)


def _written_by_people(
    ctx: IntegrityContext, path: str, number: int, found: scan.Suppression, cache: dict[tuple[str, str, str], list]
) -> str | None:
    """The short sha(s) of the people's commits that wrote this comment, or None when the unit did. Per commit (the
    `_introducers` rule of L4-SEC-004): the commits of `base..head` that raised the number of comments of this kind and
    text in the file. Only people's: it is theirs, even if a harness commit later rewrote the line around it. Both:
    `git blame` tells the lines apart, and a line a harness commit wrote, or that nobody can be named for, stays the
    unit's. None found (the history cannot say) is the unit's too."""
    key = (found.kind, found.text)
    cached = cache.get((path, *key))
    if cached is None:
        cached = cache[(path, *key)] = _introducers(
            ctx, path, lambda before, after: _mark_count(after, key) > _mark_count(before, key)
        )
    if not cached:
        return None
    if _by_people(cached):
        return ", ".join(r[SHA][:10] for r in cached)
    out = ctx.git.run(
        "blame", "--porcelain", "-L", f"{number},{number}", ctx.head_sha, "--", path, check=False
    ).stdout.split(None, 1)
    blamed = out[0] if out else ""
    return blamed[:10] if any(r[SHA] == blamed and not is_harness(r) for r in cached) else None


def _covers(declared: Mapping[str, Any], path: str, number: int, found: scan.Suppression) -> bool:
    if str(declared.get("file", "")).removeprefix("./") != path:
        return False
    if declared.get("line") == number:
        return True
    rule = str(declared.get("rule", "")).lower()
    comment = found.text.lower()
    return bool(rule) and (rule in comment or found.kind.replace("-", " ") in rule or found.kind in rule)


def check_suppressions(ctx: IntegrityContext) -> Outcome:
    """New inline suppressions in the unit's Python diff. One the ledger's steps did not declare is major (a
    declaration matches by file and line, or by file and rule, and covers one comment); `nosec` and `gitleaks:allow` are
    major unless a task tagged `[config]` touched the file. Declared ones are listed for the report and the judge."""
    # the verifier's own audit tests, by the paths its `verify.audit` events recorded: a name pattern would also
    # excuse an implementer's file that borrows the name
    audit_paths = sorted({str(e.data["path"]) for e in ctx.events if e.type == "verify.audit" and e.data.get("path")})
    audit_paths += sorted(  # and the e2e tests step 5 wrote (`verify.generated`), likewise by recorded path
        {
            str(e.data["test"])
            for e in ctx.events
            if e.type == "verify.generated" and e.data.get("status") == "accepted" and e.data.get("test")
        }
    )
    diff = ctx.git.run(
        "-c", "core.quotePath=false", "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", ctx.base_sha,
        ctx.head_sha, "--", "*.py", ":(exclude,glob)**/.l4/**", *(f":(exclude,literal){p}" for p in audit_paths),
    ).stdout  # fmt: skip
    marks = [(line, s) for line in scan.added_lines(diff) for s in scan.suppressions_in(line.text)]
    unread = sorted(  # the diff above reads `*.py` only; source and tests in another language are named, not skipped
        p for p, status in _changed(ctx.git, ctx.base_sha, ctx.head_sha).items()
        if status != "D" and _suffix(p) in CODE_SUFFIXES and not p.endswith(".py") and "/.l4/" not in f"/{p}"
        and not _in_unit_dirs(ctx, p) and p not in audit_paths
    )  # fmt: skip
    if not marks:
        if unread:
            return Outcome(note=_not_python(unread), skipped=True)
        return Outcome(note="no new suppression comment", skipped=True)
    config_files = tagged_files(ctx, "config")
    open_declarations = _declarations(ctx.events)
    findings, declared, undeclared, unreviewed, human = [], [], [], [], []
    attribution: dict[tuple[str, str, str], list] = {}
    for line, found in marks:
        # a comment a person's commit wrote (the owner's edit on the unit branch) is the owner's, not the unit's
        # violation: listed, never a finding, and no declaration is spent on it (W-D6, SPEC 2.10)
        if (who := _written_by_people(ctx, line.path, line.number, found, attribution)) is not None:
            human.append(f"{line.path}:{line.number} {found.text} (added by {who})")
            continue
        match = next((d for d in open_declarations if _covers(d, line.path, line.number, found)), None)
        where = f"{line.path}:{line.number} {found.text}"
        if match is not None:
            open_declarations.remove(match)
            declared.append(f"{where} (declared: {str(match.get('reason', ''))[:120]})")
        else:
            undeclared.append(where)
        if found.kind in ("nosec", "gitleaks") and line.path not in config_files:
            unreviewed.append(where)
    if undeclared:
        advice = "Remove each comment by fixing what it hides; declare one only if it cannot be removed"
        detail = f"{_listed(undeclared)}. {advice}"
        findings.append(_blocker("an inline suppression was not declared", detail, Severity.MAJOR))
    if unreviewed:
        findings.append(
            _blocker("nosec or gitleaks:allow without a [config] task", _listed(unreviewed), Severity.MAJOR)
        )
    extra = f" (+{len(human)} by humans, listed)" if human else ""
    note = f"{len(marks)} new suppression(s), {len(declared)} declared{extra}"
    if unread:
        note += f"; {_not_python(unread)}"
    return Outcome(findings, note, declared=declared, human_suppressions=human)


# --- 2.13 TDD history -----------------------------------------------------------------------------------------------


def _last(ctx: IntegrityContext, kind: str, unit: str, task: str) -> LedgerEvent | None:
    found = [e for e in ctx.events if e.type == kind and e.data.get("task") == task and _unit_of(ctx, e) == unit]
    return found[-1] if found else None


def check_tdd_history(ctx: IntegrityContext) -> Outcome:
    """Per done task of the unit and its fix units: its commits are a red commit and then its green commit, or one
    `already-satisfied` commit, found by `L4-Unit`, `L4-Task` and `L4-TDD` and equal to the ledger's shas. A missing
    red is a blocker (SCN-VER-15). Tasks tagged with a TDD-exempt kind are skipped."""
    exempt = set(ctx.cfg.tdd.exempt_task_kinds)
    skipped = {(unit, t.key) for unit, t in ctx.tasks if exempt & task_tags(t.title)}
    by_task: dict[tuple[str, str], list[Commit]] = {}
    for commit in commits(ctx):
        by_task.setdefault((commit.unit, commit.task), []).append(commit)
    pairs = {(_unit_of(ctx, e), str(e.data.get("task"))) for e in ctx.events if e.type == "task.done"} | set(by_task)
    findings, checked = [], 0
    for unit, task in sorted(pairs - skipped):
        done, red = _last(ctx, "task.done", unit, task), _last(ctx, "task.red_ok", unit, task)
        mine = by_task.get((unit, task), [])
        kinds = [c.tdd for c in mine]
        label = f"{unit} task {task}"
        if done is not None and done.data.get("tdd") in ("exempt", "already-done"):
            continue  # a fix chore, or a retaken feedback item with nothing left to change: no red, no green
        if done is not None and done.data.get("closed") and not any(kinds):
            continue  # a parent closed with no step (M1.4 `_close_parents`): no red, no green, no `L4-TDD`
        checked += 1
        if "already-satisfied" in kinds:
            sha = [c.sha for c in mine if c.tdd == "already-satisfied"][-1]
            ok = done is not None and _sha(ctx, done) == sha and red is not None and _sha(ctx, red) == sha
            if not ok:
                findings.append(_blocker("the already-satisfied commit does not match the ledger", label))
            continue
        reds, greens = [c for c in mine if c.tdd == "red"], [c for c in mine if c.tdd == "green"]
        if greens and not reds or (done is not None and red is None):
            findings.append(_blocker("a green commit has no red commit before it", label))
        elif done is not None and (not reds or not greens):
            findings.append(_blocker("the task is done but its red or green commit is missing", label))
        elif reds and greens:
            if red is None or done is None or _sha(ctx, red) != reds[-1].sha or _sha(ctx, done) != greens[-1].sha:
                findings.append(_blocker("the red and green commits do not match the ledger", label))
            elif ctx.git.run("merge-base", "--is-ancestor", reds[-1].sha, greens[-1].sha, check=False).returncode != 0:
                findings.append(_blocker("the red commit does not precede the green commit", label))
    if not checked:
        return Outcome(note="no task has a TDD history to check", skipped=True)
    return Outcome(findings, f"{checked} task(s); red tests passing at head: step 3")


# --- 2.9 gate and runner configuration (L4-IMP-040) ------------------------------------------------------------------

_PHASE_OF = {"red": "red", "already-satisfied": "red", "green": "green", "already-done": "green", "exempt": "single"}


def _opened_config(ctx: IntegrityContext, commit: "Commit", phase: str) -> set[str]:
    """The paths a `task.config_opened` of this commit's unit, task and phase names (L4-IMP-041)."""
    return {
        str(p)
        for e in ctx.events
        if e.type == "task.config_opened" and e.data.get("task") == commit.task and e.data.get("phase") == phase
        and _unit_of(ctx, e) == commit.unit
        for p in e.data.get("paths") or []
    }  # fmt: skip


def _sections_text(changed: Mapping[str, tuple[str, ...]]) -> str:
    return "; ".join(
        f"{kind}: {', '.join(s or 'the whole file' for s in sections)}" for kind, sections in changed.items()
    )


def check_gate_config(ctx: IntegrityContext) -> Outcome:
    """A harness commit between base and head that changed a gate or runner configuration file in a guarded section
    (`GateConfig`) is a blocker, unless L4-IMP-041 allowed it for that unit, task and phase: a human `[config]` or
    `[test-infra]` tag, or a `task.config_opened` that names the file, and runner configuration never in a green
    commit. A harness commit that is no task step (no `L4-Task`) is never allowed. A change that only people's commits
    made is allowed and listed (`Outcome.human_config`)."""
    gc = GateConfig.of(ctx.cfg, ctx.git.repo)
    paths = sorted(
        p for p in _changed(ctx.git, ctx.base_sha, ctx.head_sha) if gc.kinds(p) and not _in_unit_dirs(ctx, p)
    )
    if not paths:
        return Outcome(note="no gate or runner configuration file changed", skipped=True)
    steps = {c.sha: c for c in commits(ctx)}
    tags = {(unit, t.key): task_tags(t.title) for unit, t in ctx.tasks}
    hits: list[str] = []
    human: list[str] = []
    for path in paths:
        for record in commit_records(
            ctx.git, "--reverse", f"{ctx.base_sha}..{ctx.head_sha}", "--", f":(literal){path}"
        ):
            sha = record[SHA]
            changed = gc.changed(path, _blob(ctx.git, f"{sha}^", path), _blob(ctx.git, sha, path))
            if not changed:
                continue
            if not is_harness(record):
                human.append(f"{path} ({_sections_text(changed)}) by {sha[:10]}")
                continue
            commit = steps.get(sha)
            permitted: frozenset[Kind] = frozenset()
            if commit is not None and (phase := _PHASE_OF.get(commit.tdd)) is not None:
                opened = path in _opened_config(ctx, commit, phase)
                permitted = allowed_kinds(phase, tags.get((commit.unit, commit.task), frozenset()), opened=opened)
            refused = {kind: sections for kind, sections in changed.items() if kind not in permitted}
            if refused:
                hits.append(f"{path} ({_sections_text(refused)}), commit {sha[:10]}")
    extra = f" (+{len(human)} changed by humans, listed)" if human else ""
    if not hits:
        return Outcome(note=f"{len(paths)} configuration file(s) changed, none by the unit{extra}", human_config=human)
    finding = _blocker("gate or runner configuration changed by the unit", _listed(hits))
    return Outcome([finding], f"{len(hits)} change(s) of gate or runner configuration{extra}", human_config=human)


# --- 2.14 production code that looks for the test run (second review N1, N2; L4-VER-039) -----------------------------

_BENIGN_ENV = frozenset({"PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID"})
_ENV_NAME = re.compile(r"^(?:L4|PYTEST)_[A-Z0-9_]+$")
_ENV_WORDS = re.compile(r"environ|getenv|process\.env|\bENV\b")
_OUTPUT = re.compile(r"(?<![\w.-])\.l4-out(?![\w-])")
_SIGNS = (  # other signs that code knows it runs under a test: listed for the judge, not blocked
    re.compile(r"""['"]_?pytest['"]\s+in\s+sys\.modules"""),
    re.compile(r"^\s*(?:import|from)\s+_?pytest\b"),
    re.compile(r"\batexit\.register\b"),
    re.compile(r"sys\.argv.*pytest|pytest.*sys\.argv"),
)


def _report_patterns(ctx: IntegrityContext) -> list[re.Pattern[str]]:
    reports = [r for r in (*ctx.cfg.gates.test.reports, *ctx.cfg.gates.e2e.reports) if r]
    return [re.compile(r"(?<![\w.-])" + re.escape(r) + r"(?![\w.-])") for r in reports]


def _names_output(ctx: IntegrityContext, text: str) -> bool:
    return bool(_OUTPUT.search(text)) or any(p.search(text) for p in _report_patterns(ctx))


def awareness_lines(ctx: IntegrityContext, path: str, text: str) -> dict[int, str]:
    """line number -> why, for the lines of `text` that read the run's environment or name its output. Python is read
    with the AST: comments and docstrings are ignored, and an environment read is a call or subscript of `environ` or
    `getenv` whose own expression holds a string `L4_*` or `PYTEST_*` (an xdist worker variable is benign). Another
    language is read line by line, comments of the `#` and `//` kind removed."""
    found: dict[int, str] = {}
    if not path.endswith(".py"):
        for number, raw in enumerate(text.splitlines(), 1):
            line = re.sub(r"(?:^|\s)(?:#|//).*$", "", raw)
            if _names_output(ctx, line):
                found[number] = "names the test output"
            elif _ENV_WORDS.search(line) and any(
                _ENV_NAME.match(m) and m not in _BENIGN_ENV for m in re.findall(r"[A-Z][A-Z0-9_]+", line)
            ):
                found[number] = "reads a test-run variable"
        return found
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return found
    docstrings = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    parents = {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for number, why in scan.harness_reference_lines(tree):
        found[number] = why
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in docstrings:
            continue
        if _names_output(ctx, node.value):
            found[node.lineno] = "names the test output"
        elif _ENV_NAME.match(node.value) and node.value not in _BENIGN_ENV:
            top: ast.AST = node
            while isinstance(parents.get(id(top)), ast.expr):
                top = parents[id(top)]
            if _ENV_WORDS.search(ast.unparse(top)):
                found[node.lineno] = "reads a test-run variable"
    return found


def _awareness_allow(ctx: IntegrityContext) -> list[str]:
    """`verifier.test_awareness_allow` as the BASE commit's `.l4/config.yaml` says it: a unit cannot add itself. A
    missing or unreadable config at the base allows nothing."""
    blob = _blob(ctx.git, ctx.base_sha, ".l4/config.yaml")
    if blob is None:
        return []
    try:
        return list(load_config_text(blob.decode("utf-8", "replace")).verifier.test_awareness_allow)
    except ConfigSchemaError:
        return []


def check_test_awareness(ctx: IntegrityContext) -> Outcome:
    """Production code that reacts to the verifier's own run (a blocker): a line of the unit's non-test, non-support
    diff that names `.l4-out`, a configured report path, an `L4_*` or `PYTEST_*` variable. Code that only looks like it
    knows about a test run (`"pytest" in sys.modules`, importing pytest, `atexit.register`, `sys.argv` checked for
    pytest) is listed for the judge (`Outcome.listed`). A line only people's commits wrote is listed in `human_scan`."""
    tdd, git = ctx.cfg.tdd, ctx.git
    paths = sorted(
        p for p, s in _changed(git, ctx.base_sha, ctx.head_sha).items()
        if s != "D" and _suffix(p) in CODE_SUFFIXES and not _in_unit_dirs(ctx, p) and "/.l4/" not in f"/{p}"
        and not _matches([*tdd.test_globs, *tdd.test_support_globs], p)
    )  # fmt: skip
    if not paths:
        return Outcome(note="no production file changed", skipped=True)
    diff = git.run(
        "-c", "core.quotePath=false", "diff", "-U0", "--no-color", "--no-ext-diff", "--no-renames", ctx.base_sha,
        ctx.head_sha, "--", *(f":(literal){p}" for p in paths),
    ).stdout  # fmt: skip
    allowed = _awareness_allow(ctx)
    added: dict[str, set[int]] = {}
    for line in scan.added_lines(diff):
        added.setdefault(line.path, set()).add(line.number)
    hits: dict[str, list[tuple[int, str]]] = {}
    listed: list[str] = []
    for path in paths:
        text = _text(git, ctx.head_sha, path)
        lines = text.splitlines()
        for number, why in sorted(awareness_lines(ctx, path, text).items()):
            if number not in added.get(path, ()):
                continue
            shown = lines[number - 1].strip()[:80] if 0 < number <= len(lines) else ""
            if glob := next((g for g in allowed if glob_match(g, path)), None):
                listed.append(f"{path}:{number}: {shown} (allowed by `{glob}`)")
            else:
                hits.setdefault(path, []).append((number, f"{shown}; {why}"))
        blocked_lines = {n for n, _ in hits.get(path, ())}
        for number in sorted(added.get(path, ())):
            sign = 0 < number <= len(lines) and number not in blocked_lines
            if sign and any(s.search(lines[number - 1]) for s in _SIGNS):
                listed.append(f"{path}:{number}: {lines[number - 1].strip()[:100]}")
    blockers: list[str] = []
    human: list[str] = []
    for path, found in sorted(hits.items()):
        who = _introducers(
            ctx,
            path,
            lambda before, after, p=path: len(awareness_lines(ctx, p, after)) > len(awareness_lines(ctx, p, before)),
        )
        rows = [f"{path}:{number} ({why})" for number, why in found]
        if _by_people(who):
            human += [f"{row} (added by {', '.join(r[SHA][:10] for r in who)})" for row in rows]
        else:
            blockers += rows
    findings = []
    if blockers:
        advice = (
            "Production code may not look for the test run, its output or its environment; a repository whose code "
            "legitimately does names the paths in verifier.test_awareness_allow (read at the base branch)"
        )
        findings.append(_blocker("production code reacts to the test run", f"{_listed(blockers)}. {advice}"))
    extra = f", {len(listed)} listed for the judge" if listed else ""
    note = f"{len(blockers)} hit(s){extra}" if blockers else f"no production line reacts to the test run{extra}"
    return Outcome(findings, note, human_scan=human, listed=listed)


# --- a Python file must be UTF-8 (L4-SEC-042) ------------------------------------------------------------------------

_REGULAR_MODES = ("100644", "100755")
_LINK_MODE = "120000"


@dataclass(frozen=True)
class _Entry:
    status: str  # A, M, D or T
    mode: str  # the mode at head ("000000" for a deleted path)
    sha: str  # the blob at head


def _diff_entries(git: Git, base: str, head: str) -> dict[str, _Entry]:
    """path -> what `git diff <base> <head>` says about it (no renames, full blob ids). Names are decoded with
    `os.fsdecode` (surrogateescape): two names that are not UTF-8 never collapse into one key."""
    raw = git.run_bytes("diff", "--raw", "--no-abbrev", "-z", "--no-renames", base, head, "--")
    fields = [f for f in raw.split(b"\0") if f]
    found: dict[str, _Entry] = {}
    for meta, path in zip(fields[0::2], fields[1::2], strict=True):
        _, new_mode, _, new_sha, status = meta.decode("ascii", "replace").lstrip(":").split(" ")[:5]
        found[os.fsdecode(path)] = _Entry(status[:1], new_mode, new_sha)
    return found


def _head_tree(git: Git, head: str) -> dict[str, tuple[str, str]]:
    """path -> (mode, blob id) of every file, link and submodule of the tree at `head`, names as in `_diff_entries`."""
    found: dict[str, tuple[str, str]] = {}
    for entry in git.run_bytes("ls-tree", "-r", "-z", "--full-tree", head).split(b"\0"):
        meta, _, name = entry.partition(b"\t")
        parts = meta.decode("ascii", "replace").split(" ")
        if len(parts) == 3:
            found[os.fsdecode(name)] = (parts[0], parts[2])
    return found


def _fold(path: str) -> str:
    """The name as a file system that ignores case and Unicode normalisation (macOS, Windows) sees it."""
    return unicodedata.normalize("NFC", path).casefold()


def _shown(path: str) -> str:
    """A name for a message: bytes that are not UTF-8 appear as `\\xff`, never as a character that is not theirs."""
    return os.fsencode(path).decode("utf-8", "backslashreplace")


def check_python_encoding(ctx: IntegrityContext) -> Outcome:
    """A Python file (`.py`, `.pyi`) that `base..head` adds or changes, by anyone, whose declared encoding
    (`tokenize.detect_encoding` on the blob at `head`) is not UTF-8 is a blocker: the harness and the judge read the
    file as UTF-8, Python reads the cookie, and code can hide behind a comment (the agent steps put such a file back, a
    person's commit or an older run is only seen here). Every blob is read up to `COOKIE_PREFIX_BYTES` + 1 bytes, never
    whole: a line 1 or 2 longer than that which could hold a cookie is `unreadable`, a violation too. Every name is
    decoded with `os.fsdecode`, so names that are not UTF-8 stay distinct and a link to one finds that one.

    A Python-named symbolic link of the tree at `head` is followed (a chain, a linked directory; at most 40 links)
    inside the tree. The link is touched by `base..head` when it, a link on the way, or its target is added, changed or
    deleted (a target that is renamed, case only included, counts as deleted), or when its target, folded for case and
    Unicode normalisation, is a changed path's folded name (a case-insensitive file system gives one file both names).
    A touched link is checked at the file it ends at: `<link>: <encoding> (link to <file>)`. When its literal target is
    not a regular file of the tree, a folded name that matches exactly one regular file is taken for it, unless the
    target was deleted. A touched link that ends at no regular file (dangling, a directory, a loop, outside, a target
    deleted or renamed, several folded matches) is the row `<link>: link that cannot be checked`: nothing can say what
    Python reads there. An untouched link is not looked at."""
    git, base, head = ctx.git, ctx.base_sha, ctx.head_sha
    entries = _diff_entries(git, base, head)
    tree = _head_tree(git, head)
    regular = {p: e for p, e in entries.items() if e.status != "D" and e.mode in _REGULAR_MODES and is_python_file(p)}
    links = sorted(p for p, (mode, _) in tree.items() if mode == _LINK_MODE and is_python_file(p))
    if not regular and not links:
        return Outcome(note="no Python file added or changed", skipped=True)
    rows = [
        f"{_shown(path)}: {encoding}"
        for path, entry in sorted(regular.items())
        if (encoding := non_utf8(git.blob_prefix(entry.sha, COOKIE_PREFIX_BYTES + 1))) is not None
    ]  # a bounded prefix of each blob: only the first two lines can hold a cookie
    texts: dict[str, str] = {}

    def read_link(rel: str) -> str | None:
        mode, sha = tree.get(rel, ("", ""))
        if mode != _LINK_MODE:
            return None
        if rel not in texts:
            texts[rel] = os.fsdecode(git.blob_prefix(sha, 4096))
        return texts[rel]

    changed = {p for p, e in entries.items() if e.status != "D"}
    changed_folds = {_fold(p) for p in changed}
    files_by_fold: dict[str, list[str]] = {}
    for p, (mode, _) in tree.items():
        if mode in _REGULAR_MODES:
            files_by_fold.setdefault(_fold(p), []).append(p)

    checked = len(regular)
    for link in links:
        target, followed = resolve_links(link, read_link)
        chain_changed = bool({link, *followed} & changed)
        if target is None:
            if chain_changed:
                rows.append(f"{_shown(link)}: link that cannot be checked")
            continue
        deleted = target in entries and entries[target].status == "D"
        touched = chain_changed or target in entries or _fold(target) in changed_folds
        if not touched:
            continue
        if tree.get(target, ("", ""))[0] in _REGULAR_MODES:
            found = target
        else:
            matches = [] if deleted else files_by_fold.get(_fold(target), [])
            found = matches[0] if len(matches) == 1 else None
        if found is None:
            rows.append(f"{_shown(link)}: link that cannot be checked")
            continue
        checked += 1
        if (encoding := non_utf8(git.blob_prefix(tree[found][1], COOKIE_PREFIX_BYTES + 1))) is not None:
            rows.append(f"{_shown(link)}: {encoding} (link to {_shown(found)})")
    if not rows:
        return Outcome(note=f"{checked} Python file(s) added or changed, each read, none declares another encoding")
    advice = (
        "Python reads the cookie and the harness and the judge read UTF-8, so code can hide behind a comment. "
        "Convert each file to UTF-8 and remove the coding cookie (a link must end at a regular file of the "
        "repository)"
    )
    finding = _blocker("a Python file declares a non-UTF-8 encoding", f"{_listed(rows)}. {advice}")
    return Outcome([finding], f"{len(rows)} Python file(s) with another encoding or a link that cannot be checked")


CHECKS: tuple[tuple[str, Callable[[IntegrityContext], Outcome]], ...] = (
    ("protected paths", check_protected),
    ("pre-existing tests", check_tests),
    ("red-green freeze", check_freeze),
    ("test path freeze", check_test_paths),
    ("content scan", check_scan),
    ("gate configuration", check_gate_config),
    ("test awareness", check_test_awareness),
    ("suppressions", check_suppressions),
    ("tdd history", check_tdd_history),
    ("python encoding", check_python_encoding),
)


def run_integrity(ctx: IntegrityContext) -> IntegrityReport:
    report = IntegrityReport()
    for name, check in CHECKS:
        record_outcome(report, name, check(ctx))
    return report


def record_outcome(report: IntegrityReport, name: str, out: Outcome) -> None:
    """Add one sub-check's row, findings and listings to the report."""
    status = "failed" if any(f.blocking for f in out.findings) else "skipped" if out.skipped else "ok"
    report.checks.append(IntegrityCheck(name, status, out.note))  # type: ignore[arg-type]
    report.findings.extend(out.findings)
    if out.base_tests is not None:
        report.base_tests = out.base_tests
    report.test_awareness.extend(out.listed)
    report.declared.extend(out.declared)
    report.human_protected.extend(out.human)
    report.human_tests.extend(out.human_tests)
    report.human_suppressions.extend(out.human_suppressions)
    report.human_scan.extend(out.human_scan)
    report.human_config.extend(out.human_config)
    report.allowed_tests.extend(out.allowed_tests)
    report.mocked_support.extend(out.mocked)
    report.unfrozen.extend(out.unfrozen)
