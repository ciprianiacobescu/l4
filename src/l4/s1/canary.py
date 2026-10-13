"""The canary generator (M16-G12): labelled S1 items from mutated copies of finished units, labelled by the Stage A
checks and by nothing else.

For a source unit (an `L4-Unit` trailer range with an `implementing` commit) a scratch worktree is made at its head, a
mutation is applied, the project's test command runs with the `l4_cov` plugin, and `collect_evidence` labels files,
changed functions and the test run. A mutation whose labels differ from the intended one is dropped and counted as
`checker_disagreement` (which is also a self-test of Stage A). No engine is built or called here: the module imports
no System-One backend and an import-graph test says so. The runner is `NoSandbox`-like (a plain argv subprocess) and
works on the maintainer's own repositories only (`L4_S1_CANARY_ROOTS`).
"""

import contextlib
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from l4.config.schema import L4Config
from l4.evidence.collect import Evidence, changed_files, collect_evidence, coverage_sources
from l4.evidence.diffcov import changed_functions, diff_lines
from l4.evidence.scope import ChangedFile, classify_files, file_kind, module_of, unit_declared_scope
from l4.evidence.testsran import file_of_test
from l4.exitcodes import ExitCode, L4Exit
from l4.gates.coverage import cov_env, junit_ids
from l4.gates.e2e import E2E_TEST_DIR, e2e_test_dir
from l4.gates.junit import ReportError, TestReport, parse_junit
from l4.redact import Redactor
from l4.s1 import mutations as mut
from l4.s1 import questions as q
from l4.s1.export import SPLITS, Row, assign_splits, balance
from l4.s1.items import items_from_evidence, project_key
from l4.s1.records import ItemRecord
from l4.security.protected import glob_match
from l4.specs.base import Framework, UnitRef
from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers

GENERATOR = "l4/s1-canary@1"
DEFAULT_SPLIT_SEED = 1606
DEFAULT_TEST_COMMAND = f"{sys.executable} -m pytest -q -p no:cacheprovider --junitxml=.l4-out/junit.xml"
ROOTS_ENV = "L4_S1_CANARY_ROOTS"
RUN_ID = "canary"
_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV", "UV_CACHE_DIR", "SYSTEMROOT")
CLASS_QUESTION = {
    q.FILE_RELEVANT: "relevant",
    q.CHANGE_COVERED: "exercised",
    q.TESTS_OK: "all_passed",
}


@dataclass(frozen=True)
class SourceUnit:
    id: str
    name: str
    base: str
    head: str
    spec_dir: str  # repository-relative, in the tree of `head`


@dataclass(frozen=True)
class Intent:
    """What a Stage A label must be after a mutation: `file`/`func` by key, `tests`, or `clean` (nothing is wrong)."""

    kind: Literal["file", "func", "tests", "clean"]
    key: str = ""
    expect: bool = True


@dataclass
class Applied:
    mutation: str
    edits: dict[str, str | None]
    intents: list[Intent]


@dataclass
class RunResult:
    items: list[ItemRecord] = field(default_factory=list)
    dropped: str = ""  # a reason: not_applicable | checker_disagreement | tests_not_run


@dataclass
class Baseline:
    evidence: Evidence
    report: TestReport | None
    new_tests: frozenset[str]
    changes: list[tuple[str, str]]
    items: list[ItemRecord]


# --- repositories and units ------------------------------------------------------------------------------------


def allowed_roots(environ: Mapping[str, str]) -> list[Path]:
    raw = environ.get(ROOTS_ENV)
    if raw:
        return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p]
    return [Path(environ.get("HOME") or Path.home()).expanduser().resolve() / "src"]


def check_repo_allowed(repo: Path, environ: Mapping[str, str]) -> Path:
    """The canary runs the repository's own tests without a sandbox: only the maintainer's repositories. Exit 2."""
    real = repo.resolve()
    if not any(real == root or root in real.parents for root in allowed_roots(environ)):
        raise L4Exit(
            ExitCode.USAGE_ERROR, f"{real} is outside the canary allow-list; set {ROOTS_ENV} to the repository roots"
        )
    return real


def _trailers(message: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in message.splitlines():
        key, sep, value = line.partition(": ")
        if sep and key.startswith("L4-") and key not in out:
            out[key] = value.strip()
    return out


BASE_MERGE = re.compile(r"^chore\(.+\): merge .+@[0-9a-f]{7,40} into the unit branch")  # verifier/basemerge.py


def find_source_units(git: Git, *refs: str) -> list[SourceUnit]:
    """Units with an `implementing` commit, in history order, on the history of `refs` (default `HEAD`; the
    generator passes `HEAD --branches`, so a unit on an open MR branch that never reached `main` is found). base = the
    parent of the first such commit, head = the last commit that carries the unit's trailer and is not its archive
    commit (`L4-Phase: archived`): the verifier saw the unit before the archive moved its change directory, and the
    scope is read at the base, where the archive path does not exist. A unit whose only trailers are on archive
    commits is not found; a unit archived without an archive-phase trailer is found under
    `openspec/changes/archive/*-<name>`.
    # M2: archive-only units"""
    done = git.run(
        "log", "--reverse", "--topo-order", "--format=%H%x1f%P%x1f%B%x1e", *(refs or ("HEAD",)), check=False
    )  # fmt: skip
    first_impl: dict[str, str] = {}
    merged: dict[str, str] = {}  # unit -> the base head its latest base merge brought in (that merge's second parent)
    last: dict[str, str] = {}
    order: list[str] = []
    for record in done.stdout.split("\x1e"):
        fields = record.strip("\n").split("\x1f")
        if len(fields) != 3:
            continue
        sha, parents, message = fields[0].strip(), fields[1].split(), fields[2]
        trailers = _trailers(message)
        unit = trailers.get("L4-Unit")
        if not unit:
            continue
        if unit not in last:
            order.append(unit)
        if trailers.get("L4-Phase") == "archived":
            continue  # the archive commit moves the change directory: the unit's head is the commit before it
        last[unit] = sha
        if len(parents) >= 2 and BASE_MERGE.match(message.splitlines()[0] if message else ""):
            merged[unit] = parents[1]
        if trailers.get("L4-Phase") == "implementing" and unit not in first_impl and parents:
            first_impl[unit] = parents[0]
    out: list[SourceUnit] = []
    for unit in order:
        if unit not in first_impl or ":" not in unit:
            continue
        name = unit.split(":", 1)[1]
        tree = git.run("ls-tree", "-r", "--name-only", last[unit], "--", "openspec/changes", check=False).stdout
        spec = next(
            (
                d
                for d in (f"openspec/changes/{name}", *sorted(_archive_dirs(tree, name)))
                if any(p.startswith(d + "/") for p in tree.splitlines())
            ),
            None,
        )
        if spec is not None:
            base = _unit_base(git, first_impl[unit], last[unit], merged.get(unit))
            out.append(SourceUnit(unit, name, base, last[unit], spec))
    return out


def _unit_base(git: Git, first: str, head: str, merged: str | None) -> str:
    """The commit the unit's change starts from. Without a base merge it is the parent of the first implementing
    commit. After one (M1.7) it is what the verifier uses: the merge-base of the head and the base as merged, so that
    what main brought in is not the unit's change."""
    if merged is None:
        return first
    done = git.run("merge-base", head, merged, check=False)
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else first


def _archive_dirs(tree: str, name: str) -> set[str]:
    found: set[str] = set()
    for path in tree.splitlines():
        parts = PurePosixPath(path).parts
        if len(parts) > 3 and parts[2] == "archive" and parts[3].endswith(f"-{name}"):
            found.add("/".join(parts[:4]))
    return found


# --- running the tests in a scratch copy -------------------------------------------------------------------------


def run_tests(worktree: Path, command: str, cov_dir: Path, packages: Sequence[str], *, timeout: float) -> bool:
    """The project's test command with `l4_cov` loaded. argv list, a minimal environment, no shell. True when the exit
    code is 0. The JUnit report is where the command's `--junitxml` points (default `.l4-out/junit.xml`)."""
    env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
    env.update(cov_env(cov_dir, list(packages)))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        done = subprocess.run(  # noqa: S603 - argv list; the repository is on the maintainer's allow-list
            shlex.split(command), cwd=worktree, env=env, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, check=False,
        )  # fmt: skip
    except (subprocess.TimeoutExpired, OSError):
        return False
    return done.returncode == 0


def write_preserving_newlines(target: Path, text: str) -> None:
    """`text` was read with universal newlines; a file that used CRLF keeps it, or every line would show as changed."""
    target.parent.mkdir(parents=True, exist_ok=True)
    crlf = target.is_file() and b"\r\n" in target.read_bytes()
    target.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


@dataclass
class Bench:
    def __init__(self, git: Git, cfg: L4Config, worktree: Path) -> None:
        self.git, self.cfg, self.worktree = git, cfg, worktree


@dataclass
class Ctx:
    """What a mutation may look at: the scratch tree and the untouched unit's evidence."""

    unit: SourceUnit
    variant: int
    wt: Path
    git: Git
    base: Baseline
    tree: list[str]

    def read(self, path: str) -> str | None:
        try:
            return (self.wt / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None


@contextlib.contextmanager
def _scratch(git: Git, rev: str, root: Path, name: str) -> Iterator[Path]:
    path = root / name
    git.run("worktree", "add", "--quiet", "--detach", str(path), rev)
    try:
        yield path
    finally:
        git.run("worktree", "remove", "--force", str(path), check=False)
        shutil.rmtree(path, ignore_errors=True)


# --- the canary --------------------------------------------------------------------------------------------------


class Canary:
    def __init__(
        self,
        repo: Path,
        *,
        cfg: L4Config,
        seed: int,
        work_dir: Path,
        redactor: Redactor,
        test_command: str | None = None,
        timeout: float = 600.0,
        runner: Callable[..., bool] = run_tests,
    ) -> None:
        self.repo, self.cfg, self.seed, self.work_dir, self.redactor = repo, cfg, seed, work_dir, redactor
        self.git = Git(repo)
        self.command = test_command or cfg.gates.test.command or DEFAULT_TEST_COMMAND
        self.report_rel = cfg.gates.test.reports[0] if cfg.gates.test.reports else ".l4-out/junit.xml"
        self.timeout, self.runner = timeout, runner
        self.project = project_key(self.git, repo.name)
        self.units: list[SourceUnit] = []
        # the canary runs the unit gate command and no browser: a unit's e2e test files are left out of the tests-ran
        # check (a recorded skip), so that its other items still count (live M1.6: two units were `baseline_failed`)
        self.e2e_globs = tuple(dict.fromkeys((f"{E2E_TEST_DIR}/**", f"{e2e_test_dir(cfg.gates.e2e)}/**")))
        self.skipped_e2e: dict[str, list[str]] = {}
        self._baselines: dict[str, Baseline | None] = {}
        self._runs = 0
        self.counts: Counter[str] = Counter()
        self.work_dir.mkdir(parents=True, exist_ok=True)

    # -- running

    skip_reason = "e2e test files were not run: the canary runs the unit gate command, with no browser and no server"

    def _run_once(
        self,
        unit: SourceUnit,
        mutation: str,
        variant: int,
        baseline: Baseline | None,
    ) -> tuple[RunResult, Baseline | None]:
        """One scratch run. With `baseline` None this is the untouched unit and the baseline comes back."""
        self._runs += 1
        name = f"w{self._runs}"
        with _scratch(self.git, unit.head, self.work_dir, name) as wt:
            wt_git = self.git.at(wt)
            head, intents = unit.head, [Intent("clean")]
            if baseline is not None:
                tree = wt_git.run("ls-files").stdout.splitlines()
                applied = self._apply(mutation, Ctx(unit, variant, wt, wt_git, baseline, tree))
                if applied is None:
                    return RunResult(dropped="not_applicable"), None
                for rel, text in applied.edits.items():
                    target = wt / rel
                    if text is None:
                        target.unlink(missing_ok=True)
                    else:
                        write_preserving_newlines(target, text)
                wt_git.run("add", "-A", "--", *applied.edits)
                head = wt_git.commit(
                    f"canary: {applied.mutation}", CommitTrailers(unit.id, RUN_ID, 1, "implementing")
                )  # fmt: skip
                mutation, intents = applied.mutation, applied.intents
            cov_dir = self.work_dir / f"{name}-cov"
            packages = coverage_sources(wt_git, unit.base, head, self.cfg, unit.spec_dir)
            passed = self.runner(wt, self.command, cov_dir, packages, timeout=self.timeout)
            try:
                report: TestReport | None = parse_junit(wt / self.report_rel)
            except (ReportError, OSError):
                report = None
            changes = changed_files(wt_git, unit.base, head)
            added = {p for s, p in changes if s == "A" and file_kind(p, unit.spec_dir, self.cfg) == "test"}
            known = baseline.new_tests if baseline else frozenset()
            head_tree = frozenset(wt_git.run("ls-tree", "-r", "--name-only", head).stdout.splitlines())
            fresh = frozenset(i for i in (report.tests if report else ()) if file_of_test(i, added, head_tree))
            new_tests = known | fresh
            ref = UnitRef(Framework.OPENSPEC, unit.name, wt / unit.spec_dir)
            ev = collect_evidence(
                Bench(wt_git, self.cfg, wt), unit.base, head, report, cov_dir, ref, new_tests=new_tests,
                gate_passed=passed, unrun_test_globs=self.e2e_globs,
            )  # fmt: skip
            if ev.unrun_test_files and unit.id not in self.skipped_e2e:
                self.skipped_e2e[unit.id] = list(ev.unrun_test_files)
            shutil.rmtree(cov_dir, ignore_errors=True)
            if report is None:
                return RunResult(dropped="tests_not_run"), None
            if not _holds(ev, intents):
                return RunResult(dropped="checker_disagreement"), None
            items = items_from_evidence(
                ev, git=wt_git, cfg=self.cfg, redactor=self.redactor, project=self.project, unit_id=unit.id,
                unit_name=unit.name, spec_dir=unit.spec_dir, base=unit.base, head=head, report=report,
                new_tests=new_tests, origin="canary", run_id=RUN_ID, round=1,
                tags=[f"mutation:{mutation}", f"source:{unit.id}"],
            )  # fmt: skip
            made = Baseline(ev, report, new_tests, changes, items) if baseline is None else None
            return RunResult(items), made

    def baseline(self, unit: SourceUnit) -> Baseline | None:
        if unit.id not in self._baselines:
            result, made = self._run_once(unit, "none", 0, None)
            self.counts[f"run:none:{result.dropped or 'ok'}"] += 1
            self._baselines[unit.id] = made
            if made is not None:
                made.items = result.items
        return self._baselines[unit.id]

    def run(self, unit: SourceUnit, mutation: str, variant: int = 0) -> RunResult:
        """The items one mutation of one unit yields; `dropped` says why there are none."""
        base = self.baseline(unit)
        if base is None:
            return RunResult(dropped="baseline_failed")
        if mutation == "none":
            return RunResult(base.items) if variant == 0 else RunResult(dropped="not_applicable")
        result, _ = self._run_once(unit, mutation, variant, base)
        self.counts[f"run:{mutation}:{result.dropped or 'ok'}"] += 1
        return result

    # -- mutations

    def _apply(self, mutation: str, ctx: Ctx) -> Applied | None:
        if mutation == "transplant_hunk":
            return self._transplant(ctx) or self._template(ctx)
        return {
            "template_edit": self._template,
            "drop_covering_test": self._drop_test,
            "untested_function": self._untested,
            "break_test": self._break_test,
            "add_passing_test": self._add_passing_test,
            "skip_old_test": self._skip_old_test,
        }[mutation](ctx)

    def _scope(self, ctx: Ctx) -> Any:
        return unit_declared_scope(ctx.read, ctx.unit.spec_dir, ctx.tree, self.cfg.verifier.evidence.module_roots)

    def _out_of_scope(self, ctx: Ctx, path: str) -> bool:
        (fs,) = classify_files([ChangedFile(path, "M")], self._scope(ctx), self.cfg, unit_dir=ctx.unit.spec_dir)
        return fs.kind == "code" and fs.label == "out_of_scope"

    def _template(self, ctx: Ctx) -> Applied | None:
        candidates = sorted(p for p in ctx.tree if p.endswith(".py") and self._out_of_scope(ctx, p))
        if not candidates:
            return None
        path = candidates[mut.pick(self.seed, len(candidates), ctx.unit.id, "template", ctx.variant)]
        text = ctx.read(path)
        if text is None:
            return None
        return Applied("template_edit", {path: mut.add_template_edit(text, ctx.variant)}, [Intent("file", path, False)])

    def _transplant(self, ctx: Ctx) -> Applied | None:
        others = [u for u in self.units if u.id != ctx.unit.id]
        if not others:
            return None
        start = mut.pick(self.seed, len(others), ctx.unit.id, "transplant", ctx.variant)
        for offset in range(len(others)):
            other = others[(start + offset) % len(others)]
            found = self._donor(ctx, other)
            if found is not None:
                path, blocks = found
                text = ctx.read(path) or ""
                return Applied(
                    "transplant_hunk", {path: mut.append_blocks(text, blocks)}, [Intent("file", path, False)]
                )
        return None

    def _donor(self, ctx: Ctx, other: SourceUnit) -> tuple[str, list[str]] | None:
        """A code file another unit changed, in a module this unit does not name, and the top-level definitions of
        that change, renamed, as blocks."""
        git = self.git
        for status, path in changed_files(git, other.base, other.head):
            if status == "D" or not path.endswith(".py") or file_kind(path, other.spec_dir, self.cfg) != "code":
                continue
            if module_of(path, self.cfg.verifier.evidence.module_roots) is None or not self._out_of_scope(ctx, path):
                continue
            text = git.run("show", f"{other.head}:{path}", check=False).stdout
            lines = diff_lines(git, other.base, other.head).get(path, frozenset())
            blocks = [
                b
                for f in changed_functions(path, text, set(lines))
                if "." not in f.qualname and not f.qualname.startswith("<")
                if (b := mut.top_level_block(text, f.span, ctx.read(path) or "", ctx.variant)) is not None
            ]
            if blocks:
                return path, blocks
        return None

    def _untested(self, ctx: Ctx) -> Applied | None:
        files = [f for f in ctx.base.evidence.scope.files if f.kind == "code" and f.label == "relevant"]
        files = [f for f in files if f.path.endswith(".py") and ctx.read(f.path) is not None]
        if not files:
            return None
        path = files[mut.pick(self.seed, len(files), ctx.unit.id, "untested", ctx.variant)].path
        text, name = mut.add_untested_function(ctx.read(path) or "", ctx.variant)
        return Applied("untested_function", {path: text}, [Intent("func", f"{path}::{name}", False)])

    def _drop_test(self, ctx: Ctx) -> Applied | None:
        cov = ctx.base.evidence.coverage
        report = ctx.base.report
        if cov is None or report is None:
            return None
        funcs = sorted(
            (f for f in cov.functions if f.status == "covered" and f.tests), key=lambda f: (f.path, f.qualname)
        )
        if not funcs:
            return None
        func = funcs[mut.pick(self.seed, len(funcs), ctx.unit.id, "drop", ctx.variant)]
        test_files = {p for p in ctx.tree if p.endswith(".py")}
        per_file: dict[str, list[tuple[str | None, str]]] = {}
        for test_id in sorted(junit_ids(func.tests, report.tests)):
            path = file_of_test(test_id, test_files)
            if path is None:
                continue
            classname, _, name = test_id.rpartition("::")
            owner = classname.split(".")[-1] if PurePosixPath(path).stem != classname.split(".")[-1] else None
            per_file.setdefault(path, []).append((owner, name.split("[", 1)[0]))
        edits: dict[str, str | None] = {}
        for path, targets in per_file.items():
            text = ctx.read(path)
            skip = ctx.variant % 2 == 1
            new = mut.remove_or_skip_tests(text, targets, skip=skip, variant=ctx.variant) if text is not None else None
            if new is None:
                return None
            edits[path] = new
        if not edits:
            return None
        return Applied("drop_covering_test", edits, [Intent("func", f"{func.path}::{func.qualname}", False)])

    def _break_test(self, ctx: Ctx) -> Applied | None:
        """A new test that fails; when no test has an integer equality to flip, one that errors at setup or is
        skipped. All three make `tests_ok` false."""
        added = sorted(
            p for s, p in ctx.base.changes
            if s == "A" and file_kind(p, ctx.unit.spec_dir, self.cfg) == "test" and self._runs_it(p)
        )  # fmt: skip
        edits: tuple[Callable[[str], str | None], ...] = (
            lambda t: mut.flip_expected_literal(t, ctx.variant),
            lambda t: mut.add_missing_fixture(t, ctx.variant),
            lambda t: mut.skip_a_test(t, ctx.variant),
        )
        for edit in edits:
            for offset in range(len(added)):
                path = added[(mut.pick(self.seed, len(added), ctx.unit.id, "break") + offset) % len(added)]
                text = ctx.read(path)
                new = edit(text) if text is not None else None
                if new is not None:
                    return Applied("break_test", {path: new}, [Intent("tests", "", False)])
        return None

    def _runs_it(self, path: str) -> bool:
        """Whether the canary's command runs the test file: an e2e one it leaves out (`e2e_globs`) is no mutation
        target, since a change to it changes nothing the checks see (a `checker_disagreement` that is not one)."""
        return not any(glob_match(g, path) for g in self.e2e_globs)

    def _added_tests(self, ctx: Ctx) -> list[str]:
        return sorted(
            p for s, p in ctx.base.changes
            if s == "A" and p.endswith(".py") and file_kind(p, ctx.unit.spec_dir, self.cfg) == "test"
            and self._runs_it(p)
        )  # fmt: skip

    def _add_passing_test(self, ctx: Ctx) -> Applied | None:
        """A passing test added to a test file the unit added: tests-ok stays true and its state changes."""
        added = self._added_tests(ctx)
        for offset in range(len(added)):
            path = added[(mut.pick(self.seed, len(added), ctx.unit.id, "passing", ctx.variant) + offset) % len(added)]
            text = ctx.read(path)
            new = mut.add_passing_test(text, ctx.variant) if text is not None else None
            if new is not None:
                return Applied("add_passing_test", {path: new}, [Intent("tests", "", True)])
        return None

    def _skip_old_test(self, ctx: Ctx) -> Applied | None:
        """An existing test, in a test file the unit did not add, is skipped: the state lists it under "Not passed", so
        "did every test of the run pass?" is no (the run's own exit status is still green)."""
        added = set(self._added_tests(ctx))
        old = sorted(
            p for p in ctx.tree
            if p.endswith(".py") and p not in added and file_kind(p, ctx.unit.spec_dir, self.cfg) == "test"
            and self._runs_it(p)
        )  # fmt: skip
        for offset in range(len(old)):
            path = old[(mut.pick(self.seed, len(old), ctx.unit.id, "skipold", ctx.variant) + offset) % len(old)]
            text = ctx.read(path)
            new = mut.skip_a_test(text, ctx.variant) if text is not None else None
            if new is not None:
                return Applied("skip_old_test", {path: new}, [Intent("tests", "", False)])
        return None


def _holds(ev: Evidence, intents: Sequence[Intent]) -> bool:
    """Did the Stage A checks label the mutated tree the way the mutation meant?"""
    files, funcs, tests_ok = ev.labels["files"], ev.labels["functions"], ev.labels["tests_ok"]
    all_passed = ev.labels["all_passed"]
    for intent in intents:
        if intent.kind == "file":
            if files.get(intent.key) != ("relevant" if intent.expect else "out_of_scope"):
                return False
        elif intent.kind == "func":
            if funcs.get(intent.key) is not intent.expect:
                return False
        elif intent.kind == "tests":
            if all_passed is not intent.expect:
                return False
        else:  # clean: nothing is out of scope, uncovered or failing
            if "out_of_scope" in files.values() or False in funcs.values() or tests_ok is False:
                return False
            if not any(v is not None for v in (*files.values(), *funcs.values())):
                return False
    return True


# --- quotas and the generator loop ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Quota:
    target: int = 500
    min_share: float = 0.3  # every label holds at least this share of its question's items
    min_test: int = 30  # and the planned test split holds at least this many per (question, label)
    split_seed: int = DEFAULT_SPLIT_SEED


def balanced_count(items: Mapping[str, ItemRecord], seed: int) -> int:
    """How many rows `l4 s1 export` keeps: the 2:1 class cut runs per split, so the target is checked after it."""
    split_of = assign_splits((i.unit_hash for i in items.values()), seed)
    by_split: dict[str, list[Row]] = {s: [] for s in SPLITS}
    for i in items.values():
        by_split[split_of[i.unit_hash]].append(Row(i.item_key, i.question_set, "", i.expected, i.unit_hash, ()))
    return sum(len(balance(rows, seed)[0]) for rows in by_split.values())


def quota_gaps(items: Mapping[str, ItemRecord], quota: Quota) -> list[str]:
    """What is still missing, empty when the quotas are met. A question is the class question of a set."""
    gaps: list[str] = []
    split_of = assign_splits((i.unit_hash for i in items.values()), quota.split_seed)
    kept = balanced_count(items, quota.split_seed)
    if kept < quota.target:
        gaps.append(f"{kept} of {quota.target} rows after the class balance ({len(items)} items)")
    for set_name, qid in CLASS_QUESTION.items():
        if set_name == q.TESTS_OK:  # a sanity question: its facts are in its own input, so no share or test quota
            continue
        rows = [i for i in items.values() if i.question_set == set_name and qid in i.expected]
        for label in (True, False):
            mine = [i for i in rows if i.expected[qid] is label]
            share = len(mine) / len(rows) if rows else 0.0
            in_test = sum(split_of[i.unit_hash] == "test" for i in mine)
            name = f"{set_name}/{qid}={str(label).lower()}"
            if share < quota.min_share:
                gaps.append(f"{name}: share {share:.0%} below {quota.min_share:.0%}")
            if in_test < quota.min_test:
                gaps.append(f"{name}: {in_test} in the test split, {quota.min_test} wanted")
    return gaps


@dataclass
class Generated:
    items: dict[str, ItemRecord] = field(default_factory=dict)
    counts: Counter[str] = field(default_factory=Counter)
    gaps: list[str] = field(default_factory=list)

    @property
    def met(self) -> bool:
        return not self.gaps


def generate(
    canaries: Sequence[Canary],
    quota: Quota,
    *,
    max_variants: int = 6,
    mutations: Sequence[str] = mut.MUTATIONS,
    on_run: Callable[[str], None] = lambda line: None,
) -> Generated:
    """Round-robin over repositories, units and mutations, variant by variant, until the quotas are met or the
    variants run out. Items are keyed by `item_key`, so a repeated item counts once."""
    out = Generated()
    for canary in canaries:
        canary.units = find_source_units(canary.git, "HEAD", "--branches")  # local branches only, not remotes
        out.counts[f"units:{canary.project}"] = len(canary.units)
    for variant in range(max_variants):
        for canary in canaries:
            for unit in canary.units:
                for mutation in mutations:
                    if mutation == "none" and variant:
                        continue
                    result = canary.run(unit, mutation, variant)
                    out.counts[f"{mutation}:{result.dropped or 'ok'}"] += 1
                    if (
                        unit.id in canary.skipped_e2e
                        and (key := f"e2e_skipped:{canary.project}:{unit.name}") not in out.counts
                    ):
                        out.counts[key] = len(canary.skipped_e2e[unit.id])
                        files = ", ".join(canary.skipped_e2e[unit.id])
                        on_run(f"{canary.project} {unit.name}: {canary.skip_reason} ({files})")
                    for item in result.items:
                        out.items.setdefault(item.item_key, item)
                    on_run(f"{canary.project} {unit.name} {mutation}#{variant}: {result.dropped or len(result.items)}")
                    if not result.dropped and not quota_gaps(out.items, quota):
                        out.gaps = []
                        return out
    out.gaps = quota_gaps(out.items, quota)
    return out
