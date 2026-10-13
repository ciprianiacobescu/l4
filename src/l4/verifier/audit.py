"""Step 4a of the ladder, audit sampling (SPEC 10.2, L4-VER-002 step 4a, L4-VER-002a).

For a seeded sample of the covered new criteria, plus every pre-satisfied one, the verifier agent writes an
independent test from the criterion text and the head source of the unit's changed non-test modules: the writer is
tool-less (`testwriter.request_test`), so it cannot read a test of the unit, and it does not run anything. At most
`MAX_AUDIT_PER_ROUND` criteria are audited per round, pre-satisfied ones first; the rest read `skipped (cap)`.

The test is written to `tests/test_l4_audit_c_<hex>_r<n>.py`, and all of a round's audit tests run in one gate run.
Accepted: it passes at head and, with the project's public functions answering their zero value (the red phase's
`confirm_pre_satisfied`), at least one of its tests fails. Rejected: it cannot be collected, or it passes against
the zero values (a minor finding). Failed: it fails at head, which makes the criterion `needs_human` (the panel review
of L4-VER-012 is not built). Rejected and failed files are removed; accepted ones stay in the worktree for
`evidence.commit_verifier_tests`.

An accepted test is then linted here, on its own file (M1.12, K2): the lint gate of step 2 ran before the test existed,
and moving it behind 4a would fail the whole ladder on a test the verifier wrote. Every `gates.lint` and
`gates.typecheck` command runs on the file (a `ruff check` is narrowed to it; any other command runs as configured).
A failure goes back to the writer once, with the lint output and the test; the fixed test is run and judged like a new
one. A test that still fails is rejected with the reason `lint: ...`: it is not committed, not shown to the judge, and
reported as a minor finding like any rejected audit test: the criterion is not held (its own tests trace it).
A lint failure never reaches a hand-off head.
M1: verifier 3.8 (the exported tree without `.git`: the writer sees no file, so L4-VER-002a already holds), the panel
review of a failing audit test (5.5, 5.6), the verifier red commit.
"""

import hashlib
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from l4.agents.factory import RoleUnavailable
from l4.gates.dryrun import narrow_ruff_paths
from l4.implementer.discrimination import confirm_pre_satisfied
from l4.implementer.excerpt import lint_excerpt
from l4.implementer.prompt import collect_sources
from l4.implementer.tdd import RoleLimit
from l4.implementer.workbench import Workbench
from l4.llm.agent_judge import LLMBackend
from l4.security.protected import glob_match
from l4.specs.base import Criterion
from l4.verifier.conventions import base_test_header, test_conventions
from l4.verifier.testwriter import request_test, test_path, write_test_file
from l4.verifier.types import AuditRecord, CriterionEvidence, Finding, Severity

MAX_AUDIT_PER_ROUND = 2
MAX_SOURCE_CHARS = 60_000
MAX_FILE_CHARS = 20_000
MAX_SPEC_CHARS = 8_000  # the unit's proposal and design together (W-C4: the writer must see what the spec lets change)
SPEC_FILES = ("design.md", "proposal.md")
PRE_SATISFIED = "pre_satisfied"
LINT_REJECTED = "lint:"  # the start of the reason of an audit test rejected for failing the project's lint
MAX_LINT_REASON_CHARS = 200


def choose(
    covered: Sequence[CriterionEvidence], ratio: float, unit_id: str, round_no: int
) -> tuple[list[str], list[str]]:
    """(audited, skipped by the cap): `ceil(ratio x covered)` criteria (at least one), picked by a sha256 of the unit
    id, the round and the criterion id so the choice repeats, plus every pre-satisfied criterion; pre-satisfied first,
    then the cap. A ratio of 0 turns the step off."""
    if ratio <= 0 or not covered:
        return [], []

    def seed(e: CriterionEvidence) -> str:
        return hashlib.sha256(f"{unit_id}|{round_no}|{e.criterion}".encode()).hexdigest()

    pre = sorted((e for e in covered if any(t.proof == PRE_SATISFIED for t in e.tests)), key=seed)
    rest = sorted((e for e in covered if e not in pre), key=seed)
    count = max(1, math.ceil(ratio * len(covered)))
    ordered = [e.criterion for e in pre] + [e.criterion for e in rest][: max(count - len(pre), 0)]
    return ordered[:MAX_AUDIT_PER_ROUND], ordered[MAX_AUDIT_PER_ROUND:]


def _changed_files(wb: Workbench, base_sha: str, head: str) -> list[str]:
    raw = wb.git.run_bytes("diff", "--name-only", "-z", "--no-renames", base_sha, head)
    return [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]


def _style_blocks(
    wb: Workbench, base_sha: str, changed: Sequence[str], near: str, conventions: str
) -> list[tuple[str, str]]:
    """How this project writes tests: the start of one existing test file the unit did not change (read at the base),
    and its skip helpers and markers. Neither is the unit's own test (L4-VER-002a)."""
    blocks: list[tuple[str, str]] = []
    if (found := base_test_header(wb.git, base_sha, changed, near)) is not None:
        blocks.append((f"{found[0]} (the start of an existing test file)", found[1]))
    if conventions:
        blocks.append(("project test conventions", conventions))
    return blocks


def _matches(globs: Sequence[str], path: str) -> bool:
    return any(glob_match(glob, path) for glob in globs)


def spec_blocks(wb: Workbench) -> list[tuple[str, str]]:
    """The unit's design and proposal, cut at `MAX_SPEC_CHARS` together, as data blocks after the code: a file that the
    spec says may change, or that the program writes itself (an event log), must not end up in a whole-folder
    comparison (wave C). Read as `collect_sources` does: a symlink or an oversized file is skipped."""
    found = dict(collect_sources(wb.ref.path))
    blocks, left = [], MAX_SPEC_CHARS
    for name in SPEC_FILES:
        if name in found and left > 0:
            blocks.append((name, found[name][:left]))
            left -= len(found[name])
    return blocks


def head_sources(wb: Workbench, base_sha: str, head: str) -> list[tuple[str, str]]:
    """The head text of the unit's changed Python modules outside the test and test-support globs, cut at a size:
    (path, text) blocks for the writer's prompt. No test, no support file, no git history."""
    tdd = wb.cfg.tdd
    raw = wb.git.run_bytes("diff", "--name-only", "-z", "--no-renames", "--diff-filter=AM", base_sha, head)
    blocks, total = [], 0
    for rel in sorted(p.decode("utf-8", "replace") for p in raw.split(b"\0") if p):
        if not rel.endswith(".py") or "/.l4/" in f"/{rel}" or _matches([*tdd.test_globs, *tdd.test_support_globs], rel):
            continue
        shown = wb.git.run("show", f"{head}:{rel}", check=False)
        if shown.returncode != 0:
            continue
        text = shown.stdout[:MAX_FILE_CHARS]
        if total + len(text) > MAX_SOURCE_CHARS:
            break
        total += len(text)
        blocks.append((rel, text))
    return blocks


@dataclass
class AuditOutcome:
    records: list[AuditRecord] = field(default_factory=list)
    accepted: list[Path] = field(default_factory=list)  # files to commit with the round's verifier tests
    findings: list[Finding] = field(default_factory=list)
    cost_usd: float = 0.0


def _minor(title: str, detail: str, criterion: str) -> Finding:
    return Finding(Severity.MINOR, title, detail, "deterministic", criterion)


def _ids_of(report_tests: Mapping[str, object], stem: str) -> list[str]:
    return sorted(i for i in report_tests if stem in i)


def run_audit(
    wb: Workbench,
    writer: LLMBackend,
    criteria: Mapping[str, Criterion],
    chosen: Sequence[str],
    skipped: Sequence[str],
    *,
    base_sha: str,
    head: str,
    round_no: int,
    timeout_s: int,
    emit: Callable[..., None],
) -> AuditOutcome:
    """Write, run and judge the audit tests of `chosen`. `RoleLimit` (a usage limit) and `RoleUnavailable` (the writer
    cannot run) propagate: the unit waits for capacity. `emit(type, **data)` records `verify.audit`."""
    out = AuditOutcome(records=[AuditRecord(cid, "skipped", reason="cap") for cid in skipped])
    sources = head_sources(wb, base_sha, head)
    conventions = test_conventions(wb.git, base_sha, wb.cfg)  # the base only: L4-VER-002a forbids the unit's tests
    changed = _changed_files(wb, base_sha, head)
    written: dict[str, str] = {}
    for cid in chosen:
        criterion = criteria[cid]
        near = test_path("audit", cid, round_no=round_no)
        blocks = [*sources, *spec_blocks(wb), *_style_blocks(wb, base_sha, changed, near, conventions)]
        retry_reason: str | None = None
        for _ in range(2):  # an invalid reply is retried once, with the reason
            reply = request_test(
                writer, kind="audit", criterion_id=cid, criterion_text=f"{criterion.alias}\n{criterion.text}",
                data_blocks=blocks, retry_reason=retry_reason, redact=wb.redactor.redact_text, timeout_s=timeout_s,
            )  # fmt: skip
            out.cost_usd += reply.cost_usd or 0.0
            if reply.status != "invalid" or not reply.detail:
                break
            retry_reason = reply.detail
        if reply.status == "limit" and reply.run is not None:
            raise RoleLimit(reply.run)
        if reply.status in ("limit", "error"):
            raise RoleUnavailable("verifier_agent", reply.detail or "the audit writer cannot answer")
        if reply.status == "ok" and reply.test is not None:
            rel = test_path("audit", cid, round_no=round_no)
            write_test_file(wb.worktree, rel, reply.test.code)
            written[cid] = rel
            continue
        status = "not_testable" if reply.status == "not_testable" else reply.status
        reason = reply.not_testable.reason if reply.not_testable else reply.detail
        out.records.append(AuditRecord(cid, status, reason=reason[:300]))
        if status != "not_testable":
            out.findings.append(_minor("an audit test could not be written", f"{status}: {reason[:200]}", cid))
    if written:
        collected: dict[str, tuple[str, str]] = {}
        _judge_written(wb, written, round_no, out, collected)
        if collected:
            _retry_collected(
                wb, writer, criteria, collected, out, round_no=round_no, timeout_s=timeout_s, blocks=sources
            )
        _lint_accepted(wb, writer, criteria, out, round_no=round_no, timeout_s=timeout_s, blocks=sources, emit=emit)
    for record in out.records:
        emit("verify.audit", round=round_no, criterion=record.criterion, status=record.status,
             path=record.test_path, tests=list(record.tests), reason=record.reason)  # fmt: skip
    return out


def _judge_written(
    wb: Workbench,
    written: Mapping[str, str],
    round_no: int,
    out: AuditOutcome,
    collected: dict[str, tuple[str, str]] | None = None,
) -> None:
    """Runs the round's audit tests in one gate run and records each file's fate. With `collected`, a file that failed
    to import when the tests were collected is not rejected yet: it is removed and `collected[cid] = (the error, the
    code)` is left for the writer's one retry (`_retry_collected`)."""
    gate = wb.run_gate("audit", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)
    report = gate.report
    candidates: dict[str, list[str]] = {}
    deferred: dict[str, str] = {}  # files only the collection error of another file kept from running
    interrupted = report is not None and any(
        f"test_l4_audit_c_{c.removeprefix('C-')}_r{round_no}" in e for c in written for e in report.collection_errors
    )
    for cid, rel in written.items():
        stem = f"test_l4_audit_c_{cid.removeprefix('C-')}_r{round_no}"
        ids = _ids_of(report.tests, stem) if report is not None else []
        broken = report is None or any(stem in e for e in report.collection_errors)
        statuses = {report.tests[i].status for i in ids} if report is not None else set()
        if collected is not None and report is not None and any(stem in e for e in report.collection_errors):
            code = (wb.worktree / rel).read_text(encoding="utf-8", errors="replace")
            collected[cid] = (_collection_error(gate.log_path, stem), code)
            (wb.worktree / rel).unlink(missing_ok=True)
        elif collected is not None and interrupted and not ids and not broken:
            deferred[cid] = rel  # pytest stops at a collection error: this file never ran, so it runs again below
        elif broken or not ids:
            why = "the audit test could not be collected" if report is not None else f"no report ({gate.reason})"
            _reject(wb, out, cid, rel, "rejected", why)
        elif statuses & {"failed", "error"}:
            failing = next(i for i in ids if report.tests[i].status in ("failed", "error"))  # type: ignore[union-attr]
            out.records.append(AuditRecord(cid, "failed", rel, tuple(ids), f"{failing} fails at head"))
            (wb.worktree / rel).unlink(missing_ok=True)
        elif statuses != {"passed"}:
            _reject(wb, out, cid, rel, "rejected", "the audit test was skipped")
        else:
            candidates[cid] = ids
    if deferred:
        _judge_written(wb, deferred, round_no, out)  # the broken file is gone: a plain run of the others
    if not candidates:
        return
    confirmation = confirm_pre_satisfied(wb, candidates)
    for cid, ids in candidates.items():
        rel = written[cid]
        if cid in confirmation.confirmed:
            out.records.append(AuditRecord(cid, "accepted", rel, tuple(ids)))
            out.accepted.append(wb.worktree / rel)
        else:
            why = confirmation.reason or "it passes when the project's functions answer their zero value"
            _reject(wb, out, cid, rel, "rejected", why, tuple(ids))


_COLLECTION_LINE = re.compile(r"^(E\s+.+|\w*(?:Error|Exception)\b.*)$")
_COLLECTING = re.compile(r"^_{3,} ERROR collecting (\S+) _{3,}$")
_SECTION_END = re.compile(r"^(?:_{3,}|={3,})")
MAX_COLLECTION_ERROR_CHARS = 600


def _own_section(lines: Sequence[str], stem: str) -> Sequence[str] | None:
    """The lines pytest printed under `ERROR collecting <the file of stem>`; None when it printed no such section."""
    for i, line in enumerate(lines):
        if (m := _COLLECTING.match(line.strip())) and stem in m.group(1):
            end = next((j for j in range(i + 1, len(lines)) if _SECTION_END.match(lines[j].strip())), len(lines))
            return lines[i + 1 : end]
    return None


def _collection_error(log_path: Path, stem: str) -> str:
    """What the test run printed for the audit file that could not be imported: its `E ` lines (a pytest collection
    error) from its own `ERROR collecting` section when there is one (two broken files must not see each other's
    error), else from the whole log, bounded. Empty log or unreadable: the plain fact."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")[-40_000:]
    except OSError:
        text = ""
    every = text.splitlines()
    own = _own_section(every, stem)
    picked = every if own is None else own
    lines = [m.group(1).strip() for line in picked if (m := _COLLECTION_LINE.match(line.strip()))]
    shown = "\n".join(dict.fromkeys(lines))[:MAX_COLLECTION_ERROR_CHARS]
    return shown or "the file could not be imported when the tests were collected"


def _collect_retry_reason(error: str, code: str) -> str:
    return (
        "The test you wrote could not be collected: importing the file failed, so no test in it ran. Return the same "
        "test with only what the output below names fixed (import what you use, import only names the shown sources "
        f"define), keeping what it asserts.\n\nCollection output:\n{error}\n\nThe test you wrote:\n{code}"
    )


def _retry_collected(
    wb: Workbench,
    writer: LLMBackend,
    criteria: Mapping[str, Criterion],
    collected: Mapping[str, tuple[str, str]],
    out: AuditOutcome,
    *,
    round_no: int,
    timeout_s: int,
    blocks: Sequence[tuple[str, str]],
) -> None:
    """The writer gets the collection error once (live wave D, W-D2). A test that still cannot be collected, or no
    test at all, is rejected: a minor finding, never a held criterion or a question."""
    for cid, (error, code) in collected.items():
        rel = test_path("audit", cid, round_no=round_no)
        criterion = criteria[cid]
        reply = request_test(
            writer, kind="audit", criterion_id=cid, criterion_text=f"{criterion.alias}\n{criterion.text}",
            data_blocks=blocks, retry_reason=_collect_retry_reason(error, code), redact=wb.redactor.redact_text,
            timeout_s=timeout_s,
        )  # fmt: skip
        out.cost_usd += reply.cost_usd or 0.0
        if reply.status == "limit" and reply.run is not None:
            raise RoleLimit(reply.run)
        if reply.status in ("limit", "error"):
            raise RoleUnavailable("verifier_agent", reply.detail or "the audit writer cannot answer")
        if reply.status == "ok" and reply.test is not None:
            write_test_file(wb.worktree, rel, reply.test.code)
            _judge_written(wb, {cid: rel}, round_no, out)  # judged like a new one; a second break is rejected
            continue
        why = f"the audit test could not be collected ({error.splitlines()[0][:150]}); the retry gave {reply.status}"
        out.records.append(AuditRecord(cid, "rejected", rel, (), why))
        out.findings.append(_minor("an audit test was rejected", why, cid))


def _reject(
    wb: Workbench, out: AuditOutcome, cid: str, rel: str, status: str, why: str, tests: tuple[str, ...] = ()
) -> None:
    out.records.append(AuditRecord(cid, status, rel, tests, why))
    out.findings.append(_minor("an audit test was rejected", why, cid))
    (wb.worktree / rel).unlink(missing_ok=True)


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "no output")[:MAX_LINT_REASON_CHARS]


def lint_failure(wb: Workbench, rel: str) -> str:
    """The output of the first `gates.lint` or `gates.typecheck` command that fails on the audit test `rel` (empty when
    every one passes). Each command runs through the workbench's gate runner, so the sandbox, the gate log and the
    protected-file restore are the ones of step 2. Any status but `pass` counts: a command that cannot run must not let
    an unlinted test through."""
    for name, commands in (("lint", wb.cfg.gates.lint), ("typecheck", wb.cfg.gates.typecheck)):
        for command in commands:
            result = wb.run_gate(f"{name}-audit", narrow_ruff_paths(command, [rel]) or command)
            if result.status != "pass":
                text = result.log_path.read_text(encoding="utf-8", errors="replace")[-20_000:]
                return lint_excerpt(text) or result.reason or f"`{command}` failed"
    return ""


def _lint_retry_reason(code: str, failure: str) -> str:
    return (
        "The test you wrote passed, but the project's lint (or type check) rejects its file. Return the same test with "
        "only what the output below names fixed, keeping what it asserts.\n\nLint output:\n"
        f"{failure}\n\nThe test you wrote:\n{code}"
    )


def _lint_accepted(
    wb: Workbench,
    writer: LLMBackend,
    criteria: Mapping[str, Criterion],
    out: AuditOutcome,
    *,
    round_no: int,
    timeout_s: int,
    blocks: Sequence[tuple[str, str]],
    emit: Callable[..., None],
) -> None:
    """Lints every accepted audit test (see the module docstring). Nothing to do without a lint or typecheck command."""
    if not (wb.cfg.gates.lint or wb.cfg.gates.typecheck):
        return
    for record in [r for r in out.records if r.status == "accepted"]:
        cid, rel = record.criterion, record.test_path
        failure = lint_failure(wb, rel)
        if not failure:
            continue
        reason = _first_line(failure)
        emit("verify.audit_lint", round=round_no, criterion=cid, outcome="failed", attempt=1, reason=reason)
        code = (wb.worktree / rel).read_text(encoding="utf-8", errors="replace")
        criterion = criteria[cid]
        reply = request_test(
            writer, kind="audit", criterion_id=cid, criterion_text=f"{criterion.alias}\n{criterion.text}",
            data_blocks=blocks, retry_reason=_lint_retry_reason(code, failure), redact=wb.redactor.redact_text,
            timeout_s=timeout_s,
        )  # fmt: skip
        out.cost_usd += reply.cost_usd or 0.0
        if reply.status == "limit" and reply.run is not None:
            raise RoleLimit(reply.run)
        if reply.status in ("limit", "error"):
            raise RoleUnavailable("verifier_agent", reply.detail or "the audit writer cannot answer")
        if reply.status == "ok" and reply.test is not None:
            write_test_file(wb.worktree, rel, reply.test.code)
            out.records.remove(record)  # judged afresh: it must still pass at head and fail against the zero values
            out.accepted = [p for p in out.accepted if p != wb.worktree / rel]
            _judge_written(wb, {cid: rel}, round_no, out)
            again = next((r for r in out.records if r.criterion == cid and r is not record), None)
            if again is None or again.status != "accepted":
                emit(
                    "verify.audit_lint", round=round_no, criterion=cid, outcome="not_accepted", attempt=2, reason=reason
                )
                continue  # `_judge_written` recorded why (failed at head holds the criterion; rejected is a finding)
            second = lint_failure(wb, rel)
            if not second:
                emit("verify.audit_lint", round=round_no, criterion=cid, outcome="fixed", attempt=2, reason="")
                continue
            reason = _first_line(second)
            record = again
        emit("verify.audit_lint", round=round_no, criterion=cid, outcome="rejected", attempt=2, reason=reason)
        out.records.remove(record)
        out.accepted = [p for p in out.accepted if p != wb.worktree / rel]
        _reject(wb, out, cid, rel, "rejected", f"{LINT_REJECTED} {reason}", record.tests)
