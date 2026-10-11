from dataclasses import replace

from l4.agents.fake import Step
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer.tdd import check_green, run_green, run_red
from l4.specs.base import Task

from .conftest import IMPL, KNOWN, STUB, TESTS, UNKNOWN, blocked_step, green_step, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)


def red_green(make_bench, green: Step, task: Task = TASK, *, attempt: int = 1):
    bench = make_bench([red_step(), green])
    red = run_red(bench.wb, task, attempt=1)
    assert red.status == "ok", red.reason
    return bench, red, run_green(bench.wb, task, red, attempt=attempt)


def test_green_marks_task_done_and_commits_with_trailer(make_bench):
    bench, red, green = red_green(make_bench, green_step())
    assert green.status == "ok", green.reason
    tasks = (bench.wb.ref.path / "tasks.md").read_text()
    assert "- [x] 1.1 Add" in tasks and "[ ]" not in tasks  # one byte, in the same commit as the code
    message = bench.wb.git.run("log", "-1", "--format=%B").stdout
    assert message.splitlines()[0] == "feat(add-discount-codes): 1.1 Add `apply_discount` [skip ci]"
    assert "L4-TDD: green" in message and "L4-Step: 1.1/green/1" in message
    changed = bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert any(p.endswith("tasks.md") for p in changed) and "src/pytdd/pricing.py" in changed
    [done] = bench.events("task.done")
    assert done["task"] == "1.1" and done["base"] == red.sha  # the commit carries it, so it cannot name itself
    assert '"type": "task.done"' in bench.wb.git.run("show", f"{green.sha}:{bench.wb.ledger_rel}").stdout
    # red first, then green, on the unit branch
    subjects = bench.subjects()
    assert subjects[0].startswith("test(") and subjects[1].startswith("feat(")
    assert bench.pushes == [red.sha, green.sha]


def test_green_edit_to_a_red_test_is_restored_and_recorded(make_bench):
    cheat = Step(
        writes={"src/pytdd/pricing.py": IMPL, "tests/test_discount.py": TESTS.replace("== 45.0", "== 50.0")},
        structured=result("green"),
    )
    bench, red, green = red_green(make_bench, cheat)
    assert green.status == "ok", green.reason  # the restored test passes against the real implementation
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == TESTS
    assert [e["path"] for e in bench.events("guard.test_tamper")] == ["tests/test_discount.py"]


def test_green_that_does_not_make_the_red_tests_pass_fails_and_keeps_the_red_commit(make_bench):
    lazy = Step(structured=result("green"))
    bench, red, green = red_green(make_bench, lazy)
    assert green.status == "failed" and green.reason.startswith("red tests still failing")
    assert bench.wb.head() == red.sha
    assert "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()
    assert bench.events("task.done") == []


def test_green_that_breaks_an_existing_test_fails(make_bench):
    breaker = Step(
        writes={"src/pytdd/pricing.py": IMPL.replace("round(sum(prices), 2)", "0")}, structured=result("green")
    )
    _, _, green = red_green(make_bench, breaker)
    assert green.status == "failed" and green.reason.startswith("green broke existing tests: ")


def test_green_that_adds_a_failing_test_of_its_own_fails(make_bench):
    extra = "def test_extra():\n    assert False\n"
    sneaky = Step(writes={"src/pytdd/pricing.py": IMPL, "tests/test_extra.py": extra}, structured=result("green"))
    # the human `[test-infra]` tag lets the task add a test file; without it the file is removed (test path freeze)
    _, _, green = red_green(make_bench, sneaky, replace(TASK, title=f"{TASK.title} [test-infra]"))
    assert green.status == "failed" and green.reason == "new failing tests added in green: tests.test_extra::test_extra"


def test_green_blocked_resets_to_the_red_commit(make_bench):
    step = blocked_step()
    step.writes = {"src/pytdd/pricing.py": "garbage\n"}
    bench, red, green = red_green(make_bench, step)
    assert green.status == "blocked" and green.questions[0].kind == "ambiguous"
    assert bench.wb.head() == red.sha
    assert "garbage" not in (bench.wb.worktree / "src" / "pytdd" / "pricing.py").read_text()


def test_ticking_the_last_child_ticks_the_parent_in_the_same_commit(make_bench):
    bench = make_bench([red_step(), green_step()])
    (bench.wb.ref.path / "tasks.md").write_text("- [ ] 1.1 Parent\n  - [ ] 1.1.1 Child\n")
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("-c", "user.name=t", "-c", "user.email=t@x.invalid", "commit", "-q", "-m", "nested tasks")
    child = Task("1.1.1", "1.1.1", "1.1.1 Child", False, " ", 2, 2, 3)
    red = run_red(bench.wb, child, attempt=1)
    run_green(bench.wb, child, red, attempt=1)
    assert (bench.wb.ref.path / "tasks.md").read_text() == "- [x] 1.1 Parent\n  - [x] 1.1.1 Child\n"
    assert bench.events("task.done")[0]["parents"] == ["1.1"]


def report(**status: str) -> TestReport:
    return TestReport({i: TestCase(i, s) for i, s in status.items()})  # type: ignore[arg-type]


def gate(rep: TestReport | None, **kw) -> GateResult:
    from pathlib import Path

    return GateResult("test", "fail", kw.pop("reason", "exit code 1"), 1, Path("x.log"), rep, **kw)


def test_check_green_reasons():
    base = report(old="passed", old_fail="failed")
    assert check_green(base, ["new"], gate(report(old="passed", old_fail="failed", new="passed"))) == ""
    assert "no readable report" in check_green(base, ["new"], gate(None))
    assert check_green(base, ["new"], gate(None, reason="timed out after 5s", timed_out=True)) == "timed out after 5s"
    assert check_green(base, ["new"], gate(report())) == "vacuous: 0 tests executed"
    collect = TestReport({"a": TestCase("a", "passed")}, ["tests.test_x"])
    assert check_green(base, ["a"], gate(collect)).startswith("tests not collected")
    assert check_green(base, ["new"], gate(report(old="passed", new="failed"))) == "red tests still failing: new"
    assert check_green(base, ["new"], gate(report(old="error", new="passed"))) == "green broke existing tests: old"
    assert check_green(base, ["new"], gate(report(new="passed"))) == "green broke existing tests: old"
    extra = report(old="passed", old_fail="failed", new="passed", extra="failed")
    assert check_green(base, ["new"], gate(extra)) == "new failing tests added in green: extra"
    assert check_green(base, ["new"], gate(report(old="passed", new="passed", extra="skipped"))) == ""


def test_green_whose_code_fails_lint_is_a_failed_attempt_and_the_agent_sees_why(make_bench):
    lint = "sh -c 'if grep -q round.amount src/pytdd/pricing.py; then echo E501 too long; exit 1; fi'"
    bench = make_bench([red_step(), green_step()], lint=[lint])  # passes at the base, fails once green implements
    red = run_red(bench.wb, TASK, attempt=1)
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "lint gate" in green.reason and "E501 too long" in green.reason
    assert bench.events("task.done") == [] and bench.wb.head() == red.sha
    assert "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()


def test_green_passes_when_lint_and_typecheck_pass_and_the_prompt_names_them(make_bench):
    bench = make_bench([red_step(), green_step()], lint=["true"], typecheck=["true"])
    red = run_red(bench.wb, TASK, attempt=1)
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"
    red_prompt, green_prompt = (r.prompt for r in bench.adapter.requests)
    assert "`true`" in green_prompt and "rejects the task while they fail" in green_prompt
    assert "rejects the task while they fail" not in red_prompt  # red has its own wording (test_tdd_static)


def test_notes_for_verifier_are_kept_in_the_ledger_for_the_verifier(make_bench):
    bench = make_bench(
        [
            Step(writes=red_step().writes, structured=result("red", tests_added=["x"], notes_for_verifier="red note")),
            Step(writes=green_step().writes, structured=result("green", notes_for_verifier="green note")),
        ]
    )
    red = run_red(bench.wb, TASK, attempt=1)
    run_green(bench.wb, TASK, red, attempt=1)
    assert bench.events("task.red_ok")[0]["notes"] == "red note"
    assert bench.events("task.done")[0]["notes"] == "green note"


# --- M1.10 (C2): a human answer that names a frozen test unfreezes it for green (decisions 6 to 8) ---

EXTRA_TEST = (
    "import pytest\n\nfrom pytdd.pricing import apply_discount\n\n\n"
    f'@pytest.mark.l4("{KNOWN}")\ndef test_extra():\n    assert apply_discount(10.0, "SAVE10") == 9.0\n'
)
CORRECTED = TESTS.replace('apply_discount(50.0, "SAVE10") == 45.0', 'apply_discount(100.0, "SAVE10") == 90.0')
TWO_TESTS = ["tests/test_discount.py::test_known_code", "tests/test_extra.py::test_extra"]


def two_test_red() -> Step:
    return Step(
        writes={"tests/test_discount.py": TESTS, "tests/test_extra.py": EXTRA_TEST, "src/pytdd/pricing.py": STUB},
        structured=result("red", tests_added=TWO_TESTS, criteria_ids=[KNOWN, UNKNOWN]),
    )


def answer_naming(bench, raw, text: str, status: str = "accepted") -> None:
    """A human accepted a clarifier suggestion that names `text`, and the re-entry recorded it (as `l4 run` does)."""
    from l4.redact import Redactor
    from l4.specs.questions import (
        NewQuestion,
        QuestionKind,
        QuestionsFile,
        QuestionStatus,
        answer_sha256,
        raise_questions,
    )

    unit = bench.wb.ref.path
    raise_questions(
        unit, "add-discount-codes",
        [NewQuestion("The test freezes a wrong value", QuestionKind.TECHNICAL, ("1.1",),
                     "tests/test_discount.py:9 expects 45.0 for 50.0", "now", ("a", "b"))],
        redactor=Redactor({}),
    )  # fmt: skip
    file = QuestionsFile.load(unit / "questions.md")
    file = file.set_suggestion("Q-001", text, redactor=Redactor({})).set_status("Q-001", QuestionStatus(status))
    file.save(unit / "questions.md")
    raw(bench.wb.worktree, "add", "-A")
    raw(
        bench.wb.worktree, "-c", "user.name=Pat", "-c", "user.email=pat@example.invalid", "commit", "-q", "-m", "answer"
    )
    digest = answer_sha256(QuestionsFile.load(unit / "questions.md").get("Q-001"))
    bench.writer.append("question.answered", id="Q-001", by="human", answer_sha256=digest)


def test_an_unfrozen_test_edit_is_kept_and_recorded(make_bench, raw):
    bench = make_bench([two_test_red(), Step(writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL},
                                             structured=result("green"))])  # fmt: skip
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    answer_naming(bench, raw, "Change `tests/test_discount.py:9` to use a 100.0 amount.")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == CORRECTED  # kept, not restored
    assert [e["path"] for e in bench.events("guard.test_tamper")] == []  # it stays a test of the task
    [event] = bench.events("task.unfrozen")
    assert event["task"] == "1.1" and event["paths"] == ["tests/test_discount.py"] and event["question"] == "Q-001"
    assert event["red_sha"] == red.sha and len(event["answer_sha256"]) == 64
    assert "tests/test_discount.py" in bench.adapter.requests[-1].prompt.split("# Tests unfrozen")[1]
    assert bench.wb.git.run("show", f"{green.sha}:tests/test_discount.py").stdout == CORRECTED


def test_other_frozen_tests_are_still_restored(make_bench, raw):
    both = Step(
        writes={
            "tests/test_discount.py": CORRECTED, "tests/test_extra.py": EXTRA_TEST.replace("== 9.0", "== 10.0"),
            "src/pytdd/pricing.py": IMPL,
        },
        structured=result("green"),
    )  # fmt: skip
    bench = make_bench([two_test_red(), both])
    red = run_red(bench.wb, TASK, attempt=1)
    answer_naming(bench, raw, "Change tests/test_discount.py only.")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason  # the restored extra test passes against the implementation
    assert (bench.wb.worktree / "tests" / "test_extra.py").read_text() == EXTRA_TEST
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == CORRECTED
    assert [e["path"] for e in bench.events("guard.test_tamper")] == ["tests/test_extra.py"]


def test_a_corrected_test_that_passes_at_red_is_rejected(make_bench, raw):
    vacuous = TESTS.replace('    assert apply_discount(50.0, "SAVE10") == 45.0\n', "    assert True\n")
    bench = make_bench([two_test_red(), Step(writes={"tests/test_discount.py": vacuous, "src/pytdd/pricing.py": IMPL},
                                             structured=result("green"))])  # fmt: skip
    red = run_red(bench.wb, TASK, attempt=1)
    answer_naming(bench, raw, "Change `tests/test_discount.py` as you see fit.")
    before = bench.wb.head()
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "no longer discriminates" in green.reason
    assert "tests.test_discount::test_known_code" in green.reason  # the id that passes against the red code
    assert bench.wb.head() == before and bench.events("task.done") == []
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == TESTS  # the attempt is discarded
    assert bench.events("task.unfrozen")  # the attempt was recorded as unfrozen all the same


def test_a_corrected_test_that_fails_at_red_is_accepted(make_bench, raw):
    fix = Step(writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL}, structured=result("green"))
    bench = make_bench([two_test_red(), fix])
    red = run_red(bench.wb, TASK, attempt=1)
    answer_naming(bench, raw, "Change `tests/test_discount.py`.")
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "ok", green.reason
    assert (bench.wb.worktree / "src" / "pytdd" / "pricing.py").read_text() == IMPL  # the swap was put back
    assert bench.wb.is_clean()


def test_the_swap_is_restored_when_the_gate_raises(make_bench):
    import pytest

    from l4.implementer.discrimination import fails_at_red

    bench = make_bench([two_test_red()])
    red = run_red(bench.wb, TASK, attempt=1)
    pricing = bench.wb.worktree / "src" / "pytdd" / "pricing.py"
    pricing.write_text(IMPL)  # what green wrote, uncommitted
    added = bench.wb.worktree / "src" / "pytdd" / "added_by_green.py"
    added.write_text("X = 1\n")  # a module green added has no red version: it is set aside during the run
    seen: list[tuple[str, bool]] = []

    def boom(*args, **kwargs):
        seen.append((pricing.read_text(), added.exists()))
        raise RuntimeError("the gate crashed")

    bench.wb.run_gate = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="the gate crashed"):
        fails_at_red(bench.wb, red.sha, ["tests.test_discount::test_known_code"])
    assert seen == [(STUB, False)]  # at the gate the code was the red commit's
    assert pricing.read_text() == IMPL and added.read_text() == "X = 1\n"


def test_an_id_the_run_at_red_does_not_report_is_not_failing_there(make_bench):
    """Fail closed (review of M1.10 line 12): an id the run at red did not report (its module did not even import the
    red code: a collection error) or a run that wrote no report (a crash, a timeout) proves nothing, so the id does not
    count as failing at red."""
    from l4.implementer.discrimination import fails_at_red

    bench = make_bench([two_test_red()])
    red = run_red(bench.wb, TASK, attempt=1)
    known, extra = "tests.test_discount::test_known_code", "tests.test_extra::test_extra"
    log = bench.wb.out_dir / "at-red.log"
    collection = TestReport({extra: TestCase(extra, "failed")}, collection_errors=["tests/test_discount.py"])
    for report, expected in ((collection, [known]), (None, [known, extra])):
        gate = GateResult("test-at-red", "fail", "exit 2", 2, log, report)
        bench.wb.run_gate = lambda *a, gate=gate, **k: gate  # type: ignore[method-assign]
        assert fails_at_red(bench.wb, red.sha, [known, extra]) == expected


def test_a_corrected_test_that_cannot_import_the_red_code_is_rejected(make_bench, raw):
    """A vacuous corrected test that imports a module only green added fails to collect against the red code: it does
    not discriminate, whatever it asserts."""
    vacuous = "import pytdd.added_by_green  # noqa: F401\n" + TESTS.replace(
        '    assert apply_discount(50.0, "SAVE10") == 45.0\n', "    assert True\n"
    )
    writes = {"tests/test_discount.py": vacuous, "src/pytdd/pricing.py": IMPL, "src/pytdd/added_by_green.py": "X = 1\n"}
    step = Step(writes=writes, structured=result("green"))
    bench = make_bench([two_test_red(), step])
    red = run_red(bench.wb, TASK, attempt=1)
    answer_naming(bench, raw, "Change `tests/test_discount.py` as you see fit.")
    before = bench.wb.head()
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "discriminates" in green.reason, green.reason
    assert "tests.test_discount::test_known_code" in green.reason
    assert bench.wb.head() == before and bench.events("task.done") == []


def test_green_failing_tests_carry_their_errors(make_bench):
    bench, red, green = red_green(make_bench, Step(structured=result("green")))
    assert green.status == "failed" and green.reason.startswith("red tests still failing")
    assert "NotImplementedError" not in green.reason
    assert "E       NotImplementedError" in green.excerpt and "src/pytdd/pricing.py:6" in green.excerpt


# --- W-D1: a test that hangs is named, not a 30 minute timeout -------------------------------------------

from l4.implementer.tdd import green_failures  # noqa: E402


def _gate(report, tmp_path, *, timed_out=False, exit_code=1, log=""):
    path = tmp_path / "test.log"
    path.write_text(log)
    return GateResult(
        "test", "fail", "timed out after 1800s" if timed_out else "exit code 1", exit_code, path, report, timed_out
    )


def test_a_soft_timeout_names_the_test_even_when_the_run_finished(tmp_path):
    report = TestReport(
        {
            "t::new": TestCase(
                "t::new",
                "failed",
                "Failed: l4-test-timeout: the test ran longer than 600s",
                (),
                "assertion",
                "a.recv(1)",
            ),
        }
    )
    reason, named = green_failures(TestReport(), ["t::new"], _gate(report, tmp_path))
    assert named == ["t::new"] and "hung" in reason and "t::new" in reason and "1800" not in reason


def test_a_hard_hang_with_no_report_is_named_from_the_log(tmp_path):
    log = "L4_TEST_HANG: tests/test_x.py::test_new\nThread 0x1:\n  File a.py, line 1\n"
    reason, named = green_failures(
        TestReport(), ["tests.test_x::test_new"], _gate(None, tmp_path, exit_code=70, log=log)
    )
    assert named == ["tests.test_x::test_new"] and "hung" in reason


def test_a_plain_whole_gate_timeout_is_unchanged(tmp_path):
    reason, named = green_failures(TestReport(), ["t::new"], _gate(None, tmp_path, timed_out=True))
    assert (reason, named) == ("timed out after 1800s", [])


def test_the_green_attempt_that_hangs_carries_the_hung_tests_and_their_frame(make_bench):
    hang_tests = (
        "import socket\n\nimport pytest\n\nfrom pytdd.pricing import apply_discount\n\n\n"
        f'@pytest.mark.l4("{KNOWN}", "{UNKNOWN}")\n'
        "def test_known_code():\n"
        '    assert apply_discount(50.0, "SAVE10") == 45.0\n'
        "    server_side, client = socket.socketpair()\n"
        "    client.recv(1)\n"
    )
    red = Step(
        writes={"tests/test_discount.py": hang_tests, "src/pytdd/pricing.py": STUB},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
        ),
    )
    bench = make_bench([red, green_step()], test_timeout="2s")
    red_out = run_red(bench.wb, TASK, attempt=1)
    assert red_out.status == "ok", red_out.reason
    green = run_green(bench.wb, TASK, red_out, attempt=1)
    assert green.status == "failed" and "hung" in green.reason and "test_known_code" in green.reason
    assert [h.id for h in green.hung] == ["tests.test_discount::test_known_code"]
    assert "client.recv(1)" in green.excerpt
    assert bench.events("gate.hung")[0]["tests"] == ["tests.test_discount::test_known_code"]
