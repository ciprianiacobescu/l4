"""ui-carry-followup 1.1 (L4-VER-096, SCN-VER-412, 413): `read_at_base` gives a merged parent's criterion the text the
base's capability spec holds, and only that. Pure: two lists of criteria."""

from dataclasses import replace

import pytest

from l4.specs.base import Criterion, Framework
from l4.specs.criteria import criterion_id, read_at_base, unchanged_ids

CAP, REQ = "journeys", "Opening a journey"
OLD_PATH = "- **WHEN** a person opens a journey\n- **THEN** the page opens /flows"
NEW_PATH = (
    "- **WHEN** a person opens a journey\n- **THEN** the page opens /no-such-page-deep-link, a path no feature owns"
)
OLD_COUNT = "- **THEN** the plan's eight calls are made"
NEW_COUNT = "- **THEN** the nine calls are made, the frozen calls.test.ts included"


def crit(scenario: str, text: str, *, capability: str = CAP, requirement: str = REQ, line: int = 7) -> Criterion:
    alias = f"{capability} › {requirement} › {scenario}"
    return Criterion(
        criterion_id("openspec", capability, requirement, scenario), alias, Framework.OPENSPEC, capability,
        requirement, scenario, text, "specs/journeys/spec.md", line,
    )  # fmt: skip


def as_base(c: Criterion, text: str) -> Criterion:
    """The same scenario as the base's capability spec holds it: a repository path, another line."""
    return replace(c, text=text, source_path=f"openspec/specs/{c.capability}/spec.md", source_line=40)


@pytest.mark.parametrize("old,new", [(OLD_PATH, NEW_PATH), (OLD_COUNT, NEW_COUNT)])
def test_scn_ver_412_a_reworded_scenario_takes_the_bases_text_and_keeps_everything_else(old, new):
    parent = crit("opens the flow", old)
    [read] = read_at_base([parent], [as_base(parent, new)])
    assert read.text == new
    assert (read.id, read.alias, read.capability, read.requirement, read.scenario) == (
        parent.id, parent.alias, parent.capability, parent.requirement, parent.scenario,
    )  # fmt: skip
    assert (read.source_path, read.source_line, read.framework) == ("specs/journeys/spec.md", 7, Framework.OPENSPEC)
    assert unchanged_ids([read], [as_base(parent, new)]) == {parent.id}  # step 4's pass-to-pass rule now holds it
    assert unchanged_ids([parent], [as_base(parent, new)]) == frozenset()  # and did not before


def test_order_and_number_of_criteria_do_not_change_and_the_others_are_the_same_objects():
    a, b, c = crit("a", "x"), crit("b", OLD_PATH), crit("c", "z")
    out = read_at_base([a, b, c], [as_base(b, NEW_PATH)])
    assert [x.id for x in out] == [a.id, b.id, c.id]
    assert out[0] is a and out[2] is c and out[1].text == NEW_PATH


def test_scn_ver_413_no_base_scenario_with_that_id_keeps_the_parents_text():
    renamed = crit("opens the flow", OLD_PATH, requirement="Opening")  # the base renamed the requirement
    base = crit("opens the flow", NEW_PATH)  # another id: it is another scenario
    assert renamed.id != base.id
    assert read_at_base([renamed], [as_base(base, NEW_PATH)]) == [renamed]
    assert read_at_base([renamed], []) == [renamed]


def test_scn_ver_413_a_base_that_holds_the_id_twice_keeps_the_parents_text():
    parent = crit("opens the flow", OLD_PATH)
    twice = [as_base(parent, NEW_PATH), as_base(parent, "- **THEN** a third wording")]
    assert read_at_base([parent], twice) == [parent]


@pytest.mark.parametrize(
    "same", [OLD_PATH, "- **WHEN**   a person opens a journey\n- **THEN** the page\n  opens /flows"]
)
def test_scn_ver_413_an_equal_text_after_normalise_is_left_alone(same):
    parent = crit("opens the flow", OLD_PATH)
    [read] = read_at_base([parent], [as_base(parent, same)])
    assert read is parent


@pytest.mark.parametrize("empty", ["", "   \n  "])
def test_scn_ver_413_an_empty_base_text_is_left_alone(empty):
    parent = crit("opens the flow", OLD_PATH)
    assert read_at_base([parent], [as_base(parent, empty)]) == [parent]


def test_a_same_id_with_another_requirement_or_capability_is_a_collision_and_is_left_alone():
    parent = crit("opens the flow", OLD_PATH)
    for other in (
        replace(as_base(parent, NEW_PATH), requirement="Another"),
        replace(as_base(parent, NEW_PATH), capability="other"),
    ):
        assert other.id == parent.id  # the key's own fields are what is checked beyond the id
        assert read_at_base([parent], [other]) == [parent]


def test_scn_ver_413_a_kiro_criterion_is_never_rewritten():
    parent = replace(crit("x", OLD_PATH), framework=Framework.KIRO)
    base = replace(as_base(parent, NEW_PATH), framework=Framework.KIRO)
    assert read_at_base([parent], [base]) == [parent]


def test_nothing_in_nothing_out():
    assert read_at_base([], []) == []
