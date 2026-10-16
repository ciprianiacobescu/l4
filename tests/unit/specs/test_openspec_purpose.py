"""L4-ADO-007 / L4-OSP-007: a delta for a capability new to `openspec/specs/` needs a Purpose of 50+ characters."""

from pathlib import Path

from l4.specs.openspec import MIN_PURPOSE_CHARS, purpose_issues

LONG = "What the dreaming capability guarantees: memories are linked and contradictions are resolved."
BODY = "## ADDED Requirements\n\n### Requirement: Dream\nText.\n\n#### Scenario: One\n- **WHEN** a\n- **THEN** b\n"


def delta(unit: Path, capability: str, text: str) -> None:
    folder = unit / "specs" / capability
    folder.mkdir(parents=True)
    (folder / "spec.md").write_text(text)


def base(root: Path, capability: str) -> None:
    folder = root / capability
    folder.mkdir(parents=True)
    (folder / "spec.md").write_text("# x\n\n## Purpose\nTBD\n\n## Requirements\n")


def test_a_new_capability_without_a_purpose_is_one_error(tmp_path: Path):  # SCN-ADO-21
    unit, root = tmp_path / "change", tmp_path / "specs"
    delta(unit, "dreaming", BODY)
    (issue,) = purpose_issues(unit, root)
    assert issue.level == "ERROR" and issue.path == "specs/dreaming/spec.md"
    assert "Purpose" in issue.message and "dreaming" in issue.message and str(MIN_PURPOSE_CHARS) in issue.message


def test_a_short_purpose_is_an_error_and_a_long_one_is_not(tmp_path: Path):
    unit, root = tmp_path / "change", tmp_path / "specs"
    delta(unit, "short", f"## Purpose\nToo short.\n\n{BODY}")
    delta(unit, "long", f"## Purpose\n{LONG}\n\n{BODY}")
    assert [i.path for i in purpose_issues(unit, root)] == ["specs/short/spec.md"]


def test_the_purpose_counts_without_the_line_breaks_around_it(tmp_path: Path):
    unit, root = tmp_path / "change", tmp_path / "specs"
    delta(unit, "edge", f"## Purpose\n{'x' * 49}\n\n{BODY}")
    delta(unit, "ok", f"## Purpose\n{'x' * 50}\n\n{BODY}")
    assert [i.path for i in purpose_issues(unit, root)] == ["specs/edge/spec.md"]


def test_a_capability_that_exists_in_the_base_needs_no_purpose(tmp_path: Path):
    unit, root = tmp_path / "change", tmp_path / "specs"
    delta(unit, "dreaming", BODY)
    base(root, "dreaming")
    assert purpose_issues(unit, root) == []


def test_one_error_per_delta_in_name_order_and_no_specs_folder_is_fine(tmp_path: Path):
    unit, root = tmp_path / "change", tmp_path / "specs"
    unit.mkdir()
    assert purpose_issues(unit, root) == []
    delta(unit, "b-cap", BODY)
    delta(unit, "a-cap", BODY)
    assert [i.path for i in purpose_issues(unit, root)] == ["specs/a-cap/spec.md", "specs/b-cap/spec.md"]


def _raw(tmp_path: Path, text: str) -> list:
    unit, root = tmp_path / "change", tmp_path / "specs"
    folder = unit / "specs" / "dreaming"
    folder.mkdir(parents=True)
    (folder / "spec.md").write_bytes(text.encode())
    return purpose_issues(unit, root)


def test_crlf_bom_and_lower_case_heading_read_like_openspec(tmp_path: Path):
    body = f"## Purpose\n{LONG}\n\n{BODY}"
    assert _raw(tmp_path / "a", body.replace("\n", "\r\n")) == []
    assert _raw(tmp_path / "b", "﻿" + body) == []
    assert _raw(tmp_path / "c", body.replace("## Purpose", "## purpose")) == []
    assert _raw(tmp_path / "d", body.replace("## Purpose", "##  PURPOSE  ")) == []


def test_a_purpose_that_is_only_a_comment_or_blank_is_empty(tmp_path: Path):
    comment = "<!-- " + "x" * 80 + " -->"
    assert len(_raw(tmp_path / "a", f"## Purpose\n{comment}\n\n{BODY}")) == 1
    assert len(_raw(tmp_path / "b", f"## Purpose\n<!--\n{'x' * 80}\n-->\n\n{BODY}")) == 1
    assert len(_raw(tmp_path / "c", f"## Purpose\n   \n\n{BODY}")) == 1
    assert _raw(tmp_path / "d", f"## Purpose\n<!-- note -->\n{LONG}\n\n{BODY}") == []
