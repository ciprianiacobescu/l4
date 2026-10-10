import json

from l4.evidence.diffcov import DiffCoverage, FunctionCoverage
from l4.evidence.report import evidence_json, render_evidence_section
from l4.evidence.scope import FileScope, ScopeOutcome
from l4.evidence.testsran import TestsRanOutcome, TestsSummary

SCOPE = ScopeOutcome(
    files=[
        FileScope("src/shop/pricing.py", "shop", "code", "relevant", "named in the spec"),
        FileScope("src/inventory/a|b.py", "inventory", "code", "out_of_scope", "module `inventory` is not named"),
        FileScope("pyproject.toml", None, "root", None, "root file, not judged"),
    ],
    holds=["scope: `src/inventory/a|b.py` changes module `inventory`, which the spec does not name"],
    declared=["src/shop/pricing.py"],
)
DC = DiffCoverage(
    50.0,
    [
        FunctionCoverage("src/shop/pricing.py", "apply", "covered", 2, 2, ("test_x.test_a",)),
        FunctionCoverage("src/inventory/a.py", "reserve", "uncovered", 3, 0),
    ],
)
RAN = TestsRanOutcome([], True, TestsSummary(total=5, passed=4, skipped=1, new=2, new_passed=2))


def test_section_is_stable_and_lists_majors_first():
    first = render_evidence_section(SCOPE, DC, RAN)
    assert first == render_evidence_section(SCOPE, DC, RAN)
    text = "\n".join(first)
    assert first[0] == "## Evidence"
    assert text.index("Needs attention") < text.index("### Files") < text.index("### Changed functions")
    assert text.index("### Changed functions") < text.index("### Tests")
    attention = text[text.index("Needs attention") : text.index("### Files")]
    assert "src/inventory/a\\|b.py" in attention and "src/inventory/a.py::reserve" in attention
    assert "a|b" not in text.replace("a\\|b", "")  # a pipe in a path cannot break the table
    assert "| `src/shop/pricing.py` | shop | relevant |" in text
    assert "4 of 5 passed" in text and "2 of 2 new tests passed" in text


def test_clean_and_missing_parts():
    clean = ScopeOutcome(files=[FileScope("src/a.py", "a", "code", "relevant", "named")])
    text = "\n".join(render_evidence_section(clean, None, None))
    assert "Nothing needs attention" in text and "not run" in text
    skipped = ScopeOutcome(skipped=True, note="the spec names no path or module in backticks")
    assert "names no path or module" in "\n".join(render_evidence_section(skipped, None, None))


def test_evidence_json_shape():
    data = evidence_json(SCOPE, DC, RAN)
    assert json.loads(json.dumps(data)) == data
    assert data["schema"] == "l4/evidence@1"
    assert data["scope"]["files"][1] == {
        "path": "src/inventory/a|b.py", "module": "inventory", "kind": "code", "label": "out_of_scope",
        "reason": "module `inventory` is not named",
    }  # fmt: skip
    assert data["diff_coverage"]["percent"] == 50.0 and data["diff_coverage"]["functions"][1]["label"] is False
    assert data["tests_ran"]["tests_ok"] is True and data["tests_ran"]["summary"]["new"] == 2
    assert evidence_json(None, None, None) == {"schema": "l4/evidence@1", "holds": [], "items": {}, "scope": None,
                                               "diff_coverage": None, "tests_ran": None}  # fmt: skip


def test_coverage_that_was_not_measured_needs_attention():
    """Under `warn` a `not_run` is no hold (D4), so the section is the only place a reader learns that the changed
    code was never measured: it must not also say that nothing needs attention."""
    clean = ScopeOutcome(files=[FileScope("src/a.py", "a", "code", "relevant", "named")])
    reason = "the coverage plugin wrote no status"
    dc = DiffCoverage(0.0, [FunctionCoverage("src/a.py", "f", "not_run")], "not_run", reason)
    text = "\n".join(render_evidence_section(clean, dc, RAN))
    attention = text[text.index("### Needs attention") : text.index("### Files")]
    assert "diff coverage not measured: the coverage plugin wrote no status" in attention
    assert "Nothing needs attention" not in attention


def test_not_applicable_and_mixed_coverage_say_not_measured_and_survive_verdict_json():
    from l4.evidence.report import render_evidence_json

    reason = "diff coverage measures python only; changed code outside it: a.ts"
    na = DiffCoverage(0.0, status="not_applicable", reason=reason, other_files=("a.ts",))
    text = "\n".join(render_evidence_section(SCOPE, na, RAN))
    attention = text[text.index("Needs attention") : text.index("### Files")]
    assert "diff coverage" not in attention  # no "Needs attention" line: it is not a failure
    assert "Diff coverage not measured: diff coverage measures python only; changed code outside it: a.ts" in text
    mixed = DiffCoverage(100.0, other_files=("a.ts", "b.tsx"))
    mixed_text = "\n".join(render_evidence_section(SCOPE, mixed, RAN))
    assert "100.0% of the changed executable lines ran." in mixed_text
    assert "Not measured: diff coverage measures python only; changed code outside it: a.ts, b.tsx" in mixed_text
    for dc in (na, mixed):
        data = json.loads(json.dumps(evidence_json(SCOPE, dc, RAN)))
        assert data["diff_coverage"]["other_files"] == list(dc.other_files)
        assert render_evidence_json(data) == render_evidence_section(SCOPE, dc, RAN)
