"""The resolution path of a plan review is documented where a person and an agent look for it (L4-YOLO-029)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = text.find("\n### ", start + len(heading))
    return text[start : following if following != -1 else len(text)]


def test_the_runbook_has_the_resolution_path() -> None:  # SCN-YOLO-70
    runbook = (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")
    procedure = _section(runbook, "### 12.2a ")
    for needle in (
        "l4 yolo findings <plan-id>",
        "l4 yolo review <plan-id> --worktree",
        "--record",
        "l4 yolo accept <plan-id> <subject> --reason",
        "l4 yolo activate <plan-id>",
        "accept_after_rounds",
        "accept_by_agents",
        "bwrap",
    ):
        assert needle in procedure, needle
    assert "accepted_finding_open" in _section(runbook, "### 12.2b ")
    assert "accepted_finding_open" in _section(runbook, "### 12.4 ")
    assert "12.2a" in _section(runbook, "### 12.2 ")


def test_the_yolo_guide_describes_the_review_rules() -> None:
    guide = (ROOT / "docs" / "yolo-mode.md").read_text(encoding="utf-8")
    review = guide[guide.index("## The review") : guide.index("## What runs in each CI run")]
    for needle in ("l4 yolo findings", "--worktree", "max_dependency_chars", "check marks", "l4 yolo accept"):
        assert needle.lower() in review.lower(), needle


def test_the_plan_reference_tells_an_agent_to_iterate_and_not_to_accept() -> None:  # SCN-YOLO-70
    skill = ROOT / "plugins" / "l4" / "skills" / "l4" / "references"
    plan = (skill / "plan.md").read_text(encoding="utf-8")
    for needle in ("--worktree", "--record", "l4 yolo findings", "accept_by_agents", "validate_plan.py"):
        assert needle in plan, needle
    operate = (skill / "operate.md").read_text(encoding="utf-8")
    for needle in ("l4 yolo findings", "l4 yolo accept", "--worktree", "--record", "--fresh"):
        assert needle in operate, needle
