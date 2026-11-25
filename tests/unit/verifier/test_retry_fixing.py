"""`l4 retry` of a unit in `fixing` whose open fix unit waits on a person (L4-VER-095, design D6, SCN-VER-389..392).

Task 5.1, read in the code before anything was changed (file:line are of the branch before this change):

(a) Can `Orchestrator.resume` record `unit.retried` for a unit in `fixing`? NOT AS IT WAS. `resume` appends the event
    (`src/l4/orchestrator.py:707`) and then takes an edge with `self._go(trigger)` (`:723`). `retry_unit` passes
    `Trigger.RESUMED` for every phase that has no edge of its own (`src/l4/state/retry.py:25`), and `TRANSITIONS` has no
    `FIXING` source for `RESUMED` (`src/l4/state/lifecycle.py:122-144`; `RESUMED` is for `halted` and `escalated`,
    `:134`): the event would be written and `IllegalTransition` raised after it. Before that, `refuse` lists `fixing` in
    `_CONTINUES` (`retry.py:61-62`) and says `the harness continues it at the next run`. What this change does: `refuse`
    accepts `fixing` when the open fix unit waits on a person; `resume` takes a `close_fix_unit` and then takes NO edge
    (the unit stays `fixing` until the run's `fix_unit_done`); `_take_pending_spec_edit` is already a no-op in `fixing`
    (`orchestrator.py:766`).
(b) Does `question.superseded` take a fix unit's technical question out of `questions.open`? YES, when the event carries
    `fix_unit`: `_question_superseded` (`src/l4/state/fold.py:272-280`) prefixes each id with the event's `fix_unit` and
    removes `<fix unit>/Q-001`, the key `question.raised{fix_unit}` added (`_question_id`, `:243-247`). The round-based
    supersede (`verifiers/verdicts.py:981`) carries none because verdict questions are the parent's. Pinned in
    `tests/unit/state/test_fold_fix_units.py`. The mirror drops `l4:needs-answers` through the same fold
    (`answers_recorded`, `orchestrator.py:670`).
(c) Not in the task: after the retry the planner still said `fixing: fix unit questions open` (`planner.py:196-199`),
    which is `none`, so a run that selects units by the plan would never reach `fix_hook`. The planner now reads the
    pending close (`UnitState.close_fix_unit`) and says `implement`.

SCN-VER-389 here asserts the close, the supersede, `fix.done`, `verifying`, a fresh round and no `-fix-3`; the hold that
the new round raises (L4-VER-092) is asserted by the last test of this file, which runs both streams together.
"""

import json

import pytest

from l4 import services
from l4.cli import main
from l4.specs.questions import QuestionsFile, QuestionStatus

from ..conftest import UNIT
from ..implementer.conftest import KNOWN, UNKNOWN, green_step, red_step
from ..orchestrator.conftest import BRANCH, UNIT_DIR, new_origin_main
from .test_ladder_fix import FIX_DIR, FIX_UNIT, chore_fix, judge, noqa_green, plan_entry

REASON = "the skipped tests are env-gated, see the hold"
QUESTION = [{"title": "Which flag?", "context": "two ways", "kind": "technical", "options": ["a", "b"]}]


@pytest.fixture(autouse=True)
def no_fix_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Overrides the verifier suite's switch: these tests are about the fix loop."""
    monkeypatch.setitem(services.HOOKS, "fix", "l4.verifier.fixloop:fix_hook")


def blocked():
    return chore_fix(status="blocked", questions=QUESTION)


def retry(tdd_repo, *flags: str) -> int:
    argv = ["retry", "--unit", UNIT, "--reason", REASON, "--no-run", *flags, "--repo", str(tdd_repo.repo)]
    return main(argv, environ=tdd_repo.environ)


@pytest.fixture
def waiting(run_l4, valid_spec):
    """Round 1 failed, fix unit 1 was written and its one task asked a question: the unit is `fixing` and waits."""
    first = run_l4([red_step(), noqa_green(), blocked()])
    assert first.code == 11 and first.outcome["units"][0]["phase_after"] == "fixing"
    return first


def fold_of(run):
    from datetime import datetime

    from l4.state.fold import fold
    from l4.state.ledger import LedgerEvent

    rows = [
        LedgerEvent(
            datetime.fromisoformat(e["ts"]), e["run_id"], UNIT, e["seq"], e["type"],
            {k: v for k, v in e.items() if k not in {"ts", "run_id", "seq", "type", "unit"}},
        )
        for e in run.ledger()
    ]  # fmt: skip
    return fold(rows, UNIT)


# --- SCN-VER-389, SCN-VER-390 ------------------------------------------------------------------------------------


def test_a_retry_is_accepted_and_records_the_fix_unit_to_close_and_no_phase_edge(waiting, tdd_repo, raw, capsys):
    phases = len(waiting.events("phase.changed"))
    assert retry(tdd_repo) == 0
    [retried] = waiting.events("unit.retried")
    assert retried["close_fix_unit"] == FIX_UNIT and retried["reason"] == REASON
    assert len(waiting.events("phase.changed")) == phases  # 5.1(a): no edge, the unit is still `fixing`
    assert fold_of(waiting).phase == "fixing" and fold_of(waiting).close_fix_unit == FIX_UNIT
    assert waiting.subjects()[-1].startswith("chore(add-discount-codes): retry")
    capsys.readouterr()
    assert main(["questions", "--unit", UNIT, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 0
    assert "Q-001" in capsys.readouterr().out  # still asked until the run closes the fix unit (the control of 390)
    entry = plan_entry(tdd_repo, raw, capsys)  # 5.1(c): the plan lets the run in
    assert entry["next_action"] == "implement" and entry["actionable"] is True
    assert FIX_UNIT in entry["reason"] and "closed by the retry" in entry["reason"]


def test_the_run_after_the_retry_closes_the_fix_unit_in_harness_commits_and_verifies_a_fresh_round(
    waiting, run_l4, tdd_repo, raw, capsys
):
    """SCN-VER-389 and SCN-VER-390. The unit's round 1 failed on a suppression the fix task never removed, so the fresh
    round fails again here (a suppression is a finding, not a hold): it spawns fix unit 2, and the retry never reaches
    fix unit 3 on its own."""
    assert retry(tdd_repo) == 0
    second = run_l4([chore_fix(), judge()])
    assert second.code == 0, second.adapter.requests[-1].prompt[-800:]
    [done] = [e for e in second.events("task.done") if e.get("closed_by")]
    closed = (done["fix_unit"], done["task"], done["tdd"], done["closed_by"])
    assert closed == (FIX_UNIT, "1.1", "already-done", "retry")
    assert REASON in done["reason"] and done["reason"].startswith("closed by l4 retry: ")
    tasks = second.pushed(f"{FIX_DIR}/tasks.md")
    assert "- [x] 1.1" in tasks and "- [ ] 1.1" not in tasks
    question = QuestionsFile.parse(second.pushed(f"{FIX_DIR}/questions.md"))
    one = question.get("Q-001")
    assert one is not None and one.status is QuestionStatus.SUPERSEDED and one.retried and "Which flag?" in one.title
    [gone] = second.events("question.superseded")
    assert (gone["fix_unit"], gone["ids"]) == (FIX_UNIT, ["Q-001"])
    # the order: tick, supersede, fix.done, then the parent verifies again
    kinds = [e["type"] for e in second.ledger() if e["type"] in {"unit.retried", "task.done", "question.superseded",
                                                                   "fix.done", "verify.verdict"}]  # fmt: skip
    assert kinds[kinds.index("unit.retried") :][:6] == [
        "unit.retried", "question.superseded", "task.done", "fix.done", "verify.verdict", "task.done"
    ]  # fmt: skip
    # F9: `question.superseded` is written before the commit of the task it releases, so it travels inside that commit;
    # `task.done` names the commit's sha and follows it. A run that ends between them leaves the ledger and the
    # question's Status agreeing (the question is out of `questions.open`), and the commit with no event is no blocker
    log = raw(tdd_repo.origin, "log", "--format=%H %s", f"main..{BRANCH}").splitlines()
    [closing] = [line.split()[0] for line in log if line.endswith("already done [skip ci]")]
    shown = raw(tdd_repo.origin, "show", "--format=", closing)
    assert "question.superseded" in shown and "task.done" not in shown and "superseded by retry" in shown
    closing = [e["fix_unit"] for e in second.events("fix.done")]
    assert closing == [FIX_UNIT, f"{FIX_UNIT[:-1]}2"]  # fix unit 1 by the close, fix unit 2 by its own task
    assert second.triggers()[-4:] == ["fix_unit_done", "verify_fail_fix", "fix_unit_done", "verify_pass"]
    verdicts = [(e["round"], e["verdict"]) for e in second.events("verify.verdict")]
    assert verdicts == [(1, "FAIL"), (2, "FAIL"), (3, "PASS")]  # a fresh round, the failed one not reused
    spawned = [(e["fix_unit"], e["round"]) for e in second.events("fix.spawned")]
    assert spawned == [(FIX_UNIT, 1), (f"{FIX_UNIT[:-1]}2", 2)]  # the closed fix round stays counted; no `-fix-3`
    state = fold_of(second)
    assert state.fix_rounds_counted == 2 and state.close_fix_unit is None and state.questions.open == []
    subjects = second.subjects()
    assert any(s.startswith(f"fix({FIX_UNIT}): ") and s.endswith("already done [skip ci]") for s in subjects)
    trailers = raw(tdd_repo.origin, "log", "--format=%B", BRANCH)
    assert "L4-TDD: already-done" in trailers and "L4-Task: 1.1" in trailers
    assert "L4-Unit: openspec:" + FIX_UNIT in trailers  # as `_already_done` writes it, by the fix unit's workbench
    listed = main(["questions", "--unit", UNIT, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)
    out = capsys.readouterr().out
    assert listed == 0 and "Q-001" not in out  # nothing is open: SCN-VER-390


def test_the_close_keeps_the_questions_text_and_the_fix_units_marker(waiting, run_l4, tdd_repo):
    assert retry(tdd_repo) == 0
    second = run_l4([chore_fix(), judge()])
    text = second.pushed(f"{FIX_DIR}/questions.md")
    assert "Which flag?" in text and "- **Status:** superseded by retry" in text
    assert second.pushed(f"{FIX_DIR}/.l4/fix.json")  # the marker is untouched


def test_a_close_writes_no_source_file(waiting, run_l4, tdd_repo):
    before = waiting.raw(tdd_repo.origin, "ls-tree", "-r", "--name-only", BRANCH, "src/")
    assert retry(tdd_repo) == 0
    second = run_l4([chore_fix(), judge()])
    assert second.raw(tdd_repo.origin, "ls-tree", "-r", "--name-only", BRANCH, "src/") == before


# --- SCN-VER-391 ----------------------------------------------------------------------------------------------------


def test_a_fix_unit_with_a_task_that_can_run_is_not_closed(waiting, tdd_repo, raw, capsys):
    from .test_ladder_fix import answer_fix_question

    answer_fix_question(tdd_repo, raw)  # the question is answered: the task can run
    head = raw(tdd_repo.origin, "rev-parse", BRANCH)
    kinds = [e["type"] for e in waiting.ledger()]
    code = retry(tdd_repo)
    err = capsys.readouterr().err
    assert code == 2
    assert f"the fix unit {FIX_UNIT} is running: the harness continues it at the next run" in err
    assert raw(tdd_repo.origin, "rev-parse", BRANCH) == head and [e["type"] for e in waiting.ledger()] == kinds


def test_a_question_that_cannot_be_read_does_not_open_the_close(waiting, tdd_repo, raw, capsys):
    clone = tdd_repo.repo.parent / "human-break"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    path = clone / FIX_DIR / "questions.md"
    path.write_text(path.read_text().replace("- **Blocking tasks:** 1.1", "- **Blocking tasks:** see the design"))
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "break the line")
    raw(clone, "push", "-q", "origin", BRANCH)
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    assert retry(tdd_repo) == 2
    assert f"the fix unit {FIX_UNIT} is running" in capsys.readouterr().err


# --- the run finds the close no longer safe -------------------------------------------------------------------------


def test_an_answer_that_arrives_between_the_retry_and_the_run_makes_the_task_run_and_the_close_is_dropped(
    waiting, run_l4, tdd_repo, raw
):
    from .test_ladder_fix import answer_fix_question

    assert retry(tdd_repo) == 0
    answer_fix_question(tdd_repo, raw)
    second = run_l4([chore_fix(), judge()])
    assert second.code == 0, second.adapter.requests[-1].prompt[-800:]
    [skipped] = second.events("fix.close_skipped")
    assert skipped["fix_unit"] == FIX_UNIT and "can run" in skipped["reason"]
    assert [e for e in second.events("task.done") if e.get("closed_by")] == []  # the task ran as it always does
    assert "superseded by retry" not in second.pushed(f"{FIX_DIR}/questions.md")
    assert fold_of(second).close_fix_unit is None


def test_the_pending_close_is_in_the_folded_state_that_status_prints(waiting, tdd_repo):
    assert retry(tdd_repo) == 0
    dumped = json.loads(fold_of(waiting).model_dump_json())
    assert dumped["close_fix_unit"] == FIX_UNIT


# --- the two streams together: the old finding, the retry, the hold (SCN-VER-389, last part) ------------------------

OLD_TITLE = "existing tests are skipped in a changed test file"
STACK_TESTS = (
    "import os\n\nimport pytest\n\nfrom pytdd import total\n\n\n"
    '@pytest.mark.skipif(os.getenv("PYTDD_STACK") != "true", reason="needs the stack")\n'
    "def test_total_adds_prices():\n    assert total([1.25, 2.5]) == 3.75\n\n\n"
    "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n"
)
NEW_TESTS = (
    f'\n\n@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n    from pytdd.pricing import apply_discount\n\n'
    '    assert apply_discount(50.0, "SAVE10") == 45.0\n\n\n'
    f'@pytest.mark.l4("{UNKNOWN}")\ndef test_unknown_code():\n    from pytdd.pricing import apply_discount\n\n'
    '    with pytest.raises(ValueError):\n        apply_discount(50.0, "NOPE")\n'
)


STACK_ID = "tests.test_pricing::test_total_adds_prices"


def _round_one_on_the_old_harness(run_l4, tdd_repo, raw, monkeypatch):
    """Round 1 as the harness before this change ran it: no skip predates the unit (the rule is off), and step 1's
    record carries no `skipped` key, so that nothing the earlier rounds wrote can say what the base skipped."""
    from l4.evidence import collect
    from l4.verifier import base_tests

    new_origin_main(tdd_repo, raw, {"tests/test_pricing.py": STACK_TESTS})
    real_rule = collect.skip_predating
    monkeypatch.setattr(collect, "skip_predating", lambda *a, **k: collect.Predating())
    real = base_tests.check_base_tests

    def older(*args, **kwargs):
        out = real(*args, **kwargs)
        if out.base_tests is not None:
            out.base_tests.pop("skipped", None)  # an older harness wrote `passed` only
        out.base_report = None
        return out

    monkeypatch.setattr(base_tests, "check_base_tests", older)
    red = red_step()  # the unit adds its tests to the file that holds the stack-gated one and leaves that one alone
    red.writes = {
        "tests/test_pricing.py": STACK_TESTS + NEW_TESTS,
        "src/pytdd/pricing.py": red.writes["src/pytdd/pricing.py"],
    }
    red.structured = {**red.structured, "tests_added": ["tests/test_pricing.py::test_known_code"]}
    first = run_l4([red, green_step(), judge(), blocked()])
    assert first.code == 11 and first.outcome["units"][0]["phase_after"] == "fixing", first.outcome
    [verdict] = first.events("verify.verdict")
    assert verdict["verdict"] == "FAIL"
    tasks = first.pushed(f"{FIX_DIR}/tasks.md")
    assert OLD_TITLE in tasks and "- [ ] 1.1" in tasks  # the fix unit's only task is the old finding
    record = json.loads(first.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verdict.json"))["integrity"]["base_tests"]
    assert "skipped" not in record and record["passed"]  # an older harness's record
    monkeypatch.setattr(base_tests, "check_base_tests", real)  # the release
    monkeypatch.setattr(collect, "skip_predating", real_rule)
    return first


def _base_gate_counting(monkeypatch, report):
    """Counts the runs of the test gate in a base worktree (`run_gate_at`) and answers each with `report` (None: the
    gate gave no report)."""
    from types import SimpleNamespace

    from l4.verifier import base_tests

    runs: list[str] = []

    def fake(wb, tree, spec, network):
        runs.append(spec.name)
        return SimpleNamespace(report=report, reason="FAKE: the base's gate gave no report")

    monkeypatch.setattr(base_tests, "run_gate_at", fake)
    return runs


def test_a_fixing_unit_for_the_old_finding_is_retried_and_the_fresh_round_has_the_hold_not_the_major(
    run_l4, valid_spec, tdd_repo, raw, monkeypatch, capsys
):
    """The consumer's case, in the shape it really has. A stack-gated test of a file the unit edits is skipped before
    the unit and after it. Round 1 runs as the old harness did: no skip is judged to predate the unit and the record of
    step 1 has no `skipped` key. The fix unit's one task asks a question; the person upgrades (here: the rule is back
    on) and retries. The fresh round has no earlier record of the base's statuses, so it gets them from one run of the
    test gate in a base worktree, holds the test as skipped there, and raises one `skipped` hold: no major, no second
    fix unit."""
    from l4.gates.junit import TestCase, TestReport

    first = _round_one_on_the_old_harness(run_l4, tdd_repo, raw, monkeypatch)
    assert first.events("fix.spawned")
    base_run = TestReport(
        {
            STACK_ID: TestCase(STACK_ID, "skipped"),
            "tests.test_pricing::test_total_of_nothing_is_zero": TestCase(
                "tests.test_pricing::test_total_of_nothing_is_zero", "passed"
            ),
        }
    )
    runs = _base_gate_counting(monkeypatch, base_run)
    assert retry(tdd_repo) == 0
    second = run_l4([judge()])
    assert second.code == 11, second.adapter.requests[-1].prompt[-800:]
    assert runs == ["base-tests-base"]  # one run of the base's gate in the whole round, for step 3's lookup
    [done] = [e for e in second.events("task.done") if e.get("closed_by")]
    assert (done["fix_unit"], done["task"], done["closed_by"]) == (FIX_UNIT, "1.1", "retry")
    verdicts = [(e["round"], e["verdict"]) for e in second.events("verify.verdict")]
    assert verdicts == [(1, "FAIL"), (2, "NEEDS_HUMAN")]  # a fresh round, and the hold is not a failure
    [spawned] = second.events("fix.spawned")  # the one fix unit of round 1: no `-fix-2`, no `-fix-3`
    assert spawned["fix_unit"] == FIX_UNIT
    evidence = json.loads(second.pushed(f"{UNIT_DIR}/.l4/evidence/round-2/verdict.json"))["evidence"]
    assert [h["kind"] for h in evidence["holds"]] == ["skipped"]
    assert "tests/test_pricing.py" in evidence["holds"][0]["text"]
    assert evidence["tests_ran"]["summary"]["skipped_predating"] == [STACK_ID]
    assert evidence["tests_ran"]["summary"]["skipped_source"] == "a base worktree run"
    assert OLD_TITLE not in json.dumps(evidence["tests_ran"]["findings"])  # the major is gone
    report = second.pushed(f"{UNIT_DIR}/verification.md")
    assert OLD_TITLE not in report and "skipped" in report and "a base worktree run" in report
    asked = [e for e in second.events("question.raised") if e.get("kind") == "verdict"]
    assert len(asked) == 1 and fold_of(second).phase == "awaiting_human"
    question = QuestionsFile.parse(second.pushed(f"{UNIT_DIR}/questions.md"))
    assert "(a base worktree run)" in " ".join(question.questions[-1].context_text.split())


def test_the_fresh_round_keeps_the_major_when_the_base_worktree_run_gives_no_report(
    run_l4, valid_spec, tdd_repo, raw, monkeypatch, capsys
):
    """The same unit when the base's gate cannot give a report: fail closed. The round has the major, no hold, and says
    why; the one run of the base's gate is not repeated."""
    first = _round_one_on_the_old_harness(run_l4, tdd_repo, raw, monkeypatch)
    assert first.events("fix.spawned")
    runs = _base_gate_counting(monkeypatch, None)
    assert retry(tdd_repo) == 0
    second = run_l4([judge(), blocked()])
    assert runs == ["base-tests-base"]
    verdicts = [(e["round"], e["verdict"]) for e in second.events("verify.verdict")]
    assert verdicts[:2] == [(1, "FAIL"), (2, "FAIL")]
    evidence = json.loads(second.pushed(f"{UNIT_DIR}/.l4/evidence/round-2/verdict.json"))["evidence"]
    assert evidence["holds"] == [] and evidence["tests_ran"]["summary"]["skipped_predating"] == []
    assert OLD_TITLE in json.dumps(evidence["tests_ran"]["findings"])  # the major stays
    note = evidence["tests_ran"]["summary"]["skipped_note"]
    assert note.startswith("no base report with statuses: the base's test gate gave no report")
