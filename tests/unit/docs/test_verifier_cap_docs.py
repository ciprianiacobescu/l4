"""The docs of verifier-cap (L4-VER-052 to L4-VER-055, SCN-VER-170 to SCN-VER-189)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.replace("`", "").split())


def test_the_spec_has_the_requirements_and_scenarios() -> None:
    spec = read("docs", "SPEC.md")
    requirements = [spec.index(f"**L4-VER-{n:03d} ") for n in range(51, 56)]
    assert requirements == sorted(requirements)
    scenarios = [spec.index(f"#### SCN-VER-{n} ") for n in (157, *range(170, 190))]
    assert scenarios == sorted(scenarios)
    paragraph = spec.split("**L4-VER-009 Discriminating evidence.**", 1)[1].split("\n\n", 1)[0]
    assert "L4-VER-054" in paragraph
    comment = spec.split("  max_criteria_per_test: 3", 1)[1][:500]
    assert "L4-VER-052" in comment and "L4-VER-054" in comment
    assert "| 59 | `verifier-cap` |" in spec


def test_the_eval_framework_names_the_write_time_check() -> None:
    row = next(line for line in read("docs", "eval-framework.md").splitlines() if line.startswith("| 15 |"))
    assert "L4-VER-052" in row and "L4-VER-054" in row


def test_the_changelog_names_the_cap() -> None:
    log = read("CHANGELOG.md")
    section = log.split("## 0.4.21 (", 1)[1].split("\n## ", 1)[0]
    assert log.index("## 0.4.21 (") < log.index("## 0.4.20 (2026-10-20)")
    assert re.search(r"^## 0\.4\.21 \(\d{4}-\d{2}-\d{2}\)$", log, re.M)  # the release is dated
    text = flat(section)
    for needle in (
        "verifier.max_criteria_per_test",
        "too many criteria on one test",
        "named by the judge",
        "judge@12",
        "only the per-test cap left it uncovered",
    ):
        assert needle in text, needle


def test_the_runbook_explains_the_cap_question() -> None:
    runbook = read("docs", "runbook.md")
    bullet = runbook.split("- A hold `judge view: …`", 1)[1].split("- Before you reject", 1)[0]
    text = flat(bullet)
    for needle in (
        "only the per-test cap left it uncovered",
        "harness 0.4.21 and later",
        "verifier.max_criteria_per_test",
        "accept when it checks this criterion as its scenario says",
        "starts a fix round",
    ):
        assert needle in text, needle
