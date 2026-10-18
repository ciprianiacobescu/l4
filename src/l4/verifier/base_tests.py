"""Step 1, the run of the base's tests on the unit's code (L4-VER-038, design D13).

The AST comparison of `integrity.check_tests` reads texts; this reads behaviour, in any language with a JUnit
report. The test gate runs once at the unit's head with every test and support file the unit added, changed or
deleted at its base version (`support_base.unit_test_plan`: an added one is set aside), and each test that passed at
the base must still pass. A test that fails, no longer runs, or no longer collects is a blocker, unless a
`tests.superseded` event, a `task.unfrozen`, a `[test-infra]` task or only people's commits cover its file.

The base reference (R0) is needed only when the run (R1) is not all green or the unit changed runner configuration:
R1's test files are exactly the base's, so an all-green R1 with no collection error has run and passed every test that
passed at the base. R0 comes from the workbench's baseline of the same base sha, from an earlier round of this unit
(`integrity.base_tests` of its `verdict.json`, which lies under the protected `.l4/` and holds a non-empty `passed`
list), or from a run in a merge-base worktree.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from l4.config.schema import duration_seconds
from l4.gates.e2e import run_gate_at
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateSpec
from l4.implementer.workbench import Workbench
from l4.security.protected import glob_match
from l4.vcs.authorship import SHA
from l4.verifier.audit import BASE_RUN_ENV, _collection_error
from l4.verifier.evidence import read_verdict
from l4.verifier.integrity import (
    IntegrityContext,
    Outcome,
    _allowance,
    _blob,
    _blocker,
    _by_people,
    _changed,
    _introducers,
    _listed,
    _superseded,
    commits,
    tagged_files,
)
from l4.verifier.playwright import base_checkout
from l4.verifier.support_base import support_at_base, unit_test_plan
from l4.verifier.types import IntegrityCheck, Severity

FAILS_TITLE = "a pre-existing test fails on the unit's code"
GONE_TITLE = "a pre-existing test no longer runs on the unit's code"
FLAKY_TITLE = "a pre-existing test is flaky on the unit's code"
ROW = "pre-existing tests still pass"


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


def _file_of(ctx: IntegrityContext, test_id: str) -> str | None:
    """`tests.test_pricing.TestCart::test_x` -> `tests/test_pricing.py`, looked up at head and then at the base."""
    parts = test_id.split("::", 1)[0].split(".")
    while parts:
        candidate = "/".join(parts) + ".py"
        if any(_blob(ctx.git, rev, candidate) is not None for rev in (ctx.head_sha, ctx.base_sha)):
            return candidate
        parts.pop()
    return None


def split_allowed(ctx: IntegrityContext, candidates: Sequence[str]) -> tuple[list[str], list[str], list[str]]:
    """(blocked ids, allowed lines, people's lines). Allowed: a `tests.superseded` id; a file a `task.unfrozen` of the
    unit names; a file a `[test-infra]` task's commits touched. People's: a file only people's commits changed."""
    recorded = {r.split("[", 1)[0] for r in _superseded(ctx)} | set(_superseded(ctx))
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
        if test_id in recorded or test_id.split("[", 1)[0] in recorded:
            allowed.append(f"{test_id} (superseded by a changed criterion)")
        elif file in unfrozen:
            allowed.append(f"{test_id} (task.unfrozen: {unfrozen[file]})")
        elif file in infra:
            allowed.append(f"{test_id} ([test-infra] task)")
        elif file is not None and _by_people(who := _introducers(ctx, file, lambda before, after: before != after)):
            human.append(
                f"{test_id} fails with the base version of its files (changed by {', '.join(r[SHA][:10] for r in who)})"
            )
        else:
            blocked.append(test_id)
    return blocked, allowed, human


def kept_files(ctx: IntegrityContext, paths: Sequence[str]) -> dict[str, str]:
    """The files of the revert set that stay at head for the run (second review M4): a support file (conftest,
    fixture, golden data, helper) that only people's commits changed, that a `[test-infra]` task changed, or that a
    `task.unfrozen` frees. Their effect on the tests is accepted and listed; every other file is reverted."""
    by_sha = {c.sha: c for c in commits(ctx)}
    kept: dict[str, str] = {}
    for path in paths:
        who = _introducers(ctx, path, lambda before, after: before != after)
        if _by_people(who):
            kept[path] = f"only people's commits changed it ({', '.join(r[SHA][:10] for r in who)})"
        elif (why := _allowance(ctx, who, path, by_sha)) is not None:
            kept[path] = why.strip("()")
    return kept


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
    spec = GateSpec("base-tests-base", command, _reports(wb), "junit", duration_seconds(wb.cfg.gates.timeout))
    with base_checkout(wb, ctx.base_sha) as tree:
        result = run_gate_at(wb, tree, spec, network=False)
    if result.report is None:
        return None, "", f"the base's test gate gave no report ({result.reason})"
    return result.report, "base worktree", ""


def check_base_tests(
    wb: Workbench, ctx: IntegrityContext, *, prior: Sequence[IntegrityCheck], round_no: int
) -> Outcome:
    """The sub-check `pre-existing tests still pass` (design D13). Emits `verify.base_tests`."""
    if any(c.status == "failed" for c in prior):
        return Outcome(note="step 1 already failed", skipped=True)
    cfg = wb.cfg
    full = unit_test_plan(wb.git, cfg, ctx.base_sha, ctx.head_sha, None)
    kept = kept_files(ctx, [path for path, _ in full.changes])
    plan = replace(full, changes=tuple(c for c in full.changes if c[0] not in kept))
    allowed_files = [f"{p} kept at head for the run ({why})" for p, why in kept.items() if "people" not in why]
    people_files = [f"{p} kept at head for the run ({why})" for p, why in kept.items() if "people" in why]
    changed = _changed(ctx.git, ctx.base_sha, ctx.head_sha)
    runner_changed = sorted(p for p in changed if any(glob_match(g, p) for g in cfg.tdd.runner_config_files))
    if not plan.changes and not runner_changed:
        note = "the unit changed no test or support file; step 3 runs the base's tests as they are"
        if kept:
            note = f"all {len(kept)} changed test and support file(s) are allowed and kept at head (listed)"
        return Outcome(note=note, allowed_tests=allowed_files, human_tests=people_files)
    command = cfg.gates.test.command
    for setup in cfg.gates.setup:
        done = wb.run_gate("setup-base-tests", setup, network=True)
        if done.status != "pass":
            return Outcome(note="gates.setup failed (step 2 reports it)", skipped=True)
    with support_at_base(wb, ctx.base_sha, plan) as reverted:
        gate = wb.run_gate("base-tests", command, reports=_reports(wb), extra_env=BASE_RUN_ENV)
        repeat = None
        r1 = gate.report
        if r1 is not None and any(c.status in ("failed", "error") for c in r1.tests.values()):
            repeat = wb.run_gate("base-tests-repeat", command, reports=_reports(wb), extra_env=BASE_RUN_ENV).report
    if r1 is None:
        detail = f"the test gate gave no report with the unit's test and support files at the base ({gate.reason})"
        _emit(wb, round_no, ctx, "not needed", reverted, Judged(), [], [], [])
        return Outcome([_blocker(GONE_TITLE, detail)], "no report from the run of the base's tests")
    needs_base = runner_changed or r1.collection_errors or any(c.status != "passed" for c in r1.tests.values())
    if needs_base:
        r0, source, why = _base_reference(wb, ctx, command, round_no)
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
    if failing:
        detail = [f"{i} ({_first_line(r1.tests[i].message or r1.tests[i].status)})" for i in failing]
        findings.append(_blocker(FAILS_TITLE, _listed(detail)))
    if gone or errors:
        findings.append(_blocker(GONE_TITLE, _listed([*gone, *errors])))
    if flaky:
        findings.append(_blocker(FLAKY_TITLE, _listed(flaky), Severity.MINOR))
    note = (
        f"{judged.still_passing + len(allowed) + len(human)} of {judged.passed_at_base} base tests pass on the unit's "
        f"code with its {len(reverted)} test and support files at the base (base: {source})"
    )
    _emit(wb, round_no, ctx, source, reverted, judged, flaky, [a.split(" (")[0] for a in allowed], errors)
    record = {
        "base_sha": ctx.base_sha,
        "command": command,
        "passed": sorted(i for i, c in r0.tests.items() if c.status == "passed"),
        "collection_errors": list(r0.collection_errors),
    }
    return Outcome(
        findings, note, allowed_tests=[*allowed_files, *allowed], human_tests=[*people_files, *human], base_tests=record
    )


def _emit(
    wb: Workbench, round_no: int, ctx: IntegrityContext, source: str, reverted: Sequence[str], judged: Judged,
    flaky: Sequence[str], allowed: Sequence[str], errors: Sequence[str],
) -> None:  # fmt: skip
    wb.emit(
        "verify.base_tests", round=round_no, base_sha=ctx.base_sha, base_source=source, reverted=list(reverted),
        passed_at_base=judged.passed_at_base, still_passing=judged.still_passing, failing=judged.failing,
        not_run=judged.not_run, collection_errors=list(errors), flaky=list(flaky), allowed=list(allowed),
    )  # fmt: skip
