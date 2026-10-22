"""detect-test-tamper 2.1 (L4-IMP-048, L4-IMP-006): a red step may not change a test that existed before it. Ports the
implementer-4 reproduction, which asserted the bug (red `ok`, the tampered file committed, no event)."""

from l4.agents.fake import Step
from l4.implementer.tdd import run_red
from l4.specs.base import Task

from .conftest import HEADER, KNOWN, STUB, TESTS, UNKNOWN, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
BASE_TEST = "tests/test_pricing.py"
WEAKENED = (
    "from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert True\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)
REBOUND_SUFFIX = "\n\ndef test_total_adds_prices():\n    pass\n"
MORE = (
    f'@pytest.mark.l4("{UNKNOWN}")\ndef test_more():\n    with pytest.raises(ValueError):\n'
    '        apply_discount(10.0, "NOPE")\n'
)
ADVICE = "A red step adds new tests with new names."


def tampering_red(text: str) -> Step:
    return Step(
        writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB, BASE_TEST: text},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
        ),
    )


def committed(bench, path=BASE_TEST):
    return bench.wb.git.run("show", f"HEAD:{path}").stdout


def tamper_events(bench):
    return [e for e in bench.events("guard.test_tamper") if e.get("rule") == "pre-existing test"]


def test_a_weakened_pre_existing_test_fails_the_red_attempt(make_bench):  # SCN-IMP-276
    bench = make_bench([])
    original = (bench.wb.worktree / BASE_TEST).read_text()
    bench.adapter._script.append(tampering_red(WEAKENED))
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed"
    assert committed(bench) == original  # nothing of the attempt reached the branch
    assert bench.wb.git.run("log", "--oneline", "main..HEAD").stdout == ""
    [event] = tamper_events(bench)
    assert event["phase"] == "red" and event["path"] == BASE_TEST and event["action"] == "rejected"
    assert event["tests"] == ["test_total_adds_prices"]
    assert out.reason.startswith(
        "red changed tests that existed before this step: tests/test_pricing.py::test_total_adds_prices ("
    )
    assert "\n" not in out.reason
    assert ADVICE in out.excerpt and "test_total_adds_prices" in out.excerpt
    assert (bench.wb.worktree / BASE_TEST).read_text() == original


def test_a_rebinding_fails_the_red_attempt(make_bench):  # SCN-IMP-277
    bench = make_bench([])
    original = (bench.wb.worktree / BASE_TEST).read_text()
    bench.adapter._script.append(tampering_red(original + REBOUND_SUFFIX))
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and "its name is bound again" in out.reason
    assert committed(bench) == original
    assert [e["tests"] for e in tamper_events(bench)] == [["test_total_adds_prices"]]


def test_an_honest_red_appends_and_goes_on(make_bench):
    bench = make_bench([])
    original = (bench.wb.worktree / BASE_TEST).read_text()
    extra = original + (
        "\n\ndef test_discount_of_ten():\n    from pytdd.pricing import apply_discount\n\n"
        '    assert apply_discount(10.0, "SAVE10") == 9.0\n'
    )
    bench.adapter._script.append(tampering_red(extra))
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert tamper_events(bench) == []
    assert committed(bench) == extra


def test_a_red_that_breaks_an_existing_test_keeps_its_reason(make_bench):  # SCN-IMP-275
    wreck = tampering_red("from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert False\n")
    out = run_red(make_bench([wreck]).wb, TASK, attempt=1)
    assert out.reason.startswith("red broke existing tests: tests.test_pricing::test_total_adds_prices")
    assert "assert False" in out.excerpt or "AssertionError" in out.excerpt or out.excerpt


def test_a_red_that_breaks_an_existing_test_records_no_pre_existing_event(make_bench):  # SCN-IMP-275
    bench = make_bench(
        [tampering_red("from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert False\n")]
    )
    run_red(bench.wb, TASK, attempt=1)
    assert tamper_events(bench) == []


def test_a_test_infra_task_may_change_existing_tests(make_bench):  # SCN-IMP-272
    infra = Task("2.1", "2.1", "2.1 [test-infra] Share the cart fixture", False, " ", 0, 3, 3)
    bench = make_bench([])
    approx = (bench.wb.worktree / BASE_TEST).read_text().replace("== 3.75", "== 3.75 or True")
    bench.adapter._script.append(tampering_red(approx))
    out = run_red(bench.wb, infra, attempt=1)
    assert out.status == "ok" and tamper_events(bench) == []
    assert committed(bench) == approx


def test_a_later_tasks_red_may_not_change_an_earlier_tasks_red_test(make_bench):  # SCN-IMP-273
    bench = make_bench([])
    bench.adapter._script.append(
        Step(
            writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB},
            structured=result("red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN]),
        )
    )
    first = run_red(bench.wb, TASK, attempt=1)
    assert first.status == "ok", first.reason
    weaker = TESTS.replace('apply_discount(50.0, "SAVE10") == 45.0', "True")
    later = Task("1.2", "1.2", "1.2 More discounts", False, " ", 0, 3, 3)
    bench.adapter._script.append(
        Step(
            writes={
                "tests/test_discount.py": weaker,
                "tests/test_more.py": HEADER + MORE,
            },
            structured=result(
                "red", task_ids=["1.2"], tests_added=["tests/test_more.py::test_more"], criteria_ids=[UNKNOWN]
            ),
        )
    )
    out = run_red(bench.wb, later, attempt=1)
    assert out.status == "failed" and "tests/test_discount.py::test_known_code" in out.reason
    [event] = tamper_events(bench)
    assert event["path"] == "tests/test_discount.py"


def test_a_code_swap_in_the_test_file_fails_the_red_attempt(make_bench):  # SCN-IMP-278 at red level (review B1)
    bench = make_bench([])
    original = (bench.wb.worktree / BASE_TEST).read_text()
    swap = original + "\n\ntest_total_adds_prices.__code__ = (lambda: None).__code__\n"
    bench.adapter._script.append(tampering_red(swap))
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and committed(bench) == original
    assert "test_total_adds_prices" in out.reason and "<module>" in out.reason
    [event] = tamper_events(bench)
    assert event["path"] == BASE_TEST and event["action"] == "rejected"
    assert sorted(event["tests"]) == ["test_total_adds_prices", "test_total_of_nothing_is_zero"]


# --- named-tests 1.2: the reviewed text names the test (L4-IMP-082) ---

NAMING_TEXT = "- [ ] 1.1 Add `apply_discount`; update `tests/test_pricing.py::test_total_adds_prices` in place\n"
BARE_TEXT = "- [ ] 1.1 Add `apply_discount`; test_total_adds_prices and test_total_of_nothing_is_zero are rewritten\n"
REWRITTEN = (
    "from pytdd import total\n\n\ndef test_total_adds_prices():\n"
    "    assert total([1.25, 2.5]) == 3.75  # in place\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)
REWRITTEN_BOTH = (
    "from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert total([1]) == 1\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0.0\n"
)
FAILING = "from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert total([1.25, 2.5]) == 99\n\n\n" + (
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)
ONLY_FIRST_DELETED = "from pytdd import total\n\n\ndef test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"


def reviewed(bench, text: str = NAMING_TEXT) -> Task:
    from l4.yolo.digest import unit_digest

    tasks = bench.wb.ref.path / "tasks.md"
    tasks.write_text(tasks.read_text().split("- [ ]")[0] + text)
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("-c", "user.name=t", "-c", "user.email=t@x.invalid", "commit", "-q", "-m", "task text")
    bench.wb.activated_plan = "p1"
    bench.wb.activated_digest = unit_digest(bench.wb.git, "HEAD", bench.wb.unit_rel)
    return bench.wb.provider.tasks(bench.wb.ref)[0]


def superseded_events(bench):
    return bench.events("tests.superseded")


def test_a_named_test_is_changed_in_place_and_recorded(make_bench):  # SCN-IMP-400
    bench = make_bench([])
    task = reviewed(bench)
    bench.adapter._script.append(tampering_red(REWRITTEN.replace("# in place", "+ 0")))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    assert tamper_events(bench) == []
    [event] = superseded_events(bench)
    assert event["tests"] == ["tests.test_pricing::test_total_adds_prices"] and event["criteria"] == []
    assert event["reason"] == "named_by_task" and event["source"] == f"plan:p1@{bench.wb.activated_digest}"
    assert out.superseded == frozenset()


def test_a_named_test_may_fail_after_red_like_a_red_test(make_bench):  # SCN-IMP-400
    bench = make_bench([])
    task = reviewed(bench)
    bench.adapter._script.append(tampering_red(FAILING))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    assert [e["tests"] for e in superseded_events(bench)] == [["tests.test_pricing::test_total_adds_prices"]]


def test_bare_names_in_the_text_name_both_tests(make_bench):  # SCN-IMP-401
    bench = make_bench([])
    task = reviewed(bench, BARE_TEXT)
    bench.adapter._script.append(tampering_red(REWRITTEN_BOTH))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    [event] = superseded_events(bench)
    assert event["tests"] == [
        "tests.test_pricing::test_total_adds_prices",
        "tests.test_pricing::test_total_of_nothing_is_zero",
    ]


def test_a_named_test_may_not_be_deleted(make_bench):  # SCN-IMP-402
    bench = make_bench([])
    task = reviewed(bench)
    bench.adapter._script.append(tampering_red(ONLY_FIRST_DELETED))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed"
    assert out.reason.startswith("red changed tests that existed before this step: ")
    assert "tests/test_pricing.py::test_total_adds_prices" in out.reason
    assert superseded_events(bench) == []


def test_an_unnamed_test_stays_protected(make_bench):  # SCN-IMP-402
    bench = make_bench([])
    task = reviewed(bench)
    bench.adapter._script.append(tampering_red(REWRITTEN_BOTH))  # also changes test_total_of_nothing_is_zero
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed"
    assert "tests/test_pricing.py::test_total_of_nothing_is_zero" in out.reason
    assert "test_total_adds_prices" not in out.reason
    assert superseded_events(bench) == []
    assert ADVICE in out.excerpt and "may be changed in place" in out.excerpt


def test_the_advice_says_a_named_test_may_change():
    from l4.implementer import tdd

    assert "may be changed in place" in tdd._PREEXISTING_ADVICE
