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

import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from l4.config.schema import L4Config
from l4.evidence.diffcov import CODE_SUFFIXES
from l4.security.protected import HumanChange, ProtectedSet, glob_match, protected_changes_by_human
from l4.specs.base import Task
from l4.specs.feedback import FEEDBACK_FILENAME
from l4.specs.followup import feedback_home
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
_PYTEST_TABLES = ("pytest", "coverage")
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
    folder = feedback_home(root / ctx.unit_dirs[0])
    if folder == root / ctx.unit_dirs[0]:
        return None
    return (folder / FEEDBACK_FILENAME).relative_to(root).as_posix()


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
    for path in sorted(_changed(ctx.git, ctx.base_sha, ctx.head_sha)):
        if _in_unit_dirs(ctx, path) or path.startswith(HARNESS_OWNED) or path == parents_file:
            continue
        if (rule := protected.match(path)) is not None:
            protected_paths[path] = rule
    # a protected path that only people's commits changed on the branch is allowed and listed (L4-SEC-004); one a
    # harness commit also touched, or that no commit in the range names, stays a blocker
    human = protected_changes_by_human(ctx.git, ctx.base_sha, ctx.head_sha, list(protected_paths))
    listed = {change.path for change in human}
    hits = [f"{path} ({rule})" for path, rule in protected_paths.items() if path not in listed]
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


def check_tests(ctx: IntegrityContext) -> Outcome:
    """A `test_*` function that exists at the base and is gone at head is a blocker (a test moved to another changed
    file is not gone); so is a skip, skipif or xfail marker, or a `pytest.skip(` call, that head has and the base
    did not (new tests included). Per commit (L4-SEC-004, M1.9): one that only people's commits introduced is allowed
    and listed (`Outcome.human_tests`); any harness commit that introduced it too keeps it a blocker."""
    globs = ctx.cfg.tdd.test_globs
    changed = {p: s for p, s in _changed(ctx.git, ctx.base_sha, ctx.head_sha).items() if p.endswith(".py")}
    files = {p: s for p, s in changed.items() if _matches(globs, p) and not _in_unit_dirs(ctx, p)}
    if not files:
        return Outcome(note="no test file changed", skipped=True)
    head_defined: set[str] = set()
    for path, status in files.items():
        if status != "D":
            head_defined |= scan.defined_tests(_text(ctx.git, ctx.head_sha, path))
    deleted, skipped, human = [], [], []
    for path, status in sorted(files.items()):
        before = _text(ctx.git, ctx.base_sha, path)
        after = "" if status == "D" else _text(ctx.git, ctx.head_sha, path)
        for name in sorted(scan.defined_tests(before) - scan.defined_tests(after)):
            if name in head_defined:
                continue
            who = _introducers(
                ctx, path, lambda b, a, n=name: n in scan.defined_tests(b) and n not in scan.defined_tests(a)
            )
            if _by_people(who):
                human.append(f"{path}::{name} deleted by {', '.join(r[SHA][:10] for r in who)}")
            else:
                deleted.append(f"{path}::{name}")
        added = scan.skip_markers(after) - scan.skip_markers(before)
        for name in sorted(added):
            who = _introducers(ctx, path, lambda b, a, n=name: scan.skip_markers(a)[n] > scan.skip_markers(b)[n])
            if _by_people(who):
                human.append(f"{path}::{name} skip marker added by {', '.join(r[SHA][:10] for r in who)}")
            else:
                skipped.append(f"{path}::{name}")
    findings = []
    if deleted:
        findings.append(_blocker("a pre-existing test was deleted", _listed(deleted)))
    if skipped:
        findings.append(_blocker("a skip or xfail marker was added", _listed(skipped)))
    extra = f" (+{len(human)} by humans, listed)" if human else ""
    return Outcome(findings, f"{len(files)} test file(s) compared with the base{extra}", human_tests=human)


# --- 2.5 the red -> green freeze ------------------------------------------------------------------------------------


def _unit_of(ctx: IntegrityContext, event: LedgerEvent) -> str:
    fix = event.data.get("fix_unit")
    return f"{ctx.unit_id.split(':', 1)[0]}:{fix}" if isinstance(fix, str) and fix else ctx.unit_id


# contract C22: `task.red_ok` and `task.done` are written before their commits (they travel inside them) and name the
# step `base`; the sha follows in these events, or is derived from the commits when a kill lost the line
_COMMITTED = {"task.red_ok": "task.red_committed", "task.done": "task.green_committed"}
_STEP_KINDS = {"task.red_ok": ("red", "already-satisfied"), "task.done": ("green", "already-satisfied", "exempt")}


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
    unit, task = _unit_of(ctx, red), red.data.get("task")
    done = [
        e for e in ctx.events
        if e.type == "task.done" and e.data.get("task") == task and _unit_of(ctx, e) == unit
        and (e.ts, e.run_id, e.seq) >= (red.ts, red.run_id, red.seq)
    ]  # fmt: skip
    sha = _sha(ctx, done[-1]) if done else None
    return sha if isinstance(sha, str) and sha != _sha(ctx, red) else None


def _pytest_config(raw: bytes | None) -> Any:
    if raw is None:
        return None
    try:
        tool = tomllib.loads(raw.decode("utf-8")).get("tool", {})
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return raw  # unreadable at one end: any difference counts
    return {k: v for k, v in tool.items() if k in _PYTEST_TABLES}


def _unfrozen_paths(ctx: IntegrityContext, red: LedgerEvent, red_sha: str) -> dict[str, str]:
    """path -> question id, for the paths a `task.unfrozen` of this very red commit (same unit and task) freed: the
    harness wrote it before green's attempt, from a human answer that names the file (M1.10 decision 6)."""
    freed: dict[str, str] = {}
    for e in ctx.events:
        if (
            e.type == "task.unfrozen" and e.data.get("task") == red.data.get("task")
            and e.data.get("red_sha") == red_sha and _unit_of(ctx, e) == _unit_of(ctx, red)
        ):  # fmt: skip
            for path in e.data.get("paths") or []:
                freed[str(path)] = str(e.data.get("question") or "a human answer")
    return freed


def check_freeze(ctx: IntegrityContext) -> Outcome:
    """For each task with a red commit and a green commit: the frozen files (the red tests and the test-support
    files, `task.red_ok.frozen`) are identical at both, and so are the `[tool.pytest*]`/`[tool.coverage*]` sections of
    `pyproject.toml` and the files `pytest.ini`, `.pytest.ini`, `pytest.toml`, `.pytest.toml`, `tox.ini` and
    `setup.cfg`."""
    git, findings, checked, listed = ctx.git, [], 0, []
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
        listed += [
            f"{p} (task {task}, unfrozen by {freed[p]} (human))" for p in sorted(freed) if p in frozen and p in changed
        ]
        runner = sorted(p for p in changed if p in _RUNNER_FILES)
        if "pyproject.toml" in changed and _pytest_config(_blob(git, red_sha, "pyproject.toml")) != _pytest_config(
            _blob(git, green, "pyproject.toml")
        ):
            runner.append("pyproject.toml")
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
    note = f"{checked} task(s): red and green compared" + (
        f" (+{len(listed)} unfrozen by human answers)" if listed else ""
    )
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
    steps = {c.sha: c for c in commits(ctx) if c.tdd in ("green", "exempt")}
    infra = {(unit, t.key) for unit, t in ctx.tasks if "test-infra" in task_tags(t.title)}
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
    keys = {(unit, task.key) for unit, task in ctx.tasks if tag in task_tags(task.title)}
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

    def found_in(path: str, before: str, after: str) -> list[str]:
        found: list[str] = []
        if path.endswith(".py") and _matches(tdd.test_support_globs, path):
            found = sorted(set(scan.result_hooks(after)) - set(scan.result_hooks(before)))
        elif _matches(tdd.runner_config_files, path):
            found = [f"adds the option {option}" for option in scan.addopts_added(before, after)]
        if path.endswith(".py") and (refs := sorted(set(scan.coverage_refs(after)) - set(scan.coverage_refs(before)))):
            found.append(f"names the coverage plugin or its output ({', '.join(refs)})")
        return found

    hits: list[str] = []
    human: list[str] = []
    for path in sorted(changed):
        before, after = _text(git, ctx.base_sha, path), _text(git, ctx.head_sha, path)
        found = [what for what in found_in(path, before, after) if path not in exempt]
        if not found:
            continue
        # per commit (L4-SEC-004, W-D6): a file whose offending change only people's commits introduced is the owner's
        # edit, listed; any harness commit that introduced a hit in it too keeps the hits findings
        who = _introducers(ctx, path, lambda b, a, p=path: bool(found_in(p, b, a)))
        if _by_people(who):
            human += [f"{path}: {what} (added by {', '.join(r[SHA][:10] for r in who)})" for what in found]
        else:
            hits += [f"{path}: {what}" for what in found]
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
        return Outcome(note=_not_python(unread), skipped=True, human_scan=human)
    if not hits:
        return Outcome(
            note=f"no result-manipulating construct in the changed support and runner files{extra}", human_scan=human
        )
    return Outcome(
        [_blocker("a construct that can change what the tests report", _listed(hits))],
        f"{len(hits)} hit(s){extra}" + (f"; {_not_python(unread)}" if unread else ""),
        human_scan=human,
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
        if done is not None and done.data.get("tdd") == "exempt":
            continue
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


CHECKS: tuple[tuple[str, Callable[[IntegrityContext], Outcome]], ...] = (
    ("protected paths", check_protected),
    ("pre-existing tests", check_tests),
    ("red-green freeze", check_freeze),
    ("test path freeze", check_test_paths),
    ("content scan", check_scan),
    ("suppressions", check_suppressions),
    ("tdd history", check_tdd_history),
)


def run_integrity(ctx: IntegrityContext) -> IntegrityReport:
    report = IntegrityReport()
    for name, check in CHECKS:
        out = check(ctx)
        status = "failed" if any(f.blocking for f in out.findings) else "skipped" if out.skipped else "ok"
        report.checks.append(IntegrityCheck(name, status, out.note))  # type: ignore[arg-type]
        report.findings.extend(out.findings)
        report.declared.extend(out.declared)
        report.human_protected.extend(out.human)
        report.human_tests.extend(out.human_tests)
        report.human_suppressions.extend(out.human_suppressions)
        report.human_scan.extend(out.human_scan)
        report.unfrozen.extend(out.unfrozen)
    return report
