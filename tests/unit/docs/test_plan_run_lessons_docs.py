"""The docs of plan-run-lessons: the judge in parts, the judge-view holds, a limit of an active plan, and the hints
after an answer (L4-VER-040 to L4-VER-045, L4-YOLO-050 to L4-YOLO-055)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_the_spec_has_the_eleven_requirements_and_their_scenarios_in_order() -> None:
    spec = read("docs", "SPEC.md")
    for rid in (*[f"L4-VER-0{n}" for n in range(40, 46)], *[f"L4-YOLO-0{n}" for n in range(50, 56)]):
        assert f"**{rid} " in spec, rid
    assert spec.index("**L4-VER-018 ") < spec.index("**L4-VER-040 ") < spec.index("**L4-VER-045 ")
    assert spec.index("**L4-YOLO-035** ") < spec.index("**L4-YOLO-050 ") < spec.index("**L4-YOLO-055 ")
    for n in range(130, 145):
        assert f"#### SCN-VER-{n} " in spec, n
    for n in range(130, 144):
        assert f"#### SCN-YOLO-{n} " in spec, n
    assert spec.index("#### SCN-VER-77 ") < spec.index("#### SCN-VER-130 ") < spec.index("### 23.9.1 Human feedback")
    assert "`yolo.extend_by_agents`" in spec and "extend_by_agents: false" in spec
    assert "| 40 | `plan-run-lessons` |" in spec and "judge@10" in spec


def test_the_runbook_teaches_the_holds_the_escalation_and_the_extension() -> None:
    runbook = read("docs", "runbook.md")
    assert "#### 7.3.2 Escalated with `judge_view_rejected`" in runbook
    way = runbook.split("#### 7.3.2 ", 1)[1].split("### 7.4 ", 1)[0]
    for needle in ("l4 restart --unit", "--replace", "l4 retry --unit", "A retry alone repeats the same hold"):
        assert needle in way, needle
    assert "the diff is longer than 120000 characters" not in runbook
    first = runbook.split("### 7.1 ", 1)[1].split("### 7.2 ", 1)[0]
    assert "judge view: …" in first and "judge_view_rejected" in first
    stopped = runbook.split("### 12.3 ", 1)[1].split("### 12.4 ", 1)[0]
    assert "plan.extended" in stopped and "yolo.extend_by_agents" in stopped
    waiting = runbook.split("### 12.4 ", 1)[1].split("### 12.5 ", 1)[0]
    assert "no resume is needed" in waiting and "l4 questions answer" in waiting


def test_the_yolo_doc_and_the_skill_teach_the_extension_and_the_judge_view_hold() -> None:
    yolo = read("docs", "yolo-mode.md")
    assert "plan.extended" in yolo and "yolo.extend_by_agents" in yolo and "no resume is needed" in yolo
    operate = read("plugins", "l4", "skills", "l4", "references", "operate.md")
    assert "judge view: …" in operate and "judge_view_rejected" in operate and "yolo.extend_by_agents" in operate
    assert "yolo.extend_by_agents" in read("plugins", "l4", "skills", "l4", "references", "plan.md")


def test_the_changelog_has_an_unreleased_0_4_16_above_the_released_sections() -> None:
    changelog = read("CHANGELOG.md")
    assert changelog.index("## 0.4.16 (unreleased)") < changelog.index("## 0.4.14 (")
    head = changelog.split("## 0.4.16 (unreleased)", 1)[1].split("\n## ", 1)[0]
    for needle in ("### Added", "### Fixed", "### Changed", "judge@10", "judge_view_rejected", "plan.extended"):
        assert needle in head, needle
    assert "yolo.extend_by_agents" in head and "Lock files" in head
