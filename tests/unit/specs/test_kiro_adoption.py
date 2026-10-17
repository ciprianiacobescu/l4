"""L4-KSP-006: finished Kiro history is read, not validated as work (SCN-ODD-10 .. SCN-ODD-15)."""

from pathlib import Path

from l4.specs.criteria import kiro_criteria
from l4.specs.kiro import KiroProvider, kiro_tasks, parse_kiro_tasks

REQUIREMENTS = "### Requirement 1: Cache\n\n#### Acceptance Criteria\n\n1. WHEN a THEN b\n2. WHEN c THEN d\n"
MERMAID = "## Task Dependency Graph\n\n```mermaid\ngraph TD\n  A --> B\n```\n"


def unit_of(repo: Path, tasks: str, requirements: str = REQUIREMENTS, *, enforce: bool = True):
    directory = repo / ".kiro" / "specs" / "x"
    directory.mkdir(parents=True)
    (directory / "tasks.md").write_text(tasks)
    (directory / "design.md").write_text("d")
    (directory / "requirements.md").write_text(requirements)
    provider = KiroProvider(repo, enforce=enforce)
    (unit,) = provider.list_units()
    return provider, unit


def levels(provider, unit) -> list[tuple[str, str]]:
    return [(i.level, i.message) for i in provider.validate(unit, strict=True).issues]


def test_scn_odd_10_a_finished_leaf_with_no_requirement_link_is_a_warning(tmp_path):
    """SCN-ODD-10: a done leaf without `_Requirements:_` warns under sdd.enforce; intake admits the unit."""
    provider, unit = unit_of(tmp_path, "- [x] 3.1 Add cache\n- [ ] 3.2 Add more\n  - _Requirements: 1.1_\n")
    report = provider.validate(unit, strict=True)
    assert report.valid
    assert [(i.level, i.line) for i in report.issues] == [("WARNING", 1)]
    assert "task 3.1" in report.issues[0].message


def test_scn_odd_10_a_finished_leaf_with_an_unresolvable_reference_is_a_warning(tmp_path):
    """SCN-ODD-10: a done leaf citing a requirement no criterion has warns; a pending one still errors."""
    provider, unit = unit_of(
        tmp_path, "- [x] 1.1 Done\n  - _Requirements: 9.9_\n- [ ] 1.2 Pending\n  - _Requirements: 8.8_\n"
    )
    assert [(lv, "9.9" in m) for lv, m in levels(provider, unit)] == [("WARNING", True), ("ERROR", False)]


def test_scn_odd_11_a_pending_leaf_with_no_requirement_link_is_still_an_error(tmp_path):
    """SCN-ODD-11 (and SCN-ODD-02): intake rejects a pending leaf without a link; doctor SPEC-004 lists it only."""
    provider, unit = unit_of(tmp_path, "- [x] 3.1 Done\n- [ ] 3.2 Add eviction\n")
    report = provider.validate(unit, strict=True)
    assert not report.valid
    assert [(i.level, "task 3.2 has no _Requirements:_ line" in i.message) for i in report.issues] == [
        ("WARNING", False),
        ("ERROR", True),
    ]
    assert [t.key for t in provider.leaves_without_requirements(unit)] == ["3.2"]


def test_scn_odd_12_a_mermaid_dependency_graph_falls_back_to_document_order(tmp_path):
    """SCN-ODD-12: a graph block that is not JSON warns, and the tasks keep document order."""
    tasks = "- [ ] 1.1 A\n  - _Requirements: 1.1_\n- [ ] 1.2 B\n  - _Requirements: 1.2_\n\n" + MERMAID
    provider, unit = unit_of(tmp_path, tasks)
    report = provider.validate(unit, strict=True)
    assert report.valid
    assert [i.level for i in report.issues] == ["WARNING"] and "Task Dependency Graph" in report.issues[0].message
    read = kiro_tasks(tasks.encode())
    assert [t.key for t in read] == ["1.1", "1.2"] and all(t.wave is None for t in read)


def test_scn_odd_12_a_json_block_that_does_not_parse_is_a_warning_and_a_wrong_graph_an_error(tmp_path):
    """SCN-ODD-12: not JSON warns; JSON that is wrong (unknown task, no waves list) stays an error."""
    body = "- [ ] 1.1 A\n  - _Requirements: 1.1_\n\n## Task Dependency Graph\n\n```json\n{0}\n```\n"
    for block, level in (
        ("{nope", "WARNING"),
        ('{"waves": [{"id": 0, "tasks": ["9.9"]}]}', "ERROR"),
        ('{"phases": []}', "ERROR"),
    ):
        directory = tmp_path / level / str(len(block))
        directory.mkdir(parents=True)
        provider, unit = unit_of(directory, body.replace("{0}", block))
        graph = [lv for lv, m in levels(provider, unit) if "Task Dependency Graph" in m]
        assert graph == [level], block


def test_scn_odd_13_a_whole_requirement_reference_resolves(tmp_path):
    """SCN-ODD-13: `_Requirements: 1_` resolves when requirement 1 has criteria, and cites C(1.1) and C(1.2)."""
    provider, unit = unit_of(tmp_path, "- [ ] 1.1 A\n  - _Requirements: 1_\n")
    assert provider.validate(unit, strict=True).issues == ()
    (task,) = provider.tasks(unit)
    assert task.links == ("1",)
    assert {c.alias for c in provider.criteria(unit)} == {"Req 1.1", "Req 1.2"}


def test_scn_odd_13_a_whole_requirement_without_criteria_does_not_resolve(tmp_path):
    """SCN-ODD-13: requirement 7 has no criteria, so `7` stays unresolved (error for a pending leaf)."""
    provider, unit = unit_of(tmp_path, "- [ ] 1.1 A\n  - _Requirements: 7_\n")
    assert [lv for lv, _ in levels(provider, unit)] == ["ERROR"]


def test_scn_odd_14_a_requirement_one_heading_level_higher_is_read(tmp_path):
    """SCN-ODD-14: `## Requirement 1` with `### Acceptance Criteria` gives Req 1.1 and Req 1.2."""
    directory = tmp_path / "s"
    directory.mkdir()
    (directory / "requirements.md").write_text(
        "# Requirements\n\n## Requirement 1: Login\n\n**User Story:** As a u\n\n### Acceptance Criteria\n\n"
        "1. WHEN a THEN b\n2. WHEN c THEN d\n"
    )
    assert [c.alias for c in kiro_criteria(directory)] == ["Req 1.1", "Req 1.2"]


def test_scn_odd_15_a_number_inside_a_word_is_not_a_reference():
    """SCN-ODD-15: `ADR-0014.8` and `AC3` are not references; `2.1` and `Req 1` are."""
    (task,) = parse_kiro_tasks(b"- [ ] 1 A\n  - _Requirements: 2.1, ADR-0014.8, Req 1 AC3_\n")
    assert task.links == ("2.1", "1")
