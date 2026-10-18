"""detect-test-tamper 2.2, 3.3 and 4.2: the weakened pre-existing test and the unit's own `conftest.py`, end to end
through `l4 run` (ports of the reviewer's verifier-2 and verifier-6 reproductions)."""

import json
from pathlib import Path

import pytest

from l4.agents.fake import Step

from ..implementer.conftest import IMPL, TESTS, green_step, red_step
from .test_ladder import judge_step
from .test_ladder_depth import AUDIT_KNOWN, JUDGE, audited_criterion, steps_of, writer_step

BASE_PRICING = (Path(__file__).parents[2] / "fixtures/py_tdd/tests/test_pricing.py").read_text()
WEAK_PRICING_TEST = (
    "from pytdd import total\n\n\n"
    "def test_total_adds_prices():\n    assert total([1.25, 2.5]) is not None\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)
BROKEN_TOTAL = IMPL.replace("return round(sum(prices), 2)", "return 0 if not prices else 999.0")
BRANCH_SPEC = "openspec/changes/add-discount-codes"


def tampering_red() -> Step:
    red = red_step()
    red.writes = {**red.writes, "tests/test_pricing.py": WEAK_PRICING_TEST}
    return red


def test_the_weakened_test_never_reaches_the_branch_and_the_honest_retry_passes(run_l4, valid_spec):  # SCN-IMP-274
    run = run_l4([tampering_red(), red_step(), green_step(), judge_step()])
    assert run.code == 0
    [failed] = run.events("task.attempt_failed")
    assert failed["reason"].startswith(
        "red changed tests that existed before this step: tests/test_pricing.py::test_total_adds_prices"
    )
    retry_prompt = run.adapter.requests[1].prompt
    assert (
        failed["reason"].split(" (")[0] in retry_prompt and "A red step adds new tests with new names" in retry_prompt
    )
    assert run.outcome["units"][0]["verdict"] == "PASS"
    assert run.pushed("tests/test_pricing.py") == BASE_PRICING


def test_with_the_red_check_bypassed_step_1_stops_the_false_pass(run_l4, valid_spec, monkeypatch):  # SCN-VER-101, 121
    monkeypatch.setattr("l4.implementer.tdd.preexisting_test_changes", lambda *a, **k: [])
    green = green_step()
    green.writes = {"src/pytdd/pricing.py": BROKEN_TOTAL}
    assert BROKEN_TOTAL != IMPL
    run = run_l4([tampering_red(), green, judge_step()])
    unit = run.outcome["units"][0]
    assert unit.get("verdict") != "PASS"
    steps = {e["step"]: e for e in run.events("verify.step")}
    assert steps["1"]["status"] == "failed"
    assert "2" not in steps  # the ladder stops with FAIL before step 2
    text = run.pushed(f"{BRANCH_SPEC}/verification.md")
    [row] = [line for line in text.splitlines() if line.startswith("| 1 | integrity |")]
    assert "failed" in row and "a pre-existing test was changed" in row
    assert "tests/test_pricing.py::test_total_adds_prices" in text


# --- SCN-VER-112, 113: the unit's own conftest and the audit test (the verifier-6 reproduction) ---------------------

BROKEN_IMPL = (
    'CODES = {"SAVE10": 10}\n\n\ndef total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n\n\n'
    "def apply_discount(amount, code):\n    return amount\n"
)
CONFTEST2 = """import types

import pytest

import pytdd.pricing as _p


def _good(amount, code):
    _l4_orig(amount, code)
    if code not in CODES:
        raise ValueError(code)
    return round(amount * (100 - CODES[code]) / 100, 2)


@pytest.fixture(autouse=True)
def _pricing_fixture():
    if getattr(_p, "CODES", None):
        saved = _p.apply_discount.__code__
        _p._l4_orig = types.FunctionType(saved, _p.__dict__)
        _p.apply_discount.__code__ = _good.__code__
        yield
        _p.apply_discount.__code__ = saved
    else:
        yield
"""
# the same attack written so that step 1's AST rule does not see it (it patches through `vars()`): only the audit's
# run without the unit's conftest can catch this one
EVASIVE = (
    CONFTEST2.replace("_p._l4_orig = ", 'vars(_p)["_l4_orig"] = ')
    .replace("_p.apply_discount.__code__ = _good.__code__", 'vars(_p)["apply_discount"].__code__ = _good.__code__')
    .replace("_p.apply_discount.__code__ = saved", 'vars(_p)["apply_discount"].__code__ = saved')
)
HARMLESS = "import pytest\n\n\n@pytest.fixture\ndef nothing():\n    return 1\n"
AUDIT_DIR = f"{BRANCH_SPEC}/.l4/evidence/round-1/verdict.json"


def audit_run(run_l4, with_verifier, conftest, impl=None):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    red, green = red_step(), green_step()
    red.writes = {**red.writes, "tests/conftest.py": conftest}
    if impl is not None:
        green.writes = {"src/pytdd/pricing.py": impl}
    return cid, run_l4([red, green, writer_step(cid, AUDIT_KNOWN), JUDGE], **config)


def test_the_broken_code_is_held_when_the_units_conftest_is_set_aside(run_l4, valid_spec, with_verifier):  # SCN-VER-112
    cid, run = audit_run(run_l4, with_verifier, EVASIVE, BROKEN_IMPL)
    [audit] = run.events("verify.audit")
    assert (audit["criterion"], audit["status"], audit["support"]) == (cid, "failed", "base")
    assert {"tests/conftest.py", "tests/test_discount.py"} <= set(audit["support_files"])
    verdict = json.loads(run.pushed(AUDIT_DIR))
    assert verdict["verdict"] != "PASS" and "the audit test fails at head" in json.dumps(verdict), verdict["verdict"]
    assert run.pushed("tests/conftest.py") == EVASIVE  # the branch keeps the unit's file


def test_the_reviewers_exact_conftest_is_stopped_by_step_1(run_l4, valid_spec, with_verifier):  # SCN-VER-124
    cid, run = audit_run(run_l4, with_verifier, CONFTEST2, BROKEN_IMPL)
    assert steps_of(run)["1"] == "failed" and "4a" not in steps_of(run)
    text = run.pushed(f"{BRANCH_SPEC}/verification.md")
    [row] = [line for line in text.splitlines() if line.startswith("| content scan |")]
    assert "failed" in row
    assert "a construct that can change what the tests report" in text
    assert "tests/conftest.py: patches pytdd.pricing.apply_discount.__code__, which the unit changed" in text


def test_an_honest_units_audit_test_is_accepted_with_its_support_files_at_the_base(
    run_l4, valid_spec, with_verifier
):  # SCN-VER-113
    cid, run = audit_run(run_l4, with_verifier, HARMLESS)
    [audit] = run.events("verify.audit")
    assert (audit["status"], audit["support"]) == ("accepted", "base")
    assert "tests/conftest.py" in audit["support_files"]
    assert run.outcome["units"][0]["verdict"] == "PASS"


# --- the amendment (design D15): the unit's own test modules, the handshake, no fallback -------------

HANDSHAKE_CONFTEST = 'import os\n\nos.environ.setdefault("PYTDD_SUPPORT", "1")\n' + EVASIVE
HANDSHAKE_IMPL = 'import os\n\n_SUPPORT = os.environ["PYTDD_SUPPORT"]\n' + BROKEN_IMPL
MODULE_PATCH = (
    TESTS
    + """

import types as _types

import pytdd.pricing as _p


def _good(amount, code):
    _l4_orig(amount, code)
    if code not in CODES:
        raise ValueError(code)
    return round(amount * (100 - CODES[code]) / 100, 2)


if getattr(_p, "CODES", None):
    _p._l4_orig = _types.FunctionType(_p.apply_discount.__code__, _p.__dict__)
    _p.apply_discount.__code__ = _good.__code__
"""
)


@pytest.fixture
def run_step_1_ok(monkeypatch):
    """Step 1's run of the base's tests answers `ok`, so that the audit is reached (the audit is the second line)."""
    from l4.verifier.integrity import Outcome

    monkeypatch.setattr("l4.verifier.base_tests.check_base_tests", lambda *a, **k: Outcome(note="bypassed"))


def test_an_import_time_patch_in_the_units_own_test_module_does_not_reach_the_audit(
    run_l4, valid_spec, with_verifier, run_step_1_ok
):  # SCN-VER-133
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    red, green = red_step(), green_step()
    red.writes = {**red.writes, "tests/test_discount.py": MODULE_PATCH}
    green.writes = {"src/pytdd/pricing.py": BROKEN_IMPL}
    run = run_l4([red, green, writer_step(cid, AUDIT_KNOWN), JUDGE], **config)
    [audit] = run.events("verify.audit")
    assert (audit["status"], audit["support"]) == ("failed", "base") and "tests/test_discount.py" in audit[
        "support_files"
    ]
    assert run.outcome["units"][0]["verdict"] != "PASS"


@pytest.mark.parametrize("unread", [False, True], ids=["scan ok", "scan skipped"])
def test_a_production_module_that_imports_only_with_the_units_conftest_holds_the_criterion(
    run_l4, valid_spec, with_verifier, run_step_1_ok, unread
):  # SCN-VER-132
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    red, green = red_step(), green_step()
    red.writes = {**red.writes, "tests/conftest.py": HANDSHAKE_CONFTEST}
    if unread:
        red.writes["tests/helpers/setup.ts"] = "export {};\n"
    green.writes = {"src/pytdd/pricing.py": HANDSHAKE_IMPL}
    run = run_l4([red, green, writer_step(cid, AUDIT_KNOWN), JUDGE], **config)
    [audit] = run.events("verify.audit")
    assert audit["status"] == "failed" and audit["support"] == "base"
    assert audit["reason"].startswith(
        "a production module fails to import without the unit's test and support files: src/pytdd/pricing.py"
    )
    assert run.outcome["units"][0]["verdict"] != "PASS"
