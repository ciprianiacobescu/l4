"""`run_single`: the one-phase task of a fix unit that answers a finding no criterion names (M1.3 line 34, D8)."""

from l4.agents.fake import Step
from l4.implementer.tdd import run_single
from l4.specs.base import Task

from .conftest import IMPL, blocked_step, result

TASK = Task("1.1", "1.1", "1.1 an inline suppression was not declared (F-6eb0cc43)", False, " ", 0, 3, 3)
FINDINGS = ["F-6eb0cc43", "F-11111111"]
FIX = Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("single"))


def test_a_single_step_ticks_the_task_and_commits_it_as_exempt(make_bench):
    bench = make_bench([FIX])
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1)
    assert done.status == "ok", done.reason
    message = bench.wb.git.run("log", "-1", "--format=%B").stdout
    assert message.splitlines()[0].startswith("fix(add-discount-codes): 1.1 an inline suppression")
    assert "L4-TDD: exempt" in message and "L4-Step: 1.1/single/1" in message
    assert "- [x] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()
    [exempt] = bench.events("task.tdd_exempt")
    assert (exempt["kind"], exempt["finding"], exempt["findings"], exempt["sha"]) == (
        "harness", "F-6eb0cc43", FINDINGS, done.sha,
    )  # fmt: skip
    [event] = bench.events("task.done")
    assert event["tdd"] == "exempt" and event["sha"] == done.sha
    assert bench.events("task.red_ok") == [] and bench.pushes == [done.sha]


def test_the_prompt_is_the_single_template_with_no_red_rules_to_follow(make_bench):
    bench = make_bench([FIX])
    run_single(bench.wb, TASK, FINDINGS, attempt=1)
    [rendered] = bench.events("prompt.rendered")
    assert rendered["template_version"] == "contract@11+single@3" and rendered["role"] == "single"
    prompt = bench.adapter.requests[0].prompt
    assert "Phase: SINGLE" in prompt and "Phase: RED" not in prompt and 'phase "single"' in prompt


def test_a_step_that_breaks_an_existing_test_is_discarded(make_bench):
    breaker = Step(writes={"src/pytdd/pricing.py": "def total(prices):\n    return 0\n"}, structured=result("single"))
    bench = make_bench([breaker])
    before = bench.wb.head()
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1)
    assert done.status == "failed" and "broke existing tests" in done.reason
    assert bench.wb.head() == before and "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()
    assert bench.events("task.done") == [] and bench.events("task.tdd_exempt") == []


def test_a_blocked_single_step_returns_its_questions(make_bench):
    bench = make_bench([blocked_step()])
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1)
    assert done.status == "blocked" and [q.title for q in done.questions] == ["Which rounding?"]


# --- the chore reproduces, then requires, the failing CI step (M1.10 line 7; decision 4) ---

import sys  # noqa: E402

from l4.verifier.types import finding_id  # noqa: E402

CI_FINDING = finding_id("repository CI failed: test")
CHECK_LEN = (
    "import pathlib, sys\n"
    "bad = [(p, n) for p in sorted(pathlib.Path(sys.argv[1]).rglob('*.py'))\n"
    "       for n, line in enumerate(p.read_text().splitlines(), 1) if len(line) > 40]\n"
    "for p, n in bad:\n    print(f'E501 Line too long at {p}:{n}')\n"
    "sys.exit(1 if bad else 0)\n"
)
LONG = "# " + "x" * 60 + "\n"
PRICING = "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n"
CI_COMMAND = f"{sys.executable} scripts/check_len.py src"
CI_TAIL = (
    f"Executing step_script\n$ {CI_COMMAND}\nE501 Line too long at src/pytdd/pricing.py:3\n"
    "ERROR: Job failed: exit code 1"
)


def seed_main(tdd, raw, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = tdd.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    raw(tdd.repo, "add", "-A")
    raw(tdd.repo, "commit", "-q", "-m", "ci fixture")
    raw(tdd.repo, "push", "-q", "origin", "main")
    raw(tdd.repo, "fetch", "-q", "origin")


def seed_ci(bench, command: str = CI_COMMAND, tail: str = CI_TAIL) -> None:
    head = bench.wb.head()
    bench.writer.append(
        "phase.changed", **{"from": "in_review", "to": "verifying"}, trigger="repository_ci_failed", head=head,
        pipeline=5, preexisting=[], jobs=[{"name": "test", "stage": "test", "url": "", "tail": tail, "step": command}],
    )  # fmt: skip
    bench.writer.append(
        "ci.step", job="test", head=head, step=command, command=command, status="derived", reason=None,
        source=f".gitlab-ci.yml@{head[:10]}",
    )  # fmt: skip


def ci_gates(bench) -> list[str]:
    return [e["name"] for e in bench.events("gate.finished") if e["name"].startswith("repository-ci")]


def long_step() -> Step:
    return Step(writes={"src/pytdd/pricing.py": PRICING + LONG}, structured=result("single"))


def short_step() -> Step:
    return Step(writes={"src/pytdd/pricing.py": PRICING + "# short\n"}, structured=result("single"))


def test_a_reproduced_ci_step_must_pass_after_the_chore(make_bench, tdd_repo, raw):
    seed_main(tdd_repo, raw, {"scripts/check_len.py": CHECK_LEN, "src/pytdd/pricing.py": PRICING + LONG})
    bench = make_bench([long_step(), short_step()])
    seed_ci(bench)
    findings = [CI_FINDING]
    first = run_single(bench.wb, TASK, findings, attempt=1)
    assert first.status == "failed"
    assert "repository-ci:test still fails" in first.reason and "E501 Line too long" in first.reason  # the tool's error
    assert "[ ] 1.1" in (bench.wb.ref.path / "tasks.md").read_text() and bench.events("task.done") == []
    second = run_single(bench.wb, TASK, findings, attempt=2, previous_failure=first.reason)
    assert second.status == "ok", second.reason
    steps = bench.events("ci.step")
    assert [s["status"] for s in steps] == ["derived", "reproduced"]  # once, not once per attempt
    assert steps[1]["job"] == "test" and steps[1]["command"] == CI_COMMAND and steps[1]["head"] == steps[0]["head"]
    assert ci_gates(bench) == ["repository-ci:test"] * 3  # at the base, after attempt 1 (fail), after attempt 2 (pass)
    assert "E501 Line too long" in bench.adapter.requests[1].prompt  # the retry prompt shows the tool's error


def test_a_step_that_passes_at_the_base_is_skipped_and_the_chore_runs_as_today(make_bench, tdd_repo, raw):
    seed_main(tdd_repo, raw, {"scripts/check_len.py": CHECK_LEN})  # no long line at the base: the step passes
    bench = make_bench([long_step()])  # the chore adds a long line: today's checks do not look at it
    seed_ci(bench)
    done = run_single(bench.wb, TASK, [CI_FINDING], attempt=1)
    assert done.status == "ok", done.reason
    steps = bench.events("ci.step")
    assert [s["status"] for s in steps] == ["derived", "skipped"]
    assert "passes at the fix's base" in steps[1]["reason"] and "does not reproduce" in steps[1]["reason"]
    assert ci_gates(bench) == ["repository-ci:test"]  # only the reproduction at the base


def test_exit_127_is_skipped_with_its_reason(make_bench, tdd_repo, raw):
    seed_main(tdd_repo, raw, {"scripts/gone.py": "import sys\nsys.exit(127)\n"})
    command = f"{sys.executable} scripts/gone.py"
    bench = make_bench([short_step()])
    seed_ci(bench, command=command, tail=f"$ {command}\nboom")
    done = run_single(bench.wb, TASK, [CI_FINDING], attempt=1)
    assert done.status == "ok", done.reason
    skipped = bench.events("ci.step")[-1]
    assert skipped["status"] == "skipped" and "127" in skipped["reason"] and "not runnable" in skipped["reason"]
    assert skipped["command"] == command


def test_a_chore_without_a_ci_finding_runs_no_extra_gate(make_bench, tdd_repo, raw):
    seed_main(tdd_repo, raw, {"scripts/check_len.py": CHECK_LEN, "src/pytdd/pricing.py": PRICING + LONG})
    bench = make_bench([short_step()])
    seed_ci(bench)
    done = run_single(bench.wb, TASK, FINDINGS, attempt=1)  # findings that are not the job's
    assert done.status == "ok", done.reason
    assert ci_gates(bench) == [] and [s["status"] for s in bench.events("ci.step")] == ["derived"]


# --- a coverage hold's chore adds tests (M1.11 W5, decision 7) ----------------------------------------------------

from l4.implementer.tdd import run_green, run_red  # noqa: E402

from .conftest import TESTS, green_step, red_step  # noqa: E402

UNIT_TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
TESTS_TASK = Task("1.2", "1.2", "1.2 Changed code that no test runs (H-0a1b2c3d)", False, " ", 0, 3, 3)
HOLD = ["H-0a1b2c3d"]
NEW_TESTS = "from pytdd.pricing import total\n\n\ndef test_total_of_two():\n    assert total([1.0, 2.0]) == 3.0\n"
APPENDED = TESTS + "\n\ndef test_total_of_none():\n    from pytdd.pricing import total\n\n    assert total([]) == 0\n"


def run_tests_chore(make_bench, step: Step, **kw):
    """The unit's red and green are done (its test file is frozen), then the chore step runs as `kind="tests"`."""
    bench = make_bench([red_step(), green_step(), step])
    tasks = bench.wb.ref.path / "tasks.md"
    tasks.write_text(tasks.read_text().rstrip("\n") + "\n- [ ] 1.2 Changed code that no test runs (H-0a1b2c3d)\n")
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "a second task")
    red = run_red(bench.wb, UNIT_TASK, attempt=1)
    assert red.status == "ok", red.reason
    assert run_green(bench.wb, UNIT_TASK, red, attempt=1).status == "ok"
    return bench, run_single(
        bench.wb, TESTS_TASK, HOLD, attempt=1, kind=kw.get("kind", "tests"), retake=kw.get("retake", False)
    )


def test_a_test_chore_keeps_a_new_test_file(make_bench):
    bench, done = run_tests_chore(
        make_bench, Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single"))
    )
    assert done.status == "ok", done.reason
    [added] = bench.events("task.tests_added")
    assert added["task"] == "1.2" and added["files"] == ["tests/test_more.py"]
    assert added["tests"] == ["tests.test_more::test_total_of_two"]
    assert "L4-TDD: exempt" in bench.wb.git.run("log", "-1", "--format=%B").stdout
    assert "tests/test_more.py" in bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout
    [_, _, rendered] = bench.events("prompt.rendered")
    assert rendered["template_version"] == "contract@11+single_tests@5"
    assert "Do not add tests" not in bench.adapter.requests[2].prompt


def test_tests_appended_to_the_units_test_file_are_kept(make_bench):
    bench, done = run_tests_chore(
        make_bench, Step(writes={"tests/test_discount.py": APPENDED}, structured=result("single"))
    )
    assert done.status == "ok", done.reason
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == APPENDED
    [added] = bench.events("task.tests_added")
    assert added["files"] == ["tests/test_discount.py"]
    assert added["tests"] == ["tests.test_discount::test_total_of_none"]


def test_an_edited_existing_test_is_put_back_with_a_note(make_bench):
    old = "def test_total_adds_prices():\n    assert False\n"
    cheat = TESTS.replace("== 45.0", "== 50.0")
    step = Step(
        writes={"tests/test_pricing.py": old, "tests/test_discount.py": cheat, "tests/test_more.py": NEW_TESTS},
        structured=result("single"),
    )
    bench, done = run_tests_chore(make_bench, step)
    assert done.status == "ok", done.reason  # the originals are back, so the gate passes, and the new test counts
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == TESTS
    assert "assert False" not in (bench.wb.worktree / "tests" / "test_pricing.py").read_text()
    touched = {e["path"] for e in bench.events("guard.test_tamper")}
    assert touched == {"tests/test_pricing.py", "tests/test_discount.py"}


def test_a_test_chore_that_adds_no_test_fails(make_bench):
    bench, done = run_tests_chore(make_bench, Step(structured=result("single")))
    assert done.status == "failed" and done.reason == "no tests added"
    assert bench.events("task.tests_added") == []
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"]  # only the unit's own task is done


def test_a_retaken_tests_item_with_no_test_to_add_completes_as_already_done(make_bench):
    """review #8 follow-up: the tests are there already, the judge only left the item out of its reply."""
    bench, done = run_tests_chore(make_bench, Step(structured=result("single")), retake=True)
    assert done.status == "ok", done.reason
    done_events = [e for e in bench.events("task.done") if e["task"] == "1.2"]
    assert [e["tdd"] for e in done_events] == ["already-done"]
    assert bench.events("task.tests_added") == [] and bench.events("task.tdd_exempt") == []
    assert "- [x] 1.2" in (bench.wb.ref.path / "tasks.md").read_text()


def test_a_retaken_tests_item_that_adds_a_test_keeps_it(make_bench):
    bench, done = run_tests_chore(
        make_bench, Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single")), retake=True
    )
    assert done.status == "ok" and [e["files"] for e in bench.events("task.tests_added")] == [["tests/test_more.py"]]
    assert [e["tdd"] for e in bench.events("task.done") if e["task"] == "1.2"] == ["exempt"]


def test_a_production_change_in_a_test_chore_fails(make_bench):
    step = Step(
        writes={"src/pytdd/pricing.py": IMPL + "\n# touched\n", "tests/test_more.py": NEW_TESTS},
        structured=result("single"),
    )
    bench, done = run_tests_chore(make_bench, step)
    assert done.status == "failed" and "non-test" in done.reason and "src/pytdd/pricing.py" in done.reason
    assert bench.wb.is_clean() and not (bench.wb.worktree / "tests" / "test_more.py").exists()  # discarded
    assert bench.events("task.tests_added") == []


def test_an_appended_test_that_shadows_an_existing_one_is_put_back(make_bench):
    shadow = TESTS + "\n\ndef test_known_code():\n    pass\n"  # same name: the proof test would be shadowed, id intact
    bench, done = run_tests_chore(
        make_bench, Step(writes={"tests/test_discount.py": shadow}, structured=result("single"))
    )
    assert done.status == "failed" and done.reason == "no tests added"
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == TESTS
    assert [e["path"] for e in bench.events("guard.test_tamper")] == ["tests/test_discount.py"]


def test_an_appended_autouse_fixture_that_neuters_the_proof_tests_is_put_back(make_bench):
    """m1.11(fix): the fixture's name is new and every existing statement survives, yet it reaches every test of the
    file: with it, the proof tests pass whatever `apply_discount` does."""
    neuter = (
        TESTS + "\n\n@pytest.fixture(autouse=True)\ndef _answer(monkeypatch):\n"
        "    def fake(amount, code):\n        if code != 'SAVE10':\n            raise ValueError(code)\n"
        "        return 45.0\n\n    monkeypatch.setitem(globals(), 'apply_discount', fake)\n"
        "\n\ndef test_total_of_none():\n    from pytdd.pricing import total\n\n    assert total([]) == 0\n"
    )
    bench, done = run_tests_chore(
        make_bench, Step(writes={"tests/test_discount.py": neuter}, structured=result("single"))
    )
    assert done.status == "failed" and done.reason == "no tests added"
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == TESTS
    [tamper] = bench.events("guard.test_tamper")
    assert tamper["path"] == "tests/test_discount.py"
    assert "a fixture" in tamper["reason"] and "new test file" in tamper["reason"]  # the next attempt's guard note


def test_a_new_conftest_in_a_test_chore_is_put_back(make_bench):
    conftest = "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef everywhere():\n    yield\n"
    step = Step(writes={"tests/conftest.py": conftest, "tests/test_more.py": NEW_TESTS}, structured=result("single"))
    bench, done = run_tests_chore(make_bench, step)
    assert done.status == "ok", done.reason
    assert not (bench.wb.worktree / "tests" / "conftest.py").exists()
    assert [e["path"] for e in bench.events("guard.violation")] == ["tests/conftest.py"]
    [added] = bench.events("task.tests_added")
    assert added["files"] == ["tests/test_more.py"]


def test_a_fix_chore_is_unchanged(make_bench):
    cheat = TESTS.replace("== 45.0", "== 50.0")
    step = Step(writes={"tests/test_discount.py": cheat, "src/pytdd/pricing.py": IMPL}, structured=result("single"))
    bench, done = run_tests_chore(make_bench, step, kind="fix")
    assert done.status == "ok", done.reason
    assert (bench.wb.worktree / "tests" / "test_discount.py").read_text() == TESTS  # put back, as before
    assert bench.events("task.tests_added") == []
    assert bench.events("prompt.rendered")[-1]["template_version"] == "contract@11+single@3"
