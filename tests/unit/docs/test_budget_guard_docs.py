"""The docs of budget-guard (L4-IMP-076 to L4-IMP-079, SCN-IMP-385 to SCN-IMP-395)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.replace("`", "").split())


def test_the_spec_has_the_requirements_and_scenarios() -> None:
    spec = read("docs", "SPEC.md")
    positions = [spec.index(f"**L4-IMP-{n:03d}** ") for n in range(75, 80)]
    assert positions == sorted(positions)
    scenarios = [spec.index(f"#### SCN-IMP-{n} ") for n in range(385, 396)]
    assert scenarios == sorted(scenarios) and scenarios[-1] < spec.index("### 23.8")
    assert "| CFG-012 | error |" in spec
    assert "| 58 | `budget-guard` |" in spec
    for requirement in ("L4-IMP-070", "L4-IMP-071"):
        text = spec.split(f"**{requirement}** ", 1)[1].split("\n**L4-IMP-", 1)[0]
        assert "the fix for the budget's source" in text, requirement


def test_the_runbook_names_the_budget_check() -> None:
    runbook = read("docs", "runbook.md")
    section = runbook.split("- The soft deadline is `ci.time_budget`", 1)[1].split("\n## ", 1)[0]
    text = flat(section)
    for needle in (
        "CFG-012",
        "ci.time_budget: auto",
        "less than 10 minutes",
        "raise ci.time_budget (or set it to auto)",
    ):
        assert needle in text, needle
    assert "(or ci.time_budget)" not in flat(runbook)


def test_the_skill_has_the_budget_rows() -> None:
    operate = read("plugins", "l4", "skills", "l4", "references", "operate.md")
    assert "less than one step (10 min)" in operate and "is shorter than the job's timeout" in operate
    row = next(line for line in operate.splitlines() if line.startswith("| `deadline_repeated`"))
    assert "ci.time_budget" in row


def test_the_changelog_names_the_budget_guard() -> None:
    changelog = read("CHANGELOG.md")
    assert changelog.index("## 0.4.20 (unreleased)") < changelog.index("## 0.4.19 (")
    head = changelog.split("## 0.4.20 (unreleased)", 1)[1].split("\n## ", 1)[0]
    for needle in ("CFG-012", "ci.time_budget: auto", "exits 2", "job_budget_source", "raise ci.time_budget"):
        assert needle in head, needle
