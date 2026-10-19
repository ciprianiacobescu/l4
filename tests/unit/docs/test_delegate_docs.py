"""SPEC, runbook, guides, skill and CHANGELOG teach the delegate (delegate-answers 17.1; L4-DLG-001..014)."""

import re
from pathlib import Path

import yaml

from l4.config.schema import DelegateCfg, L4Config

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "plugins" / "l4" / "skills" / "l4"
CHANGE = ROOT / "openspec" / "changes" / "delegate-answers"
SPEC = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
PART1, PART2 = SPEC.split("# Part II", 1)


def _read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def _section(text: str, heading: str, level: str = "### ") -> str:
    start = text.index(heading)
    end = text.find("\n" + level, start + len(heading))
    return text[start : end if end != -1 else len(text)]


def _change_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted((CHANGE / "specs").rglob("spec.md")))


def test_every_dlg_requirement_and_scenario_of_the_change_is_in_the_spec() -> None:
    change = _change_text()
    requirements = set(re.findall(r"### Requirement: (L4-[A-Z]+-\d{3}[a-z]?)", change))
    scenarios = set(re.findall(r"Scenario: (SCN-DLG-\d+[a-z]?)", change))
    assert {f"L4-DLG-{n:03d}" for n in range(1, 15)} <= requirements
    assert len(scenarios) >= 55
    for requirement in requirements:
        assert re.search(rf"^\*\*{requirement}\b", PART1, re.M), requirement
    headings = set(re.findall(r"^#### (SCN-DLG-\d+[a-z]?) ", PART2, re.M))
    assert scenarios <= headings, sorted(scenarios - headings)
    assert headings <= scenarios, sorted(headings - scenarios)
    assert "### 23.25 Delegate (DLG)" in PART2


def test_a_scenario_heading_names_its_requirement() -> None:
    for sid, title in re.findall(r"^#### (SCN-DLG-\d+[a-z]?) \([+−]\) (.*)$", PART2, re.M):
        assert re.search(r" · L4-[A-Z]+-\d{3}", title), sid


def test_the_delegate_section_9_1_holds_the_fourteen_requirements() -> None:
    section = _section(PART1, "### 9.1 Delegate")
    for n in range(1, 15):
        assert f"**L4-DLG-{n:03d}" in section, n
    assert PART1.index("### 9.1 Delegate") > PART1.index("## 9. Clarifier")
    assert PART1.index("### 9.1 Delegate") < PART1.index("## 10. Verifier")


def test_the_reference_configuration_has_the_delegate_section_and_profiles() -> None:
    block = re.search(r"### 3\.2 Reference configuration.*?```yaml\n(.*?)```", SPEC, re.S).group(1)  # type: ignore[union-attr]
    cfg = yaml.safe_load(block)
    assert set(cfg["delegate"]) == set(DelegateCfg.model_fields)
    assert DelegateCfg(**cfg["delegate"]) == DelegateCfg()
    assert cfg["profiles"]["delegate-opus"]["model"] == "claude-opus-5-5"
    assert cfg["profiles"]["delegate-sol"]["model"] == "gpt-6.1-sol"
    assert cfg["profiles"]["delegate-sol"]["options"]["reasoning_effort"] == "high"
    assert cfg["roles"]["delegate"] == ["delegate-opus", "delegate-sol", "delegate-sonnet"]
    cfg["harness"]["commit"] = "0" * 40  # the placeholder of the reference file
    assert L4Config.model_validate(cfg).roles.delegate == ["delegate-opus", "delegate-sol", "delegate-sonnet"]
    assert "L4-DLG-001" in block and "L4-DLG-009" in block and "L4-DLG-014" in block


def test_the_modified_requirements_carry_the_changes_text() -> None:
    assert "- **Answered by:** the delegate" in PART1[PART1.index("### 6.2 Grammar") : PART1.index("## 7. Implementer")]
    qmd1 = _section(PART1, "**L4-QMD-001**", "\n**L4-")
    assert "Answered by:" in qmd1 and "L4-DLG-006" in qmd1
    qmd3 = _section(PART1, "**L4-QMD-003**", "\n**L4-")
    assert "Escalated by:" in qmd3 and "refused as structure" in qmd3
    qmd9 = _section(PART1, "**L4-QMD-009**", "\n**L4-")
    for needle in (
        "the delegate when the ledger",
        "delegate_override",
        "by: human | agent | clarifier | delegate",
        "no ledger",
    ):
        assert needle in qmd9, needle
    assert "agent_override" in qmd9
    avl = _section(PART1, "**L4-AVL-010**", "\n**L4-")
    assert "`delegate`" in avl and "L4-DLG-013" in avl
    clr2 = _section(PART1, "**L4-CLR-002**", "\n**L4-")
    assert "the delegate" in clr2 and "after the clarifier" in clr2
    clr4 = _section(PART1, "**L4-CLR-004**", "\n**L4-")
    for needle in ("l4:needs-person", "Needs a person (the delegate escalated)", "Answered by the delegate"):
        assert needle in clr4, needle
    clr6 = _section(PART1, "**L4-CLR-006**", "\n**L4-")
    assert 'by="human|agent|clarifier|delegate"' in clr6
    ver = _section(PART1, "**L4-VER-051", "\n**L4-")
    assert "delegate_override" in ver and "accepted by the delegate (<model> via <cli>) through Q-NNN" in ver
    y12 = _section(PART1, "**L4-YOLO-012**", "\n**L4-")
    assert "L4-DLG-007" in y12 and "plan.run_idle" not in y12 and "idle run" in y12
    y14 = _section(PART1, "**L4-YOLO-014**", "\n**L4-")
    flat = " ".join(y14.split())
    assert "plan.run_idle{unit, attempt, run}" in flat and "not count against `max_runs`" in flat


def test_the_ledger_section_names_the_delegate_records() -> None:
    ledger = _section(PART1, "### 12.1 Ledger", "### 12.2")
    for needle in (
        "delegate.asked",
        "delegate.result",
        "plan.run_idle",
        "task.unfrozen",
        "delegate_answer",
        "judges",
    ):
        assert needle in ledger, needle
    assert "`profile`" in ledger and "`model`" in ledger


def test_doctor_rows_and_the_delivery_row() -> None:
    doctor = _section(PART1, "## 15. Doctor", "\n## ")
    rows = {line.split("|")[1].strip(): line for line in doctor.splitlines() if line.startswith("| DLG-")}
    assert set(rows) == {"DLG-001", "DLG-002"}
    assert "error" in rows["DLG-001"] and "warn" in rows["DLG-002"]
    live = next(line for line in doctor.splitlines() if line.startswith("| LIVE-002"))
    assert "delegate" in live
    delivery = [line for line in PART1.splitlines() if line.startswith("| 49 | `delegate-answers` |")]
    assert len(delivery) == 1
    assert "openspec/changes/delegate-answers/" in delivery[0] and "L4-DLG-001" in delivery[0]
    assert "dummy repository" in delivery[0]
    assert "L4-YOLO-012" in PART1[PART1.index("### 12.5 ") : PART1.index("### 12.6 ")]


def test_the_runbook_has_the_procedure_the_label_and_the_plan_rules() -> None:
    runbook = _read("docs", "runbook.md")
    procedure = _section(runbook, "### 7.1 ")
    block = _section(procedure, "**Procedure: the delegate answered or escalated**", "\n**")
    for needle in (
        "Delegate:",
        "l4:needs-person",
        "Escalated by:",
        "l4 questions answer Q-NNN --unit <unit> --text",
        "delegate.enabled: false",
        "base branch",
        "By: delegate",
    ):
        assert needle in block, needle
    assert procedure.index("**Procedure: the command**") < procedure.index("**Procedure: the delegate answered")
    labels = _section(runbook, "### 10.2 ")
    row = next(line for line in labels.splitlines() if line.startswith("| `l4:needs-person`"))
    assert "delegate" in row and "Harness" in row
    waiting = _section(runbook, "### 12.4 ")
    assert "delegate" in waiting and "unit_awaiting_human" in waiting and "l4:needs-person" in waiting
    run = _section(runbook, "### 12.6 ")
    for needle in ("delegate pass", "plan.run_idle", "max_runs", "idle"):
        assert needle in run, needle
    limits = runbook[runbook.index("## 11. ") : runbook.index("## 12. ")]
    assert "read-only mode" in limits and "[U]" in limits


def test_the_yolo_guide_has_a_section_on_the_delegate() -> None:
    guide = _read("docs", "yolo-mode.md")
    block = _section(guide, "## The delegate", "\n## ")
    for needle in (
        "delegate.enabled",
        "scope",
        "read-only",
        "independence",
        "delegate.unfreeze",
        "delegate_override",
        "`merge: auto`",
        "l4:needs-person",
        "never",
        "L4-DLG-001",
    ):
        assert needle in block, needle
    assert "idle" in _section(guide, "## Limits", "\n## ")


def test_the_control_loop_page_places_the_delegate_pass() -> None:
    page = _read("docs", "control-loop.md")
    step = _section(page, "## 5. One run, step by step", "\n## ")
    assert "delegate" in step and "`delegate`" in step
    kept = _section(page, "## 6. What is kept", "\n## ")
    assert "delegate" in kept
    commands = _section(page, "## 7. What your local commands do", "\n## ")
    assert "delegate" in commands
    assert "idle" in page


def test_the_skill_references_teach_the_delegate() -> None:
    operate = _read("plugins", "l4", "skills", "l4", "references", "operate.md")
    for needle in ("delegate", "Delegate:", "l4:needs-person", "`By: delegate`", "Escalated by"):
        assert needle in operate, needle
    assert "never" in operate[operate.index("`By: delegate`") - 200 : operate.index("`By: delegate`") + 200]
    plan = _read("plugins", "l4", "skills", "l4", "references", "plan.md")
    assert "delegate.enabled" in plan and "person approves" in plan


def test_the_changelog_entry_sits_above_the_newest() -> None:
    log = _read("CHANGELOG.md")
    assert log.index("## 0.4.19 (unreleased)") < log.index("## 0.4.18 (unreleased)")
    entry = log[log.index("## 0.4.19 (unreleased)") : log.index("## 0.4.18 (unreleased)")]
    assert entry.index("### Added") < entry.index("### Changed") < entry.index("### Fixed")
    for needle in ("delegate", "roles.delegate", "l4:needs-person", "plan.run_idle", "delegate_override", "L4-DLG"):
        assert needle in entry, needle


def test_the_change_claims_only_doctor_checks_that_exist() -> None:  # review F13
    from l4.doctor.registry import REGISTRY, load_check_modules

    load_check_modules()
    known = {check.id for check in REGISTRY.checks()}
    changelog = _read("CHANGELOG.md")
    unreleased = changelog[changelog.index("## 0.4.19") : changelog.index("## 0.4.18")]
    for text in (unreleased, _change_text(), _section(SPEC, "**L4-CLR-004", level="**L4-CLR-005")):
        claimed = set(re.findall(r"\b(?:doctor|Doctor)[ `]+([A-Z]+-\d{3})", text))
        assert claimed <= known, sorted(claimed - known)
