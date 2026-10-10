"""A fix unit against the real pinned OpenSpec (L4_LIVE=1): `skip_specs` and an ADDED `- regression 1` delta both pass
`validate --strict`, and the CLI's own side effects are cleaned up."""

import os
from pathlib import Path

import pytest

from l4.specs.base import DeltaRequirement, DeltaScenario, Finding, SpecDelta
from l4.specs.openspec import OpenSpecProvider

pytestmark = pytest.mark.live

PARENT_SPEC = """# Spec Delta

## Purpose
Greeting a named user of the command line tool, with the exact output format of the greeting.

## ADDED Requirements

### Requirement: Greet by name
The system SHALL greet the user by the name given on the command line.

#### Scenario: Named greeting
- **WHEN** the user runs `greet Ada`
- **THEN** the output is `Hello, Ada!`
"""
FINDING = Finding(("F-aaaaaaaa",), "Trim fails", "the name is not trimmed", "major", ("C-11111111",))


@pytest.fixture
def parent(tmp_path: Path):
    repo = tmp_path / "repo"
    change = repo / "openspec" / "changes" / "add-greeting"
    (change / "specs" / "greeting").mkdir(parents=True)
    (change / "specs" / "greeting" / "spec.md").write_text(PARENT_SPEC)
    (change / "tasks.md").write_text("# Tasks\n\n## 1. Greet\n\n- [x] 1.1 greet\n")
    (change / "proposal.md").write_text("# Proposal\n\n## Why\nGreet users by name on the command line.\n")
    (change / ".openspec.yaml").write_text("schema: spec-driven\ncreated: 2026-10-04\n")
    environ = {**os.environ, "L4_CACHE": str(tmp_path / "cache")}
    provider = OpenSpecProvider(repo, environ)
    return repo, provider, provider.list_units()[0]


def test_skip_specs_fix_unit_validates_strict_and_leaves_no_stray_files(parent):
    repo, provider, ref = parent
    fix = provider.create_fix_unit(ref, 1, [FINDING], None)
    assert provider.validate(fix, strict=True).valid
    assert not (repo / "openspec" / "config.yaml").exists()


def test_an_added_regression_requirement_validates_strict(parent):
    repo, provider, ref = parent
    delta = SpecDelta(
        (
            DeltaRequirement(
                "greeting",
                "Greet by name — regression 1",
                (DeltaScenario("Empty name", "- **WHEN** the name is empty\n- **THEN** it refuses", "F-aaaaaaaa"),),
            ),
        )
    )
    fix = provider.create_fix_unit(ref, 1, [FINDING], delta)
    report = provider.validate(fix, strict=True)
    assert report.valid, report.issues
    assert [c.requirement for c in provider.criteria(fix)] == ["Greet by name — regression 1"]
