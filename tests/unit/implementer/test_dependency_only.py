"""L4-IMP-062 (SCN-IMP-306, 307): a criterion whose every test reads a dependency and no project code cannot be shown
discriminating by any variant run; it is recorded `discrimination not applicable`, and the judge sees the label."""

from l4.agents.fake import Step
from l4.implementer import depcheck, discrimination
from l4.implementer.discrimination import confirm_pre_satisfied, import_roots
from l4.implementer.tdd import run_red, run_setup
from l4.specs.base import Task

from .conftest import KNOWN, UNKNOWN, Bench, result

TASK = Task("1.1", "1.1", "1.1 Pin the runner", False, " ", 0, 1, 3)
DISCOUNT_TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
C1, C2 = "C-aaaaaaaa", "C-bbbbbbbb"
PIN = (
    "import importlib.metadata\n\nimport pytest\n\nimport pytdd\n\n\n"
    '@pytest.mark.l4("C-aaaaaaaa")\n'
    "def test_runner_is_the_verified_pin():\n"
    '    assert importlib.metadata.version("pytest") == pytest.__version__\n\n\n'
    '@pytest.mark.l4("C-bbbbbbbb")\n'
    "def test_uses_the_project():\n"
    "    assert pytdd.total([1.0]) == 1.0\n"
)
PIN_ID = "tests.test_pins::test_runner_is_the_verified_pin"
PROJECT_ID = "tests.test_pins::test_uses_the_project"


def staged(make_bench, source: str, name: str = "test_pins") -> Bench:
    bench: Bench = make_bench([])
    (bench.wb.worktree / "tests" / f"{name}.py").write_text(source)
    run_setup(bench.wb)
    return bench


def real_report(bench: Bench):
    gate = bench.wb.run_gate("test", bench.wb.cfg.gates.test.command, reports=bench.wb.cfg.gates.test.reports)
    assert gate.report is not None
    return gate.report


PIN_TEXT = "The installed pytest is the verified version: the runner is pinned"


def only(bench: Bench, test_id: str, text: str = PIN_TEXT) -> bool:
    return depcheck.dependency_only(bench.wb, test_id, import_roots(bench.wb), text)


def test_scn_imp_306_a_version_pin_is_not_applicable(make_bench, monkeypatch):
    bench = staged(make_bench, PIN)
    gates: list[str] = []

    def no_run(*args, **kwargs):
        gates.append("zero")
        raise AssertionError("a not applicable criterion runs no variant run")

    monkeypatch.setattr(discrimination, "zeroed_run", no_run)
    monkeypatch.setattr(discrimination, "_criterion_texts", lambda wb: {C1: PIN_TEXT})
    got = confirm_pre_satisfied(bench.wb, {C1: [PIN_ID]}, real=real_report(bench))
    assert got.not_applicable == {C1: (PIN_ID,)} and gates == []
    assert got.confirmed == {} and got.unconfirmed == {} and got.inconclusive == {} and got.message == ""


def test_scn_imp_306_through_run_red_the_proof_says_not_applicable(make_bench, monkeypatch):
    monkeypatch.setattr(discrimination, "_criterion_texts", lambda wb: {KNOWN: PIN_TEXT})
    pin = (
        "import importlib.metadata\n\nimport pytest\n\n\n"
        f'@pytest.mark.l4("{KNOWN}")\n'
        "def test_runner_is_the_verified_pin():\n"
        '    assert importlib.metadata.version("pytest") == pytest.__version__\n'
    )
    step = Step(writes={"tests/test_pins.py": pin}, structured=result("red", criteria_ids=[KNOWN]))
    bench: Bench = make_bench([step])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    test_id = "tests.test_pins::test_runner_is_the_verified_pin"
    assert bench.events("task.red_ok")[-1]["criteria"][KNOWN] == {
        "tests": [test_id], "proof": "pre_satisfied", "discriminating": [test_id], "via": "not_applicable",
    }  # fmt: skip
    assert bench.events("criterion.pre_satisfied")[-1]["via"] == "not_applicable"


def test_scn_imp_307_a_test_that_reads_no_dependency_is_still_not_discriminating(make_bench):
    source = (
        "import json\n\nfrom pytdd import total\n\n\n"
        "def test_arithmetic():\n    assert 1 + 1 == 2\n\n\n"
        'def test_stdlib_only():\n    assert json.loads("1") == 1\n'
    )
    bench = staged(make_bench, source)
    for test_id in ("tests.test_pins::test_arithmetic", "tests.test_pins::test_stdlib_only"):
        assert not only(bench, test_id)
    got = confirm_pre_satisfied(
        bench.wb,
        {C1: ["tests.test_pins::test_arithmetic"], C2: ["tests.test_pins::test_stdlib_only"]},
        real=real_report(bench),
    )
    assert set(got.unconfirmed) == {C1, C2} and got.not_applicable == {}


def test_project_code_a_helper_or_a_fixture_is_not_dependency_only(make_bench):
    source = """\
import importlib.metadata

import pytest

from helpers import make
from pytdd import total

PIN = "pytest"


def local() -> str:
    return "pytest"


def test_calls_a_local_def():
    assert importlib.metadata.version(local()) == pytest.__version__


@pytest.fixture
def exporter():
    return []


def test_takes_a_fixture(exporter):
    assert importlib.metadata.version("pytest") and exporter == []


def test_imports_project_in_body():
    from pytdd.pricing import total as t

    assert importlib.metadata.version("pytest") and t([1.0]) == 1.0


def test_uses_a_helper_module():
    assert importlib.metadata.version("pytest") and make()


def test_uses_a_project_import():
    assert importlib.metadata.version("pytest") and total([1.0]) == 1.0
"""
    bench = staged(make_bench, source)
    (bench.wb.worktree / "tests/helpers.py").write_text("def make() -> int:\n    return 1\n")
    for name in (
        "test_calls_a_local_def", "test_takes_a_fixture", "test_imports_project_in_body",
        "test_uses_a_helper_module", "test_uses_a_project_import",
    ):  # fmt: skip
        assert not only(bench, f"tests.test_pins::{name}"), name


def test_a_class_test_and_a_version_attribute_are_read_with_a_literal_name_the_criterion_names(make_bench):
    source = """\
import importlib.metadata

import pytest


class TestPins:
    def test_pin(self):
        assert importlib.metadata.version("pytest") == "8.3.0"  # round 2 (L4-IMP-062): the version is compared


def test_dependency_attribute():
    assert pytest.__version__ == "8.3.0"
"""
    bench = staged(make_bench, source)
    assert only(bench, "tests.test_pins.TestPins::test_pin")
    assert only(bench, "tests.test_pins::test_dependency_attribute")
    assert not only(bench, "tests.test_pins.TestPins::test_pin", "the discount is 10 percent")  # text names no pytest
    assert not only(bench, "tests.test_pins::test_missing")
    assert not only(bench, "tests.no_such_file::test_x")


def test_a_distribution_name_that_is_not_a_literal_is_not_read(make_bench):
    source = """\
import importlib.metadata

import pytest

PIN = "pytest"


@pytest.mark.parametrize("name", ["pytest"])
def test_param(name):
    assert importlib.metadata.version(name)


def test_constant():
    assert importlib.metadata.version(PIN)
"""
    bench = staged(make_bench, source)
    assert not only(bench, "tests.test_pins::test_param[pytest]")
    assert not only(bench, "tests.test_pins::test_constant")


VACUOUS_PIN = f"""\
import pytest


@pytest.mark.l4("{KNOWN}")
def test_known_code():
    assert pytest.__version__


@pytest.mark.l4("{UNKNOWN}")
def test_unknown_code():
    assert pytest.__version__
"""


def test_a1_a_dependency_read_does_not_tick_a_behavioural_criterion(make_bench):
    """Review M2: `assert pytest.__version__` tagged with criteria about `apply_discount` fails red as on 0.4.15: the
    criterion text does not name the dependency."""
    step = Step(writes={"tests/test_discount.py": VACUOUS_PIN}, structured=result("red", criteria_ids=[KNOWN, UNKNOWN]))
    bench: Bench = make_bench([step])
    out = run_red(bench.wb, DISCOUNT_TASK, attempt=1)
    assert out.status == "failed" and out.reason.startswith("not discriminating: "), out.reason
    assert [e for e in bench.events("criterion.pre_satisfied") if e["task"] == "1.1"] == []


BYPASS = """\
import importlib
import importlib.metadata

import pytest


def test_importorskip():
    m = pytest.importorskip("pytdd")
    assert m.total([1.0]) == 1.0 and importlib.metadata.version("pytest")


def test_import_module():
    m = importlib.import_module("pytdd")
    assert m.total([1.0]) == 1.0 and importlib.metadata.version("pytest")


def test_dunder_import():
    m = __import__("pytdd")
    assert m.total([1.0]) == 1.0 and importlib.metadata.version("pytest")


def test_request_fixture(request):
    m = request.getfixturevalue("pricing_module")
    assert m.total([1.0]) == 1.0 and importlib.metadata.version("pytest")
"""
CONFTEST = "import pytest\n\nimport pytdd\n\n\n@pytest.fixture\ndef pricing_module():\n    return pytdd\n"


def test_a2_tests_that_run_project_code_by_name_are_not_dependency_only(make_bench):
    bench: Bench = make_bench([])
    (bench.wb.worktree / "tests/test_bypass.py").write_text(BYPASS)
    (bench.wb.worktree / "tests/conftest.py").write_text(CONFTEST)
    run_setup(bench.wb)
    for name in ("test_importorskip", "test_import_module", "test_dunder_import", "test_request_fixture"):
        assert not only(bench, f"tests.test_bypass::{name}"), name


# --- round-2 review N3: a pin needs a dependency of its own, a version in the text, a comparison ---
def one(bench: Bench, dist: str, text: str, compare: str = ' == "1.0"') -> bool:
    name = "test_probe_" + dist.replace("-", "_")
    (bench.wb.worktree / "tests" / f"{name}.py").write_text(
        f'import importlib.metadata\n\n\ndef test_probe():\n    assert importlib.metadata.version("{dist}"){compare}\n'
    )
    return depcheck.dependency_only(bench.wb, f"tests.{name}::test_probe", import_roots(bench.wb), text)


def test_n3_the_project_s_own_distribution_is_no_dependency(make_bench):
    bench = staged(make_bench, PIN)
    text = "pytdd 1.0 version: `pytdd.pricing.apply_discount(50.0, 'SAVE10')` is called"
    assert one(bench, "pytdd", text) is False
    assert depcheck.own_distributions(bench.wb) == frozenset({"pytdd"})


def test_n3_the_name_must_be_a_whole_token(make_bench):
    bench = staged(make_bench, PIN)
    assert one(bench, "mcp", "the client of `mintmory-history-mcp` pins version 1.2 of nothing") is False
    assert one(bench, "distro", "the distribution list of version 1.2 is exported") is False
    assert one(bench, "pytest", "pytest is pinned to version 1.0") is True


def test_n3_the_text_must_give_a_version(make_bench):
    bench = staged(make_bench, PIN)
    assert one(bench, "packaging", "the packaging fee is discounted") is False
    assert one(bench, "packaging", "packaging is pinned at 24.1") is True
    assert one(bench, "pytest", "the tool pytest 8.3 is the runner") is True


def test_n3_the_test_must_compare_the_version(make_bench):
    bench = staged(make_bench, PIN)
    text = "pytest version 8 is pinned"
    assert one(bench, "pytest", text, "") is False  # truth of the version pins nothing
    assert one(bench, "pytest", text, ".startswith('8.')") is True
    assert one(bench, "pytest", text, " >= '8'") is True


def test_n3_a_dependency_s_dunder_version_is_compared_too(make_bench):
    bench = staged(make_bench, PIN)
    path = bench.wb.worktree / "tests" / "test_dunder.py"
    path.write_text("import pytest\n\n\ndef test_probe():\n    assert pytest.__version__\n")
    assert (
        depcheck.dependency_only(bench.wb, "tests.test_dunder::test_probe", import_roots(bench.wb), PIN_TEXT) is False
    )
    path.write_text("import pytest\n\n\ndef test_probe():\n    assert pytest.__version__ == '8.3.0'\n")
    assert depcheck.dependency_only(bench.wb, "tests.test_dunder::test_probe", import_roots(bench.wb), PIN_TEXT) is True
