"""`verification.md` and `verdict.json` (SPEC 10.6, L4-VER-005), written on every verdict, FAIL included.

`<unit>/verification.md` is overwritten each round; `.l4/evidence/round-<n>/` keeps every round's copy and the
machine version (`l4/verdict@1`, named by the verifier design). Text that came from a judge, a gate or the repository
is flattened before it enters a table row or a list item, so it cannot add a row or start a section, and the whole
file is redacted before it is written.
M1: CI artifact links (the job's URL), TDD exemptions and `pre_adoption`
tasks (verifier 1.16).
"""

import contextlib
import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from l4.buildinfo import harness_commit
from l4.evidence.report import render_evidence_json
from l4.fsutil import atomic_write_bytes, reject_symlinks
from l4.redact import Redactor
from l4.state.ledger import LedgerCorrupt, LedgerEvent, read_ledger
from l4.verifier.types import (
    REPLY_OUTCOMES,
    CriterionEvidence,
    CriterionOutcome,
    Finding,
    GeneratedOutcome,
    VerifyResult,
)

VERDICT_SCHEMA_ID = "l4/verdict@1"
MAX_CELL_CHARS = 300
MAX_TESTS_LISTED = 50
_JUDGED_EVENTS = ("feedback.taken", "feedback.judged", "feedback.addressed", "feedback.not_addressed")


def _flat(text: object, limit: int = MAX_CELL_CHARS) -> str:
    one_line = " ".join(str(text).split())
    return (one_line[:limit] + "...") if len(one_line) > limit else one_line


def _cell(text: object) -> str:
    return _flat(text).replace("|", "\\|")


def _finding_line(f: Finding) -> str:
    gap = " (spec gap)" if f.spec_gap else ""
    where = f" (criterion {f.criterion})" if f.criterion else ""
    log = f" Log: `{f.log}`." if f.log else ""
    return f"- [{f.severity.value}, {f.source}] {_flat(f.title, 120)}{gap}{where}: {_flat(f.detail, 600)}{log}"


def _traceability_line(result: VerifyResult) -> str:
    ran = any(s.step == "4" and s.status in ("ok", "reused") for s in result.steps)
    if not ran:
        return "traceability: not checked (an earlier step failed)"
    covered = sum(e.state == "covered" for e in result.trace)
    return f"traceability: {covered}/{len(result.trace)} criteria covered by a discriminating test"


SNAPSHOT_LINK = ".l4-out/e2e/page.html"  # `gates.e2e.SNAPSHOT_RELPATH`: the page the head app served, a CI artefact
MAX_CODE_CHARS = 4_000


def _generated_for(result: VerifyResult, criterion: str) -> GeneratedOutcome | None:
    return next((g for g in result.generated if g.criterion == criterion), None)


def _test_cell(result: VerifyResult, e: CriterionEvidence) -> str:
    made = _generated_for(result, e.criterion)
    parts = []
    for t in e.tests:
        extra = ""
        if t.proof == "generated" and made is not None and t.id in made.tests:
            extra = f", base {made.base}, head {made.head}"
        parts.append(f"{t.id} ({t.status}, {t.proof}{extra}{'' if t.adequate else ', inadequate'})")
    return "; ".join(parts)


def _links(result: VerifyResult, criterion: str) -> str:
    made = _generated_for(result, criterion)
    links = [made.path, *made.artifacts] if made is not None and made.path else []
    if links and any(g.name.startswith("e2e") for g in result.gates):
        links.append(SNAPSHOT_LINK)
    return ", ".join(f"`{link}`" for link in links)


def _evidence_rows(result: VerifyResult) -> list[str]:
    s1 = {r.criterion: r for r in result.s1}
    columns = ["Id", "Criterion", "State", "Tests (status, proof)", "Not evidence"]
    columns += ["S1 p"] if result.s1 else []
    columns += ["Evidence links"] if result.generated else []
    rows = [f"| {' | '.join(columns)} |", f"|{'---|' * len(columns)}"]
    for e in result.trace:
        ignored = "; ".join(f"{t} ({why})" for t, why in e.ignored)
        cells = [e.criterion, e.alias, e.state, _test_cell(result, e) or "-", ignored or "-"]
        if result.s1:
            record = s1.get(e.criterion)
            cells.append("-" if record is None or record.p is None else f"{record.p:.2f}")
        if result.generated:
            cells.append(_links(result, e.criterion) or "-")
        rows.append(f"| {' | '.join(_cell(c) for c in cells)} |")
    return rows


def _generated_rows(result: VerifyResult) -> list[str]:
    rows = [
        "| Criterion | Status | Test | Base | Head | Attempts | Reason | Artefacts |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for g in result.generated:
        reason = f"{g.reason + '; ' if g.reason else ''}support: {g.support}" if g.support in ("base", "head") else ""
        cells = [
            g.criterion, g.status, g.path or "-", g.base or "-", g.head or "-", g.attempts, reason or g.reason or "-",
            ", ".join(g.artifacts) or "-",
        ]  # fmt: skip
        rows.append(f"| {' | '.join(_cell(c) for c in cells)} |")
    return rows


def _s1_rows(result: VerifyResult) -> list[str]:
    rows = ["| Criterion | Status | p | Model | Engine | Note |", "|---|---|---|---|---|---|"]
    for r in result.s1:
        note = r.reason or ("evidence cut to fit the budget" if r.truncated else "")
        p = "-" if r.p is None else f"{r.p:.3f}"
        cells = [r.criterion, r.status, p, r.model or "-", r.engine or "-", note or "-"]
        rows.append(f"| {' | '.join(_cell(c) for c in cells)} |")
    return rows


def _criterion_row(c: CriterionOutcome) -> str:
    return f"| {_cell(c.id)} | {_cell(c.alias)} | {_cell(c.judge or '-')} | {_cell(c.result)} | {_cell(c.reason)} |"


def _fix_lines(result: VerifyResult) -> list[str]:
    fix = result.fix
    assert fix is not None
    head = {
        "spawn": f"Fix unit {fix.ordinal} is created for these tasks:",
        "escalate": f"Escalated: {_flat(fix.reason, 300)}",
        "none": "No fix unit.",
    }[fix.action]
    tasks = [f"- {_flat(t, 300)}" for t in fix.tasks]
    return [head, *tasks, *(f"- not converted: {_flat(n, 300)}" for n in fix.not_converted)]


def feedback_lines(events: Sequence[LedgerEvent], round_no: int) -> list[str]:
    """The items taken or judged in round `round_no`, one line each (design D12). `feedback.taken`, `.addressed` and
    `.not_addressed` carry their round; `feedback.waiting` does not, so it belongs to the round whose verdict has not
    been written yet: after the verdict of the round before. The last event of an item wins."""
    start = 0
    for index, event in enumerate(events):
        round_of = event.data.get("round")
        if event.type == "verify.verdict" and isinstance(round_of, int) and round_of < round_no:
            start = index + 1
    found: dict[str, str] = {}
    for event in events[start:]:
        data = event.data
        if event.type == "feedback.waiting":
            why = str(data.get("reason") or "").replace("_", " ")
            ids = data.get("ids")
            for fid in ids if isinstance(ids, list) else []:
                found[str(fid)] = f"{fid}: waiting for the next round" + (f" ({why})" if why else "")
            continue
        if event.type not in _JUDGED_EVENTS or data.get("round") != round_no:
            continue
        fid = str(data.get("id") or "")
        evidence = _flat(data.get("evidence") or "", 300)
        if event.type == "feedback.taken":
            kind = f" ({_flat(data.get('kind') or '', 20)})" if data.get("kind") else ""
            found[fid] = f"{fid}{kind}: taken into {_flat(data.get('fix_unit') or '-', 80)}"
        elif event.type == "feedback.judged":  # the judge's yes; the item is closed by a PASS round only (review #14)
            found[fid] = f"{fid}: judged addressed, pending a PASS round" + (f": {evidence}" if evidence else "")
        elif event.type == "feedback.addressed":
            sha = f" at {str(data['sha'])[:10]}" if data.get("sha") else ""
            found[fid] = f"{fid}: addressed{sha}" + (f": {evidence}" if evidence else "")
        else:
            found[fid] = f"{fid}: not addressed" + (f": {evidence}" if evidence else "")
    return list(found.values())


def render_verification_md(result: VerifyResult) -> str:
    lines = [
        f"# Verification: {_flat(result.unit, 120)}: {result.verdict.value} (round {result.round})",
        "",
        _traceability_line(result),
        "",
        f"- Base: `{result.base_sha}`",
        f"- Head: `{result.head_sha}`",
        f"- Implementer profiles: {_flat(', '.join(result.implementer_profiles) or '-')}",
    ]
    judge = _flat(result.judge_profile or "-")
    model = f" ({_flat(result.judge_model)})" if result.judge_model else ""
    lines.append(
        f"- Judge: {judge}{model}, {result.judge_calls} call(s), prompt sha256 `{result.prompt_sha256 or '-'}`"
    )
    if result.judge_replies:
        counts = ", ".join(f"{name} {result.judge_replies.get(name, 0)}" for name in REPLY_OUTCOMES)
        lines.append(
            f"- Judge replies of {judge} (this unit, all rounds): {counts}; this round: {result.judge_reply or '-'}"
        )
    if result.independence is not None:
        lines.append(f"- {_flat(result.independence.line(), 600)}")
    if result.cost_usd is not None:
        lines.append(f"- Cost: ${result.cost_usd:.4f}")
    lines += ["", "## Ladder", "", "| Step | Name | Status | Seconds | Note |", "|---|---|---|---|---|"]
    lines += [f"| {s.step} | {s.name} | {s.status} | {s.seconds:.1f} | {_cell(s.note)} |" for s in result.steps]
    if result.gates:
        lines += ["", "## Gates", "", "| Gate | Status | Command | Log |", "|---|---|---|---|"]
        lines += [f"| {g.name} | {g.status} | `{_cell(g.command)}` | {_cell(g.log or '-')} |" for g in result.gates]
    if result.integrity is not None:
        lines += ["", "## Integrity", "", "| Check | Status | Note |", "|---|---|---|"]
        lines += [f"| {_cell(c.name)} | {c.status} | {_cell(c.note)} |" for c in result.integrity.checks]
        if result.integrity.declared:
            lines += ["", "Declared suppressions:"] + [f"- {_flat(d, 300)}" for d in result.integrity.declared]
        if result.integrity.human_protected:
            lines += ["", "## Protected paths changed by humans (allowed, L4-SEC-004)", ""]
            lines += [
                f"- `{_flat(c.path, 200)}`: "
                + ", ".join(f"{h.sha[:10]} by {_flat(h.author, 40)}" for h in c.commits[:5])
                for c in result.integrity.human_protected
            ]
        if result.integrity.human_tests:
            lines += ["", "## Test changes made by humans (allowed, L4-SEC-004)", ""]
            lines += [f"- {_flat(t, 300)}" for t in result.integrity.human_tests]
        if result.integrity.allowed_tests:
            lines += ["", "## Pre-existing tests changed with an allowance (L4-VER-031)", ""]
            lines += [f"- {_flat(t, 300)}" for t in result.integrity.allowed_tests]
        if result.integrity.test_awareness:
            lines += [
                "",
                "## Production code that may know about a test run (for the judge, L4-VER-039)",
                "",
            ]
            lines += [f"- {_flat(t, 300)}" for t in result.integrity.test_awareness]
        if result.integrity.mocked_support:
            lines += ["", "## Fixtures that patch the unit's code when a test requests them (L4-VER-037)", ""]
            lines += [f"- {_flat(t, 300)}" for t in result.integrity.mocked_support]
        if result.integrity.human_suppressions:
            lines += ["", "## Suppressions added by humans (allowed, listed: SPEC 2.10)", ""]
            lines += [f"- {_flat(t, 300)}" for t in result.integrity.human_suppressions]
        if result.integrity.human_scan:
            lines += ["", "## Support and runner-config changes made by humans (allowed, listed: SPEC 2.10)", ""]
            lines += [f"- {_flat(t, 300)}" for t in result.integrity.human_scan]
        if result.integrity.unfrozen:
            lines += ["", "## Tests unfrozen by human answers (allowed, L4-IMP-002)", ""]
            lines += [f"- {_flat(t, 300)}" for t in result.integrity.unfrozen]
    if result.trace:
        lines += ["", "## Traceability", ""] + _evidence_rows(result)
    if result.evidence is not None:
        lines += [""] + render_evidence_json(result.evidence)
    if result.generated:
        lines += ["", "## Generated UI tests", ""] + _generated_rows(result)
    if result.s1:
        lines += ["", "## S1 (recorded for calibration, never decides)", ""] + _s1_rows(result)
    if result.audit:
        lines += ["", "## Audit", "", "| Criterion | Status | Test | Support | Reason |", "|---|---|---|---|---|"]
        lines += [
            f"| {_cell(a.criterion)} | {a.status} | {_cell(a.test_path or '-')} | "
            f"{a.support if a.support in ('base', 'head') else '-'} | {_cell(a.reason or '-')} |"
            for a in result.audit
        ]
        if rejected := [a for a in result.audit if a.status == "rejected"]:
            lines += ["", "## Rejected audit tests", ""]
            lines += [f"- {_flat(a.criterion, 20)}: {_flat(a.reason or 'no reason', 300)}" for a in rejected]
    if result.human:
        lines += ["", "## Human verdicts", ""]
        lines += [
            f"- {_flat(v.question, 20)} {v.decision} {_flat(v.target, 20)} by {_flat(v.by, 40)}"
            + (f": {_flat(v.reason, 300)}" if v.reason else "")
            for v in result.human
        ]
    lines += ["", "## Criteria", ""]
    if result.criteria:
        lines += ["| Id | Criterion | Judge | Result | Reason |", "|---|---|---|---|---|"]
        lines += [_criterion_row(c) for c in result.criteria]
        for c in result.criteria:
            if c.counterexample is not None:
                lines.append(
                    f"- {c.id}: counterexample {c.counterexample.status}"
                    + (f" ({_flat(c.counterexample.note, 200)})" if c.counterexample.note else "")
                )
    else:
        lines.append("None judged.")
    lines += ["", "## Findings", ""]
    lines += [_finding_line(f) for f in result.findings] or ["None."]
    if result.fix is not None and (result.fix.action != "none" or result.fix.not_converted):
        lines += ["", "## Fix unit", ""] + _fix_lines(result)
    if result.feedback:
        lines += ["", "## Feedback", ""] + [f"- {_flat(f, 400)}" for f in result.feedback]
    if result.holds:
        lines += ["", "## Needs a human", ""] + [f"- {_flat(h, 300)}" for h in result.holds]
    if result.red_green:
        lines += ["", "## New tests (red then green, `task.red_ok` in the ledger)", ""]
        shown = sorted(result.red_green.items())[:MAX_TESTS_LISTED]
        lines += [
            f"- `{_flat(t, 200)}` (task {_flat(task, 40)}): {result.tests.get(t, 'not in the report')}"
            for t, task in shown
        ]
    if result.guards:
        lines += ["", "## Guard events", ""] + [f"- {_flat(g, 300)}" for g in result.guards]
    return "\n".join(lines) + "\n"


def _generated_json(g: GeneratedOutcome) -> dict[str, Any]:
    """The test the writer wrote is kept only when it was not accepted: an accepted one is in the repository."""
    data = dataclasses.asdict(g)
    data["tests"], data["artifacts"] = list(g.tests), list(g.artifacts)
    data["code"] = "" if g.accepted else g.code[:MAX_CODE_CHARS]
    if not data["code"]:
        del data["code"]
    return data


def verdict_json(result: VerifyResult) -> dict[str, Any]:
    return {
        "schema": VERDICT_SCHEMA_ID,
        "round": result.round,
        "verdict": result.verdict.value,
        "base_sha": result.base_sha,
        "head_sha": result.head_sha,
        "steps": [dataclasses.asdict(s) for s in result.steps],
        "gates": [dataclasses.asdict(g) for g in result.gates],
        "criteria": [{**dataclasses.asdict(c), "tests": list(c.tests)} for c in result.criteria],
        "findings": [{**dataclasses.asdict(f), "severity": f.severity.value} for f in result.findings],
        "holds": list(result.holds),
        "subject_sha": result.subject_sha,
        "family_criteria": [c.id for c in result.criteria],
        "reused_from": result.reused_from,
        "integrity": dataclasses.asdict(result.integrity) if result.integrity else None,
        "trace": [dataclasses.asdict(e) for e in result.trace],
        "audit": [dataclasses.asdict(a) for a in result.audit],
        "generated": [_generated_json(g) for g in result.generated],
        "s1": [dataclasses.asdict(r) for r in result.s1],
        "evidence": result.evidence,
        "human": [dataclasses.asdict(h) for h in result.human],
        "fix": dataclasses.asdict(dataclasses.replace(result.fix, plan=None)) if result.fix else None,
        "judge_verdict": result.judge_verdict,
        "cx_runs": {cid: dataclasses.asdict(run) for cid, run in result.cx_runs.items()},
        "tests": dict(result.tests),
        "red_green": dict(result.red_green),
        "guards": list(result.guards),
        "prompt_sha256": result.prompt_sha256,
        "template": result.prompt_template,
        "harness_commit": harness_commit(),
        "judge_calls": result.judge_calls,
        "judge_reply": result.judge_reply,
        "judge_replies": dict(result.judge_replies),
        "profiles": {"judge": result.judge_profile, "implementer": list(result.implementer_profiles)},
        "judge_model": result.judge_model,
        "independence": result.independence.to_json() if result.independence else None,
        "cost_usd": result.cost_usd,
    }


def write_round_evidence(unit_dir: Path, round_no: int, result: VerifyResult, redactor: Redactor) -> list[Path]:
    """Writes the files (a fourth, `evidence.json`, when the round collected evidence) and returns their
    paths. A symlinked `.l4`, `evidence` or round directory raises
    `UnsafeFile`: the unit directory is repository content and the files must land inside the checkout."""
    round_dir = f"round-{round_no}"
    reject_symlinks(unit_dir, ".l4", "evidence", round_dir)
    if not result.feedback:  # the round's `feedback.*` events, as the ledger holds them now (L4-FBK-011)
        with contextlib.suppress(LedgerCorrupt):  # a corrupt ledger: no section
            result = dataclasses.replace(result, feedback=feedback_lines(read_ledger(unit_dir).events, round_no))
    target = unit_dir / ".l4" / "evidence" / round_dir
    target.mkdir(parents=True, exist_ok=True)
    scrub = redactor.scrub_for_commit  # the forge host is `<forge>` in what is committed (L4-OBS-002)
    markdown = scrub(redactor.redact_text(render_verification_md(result))).encode("utf-8")
    machine = scrub(json.dumps(redactor.redact_obj(verdict_json(result)), indent=2, ensure_ascii=False) + "\n")
    files = [
        (unit_dir / "verification.md", markdown),
        (target / "verification.md", markdown),
        (target / "verdict.json", machine.encode("utf-8")),
    ]
    if result.evidence is not None:
        document = scrub(json.dumps(redactor.redact_obj(result.evidence), indent=2, ensure_ascii=False) + "\n")
        files.append((target / "evidence.json", document.encode("utf-8")))
    for path, data in files:
        atomic_write_bytes(path, data)
    return [path for path, _ in files]
