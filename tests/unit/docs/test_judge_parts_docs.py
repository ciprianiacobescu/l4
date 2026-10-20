"""The docs of judge-parts (L4-VER-056 to L4-VER-058, SCN-VER-190 to SCN-VER-203)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.replace("`", "").split())


def test_the_spec_has_the_requirements_and_scenarios() -> None:
    spec = read("docs", "SPEC.md")
    requirements = [spec.index(f"**L4-VER-{n:03d} ") for n in (47, 56, 57, 58)]
    assert requirements == sorted(requirements)
    scenarios = [spec.index(f"#### SCN-VER-{n} ") for n in (157, *range(190, 204))]
    assert scenarios == sorted(scenarios)
    between = spec[scenarios[1] : spec.index("## MODIFIED Requirements", scenarios[-1])]
    assert "\n## " not in between  # SCN-VER-190 to 203 sit before the next `## MODIFIED Requirements` heading
    assert "| 60 | `judge-parts` |" in spec
    assert "judge@12" in spec.split("**L4-VER-018 ", 1)[1].split("\n\n", 1)[0]
    step_nine = next(line for line in spec.splitlines() if line.startswith("| 9 | LLM judge panel"))
    assert "L4-VER-056 to L4-VER-058" in step_nine


def test_the_runbook_names_a_split_criterion() -> None:
    runbook = read("docs", "runbook.md")
    bullet = runbook.split("- A hold `judge view: …`", 1)[1].split("- Before you reject", 1)[0]
    text = flat(bullet)
    for needle in ("its evidence was split over parts", "follow-up call", "Files by part"):
        assert needle in text, needle


def test_the_skill_names_a_split_criterion() -> None:
    operate = read("plugins", "l4", "skills", "l4", "references", "operate.md")
    questions = operate.split("**Verdict questions**", 1)[1].split("\n\n", 1)[0]
    text = flat(questions)
    assert "its evidence was split over parts" in text and "Files by part" in text


def test_the_changelog_names_the_follow_up() -> None:
    log = read("CHANGELOG.md")
    assert log.index("## 0.4.21 (unreleased)") < log.index("## 0.4.20 (")
    section = log.split("## 0.4.21 (unreleased)", 1)[1].split("\n## ", 1)[0]
    text = flat(section)
    for needle in ("follow-up", "L4-VER-056", "L4-VER-058", "judge@12", "its evidence was split over parts"):
        assert needle in text, needle
    assert log.count("## 0.4.21 (unreleased)") == 1
