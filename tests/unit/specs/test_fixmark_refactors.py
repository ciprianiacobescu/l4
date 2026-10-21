"""The marker's `refactors` (L4-FBK-005, D5): ids of findings whose tasks are behaviour-preserving refactors."""

import json

from l4.specs.fixmark import FixMarker, chore_findings, chore_kind, read_fix_marker, refactor_findings, write_fix_marker


def test_refactors_round_trip_through_the_marker(tmp_path):
    marker = FixMarker("openspec:add-greeting", 1, ("FB-001", "F-1"), ("F-1",), (), ("FB-001",))
    write_fix_marker(tmp_path, marker)
    assert read_fix_marker(tmp_path) == marker
    assert json.loads((tmp_path / ".l4" / "fix.json").read_text())["refactors"] == ["FB-001"]


def test_a_marker_without_the_field_reads_as_no_refactors(tmp_path):
    (tmp_path / ".l4").mkdir()
    body = {"schema": "l4/fix-unit@1", "parent": "p", "round": 1, "findings": ["F-1"], "chores": ["F-1"]}
    (tmp_path / ".l4" / "fix.json").write_text(json.dumps(body))
    marker = read_fix_marker(tmp_path)
    assert marker is not None and marker.refactors == ()
    assert refactor_findings(tmp_path, "1.1 F-1") == () and chore_kind(tmp_path, "1.1 F-1") == "fix"


def test_a_refactor_id_is_a_chore_of_kind_refactor_by_the_marker_only(tmp_path):
    write_fix_marker(tmp_path, FixMarker("p", 1, ("FB-001", "F-1"), ("F-1",), (), ("FB-001",)))
    assert refactor_findings(tmp_path, "1.1 do FB-001") == ("FB-001",)
    assert chore_findings(tmp_path, "1.1 do FB-001") == ("FB-001",)
    assert chore_kind(tmp_path, "1.1 do FB-001") == "refactor" and chore_kind(tmp_path, "1.2 F-1") == "fix"
    assert refactor_findings(tmp_path, "1.1 [refactor] other") == () and chore_kind(tmp_path, "1.1 other") is None
