"""`question.raised` names who asked (delegate-answers 3.1; L4-DLG-002, D3): the profile and the model of the step that
raised it, so the delegate is never the mind that asked."""

from dataclasses import replace

from l4.implementer.loop import run_task

from .conftest import blocked_step
from .test_earlier_red import TASK as HELD_TASK
from .test_held_check import held_bench, no_test, zero_says
from .test_loop import TASK


def with_model(bench, model: str | None):
    """The workbench of the bench with its profile declaring `model`."""
    profile = bench.wb.selected.profile.model_copy(update={"model": model})
    return replace(bench.wb, selected=replace(bench.wb.selected, profile=profile))


def test_a_blocked_step_records_its_profile_and_model(make_bench):
    bench = make_bench([blocked_step()])
    wb = with_model(bench, "claude-opus-5-5")
    run_task(wb, TASK)
    [raised] = bench.events("question.raised")
    assert raised["profile"] == wb.selected.profile_name == "impl"
    assert raised["model"] == "claude-opus-5-5"  # the adapter reports none: the profile's model


def test_the_served_model_wins_over_the_configured_one(make_bench):
    bench = make_bench([blocked_step(model="gpt-6.1-sol")])
    bench.adapter._served_model = True  # this adapter reports the model that served the run
    run_task(with_model(bench, "claude-opus-5-5"), TASK)
    [raised] = bench.events("question.raised")
    assert (raised["profile"], raised["model"]) == ("impl", "gpt-6.1-sol")


def test_a_model_that_nobody_names_is_recorded_as_none(make_bench):
    bench = make_bench([blocked_step()])
    run_task(with_model(bench, None), TASK)
    [raised] = bench.events("question.raised")
    assert raised["profile"] == "impl" and raised["model"] is None


def test_a_served_model_of_an_earlier_task_is_not_the_askers(make_bench):
    bench = make_bench([blocked_step(model="gpt-6.1-sol"), blocked_step()])
    bench.adapter._served_model = True
    wb = with_model(bench, "claude-opus-5-5")
    run_task(wb, TASK)
    bench.adapter._served_model = False  # the next step reports none
    run_task(wb, TASK)
    models = [e["model"] for e in bench.events("question.raised")]
    assert models == ["gpt-6.1-sol", "claude-opus-5-5"]


def test_a_harness_question_records_its_profile_and_model(make_bench, monkeypatch):
    zero_says(monkeypatch)
    bench = held_bench(make_bench, [no_test()])
    wb = with_model(bench, "claude-opus-5-5")
    outcome = run_task(wb, HELD_TASK)
    assert outcome.status == "blocked"
    [raised] = bench.events("question.raised")
    assert raised["kind"] == "harness"
    assert (raised["profile"], raised["model"]) == ("impl", "claude-opus-5-5")
