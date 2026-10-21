import pytest

from l4.s1 import questions as q
from l4.verifier.s1 import QUESTION as STEP8_QUESTION


def test_every_question_maps_from_ground_truth_and_sha_is_stable():
    assert set(q.SETS) == {q.FILE_RELEVANT, q.CHANGE_COVERED, q.TESTS_OK, q.CRITERION}
    cases = {
        q.FILE_RELEVANT: ({"relevant": False}, {"relevant": False, "unrelated": True, "relatedness": 0}),
        q.CHANGE_COVERED: ({"covered": True}, {"exercised": True, "untested": False, "extent": 3}),
        q.TESTS_OK: ({"tests_ok": False}, {"all_passed": False}),
        q.CRITERION: (
            {"satisfied": True},
            {"satisfied": True, "status_fwd": "implemented", "status_rev": "implemented"},
        ),
    }
    for name, (truth, expected) in cases.items():
        got = q.expected_for(name, truth)
        assert got == expected
        assert set(got) <= {s.id for s in q.get_set(name).questions}
        assert q.get_set(name).class_question in got
    # the sha is a function of the question text alone, and any edit moves it
    sets = [q.get_set(n) for n in q.SETS]
    assert len({s.sha256 for s in sets}) == 4
    assert all(s.sha256 == q.get_set(s.name).sha256 and len(s.sha256) == 64 for s in sets)


def test_pinned_shas_change_only_with_the_text():
    import dataclasses

    base = q.get_set(q.TESTS_OK)
    edited = dataclasses.replace(
        base, questions=(dataclasses.replace(base.questions[0], instructions="Did all tests pass?"),)
    )
    assert edited.sha256 != base.sha256


def test_labels_per_set_follow_the_stage_a_semantics():
    f = q.expected_for
    assert f(q.FILE_RELEVANT, {"relevant": True, "named": True})["relatedness"] == 2
    assert f(q.FILE_RELEVANT, {"relevant": True, "named": False})["relatedness"] == 1
    assert "relatedness" not in f(q.FILE_RELEVANT, {"relevant": True})  # a test file: no level to claim
    assert f(q.CHANGE_COVERED, {"covered": False})["extent"] == 0
    assert f(q.CHANGE_COVERED, {"covered": False, "executed": 0, "executable": 4})["untested"] is True
    assert f(q.CHANGE_COVERED, {"covered": True, "executed": 3, "executable": 4})["extent"] == 2
    assert f(q.CHANGE_COVERED, {"covered": True, "executed": 1, "executable": 4})["extent"] == 1
    # criterion: false alone gives no choice label (not_implemented and contradicted cannot be told apart)
    assert f(q.CRITERION, {"satisfied": False}) == {"satisfied": False}
    assert f(q.CRITERION, {}) == {}
    assert f(q.CRITERION, {"satisfied": False, "outcome": "contradicted"})["status_rev"] == "contradicted"
    with pytest.raises(ValueError):
        f(q.CRITERION, {"outcome": "perhaps"})
    with pytest.raises(ValueError):
        f(q.TESTS_OK, {})
    with pytest.raises(q.UnknownQuestionSet):
        f("l4/file-relevant@9", {"relevant": True})


def test_choice_comes_in_both_orders_and_canonical_drops_the_reversed():
    wire = q.get_set(q.CRITERION).wire()
    assert list(wire["status_fwd"]["criteria"]) == list(reversed(list(wire["status_rev"]["criteria"])))
    canonical = q.get_set(q.CRITERION).wire(canonical_only=True)
    assert set(canonical) == {"satisfied", "status_fwd"}


def test_step8_noul_text_is_the_one_verifier_s1_asks():
    assert q.CRITERION_QUESTION == STEP8_QUESTION
    assert q.get_set(q.CRITERION).questions[0].instructions == STEP8_QUESTION


def test_tests_ok_question_is_version_two_and_names_skipped_tests():
    assert q.TESTS_OK == "l4/tests-ok@2"
    text = " ".join(str(v) for v in q.get_set(q.TESTS_OK).questions[0].criteria.values())
    assert "skipped" in text
