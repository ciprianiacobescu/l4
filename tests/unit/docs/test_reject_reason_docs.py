"""The docs of reject-reason (L4-VER-059, L4-VER-060, SCN-VER-205 to SCN-VER-216)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.replace("`", "").split())


def test_the_spec_has_the_requirements_and_scenarios() -> None:
    spec = read("docs", "SPEC.md")
    v59 = spec.index("**L4-VER-059 ")
    assert spec.index("**L4-VER-006") < v59 < spec.index("**L4-VER-007")
    assert spec.index("**L4-VER-013") < spec.index("**L4-VER-060 ") < spec.index("**L4-VER-014 ")
    scenarios = [spec.index(f"#### SCN-VER-{n} ") for n in range(205, 217)]
    assert scenarios == sorted(scenarios)
    assert spec.index("#### SCN-VER-157 ") < scenarios[0] and scenarios[-1] < spec.index("### 23.9.1")
    text = flat(spec)
    assert "when L4-VER-059 gives it one" in text and "a spec gap that L4-VER-059 gives no scenario adds none" in text
    assert "| `reject-reason` |" in spec
    assert "a spec gap's reject needs a reason or a WHEN ... THEN ..." in text


def test_the_runbook_says_what_a_reject_without_a_scenario_does() -> None:
    runbook = read("docs", "runbook.md")
    section = runbook.split("**For verdict questions**", 1)[1].split("\n**", 1)[0]
    text = flat(section)
    for needle in ("checked against", "suggested fix", "describes what the code does now", "A spec gap's bare reject"):
        assert needle in text, needle


def test_the_skill_says_it_too() -> None:
    skill = read("plugins", "l4", "skills", "l4", "references", "operate.md")
    text = flat(skill.split("**Verdict questions**", 1)[1].split("## Retry or restart", 1)[0])
    assert "checked against" in text and "suggested fix" in text and "bare reject" in text


def test_the_way_out_of_no_convertible_finding_names_a_replaced_reject() -> None:
    runbook = read("docs", "runbook.md")
    section = flat(runbook.split("#### 7.3.1 ", 1)[1].split("\n#### ", 1)[0])
    assert "--replace" in section and "reject: <reason>. WHEN … THEN …" in section
    skill = read("plugins", "l4", "skills", "l4", "references", "operate.md")
    bullet = flat(skill.split("**Escalated with `no finding of this round", 1)[1].split("\n- **", 1)[0])
    assert "--replace" in bullet and "WHEN … THEN …" in bullet


def test_the_changelog_names_the_fix() -> None:
    log = read("CHANGELOG.md")
    section = flat(log.split("## 0.4.21 (", 1)[1].split("## 0.4.20 (", 1)[0])
    for needle in ("L4-VER-059", "L4-VER-060", "answer again with a scenario", "suggested fix"):
        assert needle in section, needle
