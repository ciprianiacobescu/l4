"""L4-GAT-005: a test gate that lists several reports reads every one of them (SCN-GAT-05..07)."""

import sys
from pathlib import Path

from l4.gates.runner import GateSpec

from .test_runner import go, work  # noqa: F401  (the fixture)

PASSED = '<testsuite><testcase classname="{c}" name="{n}"/></testsuite>'
FAILED = (
    '<testsuite><testcase classname="{c}" name="{n}"><failure message="assert 1 == 2">E</failure></testcase>'
    "</testsuite>"
)


def _writes(tmp: Path, reports: dict[str, str]) -> str:
    """A gate command that writes `reports` (relative path -> junit text) and exits 0."""
    script = tmp / "write_reports.py"
    lines = ["import pathlib"]
    for rel, text in reports.items():
        lines.append(f"p = pathlib.Path({rel!r}); p.parent.mkdir(parents=True, exist_ok=True); p.write_text({text!r})")
    script.write_text("\n".join(lines) + "\n")
    return f"{sys.executable} {script}"


def test_every_listed_report_is_read(work):  # noqa: F811
    tmp, _ = work
    cmd = _writes(tmp, {
        ".l4-out/a.xml": PASSED.format(c="apps.api.tests.test_a", n="test_one"),
        ".l4-out/b.xml": PASSED.format(c="packages.models.tests.test_b", n="test_two"),
    })  # fmt: skip
    result = go(work, GateSpec("test", cmd, reports=(".l4-out/a.xml", ".l4-out/b.xml")))
    assert result.status == "pass", result.reason
    assert result.report is not None
    assert set(result.report.tests) == {"apps.api.tests.test_a::test_one", "packages.models.tests.test_b::test_two"}


def test_a_listed_report_that_is_missing_fails_the_gate(work):  # noqa: F811
    tmp, _ = work
    cmd = _writes(tmp, {".l4-out/a.xml": PASSED.format(c="tests.test_a", n="test_one")})
    result = go(work, GateSpec("test", cmd, reports=(".l4-out/a.xml", ".l4-out/b.xml")))
    assert (result.status, result.reason) == ("fail", "report missing: .l4-out/b.xml")


def test_a_test_in_two_reports_keeps_its_worse_result(work):  # noqa: F811
    tmp, _ = work
    cmd = _writes(tmp, {
        ".l4-out/a.xml": PASSED.format(c="tests.test_a", n="test_one"),
        ".l4-out/b.xml": FAILED.format(c="tests.test_a", n="test_one"),
    })  # fmt: skip
    result = go(work, GateSpec("test", cmd, reports=(".l4-out/a.xml", ".l4-out/b.xml")))
    assert result.report is not None
    assert result.report.tests["tests.test_a::test_one"].status == "failed"  # the gate's verdict stays the exit code's
