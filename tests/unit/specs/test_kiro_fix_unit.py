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
    # the generic sentence is no criterion: no test could trace it, and a criterion without one fails traceability
    assert "\nThe system SHALL CONTINUE TO satisfy every other acceptance criterion of login.\n" in bugfix
    assert "3.1" not in bugfix
    assert [c.alias for c in kiro_criteria(folder)] == ["Req 2.1"]
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
    assert [(t.key, t.links) for t in leaves] == [("1.1", ("2.1",)), ("1.2", ())]
    assert f"1.1 Wrong password opens a session (F-aaaaaaaa, F-bbbbbbbb; {cid})" in text
    assert "1.2 [chore] Undeclared suppression (F-cccccccc)" in text
    assert text.count("- _Requirements:") == 1 and "    - _Requirements: 2.1_" in text  # a chore cites nothing
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
    assert [c.alias for c in kiro_criteria(fix.path)] == ["Req 2.1"]


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
    assert "3.1 WHEN LOGIN_URL is not set THEN the system SHALL CONTINUE TO behave as before" in bugfix
    assert "every other acceptance criterion of login" in bugfix and "3.2" not in bugfix
    tasks = {t.key: t.links for t in parse_kiro_tasks((fix.path / "tasks.md").read_bytes()) if t.depth > 0}
    assert tasks == {"1.1": ("2.1",), "1.2": ("3.1",)}
    assert [c.alias for c in kiro_criteria(fix.path)] == ["Req 2.1", "Req 3.1"]


def test_a_criterion_of_an_earlier_fix_unit_is_restated_with_its_own_id(parent):
    repo, ref = parent
    provider = provider_of(repo)
    unset = "- **WHEN** LOGIN_URL is not set\n- **THEN** the system SHALL CONTINUE TO behave as before"
    delta = SpecDelta((DeltaRequirement("login", "Sign in", (DeltaScenario("Unset", unset, "F-bbbbbbbb"),)),))
    first = provider.create_fix_unit(ref, 1, [Finding(("F-bbbbbbbb",), "Env", "y", "major", ())], delta)
    [own] = kiro_criteria(first.path)  # fix-1's own 3.1
    again = [Finding(("F-dddddddd",), "Still broken", "z", "major", (own.id,))]
    second = provider.create_fix_unit(ref, 2, again, None)
    restated = [c for c in kiro_criteria(second.path) if c.id == own.id]
    assert [c.alias for c in restated] == ["Req 2.1"]
    assert "WHEN LOGIN_URL is not set" in restated[0].text


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


def test_a_fix_unit_of_chores_only_has_no_criteria_and_no_requirements_line_and_still_validates(parent):
    """L4-FBK-008 (review): the generic line is no criterion; a `[chore]` leaf is TDD-exempt (SPEC-004), so a unit of
    chores alone validates strictly under `sdd.enforce`."""
    repo, ref = parent
    provider = KiroProvider(repo, uuid_factory=lambda: UUID, enforce=True)
    fix = provider.create_fix_unit(ref, 1, [FINDINGS[1]], None)
    assert kiro_criteria(fix.path) == []
    text = (fix.path / "tasks.md").read_text()
    assert "_Requirements" not in text and "1.1 [chore] Undeclared suppression (F-cccccccc)" in text
    assert provider.validate(fix, strict=True).valid and provider.leaves_without_requirements(fix) == []
    assert "Every task of this fix unit is a chore" in (fix.path / "bugfix.md").read_text()


def test_a_harness_chore_needs_no_link_even_when_the_exempt_kinds_leave_chore_out(parent):
    """The marker names the chore, so a configuration that drops `chore` from the exempt kinds cannot invalidate it; a
    person's untagged leaf in the same unit is still flagged."""
    repo, ref = parent
    provider = KiroProvider(repo, uuid_factory=lambda: UUID, enforce=True, exempt_kinds=["docs"])
    fix = provider.create_fix_unit(ref, 1, [FINDINGS[1]], None)
    assert provider.validate(fix, strict=True).valid
    path = fix.path / "tasks.md"
    path.write_text(path.read_text().replace("(F-cccccccc)", "(F-zzzzzzzz)"))  # no longer the marker's id
    assert [t.key for t in provider.leaves_without_requirements(fix)] == ["1.1"]


# --- feedback items (human-feedback 2.3, L4-FBK-005, L4-FBK-008; SCN-FBK-13, SCN-FBK-14) ------------------------------

REQUEST = "Requested by Ana, 2026-10-12T15:04:00Z in FB-001 (config, src/login.py:7-9): Read the URL from LOGIN_URL."


def feedback_finding(kind: str, **over) -> Finding:
    body = {
        "ids": ("F-feed0001",), "title": f"Feedback FB-001 ({kind}): Read the URL", "detail": "", "severity": "major",
        "chore": kind in ("refactor", "duplication", "tests"), "tests": kind == "tests",
        "refactor": kind in ("refactor", "duplication"), "item": "FB-001", "request": REQUEST,
        "code": "URL = 'http://x'\n## sneaky",
    }  # fmt: skip
    return Finding(**{**body, **over})


def test_a_config_item_is_2_n_for_the_first_scenario_and_3_n_for_the_continue_to_one(parent):
    repo, ref = parent
    delta = SpecDelta(
        (
            DeltaRequirement(
                "login",
                "Read the URL \N{EM DASH} feedback FB-001",
                (
                    DeltaScenario(
                        "LOGIN_URL is set",
                        "- **WHEN** the environment variable LOGIN_URL is set\n- **THEN** the system SHALL use it",
                        "F-feed0001",
                    ),
                    DeltaScenario(
                        "LOGIN_URL is not set",
                        "- **WHEN** LOGIN_URL is not set\n- **THEN** the system SHALL CONTINUE TO behave as before",
                        "F-feed0001",
                    ),
                ),
            ),
        )
    )
    fix = provider_of(repo).create_fix_unit(ref, 1, [feedback_finding("config", chore=False, refactor=False)], delta)
    bugfix = (fix.path / "bugfix.md").read_text()
    assert "2.1 WHEN the environment variable LOGIN_URL is set THEN the system SHALL use it" in bugfix
    assert "3.1 WHEN LOGIN_URL is not set THEN the system SHALL CONTINUE TO behave as before" in bugfix
    [leaf] = [t for t in parse_kiro_tasks((fix.path / "tasks.md").read_bytes()) if t.depth > 0]
    assert leaf.links == ("2.1", "3.1")
    assert [c.alias for c in kiro_criteria(fix.path)] == ["Req 2.1", "Req 3.1"]


def test_the_request_is_the_defect_line_and_the_code_follows_whole_on_that_line(parent):
    repo, ref = parent
    fix = provider_of(repo).create_fix_unit(ref, 1, [feedback_finding("refactor")], None)
    bugfix = (fix.path / "bugfix.md").read_text()
    defect = next(line for line in bugfix.splitlines() if line.startswith("1.1 "))
    assert defect.startswith("1.1 " + REQUEST + " Quoted code: URL = 'http://x' ## sneaky")
    assert "\n## sneaky" not in bugfix and "(Feedback FB-001 (refactor): Read the URL; F-feed0001)" in defect
    design = (fix.path / "design.md").read_text()
    assert "    URL = 'http://x'\n    ## sneaky\n" in design  # the design keeps the lines, indented
    marker = read_fix_marker(fix.path)
    assert marker is not None
    assert marker.chores == marker.refactors == ("F-feed0001",) and marker.test_chores == ()


def test_a_long_request_is_kept_whole_up_to_1200_characters(parent):
    repo, ref = parent
    text = "w" * 1200
    request = f"Requested by Ana in FB-001 (refactor, src/login.py:1): {text}"
    fix = provider_of(repo).create_fix_unit(ref, 1, [feedback_finding("refactor", request=request)], None)
    assert request in (fix.path / "bugfix.md").read_text()


def test_a_rejected_spec_gap_without_a_scenario_restates_only_its_criterion(parent):  # SCN-VER-205
    from l4.verifier.fixunit import plan_fix_unit
    from l4.verifier.types import Finding as Judged
    from l4.verifier.types import HumanVerdict, Severity, Verdict, VerifyResult
    from l4.verifier.verdicts import apply_finding_verdicts

    repo, ref = parent
    cid = second_criterion(ref)
    reason = "the criterion requires an error; the code opens a session"
    gap = Judged(
        Severity.MAJOR, "Wrong password opens a session", reason, "judge", cid, spec_gap=True,
        suggested_fix="WHEN the password is wrong THEN the command opens a session",
    )  # fmt: skip
    verdict = HumanVerdict("Q-002", gap.id, "reject", "human", reason, "x")
    verified = VerifyResult("kiro:login", 1, Verdict.FAIL, "b", "h")
    verified.findings = apply_finding_verdicts([gap], {gap.id: verdict})
    plan = plan_fix_unit(kiro_criteria(ref.path), verified, [verdict], ordinal=1, fix_minor=False)
    fix = provider_of(repo).create_fix_unit(ref, 1, plan.groups, plan.delta)
    bugfix = (fix.path / "bugfix.md").read_text()
    expected = [line for line in bugfix.splitlines() if line.startswith("2.")]
    assert len(expected) == 1 and cid in expected[0]
    tasks = (fix.path / "tasks.md").read_text()
    assert "2.1" in tasks and "2.2" not in tasks
    texts = [p.read_text() for p in fix.path.rglob("*") if p.is_file()]
    assert not any("THEN the command opens a session" in t for t in texts)


CI_DETAIL = (
    "job `ci.yml / tests` failed in step `tests` on the hand-off commit aaaaaaaaaa. Failed: FAILED "
    "tests/test_cli.py::test_help - AssertionError | 1 failed, 2277 passed in 312.40s. Log ends: ...TOTAL 9000 300 97% "
    "Error: Process completed with exit code 1.\n\nRun uv run pytest -q\nFAILED tests/test_cli.py::test_help\n"
    "Error: Process completed with exit code 1."
)


def test_the_fix_spec_carries_the_ci_excerpt(parent):
    """SCN-VER-231: the requirements of a Kiro fix unit hold the failing step, the failing test and the closing line."""
    repo, ref = parent
    finding = Finding(("F-cccccccc",), "repository CI failed: ci.yml / tests", CI_DETAIL, "blocker", chore=True)
    fix = provider_of(repo).create_fix_unit(ref, 1, [finding], None)
    requirements = "".join(path.read_text() for path in sorted(fix.path.glob("*.md")))
    assert "failed in step `tests`" in requirements
    assert "FAILED tests/test_cli.py::test_help - AssertionError" in requirements
    assert "Error: Process completed with exit code 1." in requirements and "##(" not in requirements
