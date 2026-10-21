"""L4-ADO-008: the intake hint for an archive refusal, and the errors of a report kept in full (SCN-ADO-24)."""

from l4.specs.base import ValidationIssue, ValidationReport
from l4.specs.openspec import ARCHIVE_REFUSAL, intake_errors, intake_hint

MISSING = (
    f"{ARCHIVE_REFUSAL} dreaming: target spec does not exist; only ADDED requirements are allowed for new specs. "
    "MODIFIED and RENAMED operations require an existing spec."
)
OMITTED = (
    'MODIFIED "Fusion" omits scenario(s) the current spec still has: "One list empty". '
    "Copy the omitted scenarios into the MODIFIED block"
)


def test_the_hint_names_the_capability_and_the_target():
    hint = intake_hint(MISSING, "staging")
    assert "`openspec/specs/dreaming/spec.md` is not on `staging`" in hint
    assert "archive the change that creates `dreaming` first" in hint
    assert "`## ADDED Requirements` (with a `## Purpose`)" in hint
    assert "A unit cannot modify what another unit of the same plan only adds" in hint


def test_other_messages_get_no_hint():
    assert intake_hint(OMITTED, "staging") == ""
    assert intake_hint(f"{ARCHIVE_REFUSAL} greeting MODIFIED failed for header X - not found", "staging") == ""
    assert intake_hint("target spec does not exist", "staging") == ""  # not an archive refusal


def test_two_errors_are_kept_in_full_with_the_hint_after_the_refusal():  # SCN-ADO-24
    report = ValidationReport(
        False,
        (
            ValidationIssue("ERROR", "specs/fusion/spec.md", OMITTED, None),
            ValidationIssue("WARNING", "x", "ignored", None),
            ValidationIssue("ERROR", "specs", MISSING, 7),
        ),
    )
    lines = intake_errors(report, "staging")
    assert len(lines) == 2
    assert lines[0] == f"specs/fusion/spec.md: {OMITTED}"
    assert lines[1].startswith(f"specs:7: {MISSING}") and lines[1].endswith(intake_hint(MISSING, "staging"))


def test_each_error_is_cut_at_600_characters_and_never_as_a_whole():
    report = ValidationReport(False, tuple(ValidationIssue("ERROR", "p", "x" * 900, None) for _ in range(5)))
    lines = intake_errors(report, "staging")
    assert len(lines) == 5 and all(len(line) == len("p: ") + 600 for line in lines)
