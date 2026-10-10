from pathlib import Path

from l4.gates.odd import open_question_items, raise_open_questions
from l4.redact import Redactor
from l4.specs.openspec import parse_openspec_tasks
from l4.specs.questions import QuestionsFile

TASKS = parse_openspec_tasks(b"- [ ] 1.1 Parse\n- [ ] 1.2 Apply\n- [x] 1.3 Done\n")
DESIGN = (
    "# Design\n\n## Context\n- not a question\n\n## Open questions\n\n"
    "- (technical) Should `is_empty` be a method or a property? Follow the existing conventions of `Cart`.\n"
    "- (Product) Is a cart with only free items empty?\n"
    "  It matters for checkout.\n"
    "- Unlabelled item\n"
    "* (ambiguous) Star bullet\n\n"
    "## Decisions\n- also not a question\n"
)


def unit_with(tmp_path: Path, design: str | None = DESIGN, proposal: str | None = None) -> Path:
    unit = tmp_path / "unit"
    unit.mkdir(parents=True)
    if design is not None:
        (unit / "design.md").write_text(design)
    if proposal is not None:
        (unit / "proposal.md").write_text(proposal)
    return unit


def raised(unit: Path) -> list[str]:
    return raise_open_questions(unit, "add-x", TASKS, redactor=Redactor({}))


def test_items_get_their_kind_from_the_leading_label(tmp_path: Path):
    items = open_question_items(unit_with(tmp_path))
    assert [(i.kind.value, i.text.splitlines()[0]) for i in items] == [
        ("technical", "(technical) Should `is_empty` be a method or a property? Follow the existing conventions of `Cart`."),  # noqa: E501
        ("product", "(Product) Is a cart with only free items empty?"),
        ("ambiguous", "Unlabelled item"),
        ("ambiguous", "(ambiguous) Star bullet"),
    ]  # fmt: skip
    assert "It matters for checkout." in items[1].text  # an indented continuation belongs to its item


def test_every_item_becomes_a_question_blocking_every_pending_task(tmp_path: Path):
    unit = unit_with(tmp_path)
    assert raised(unit) == ["Q-001", "Q-002", "Q-003", "Q-004"]
    file = QuestionsFile.load(unit / "questions.md")
    assert file is not None
    assert [q.kind.value for q in file.questions] == ["technical", "product", "ambiguous", "ambiguous"]
    assert {q.blocking_tasks for q in file.questions} == {("1.1", "1.2")}
    assert {q.asked for q in file.questions} == {"intake (open questions in design.md)"}
    assert "Should `is_empty` be a method or a property?" in file.data.decode()


def test_a_rerun_does_not_duplicate_and_a_new_item_is_raised(tmp_path: Path):
    unit = unit_with(tmp_path)
    assert len(raised(unit)) == 4
    assert raised(unit) == []
    (unit / "design.md").write_text(DESIGN.replace("- Unlabelled item\n", "- Unlabelled   item\n- A new one\n"))
    assert raised(unit) == ["Q-005"]  # whitespace-only edit is the same item


def test_an_item_with_a_question_in_any_status_or_an_answer_is_not_raised_again(tmp_path: Path):
    unit = unit_with(tmp_path)
    raised(unit)
    text = (unit / "questions.md").read_text()
    text = text.replace("- **Status:** open", "- **Status:** dismissed", 1)
    (unit / "questions.md").write_text(text.replace("<!-- write below this line -->", "Use a property.", 1))
    assert raised(unit) == []


def test_no_section_or_no_pending_task_raises_nothing(tmp_path: Path):
    assert raised(unit_with(tmp_path, "# Design\n\n## Context\nNothing open.\n")) == []
    assert raised(unit_with(tmp_path / "b", None)) == []
    done = parse_openspec_tasks(b"- [x] 1.1 Done\n")
    assert raise_open_questions(unit_with(tmp_path / "c"), "add-x", done, redactor=Redactor({})) == []


def test_proposal_md_with_the_same_section_counts_too(tmp_path: Path):
    unit = unit_with(tmp_path, None, "# Proposal\n\n## Open questions\n- (product) Which currency?\n")
    assert raised(unit) == ["Q-001"]
    file = QuestionsFile.load(unit / "questions.md")
    assert file is not None and "proposal.md" in file.data.decode()
