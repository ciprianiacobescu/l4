"""L4-IMP-100 (SCN-IMP-541..546): a green attempt that passed every test and failed only a static gate that passed at
its base is kept in memory and is the start of the next attempt of the task, once."""

import hashlib
import json
from dataclasses import replace

from l4.agents.fake import Step
from l4.implementer import tdd
from l4.implementer.held_patch import expected_state, step_patch
from l4.implementer.loop import run_task
from l4.implementer.result import parse_result
from l4.implementer.tdd import run_green, run_red
from l4.specs.base import Task
from l4.vcs.git import GitError

from .conftest import IMPL, RUN_ID, green_step, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
LINT_IMPL = "sh -c 'if grep -q LINTBAD src/pytdd/pricing.py; then echo E501 line too long; exit 1; fi'"
TYPE_IMPL = "sh -c 'if grep -q TYPEBAD src/pytdd/pricing.py; then echo TS2698 type error; exit 1; fi'"
PRICING = "src/pytdd/pricing.py"
TWO = {"roles": {"implementer": ["impl", "impl-b"]}, "profiles": {"impl-b": {"adapter": "fake", "vendor": "otherco"}}}


def lint_bad(marker: str = "LINTBAD") -> Step:
    """A green step whose tests pass and whose lint (or type) gate fails: the marker is what the gate looks for."""
    return Step(writes={PRICING: IMPL + f"\n# {marker}\n"}, structured=result("green"))


def fixed() -> Step:
    """The step after a near pass: it only takes the marker away."""
    return Step(writes={PRICING: IMPL}, structured=result("green"))


def tree(bench) -> str:
    return (bench.wb.worktree / PRICING).read_text()


def watching(seen: list[str], step: Step) -> Step:
    """`step`, recording what its work tree holds when it starts."""

    def on_start(request) -> None:
        seen.append((request.cwd / PRICING).read_text())

    return replace(step, on_start=on_start)


def ledger(bench) -> list[dict]:
    lines = (bench.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def failed_green(bench) -> list[dict]:
    return [e for e in bench.events("task.attempt_failed") if e["phase"] == "green"]


# --- 1. the near pass is kept (D1, D2) -------------------------------------------------------------------------


def test_a_green_step_that_passes_every_test_and_fails_only_lint_is_a_near_pass(make_bench):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL], typecheck=[TYPE_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    base = bench.wb.head()
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "lint gate" in green.reason, green.reason
    near = green.near_pass
    assert near is not None
    assert (near.task, near.attempt, near.profile, near.gates) == ("1.1", 1, "impl", ("lint",))
    assert near.patch and near.patch_sha256 == hashlib.sha256(near.patch).hexdigest()
    assert near.files == (PRICING,) and b"LINTBAD" in near.patch
    assert bench.wb.head() == base and bench.wb.is_clean()  # back at the red commit
    assert "LINTBAD" not in tree(bench)


def test_the_near_pass_names_each_failed_gate_once_in_order(make_bench):
    both = Step(writes={PRICING: IMPL + "\n# LINTBAD\n# TYPEBAD\n"}, structured=result("green"))
    bench = make_bench([red_step(), both], lint=[LINT_IMPL], typecheck=[TYPE_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.near_pass is not None and green.near_pass.gates == ("lint", "typecheck")


def test_scn_imp_543_a_failed_test_is_no_near_pass(make_bench):
    lazy = Step(structured=result("green"))  # the red tests still fail
    bench = make_bench([red_step(), lazy], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.reason.startswith("red tests still failing")
    assert green.near_pass is None


def test_scn_imp_543_a_link_out_of_the_work_tree_is_no_near_pass(make_bench, monkeypatch):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    monkeypatch.setattr(tdd, "outside_links_reason", lambda wb, base, phase: "a link points outside the worktree")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "lint gate" in green.reason
    assert green.near_pass is None and bench.wb.is_clean()


def test_scn_imp_543_a_stuck_replay_restore_is_no_near_pass(make_bench, monkeypatch):
    bench = make_bench([red_step(), lint_bad()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    monkeypatch.setattr(tdd, "restore_replay", lambda wb, where: "the replayed step could not be put back")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.near_pass is None


def test_a_replayed_green_step_is_never_a_near_pass(make_bench, monkeypatch):
    bench = make_bench([red_step()], lint=[LINT_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)

    def replay(wb, role, task, attempt, found):  # what `replay_step` leaves: the step applied, the accept noted
        (wb.worktree / PRICING).write_text(IMPL + "\n# LINTBAD\n")
        wb.replay_question = "Q-001"
        wb.replay_expected = expected_state(wb, step_patch(wb))  # the guard keeps the step as it was saved
        wb.replay_links = {}
        return tdd.StepOutcome("ok", parse_result(result("green")))

    monkeypatch.setattr(tdd, "find_replay", lambda wb, role, task, *, attempt: None if role == "red" else object())
    monkeypatch.setattr(tdd, "replay_step", replay)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "lint gate" in green.reason, green.reason
    assert green.near_pass is None and bench.wb.is_clean()


# --- 2. it is applied once to the next attempt (D3, D4, D5) ----------------------------------------------------


def test_scn_imp_541_the_next_attempt_starts_from_a_near_pass(make_bench):
    seen: list[str] = []
    bench = make_bench([red_step(), lint_bad(), watching(seen, fixed())], lint=[LINT_IMPL])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert len(seen) == 1 and "LINTBAD" in seen[0] and "apply_discount" in seen[0]  # attempt 1's code was there
    [failed] = failed_green(bench)
    assert failed["near_pass"] is True and failed["attempt"] == 1
    [applied] = bench.events("task.near_pass_applied")
    got = (applied["task"], applied["attempt"], applied["from_attempt"], applied["from_profile"])
    assert got == ("1.1", 2, 1, "impl")
    assert applied["files"] == [PRICING] and len(applied["patch_sha256"]) == 64
    assert "LINTBAD" not in str(applied)  # the patch bytes are in no record
    types = [e["type"] for e in ledger(bench)]
    starts = [i for i, e in enumerate(ledger(bench)) if e["type"] == "step.started" and e.get("phase") == "green"]
    assert types.index("task.near_pass_applied") < starts[1]
    prompt = bench.adapter.requests[2].prompt  # red, green 1, green 2
    block = prompt.split('<l4:data kind="near-pass"', 1)[1].split("</l4:data>", 1)[0]
    assert "Attempt 1" in block and "profile impl" in block and "lint" in block
    assert "were discarded" not in prompt
    assert "near-pass" not in bench.adapter.requests[1].prompt  # attempt 1 had no carry


def test_the_failed_attempt_of_a_task_without_a_near_pass_has_no_near_pass_field(make_bench):
    bench = make_bench([red_step(), Step(structured=result("green")), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    [failed] = failed_green(bench)
    assert "near_pass" not in failed
    assert bench.events("task.near_pass_applied") == [] and bench.events("task.near_pass_dropped") == []


def test_scn_imp_542_an_escalation_keeps_the_near_pass(make_bench):
    from l4.implementer.workbench import PreviousAttempt

    from .test_escalation import Hook

    class Moving(Hook):
        def __call__(self, wb, request):  # as the orchestrator's `_escalate`: the block of the profile moved to
            fresh = super().__call__(wb, request)
            fresh.previous_attempt = PreviousAttempt(
                request.profile, None, request.task, why="escalation", phase=request.phase, failures=request.failures
            )
            return fresh

    seen: list[str] = []
    bench = make_bench(
        [red_step(), lint_bad(), watching(seen, fixed())], lint=[LINT_IMPL], implementer={"escalate_after": 1}, **TWO
    )
    hook = Moving()
    outcome = run_task(bench.wb, TASK, escalate=hook)
    assert outcome.status == "done", outcome.reason
    assert [r.phase for r in hook.requests] == ["green"]
    assert len(seen) == 1 and "LINTBAD" in seen[0]
    [applied] = bench.events("task.near_pass_applied")
    assert (applied["attempt"], applied["from_attempt"], applied["from_profile"]) == (2, 1, "impl")
    prompt = bench.adapter.requests[2].prompt
    assert "(see the near pass block)" in prompt and "from attempt 1 are in the checkout" in prompt
    assert "were discarded" not in prompt


def test_scn_imp_544_a_near_pass_is_applied_once(make_bench):
    seen: list[str] = []
    wrong = Step(writes={PRICING: IMPL.replace("100 -", "99 -") + "\n# WRONG\n"}, structured=result("green"))
    steps = [red_step(), lint_bad(), watching(seen, wrong), watching(seen, fixed())]
    bench = make_bench(steps, lint=[LINT_IMPL])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert "LINTBAD" in seen[0]  # attempt 2 started from attempt 1's changes
    assert "LINTBAD" not in seen[1] and "WRONG" not in seen[1]  # attempt 3 starts at the red commit
    assert [e["attempt"] for e in bench.events("task.near_pass_applied")] == [2]
    assert "near-pass" not in bench.adapter.requests[3].prompt


def test_scn_imp_544_a_second_near_pass_replaces_the_first(make_bench):
    seen: list[str] = []
    steps = [red_step(), lint_bad(), watching(seen, lint_bad("LINTBAD\n# SECOND")), watching(seen, fixed())]
    bench = make_bench(steps, lint=[LINT_IMPL], implementer={"max_task_attempts": 4})
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert "SECOND" not in seen[0] and "SECOND" in seen[1]  # attempt 3 starts from attempt 2's changes
    applied = bench.events("task.near_pass_applied")
    assert [(e["attempt"], e["from_attempt"]) for e in applied] == [(2, 1), (3, 2)]


def test_scn_imp_546_a_patch_that_does_not_apply_is_dropped(make_bench, monkeypatch):
    seen: list[str] = []
    bench = make_bench([red_step(), lint_bad(), watching(seen, fixed())], lint=[LINT_IMPL])
    real = bench.wb.git.run_input_bytes

    def refuse(*args, **kwargs):
        if "apply" in args:
            raise GitError(["git", "apply"], 1, "error: patch failed: src/pytdd/pricing.py:1\nsecond line")
        return real(*args, **kwargs)

    monkeypatch.setattr(bench.wb.git, "run_input_bytes", refuse)
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done", outcome.reason
    assert "LINTBAD" not in seen[0]  # it started from the red commit
    assert bench.events("task.near_pass_applied") == []
    [dropped] = bench.events("task.near_pass_dropped")
    assert (dropped["task"], dropped["attempt"], dropped["from_attempt"]) == ("1.1", 2, 1)
    assert "patch failed" in dropped["reason"] and "\n" not in dropped["reason"]
    assert "near-pass" not in bench.adapter.requests[2].prompt


def test_scn_imp_546_a_found_replay_drops_the_near_pass(make_bench, monkeypatch):
    bench = make_bench([red_step(), lint_bad(), lint_bad()], lint=[LINT_IMPL])
    calls: list[int] = []

    def found(wb, role, task, *, attempt):
        calls.append(attempt)
        return object() if role == "green" and attempt == 2 else None

    monkeypatch.setattr(tdd, "find_replay", found)
    monkeypatch.setattr(
        tdd, "replay_step", lambda wb, role, task, attempt, replay: tdd.StepOutcome("failed", reason="replayed")
    )
    outcome = run_task(bench.wb, TASK, escalate=None)
    assert calls[:3] == [1, 1, 2]  # red 1, green 1, green 2
    [dropped] = bench.events("task.near_pass_dropped")
    assert (dropped["attempt"], dropped["from_attempt"], dropped["reason"]) == (2, 1, "replay")
    assert bench.events("task.near_pass_applied") == []
    assert outcome.status == "halt"


# --- 3. the halt names the near pass (D6) ----------------------------------------------------------------------


def test_scn_imp_545_the_halt_names_the_nearest_attempt(make_bench):
    timeout = Step(status="timeout")
    bench = make_bench([red_step(), lint_bad(), timeout, timeout], lint=[LINT_IMPL])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt"
    assert outcome.reason.endswith(
        "; nearest: attempt 1 (impl) passed every test and failed only its lint or type gates"
    ), outcome.reason
    assert "last failure: the agent step reached its time limit" in outcome.reason
    [tripped] = bench.events("breaker.tripped")
    assert tripped["near_pass"] == {"attempt": 1, "profile": "impl"}


def test_a_halt_without_a_near_pass_has_today_s_reason(make_bench):
    lazy = Step(structured=result("green"))
    bench = make_bench([red_step(), lazy, lazy, lazy])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and "nearest" not in outcome.reason
    [tripped] = bench.events("breaker.tripped")
    assert "near_pass" not in tripped
