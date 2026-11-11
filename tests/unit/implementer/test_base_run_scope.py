"""The base run's scope and limit (L4-IMP-097, SCN-IMP-526..532): the unit's other test files are at the unit base for
the run, and the run stops after twice the step's own test run."""

from .conftest import Bench


def sleeper(seconds: int) -> str:
    return f"sh -c 'sleep {seconds}'"


def test_run_gate_takes_a_limit_of_its_own(make_bench):
    """D3: `timeout_s` replaces `gates.timeout` for one gate."""
    bench: Bench = make_bench([])
    got = bench.wb.run_gate("slow", sleeper(5), timeout_s=1)
    assert (got.status, got.timed_out, got.reason) == ("fail", True, "timed out after 1s")
    assert 0.9 < got.seconds < 4


def test_run_gate_without_a_limit_of_its_own_uses_the_gates_timeout(make_bench):
    bench: Bench = make_bench([], timeout="2s", test_timeout="0s")
    got = bench.wb.run_gate("slow", sleeper(5))
    assert (got.timed_out, got.reason) == (True, "timed out after 2s")
