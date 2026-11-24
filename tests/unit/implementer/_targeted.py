"""Shared by the targeted-red tests (L4-IMP-118..122): the fixture unit's targeted configuration, the steps whose new
tests fail against the fixture's code and pass once `green_step` is in, and FAKE wrappers over `wb.run_gate`."""

from dataclasses import replace

from l4.agents.fake import Step
from l4.gates.junit import TestCase
from l4.implementer.tdd import run_red
from l4.specs.base import Task

from ..conftest import TEST_COMMAND
from .conftest import KNOWN, UNKNOWN, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)
TARGETED = {"command": TEST_COMMAND, "targeted": TEST_COMMAND + " {files}", "red_check": "targeted"}
FILE = "tests/test_targeted.py"
PRE = "tests.test_pricing::test_total_adds_prices"  # a test of the base, in a file the step never touches
HEAD = "import pytest\nfrom pytdd import pricing\n\n\n"
CODES = (
    f'@pytest.mark.l4("{KNOWN}")\ndef test_codes_exist():\n    assert hasattr(pricing, "CODES")\n\n\n'
    f'@pytest.mark.l4("{UNKNOWN}")\ndef test_save10_is_ten_percent():\n'
    '    assert getattr(pricing, "CODES", {}).get("SAVE10") == 10\n'
)
NEW_TESTS = HEAD + CODES  # fail by assertion against the fixture's code, pass once IMPL (green_step) is in


def red(path: str = FILE, tests: str = NEW_TESTS, **over: object) -> Step:
    return Step(
        writes={path: tests},
        structured=result("red", tests_added=[f"{path}::test_codes_exist"], criteria_ids=[KNOWN, UNKNOWN], **over),
    )


def two_files() -> Step:
    first = HEAD + CODES.split("\n\n\n")[0] + "\n"
    second = HEAD + CODES.split("\n\n\n")[1]
    return Step(
        writes={"tests/test_a.py": first, "tests/test_b.py": second},
        structured=result("red", tests_added=["tests/test_a.py::test_codes_exist"], criteria_ids=[KNOWN, UNKNOWN]),
    )


class FakeGates:
    """FAKE: wraps `wb.run_gate` of a bench. `calls` lists `(name, command)` of every gate the step ran; `change` maps a
    gate name to a function of the real result that gives the result the step sees; `before` maps a name to a function
    called before the real run (the state of the tree at that moment)."""

    def __init__(self, bench, change=None, before=None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.change, self.before = change or {}, before or {}
        self.bench, self.original = bench, bench.wb.run_gate
        bench.wb.run_gate = self.run_gate

    def restore(self) -> None:
        self.bench.wb.run_gate = self.original

    def run_gate(self, name, command, **kw):
        self.calls.append((name, command))
        if name in self.before:
            self.before[name]()
        out = self.original(name, command, **kw)
        return self.change[name](out) if name in self.change else out

    @property
    def names(self) -> list[str]:
        return [n for n, _ in self.calls if n not in ("setup", "baseline")]


def bench_of(make_bench, script, **over):
    return make_bench(script, test={**TARGETED, **over})


def ok_red(make_bench, step: Step | None = None, **over):
    bench = bench_of(make_bench, [step or red()], **over)
    fake = FakeGates(bench)
    out = run_red(bench.wb, TASK, attempt=1)
    return bench, fake, out


def failing(*ids: str):
    """FAKE: the result with `ids` failing (a test of the base that a run reports as failed)."""

    def change(out):
        return replace(
            out,
            report=replace(out.report, tests={**out.report.tests, **{i: TestCase(i, "failed", "boom") for i in ids}}),
        )

    return change


def dropping(*ids: str):
    """FAKE: the result without `ids` (a runner that names those tests otherwise)."""

    def change(out):
        return replace(
            out, report=replace(out.report, tests={i: c for i, c in out.report.tests.items() if i not in ids})
        )

    return change
