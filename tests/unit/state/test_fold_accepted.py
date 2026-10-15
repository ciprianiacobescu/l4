"""review-resolution 3.4 (L4-YOLO-028): `UnitState.accepted_addressed`, the ids that every judge of the latest
PASS round answered `addressed: true` (`review.accepted_judged`). Fail closed: an older ledger, or no answer, is
the empty set."""

from datetime import UTC, datetime, timedelta

from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
RUN = "r-20261016T1200Z-aaaa"
ONE, TWO = "F-0a1b2c", "F-3d4e5f"


def state(*rows: tuple[str, dict]):
    events = [
        LedgerEvent(T0 + timedelta(seconds=n), RUN, "openspec:p", n, kind, data) for n, (kind, data) in enumerate(rows)
    ]
    return fold(events, "openspec:p")


def judged(fid: str, addressed: bool = True, *, round_: int = 1, profile: str = "j1", evidence: str = "a.py:1"):
    data = {"id": fid, "round": round_, "addressed": addressed, "evidence": evidence, "profile": profile}
    return "review.accepted_judged", data


def verdict(name: str = "PASS", round_: int = 1):
    return "verify.verdict", {"round": round_, "verdict": name, "findings": 0}


def test_an_older_ledger_has_nothing_addressed():
    got = state(verdict())
    assert got.accepted_addressed == frozenset() and got.accepted_evidence == {}


def test_addressed_by_the_only_judge_of_a_pass_round():
    assert state(judged(ONE), judged(TWO), verdict()).accepted_addressed == {ONE, TWO}


def test_addressed_by_every_judge_of_two():
    got = state(judged(ONE, profile="j1"), judged(ONE, profile="j2"), verdict())
    assert got.accepted_addressed == {ONE}


def test_addressed_by_one_of_two_judges_is_not_addressed():
    got = state(judged(ONE, profile="j1"), judged(ONE, False, profile="j2", evidence="still inline"), verdict())
    assert got.accepted_addressed == frozenset() and got.accepted_evidence == {ONE: "still inline"}


def test_a_judge_that_answered_for_one_id_only_leaves_the_other_open():
    got = state(judged(ONE, profile="j1"), judged(TWO, profile="j1"), judged(ONE, profile="j2"), verdict())
    assert got.accepted_addressed == {ONE}


def test_not_addressed():
    got = state(judged(ONE, False, evidence="missing"), verdict())
    assert got.accepted_addressed == frozenset() and got.accepted_evidence == {ONE: "missing"}


def test_not_answered_is_recorded_as_not_addressed_with_its_evidence():
    got = state(judged(ONE, False, evidence="not answered"), verdict())
    assert got.accepted_addressed == frozenset() and got.accepted_evidence == {ONE: "not answered"}


def test_a_later_pass_round_that_addresses_it_closes_it():
    got = state(judged(ONE, False), verdict(), judged(ONE, round_=2), verdict(round_=2))
    assert got.accepted_addressed == {ONE} and got.accepted_evidence == {}


def test_a_later_pass_round_without_the_answer_reopens_it():
    got = state(judged(ONE), verdict(), verdict(round_=2))
    assert got.accepted_addressed == frozenset()


def test_an_answer_from_a_fail_round_does_not_count():
    got = state(judged(ONE), verdict("FAIL"))
    assert got.accepted_addressed == frozenset()


def test_a_fail_round_after_a_pass_round_does_not_undo_the_pass_round():
    got = state(judged(ONE), verdict(), judged(TWO, round_=2), verdict("FAIL", 2))
    assert got.accepted_addressed == {ONE}


def test_answers_before_the_verdict_event_of_their_round_only():
    """An answer with no verdict event yet (the round is running) counts for nothing."""
    assert state(judged(ONE)).accepted_addressed == frozenset()


def test_the_state_dumps_the_new_fields_in_a_stable_order():
    from l4.state.fold import dump_state

    text = dump_state(state(judged(ONE), judged(TWO), verdict())).decode()
    assert text == dump_state(state(judged(TWO), judged(ONE), verdict())).decode()
    assert '"accepted_addressed": [\n    "F-0a1b2c",\n    "F-3d4e5f"\n  ]' in text
