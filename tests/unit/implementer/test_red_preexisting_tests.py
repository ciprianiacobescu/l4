"""detect-test-tamper 2.1 (L4-IMP-048, L4-IMP-006): a red step may not change a test that existed before it. Ports the
implementer-4 reproduction, which asserted the bug (red `ok`, the tampered file committed, no event)."""

import json
import sys

import pytest

from l4.agents.fake import Step
from l4.implementer.tdd import run_red
from l4.specs.base import Task

from ..conftest import TEST_COMMAND
from .conftest import HEADER, KNOWN, RUN_ID, STUB, TESTS, UNKNOWN, result

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


def test_the_prompt_of_a_red_step_lists_the_named_tests(make_bench):  # SCN-IMP-400
    bench = make_bench([])
    task = reviewed(bench)
    bench.adapter._script.append(tampering_red(REWRITTEN))
    run_red(bench.wb, task, attempt=1)
    prompts = sorted(bench.wb.out_dir.rglob("*.prompt.md"))
    assert prompts
    text = prompts[-1].read_text()
    assert "# Existing tests this task changes in place" in text
    assert "- tests/test_pricing.py::test_total_adds_prices" in text


def test_the_prompt_of_an_unreviewed_task_has_no_such_section(make_bench):  # SCN-IMP-403
    bench = make_bench([])
    bench.adapter._script.append(tampering_red(REWRITTEN))
    run_red(bench.wb, TASK, attempt=1)
    texts = [p.read_text() for p in bench.wb.out_dir.rglob("*.prompt.md")]
    assert texts and all("# Existing tests this task changes in place" not in t for t in texts)


# --- named-test-any-language 1.1: a named test of another language (L4-IMP-089) ---

CODES = "src/api/error-codes.test.ts"
REGISTRY = "C-96e47324 The registry holds exactly the 16 codes of the API with status and message"
SIXTEEN = (
    'import { expect, it } from "vitest";\n\n'
    f'it("{REGISTRY}", () => {{\n  expect(CODES.length).toBe(16);\n}});\n\n'
    'it("every code has a status", () => {\n  expect(CODES.length).toBe(16);\n});\n'
)
TS_TEXT = f"- [ ] 1.1 Add `apply_discount`; change `{CODES}::{REGISTRY}` to count 22 codes\n"
# a test gate that runs pytest and reports the `it(...)` blocks of the TypeScript files as a JUnit runner would:
# a block passes while it expects 16 codes, which is what the code under test holds
FAKE_RUNNER = """
import re, subprocess, sys
from pathlib import Path

subprocess.run(sys.argv[1], shell=True)
report = Path(".l4-out/junit.xml")
cases = []
for path in Path("src").rglob("*.test.ts"):
    for block in re.finditer(r'^it\\("(.*?)",.*?^\\}\\);', path.read_text(), re.S | re.M):
        body = block.group(0).split("\\n", 1)[1]
        name = block.group(1).replace("&", "&amp;")
        fail = "" if "toBe(16)" in body else '<failure message="expected 16" type="AssertionError">x</failure>'
        cases.append(f'<testcase classname="{path.as_posix()}" name="{name}">{fail}</testcase>')
report.write_text(report.read_text().replace("</testsuite>", "".join(cases) + "</testsuite>", 1))
"""


def ts_bench(make_bench, tmp_path, *, text: str = TS_TEXT, source: str = SIXTEEN, runner_source: str = FAKE_RUNNER):
    runner = tmp_path / "fake_runner.py"
    runner.write_text(runner_source)
    command = f"{sys.executable} {runner} '{TEST_COMMAND}'"
    bench = make_bench([], test={"command": command})
    (bench.wb.worktree / CODES).parent.mkdir(parents=True, exist_ok=True)
    (bench.wb.worktree / CODES).write_text(source)
    return bench, reviewed(bench, text)


def ts_red(source: str) -> Step:
    return Step(
        writes={CODES: source, "tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
        ),
    )


def count(codes: int) -> str:
    return SIXTEEN.replace(
        'expect(CODES.length).toBe(16);\n});\n\nit("every',
        f'expect(CODES.length).toBe({codes});\n}});\n\nit("every',
        1,
    )


def test_scn_imp_439_a_named_typescript_test_is_changed_at_red_and_fails(make_bench, tmp_path):
    bench, task = ts_bench(make_bench, tmp_path)
    bench.adapter._script.append(ts_red(count(22)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    [event] = superseded_events(bench)
    assert event["tests"] == [f"{CODES}::{REGISTRY}"] and event["criteria"] == []
    assert event["reason"] == "named_by_task" and event["language"] == "typescript"
    assert event["source"] == f"plan:p1@{bench.wb.activated_digest}"
    assert committed(bench, CODES) == count(22) and tamper_events(bench) == []


def test_the_prompt_of_a_red_step_lists_a_named_typescript_test(make_bench, tmp_path):
    bench, task = ts_bench(make_bench, tmp_path)
    bench.adapter._script.append(ts_red(count(22)))
    run_red(bench.wb, task, attempt=1)
    text = sorted(bench.wb.out_dir.rglob("*.prompt.md"))[-1].read_text()
    assert "# Existing tests this task changes in place" in text and f"- {CODES}::{REGISTRY}" in text


def test_scn_imp_440_a_changed_named_test_that_passes_at_red_fails_the_attempt(make_bench, tmp_path):
    bench, task = ts_bench(make_bench, tmp_path)
    bench.adapter._script.append(ts_red(SIXTEEN.replace("toBe(16);\n}", "toBe(16); // six more\n}", 1)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed"
    assert out.reason == f"a test the task names was changed but does not fail at red: {CODES}::{REGISTRY}"
    assert superseded_events(bench) == [] and committed(bench, CODES) == SIXTEEN


def test_an_unchanged_named_test_is_no_change_and_an_unnamed_one_stays_protected(make_bench, tmp_path):
    bench, task = ts_bench(make_bench, tmp_path)
    other = SIXTEEN.replace(
        'status", () => {\n  expect(CODES.length).toBe(16)', 'status", () => {\n  expect(CODES.length).toBe(22)'
    )
    bench.adapter._script.append(ts_red(other))  # the second test fails at red but nothing names it
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed" and out.reason == "red broke existing tests: " + f"{CODES}::every code has a status"
    assert superseded_events(bench) == []


def test_scn_imp_441_a_named_test_red_deleted_or_renamed_fails_the_attempt(make_bench, tmp_path):
    deleted = SIXTEEN.split('\nit("every')[0].split("\n\n", 1)[0] + '\n\nit("every' + SIXTEEN.split('\nit("every', 1)[1]
    renamed = count(22).replace("The registry holds exactly", "The registry holds all")  # a new test that fails
    for source in (deleted, renamed):
        bench, task = ts_bench(make_bench, tmp_path)
        bench.adapter._script.append(ts_red(source))
        out = run_red(bench.wb, task, attempt=1)
        assert out.status == "failed" and out.reason == f"red broke existing tests: {CODES}::{REGISTRY}"
        assert superseded_events(bench) == []


@pytest.mark.parametrize("name", ["The registry", "no such test"])
def test_scn_imp_442_a_name_without_a_test_excuses_nothing_and_the_kept_reason_says_which(make_bench, tmp_path, name):
    text = f"- [ ] 1.1 Add `apply_discount`; change `{CODES}::{name}`\n"
    bench, task = ts_bench(make_bench, tmp_path, text=text)
    bench.adapter._script.append(ts_red(count(22)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed" and out.reason == f"red broke existing tests: {CODES}::{REGISTRY}"
    assert superseded_events(bench) == []
    [kept] = bench.events("named_tests.kept")
    assert kept["task"] == "1.1" and kept["token"] == f"{CODES}::{name}"
    assert kept["reason"] == "no test of that name in the base report"
    prompt = sorted(bench.wb.out_dir.rglob("*.prompt.md"))[-1].read_text()
    assert f"{CODES}::{name}: no test of that name in the base report" in prompt


def test_scn_imp_443_a_task_that_names_only_the_file_does_not_excuse_its_tests(make_bench, tmp_path):
    bench, task = ts_bench(make_bench, tmp_path, text=f"- [ ] 1.1 Add `apply_discount`; update `{CODES}`\n")
    bench.adapter._script.append(ts_red(count(22)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed" and out.reason == f"red broke existing tests: {CODES}::{REGISTRY}"


EXISTING = (
    'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("' + KNOWN + '")\n'
    "def test_total_adds():\n    assert total([1.0, 2.0]) == 3.0\n"
)


def committed_trailer(bench) -> str:
    return bench.wb.git.run("log", "-1", "--format=%B").stdout


def test_a_changed_named_python_test_that_fails_is_not_committed_as_already_satisfied(make_bench):
    bench = make_bench([])
    task = reviewed(bench)
    bench.adapter._script.append(
        Step(
            writes={"tests/test_existing.py": EXISTING, BASE_TEST: FAILING},
            structured=result("red", criteria_ids=[KNOWN]),
        )
    )
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason  # a red whose green follows, not "already_satisfied"
    assert "L4-TDD: red" in committed_trailer(bench) and "already-satisfied" not in committed_trailer(bench)
    assert [e["tests"] for e in superseded_events(bench)] == [["tests.test_pricing::test_total_adds_prices"]]


def test_a_changed_named_typescript_test_that_fails_is_not_committed_as_already_satisfied(make_bench, tmp_path):
    bench, task = ts_bench(make_bench, tmp_path)
    bench.adapter._script.append(
        Step(
            writes={"tests/test_existing.py": EXISTING, CODES: count(22)},
            structured=result("red", criteria_ids=[KNOWN]),
        )
    )
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    assert "L4-TDD: red" in committed_trailer(bench) and "already-satisfied" not in committed_trailer(bench)
    assert [e["language"] for e in superseded_events(bench)] == ["typescript"]


# --- named-test-shared-lines 1.1: a named test changed through its file's shared lines (L4-IMP-089, D1 to D4) ---

# A runner for `test(...)` blocks at any indent, named like a JUnit reporter does (the describe names, ` > `, the
# test's). A block that compares with `EXPECTED_CODES` fails unless that constant holds the 16 codes of the code under
# test; a block that calls `apply_discount(` fails once the stub of red replaced the production code.
SHARED_RUNNER = """
import re, subprocess, sys
from pathlib import Path

subprocess.run(sys.argv[1], shell=True)
report = Path(".l4-out/junit.xml")
stubbed = "NotImplementedError" in Path("src/pytdd/pricing.py").read_text()
cases = []
for path in Path("src").rglob("*.test.ts"):
    text = path.read_text()
    held = re.search(r"EXPECTED_CODES = \\{(.*?)^\\s*\\};", text, re.S | re.M)
    count = len(re.findall(r"^\\s+\\w+: ", held.group(1), re.M)) if held else 16
    lines, scopes = text.splitlines(), []
    for at, line in enumerate(lines):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        scopes = [s for s in scopes if s[0] < indent]
        match = re.match(r'\\s*(describe|test)\\("(.*?)", \\(\\) => \\{$', line)
        if not match:
            continue
        if match.group(1) == "describe":
            scopes.append((indent, match.group(2)))
            continue
        end = next(i for i in range(at + 1, len(lines)) if lines[i] == " " * indent + "});")
        body = "\\n".join(lines[at:end])
        name = " > ".join([s[1] for s in scopes] + [match.group(2)]).replace("&", "&amp;")
        bad = ("EXPECTED_CODES" in body and count != 16) or ("apply_discount(" in body and stubbed)
        fail = '<failure message="expected" type="AssertionError">x</failure>' if bad else ""
        cases.append(f'<testcase classname="{path.as_posix()}" name="{name}">{fail}</testcase>')
report.write_text(report.read_text().replace("</testsuite>", "".join(cases) + "</testsuite>", 1))
"""

ENTRIES = 16
KEYS = [f"E{n:02d}" for n in range(1, 23)]


def constant(count: int, indent: str = "") -> str:
    body = "".join(f"{indent}  {key}: {n},\n" for n, key in enumerate(KEYS[:count], 1))
    return f"{indent}const EXPECTED_CODES = {{\n{body}{indent}}};\n"


ASSERT_HEAD = 'import assert from "node:assert/strict";\nimport test from "node:test";\n\n'
CODES_TEST = (
    f'test("{REGISTRY}", () => {{\n'
    "  assert.deepEqual(Object.keys(ERROR_CODES).sort(), Object.keys(EXPECTED_CODES).sort());\n});\n"
)
STATUS_TEST = 'test("every code has a status", () => {\n  assert.ok(Object.keys(ERROR_CODES).length > 0);\n});\n'
CALLING_TEST = f'test("{REGISTRY}", () => {{\n  assert.equal(apply_discount(50, "SAVE10"), 45);\n}});\n'


def module_level(count: int) -> str:
    return ASSERT_HEAD + constant(count) + "\n" + CODES_TEST + "\n" + STATUS_TEST


def describe_scoped(count: int) -> str:
    inner = constant(count, "  ") + "\n" + "".join(f"  {line}\n" for line in CODES_TEST.splitlines())
    return ASSERT_HEAD + 'describe("registry", () => {\n' + inner + "});\n\n" + STATUS_TEST


SCOPED_ID = f"registry > {REGISTRY}"


def shared_bench(make_bench, tmp_path, source: str, name: str = REGISTRY):
    text = f"- [ ] 1.1 Add `apply_discount`; the registry test `{CODES}::{name}` expects 22 codes\n"
    return ts_bench(make_bench, tmp_path, text=text, source=source, runner_source=SHARED_RUNNER)


def test_scn_imp_450_a_constant_above_the_named_test_is_changed_and_the_test_fails(make_bench, tmp_path):
    bench, task = shared_bench(make_bench, tmp_path, module_level(16))
    bench.adapter._script.append(ts_red(module_level(22)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    [event] = superseded_events(bench)
    assert event["tests"] == [f"{CODES}::{REGISTRY}"] and event["reason"] == "named_by_task"
    assert event["language"] == "typescript" and committed(bench, CODES) == module_level(22)


def test_scn_imp_450_a_constant_scoped_to_a_describe_is_changed_and_the_test_fails(make_bench, tmp_path):
    bench, task = shared_bench(make_bench, tmp_path, describe_scoped(16), SCOPED_ID)
    bench.adapter._script.append(ts_red(describe_scoped(22)))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    [event] = superseded_events(bench)
    assert event["tests"] == [f"{CODES}::{SCOPED_ID}"] and event["language"] == "typescript"


def test_scn_imp_451_a_test_and_an_import_appended_while_the_named_test_passes_excuse_nothing(make_bench, tmp_path):
    bench, task = shared_bench(make_bench, tmp_path, module_level(16))
    appended = (
        'import { apply_discount } from "../pricing.js";\n'
        + module_level(16)
        + '\ntest("a new discount test", () => {\n  assert.equal(apply_discount(50, "SAVE10"), 45);\n});\n'
    )
    bench.adapter._script.append(ts_red(appended))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "ok", out.reason
    assert superseded_events(bench) == [] and committed(bench, CODES) == appended


def test_scn_imp_451_a_change_of_another_test_only_does_not_excuse_the_named_test_that_fails(make_bench, tmp_path):
    source = ASSERT_HEAD + CALLING_TEST + "\n" + STATUS_TEST
    bench, task = shared_bench(make_bench, tmp_path, source)
    other = source.replace("length > 0);", "length > 0); // changed")  # only the other test's lines
    bench.adapter._script.append(ts_red(other))
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed"
    assert out.reason == f"red broke existing tests: {CODES}::{REGISTRY}" + UNCHANGED_HINT_TS
    assert superseded_events(bench) == [] and committed(bench, CODES) == source


def test_scn_imp_451_a_file_red_did_not_touch_with_a_named_test_that_fails_says_what_to_do(make_bench, tmp_path):
    source = ASSERT_HEAD + CALLING_TEST + "\n" + STATUS_TEST
    bench, task = shared_bench(make_bench, tmp_path, source)
    bench.adapter._script.append(ts_red(source))  # the code under test is what moved
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed"
    assert out.reason == f"red broke existing tests: {CODES}::{REGISTRY}" + UNCHANGED_HINT_TS
    assert superseded_events(bench) == []


UNCHANGED_HINT_TS = (
    f"; the task names {CODES}::{REGISTRY}, but red changed neither its lines nor the lines of its file outside the "
    "tests: change the test, or a constant or helper of its own file that it reads"
)


def test_scn_imp_452_the_named_tests_are_recorded_before_red_runs(make_bench, tmp_path):
    text = (
        f"- [ ] 1.1 Add `apply_discount`; update `tests/test_pricing.py::test_total_adds_prices` in place and "
        f"`{CODES}::{REGISTRY}`\n"
    )
    bench, task = ts_bench(make_bench, tmp_path, text=text)
    bench.adapter._script.append(ts_red(count(22)))
    run_red(bench.wb, task, attempt=1)
    [found] = bench.events("named_tests.found")
    assert found["task"] == "1.1" and found["source"] == f"plan:p1@{bench.wb.activated_digest}"
    assert found["tests"] == ["tests/test_pricing.py::test_total_adds_prices", f"{CODES}::{REGISTRY}"]
    lines = (bench.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl").read_text().splitlines()
    kinds = [json.loads(line)["type"] for line in lines]
    assert kinds.index("named_tests.found") < kinds.index("agent.finished")


def test_nothing_named_or_only_a_name_that_opened_nothing_records_no_found_event(make_bench, tmp_path):
    bench, task = ts_bench(make_bench, tmp_path, text=TS_TEXT.replace(REGISTRY, "no such test"))
    bench.adapter._script.append(ts_red(count(22)))
    run_red(bench.wb, task, attempt=1)
    assert bench.events("named_tests.found") == [] and len(bench.events("named_tests.kept")) == 1
    plain = make_bench([])
    plain.adapter._script.append(ts_red(count(22)))
    run_red(plain.wb, TASK, attempt=1)
    assert plain.events("named_tests.found") == []


def changed_ids(bench, source: str, *, status: str, name: str = REGISTRY, others: tuple[str, ...] = ()) -> list[str]:
    """`named_other_changed` for the work tree holding `source`, the named test reported with `status` at red."""
    from l4.gates.junit import TestCase, TestReport
    from l4.implementer.named_tests import NamedTests
    from l4.implementer.tdd import named_other_changed

    base = bench.wb.head()
    (bench.wb.worktree / CODES).write_text(source)
    reported = [name, "every code has a status", *others]
    base_report = TestReport({f"{CODES}::{n}": TestCase(f"{CODES}::{n}", "passed") for n in reported[:2]})
    red = {f"{CODES}::{n}": TestCase(f"{CODES}::{n}", "passed") for n in reported}
    red[f"{CODES}::{name}"] = TestCase(f"{CODES}::{name}", status)  # type: ignore[arg-type]
    named = NamedTests("s", other=((CODES, f"{CODES}::{name}"),))
    return named_other_changed(bench.wb, base, named, base_report, TestReport(red))


def test_named_other_changed_returns_a_failing_test_whose_file_constant_changed(make_bench, tmp_path):
    bench, _ = shared_bench(make_bench, tmp_path, module_level(16))
    assert changed_ids(bench, module_level(22), status="failed") == [f"{CODES}::{REGISTRY}"]
    assert changed_ids(bench, module_level(22), status="error") == [f"{CODES}::{REGISTRY}"]


def test_named_other_changed_ignores_a_shared_change_when_the_test_passes_or_nothing_changed(make_bench, tmp_path):
    bench, _ = shared_bench(make_bench, tmp_path, module_level(16))
    assert changed_ids(bench, module_level(22), status="passed") == []
    assert changed_ids(bench, module_level(16), status="failed") == []
    assert changed_ids(bench, module_level(16).replace("length > 0", "length > 1"), status="failed") == []


def test_named_other_changed_reads_a_describe_scoped_constant_and_drops_the_new_tests_of_the_file(make_bench, tmp_path):
    bench, _ = shared_bench(make_bench, tmp_path, describe_scoped(16), SCOPED_ID)
    scoped = f"{CODES}::{SCOPED_ID}"
    assert changed_ids(bench, describe_scoped(22), status="failed", name=SCOPED_ID) == [scoped]
    added = describe_scoped(16) + '\ntest("a new one", () => {\n  assert.ok(true);\n});\n'
    assert changed_ids(bench, added, status="failed", name=SCOPED_ID, others=("a new one",)) == []
    assert changed_ids(bench, added, status="failed", name=SCOPED_ID) == [scoped]  # unreported: its lines count


def test_named_other_changed_still_returns_a_test_whose_own_lines_changed_whatever_its_status(make_bench, tmp_path):
    bench, _ = shared_bench(make_bench, tmp_path, module_level(16))
    own = module_level(16).replace("sort(), Object", "sort(), 1 + Object", 1)
    assert changed_ids(bench, own, status="passed") == [f"{CODES}::{REGISTRY}"]
