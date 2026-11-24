"""The documentation of the targeted red check (L4-CFG-007, L4-GAT-007..009, L4-IMP-117..122)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHANGE = ROOT / "openspec" / "changes" / "red-check-targeted"
REQUIREMENTS = (
    "L4-CFG-007", "L4-GAT-007", "L4-GAT-008", "L4-GAT-009", *(f"L4-IMP-{n}" for n in range(117, 123))
)  # fmt: skip
SCENARIOS = (
    *(f"SCN-CFG-{n:02}" for n in range(8, 13)),
    *(f"SCN-GAT-{n:02}" for n in range(12, 21)),
    *(f"SCN-IMP-{n}" for n in range(626, 649)),
)
# the release this change ships in is named by nobody but the orchestrator: the files may name 0.4.59 and 0.4.60 only
OTHER_VERSION = re.compile(r"\b0\.(?:4\.(?:6[1-9]|[7-9]\d)|[5-9]\.\d+)\b")


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_the_spec_holds_each_requirement_once_and_names_it_in_a_scenario() -> None:
    spec = read("docs", "SPEC.md")
    headings = [line for line in spec.splitlines() if line.startswith("#### SCN-")]
    for requirement in REQUIREMENTS:
        assert len(re.findall(rf"^\*\*{requirement} ", spec, flags=re.M)) == 1, requirement
        assert any(re.search(rf"· .*\b{requirement}\b", line) for line in headings), requirement


def test_the_spec_holds_each_scenario_once() -> None:
    spec = read("docs", "SPEC.md")
    for scenario in SCENARIOS:
        assert len(re.findall(rf"^#### {scenario} ", spec, flags=re.M)) == 1, scenario


def test_the_runbook_and_the_skill_name_the_key() -> None:
    runbook = read("docs", "runbook.md")
    skill = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "plugins" / "l4" / "skills" / "l4").rglob("*.md"))
    for name, text in (("the runbook", runbook), ("the skill", skill)):
        assert "red_check" in text and "targeted" in text, name
    assert "task.red_check_disabled" in runbook and "task.red_check_full" in runbook


def test_the_changelog_names_the_key_under_unreleased() -> None:
    unreleased = read("CHANGELOG.md").split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    assert "red_check" in unreleased


def test_no_file_of_the_change_names_a_version_of_the_release() -> None:
    texts = {p: p.read_text(encoding="utf-8") for p in CHANGE.rglob("*.md")}
    assert texts
    unreleased = read("CHANGELOG.md").split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    texts[Path("CHANGELOG.md#Unreleased")] = unreleased
    for path, text in texts.items():
        assert not OTHER_VERSION.search(text), path
