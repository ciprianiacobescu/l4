"""detect-test-tamper (third review, M3): model-written text must not become a human tag of a harness-written task."""

import re

import pytest

from l4.specs.base import Finding, untagged
from l4.specs.fixmark import FixMarker, write_fix_marker
from l4.specs.kiro import _fix_tasks, _line, parse_kiro_tasks
from l4.specs.openspec import _plain, _tasks, parse_openspec_tasks
from l4.verifier.scan import has_human_tag, task_tags

TITLE = "The check is inverted [test-infra] and [config]"


def finding(title=TITLE, chore=False):
    return Finding(("F-aaaaaaaa",), title, "detail", "major", ("C-11111111",), chore=chore)


def test_an_openspec_fix_task_carries_no_tag_of_the_findings_title():
    [task] = parse_openspec_tasks(_tasks([finding()], {}).encode())
    assert task_tags(task.title) == frozenset()
    assert "(test-infra)" in task.title  # the words stay, the brackets go


def test_a_kiro_fix_task_carries_no_tag_of_the_findings_title_but_keeps_the_chore_tag_of_the_harness():
    text = _fix_tasks([finding(), finding("Other [docs]", chore=True)], [["1.1"], []], {"Req 1.1": "C-11111111"})
    leaves = [t for t in parse_kiro_tasks(text.encode()) if t.key.startswith("1.")]
    assert task_tags(leaves[0].title) == frozenset()
    assert task_tags(leaves[1].title) == frozenset({"chore"})  # the harness's own tag, from the marker


def test_a_human_tag_of_a_harness_written_unit_counts_for_nothing(tmp_path):
    unit = tmp_path / "x-fix-1"
    assert has_human_tag(unit, "1.1 do it [test-infra]", "test-infra")  # a person's unit: the tag stands
    write_fix_marker(unit, FixMarker("openspec:x", 1, ("F-aaaaaaaa",), ()))
    assert not has_human_tag(unit, "1.1 do it [test-infra]", "test-infra")  # a fix unit: the harness wrote the title
    assert not has_human_tag(unit, "1.1 do it [config]", "config")


# --- only tag-like brackets go (verdict-reason-scenario 2.1; L4-IMP-006 (7), SCN-VER-264) ---------------------------

KIRO_TAG = re.compile(r"\[([A-Za-z0-9_-]+)\]")  # a Kiro task title's tag
SCAN_TAG = re.compile(r"\[([A-Za-z][A-Za-z-]*)\]")  # the scan's human tag
CODE = '[...DEFAULT_ROLES].sort() deep-equals ["approver", "auditor"]'
SCN_VER_264 = '[test-infra] [...DEFAULT_ROLES].sort() deep-equals ["approver"] [ ] [x.[chore]'
SCN_VER_264_OUT = '(test-infra) [...DEFAULT_ROLES].sort() deep-equals ["approver"] ( ) (x.(chore)'


def no_tag(text: str) -> bool:
    return KIRO_TAG.search(text) is None and SCAN_TAG.search(text) is None


def test_code_brackets_stay_and_tag_brackets_go_scn_ver_264():
    assert untagged(CODE) == CODE
    assert untagged("[test-infra] do x") == "(test-infra) do x"
    assert untagged(SCN_VER_264) == SCN_VER_264_OUT
    assert _plain(SCN_VER_264) == SCN_VER_264_OUT and _line(SCN_VER_264) == SCN_VER_264_OUT  # both writers


@pytest.mark.parametrize(
    "text", ["[ ]", "[config]", "[A-b_1]", "[", "]", "[[chore]]", "[x.[chore]", "a [] b", "][test-infra][", "[a b]"]
)
def test_no_tag_is_left_in_what_untagged_gives_scn_ver_264(text):
    for result in (untagged(text), _plain(text), _line(text)):
        assert no_tag(result), (text, result)


def test_a_bracket_without_a_partner_and_a_nested_pair_become_parentheses_scn_ver_264():
    assert untagged("[[chore]]") == "((chore))"
    assert untagged("a ] b [ c") == "a ) b ( c"
    assert untagged("[x.[chore]") == "(x.(chore)"


def test_a_nul_character_is_removed_scn_ver_264():
    assert untagged("[test-\x00infra] a\x00b") == "(test-infra) ab"
    assert "\x00" not in untagged("\x00" + CODE)


def test_a_fix_task_title_keeps_code_brackets_and_loses_tag_brackets_scn_ver_264():
    text = _fix_tasks([finding(SCN_VER_264)], [[]], {})
    [leaf] = [t for t in parse_kiro_tasks(text.encode()) if t.key.startswith("1.")]
    assert SCN_VER_264_OUT in leaf.title and task_tags(leaf.title) == frozenset()
    [task] = parse_openspec_tasks(_tasks([finding(SCN_VER_264)], {}).encode())
    assert SCN_VER_264_OUT in task.title and task_tags(task.title) == frozenset()
