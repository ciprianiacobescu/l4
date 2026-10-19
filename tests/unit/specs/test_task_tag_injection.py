"""detect-test-tamper (third review, M3): model-written text must not become a human tag of a harness-written task."""

from l4.specs.base import Finding
from l4.specs.fixmark import FixMarker, write_fix_marker
from l4.specs.kiro import _fix_tasks, parse_kiro_tasks
from l4.specs.openspec import _tasks, parse_openspec_tasks
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
