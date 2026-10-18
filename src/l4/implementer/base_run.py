"""Confirmation of a pre-satisfied criterion by a base run (L4-IMP-003).

A red step whose new tests all pass may test a criterion an earlier task's green of the same unit made true (a shared
helper). Neither an earlier red nor the Python-only zero-value run may be able to confirm it. The language-neutral
proof is the ordinary red-to-green fact found late: the new test FAILS BY ASSERTION against the unit base code and
passes at head. The run:

* the production files changed since the unit base, by commits or by this worktree (stubs), are swapped to their
  content at the base by `run_with_code_of` (files added since are set aside; a file deleted since stays deleted, so
  a test needing it errors there and is not confirmed); test files, test support files and
  the harness / spec / documentation paths (`file_kind` exempt) stay as the worktree holds them;
* a changed dependency manifest, lock file or runner config file means the environment differs: the run is skipped;
* the test gate runs; `red_code_in_place` puts every touched file back by sha256 in a `finally`, written fresh (no
  preserved mtimes, so incremental builds see the restored sources as newer).

A criterion is confirmed when one of its new tests failed by assertion there; an error (missing export, import
error, TypeError) is no proof; a test that passes at the base too shows the criterion was satisfied before the
unit. The base run only confirms (L4-IMP-003): the zero-value run alone can show that a test does not discriminate,
so a test the base run could not run (it imports a module the base lacks) leaves its criterion as the zero-value run
left it, inconclusive included (`combine`).
"""

import os
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from l4.evidence.scope import file_kind
from l4.gates.junit import TestReport
from l4.implementer import variant
from l4.implementer.discrimination import (
    PreSatisfied,
    _is_test_path,
    _matches,
    own_test_files,
    run_with_code_of,
    unit_base,
)
from l4.implementer.stubs import _is_inside
from l4.implementer.workbench import Workbench

VIA = "base_run"
MANIFESTS = (
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "pyproject.toml",
    "uv.lock", "poetry.lock", "requirements*.txt", "setup.py", "setup.cfg", "*.csproj", "packages.lock.json",
    "Directory.Packages.props", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock", "*.sln", "Directory.Build.props",
    "Directory.Build.targets", "global.json", "NuGet.config",
)  # fmt: skip
_LINKS = ("120000", "160000")  # a symlink or a submodule in git's raw modes


@dataclass(frozen=True)
class BaseRunResult:
    confirmed: dict[str, tuple[str, ...]] = field(default_factory=dict)  # criterion -> tests that failed by assertion
    base_sha: str = ""
    reason: str = ""  # why the run was skipped, or what it showed when it confirmed nothing
    inconclusive: dict[str, str] = field(default_factory=dict)  # criterion -> why the run could not run its tests


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


def confirmed_by_base_run(
    wb: Workbench,
    candidates: Mapping[str, Sequence[str]],
    new_ids: Collection[str],
    *,
    real: TestReport | None = None,
) -> BaseRunResult:
    """`candidates`: criterion -> this step's new tests, which passed at head and which no earlier red and no
    zero-value run confirmed. The run is classified against `real` (L4-IMP-060): a criterion is confirmed when one of
    its new tests is a proof there; one whose tests the run could not run is `inconclusive`. A skipped run says so in
    `reason` and decides nothing."""
    if not candidates:
        return BaseRunResult()
    base = unit_base(wb)
    if base is None:
        return BaseRunResult(reason="base run skipped: the unit base could not be found")
    paths, why = _plan(wb, base)
    if why:
        return BaseRunResult(base_sha=base, reason=f"base run skipped: {why}")
    gate = run_with_code_of(wb, base, paths, name="test-base-run")  # restores by sha256, reports put back
    run = variant.classify(gate, real, redact=wb.redactor.redact_text)
    own = own_test_files(wb)
    confirmed: dict[str, tuple[str, ...]] = {}
    inconclusive: dict[str, str] = {}
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
    reason = "" if confirmed else "none of its new tests fails by assertion against the unit base code"
    return BaseRunResult(confirmed, base, reason, inconclusive)


@dataclass(frozen=True)
class Decision:
    """What the zero-value run and the base run leave of the pre-satisfied candidates (design D3): `refuted` are the
    agent's to fix, `inconclusive` are not (the check could not decide)."""

    refuted: dict[str, tuple[str, ...]]
    inconclusive: dict[str, str]
    message: str


def combine(zero: PreSatisfied, based: BaseRunResult) -> Decision:
    """A criterion the base run confirmed is confirmed. Of the rest, those the zero-value run refuted stay refuted and
    those it could not decide stay inconclusive, whatever the base run saw (it only confirms)."""
    refuted = {c: t for c, t in zero.unconfirmed.items() if c not in based.confirmed}
    inconclusive = {}
    for criterion, reason in zero.inconclusive.items():
        if criterion in based.confirmed:
            continue
        note = based.inconclusive.get(criterion) or (
            based.reason if based.reason.startswith("base run skipped") else ""
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
