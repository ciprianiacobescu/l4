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
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from l4.gates.collection import LOCATION, called_names, in_repository
from l4.gates.coverage import merge_pytest_env
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer import variant
from l4.implementer.stubs import _is_inside, has_stub, import_time_names, zero_value_plan
from l4.implementer.variant import VariantRun
from l4.implementer.workbench import Workbench
from l4.security.protected import glob_match

PROOF_ZERO_VALUE = "zero_value"
PROOF_PRE_SATISFIED = "pre_satisfied"
PROOF_RED_ASSERTION = "red_assertion"
VIA_NOT_APPLICABLE = "not_applicable"  # discrimination does not apply: the tests check a dependency (L4-IMP-062)
# every variant run goes on past a collection error (L4-IMP-060): a variant that breaks one module's import, or a base
# run that sets an added module aside, must not stop pytest before it runs the others (harmless for a gate that is not
# pytest: it ignores the variable)
KEEP_GOING = {"PYTEST_ADDOPTS": "--continue-on-collection-errors"}
_ROOTS = ("", "src")  # where an import is always looked up inside the repository
_PROJECT_FILES = ("pyproject.toml", "setup.py", "setup.cfg")  # their directory is an import root (L4-IMP-025)


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


MAX_KEEP_RERUNS = 2  # a zero-value run is made again at most twice, keeping the functions a traceback names
MAX_KEPT = 50  # functions kept real by tracebacks, per check


class ZeroScope(list[str]):
    """What `zero_values_in_place` yields: the paths that were varied (the list itself, and `varied`), the functions
    each answers a zero value for (`zeroed`) and the ones kept real because their annotation says they return a
    callable or a class (`kept`), both path -> qualnames."""

    def __init__(self, varied: Sequence[str] = (), zeroed: Mapping[str, tuple[str, ...]] | None = None,
                 kept: Mapping[str, tuple[str, ...]] | None = None) -> None:  # fmt: skip
        super().__init__(varied)
        self.zeroed: dict[str, tuple[str, ...]] = dict(zeroed or {})
        self.kept: dict[str, tuple[str, ...]] = dict(kept or {})

    @property
    def varied(self) -> list[str]:
        return list(self)


def _applied_names(wb: Workbench, paths: Sequence[str]) -> frozenset[str]:
    """The names the varied modules apply or call while they are imported (`import_time_names`), over all of them."""
    names: set[str] = set()
    for relative in paths:
        target = wb.worktree / relative
        if _is_inside(wb.worktree, target) and target.is_file():
            try:
                names |= import_time_names(target.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                continue
    return frozenset(names)


@contextmanager
def zero_values_in_place(
    wb: Workbench, paths: Sequence[str], *, public: bool, keep: Mapping[str, Collection[str]] | None = None
) -> Iterator[ZeroScope]:
    """Replace the zero-value variants of `paths` (relative to the worktree) for the duration of the block and
    yield the scope (the paths that were varied). `public`: every public function and method; else only the red
    stubs. `keep`: path -> qualnames of functions that stay real (L4-IMP-061)."""
    originals: dict[Path, bytes] = {}
    zeroed: dict[str, tuple[str, ...]] = {}
    kept: dict[str, tuple[str, ...]] = {}
    seen: set[tuple[int, int]] = set()
    applied = _applied_names(wb, paths) if public else frozenset()
    try:
        for relative in paths:
            target = wb.worktree / relative
            if not _is_inside(wb.worktree, target) or not target.is_file():
                continue  # a symlinked directory in the repo must not let the gate rewrite a file outside it
            if _already_varied(target, seen):
                continue  # a second name of a file already varied: its "original" would be the variant
            data = target.read_bytes()
            try:
                plan = zero_value_plan(
                    data.decode("utf-8"), public=public, keep=(keep or {}).get(relative, ()), applied=applied
                )
            except (SyntaxError, UnicodeDecodeError):
                continue
            originals[target] = data
            zeroed[relative], kept[relative] = plan.zeroed, plan.kept
            target.write_bytes(plan.source.encode("utf-8"))
            _drop_bytecode(target)
        yield ZeroScope([t.relative_to(wb.worktree).as_posix() for t in originals], zeroed, kept)
    finally:
        broken = []
        for target, data in originals.items():
            target.write_bytes(data)
            _drop_bytecode(target)
            if _digest(target.read_bytes()) != _digest(data):
                broken.append(target.name)
        if broken:
            raise RuntimeError(f"could not restore {', '.join(broken)} after the zero-value run")


def own_test_files(wb: Workbench) -> frozenset[str]:
    """The test and support files the unit added or changed: the worktree's changes and the commits since the unit
    base. A fixture assertion in one of them is the unit's own check of a production answer (L4-IMP-002)."""
    changed = set(wb.changed_files())
    base = unit_base(wb)
    if base is not None:
        done = wb.git.run("diff", "--name-only", "--no-renames", "--diff-filter=AM", base, "HEAD", check=False)
        changed |= set(done.stdout.splitlines())
    return frozenset(p for p in changed if _is_test_path(wb, p))


@dataclass(frozen=True)
class ZeroRun:
    gate: GateResult  # the last gate run
    run: VariantRun  # that run, classified against the real run
    kept: dict[str, tuple[str, ...]]  # path -> qualnames the tracebacks asked to keep real
    reruns: int
    own: frozenset[str] = frozenset()  # the test and support files the unit added or changed (D6)


def _inconclusive_texts(run: VariantRun, candidates: Collection[str], real: TestReport | None,
                        own: frozenset[str]) -> tuple[list[str], list[str]]:  # fmt: skip
    """What an inconclusive run shows of its cause: the tracebacks of its new collection errors and of the candidates'
    setup assertions outside the unit's files. Empty when no candidate is inconclusive."""
    if run.report is None:
        return [], []
    undecided = [t for t in candidates if variant.test_outcome(run, t, real, own)[0] == "inconclusive"]
    if not undecided:
        return [], []
    collection = [run.report.collection_details.get(e, "") for e in run.new_errors]
    setup = [
        case.detail
        for t in undecided
        if (case := run.report.tests.get(t)) is not None and case.when == "setup" and case.failure_kind == "assertion"
    ]
    return collection, setup


def zeroed_run(
    wb: Workbench,
    name: str,
    paths: Sequence[str],
    *,
    public: bool,
    real: TestReport | None = None,
    candidates: Collection[str] = (),
) -> ZeroRun | None:
    """The test gate against the variants, classified against `real`; None when no path could be varied (nothing to
    decide). Only in `public` mode: while a candidate is inconclusive and a run's tracebacks name zeroed functions,
    those are kept real and the run is made again, at most `MAX_KEEP_RERUNS` times (L4-IMP-061). The reports the gate
    writes are put back as run (a) left them: the published report must describe the real code, not the variants."""
    reports = [wb.worktree / r for r in wb.cfg.gates.test.reports]
    saved = {r: r.read_bytes() for r in reports if r.is_file() and not r.is_symlink()}
    keep: dict[str, tuple[str, ...]] = {}
    own = own_test_files(wb)
    reruns = 0
    try:
        while True:
            with zero_values_in_place(wb, paths, public=public, keep=keep) as scope:
                if not scope:
                    return None
                gate = wb.run_gate(
                    name, wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports, extra_env=KEEP_GOING
                )
            run = variant.classify(gate, real, redact=wb.redactor.redact_text)
            if reruns == 0 and any(scope.kept.values()):
                wb.emit("zero.kept", gate=name, rerun=0, cause="annotation", functions=_listed(scope.kept))
            result = ZeroRun(gate, run, dict(keep), reruns, own)
            if not public or reruns >= MAX_KEEP_RERUNS:
                return result
            collection, setup = _inconclusive_texts(run, candidates, real, own)
            from_collection = called_names("\n".join(collection)) | _failing_module_calls(wb, collection)
            from_setup = called_names("\n".join(setup))
            room = MAX_KEPT - sum(len(v) for v in keep.values())
            wanted = [
                (path, qual, qual.rsplit(".", 1)[-1] in from_collection)
                for path, quals in scope.zeroed.items()
                for qual in quals
                if qual.rsplit(".", 1)[-1] in from_collection | from_setup and qual not in keep.get(path, ())
            ][: max(room, 0)]
            if not wanted:
                return result
            for path, qual, _ in wanted:
                keep[path] = (*keep.get(path, ()), qual)
            reruns += 1
            cause = "collection" if any(by_collection for _, _, by_collection in wanted) else "setup"
            wb.emit("zero.kept", gate=name, rerun=reruns, cause=cause,
                    functions=[f"{path}::{qual}" for path, qual, _ in wanted])  # fmt: skip
    finally:
        for report in reports:
            if report in saved:
                report.write_bytes(saved[report])
            else:
                report.unlink(missing_ok=True)


def _failing_module_calls(wb: Workbench, tracebacks: Sequence[str]) -> frozenset[str]:
    """The names called by module-level statements of the production modules a collection traceback passes through: the
    failing line often reads a value an earlier statement computed (`_CFG = load()` then `RATE = _CFG["rate"]`)."""
    names: set[str] = set()
    for text in tracebacks:
        for line in text.splitlines():
            found = LOCATION.match(line.strip())
            if found is None or not in_repository(found.group("path")) or not found.group("path").endswith(".py"):
                continue
            relative = found.group("path")
            target = wb.worktree / relative
            if _is_test_path(wb, relative) or not _is_inside(wb.worktree, target) or not target.is_file():
                continue
            try:
                names |= import_time_names(target.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                continue
    return frozenset(names)


def _listed(by_path: Mapping[str, Sequence[str]]) -> list[str]:
    return [f"{path}::{qual}" for path, quals in by_path.items() for qual in quals][:MAX_KEPT]


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


@dataclass(frozen=True)
class AtRed:
    failing_not: list[str]  # the ids that do not fail by the code of the red commit
    inconclusive: str = ""  # the run could not decide (no report, no test executed): why


def fails_at_red(
    wb: Workbench,
    red_sha: str,
    ids: Sequence[str],
    paths: Sequence[str] | None = None,
    *,
    name: str = "test-at-red",
    extra_env: Mapping[str, str] | None = None,
    real: TestReport | None = None,
) -> AtRed:
    """Decision 7: the test gate runs against the red commit's production code with the corrected tests, and the ids of
    `ids` that do not fail there are returned: a corrected test that passes against the code the red phase started from
    no longer discriminates. Fail closed: an id counts as failing only when the report lists it as failed or error, so
    a skipped id and one the report does not hold (its module did not import the red code: a corrected test that
    imports a module only green added is no proof of anything) are returned. A run that wrote no report or ran no test
    decides nothing: `inconclusive` says why, and nothing is returned as failing_not (L4-IMP-060). The reports the
    gate writes are put back as the real run left them."""
    gate = run_with_code_of(wb, red_sha, paths, name=name, extra_env=extra_env)
    run = variant.classify(gate, real, redact=wb.redactor.redact_text)
    if run.reason:
        return AtRed([], run.reason)
    assert run.report is not None
    tests = run.report.tests
    return AtRed([i for i in ids if i not in tests or tests[i].status not in ("failed", "error")])


def run_with_code_of(
    wb: Workbench,
    sha: str,
    paths: Sequence[str] | None = None,
    *,
    name: str,
    extra_env: Mapping[str, str] | None = None,
) -> GateResult:
    """The test gate with the production files swapped to their content at `sha` (`red_code_in_place`), going on past
    collection errors; the gate result tells no report, no test and a missing id apart. The reports the gate writes
    are put back as the real run left them."""
    reports = [wb.worktree / r for r in wb.cfg.gates.test.reports]
    kept = {r: r.read_bytes() for r in reports if r.is_file() and not r.is_symlink()}
    try:
        with red_code_in_place(wb, sha, paths):
            gate = wb.run_gate(
                name,
                wb.cfg.gates.test.command,
                reports=wb.cfg.gates.test.reports,
                extra_env=merge_pytest_env(KEEP_GOING, extra_env or {}),
            )
    finally:
        for report in reports:
            if report in kept:
                report.write_bytes(kept[report])
            else:
                report.unlink(missing_ok=True)
    return gate


@dataclass(frozen=True)
class Vacuity:
    proofs: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> tests that fail on the zero values
    vacuous: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> its tests, none of which does
    reason: str = ""  # run (b) could not decide
    inconclusive: dict[str, str] = field(default_factory=dict)  # criterion -> why the run did not decide it

    @property
    def message(self) -> str:
        if self.reason:
            return self.reason
        parts = [
            f"{criterion} (its tests pass or error against the zero-value stubs: {', '.join(tests[:5])}); "
            "a test must fail by assertion on the answer (for an object, assert `result is not None` or isinstance "
            "first, then on its attributes; for a context manager, which then yields the zero value, assert on what "
            "it yields, `with f() as x: assert x is not None`, or on its effects after the block)"
            + self._zero_answer_remedy(criterion)
            for criterion, tests in sorted(self.vacuous.items())
        ]
        text = "vacuous: " + "; ".join(parts) if parts else ""
        if self.inconclusive:
            listed = ", ".join(f"{c} ({why})" for c, why in sorted(self.inconclusive.items()))
            text = f"{text}; inconclusive: {listed}" if text else f"inconclusive: {listed}"
        return text

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


def vacuity_check(
    wb: Workbench, stub_files: Sequence[str], tracing: Mapping[str, Sequence[str]], *, real: TestReport | None = None
) -> Vacuity:
    """Run (b): with the red stubs answering their zero value, each criterion in `tracing` (criterion -> the new
    tests that trace it, pre-satisfied ones left out) needs one test that fails by assertion. A test the run did not
    run is inconclusive, never vacuous (L4-IMP-060)."""
    if not tracing:
        return Vacuity()
    candidates = sorted({t for tests in tracing.values() for t in tests})
    zero = zeroed_run(wb, "test-zero", stub_files, public=False, real=real, candidates=candidates)
    if zero is None:
        return Vacuity(reason="the zero-value run produced no readable report (no stub)")
    proofs: dict[str, tuple[str, ...]] = {}
    vacuous: dict[str, tuple[str, ...]] = {}
    inconclusive: dict[str, str] = {}
    for criterion, result in variant.judge(zero.run, tracing, real, zero.own, redact=wb.redactor.redact_text).items():
        if result.state == "confirmed":
            proofs[criterion] = result.tests
        elif result.state == "refuted":
            vacuous[criterion] = result.tests
        else:
            inconclusive[criterion] = result.reason
    return Vacuity(proofs, vacuous, inconclusive=inconclusive)


# --- pre-satisfied criteria (M13-G3) ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class PreSatisfied:
    confirmed: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> tests that discriminate
    unconfirmed: dict[str, tuple[str, ...]] = field(default_factory=dict)  # refuted: the run showed no test does
    reason: str = ""
    inconclusive: dict[str, str] = field(default_factory=dict)  # criterion -> why the run could not decide it
    not_applicable: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> its dependency-only tests
    kept: dict[str, tuple[str, ...]] = field(default_factory=dict)  # path -> functions the run kept real
    reruns: int = 0

    @property
    def message(self) -> str:
        parts = []
        if self.unconfirmed:
            listed = ", ".join(sorted(self.unconfirmed))
            why = self.reason or (
                "its tests still pass, or fail by an error rather than an assertion, "
                "when the functions they use answer the zero value"
            )
            parts.append(f"not discriminating: {listed} ({why})")
        if self.inconclusive:
            parts.append("inconclusive: " + ", ".join(f"{c} ({why})" for c, why in sorted(self.inconclusive.items())))
        return "; ".join(parts)


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


def import_roots(wb: Workbench) -> tuple[str, ...]:
    """Where an import is looked up inside the repository (L4-IMP-025): the root and `src`, every directory named
    `src`, and every directory holding a project file (`pyproject.toml`, `setup.py`, `setup.cfg`) together with its
    `src`, so that a workspace member's `packages/<name>/src/<package>` and a flat member's `packages/<name>/<package>`
    are found. The paths come from git (tracked, and untracked but not ignored), so an ignored virtual environment's
    copy of a package is not the project's source."""
    listed = wb.git.run("ls-files", "-z", "--cached", "--others", "--exclude-standard", check=False).stdout
    roots = set(_ROOTS)
    for path in filter(None, listed.split("\0")):
        parts = path.split("/")
        if parts[-1] in _PROJECT_FILES:
            parent = "/".join(parts[:-1])
            roots |= {parent, f"{parent}/src" if parent else "src"}
        roots |= {"/".join(parts[: i + 1]) for i, part in enumerate(parts[:-1]) if part == "src"}
    return tuple(sorted(roots, key=lambda root: (root.count("/") + bool(root), root)))


def _resolve(wb: Workbench, dotted: str, roots: Sequence[str] = _ROOTS) -> list[str]:
    """Every file under one of `roots` that `dotted` names: Python takes the first on its path, which the harness
    cannot know, and varying a copy the test does not import changes nothing."""
    path = dotted.replace(".", "/")
    found = []
    for root in roots:
        for candidate in (f"{path}.py", f"{path}/__init__.py"):
            relative = f"{root}/{candidate}" if root else candidate
            target = wb.worktree / relative
            if target.is_file() and _is_inside(wb.worktree, target) and _exact_case(wb.worktree, relative):
                found.append(relative)
    return found


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
    if not pending:
        return set()
    roots = import_roots(wb)
    found: set[str] = set()
    seen: set[str] = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        for dotted in _imports(wb, current):
            for resolved in _resolve(wb, dotted, roots):
                if _is_test_path(wb, resolved):
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


def _criterion_texts(wb: Workbench) -> dict[str, str]:
    """criterion id -> its text (alias and scenario): what a dependency check must name (L4-IMP-062)."""
    try:
        return {c.id: f"{c.alias} {c.text}" for c in wb.provider.criteria(wb.ref)}
    except Exception:  # noqa: BLE001 - a spec that cannot be read gives no criterion text: nothing is not applicable
        return {}


def confirm_pre_satisfied(
    wb: Workbench, candidates: Mapping[str, Sequence[str]], *, real: TestReport | None = None
) -> PreSatisfied:
    """`candidates`: criterion -> its new tests, all of which passed in run (a) (`real`). With every public function of
    the modules those tests import, and of the modules changed since the unit base, answering its zero value, at least
    one of a criterion's tests must fail by assertion, otherwise the criterion is not discriminating (refuted). A run
    that could not run the tests decides nothing: the criterion is inconclusive (L4-IMP-060). A criterion whose every
    test checks a dependency and no project code is not applicable (L4-IMP-062)."""
    from l4.implementer.depcheck import dependency_only

    if not candidates:
        return PreSatisfied()
    roots = import_roots(wb)
    texts = _criterion_texts(wb)
    not_applicable = {
        c: tuple(t)
        for c, t in candidates.items()
        if t and c in texts and all(dependency_only(wb, i, roots, texts[c]) for i in t)
    }
    rest = {c: tuple(t) for c, t in candidates.items() if c not in not_applicable}
    if not rest:
        return PreSatisfied(not_applicable=not_applicable)
    everything = sorted({t for tests in rest.values() for t in tests})
    scope = sorted(imported_modules(wb, everything) | _changed_modules(wb))
    if not scope:
        return PreSatisfied(
            {}, rest, "no project source module is imported by those tests", not_applicable=not_applicable
        )
    zero = zeroed_run(wb, "test-presatisfied", scope, public=True, real=real, candidates=everything)
    if zero is None:
        return PreSatisfied(
            {},
            rest,
            "the zero-value run produced no readable report (nothing to vary)",
            not_applicable=not_applicable,
        )
    confirmed: dict[str, tuple[str, ...]] = {}
    refuted: dict[str, tuple[str, ...]] = {}
    inconclusive: dict[str, str] = {}
    for criterion, result in variant.judge(zero.run, rest, real, zero.own, redact=wb.redactor.redact_text).items():
        if result.state == "confirmed":
            confirmed[criterion] = result.tests
        elif result.state == "refuted":
            refuted[criterion] = result.tests
        else:
            inconclusive[criterion] = result.reason
    return PreSatisfied(confirmed, refuted, "", inconclusive, not_applicable, dict(zero.kept), zero.reruns)


# --- tests no red record covers (M1.11 W6, decision 8) -------------------------------------------------------------


@dataclass(frozen=True)
class ExtraRun:
    """The verifier's decision on tests that people or a test chore wrote: `accepted` maps a test id to `zero_value` (it
    failed by assertion when the project's functions answered their zero value) or `base` (it failed by assertion
    against the unit base's production code); `rejected` are the ids that did neither; `reasons` say why a rejected id
    that did fail on the base is no proof; `inconclusive` are the rejected ids a run could not decide (their module did
    not import there, no test ran), with why (L4-VER-050); `runs` is the number of gate runs made (the zero-value run
    and its keep reruns, and the run on the base: at most four)."""

    accepted: dict[str, str] = field(default_factory=dict)
    rejected: tuple[str, ...] = ()
    runs: int = 0
    reasons: dict[str, str] = field(default_factory=dict)
    inconclusive: dict[str, str] = field(default_factory=dict)


ERROR_AT_BASE = "fails on the base only with an error, not by assertion"


def production_changes(wb: Workbench, base_sha: str) -> list[str]:
    """The Python production files the unit changed or added since `base_sha` (committed work, test files left out)."""
    done = wb.git.run("diff", "--name-only", "--no-renames", "--diff-filter=AM", base_sha, "HEAD", check=False)
    return sorted(p for p in done.stdout.splitlines() if p.endswith(".py") and not _is_test_path(wb, p))


def discriminate_extra(
    wb: Workbench, tests: Sequence[str], base_sha: str, *, real: TestReport | None = None
) -> ExtraRun:
    """Does a test that no red record covers look at the answer? Run 1: the project's functions answer their zero value
    (`zeroed_run`): a test that fails by assertion is accepted. Run 2, for the ones still passing: the unit's changed
    production files are swapped to the unit base (`red_code_in_place`): a test that fails there by assertion is
    accepted. Both runs are classified against `real` (L4-IMP-060): an error at the base shows that the test reached
    the unit's new code (a module or a function the base does not have), not that it checked the answer (m1.11 review:
    a test with no assertion on the answer that only imports the new module failed there and was accepted), so it is
    no proof; a test a run could not run (its module did not import, no test executed, no report) is `inconclusive`
    when the zero-value run could not decide it and the base run did not accept it, and is no proof otherwise. At most
    two gate runs and two keep reruns of the first, none when there is nothing to run."""
    wanted = sorted(set(tests))
    accepted: dict[str, str] = {}
    undecided: dict[str, str] = {}
    runs = 0
    redact = wb.redactor.redact_text
    scope = sorted(imported_modules(wb, wanted) | _changed_modules(wb))
    zero = zeroed_run(wb, "test-extra-zero", scope, public=True, real=real, candidates=wanted) if scope else None
    own = zero.own if zero is not None else own_test_files(wb)
    if zero is not None:
        runs += 1 + zero.reruns
        for test in wanted:
            outcome, why = variant.test_outcome(zero.run, test, real, own, redact=redact)
            if outcome == "proof":
                accepted[test] = PROOF_ZERO_VALUE
            elif outcome == "inconclusive":
                undecided[test] = why
    rest = [t for t in wanted if t not in accepted]
    production = production_changes(wb, base_sha)
    reasons: dict[str, str] = {}
    if rest and production:
        runs += 1
        # a module the unit added is set aside at the base: its own tests then fail to import; the others must still
        # run (run_with_code_of goes on past collection errors), and those ids are not proofs
        base = variant.classify(run_with_code_of(wb, base_sha, production, name="test-extra-base"), real, redact=redact)
        for test in rest:
            outcome, _ = variant.test_outcome(base, test, real, own, redact=redact, zero_value=False)
            case = base.report.tests.get(test) if base.report is not None else None
            if outcome == "proof":
                accepted[test] = "base"
            elif case is not None and case.status in ("failed", "error"):
                reasons[test] = ERROR_AT_BASE
    inconclusive = {t: why for t, why in undecided.items() if t not in accepted}
    reasons = {t: why for t, why in reasons.items() if t not in inconclusive}
    return ExtraRun(accepted, tuple(t for t in wanted if t not in accepted), runs, reasons, inconclusive)


def file_of_test(wb: Workbench, test_id: str) -> str | None:
    """The file of a test id of the report (`_test_file`)."""
    return _test_file(wb, test_id)
