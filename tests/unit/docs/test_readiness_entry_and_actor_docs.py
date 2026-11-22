"""The documentation of the entry order, the actor and the older CLI (L4-YOLO-104, SCN-YOLO-295)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REFERENCES = ("plugins", "l4", "skills", "l4", "references")


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_the_runbook_names_the_chain_the_doctor_row_and_the_older_cli() -> None:
    runbook = read("docs", "runbook.md")
    review = section(runbook, "### 12.2 ", "### 12.2a ")
    for needle in ("CFG-013", "roles.plan_judges", "roles.judges"):
        assert needle in review, needle
    assert "no fallback" in " ".join(review.split())
    computer = runbook.split("--allow-older-cli", 1)
    assert len(computer) == 2 and "older than the pin" in " ".join(runbook.split())
    assert ".l4/bin/l4" in runbook.split("--allow-older-cli", 1)[0].rsplit("Move it with the pin", 1)[1]


def test_the_skill_names_cfg_013_and_the_plan_judges_and_says_to_move_the_local_l4() -> None:
    plan, adopt = read(*REFERENCES, "plan.md"), read(*REFERENCES, "adopt.md")
    for name, text in (("plan.md", plan), ("adopt.md", adopt)):
        assert "CFG-013" in text and "roles.plan_judges" in text, name
    assert "CFG-013" in plan.split("When no judge can run", 1)[0].rsplit("Do not cut `roles.judges`", 1)[1]
    upgrade = adopt.split("Move every local `l4` with the pin", 1)[1]
    assert "--allow-older-cli" in upgrade and "older than the pin" in upgrade


def test_the_changelog_names_prompt_version_5_the_doctor_row_the_flag_and_the_actor() -> None:
    unreleased = read("CHANGELOG.md").split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    for needle in ("prompt version is now 5", "CFG-013", "--allow-older-cli", "plan.activated", "actor"):
        assert needle in unreleased, needle
