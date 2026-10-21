"""L4-OPS-015: the acceptance criteria that changed between two versions of `requirements.md` (by number, after
whitespace normalisation), and the tasks that cite them."""

import pytest

from l4.specs.base import Framework, UnitRef
from l4.specs.criteria import changed_requirements
from l4.specs.kiro import KiroProvider, cited_by_changed

REQUIREMENTS = """# Requirements Document

## Requirements

### Requirement 1: Discounts

**User Story:** As a shopper, I want a discount code, so that I pay less.

#### Acceptance Criteria

1. WHEN apply_discount is called with a known code, THE Shop SHALL reduce the amount.
2. WHEN the code is unknown, THE Shop SHALL return the amount.

### Requirement 2: Shouting

**User Story:** As a shopper, I want my name shouted.

#### Acceptance Criteria

1. WHEN shout is called, THE Shop SHALL return capitals.
2. WHEN shout gets an empty name, THE Shop SHALL return an empty string.
3. WHEN shout gets a long name, THE Shop SHALL
   return it whole.
"""
TASKS = """# Implementation Plan

- [x] 1. Discounts
  - [x] 1.1 Add `apply_discount`
    - _Requirements: 1.1, 1.2_
- [x] 2. Shouting
  - [x] 2.1 Add `shout`
    - _Requirements: 2.3_
  - [x] 2.2 Handle empty
    - _Requirements: 2.2_
  - [ ] 2.3 Document
    - _Requirements: 2_
"""


def test_a_reworded_criterion_is_changed_and_a_rewrapped_one_is_not():
    reworded = REQUIREMENTS.replace("return it whole.", "return the whole name.")
    assert changed_requirements(REQUIREMENTS, reworded) == ("2.3",)
    rewrapped = REQUIREMENTS.replace("THE Shop SHALL\n   return it whole.", "THE Shop SHALL return\n     it   whole.")
    assert changed_requirements(REQUIREMENTS, rewrapped) == ()


def test_added_and_removed_criteria_are_changed_and_the_list_is_in_number_order():
    added = REQUIREMENTS.replace("   return it whole.\n", "   return it whole.\n4. WHEN x, THE Shop SHALL y.\n")
    assert changed_requirements(REQUIREMENTS, added) == ("2.4",)
    removed = REQUIREMENTS.replace("2. WHEN the code is unknown, THE Shop SHALL return the amount.\n", "")
    assert changed_requirements(REQUIREMENTS, removed) == ("1.2",)
    both = REQUIREMENTS.replace("known code", "listed code").replace("capitals", "upper case")
    assert changed_requirements(REQUIREMENTS, both) == ("1.1", "2.1")


def test_a_missing_file_has_no_criteria():
    assert changed_requirements(None, REQUIREMENTS) == ("1.1", "1.2", "2.1", "2.2", "2.3")
    assert changed_requirements(REQUIREMENTS, None) == ("1.1", "1.2", "2.1", "2.2", "2.3")
    assert changed_requirements(None, None) == ()


@pytest.mark.parametrize(
    ("changed", "reopened"),
    [
        (("2.3",), ["2", "2.1"]),  # 2.3 cites `2` too, but it is open already
        (("1.2",), ["1", "1.1"]),
        (("2.2",), ["2", "2.2"]),
        (("2.2", "2.3"), ["2", "2.1", "2.2"]),
        (("3.1",), []),  # nobody cites it
        ((), []),
    ],
)
def test_the_tasks_that_cite_a_changed_criterion_and_their_parents_are_reopened(tmp_path, changed, reopened):
    spec = tmp_path / ".kiro" / "specs" / "discounts"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text(TASKS)
    provider = KiroProvider(tmp_path)
    ref = UnitRef(Framework.KIRO, "discounts", spec)
    assert cited_by_changed(provider.tasks(ref), changed) == reopened
    assert provider.reopen(ref, changed) == reopened
    after = {t.key: t.marker_char for t in provider.tasks(ref)}
    assert {k for k, mark in after.items() if mark == " "} == {*reopened, "2.3"}
    assert sorted(k for k, mark in after.items() if mark == "x") == sorted(
        {"1", "1.1", "2", "2.1", "2.2"} - {*reopened}
    )


def test_a_link_to_a_requirement_number_matches_all_its_criteria_and_a_cited_parent_reopens_its_children(tmp_path):
    spec = tmp_path / ".kiro" / "specs" / "discounts"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text(
        "- [x] 1. Everything\n  - _Requirements: 2_\n  - [x] 1.1 One\n    - _Requirements: 9.9_\n"
        "  - [x] 1.2 Two\n    - _Requirements: 9.9_\n"
    )
    provider = KiroProvider(tmp_path)
    ref = UnitRef(Framework.KIRO, "discounts", spec)
    assert provider.reopen(ref, ("2.3",)) == ["1", "1.1", "1.2"]
