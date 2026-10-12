from pathlib import Path

import pytest

from l4.specs.base import CriterionIdCollision, Framework
from l4.specs.criteria import kiro_criteria
from l4.specs.fixmark import FixMarker, write_fix_marker

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "specs" / "kiro" / "user-auth"


def test_ears_lines_are_numbered_per_requirement():
    criteria = kiro_criteria(FIXTURE)
    assert [c.alias for c in criteria] == ["Req 1.1", "Req 1.2", "Req 2.1", "Req 2.2", "Req 2.3"]
    assert all(c.framework is Framework.KIRO and c.source_path == "requirements.md" for c in criteria)
    assert criteria[1].text == (
        "WHEN the user submits a wrong password, THE System SHALL show an error and keep the session closed."
    )  # a continuation line is part of the criterion
    assert criteria[0].requirement == "Sign in"
    assert criteria[2].requirement.startswith("As a user, I want to sign out")  # no title: the user story
    assert criteria[0].source_line == 15
    assert all(c.id.startswith("C-") and len(c.id) == 10 for c in criteria)


def test_kiro_ids_survive_criterion_insertion(tmp_path):
    spec = tmp_path / "user-auth"
    spec.mkdir()
    original = (FIXTURE / "requirements.md").read_text()
    (spec / "requirements.md").write_text(original)
    before = {c.text: (c.id, c.alias) for c in kiro_criteria(spec)}
    inserted = original.replace(
        "2. IF the session already ended",
        "2. WHEN the user signs out twice, THE System SHALL stay signed out.\n3. IF the session already ended",
    ).replace("3. WHILE offline", "4. WHILE offline")  # SCN-CRT-05: a human renumbers the later ones
    (spec / "requirements.md").write_text(inserted)
    after = {c.text: (c.id, c.alias) for c in kiro_criteria(spec)}
    for text, (cid, _) in before.items():
        assert after[text][0] == cid
    assert before["IF the session already ended, THEN THE System SHALL ignore the request."][1] == "Req 2.2"
    assert after["IF the session already ended, THEN THE System SHALL ignore the request."][1] == "Req 2.3"
    new = set(after) - set(before)
    assert len(new) == 1
    assert after[new.pop()][0] not in {cid for cid, _ in before.values()}


def test_bugfix_spec_uses_its_own_numbers(tmp_path):
    spec = tmp_path / "login-fix-1"
    spec.mkdir()
    (spec / "bugfix.md").write_text(
        "# Bugfix Requirements Document\n\n## Bug Analysis\n\n### Current Behavior (Defect)\n\n"
        "1.1 WHEN a user logs in twice THEN the system opens two sessions\n\n"
        "### Expected Behavior (Correct)\n\n2.1 WHEN a user logs in twice THEN the system SHALL reuse the session\n\n"
        "### Unchanged Behavior (Regression Prevention)\n\n"
        "3.1 WHEN a user logs in once THEN the system SHALL CONTINUE TO work\n"
    )
    criteria = kiro_criteria(spec)
    assert [(c.alias, c.requirement) for c in criteria] == [  # the 1.n lines are the defect, not a criterion
        ("Req 2.1", "Expected Behavior (Correct)"),
        ("Req 3.1", "Unchanged Behavior (Regression Prevention)"),
    ]


def test_missing_files_give_no_criteria_and_duplicates_collide(tmp_path):
    spec = tmp_path / "x"
    spec.mkdir()
    assert kiro_criteria(spec) == []
    (spec / "requirements.md").write_text(
        "### Requirement 1\n#### Acceptance Criteria\n1. WHEN a THEN b\n2. WHEN  a   THEN b\n"
    )
    with pytest.raises(CriterionIdCollision):
        kiro_criteria(spec)


def test_fenced_examples_are_not_criteria(tmp_path):
    spec = tmp_path / "x"
    spec.mkdir()
    (spec / "requirements.md").write_text(
        "### Requirement 1\n#### Acceptance Criteria\n```\n1. WHEN fenced THEN ignored\n```\n1. WHEN real THEN kept\n"
    )
    assert [c.text for c in kiro_criteria(spec)] == ["WHEN real THEN kept"]


SEEDS = Path(__file__).resolve().parents[2] / "fixtures" / "specs" / "kiro-seeds"


def test_seed_specs_keep_their_ids_and_read_every_form():
    """Pinned over the H2/H3 seed requirements: the id hashes the text, so `1.` and `1.1.` give one id (L4-CRT-001)."""
    got = {name: [(c.alias, c.id) for c in kiro_criteria(SEEDS / name)] for name in ("h2-A", "h3-A", "h3-A1")}
    assert [a for a, _ in got["h2-A"]] == ["Req 1.1", "Req 1.2", "Req 1.3", "Req 2.1", "Req 2.2", "Req 2.3"]
    assert [a for a, _ in got["h3-A"]] == ["Req 1.1", "Req 1.2", "Req 1.3", "Req 2.1", "Req 2.2"]
    assert [a for a, _ in got["h3-A1"]] == ["Req 1.1", "Req 1.2", "Req 1.3", "Req 2.1", "Req 2.2"]
    assert [i for _, i in got["h2-A"]] == [
        "C-ea32f9f6", "C-de8189e0", "C-6512fdc2", "C-616450a0", "C-e0c3737a", "C-9ce5721d",
    ]  # fmt: skip
    assert [i for _, i in got["h3-A"]] == ["C-1039cd56", "C-38f1a92d", "C-0f5d8f71", "C-21d7f11b", "C-d3a5c776"]


@pytest.mark.parametrize(
    "lines",
    [
        ["1.1. WHEN a THEN b", "1.2. WHEN c THEN d"],
        ["1.1 WHEN a THEN b", "1.2 WHEN c THEN d"],
        ["1.1) WHEN a THEN b", "1.2) WHEN c THEN d"],
        ["1. WHEN a THEN b", "2. WHEN c THEN d"],
        ["1) WHEN a THEN b", "2) WHEN c THEN d"],
        ["- 1.1. WHEN a THEN b", "- 1.2. WHEN c THEN d"],
    ],
)
def test_numbered_forms_give_one_set_of_aliases_and_ids(tmp_path, lines):
    spec = tmp_path / "x"
    spec.mkdir()
    (spec / "requirements.md").write_text("### Requirement 1\n#### Acceptance Criteria\n" + "\n".join(lines) + "\n")
    got = kiro_criteria(spec)
    assert [c.alias for c in got] == ["Req 1.1", "Req 1.2"]
    assert [c.text for c in got] == ["WHEN a THEN b", "WHEN c THEN d"]
    (spec / "requirements.md").write_text(
        "### Requirement 1\n#### Acceptance Criteria\n1. WHEN a THEN b\n2. WHEN c THEN d\n"
    )
    assert [c.id for c in kiro_criteria(spec)] == [c.id for c in got]  # the form never moves an id


def test_a_decimal_at_the_start_of_a_continuation_line_is_not_a_criterion(tmp_path):
    spec = tmp_path / "x"
    spec.mkdir()
    (spec / "requirements.md").write_text(
        "### Requirement 1\n#### Acceptance Criteria\n1. WHEN the subtotal is\n   19.99 THEN return 2.00\n"
    )
    assert [c.text for c in kiro_criteria(spec)] == ["WHEN the subtotal is 19.99 THEN return 2.00"]


def test_a_requirement_main_already_read_keeps_its_criteria_exactly(tmp_path):
    """A requirement with a plain `N.` item was read before the dotted forms existed: its sub-numbered lines stay part
    of the criterion they continue (or stay ignored at column zero), so no id and no alias moves (L4-CRT-001)."""
    spec = tmp_path / "u"
    spec.mkdir()
    (spec / "requirements.md").write_text(
        "### Requirement 1\n#### Acceptance Criteria\n1. WHEN x THEN the system SHALL:\n   1.1 show a\n   1.2 show b\n"
        "2. WHEN y THEN z\n1.5 note at column zero\n3. WHEN w THEN v\n"
    )
    got = [(c.alias, c.id, c.text) for c in kiro_criteria(spec)]
    assert got == [  # what the parser before the dotted forms read, byte for byte
        ("Req 1.1", "C-85d93b03", "WHEN x THEN the system SHALL: 1.1 show a 1.2 show b"),
        ("Req 1.2", "C-1f87ccc2", "WHEN y THEN z"),
        ("Req 1.3", "C-dc09dc14", "WHEN w THEN v"),
    ]


def test_the_dotted_form_counts_only_in_a_requirement_with_no_plain_item(tmp_path):
    spec = tmp_path / "u"
    spec.mkdir()
    (spec / "requirements.md").write_text(
        "### Requirement 1\n#### Acceptance Criteria\n1.1. WHEN a THEN the system SHALL:\n   1. do x\n   2. do y\n"
        "1.2. WHEN b THEN c\n\n### Requirement 2\n#### Acceptance Criteria\n2.1. WHEN d THEN e\n2.2. WHEN f THEN g\n"
    )
    got = [(c.alias, c.id, c.text) for c in kiro_criteria(spec)]
    assert got == [
        ("Req 1.1", "C-cf55f794", "do x"),  # read before as they are now: requirement 1 has plain items
        ("Req 1.2", "C-0a17461b", "do y"),
        ("Req 2.1", "C-c4518a99", "WHEN d THEN e"),  # requirement 2 read nothing before: its dotted items count
        ("Req 2.2", "C-d524c1ca", "WHEN f THEN g"),
    ]


BUGFIX = (
    "# Bugfix Requirements Document\n\n## Bug Analysis\n\n### Current Behavior (Defect)\n\n"
    "1.1 WHEN a user logs in twice THEN the system opens two sessions\n\n"
    "### Expected Behavior (Correct)\n\n"
    "2.1 WHEN a user logs in twice THEN the system SHALL reuse the session (parent Req 1.2, C-1a2b3c4d)\n"
    "2.2 WHEN a user logs in from a second tab THEN the system SHALL reuse the session\n\n"
    "### Unchanged Behavior (Regression Prevention)\n\n"
    "3.1 WHEN any other acceptance criterion of login is exercised THEN the system SHALL CONTINUE TO satisfy it\n"
)


def fix_unit(where: Path, *, marker: bool = True) -> Path:
    spec = where / "login-fix-1"
    spec.mkdir()
    (spec / "bugfix.md").write_text(BUGFIX)
    if marker:
        write_fix_marker(spec, FixMarker("kiro:login", 1, ("F-aaaaaaaa",), ()))
    return spec


def test_the_defect_items_are_no_criteria_and_the_expected_and_unchanged_items_are(tmp_path):
    """L4-FBK-008, SCN-FBK-20: 2.n and 3.n are read, 1.n is not."""
    criteria = kiro_criteria(fix_unit(tmp_path))
    assert [c.alias for c in criteria] == ["Req 2.1", "Req 2.2", "Req 3.1"]


def test_an_expected_item_that_carries_a_parent_id_is_read_as_that_criterion(tmp_path):
    """SCN-FBK-20: the id is the parent's, the alias stays the fix unit's own number (tasks cite `2.1`)."""
    first, second, third = kiro_criteria(fix_unit(tmp_path))
    assert (first.id, first.alias) == ("C-1a2b3c4d", "Req 2.1")
    assert second.id != "C-1a2b3c4d" and third.id != "C-1a2b3c4d"
    assert first.text.endswith("(parent Req 1.2, C-1a2b3c4d)")


def test_a_parent_id_counts_only_in_a_fix_unit_and_only_on_an_expected_item(tmp_path):
    """The harness marker is what makes a folder a fix unit: a person's bugfix spec cannot claim another id."""
    (tmp_path / "plain").mkdir()
    plain = kiro_criteria(fix_unit(tmp_path / "plain", marker=False))
    assert "C-1a2b3c4d" not in {c.id for c in plain}
    (tmp_path / "fix").mkdir()
    spec = fix_unit(tmp_path / "fix")
    unchanged = "satisfy it"
    (spec / "bugfix.md").write_text(BUGFIX.replace(unchanged, unchanged + " (parent Req 9, C-deadbeef)"))
    assert "C-deadbeef" not in {c.id for c in kiro_criteria(spec)}


def test_two_expected_items_that_restate_the_same_parent_criterion_collide(tmp_path):
    spec = fix_unit(tmp_path)
    again = "2.2 WHEN again THEN the system SHALL reuse it (parent Req 1.2, C-1a2b3c4d)"
    second = "2.2 WHEN a user logs in from a second tab THEN the system SHALL reuse the session"
    (spec / "bugfix.md").write_text(BUGFIX.replace(second, again))
    with pytest.raises(CriterionIdCollision):
        kiro_criteria(spec)
