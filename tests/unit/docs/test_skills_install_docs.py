"""The front door leads with `uv tool install … && l4 skills install` (skills-install 4.1, L4-SKL-003)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LEAD = re.compile(r"uv tool install git\+https://github\.com/\S+/l4@v\S+ && l4 skills install")


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_readme_quickstart_and_adopt_lead_with_the_one_line() -> None:
    for text in (
        read("README.md"),
        read("docs", "quickstart.md"),
        read("plugins", "l4", "skills", "l4", "references", "adopt.md"),
    ):
        assert LEAD.search(text), "the one-line install is missing"
    assert "/plugin marketplace add ciprianiacobescu/l4" in read("README.md")


def test_the_spec_and_the_changelog_carry_the_requirement() -> None:
    spec = read("docs", "SPEC.md")
    skl_001 = spec.split("**L4-SKL-001**", 1)[1].split("**L4-SKL-002**", 1)[0]
    assert "[Not yet built" not in skl_001 and "L4-SKL-003" in skl_001
    assert spec.index("**L4-SKL-002**") < spec.index("**L4-SKL-003**")
    for n in range(4, 9):
        assert f"#### SCN-SKL-0{n} " in spec
    assert "| `l4 skills install " in spec and "| `l4 skills status` |" in spec
    changelog = read("CHANGELOG.md")
    head = changelog.split("## 0.4.14 (", 1)[1].split("\n## ", 1)[0]
    assert "### Added" in head and "l4 skills install" in head
