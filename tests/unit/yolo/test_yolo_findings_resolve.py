"""Findings: the `Resolve:` text per criterion (review-resolution 1.6, design D1)."""

import pytest

from l4.yolo import findings as fnd


def resolve(
    criterion,
    text="a finding",
    *,
    subject="openspec:a",
    folder="openspec/changes/a",
    batch="b1",
    depends_on=(),
    known=("openspec:a", "openspec:b", "openspec:ab"),
):
    return fnd.resolve(
        "p1",
        "staging",
        subject,
        {"criterion": criterion, "severity": "major", "text": text},
        folder=folder,
        batch=batch,
        depends_on=depends_on,
        known_units=known,
    )


def test_outcome():
    assert (
        resolve("outcome")
        == "State the observable result in openspec/changes/a/proposal.md or the spec, not only the work."
    )


def test_testability_names_the_spec_files():
    line = resolve("testability")
    assert line.startswith("Give the scenario concrete inputs and outputs in openspec/changes/a/specs/*/spec.md")
    assert "tolerance or an injected clock" in line


def test_a_kiro_units_testability_line_names_requirements_md():
    line = resolve("testability", subject="kiro:y", folder=".kiro/specs/y")
    assert ".kiro/specs/y/requirements.md" in line and "spec.md" not in line
    assert ".kiro/specs/y/requirements.md" in resolve("outcome", subject="kiro:y", folder=".kiro/specs/y")


def test_interfaces():
    assert resolve("interfaces").startswith("Fix names, signatures, data shapes and error values in the spec")


def test_failure_cases():
    assert resolve("failure_cases") == (
        "State what happens on bad input, absence, concurrency and a failing dependency."
    )


def test_feasibility():
    line = resolve("feasibility")
    assert line.startswith("Split the unit") and "a person, a secret or a service" in line


def test_duplicate_scope():
    assert resolve("duplicate_scope") == "Remove the overlap from one of the units the finding names."


def test_contradiction():
    assert resolve("contradiction") == ("Make the two statements agree, in this folder or in a prerequisite's.")


def test_missing_dependency_names_the_entry_to_add():
    line = resolve("missing_dependency", 'needs the result of "openspec:b" first', subject="openspec:a")
    assert 'add "openspec:b" to depends_on of openspec:a in .l4/plans/p1.json (batch b1)' in line


def test_scn_yolo_46_a_missing_dependency_names_the_plan_entry_to_add():
    line = resolve("missing_dependency", "it uses openspec:a, which is not a prerequisite", subject="openspec:b")
    assert 'add "openspec:a" to depends_on of openspec:b in .l4/plans/p1.json (batch b1)' in line


def test_an_id_already_in_depends_on_gets_no_suggestion():
    line = resolve("missing_dependency", "it uses openspec:b", subject="openspec:a", depends_on=("openspec:b",))
    assert "add " not in line.split("depends_on")[0] and 'add "openspec:b"' not in line
    assert line.startswith("Add a `depends_on` to `openspec:a` in `.l4/plans/p1.json` (batch `b1`)")


def test_an_unknown_id_gets_no_suggestion():
    line = resolve("missing_dependency", "it uses openspec:zzz", subject="openspec:a")
    assert 'add "' not in line and line.startswith("Add a `depends_on` to")


def test_an_id_must_appear_verbatim_not_as_part_of_another():
    line = resolve(
        "missing_dependency",
        "it uses openspec:ab",
        subject="openspec:b",
        known=("openspec:a", "openspec:ab", "openspec:b"),
    )
    assert 'add "openspec:ab"' in line and 'add "openspec:a"' not in line


def test_the_unit_itself_is_never_suggested():
    line = resolve("missing_dependency", "openspec:a needs more", subject="openspec:a")
    assert 'add "' not in line


def test_two_ids_are_both_suggested():
    line = resolve(
        "missing_dependency",
        "it needs openspec:a and openspec:b",
        subject="openspec:c",
        known=("openspec:a", "openspec:b", "openspec:c"),
    )
    assert '"openspec:a"' in line and '"openspec:b"' in line and "openspec:c in .l4/plans/p1.json" in line


def test_a_batch_without_a_batch_name_leaves_the_batch_out():
    line = resolve("missing_dependency", "it uses openspec:b", subject="openspec:a", batch=None)
    assert "(batch" not in line and 'add "openspec:b"' in line


def test_batch_acceptance():
    assert resolve("batch_acceptance", subject="batch:b1", folder=None).startswith(
        "State the batch outcome in a unit's proposal, or give batch b1 an acceptance profile that can show it"
    )


def test_material_is_the_findings_own_text():
    text = "material_cut: x.md has 30000 characters; shorten the file"
    assert resolve("material", text) == text


@pytest.mark.parametrize("criterion", ["schema", "unit_missing", "completeness"])
def test_harness_findings_say_that_no_review_happened(criterion):
    line = resolve(criterion)
    assert "No review happened" in line and "l4 yolo review p1" in line


def test_unit_missing_says_to_push_the_folder_or_remove_the_unit():
    line = resolve("unit_missing")
    assert "push the folder" in line and "staging" in line and ".l4/plans/p1.json" in line


def test_verdict_finding_says_how_to_ask_again():
    line = resolve("verdict", subject="openspec:a")
    assert "named no finding" in line and "--fresh openspec:a" in line


def test_an_unknown_criterion_gets_a_general_line():
    assert resolve("something_new").startswith("Read the finding")


def test_a_missing_folder_is_not_printed_as_none():
    for criterion in ("outcome", "testability"):
        assert "None" not in resolve(criterion, folder=None)


def test_the_general_line_adds_a_dependency_only_on_a_unit_of_the_plan():
    """review-resolution 4.2b: code that is already on the base branch is no unit to depend on."""
    line = resolve("missing_dependency", "it uses a helper", subject="openspec:a")
    assert "only on a unit of the plan that introduces it" in line
    assert "if the code already exists on the base branch, say so in the spec instead" in line
    assert "Add the unit it needs" not in line
