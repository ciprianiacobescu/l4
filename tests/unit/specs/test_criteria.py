import re
from pathlib import Path

import pytest

from l4.specs.base import CriterionIdCollision, Framework, SpecError
from l4.specs.criteria import criterion_id, normalise, openspec_criteria


def test_golden_vectors():
    # computed outside the code under test: printf '<framework>|<container>|<requirement>|<leaf>' | shasum -a 256
    assert criterion_id("openspec", "greeting", "Greet by name", "Named greeting") == "C-9618b9f5"
    assert criterion_id("openspec", "greeting", "L4-X-001 Greet by name", "Named greeting") == "C-0a9f853f"
    # NFC, trimmed, whitespace runs collapsed, case kept
    decomposed = "cafe\N{COMBINING ACUTE ACCENT}"
    assert criterion_id("openspec", decomposed, "  Greet \t by\nname ", "Named greeting") == "C-857527fd"
    assert normalise("  A \N{NO-BREAK SPACE} b ") == "A b"
    assert criterion_id("openspec", "greeting", "greet by name", "Named greeting") != "C-9618b9f5"


def test_openspec_criteria_and_aliases(add_farewell, recorded):
    _, change = add_farewell
    criteria = openspec_criteria(change)
    expected = [
        (d["spec"], r["name"], s["name"], s["rawText"])
        for d in recorded("show-add-farewell.json")["deltas"]
        for r in d["requirements"]
        for s in r["scenarios"]
    ]
    # the CLI is the oracle for what the headings and bodies are; the harness only adds the ids and the order
    assert sorted((c.capability, c.requirement, c.scenario, c.text) for c in criteria) == sorted(expected)
    assert [(c.capability, c.scenario) for c in criteria] == [
        ("farewell", "Named farewell"),
        ("greeting", "Named greeting"),
        ("greeting", "Shouted greeting"),
    ]
    first = criteria[0]
    assert re.fullmatch(r"C-[0-9a-f]{8}", first.id) and len({c.id for c in criteria}) == 3
    assert first.alias == "farewell › Say goodbye › Named farewell"
    assert first.framework is Framework.OPENSPEC and first.source_path == "specs/farewell/spec.md"
    assert first.id == criterion_id("openspec", "farewell", "Say goodbye", "Named farewell")
    assert first.source_line == 9 and "Goodbye" in first.text
    assert openspec_criteria(change) == criteria  # deterministic


def test_crlf_and_bom_specs_give_the_same_ids(add_farewell, tmp_path: Path, make_change):
    _, change = add_farewell
    plain = [(c.id, c.text) for c in openspec_criteria(change)]
    crlf = {
        cap: b"\xef\xbb\xbf" + (change / "specs" / cap / "spec.md").read_bytes().replace(b"\n", b"\r\n")
        for cap in ("greeting", "farewell")
    }
    other = make_change(tmp_path / "other", "add-farewell", specs=crlf)
    assert [(c.id, c.text) for c in openspec_criteria(other)] == plain


def test_only_added_and_modified_scenarios_under_requirement_headings_count(tmp_path: Path, make_change):
    delta = """## ADDED Requirements

### Requirement: Real
The system SHALL do it.

#### Scenario: Counted
- **WHEN** a
- **THEN** b

### Scenario: Three hashtags is ignored by OpenSpec
- **WHEN** x

```md
### Requirement: Inside a fence
#### Scenario: Fenced
```

## REMOVED Requirements

### Requirement: Gone
#### Scenario: Removed ones are not criteria

## RENAMED Requirements
- FROM: `### Requirement: Old`
- TO: `### Requirement: New`
"""
    change = make_change(tmp_path / "repo", "c", specs={"cap": delta})
    assert [(c.requirement, c.scenario, c.text) for c in openspec_criteria(change)] == [
        ("Real", "Counted", "- **WHEN** a\n- **THEN** b")
    ]


def test_a_unit_without_scenarios_has_no_criteria_and_collisions_are_refused(tmp_path: Path, make_change):
    chore = make_change(tmp_path / "repo", "chore", tasks="# Tasks\n")
    assert openspec_criteria(chore) == []
    twice = "## ADDED Requirements\n\n### Requirement: R\nSHALL.\n\n#### Scenario: S\n- a\n\n#### Scenario: S\n- b\n"
    dup = make_change(tmp_path / "repo2", "dup", specs={"cap": twice})
    with pytest.raises(CriterionIdCollision, match="cap .* R .* S"):
        openspec_criteria(dup)


def test_a_symlinked_spec_file_is_refused(tmp_path: Path, make_change):
    secret = tmp_path / "secret.md"
    secret.write_text("## ADDED Requirements\n\n### Requirement: Leak\n#### Scenario: Leak\n- x\n")
    change = make_change(tmp_path / "repo", "c", specs={"cap": "x"})
    (change / "specs" / "cap" / "spec.md").unlink()
    (change / "specs" / "cap" / "spec.md").symlink_to(secret)
    with pytest.raises(SpecError, match="symlink"):
        openspec_criteria(change)
