"""The sticky sections of the delegate (delegate-answers 12.1; L4-CLR-004, L4-DLG-008; SCN-DLG-25, SCN-DLG-45)."""

from l4.clarifier.notify import (
    DelegateAnswer,
    DelegateEscalation,
    answered_by_delegate_section,
    needs_person_section,
)


def test_needs_a_person_section():
    section = needs_person_section(
        [
            DelegateEscalation("Q-002", "product", "Allow unverified e-mails?", "no project document decides this"),
            DelegateEscalation(
                "fix-1/Q-001", None, "Which\n@all <b>[x](http://evil)</b>", "the answer\nwould unfreeze `t.py`"
            ),
        ]
    )  # fmt: skip
    lines = section.splitlines()
    assert lines[0] == "### Needs a person (the delegate escalated)"
    assert "- Q-002 (product): Allow unverified e-mails?: no project document decides this" in lines
    nasty = next(line for line in lines if line.startswith("- fix-1/Q-001"))
    assert "(unlabelled)" in nasty and "@all" not in nasty and "](http" not in nasty and "<b>" not in nasty
    assert "\n" not in nasty and "'t.py'" in nasty  # one line, no markup
    assert needs_person_section([]) == ""


def test_answered_by_the_delegate_section():
    section = answered_by_delegate_section(
        [DelegateAnswer("Q-001", "technical", "Which error?", "claude-opus-5-5", "claude-code")]
    )  # fmt: skip
    assert section.splitlines()[0] == "### Answered by the delegate"
    assert "- Q-001 (technical): Which error? (claude-opus-5-5 via claude-code)" in section
    assert answered_by_delegate_section([]) == ""
