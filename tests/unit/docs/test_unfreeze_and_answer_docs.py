"""The runbook and the skill teach `l4 questions` and the named-path unfreeze (L4-OPS-017, L4-IMP-014)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "plugins" / "l4" / "skills" / "l4"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = text.find("\n### ", start + len(heading))
    return text[start : following if following != -1 else len(text)]


def test_the_runbook_gives_the_command_before_the_hand_edit() -> None:  # SCN-OPS-27
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    procedure = _section(runbook, "### 7.1 ")
    command = procedure.index("l4 questions answer Q-NNN --unit <unit> --text")
    assert procedure.index("l4 questions show Q-NNN --unit <unit>") < command
    assert "l4 questions accept Q-NNN --unit <unit>" in procedure
    assert "--no-push" in procedure
    assert command < procedure.index("The hand edit")
    assert "clarifier.answer_by_agents" in procedure
    assert "is not available in 0.4.1" not in procedure


def test_the_runbook_no_longer_lists_the_command_as_unavailable() -> None:  # SCN-OPS-27
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    commands = _section(runbook, "### 10.4 ")
    assert "| `l4 questions" in commands
    unavailable = commands[commands.index("not available") :]
    assert "l4 questions" not in unavailable
    for stub in ("l4 unlock", "l4 status --rebuild", "l4 verify --dry-run", "(not yet implemented)"):
        assert stub in unavailable, stub
    files = _section(runbook, "### 10.5 ")
    row = next(line for line in files.splitlines() if line.startswith("| `questions.md`"))
    assert "l4 questions" in row
    limits = runbook[runbook.index("## 11. ") : runbook.index("## 12. ")]
    assert "agent rule" in limits.lower() and "--no-push" in limits
    assert "`l4 questions`," not in limits


def test_the_runbook_says_a_support_file_question_can_be_accepted() -> None:
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    halted = _section(runbook, "### 7.2 ")
    assert "l4 questions accept" in halted and "conftest.py" in halted
    assert "ignore file" in halted


def test_the_skill_operate_reference_teaches_the_command_and_the_agent_rule() -> None:  # SCN-OPS-27
    operate = (SKILL / "references" / "operate.md").read_text(encoding="utf-8")
    block = operate[operate.index("## Answering `questions.md`") : operate.index("## Retry or restart")]
    assert "is not built yet" not in operate
    command = block.index("l4 questions answer Q-NNN --unit FW:NAME --text")
    assert block.index("l4 questions show") < command < block.index("hand edit")
    for needle in (
        "l4 questions accept Q-NNN --unit FW:NAME",
        "--no-push",
        "clarifier.answer_by_agents",
        "clarifier.auto_accept_kinds",
        "product",
        "verdict",
        "frozen",
        "a person",
    ):
        assert needle in block, needle
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    pointer = skill[skill.index("- `references/operate.md`") : skill.index("- `references/adopt.md`")]
    assert "l4 questions" in pointer


def test_the_spec_reference_teaches_the_named_support_file() -> None:  # L4-IMP-014
    spec = (SKILL / "references" / "spec.md").read_text(encoding="utf-8")
    assert len(spec.split()) <= 530
    for needle in ("`conftest.py`", 'not "the conftest"', "test-infra", "data fixture", "ignore file", "reviewed"):
        assert needle in spec, needle
