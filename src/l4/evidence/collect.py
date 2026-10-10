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
from l4.evidence.testsran import TestsRanOutcome, check_tests_ran
from l4.gates.coverage import JSON_NAME, NONCE_NAME, STATUS_NAME
from l4.gates.junit import TestReport
from l4.security.protected import glob_match
from l4.specs.base import UnitRef
from l4.vcs.authorship import SHA, commit_records, is_harness
from l4.vcs.git import Git
from l4.verifier.types import Finding
from l4.verifier.verdicts import hold_id

UNIT_FILES = ("proposal.md", "design.md", "tasks.md")
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
    kind: Literal["scope", "coverage", "unsafe"]
    subjects: tuple[str, ...]  # file paths (scope, unsafe) or `path::qualname` (coverage); empty when about the run

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
    unrun_test_files: list[str] = field(default_factory=list)  # changed test files the caller did not run (not judged)

    @property
    def later_holds(self) -> list[Hold]:
        """The holds of step 6 (diff coverage): step 1 has already reported the scope ones."""
        return self.hold_records[self.scope_holds :]

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


def changed_files(git: Git, base: str, head: str) -> list[tuple[str, str]]:
    """(status letter A|M|D|R, head path) per file of `git diff base head`, by NUL-separated names so that no path
    needs unquoting. Copies and type changes count as additions and modifications."""
    raw = git.run_bytes("diff", "--name-status", "-z", "--find-renames", "--no-ext-diff", base, head, "--")
    fields = [f.decode("utf-8", "replace") for f in raw.split(b"\0") if f]
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(fields):
        code = fields[i][0]
        if code in "RC":
            out.append(("R" if code == "R" else "A", fields[i + 2]))
            i += 3
        else:
            out.append((code if code in "AMD" else "M", fields[i + 1]))
            i += 2
    return out


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
) -> Evidence:
    """`new_tests`: the ledger's red tests. `report`: the step 3 JUnit report (None when the gate produced none).
    `cov_dir`: where `l4_cov` wrote (`cov_env(cov_dir, ...)`), None when the ladder found it to be a symlink (it is
    never read then); `cov_nonce`: that call's `L4_COV_NONCE`, when the caller kept it (else the one recorded in
    `cov_dir`). `gate_passed`: the step 3 gate's own result. `step1`: the `scope_evidence` the ladder already computed
    at step 1 (else it is computed here). `unrun_test_globs`: test files the caller deliberately did not run (the S1
    canary has no browser: `e2e/**`); they are left out of the tests-ran check and listed in `unrun_test_files`."""
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
        ran = check_tests_ran(
            report, new_tests, test_files, added_test_files=added, tree=head_tree, gate_passed=gate_passed
        )

    labels: dict[str, Any] = {
        "files": {f.path: f.label for f in scope_out.files},
        "functions": {f"{f.path}::{f.qualname}": f.label for f in dc.functions} if dc else {},
        "tests_ok": ran.label if ran else None,
        "all_passed": ran.all_passed if ran else None,
    }
    records = [
        *step1.holds,
        *(
            Hold(hold_id(t), t, "coverage", tuple(subjects))
            for t, subjects in zip(cov_check.holds, cov_check.hold_subjects, strict=True)
        ),
    ]
    return Evidence(
        scope_out, dc, cov_check, ran,
        findings=[*scope_out.findings, *cov_check.findings, *(ran.findings if ran else [])],
        holds=[h.text for h in records], hold_records=records, labels=labels, scope_holds=len(step1.holds),
        unrun_test_files=unrun,
    )  # fmt: skip
