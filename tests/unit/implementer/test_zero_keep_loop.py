"""L4-IMP-061 (SCN-IMP-302..304): the pre-satisfied zero-value run keeps what imports need. A decorator factory
annotated to return a callable is kept at once; one that is not is kept after the run's traceback names it, and the
run is made again, at most twice."""

import hashlib
from pathlib import Path

from l4.gates.junit import TestReport
from l4.gates.runner import GateResult
from l4.implementer import discrimination, variant
from l4.implementer.discrimination import zeroed_run
from l4.implementer.tdd import run_setup
from l4.implementer.workbench import Workbench

from .conftest import Bench

TELEMETRY = """\
from collections.abc import Callable
from typing import Any, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])


def traced(name: str) -> Callable[[_F], _F]:
    def decorate(fn: _F) -> _F:
        return fn

    return decorate


def init(out: list) -> bool:
    out.append("on")
    return True
"""
TELEMETRY_UNANNOTATED = TELEMETRY.replace("def traced(name: str) -> Callable[[_F], _F]:", "def traced(name):")
STORE = """\
from pytdd import telemetry


class Store:
    @telemetry.traced("store.add")
    def add(self, a: int, b: int) -> int:
        return a + b
"""
TEST_STORE = """\
import pytest

from pytdd.store import Store


@pytest.mark.l4("C-aaaaaaaa")
def test_add():
    assert Store().add(1, 2) == 3
"""
TEST_ID = "tests.test_store::test_add"
PATHS = ["src/pytdd/telemetry.py", "src/pytdd/store.py"]


def staged(make_bench, telemetry: str) -> tuple[Bench, TestReport | None]:
    bench: Bench = make_bench([])
    wt = bench.wb.worktree
    (wt / "src/pytdd/telemetry.py").write_text(telemetry)
    (wt / "src/pytdd/store.py").write_text(STORE)
    (wt / "tests/test_store.py").write_text(TEST_STORE)
    run_setup(bench.wb)
    real = bench.wb.run_gate("test", bench.wb.cfg.gates.test.command, reports=bench.wb.cfg.gates.test.reports)
    assert real.report is not None and real.report.tests[TEST_ID].status == "passed"
    return bench, real.report


def test_scn_imp_302_the_presatisfied_run_imports_a_module_decorated_at_class_definition(make_bench):
    bench, real = staged(make_bench, TELEMETRY)
    run = zeroed_run(bench.wb, "test-presatisfied", PATHS, public=True, real=real, candidates=[TEST_ID])
    assert run is not None and run.reruns == 0
    assert run.run.report is not None and run.run.report.collection_errors == []
    assert variant.test_outcome(run.run, TEST_ID, real, frozenset())[0] == "proof"
    kept = bench.events("zero.kept")
    assert [(k["gate"], k["rerun"], k["cause"], k["functions"]) for k in kept] == [
        ("test-presatisfied", 0, "annotation", ["src/pytdd/telemetry.py::traced"])
    ]


def test_scn_imp_303_an_unannotated_decorator_factory_is_kept_after_the_run_names_it(make_bench):
    bench, real = staged(make_bench, TELEMETRY_UNANNOTATED)
    run = zeroed_run(bench.wb, "test-presatisfied", PATHS, public=True, real=real, candidates=[TEST_ID])
    assert run is not None and run.reruns == 1
    assert variant.test_outcome(run.run, TEST_ID, real, frozenset())[0] == "proof"
    kept = bench.events("zero.kept")
    assert [(k["rerun"], k["cause"], k["functions"]) for k in kept] == [
        (1, "collection", ["src/pytdd/telemetry.py::traced"])
    ]
    assert run.kept == {"src/pytdd/telemetry.py": ("traced",)}
    assert len([e for e in bench.events("gate.finished") if e["name"] == "test-presatisfied"]) == 2


CHAIN = "".join(f"def f{n}() -> int:\n    return {n}\n\n\n" for n in range(6))


def test_scn_imp_304_the_keep_reruns_are_bounded(make_bench, monkeypatch, tmp_path):
    bench, real = staged(make_bench, TELEMETRY)
    (bench.wb.worktree / "src/pytdd/chain.py").write_text(CHAIN)
    calls: list[int] = []

    def fake(self, name, command, **kwargs):
        n = len(calls)
        calls.append(n)
        log = tmp_path / f"gate-{n}.log"
        log.write_text("")
        detail = f"src/pytdd/chain.py:1: in <module>\n    X = f{n}()\nE   TypeError: x\n"
        report = TestReport({}, ["tests.test_store"], {"tests.test_store": detail})
        return GateResult(name, "fail", "exit code 2", 2, log, report)

    monkeypatch.setattr(Workbench, "run_gate", fake)
    run = zeroed_run(
        bench.wb, "test-presatisfied", ["src/pytdd/chain.py"], public=True, real=real, candidates=[TEST_ID]
    )
    assert run is not None and len(calls) == 3 and run.reruns == 2
    assert [(k["rerun"], k["cause"]) for k in bench.events("zero.kept")] == [(1, "collection"), (2, "collection")]
    assert variant.test_outcome(run.run, TEST_ID, real, frozenset())[0] == "inconclusive"
    assert run.kept == {"src/pytdd/chain.py": ("f0", "f1")}
    assert discrimination.MAX_KEEP_RERUNS == 2


def test_the_worktree_is_byte_identical_after_the_reruns(make_bench):
    bench, real = staged(make_bench, TELEMETRY_UNANNOTATED)

    def digest() -> dict[str, str]:
        return {p: hashlib.sha256((bench.wb.worktree / p).read_bytes()).hexdigest() for p in PATHS}

    before = digest()
    run = zeroed_run(bench.wb, "test-presatisfied", PATHS, public=True, real=real, candidates=[TEST_ID])
    assert run is not None and run.reruns == 1
    assert digest() == before
    assert not list(Path(bench.wb.worktree).glob("src/pytdd/*.l4zero"))
