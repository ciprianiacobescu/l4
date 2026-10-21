from pathlib import Path

from l4.gates.odd import raise_scenario_questions, scenario_conflicts
from l4.redact import Redactor
from l4.specs.criteria import base_criteria, openspec_criteria, replaced_requirements
from l4.specs.openspec import parse_openspec_tasks
from l4.specs.questions import QuestionsFile, QuestionStatus

DELTA = "## ADDED Requirements\n\n### Requirement: Codes\nSAVE10 takes 10 %.\n\n{scenarios}"
TASKS = parse_openspec_tasks(b"- [ ] 1.1 Parse\n- [ ] 1.2 Apply\n- [x] 1.3 Done\n")


def scenario(name: str, when: str, then: str, *, lead: str = "- ") -> str:
    return f"#### Scenario: {name}\n{lead}**WHEN** {when}\n{lead}**THEN** {then}\n\n"


def write_delta(unit: Path, *scenarios: str, capability: str = "pricing") -> None:
    path = unit / "specs" / capability / "spec.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DELTA.format(scenarios="".join(scenarios)))


def write_base(root: Path, *scenarios: str, capability: str = "pricing", requirement: str = "Rounding") -> None:
    path = root / "openspec" / "specs" / capability / "spec.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    head = f"# {capability}\n\n## Requirements\n\n### Requirement: {requirement}\nText.\n\n"
    path.write_text(head + "".join(scenarios))


def conflicts(unit: Path, root: Path):
    return scenario_conflicts(
        openspec_criteria(unit), base_criteria(root / "openspec" / "specs"), replaced_requirements(unit)
    )


def test_same_when_different_then_raises_one_ambiguous_question(tmp_path: Path):
    """SCN-ODD-08"""
    unit = tmp_path / "unit"
    write_delta(
        unit,
        scenario("Ten off", '`apply_code("SAVE10")` is called with a total of 100', "the total is 90"),
        scenario("Nothing off", '`apply_code("SAVE10")`   is called with a total of 100', "the total is 100"),
        scenario("Unknown", '`apply_code("NOPE")` is called', "it raises"),
    )
    [conflict] = conflicts(unit, tmp_path)
    assert {conflict.first.scenario, conflict.second.scenario} == {"Ten off", "Nothing off"}
    ids = raise_scenario_questions(unit, "add-x", conflicts(unit, tmp_path), TASKS, redactor=Redactor({}))
    assert ids == ["Q-001"]
    file = QuestionsFile.load(unit / "questions.md")
    assert file is not None
    (question,) = file.questions
    assert question.kind is not None and question.kind.value == "ambiguous"
    assert question.status is QuestionStatus.OPEN
    assert question.asked == "intake lint (L4-ODD-004)"
    assert question.blocking_tasks == ("1.1", "1.2")  # every pending task: tasks are not linked to scenarios
    text = file.data.decode()
    assert "the total is 90" in text and "the total is 100" in text  # both scenarios with their THEN lines
    assert conflict.first.id in text and conflict.second.id in text


def test_clean_change_raises_nothing(tmp_path: Path):
    """SCN-ODD-09"""
    unit = tmp_path / "unit"
    write_delta(
        unit,
        scenario("Same result", "a code is applied", "the total is 90"),
        scenario("Same result again", "a code is applied", "the total   is 90"),  # equal THEN: no conflict
        scenario("Code A", '`apply_code("A")` is called', "A applies"),
        scenario("Code B", '`apply_code("B")` is called', "B applies"),  # WHEN differs only inside a code span
    )
    assert conflicts(unit, tmp_path) == []
    assert raise_scenario_questions(unit, "add-x", [], TASKS, redactor=Redactor({})) == []
    assert not (unit / "questions.md").exists()


def test_the_normalisation_keeps_case_and_code_spans_verbatim(tmp_path: Path):
    unit = tmp_path / "unit"
    write_delta(
        unit,
        scenario("a", "the User logs in", "x"),
        scenario("b", "the user logs in", "y"),  # case is kept: a different WHEN
        scenario("c", '`f("a  b")` runs', "x"),
        scenario("d", '`f("a b")` runs', "y"),  # whitespace inside a code span is kept: a different WHEN
    )
    assert conflicts(unit, tmp_path) == []


def test_conflict_with_base_spec(tmp_path: Path):
    unit = tmp_path / "unit"
    write_delta(unit, scenario("Round up", "the total is 10.005", "it shows 10.01"))
    write_base(tmp_path, scenario("Round down", "the total is 10.005", "it shows 10.00"))
    [conflict] = conflicts(unit, tmp_path)
    assert (conflict.first.scenario, conflict.second.scenario) == ("Round up", "Round down")
    assert conflict.second.source_path == "openspec/specs/pricing/spec.md"


def test_a_base_requirement_the_change_modifies_is_not_a_conflict_with_itself(tmp_path: Path):
    unit = tmp_path / "unit"
    path = unit / "specs" / "pricing" / "spec.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "## MODIFIED Requirements\n\n### Requirement: Rounding\nNew.\n\n"
        + scenario("Round up", "the total is 10.005", "it shows 10.01")
    )
    write_base(tmp_path, scenario("Round down", "the total is 10.005", "it shows 10.00"))
    assert conflicts(unit, tmp_path) == []


def test_two_base_scenarios_that_disagree_are_not_this_units_problem(tmp_path: Path):
    unit = tmp_path / "unit"
    write_delta(unit, scenario("Other", "something else", "ok"))
    write_base(tmp_path, scenario("A", "x", "1"), scenario("B", "x", "2"))
    assert conflicts(unit, tmp_path) == []


def test_existing_pair_not_reraised(tmp_path: Path):
    unit = tmp_path / "unit"
    write_delta(unit, scenario("One", "same", "a"), scenario("Two", "same", "b"))
    redactor = Redactor({})
    found = conflicts(unit, tmp_path)
    assert raise_scenario_questions(unit, "add-x", found, TASKS, redactor=redactor) == ["Q-001"]
    assert raise_scenario_questions(unit, "add-x", found, TASKS, redactor=redactor) == []
    file = QuestionsFile.load(unit / "questions.md")
    assert file is not None
    for status in (QuestionStatus.ANSWERED, QuestionStatus.DISMISSED, QuestionStatus.SUPERSEDED):
        file.set_status("Q-001", status).save(unit / "questions.md")  # in any Status
        assert raise_scenario_questions(unit, "add-x", found, TASKS, redactor=redactor) == []
    write_delta(unit, scenario("One", "same", "a"), scenario("Two", "same", "b"), scenario("Three", "same", "c"))
    more = conflicts(unit, tmp_path)
    assert len(more) == 3
    new_pairs_only = raise_scenario_questions(unit, "add-x", more, TASKS, redactor=redactor)
    assert new_pairs_only == ["Q-002", "Q-003"]


def test_one_line_when_then_and_and_lines(tmp_path: Path):
    unit = tmp_path / "unit"
    path = unit / "specs" / "pricing" / "spec.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "## ADDED Requirements\n\n### Requirement: R\nText.\n\n"
        "#### Scenario: a\nWHEN x happens THEN it is 1\n\n"
        "#### Scenario: b\n- **WHEN** x happens\n- **AND** y holds\n- **THEN** it is 1\n\n"
        "#### Scenario: c\n- **WHEN** x happens\n- **THEN** it is 2\n- **AND** it is logged\n\n"
    )
    pairs = {(c.first.scenario, c.second.scenario) for c in conflicts(unit, tmp_path)}
    # b's WHEN has an AND line, so it is a different WHEN; a and c share theirs and differ in THEN
    assert pairs == {("a", "c")}


def test_a_removed_or_renamed_base_requirement_is_replaced_not_in_conflict(tmp_path: Path):
    unit = tmp_path / "unit"
    base = tmp_path / "openspec" / "specs" / "vat" / "spec.md"
    base.parent.mkdir(parents=True)
    base.write_text(
        "# vat\n\n## Requirements\n\n### Requirement: Flat VAT\nText.\n\n"
        + scenario("Romanian cart", "a Romanian cart totals 100", "the total is 119")
        + "### Requirement: Old name\nText.\n\n"
        + scenario("Czech cart", "a Czech cart totals 100", "the total is 121")
    )
    path = unit / "specs" / "vat" / "spec.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "## REMOVED Requirements\n\n### Requirement: Flat VAT\n**Reason**: by country now.\n\n"
        "## RENAMED Requirements\n\n- FROM: `### Requirement: Old name`\n- TO: `### Requirement: New name`\n\n"
        "## ADDED Requirements\n\n### Requirement: VAT by country\nText.\n\n"
        + scenario("Romanian cart", "a Romanian cart totals 100", "the total is 121")
        + scenario("Czech cart again", "a Czech cart totals 100", "the total is 100")
    )
    assert replaced_requirements(unit) == {("vat", "Flat VAT"), ("vat", "Old name")}
    assert conflicts(unit, tmp_path) == []
    # without the REMOVED/RENAMED sections the same pair does conflict: the test would catch a missing exclusion
    assert len(scenario_conflicts(openspec_criteria(unit), base_criteria(tmp_path / "openspec" / "specs"))) == 2


def given_scenario(name: str, given: str, when: str, then: str) -> str:
    return f"#### Scenario: {name}\n- **GIVEN** {given}\n- **WHEN** {when}\n- **THEN** {then}\n\n"


def test_scenarios_with_different_givens_and_the_same_when_do_not_conflict(tmp_path: Path):
    unit = tmp_path / "unit"
    write_delta(
        unit,
        given_scenario("Member", "a member", "the code is applied", "the total is 90"),
        given_scenario("Guest", "a guest", "the code is applied", "the total is 100"),
    )
    assert conflicts(unit, tmp_path) == []


def test_scenarios_with_the_same_given_and_when_conflict_on_a_different_then(tmp_path: Path):
    unit = tmp_path / "unit"
    write_delta(
        unit,
        given_scenario("Ten off", "a member  \n- **AND** a cart", "the code is applied", "the total is 90"),
        given_scenario("Nothing off", "a member\n- **AND** a cart", "the code is applied", "the total is 100"),
    )
    [conflict] = conflicts(unit, tmp_path)
    assert conflict.given == "a member a cart" and conflict.when == "the code is applied"


def test_a_scenario_without_a_given_does_not_conflict_with_one_that_has_it(tmp_path: Path):
    unit = tmp_path / "unit"
    write_delta(
        unit,
        given_scenario("Member", "a member", "the code is applied", "the total is 90"),
        scenario("Anyone", "the code is applied", "the total is 100"),
    )
    assert conflicts(unit, tmp_path) == []
