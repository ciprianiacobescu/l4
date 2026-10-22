"""The skill and the docs say what the adoption code does (adoption-lessons 8.x, L4-ADO-014 and L4-ADO-018)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "plugins" / "l4" / "skills" / "l4"


def test_the_spec_reference_is_short_and_linked() -> None:  # SCN-ADO-41
    spec = (SKILL / "references" / "spec.md").read_text(encoding="utf-8")
    assert len(spec.split()) <= 520
    for needle in ("## Purpose", "ADDED", "validate", "validate_plan.py", "depends_on"):
        assert needle in spec, needle
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "references/spec.md" in skill
    assert "writing a spec for L4" in skill.split("---", 2)[1]
    assert "references/spec.md" in (SKILL / "references" / "plan.md").read_text(encoding="utf-8")


def test_the_adoption_docs_agree_with_the_code() -> None:  # SCN-ADO-50
    adopt = (SKILL / "references" / "adopt.md").read_text(encoding="utf-8")
    for needle in ("--hold-existing", "yolo.hold", "L4_FORGE_TOKEN", "forge.token_env", ".l4-out/junit.xml", "--s1"):
        assert needle in adopt, needle
    assert "l4 yolo draft backlog" in adopt.split("On 0.4.0")[1]  # the plan is only the fallback
    assert "add the default branch" not in adopt.lower()  # `l4 setup github` does it
    quickstart = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
    assert ".l4/bin/l4 setup github" not in quickstart
    assert "default branch" in quickstart
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "is manual" not in readme and "l4 setup github" in readme
