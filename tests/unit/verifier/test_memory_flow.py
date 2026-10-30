"""SCN-MEM-01 end to end (memory-lessons 3.13, plan line 36): a UI unit's deterministic finding is closed by an accepted
generated test, the PASS round curates it into `lessons.md` in its own `chore(memory)` commit before the hand-off, and
the lesson is what a later UI task is given."""

from l4.config.loader import load_config
from l4.memory.inject import inject_for_task
from l4.vcs.names import UnitNames

from ..conftest import UNIT
from ..implementer.conftest import KNOWN, UNKNOWN, red_step
from ..orchestrator.conftest import BRANCH, UNIT_DIR
from .test_ui_flow import JUDGE, ui_test, web_green, web_repo  # noqa: F401

LESSONS = ".serena/memories/harness/lessons.md"


def script():
    return [
        red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), ui_test(UNKNOWN, "SAVE10", "code"),
        JUDGE,
    ]  # fmt: skip


def test_finding_becomes_lesson_and_is_injected_later(run_l4, valid_spec, web_repo, tdd_repo):  # noqa: F811
    run = run_l4(script(), **web_repo)
    assert run.code == 0, run.outcome
    subjects = run.subjects()
    shas = run.raw(run.tdd.origin, "log", "--format=%H", f"main..{BRANCH}").split()[::-1]
    tests = subjects.index("test(add-discount-codes): verifier round 1 [skip ci]")
    docs = subjects.index("docs(add-discount-codes): verification round 1 [skip ci]")
    memory = next(i for i, s in enumerate(subjects) if s.startswith("chore(memory):"))
    assert tests < docs < memory and subjects[memory].endswith("[skip ci]")
    phase = run.raw(run.tdd.origin, "log", "-1", "--format=%(trailers:key=L4-Phase,valueonly)", shas[memory])
    assert phase.strip() == "lessons"
    assert run.raw(run.tdd.origin, "show", "--name-only", "--format=", shas[memory]).split() == [LESSONS]
    assert "ui-criterion-without-e2e-test" in run.pushed(LESSONS)
    [curated] = run.events("lessons.curated")
    assert curated["action"] == "created" and curated["origin"] == "verifier_finding_fixed"
    # a later task that touches the UI is given it
    worktree = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=tdd_repo.cache, repo_key=tdd_repo.key).worktree
    injection = inject_for_task(worktree, load_config(worktree).memory, ["app.py"])
    assert injection.ids == (curated["id"],) and "end-to-end" in injection.block


def test_nothing_is_curated_when_the_final_pass_was_not_reached(run_l4, valid_spec, web_repo):  # noqa: F811
    from l4.agents.fake import Step

    refuse = Step(structured={"criterion": UNKNOWN, "not_testable": "not now"})
    run = run_l4([red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), refuse, JUDGE], **web_repo)
    assert run.code == 11
    assert not any(s.startswith("chore(memory)") for s in run.subjects()) and run.events("lessons.curated") == []


def test_the_round_that_closes_the_gap_is_the_one_that_curates(run_l4, valid_spec, web_repo, tdd_repo, raw):  # noqa: F811
    from l4.agents.fake import Step

    from ..orchestrator.conftest import edit_questions_on_origin

    refuse = Step(structured={"criterion": UNKNOWN, "not_testable": "not now"})
    first = run_l4([red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), refuse, JUDGE], **web_repo)
    assert first.code == 11
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: a unit test covers it")
    clone = tdd_repo.repo.parent / "human-answered"
    (clone / "app.py").write_text((clone / "app.py").read_text() + "\n# touched\n")
    # the accept is bound to the criterion's tracing tests (L4-VER-067): a change of one ends the waiver, so the next
    # round asks the writer again, and the round that closes the gap curates
    tracing = clone / "tests" / "test_discount.py"
    tracing.write_text(tracing.read_text() + "\n# touched\n")
    raw(clone, "commit", "-q", "-am", "touch the app and the tracing test")
    raw(clone, "push", "-q", "origin", BRANCH)
    second = run_l4([ui_test(UNKNOWN, "SAVE10", "code"), JUDGE], **web_repo)
    assert second.code == 0
    assert [e["action"] for e in second.events("lessons.curated")] == ["created"]


def test_a_second_unit_branched_after_the_first_merged_gets_the_lesson_in_its_red_prompt(
    run_l4, valid_spec, web_repo, tdd_repo, raw  # noqa: F811
):
    """Exit C, unit 2: run 1 curates the lesson, a human merges the unit branch, and unit 2 (a task that names `app.py`)
    is given the lesson in the red prompt, with `lessons.injected` in its ledger before the agent runs."""
    import json
    import shutil

    first = run_l4(script(), **web_repo)
    assert first.code == 0, first.outcome
    [curated] = first.events("lessons.curated")
    raw(tdd_repo.repo, "merge", "-q", "--no-edit", f"origin/{BRANCH}")
    second = "add-shipping"
    source, target = tdd_repo.repo / UNIT_DIR, tdd_repo.repo / "openspec" / "changes" / second
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".l4", "questions.md"))
    tasks = target / "tasks.md"
    tasks.write_text("## 1. Shipping\n\n- [ ] 1.1 Show the shipping line in `app.py`\n")
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "a second unit")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    names = UnitNames.for_unit(f"openspec:{second}", branch_prefix="l4/", cache=tdd_repo.cache, repo_key=tdd_repo.key)
    run = run_l4([red_step()], **web_repo, unit=False)
    assert run.adapter.requests, run.outcome
    block = f'<l4:data kind="lessons" ids="{curated["id"]}">'
    assert block in run.adapter.requests[0].prompt
    ledger = names.worktree / "openspec" / "changes" / second / ".l4" / "ledger"
    types = [json.loads(line)["type"] for path in ledger.glob("*.jsonl") for line in path.read_text().splitlines()]
    assert types.index("lessons.injected") < types.index("step.started")
