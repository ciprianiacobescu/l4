"""A repeated base-tests failure escalates with the reverted support files and the way out (L4-VER-081)."""

from l4.verifier.base_tests import FAILS_TITLE, GONE_TITLE
from l4.verifier.fixloop import (
    BASE_TESTS_WAY_OUT,
    WAY_OUT_CHARS,
    base_tests_way_out,
    repeated_failure,
    same_failure_text,
)

from .test_fixloop_escalation import BOT, blocker, commit, current, event, gate, previous, unit  # noqa: F401

SUPPORT = [{"path": "test/arch/modules.ts", "tasks": ["1.1", "1.2"], "people": False}]
WAY = BASE_TESTS_WAY_OUT + "test/arch/modules.ts (task 1.1, 1.2)"


def base_event(seq=1, rnd=2, support=SUPPORT):
    data = {"round": rnd} if support is None else {"round": rnd, "support_reverted": support}
    return event("verify.base_tests", seq, **data)


def repeat_of(unit, title):  # noqa: F811
    """A round 2 that fails the way round 1 did, on the finding `title`; returns (result, `same_failure` detail)."""
    git, repo, path, head = unit
    found = blocker(title)
    previous(path, head, [gate("lint", "pass", "")], findings=[found])
    (repo / "b.txt").write_text("fix")
    now = commit(git, repo, BOT, "fix(u): task")
    result = current(now, [gate("lint", "pass", "")], findings=[found])
    return result, repeated_failure(path, git, [], result)


def test_scn_ver_320_the_escalation_tells_the_person_which_task_to_tag(unit):  # noqa: F811
    result, detail = repeat_of(unit, FAILS_TITLE)
    text = same_failure_text([base_event()], result, detail)
    assert text.startswith(WAY + "; ") and detail in text
    assert text.startswith("base versions of support files fail a pre-existing test; tag the task that changed one ")
    assert "round 2 failed the same way as round 1" in text


def test_a_pre_existing_test_that_no_longer_runs_leads_the_same_way(unit):  # noqa: F811
    result, detail = repeat_of(unit, GONE_TITLE)
    assert same_failure_text([base_event()], result, detail).startswith(WAY)


def test_scn_ver_321_another_repeated_failure_keeps_its_text(unit):  # noqa: F811
    result, detail = repeat_of(unit, "a skip or xfail marker was added")
    assert same_failure_text([base_event()], result, detail) == detail
    assert detail.startswith("round 2 failed the same way as round 1: ")


def test_scn_ver_321_an_event_without_support_reverted_gives_the_detail_alone(unit):  # noqa: F811
    result, detail = repeat_of(unit, FAILS_TITLE)
    assert same_failure_text([base_event(support=None)], result, detail) == detail
    assert same_failure_text([], result, detail) == detail
    only_people = [{"path": "a.ts", "tasks": [], "people": True}]
    assert same_failure_text([base_event(support=only_people)], result, detail) == detail


def test_the_newest_event_up_to_the_round_counts():
    old = base_event(1, 1, [{"path": "old.ts", "tasks": ["1.1"], "people": False}])
    new = base_event(2, 2)
    later = base_event(3, 3, [{"path": "later.ts", "tasks": ["9.9"], "people": False}])
    assert base_tests_way_out([old, new, later], 2) == WAY
    assert base_tests_way_out([old, new, later], 1).endswith("old.ts (task 1.1)")


def test_at_most_three_files_and_the_whole_way_out_stays_within_300_characters():
    files = [{"path": f"test/arch/{c}" + "x" * 90 + ".ts", "tasks": ["1.1"], "people": False} for c in "abcd"]
    text = base_tests_way_out([base_event(support=files)], 2)
    assert text.startswith(BASE_TESTS_WAY_OUT) and len(text) <= WAY_OUT_CHARS
    assert "test/arch/a" in text and "test/arch/d" not in text  # a cut drops files, never the way out


def test_the_way_out_survives_the_exit_reasons_cut_with_a_long_unit_id(unit):  # noqa: F811
    result, detail = repeat_of(unit, FAILS_TITLE)
    reason = same_failure_text([base_event()], result, detail)
    unit_id = "openspec:" + "u" * 31  # 40 characters
    shown = f"escalated: {reason}. Next: l4 retry --unit {unit_id} --reason TEXT"[:300]
    assert "then l4 retry:" in shown and "test/arch/modules.ts" in shown
