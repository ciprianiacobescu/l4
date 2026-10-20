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
    UnitRef,
)
from l4.specs.criteria import openspec_criteria
from l4.specs.fixmark import read_fix_marker
from l4.specs.openspec import OpenSpecProvider, parse_openspec_tasks

from .conftest import GREETING_DELTA
from .fixcli import FixCli


@pytest.fixture
def parent(tmp_path: Path, make_change) -> tuple[Path, UnitRef]:
    repo = tmp_path / "repo"
    make_change(repo, "add-greeting", tasks="# Tasks\n\n- [x] 1.1 greet\n", specs={"greeting": GREETING_DELTA})
    ref = OpenSpecProvider(repo, {}).list_units()[0]
    return repo, ref


FINDINGS = [
    Finding(("F-aaaaaaaa", "F-bbbbbbbb"), "Trim fails", "the name is not trimmed", "major", ("C-11111111",)),
    Finding(("F-cccccccc",), "Undeclared suppression", "a noqa in src/x.py", "major", chore=True),
]
DELTA = SpecDelta(
    (
        DeltaRequirement(
            "greeting",
            "Greet by name — regression 1",
            (DeltaScenario("Empty name", "- **WHEN** the name is empty\n- **THEN** greet refuses", "F-aaaaaaaa"),),
        ),
    )
)


def provider_of(repo: Path, **kw) -> tuple[OpenSpecProvider, FixCli]:
    cli = FixCli(repo, **kw)
    return OpenSpecProvider(repo, {}, cli=cli), cli  # type: ignore[arg-type]


def test_the_provider_is_fix_unit_capable():
    assert isinstance(OpenSpecProvider(Path("."), {}), FixUnitCapable)


def test_a_plain_defect_gets_skip_specs_a_proposal_tasks_and_a_marker(parent):
    repo, ref = parent
    provider, cli = provider_of(repo)
    fix = provider.create_fix_unit(ref, 1, FINDINGS, None)
    folder = repo / "openspec" / "changes" / "add-greeting-fix-1"
    assert fix.id == "openspec:add-greeting-fix-1" and fix.path == folder
    assert (folder / ".openspec.yaml").read_text() == "schema: spec-driven\ncreated: 2026-10-04\nskip_specs: true\n"
    assert not (folder / "specs").exists()
    tasks = parse_openspec_tasks((folder / "tasks.md").read_bytes())
    assert [(t.key, t.title, t.done) for t in tasks] == [
        ("1.1", "1.1 Trim fails (F-aaaaaaaa, F-bbbbbbbb; C-11111111)", False),
        ("1.2", "1.2 Undeclared suppression (F-cccccccc)", False),
    ]
    proposal = (folder / "proposal.md").read_text()
    assert "## Why" in proposal and "F-cccccccc (major): Undeclared suppression: a noqa in src/x.py" in proposal
    marker = read_fix_marker(folder)
    assert marker is not None
    assert (marker.parent, marker.round, marker.chores) == ("openspec:add-greeting", 1, ("F-cccccccc",))
    assert cli.calls[0] == ("new", "change", "add-greeting-fix-1", "--json")
    assert cli.calls[-1] == ("validate", "add-greeting-fix-1", "--strict", "--json")


def test_a_spec_delta_adds_a_regression_requirement_with_the_parents_purpose_and_cites_the_new_criterion(parent):
    repo, ref = parent
    spec = repo / "openspec" / "changes" / "add-greeting" / "specs" / "greeting" / "spec.md"
    purpose = "Greeting a named user of the command line tool, with the exact output format."
    spec.write_text(f"## Purpose\n{purpose}\n\n" + spec.read_text())
    provider, _ = provider_of(repo)
    fix = provider.create_fix_unit(ref, 1, FINDINGS[:1], DELTA)
    text = (fix.path / "specs" / "greeting" / "spec.md").read_text()
    assert f"## Purpose\n{purpose}\n" in text
    assert "## ADDED Requirements\n\n### Requirement: Greet by name — regression 1\n" in text
    assert "MODIFIED" not in text and "REMOVED" not in text
    assert "skip_specs" not in (fix.path / ".openspec.yaml").read_text()
    [criterion] = openspec_criteria(fix.path)
    assert criterion.scenario == "Empty name"
    [task] = parse_openspec_tasks((fix.path / "tasks.md").read_bytes())
    assert task.title.endswith(f"(F-aaaaaaaa, F-bbbbbbbb; C-11111111, {criterion.id})")


def test_a_purpose_is_made_up_when_the_parent_has_none(parent):
    repo, ref = parent
    provider, _ = provider_of(repo)
    fix = provider.create_fix_unit(ref, 1, FINDINGS[:1], DELTA)
    text = (fix.path / "specs" / "greeting" / "spec.md").read_text()
    purpose = text.split("## Purpose\n", 1)[1].split("\n", 1)[0]
    assert len(purpose) >= 50


def test_an_existing_fix_change_is_never_overwritten(parent):
    repo, ref = parent
    provider, cli = provider_of(repo)
    provider.create_fix_unit(ref, 1, FINDINGS, None)
    marker = (repo / "openspec" / "changes" / "add-greeting-fix-1" / "tasks.md").read_text()
    cli.calls.clear()
    with pytest.raises(FixUnitExists):
        provider.create_fix_unit(ref, 1, FINDINGS[:1], None)
    assert cli.calls == []
    assert (repo / "openspec" / "changes" / "add-greeting-fix-1" / "tasks.md").read_text() == marker


def test_an_invalid_fix_unit_is_removed_with_everything_the_cli_created(parent):
    repo, ref = parent
    provider, _ = provider_of(repo, valid=False, message="Change must have a Why section")
    assert not (repo / "openspec" / "config.yaml").exists()
    with pytest.raises(FixUnitInvalid, match="Why section"):
        provider.create_fix_unit(ref, 1, FINDINGS, None)
    assert [p.name for p in (repo / "openspec" / "changes").iterdir()] == ["add-greeting"]
    assert not (repo / "openspec" / "config.yaml").exists()


def test_the_cli_side_effects_outside_the_change_are_removed_on_success_too(parent):
    repo, ref = parent
    provider, _ = provider_of(repo)
    provider.create_fix_unit(ref, 1, FINDINGS, None)
    assert not (repo / "openspec" / "config.yaml").exists()


def test_text_from_a_finding_cannot_open_a_heading_or_a_checkbox(parent):
    repo, ref = parent
    provider, _ = provider_of(repo)
    evil = Finding(("F-dddddddd",), "# Heading\n- [ ] 9.9 sneaky", "x\n## Why\n- [ ] 8.8", "major")
    fix = provider.create_fix_unit(ref, 1, [evil], None)
    assert [t.key for t in parse_openspec_tasks((fix.path / "tasks.md").read_bytes())] == ["1.1"]
    assert [t.key for t in parse_openspec_tasks((fix.path / "proposal.md").read_bytes())] == []
    assert json.loads((fix.path / ".l4" / "fix.json").read_text())["findings"] == ["F-dddddddd"]


def test_a_marker_without_test_chores_reads_as_fix(parent, tmp_path):
    """M1.11 W5: a marker an older harness wrote has no `test_chores` key: its chores are fix chores, as before."""
    from l4.specs.fixmark import chore_kind

    repo, ref = parent
    provider, _ = provider_of(repo)
    plain = provider.create_fix_unit(ref, 1, FINDINGS, None)
    assert read_fix_marker(plain.path).test_chores == ()  # type: ignore[union-attr]
    assert chore_kind(plain.path, "1.2 Undeclared suppression (F-cccccccc)") == "fix"
    assert chore_kind(plain.path, "1.1 Trim fails (F-aaaaaaaa, F-bbbbbbbb; C-11111111)") is None  # not a chore
    old = json.loads((plain.path / ".l4" / "fix.json").read_text())
    old.pop("test_chores", None)
    (plain.path / ".l4" / "fix.json").write_text(json.dumps(old))
    assert chore_kind(plain.path, "1.2 Undeclared suppression (F-cccccccc)") == "fix"
    tests = provider.create_fix_unit(
        ref, 2, [Finding(("F-dddddddd",), "Changed code that no test runs", chore=True, tests=True)], None
    )
    assert read_fix_marker(tests.path).test_chores == ("F-dddddddd",)  # type: ignore[union-attr]
    assert chore_kind(tests.path, "1.1 Changed code that no test runs (F-dddddddd)") == "tests"


def test_a_rejected_holds_decision_is_in_the_proposal_whole_and_redacted(parent):
    """M1.12 line 26, a pin of the live-fix a1a0ca3 path for holds: the fix unit's proposal carries the human's reject
    text first, whole up to MAX_DECISION_CHARS, with the plan redacted before the files are written."""
    from l4.redact import Redactor
    from l4.verifier.fixunit import plan_fix_unit, redact_plan
    from l4.verifier.types import Verdict, VerifyResult

    from ..verifier.test_fixunit import COVERAGE_HOLD, FAMILY, settled

    reason = "the code is wrong: sub_areas must go from the rename payload; token=ghp_" + "a1B2c3D4e5F6g7H8i9J0" * 2
    outcome, human, _ = settled(COVERAGE_HOLD, reason)
    assert isinstance(outcome, VerifyResult) and outcome.verdict is Verdict.FAIL
    plan = redact_plan(plan_fix_unit(FAMILY, outcome, human, ordinal=1, fix_minor=False), Redactor({}).redact_text)
    repo, ref = parent
    provider, _ = provider_of(repo)
    fix = provider.create_fix_unit(ref, 1, plan.groups, plan.delta)
    proposal = (repo / "openspec" / "changes" / fix.name / "proposal.md").read_text()
    assert "Decided by human in Q-001: the code is wrong: sub_areas must go from the rename payload" in proposal
    assert "ghp_a1B2" not in proposal


# --- feedback tasks (human-feedback 2.3, L4-FBK-005; SCN-FBK-13, SCN-FBK-14) --------------------------------------

REQUEST = "Requested by Ana, 2026-10-12T15:04:00Z in FB-001 (refactor, src/greeting.py:7): Pull the trim out."


def feedback_finding(fid: str = "F-feed0001", kind: str = "refactor", **over) -> Finding:
    body = {
        "ids": (fid,), "title": f"Feedback FB-001 ({kind}): Extract the trim", "detail": "", "severity": "major",
        "chore": kind in ("refactor", "duplication", "tests"), "tests": kind == "tests",
        "refactor": kind in ("refactor", "duplication"), "item": "FB-001", "request": REQUEST,
        "code": "name = name.strip()\n## Why\n```",
    }  # fmt: skip
    return Finding(**{**body, **over})


def test_a_refactor_feedback_task_is_a_chore_in_the_markers_refactors_and_the_request_comes_first(parent):
    repo, ref = parent
    provider, _ = provider_of(repo)
    fix = provider.create_fix_unit(ref, 1, [feedback_finding(), FINDINGS[0]], None)
    marker = read_fix_marker(fix.path)
    assert marker is not None
    assert marker.chores == marker.refactors == ("F-feed0001",) and marker.test_chores == ()
    proposal = (fix.path / "proposal.md").read_text()
    why = proposal.split("## Why\n", 1)[1]
    assert why.startswith(REQUEST + "\n\n    name = name.strip()\n    ## Why\n    ```\n"), why[:300]
    assert "F-feed0001 (major): Feedback FB-001 (refactor): Extract the trim" in proposal
    assert proposal.count("\n## Why\n") == 1  # the quoted code cannot open a section
    [task, _] = parse_openspec_tasks((fix.path / "tasks.md").read_bytes())
    assert task.title == "1.1 Feedback FB-001 (refactor): Extract the trim (F-feed0001)"
    assert "skip_specs: true" in (fix.path / ".openspec.yaml").read_text()


def test_a_tests_feedback_task_is_a_test_chore_not_a_refactor(parent):
    repo, ref = parent
    provider, _ = provider_of(repo)
    fix = provider.create_fix_unit(ref, 1, [feedback_finding(kind="tests")], None)
    marker = read_fix_marker(fix.path)
    assert marker is not None
    assert (marker.chores, marker.test_chores, marker.refactors) == (("F-feed0001",), ("F-feed0001",), ())


def test_a_config_feedback_item_is_an_added_requirement_named_for_the_item(parent):
    repo, ref = parent
    provider, _ = provider_of(repo)
    delta = SpecDelta(
        (
            DeltaRequirement(
                "greeting",
                "Greeting from the environment \N{EM DASH} feedback FB-001",
                (
                    DeltaScenario(
                        "GREETING is set",
                        "- **WHEN** the environment variable GREETING is set\n- **THEN** the system SHALL use it",
                        "F-feed0001",
                    ),
                    DeltaScenario(
                        "GREETING is not set",
                        "- **WHEN** GREETING is not set\n- **THEN** the system SHALL CONTINUE TO behave as before",
                        "F-feed0001",
                    ),
                ),
            ),
        )
    )
    fix = provider.create_fix_unit(ref, 1, [feedback_finding(kind="config", chore=False, refactor=False)], delta)
    text = (fix.path / "specs" / "greeting" / "spec.md").read_text()
    assert "### Requirement: Greeting from the environment \N{EM DASH} feedback FB-001\n" in text
    assert "skip_specs" not in (fix.path / ".openspec.yaml").read_text()
    criteria = openspec_criteria(fix.path)
    assert [c.scenario for c in criteria] == ["GREETING is set", "GREETING is not set"]
    [task] = parse_openspec_tasks((fix.path / "tasks.md").read_bytes())
    assert task.title.endswith(f"(F-feed0001; {criteria[0].id}, {criteria[1].id})")
    marker = read_fix_marker(fix.path)
    assert marker is not None and marker.chores == () and marker.refactors == ()


def test_a_rejected_spec_gap_without_a_scenario_gets_skip_specs(parent):  # SCN-VER-205
    from l4.verifier.fixunit import plan_fix_unit
    from l4.verifier.types import Finding as Judged
    from l4.verifier.types import HumanVerdict, Severity, Verdict, VerifyResult
    from l4.verifier.verdicts import apply_finding_verdicts

    repo, ref = parent
    family = openspec_criteria(ref.path)
    reason = "the scenario requires a trimmed name; the code keeps the spaces"
    gap = Judged(
        Severity.MAJOR, "Spaces kept", reason, "judge", family[0].id, spec_gap=True,
        suggested_fix="WHEN the name has spaces THEN the name keeps the spaces",
    )  # fmt: skip
    verdict = HumanVerdict("Q-002", gap.id, "reject", "human", reason, "x")
    verified = VerifyResult("openspec:add-greeting", 1, Verdict.FAIL, "b", "h")
    verified.findings = apply_finding_verdicts([gap], {gap.id: verdict})
    plan = plan_fix_unit(family, verified, [verdict], ordinal=1, fix_minor=False)
    assert plan.delta is None
    provider, _ = provider_of(repo)
    fix = provider.create_fix_unit(ref, 1, plan.groups, plan.delta)
    assert "skip_specs: true" in (fix.path / ".openspec.yaml").read_text()
    assert not (fix.path / "specs").exists()
    proposal = (fix.path / "proposal.md").read_text()
    assert f"Decided by human in Q-002: {reason}." in proposal
    texts = [p.read_text() for p in fix.path.rglob("*") if p.is_file()]
    assert not any("the name keeps the spaces" in t for t in texts)
