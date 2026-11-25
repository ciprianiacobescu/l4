"""Step 1, the run of the base's tests on the unit's code (L4-VER-038, design D13).

The AST comparison of `integrity.check_tests` reads texts; this reads behaviour, in any language with a JUnit
report. The test gate runs once at the unit's head with every test and support file the unit added, changed or
deleted at its base version (`support_base.unit_test_plan`: an added one is set aside), and each test that passed at
the base must still pass. A test that fails, no longer runs, or no longer collects is a blocker, unless a
`tests.superseded` event, a `task.unfrozen`, a `[test-infra]` task or a person's commit as the last to change its
file covers it.

The base reference (R0) is needed only when the run (R1) is not all green or the unit changed runner configuration:
R1's test files are exactly the base's, so an all-green R1 with no collection error has run and passed every test that
passed at the base. R0 comes from the workbench's baseline of the same base sha, from an earlier round of this unit
(`integrity.base_tests` of its `verdict.json`, which lies under the protected `.l4/` and holds a non-empty `passed`
list), or from a run in a merge-base worktree.
"""

import posixpath
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from l4.config.schema import duration_seconds
from l4.evidence.skippred import EARLIER_SOURCE, STEP1_SOURCE, WORKTREE_SOURCE, BaseSkips
from l4.exitcodes import L4Exit
from l4.gates.e2e import run_gate_at
from l4.gates.junit import TestCase, TestReport, fold_subtest_id
from l4.gates.runner import GateSpec
from l4.implementer.excerpt import case_excerpt
from l4.implementer.guards import IGNORE_FILE_GLOBS
from l4.implementer.test_locate import file_of_id
from l4.implementer.workbench import BaseRun, Workbench
from l4.security.protected import glob_match
from l4.vcs.authorship import SHA, is_harness
from l4.verifier.audit import BASE_RUN_ENV, _collection_error
from l4.verifier.evidence import read_verdict
from l4.verifier.failures import BASE_FAILS_TITLE, BASE_GONE_TITLE, BASE_TESTS_GATE
from l4.verifier.gate_repeat import JS_EXTENSIONS
from l4.verifier.gates import failure_records
from l4.verifier.integrity import (
    Commit,
    IntegrityContext,
    Outcome,
    _allowance,
    _blob,
    _blocker,
    _by_people,
    _changed,
    _introducers,
    _last_by_people,
    _listed,
    _named_by_task,
    _text,
    _unit_of,
    commits,
    tagged_files,
)
from l4.verifier.playwright import base_checkout
from l4.verifier.support_base import is_support_file, support_at_base, unit_test_plan
from l4.verifier.types import IntegrityCheck, Severity

FAILS_TITLE = BASE_FAILS_TITLE
GONE_TITLE = BASE_GONE_TITLE
FLAKY_TITLE = "a pre-existing test is flaky on the unit's code"
ROW = "pre-existing tests still pass"
MAX_NAMED_SUPPORT = 3  # files per task that stay at head by L4-VER-079 (the bound of `unfreeze.MAX_PATHS_PER_QUESTION`)
MAX_SUPPORT_REVERTED = 20  # entries of `verify.base_tests.support_reverted`
MAX_LEAD_FILES = 5  # support files the blocker's lead names
MAX_NAMED_SUPPORT_LINES = 40  # added plus deleted lines of such a file
_PARAMETRISED = re.compile(r"\S+\[.*\]")  # the test-name part of a pytest id with a parameter: `test_x[a-b]`


@dataclass
class Judged:
    """R1 against R0: base-passing ids that fail now, ids R1 does not hold, and new collection errors."""

    failing: list[str] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)
    collection_errors: list[str] = field(default_factory=list)
    passed_at_base: int = 0
    still_passing: int = 0


def judge_reports(base: TestReport, head: TestReport) -> Judged:
    passed = sorted(i for i, c in base.tests.items() if c.status == "passed")
    failing = [i for i in passed if i in head.tests and head.tests[i].status != "passed"]
    not_run = [i for i in passed if i not in head.tests]
    new_errors = [e for e in head.collection_errors if e not in base.collection_errors]
    return Judged(failing, not_run, new_errors, len(passed), len(passed) - len(failing) - len(not_run))


def _go_file_of(ctx: IntegrityContext, classname: str, name: str) -> str | None:
    """gotestsum's JUnit id `<import path>::<TestName>[/<case>]` -> the one `*_test.go` file of the package that
    declares `func TestName(`, at head and then at the base. The module path is the `module` line of a `go.mod` and
    need not match where it lies: the longest module that starts the import path gives the package's directory. One
    declaring file or none: more than one is no file."""
    declared = re.compile(rf"^func\s+{re.escape(name.split('/', 1)[0])}\s*\(", re.MULTILINE)
    for rev in (ctx.head_sha, ctx.base_sha):
        paths = ctx.git.run("ls-tree", "-r", "--name-only", rev, check=False).stdout.splitlines()
        best: tuple[str, str] | None = None
        for path in paths:
            if path != "go.mod" and not path.endswith("/go.mod"):
                continue
            found = re.search(r"^\s*module\s+(\S+)", _text(ctx.git, rev, path), re.MULTILINE)
            module = found.group(1).strip('"') if found else ""
            starts = module and (classname == module or classname.startswith(module + "/"))
            if starts and (best is None or len(module) > len(best[0])):
                best = (module, posixpath.dirname(path))
        if best is None:
            continue
        module, root = best
        rest = classname[len(module) :].lstrip("/")
        directory = posixpath.join(root, rest) if rest else root
        files = [
            path
            for path in paths
            if path.endswith("_test.go")
            and posixpath.dirname(path) == directory
            and declared.search(_text(ctx.git, rev, path))
        ]
        if len(files) == 1:
            return files[0]
    return None


def _file_of(ctx: IntegrityContext, test_id: str) -> str | None:
    """The file of a test, looked up at head and then at the base. A pytest id by its dotted module:
    `tests.test_pricing.TestCart::test_x` -> `tests/test_pricing.py`. A Go id by its package: `_go_file_of`."""
    classname, _, name = test_id.partition("::")
    parts = classname.split(".")
    while parts:
        candidate = "/".join(parts) + ".py"
        if any(_blob(ctx.git, rev, candidate) is not None for rev in (ctx.head_sha, ctx.base_sha)):
            return candidate
        parts.pop()
    return _go_file_of(ctx, classname, name) if name else None


def _folds(test_id: str) -> bool:
    """Does a pytest parameter end the id (`mod::test_x[a-b]`)? Only then is `mod::test_x` the test it belongs to."""
    return bool(_PARAMETRISED.fullmatch(test_id.rpartition("::")[2]))


def _recorded(ctx: IntegrityContext) -> tuple[set[str], set[str]]:
    """(exact, bases): the ids of every `tests.superseded` event, and the ids of the Python ones without their
    parameter. The `[` fold is pytest's (`test_x[a-b]` is `test_x`): the ids of another language, whose names may hold
    brackets, are compared exactly."""
    exact: set[str] = set()
    bases: set[str] = set()
    for e in ctx.events:
        if e.type != "tests.superseded" or not isinstance(e.data.get("tests"), list):
            continue
        python = e.data.get("language") in (None, "python")
        for recorded in e.data["tests"]:
            if isinstance(recorded, str):
                exact.add(fold_subtest_id(recorded))
                if python:
                    bases.add(fold_subtest_id(recorded).split("[", 1)[0])
    return exact, bases


def split_allowed(ctx: IntegrityContext, candidates: Sequence[str]) -> tuple[list[str], list[str], list[str]]:
    """(blocked ids, allowed lines, people's lines). Allowed: a `tests.superseded` id; a file a `task.unfrozen` of the
    unit names; a file a `[test-infra]` task's commits touched. People's: a file whose last change in `base..head` is a
    person's commit; the line names every commit that changed it."""
    exact, bases = _recorded(ctx)
    task_named = _named_by_task(ctx)
    unfrozen: dict[str, str] = {}
    for e in ctx.events:
        if e.type == "task.unfrozen":
            named = e.data.get("reason") == "named_by_task"
            source = str((e.data.get("source") if named else e.data.get("question")) or "a human answer")
            for path in e.data.get("paths") or []:
                unfrozen.setdefault(str(path), source)
    infra = tagged_files(ctx, "test-infra")
    blocked, allowed, human = [], [], []
    for test_id in candidates:
        file = _file_of(ctx, test_id)
        folded = test_id.split("[", 1)[0] if _folds(test_id) else test_id
        if test_id in exact or folded in bases:
            by_text = task_named.get(test_id) or task_named.get(folded)
            allowed.append(
                f"{test_id} (named by the task text, {by_text})"
                if by_text
                else f"{test_id} (superseded by a changed criterion)"
            )
        elif file in unfrozen:
            allowed.append(f"{test_id} (task.unfrozen: {unfrozen[file]})")
        elif file in infra:
            allowed.append(f"{test_id} ([test-infra] task)")
        elif file is not None and _last_by_people(
            who := _introducers(ctx, file, lambda before, after: before != after)
        ):
            human.append(
                f"{test_id} fails with the base version of its files (changed by {', '.join(r[SHA][:10] for r in who)})"
            )
        else:
            blocked.append(test_id)
    return blocked, allowed, human


def kept_files(ctx: IntegrityContext, paths: Sequence[str], base: TestReport | None = None) -> dict[str, str]:
    """The files of the revert set that stay at head for the run (second review M4): a test or support file (conftest,
    fixture, golden data, helper) that only people's commits changed, that a `[test-infra]` task changed or that a
    `task.unfrozen` frees, a support file that a task's reviewed text names and only that task's red commit changed
    (L4-VER-079), and a test module whose last change in `base..head` is a person's commit (the rule that excuses its
    failing tests, so the run uses the content the person set). Their effect on the tests is accepted and listed; every
    other file is reverted. A harness change to a support file is read by that listing and by the judge, whose diff
    holds it. A support file a person changed last is reverted: it can change what other files' tests check. `base` is
    the base's test report: a support file a task names stays only when no test of it maps to the file, and with no
    report none stays this way (L4-VER-079)."""
    return _kept(ctx, paths, lambda: base)[0]


def _kept(
    ctx: IntegrityContext, paths: Sequence[str], base_of: Callable[[], TestReport | None]
) -> tuple[dict[str, str], dict[str, int], set[str]]:
    """(kept files with their reasons, task -> named support files reverted for the cap of L4-VER-079, the files kept by
    L4-VER-079). `check_base_tests` lists the last as allowances whatever their reason says: it embeds a plan id, and
    the word `people` in one is no person's commit. `base_of` gives the base's test report, and is called only for a
    file that passed every other condition of L4-VER-079."""
    by_sha = {c.sha: c for c in commits(ctx)}
    kept: dict[str, str] = {}
    named_files: set[str] = set()
    per_task: dict[tuple[str, str], int] = {}
    over: dict[str, int] = {}
    for path in sorted(paths):
        who = _introducers(ctx, path, lambda before, after: before != after)
        if _by_people(who):
            kept[path] = f"only people's commits changed it ({', '.join(r[SHA][:10] for r in who)})"
        elif (why := _allowance(ctx, who, path, by_sha)) is not None:
            kept[path] = why.strip("()")
        elif (named := _named_red_change(ctx, who, path, by_sha, base_of)) is not None:
            key, task, reason = named
            if per_task.get(key, 0) < MAX_NAMED_SUPPORT:
                per_task[key] = per_task.get(key, 0) + 1
                kept[path] = reason
                named_files.add(path)
            else:
                over[task] = over.get(task, 0) + 1
        elif _last_by_people(who) and not is_support_file(ctx.git, ctx.cfg, path, _rev_of(ctx, path)):
            kept[path] = f"people changed it last ({', '.join(r[SHA][:10] for r in who)})"
    return kept, over, named_files


def _regular(ctx: IntegrityContext, rev: str, path: str) -> bool:
    """`path` is a regular file (not a link, not a submodule) at `rev`."""
    listed = ctx.git.run("ls-tree", "-z", rev, "--", f":(literal){path}", check=False).stdout
    return listed.split(" ", 1)[0] in ("100644", "100755") and " blob " in listed


def _changed_lines(ctx: IntegrityContext, path: str) -> int | None:
    """Added plus deleted lines of `path` in `base..head`; None for a binary file or when git cannot count."""
    out = ctx.git.run("diff", "--numstat", ctx.base_sha, ctx.head_sha, "--", f":(literal){path}", check=False).stdout
    fields = out.split("\t")
    if len(fields) < 3 or not fields[0].isdigit() or not fields[1].isdigit():
        return None
    return int(fields[0]) + int(fields[1])


def _names_red_change(ctx: IntegrityContext, commit: Commit, path: str) -> str | None:
    """The `source` of the `task.unfrozen{named_by_task}` of this red commit that lists `path`, else None."""
    for e in ctx.events:
        if (
            e.type != "task.unfrozen" or e.data.get("reason") != "named_by_task"
            or e.data.get("task") != commit.task or _unit_of(ctx, e) != commit.unit
            or e.data.get("red_sha") != commit.sha
        ):  # fmt: skip
            continue
        listed = [str(p) for p in e.data.get("paths") or []]
        listed += [str(k.get("path")) for k in e.data.get("kept") or [] if isinstance(k, dict)]
        source = e.data.get("source")
        if path in listed and isinstance(source, str) and source:
            return source
    return None


def _in_report(report: TestReport, path: str) -> bool:
    """Does a test id of `report` belong to the file `path`? `test_locate.file_of_id` over this one path (the id's head
    is the path, the path with dots for slashes, a dotted Python module or a class of it, or the end of such a path),
    with the JavaScript reading of `gate_repeat.untouched` (a spec id is relative to the runner's test directory: its
    slashes are dots), and one more form: a dotted class name that ends the path without its extension
    (`com.acme.Shared::name` and `src/test/java/com/acme/Shared.java`). An id that holds no path (jest-junit's default
    `{classname} {title}`) maps to no file: the report cannot see a test file then. With one path there is no
    ambiguity to give up on: the id is the file's whenever it can be, which reverts more, never less."""
    stem = posixpath.splitext(path)[0]
    for test_id in report.tests:
        head, sep, rest = test_id.partition("::")
        head = head.removeprefix("./")
        if head.rsplit(".", 1)[-1] in JS_EXTENSIONS:
            head = head.replace("/", ".")
        if file_of_id(head + sep + rest, [path]) == path:
            return True
        if "." in head and stem.endswith("/" + head.replace(".", "/")):
            return True
    return False


def _named_red_change(
    ctx: IntegrityContext,
    who: list[list[str]],
    path: str,
    by_sha: Mapping[str, Commit],
    base_of: Callable[[], TestReport | None],
) -> tuple[tuple[str, str], str, str] | None:
    """L4-VER-079: ((unit, task), task, reason) when `path` is a support file that exists at the base and at head, is no
    ignore file, is at most `MAX_NAMED_SUPPORT_LINES` changed lines, no test of the base's report belongs to, and every
    harness commit that changed it is the red commit of a task whose reviewed text names it (a
    `task.unfrozen{named_by_task}` of that commit). A person's commit needs no cover. With no base report, nothing
    stays. Only `kept_files` reads this; `_allowance` is not widened (L4-VER-030 shares it)."""
    harness = [r for r in who if is_harness(r)]
    if not harness:
        return None
    sources: list[tuple[Commit, str]] = []
    for record in harness:
        commit = by_sha.get(record[SHA])
        source = _names_red_change(ctx, commit, path) if commit is not None and commit.tdd == "red" else None
        if commit is None or source is None:
            return None
        sources.append((commit, source))
    if any(glob_match(g, path) for g in IGNORE_FILE_GLOBS):
        return None
    if not (_regular(ctx, ctx.base_sha, path) and _regular(ctx, ctx.head_sha, path)):
        return None
    if not is_support_file(ctx.git, ctx.cfg, path, ctx.head_sha):
        return None
    lines = _changed_lines(ctx, path)
    if lines is None or lines > MAX_NAMED_SUPPORT_LINES:
        return None
    base = base_of()  # last: it may run the base's tests
    if base is None or _in_report(base, path):
        return None
    commit, source = sources[0]
    tasks = list(dict.fromkeys(c.task for c, _ in sources))
    label = ", ".join(tasks)
    return (
        (commit.unit, commit.task),
        commit.task,
        f"task {label}: changed by its red step, named by its reviewed text ({source})",
    )


def _rev_of(ctx: IntegrityContext, path: str) -> str:
    """The revision that has `path`: head, or the base for a file the unit deleted."""
    return ctx.head_sha if _blob(ctx.git, ctx.head_sha, path) is not None else ctx.base_sha


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or ["no message"])[0][:150]


def _collection_lines(ctx: IntegrityContext, errors: Sequence[str], log_path: Path | None) -> list[str]:
    lines = []
    for error in errors:
        what = ""
        if log_path is not None:
            for stem in (error, error.replace(".", "/")):
                what = _collection_error(log_path, stem).splitlines()[0]
                if "could not be imported" not in what:
                    break
        where = _file_of(ctx, error) or error
        lines.append(f"{where}: {what}" if what else where)
    return lines


def _reports(wb: Workbench) -> tuple[str, ...]:
    return tuple(wb.cfg.gates.test.reports)


def _evidence(wb: Workbench, base_sha: str, command: str, round_no: int) -> dict[str, Any] | None:
    """The `integrity.base_tests` of the newest earlier round with this base sha and command and a non-empty `passed`
    list (an empty one would neuter the check)."""
    for earlier in range(round_no - 1, 0, -1):
        prev = read_verdict(wb.ref.path, earlier)
        data = ((prev or {}).get("integrity") or {}).get("base_tests")
        if (
            isinstance(data, dict)
            and data.get("base_sha") == base_sha
            and data.get("command") == command
            and data.get("passed")
        ):
            return data
    return None


def _report_of(passed: Sequence[str], errors: Sequence[str]) -> TestReport:
    return TestReport({i: TestCase(i, "passed") for i in passed}, list(errors))


def _base_reference(
    wb: Workbench, ctx: IntegrityContext, command: str, round_no: int
) -> tuple[TestReport | None, str, str]:
    """(R0, where it came from, why not)."""
    cached = wb.baselines.get(ctx.base_sha)
    if cached is not None:
        return cached, "baseline", ""
    if (data := _evidence(wb, ctx.base_sha, command, round_no)) is not None:
        return _report_of(data["passed"], data.get("collection_errors") or []), "evidence", ""
    report, why = _run_base_gate(wb, ctx.base_sha, command)
    return (report, "base worktree", "") if report is not None else (None, "", why)


def _exit_reason(wb: Workbench, exc: L4Exit) -> str:
    """The first line of an exit's message, redacted and cut: it goes into a note that is committed."""
    lines = str(exc).splitlines()
    return wb.redactor.redact_text(lines[0] if lines else type(exc).__name__)[:300]


def _run_base_gate(wb: Workbench, base_sha: str, command: str) -> tuple[TestReport | None, str]:
    """The test gate in a worktree of the base, network off: (its report, why not). The run is kept on `wb.base_runs`,
    whoever asked (step 1's reference, or step 3's lookup), and so is its failure (no report, or an exit of the
    checkout, which is raised again to the caller that made the run): no round runs the gate twice."""
    key = (base_sha, command)
    if (kept := wb.base_runs.get(key)) is not None:
        return kept.report, kept.why
    spec = GateSpec("base-tests-base", command, _reports(wb), "junit", duration_seconds(wb.cfg.gates.timeout))
    try:
        with base_checkout(wb, base_sha) as tree:
            result = run_gate_at(wb, tree, spec, network=False)
    except L4Exit as exc:
        wb.base_runs[key] = BaseRun(None, _exit_reason(wb, exc))
        raise
    if result.report is None:
        why = f"the base's test gate gave no report ({result.reason})"
        wb.base_runs[key] = BaseRun(None, why)
        return None, why
    wb.base_runs[key] = BaseRun(result.report)
    return result.report, ""


def _skipped_ids(report: TestReport) -> list[str]:
    return sorted(i for i, c in report.tests.items() if c.status == "skipped")


def _recorded_skips(wb: Workbench, base_sha: str, command: str, round_no: int) -> list[str] | None:
    """The `skipped` list of the newest earlier round's `integrity.base_tests` with this base sha and command that has
    one. A record without the key says nothing (an older harness, or a round whose reference was rebuilt from passed ids
    or was the head's own run): it is walked past, never read as "nothing was skipped"."""
    for earlier in range(round_no - 1, 0, -1):
        data = (((read_verdict(wb.ref.path, earlier) or {}).get("integrity") or {}).get("base_tests")) or {}
        if (
            isinstance(data, dict)
            and data.get("base_sha") == base_sha
            and data.get("command") == command
            and isinstance(data.get("skipped"), list)
        ):
            return [i for i in data["skipped"] if isinstance(i, str)]
    return None


class SkipLookup:
    """What the base's test report with statuses says about skipped tests (L4-VER-092, rule (a)), asked by step 3 once a
    skipped test of a changed file could predate the unit. Where the answer comes from, in this order:

    (i) the reference step 1 used this round, when it was a full report (`step1`, from `Outcome.base_report`: a cached
        baseline or a base worktree run; never R1, which is the base's test files on the unit's code);
    (ii) the newest earlier round's `integrity.base_tests` of this base sha and command that has a `skipped` key;
    (iii) the run of the test gate in a base worktree, kept on the workbench (`wb.base_runs`) so that no round runs it
        twice: step 1's reference may have made it already (it keeps the run even when it hands nothing over, for
        example an all-kept or all-green step 1); else this lookup makes it. The implementer's `wb.baselines` is left
        as it is.

    The answer is kept in the object, so a round that asks twice gets the same one. No report is `skipped=None`.

    The verifier builds a workbench for each round, so (iii) lives for one round. `record` is what carries it to the
    next: the round writes it into its own `integrity.base_tests`, and the next round's lookup finds it at (ii)."""

    def __init__(self, wb: Workbench, base_sha: str, round_no: int, step1: TestReport | None = None) -> None:
        self.wb, self.base_sha, self.round_no, self.step1 = wb, base_sha, round_no, step1
        self._found: BaseSkips | None = None
        self._ran: TestReport | None = None  # the full report of a base worktree run, when the answer came from one

    def __call__(self) -> BaseSkips:
        if self._found is None:
            self._found = self._look()
        return self._found

    def _look(self) -> BaseSkips:
        wb, command = self.wb, self.wb.cfg.gates.test.command
        if self.step1 is not None:
            return BaseSkips(frozenset(_skipped_ids(self.step1)), STEP1_SOURCE)
        if (recorded := _recorded_skips(wb, self.base_sha, command, self.round_no)) is not None:
            return BaseSkips(frozenset(recorded), EARLIER_SOURCE)
        try:
            report, why = _run_base_gate(wb, self.base_sha, command)  # kept: step 1 may have made it
        except L4Exit as exc:  # `gates.setup` failed at the merge base: say so, and leave the finding in place
            return BaseSkips(None, "", f"no base report with statuses: {_exit_reason(wb, exc)}")
        if report is None:
            return BaseSkips(None, "", f"no base report with statuses: {why}")
        self._ran = report
        return BaseSkips(frozenset(_skipped_ids(report)), WORKTREE_SOURCE)

    def record(self, current: dict[str, Any] | None) -> dict[str, Any] | None:
        """The `integrity.base_tests` of this round after the lookup, when it must change, else None. Only a full report
        is written: a lookup that ran the base gate (a full report, every status) adds `skipped` to the round's record
        when that has none, or makes the whole record (`passed`, `collection_errors` and `skipped`, as step 1 writes it
        from a full reference) when step 1 wrote none. `current` is not changed in place."""
        if self._ran is None:
            return None
        command = self.wb.cfg.gates.test.command
        skipped = _skipped_ids(self._ran)
        if current is None:
            return {
                "base_sha": self.base_sha,
                "command": command,
                "passed": sorted(i for i, c in self._ran.tests.items() if c.status == "passed"),
                "collection_errors": list(self._ran.collection_errors),
                "skipped": skipped,
            }
        if current.get("base_sha") != self.base_sha or current.get("command") != command or "skipped" in current:
            return None
        return {**current, "skipped": skipped}


def _support_reverted(
    ctx: IntegrityContext, reverted: Sequence[str], by_sha: Mapping[str, Commit]
) -> list[dict[str, Any]]:
    """L4-VER-080: for each reverted file that is a support file, `{path, tasks, people}`: the tasks of the harness
    commits that changed it and whether a person's commit did. Sorted by path, at most `MAX_SUPPORT_REVERTED`."""
    support = sorted(p for p in reverted if is_support_file(ctx.git, ctx.cfg, p, _rev_of(ctx, p)))
    found: list[dict[str, Any]] = []
    for path in support[:MAX_SUPPORT_REVERTED]:
        who = _introducers(ctx, path, lambda before, after: before != after)
        tasks = [c.task for r in who if is_harness(r) and (c := by_sha.get(r[SHA])) is not None]
        found.append({"path": path, "tasks": list(dict.fromkeys(tasks)), "people": any(not is_harness(r) for r in who)})
    return found


def _lead(support: Sequence[Mapping[str, Any]], total: int, files: int, verb: str) -> str:
    """The start of a base-tests blocker's detail (L4-VER-080): which support files the run reverted and who changed
    them. Empty when it reverted none."""
    if not support:
        return ""
    named = []
    for entry in support[:MAX_LEAD_FILES]:
        if entry["tasks"]:
            who = f"task {', '.join(entry['tasks'])}"
        else:  # no task trailer: a person's commit, or a harness commit with none (a lessons commit)
            who = "a person" if entry["people"] else "a harness commit"
        named.append(f"{entry['path']} ({who})")
    more = f" (+{total - MAX_LEAD_FILES} more)" if total > MAX_LEAD_FILES else ""
    return (
        f"with the unit's test and support files at their base version (support files reverted: "
        f"{', '.join(named)}{more}; {files} files in all), these base tests {verb}: "
    )


def check_base_tests(
    wb: Workbench, ctx: IntegrityContext, *, prior: Sequence[IntegrityCheck], round_no: int
) -> Outcome:
    """The sub-check `pre-existing tests still pass` (design D13). Emits `verify.base_tests`."""
    if any(c.status == "failed" for c in prior):
        return Outcome(note="step 1 already failed", skipped=True)
    cfg = wb.cfg
    command = cfg.gates.test.command
    reference: list[tuple[TestReport | None, str, str]] = []

    def base_reference() -> tuple[TestReport | None, str, str]:
        if not reference:
            reference.append(_base_reference(wb, ctx, command, round_no))
        return reference[0]

    full = unit_test_plan(wb.git, cfg, ctx.base_sha, ctx.head_sha, None)
    kept, over, named_files = _kept(ctx, [path for path, _ in full.changes], lambda: base_reference()[0])
    plan = replace(full, changes=tuple(c for c in full.changes if c[0] not in kept))
    # a file the named rule kept is an allowance; for the others the reason text decides, as in 0.4.59
    human_kept = {p for p, why in kept.items() if "people" in why and p not in named_files}
    allowed_files = [f"{p} kept at head for the run ({why})" for p, why in kept.items() if p not in human_kept]
    people_files = [f"{p} kept at head for the run ({why})" for p, why in kept.items() if p in human_kept]
    changed = _changed(ctx.git, ctx.base_sha, ctx.head_sha)
    runner_changed = sorted(p for p in changed if any(glob_match(g, p) for g in cfg.tdd.runner_config_files))
    if not plan.changes and not runner_changed:
        note = "the unit changed no test or support file; step 3 runs the base's tests as they are"
        if kept:
            note = f"all {len(kept)} changed test and support file(s) are allowed and kept at head (listed)"
        return Outcome(note=note, allowed_tests=allowed_files, human_tests=people_files)
    for setup in cfg.gates.setup:
        done = wb.run_gate("setup-base-tests", setup, network=True, builds_env=True)
        if done.status != "pass":
            return Outcome(note="gates.setup failed (step 2 reports it)", skipped=True)
    with support_at_base(wb, ctx.base_sha, plan) as reverted:
        gate = wb.run_gate("base-tests", command, reports=_reports(wb), extra_env=BASE_RUN_ENV)
        repeat = None
        r1 = gate.report
        if r1 is not None and any(c.status in ("failed", "error") for c in r1.tests.values()):
            repeat = wb.run_gate("base-tests-repeat", command, reports=_reports(wb), extra_env=BASE_RUN_ENV).report
    support = _support_reverted(ctx, reverted, {c.sha: c for c in commits(ctx)})  # L4-VER-080: recorded for every run
    if r1 is None:
        detail = f"the test gate gave no report with the unit's test and support files at the base ({gate.reason})"
        _emit(wb, round_no, ctx, "not needed", reverted, Judged(), [], [], [], support)
        return Outcome([_blocker(GONE_TITLE, detail)], "no report from the run of the base's tests")
    needs_base = runner_changed or r1.collection_errors or any(c.status != "passed" for c in r1.tests.values())
    if needs_base:
        r0, source, why = base_reference()
        if r0 is None:
            return Outcome(note=f"no base reference: {why}", skipped=True)
    else:
        r0, source = r1, "not needed"
    judged = judge_reports(r0, r1)
    flaky: list[str] = []
    if repeat is not None:
        flaky = [i for i in judged.failing if i in repeat.tests and repeat.tests[i].status == "passed"]
        judged.failing = [i for i in judged.failing if i not in flaky]
        judged.still_passing += len(flaky)
    candidates = [*judged.failing, *judged.not_run]
    blocked, allowed, human = split_allowed(ctx, candidates)
    findings = []
    failing = [i for i in judged.failing if i in blocked]
    gone = [i for i in judged.not_run if i in blocked]
    errors = _collection_lines(ctx, judged.collection_errors, gate.log_path)
    total = len([p for p in reverted if is_support_file(ctx.git, ctx.cfg, p, _rev_of(ctx, p))]) if support else 0
    records: dict[str, dict[str, str]] = {}
    if failing:
        detail = [f"{i} ({_first_line(r1.tests[i].message or r1.tests[i].status)})" for i in failing]
        findings.append(_blocker(FAILS_TITLE, _lead(support, total, len(reverted), "fail") + _listed(detail)))
        redact, tmp_root = wb.redactor.redact_text, wb.unit_cache / "gate-tmp"  # as `ladder.tests()` (L4-VER-078)
        records, _ = failure_records(
            TestReport({i: r1.tests[i] for i in failing}), None, redact, unit_gate=BASE_TESTS_GATE,
            excerpt=lambda case: case_excerpt(case, worktree=wb.worktree, tmp_root=tmp_root, redact=redact),
        )  # fmt: skip
    if gone or errors:
        lead = _lead(support, total, len(reverted), "no longer run")
        findings.append(_blocker(GONE_TITLE, lead + _listed([*gone, *errors])))
    if flaky:
        findings.append(_blocker(FLAKY_TITLE, _listed(flaky), Severity.MINOR))
    note = (
        f"{judged.still_passing + len(allowed) + len(human)} of {judged.passed_at_base} base tests pass on the unit's "
        f"code with its {len(reverted)} test and support files at the base (base: {source})"
    )
    for task, count in sorted(over.items()):
        note += f"; {count} more support file(s) named by task {task} reverted (at most {MAX_NAMED_SUPPORT} kept)"
    _emit(wb, round_no, ctx, source, reverted, judged, flaky, [a.split(" (")[0] for a in allowed], errors, support)
    record: dict[str, Any] = {
        "base_sha": ctx.base_sha,
        "command": command,
        "passed": sorted(i for i, c in r0.tests.items() if c.status == "passed"),
        "collection_errors": list(r0.collection_errors),
    }
    full = source in ("baseline", "base worktree")  # R0 is the base's tests on the base's code, with every status
    if full:  # absent means "not observed", never "nothing skipped": R1 and an evidence-built R0 do not say
        record["skipped"] = _skipped_ids(r0)
    return Outcome(
        findings,
        note,
        allowed_tests=[*allowed_files, *allowed],
        human_tests=[*people_files, *human],
        base_tests=record,
        failures=records,
        base_report=r0 if full else None,
    )


def _emit(
    wb: Workbench, round_no: int, ctx: IntegrityContext, source: str, reverted: Sequence[str], judged: Judged,
    flaky: Sequence[str], allowed: Sequence[str], errors: Sequence[str], support: Sequence[Mapping[str, Any]] = (),
) -> None:  # fmt: skip
    wb.emit(
        "verify.base_tests", round=round_no, base_sha=ctx.base_sha, base_source=source, reverted=list(reverted),
        passed_at_base=judged.passed_at_base, still_passing=judged.still_passing, failing=judged.failing,
        not_run=judged.not_run, collection_errors=list(errors), flaky=list(flaky), allowed=list(allowed),
        support_reverted=[dict(e) for e in support],
    )  # fmt: skip
