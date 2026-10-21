"""The excerpt of a red job's log (ci-evidence D1, D2, D4, D5; L4-VER-061, L4-VER-063)."""

import ast
from datetime import UTC, datetime
from pathlib import Path

from l4.forge import logexcerpt
from l4.forge.base import clip_log
from l4.forge.logexcerpt import (
    ActionsStep,
    actions_excerpt,
    actions_failed_step,
    ranked_summary_lines,
    section_excerpt,
    summary_lines,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ci_logs"
BOM = "﻿"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def stamped(*lines: str, start: str = "2026-10-20T10:00:00", bom: bool = True) -> str:
    """A log whose lines carry the runner's timestamp, one second apart from `start`."""
    base = datetime.fromisoformat(start)
    out = []
    for n, text in enumerate(lines):
        moment = datetime.fromtimestamp(base.replace(tzinfo=UTC).timestamp() + n, UTC)
        out.append(f"{moment.strftime('%Y-%m-%dT%H:%M:%S')}.1234567Z {text}")
    return (BOM if bom else "") + "\n".join(out) + "\n"


def at(second: int) -> datetime:
    return datetime(2026, 10, 20, 10, 0, second, tzinfo=UTC)


INCIDENT_STEPS = [
    ActionsStep("Set up job", "success", at(0)),
    ActionsStep("Run actions/checkout@v4", "success", at(5)),
    ActionsStep("tests", "failure", datetime(2026, 10, 20, 10, 0, 19, tzinfo=UTC)),
    ActionsStep("Post Run actions/checkout@v4", "success", datetime(2026, 10, 20, 10, 4, 4, tzinfo=UTC)),
]


def test_the_incident_gives_the_failing_step() -> None:
    result = actions_excerpt(fixture("github-pytest-failure.log"), INCIDENT_STEPS)
    lines = result.text.split("\n")
    assert lines[0] == "Run uv run pytest -q"
    assert "FAILED tests/test_cli.py::test_help - AssertionError" in result.text
    assert "1 failed, 2277 passed in 312.40s (0:05:12)" in result.text
    assert "E       AssertionError: assert 'run' in" in result.text
    assert lines[-1] == "Error: Process completed with exit code 1."
    for absent in ("Post job cleanup.", "Node.js 20", "UV_FROZEN", "2026-10-20T", BOM, "GITHUB_TOKEN"):
        assert absent not in result.text
    assert result.failed_step == "tests"
    assert len(result.text) <= 3000


def test_the_first_failed_step_is_the_anchor() -> None:
    """SCN-VER-218: the first failed step is the anchor, not an `always()` step after it."""
    result = actions_excerpt(fixture("github-two-failed-steps.log"), None)
    assert result.text.split("\n")[0].startswith("Run git fetch")
    assert "fatal: could not read Username" in result.text
    assert "Error: Process completed with exit code 128." in result.text
    assert "exit code 127" not in result.text
    assert result.failed_step is not None and result.failed_step.startswith("Run git fetch")


def test_an_annotation_does_not_cut_the_step() -> None:
    """SCN-VER-219: an annotation in the middle of a step does not cut the step."""
    body = ["##[group]Run pytest", "pytest", "##[endgroup]", "##[error]tests/test_a.py:3: assert 1 == 2"]
    body += [f"line {i}" for i in range(20)]
    body += ["1 failed, 4 passed", "##[error]Process completed with exit code 1.", "Post job cleanup.", "post line"]
    result = actions_excerpt(stamped(*body), None)
    assert result.text.split("\n")[-1] == "Error: Process completed with exit code 1."
    assert "1 failed, 4 passed" in result.text
    assert "Error: tests/test_a.py:3: assert 1 == 2" in result.text
    assert "post line" not in result.text


def test_a_continue_on_error_step_is_not_the_anchor() -> None:
    """SCN-VER-220: an error of a step that did not fail the job is not the anchor."""
    lines = [
        "Set up",
        "##[group]Run optional-lint",
        "##[endgroup]",
        "lint output",
        "##[error]Process completed with exit code 2.",
        "##[group]Run tests",
        "##[endgroup]",
        "FAILED tests/test_a.py::test_x - assert 1 == 2",
        "##[error]Process completed with exit code 1.",
    ]
    log = stamped(*lines, start="2026-10-20T10:00:03")  # exit code 2 at 10:00:07, `tests` starts at 10:00:08
    steps = [ActionsStep("optional-lint", "success", at(3)), ActionsStep("tests", "failure", at(8))]
    with_steps = actions_excerpt(log, steps)
    assert with_steps.text.startswith("Run tests")
    assert "exit code 2" not in with_steps.text
    assert with_steps.failed_step == "tests"
    without = actions_excerpt(log, None)
    assert without.text.startswith("Run optional-lint")
    assert "exit code 2" in without.text


def test_the_steps_filter_is_ignored_when_it_leaves_no_error_line() -> None:
    log = stamped("a", "##[group]Run x", "##[endgroup]", "##[error]Process completed with exit code 3.")
    result = actions_excerpt(log, [ActionsStep("x", "failure", at(59))])
    assert "exit code 3" in result.text and result.failed_step == "x"


def test_no_error_line_gives_todays_tail() -> None:
    """SCN-VER-221: no error line: the excerpt degrades to today's last lines."""
    lines = [f"line {i}" for i in range(60)]
    log = stamped(*lines)
    result = actions_excerpt(log, [ActionsStep("tests", "failure", at(1))])
    assert result.text == clip_log("\n".join(lines))
    assert result.failed_step == "tests"
    assert actions_excerpt(log, None).failed_step is None


def test_without_steps_the_name_is_the_header() -> None:
    """SCN-VER-221: without the API's steps the failing step is named by its `Run …` header."""
    log = stamped(
        "##[group]Run uv run pytest -q",
        "uv run pytest -q",
        "##[endgroup]",
        "boom",
        "##[error]Process completed with exit code 1.",
    )
    result = actions_excerpt(log, None)
    assert result.failed_step == "Run uv run pytest -q"
    assert result.text == "Run uv run pytest -q\nboom\nError: Process completed with exit code 1."


def test_a_failure_before_any_step() -> None:
    """SCN-VER-222: a failure before any step is the set-up lines, named `Set up job`."""
    log = stamped(
        "Current runner version",
        "Prepare all required actions",
        "##[error]Unable to resolve action",
        "##[group]Run later",
        "##[endgroup]",
        "later output",
    )
    result = actions_excerpt(log, [ActionsStep("Set up job", "failure", at(0))])
    assert result.failed_step == "Set up job"
    assert "Error: Unable to resolve action" in result.text
    assert "later output" not in result.text
    assert result.text.startswith("Current runner version")


def test_a_composite_step_is_its_own_section() -> None:
    """SCN-VER-222: a step of a composite action is its own section."""
    log = stamped(
        "##[group]Run owner/composite@v1",
        "with:",
        "##[endgroup]",
        "##[group]Run make check",
        "make check",
        "##[endgroup]",
        "make: *** [check] Error 2",
        "##[error]Process completed with exit code 2.",
        "Post job cleanup.",
    )
    result = actions_excerpt(log, None)
    assert result.text.split("\n")[0] == "Run make check"
    assert "make: *** [check] Error 2" in result.text


def test_markers_read_as_on_the_page() -> None:
    log = stamped(
        "##[group]Run x",
        "x",
        "##[endgroup]",
        "##[group]Inner group",
        "##[warning]careful",
        "##[notice]fyi",
        "##[endgroup]",
        "##[error]Process completed with exit code 1.",
    )
    text = actions_excerpt(log, None).text
    assert "Inner group" in text and "##[group]" not in text and "##[endgroup]" not in text
    assert "Warning: careful" in text and "Notice: fyi" in text
    assert "##[" not in text


def test_a_failed_step_is_the_first_failure_else_timeout_or_cancel() -> None:
    steps = [ActionsStep("a", "success", None), ActionsStep("b", "cancelled", None), ActionsStep("c", "failure", None)]
    assert actions_failed_step(steps) == steps[2]
    assert actions_failed_step(steps[:2]) == steps[1]
    assert actions_failed_step([ActionsStep("t", "timed_out", None)]).name == "t"  # type: ignore[union-attr]
    assert actions_failed_step([ActionsStep("a", "success", None)]) is None
    assert actions_failed_step([]) is None


def test_summary_lines_patterns() -> None:
    hits = [
        "FAILED tests/test_a.py::test_x - assert 1 == 2",
        "ERROR tests/test_a.py::test_y - ImportError",
        "E       assert 1 == 2",
        " FAIL  src/a.test.ts > renders",
        "--- FAIL: TestThing (0.00s)",
        "    --- FAIL: TestThing/sub (0.00s)",
        "1 failed, 2277 passed in 3s",
        "Found 2 errors.",
        "Tests: 1 failed, 3 passed",
        "Error: tests/test_a.py:3: assert 1 == 2",
        "##[error]annotation text",
    ]
    for line in hits:
        assert summary_lines([line]) == [line], line
    for line in (
        "0 failed, 5 passed",
        "Error: Process completed with exit code 1.",
        "PASSED t::x",
        "E",
        "  E  indented",
        "ok",
    ):
        assert summary_lines([line]) == [], line
    sixes = [f"E       line {i}" for i in range(9)]
    assert summary_lines(sixes) == sixes[:6]
    mixed = ["FAILED a::b - x", "noise", "1 failed in 2s", "FAILED a::b - x"]
    assert summary_lines(mixed) == ["FAILED a::b - x", "1 failed in 2s"]


def test_ranked_summary_lines_put_the_failing_tests_first() -> None:
    lines = [
        "E       assert x",
        "Error: annotation",
        "1 failed, 4 passed",
        "FAILED a::b - boom",
        "--- FAIL: TestX (0.0s)",
        "E       more",
    ]
    assert ranked_summary_lines(lines) == [
        "FAILED a::b - boom",
        "--- FAIL: TestX (0.0s)",
        "1 failed, 4 passed",
        "E       assert x",
        "E       more",
        "Error: annotation",
    ]


def test_section_excerpt_budgets() -> None:
    body = [f"FAILED t.py::t{i} - boom" for i in range(5)] + [f"E       detail {i}" for i in range(30)]
    body += [f"output {i}" for i in range(200)] + ["5 failed, 900 passed"]
    text = section_excerpt("Run pytest", body, max_lines=40, max_chars=3000).split("\n")
    assert text[0] == "Run pytest"
    assert text[1:6] == [f"FAILED t.py::t{i} - boom" for i in range(5)]
    assert text[6:12] == [f"E       detail {i}" for i in range(6)]
    assert text[12] == "..."
    assert text[13:] == body[-40:]
    assert len("\n".join(text)) <= 3000


def test_section_excerpt_cuts_a_long_line_and_a_small_body_has_no_gap() -> None:
    long = "x" * 2000
    text = section_excerpt(None, ["a", long, "b"], max_lines=40, max_chars=3000)
    assert text.split("\n") == ["a", "x" * 500 + "...", "b"]


def test_section_excerpt_over_budget_drops_the_tail_then_the_summary() -> None:
    body = [f"FAILED t.py::t{i} - " + "y" * 80 for i in range(12)] + ["z" * 100 for _ in range(60)]
    text = section_excerpt("Run p", body, ["closing line"], max_lines=40, max_chars=2000)
    assert len(text) <= 2000
    lines = text.split("\n")
    assert lines[-1] == "closing line"
    assert lines[-2] == "z" * 100
    # the tail lost its first lines before the summary lost any
    assert sum(1 for line in lines if line.startswith("FAILED")) == 12 or len(lines) - 3 <= 6
    tiny = section_excerpt("Run p", body, ["closing line"], max_lines=40, max_chars=900)
    assert len(tiny) <= 900 and tiny.endswith("closing line")


def test_section_excerpt_keeps_the_closing_lines_after_the_tail() -> None:
    text = section_excerpt(None, ["a", "b"], ["ERROR: Job failed: exit code 1"], max_lines=40, max_chars=3000)
    assert text == "a\nb\nERROR: Job failed: exit code 1"


def test_the_module_imports_only_the_forge_base() -> None:
    tree = ast.parse(Path(logexcerpt.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("l4"):
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names if a.name.startswith("l4")}
    assert imported <= {"l4.forge.base"}
