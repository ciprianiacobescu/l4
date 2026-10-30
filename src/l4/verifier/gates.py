"""Steps 2 and 3 of the ladder (SPEC 10.2): a thin adapter over `Workbench.run_gate`, so the verifier runs the same
gates, in the same gate sandbox, with the same logs as the implementer loop.

Step 2 runs `gates.setup` (with the network, the dependencies are downloaded there), `build`, `lint` and `typecheck`
in that order and stops at the first failure: every failure is a deterministic blocker with a link to the log, not an
exit code (the implementer's setup failure is exit 3; here the verdict is FAIL, SPEC L4-VER-002).
Step 3 runs the full `gates.test`, non-vacuous: zero tests, a missing report or a missing new test fail it.
The end-to-end gate (`gates.e2e`, served by `l4.gates.e2e`) is part of step 3 when it has a command.
M1: verifier 1.7 (extra gates), 1.8 (`flaky_repeats`).
"""

import hashlib
import os
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from l4.ci.failing_step import STEP_GATE_PREFIX, ChoreCiStep
from l4.config.schema import L4Config
from l4.gates.e2e import run_e2e
from l4.gates.junit import TestReport
from l4.gates.runner import GateResult
from l4.implementer.workbench import Workbench
from l4.verifier.types import Finding, GateLine, Severity

MAX_NAMED = 5
MAX_FAILURE_CHARS = 200  # the first line of a failing test's message in the verdict's `failures` (L4-VER-069)
ALTERED = "the test report was altered"  # the reason `Workbench._cross_check` gives (L4-VER-039)


@dataclass
class BuildOutcome:
    gates: list[GateLine] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


@dataclass
class TestGateOutcome:
    __test__ = False  # not a pytest class

    gate: GateLine
    report: TestReport | None
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


DIGEST_LINES, DIGEST_LENGTH = 30, 12
_VOLATILE = (  # what differs between two runs of the same failure, removed in this order
    re.compile(r"\x1b\[[0-9;]*[A-Za-z]"),  # colours
    re.compile(r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:Z|[+-]\d\d:?\d\d)?"),  # timestamps
    re.compile(r"(?<![\w.])/[^\s:'\"),;]+"),  # absolute paths
    re.compile(r"\b(?:0x)?[0-9a-fA-F]{7,}\b"),  # hex ids and addresses
    re.compile(r"\d+"),
)


def log_digest(path: Path) -> str | None:
    """A failed gate's fingerprint (review M5, L4-OPS-007): the last 30 lines of its log with colours, timestamps,
    absolute paths, hex ids and digits removed, sha256, 12 characters. The same crash twice gives the same digest, two
    different lint errors do not. None when the log cannot be read."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-DIGEST_LINES:]
    except OSError:
        return None
    text = "\n".join(line.rstrip() for line in lines)
    for pattern in _VOLATILE:
        text = pattern.sub("", text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


def _line(wb: Workbench, name: str, command: str, result: GateResult) -> GateLine:
    log = os.path.relpath(result.log_path, wb.out_dir.parent)
    digest = log_digest(result.log_path) if result.status == "fail" else None
    return GateLine(name, command, result.status, result.reason, log, digest)


def _blocker(name: str, command: str, reason: str, log: str | None) -> Finding:
    return Finding(
        Severity.BLOCKER, f"{name} gate failed", f"`{command}` failed: {reason}", "deterministic", log=log,
    )  # fmt: skip


def _run_stage(wb: Workbench, out: BuildOutcome, name: str, commands: Sequence[str]) -> bool:
    """Run the commands of one stage in order; the first failure is the stage's blocker and ends it (False)."""
    for command in commands:
        result = wb.run_gate(name, command, network=True if name == "setup" else None, builds_env=name == "setup")
        line = _line(wb, name, command, result)
        out.gates.append(line)
        if result.status != "pass":
            out.findings.append(_blocker(name, command, result.reason, line.log))
            return False
    return True


def run_build_only(wb: Workbench) -> BuildOutcome:
    """`gates.build` alone, the way step 2 runs it (L4-IMP-090: a fix chore for a browser-test finding builds what the
    e2e gate serves). `gates.setup` ran before the chore's agent step."""
    out = BuildOutcome()
    _run_stage(wb, out, "build", wb.cfg.gates.build)
    return out


def run_build_gates(wb: Workbench, ci_steps: Sequence[ChoreCiStep] = ()) -> BuildOutcome:
    """`ci_steps`: the reproduced failing steps of the project's own CI job that are in their window
    (`active_ci_steps`); each runs after `typecheck` as `repository-ci:<job>`, and a failure is the blocker
    `repository CI failed: <job>`, the finding step 0 raised for that job (same id, M1.10 decisions 4 and 5)."""
    out = BuildOutcome()
    cfg = wb.cfg.gates
    for name, commands in (
        ("setup", cfg.setup),
        ("build", cfg.build),
        ("lint", cfg.lint),
        ("typecheck", cfg.typecheck),
    ):
        if not _run_stage(wb, out, name, commands):
            return out
    for step in ci_steps:
        result = wb.run_gate(f"{STEP_GATE_PREFIX}{step.job}", step.command)
        line = _line(wb, f"{STEP_GATE_PREFIX}{step.job}", step.command, result)
        out.gates.append(line)
        if result.status != "pass":
            out.findings.append(
                Finding(
                    Severity.BLOCKER,
                    f"repository CI failed: {step.job}",
                    f"the project's CI step `{step.command}` still fails in the gate sandbox: {result.reason}",
                    "deterministic",
                    log=line.log,
                )  # fmt: skip
            )
            return out
    return out


def _judged(wb: Workbench, name: str, command: str, reports_key: str, result: GateResult) -> TestGateOutcome:
    """A test-shaped gate (`test`, `e2e`) judged on its report: failing tests are named, and a pass with a missing
    report, a collection error or no test at all is a failure, so a gate that ran nothing never passes."""
    line = _line(wb, name, command, result)
    out = TestGateOutcome(line, result.report)
    reason = result.reason
    report = result.report
    if result.status == "pass" and report is not None and report.collection_errors:
        reason = f"tests not collected: {', '.join(sorted(report.collection_errors)[:MAX_NAMED])}"
    elif result.status == "fail" and report is not None:
        failing = sorted(i for i, c in report.tests.items() if c.status in ("failed", "error"))
        if failing:
            reason = f"{reason}; failing: {', '.join(failing[:MAX_NAMED])}"
    elif result.status == "pass" and report is None:  # without a report the exit code alone would pass
        reason = f"report missing: {reports_key} is empty"
    elif result.status == "pass":
        return out
    out.gate = GateLine(line.name, line.command, "fail", reason, line.log, log_digest(result.log_path))
    if reason.startswith(ALTERED):  # the report disagrees with what pytest judged: its own blocker
        out.findings.append(Finding(Severity.BLOCKER, ALTERED, reason, "deterministic", log=line.log))
    else:
        out.findings.append(_blocker(name, command, reason, line.log))
    return out


def failure_records(
    unit: TestReport | None, browser: TestReport | None, redact: Callable[[str], str]
) -> dict[str, dict[str, str]]:
    """L4-VER-069: for each test id that failed or errored, the gate it failed in (`test` for the unit report, `e2e` for
    the browser report, which wins for an id both hold), the kind the JUnit reader gave (`error` for an error of no
    known shape, `other` for a failure of none) and the first line of its message, redacted and cut."""
    out: dict[str, dict[str, str]] = {}
    for gate, report in (("test", unit), ("e2e", browser)):
        for test_id, case in (report.tests if report is not None else {}).items():
            if case.status not in ("failed", "error"):
                continue
            first = redact(case.message.strip().split("\n", 1)[0])[:MAX_FAILURE_CHARS]
            kind = case.failure_kind or ("error" if case.status == "error" else "other")
            out[test_id] = {"gate": gate, "kind": kind, "message": first}
    return out


def run_test_gate(
    wb: Workbench, must_contain: Collection[str], *, extra_env: Mapping[str, str] | None = None
) -> TestGateOutcome:
    """`extra_env`: the coverage plugin's environment (M1.6), merged with the trace plugin's by the workbench."""
    command = wb.cfg.gates.test.command
    result = wb.run_gate(
        "test", command, reports=wb.cfg.gates.test.reports, must_contain=must_contain, extra_env=extra_env
    )
    return _judged(wb, "test", command, "gates.test.reports", result)


def e2e_gate_configured(cfg: L4Config) -> bool:
    """Step 3 runs `gates.e2e` whenever it has a command; a half-configured gate is then refused (exit 2) by
    `run_e2e` rather than skipped without a word."""
    return bool(cfg.gates.e2e.command.strip())


@dataclass
class E2eGateOutcome(TestGateOutcome):
    snapshot: str | None = None  # `GET <origin>/` as the launcher saved it: what step 5 shows the test writer


def run_e2e_gate(wb: Workbench) -> E2eGateOutcome:
    """Step 3, second half: the app is served and the browser tests run against the head, in one gate spawn. A server
    that never gets ready raises (exit 1): that is the runner's trouble, not a finding about the unit."""
    command = wb.cfg.gates.e2e.command
    run = run_e2e(wb)
    out = _judged(wb, "e2e", command, "gates.e2e.reports", run.gate)
    return E2eGateOutcome(out.gate, out.report, out.findings, run.snapshot_text)
