from pathlib import Path

import pytest

from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.gates.junit import TestCase, TestReport
from l4.implementer.tdd import BaselineFailed, RoleLimit, classify_red, run_green, run_red
from l4.specs.base import Task

from .conftest import KNOWN, RUN_ID, STUB, UNKNOWN, Bench, blocked_step, red_step, result

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "copilot-cli" / "1.0.102-byok"
TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)


def report(**status: str) -> TestReport:
    return TestReport({i: TestCase(i, s) for i, s in status.items()})  # type: ignore[arg-type]


BASE = report(old="passed", old2="failed")


def test_passing_new_test_and_no_tests_and_collection_error_fail_red():
    no_tests = classify_red(BASE, BASE, test_files_changed=False)
    assert (no_tests.ok, no_tests.reason) == (False, "no tests added")
    passing = classify_red(BASE, report(old="passed", old2="failed", new="passed"), test_files_changed=True)
    assert (passing.ok, passing.reason) == (False, "new tests passed before implementation: new")
    broken = TestReport({"old": TestCase("old", "passed")}, collection_errors=["tests.test_new"])
    collection = classify_red(BASE, broken, test_files_changed=True)
    assert (collection.ok, collection.reason) == (False, "tests not collected individually: tests.test_new")


def test_test_files_without_a_new_test_id_say_no_new_test_not_that_collection_failed():
    """Kiro e2e H2 (task 2.2 on a leaf whose behaviour already existed): the agent only added `@pytest.mark.l4` to
    existing tests. Every test was collected (33 of 33, no collection error), so "not collected individually" was
    false and sent the next attempt to do the same again."""
    for verdict in (
        classify_red(BASE, BASE, test_files_changed=True),
        classify_red(BASE, BASE, test_files_changed=False, tests_added=["t::x"]),
    ):
        assert verdict.reason.startswith("no new test: no test with a new name was added")
        assert "not collected" not in verdict.reason
        assert "re-tagging" in verdict.reason and "new test function" in verdict.reason
    broken = TestReport({"old": TestCase("old", "passed"), "old2": TestCase("old2", "failed")}, collection_errors=["m"])
    assert classify_red(BASE, broken, test_files_changed=True).reason == "tests not collected individually: m"


def test_red_broke_existing_tests_and_a_valid_red():
    after = report(old="failed", old2="failed", new="failed")
    assert classify_red(BASE, after, test_files_changed=True).reason == "red broke existing tests: old"
    gone = report(old2="failed", new="error")
    assert classify_red(BASE, gone, test_files_changed=True).reason == "red broke existing tests: old"
    fine = report(old="passed", old2="failed", new="failed", other="error")
    assert classify_red(BASE, fine, test_files_changed=True).ok
    skipped = report(old="passed", old2="failed", new="skipped")
    assert not classify_red(BASE, skipped, test_files_changed=True).ok  # a skipped test proves nothing


def test_valid_red_commits_with_trailer_and_ledger_event(make_bench):
    bench: Bench = make_bench([red_step()])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    message = bench.wb.git.run("log", "-1", "--format=%B").stdout
    assert message.splitlines()[0] == "test(add-discount-codes): red for 1.1 [skip ci]"
    for trailer in (
        "L4-Unit: openspec:add-discount-codes", f"L4-Run: {RUN_ID}", "L4-Iteration: 1", "L4-Task: 1.1",
        "L4-TDD: red", "L4-Agent: impl", "L4-Step: 1.1/red/1",
    ):  # fmt: skip
        assert trailer in message
    committed = bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout.split()
    assert "tests/test_discount.py" in committed and "src/pytdd/pricing.py" in committed
    assert not any(p.startswith((".venv", ".l4-out")) for p in committed)  # the harness's own ignore file
    assert any(p.endswith(f"{RUN_ID}.jsonl") for p in committed)  # the branch carries the ledger
    [event] = bench.events("task.red_ok")
    assert event["task"] == "1.1" and len(event["tests"]) == 2
    assert event["base"] == bench.wb.git.rev_parse(f"{outcome.sha}~1")  # recorded inside the red commit itself
    in_commit = bench.wb.git.run("show", f"{outcome.sha}:{bench.wb.ledger_rel}").stdout
    assert '"type": "task.red_ok"' in in_commit
    assert outcome.new_ids == {"tests.test_discount::test_known_code", "tests.test_discount::test_unknown_code"}
    assert bench.pushes == [outcome.sha]
    assert [e["selected"] for e in bench.events("availability.selected")] == ["impl"]


def test_the_prompt_the_agent_receives_is_the_rendered_red_prompt(make_bench):
    bench = make_bench([red_step()])
    run_red(bench.wb, TASK, attempt=1)
    [req] = bench.adapter.requests
    assert "# Phase: RED" in req.prompt and "same WHEN but different THEN" in req.prompt
    assert req.result_schema is not None and req.result_schema["$id"] == "l4/implementer-result@1"
    assert req.permission_policy.mode == "implement"
    assert req.env["L4_RESULT_PATH"] == str(req.result_path)
    assert "L4_FORGE_TOKEN" not in req.env
    [rendered] = bench.events("prompt.rendered")
    assert rendered["role"] == "red" and len(rendered["sha256"]) == 64


def test_new_tests_that_already_pass_are_rejected_and_the_worktree_is_clean(make_bench):
    passing = (  # one criterion, a test that passes and a test that fails: the passing one proves nothing
        f'import pytest\nfrom pytdd import total\n\n\n@pytest.mark.l4("{KNOWN}")\ndef test_it():\n'
        f'    assert total([1]) == 1\n\n\n@pytest.mark.l4("{KNOWN}")\ndef test_other():\n    assert False\n'
    )
    bench = make_bench([Step(writes={"tests/test_new.py": passing}, structured=result("red"))])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "passed before implementation" in outcome.reason
    assert bench.wb.changed_files() == [bench.wb.ledger_rel]  # only this run's ledger is left over
    assert not (bench.wb.worktree / "tests" / "test_new.py").exists()
    assert bench.events("run.started")  # the ledger survived the discard
    assert bench.wb.git.run("log", "--oneline", "main..HEAD").stdout == ""


def test_a_red_without_tests_fails(make_bench):
    bench = make_bench([Step(structured=result("red"))])
    assert run_red(bench.wb, TASK, attempt=1).reason == "no tests added"


def test_uncollectable_tests_fail_red(make_bench):
    bench = make_bench([Step(writes={"tests/test_bad.py": "def test_x(:\n"}, structured=result("red"))])
    assert run_red(bench.wb, TASK, attempt=1).reason.startswith("tests not collected individually: tests.test_bad")


def test_red_that_breaks_an_existing_test_fails(make_bench):
    wreck = Step(
        writes={
            "tests/test_discount.py": f'import pytest\n\n\n@pytest.mark.l4("{KNOWN}")\ndef test_new():\n'
            "    assert False\n",
            "tests/test_pricing.py": "def test_total_adds_prices():\n    assert False\n",
        },
        structured=result("red"),
    )
    outcome = run_red(make_bench([wreck]).wb, TASK, attempt=1)
    assert outcome.reason.startswith("red broke existing tests: tests.test_pricing::test_total_adds_prices")


def test_protected_paths_are_reverted_and_recorded_but_do_not_fail_red(make_bench):
    step = red_step()
    step.writes = {
        **step.writes,
        ".gitlab-ci.yml": "evil: true\n",
        "openspec/changes/add-discount-codes/tasks.md": "x\n",
    }
    bench = make_bench([step])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok"
    assert not (bench.wb.worktree / ".gitlab-ci.yml").exists()
    assert (bench.wb.worktree / "openspec/changes/add-discount-codes/tasks.md").read_text().startswith("## 1.")
    assert sorted(e["path"] for e in bench.events("guard.violation")) == [
        ".gitlab-ci.yml", "openspec/changes/add-discount-codes/tasks.md",
    ]  # fmt: skip


def test_an_agent_that_ends_in_error_or_returns_garbage_fails_the_attempt(make_bench):
    bench = make_bench([Step(status="timeout"), Step(structured={"status": "great"}), Step()])
    assert "reached its time limit" in run_red(bench.wb, TASK, attempt=1).reason
    assert run_red(bench.wb, TASK, attempt=2).reason == "no tests added"  # normalized, then judged on the work
    assert "result is invalid: no result was delivered" in run_red(bench.wb, TASK, attempt=3).reason


def test_blocked_returns_its_questions_and_leaves_a_clean_tree(make_bench):
    bench = make_bench([Step(writes={"tests/test_x.py": "x = 1\n"}, structured=blocked_step().structured)])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "blocked" and outcome.questions[0].title == "Which rounding?"
    assert not (bench.wb.worktree / "tests" / "test_x.py").exists()


def test_a_usage_limit_is_a_role_limit_not_a_failed_attempt(make_bench):
    limit = LimitSignal("codex", None, "usage_limit", None, "text", "usage limit")
    bench = make_bench([Step(status="quota", limit=limit)])
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)


def test_credits_are_recorded_with_their_source_and_are_not_dollars(make_bench):
    bench = make_bench([red_step(credits=2.5, credits_source="kiro.stream")])
    assert run_red(bench.wb, TASK, attempt=1).status == "ok"
    (cost,) = bench.events("budget.cost")
    assert cost["credits"] == 2.5 and cost["credits_source"] == "kiro.stream" and "usd" not in cost
    from l4.state.fold import fold
    from l4.state.ledger import read_ledger

    assert fold(read_ledger(bench.wb.ref.path).events, bench.wb.ref.id).cost_usd == 0.0


def test_a_throttled_step_is_a_role_limit_that_consumes_no_attempt(make_bench):
    """Kiro e2e H2: a FREE-tier throttle (`rate_limited`, a `rate_limit` signal) falls through like a 429."""
    limit = LimitSignal("kiro-cli", None, "rate_limit", None, "kiro.run_error", "throttled by the service")
    bench = make_bench([Step(status="rate_limited", limit=limit)])
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    assert bench.events("task.attempt_failed") == []


def test_a_copilot_429_is_a_role_limit_that_consumes_no_attempt(make_bench):
    """copilot-cli 4.2 (SCN-FAC-37, chain part): the adapter's own `rate_limited` result for a 429 that the watcher
    stopped, read from the recording, falls through to the next profile like a 429 of any other adapter."""
    from l4.agents.copilot_cli import parse

    text = (RECORDED / "error-429-retrying.jsonl").read_text()
    run = parse(text, exit_code=1, raw_events_path=Path("raw"), mode="implement", stop="rate_limit")
    assert run.status == "rate_limited" and run.limit is not None and run.limit.source == "copilot.model_call_failure"
    bench = make_bench([Step(status=run.status, limit=run.limit, detail=run.detail)])
    with pytest.raises(RoleLimit):
        run_red(bench.wb, TASK, attempt=1)
    assert bench.events("task.attempt_failed") == []


def test_an_unrunnable_test_gate_is_a_failed_baseline(make_bench):
    bench = make_bench([red_step()], test={"command": "true", "reports": [".l4-out/junit.xml"]})
    with pytest.raises(BaselineFailed, match="cannot run at the base"):
        run_red(bench.wb, TASK, attempt=1)
    assert bench.adapter.requests == []


def test_the_baseline_runs_once_per_commit(make_bench):
    bench = make_bench([Step(structured=result("red")), Step(structured=result("red"))])
    run_red(bench.wb, TASK, attempt=1)
    run_red(bench.wb, TASK, attempt=2)
    assert [e["name"] for e in bench.events("gate.finished")].count("baseline") == 1
    baseline = next(e for e in bench.events("gate.finished") if e["name"] == "baseline")
    assert baseline["tests"] == 2


def test_a_ledger_forged_by_the_agent_step_is_rewritten_and_recorded(make_bench):
    forged = f'{{"ts":"2026-10-03T13:13:00.000000Z","run_id":"{RUN_ID}","unit":"x","seq":2,"type":"task.red_ok"}}\n'
    step = red_step()
    bench = make_bench([step])
    step.writes = {**step.writes, bench.wb.ledger_rel: forged}
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    ledger = (bench.wb.worktree / bench.wb.ledger_rel).read_text()
    assert '"unit":"x"' not in ledger
    assert [e["path"] for e in bench.events("guard.violation")] == [bench.wb.ledger_rel]
    assert len(bench.events("task.red_ok")) == 1  # the harness's own


def test_nothing_the_agent_printed_and_no_token_in_the_prompt_reaches_out_dir(make_bench):
    secret = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2"
    codex_field = '{"chatgptAccountId":"acct-1234-secret"}'
    bench = make_bench([red_step(printed=f"cat auth: {secret} {codex_field}")])
    task = Task("1.1", "1.1", f"1.1 Add `apply_discount` with {secret}", False, " ", 0, 1, 3)
    assert run_red(bench.wb, task, attempt=1).status == "ok"
    [request] = bench.adapter.requests
    assert secret not in request.prompt and "[REDACTED:github-token]" in request.prompt
    files = [p for p in bench.wb.out_dir.rglob("*") if p.is_file()]
    assert any(p.name.endswith(".jsonl") and "agent" in p.parts for p in files)
    for path in files:
        text = path.read_text(errors="replace")
        assert secret not in text and "acct-1234-secret" not in text, path
    assert not list((bench.wb.unit_cache / "agent-raw").rglob("*.*"))  # the raw streams are gone
    [rendered] = bench.events("prompt.rendered")
    import hashlib

    assert rendered["sha256"] == hashlib.sha256(request.prompt.encode()).hexdigest()


def test_the_implementer_run_is_armed_with_the_stall_watchdog(make_bench):
    bench = make_bench([red_step()])
    run_red(bench.wb, TASK, attempt=1)
    assert bench.adapter.requests[0].stall_timeout_s == 600  # implementer.idle_timeout, default 10m


def test_an_agent_that_crashes_leaves_nothing_protected_or_forged_behind(make_bench):
    import pytest

    bench = make_bench([red_step()])
    wb = bench.wb
    ledger = wb.worktree / wb.ledger_rel

    def crash(req):
        (wb.worktree / ".claude").mkdir(exist_ok=True)
        (wb.worktree / ".claude" / "settings.json").write_text("planted\n")
        ledger.write_text('{"type":"phase.changed","to":"verified"}\n')
        raise RuntimeError("adapter blew up")

    bench.adapter.run = crash  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="blew up"):
        run_red(wb, TASK, attempt=1)
    assert not (wb.worktree / ".claude").exists()
    assert "verified" not in ledger.read_text()
    assert [e["path"] for e in bench.events("guard.violation")] == [".claude/settings.json", wb.ledger_rel]


def _answer(bench: Bench, status: str, text: str, tasks: str) -> None:
    from l4.redact import Redactor
    from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, raise_questions

    unit_dir = bench.wb.ref.path
    new = NewQuestion("Which rate?", QuestionKind.PRODUCT, tuple(tasks.split(",")), "ctx", "asked")
    raise_questions(unit_dir, "x", [new], redactor=Redactor({}))
    file = QuestionsFile.load(unit_dir / "questions.md")
    assert file is not None
    q = file.get("Q-001")
    assert q is not None and q.answer is not None
    data = file.data[: q.answer.body.end] + text.encode() + b"\n" + file.data[q.answer.body.end :]
    QuestionsFile.parse(data).set_status("Q-001", QuestionStatus(status)).save(unit_dir / "questions.md")


def test_an_answered_question_reaches_the_red_prompt_as_a_data_block(make_bench):
    bench = make_bench([red_step()])
    _answer(bench, "answered", "The rate is 21%.", "1.1")
    run_red(bench.wb, TASK, attempt=1)
    [req] = bench.adapter.requests
    block = '<l4:data kind="answer" id="Q-001" by="human">\nThe rate is 21%.\n</l4:data>'
    assert f"# Answered questions\n{block}" in req.prompt
    assert req.prompt.index("# Criteria of this unit") < req.prompt.index("# Answered questions")
    assert req.prompt.index("# Answered questions") < req.prompt.index("# Phase: RED")
    [rendered] = bench.events("prompt.rendered")
    import hashlib

    assert rendered["sha256"] == hashlib.sha256(req.prompt.encode()).hexdigest()  # the hash covers the answer
    assert rendered["template_version"].startswith("contract@13+")
    assert rendered["answers"] == [{"id": "Q-001", "answer_sha256": hashlib.sha256(b"The rate is 21%.").hexdigest()}]


def test_the_prompt_as_sent_is_published_next_to_the_agent_events(make_bench):
    import hashlib

    bench = make_bench([red_step()])
    _answer(bench, "answered", "The rate is 21%.", "1.1")
    run_red(bench.wb, TASK, attempt=1)
    [req] = bench.adapter.requests
    [path] = sorted((bench.wb.out_dir / "agent").rglob("*.prompt.md"))
    text = path.read_text(encoding="utf-8")
    assert text == req.prompt and '<l4:data kind="answer" id="Q-001" by="human">' in text
    assert hashlib.sha256(text.encode()).hexdigest() == bench.events("prompt.rendered")[0]["sha256"]


@pytest.mark.parametrize(("status", "tasks"), [("open", "1.1"), ("answered", "9.9")])
def test_a_draft_or_an_unrelated_answer_is_not_in_the_prompt(make_bench, status, tasks):
    bench = make_bench([red_step()])
    _answer(bench, status, "not for this task", tasks)
    run_red(bench.wb, TASK, attempt=1)
    assert "Answered questions" not in bench.adapter.requests[0].prompt
    assert bench.events("prompt.rendered")[0]["answers"] == []


def _commit_pricing_on_main(tdd_repo, raw, extra: str) -> None:
    pricing = tdd_repo.repo / "src/pytdd/pricing.py"
    pricing.write_text(pricing.read_text() + extra)
    raw(tdd_repo.repo, "commit", "-qam", "scaffold")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")


def _only_known_test(body: str) -> Step:
    from .conftest import HEADER

    text = HEADER + f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n    {body}\n'
    return Step(writes={"tests/test_discount.py": text}, structured=result("red", criteria_ids=[KNOWN]))


HEAD_STUB = "\n\ndef apply_discount(amount, code):\n    raise NotImplementedError\n"


def test_a_call_only_test_against_a_stub_that_head_already_holds_is_vacuous(make_bench, tdd_repo, raw):
    _commit_pricing_on_main(tdd_repo, raw, HEAD_STUB)
    bench: Bench = make_bench([_only_known_test('apply_discount(50.0, "SAVE10")')])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason.startswith("vacuous: " + KNOWN)


def test_a_test_that_asserts_on_the_answer_of_a_head_stub_is_proved_by_the_zero_value_run(make_bench, tdd_repo, raw):
    _commit_pricing_on_main(tdd_repo, raw, HEAD_STUB)
    bench: Bench = make_bench([_only_known_test('assert apply_discount(50.0, "SAVE10") == 45.0')])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    proof = outcome.criteria[KNOWN]
    assert proof["proof"] == "zero_value" and proof["discriminating"] == ["tests.test_discount::test_known_code"]


def test_without_any_stub_a_failure_that_is_not_an_assertion_is_vacuous(make_bench, tdd_repo, raw):
    # not a stub site (the body does more than raise and does not END in the raise: that would be a partial stub, which
    # the zero-value run covers), so no zero-value run is possible: run (a) must show an assertion
    body = (
        "\n\ndef apply_discount(amount, code):\n    amount = float(amount)\n"
        '    raise NotImplementedError("later")\n    return amount\n'
    )
    _commit_pricing_on_main(tdd_repo, raw, body)
    bench: Bench = make_bench([_only_known_test('apply_discount(50.0, "SAVE10")')])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "none of its tests fails by assertion" in outcome.reason


def test_without_any_stub_a_failing_assertion_is_a_red_assertion_proof(make_bench, tdd_repo, raw):
    body = "\n\ndef apply_discount(amount, code):\n    return amount\n"
    _commit_pricing_on_main(tdd_repo, raw, body)
    bench: Bench = make_bench([_only_known_test('assert apply_discount(50.0, "SAVE10") == 45.0')])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    assert outcome.criteria[KNOWN]["proof"] == "red_assertion"
    assert outcome.criteria[KNOWN]["discriminating"] == ["tests.test_discount::test_known_code"]


def _mutating_test(counter, fire_on: int) -> str:
    """A test module whose import-time code rewrites production files on the `fire_on`-th gate run."""
    return (
        "from pathlib import Path\n\n"
        f"counter = Path({str(counter)!r})\n"
        "n = int(counter.read_text() or '0') + 1 if counter.exists() else 1\n"
        "counter.write_text(str(n))\n"
        f"if n == {fire_on}:\n"
        "    root = Path(__file__).resolve().parents[1]\n"
        "    pricing = root / 'src/pytdd/pricing.py'\n"
        "    pricing.write_text(pricing.read_text() + '\\n# planted by a gate run\\n')\n"
        "    (root / 'src/pytdd/planted.py').write_text('X = 1\\n')\n"
    )


@pytest.mark.parametrize("fire_on", [1, 2])
def test_test_code_that_rewrites_production_in_a_red_gate_run_fails_the_attempt(make_bench, tmp_path, fire_on):
    red = red_step()
    red.writes = {**red.writes, "tests/test_zz_side.py": _mutating_test(tmp_path / "count", fire_on)}
    bench: Bench = make_bench([red])
    before = bench.wb.head()
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "production" in outcome.reason
    assert bench.wb.head() == before, "nothing was committed"
    assert bench.pushes == []
    rules = [e["rule"] for e in bench.events("guard.violation")]
    assert "gate-mutated-production" in rules
    assert not (bench.wb.worktree / "src/pytdd/planted.py").exists()
    assert "planted" not in (bench.wb.worktree / "src/pytdd/pricing.py").read_text()


_PATCHED_INIT = (  # what the planted bytecode runs instead of `src/pytdd/__init__.py`: the real implementation
    "from pytdd.pricing import total\n"
    "import pytdd.pricing as _p\n"
    "def _apply(amount, code):\n"
    "    if code != 'SAVE10':\n        raise ValueError(code)\n"
    "    return round(amount * 0.9, 2)\n"
    "_p.apply_discount = _apply\n"
)


def _bytecode_plant(counter) -> str:
    """A test module that, as the second (last) red gate run exits, writes an unchecked hash-based `.pyc` for the
    package `__init__`: Python never compares such a file with its source, so every later gate in the worktree would
    run the planted code. It is not a production path (`__pycache__` is ignored), so no guard sees it."""
    return (
        "import atexit, importlib.util, py_compile, tempfile\nfrom pathlib import Path\n\n"
        f"counter = Path({str(counter)!r})\n"
        "n = int(counter.read_text()) + 1 if counter.exists() else 1\n"
        "counter.write_text(str(n))\n"
        f"PATCHED = {_PATCHED_INIT!r}\n\n\n"
        "def plant():\n"
        "    src = Path(__file__).resolve().parents[1] / 'src/pytdd/__init__.py'\n"
        "    tmp = Path(tempfile.mkdtemp()) / '__init__.py'\n"
        "    tmp.write_text(PATCHED)\n"
        "    mode = py_compile.PycInvalidationMode.UNCHECKED_HASH\n"
        "    cfile = importlib.util.cache_from_source(str(src))\n"
        "    py_compile.compile(str(tmp), cfile=cfile, invalidation_mode=mode)\n\n\n"
        "if n == 2:\n"
        "    atexit.register(plant)\n"
    )


def test_bytecode_that_a_red_gate_plants_never_reaches_a_later_gate(make_bench, tmp_path):
    red = red_step()
    red.writes = {**red.writes, "tests/test_zz_side.py": _bytecode_plant(tmp_path / "count")}
    lazy = Step(writes={"src/pytdd/pricing.py": STUB + "\n# green\n"}, structured=result("green"))  # still a stub
    bench: Bench = make_bench([red, lazy])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    assert (tmp_path / "count").read_text() == "2", "the plant fires on the last red gate run"
    green = run_green(bench.wb, TASK, outcome, attempt=1)
    assert green.status == "failed" and green.reason.startswith("red tests still failing"), green
    assert bench.wb.head() == outcome.sha, "the stub is not committed as green"


def test_a_configured_e2e_gate_puts_its_directory_in_the_red_prompt(make_bench):
    """Live M1.5 P3: Codex put the browser test under tests/ (the unit gate ran it without a server) and lost a red
    attempt. The prompt names the directory the e2e gate runs."""
    bench = make_bench(
        [red_step()],
        e2e={
            "command": ".venv/bin/python -m pytest e2e -q",
            "reports": [".l4-out/e2e.xml"],
            "serve": {"command": "python -m http.server 8765", "ready_url": "http://127.0.0.1:8765/"},
        },
    )
    run_red(bench.wb, TASK, attempt=1)
    [req] = bench.adapter.requests
    assert "`e2e/`" in req.prompt and "L4_E2E_BASE_URL" in req.prompt


def test_without_an_e2e_gate_the_red_prompt_names_no_directory(make_bench):
    bench = make_bench([red_step()])
    run_red(bench.wb, TASK, attempt=1)
    assert "`e2e/`" not in bench.adapter.requests[0].prompt


VITEST_GATE = "npx vitest run --reporter=default --reporter=junit --outputFile.junit=.l4-out/junit.xml"


def _red_with(rules=None, **messages: str):
    head = TestReport({"old": TestCase("old", "passed"), "old2": TestCase("old2", "failed")})
    for test_id, message in messages.items():
        head.tests[test_id] = TestCase(test_id, "failed", message, failure_kind="other")
    kwargs = {} if rules is None else {"rules": rules}
    return classify_red(BASE, head, test_files_changed=True, failure_kinds=True, **kwargs)


def test_import_error_red_advises_catching_it_and_pytest_fail():
    verdict = _red_with(blocked="ModuleNotFoundError: import of xattr halted; None in sys.modules")
    assert not verdict.ok
    assert "neither an assertion nor NotImplementedError" in verdict.reason
    assert "catch `ImportError`" in verdict.reason and "pytest.fail" in verdict.reason
    assert "guarded stub" not in verdict.reason  # the TypeError advice would misdirect the agent (job 5561)


def test_type_error_red_keeps_the_guarded_stub_advice():
    verdict = _red_with(typed="TypeError: f() got an unexpected keyword argument 'x'")
    assert "guarded stub" in verdict.reason and "pytest.fail" not in verdict.reason


def test_the_red_advice_for_a_vitest_gate_names_expect_and_no_pytest():
    """SCN-IMP-79: the retry advice follows the test gate, as the trace wording does."""
    from l4.implementer.result import trace_rules

    rules = trace_rules(VITEST_GATE)
    other = _red_with(rules, a="ReferenceError: render is not defined").reason
    assert "expect(...)" in other and "Vitest or Jest" in other and 'throw new Error("not implemented")' in other
    assert "NotImplementedException()" in other and "pytest" not in other.split("neither", 1)[1]
    typed = _red_with(rules, a="TypeError: f is not a function").reason
    assert "optional trailing parameter" in typed and "throws a not-implemented error" in typed
    assert "pytest" not in typed.split("neither", 1)[1] and "raise NotImplementedError" not in typed
    imported = _red_with(rules, a="ImportError: nope").reason
    assert "catch `ImportError`" not in imported and "expect(...)" in imported


def test_the_red_advice_for_a_pytest_gate_is_unchanged():
    from l4.implementer.result import trace_rules

    for rules in (None, trace_rules("uv run pytest")):
        other = _red_with(rules, a="ValueError: x").reason
        assert other.endswith(
            "Make the test fail by assertion: catch the error and call `pytest.fail(...)`, or stub the missing "
            "symbol with `raise NotImplementedError`"
        )
        typed = _red_with(rules, a="TypeError: x").reason
        assert typed.endswith(
            "A parameter that does not exist yet needs a guarded stub (a new trailing parameter with a default and "
            "`if <condition>: raise NotImplementedError` as the first statement), not a TypeError"
        )


def test_mixed_kinds_give_each_advice_once():
    verdict = _red_with(
        a="TypeError: f() got an unexpected keyword argument 'x'",
        b="ImportError: nope",
        c="SystemExit: 1",
        d="TypeError: again",
    )
    assert verdict.reason.count("guarded stub") == 1
    assert verdict.reason.count("catch `ImportError`") == 1


def test_unknown_kind_advises_making_the_test_fail_by_assertion():
    verdict = _red_with(odd="KeyError: 'x'")
    assert "pytest.fail" in verdict.reason and "NotImplementedError" in verdict.reason
    assert "guarded stub" not in verdict.reason


def test_a_red_that_breaks_an_existing_test_tells_the_next_attempt_why(make_bench):
    wreck = Step(
        writes={
            "tests/test_discount.py": f'import pytest\n\n\n@pytest.mark.l4("{KNOWN}")\ndef test_new():\n'
            "    assert False\n",
            "tests/test_pricing.py": "def test_total_adds_prices():\n    open('data/missing.csv')\n",
        },
        structured=result("red"),
    )
    outcome = run_red(make_bench([wreck]).wb, TASK, attempt=1)
    assert outcome.reason.startswith("red broke existing tests: tests.test_pricing::test_total_adds_prices")
    assert "FileNotFoundError" not in outcome.reason  # the headline stays one line
    assert "FileNotFoundError" in outcome.excerpt
    assert "tests/test_pricing.py:2" in outcome.excerpt and "open('data/missing.csv')" in outcome.excerpt


def test_an_existing_test_changed_in_place_is_named_with_its_failure_not_called_uncollected():
    """Live M1.11 (dummy-agentic job 5810): red edited an existing test in place and added no test id; the retry said
    only `tests not collected individually`, with no excerpt, and the agent did the same again."""
    edited = report(old="failed", old2="failed")
    verdict = classify_red(BASE, edited, test_files_changed=True, excerpt=lambda _r, ids: f"EXCERPT {list(ids)}")
    assert verdict.reason.startswith("no new test: existing tests were changed and now fail: old")
    assert "not collected" not in verdict.reason
    assert verdict.excerpt == "EXCERPT ['old']"


def test_a_red_that_only_edits_an_existing_test_tells_the_next_attempt_why(make_bench):
    edit = Step(
        writes={"tests/test_pricing.py": "def test_total_adds_prices():\n    assert 1 + 1 == 3\n"},
        structured=result("red"),
    )
    outcome = run_red(make_bench([edit]).wb, TASK, attempt=1)
    assert outcome.reason.startswith(
        "no new test: existing tests were changed and now fail: tests.test_pricing::test_total_adds_prices"
    )
    assert "tests/test_pricing.py:2" in outcome.excerpt and "assert 1 + 1 == 3" in outcome.excerpt


def test_a_new_test_that_hangs_in_red_is_not_a_valid_red():
    """W-D1: the soft timeout reads as `Failed:` (an assertion), but a test that only hangs proves nothing."""
    hung = TestCase("new", "failed", "Failed: l4-test-timeout: the test ran longer than 600s", (), "assertion")
    head = TestReport({"old": TestCase("old", "passed"), "old2": TestCase("old2", "failed"), "new": hung})
    verdict = classify_red(BASE, head, test_files_changed=True, failure_kinds=True)
    assert verdict.ok is False and verdict.reason.startswith("new tests hang instead of failing: new")


def test_the_red_retry_message_for_a_vitest_gate_names_the_id_in_the_name_form(make_bench, monkeypatch):
    """SCN-IMP-69: tdd.py hands the gate's hint to check_criteria; no pytest marker reaches a non-pytest gate."""
    from l4.implementer import result as result_module
    from l4.implementer import tdd

    vitest = "npx vitest run --reporter=default --reporter=junit --outputFile.junit=.l4-out/junit.xml"
    monkeypatch.setattr(tdd, "trace_rules", lambda command: result_module.trace_rules(vitest))
    untagged = red_step().writes["tests/test_discount.py"].replace(f'@pytest.mark.l4("{KNOWN}")\n', "")
    untagged = untagged.replace(f'@pytest.mark.l4("{UNKNOWN}")\n', "")
    step = red_step()
    step.writes["tests/test_discount.py"] = untagged
    bench: Bench = make_bench([step])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed"
    assert f"no new test traces {KNOWN}" in outcome.reason and 'it("C-xxxxxxxx: …")' in outcome.reason
    assert "@pytest.mark.l4" not in outcome.reason


def test_the_red_retry_message_for_a_pytest_gate_names_the_marker(make_bench):
    step = red_step()
    marked = step.writes["tests/test_discount.py"]
    step.writes["tests/test_discount.py"] = marked.replace(f'@pytest.mark.l4("{KNOWN}")\n', "")
    bench: Bench = make_bench([step])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "tag each test that checks a criterion with @pytest.mark.l4" in outcome.reason
    assert "any other runner" not in outcome.reason


def test_scn_ver_151_a_test_chore_whose_check_cannot_decide_is_held(make_bench, monkeypatch):
    """L4-VER-009, L4-IMP-063 (review m2): tests the chore added, none of which the discrimination runs could run, are
    not rejected and not accepted either: the chore is held with a harness question."""
    from l4.implementer import tdd
    from l4.implementer.discrimination import ExtraRun

    bench = make_bench([])
    ids = ["tests.test_a::test_one", "tests.test_a::test_two"]
    reason = "did not run in test-extra-zero"
    monkeypatch.setattr(
        tdd, "discriminate_extra", lambda wb, tests, base, **kw: ExtraRun(inconclusive=dict.fromkeys(ids, reason))
    )
    task = Task("1.2", "1.2", "1.2 New tests (F-0a1b2c3d; C-2d3a8daf)", False, " ", 0, 3, 3)
    tests, why, held = tdd._discriminating_tests(bench.wb, ids, task)
    assert (tests, why) == ([], "")
    assert held is not None and (held.check, held.phase, held.tests, held.reason) == (
        "tests",
        "green",
        tuple(ids),
        reason,
    )


# --- named-test-any-language 1.1: a named test of another language, changed in place (L4-IMP-089, D2) ---

TS_BASE = report(old="passed", **{"src/a.test.ts::the registry holds 16": "passed"})
TS_NAMED = ["src/a.test.ts::the registry holds 16"]


def named_red(head: TestReport, **kw: object):
    return classify_red(TS_BASE, head, test_files_changed=True, named_other=TS_NAMED, **kw)  # type: ignore[arg-type]


def test_scn_imp_439_a_named_test_that_fails_at_red_is_no_regression():
    head = report(old="passed", new="failed", **{"src/a.test.ts::the registry holds 16": "failed"})
    assert named_red(head).ok
    without = classify_red(TS_BASE, head, test_files_changed=True)
    assert without.reason == "red broke existing tests: src/a.test.ts::the registry holds 16"  # as before


def test_scn_imp_440_a_changed_named_test_that_passes_at_red_fails_the_attempt_naming_it():
    head = report(old="passed", new="failed", **{"src/a.test.ts::the registry holds 16": "passed"})
    verdict = named_red(head)
    assert not verdict.ok
    assert (
        verdict.reason
        == "a test the task names was changed but does not fail at red: src/a.test.ts::the registry holds 16"
    )
    assert not named_red(report(old="passed", new="failed", **{TS_NAMED[0]: "skipped"})).ok
    only = report(old="passed", **{TS_NAMED[0]: "passed"})  # the change is its only one: still named first
    assert named_red(only).reason.startswith("a test the task names was changed but does not fail at red")


def test_scn_imp_441_a_named_test_that_is_gone_from_the_report_is_a_regression():
    head = report(old="passed", new="failed")
    assert named_red(head).reason == "red broke existing tests: src/a.test.ts::the registry holds 16"


def test_a_named_test_of_another_language_is_no_new_test_and_other_regressions_stay():
    head = report(old="passed", **{TS_NAMED[0]: "failed"})
    assert named_red(head).reason.startswith("no new test: no test with a new name was added")
    broken = report(old="failed", new="failed", **{TS_NAMED[0]: "failed"})
    assert named_red(broken).reason == "red broke existing tests: old"
