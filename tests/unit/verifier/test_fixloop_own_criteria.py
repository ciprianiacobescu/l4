"""A fix unit's task cites criteria by the numbers of its own bugfix.md (L4-KSP-003, kiro-prompt-context D1)."""

from pathlib import Path

import pytest

from l4.specs.base import Finding as SpecFinding
from l4.specs.base import UnitRef
from l4.specs.criteria import linked_criteria, own_criteria
from l4.specs.kiro import KiroProvider
from l4.verifier.fixloop import FamilyProvider

from ..orchestrator.test_kiro_unit import DISCOUNT_ID, REQUIREMENTS, SHOUT_ID, SPEC, TASKS
from ..specs.test_kiro_fix_unit import UUID


@pytest.fixture
def family(tmp_path: Path) -> tuple[KiroProvider, UnitRef, UnitRef]:
    repo = tmp_path / "repo"
    spec = repo / SPEC
    spec.mkdir(parents=True)
    (spec / "requirements.md").write_text(REQUIREMENTS)
    (spec / "tasks.md").write_text(TASKS.replace("[ ]", "[x]"))
    provider = KiroProvider(repo, uuid_factory=lambda: UUID)
    parent = provider.list_units()[0]
    finding = SpecFinding(("F-00000001",), "Discount fails", "no discount", "major", (DISCOUNT_ID,))
    return provider, parent, provider.create_fix_unit(parent, 1, [finding], None)


def test_the_family_gives_two_criteria_for_the_alias_a_fix_task_cites(family):
    """The gap: the parent's own `Req 2.1` (shout) and the fix item `2.1` (which restates the parent's `Req 1.1`)
    share an alias in the family, so a link `2.1` of a fix leaf named both."""
    provider, parent, fix = family
    members = FamilyProvider(provider, parent)
    assert {c.id for c in linked_criteria(members.criteria(fix), ("2.1",))} == {SHOUT_ID, DISCOUNT_ID}


def test_own_criteria_of_a_fix_unit_are_its_own_items_only(family):
    provider, parent, fix = family
    members = FamilyProvider(provider, parent)
    assert [(c.id, c.alias) for c in own_criteria(members, fix)] == [(DISCOUNT_ID, "Req 2.1")]
    assert [c.id for c in linked_criteria(own_criteria(members, fix), ("2.1",))] == [DISCOUNT_ID]
    assert {c.id for c in members.criteria(fix)} >= {SHOUT_ID, DISCOUNT_ID}  # the family list still knows both ids
    assert [c.id for c in members.own_criteria(fix)] == [DISCOUNT_ID]


def test_own_criteria_of_a_plain_provider_and_of_the_parent(family):
    provider, parent, _ = family
    members = FamilyProvider(provider, parent)
    assert own_criteria(provider, parent) == provider.criteria(parent)
    assert [c.id for c in own_criteria(members, parent)] == [c.id for c in provider.criteria(parent)]
