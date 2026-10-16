"""The escalation and the retry note are documented where a person and an agent look for them (L4-OPS-019)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "plugins" / "l4" / "skills" / "l4"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = text.find("\n## ", start + len(heading))
    return text[start : following if following != -1 else len(text)]


def test_the_runbook_teaches_the_note_and_the_escalation() -> None:  # SCN-OPS-33
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    halted = runbook[runbook.index("### 7.2 `halted`") : runbook.index("### 7.3 ")]
    for needle in (
        "implementer.escalate_after",
        "escalate_after: 0",
        "--reason",
        "implementer of that task",
        "note: the reason goes to the next steps of task",
        "note: the stop names no task",
        "opencode-go/deepseek-v4.1-flash",
        "profile",
    ):
        assert needle in halted, needle
    lines = runbook[runbook.index("### 4.2 ") : runbook.index("### 4.3 ")]
    for needle in (
        "escalated from <from> to <to> after <n> failed attempts",
        "attempt <n> failed on <profile>",
        "escalated from <from>",
        "halted: max_task_attempts (task <k>: <p1> <f1>, <p2> <f2>)",
        "the prompt holds the person's retry note",
        "no later profile can take it",
    ):
        assert needle in lines, needle
    commands = runbook[runbook.index("### 10.4 ") : runbook.index("### 10.5 ")]
    retry_row = commands.split("| `l4 retry")[1].split("\n")[0]
    assert "reason" in retry_row and "note" in retry_row
    limits = _section(runbook, "## 11. ")
    for needle in ("fix unit", "max_cost_usd_per_unit", "between unit runs"):
        assert needle in limits, needle


def test_the_adopt_reference_shows_the_cheap_first_chain() -> None:  # SCN-OPS-33
    adopt = (SKILL / "references" / "adopt.md").read_text(encoding="utf-8")
    for needle in (
        "implementer: [deepseek, glm, claude-sonnet]",
        "opencode-go/deepseek-v4.1-flash",
        "opencode-go/glm-5.3-flash",
        "OPENCODE_API_KEY",
        "judges: [claude-judge, codex-judge]",
        "escalate_after: 2",
        "max_task_attempts: 3",
    ):
        assert needle in adopt, needle
    assert adopt.index("deepseek:") < adopt.index("claude-sonnet:")


def test_the_operate_reference_says_what_the_reason_is_for() -> None:  # SCN-OPS-33
    operate = (SKILL / "references" / "operate.md").read_text(encoding="utf-8")
    assert "300 characters" in operate and "implementer" in operate and "note" in operate
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "note" in skill[skill.index("operate.md") - 300 : skill.index("operate.md") + 300]


def test_the_changelog_has_the_0_4_4_section() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index("## 0.4.4 (") < changelog.index("## 0.4.3")
    section = changelog[changelog.index("## 0.4.4") : changelog.index("## 0.4.3")]
    for needle in ("escalate_after", "implementer.escalated", "CFG-009", "escalate_after: 0"):
        assert needle in section, needle
