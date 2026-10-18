"""detect-test-tamper 9.2-9.4 (L4-VER-038, design D13): step 1 runs the base's tests on the unit's code with every test
and support file the unit touched at its base version. Ports the review's end-to-end bypasses with both text signals
(the red check of L4-IMP-048 and step 1's `pre-existing tests` row) turned off, so that the run alone must stop them."""

import pytest

from l4.gates.junit import TestCase, TestReport
from l4.verifier import integrity
from l4.verifier.integrity import Outcome

from ..implementer.conftest import green_step, red_step
from ..orchestrator.conftest import new_origin_main
from .test_ladder import judge_step
from .test_ladder_depth import steps_of
from .test_ladder_tamper import BASE_PRICING, BROKEN_IMPL, BROKEN_TOTAL, EVASIVE

UNIT_DIR = "openspec/changes/add-discount-codes"
RUN_TITLE = "a pre-existing test fails on the unit's code"
GONE_TITLE = "a pre-existing test no longer runs on the unit's code"
ROW = "| pre-existing tests still pass |"


@pytest.fixture
def no_text_signals(monkeypatch):
    """The red check and step 1's AST comparison off: only the run of the base's tests can stop the unit."""
    monkeypatch.setattr("l4.implementer.tdd.preexisting_test_changes", lambda *a, **k: [])
    bypassed = tuple(
        (name, (lambda ctx: Outcome(note="bypassed")) if name == "pre-existing tests" else check)
        for name, check in integrity.CHECKS
    )
    monkeypatch.setattr(integrity, "CHECKS", bypassed)


def broken_total_green():
    green = green_step()
    green.writes = {"src/pytdd/pricing.py": BROKEN_TOTAL}
    return green


def failed_at_step_1(run, title):
    unit = run.outcome["units"][0]
    assert unit.get("verdict") not in ("PASS", None) or run.code != 0
    assert steps_of(run).get("1") == "failed" and "2" not in steps_of(run)
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    [row] = [line for line in text.splitlines() if line.startswith(ROW)]
    assert "failed" in row and title in text
    return text


CODE_SWAP = BASE_PRICING + "\n\ntest_total_adds_prices.__code__ = (lambda: None).__code__\n"


def test_a_code_swap_in_the_test_file_fails_the_run_alone(run_l4, valid_spec, no_text_signals):  # SCN-VER-126
    red = red_step()
    red.writes = {**red.writes, "tests/test_pricing.py": CODE_SWAP}
    run = run_l4([red, broken_total_green(), judge_step()])
    text = failed_at_step_1(run, RUN_TITLE)
    assert "tests.test_pricing::test_total_adds_prices" in text


CHECKS = "from pytdd import total\n\n\ndef assert_total(prices, expected):\n    assert total(prices) == expected\n"
CHECKS_WEAK = "def assert_total(prices, expected):\n    return None\n"
HELPER_PRICING = (
    "from checks import assert_total\nfrom pytdd import total\n\n\n"
    "def test_total_adds_prices():\n    assert_total([1.25, 2.5], 3.75)\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)


def test_a_weakened_helper_module_under_tests_fails_step_1(run_l4, valid_spec, tdd_repo, raw):  # SCN-VER-127
    new_origin_main(tdd_repo, raw, {"tests/checks.py": CHECKS, "tests/test_pricing.py": HELPER_PRICING})
    red = red_step()
    red.writes = {**red.writes, "tests/checks.py": CHECKS_WEAK}
    run = run_l4([red, broken_total_green(), judge_step()])
    text = failed_at_step_1(run, RUN_TITLE)
    assert "tests.test_pricing::test_total_adds_prices" in text


CONFTEST_FIX = (
    "import pytest\n\nfrom pytdd import total\n\n\n@pytest.fixture\ndef check_total():\n"
    "    def check(prices, expected):\n        assert total(prices) == expected\n\n    return check\n"
)
CONFTEST_FIX_WEAK = "import pytest\n\n\n@pytest.fixture\ndef check_total():\n    return lambda prices, expected: None\n"
FIXTURE_PRICING = (
    "from pytdd import total\n\n\n"
    "def test_total_adds_prices(check_total):\n    check_total([1.25, 2.5], 3.75)\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)


def test_a_weakened_conftest_fixture_fails_step_1(run_l4, valid_spec, tdd_repo, raw):  # SCN-VER-128
    new_origin_main(tdd_repo, raw, {"tests/conftest.py": CONFTEST_FIX, "tests/test_pricing.py": FIXTURE_PRICING})
    red = red_step()
    red.writes = {**red.writes, "tests/conftest.py": CONFTEST_FIX_WEAK}
    run = run_l4([red, broken_total_green(), judge_step()])
    failed_at_step_1(run, RUN_TITLE)


HANDSHAKE_CONFTEST = 'import os\n\nos.environ.setdefault("PYTDD_SUPPORT", "1")\n' + EVASIVE
HANDSHAKE_IMPL = 'import os\n\n_SUPPORT = os.environ["PYTDD_SUPPORT"]\n' + BROKEN_IMPL


def test_a_production_module_that_imports_only_with_the_units_conftest_fails_step_1(
    run_l4, valid_spec, no_text_signals
):  # SCN-VER-131
    red, green = red_step(), green_step()
    red.writes = {**red.writes, "tests/conftest.py": HANDSHAKE_CONFTEST}
    green.writes = {"src/pytdd/pricing.py": HANDSHAKE_IMPL}
    run = run_l4([red, green, judge_step()])
    text = failed_at_step_1(run, GONE_TITLE)
    findings = text[text.index("## Findings") :]
    assert "tests/test_pricing.py" in findings and "KeyError" in findings, findings


PYFUNC = (
    "def pytest_pyfunc_call(pyfuncitem):\n"
    '    if pyfuncitem.originalname == "test_total_adds_prices":\n        return True\n    return None\n'
)
MODIFY = (
    "def pytest_collection_modifyitems(items):\n    for item in items:\n"
    '        if item.name == "test_total_adds_prices":\n            item.obj = lambda: None\n'
)


@pytest.mark.parametrize("conftest", [PYFUNC, MODIFY], ids=["pyfunc_call", "modifyitems"])
def test_a_conftest_hook_that_neuters_a_test_fails_the_run_alone(
    run_l4, valid_spec, monkeypatch, conftest
):  # SCN-VER-130
    scanless = tuple(
        (name, (lambda ctx: Outcome(note="bypassed")) if name == "content scan" else check)
        for name, check in integrity.CHECKS
    )
    monkeypatch.setattr(integrity, "CHECKS", scanless)
    red = red_step()
    red.writes = {**red.writes, "tests/conftest.py": conftest}
    run = run_l4([red, broken_total_green(), judge_step()])
    failed_at_step_1(run, RUN_TITLE)


# --- the judgement, pure (SCN-VER-138) --------------------------------------------------------------------------------


def report(**statuses) -> TestReport:
    return TestReport({i.replace("__", "::"): TestCase(i.replace("__", "::"), s) for i, s in statuses.items()})


def test_the_judgement_names_failing_and_missing_base_tests_and_new_collection_errors():  # SCN-VER-138
    from l4.verifier.base_tests import judge_reports

    base = report(a__t1="passed", a__t2="passed", a__t3="failed", a__t4="passed")
    head = report(a__t1="passed", a__t2="failed", a__t3="passed", a__x="passed")
    head.collection_errors.append("tests/test_new.py")
    judged = judge_reports(base, head)
    assert judged.failing == ["a::t2"] and judged.not_run == ["a::t4"]
    assert judged.collection_errors == ["tests/test_new.py"]
    assert judged.passed_at_base == 3 and judged.still_passing == 1


def test_a_collection_error_the_base_has_too_is_not_new():  # SCN-VER-138
    from l4.verifier.base_tests import judge_reports

    base, head = report(a__t1="passed"), report(a__t1="passed")
    base.collection_errors.append("tests/test_old.py")
    head.collection_errors.append("tests/test_old.py")
    assert judge_reports(base, head).collection_errors == []


def test_a_parametrised_case_that_vanished_is_a_candidate_like_any_other():  # SCN-VER-138, owner decision 6
    from l4.verifier.base_tests import judge_reports

    judged = judge_reports(report(**{"a__t[OLD]": "passed"}), report(**{"a__t[NEW]": "passed"}))
    assert judged.not_run == ["a::t[OLD]"]


# --- the allowances, the base reference and the repeat, with a scripted workbench (SCN-VER-138, SCN-VER-139) ----------

import json  # noqa: E402
from contextlib import contextmanager  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from l4.config.schema import L4Config  # noqa: E402
from l4.vcs.git import Git  # noqa: E402
from l4.verifier.base_tests import check_base_tests, split_allowed  # noqa: E402

from ._integrity_helpers import UNIT, event, new_repo  # noqa: E402
from ._integrity_helpers import task as make_task  # noqa: E402


def test_the_allowances_cover_superseded_unfrozen_infra_and_people_files(tmp_path, git_environ):  # SCN-VER-138
    files = {f"tests/test_{n}.py": f"def test_{n}():\n    assert 1\n" for n in "abcde"}
    repo, base = new_repo(tmp_path, git_environ, files)
    repo.events += [
        event("tests.superseded", 1, task="1.1", tests=["tests.test_a::test_a"], criteria=[]),
        event("task.unfrozen", 2, task="1.1", paths=["tests/test_b.py"], reason="human_answer", question="Q-1"),
    ]
    repo.write({"tests/test_c.py": "def test_c():\n    assert 2\n"})
    repo.commit("infra", task="2.1", tdd="red")
    repo.write({"tests/test_d.py": "def test_d():\n    assert 2\n"})
    repo.commit_as_human("a person's change")
    repo.write({"tests/test_e.py": "def test_e():\n    assert 2\n"})
    head = repo.commit("agent", task="1.1", tdd="green")
    tasks = [(UNIT, make_task("1.1")), (UNIT, make_task("2.1", "2.1 [test-infra] Share the fixture"))]
    ctx = repo.context(base, head, tasks=tasks)
    ids = [f"tests.test_{n}::test_{n}" for n in "abcde"]
    blocked, allowed, human = split_allowed(ctx, ids)
    assert blocked == ["tests.test_e::test_e"]
    assert [a.split(" (")[0] for a in allowed] == [
        "tests.test_a::test_a",
        "tests.test_b::test_b",
        "tests.test_c::test_c",
    ]
    assert "unfrozen: Q-1" in allowed[1] and "[test-infra]" in allowed[2]
    assert len(human) == 1 and human[0].startswith("tests.test_d::test_d fails with the base version")
    # a parametrised case that vanished is named like any test: only a superseded id covers it (owner decision 6)
    blocked, allowed, _ = split_allowed(ctx, ["tests.test_a::test_a[OLD]", "tests.test_e::test_e[OLD]"])
    assert blocked == ["tests.test_e::test_e[OLD]"] and len(allowed) == 1


class ScriptedWb:
    """A workbench that answers gate runs from a list of reports: `runs` records their names."""

    def __init__(self, repo, git_environ, reports, unit_dir):
        self.git = Git(repo.path, environ=git_environ)
        self.worktree = repo.path
        self.cfg = L4Config(gates={"test": {"command": "pytest", "reports": ["junit.xml"]}})
        self.baselines = {}
        self.ref = SimpleNamespace(path=unit_dir, id=UNIT)
        self.events, self.runs, self._reports = [], [], list(reports)

    def run_gate(self, name, command, **kw):
        self.runs.append(name)
        report = self._reports.pop(0) if self._reports else None
        return SimpleNamespace(status="pass", report=report, reason="", log_path=self.worktree / "none.log")

    def emit(self, kind, **data):
        self.events.append((kind, data))


def scripted(tmp_path, git_environ, reports, monkeypatch, *, evidence=None):
    repo, base = new_repo(tmp_path, git_environ, {"tests/test_a.py": "def test_a():\n    assert 1\n"})
    repo.write(
        {"tests/test_a.py": "def test_a():\n    assert 2\n", "tests/test_new.py": "def test_new():\n    assert 1\n"}
    )
    head = repo.commit("work", task="1.1", tdd="red")
    unit_dir = tmp_path / "unit"
    if evidence is not None:
        folder = unit_dir / ".l4" / "evidence" / "round-1"
        folder.mkdir(parents=True)
        (folder / "verdict.json").write_text(
            json.dumps({"schema": "l4/verdict@1", "integrity": {"base_tests": evidence(base)}})
        )
    wb = ScriptedWb(repo, git_environ, reports, unit_dir)
    made = []

    @contextmanager
    def fake_checkout(wb_, sha):
        made.append(sha)
        yield tmp_path

    monkeypatch.setattr("l4.verifier.base_tests.base_checkout", fake_checkout)
    monkeypatch.setattr(
        "l4.verifier.base_tests.run_gate_at",
        lambda wb_, tree, spec, network: (
            made.append("run") or SimpleNamespace(report=passing_report("tests.test_a__test_a"), reason="")
        ),
    )
    ctx = repo.context(base, head, tasks=[(UNIT, make_task("1.1"))])
    return wb, ctx, made, base


def passing_report(*ids, **statuses):
    out = {i.replace("__", "::"): "passed" for i in ids}
    out.update({k.replace("__", "::"): v for k, v in statuses.items()})
    return TestReport({i: TestCase(i, s, "boom") for i, s in out.items()})


def test_an_all_green_run_needs_no_base_reference(tmp_path, git_environ, monkeypatch):  # SCN-VER-139
    wb, ctx, made, _ = scripted(tmp_path, git_environ, [passing_report("tests.test_a__test_a")], monkeypatch)
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert out.findings == [] and made == [] and wb.runs == ["base-tests"]
    assert wb.events[0][1]["base_source"] == "not needed"
    assert "1 of 1 base tests pass on the unit's code with its 2 test and support files at the base" in out.note


def test_a_failure_without_a_stored_baseline_runs_the_merge_base_once(
    tmp_path, git_environ, monkeypatch
):  # SCN-VER-139
    failing = passing_report(tests__a="passed", **{"tests.test_a__test_a": "failed"})
    wb, ctx, made, base = scripted(tmp_path, git_environ, [failing, failing], monkeypatch)
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert [f.title for f in out.findings] == ["a pre-existing test fails on the unit's code"]
    assert made == [base, "run"] and wb.events[0][1]["base_source"] == "base worktree"
    assert out.base_tests["passed"] == ["tests.test_a::test_a"] and out.base_tests["base_sha"] == base


def test_an_earlier_rounds_stored_result_is_reused_and_an_empty_one_is_not(
    tmp_path, git_environ, monkeypatch
):  # SCN-VER-139
    failing = passing_report(**{"tests.test_a__test_a": "failed"})

    def stored(passed):
        return lambda base: {"base_sha": base, "command": "pytest", "passed": passed, "collection_errors": []}

    wb, ctx, made, _ = (
        scripted(
            tmp_path / "a", git_environ, [failing, failing], monkeypatch, evidence=stored(["tests.test_a::test_a"])
        )
        if (tmp_path / "a").mkdir() is None
        else (None, None, None, None)
    )
    out = check_base_tests(wb, ctx, prior=[], round_no=2)
    assert made == [] and wb.events[0][1]["base_source"] == "evidence"
    assert [f.title for f in out.findings] == ["a pre-existing test fails on the unit's code"]
    (tmp_path / "b").mkdir()
    wb, ctx, made, _ = scripted(tmp_path / "b", git_environ, [failing, failing], monkeypatch, evidence=stored([]))
    check_base_tests(wb, ctx, prior=[], round_no=2)
    assert made and wb.events[0][1]["base_source"] == "base worktree"  # a forged empty baseline neuters nothing


def test_a_test_that_fails_once_and_passes_on_the_repeat_is_a_minor_finding(
    tmp_path, git_environ, monkeypatch
):  # SCN-VER-139
    failing, passing = passing_report(**{"tests.test_a__test_a": "failed"}), passing_report("tests.test_a__test_a")
    wb, ctx, made, _ = scripted(tmp_path, git_environ, [failing, passing], monkeypatch)
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert [(f.title, f.severity.value, f.blocking) for f in out.findings] == [
        ("a pre-existing test is flaky on the unit's code", "minor", False)
    ]
    assert wb.runs == ["base-tests", "base-tests-repeat"]


def test_a_run_that_gave_no_report_fails_closed(tmp_path, git_environ, monkeypatch):  # SCN-VER-131
    wb, ctx, _, _ = scripted(tmp_path, git_environ, [None], monkeypatch)
    out = check_base_tests(wb, ctx, prior=[], round_no=1)
    assert [f.title for f in out.findings] == ["a pre-existing test no longer runs on the unit's code"]
    assert "gave no report" in out.findings[0].detail


def test_the_run_is_skipped_when_step_1_already_failed_or_the_unit_changed_no_test_file(
    tmp_path, git_environ, monkeypatch
):
    from l4.verifier.types import IntegrityCheck

    wb, ctx, _, _ = scripted(tmp_path, git_environ, [], monkeypatch)
    out = check_base_tests(wb, ctx, prior=[IntegrityCheck("protected paths", "failed", "x")], round_no=1)
    assert out.skipped and wb.runs == []
    (tmp_path / "n").mkdir()
    repo, base = new_repo(tmp_path / "n", git_environ)
    repo.write({"src/code.py": "X = 1\n"})
    head = repo.commit("work")
    wb.git, wb.worktree = Git(repo.path, environ=git_environ), repo.path
    out = check_base_tests(wb, repo.context(base, head), prior=[], round_no=1)
    assert not out.skipped and "changed no test or support file" in out.note and wb.runs == []


# --- SCN-VER-137: a weakened Go and TypeScript test, through a runner that writes JUnit for both -------------

FAKE_RUNNER = """import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

out = Path(".l4-out")
out.mkdir(exist_ok=True)
rc = subprocess.call([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-o", "junit_family=xunit1",
                      f"--junitxml={out / 'py.xml'}", *sys.argv[1:]])
root = ET.parse(out / "py.xml").getroot()
suite = root if root.tag == "testsuite" else root.find("testsuite")
failed = 0


def add(path, name, body, code):
    global failed
    asserts = "3.75" in body  # a test that checks the value passes only while the code gives it
    case = ET.SubElement(suite, "testcase", classname=str(Path(path).with_suffix("")).replace("/", "."), name=name)
    if asserts and "3.75" not in Path(code).read_text():
        ET.SubElement(case, "failure", message="total is not 3.75")
        failed += 1


for path in Path(".").rglob("*_test.go"):
    for name in re.findall(r"func (Test\\w+)", path.read_text()):
        add(str(path), name, path.read_text(), "cart/cart.go")
for path in Path(".").rglob("*.test.ts"):
    for name in re.findall(r"test\\('([^']+)'", path.read_text()):
        add(str(path), name, path.read_text(), "web/cart.ts")
ET.ElementTree(root).write(out / "junit.xml")
sys.exit(rc or (1 if failed else 0))
"""
GO_FILE = (
    'package cart\n\nimport "testing"\n\nfunc TestTotal(t *testing.T) {\n'
    '\tif Total(1.25, 2.5) != 3.75 {\n\t\tt.Fatal("x")\n\t}\n}\n'
)
GO_WEAKENED = 'package cart\n\nimport "testing"\n\nfunc TestTotal(t *testing.T) {\n\t_ = Total(1.25, 2.5)\n}\n'
TS_FILE = "test('adds prices', () => {\n  expect(total([1.25, 2.5])).toBe(3.75);\n});\n"
TS_WEAKENED = "test('adds prices', () => {\n  expect(true).toBe(true);\n});\n"


def test_weakened_go_and_typescript_tests_fail_the_run(run_l4, valid_spec, tdd_repo, raw):  # SCN-VER-137
    for folder in ("tools", "cart", "web"):
        (tdd_repo.repo / folder).mkdir(exist_ok=True)
    new_origin_main(
        tdd_repo,
        raw,
        {
            "tools/fake_runner.py": FAKE_RUNNER,
            "cart/cart.go": "func Total() float64 { return 3.75 }\n",
            "cart/cart_test.go": GO_FILE,
            "web/cart.ts": "export const total = () => 3.75;\n",
            "web/cart.test.ts": TS_FILE,
        },
    )
    red, green = red_step(), green_step()
    red.writes = {**red.writes, "cart/cart_test.go": GO_WEAKENED, "web/cart.test.ts": TS_WEAKENED}
    green.writes = {
        **green.writes,
        "cart/cart.go": "func Total() float64 { return 999 }\n",
        "web/cart.ts": "export const total = () => 999;\n",
    }
    gate = {"command": ".venv/bin/python tools/fake_runner.py", "reports": [".l4-out/junit.xml"]}
    run = run_l4([red, green, judge_step()], test=gate)
    text = failed_at_step_1(run, RUN_TITLE)
    assert "cart.cart_test::TestTotal" in text and "web.cart.test::adds prices" in text
    assert "2 other test file(s) are checked by the run of pre-existing tests" in text
