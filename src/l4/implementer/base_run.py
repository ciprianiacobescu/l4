"""Confirmation of a pre-satisfied criterion by a base run (L4-IMP-003).

A red step whose new tests all pass may test a criterion an earlier task's green of the same unit made true (a shared
helper). Neither an earlier red nor the Python-only zero-value run may be able to confirm it. The language-neutral
proof is the ordinary red-to-green fact found late: the new test FAILS BY ASSERTION against the unit base code and
passes at head. The run:

* the production files changed since the unit base, by commits or by this worktree (stubs), are swapped to their
  content at the base by `run_with_code_of` (files added since are set aside; a file deleted since stays deleted, so
  a test needing it errors there and is not confirmed); test support files and the harness / spec / documentation
  paths (`file_kind` exempt) stay as the worktree holds them, and so do the test files that hold a decided test or no
  reported test; the test files the unit added and that hold none of the decided tests are set aside for the run
  (L4-IMP-097: an earlier task's test file that cannot finish against the base code would keep the run from writing a
  report; a pre-existing test file the unit changed stays, a runner may write snapshots next to it);
* a changed dependency manifest, lock file or runner config file means the environment differs: the run is skipped;
* the test gate runs, stopped at its own limit (twice the step's test run, or the step's test run plus one test's
  limit, L4-IMP-097); `red_code_in_place` and
  `other_tests_at_base` put every touched file back by sha256 in a `finally`, written fresh (no preserved mtimes, so
  incremental builds see the restored sources as newer).

A criterion is confirmed when one of its new tests failed by assertion there; an error (missing export, import
error, TypeError) is no proof; a test that passes at the base too shows the criterion was satisfied before the
unit. The base run only confirms (L4-IMP-003): the zero-value run alone can show that a test does not discriminate,
so a test the base run could not run (it imports a module the base lacks) leaves its criterion as the zero-value run
left it, inconclusive included (`combine`).
"""

import os
from collections.abc import Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from math import ceil
from pathlib import Path, PurePosixPath

from l4.config.schema import duration_seconds
from l4.evidence.scope import file_kind
from l4.gates.junit import TestReport
from l4.implementer import variant
from l4.implementer.discrimination import (
    PreSatisfied,
    _drop_bytecode_of,
    _is_test_path,
    _matches,
    _read,
    _restore,
    _unlink,
    own_test_files,
    run_with_code_of,
    unit_base,
    worktree_files,
)
from l4.implementer.stubs import _is_inside
from l4.implementer.test_locate import file_of_id
from l4.implementer.workbench import Workbench
from l4.vcs.git import GitError

VIA = "base_run"
MANIFESTS = (
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "pyproject.toml",
    "uv.lock", "poetry.lock", "requirements*.txt", "setup.py", "setup.cfg", "*.csproj", "packages.lock.json",
    "Directory.Packages.props", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "*.sln", "Directory.Build.props",
    "Directory.Build.targets", "global.json", "NuGet.config",
)  # fmt: skip
_LINKS = ("120000", "160000")  # a symlink or a submodule in git's raw modes
BASE_RUN_FLOOR_S = 300  # the base run's own limit is at least this, at most `gates.timeout` (L4-IMP-097)
BASE_RUN_FACTOR = 2  # ... and twice the wall time of the step's own test run, or that time plus one test's limit
MAX_LISTED = (20, 50)  # the paths `base_run.scope` records: kept, set aside


SEEN_PASSES = "the base run: every new test passes against the unit base code too"
SEEN_ERROR = "the base run: its new tests fail against the unit base code only by an error, not by assertion"


@dataclass(frozen=True)
class BaseRunResult:
    confirmed: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> tests that failed by assertion
    base_sha: str = ""
    reason: str = ""  # why the run was skipped, or what it showed when it confirmed nothing
    inconclusive: dict[str, str] = field(default_factory=dict)  # criterion -> why the run could not run its tests
    seen: dict[str, str] = field(default_factory=dict)  # criterion -> what the run showed, when it decided nothing


def _is_manifest(wb: Workbench, path: str) -> bool:
    name = PurePosixPath(path).name
    return any(fnmatchcase(name, g) for g in MANIFESTS) or any(
        fnmatchcase(name, g) or _matches([g], path) for g in wb.cfg.tdd.runner_config_files
    )


def _changed_since(wb: Workbench, base: str) -> tuple[dict[str, tuple[str, str]], str]:
    """path -> (old mode, new mode) of `git diff base HEAD`, without rename detection; the reason when git failed."""
    done = wb.git.run_bytes("diff", "--raw", "-z", "--no-renames", "--no-abbrev", base, "HEAD", check=False)
    tokens = done.split(b"\0")
    found: dict[str, tuple[str, str]] = {}
    index = 0
    while index < len(tokens):
        meta = tokens[index]
        if not meta.startswith(b":"):
            index += 1
            continue
        fields = meta[1:].split()
        if len(fields) < 5 or index + 1 >= len(tokens):
            return {}, "git diff output could not be read"
        found[os.fsdecode(tokens[index + 1])] = (fields[0].decode(), fields[1].decode())
        index += 2
    return found, ""


def _kept(wb: Workbench, path: str) -> bool:
    unit_dir = Path(wb.ledger_rel).parents[2].as_posix()
    return _is_test_path(wb, path) or file_kind(path, unit_dir, wb.cfg) in ("exempt", "test")


def _plan(wb: Workbench, base: str) -> tuple[list[str], str]:
    """The production paths to swap to their content at the base (`run_with_code_of` swaps changed ones, sets aside the
    ones the base lacks); or the reason the run cannot be made."""
    committed, why = _changed_since(wb, base)
    if why:
        return [], why
    paths = set(committed) | set(wb.changed_files())
    paths.discard(wb.ledger_rel)
    for path in sorted(paths):
        if _is_manifest(wb, path):
            return [], f"{path} changed since the unit base: the environment differs"
    swap: list[str] = []
    for path in sorted(paths):
        if _kept(wb, path):
            continue
        if any(m in _LINKS for m in committed.get(path, ("", ""))):
            return [], f"{path} is a symlink or submodule"
        target = wb.worktree / path
        if not _is_inside(wb.worktree, target) or target.is_symlink() or target.is_dir():
            return [], f"{path} is not a plain file inside the worktree"
        swap.append(path)
    return swap, ""


@dataclass(frozen=True)
class Scope:
    """What `other_tests_at_base` did (L4-IMP-097): `aside` the added test files removed for the run, `unscoped` why
    nothing was set aside (empty when the run is scoped)."""

    aside: tuple[str, ...] = ()
    unscoped: str = ""


def _decided_files(wb: Workbench, decided: Sequence[str], real: TestReport | None) -> tuple[set[str], str]:
    """The files of the tests the run decides (design D1), or the reason the run is not scoped."""
    if real is None:
        return set(), "no head report"
    if not decided:
        return set(), "no test to decide"
    files, own = worktree_files(wb), own_test_files(wb)
    keep: set[str] = set()
    for test in decided:
        found = file_of_id(test, files, own)
        if found is None:
            return set(), f"the file of {test} was not found"
        keep.add(found)
    return keep, ""


def _exists_at_base(wb: Workbench, base: str, rel: str) -> tuple[bool, str]:
    """(whether the unit base holds `rel`, ""); (False, why) when git could not tell."""
    try:
        return bool(wb.git.run_bytes("ls-tree", "-z", base, "--", f":(literal){rel}")), ""  # a git failure raises
    except GitError:
        return False, f"{rel} could not be looked up at the unit base"


@contextmanager
def other_tests_at_base(wb: Workbench, base: str, keep: Collection[str], real: TestReport) -> Iterator[Scope]:
    """L4-IMP-097: the test files the unit added that hold none of the decided tests, removed for the run.
    The files set aside are the files of the head report's tests (`real`, tests and collection errors) that the unit
    added (the unit base lacks them), that match the test globs and not the support globs, that lie under no protected
    path (the gate would put one back to HEAD in the middle of the run) and are not in `keep`. A pre-existing test file
    the unit changed stays as the work tree holds it: a runner may write snapshots next to a file at its base content
    that nothing would put back. Each file is read first through the no-follow helpers; one that cannot be read, a
    link or one too large makes the run unscoped (nothing is touched). Every file is put back by sha256 in a `finally`
    (the restore of `red_code_in_place`), a mismatch is `restore failed`."""
    where, tdd = "test-base-run", wb.cfg.tdd
    files, own = worktree_files(wb), own_test_files(wb)
    heads = {test.partition("::")[0]: test for test in (*real.tests, *real.collection_errors)}  # one id per file
    reported = {found for test in heads.values() if (found := file_of_id(test, files, own)) is not None}
    candidates = sorted(
        path for path in reported & own
        if path not in keep and _matches(tdd.test_globs, path) and not _matches(tdd.test_support_globs, path)
        and wb.protected.match(path) is None
    )  # fmt: skip
    originals: dict[str, tuple[bytes, int]] = {}
    why = ""
    for rel in candidates:
        existing, why = _exists_at_base(wb, base, rel)
        if why:
            break
        if existing:
            continue  # a pre-existing file stays as the work tree holds it
        read = _read(wb, rel)
        if read is None:
            why = f"{rel} is a link, is outside the work tree, cannot be read or is too large to vary"
            break
        originals[rel] = read
    if why:
        yield Scope(unscoped=why)
        return
    aside: list[str] = []
    try:
        for rel in originals:
            _unlink(wb, rel, where)
            if not os.path.lexists(wb.worktree / rel):  # a refused removal is recorded; the file is not set aside
                aside.append(rel)
            _drop_bytecode_of(wb, rel, where)
        yield Scope(tuple(aside))
    finally:
        _restore(wb, originals, where)


def confirmed_by_base_run(
    wb: Workbench,
    candidates: Mapping[str, Sequence[str]],
    new_ids: Collection[str],
    *,
    real: TestReport | None = None,
    head_seconds: float = 0.0,
) -> BaseRunResult:
    """`candidates`: criterion -> this step's new tests, which passed at head and which no earlier red and no
    zero-value run confirmed. The run is classified against `real` (L4-IMP-060): a criterion is confirmed when one of
    its new tests is a proof there; one whose tests the run could not run is `inconclusive`. A skipped run says so in
    `reason` and decides nothing. L4-IMP-097: the test files the unit added and that hold no decided test are set aside
    for the run, and the run stops after twice `head_seconds`, the wall time of the step's own test gate, or after
    `head_seconds` plus one test's limit, whichever is longer (at least 300s, at most `gates.timeout`; `gates.timeout`
    when `head_seconds` is unknown)."""
    if not candidates:
        return BaseRunResult()
    base = unit_base(wb)
    if base is None:
        return BaseRunResult(reason="base run skipped: the unit base could not be found")
    paths, why = _plan(wb, base)
    if why:
        return BaseRunResult(base_sha=base, reason=f"base run skipped: {why}")
    limit = duration_seconds(wb.cfg.gates.timeout)
    one_test = wb.cfg.gates.test_timeout_seconds()  # the run is not cut in before one test's own limit
    bound = (
        min(limit, max(BASE_RUN_FLOOR_S, ceil(BASE_RUN_FACTOR * head_seconds), ceil(head_seconds) + one_test))
        if head_seconds > 0
        else limit
    )
    decided = sorted({t for tests in candidates.values() for t in tests if t in new_ids})
    keep, unscoped = _decided_files(wb, decided, real)
    scoped = (
        nullcontext(Scope(unscoped=unscoped)) if real is None or unscoped else other_tests_at_base(wb, base, keep, real)
    )
    with scoped as scope:
        listed = ([] if scope.unscoped else sorted(keep), sorted(scope.aside))  # an unscoped run keeps nothing apart
        wb.emit(
            "base_run.scope", decided=len(decided), kept=listed[0][: MAX_LISTED[0]], aside=listed[1][: MAX_LISTED[1]],
            timeout_s=bound, unscoped=scope.unscoped,
            more=sum(max(0, len(names) - most) for names, most in zip(listed, MAX_LISTED, strict=True)),
        )  # fmt: skip
        gate = run_with_code_of(wb, base, paths, name="test-base-run", timeout_s=bound)  # restores by sha256
    if gate.timed_out and bound < limit:  # the run's own limit stopped it, not gates.timeout: say so (L4-IMP-097)
        gate = replace(
            gate,
            reason=f"timed out after {bound}s: the base run's own limit (twice the step's test run, or the step's test "
            f"run plus one test's limit, at least {BASE_RUN_FLOOR_S}s)",
        )
    run = variant.classify(gate, real, redact=wb.redactor.redact_text)
    own = own_test_files(wb)
    confirmed: dict[str, tuple[str, ...]] = {}
    inconclusive: dict[str, str] = {}
    seen: dict[str, str] = {}
    for criterion, names in candidates.items():
        outcomes = [
            (t, *variant.test_outcome(run, t, real, own, redact=wb.redactor.redact_text, zero_value=False))
            for t in names
        ]
        outcomes = [o for o in outcomes if o[0] in new_ids]
        proving = tuple(t for t, outcome, _ in outcomes if outcome == "proof")
        if proving:
            confirmed[criterion] = proving
        elif undecided := [why for _, outcome, why in outcomes if outcome == "inconclusive"]:
            inconclusive[criterion] = undecided[0]
        elif outcomes:  # the run decided nothing about it: a hold that follows shows what the run did see (L4-IMP-092)
            cases = [run.report.tests.get(t) if run.report is not None else None for t, _, _ in outcomes]
            passed = all(case is not None and case.status == "passed" for case in cases)
            seen[criterion] = SEEN_PASSES if passed else SEEN_ERROR
    reason = "" if confirmed else "none of its new tests fails by assertion against the unit base code"
    return BaseRunResult(confirmed, base, reason, inconclusive, seen)


@dataclass(frozen=True)
class Decision:
    """What the zero-value run and the base run leave of the pre-satisfied candidates (design D3): `refuted` are the
    agent's to fix, `inconclusive` are not (the check could not decide)."""

    refuted: dict[str, tuple[str, ...]]
    inconclusive: dict[str, str]
    message: str


def combine(zero: PreSatisfied, based: BaseRunResult) -> Decision:
    """A criterion the base run confirmed is confirmed. Of the rest, those the zero-value run refuted stay refuted and
    those it could not decide stay inconclusive, whatever the base run saw (it only confirms); the reason of an
    inconclusive one ends with what the base run said or saw of it (L4-IMP-092)."""
    refuted = {c: t for c, t in zero.unconfirmed.items() if c not in based.confirmed}
    inconclusive = {}
    for criterion, reason in zero.inconclusive.items():
        if criterion in based.confirmed:
            continue
        note = (
            based.inconclusive.get(criterion)
            or based.seen.get(criterion)
            or (based.reason if based.reason.startswith("base run skipped") else "")
        )
        inconclusive[criterion] = f"{reason}; {note}" if note else reason
    parts = []
    if refuted:
        message = PreSatisfied({}, refuted, zero.reason).message
        note = based.reason or ("some of the others were confirmed by the base run" if based.confirmed else "")
        parts.append(f"{message[:-1]}; {note})" if note else message)
    if inconclusive:
        parts.append("inconclusive: " + ", ".join(f"{c} ({why})" for c, why in sorted(inconclusive.items())))
    return Decision(refuted, inconclusive, "; ".join(parts))


def failure_message(zero: PreSatisfied, based: BaseRunResult) -> str:
    """The "not discriminating" and "inconclusive" message for the criteria neither the zero-value run nor the base run
    confirmed; empty when there are none. A base run that was skipped, or that confirmed nothing, adds why."""
    return combine(zero, based).message
