"""Do the red tests discriminate? Zero-value runs of the project source (L4-IMP-002 run (b), pre-satisfied criteria).

Both checks write a zero-value variant of some source modules in place, run the test gate and put the bytes back
(D7): uv installs the project editable, so a scratch copy would import the original worktree's code. The restore is
checked by sha256 and happens before anything is committed; a crash leaves nothing behind because the worktree is
rebuilt on every run.

A test "fails on the zero values" only when it fails by assertion (L4-IMP-002 check 5): an error raised by the zero
value (`round(None)`, `1 / 0`) shows the test touched the answer, not that it checked it. For a stub that returns an
object the test first asserts `result is not None`, then asserts on its attributes.
M1: implementer-tdd-loop 2.2 for languages other than Python.
"""

import ast
import hashlib
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer.stubs import _is_inside, has_stub, zero_value_variant
from l4.implementer.workbench import Workbench
from l4.security.protected import glob_match

PROOF_ZERO_VALUE = "zero_value"
PROOF_PRE_SATISFIED = "pre_satisfied"
PROOF_RED_ASSERTION = "red_assertion"
_ROOTS = ("", "src")  # where an import is looked up inside the repository


def fails_on_zero(case: TestCase | None) -> bool:
    return case is not None and case.status == "failed" and case.failure_kind == "assertion"


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _drop_bytecode(source: Path) -> None:
    """A cached `.pyc` is validated by the source's mtime (in seconds) and size: a variant of the same size written
    within the second of the original could be served the original's bytecode."""
    for cached in (source.parent / "__pycache__").glob(f"{source.stem}.*.pyc"):
        cached.unlink(missing_ok=True)


def _already_varied(target: Path, seen: set[tuple[int, int]]) -> bool:
    """True when `target` is a second name (a hard link, or another spelling on a case-insensitive filesystem) of a file
    in `seen`; otherwise records it. Kiro e2e H1 re-run: `Cart.py` and `cart.py` were one file, the second read
    took the zero-value variant for the original and the restore left it in place."""
    info = target.stat()
    key = (info.st_dev, info.st_ino)
    if key in seen:
        return True
    seen.add(key)
    return False


@contextmanager
def zero_values_in_place(wb: Workbench, paths: Sequence[str], *, public: bool) -> Iterator[list[str]]:
    """Replace the zero-value variants of `paths` (relative to the worktree) for the duration of the block and
    yield the paths that were varied. `public`: every public function and method; else only the red stubs."""
    originals: dict[Path, bytes] = {}
    seen: set[tuple[int, int]] = set()
    try:
        for relative in paths:
            target = wb.worktree / relative
            if not _is_inside(wb.worktree, target) or not target.is_file():
                continue  # a symlinked directory in the repo must not let the gate rewrite a file outside it
            if _already_varied(target, seen):
                continue  # a second name of a file already varied: its "original" would be the variant
            data = target.read_bytes()
            try:
                variant = zero_value_variant(data.decode("utf-8"), public=public)
            except (SyntaxError, UnicodeDecodeError):
                continue
            originals[target] = data
            target.write_bytes(variant.encode("utf-8"))
            _drop_bytecode(target)
        yield [target.relative_to(wb.worktree).as_posix() for target in originals]
    finally:
        broken = []
        for target, data in originals.items():
            target.write_bytes(data)
            _drop_bytecode(target)
            if _digest(target.read_bytes()) != _digest(data):
                broken.append(target.name)
        if broken:
            raise RuntimeError(f"could not restore {', '.join(broken)} after the zero-value run")


def zeroed_run(wb: Workbench, name: str, paths: Sequence[str], *, public: bool) -> GateResult | None:
    """The test gate against the variants; None when no path could be varied (nothing to decide). The reports the gate
    writes are put back as run (a) left them: the published report must describe the real code, not the variants."""
    reports = [wb.worktree / r for r in wb.cfg.gates.test.reports]
    kept = {r: r.read_bytes() for r in reports if r.is_file() and not r.is_symlink()}
    try:
        with zero_values_in_place(wb, paths, public=public) as varied:
            if not varied:
                return None
            return wb.run_gate(name, wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)
    finally:
        for report in reports:
            if report in kept:
                report.write_bytes(kept[report])
            else:
                report.unlink(missing_ok=True)


@contextmanager
def red_code_in_place(wb: Workbench, red_sha: str, paths: Sequence[str] | None = None) -> Iterator[list[str]]:
    """The production files green changed are swapped to their content at the red commit for the duration of the block,
    and put back with a sha256 check (the pattern of `zero_values_in_place`, D7). A module green added has no red
    version: it is set aside. Test and support files are not touched, the corrected test stays as it is. Yields the
    paths that were swapped or set aside. `paths` (M1.11, the verifier's step 4): swap these files to `red_sha`
    instead of the files the worktree has changed since HEAD, which is none when the verifier looks at a commit."""
    ledger = wb.ledger_rel
    originals: dict[Path, bytes] = {}
    seen: set[tuple[int, int]] = set()
    try:
        for relative in sorted(wb.changed_files() if paths is None else paths):
            if relative == ledger or _is_test_path(wb, relative) or relative.startswith((".l4-out/", ".l4/")):
                continue
            target = wb.worktree / relative
            if not _is_inside(wb.worktree, target) or target.is_symlink() or not target.is_file():
                continue  # a deleted file stays deleted; a link must not let the gate rewrite a file outside
            if _already_varied(target, seen):
                continue
            exists_at_red = wb.git.run("cat-file", "-e", f"{red_sha}:{relative}", check=False).returncode == 0
            originals[target] = target.read_bytes()
            if exists_at_red:
                target.write_bytes(wb.git.run_bytes("show", f"{red_sha}:{relative}"))
            else:
                target.unlink()
            _drop_bytecode(target)
        yield [target.relative_to(wb.worktree).as_posix() for target in originals]
    finally:
        broken = []
        for target, data in originals.items():
            target.write_bytes(data)
            _drop_bytecode(target)
            if _digest(target.read_bytes()) != _digest(data):
                broken.append(target.name)
        if broken:
            raise RuntimeError(f"could not restore {', '.join(broken)} after the run at the red commit's code")


def fails_at_red(
    wb: Workbench,
    red_sha: str,
    ids: Sequence[str],
    paths: Sequence[str] | None = None,
    *,
    name: str = "test-at-red",
    extra_env: Mapping[str, str] | None = None,
) -> list[str]:
    """Decision 7: the test gate runs against the red commit's production code with the corrected tests, and the ids of
    `ids` that do not fail there are returned: a corrected test that passes against the code the red phase started from
    no longer discriminates. Fail closed: an id counts as failing only when the report lists it as failed or error, so
    a skipped id, one the report does not hold (its module did not import the red code) and every id of a run that
    wrote no report are returned. Empty: every id still fails at red. The reports the gate writes are put back as the
    real run left them."""
    tests = run_with_code_of(wb, red_sha, paths, name=name, extra_env=extra_env)
    return [i for i in ids if i not in tests or tests[i].status not in ("failed", "error")]


def run_with_code_of(
    wb: Workbench,
    sha: str,
    paths: Sequence[str] | None = None,
    *,
    name: str,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, TestCase]:
    """The test gate's cases with the production files swapped to their content at `sha` (`red_code_in_place`); empty
    when the run wrote no report. The reports the gate writes are put back as the real run left them."""
    reports = [wb.worktree / r for r in wb.cfg.gates.test.reports]
    kept = {r: r.read_bytes() for r in reports if r.is_file() and not r.is_symlink()}
    try:
        with red_code_in_place(wb, sha, paths):
            gate = wb.run_gate(name, wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports, extra_env=extra_env)
    finally:
        for report in reports:
            if report in kept:
                report.write_bytes(kept[report])
            else:
                report.unlink(missing_ok=True)
    return dict(gate.report.tests) if gate.report is not None else {}


@dataclass(frozen=True)
class Vacuity:
    proofs: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> tests that fail on the zero values
    vacuous: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> its tests, none of which does
    reason: str = ""  # run (b) could not decide

    @property
    def message(self) -> str:
        if self.reason:
            return self.reason
        parts = [
            f"{criterion} (its tests pass or error against the zero-value stubs: {', '.join(tests[:5])}); "
            "a test must fail by assertion on the answer (for an object, assert `result is not None` or isinstance "
            "first, then on its attributes)" + self._zero_answer_remedy(criterion)
            for criterion, tests in sorted(self.vacuous.items())
        ]
        return "vacuous: " + "; ".join(parts) if parts else ""

    def _zero_answer_remedy(self, criterion: str) -> str:
        """How a criterion whose scenario expects the zero value itself (an empty cart counts 0) gets a test that
        fails on the stubs: the criterion's own tag on a test that asserts a real answer. Named with a test of this
        attempt that did fail on the zero values, when there is one (live M1.7: "a sibling" was read as a test of
        another criterion, three attempts in a row)."""
        text = (
            f'. If the scenario\'s answer is the zero value itself (0, "", [], None, False), {criterion} still needs '
            "a test that fails on the zero-value stubs: assert a real answer in the same test too"
        )
        proved = next(((c, tests[0]) for c, tests in sorted(self.proofs.items()) if tests and c != criterion), None)
        if proved is not None:
            other, test = proved
            text += (
                f", or tag a test that asserts a real answer with {criterion} as well, for example "
                f'{test}: @pytest.mark.l4("{other}", "{criterion}")'
            )
        return text


def vacuity_check(wb: Workbench, stub_files: Sequence[str], tracing: Mapping[str, Sequence[str]]) -> Vacuity:
    """Run (b): with the red stubs answering their zero value, each criterion in `tracing` (criterion -> the new
    tests that trace it, pre-satisfied ones left out) needs one test that fails."""
    if not tracing:
        return Vacuity()
    gate = zeroed_run(wb, "test-zero", stub_files, public=False)
    if gate is None or gate.report is None:
        return Vacuity(reason=f"the zero-value run produced no readable report ({gate.reason if gate else 'no stub'})")
    proofs: dict[str, tuple[str, ...]] = {}
    vacuous: dict[str, tuple[str, ...]] = {}
    for criterion, tests in tracing.items():
        failing = tuple(t for t in tests if fails_on_zero(gate.report.tests.get(t)))
        (proofs if failing else vacuous)[criterion] = failing or tuple(tests)
    return Vacuity(proofs, vacuous)


# --- pre-satisfied criteria (M13-G3) ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class PreSatisfied:
    confirmed: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> tests that discriminate
    unconfirmed: dict[str, tuple[str, ...]] = field(default_factory=dict)
    reason: str = ""

    @property
    def message(self) -> str:
        if not self.unconfirmed:
            return ""
        listed = ", ".join(sorted(self.unconfirmed))
        why = self.reason or (
            "its tests still pass, or fail by an error rather than an assertion, "
            "when the functions they use answer the zero value"
        )
        return f"not discriminating: {listed} ({why})"


def _matches(globs: Sequence[str], path: str) -> bool:
    return any(glob_match(glob, path) for glob in globs)


def _is_test_path(wb: Workbench, path: str) -> bool:
    tdd = wb.cfg.tdd
    return _matches([*tdd.test_globs, *tdd.test_support_globs], path)


def unit_base(wb: Workbench) -> str | None:
    """Where the unit branch left the base branch, the way the verifier finds it (preconditions step 0)."""
    branch = wb.cfg.forge.base_branch
    for ref in (f"refs/remotes/origin/{branch}", branch):
        sha = wb.git.rev_parse(ref)
        if sha is None:
            continue
        done = wb.git.run("merge-base", sha, "HEAD", check=False)
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip()
    return None


def _changed_modules(wb: Workbench) -> set[str]:
    changed = set(wb.changed_files())
    base = unit_base(wb)
    if base is not None:
        done = wb.git.run("diff", "--name-only", "--no-renames", "--diff-filter=AM", base, "HEAD", check=False)
        changed |= set(done.stdout.splitlines())
    return {p for p in changed if p.endswith(".py") and not _is_test_path(wb, p)}


def _test_file(wb: Workbench, test_id: str) -> str | None:
    """`tests.test_pricing.TestCart::test_x` -> `tests/test_pricing.py` (pytest's classname is the module path)."""
    parts = test_id.split("::", 1)[0].split(".")
    while parts:
        candidate = "/".join(parts) + ".py"
        if (wb.worktree / candidate).is_file():
            return candidate
        parts.pop()
    return None


def _exact_case(root: Path, relative: str) -> bool:
    """Every component of `relative` is spelled as the directory lists it. On a case-insensitive filesystem (macOS)
    `src/pricing/Cart.py` is a file when `cart.py` is, and `from pricing import Cart` names a class, not that module:
    Python's own import checks the case too."""
    current = root
    for part in relative.split("/"):
        try:
            if part not in os.listdir(current):
                return False
        except OSError:
            return False
        current = current / part
    return True


def _resolve(wb: Workbench, dotted: str) -> str | None:
    path = dotted.replace(".", "/")
    for root in _ROOTS:
        for candidate in (f"{path}.py", f"{path}/__init__.py"):
            relative = f"{root}/{candidate}" if root else candidate
            target = wb.worktree / relative
            if target.is_file() and _is_inside(wb.worktree, target) and _exact_case(wb.worktree, relative):
                return relative
    return None


def _imports(wb: Workbench, relative: str) -> set[str]:
    """Dotted names (and, for relative imports, repository paths as dotted names) that a module imports."""
    try:
        tree = ast.parse((wb.worktree / relative).read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return set()
    package = Path(relative).parent.parts
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = package[: max(len(package) - node.level + 1, 0)]
                module = ".".join([*anchor, *(node.module.split(".") if node.module else [])])
            else:
                module = node.module or ""
            if module:
                names |= {module, *(f"{module}.{alias.name}" for alias in node.names)}
    return names


def imported_modules(wb: Workbench, test_ids: Sequence[str]) -> set[str]:
    """The project source modules (inside the repository, outside the test globs) that the tests import. A package
    `__init__.py` is followed, because it usually only re-exports the modules that hold the code."""
    pending = [f for t in test_ids if (f := _test_file(wb, t))]
    found: set[str] = set()
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for dotted in _imports(wb, current):
            resolved = _resolve(wb, dotted)
            if resolved is None or _is_test_path(wb, resolved):
                continue
            found.add(resolved)
            if resolved.endswith("__init__.py"):
                pending.append(resolved)
    return found


def head_stub_modules(wb: Workbench, test_ids: Sequence[str]) -> list[str]:
    """The modules the tests import that already hold a `raise NotImplementedError` stub at HEAD (a scaffold, or an
    earlier task's leftover): red added none of its own, so run (b) zeroes these."""
    found = []
    for relative in sorted(imported_modules(wb, test_ids)):
        try:
            if has_stub((wb.worktree / relative).read_text(encoding="utf-8")):
                found.append(relative)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
    return found


def no_assertion_failure(report: TestReport, tracing: Mapping[str, Sequence[str]]) -> str:
    """Red without a stub of its own and without a HEAD stub fails against real code: each criterion needs a test
    that fails by assertion, the error of a missing parameter or a wrong call does not show the test looks at the
    answer. The message is empty when every criterion has one."""
    bad = {c: tests for c, tests in tracing.items() if not any(fails_on_zero(report.tests.get(t)) for t in tests)}
    if not bad:
        return ""
    return "vacuous: " + "; ".join(
        f"{criterion} (none of its tests fails by assertion: {', '.join(tests[:5])}); a test must assert on the answer"
        for criterion, tests in sorted(bad.items())
    )


def confirm_pre_satisfied(wb: Workbench, candidates: Mapping[str, Sequence[str]]) -> PreSatisfied:
    """`candidates`: criterion -> its new tests, all of which passed in run (a). With every public function of the
    modules those tests import, and of the modules changed since the unit base, answering its zero value, at least
    one of a criterion's tests must fail, otherwise the criterion is not discriminating."""
    if not candidates:
        return PreSatisfied()
    everything = sorted({t for tests in candidates.values() for t in tests})
    scope = sorted(imported_modules(wb, everything) | _changed_modules(wb))
    unconfirmed = {c: tuple(t) for c, t in candidates.items()}
    if not scope:
        return PreSatisfied({}, unconfirmed, "no project source module is imported by those tests")
    gate = zeroed_run(wb, "test-presatisfied", scope, public=True)
    if gate is None or gate.report is None:
        return PreSatisfied(
            {},
            unconfirmed,
            f"the zero-value run produced no readable report ({gate.reason if gate else 'nothing to vary'})",
        )
    return _evaluate(gate.report, candidates)


def _evaluate(report: TestReport, candidates: Mapping[str, Sequence[str]]) -> PreSatisfied:
    confirmed: dict[str, tuple[str, ...]] = {}
    unconfirmed: dict[str, tuple[str, ...]] = {}
    for criterion, tests in candidates.items():
        failing = tuple(t for t in tests if fails_on_zero(report.tests.get(t)))
        if failing:
            confirmed[criterion] = failing
        else:
            unconfirmed[criterion] = tuple(tests)
    return PreSatisfied(confirmed, unconfirmed)


# --- tests no red record covers (M1.11 W6, decision 8) -------------------------------------------------------------


@dataclass(frozen=True)
class ExtraRun:
    """The verifier's decision on tests that people or a test chore wrote: `accepted` maps a test id to `zero_value` (it
    failed by assertion when the project's functions answered their zero value) or `base` (it failed by assertion
    against the unit base's production code); `rejected` are the ids that did neither; `reasons` say why a rejected id
    that did fail on the base is no proof; `runs` is the number of gate runs made (at most two)."""

    accepted: dict[str, str] = field(default_factory=dict)
    rejected: tuple[str, ...] = ()
    runs: int = 0
    reasons: dict[str, str] = field(default_factory=dict)


ERROR_AT_BASE = "fails on the base only with an error, not by assertion"


def production_changes(wb: Workbench, base_sha: str) -> list[str]:
    """The Python production files the unit changed or added since `base_sha` (committed work, test files left out)."""
    done = wb.git.run("diff", "--name-only", "--no-renames", "--diff-filter=AM", base_sha, "HEAD", check=False)
    return sorted(p for p in done.stdout.splitlines() if p.endswith(".py") and not _is_test_path(wb, p))


def discriminate_extra(wb: Workbench, tests: Sequence[str], base_sha: str) -> ExtraRun:
    """Does a test that no red record covers look at the answer? Run 1: the project's functions answer their zero value
    (`zeroed_run`): a test that fails by assertion is accepted. Run 2, for the ones still passing: the unit's changed
    production files are swapped to the unit base (`red_code_in_place`): a test that fails there by assertion is
    accepted. Fail closed: in both runs an id counts as failing only when the report lists it as failed by assertion
    (`fails_on_zero`). An error at the base shows that the test reached the unit's new code (a module or a function the
    base does not have), not that it checked the answer (m1.11 review: a test with no assertion on the answer that only
    imports the new module failed there and was accepted); like a module that does not import at the base, a skipped
    id, an id the report lacks and a run that wrote no report, it is no proof. At most two gate runs, none when there is
    nothing to run."""
    wanted = sorted(set(tests))
    accepted: dict[str, str] = {}
    runs = 0
    scope = sorted(imported_modules(wb, wanted) | _changed_modules(wb))
    zero = zeroed_run(wb, "test-extra-zero", scope, public=True) if scope else None
    if zero is not None:
        runs += 1
        if zero.report is not None:
            accepted |= {t: PROOF_ZERO_VALUE for t in wanted if fails_on_zero(zero.report.tests.get(t))}
    rest = [t for t in wanted if t not in accepted]
    production = production_changes(wb, base_sha)
    if rest and production:
        runs += 1
        # a module the unit added is set aside at the base: its own tests then fail to import, and pytest would stop
        # the whole run at the first collection error; the others must still run, and those ids fail closed
        keep_going = {"PYTEST_ADDOPTS": "--continue-on-collection-errors"}
        at_base = run_with_code_of(wb, base_sha, production, name="test-extra-base", extra_env=keep_going)
        accepted |= {t: "base" for t in rest if fails_on_zero(at_base.get(t))}
        reasons = {
            t: ERROR_AT_BASE
            for t in rest
            if t not in accepted and t in at_base and at_base[t].status in ("failed", "error")
        }
    else:
        reasons = {}
    return ExtraRun(accepted, tuple(t for t in wanted if t not in accepted), runs, reasons)


def file_of_test(wb: Workbench, test_id: str) -> str | None:
    """The file of a test id of the report (`_test_file`)."""
    return _test_file(wb, test_id)
