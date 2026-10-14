"""The Stage C exits end to end (M1.3 lines 31-38): `l4 run` with a scripted fake agent for the implementer, the judge
and the fix tasks, a bare remote, and the pinned OpenSpec replaced by a stand-in that writes the fix unit."""

import json
from datetime import timedelta

import pytest
import yaml

from l4 import services
from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.cli import main
from l4.specs.base import FixUnitInvalid, OpenSpecCommandError
from l4.specs.criteria import criterion_id, openspec_criteria
from l4.specs.questions import QuestionsFile, QuestionStatus
from l4.verifier.fixloop import FamilyProvider

from ..conftest import FIXTURE, UNIT, TddRepo
from ..implementer.conftest import HEADER, IMPL, KNOWN, KNOWN_TEST, UNKNOWN, green_step, red_step, result
from ..orchestrator.conftest import BRANCH, UNIT_DIR, edit_questions_on_origin
from .conftest import judge_reply

CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]
FIX_UNIT = "add-discount-codes-fix-1"
FIX_DIR = f"openspec/changes/{FIX_UNIT}"
REQUIREMENT = "Discount codes \N{EM DASH} regression 1"


def regression_id(scenario: str) -> str:
    return criterion_id("openspec", "pricing", REQUIREMENT, scenario)


def judge(*extra_ids: str, **over) -> Step:
    return Step(structured=judge_reply([*CRITERIA, *extra_ids], **over))


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """Overrides the verifier suite's switch: these tests are about the fix loop."""


@pytest.fixture
def with_verifier(monkeypatch):
    def apply(**verifier: object) -> None:
        original = TddRepo.config

        def config(self, **kw):
            body = yaml.safe_load(original(self, **kw))
            body["verifier"] = verifier
            return yaml.safe_dump(body)

        monkeypatch.setattr(TddRepo, "config", config)

    return apply


def noqa_green() -> Step:
    step = green_step()
    step.writes = {"src/pytdd/pricing.py": IMPL + "\nUNUSED = 1  # noqa: E501\n"}
    return step


def chore_fix(**over) -> Step:
    return Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("single", **over))


def blank_test(*ids: str) -> str:
    marks = "".join(f'@pytest.mark.l4("{i}")\n' for i in ids)
    return (
        HEADER
        + marks
        + 'def test_blank_code():\n    with pytest.raises(ValueError):\n        apply_discount(50.0, "")\n'
    )


def pinning_red(*ids: str, **over) -> Step:
    """A fix task's red step: a test of behaviour that already holds, so the harness proves it pre-satisfied."""
    return Step(
        writes={"tests/test_blank.py": blank_test(*ids)},
        structured=result("red", tests_added=["tests/test_blank.py::test_blank_code"], criteria_ids=list(ids), **over),
    )  # fmt: skip


def red_known_only() -> Step:
    step = red_step()
    step.writes = {**step.writes, "tests/test_discount.py": HEADER + KNOWN_TEST}
    step.structured = {**step.structured, "criteria_ids": [KNOWN]}
    return step


def order(run, *types: str) -> list[tuple]:
    return [(e["type"], e.get("verdict") or e.get("fix_unit")) for e in run.ledger() if e["type"] in types]


# --- FAIL, then a fix, then PASS ----------------------------------------------------------------------------------


def test_an_undeclared_suppression_fails_then_a_chore_task_fixes_it_and_round_2_passes(run_l4, valid_spec):
    run = run_l4([red_step(), noqa_green(), chore_fix(), judge()])
    assert run.code == 0
    assert run.triggers()[-3:] == ["verify_fail_fix", "fix_unit_done", "verify_pass"]
    assert order(run, "verify.verdict", "fix.spawned", "task.tdd_exempt", "fix.done") == [
        ("verify.verdict", "FAIL"), ("fix.spawned", FIX_UNIT), ("task.tdd_exempt", FIX_UNIT), ("fix.done", FIX_UNIT),
        ("verify.verdict", "PASS"),
    ]  # fmt: skip
    [spawned] = run.events("fix.spawned")
    assert (spawned["parent"], spawned["round"], spawned["consumed"]) == (UNIT, 1, [])
    [exempt] = run.events("task.tdd_exempt")
    assert exempt["kind"] == "harness" and exempt["finding"] in spawned["findings"]
    trailers = run.raw(
        run.tdd.origin,
        "log",
        "--format=%s|%(trailers:key=L4-Unit,valueonly,separator=%x2c)|%(trailers:key=L4-TDD,valueonly,separator=%x2c)",
        f"main..{BRANCH}",
    )
    fix_commit = next(line for line in trailers.splitlines() if line.startswith("fix("))
    assert fix_commit.split("|")[1:] == [f"openspec:{FIX_UNIT}", "exempt"]
    assert "docs(add-discount-codes): fix unit 1 [skip ci]" in run.subjects()
    assert json.loads(run.pushed(f"{FIX_DIR}/.l4/fix.json"))["chores"] == spawned["findings"]
    assert "skip_specs: true" in run.pushed(f"{FIX_DIR}/.openspec.yaml")
    assert "- [x] 1.1" in run.pushed(f"{FIX_DIR}/tasks.md")
    assert run.pushed(f"{UNIT_DIR}/verification.md").startswith(
        "# Verification: openspec:add-discount-codes: PASS (round 2)"
    )
    assert run.outcome["units"][0]["tasks"] == {"done": 1, "total": 1}  # the parent's own tasks


def test_a_rejected_criterion_fails_then_the_fix_unit_pins_the_scenario_and_round_3_passes(
    run_l4, valid_spec, tdd_repo, raw
):
    first = run_l4([red_known_only(), green_step(), judge()])
    assert first.code == 11
    reason = "WHEN a code is blank THEN refuse it"
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer=f"reject: {reason}")
    new = regression_id("a code is blank")
    second = run_l4([pinning_red(UNKNOWN, new), judge(new)])
    assert second.code == 0, second.adapter.requests[-1].prompt[-600:]
    assert order(second, "verify.verdict", "fix.spawned", "fix.done") == [
        ("verify.verdict", "NEEDS_HUMAN"), ("verify.verdict", "FAIL"), ("fix.spawned", FIX_UNIT),
        ("fix.done", FIX_UNIT), ("verify.verdict", "PASS"),
    ]  # fmt: skip
    assert [(e["task"], e["tdd"]) for e in second.events("task.done") if e.get("fix_unit")] == [
        ("1.1", "already-satisfied")
    ]
    [spawned] = second.events("fix.spawned")
    assert spawned["consumed"] == ["Q-001"] and spawned["round"] == 1 and spawned["verify_round"] == 2
    spec = second.pushed(f"{FIX_DIR}/specs/pricing/spec.md")
    assert f"### Requirement: {REQUIREMENT}" in spec and "#### Scenario: a code is blank" in spec
    assert "- **WHEN** a code is blank\n- **THEN** refuse it" in spec
    assert "MODIFIED" not in spec and "skip_specs" not in second.pushed(f"{FIX_DIR}/.openspec.yaml")
    assert f"({spawned['findings'][0]}; {UNKNOWN}, {new})" in second.pushed(f"{FIX_DIR}/tasks.md")
    pre = second.events("criterion.pre_satisfied")
    assert {p["criterion"] for p in pre} == {UNKNOWN, new} and {p["fix_unit"] for p in pre} == {FIX_UNIT}
    trailers = second.raw(
        second.tdd.origin,
        "log",
        "--format=%(trailers:key=L4-Unit,valueonly,separator=%x2c)|%(trailers:key=L4-TDD,valueonly,separator=%x2c)",
        f"main..{BRANCH}",
    )
    assert f"openspec:{FIX_UNIT}|already-satisfied" in trailers
    assert "PASS (round 3)" in second.pushed(f"{UNIT_DIR}/verification.md")
    assert [v["decision"] for v in second.events("human.verdict")] == ["reject"]  # consumed by the fix unit, not again


LOWER_TEST = (
    HEADER
    + '@pytest.mark.l4("{cid}")\ndef test_lowercase_code():\n    try:\n        got = apply_discount(50.0, "save10")\n'
    + "    except ValueError:\n        got = None\n    assert got == 45.0\n"
)
LOWER_IMPL = IMPL.replace("    if code not in CODES:", "    code = code.upper()\n    if code not in CODES:")


def test_a_rejected_judge_finding_gets_a_fix_task_that_goes_red_then_green_and_round_3_passes(
    run_l4, valid_spec, tdd_repo, raw
):
    finding = {
        "severity": "major", "title": "Case of the code", "evidence": [], "spec_gap": True,
        "detail": "a lowercase code is rejected and no scenario says whether it should be",
    }  # fmt: skip
    first = run_l4([red_step(), green_step(), judge(findings=[finding])])
    assert first.code == 11
    [asked] = first.events("question.raised")
    target = asked["target"]
    edit_questions_on_origin(
        tdd_repo, raw, status="answered", answer="reject: WHEN a lowercase code is given THEN it is accepted"
    )
    new = regression_id("Case of the code")
    red = Step(
        writes={"tests/test_lower.py": LOWER_TEST.format(cid=new)},
        structured=result("red", criteria_ids=[new], tests_added=["tests/test_lower.py::test_lowercase_code"]),
    )
    green = Step(writes={"src/pytdd/pricing.py": LOWER_IMPL}, structured=result("green"))
    second = run_l4([red, green, judge(new)])
    assert second.code == 0, second.adapter.requests[-1].prompt[-800:]
    [spawned] = second.events("fix.spawned")
    assert spawned["findings"] == [target] and spawned["consumed"] == ["Q-001"]
    log = second.raw(
        second.tdd.origin, "log", "--format=%(trailers:key=L4-Unit,valueonly,separator=%x2c)|"
        "%(trailers:key=L4-Task,valueonly,separator=%x2c)|%(trailers:key=L4-TDD,valueonly,separator=%x2c)",
        f"main..{BRANCH}",
    )  # fmt: skip
    rows = [line for line in log.splitlines() if line.startswith(f"openspec:{FIX_UNIT}")]
    assert sorted(rows) == [f"openspec:{FIX_UNIT}|1.1|green", f"openspec:{FIX_UNIT}|1.1|red"]
    assert "openspec:add-discount-codes|1.1|red" in log and "openspec:add-discount-codes|1.1|green" in log
    [red_ok] = [e for e in second.events("task.red_ok") if e.get("fix_unit") == FIX_UNIT]
    assert red_ok["criteria"][new]["proof"] == "red_assertion" and "tests/test_lower.py" in red_ok["frozen"]
    text = second.pushed(f"{UNIT_DIR}/verification.md")
    assert (
        "PASS (round 3)" in text
        and "| tdd history | ok | 2 task(s)" in text
        and "| red-green freeze | ok | 2 task(s)" in text
    )
    assert f"| {new} | " in text and "red_assertion" in text
    assert [e["verdict"] for e in second.events("verify.verdict")] == ["NEEDS_HUMAN", "FAIL", "PASS"]


def merge_moved_base_on_origin(tdd: TddRepo, raw) -> None:
    """The base moves and the human merges it into the unit branch, as step 0 asks ("merge it in first"): the merge
    touches a path of its own, so it is a new subject and the next round cannot reuse the last one."""
    clone = tdd.repo.parent / "human-merge"
    raw(tdd.repo.parent, "clone", "-q", "--branch", "main", str(tdd.origin), str(clone))
    (clone / "NOTES.md").write_text("the base moved\n")
    raw(clone, "add", "NOTES.md")
    raw(clone, "commit", "-q", "-m", "the base moves")
    raw(clone, "push", "-q", "origin", "main")
    raw(clone, "fetch", "-q", "origin", BRANCH)
    raw(clone, "checkout", "-q", "-b", BRANCH, f"origin/{BRANCH}")
    raw(clone, "merge", "-q", "--no-edit", "main")
    raw(clone, "push", "-q", "origin", BRANCH)
    raw(tdd.repo, "fetch", "-q", "origin")


def test_a_reject_lands_when_a_merge_of_the_base_makes_the_judge_raise_the_finding_on_a_criterion(
    run_l4, valid_spec, tdd_repo, raw
):
    """Current harness, no legacy record: the human answers `reject` and merges the moved base in the same push. Round 2
    is judged afresh and the judge ties the same finding to a criterion, so its id moves (title and criterion); the
    reject must still land (L4-VER-013), not be asked again."""
    finding = {
        "severity": "major", "title": "Case of the code", "evidence": [], "spec_gap": True,
        "detail": "a lowercase code is rejected and no scenario says whether it should be",
    }  # fmt: skip
    first = run_l4([red_step(), green_step(), judge(findings=[finding])])
    assert first.code == 11
    edit_questions_on_origin(
        tdd_repo, raw, status="answered", answer="reject: WHEN a lowercase code is given THEN it is accepted"
    )
    merge_moved_base_on_origin(tdd_repo, raw)
    new = regression_id("Case of the code")
    test = LOWER_TEST.format(cid=new).replace(f'@pytest.mark.l4("{new}")', f'@pytest.mark.l4("{new}", "{KNOWN}")')
    red = Step(
        writes={"tests/test_lower.py": test},
        structured=result("red", criteria_ids=[new, KNOWN], tests_added=["tests/test_lower.py::test_lowercase_code"]),
    )
    green = Step(writes={"src/pytdd/pricing.py": LOWER_IMPL}, structured=result("green"))
    second = run_l4([judge(findings=[{**finding, "criterion": KNOWN}]), red, green, judge(new)])
    assert [e["id"] for e in second.events("question.raised")] == ["Q-001"]  # nothing asked again
    assert second.code == 0, second.adapter.requests[-1].prompt[-800:]
    assert [e["verdict"] for e in second.events("verify.verdict")] == ["NEEDS_HUMAN", "FAIL", "PASS"]
    [spawned] = second.events("fix.spawned")
    assert spawned["consumed"] == ["Q-001"]


def test_a_minor_spec_gap_on_a_pass_becomes_a_fix_unit_before_the_hand_off(run_l4, valid_spec, with_verifier):
    with_verifier(fix_minor_findings=True, max_fix_rounds=1)
    gap = {
        "severity": "minor", "criterion": KNOWN, "title": "Blank code", "detail": "no scenario covers a blank code",
        "evidence": [], "spec_gap": True, "suggested_fix": "WHEN a blank code is given THEN it raises ValueError",
    }  # fmt: skip
    new = regression_id("Blank code")
    run = run_l4([red_step(), green_step(), judge(findings=[gap]), pinning_red(KNOWN, new), judge(new)])
    assert run.code == 0
    assert run.triggers()[-4:] == ["verify_pass", "minor_findings_fix", "fix_unit_done", "verify_pass"]
    assert order(run, "verify.verdict", "fix.spawned", "fix.done") == [
        ("verify.verdict", "PASS"), ("fix.spawned", FIX_UNIT), ("fix.done", FIX_UNIT), ("verify.verdict", "PASS"),
    ]  # fmt: skip
    assert "- **WHEN** a blank code is given\n- **THEN** it raises ValueError" in run.pushed(
        f"{FIX_DIR}/specs/pricing/spec.md"
    )
    assert "Fix unit 1 is created" in run.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verification.md")
    assert "PASS (round 2)" in run.pushed(f"{UNIT_DIR}/verification.md")


def test_the_minors_that_are_left_after_the_last_fix_round_are_listed_not_converted(run_l4, valid_spec, with_verifier):
    with_verifier(fix_minor_findings=True, max_fix_rounds=1)
    gap = {
        "severity": "minor", "criterion": KNOWN, "title": "Blank code", "detail": "d", "evidence": [], "spec_gap": True,
        "suggested_fix": "WHEN a blank code is given THEN it raises ValueError",
    }  # fmt: skip
    new = regression_id("Blank code")
    again = {**gap, "title": "Blank code again", "suggested_fix": "WHEN a code is a space THEN it raises ValueError"}
    run = run_l4(
        [red_step(), green_step(), judge(findings=[gap]), pinning_red(KNOWN, new), judge(new, findings=[again])]
    )
    assert run.code == 0 and len(run.events("fix.spawned")) == 1
    assert "not converted: " in run.pushed(f"{UNIT_DIR}/verification.md")
    assert "fix rounds used 1/1" in run.pushed(f"{UNIT_DIR}/verification.md")


def test_no_rounds_left_escalates_the_unit_with_exit_13(run_l4, valid_spec, with_verifier):
    with_verifier(max_fix_rounds=0)
    run = run_l4([red_step(), noqa_green()])
    assert run.code == 13
    assert run.triggers()[-1] == "verify_fail_exhausted"
    assert run.outcome["units"][0]["phase_after"] == "escalated"
    assert run.events("fix.spawned") == []
    assert "Escalated: fix rounds used 0/0" in run.pushed(f"{UNIT_DIR}/verification.md")
    assert not any("fix unit" in s for s in run.subjects())


def test_a_second_fail_after_the_only_fix_round_escalates(run_l4, valid_spec, with_verifier):
    with_verifier(max_fix_rounds=1)
    still_bad = chore_fix()
    # a second, different deterministic finding: the same one twice would be `same_failure` (D7), not the limit
    still_bad.writes = {"src/pytdd/pricing.py": IMPL + "\nUNUSED = 2  # noqa: E501\nNOSEC = 1  # nosec\n"}
    run = run_l4([red_step(), noqa_green(), still_bad])
    assert run.code == 13
    assert [e["verdict"] for e in run.events("verify.verdict")] == ["FAIL", "FAIL"]
    assert len(run.events("fix.spawned")) == 1
    assert "fix rounds used 1/1" in run.pushed(f"{UNIT_DIR}/verification.md")


def test_a_fix_unit_that_cannot_be_created_escalates_instead_of_re_verifying_forever(
    run_l4, valid_spec, monkeypatch
):
    def broken(self, *args, **kwargs):
        raise FixUnitInvalid("add-discount-codes-fix-1 does not validate --strict: nope")

    monkeypatch.setattr(FamilyProvider, "create_fix_unit", broken)
    run = run_l4([red_step(), noqa_green()])
    assert run.code == 13 and run.triggers()[-1] == "verify_fail_exhausted"
    assert run.events("fix.spawned") == []
    assert run.outcome["units"][0]["phase_after"] == "escalated"


def test_a_pass_stays_a_pass_when_the_optional_minor_fix_unit_cannot_be_created(
    run_l4, valid_spec, with_verifier, monkeypatch
):
    with_verifier(fix_minor_findings=True, max_fix_rounds=1)

    def broken(self, *args, **kwargs):
        raise FixUnitInvalid("add-discount-codes-fix-1 does not validate --strict: nope")

    monkeypatch.setattr(FamilyProvider, "create_fix_unit", broken)
    gap = {
        "severity": "minor", "criterion": KNOWN, "title": "Blank code", "detail": "no scenario covers a blank code",
        "evidence": [], "spec_gap": True, "suggested_fix": "WHEN a blank code is given THEN it raises ValueError",
    }  # fmt: skip
    run = run_l4([red_step(), green_step(), judge(findings=[gap])])
    assert run.code == 0
    assert run.triggers()[-1] == "verify_pass" and run.events("fix.spawned") == []
    assert run.outcome["units"][0]["phase_after"] != "escalated"
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert text.startswith("# Verification: openspec:add-discount-codes: PASS (round 1)")
    assert "Fix unit 1 is created" not in text and "could not be created" in text
    assert "No fix unit." in run.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verification.md")


def test_a_transient_openspec_failure_on_a_fail_is_retryable_and_does_not_escalate(
    run_l4, valid_spec, monkeypatch
):
    def flaky(self, *args, **kwargs):
        raise OpenSpecCommandError("openspec timed out")

    monkeypatch.setattr(FamilyProvider, "create_fix_unit", flaky)
    run = run_l4([red_step(), noqa_green()])
    assert run.code == 1
    assert "verify_fail_exhausted" not in run.triggers() and run.events("fix.spawned") == []


def test_a_fix_unit_committed_without_its_event_is_adopted_and_run_not_planned_again(
    run_l4, valid_spec, monkeypatch
):
    from l4.state.ledger import LedgerWriter

    original = LedgerWriter.append

    def die_once(self, event_type, /, **data):
        if event_type == "fix.spawned" and not data.get("adopted"):
            monkeypatch.setattr(LedgerWriter, "append", original)
            raise RuntimeError("the run died after the fix unit was committed")
        return original(self, event_type, **data)

    monkeypatch.setattr(LedgerWriter, "append", die_once)
    first = run_l4([red_step(), noqa_green()])
    assert first.code != 0 and first.events("fix.spawned") == []
    assert "docs(add-discount-codes): fix unit 1 [skip ci]" in first.subjects()  # the orphan is on the branch
    second = run_l4([chore_fix(), judge()])
    assert second.code == 0, second.adapter.requests[-1].prompt[-600:]
    [spawned] = second.events("fix.spawned")
    assert spawned["fix_unit"] == FIX_UNIT and spawned["adopted"] is True and spawned["round"] == 1
    assert order(second, "fix.spawned", "task.tdd_exempt", "fix.done", "verify.verdict")[-3:] == [
        ("task.tdd_exempt", FIX_UNIT), ("fix.done", FIX_UNIT), ("verify.verdict", "PASS"),
    ]  # fmt: skip
    assert not [e for e in second.ledger() if e["type"] == "fix.spawned" and e["fix_unit"] != FIX_UNIT]


def test_a_chore_task_cannot_rewrite_the_red_tests_that_carry_the_proofs(run_l4, valid_spec):
    weak = (
        HEADER + f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n    assert True\n\n\n'
        f'@pytest.mark.l4("{UNKNOWN}")\ndef test_unknown_code():\n    assert True\n'
    )
    chore = Step(writes={"src/pytdd/pricing.py": IMPL, "tests/test_discount.py": weak}, structured=result("single"))
    run = run_l4([red_step(), noqa_green(), chore, judge()])
    assert run.code == 0
    assert "assert True" not in run.pushed("tests/test_discount.py")
    [tamper] = run.events("guard.test_tamper")
    assert (tamper["path"], tamper["phase"], tamper["fix_unit"]) == ("tests/test_discount.py", "single", FIX_UNIT)


# --- a usage limit in the fix loop ------------------------------------------------------------------------------


def test_a_usage_limit_in_a_fix_task_parks_the_unit_and_the_next_run_resumes_the_fix(run_l4, valid_spec, fake_clock):
    limit = LimitSignal("fake", None, "usage_limit", None, "fake.limit", "")
    first = run_l4([red_step(), noqa_green(), Step(status="quota", limit=limit)])
    assert first.code == 12 and first.events("availability.limit")
    assert [e["to"] for e in first.events("phase.changed")][-2:] == ["fixing", "waiting_capacity"]
    fake_clock.advance(timedelta(hours=1))  # the limited profile cools down (C21: the fix loop falls back through M1.2)
    second = run_l4([chore_fix(), judge()])
    assert second.code == 0
    assert [(e["from"], e["to"]) for e in second.events("phase.changed")][-3:] == [
        ("waiting_capacity", "fixing"), ("fixing", "verifying"), ("verifying", "verified"),
    ]  # fmt: skip
    assert len(second.events("fix.spawned")) == 1  # the same fix unit, not a second one


def test_a_fix_task_whose_run_dies_between_red_and_green_resumes_at_green(
    run_l4, valid_spec, tdd_repo, raw, fake_clock
):
    finding = {
        "severity": "major", "title": "Case of the code", "evidence": [], "spec_gap": True,
        "detail": "a lowercase code is rejected and no scenario says whether it should be",
    }  # fmt: skip
    assert run_l4([red_step(), green_step(), judge(findings=[finding])]).code == 11
    edit_questions_on_origin(
        tdd_repo, raw, status="answered", answer="reject: WHEN a lowercase code is given THEN it is accepted"
    )
    new = regression_id("Case of the code")
    red = Step(
        writes={"tests/test_lower.py": LOWER_TEST.format(cid=new)},
        structured=result("red", criteria_ids=[new], tests_added=["tests/test_lower.py::test_lowercase_code"]),
    )
    limit = LimitSignal("fake", None, "usage_limit", None, "fake.limit", "")
    parked = run_l4([red, Step(status="quota", limit=limit)])
    assert parked.code == 12
    fake_clock.advance(timedelta(hours=1))  # the limited profile cools down (C21)
    green = Step(writes={"src/pytdd/pricing.py": LOWER_IMPL}, structured=result("green"))
    resumed = run_l4([green, judge(new)])
    assert resumed.code == 0, resumed.adapter.requests[-1].prompt[-800:]
    assert [e["fix_unit"] for e in resumed.events("task.red_resumed")] == [FIX_UNIT]
    assert len(resumed.adapter.requests) == 2  # the green step and the judge, no second red


# --- a blocked fix task -------------------------------------------------------------------------------------------


def plan_entry(tdd, raw, capsys) -> dict:
    raw(tdd.repo, "fetch", "-q", "origin")
    capsys.readouterr()
    main(["plan", "--json", "--repo", str(tdd.repo)], environ=tdd.environ)
    return json.loads(capsys.readouterr().out)["units"][0]


def answer_fix_question(tdd, raw) -> None:
    clone = tdd.repo.parent / "human-fix"
    raw(tdd.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd.origin), str(clone))
    path = clone / FIX_DIR / "questions.md"
    file = QuestionsFile.load(path)
    assert file is not None
    file = file.set_status("Q-001", QuestionStatus.ANSWERED)
    body = file.get("Q-001").answer.body
    QuestionsFile.parse(file.data[: body.end] + b"Use the second option.\n" + file.data[body.end :]).save(path)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "answer the fix unit's question")
    raw(clone, "push", "-q", "origin", BRANCH)


def test_a_blocked_fix_task_asks_in_the_fix_units_questions_and_resumes_after_the_answer(
    run_l4, valid_spec, tdd_repo, raw, capsys
):
    blocked = chore_fix(
        status="blocked",
        questions=[{"title": "Which flag?", "context": "two ways", "kind": "technical", "options": ["a", "b"]}],
    )
    first = run_l4([red_step(), noqa_green(), blocked])
    assert first.code == 11
    assert first.outcome["units"][0]["phase_after"] == "fixing"
    assert "Which flag?" in first.pushed(f"{FIX_DIR}/questions.md")
    assert (
        "Which flag?" not in first.pushed(f"{UNIT_DIR}/questions.md")
        if "questions.md" in first.raw(first.tdd.origin, "ls-tree", "--name-only", BRANCH, f"{UNIT_DIR}/")
        else True
    )
    [raised] = first.events("question.raised")
    assert (raised["id"], raised["fix_unit"]) == ("Q-001", FIX_UNIT)
    waiting = plan_entry(tdd_repo, raw, capsys)
    assert waiting["next_action"] == "none" and waiting["reason"] == "fixing: fix unit questions open: Q-001"
    answer_fix_question(tdd_repo, raw)
    ready = plan_entry(tdd_repo, raw, capsys)
    assert ready["next_action"] == "implement" and ready["reason"] == f"fix unit {FIX_UNIT}: 0/1 tasks"
    second = run_l4([chore_fix(), judge()])
    assert second.code == 0
    answered = [e for e in second.events("question.answered") if e.get("fix_unit") == FIX_UNIT]
    assert [(e["id"], e["by"]) for e in answered] == [("Q-001", "human")]
    assert "Use the second option." in second.adapter.requests[0].prompt
    assert order(second, "fix.done", "verify.verdict")[-2:] == [("fix.done", FIX_UNIT), ("verify.verdict", "PASS")]


# --- `l4 verify` has no fix hook ---------------------------------------------------------------------------------


def test_l4_verify_on_a_fail_stops_at_fixing_with_exit_10(run_verify, valid_spec, monkeypatch):
    monkeypatch.setitem(services.HOOKS, "verify", "l4_test_no_verifier:verify_hook")
    run_verify([red_step(), noqa_green()], via="run")  # stops at `implemented`
    monkeypatch.setitem(services.HOOKS, "verify", "l4.verifier.ladder:verify_hook")
    verified = run_verify([], via="verify")
    assert verified.code == 10
    unit = verified.outcome["units"][0]
    assert (unit["phase_before"], unit["phase_after"], unit["verdict"]) == ("implemented", "fixing", "FAIL")
    assert len(verified.events("fix.spawned")) == 1 and verified.events("fix.done") == []


def test_an_escalation_names_its_cause_in_the_outcome(run_l4, valid_spec, with_verifier):
    with_verifier(max_fix_rounds=0)
    run = run_l4([red_step(), noqa_green()])
    assert run.code == 13
    assert "escalated" in run.outcome["units"][0]["exit_reason"]
