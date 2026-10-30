"""What a round leaves behind and what the next one can take from it (SPEC L4-VER-011, design D4, contract C9).

`subject_sha` is the last commit that is neither the harness's evidence nor a human's answer: it does not carry
`L4-Phase: verifying` or `L4-Phase: lessons` and it touches a path other than the unit's harness-owned files
(`questions.md`, `verification.md`, `.l4/**`) and `.serena/memories/harness/**`. A commit with two or more parents
(the base merge of step 0, `chore(<unit>): merge <base>@<sha> ... L4-Phase: verifying`) is never skipped for its phase:
its first-parent diff decides, so a merge that brings code is a new subject (L4-VER-011) and one that brings nothing,
or only harness-owned files, is not. While it and the family's set of
criterion ids are unchanged, a round that follows a NEEDS_HUMAN one reuses that round's steps 0-9 from its
`verdict.json` and only aggregates again with the human verdicts: no gate run and no judge call (`reusable`).
`commit_verifier_tests` makes the one commit per round for the tests the verifier wrote (audit tests, M1.5's
generated tests).
"""

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from l4.fsutil import UnsafeFile, read_regular_file
from l4.implementer.workbench import Workbench, clip_subject
from l4.security.protected import HumanChange, HumanCommit
from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers
from l4.verifier.report import VERDICT_SCHEMA_ID
from l4.verifier.types import (
    AuditRecord,
    CounterexampleRun,
    CriterionEvidence,
    Finding,
    GateLine,
    GeneratedOutcome,
    IntegrityCheck,
    IntegrityReport,
    S1Record,
    Severity,
    StepRecord,
    TracingTest,
    Verdict,
    VerifyResult,
)

if TYPE_CHECKING:
    from l4.verifier.selection import Independence

log = logging.getLogger("l4.verify")

MAX_VERDICT_BYTES = 8 * 1024 * 1024
MAX_COMMITS_SCANNED = 200
SKIPPED_PHASES = frozenset({"verifying", "lessons"})
HARNESS_MEMORY = ".serena/memories/harness/"


def _harness_owned(path: str, unit_dirs: Sequence[str]) -> bool:
    if path.startswith(HARNESS_MEMORY):
        return True
    return any(path in (f"{d}/questions.md", f"{d}/verification.md") or path.startswith(f"{d}/.l4/") for d in unit_dirs)


def subject_sha(git: Git, head: str, unit_dirs: Sequence[str]) -> str:
    """See the module docstring. `unit_dirs`: the unit directories of the family, relative to the repository. A history
    with no such commit gives `head`."""
    fmt = "%H%x01%P%x01%(trailers:key=L4-Phase,valueonly,separator=%x2c)%x02"
    log_text = git.run("log", "--first-parent", f"--max-count={MAX_COMMITS_SCANNED}", f"--format={fmt}", head).stdout
    for record in filter(None, (r.strip("\n") for r in log_text.split("\x02"))):
        sha, parents, phase = (part.strip() for part in record.split("\x01"))
        merge = len(parents.split()) >= 2
        if phase in SKIPPED_PHASES and not merge:
            continue
        if merge:  # `diff-tree -m` lists the diff against every parent: only the first one (the unit's own line) counts
            raw = git.run_bytes("diff", "--name-only", "-z", "--no-renames", f"{sha}^1", sha)
        else:
            raw = git.run_bytes("diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "--root", sha)
        paths = [p.decode("utf-8", "replace") for p in raw.split(b"\0") if p]
        if any(not _harness_owned(p, unit_dirs) for p in paths):
            return sha
    return head


def commit_verifier_tests(wb: Workbench, paths: Sequence[Path], round_no: int) -> str | None:
    """`test(<unit>): verifier round <n> [skip ci]` with `L4-Phase: verifying`: the tests the verifier wrote in this
    round, in one commit, made after steps 4a and 5. None when there is nothing to commit."""
    if not paths:
        return None
    root = wb.worktree.resolve()
    wb.git.run("add", "--", *(p.resolve().relative_to(root).as_posix() for p in paths))
    if wb.git.run("diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    trailers = CommitTrailers(unit=wb.ref.id, run_id=wb.run_id, iteration=max(wb.iteration, 1), phase="verifying")
    return wb.git.commit(clip_subject(f"test({wb.ref.name}): verifier round {round_no} [skip ci]"), trailers)


# --- reading a round back -----------------------------------------------------------------------------------------


def read_verdict(unit_dir: Path, round_no: int) -> dict[str, Any] | None:
    """`.l4/evidence/round-<n>/verdict.json` of the unit directory, or None when it is missing, a symlink, too big
    or not a verdict object."""
    path = unit_dir / ".l4" / "evidence" / f"round-{round_no}" / "verdict.json"
    try:
        data = json.loads(read_regular_file(path, limit=MAX_VERDICT_BYTES))
    except (FileNotFoundError, UnsafeFile, ValueError, OSError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == VERDICT_SCHEMA_ID else None


def reusable(prev: Mapping[str, Any] | None, subject: str, criterion_ids: Sequence[str]) -> bool:
    """The previous round may be reused when it ended NEEDS_HUMAN on the same subject and the same criteria."""
    return (
        prev is not None
        and prev.get("verdict") == Verdict.NEEDS_HUMAN.value
        and prev.get("subject_sha") == subject
        and sorted(prev.get("family_criteria") or []) == sorted(criterion_ids)
        and bool(prev.get("subject_sha"))
    )


def _finding(d: Mapping[str, Any]) -> Finding:
    return Finding(
        Severity(d["severity"]), d["title"], d["detail"], d["source"], d.get("criterion"), d.get("log"),
        bool(d.get("spec_gap")), d.get("suggested_fix", ""), d.get("id", ""),
    )  # fmt: skip


def stored_finding(prev: Mapping[str, Any] | None, target: str) -> Finding | None:
    """The finding `target` of a stored round (`read_verdict`), or None: no record, or no readable finding with that
    id. The record is data from the branch: an entry this harness cannot read is skipped, never raised."""
    entries = prev.get("findings") if prev is not None else None
    for d in entries if isinstance(entries, list) else []:
        try:
            found = _finding(d)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if found.id == target:
            return found
    return None


def _evidence(d: Mapping[str, Any]) -> CriterionEvidence:
    def test(t: Mapping[str, Any]) -> TracingTest:
        return TracingTest(
            t["id"], t["status"], t["proof"], bool(t.get("adequate", True)), str(t.get("note") or ""),
            int(t.get("over_cap") or 0),
        )  # fmt: skip

    tests = tuple(test(t) for t in d["tests"])
    capped = tuple(test(t) for t in d.get("capped") or [])
    ignored = tuple((str(a), str(b)) for a, b in d.get("ignored", []))
    return CriterionEvidence(d["criterion"], d["alias"], d["state"], tests, ignored, d.get("held", ""), capped)


def _independence(d: Any) -> "Independence | None":
    """M1.2's record of the judge whose step 9 the round reuses (its `to_json`); None when the round had none."""
    from l4.verifier.selection import Independence, Party  # selection imports the agent factory

    if not isinstance(d, Mapping) or not isinstance(d.get("judge"), Mapping):
        return None
    fields = ("profile", "vendor", "model", "provenance", "served")

    def party(p: Mapping[str, Any]) -> Party:
        listed = {k: tuple(str(v) for v in p.get(k) or ()) for k in ("vendors", "routed_models")}
        return Party(**{k: p.get(k) for k in fields}, **listed)

    return Independence(str(d.get("mode", "")), party(d["judge"]), tuple(party(p) for p in d.get("implementers", [])))


def _generated(d: Mapping[str, Any]) -> GeneratedOutcome:
    return GeneratedOutcome(**{**d, "tests": tuple(d.get("tests", ())), "artifacts": tuple(d.get("artifacts", ()))})


def restore_round(prev: Mapping[str, Any], unit: str, round_no: int) -> VerifyResult:
    """A `VerifyResult` for `round_no` that holds what steps 0-9 of the previous round found. Its criteria, its
    verdict and the human verdicts are left for the caller to aggregate again; its steps read `reused (round n)`."""
    profiles = prev.get("profiles") or {}
    result = VerifyResult(
        unit, round_no, Verdict.NEEDS_HUMAN, prev.get("base_sha", ""), prev.get("head_sha", ""),
        judge_profile=profiles.get("judge", ""), implementer_profiles=list(profiles.get("implementer", [])),
        judge_model=prev.get("judge_model"), judge_calls=int(prev.get("judge_calls") or 0),
        judge_reply=prev.get("judge_reply", ""), judge_replies=dict(prev.get("judge_replies") or {}),
        prompt_sha256=prev.get("prompt_sha256", ""), prompt_template=prev.get("template", ""),
        cost_usd=prev.get("cost_usd"),
        tests=dict(prev.get("tests") or {}), red_green=dict(prev.get("red_green") or {}),
        guards=list(prev.get("guards") or []), judge_verdict=prev.get("judge_verdict"),
        subject_sha=prev.get("subject_sha", ""), reused_from=int(prev.get("round") or 0),
    )  # fmt: skip
    result.gates = [GateLine(**g) for g in prev.get("gates", [])]
    result.findings = [_finding(f) for f in prev.get("findings", [])]
    result.failures = {str(i): {str(k): str(v) for k, v in r.items()} for i, r in (prev.get("failures") or {}).items()}
    result.failures_dropped = int(prev.get("failures_dropped") or 0)
    result.e2e_tests = [str(i) for i in prev.get("e2e_tests") or []]
    result.holds = list(prev.get("holds") or [])
    result.hold_views = {str(h): dict(v) for h, v in (prev.get("hold_views") or {}).items()}
    result.judge_parts = [dict(r) for r in prev.get("judge_parts") or []]
    result.judge_files = [list(r) for r in prev.get("judge_files") or []]
    result.judge_followups = [dict(r) for r in prev.get("judge_followups") or []]
    result.judge_split = {str(cid): dict(r) for cid, r in (prev.get("judge_split") or {}).items()}
    result.cx_runs = {cid: CounterexampleRun(**run) for cid, run in (prev.get("cx_runs") or {}).items()}
    result.trace = [_evidence(e) for e in prev.get("trace", [])]
    result.audit = [
        AuditRecord(**{**a, "tests": tuple(a.get("tests", ())), "support_files": tuple(a.get("support_files", ()))})
        for a in prev.get("audit", [])
    ]
    result.generated = [_generated(g) for g in prev.get("generated", [])]
    result.s1 = [S1Record(**r) for r in prev.get("s1", [])]
    result.evidence = prev.get("evidence")
    result.independence = _independence(prev.get("independence"))
    integrity = prev.get("integrity")
    if integrity:
        result.integrity = IntegrityReport(
            [IntegrityCheck(**c) for c in integrity.get("checks", [])],
            [_finding(f) for f in integrity.get("findings", [])],
            list(integrity.get("declared", [])),
            [
                HumanChange(c["path"], tuple(HumanCommit(**k) for k in c.get("commits", [])))
                for c in integrity.get("human_protected", [])
            ],
            list(integrity.get("human_tests", [])),
            list(integrity.get("unfrozen", [])),
            list(integrity.get("human_suppressions", [])),
            list(integrity.get("human_scan", [])),
            list(integrity.get("human_config", [])),
            list(integrity.get("allowed_tests", [])),
            list(integrity.get("mocked_support", [])),
            integrity.get("base_tests"),
            list(integrity.get("test_awareness", [])),
        )
    result.steps = [
        StepRecord(s["step"], s["name"], "reused" if s["status"] == "ok" else s["status"], 0.0, _reused_note(s, prev))
        for s in prev.get("steps", [])
        if s["step"] != "10"
    ]
    return result


def _reused_note(step: Mapping[str, Any], prev: Mapping[str, Any]) -> str:
    return f"reused (round {prev.get('round')})" if step["status"] == "ok" else str(step.get("note", ""))
