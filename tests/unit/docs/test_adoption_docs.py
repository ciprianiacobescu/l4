"""The skill and the docs say what the adoption code does (adoption-lessons 8.x, L4-ADO-014 and L4-ADO-018)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "plugins" / "l4" / "skills" / "l4"


def test_the_spec_reference_is_short_and_linked() -> None:  # SCN-ADO-41
    spec = (SKILL / "references" / "spec.md").read_text(encoding="utf-8")
    assert len(spec.split()) <= 450
    for needle in ("## Purpose", "ADDED", "validate", "validate_plan.py", "depends_on"):
        assert needle in spec, needle
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "references/spec.md" in skill
    assert "writing a spec for L4" in skill.split("---", 2)[1]
    assert "references/spec.md" in (SKILL / "references" / "plan.md").read_text(encoding="utf-8")
