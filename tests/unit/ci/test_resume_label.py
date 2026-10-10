from l4.ci.resume_label import Refusal, ResumeSignal, resume_signal
from l4.forge.base import LabelEvent

LABEL = "l4:resume"
BOT, MEMBER, REPORTER, STRANGER = 62, 3, 9, 77
LEVELS = {BOT: 30, MEMBER: 40, REPORTER: 20}


def add(event_id: int, user: int | None, label: str = LABEL, action: str = "add") -> LabelEvent:
    return LabelEvent(event_id, label, action, user)  # type: ignore[arg-type]


def decide(events, *, labels=(LABEL,), consumed=frozenset(), own=BOT):
    return resume_signal(labels, events, label=LABEL, own_id=own, access=lambda uid: LEVELS.get(uid), consumed=consumed)


def test_a_developer_label_is_a_signal():
    got = decide([add(10, MEMBER)])
    assert got == ResumeSignal(event_id=10, signal="label:10", user_id=MEMBER, access_level=40)


def test_a_reporter_is_refused():
    got = decide([add(11, REPORTER)])
    assert isinstance(got, Refusal) and got.signal == "label:11" and "Developer" in got.why
    stranger = decide([add(12, STRANGER)])
    assert isinstance(stranger, Refusal) and "not a member" in stranger.why


def test_the_bot_is_refused_although_it_is_a_developer():
    got = decide([add(13, BOT)])  # the probed level of the project's bot is 30: the level check alone would pass it
    assert isinstance(got, Refusal) and "harness" in got.why
    unknown = decide([add(14, MEMBER)], own=None)  # the harness cannot tell who it is: fail closed
    assert isinstance(unknown, Refusal)


def test_a_consumed_event_id_is_no_signal():
    assert decide([add(10, MEMBER)], consumed={"label:10"}) is None
    assert isinstance(decide([add(10, MEMBER), add(15, MEMBER)], consumed={"label:10"}), ResumeSignal)


def test_the_latest_add_wins_and_a_removed_label_is_none():
    got = decide([add(10, REPORTER), add(11, MEMBER), add(12, MEMBER, "bug")])
    assert isinstance(got, ResumeSignal) and got.event_id == 11
    assert decide([add(10, MEMBER)], labels=()) is None  # the label is not on the MR now
    assert decide([add(10, MEMBER), add(11, MEMBER, action="remove")]) is None
    assert decide([]) is None  # a label with no event (a forge that cannot say) is never a signal


# --- M1.13 line 19 (W-C2): an escalated unit is resumed, with one more fix round ----------------------------------


def test_the_escalated_section_says_how_the_unit_goes_on():
    from l4.ci.resume_label import halted_section

    text = halted_section("escalated", "fix rounds used 3/3", "openspec:x", "l4:resume")
    assert text.startswith("### Escalated: fix rounds used 3/3")
    assert "adds the label `l4:resume`" in text and "one more fix round" in text
    assert "l4 resume --unit openspec:x --reason TEXT --extend-fix-rounds N" in text
    assert "Neither the label" not in text


def test_the_spec_says_the_label_gives_one_fix_round_to_an_escalated_unit():
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[3] / "docs" / "SPEC.md").read_text(encoding="utf-8")
    spec = " ".join(spec.split())
    assert "An `escalated` unit whose fix rounds are used up gets one more fix round per label event" in spec
    assert "`budget.extended{fix_rounds: 1, by: member, signal}`" in spec
