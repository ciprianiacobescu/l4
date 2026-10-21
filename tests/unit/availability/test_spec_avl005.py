"""M1.12 line 7: SPEC L4-AVL-005 states the class rule and the skipped line, and the 3.2 sample lists the key."""

import re
from pathlib import Path

SPEC = (Path(__file__).resolve().parents[3] / "docs" / "SPEC.md").read_text(encoding="utf-8")


def requirement(rid: str) -> str:
    match = re.search(rf"^\*\*{rid}\*\*(.*?)(?=^\*\*L4-|^#)", SPEC, re.S | re.M)
    assert match, rid
    return match.group(1)


def test_avl005_names_the_classes_the_ttl_and_the_cached_line():
    text = " ".join(requirement("L4-AVL-005").split())
    for needle in (
        "auth_failure_ttl", "401", "403", "transient", "not cached", "cached Nm ago", "l4 probe --no-cache",
        "re-probed once",
    ):  # fmt: skip
        assert needle in text, needle


def test_avl007_says_a_parked_role_looks_at_a_remembered_auth_refusal_again():
    assert "remembered auth refusal" in " ".join(requirement("L4-AVL-007").split())


def test_the_sample_config_lists_auth_failure_ttl_with_its_default():
    assert re.search(r"^  auth_failure_ttl: 2m\b", SPEC, re.M)
