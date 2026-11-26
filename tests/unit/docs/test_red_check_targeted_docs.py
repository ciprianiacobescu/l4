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
    *(f"SCN-IMP-{n}" for n in range(626, 653)),
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
    unreleased = read("CHANGELOG.md").split("## 0.4.61 (", 1)[1].split("\n## ", 1)[0]
    assert "red_check" in unreleased


def test_no_file_of_the_change_names_a_version_of_the_release() -> None:
    texts = {p: p.read_text(encoding="utf-8") for p in CHANGE.rglob("*.md")}
    assert texts
    unreleased = read("CHANGELOG.md").split("## 0.4.61 (", 1)[1].split("\n## ", 1)[0]
    texts[Path("CHANGELOG.md#0.4.61")] = unreleased
    for path, text in texts.items():
        assert not OTHER_VERSION.search(text), path


def test_the_review_round_decisions_are_in_every_document() -> None:
    """The resumed base, the two other green failures and the ledger-driven switch (L4-IMP-119, L4-IMP-121)."""
    texts = {
        "SPEC": read("docs", "SPEC.md"),
        "delta spec": read("openspec", "changes", "red-check-targeted", "specs", "red-check-targeted", "spec.md"),
        "design": read("openspec", "changes", "red-check-targeted", "design.md"),
        "runbook": read("docs", "runbook.md"),
    }
    for name, text in texts.items():
        for word in ("green_collection", "green_no_report", "resume_put_back", "resume_files"):
            assert word in text, (name, word)
    for name in ("SPEC", "delta spec", "design"):
        assert "`@`" in texts[name], name  # pytest reads `@file` as an argument file


def test_no_document_keeps_the_wording_the_review_round_replaced() -> None:
    stale = (
        "this is a limit, and verification's whole-suite steps are its backstop",
        "gets no record",
        "records nothing:\n  verification's whole-suite steps report it",
        "A `full` configuration SHALL write none of these keys and events",
        "a regressed base-passing test of green's whole run after its re-run, or a red test of a targeted task missing",
    )
    changed = (
        read("docs", "SPEC.md"),
        read("docs", "runbook.md"),
        read("CHANGELOG.md"),
        *(p.read_text(encoding="utf-8") for p in CHANGE.rglob("*.md")),
    )
    for text in changed:
        for phrase in stale:
            assert phrase not in text, phrase
