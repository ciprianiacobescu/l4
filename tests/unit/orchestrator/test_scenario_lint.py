from l4.agents.base import ProbeResult
from l4.agents.fake import Step

from ..implementer.conftest import HEADER, KNOWN, KNOWN_TEST, green_step, red_step
from .conftest import BRANCH, UNIT_DIR, new_origin_main

SPEC = f"{UNIT_DIR}/specs/pricing/spec.md"
CONFLICT = (
    "## ADDED Requirements\n\n### Requirement: Discount codes\nSAVE10 is a known code.\n\n"
    '#### Scenario: Known code\n- **WHEN** `apply_discount(50.0, "SAVE10")` is called\n- **THEN** it returns `45.0`\n\n'
    '#### Scenario: Known code, other rule\n- **WHEN** `apply_discount(50.0, "SAVE10")` is called\n'
    "- **THEN** it returns `50.0`\n"
)
SUBJECT = "docs(add-discount-codes): questions [skip ci]"


def test_a_conflicting_pair_raises_a_question_and_no_agent_step_runs(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {SPEC: CONFLICT})
    run = run_l4([red_step(), green_step()])
    assert run.code == 11 and run.outcome["units"][0]["phase_after"] == "awaiting_human"
    assert run.adapter.requests == []  # no agent was asked anything
    assert run.events("task.started") == [] and run.events("agent.session") == []
    assert [e["selected"] for e in run.events("availability.selected")] == ["impl"]  # the probe at `ready` still ran
    assert [(e["id"], e["source"]) for e in run.events("question.raised")] == [("Q-001", "intake_lint")]
    questions = run.pushed(f"{UNIT_DIR}/questions.md")
    assert "- **Kind:** ambiguous" in questions and "- **Asked:** intake lint (L4-ODD-004)" in questions
    assert "- **Blocking tasks:** 1.1" in questions
    assert "it returns `45.0`" in questions and "it returns `50.0`" in questions
    assert run.subjects().count(SUBJECT) == 1
    assert run.triggers()[-1] == "questions_blocking"


def test_the_pair_is_not_raised_again_on_the_next_run(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {SPEC: CONFLICT})
    run_l4([])
    again = run_l4([red_step(), green_step()])
    assert again.code == 11 and again.adapter.requests == []
    assert [e["id"] for e in again.events("question.raised")] == ["Q-001"]
    assert again.subjects().count(SUBJECT) == 1


def test_a_clean_change_raises_nothing_and_goes_on_to_the_agent(run_l4):
    run = run_l4([red_step(), green_step()])
    assert run.code == 0 and run.events("question.raised") == []
    assert SUBJECT not in run.subjects()


def test_a_conflict_with_a_base_spec_is_found_too(run_l4, tdd_repo, raw):
    base = (
        "# pricing\n\n## Requirements\n\n### Requirement: Old rule\nText.\n\n"
        '#### Scenario: Old\n- **WHEN** `apply_discount(50.0, "SAVE10")` is called\n- **THEN** it returns `40.0`\n'
    )
    base_path = tdd_repo.repo / "openspec" / "specs" / "pricing"
    base_path.mkdir(parents=True)
    new_origin_main(tdd_repo, raw, {"openspec/specs/pricing/spec.md": base})
    run = run_l4([Step()])
    assert run.code == 11 and run.adapter.requests == []
    assert "openspec/specs/pricing/spec.md" in run.pushed(f"{UNIT_DIR}/questions.md")


def test_a_unit_parked_after_the_lint_gets_no_branch_and_raises_the_pair_again(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {SPEC: CONFLICT})
    first = run_l4([red_step()], probes={"auth": ProbeResult("auth", False, reason="logged out")})
    assert first.code == 12 and first.adapter.requests == []
    assert raw(tdd_repo.origin, "for-each-ref", "--format=%(refname)").split() == ["refs/heads/main"]
    # the capacity is back: the questions are raised again and now the unit is pushed with them
    second = run_l4([red_step()])
    assert second.code == 11 and "Q-001" in second.pushed(f"{UNIT_DIR}/questions.md")
    assert second.subjects().count(SUBJECT) == 1


def test_a_removed_base_requirement_does_not_conflict_with_its_replacement(run_l4, tdd_repo, raw):
    base = (
        "# pricing\n\n## Requirements\n\n### Requirement: Old rule\nText.\n\n"
        '#### Scenario: Old\n- **WHEN** `apply_discount(50.0, "SAVE10")` is called\n- **THEN** it returns `40.0`\n'
    )
    (tdd_repo.repo / "openspec" / "specs" / "pricing").mkdir(parents=True)
    delta = (
        "## REMOVED Requirements\n\n### Requirement: Old rule\n**Reason**: replaced.\n\n"
        "## ADDED Requirements\n\n### Requirement: Discount codes\nSAVE10 is a known code.\n\n"
        '#### Scenario: Known code\n- **WHEN** `apply_discount(50.0, "SAVE10")` is called\n'
        "- **THEN** it returns `45.0`\n"
    )
    new_origin_main(tdd_repo, raw, {"openspec/specs/pricing/spec.md": base, SPEC: delta})
    known_only = red_step()  # the delta above leaves only the "Known code" scenario
    known_only.writes = {**known_only.writes, "tests/test_discount.py": HEADER + KNOWN_TEST}  # type: ignore[misc]
    known_only.structured["criteria_ids"] = [KNOWN]  # type: ignore[index]
    run = run_l4([known_only, green_step()])
    assert run.code == 0 and run.events("question.raised") == []


def test_a_spec_push_to_a_unit_past_implementation_re_enters_it_and_the_lint_reads_the_new_spec(run_l4, tdd_repo, raw):
    ok = run_l4([red_step(), green_step()])
    assert ok.code == 0 and ok.outcome["units"][0]["phase_after"] == "implemented"  # no verifier: it stops there
    # a human reopens a task and breaks the spec on the unit branch. Since L4-OPS-014 that is a spec edit: the unit goes
    # back to `implementing`, a phase the lint covers, so the conflict is raised before any agent step.
    clone = tdd_repo.repo.parent / "human-spec"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    (clone / SPEC).write_text(CONFLICT)
    tasks = clone / UNIT_DIR / "tasks.md"
    tasks.write_text(tasks.read_text().replace("[x]", "[ ]"))
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "reopen")
    raw(clone, "push", "-q", "origin", BRANCH)
    again = run_l4([Step()])
    assert again.outcome["units"][0]["phase_before"] == "implemented"
    assert "spec_edited" in again.triggers() and again.events("unit.retried")[-1]["reason"] == "spec edited"
    assert again.events("question.raised") and SUBJECT in again.subjects()


DESIGN = f"{UNIT_DIR}/design.md"
OPEN_QUESTIONS = (
    "# Design\n\n## Open questions\n\n"
    "- (technical) Should `is_empty` be a method or a property? Follow the existing conventions of `Cart`.\n"
    "- (product) Is a cart of free items empty?\n- Unlabelled item\n"
)


def test_open_questions_in_design_md_are_raised_at_intake_and_no_agent_step_runs(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {DESIGN: OPEN_QUESTIONS})
    run = run_l4([red_step(), green_step()])
    assert run.code == 11 and run.adapter.requests == []
    assert run.events("task.started") == [] and run.events("agent.session") == []
    raised = run.events("question.raised")
    assert [(e["id"], e["kind"], e["source"]) for e in raised] == [
        ("Q-001", "technical", "intake_open_questions"),
        ("Q-002", "product", "intake_open_questions"),
        ("Q-003", "ambiguous", "intake_open_questions"),
    ]
    questions = run.pushed(f"{UNIT_DIR}/questions.md")
    assert "- **Asked:** intake (open questions in design.md)" in questions
    assert "- **Blocking tasks:** 1.1" in questions and "Should `is_empty` be a method or a property?" in questions
    assert run.subjects().count(SUBJECT) == 1


def test_open_questions_are_not_raised_again_on_the_next_run(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {DESIGN: OPEN_QUESTIONS})
    run_l4([])
    again = run_l4([red_step(), green_step()])
    assert again.code == 11 and again.adapter.requests == []
    assert [e["id"] for e in again.events("question.raised")] == ["Q-001", "Q-002", "Q-003"]
    assert again.subjects().count(SUBJECT) == 1


def test_the_lint_question_event_carries_its_title(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {SPEC: CONFLICT})
    run = run_l4([red_step(), green_step()])
    [event] = run.events("question.raised")
    questions = run.pushed(f"{UNIT_DIR}/questions.md")
    assert event["title"] and f"## Q-001: {event['title']}" in questions


def test_the_open_questions_events_carry_their_titles(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {DESIGN: OPEN_QUESTIONS})
    run = run_l4([red_step(), green_step()])
    raised = run.events("question.raised")
    questions = run.pushed(f"{UNIT_DIR}/questions.md")
    assert len(raised) == 3 and all(e["title"] and f"## {e['id']}: {e['title']}" in questions for e in raised)
