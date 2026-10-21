import json
from dataclasses import replace

import pytest

from l4.agents.fake import Step
from l4.implementer.loop import run_task, seed_attempts
from l4.specs.base import Task

from .conftest import KNOWN, RUN_ID, blocked_step, green_step, red_step, result
from .test_escalation import BAD, TWO, Hook, agents

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
TESTS_NEW = f'import pytest\n\n\n@pytest.mark.l4("{KNOWN}")\ndef test_new():\n    assert False\n'


def test_a_task_runs_red_then_green_and_is_done(make_bench):
    bench = make_bench([red_step(), green_step()])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done"
    assert [s.split("(")[0] for s in bench.subjects()] == ["test", "feat"]
    assert [e["task"] for e in bench.events("task.started")] == ["1.1"]


def test_blocked_result_writes_question_and_stops(make_bench):
    bench = make_bench([blocked_step()])
    outcome = run_task(bench.wb, TASK)
    assert (outcome.status, outcome.question_ids) == ("blocked", ["Q-001"])
    text = (bench.wb.ref.path / "questions.md").read_text()
    assert (
        "## Q-001: Which rounding?" in text and "- **Blocking tasks:** 1.1" in text and "- **Kind:** ambiguous" in text
    )
    assert "1. a" in text and "scenarios disagree" in text
    assert bench.subjects() == ["docs(add-discount-codes): questions [skip ci]"]
    committed = bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert sorted(p.rsplit("/", 1)[-1] for p in committed) == sorted(
        ["questions.md", bench.wb.ledger_rel.rsplit("/", 1)[-1]]
    )
    [raised] = bench.events("question.raised")
    assert (raised["id"], raised["task"], raised["kind"]) == ("Q-001", "1.1", "ambiguous")
    assert bench.pushes and len(bench.adapter.requests) == 1  # one agent call, then it stops
    assert "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()


def test_a_blocked_result_without_questions_still_raises_one(make_bench):
    bench = make_bench([Step(structured=result("red", status="blocked", summary="I cannot tell which rounding"))])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "blocked"
    text = (bench.wb.ref.path / "questions.md").read_text()
    assert "Task 1.1 is blocked" in text and "I cannot tell which rounding" in text


def test_a_second_run_of_a_blocked_task_appends_a_new_question(make_bench):
    bench = make_bench([blocked_step(), blocked_step()])
    run_task(bench.wb, TASK)
    outcome = run_task(bench.wb, TASK)
    assert outcome.question_ids == ["Q-002"]


def test_a_task_that_runs_again_after_a_block_keeps_the_blocked_steps_prompt_and_events(make_bench):
    bench = make_bench([blocked_step(), red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "blocked"
    assert run_task(bench.wb, TASK).status == "done"  # the clarifier answered: the same run goes on
    published = {p.name for p in (bench.wb.out_dir / "agent").rglob("*.prompt.md")}
    assert published == {"1.1-red-1.prompt.md", "1.1-red-1-r2.prompt.md", "1.1-green-1.prompt.md"}
    assert {p.name for p in (bench.wb.out_dir / "agent").rglob("*.jsonl")} == {
        "1.1-red-1.jsonl", "1.1-red-1-r2.jsonl", "1.1-green-1.jsonl",
    }  # fmt: skip


def test_a_rejected_red_is_retried_with_the_reason_in_the_prompt(make_bench):
    bench = make_bench([Step(structured=result("red")), red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    second = bench.adapter.requests[1].prompt
    assert "Your previous attempt was rejected" in second and "no tests added" in second
    assert "previous attempt was rejected" not in bench.adapter.requests[0].prompt
    assert [e["reason"] for e in bench.events("task.attempt_failed")] == ["no tests added"]


def test_only_green_is_retried_once_red_is_committed(make_bench):
    bench = make_bench([red_step(), Step(structured=result("green")), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    phases = [("# Phase: RED" in r.prompt) for r in bench.adapter.requests]
    assert phases == [True, False, False]
    assert "red tests still failing" in bench.adapter.requests[2].prompt


def test_attempts_run_out_and_the_unit_halts(make_bench):
    bench = make_bench(
        [Step(structured=result("red")), Step(structured=result("red"))], implementer={"max_task_attempts": 2}
    )
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and "max_task_attempts" in outcome.reason
    [tripped] = bench.events("breaker.tripped")
    assert (tripped["task"], tripped["attempts"]) == ("1.1", 2)
    assert len(bench.adapter.requests) == 2


def test_a_committed_red_is_resumed_at_green_not_redone(make_bench):
    from l4.implementer.tdd import run_red

    bench = make_bench([red_step(), green_step()])
    assert run_red(bench.wb, TASK, attempt=1).status == "ok"  # the earlier run died after this commit
    bench.wb.ledger.append("chore.noise")  # and left unrelated commits on top
    bench.wb.git.run(
        "commit", "-q", "--allow-empty", "-m", "chore: ledger", config=(("user.name", "t"), ("user.email", "t@x"))
    )
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done"
    assert len(bench.adapter.requests) == 2  # one red (before the "crash"), one green: no second red
    assert "# Phase: GREEN" in bench.adapter.requests[1].prompt
    assert [e["task"] for e in bench.events("task.red_resumed")] == ["1.1"]
    assert [s.split("(")[0] for s in bench.subjects()] == ["test", "chore: ledger", "feat"]


def test_attempts_count_per_phase_so_green_starts_at_one_after_a_failed_red(make_bench):
    bench = make_bench([Step(structured=result("red")), red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    trailers = bench.wb.git.run("log", "--format=%(trailers:key=L4-Step,valueonly)", "main..HEAD").stdout.split()
    assert sorted(trailers) == ["1.1/green/1", "1.1/red/2"]
    started = [(e["phase"], e["attempt"]) for e in bench.events("step.started")]
    assert started == [("red", 1), ("red", 2), ("green", 1)]


def test_agent_finished_counts_denials_and_each_codex_rejection_is_an_event(make_bench):
    """HB-6: denials are recoverable, but they were never visible; the count and the tools are on `agent.finished`."""
    red = red_step()
    red.permission_denials = [{"tool_name": "Bash", "tool_input": {"command": "ls /"}}, {"tool_name": "Write"}]
    red.tool_rejections = [{"tool": "exec_command", "reason": "rm -f style commands are not permitted"}]
    bench = make_bench([red, green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    first, second = bench.events("agent.finished")
    assert first["permission_denials"] == 2 and first["denied_tools"] == ["Bash", "Write"]
    assert second["permission_denials"] == 0 and second["denied_tools"] == []
    [rejected] = bench.events("agent.tool_rejected")
    assert (rejected["task"], rejected["phase"], rejected["tool"]) == ("1.1", "red", "exec_command")
    assert "rm -f" in rejected["reason"] and "command" not in {k for k in rejected if k == "tool_input"}


def test_green_has_its_own_attempt_budget_after_a_late_red(make_bench):
    """Live M1.8 job 5561: two failed rereds left green one attempt, because failures were shared."""
    bench = make_bench(
        [
            Step(structured=result("red")), Step(structured=result("red")), red_step(),
            Step(structured=result("green")), Step(structured=result("green")), green_step(),
        ],
        implementer={"max_task_attempts": 3},
    )  # fmt: skip
    assert run_task(bench.wb, TASK).status == "done"
    assert not bench.events("breaker.tripped")
    failed = [(e["phase"], e["attempt"]) for e in bench.events("task.attempt_failed")]
    assert failed == [("red", 1), ("red", 2), ("green", 1), ("green", 2)]


def test_red_budget_exhausted_halts_with_phase_red(make_bench):
    bench = make_bench([Step(structured=result("red"))] * 3, implementer={"max_task_attempts": 3})
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and "red" in outcome.reason and "max_task_attempts" in outcome.reason
    [tripped] = bench.events("breaker.tripped")
    assert (tripped["phase"], tripped["attempts"]) == ("red", 3)


def test_green_budget_exhausted_halts_with_phase_green(make_bench):
    bench = make_bench([red_step()] + [Step(structured=result("green"))] * 2, implementer={"max_task_attempts": 2})
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and "green" in outcome.reason
    [tripped] = bench.events("breaker.tripped")
    assert (tripped["phase"], tripped["attempts"]) == ("green", 2)


def test_single_phase_budget_unchanged(make_bench, monkeypatch):
    from types import SimpleNamespace

    import l4.implementer.loop as loop

    calls = []

    def failing(wb, task, findings, *, attempt, previous_failure, kind="fix", retake=False):
        calls.append(attempt)
        return SimpleNamespace(status="failed", reason="still wrong", questions=[], summary="", excerpt="")

    monkeypatch.setattr(loop, "chore_findings", lambda path, title: ("F-00000001",))
    monkeypatch.setattr(loop, "run_single", failing)
    bench = make_bench([], implementer={"max_task_attempts": 2})
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and calls == [1, 2]
    [tripped] = bench.events("breaker.tripped")
    assert (tripped["phase"], tripped["attempts"]) == ("single", 2)


def test_attempt_failed_keeps_the_headline_only(make_bench):
    wreck = Step(
        writes={
            "tests/test_discount.py": TESTS_NEW,
            "tests/test_pricing.py": "def test_total_adds_prices():\n    open('data/missing.csv')\n",
        },
        structured=result("red"),
    )
    bench = make_bench([wreck, red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    [failed] = bench.events("task.attempt_failed")
    assert failed["reason"].startswith("red broke existing tests: ")
    assert "FileNotFoundError" not in failed["reason"] and "\n" not in failed["reason"]
    assert failed["excerpt_lines"] >= 3


def test_the_second_red_attempt_sees_the_first_attempts_error(make_bench):
    wreck = Step(
        writes={
            "tests/test_discount.py": TESTS_NEW,
            "tests/test_pricing.py": "def test_total_adds_prices():\n    open('data/missing.csv')\n",
        },
        structured=result("red"),
    )
    bench = make_bench([wreck, red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    second = bench.adapter.requests[1].prompt
    fence = second.split("# Your previous attempt was rejected", 1)[1].split("# ", 1)[0]
    assert "E       FileNotFoundError" in fence and "tests/test_pricing.py:2" in fence
    assert "previous attempt" in fence
    assert "FileNotFoundError" not in bench.adapter.requests[0].prompt


# --- W-D1: a frozen test that hangs twice becomes one question, not a halt ---------------------------------

HANGS = (
    "import socket\n\nimport pytest\n\nfrom pytdd.pricing import apply_discount\n\n\n"
    f'@pytest.mark.l4("{KNOWN}", "C-d80f494d")\n'
    "def test_known_code():\n"
    '    assert apply_discount(50.0, "SAVE10") == 45.0\n'
    "    server_side, client = socket.socketpair()\n"
    "    client.recv(1)\n"
)


def _hanging_red():
    from l4.agents.fake import Step

    from .conftest import STUB

    return Step(
        writes={"tests/test_discount.py": HANGS, "src/pytdd/pricing.py": STUB},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, "C-d80f494d"]
        ),
    )


def test_a_frozen_test_that_hangs_raises_one_question_naming_its_file_at_once(make_bench):
    bench = make_bench([_hanging_red(), green_step(), green_step(), green_step()], test_timeout="2s")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "blocked" and len(outcome.question_ids) == 1
    assert len(bench.adapter.requests) == 2  # red, green: not three greens and a halt
    text = (bench.wb.ref.path / "questions.md").read_text()
    assert "Frozen test tests.test_discount::test_known_code hangs once the code works" in text
    assert "Edit `tests/test_discount.py`:" in text and "client.recv(1)" in text
    assert "Suggested answer" in text or "Edit `tests/test_discount.py`" in text
    assert bench.events("breaker.tripped") == []
    assert len(bench.events("gate.hung")) == 1
    assert "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()


def test_a_hang_in_a_test_that_is_not_frozen_is_retried_with_the_test_named(make_bench):
    from l4.agents.fake import Step

    from .conftest import IMPL

    hanging_impl = IMPL + (
        "\n\ndef wait_forever():\n    import socket\n    a, b = socket.socketpair()\n    a.recv(1)\n"
    )
    extra = "import pytest\n\nfrom pytdd.pricing import wait_forever\n\n\ndef test_extra_waits():\n    wait_forever()\n"
    writes = {"src/pytdd/pricing.py": hanging_impl, "tests/test_extra.py": extra}
    green = Step(writes=writes, structured=result("green"))
    bench = make_bench([red_step(), green, blocked_step()], test_timeout="2s")
    outcome = run_task(bench.wb, replace(TASK, title=f"{TASK.title} [test-infra]"))  # may add a test file
    assert outcome.status == "blocked"  # the second attempt's own blocked result: the first was a retry, not a question
    second_prompt = bench.adapter.requests[2].prompt
    assert "hung" in second_prompt and "tests.test_extra::test_extra_waits" in second_prompt
    assert len(bench.events("gate.hung")) == 1


def test_a_blocked_green_with_a_support_file_in_option_1_gets_the_note_that_offers_accepted(make_bench):
    """SCN-IMP-170: 0.4.1 offered `accepted` for `conftest.py` and the code refused it; now it unfreezes it."""
    question = {
        "title": "The fixture in conftest.py hides the setting",
        "context": "conftest.py sets the variable before the test runs.",
        "kind": "technical",
        "options": ["Edit `conftest.py`: remove the line", "Keep it"],
    }
    red = red_step()
    red = replace(red, writes={**red.writes, "conftest.py": "import os\n\nos.environ['X'] = '1'\n"})
    blocked = Step(structured=result("green", status="blocked", questions=[question]))
    bench = make_bench([red, blocked])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "blocked"
    text = (bench.wb.ref.path / "questions.md").read_text()
    assert "Harness note:" in text and "`conftest.py`" in text.split("Harness note:")[1]
    assert "l4 questions accept Q-NNN --unit add-discount-codes" in text
    assert "ignore file" in text


def test_task_attempt_failed_carries_a_bounded_excerpt(make_bench):
    """L4-IMP-064: the E lines and the deepest repository location of the failure, in the committed ledger."""
    wreck = Step(
        writes={
            "tests/test_discount.py": TESTS_NEW,
            "tests/test_pricing.py": "def test_total_adds_prices():\n    open('data/missing.csv')\n",
        },
        structured=result("red"),
    )
    bench = make_bench([wreck, red_step(), green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    [failed] = bench.events("task.attempt_failed")
    assert "FileNotFoundError" in failed["excerpt"]
    assert len(failed["excerpt"]) <= 600 and "tests/test_pricing.py:2" in failed["excerpt"]
    assert failed["excerpt_lines"] >= 3  # unchanged


# --- failed attempts count across runs (L4-IMP-075, D7b) ----------------------------------------------------------


def fail(bench, phase: str, attempt: int, profile: str = "impl", reason: str = "r", **more: object) -> None:
    """An earlier run's failed attempt, on the bench's ledger."""
    bench.writer.append(
        "task.attempt_failed", task="1.1", phase=phase, attempt=attempt, profile=profile, reason=reason, **more
    )


@pytest.mark.parametrize("reset", ["unit.retried", "unit.resumed", "unit.restarted"])
def test_seed_attempts_reads_the_window(make_bench, reset):
    """Failures before the task's last commit or before a retry, resume or restart, of another task, or of another
    fix unit are not counted; the rest give the counts, the reasons and the highest attempt, stops included."""
    bench = make_bench([], **TWO)
    w = bench.writer
    fail(bench, "red", 1, reason="before the red commit")
    w.append("task.red_committed", task="1.1", base="b", sha="s")
    fail(bench, "green", 1, reason="before the reset")
    w.append(reset, reason="again")
    fail(bench, "green", 2, reason="g1")
    w.append("task.attempt_failed", task="1.2", phase="green", attempt=9, profile="impl", reason="another task")
    fail(bench, "green", 8, reason="another fix unit", fix_unit="fix-1")
    fail(bench, "green", 3, profile="impl-b", reason="g2")
    w.append("deadline.reached", when="during", phase="green", task="1.1", attempt=4, first=True)
    w.append("deadline.reached", when="before", phase="green", task="1.1", attempt=7)  # not started: no attempt
    seeded = seed_attempts(bench.wb, TASK)
    assert seeded.failures["green"] == {"impl": 1, "impl-b": 1} and seeded.failures["red"] == {}
    assert seeded.reasons["green"] == [("impl", "g1"), ("impl-b", "g2")]
    assert seeded.attempts == {"red": 0, "green": 4}


def test_seed_attempts_is_empty_for_a_task_that_never_ran(make_bench):
    seeded = seed_attempts(make_bench([]).wb, TASK)
    assert seeded.failures == {"red": {}, "green": {}, "single": {}} and seeded.attempts == {"red": 0, "green": 0}


def test_a_chores_attempts_are_the_green_ones(make_bench):
    bench = make_bench([])
    fail(bench, "single", 1)
    bench.writer.append("deadline.reached", when="during", phase="single", task="1.1", attempt=2, first=True)
    seeded = seed_attempts(bench.wb, TASK)
    assert seeded.failures["single"] == {"impl": 1} and seeded.attempts == {"red": 0, "green": 2}


def test_seeded_failures_reach_max_task_attempts(make_bench):
    """Two red failures of earlier runs and `max_task_attempts: 3`: one more failure halts the task."""
    bench = make_bench([BAD])
    fail(bench, "red", 1)
    fail(bench, "red", 2)
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and len(bench.adapter.requests) == 1
    assert agents(bench) == [("red", "impl", 3)]  # the attempt number continues after the failed ones
    [tripped] = bench.events("breaker.tripped")
    assert (tripped["reason"], tripped["attempts"]) == ("max_task_attempts", 3)


def test_the_limit_is_already_reached_before_any_attempt(make_bench):
    bench = make_bench([BAD])
    for attempt in (1, 2, 3):
        fail(bench, "red", attempt, reason=f"r{attempt}")
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt" and bench.adapter.requests == []
    assert "last failure: r3" in outcome.reason and "None" not in outcome.reason  # A-m3


def test_seeded_failures_escalate_before_the_first_attempt(make_bench):
    """SCN-IMP-379 at loop level: two failures on `impl` in earlier runs, a later profile in the chain."""
    bench = make_bench([red_step(), green_step()], **TWO)
    fail(bench, "red", 1, reason="first")
    fail(bench, "red", 2, reason="second")
    hook = Hook()
    assert run_task(bench.wb, TASK, escalate=hook).status == "done"
    [request] = hook.requests
    assert (request.task, request.phase, request.profile, request.attempt) == ("1.1", "red", "impl", 3)
    assert request.failures == (("impl", "first"), ("impl", "second"))
    [moved] = bench.events("implementer.escalated")
    assert (moved["from"], moved["to"], moved["failures"], moved["attempt"]) == ("impl", "impl-b", 2, 3)
    lines = (bench.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl").read_text().splitlines()
    types = [json.loads(line)["type"] for line in lines]
    assert types.index("implementer.escalated") < types.index("step.started")
    assert agents(bench) == [("red", "impl-b", 3), ("green", "impl-b", 1)]


class ChainHook:
    """A fake `escalate` that moves to the next profile of `roles.implementer`, as the real hook does."""

    def __init__(self, chain: list[str]) -> None:
        self.chain, self.requests = chain, []

    def __call__(self, wb, request):
        self.requests.append(request)
        nxt = self.chain[self.chain.index(request.profile) + 1]
        return replace(wb, selected=replace(wb.selected, profile_name=nxt))


THREE = {
    "roles": {"implementer": ["impl", "impl-b", "impl-c"]},
    "profiles": {
        "impl-b": {"adapter": "fake", "vendor": "otherco"},
        "impl-c": {"adapter": "fake", "vendor": "thirdco"},
    },
    "implementer": {"escalate_after": 2, "max_task_attempts": 3},
}


def test_seeded_failures_escalate_through_several_profiles_before_the_first_attempt(make_bench):
    """A-M1: impl and impl-b each failed twice in an earlier run: the run starts on impl-c, not on impl-b's third."""
    bench = make_bench([red_step(), green_step()], **THREE)
    for attempt, profile in ((1, "impl"), (2, "impl"), (3, "impl-b"), (4, "impl-b")):
        fail(bench, "red", attempt, profile=profile)
    hook = ChainHook(["impl", "impl-b", "impl-c"])
    assert run_task(bench.wb, TASK, escalate=hook).status == "done"
    assert [r.profile for r in hook.requests] == ["impl", "impl-b"]
    moved = [(e["from"], e["to"]) for e in bench.events("implementer.escalated")]
    assert moved == [("impl", "impl-b"), ("impl-b", "impl-c")]
    assert agents(bench) == [("red", "impl-c", 5), ("green", "impl-c", 1)]


def test_a_seeded_failure_below_escalate_after_does_not_escalate(make_bench):
    bench = make_bench([red_step(), green_step()], **TWO)
    fail(bench, "red", 1)
    hook = Hook()
    assert run_task(bench.wb, TASK, escalate=hook).status == "done" and hook.requests == []
    assert agents(bench)[0] == ("red", "impl", 2)


def test_a_chore_question_cannot_unfreeze_a_file(make_bench, monkeypatch):
    """SCN-IMP-398: a technical question of a blocked fix chore gets the note that a person commits the change; a
    blocked green question keeps the unfreeze note."""
    import l4.implementer.loop as loop

    asking = {
        "title": "Unfreeze tests/conftest.py?",
        "context": "the fixture must change",
        "kind": "technical",
        "options": ["Edit `tests/conftest.py`: set the environment in a fixture"],
    }
    monkeypatch.setattr(loop, "chore_findings", lambda path, title: ("F-00000001",))
    bench = make_bench([Step(structured=result("single", status="blocked", questions=[asking]))])
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "blocked"
    text = (bench.wb.ref.path / "questions.md").read_text()
    assert "Harness note: this is a fix task. It cannot unfreeze a test or test-support file" in text
    assert "A person must commit the change on the unit branch themselves, then answer this question" in text
    assert 'l4 questions answer Q-NNN --unit openspec:add-discount-codes --text "..."' in text
    assert "the red tests and test-support files of this task are frozen" not in text


def test_a_fix_units_chore_question_names_the_answer_not_a_retry_of_the_fix_unit(make_bench, monkeypatch):
    """review M2: the workbench of a real run is the fix unit's; `l4 retry --unit <fix unit>` is refused, so the note
    names the answer on the fix unit (D13 resolves it to the parent's branch)."""
    from dataclasses import replace

    import l4.implementer.loop as loop

    asking = {"title": "Unfreeze tests/conftest.py?", "context": "the fixture must change", "kind": "technical"}
    monkeypatch.setattr(loop, "chore_findings", lambda path, title: ("F-00000001",))
    bench = make_bench([Step(structured=result("single", status="blocked", questions=[asking]))])
    object.__setattr__(bench.wb, "ref", replace(bench.wb.ref, name=f"{bench.wb.ref.name}-fix-1"))
    fix_id = bench.wb.ref.id
    assert fix_id.endswith("-fix-1")
    assert run_task(bench.wb, TASK).status == "blocked"
    text = (bench.wb.ref.path / "questions.md").read_text()
    assert f'l4 questions answer Q-NNN --unit {fix_id} --text "..."' in text
    assert "l4 retry" not in text
