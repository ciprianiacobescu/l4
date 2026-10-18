"""Review M4 and m1 (L4-IMP-061, SCN-IMP-324, 325): a function is kept real by its annotation only when a module of the
varied set applies it at import time; the keep loop also reads the module-level statements of the module whose import
failed."""

import textwrap

from l4.agents.fake import Step
from l4.implementer.stubs import import_time_names, zero_value_plan
from l4.implementer.tdd import run_red
from l4.specs.base import Task

from .conftest import KNOWN, Bench, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)


def test_import_time_names_are_decorators_and_module_or_class_level_calls():
    source = textwrap.dedent(
        """\
        import functools

        @telemetry.traced("x")
        def a(): ...

        @plain
        class B:
            @timed
            def m(self): ...

            LIMIT = compute()

        handler = make_handler("h")

        def inside():
            return not_import_time()
        """
    )
    assert import_time_names(source) == {"traced", "plain", "timed", "compute", "make_handler"}


FACTORY = (
    "from collections.abc import Callable\n\n\n"
    "def make_adder(n: int) -> Callable[[int], int]:\n    return lambda x: x + n\n"
)


def test_a_callable_returning_function_nothing_applies_is_zeroed():
    plan = zero_value_plan(FACTORY, public=True)
    assert plan.kept == () and plan.zeroed == ("make_adder",)
    applied = zero_value_plan(FACTORY, public=True, applied={"make_adder"})
    assert applied.kept == ("make_adder",) and applied.zeroed == ()


def commit_base(tdd_repo, raw, files: dict[str, str]) -> None:
    root = tdd_repo.repo
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    raw(root, "add", "-A")
    raw(root, "commit", "-q", "-m", "base")
    raw(root, "push", "-q", "origin", "main")
    raw(root, "fetch", "-q", "origin")


FACTORY_TEST = f"""\
import pytest

from pytdd.factory import make_adder


@pytest.mark.l4("{KNOWN}")
def test_make_adder():
    f = make_adder(2)
    assert f is not None
    assert f(3) == 5
"""


def test_r1_an_honest_test_of_a_callable_returning_function_is_confirmed_as_on_0415(make_bench, tdd_repo, raw):
    commit_base(tdd_repo, raw, {"src/pytdd/factory.py": FACTORY})
    step = Step(writes={"tests/test_factory.py": FACTORY_TEST}, structured=result("red", criteria_ids=[KNOWN]))
    bench: Bench = make_bench([step])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "already_satisfied", out.reason
    assert bench.events("zero.kept") == []


CONFIG = 'def load() -> dict:\n    return {"rate": 2}\n\n\n_CFG = load()\nRATE = _CFG["rate"]\n'
CONFIG_TEST = f"""\
import pytest

from pytdd.config import RATE, load


@pytest.mark.l4("{KNOWN}")
def test_rate():
    assert load()["rate"] == RATE == 2
"""


def test_k1_two_statement_import_time_code_is_not_held(make_bench, tdd_repo, raw):
    """The failing line `RATE = _CFG["rate"]` calls nothing; the statement above it calls `load`."""
    commit_base(tdd_repo, raw, {"src/pytdd/config.py": CONFIG})
    step = Step(writes={"tests/test_config.py": CONFIG_TEST}, structured=result("red", criteria_ids=[KNOWN]))
    bench: Bench = make_bench([step])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and out.reason.startswith(f"not discriminating: {KNOWN}"), out.reason  # as on 0.4.15
    assert bench.events("question.raised") == []
    kept = bench.events("zero.kept")
    assert [(k["rerun"], k["cause"]) for k in kept] == [(1, "collection")]
    assert kept[0]["functions"] == ["src/pytdd/config.py::load"]
