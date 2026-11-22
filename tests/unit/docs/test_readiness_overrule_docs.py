"""The documentation of the overrule (L4-YOLO-108, SCN-YOLO-306)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REFERENCES = ("plugins", "l4", "skills", "l4", "references")


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.split())


def test_the_runbook_names_the_command_the_person_and_the_end_of_the_overrule() -> None:
    runbook = read("docs", "runbook.md")
    section = flat(runbook.split("### 12.2a ", 1)[1].split("### 12.2b ", 1)[0])
    for needle in (
        "l4 yolo overrule",
        "plan.finding_overruled",
        "no longer holds",
        "Only a person in a terminal can overrule",
        "an agent prints the command for the person",
        "--all --force",
        "next judge of the subject reads",
        "material changes",
    ):
        assert needle in section, needle


def test_the_skill_says_an_agent_prints_the_command_for_the_person() -> None:
    plan = flat(read(*REFERENCES, "plan.md"))
    for needle in (
        "l4 yolo overrule",
        "a person's decision",
        "one blocking finding",
        "material changes",
        "Never run it yourself",
    ):
        assert needle in plan, needle


def test_the_changelog_has_the_entry_under_unreleased() -> None:
    unreleased = flat(read("CHANGELOG.md").split("## Unreleased", 1)[1].split("\n## ", 1)[0])
    for needle in ("l4 yolo overrule", "plan.finding_overruled", "Only a person in a terminal", "material changes"):
        assert needle in unreleased, needle
