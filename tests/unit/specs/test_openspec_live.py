"""Against the real pinned OpenSpec at $L4_HOME/npm (L4_LIVE=1). Proves the recorded-fixture tests describe reality."""

import os
from pathlib import Path

import pytest

from l4.specs.base import Marker
from l4.specs.openspec import OpenSpecCli, OpenSpecProvider, parse_openspec_tasks

pytestmark = pytest.mark.live

GREETING_BASE = """# greeting Specification

## Purpose
The greeting capability produces a friendly greeting for a named user of the CLI.

## Requirements

### Requirement: Greet by name
The system SHALL greet the user by the name given on the command line.

#### Scenario: Named greeting
- **WHEN** the user runs `greet Ada`
- **THEN** the output is `Hello, Ada!`
"""


def test_validate_and_task_parity_against_the_real_cli(tmp_path: Path, add_farewell):
    repo, change = add_farewell
    (repo / "openspec" / "specs" / "greeting").mkdir(parents=True)
    (repo / "openspec" / "specs" / "greeting" / "spec.md").write_text(GREETING_BASE)
    (change / ".openspec.yaml").write_text("schema: spec-driven\ncreated: 2026-10-03\n")
    (change / "proposal.md").write_text("# Proposal\n\n## Why\nSay goodbye.\n\n## What Changes\n- farewell\n")
    environ = {**os.environ, "L4_CACHE": str(tmp_path / "cache")}
    provider = OpenSpecProvider(repo, environ)
    (unit,) = provider.list_units()
    assert provider.validate(unit).valid

    reply = OpenSpecCli(repo, environ).run_json("instructions", "apply", "--change", "add-farewell", "--json").data
    tasks = parse_openspec_tasks((change / "tasks.md").read_bytes())
    assert reply["progress"] == {"total": len(tasks), "complete": sum(t.done for t in tasks), "remaining": 3}
    assert [(t["line"], t["done"], t["description"]) for t in reply["tasks"]] == [
        (t.line, t.done, t.title) for t in tasks
    ]

    provider.set_marker(unit, "2.1", Marker.DONE)
    after = OpenSpecCli(repo, environ).run_json("instructions", "apply", "--change", "add-farewell", "--json").data
    assert after["progress"]["complete"] == 3
