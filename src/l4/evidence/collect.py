"""Evidence of one unit: scope, diff coverage and tests-ran, collected from git, the spec files, the step 3 JUnit
report and the `l4_cov` output (M1.6, Stage A). Ground truth only: no LLM and no S1 is consulted.

The caller runs the tests (with `l4.gates.coverage.cov_env` in the environment) and hands the report and the coverage
directory in; this module never starts a test run.
"""

import ast
import hashlib
import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Protocol

from l4.config.schema import L4Config
from l4.evidence.diffcov import (
    CODE_SUFFIXES,
    ChangedFunction,
    CoverageCheck,
    DiffCoverage,
    changed_functions,
    check_diff_coverage,
    diff_coverage,
    diff_lines,
    outside_note,
    suffixes,
)
from l4.evidence.report import evidence_json, render_evidence_section
from l4.evidence.scope import ChangedFile, Kind, ScopeContext, ScopeOutcome, check_scope, file_kind, unit_declared_scope
from l4.evidence.skippred import BaseLookup, SkipRule, qualified_name, support_module
from l4.evidence.testsran import TestsRanOutcome, check_tests_ran, file_of_test
from l4.gates.coverage import JSON_NAME, NONCE_NAME, STATUS_NAME
from l4.gates.junit import TestReport
from l4.security.protected import glob_match
from l4.specs.base import UnitRef
from l4.vcs.authorship import SHA, commit_records, is_harness
from l4.vcs.git import Git
from l4.verifier.types import Finding
from l4.verifier.verdicts import hold_id

UNIT_FILES = ("proposal.md", "design.md", "tasks.md", "requirements.md", "bugfix.md")
MAX_SOURCE_BYTES = 500_000


class Bench(Protocol):
    """What collection needs of a `Workbench`."""

    git: Git
    cfg: L4Config
    worktree: Path


@dataclass(frozen=True)
class Hold:
    """A hold with the id its verdict question carries (`H-` + hash of the text) and what it is about, so a later
    verdict round can turn a human's answer into a label without rebuilding anything from a moved head."""

    id: str
    text: str
    kind: Literal["scope", "coverage", "unsafe", "skipped"]
    subjects: tuple[str, ...]  # file paths (scope, unsafe, skipped) or `path::qualname` (coverage); empty: the run

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "kind": self.kind, "subjects": list(self.subjects)}


@dataclass
class Evidence:
    scope: ScopeOutcome
    coverage: DiffCoverage | None
    coverage_check: CoverageCheck
    ran: TestsRanOutcome | None
    findings: list[Finding] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)
    hold_records: list[Hold] = field(default_factory=list)  # the same holds, in the same order, with ids and subjects
    labels: dict[str, Any] = field(default_factory=dict)  # ground truth: files, functions, tests_ok
    item_keys: dict[str, str] = field(default_factory=dict)  # `<question set>|<subject>` -> item_key, set by the caller
    scope_holds: int = 0  # how many of `holds` / `hold_records` come from step 1 (scope and unsafe names)
    ran_holds: int = 0  # how many come from the tests-ran check (skipped tests that predate the unit), after those
    hold_views: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )  # a `skipped` hold's text -> {sha, paths, base_source}
    unrun_test_files: list[str] = field(default_factory=list)  # changed test files the caller did not run (not judged)

    @property
    def ran_hold_records(self) -> list[Hold]:
        """The holds of step 3 (the tests-ran check): they join the round there, whether diff coverage is on or not."""
        return self.hold_records[self.scope_holds : self.scope_holds + self.ran_holds]

    @property
    def later_holds(self) -> list[Hold]:
        """The holds of step 6 (diff coverage): step 1 has already reported the scope ones, step 3 the skipped ones."""
        return self.hold_records[self.scope_holds + self.ran_holds :]

    def section(self) -> list[str]:
        return render_evidence_section(self.scope, self.coverage, self.ran)

    def to_json(self) -> dict[str, Any]:
        return evidence_json(
            self.scope, self.coverage, self.ran, holds=[h.to_json() for h in self.hold_records], items=self.item_keys
        )


def show_blob(git: Git, rev: str, path: str) -> str | None:
    """The text of `path` at `rev` from git, never from the worktree (a link or an edit there is not the commit)."""
    done = git.run("show", f"{rev}:{path}", check=False)
    return done.stdout if done.returncode == 0 and len(done.stdout) <= MAX_SOURCE_BYTES else None


def defines_tests(text: str) -> bool:
    """Does a Python test file define a test function? A file that does not parse is assumed to (the collection
    error is reported on its own)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return True
    return any(
        isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name.startswith("test") for n in ast.walk(tree)
    )


def unsafe_path(path: str) -> bool:
    """A control character in a name: it would reach the coverage rc file and the hold texts verbatim."""
    return any(ord(c) < 32 or ord(c) == 127 for c in path)


def name_status(git: Git, base: str, head: str) -> list[tuple[str, str, str | None]]:
    """(status letter A|M|D|R, head path, old path of a rename or None) per file of `git diff base head`, by
    NUL-separated names so that no path needs unquoting. Copies and type changes count as additions and
    modifications."""
    raw = git.run_bytes("diff", "--name-status", "-z", "--find-renames", "--no-ext-diff", base, head, "--")
    fields = [f.decode("utf-8", "replace") for f in raw.split(b"\0") if f]
    out: list[tuple[str, str, str | None]] = []
    i = 0
    while i < len(fields):
        code = fields[i][0]
        if code in "RC":
            out.append(("R" if code == "R" else "A", fields[i + 2], fields[i + 1] if code == "R" else None))
            i += 3
        else:
            out.append((code if code in "AMD" else "M", fields[i + 1], None))
            i += 2
    return out


def changed_files(git: Git, base: str, head: str) -> list[tuple[str, str]]:
    """(status letter A|M|D|R, head path) per file of `git diff base head` (`name_status` without the old path)."""
    return [(code, path) for code, path, _ in name_status(git, base, head)]


@dataclass(frozen=True)
class Predating:
    """What `skip_predating` decided: the ids whose skip predates the unit, the base report they were read in
    (`source`), and, when no base report with statuses could be had, why (`note`: every candidate stayed a finding)."""

    ids: frozenset[str] = frozenset()
    source: str = ""
    note: str = ""


def skip_predating(
    git: Git,
    base: str,
    head: str,
    files: Collection[str],
    ids: Collection[str],
    cfg: L4Config,
    tree: Collection[str],
    base_skips: BaseLookup | None = None,
) -> Predating:
    """The ids of `ids` (old skipped tests) whose skip predates the unit (L4-VER-092, `skippred.skip_predates`): the
    file is one of `files` (the changed test files), reported modified (not added, renamed or deleted) by `base..head`,
    both blobs are read and parse, the unit added no skip construct that can affect the test, changed no support,
    runner, setup or dependency file and no support module of the tests tree, changed the file only in places that
    cannot change why a test skips (`skipscope`), and the base report holds the test as skipped. `base_skips` gives that
    report; it is called once, and only when a test passed the rest. With none, or when it gives no report or raises,
    nothing predates the unit and the note says why. Never raises and never runs a test: every failure is a skip that
    does not predate the unit."""
    try:
        changes = name_status(git, base, head)
        status = {path: code for code, path, _ in changes}
        changed = [*status, *(old for _, _, old in changes if old is not None)]  # a rename counts at its old path too
        supports: list[str] | None = None  # read from git when the first test of a modified file asks
        candidates: set[str] = set()
        rules: dict[str, SkipRule | None] = {}
        for test_id in sorted(ids):
            path = file_of_test(test_id, files, tree)
            if path is None or status.get(path) != "M":
                continue
            if path not in rules:  # one read and one scan per file, not per test
                if supports is None:
                    supports = _support_modules(git, base, head, changes, cfg)
                before, after = show_blob(git, base, path), show_blob(git, head, path)
                rules[path] = (
                    None if before is None or after is None else SkipRule(before, after, changed, cfg, supports)
                )
            rule = rules[path]
            name = qualified_name(test_id, path)
            if rule is not None and name is not None and rule.no_skip_added(name):
                candidates.add(test_id)
    except Exception:  # a git or parse failure must not stop the evidence step: the skip stays a finding
        return Predating()
    if not candidates:
        return Predating()
    return _with_base_report(candidates, base_skips)


def _support_modules(
    git: Git, base: str, head: str, changes: Sequence[tuple[str, str, str | None]], cfg: L4Config
) -> list[str]:
    """The changed Python files of the tests tree that define no test (`skippred.support_module`; rule (c)): read at
    the head, and at the base for a file the unit changed, deleted or renamed (a module that held tests at the base and
    none now is one too), by the path each revision has it at."""
    found: list[str] = []
    for code, path, old in changes:
        looked = [(head, path)] if code != "D" else []
        looked += [(base, old or path)] if code in "MDR" else []
        for rev, where in looked:
            if (
                where.endswith(".py")
                and not unsafe_path(where)
                and support_module(cfg, where, show_blob(git, rev, where))
            ):
                found.append(where)
                break
    return found


def _with_base_report(candidates: set[str], base_skips: BaseLookup | None) -> Predating:
    """Rule (a): the candidates the base report holds as skipped. No lookup, no report, a failure: none."""
    if base_skips is None:
        return Predating(note="no base report with statuses: none was offered")
    try:
        found = base_skips()
    except Exception as exc:  # noqa: BLE001 - the lookup runs a gate; its failure must leave the finding in place
        return Predating(note=f"no base report with statuses: the lookup failed ({type(exc).__name__})")
    if found.skipped is None:
        return Predating(note=found.why or "no base report with statuses")
    return Predating(frozenset(i for i in candidates if i in found.skipped), found.source)


def skipped_hold_text(path: str, count: int) -> str:
    return (
        f"skipped: existing tests in `{path}` were also skipped in a base report, and the file adds or changes no skip "
        f"the harness reads ({count} tests)"
    )


def _skipped_holds(
    git: Git, head: str, ids: Collection[str], files: Collection[str], tree: Collection[str], source: str = ""
) -> tuple[list[Hold], dict[str, dict[str, Any]]]:
    """One hold per test file for the skipped ids that predate the unit (L4-VER-092, D2), with the binding of its
    accept: the sha of the text, the head blob of the file and the sorted ids, so that an edit of the file or a change
    of what is skipped voids the accept. The ids are not in the text: the question lists them (`paths` of the view). The
    base report the ids were read in (`source`) is in the view and in neither the text nor the binding: the same file
    and ids read in another report are the same hold, and an accept stays in force."""
    by_file: dict[str, list[str]] = {}
    for test_id in sorted(ids):
        if (path := file_of_test(test_id, files, tree)) is not None:
            by_file.setdefault(path, []).append(test_id)
    holds: list[Hold] = []
    views: dict[str, dict[str, Any]] = {}
    for path, found in sorted(by_file.items()):
        text = skipped_hold_text(path, len(found))
        done = git.run("rev-parse", f"{head}:{path}", check=False)
        blob = done.stdout.strip() if done.returncode == 0 else "unreadable"
        sha = hashlib.sha256("\0".join([text, blob, *found]).encode()).hexdigest()
        holds.append(Hold(hold_id(text), text, "skipped", (path,)))
        views[text] = {"sha": sha, "paths": found, "base_source": source}
    return holds, views


def changed_unit_files(git: Git, base: str, head: str, cfg: L4Config, unit_dir: str = "") -> list[tuple[str, Kind]]:
    """(path, kind) of the files the unit added or changed (not deleted), leaving out the harness, spec and
    documentation paths the files table calls exempt (`file_kind`: the unit's folder, `scope_exempt`)."""
    out: list[tuple[str, Kind]] = []
    for status, path in changed_files(git, base, head):
        if status != "D" and not unsafe_path(path) and (kind := file_kind(path, unit_dir, cfg)) != "exempt":
            out.append((path, kind))
    return sorted(out)


def changed_code_files(git: Git, base: str, head: str, cfg: L4Config, unit_dir: str = "") -> list[str]:
    """The changed source files of the unit: code or root files by extension (`CODE_SUFFIXES`), tests and exempt
    paths left out, as `diff_lines` leaves them out for Python."""
    return [
        p for p, kind in changed_unit_files(git, base, head, cfg, unit_dir)
        if kind in ("code", "root") and PurePosixPath(p).suffix.lower() in CODE_SUFFIXES
    ]  # fmt: skip


def coverage_sources(git: Git, base: str, head: str, cfg: L4Config, unit_dir: str = "") -> list[str]:
    """The directories coverage.py should measure: the module directory of every changed Python code file. Needed
    before the test run, to write the rc file."""
    roots = cfg.verifier.evidence.module_roots
    found: set[str] = set()
    for status, path in changed_files(git, base, head):
        if status == "D" or unsafe_path(path) or not path.endswith(".py"):
            continue
        if file_kind(path, unit_dir, cfg) not in ("code",):
            continue
        parts = PurePosixPath(path).parts
        if parts[0] in roots:
            found.add("/".join(parts[:2]) if len(parts) > 2 else parts[0])
        else:
            found.add(parts[0])
    return sorted(found)


def read_coverage(cov_dir: Path, nonce: str | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(coverage JSON, plugin status). The status is `not_run` unless `status.json` says `ok`, carries this run's
    nonce (`nonce`, else the one `cov_env` recorded in the directory) and `coverage.json` is the file the plugin
    wrote (same sha256): a leftover or a rewritten file is refused."""
    try:
        status = json.loads((cov_dir / STATUS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, {"status": "not_run", "reason": "the coverage plugin wrote no status"}
    if not isinstance(status, dict) or status.get("status") != "ok":
        return None, status if isinstance(status, dict) else {"status": "not_run", "reason": "unreadable status"}
    if nonce is None:
        try:
            nonce = (cov_dir / NONCE_NAME).read_text(encoding="utf-8")
        except OSError:
            nonce = ""
    if not nonce or status.get("nonce") != nonce:
        return None, {"status": "not_run", "reason": "coverage was not written by this run"}
    try:
        data = (cov_dir / JSON_NAME).read_bytes()
        cov = json.loads(data)
    except (OSError, ValueError):
        return None, {"status": "not_run", "reason": "the coverage report is missing or unreadable"}
    version = cov.get("meta", {}).get("version") if isinstance(cov, dict) else None
    if hashlib.sha256(data).hexdigest() != status.get("json_sha256") or version != status.get("coverage_version"):
        return None, {"status": "not_run", "reason": "the coverage report does not match what the plugin wrote"}
    return cov, status


@dataclass
class ScopeEvidence:
    """Step 1 of the ladder: what the unit changed and whether it stays inside what the spec declares. Needs no test
    run."""

    outcome: ScopeOutcome
    files: list[ChangedFile]
    unit_rel: str
    holds: list[Hold]


def _human_commit(git: Git, base: str, head: str, path: str) -> str | None:
    """sha10 of the first commit of `base..head` touching `path`, when every such commit is a person's (not the
    harness's): per-commit attribution of the scope check (L4-SEC-004). None: a harness commit touched it, or none."""
    records = commit_records(git, "--reverse", f"{base}..{head}", "--", f":(literal){path}")
    return records[0][SHA][:10] if records and not any(is_harness(r) for r in records) else None


def human_only(git: Git, base: str, head: str, path: str) -> bool:
    """Every commit of `base..head` that touches `path` is a person's, and there is one (`_human_commit`)."""
    return _human_commit(git, base, head, path) is not None


def scope_evidence(wb: Bench, base: str, head: str, unit: UnitRef) -> ScopeEvidence:
    git, cfg = wb.git, wb.cfg
    unit_rel = unit.path.resolve().relative_to(wb.worktree.resolve()).as_posix()
    tree = git.run("ls-tree", "-r", "--name-only", head).stdout.splitlines()
    scope = unit_declared_scope(lambda p: show_blob(git, base, p), unit_rel, tree, cfg.verifier.evidence.module_roots)

    all_changes = changed_files(git, base, head)
    changes = [c for c in all_changes if not unsafe_path(c[1])]
    holds: list[Hold] = []
    for _, path in all_changes:
        if unsafe_path(path):
            note = f"unsafe path name: {path.encode('unicode_escape').decode()}"
            holds.append(Hold(hold_id(note), note, "unsafe", (path,)))
    files: list[ChangedFile] = []
    for status, path in changes:
        text = None
        if file_kind(path, unit_rel, cfg) == "test" and path.endswith(".py") and status != "A":
            text = show_blob(git, base if status == "D" else head, path)
        files.append(ChangedFile(path, status, text, _human_commit(git, base, head, path)))  # type: ignore[arg-type]
    outcome = check_scope(ScopeContext(files, scope, cfg, unit_dir=unit_rel))
    holds += [
        Hold(hold_id(t), t, "scope", (p,) if p else ()) for t, p in zip(outcome.holds, outcome.hold_paths, strict=True)
    ]
    return ScopeEvidence(outcome, files, unit_rel, holds)


def collect_evidence(
    wb: Bench,
    base: str,
    head: str,
    report: TestReport | None,
    cov_dir: Path | None,
    unit: UnitRef,
    *,
    new_tests: Collection[str] = (),
    gate_passed: bool,
    cov_nonce: str | None = None,
    step1: "ScopeEvidence | None" = None,
    unrun_test_globs: Sequence[str] = (),
    base_skips: BaseLookup | None = None,
) -> Evidence:
    """`new_tests`: the ledger's red tests. `report`: the step 3 JUnit report (None when the gate produced none).
    `cov_dir`: where `l4_cov` wrote (`cov_env(cov_dir, ...)`), None when the ladder found it to be a symlink (it is
    never read then); `cov_nonce`: that call's `L4_COV_NONCE`, when the caller kept it (else the one recorded in
    `cov_dir`). `gate_passed`: the step 3 gate's own result. `step1`: the `scope_evidence` the ladder already computed
    at step 1 (else it is computed here). `unrun_test_globs`: test files the caller deliberately did not run (the S1
    canary has no browser: `e2e/**`); they are left out of the tests-ran check and listed in `unrun_test_files`.
    `base_skips`: what the base report with statuses says (`skippred.BaseSkips`), asked once and only when an old
    skipped test of a changed file could predate the unit; without it no skip predates the unit (L4-VER-092)."""
    git, cfg = wb.git, wb.cfg
    step1 = step1 or scope_evidence(wb, base, head, unit)
    scope_out, files = step1.outcome, step1.files

    kinds = {f.path: f.kind for f in scope_out.files}
    mode = cfg.verifier.evidence.diff_coverage.mode
    dc: DiffCoverage | None = None
    if mode != "off":
        # A root-level file (setup.py, noxfile.py, a flat-layout app.py) is never a coverage source (see
        # `coverage_sources`: directories only), so the report cannot contain it. It is listed as unmeasured, with no
        # label and outside the percentage, rather than counted as uncovered.
        lines = diff_lines(git, base, head, exclude=lambda p: unsafe_path(p) or kinds.get(p) in ("test", "exempt"))
        root_files = tuple(p for p in lines if kinds.get(p) == "root")
        funcs: list[ChangedFunction] = []
        for path, changed in lines.items():
            if path not in root_files:
                funcs += changed_functions(path, show_blob(git, head, path) or "", set(changed))
        unsafe = {"status": "not_run", "reason": "the coverage directory .l4-out/cov is a symlink"}
        measured = read_coverage(cov_dir, cov_nonce) if cov_dir is not None else (None, unsafe)
        # Nothing changed in code: 100 percent. Code changed, none of it in a measured language: not applicable, never
        # a pass by default. Both: the Python is measured and the rest is named.
        unit_rel = unit.path.resolve().relative_to(wb.worktree.resolve()).as_posix()
        measured_suffixes = suffixes(cfg.verifier.evidence.diff_coverage.languages)
        other = tuple(
            p for p in changed_code_files(git, base, head, cfg, unit_rel)
            if not p.endswith(measured_suffixes) and kinds.get(p, "code") in ("code", "root")
        )  # fmt: skip
        if funcs:
            dc = diff_coverage(funcs, *measured)
        elif other:
            dc = DiffCoverage(0.0, status="not_applicable", reason=outside_note(other))
        else:
            dc = DiffCoverage(100.0)
        dc = replace(dc, unmeasured_files=root_files, other_files=other)
    cov_check = check_diff_coverage(dc, cfg) if dc else CoverageCheck()

    ran = None
    unrun: list[str] = []
    skipped_holds: list[Hold] = []
    hold_views: dict[str, dict[str, Any]] = {}
    if report is not None:
        test_files = {f.path for f in scope_out.files if f.kind == "test"}
        unrun = sorted(p for p in test_files if any(glob_match(g, p) for g in unrun_test_globs))
        test_files -= set(unrun)
        added = {
            f.path
            for f in files
            if f.status == "A"
            and f.path in test_files
            and f.path.endswith(".py")
            and defines_tests(show_blob(git, head, f.path) or "")
        }
        head_tree = frozenset(git.run("ls-tree", "-r", "--name-only", head).stdout.splitlines())
        old_skipped = report.ids_with("skipped") - set(new_tests)
        predating = (
            skip_predating(git, base, head, test_files, old_skipped, cfg, head_tree, base_skips)
            if old_skipped
            else Predating()
        )
        ran = check_tests_ran(
            report, new_tests, test_files, added_test_files=added, tree=head_tree, gate_passed=gate_passed,
            predating=predating.ids, predating_source=predating.source, base_note=predating.note,
        )  # fmt: skip
        skipped_holds, hold_views = _skipped_holds(
            git, head, ran.summary.skipped_predating, test_files, head_tree, predating.source
        )

    labels: dict[str, Any] = {
        "files": {f.path: f.label for f in scope_out.files},
        "functions": {f"{f.path}::{f.qualname}": f.label for f in dc.functions} if dc else {},
        "tests_ok": ran.label if ran else None,
        "all_passed": ran.all_passed if ran else None,
    }
    records = [
        *step1.holds,
        *skipped_holds,
        *(
            Hold(hold_id(t), t, "coverage", tuple(subjects))
            for t, subjects in zip(cov_check.holds, cov_check.hold_subjects, strict=True)
        ),
    ]
    return Evidence(
        scope_out, dc, cov_check, ran,
        findings=[*scope_out.findings, *cov_check.findings, *(ran.findings if ran else [])],
        holds=[h.text for h in records], hold_records=records, labels=labels, scope_holds=len(step1.holds),
        ran_holds=len(skipped_holds), hold_views=hold_views, unrun_test_files=unrun,
    )  # fmt: skip
