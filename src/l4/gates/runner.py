"""Run one gate command (SPEC L4-GAT-001, L4-GAT-002): inside the sandbox, in its own process group, with a log.

The command is split with `shlex` and never goes through a shell; a command that needs one is written
`sh -c '...'` in the config. The kill on timeout is SIGKILL to the whole group (agents' test runs start children),
without the SIGTERM grace of the design (M1: implementer-tdd-loop D9).
M1: formats other than JUnit, `serve`, Playwright.
"""

import shlex
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Literal

from l4.agents.proc import ProcRunner
from l4.gates.junit import ReportError, TestReport, parse_junit
from l4.redact import Redactor
from l4.sandbox.base import Sandbox, SandboxSpec
from l4.sandbox.env import build_gate_env


@dataclass(frozen=True)
class GateSpec:
    name: str
    command: str
    reports: tuple[str, ...] = ()  # worktree-relative; empty: the exit code alone decides (setup, lint)
    format: str = "junit"
    timeout_s: int = 1800
    must_contain: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class GateResult:
    name: str
    status: Literal["pass", "fail"]
    reason: str
    exit_code: int | None
    log_path: Path
    report: TestReport | None = None  # parsed whenever a readable report exists, whatever the exit code
    timed_out: bool = False


def judge_test_gate(
    exit_code: int, report: TestReport | None, must_contain: Collection[str] | None = None
) -> tuple[bool, str]:
    """The exit code first, then the report: a missing report, zero executed tests or a missing expected id fail the
    gate, so an empty or crashed run can never pass for a green one."""
    if exit_code != 0:
        return False, f"exit code {exit_code}"
    if report is None:
        return False, "report missing"
    if report.executed == 0:
        return False, "vacuous: 0 tests executed"
    missing = sorted(set(must_contain or ()) - set(report.tests))
    if missing:
        return False, "expected tests missing: " + ", ".join(missing[:5])
    return True, ""


def _report_files(worktree: Path, reports: tuple[str, ...]) -> list[tuple[str, Path]]:
    files = []
    for relative in reports:
        pure = PurePosixPath(relative)
        if not relative or pure.is_absolute() or ".." in pure.parts:
            raise ValueError(f"report path {relative!r} must be relative and stay inside the worktree")
        files.append((relative, worktree / pure))
    return files


def run_gate(
    spec: GateSpec,
    *,
    worktree: Path,
    sandbox: Sandbox,
    sandbox_spec: SandboxSpec,
    host_env: Mapping[str, str],
    log_path: Path,
    redactor: Redactor,
    runner: ProcRunner | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> GateResult:
    files = _report_files(worktree, spec.reports)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def result(
        status: Literal["pass", "fail"],
        reason: str,
        code: int | None = None,
        report: TestReport | None = None,
        timed_out: bool = False,
    ) -> GateResult:
        return GateResult(spec.name, status, reason, code, log_path, report, timed_out)

    if not spec.command.strip():
        return result("fail", "no command configured")
    try:
        argv = shlex.split(spec.command)
    except ValueError:
        return result("fail", "the command cannot be parsed")
    for _, path in files:  # a report from an earlier run must not pass for this run's
        path.unlink(missing_ok=True)
    wrapped = sandbox.wrap(argv, sandbox_spec, build_gate_env(host_env, sandbox_spec, extra=extra_env))
    out_path, err_path = log_path.with_suffix(".out"), log_path.with_suffix(".err")
    try:
        outcome = (runner or ProcRunner()).run(
            wrapped.argv, wrapped.env, worktree, stdout_path=out_path, stderr_path=err_path, timeout_s=spec.timeout_s,
        )  # fmt: skip
    except OSError as exc:
        log_path.write_text("", encoding="utf-8")
        return result("fail", f"cannot start the command ({type(exc).__name__})")
    text = out_path.read_text(encoding="utf-8", errors="replace") + err_path.read_text(
        encoding="utf-8", errors="replace"
    )
    out_path.unlink()
    err_path.unlink()
    log_path.write_text(redactor.redact_text(text), encoding="utf-8")
    if outcome.timed_out:
        return result("fail", f"timed out after {spec.timeout_s}s", outcome.returncode, timed_out=True)
    if not files:
        ok, reason = outcome.returncode == 0, f"exit code {outcome.returncode}"
        return result("pass" if ok else "fail", "" if ok else reason, outcome.returncode)
    found = next(((rel, path) for rel, path in files if path.is_file() or path.is_symlink()), None)
    if found is None:
        return result("fail", f"report missing: {spec.reports[0]}", outcome.returncode)
    if spec.format != "junit":
        return result("fail", f"report format {spec.format} is not supported in M0", outcome.returncode)
    try:
        report = parse_junit(found[1])
    except ReportError as exc:
        return result("fail", f"report unreadable: {exc}", outcome.returncode)
    ok, reason = judge_test_gate(outcome.returncode, report, spec.must_contain)
    return result("pass" if ok else "fail", reason, outcome.returncode, report=report)
