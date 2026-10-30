"""The marker's `repairs` (own-test-repair, L4-IMP-091): ids of findings whose tasks may repair the unit's own new
failing tests. A repair id is a chore id too, and nothing but the marker (written by the harness) makes a repair."""

import json
from pathlib import Path

from l4.specs.base import Finding
from l4.specs.fixmark import FixMarker, chore_findings, chore_kind, read_fix_marker, write_fix_marker
from l4.specs.kiro import KiroProvider
from l4.specs.openspec import OpenSpecProvider

from .conftest import GREETING_DELTA
from .fixcli import FixCli
from .test_kiro_fix_unit import REQUIREMENTS, TASKS, UUID


def test_repairs_round_trip_through_the_marker(tmp_path):
    marker = FixMarker("openspec:add-greeting", 1, ("F-1", "F-2"), ("F-1", "F-2"), (), (), (), ("F-1",))
    write_fix_marker(tmp_path, marker)
    assert read_fix_marker(tmp_path) == marker
    assert json.loads((tmp_path / ".l4" / "fix.json").read_text())["repairs"] == ["F-1"]


def test_a_marker_without_the_field_reads_as_no_repairs(tmp_path):
    (tmp_path / ".l4").mkdir()
    body = {"schema": "l4/fix-unit@1", "parent": "p", "round": 1, "findings": ["F-1"], "chores": ["F-1"]}
    (tmp_path / ".l4" / "fix.json").write_text(json.dumps(body))
    marker = read_fix_marker(tmp_path)
    assert marker is not None and marker.repairs == () and chore_kind(tmp_path, "1.1 F-1") == "fix"


def test_a_task_is_a_repair_only_when_every_finding_it_cites_is(tmp_path):
    write_fix_marker(
        tmp_path, FixMarker("p", 1, ("F-1", "F-2", "F-3"), ("F-1", "F-2", "F-3"), (), (), (), ("F-1", "F-2"))
    )
    assert chore_kind(tmp_path, "1.1 e2e gate failed (F-1, F-2)") == "repair"
    assert chore_kind(tmp_path, "1.2 e2e gate failed (F-1, F-3)") == "fix"  # a plain finding in the task: a fix
    assert chore_kind(tmp_path, "1.3 other (F-3)") == "fix"
    assert chore_findings(tmp_path, "1.1 e2e gate failed (F-1, F-2)") == ("F-1", "F-2")


def test_a_repair_id_that_is_no_chore_is_no_repair(tmp_path):
    """A hand-edited marker that lists a repair which is not a chore makes no repair: the task is not a chore."""
    write_fix_marker(tmp_path, FixMarker("p", 1, ("F-1",), (), (), (), (), ("F-1",)))
    assert chore_kind(tmp_path, "1.1 x (F-1)") is None


def test_a_test_chore_or_a_refactor_is_never_a_repair(tmp_path):
    write_fix_marker(
        tmp_path, FixMarker("p", 1, ("F-1", "F-2"), ("F-1", "F-2"), ("F-1",), ("F-2",), (), ("F-1", "F-2"))
    )
    assert chore_kind(tmp_path, "1.1 x (F-1)") == "tests" and chore_kind(tmp_path, "1.2 y (F-2)") == "refactor"


def test_the_openspec_provider_writes_the_repairs_of_the_findings(tmp_path, make_change):
    repo = tmp_path / "repo"
    make_change(repo, "add-greeting", tasks="# Tasks\n\n- [x] 1.1 greet\n", specs={"greeting": GREETING_DELTA})
    ref = OpenSpecProvider(repo, {}).list_units()[0]
    provider = OpenSpecProvider(repo, {}, cli=FixCli(repo))  # type: ignore[arg-type]
    findings = [
        Finding(("F-aaaaaaaa",), "e2e gate failed", "x", "blocker", chore=True, repair=True),
        Finding(("F-bbbbbbbb",), "Undeclared suppression", "y", "major", chore=True),
    ]
    fix = provider.create_fix_unit(ref, 1, findings, None)
    marker = read_fix_marker(fix.path)
    assert marker is not None and marker.repairs == ("F-aaaaaaaa",) and marker.chores == ("F-aaaaaaaa", "F-bbbbbbbb")
    assert chore_kind(fix.path, "1.1 e2e gate failed (F-aaaaaaaa)") == "repair"
    assert chore_kind(fix.path, "1.2 Undeclared suppression (F-bbbbbbbb)") == "fix"


def test_the_kiro_provider_writes_the_repairs_of_the_findings(tmp_path: Path):
    repo = tmp_path / "repo"
    spec = repo / ".kiro" / "specs" / "login"
    spec.mkdir(parents=True)
    (spec / "requirements.md").write_text(REQUIREMENTS)
    (spec / "design.md").write_text("# Design\n")
    (spec / "tasks.md").write_text(TASKS)
    provider = KiroProvider(repo, uuid_factory=lambda: UUID)
    ref = provider.list_units()[0]
    findings = [Finding(("F-aaaaaaaa",), "e2e gate failed", "x", "blocker", chore=True, repair=True)]
    fix = provider.create_fix_unit(ref, 1, findings, None)
    marker = read_fix_marker(fix.path)
    assert marker is not None and marker.repairs == ("F-aaaaaaaa",)
