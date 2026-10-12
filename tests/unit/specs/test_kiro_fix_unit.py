"""Kiro fix units are bugfix specs (L4-FBK-008, L4-KSP-005; SCN-FBK-20, SCN-FBK-21)."""

import json
from pathlib import Path

import pytest

from l4.specs.base import (
    DeltaRequirement,
    DeltaScenario,
    Finding,
    FixUnitCapable,
    FixUnitExists,
    FixUnitInvalid,
    SpecDelta,
    SpecError,
    UnitRef,
)
from l4.specs.criteria import kiro_criteria
from l4.specs.fixmark import chore_findings, read_fix_marker
from l4.specs.kiro import KiroProvider, kiro_tasks, parse_kiro_tasks

REQUIREMENTS = """# Requirements Document

## Requirements

### Requirement 1: Sign in

**User Story:** As a user, I want to sign in, so that I reach my account.

#### Acceptance Criteria

1. WHEN the user submits the right password, THE System SHALL open a session.
2. WHEN the user submits a wrong password, THE System SHALL show an error and keep the session closed.
"""
TASKS = "# Implementation Plan\n\n- [x] 1. Sign in\n  - [x] 1.1 Add `sign_in`\n    - _Requirements: 1.1, 1.2_\n"
UUID = "11111111-2222-4333-8444-555555555555"

FINDINGS = [
    Finding(("F-aaaaaaaa", "F-bbbbbbbb"), "Wrong password opens a session", "the check is inverted", "major", ()),
    Finding(("F-cccccccc",), "Undeclared suppression", "a noqa in src/x.py", "major", chore=True),
]


@pytest.fixture
def parent(tmp_path: Path) -> tuple[Path, UnitRef]:
    repo = tmp_path / "repo"
    spec = repo / ".kiro" / "specs" / "login"
    spec.mkdir(parents=True)
    (spec / "requirements.md").write_text(REQUIREMENTS)
    (spec / "design.md").write_text("# Design\n")
    (spec / "tasks.md").write_text(TASKS)
    return repo, KiroProvider(repo).list_units()[0]


def provider_of(repo: Path) -> KiroProvider:
    return KiroProvider(repo, uuid_factory=lambda: UUID)


def second_criterion(ref: UnitRef) -> str:
    return kiro_criteria(ref.path)[1].id


def with_criterion(ref: UnitRef) -> list[Finding]:
    return [
        Finding(
            ("F-aaaaaaaa", "F-bbbbbbbb"),
            "Wrong password opens a session",
            "inverted",
            "major",
            (second_criterion(ref),),
        ),
        FINDINGS[1],
    ]


def test_the_provider_is_fix_unit_capable():
    assert isinstance(KiroProvider(Path(".")), FixUnitCapable)


def test_a_failed_criterion_gets_a_bugfix_spec_of_five_files(parent):
    """SCN-FBK-20: `2.1` restates the parent criterion with its alias and id."""
    repo, ref = parent
    cid = second_criterion(ref)
    fix = provider_of(repo).create_fix_unit(ref, 1, with_criterion(ref), None)
    folder = repo / ".kiro" / "specs" / "login-fix-1"
    assert fix.id == "kiro:login-fix-1" and fix.path == folder
    assert sorted(p.name for p in folder.iterdir()) == [".config.kiro", ".l4", "bugfix.md", "design.md", "tasks.md"]
    assert (folder / ".l4" / "fix.json").is_file()
    bugfix = (folder / "bugfix.md").read_text()
    assert bugfix.startswith("# Bugfix Requirements Document\n\n## Bug Analysis\n\n### Current Behavior (Defect)\n")
    wrong = "WHEN the user submits a wrong password, THE System SHALL show an error and keep the session closed."
    assert f"2.1 {wrong} (parent Req 1.2, {cid})" in bugfix
    assert "1.1 Wrong password opens a session: inverted (F-aaaaaaaa, F-bbbbbbbb)" in bugfix
    assert "1.2 Undeclared suppression: a noqa in src/x.py (F-cccccccc)" in bugfix
    assert (
        "3.1 WHEN any other acceptance criterion of login is exercised THEN the system SHALL CONTINUE TO satisfy it"
        in bugfix
    )
    assert [c.alias for c in kiro_criteria(folder)] == ["Req 2.1", "Req 3.1"]
    assert kiro_criteria(folder)[0].id == cid  # the parent's id: the family counts it once
    config = json.loads((folder / ".config.kiro").read_text())
    assert config == {"specId": UUID, "workflowType": "requirements-first", "specType": "bugfix"}
    assert provider_of(repo).validate(fix, strict=True).valid


def test_tasks_are_kiro_leaves_that_cite_their_items_and_chores_are_tagged(parent):
    repo, ref = parent
    cid = second_criterion(ref)
    fix = provider_of(repo).create_fix_unit(ref, 1, with_criterion(ref), None)
    text = (fix.path / "tasks.md").read_text()
    tasks = kiro_tasks(text.encode())
    leaves = [t for t in tasks if t.depth > 0]
    assert [(t.key, t.links) for t in leaves] == [("1.1", ("2.1",)), ("1.2", ("3.1",))]
    assert f"1.1 Wrong password opens a session (F-aaaaaaaa, F-bbbbbbbb; {cid})" in text
    assert "1.2 [chore] Undeclared suppression (F-cccccccc)" in text
    assert text.count("- _Requirements:") == 2 and "    - _Requirements: 2.1_" in text
    assert "## Task Dependency Graph" in text
    assert [t.wave for t in tasks if t.key in {"1.1", "1.2"}] == [0, 0]
    marker = read_fix_marker(fix.path)
    assert marker is not None
    assert (marker.parent, marker.round, marker.chores) == ("kiro:login", 1, ("F-cccccccc",))
    assert marker.findings == ("F-aaaaaaaa", "F-bbbbbbbb", "F-cccccccc")
    assert chore_findings(fix.path, leaves[1].title) == ("F-cccccccc",)
    assert chore_findings(fix.path, leaves[0].title) == ()


def test_design_md_lists_the_findings_with_the_decisions_first(parent):
    repo, ref = parent
    decided = "Decided by human in Q-001: reject, the code is wrong. the check is inverted"
    findings = [Finding(("F-aaaaaaaa",), "Wrong password", decided, "major", (second_criterion(ref),))]
    fix = provider_of(repo).create_fix_unit(ref, 1, findings, None)
    design = (fix.path / "design.md").read_text()
    assert design.startswith("# Design Document\n\n## Overview\n")
    assert "login" in design and "F-aaaaaaaa" in design
    bugfix = (fix.path / "bugfix.md").read_text()
    assert (
        "1.1 Decided by human in Q-001: reject, the code is wrong. the check is inverted (Wrong password; F-aaaaaaaa)"
        in bugfix
    )


def test_a_decision_is_kept_whole_and_one_line(parent):
    repo, ref = parent
    decision = "Decided by human in Q-001: " + "x" * 3000 + ". "
    findings = [
        Finding(("F-aaaaaaaa",), "T\n\n## heading", decision + "tail\n\n1.9 sneaky", "major", (second_criterion(ref),))
    ]
    fix = provider_of(repo).create_fix_unit(ref, 1, findings, None)
    bugfix = (fix.path / "bugfix.md").read_text()
    assert "x" * 3000 in bugfix
    assert "\n## heading" not in bugfix and "\n1.9 sneaky" not in bugfix
    assert [c.alias for c in kiro_criteria(fix.path)] == ["Req 2.1", "Req 3.1"]


def test_scenarios_become_expected_items_and_preservation_scenarios_become_unchanged_items(parent):
    repo, ref = parent
    delta = SpecDelta(
        (
            DeltaRequirement(
                "login",
                "Sign in — regression 1",
                (
                    DeltaScenario(
                        "Blank", "- **WHEN** the password is blank\n- **THEN** sign_in refuses", "F-aaaaaaaa"
                    ),
                    DeltaScenario(
                        "Unset",
                        "- **WHEN** LOGIN_URL is not set\n- **THEN** the system SHALL CONTINUE TO behave as before",
                        "F-bbbbbbbb",
                    ),
                ),
            ),
        )
    )
    findings = [
        Finding(("F-aaaaaaaa",), "Blank password", "x", "major", ()),
        Finding(("F-bbbbbbbb",), "Env override", "y", "major", ()),
    ]
    fix = provider_of(repo).create_fix_unit(ref, 1, findings, delta)
    bugfix = (fix.path / "bugfix.md").read_text()
    assert "2.1 WHEN the password is blank THEN sign_in refuses" in bugfix
    assert "3.2 WHEN LOGIN_URL is not set THEN the system SHALL CONTINUE TO behave as before" in bugfix
    assert "3.1 WHEN any other acceptance criterion of login" in bugfix
    tasks = {t.key: t.links for t in parse_kiro_tasks((fix.path / "tasks.md").read_bytes()) if t.depth > 0}
    assert tasks == {"1.1": ("2.1",), "1.2": ("3.2",)}
    assert [c.alias for c in kiro_criteria(fix.path)] == ["Req 2.1", "Req 3.1", "Req 3.2"]


def test_a_criterion_of_an_earlier_fix_unit_is_restated_with_its_own_id(parent):
    repo, ref = parent
    provider = provider_of(repo)
    first = provider.create_fix_unit(ref, 1, with_criterion(ref), None)
    unchanged = kiro_criteria(first.path)[1].id  # fix-1's own 3.1
    again = [Finding(("F-dddddddd",), "Still broken", "z", "major", (unchanged,))]
    second = provider.create_fix_unit(ref, 2, again, None)
    restated = [c for c in kiro_criteria(second.path) if c.id == unchanged]
    assert [c.alias for c in restated] == ["Req 2.1"]
    assert "WHEN any other acceptance criterion of login" in restated[0].text


def test_an_unknown_criterion_id_still_gives_a_cited_item(parent):
    repo, ref = parent
    fix = provider_of(repo).create_fix_unit(
        ref, 1, [Finding(("F-aaaaaaaa",), "t", "d", "major", ("C-0badc0de",))], None
    )
    assert kiro_criteria(fix.path)[0].id == "C-0badc0de"
    assert parse_kiro_tasks((fix.path / "tasks.md").read_bytes())[1].links == ("2.1",)


def test_an_existing_fix_unit_is_never_overwritten_and_a_fix_unit_needs_a_finding(parent):
    repo, ref = parent
    provider = provider_of(repo)
    provider.create_fix_unit(ref, 1, FINDINGS, None)
    with pytest.raises(FixUnitExists):
        provider.create_fix_unit(ref, 1, FINDINGS, None)
    with pytest.raises(SpecError, match="at least one finding"):
        provider.create_fix_unit(ref, 2, [], None)
    assert not (repo / ".kiro" / "specs" / "login-fix-2").exists()


def test_an_invalid_fix_unit_leaves_nothing_behind(parent, monkeypatch):
    """SCN-FBK-21: tasks that cite a requirement no item has fail the provider's own validation."""
    repo, ref = parent
    import l4.specs.kiro as kiro

    monkeypatch.setattr(
        kiro,
        "_fix_tasks",
        lambda *a, **k: (
            "# Implementation Plan\n\n- [ ] 1. Fix\n  - [ ] 1.1 x (F-aaaaaaaa)\n    - _Requirements: 9.9_\n"
        ),
    )
    before = sorted(p.name for p in (repo / ".kiro" / "specs").iterdir())
    with pytest.raises(FixUnitInvalid, match="9.9"):
        provider_of(repo).create_fix_unit(ref, 1, FINDINGS, None)
    assert sorted(p.name for p in (repo / ".kiro" / "specs").iterdir()) == before
    assert not list(repo.rglob("*fix*"))
