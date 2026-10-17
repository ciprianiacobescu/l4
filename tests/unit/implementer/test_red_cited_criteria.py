"""Red covers every criterion a Kiro leaf's `_Requirements:_` line names (L4-KSP-012, L4-KSP-013; implementer-5)."""

from l4.agents.fake import Step
from l4.implementer import tdd
from l4.implementer.loop import run_task
from l4.implementer.tdd import cited_criteria, run_red

from .._kiro_probe import PROBE_IDS
from .conftest import (
    TIP_HEADER,
    TIP_NEGATIVE,
    TIP_ROUNDS,
    Bench,
    kiro_red_step,
    result,
)

C11, C12 = PROBE_IDS["1.1"], PROBE_IDS["1.2"]
OLD_FILE = "tests/test_old.py"
OLD_ROUNDS = TIP_ROUNDS.replace("test_tip_is_rounded", "test_old_rounds")
OLD_NEGATIVE = TIP_NEGATIVE.replace("test_negative_percent_raises", "test_old_negative")
OLD_IMPL = (  # rounding only: a negative percent does not raise yet
    "from decimal import ROUND_HALF_UP, Decimal\n\n\ndef tip(bill, percent):\n"
    '    return (Decimal(str(bill)) * Decimal(str(percent)) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)\n'
)
OLD_IMPL_BOTH = OLD_IMPL.replace("    return", "    if percent < 0:\n        raise ValueError(percent)\n    return")
OLD_ROUNDS_ID = "tests.test_old::test_old_rounds"
OLD_NEGATIVE_ID = "tests.test_old::test_old_negative"
NO_RAISE = "tests/test_tip.py"


def probe_task(bench: Bench):
    (task,) = bench.wb.provider.tasks(bench.wb.ref)
    return task


def commit_old(bench: Bench, *, both: bool = False) -> None:
    """An earlier red of task 0.9 that proved `Req 1.1` (and `Req 1.2` when `both`), already green at head."""
    wb = bench.wb
    base = wb.head()
    tests = OLD_ROUNDS + ("\n\n" + OLD_NEGATIVE if both else "")
    (wb.worktree / OLD_FILE).write_text(TIP_HEADER + tests)
    (wb.worktree / "src" / "pytdd" / "tip.py").write_text(OLD_IMPL_BOTH if both else OLD_IMPL)
    wb.git.run("add", "-A")
    sha = wb.commit("test: red for 0.9", task="0.9", attempt=1, phase="red", tdd="red")
    proved = {C11: OLD_ROUNDS_ID, **({C12: OLD_NEGATIVE_ID} if both else {})}
    bench.writer.append(
        "task.red_ok", task="0.9", base=base, tests=[OLD_ROUNDS_ID], frozen=[], tdd=None,
        criteria={c: {"tests": [t], "proof": "red_assertion", "discriminating": [t]} for c, t in proved.items()},
    )  # fmt: skip
    bench.writer.append("task.red_committed", task="0.9", base=base, sha=sha)


def test_the_kiro_bench_runs_a_red_step(make_kiro_bench):
    bench: Bench = make_kiro_bench([kiro_red_step()])
    task = probe_task(bench)
    assert (task.key, task.links) == ("1", ("1.1", "1.2"))
    outcome = run_red(bench.wb, task, attempt=1)
    assert outcome.status == "ok", outcome.reason
    (red_ok,) = bench.events("task.red_ok")
    assert sorted(red_ok["criteria"]) == sorted(PROBE_IDS.values())
    assert bench.subjects() == ["test(tip-calc): red for 1 [skip ci]"]


MESSAGE = (
    f"no new test traces {C12} (Req 1.2), which the task's _Requirements: 1.1, 1.2_ line names: write a new test for "
    "each criterion that line names, tagged with its id"
)


def test_a_red_step_that_leaves_a_cited_criterion_untested_is_rejected_with_the_reason(make_kiro_bench):
    """SCN-IMP-294: implementer-5, the red step that tested only `Req 1.1` of a leaf citing `1.1, 1.2` passed."""
    bench: Bench = make_kiro_bench([kiro_red_step(tests=TIP_ROUNDS, criteria=[C11])])
    outcome = run_red(bench.wb, probe_task(bench), attempt=1)
    assert (outcome.status, outcome.reason) == ("failed", MESSAGE)
    assert bench.subjects() == [] and not bench.events("task.red_ok")


def test_the_next_red_attempt_reads_the_reason(make_kiro_bench):
    """SCN-IMP-294, the prompt: the loop rejects the first step and the second prompt carries the message."""
    from .conftest import TIP_IMPL

    green = Step(writes={"src/pytdd/tip.py": TIP_IMPL}, structured=result("green", task_ids=["1"]))
    bench: Bench = make_kiro_bench([kiro_red_step(tests=TIP_ROUNDS, criteria=[C11]), kiro_red_step(), green])
    assert run_task(bench.wb, probe_task(bench)).status == "done"
    second = bench.adapter.requests[1].prompt
    assert "# Your previous attempt was rejected" in second and MESSAGE in second
    assert "previous attempt was rejected" not in bench.adapter.requests[0].prompt


def test_a_criterion_a_spec_edit_left_unchanged_needs_no_new_test(make_kiro_bench, monkeypatch):
    """SCN-IMP-295 (a): the L4-OPS-015 exempt set is not required."""
    monkeypatch.setattr(tdd, "unchanged_criteria", lambda wb, task, base: frozenset({C11}))
    bench: Bench = make_kiro_bench([kiro_red_step(tests=TIP_NEGATIVE, criteria=[C12])])
    outcome = run_red(bench.wb, probe_task(bench), attempt=1)
    assert outcome.status == "ok", outcome.reason


def test_a_criterion_an_earlier_red_proved_is_confirmed_by_its_new_copy(make_kiro_bench):
    """SCN-IMP-295 (b): a new test for `Req 1.1` that passes at once is confirmed `via: earlier_red`."""
    bench: Bench = make_kiro_bench([kiro_red_step()])
    commit_old(bench)
    outcome = run_red(bench.wb, probe_task(bench), attempt=1)
    assert outcome.status == "ok", outcome.reason
    proofs = bench.events("task.red_ok")[-1]["criteria"]
    assert proofs[C11]["proof"] == "pre_satisfied" and proofs[C11]["via"] == "earlier_red"
    assert proofs[C12]["proof"] in ("red_assertion", "zero_value")


def test_a_criterion_an_earlier_red_proved_needs_no_copy_when_the_step_tests_the_rest(make_kiro_bench):
    """Owner decision 4: the existing passing tests of `Req 1.1` are the proof; only `Req 1.2` needs a new test."""
    bench: Bench = make_kiro_bench([kiro_red_step(tests=TIP_NEGATIVE, criteria=[C12])])
    commit_old(bench)
    outcome = run_red(bench.wb, probe_task(bench), attempt=1)
    assert outcome.status == "ok", outcome.reason
    proofs = bench.events("task.red_ok")[-1]["criteria"]
    assert proofs[C11] == {
        "tests": [], "proof": "pre_satisfied", "discriminating": [OLD_ROUNDS_ID], "via": "earlier_red",
        "red_sha": proofs[C11]["red_sha"], "red_task": "0.9",
    }  # fmt: skip
    assert proofs[C12]["proof"] in ("red_assertion", "zero_value")
    pre = [e for e in bench.events("criterion.pre_satisfied") if e["criterion"] == C11 and e["task"] == "1"]
    assert pre and pre[0]["via"] == "earlier_red"


def test_a_criterion_nothing_proved_still_needs_its_new_test_when_another_is_proved(make_kiro_bench):
    bench: Bench = make_kiro_bench([kiro_red_step(tests=TIP_ROUNDS, criteria=[C11])])
    commit_old(bench)  # proves `Req 1.1` only
    outcome = run_red(bench.wb, probe_task(bench), attempt=1)
    assert (outcome.status, outcome.reason) == ("failed", MESSAGE)


def test_a_fix_units_leaf_cites_the_numbers_of_its_own_items(tmp_path):
    """SCN-IMP-295 (c): the parent's own `Req 2.1` is not required, only the restated criterion."""
    from l4.specs.base import Finding
    from l4.specs.kiro import KiroProvider
    from l4.verifier.fixloop import FamilyProvider

    from ..orchestrator.test_kiro_unit import DISCOUNT_ID, REQUIREMENTS, SHOUT_ID, SPEC, TASKS
    from ..specs.test_kiro_fix_unit import UUID

    repo = tmp_path / "repo"
    (repo / SPEC).mkdir(parents=True)
    (repo / SPEC / "requirements.md").write_text(REQUIREMENTS)
    (repo / SPEC / "tasks.md").write_text(TASKS.replace("[ ]", "[x]"))
    provider = KiroProvider(repo, uuid_factory=lambda: UUID)
    parent = provider.list_units()[0]
    fix = provider.create_fix_unit(parent, 1, [Finding(("F-00000001",), "d", "d", "major", (DISCOUNT_ID,))], None)
    family = FamilyProvider(provider, parent)
    assert set(cited_criteria(family, fix, ("2.1",))) == {DISCOUNT_ID}
    assert SHOUT_ID not in cited_criteria(family, fix, ("2.1",))
    assert set(cited_criteria(provider, parent, ("2.1",))) == {SHOUT_ID}
    assert cited_criteria(provider, parent, ()) == {}  # an OpenSpec task has no links: nothing is required


def no_test_step(*criteria: str) -> Step:
    return Step(
        structured=result(
            "red", task_ids=["1"], criteria_ids=list(criteria), tdd_exemption={"reason": "already_satisfied by 0.9"}
        )
    )


def test_the_no_new_test_path_refuses_a_leaf_whose_cited_criterion_no_test_traces(make_kiro_bench):
    """SCN-IMP-296."""
    bench: Bench = make_kiro_bench([no_test_step(C11)])
    commit_old(bench)  # proved `Req 1.1` only
    before = bench.subjects()
    outcome = run_red(bench.wb, probe_task(bench), attempt=1)
    assert (outcome.status, outcome.reason) == ("failed", f"no test traces {C12} yet: write a new test for each")
    assert bench.subjects() == before and "[ ] 1." in (bench.wb.ref.path / "tasks.md").read_text()


def test_a_leaf_whose_cited_criteria_are_all_proved_is_already_satisfied(make_kiro_bench):
    """SCN-IMP-297: the step reports only `Req 1.1`, both are proved."""
    bench: Bench = make_kiro_bench([no_test_step(C11)])
    commit_old(bench, both=True)
    outcome = run_red(bench.wb, probe_task(bench), attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    proofs = bench.events("task.red_ok")[-1]["criteria"]
    assert {c: p["via"] for c, p in proofs.items()} == {C11: "earlier_red", C12: "earlier_red"}
    assert all(p["proof"] == "pre_satisfied" for p in proofs.values())
