"""own-test-repair (L4-IMP-091): adding the `repair` check leaves the question of every other held check as it was. The
digests are those of the Context that `held_question` built for the same input before the change (commit 2539f015);
title and options are written out."""

import hashlib

import pytest

from l4.implementer.held import ACCEPT_OPTION, RETRY_OPTION, HeldCheck, held_question

CONTEXT_SHA256 = {
    ("at_red", False): "3907e1ecebf5a605ec545e3451581bc7acd7f694cc164605c3d12817b75c22cb",
    ("at_red", True): "4a9ef2f7030172d158797f7abe8bf90b3a07e4e6283b90ae6fb2e96ac24dcb2a",
    ("pre_satisfied", False): "9833076cee503e9a1fe174623d5f61efef65e84014936aac8da074ae9af6ef2e",
    ("pre_satisfied", True): "76ccc01eae834c4e401790d316f93e5488cbcb4ceab2ed5ef8960ca47245a596",
    ("tests", False): "ddd6b96237153102e69ef604006fc3c43429ccada64ca8f15f83ef973f508444",
    ("tests", True): "aa564abef5397b1396c3b043d85480879b641ad44d69458d72f83ff31deb8e8b",
    ("vacuity", False): "9e99d8302cdda3dd132044a343679cded007f1eb8b700a518f0479061f9a2430",
    ("vacuity", True): "c739d1063157b6771194e08ade50f0b87f8b45e6d01423edf2dc0796f0974fde",
}
TITLE = {
    "pre_satisfied": "Task 1.1: the pre-satisfied check could not decide",
    "vacuity": "Task 1.1: the run (b) zero-value check could not decide",
    "at_red": "Task 1.1: the test-at-red check could not decide",
    "tests": "Task 1.1: the test chore discrimination check could not decide",
}


def held(check: str, saved: bool) -> HeldCheck:
    criteria = ("C-1",) if check in ("pre_satisfied", "vacuity") else ()
    return HeldCheck(
        "1.1", "red" if criteria else "green", check, criteria,  # type: ignore[arg-type]
        ("tests.test_a::test_x",), "the run could not decide", runs=("zero", "base"), kept=("f",),
        patch=b"diff" if saved else None, result="{}" if saved else "",
        sources=(("tests.test_a::test_x", "def test_x():\n    assert 1"),),
        patch_path=f".l4/held/1.1-{check}.patch", changes=("added tests/test_a.py",),
        diffs=(("tests/test_a.py", "+def test_x():\n+    assert 1"),),
    )  # fmt: skip


@pytest.mark.parametrize(("check", "saved"), sorted(CONTEXT_SHA256))
def test_the_question_of_every_other_check_is_byte_for_byte_what_it_was(check, saved):
    question = held_question(held(check, saved), {}, "ASKED")
    assert question.title == TITLE[check]
    assert question.options == ((ACCEPT_OPTION, RETRY_OPTION) if saved else (RETRY_OPTION,))
    assert hashlib.sha256(question.context.encode()).hexdigest() == CONTEXT_SHA256[check, saved]


def test_the_question_of_a_repair_has_its_own_head_and_person_only_line():
    question = held_question(held("repair", True), {}, "ASKED")
    assert question.title == "Task 1.1: a repair of the unit's own failing tests waits for a person"
    assert question.options == ("accept: apply this edit", "retry: <note>")
    assert "Only a person can accept a repair of a test; no agent or delegate answer applies it." in question.context
    assert "an agent only where" not in question.context
