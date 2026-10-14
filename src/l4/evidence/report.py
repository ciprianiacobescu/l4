"""The "Evidence" section of `verification.md` and the `evidence` key of `verdict.json` (`l4/evidence@1`).

What needs a human's eye comes first; the tables follow in a fixed order, so two renders of the same evidence are
byte-identical. Paths come from repository content: pipes and line breaks are escaped before they reach a table.
"""

from dataclasses import asdict
from typing import Any

from l4.evidence.diffcov import DiffCoverage, FunctionCoverage
from l4.evidence.scope import FileScope, ScopeOutcome
from l4.evidence.testsran import TestsRanOutcome, TestsSummary
from l4.verifier.types import Finding, Severity

SCHEMA = "l4/evidence@1"


def _cell(text: object) -> str:
    return str(text).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _attention(scope: ScopeOutcome | None, dc: DiffCoverage | None, ran: TestsRanOutcome | None) -> list[str]:
    items: list[str] = []
    if scope:
        items += [
            f"- out of scope: `{_cell(f.path)}` (module `{_cell(f.module)}`)"
            for f in scope.files
            if f.label == "out_of_scope"
        ]
    if dc and dc.status == "not_run":  # under `warn` no hold says it (D4): the reader learns it here
        items.append(f"- diff coverage not measured: {_cell(dc.reason)}")
    if dc:
        items += [
            f"- changed code not run by tests: `{_cell(f.path)}::{_cell(f.qualname)}` ({f.status})"
            for f in dc.functions
            if f.status in ("uncovered", "partly")
        ]
    if ran:
        items += [f"- {f.severity.value}: {f.title}: {_cell(f.detail)}" for f in ran.findings]
        if not ran.label and not ran.findings:
            items.append("- tests are not all green (a failed or errored test, or a new test that did not pass)")
    return items or ["Nothing needs attention."]


def render_evidence_section(
    scope: ScopeOutcome | None, dc: DiffCoverage | None, ran: TestsRanOutcome | None
) -> list[str]:
    out = ["## Evidence", "", "### Needs attention", "", *_attention(scope, dc, ran), "", "### Files", ""]
    if scope is None:
        out.append("Scope check not run.")
    elif scope.skipped:
        out.append(f"Scope not judged: {_cell(scope.note)}")
    else:
        out += ["| Path | Module | Label | Why |", "|---|---|---|---|"]
        out += [
            f"| `{_cell(f.path)}` | {_cell(f.module or '')} | {f.label or 'none'} | {_cell(f.reason)} |"
            for f in sorted(scope.files, key=lambda f: f.path)
        ]
    out += ["", "### Changed functions", ""]
    if dc is None:
        out.append("Diff coverage not run.")
    elif dc.status in ("not_run", "not_applicable"):
        out.append(f"Diff coverage not measured: {_cell(dc.reason)}")
    else:
        out += [f"{dc.percent}% of the changed executable lines ran.", ""]
        if dc.other_files:
            out += [f"Not measured: {_cell(dc.outside_note)}", ""]
        if dc.unmeasured_files:
            out += [
                "Not measured (root-level files are not coverage sources; no label, outside the percentage): "
                + ", ".join(f"`{_cell(p)}`" for p in dc.unmeasured_files),
                "",
            ]
        out += ["| Function | Status | Lines run | Tests |"]
        out.append("|---|---|---|---|")
        out += [
            f"| `{_cell(f.path)}::{_cell(f.qualname)}` | {f.status} | {f.executed}/{f.executable} |"
            f" {_cell(', '.join(f.tests))} |"
            for f in sorted(dc.functions, key=lambda f: (f.path, f.qualname))
        ]
    out += ["", "### Tests", ""]
    if ran is None:
        out.append("Tests-ran check not run.")
    else:
        s = ran.summary
        out.append(f"{s.passed} of {s.total} passed, {s.failed} failed, {s.errored} errored, {s.skipped} skipped.")
        out.append(f"{s.new_passed} of {s.new} new tests passed.")
        if s.skipped_unchanged:
            out.append(
                "Skipped in files the unit did not touch: " + ", ".join(f"`{_cell(i)}`" for i in s.skipped_unchanged)
            )
    return out


def evidence_json(
    scope: ScopeOutcome | None,
    dc: DiffCoverage | None,
    ran: TestsRanOutcome | None,
    *,
    holds: list[dict[str, Any]] | None = None,
    items: dict[str, str] | None = None,
) -> dict[str, Any]:
    """`holds`: every hold with its id, kind and subjects; `items`: `<question set>|<subject>` -> S1 item key. Both let
    a later round map a human's verdict on a hold to a label from this file alone."""
    return {
        "schema": SCHEMA,
        "holds": holds or [],
        "items": dict(sorted((items or {}).items())),
        "scope": None
        if scope is None
        else {
            "declared": list(scope.declared),
            "skipped": scope.skipped,
            "note": scope.note,
            "holds": list(scope.holds),
            "files": [asdict(f) for f in scope.files],
        },
        "diff_coverage": None
        if dc is None
        else {
            "status": dc.status,
            "reason": dc.reason,
            "percent": dc.percent,
            "unmeasured_files": list(dc.unmeasured_files),
            "other_files": list(dc.other_files),
            "functions": [{**asdict(f), "tests": list(f.tests), "label": f.label} for f in dc.functions],
        },
        "tests_ran": None
        if ran is None
        else {
            "tests_ok": ran.label,
            "summary": {**asdict(ran.summary), "skipped_unchanged": list(ran.summary.skipped_unchanged)},
            "findings": [{"severity": f.severity.value, "title": f.title, "detail": f.detail} for f in ran.findings],
        },
    }


def render_evidence_json(data: dict[str, Any]) -> list[str]:
    """The section for `evidence_json` output, so that a round resumed from `verdict.json` prints what the round did."""
    scope = data.get("scope")
    dc = data.get("diff_coverage")
    ran = data.get("tests_ran")
    scope_out = (
        None
        if scope is None
        else ScopeOutcome(
            note=scope["note"],
            skipped=scope["skipped"],
            declared=list(scope["declared"]),
            files=[FileScope(**f) for f in scope["files"]],
        )  # fmt: skip
    )
    dc_out = (
        None
        if dc is None
        else DiffCoverage(
            dc["percent"],
            [
                FunctionCoverage(
                    f["path"], f["qualname"], f["status"], f["executable"], f["executed"], tuple(f.get("tests", ()))
                )
                for f in dc["functions"]
            ],
            dc["status"],
            dc["reason"],
            tuple(dc["unmeasured_files"]),
            tuple(dc.get("other_files", ())),
        )  # fmt: skip
    )
    ran_out = (
        None
        if ran is None
        else TestsRanOutcome(
            [
                Finding(Severity(f["severity"]), f["title"], f["detail"], "deterministic")
                for f in ran.get("findings", [])
            ],
            ran["tests_ok"],
            TestsSummary(**{**ran["summary"], "skipped_unchanged": tuple(ran["summary"]["skipped_unchanged"])}),
        )  # fmt: skip
    )
    return render_evidence_section(scope_out, dc_out, ran_out)
