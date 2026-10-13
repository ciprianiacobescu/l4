"""Step 5 (SPEC 10.2, L4-VER-002 step 5, L4-VER-014): a UI-facing criterion that no e2e test traces gets a Playwright
test written by the verifier's tool-less judge, and the test counts only if it is discriminating inside the gate
sandbox: it fails against the merge-base app and passes against the head app (plan D3).

The model returns code or `not_testable` (`testwriter.request_test`), and nothing it writes reaches a worktree except
through `write_test_file` at the path the harness fixes, `e2e/test_l4_c_<hex>.py` (L4-VER-002a). The file goes into
the head tree and the merge-base checkout, is linted at the head (the project's CI lints H), and is removed again
unless it was accepted. One retry carries the reason. Generation is impossible, and the criterion stays uncovered
(`needs_human`), after `not_testable`, an uncollectable test, or two attempts that are not discriminating; a test that
fails at the head is kept in the outcome as evidence and never committed (the panel review of L4-VER-012 is deferred).
Step 5 returns the accepted paths only: the single per-round commit is M1.3's `commit_verifier_tests` (line 34).
`verify.generated{criterion, test, base, head, attempts, status, reason, model, tests, sha256}` is emitted HERE, once
per criterion (the live protocol's shape, plus the evidence); line 34's ladder row must not emit it again.
M1: verifier 3.2 (`flaky_repeats`), 3.3 (the synthetic baseline), 3.7/3.8 (audit sampling), the agentic verifier.
"""

import contextlib
import hashlib
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from l4.gates.e2e import ServerNotReady, run_e2e
from l4.gates.junit import TestReport
from l4.implementer.tdd import RoleLimit
from l4.implementer.workbench import Workbench
from l4.llm.agent_judge import LLMBackend
from l4.memory.curate import UI_GAP_TITLE
from l4.specs.base import Criterion
from l4.verifier.e2e_trace import e2e_coverage
from l4.verifier.playwright import artifact_dir, base_checkout, failure_artifacts
from l4.verifier.testwriter import request_test, test_path, write_test_file
from l4.verifier.types import Finding, GeneratedOutcome, GenStatus, RunOutcome, Severity

MAX_ATTEMPTS = 2  # the first try and one retry
MAX_DIFF_CHARS = 30_000
MAX_SNAPSHOT_CHARS = 30_000
MAX_REASON_CHARS = 600


@dataclass
class UiGeneration:
    outcomes: list[GeneratedOutcome] = field(default_factory=list)

    @property
    def paths(self) -> list[str]:
        """The accepted tests, sorted: what step 5 hands to the per-round commit."""
        return sorted(o.path for o in self.outcomes if o.accepted and o.path)

    @property
    def uncovered(self) -> list[str]:
        """Criteria that stay without an e2e test: they are `needs_human`."""
        return [o.criterion for o in self.outcomes if not o.accepted]

    @property
    def cost_usd(self) -> float:
        return sum(o.cost_usd for o in self.outcomes)


def ui_gap_finding(criterion: Criterion, unproved: Sequence[str] = ()) -> Finding:
    """The deterministic finding for a UI criterion that no PROVED e2e test traces. When an accepted generated test
    closes it in a PASS round it becomes the lesson of `memory.curate.LESSON_RULES` (same title). `unproved`: e2e tests
    that trace it but have no red, audit or generated record (one the implementer wrote): the finding says so."""
    if unproved:
        shown = ", ".join(unproved[:3]) + (f" (+{len(unproved) - 3} more)" if len(unproved) > 3 else "")
        detail = (
            f"The end-to-end test {shown} traces criterion {criterion.id} ({criterion.alias}), but it was never proved "
            "to fail without the change (no red, audit or generated record), so it is not evidence; step 5 generates "
            "one."
        )
    else:
        detail = f"No end-to-end test traces criterion {criterion.id} ({criterion.alias}); step 5 generates one."
    return Finding(Severity.MINOR, UI_GAP_TITLE, detail, "deterministic", criterion=criterion.id)


def _short(text: str) -> str:
    return " ".join(text.split())[:MAX_REASON_CHARS]


def _lint(wb: Workbench) -> str:
    """The reason the project's lint rejects the head tree, or ""."""
    for command in wb.cfg.gates.lint:
        result = wb.run_gate("lint-generated", command)
        if result.status != "pass":
            return f"`{command}` failed: {_short(result.reason)}"
    return ""


def _traced(criterion: Criterion, report: TestReport | None, max_per_test: int) -> dict[str, str]:
    """test id -> status of the tests of the report that trace the criterion."""
    if report is None:
        return {}
    ids = e2e_coverage([criterion], report, max_criteria_per_test=max_per_test).get(criterion.id, [])
    return {i: report.tests[i].status for i in ids}


@dataclass(frozen=True)
class _Verdict:
    status: GenStatus
    reason: str = ""
    artifacts: tuple[str, ...] = ()
    base: RunOutcome | None = None
    head: RunOutcome | None = None
    tests: tuple[str, ...] = ()


def _outcome(statuses: Collection[str]) -> RunOutcome:
    if "error" in statuses:
        return "error"
    return "pass" if "passed" in statuses and "failed" not in statuses else "fail"


def _discriminates(wb: Workbench, base: Path, criterion: Criterion) -> _Verdict:
    """Run the new test at the merge base, then at the head. `accepted` when it fails at the base and passes at the
    head. At the base only an assertion failure counts as failing: an error (a fixture, a browser that cannot launch)
    says nothing about the app, so it never lets a test through (`base_error`). A base that cannot be served
    while the head can is about the unit (it adds the app), not the harness: `base_unservable`. A head server that
    never gets ready raises (exit 1)."""
    cap = wb.cfg.verifier.max_criteria_per_test
    try:
        at_base = run_e2e(wb, base, name="e2e-base")
    except ServerNotReady as exc:
        run_e2e(wb, name="e2e-head")  # raises when the head is not served either: then it is the harness's fault
        return _Verdict("base_unservable", f"the merge-base app cannot be served ({exc})")
    found = _traced(criterion, at_base.report, cap)
    if not found:
        return _Verdict("uncollectable", "no test of the new file ran at the merge base (collection error or no test)")
    base_outcome = _outcome(found.values())
    if base_outcome == "pass":
        return _Verdict(
            "non_discriminating", "the test passes at the merge base: it does not need the new behaviour", base="pass"
        )
    if base_outcome == "error":
        bad = sorted(i for i, status in found.items() if status == "error")
        reason = f"the test errors at the merge base, which proves nothing: {', '.join(bad[:3])}"
        return _Verdict("base_error", reason, base="error")
    at_head = run_e2e(wb, name="e2e-head")
    found = _traced(criterion, at_head.report, cap)
    if not found:
        return _Verdict("uncollectable", "no test of the new file ran at the head", base="fail")
    failing = sorted(i for i, status in found.items() if status != "passed")
    if failing:
        artifacts = tuple(
            failure_artifacts(wb.worktree, at_head.report, directory=artifact_dir(wb.cfg.gates.e2e.command))
        )
        return _Verdict(
            "fails_at_head", f"the test fails at the head: {', '.join(failing[:3])}", artifacts, "fail",
            _outcome(found.values()),
        )  # fmt: skip
    return _Verdict("accepted", base="fail", head="pass", tests=tuple(sorted(found)))


def generate_ui_test(
    wb: Workbench,
    judge: LLMBackend,
    criterion: Criterion,
    base: Path,
    *,
    ui_diff: str,
    snapshot: str,
    timeout_s: int = 600,
) -> GeneratedOutcome:
    """One criterion. `base` is the merge-base checkout of `base_checkout`, set up and ready to be served."""
    rel = test_path("e2e", criterion.id)
    blocks = [
        ("scenario", criterion.text),
        ("ui diff", ui_diff[:MAX_DIFF_CHARS]),
        ("page snapshot", snapshot[:MAX_SNAPSHOT_CHARS]),
    ]
    retry_reason: str | None = None
    cost, model, sha, last = 0.0, None, "", _Verdict("writer_failed", "no reply")
    code, digest = "", ""

    def outcome(attempts: int, verdict: _Verdict) -> GeneratedOutcome:
        return GeneratedOutcome(
            criterion.id, verdict.status, rel if code else None, attempts, verdict.reason, code, verdict.artifacts,
            cost, model, sha, verdict.base, verdict.head, verdict.tests, digest,
        )  # fmt: skip

    for attempt in range(1, MAX_ATTEMPTS + 1):
        reply = request_test(
            judge, kind="e2e", criterion_id=criterion.id, criterion_text=f"{criterion.alias}\n{criterion.text}",
            data_blocks=blocks, retry_reason=retry_reason, redact=wb.redactor.redact_text, timeout_s=timeout_s,
        )  # fmt: skip
        cost += reply.cost_usd or 0.0
        model, sha = reply.model or model, reply.prompt_sha256
        if reply.status == "limit" and reply.run is not None:
            raise RoleLimit(reply.run)
        if reply.status == "not_testable" and reply.not_testable is not None:
            return outcome(attempt, _Verdict("not_testable", _short(reply.not_testable.reason)))
        if reply.status in ("timeout", "error", "limit"):
            return outcome(attempt, _Verdict("writer_failed", _short(reply.detail) or reply.status))
        if reply.status == "invalid" or reply.test is None:
            retry_reason = _short(reply.detail) or "the reply was not a usable test"
            last = _Verdict("writer_failed", retry_reason)
            continue
        code = reply.test.code
        written = []
        try:
            for tree in (wb.worktree, base):
                write_test_file(tree, rel, code)  # replaces only the harness's own marked file
                written.append(tree)
            reason = _lint(wb)
            last = _Verdict("lint_failed", reason) if reason else _discriminates(wb, base, criterion)
        except FileExistsError:
            why = f"{rel} already exists and was never proved discriminating: step 5 never overwrites another's test"
            return outcome(attempt, _Verdict("writer_failed", why))
        finally:
            for tree in written:
                if not (last.status == "accepted" and tree == wb.worktree):
                    with contextlib.suppress(OSError):
                        (tree / rel).unlink()
        if last.status == "accepted":
            # the file ran under agent-controlled e2e runs with the tree writable: put the harness's bytes back before
            # they are hashed and committed, whatever a test did to its own file
            target = write_test_file(wb.worktree, rel, code, overwrite=True)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if last.status in ("accepted", "uncollectable", "base_unservable"):  # done, or no use trying again
            return outcome(attempt, last)
        retry_reason = last.reason
    return outcome(MAX_ATTEMPTS, last)


def generate_ui_tests(
    wb: Workbench,
    judge: LLMBackend,
    gaps: Sequence[Criterion],
    *,
    base_sha: str,
    ui_diff: str,
    snapshot: str,
) -> UiGeneration:
    """Step 5 over the UI criteria without an e2e test. The merge-base checkout is made once and removed in `finally`
    (also when a server never gets ready, which propagates as exit 1). No gaps: nothing is checked out or served."""
    out = UiGeneration()
    if not gaps:
        return out
    with base_checkout(wb, base_sha) as base:
        for criterion in gaps:
            done = generate_ui_test(wb, judge, criterion, base, ui_diff=ui_diff, snapshot=snapshot)
            wb.emit(
                "verify.generated", criterion=criterion.id, test=done.path, base=done.base, head=done.head,
                attempts=done.attempts, status=done.status, reason=done.reason, model=done.model,
                tests=list(done.tests), sha256=done.sha256,
            )  # fmt: skip
            out.outcomes.append(done)
    return out
