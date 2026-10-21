"""A tag or a person's answer opens configuration for one task, and it is recorded (L4-IMP-041; design D8)."""

from l4.agents.fake import Step
from l4.implementer.tdd import run_green, run_red, run_single
from l4.implementer.unfreeze import RUNNER_FROZEN, config_opened
from l4.redact import Redactor
from l4.specs.base import Task
from l4.specs.questions import QuestionStatus

from .conftest import IMPL, STUB, TESTS, red_step, result
from .test_gate_config_guard import commit_base, committed, pyproject, violations
from .test_tdd_green import answer_naming
from .test_unfreeze import SCOPE, ask, recorded, sub, with_status

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
CANDIDATES = {"pyproject.toml": frozenset({"gate", "runner"}), "pytest.ini": frozenset({"runner"})}
CONTEXT = "The async tests need `asyncio_mode = auto` in pyproject.toml and nothing else."
ACCEPT = "Edit `pyproject.toml`: add asyncio_mode = auto to [tool.pytest.ini_options]."
PYTEST_INI = "[pytest]\npythonpath = src\n"


# --- the rules of L4-IMP-015, at function level ---


def test_an_accepted_suggestion_that_the_question_names_opens_the_file(tmp_path):
    file = with_status(ask(tmp_path, context=CONTEXT), QuestionStatus.ACCEPTED, suggestion=ACCEPT)
    got = config_opened(file.questions, recorded(file), SCOPE, CANDIDATES, phase="red")
    assert got.paths == ("pyproject.toml",) and got.question == "Q-001" and got.kept == ()
    assert got.answer_sha256 is not None and len(got.answer_sha256) == 64


def test_an_answer_the_question_does_not_name_is_kept(tmp_path):
    file = with_status(ask(tmp_path), QuestionStatus.ACCEPTED, suggestion=ACCEPT)  # the context names no config file
    got = config_opened(file.questions, recorded(file), SCOPE, CANDIDATES, phase="red")
    assert got.paths == () and [p for p, _ in got.kept] == ["pyproject.toml"]


def test_scn_imp_252_a_clarifier_another_task_and_an_edited_answer_open_nothing(tmp_path):
    def opened(file, events=None, **over):
        return config_opened(
            file.questions, events if events is not None else recorded(file), SCOPE, CANDIDATES, **over
        )

    clarifier = with_status(ask(tmp_path, context=CONTEXT), QuestionStatus.ANSWERED_BY_CLARIFIER, suggestion=ACCEPT)
    assert opened(clarifier, phase="red").paths == ()
    elsewhere = ask(sub(tmp_path, "o"), tasks=("2.1",), context=CONTEXT)  # it blocks task 2.1 only
    other = with_status(elsewhere, QuestionStatus.ACCEPTED, suggestion=ACCEPT)
    assert opened(other, phase="red").paths == ()
    edited = with_status(ask(sub(tmp_path, "e"), context=CONTEXT), QuestionStatus.ACCEPTED, suggestion=ACCEPT)
    events = recorded(edited)
    changed = edited.set_suggestion("Q-001", ACCEPT + " Also pytest.ini.", redactor=Redactor({}))
    assert opened(changed, events, phase="red").paths == ()  # the digest no longer matches
    assert opened(edited, [], phase="red").paths == ()  # never recorded at a re-entry


def test_scn_imp_253_an_answer_cannot_open_runner_configuration_for_green(tmp_path):
    context = "tests/ need the `pytest.ini` setting and `pyproject.toml` too."
    file = with_status(
        ask(tmp_path, context=context), QuestionStatus.ACCEPTED, suggestion="Edit `pytest.ini` and `pyproject.toml`."
    )
    green = config_opened(file.questions, recorded(file), SCOPE, CANDIDATES, phase="green")
    assert green.paths == ("pyproject.toml",)  # a manifest opens: its gate sections only (D8)
    assert green.kept == (("pytest.ini", RUNNER_FROZEN),)
    red = config_opened(file.questions, recorded(file), SCOPE, CANDIDATES, phase="red")
    assert red.paths == ("pyproject.toml", "pytest.ini") and red.kept == ()


# --- through the steps ---


def test_scn_imp_250_a_config_tagged_task_keeps_its_ruff_toml_change_in_green(make_bench):
    task = Task("1.1", "1.1", "1.1 [config] Raise the line length to 120", False, " ", 0, 3, 3)
    bench = make_bench([red_step()])
    commit_base(bench, {"ruff.toml": "line-length = 100\n"})
    bench.adapter._script.append(
        Step(writes={"src/pytdd/pricing.py": IMPL, "ruff.toml": "line-length = 120\n"}, structured=result("green"))
    )
    red = run_red(bench.wb, task, attempt=1)
    out = run_green(bench.wb, task, red, attempt=1)
    assert out.status == "ok", out.reason
    assert committed(bench, out.sha, "ruff.toml") == "line-length = 120\n"
    assert not violations(bench, "gate configuration") and bench.events("task.config_opened") == []


def test_scn_imp_251_a_persons_answer_that_names_pyproject_opens_it_for_red(make_bench, raw):
    bench = make_bench([])
    original = pyproject(bench)
    edited = original.replace('pythonpath = ["src"]', 'pythonpath = ["src"]\nasyncio_mode = "auto"')
    answer_naming(bench, raw, "Yes, add it to `pyproject.toml`.", context=CONTEXT)
    bench.adapter._script.append(
        Step(
            writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB, "pyproject.toml": edited},
            structured=result("red", tests_added=["tests/test_discount.py::test_known_code"]),
        )
    )
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert committed(bench, out.sha, "pyproject.toml") == edited  # the change stays
    [event] = bench.events("task.config_opened")
    assert event["task"] == "1.1" and event["phase"] == "red" and event["paths"] == ["pyproject.toml"]
    assert event["question"] == "Q-001" and len(event["answer_sha256"]) == 64 and event["kept"] == []
    ledger = [
        e["type"]
        for e in __import__("json").loads(
            "["
            + ",".join((bench.wb.ref.path / ".l4" / "ledger" / "r-20261003T1312Z-7f3a.jsonl").read_text().splitlines())
            + "]"
        )
    ]
    assert ledger.index("task.config_opened") < ledger.index("agent.finished")  # recorded before the agent step
    assert not violations(bench, "runner configuration")


CHORE = "1.1 an inline suppression was not declared (F-6eb0cc43)"


def test_a_test_infra_tag_opens_runner_configuration_in_red(make_bench):
    task = Task("1.1", "1.1", "1.1 [test-infra] Run the tests from pytest.ini", False, " ", 0, 3, 3)
    bench = make_bench([])
    bench.adapter._script.append(
        Step(
            writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB, "pytest.ini": PYTEST_INI},
            structured=result("red", tests_added=["tests/test_discount.py::test_known_code"]),
        )
    )
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    assert committed(bench, out.sha, "pytest.ini") == PYTEST_INI
    assert not violations(bench, "runner configuration")


def test_a_test_infra_tag_opens_runner_configuration_in_a_fix_chore(make_bench):
    chore = Task("1.1", "1.1", f"{CHORE} [test-infra]", False, " ", 0, 3, 3)
    bench = make_bench([Step(writes={"pytest.ini": PYTEST_INI}, structured=result("single"))])
    done = run_single(bench.wb, chore, ["F-6eb0cc43"], attempt=1)
    assert done.status == "ok", done.reason
    assert committed(bench, done.sha, "pytest.ini") == PYTEST_INI


def test_a_fix_chore_without_the_tag_has_the_runner_file_put_back(make_bench):
    plain = Task("1.1", "1.1", CHORE, False, " ", 0, 3, 3)
    bench = make_bench([Step(writes={"pytest.ini": PYTEST_INI}, structured=result("single"))])
    run_single(bench.wb, plain, ["F-6eb0cc43"], attempt=1)
    assert not (bench.wb.worktree / "pytest.ini").exists()  # new, so removed
    assert [e["rule"] for e in (x.get("data", x) for x in bench.events("guard.violation"))] == ["runner configuration"]


def test_an_answer_cannot_open_runner_configuration_in_green_and_kept_says_why(make_bench, raw):
    bench = make_bench([red_step()])
    commit_base(bench, {"pytest.ini": PYTEST_INI})
    answer_naming(bench, raw, "Edit `pytest.ini`.", context="`pytest.ini` needs a setting.")
    bench.adapter._script.append(
        Step(
            writes={"src/pytdd/pricing.py": IMPL, "pytest.ini": PYTEST_INI + "addopts = -q\n"},
            structured=result("green"),
        )
    )
    red = run_red(bench.wb, TASK, attempt=1)
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "ok", out.reason
    [event] = [e for e in bench.events("task.config_opened") if e["phase"] == "green"]
    assert event["paths"] == [] and event["kept"] == [{"path": "pytest.ini", "why": RUNNER_FROZEN}]
    assert (bench.wb.worktree / "pytest.ini").read_text() == PYTEST_INI  # put back
    assert [e["phase"] for e in violations(bench, "runner configuration")] == ["green"]


def test_an_agents_answer_opens_configuration_like_a_persons(tmp_path):  # review F5: kept as on 0.4.18
    file = with_status(ask(tmp_path, context=CONTEXT), QuestionStatus.ACCEPTED, suggestion=ACCEPT)
    for by in ("human", "agent"):
        got = config_opened(file.questions, recorded(file, by=by), SCOPE, CANDIDATES, phase="red")
        assert got.paths == ("pyproject.toml",), by
    for by in ("delegate", "clarifier"):
        assert config_opened(file.questions, recorded(file, by=by), SCOPE, CANDIDATES, phase="red").paths == ()
