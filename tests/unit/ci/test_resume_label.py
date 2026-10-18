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
    assert "adds the label `l4:retry`" in text and "one more fix round" in text
    assert "`l4 retry --unit openspec:x --reason TEXT`" in text and "--extend" not in text and "resume" not in text
    assert "Neither the label" not in text


def test_the_escalated_section_with_no_convertible_finding_names_feedback_first():
    """SCN-OPS-38 (L4-OPS-022): the label is the retry, and it helps after the feedback only."""
    from l4.ci.resume_label import halted_section

    text = halted_section(
        "escalated", "no finding of this round can be converted into a fix task", "openspec:x", "l4:resume",
        reason_code="no_convertible_finding",
    )  # fmt: skip
    assert text.index("l4 feedback add --unit openspec:x --kind behaviour") < text.index("l4 retry --unit")
    assert "a retry alone repeats the same verdict" in text and "also the label `l4:retry`" in text
    plain = halted_section("escalated", "fix rounds used 3/3", "openspec:x", "l4:resume", reason_code="same_failure")
    assert "feedback" not in plain


def test_the_escalated_section_at_the_feedback_limit_names_feedback_rounds():
    from l4.ci.resume_label import halted_section

    text = halted_section("escalated", "feedback_rounds_exhausted", "openspec:x", "l4:resume", feedback=True)
    assert text.startswith("### Escalated: feedback_rounds_exhausted")
    assert "adds the label `l4:retry`" in text and "one more feedback round per label event" in text
    assert "`l4 retry --unit openspec:x --reason TEXT`" in text and "--extend" not in text and "resume" not in text
    assert "fix round" not in text and "--extend-fix-rounds" not in text


def test_the_spec_says_the_label_gives_one_fix_round_to_an_escalated_unit():
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[3] / "docs" / "SPEC.md").read_text(encoding="utf-8")
    spec = " ".join(spec.split())
    assert "An `escalated` unit whose fix rounds are used up gets one more fix round per label event" in spec
    assert "`budget.extended{fix_rounds: 1, by: member, signal}`" in spec


def test_a_halted_note_names_retry_not_resume():
    from l4.ci.resume_label import halted_section

    text = halted_section("halted", "max_task_attempts", "openspec:x", "l4:resume")  # the caller still passes `resume`
    assert text.startswith("### Halted: max_task_attempts")
    assert "adds the label `l4:retry`" in text and "`l4 retry --unit openspec:x --reason TEXT`" in text
    assert "resume" not in text


def test_a_refusal_names_the_command_that_works():
    """L4-OPS-008: the token owner's own label points at the command; every other refusal names it too."""
    own = resume_signal(
        ["l4:retry"], [add(20, BOT, "l4:retry")], label="l4:retry", own_id=BOT, access=lambda uid: LEVELS.get(uid),
        consumed=(), unit="openspec:x", command="l4 retry",
    )  # fmt: skip
    assert isinstance(own, Refusal)
    assert own.why.endswith("use l4 retry --unit openspec:x --reason TEXT, or ask another member")
    other = resume_signal(
        ["l4:restart"], [add(21, STRANGER, "l4:restart")], label="l4:restart", own_id=BOT,
        access=lambda uid: LEVELS.get(uid), consumed=(), unit="openspec:x", command="l4 restart",
    )  # fmt: skip
    assert isinstance(other, Refusal) and "not a member" in other.why
    assert "l4 restart --unit openspec:x --reason TEXT" in other.why


def test_the_refused_note_header_is_unchanged():
    from l4.ci.resume_label import resume_refused_note

    assert resume_refused_note({"label:1": "why"}).startswith("### The `l4:resume` label was not honoured")


def test_scn_ver_138_the_escalated_section_with_judge_view_rejected_names_its_own_way_out():
    """L4-VER-044: split the change, or replace the answer with `accept`; never feedback."""
    from l4.ci.resume_label import halted_section
    from l4.state.next_step import judge_view_way_out

    text = halted_section(
        "escalated", "a person rejected a hold on the judge's view of the diff", "openspec:x", "l4:resume",
        reason_code="judge_view_rejected",
    )  # fmt: skip
    assert text.startswith("### Escalated: a person rejected a hold on the judge's view of the diff\n\n")
    assert text.endswith(f"To go on: {judge_view_way_out('openspec:x')}.")
    assert "l4 restart --unit openspec:x" in text and "--replace" in text and "l4 retry --unit openspec:x" in text
    assert "feedback" not in text
