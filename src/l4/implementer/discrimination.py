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
import re
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from l4.fsutil import (
    LinkedPath,
    UnsafeFile,
    linked_component,
    read_inside,
    unlink_inside,
    unlink_matching_inside,
    write_inside,
)
from l4.gates.collection import LOCATION, called_names, deepest_location, in_repository
from l4.gates.coverage import merge_pytest_env
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer import variant
from l4.implementer.result import tag_example
from l4.implementer.stubs import _is_inside, has_stub, import_time_names, zero_value_plan
from l4.implementer.test_locate import file_of_id
from l4.implementer.variant import VariantRun
from l4.implementer.workbench import Workbench
from l4.security.protected import glob_match
from l4.specs.criteria import trace_ids
from l4.vcs.git import GitError

PROOF_ZERO_VALUE = "zero_value"
PROOF_PRE_SATISFIED = "pre_satisfied"
PROOF_RED_ASSERTION = "red_assertion"
VIA_NOT_APPLICABLE = (
    "not_applicable"  # read in old ledgers only; since round 3 nothing writes it as a pass (L4-IMP-062)
)
NO_PROJECT_IMPORT = "its tests import no project module: the zero-value check cannot judge them"
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


def _drop_bytecode(root: Path, rel: str) -> None:
    """A cached `.pyc` is validated by the source's mtime (in seconds) and size: a variant of the same size written
    within the second of the original could be served the original's bytecode. Works on directory descriptors
    (L4-SEC-020): a `__pycache__` that is a link is removed itself, and no `.pyc` outside the worktree is touched."""
    parent, _, name = rel.rpartition("/")
    cache = f"{parent}/__pycache__" if parent else "__pycache__"
    unlink_matching_inside(root, cache, f"{Path(name).stem}.*.pyc")


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


MAX_VARIED_BYTES = 8 * 1024 * 1024  # a source file or a report the harness varies, keeps or puts back


def _canonical(wb: Workbench, relative: str) -> str | None:
    """The real path inside the worktree of a file the harness varies, resolved before the gate (L4-SEC-020 part c): a
    link that the repository itself holds is followed now and never after the gate. None: the real path is outside the
    worktree, under the test or test-support globs, or not a regular file."""
    try:
        real = (wb.worktree / relative).resolve()
        rel = real.relative_to(wb.worktree.resolve()).as_posix()
    except (OSError, ValueError, RuntimeError):
        return None
    if rel in ("", ".") or not real.is_file() or _is_test_path(wb, rel):
        return None
    return rel


def _put(wb: Workbench, rel: str, data: bytes, mode: int | None, where: str) -> bool:
    """Write `data` over `rel` without following a link (D3). A planted link is removed and recorded, and the write is
    made once more into a real directory. A link as the last component is checked first: the rename in `write_inside`
    would replace it silently, and a plant must be recorded like every other. Nothing is raised: this runs in
    `finally` blocks."""
    if (link := linked_component(wb.worktree, rel)) is not None:
        wb.refused_write(LinkedPath(link), path=rel, where=where)
    try:
        write_inside(wb.worktree, rel, data, mode=mode)
        return True
    except LinkedPath as exc:
        wb.refused_write(exc, path=rel, where=where)
    except (UnsafeFile, OSError, ValueError) as exc:
        wb.refused_write(exc if isinstance(exc, UnsafeFile) else UnsafeFile(str(exc)), path=rel, where=where)
        return False
    try:
        write_inside(wb.worktree, rel, data, mode=mode)
        return True
    except (UnsafeFile, OSError, ValueError) as again:
        wb.refused_write(again if isinstance(again, UnsafeFile) else UnsafeFile(str(again)), path=rel, where=where)
        return False


def _unlink(wb: Workbench, rel: str, where: str) -> None:
    try:
        unlink_inside(wb.worktree, rel)
    except (UnsafeFile, OSError, ValueError) as exc:
        wb.refused_write(exc if isinstance(exc, UnsafeFile) else UnsafeFile(str(exc)), path=rel, where=where)


def _read(wb: Workbench, rel: str, where: str | None = None) -> tuple[bytes, int] | None:
    """(bytes, mode) of a regular file below the worktree, or None when it is absent, too large or not a regular file.
    With `where`, a refusal is recorded (the file is one the harness has to put back)."""
    try:
        return read_inside(wb.worktree, rel, limit=MAX_VARIED_BYTES)
    except (UnsafeFile, OSError, ValueError) as exc:
        if where is not None:
            wb.refused_write(exc if isinstance(exc, UnsafeFile) else UnsafeFile(str(exc)), path=rel, where=where)
        return None


def _restore(wb: Workbench, originals: Mapping[str, tuple[bytes, int]], where: str) -> None:
    """Put every original back and check it by sha256, reading through the same no-follow walk. A mismatch is
    `restore failed`, never an exception."""
    for rel, (data, mode) in originals.items():
        put = _put(wb, rel, data, mode, where)
        _drop_bytecode(wb.worktree, rel)
        if not put:
            continue  # the refusal is recorded already
        back = _read(wb, rel)
        if back is None or _digest(back[0]) != _digest(data):
            wb.refused_write(UnsafeFile(f"{rel} differs after the restore"), path=rel, where=where)


def _applied_names(wb: Workbench, paths: Sequence[str]) -> frozenset[str]:
    """The names the varied modules apply or call while they are imported (`import_time_names`), over all of them."""
    names: set[str] = set()
    for relative in paths:
        rel = _canonical(wb, relative)
        read = _read(wb, rel) if rel is not None else None
        if read is not None:
            try:
                names |= import_time_names(read[0].decode("utf-8"))
            except UnicodeDecodeError:
                continue
    return frozenset(names)


@contextmanager
def zero_values_in_place(
    wb: Workbench,
    paths: Sequence[str],
    *,
    public: bool,
    keep: Mapping[str, Collection[str]] | None = None,
    annotation: bool = True,
    where: str = "zero-value run",
) -> Iterator[ZeroScope]:
    """Replace the zero-value variants of `paths` (relative to the worktree) for the duration of the block and
    yield the scope (the paths that were varied). `public`: every public function and method; else only the red
    stubs. `keep`: path -> qualnames of functions that stay real (L4-IMP-061); `annotation` False leaves out the keep of
    callable-returning functions the varied modules apply at import time. Every target is taken by its real path inside
    the worktree, resolved before the gate (L4-SEC-020 part c)."""
    originals: dict[str, tuple[bytes, int]] = {}
    zeroed: dict[str, tuple[str, ...]] = {}
    kept: dict[str, tuple[str, ...]] = {}
    seen: set[tuple[int, int]] = set()
    applied = _applied_names(wb, paths) if public and annotation else frozenset()
    try:
        for relative in paths:
            rel = _canonical(wb, relative)
            if rel is None or rel in originals:
                continue  # outside the worktree, a test file, not a file; or a second spelling of one already varied
            if _already_varied(wb.worktree / rel, seen):
                continue  # a second name of a file already varied: its "original" would be the variant
            read = _read(wb, rel)
            if read is None:
                continue
            data, mode = read
            try:
                plan = zero_value_plan(
                    data.decode("utf-8"), public=public, keep=(keep or {}).get(relative, ()), applied=applied
                )
            except (SyntaxError, UnicodeDecodeError):
                continue
            originals[rel] = (data, mode)
            zeroed[relative], kept[relative] = plan.zeroed, plan.kept
            _put(wb, rel, plan.source.encode("utf-8"), mode, where)
            _drop_bytecode(wb.worktree, rel)
        yield ZeroScope(list(originals), zeroed, kept)
    finally:
        _restore(wb, originals, where)


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
    proved: frozenset[str] = (
        frozenset()
    )  # candidates that failed by assertion in ANY pass (H1: more code zeroed still proves)


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


def _keep_reports(wb: Workbench, where: str) -> dict[str, tuple[bytes, int]]:
    kept: dict[str, tuple[bytes, int]] = {}
    for rel in wb.cfg.gates.test.reports:
        if (got := _read(wb, rel, where)) is not None:
            kept[rel] = got
    return kept


def _put_reports_back(wb: Workbench, kept: Mapping[str, tuple[bytes, int]], where: str) -> None:
    for rel in wb.cfg.gates.test.reports:
        if rel in kept:
            _put(wb, rel, kept[rel][0], kept[rel][1], where)
        else:
            _unlink(wb, rel, where)


def zeroed_run(
    wb: Workbench,
    name: str,
    paths: Sequence[str],
    *,
    public: bool,
    real: TestReport | None = None,
    candidates: Collection[str] = (),
    extra_env: Mapping[str, str] | None = None,
) -> ZeroRun | None:
    """The test gate against the variants, classified against `real`; None when no path could be varied (nothing to
    decide). Only in `public` mode: while a candidate is inconclusive and a run's tracebacks name zeroed functions,
    those are kept real and the run is made again, at most `MAX_KEEP_RERUNS` times (L4-IMP-061). The reports the gate
    writes are put back as run (a) left them: the published report must describe the real code, not the variants."""
    saved = _keep_reports(wb, name)
    keep: dict[str, tuple[str, ...]] = {}
    own = own_test_files(wb)
    reruns = 0
    proved: set[str] = set()
    annotation_kept = False
    try:
        while True:
            with zero_values_in_place(wb, paths, public=public, keep=keep, where=name) as scope:
                if not scope:
                    return None
                gate = wb.run_gate(
                    name,
                    wb.cfg.gates.test.command,
                    reports=wb.cfg.gates.test.reports,
                    extra_env=merge_pytest_env(KEEP_GOING, extra_env or {}),
                )
            run = variant.classify(gate, real, redact=wb.redactor.redact_text)
            if reruns == 0 and any(scope.kept.values()):
                annotation_kept = True
                wb.emit("zero.kept", gate=name, rerun=0, cause="annotation", functions=_listed(scope.kept))
            proved |= _proofs(run, candidates, real, own)
            result = ZeroRun(gate, run, dict(keep), reruns, own, frozenset(proved))
            if not public or reruns >= MAX_KEEP_RERUNS:
                return _with_plain_pass(wb, name, paths, real, candidates, own, result, annotation_kept)
            collection, setup = _inconclusive_texts(run, candidates, real, own)
            from_collection = called_names("\n".join(collection)) | _failing_module_calls(wb, collection, own)
            from_setup = called_names("\n".join(setup))
            room = MAX_KEPT - sum(len(v) for v in keep.values())
            wanted = [
                (path, qual, qual.rsplit(".", 1)[-1] in from_collection)
                for path, quals in scope.zeroed.items()
                for qual in quals
                if qual.rsplit(".", 1)[-1] in from_collection | from_setup and qual not in keep.get(path, ())
            ][: max(room, 0)]
            if not wanted:
                return _with_plain_pass(wb, name, paths, real, candidates, own, result, annotation_kept)
            for path, qual, _ in wanted:
                keep[path] = (*keep.get(path, ()), qual)
            reruns += 1
            cause = "collection" if any(by_collection for _, _, by_collection in wanted) else "setup"
            wb.emit("zero.kept", gate=name, rerun=reruns, cause=cause,
                    functions=[f"{path}::{qual}" for path, qual, _ in wanted])  # fmt: skip
    finally:
        _put_reports_back(wb, saved, name)


def _proofs(run: VariantRun, candidates: Collection[str], real: TestReport | None, own: frozenset[str]) -> set[str]:
    return {t for t in candidates if variant.test_outcome(run, t, real, own)[0] == "proof"}


def _with_plain_pass(wb: Workbench, name: str, paths: Sequence[str], real: TestReport | None,
                     candidates: Collection[str], own: frozenset[str], result: ZeroRun,
                     annotation_kept: bool) -> ZeroRun:  # fmt: skip
    """H1: a function kept real because its annotation says it returns a callable and a varied module applies it can
    be the very subject of a candidate (a decorator factory under test). While a candidate has no proof and the first
    pass kept something by annotation, one more pass with nothing kept by annotation counts for the proofs only: a
    test that fails by assertion with more code zeroed is still a zero-value failure, as in 0.4.15."""
    if not annotation_kept or all(t in result.proved for t in candidates):
        return result
    with zero_values_in_place(wb, paths, public=True, keep=result.kept, annotation=False, where=name) as scope:
        if not scope:
            return result
        gate = wb.run_gate(name, wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports, extra_env=KEEP_GOING)
    run = variant.classify(gate, real, redact=wb.redactor.redact_text)
    proved = result.proved | _proofs(run, candidates, real, own)
    return ZeroRun(result.gate, result.run, result.kept, result.reruns, own, frozenset(proved))


def _failing_module_calls(
    wb: Workbench, tracebacks: Sequence[str], own: frozenset[str] = frozenset()
) -> frozenset[str]:
    """The names called by module-level statements of the modules a collection traceback passes through, production and
    pre-existing test-support modules alike but not the unit's own files (`own`): the failing line often reads a value
    an earlier statement computed (`_CFG = load()` then `RATE = _CFG["rate"]`)."""
    names: set[str] = set()
    for text in tracebacks:
        for line in text.splitlines():
            found = LOCATION.match(line.strip())
            if found is None or not in_repository(found.group("path")) or not found.group("path").endswith(".py"):
                continue
            relative = found.group("path")
            read = _read(wb, relative) if relative not in own else None  # a read only: test-support modules are fine
            if read is None:
                continue
            try:
                names |= import_time_names(read[0].decode("utf-8"))
            except UnicodeDecodeError:
                continue
    return frozenset(names)


def _listed(by_path: Mapping[str, Sequence[str]]) -> list[str]:
    return [f"{path}::{qual}" for path, quals in by_path.items() for qual in quals][:MAX_KEPT]


@contextmanager
def red_code_in_place(
    wb: Workbench, red_sha: str, paths: Sequence[str] | None = None, *, where: str = "run at the red code"
) -> Iterator[list[str]]:
    """The production files green changed are swapped to their content at the red commit for the duration of the block,
    and put back with a sha256 check (the pattern of `zero_values_in_place`, D7). A module green added has no red
    version: it is set aside. Test and support files are not touched, the corrected test stays as it is. Yields the
    paths that were swapped or set aside. `paths` (M1.11, the verifier's step 4): swap these files to `red_sha`
    instead of the files the worktree has changed since HEAD, which is none when the verifier looks at a commit."""
    ledger = wb.ledger_rel
    originals: dict[str, tuple[bytes, int]] = {}
    seen: set[tuple[int, int]] = set()
    try:
        for relative in sorted(wb.changed_files() if paths is None else paths):
            if relative == ledger or relative.startswith((".l4-out/", ".l4/")):
                continue
            rel = _canonical(wb, relative)  # a deleted file stays deleted; a test file is not touched
            if rel is None or rel == ledger or rel.startswith((".l4-out/", ".l4/")) or rel in originals:
                continue
            if _already_varied(wb.worktree / rel, seen):
                continue
            read = _read(wb, rel)
            if read is None:
                continue
            exists_at_red = wb.git.run("cat-file", "-e", f"{red_sha}:{rel}", check=False).returncode == 0
            originals[rel] = read
            if exists_at_red:
                _put(wb, rel, wb.git.run_bytes("show", f"{red_sha}:{rel}"), read[1], where)
            else:
                _unlink(wb, rel, where)
            _drop_bytecode(wb.worktree, rel)
        yield list(originals)
    finally:
        _restore(wb, originals, where)


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
    kept = _keep_reports(wb, name)
    try:
        with red_code_in_place(wb, sha, paths, where=name):
            gate = wb.run_gate(
                name,
                wb.cfg.gates.test.command,
                reports=wb.cfg.gates.test.reports,
                extra_env=merge_pytest_env(KEEP_GOING, extra_env or {}),
            )
    finally:
        _put_reports_back(wb, kept, name)
    return gate


@dataclass(frozen=True)
class Vacuity:
    proofs: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> tests that fail on the zero values
    vacuous: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> its tests, none of which does
    reason: str = ""  # run (b) could not decide
    inconclusive: dict[str, str] = field(default_factory=dict)  # criterion -> why the run did not decide it
    traced: dict[str, tuple[str, ...]] = field(default_factory=dict)  # test -> the unit's criteria it traces, sorted
    cap: int = 3  # `verifier.max_criteria_per_test`: a test with that many ids has no room for another
    test_command: str = "pytest"  # the test gate's command: it decides the form of the tag in the example
    # criterion -> the remedy for a vacuous criterion all of whose tests errored in the zero-value run (L4-IMP-085)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def message(self) -> str:
        if self.reason:
            return self.reason
        parts = [
            f"{criterion} (its tests pass or error against the zero-value stubs: {', '.join(tests[:5])}); "
            + (
                self.errors[criterion]
                if criterion in self.errors
                else "a test must fail by assertion on the answer (for an object, assert `result is not None` or "
                "isinstance first, then on its attributes; for a context manager, which then yields the zero value, "
                "assert on what it yields, `with f() as x: assert x is not None`, or on its effects after the block)"
                + self._zero_answer_remedy(criterion)
            )
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
        proved = [(c, t) for c, tests in sorted(self.proofs.items()) if c != criterion for t in sorted(tests)]
        roomy = [
            (test, ids)
            for c, test in proved
            if criterion not in (ids := self.traced.get(test, (c,))) and len(ids) < self.cap
        ]  # L4-VER-053: never advise an id that puts a test over the cap
        if roomy:
            test, ids = roomy[0]
            text += (
                f", or tag a test that asserts a real answer with {criterion} as well, for example "
                f"{test}: {tag_example(self.test_command, [*ids, criterion])}"
            )
        elif proved:
            text += (
                f", or write a new test that asserts a real answer and tag it with {criterion} alone "
                f"(every test that failed on the zero values already carries {self.cap} ids)"
            )
        return text


_NO_MODULE = re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'")
_NO_NAME = re.compile(r"ImportError: cannot import name '\w+' from '([\w.]+)'")
_NO_ATTRIBUTE = re.compile(r"AttributeError: .*?has no attribute '(\w+)'")


def _in_worktree(wb: Workbench, module: str) -> bool:
    """The dotted module is a file of the worktree, or would be: its first part is a package directory (or a module)
    of the worktree, or of one of the configured module roots."""
    first = module.split(".")[0]
    roots = ("", *wb.cfg.verifier.evidence.module_roots)
    return any(
        (wb.worktree / root / first).is_dir() or (wb.worktree / root / f"{first}.py").is_file() for root in roots
    )


def _worktree_file(wb: Workbench, path: str) -> str | None:
    """`path` of a traceback frame as a repository-relative path of an existing file of the worktree, else None."""
    candidate = Path(path)
    try:
        relative = candidate.relative_to(wb.worktree) if candidate.is_absolute() else candidate
    except ValueError:
        return None
    return relative.as_posix() if ".." not in relative.parts and (wb.worktree / relative).is_file() else None


def _error_remedy(wb: Workbench, text: str) -> str | None:
    """The remedy that the first matching rule of D5 gives for one test's error text, else None."""
    if (found := _NO_MODULE.search(text) or _NO_NAME.search(text)) and _in_worktree(wb, found.group(1)):
        return (
            f"its tests cannot import {found.group(1)}: create it in this red step with signature-only stubs (a body "
            "that is only raise NotImplementedError), and the harness answers them with zero values"
        )
    if "NotImplementedError" in text and (where := deepest_location(text)) is not None:
        path = _worktree_file(wb, where[0])
        if path is not None:
            return (
                f"its tests stop with NotImplementedError at {path}:{where[1]}: that body is not a stub the "
                "zero-value run answers; make it one (only raise NotImplementedError) or stub what the tests call in "
                "this red step"
            )
    if found := _NO_ATTRIBUTE.search(text):
        name = found.group(1)
        return f"its tests stop with AttributeError ({name}): add {name} as a signature-only stub in this red step"
    return None


def _error_texts(report: TestReport, tests: Sequence[str]) -> list[str] | None:
    """The error text of each of `tests` in the zero-value run, or None when one of them did not error: it passed, was
    skipped or failed by assertion (then the criterion is vacuous for another reason). A test the report lacks has the
    text of its module's collection error."""
    texts: list[str] = []
    for test in tests:
        case = report.tests.get(test)
        if case is not None:
            if case.status not in ("failed", "error") or case.failure_kind == "assertion":
                return None
            texts.append(f"{case.message}\n{case.detail}")
            continue
        names = variant._module_names(test)
        error = next((e for e in report.collection_errors if variant._error_name(e) in names), None)
        if error is None:
            return None
        texts.append(report.collection_details.get(error, ""))
    return texts


def error_remedies(wb: Workbench, report: TestReport, vacuous: Mapping[str, Sequence[str]]) -> dict[str, str]:
    """criterion -> the remedy (L4-IMP-085) for each vacuous criterion all of whose tests errored in the zero-value run
    `report`. The rules are tried in order over the tests' errors: a module that cannot be imported, a
    `NotImplementedError` raised in a file of the worktree, an `AttributeError` for a missing attribute."""
    found: dict[str, str] = {}
    for criterion, tests in vacuous.items():
        texts = _error_texts(report, tests)
        if not texts:
            continue
        remedies = [r for text in texts if (r := _error_remedy(wb, text)) is not None]
        if remedies:
            found[criterion] = remedies[0]
    return found


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
    for criterion, result in variant.judge(
        zero.run, tracing, real, zero.own, redact=wb.redactor.redact_text, proved=zero.proved
    ).items():
        if result.state == "confirmed":
            proofs[criterion] = result.tests
        elif result.state == "refuted":
            vacuous[criterion] = result.tests
        else:
            inconclusive[criterion] = result.reason
    known = {c.id for c in wb.provider.criteria(wb.ref)}
    traced = {
        test: tuple(sorted(trace_ids(real.tests[test]) & known))
        for tests in proofs.values()
        for test in tests
        if real is not None and test in real.tests
    }
    errors = error_remedies(wb, zero.run.report, vacuous) if vacuous and zero.run.report is not None else {}
    return Vacuity(
        proofs, vacuous, inconclusive=inconclusive, traced=traced, cap=wb.cfg.verifier.max_criteria_per_test,
        test_command=wb.cfg.gates.test.command, errors=errors,
    )  # fmt: skip


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
    earlier task's leftover): run (b) zeroes these along with the stubs red added (L4-IMP-084)."""
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
    wb: Workbench,
    candidates: Mapping[str, Sequence[str]],
    *,
    real: TestReport | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> PreSatisfied:
    """`candidates`: criterion -> its new tests, all of which passed in run (a) (`real`). With every public function of
    the modules those tests import, and of the modules changed since the unit base, answering its zero value, at least
    one of a criterion's tests must fail by assertion, otherwise the criterion is not discriminating (refuted). A run
    that could not run the tests decides nothing: the criterion is inconclusive (L4-IMP-060). A criterion whose every
    test checks a dependency and no project code is held with a harness question, never passed (L4-IMP-062)."""
    from l4.implementer.depcheck import dependency_only

    if not candidates:
        return PreSatisfied()
    roots = import_roots(wb)
    texts = _criterion_texts(wb)
    # Round 3: `dependency_only` is only a CLASSIFIER, never a safety rule. A criterion whose every test it accepts goes
    # to a person (inconclusive: the existing hold with a `harness` question); every other criterion with no project
    # import is refuted as on 0.4.15. Neither outcome is a pass, so the heuristic's precision decides which message a
    # person sees, not whether an agent's test is believed. Nothing is ever recorded `not_applicable` any more.
    dependency = {
        c: NO_PROJECT_IMPORT
        for c, t in candidates.items()
        if t and c in texts and all(dependency_only(wb, i, roots, texts[c]) for i in t)
    }
    rest = {c: tuple(t) for c, t in candidates.items() if c not in dependency}
    if not rest:
        return PreSatisfied(inconclusive=dependency)
    everything = sorted({t for tests in rest.values() for t in tests})
    scope = sorted(imported_modules(wb, everything) | _changed_modules(wb))
    if not scope:
        return PreSatisfied({}, rest, "no project source module is imported by those tests", inconclusive=dependency)
    zero = zeroed_run(
        wb, "test-presatisfied", scope, public=True, real=real, candidates=everything, extra_env=extra_env
    )
    if zero is None:
        return PreSatisfied(
            {},
            rest,
            "the zero-value run produced no readable report (nothing to vary)",
            inconclusive=dependency,
        )
    confirmed: dict[str, tuple[str, ...]] = {}
    refuted: dict[str, tuple[str, ...]] = {}
    inconclusive: dict[str, str] = dict(dependency)
    for criterion, result in variant.judge(
        zero.run, rest, real, zero.own, redact=wb.redactor.redact_text, proved=zero.proved
    ).items():
        if result.state == "confirmed":
            confirmed[criterion] = result.tests
        elif result.state == "refuted":
            refuted[criterion] = result.tests
        else:
            inconclusive[criterion] = result.reason
    return PreSatisfied(confirmed, refuted, "", inconclusive, {}, dict(zero.kept), zero.reruns)


# --- tests no red record covers (M1.11 W6, decision 8) -------------------------------------------------------------


@dataclass(frozen=True)
class ExtraRun:
    """The verifier's decision on tests that people or a test chore wrote: `accepted` maps a test id to `zero_value` (it
    failed by assertion when the project's functions answered their zero value) or `base` (it failed by assertion
    against the unit base's production code); `rejected` are the ids that did neither; `reasons` say why a rejected id
    that did fail on the base is no proof; `inconclusive` are the rejected ids a run could not decide (their module did
    not import there, no test ran), or all of them when no run could be made (`NO_RUN`, `NO_ZERO`), and the ones in a
    file that is not Python that no run accepted (`NOT_PYTHON`: the runs vary Python files only), with why (L4-VER-050);
    `runs` is the number of gate runs made (the zero-value run and its keep reruns, and the run on the base: at most
    four); `made` names the runs made, in order (`test-extra-zero`, `test-extra-base`)."""

    accepted: dict[str, str] = field(default_factory=dict)
    rejected: tuple[str, ...] = ()
    runs: int = 0
    reasons: dict[str, str] = field(default_factory=dict)
    inconclusive: dict[str, str] = field(default_factory=dict)
    made: tuple[str, ...] = ()


ERROR_AT_BASE = "fails on the base only with an error, not by assertion"
NO_RUN = (
    "neither run could be made: the zero-value run and the base run vary Python production files only, and the tests "
    "import no Python module of the project and the unit changed no Python production file"
)
NOT_PYTHON = "the zero-value run and the base run vary Python files only, and {file} is not a Python file"
# the source files of other languages whose tests the runs (which vary Python files) cannot reach; a pytest doctest in a
# Markdown or text file is run by pytest, so it is not here
OTHER_LANGUAGES = (
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".swift",
    ".cs",
    ".rb",
    ".php",
    ".scala",
    ".dart",
    ".ex",
    ".exs",
)
NO_ZERO = (
    "no run could be made: no file of the zero-value scope could be varied, and the unit changed no Python "
    "production file"
)


def worktree_files(wb: Workbench) -> list[str]:
    """The work tree's files, tracked and untracked, without what the harness's excludes leave out (`node_modules/`,
    its output folders: the same rules `Workbench.changed_files` reads the tree with); a test chore's new test files are
    untracked until its step is committed. A git failure gives no file."""
    try:
        done = wb.git.run(
            "ls-files", "-z", "--cached", "--others", "--exclude-standard", check=False, config=wb.exclude_config
        )
    except GitError:
        return []
    return [p for p in done.stdout.split("\0") if p] if done.returncode == 0 else []


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
    when the zero-value run could not decide it and the base run did not accept it, and is no proof otherwise. With
    no file in the zero-value scope and no production file to swap (a TypeScript project: both runs vary Python files
    only) every test is `inconclusive` (`NO_RUN`), and so it is (`NO_ZERO`) when the scope had files but no function
    in them could be varied and no production file was changed: a check that ran nothing decides nothing. A test whose
    file is found (`file_of_id`) and is a source file of another language (`OTHER_LANGUAGES`) loads none of the varied
    code, so passing both runs says nothing about it: when no run accepted it and neither run reached it (it failed on
    the base, or in the zero-value run, only by an error), it is `inconclusive` (`NOT_PYTHON`, unless a run already
    gave a reason), not rejected; a run that makes it fail by assertion still accepts it. At most two gate runs and
    two keep reruns of the first, none when there is nothing to run."""
    wanted = sorted(set(tests))
    scope = sorted(imported_modules(wb, wanted) | _changed_modules(wb))
    production = production_changes(wb, base_sha)
    if wanted and not scope and not production:
        return ExtraRun(rejected=tuple(wanted), inconclusive=dict.fromkeys(wanted, NO_RUN))
    accepted: dict[str, str] = {}
    undecided: dict[str, str] = {}
    reached: set[str] = set()  # tests that failed (by an error) in the zero-value run: it reached them
    runs = 0
    made: list[str] = []
    redact = wb.redactor.redact_text
    zero = zeroed_run(wb, "test-extra-zero", scope, public=True, real=real, candidates=wanted) if scope else None
    own = zero.own if zero is not None else own_test_files(wb)
    if zero is not None:
        runs += 1 + zero.reruns
        made.append("test-extra-zero")
        for test in wanted:
            outcome, why = variant.test_outcome(zero.run, test, real, own, redact=redact, proved=zero.proved)
            if outcome == "proof":
                accepted[test] = PROOF_ZERO_VALUE
            elif outcome == "inconclusive":
                undecided[test] = why
            case = zero.run.report.tests.get(test) if zero.run.report is not None else None
            if case is not None and case.status in ("failed", "error"):
                reached.add(test)
    rest = [t for t in wanted if t not in accepted]
    reasons: dict[str, str] = {}
    if rest and production:
        runs += 1
        made.append("test-extra-base")
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
    if wanted and not made:  # the scope had files and none could be varied, and no production file changed
        return ExtraRun(rejected=tuple(wanted), inconclusive=dict.fromkeys(wanted, NO_ZERO))
    inconclusive = {t: why for t, why in undecided.items() if t not in accepted}
    open_tests = [t for t in wanted if t not in accepted and t not in reached and reasons.get(t) != ERROR_AT_BASE]
    files = worktree_files(wb) if open_tests else []
    for test in open_tests:
        found = file_of_id(test, files, own)
        if found is not None and found.endswith(OTHER_LANGUAGES):
            inconclusive.setdefault(test, NOT_PYTHON.format(file=found))  # a reason a run gave is kept
    reasons = {t: why for t, why in reasons.items() if t not in inconclusive}
    return ExtraRun(accepted, tuple(t for t in wanted if t not in accepted), runs, reasons, inconclusive, tuple(made))


def file_of_test(wb: Workbench, test_id: str) -> str | None:
    """The file of a test id of the report (`_test_file`)."""
    return _test_file(wb, test_id)
