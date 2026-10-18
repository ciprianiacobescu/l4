"""An accept of a `judge view:` hold is bound to the content the judge did not see, not to the hold's text (review M1,
L4-VER-043): the hold id stays the text's hash, the accept's hash covers the head blob of every file the hold covers and
the full list of unseen files."""

from datetime import UTC, datetime

from l4.state.ledger import LedgerEvent
from l4.verifier import diffparts as dp
from l4.verifier.ladder import _hold_views, _judge_view_holds
from l4.verifier.verdicts import (
    HoldView,
    _hold_question,
    effective_verdicts,
    hold_id,
    unresolved_holds,
)

_seq = [0]


def ev(kind: str, **data) -> LedgerEvent:
    _seq[0] += 1
    return LedgerEvent(datetime(2026, 10, 18, tzinfo=UTC), "r1", "u", _seq[0], kind, data)


def E(path: str, n: int, fill: str = "x") -> dp.DiffEntry:
    return dp.DiffEntry((path,), fill * n)


def blobs(parts: dp.DiffParts):
    """A blob id per path: the hash of the text the judge would have been shown (stands for the blob id)."""
    import hashlib

    text = {p: e.text for part in parts.parts for e in part.entries for p in e.paths}
    return lambda path: hashlib.sha1(text.get(path, f"unseen:{path}").encode()).hexdigest()  # noqa: S324


def accept_event(hold: str, view: HoldView) -> list[LedgerEvent]:
    target = hold_id(hold)
    return [
        ev("question.raised", id="Q-001", target=target, round=1, text_sha256=view.sha),
        ev("human.verdict", question="Q-001", target=target, decision="accept", by="alex", reason="checked",
           text_sha256=view.sha),
    ]  # fmt: skip


def test_attack_a_cut_file_with_new_content_is_the_same_hold_text_and_a_different_binding():
    r1 = dp.pack([E("data/seed.json", 130_000, "a"), E("src/app.py", 500)])
    r2 = dp.pack([E("data/seed.json", 290_000, "Z"), E("src/app.py", 700)])
    h1, h2 = _judge_view_holds(r1), _judge_view_holds(r2)
    assert h1 == h2 and [hold_id(h) for h in h1] == [hold_id(h) for h in h2]  # the id (the text) is unchanged
    v1, v2 = _hold_views(r1, blobs(r1)), _hold_views(r2, blobs(r2))
    assert v1[h1[0]].sha != v2[h2[0]].sha
    events = accept_event(h1[0], v1[h1[0]])
    in_force = effective_verdicts(events, {hold_id(h): v2[h].sha for h in h2})
    assert hold_id(h2[0]) not in in_force and unresolved_holds(h2, in_force) == h2  # the hold is asked again


def test_an_accept_survives_when_the_content_is_the_same():
    r1 = dp.pack([E("data/seed.json", 130_000, "a"), E("src/app.py", 500)])
    (hold,) = _judge_view_holds(r1)
    view = _hold_views(r1, blobs(r1))[hold]
    in_force = effective_verdicts(accept_event(hold, view), {hold_id(hold): view.sha})
    assert in_force[hold_id(hold)].decision == "accept" and unresolved_holds([hold], in_force) == []


def pads() -> list[dp.DiffEntry]:
    return [E(f"pad/p{i}.py", 120_000) for i in range(8)]  # eight parts of one pad each


def test_attack_a_hidden_unseen_file_swapped_for_another_voids_the_accept():
    unseen1 = [E(f"src/u_{c}.py", 10) for c in "abcdefg"]
    unseen2 = [E(f"src/u_{c}.py", 10) for c in "abcdeX"] + [E("src/u_zz_backdoor.py", 10)]
    b1, b2 = dp.pack(pads() + unseen1), dp.pack(pads() + unseen2)
    (t1,), (t2,) = _judge_view_holds(b1), _judge_view_holds(b2)
    assert "(+2 more)" in t1 and t1 == t2  # the text names five paths and counts the rest: it cannot tell
    v1, v2 = _hold_views(b1, blobs(b1))[t1], _hold_views(b2, blobs(b2))[t2]
    assert v1.sha != v2.sha
    assert len(v1.paths) == 7 and "src/u_f.py" in v1.paths and "src/u_g.py" in v1.paths  # the full unseen list
    in_force = effective_verdicts(accept_event(t1, v1), {hold_id(t2): v2.sha})
    assert unresolved_holds([t2], in_force) == [t2]


def test_the_binding_covers_a_changed_blob_of_a_listed_file_with_the_same_size():
    unseen = [E(f"src/u_{c}.py", 10) for c in "abc"]
    b = dp.pack(pads() + unseen)
    (t,) = _judge_view_holds(b)
    same = _hold_views(b, lambda p: "blob-1")[t]
    other = _hold_views(b, lambda p: "blob-2" if p == "src/u_b.py" else "blob-1")[t]
    assert same.sha != other.sha


def test_the_question_lists_every_unseen_path_and_points_at_verification_md_when_very_long():
    paths = [f"src/u_{c}.py" for c in "abcdefg"]
    hold = "judge view: the diff needs more than 8 parts of 120000 characters: the judge did not see `src/u_a.py`"
    text = " ".join(_hold_question(hold, 1, (), paths=paths).context.split())
    assert "src/u_f.py" in text and "src/u_g.py" in text
    many = [f"src/gen/f{i:04d}.py" for i in range(500)]
    text = " ".join(_hold_question(hold, 1, (), paths=many).context.split())
    assert "src/gen/f0000.py" in text and "src/gen/f0499.py" not in text and "see verdict.json" in text
    assert "400 more" in text or "more unseen" in text
