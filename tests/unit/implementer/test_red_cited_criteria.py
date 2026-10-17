"""Red covers every criterion a Kiro leaf's `_Requirements:_` line names (L4-KSP-012, L4-KSP-013; implementer-5)."""

from l4.implementer.tdd import run_red

from .._kiro_probe import PROBE_IDS
from .conftest import Bench, kiro_red_step


def probe_task(bench: Bench):
    (task,) = bench.wb.provider.tasks(bench.wb.ref)
    return task


def test_the_kiro_bench_runs_a_red_step(make_kiro_bench):
    bench: Bench = make_kiro_bench([kiro_red_step()])
    task = probe_task(bench)
    assert (task.key, task.links) == ("1", ("1.1", "1.2"))
    outcome = run_red(bench.wb, task, attempt=1)
    assert outcome.status == "ok", outcome.reason
    (red_ok,) = bench.events("task.red_ok")
    assert sorted(red_ok["criteria"]) == sorted(PROBE_IDS.values())
    assert bench.subjects() == ["test(tip-calc): red for 1 [skip ci]"]
