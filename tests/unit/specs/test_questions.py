import hashlib
import re
from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.specs.base import Criterion, Framework, SpecError
from l4.specs.questions import (
    INDEX_END,
    INDEX_START,
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    accept_text,
    answer_sha256,
    answered_by,
    blocked_tasks,
    edit_option,
    effective_answer,
    is_answered,
    option_suggestion,
    raise_questions,
)

EM = "\N{EM DASH}"
REDACTOR = Redactor({})


def question(**overrides) -> NewQuestion:
    values = dict(
        title="Should unverified e-mails be allowed to log in?",
        kind=QuestionKind.PRODUCT,
        blocking_tasks=("3.1", "3.2"),
        context='The scenario says "WHEN a user logs in" but does not cover unverified accounts.',
        options=("Block login until verified.", "Allow login, restrict features."),
        asked="2026-10-03T13:12:00Z by implementer `codex`, run r-20261003T1312Z-7f3a, task 3.1",
    )
    return NewQuestion(**{**values, **overrides})


def ask(unit: Path, *batch: NewQuestion, redactor: Redactor = REDACTOR) -> list[str]:
    return raise_questions(unit, "add-login", list(batch), redactor=redactor)


def test_a_new_file_follows_the_spec_grammar(tmp_path: Path):
    criterion = Criterion(
        "C-1a2b3c4d", "auth › Login › Unverified account", Framework.OPENSPEC, "auth", "Login", "Unverified", "", "", 1
    )
    assert ask(tmp_path, question(criteria=(criterion,))) == ["Q-001"]
    text = (tmp_path / "questions.md").read_text(encoding="utf-8")
    assert text == (
        f"# Questions {EM} add-login\n\n"
        "<!-- l4:questions v1\n"
        'How to answer: write under "### Answer" and set **Status** to `answered`.\n'
        "To accept the clarifier's suggestion as-is, set **Status** to `accepted`.\n"
        "Status values: open · answered · accepted · answered-by-clarifier · dismissed · superseded\n"
        "Kind values: technical · product · ambiguous · verdict · harness. For a `verdict` question, start the answer "
        "with `accept` or\n`reject`, then give your reason; for a `harness` question, with `accept` or `retry`.\n"
        "Do not change question IDs. Commit and push to the l4/… branch to resume the run. -->\n\n"
        "<!-- l4:index:start -->\n"
        "| ID | Status | Blocking | Kind | Question |\n"
        "|----|--------|----------|------|----------|\n"
        "| Q-001 | open | 3.1, 3.2 | product | Should unverified e-mails be allowed to log in? |\n"
        "<!-- l4:index:end -->\n\n"
        "---\n\n"
        "## Q-001: Should unverified e-mails be allowed to log in?\n\n"
        "- **Status:** open\n"
        "- **Blocking tasks:** 3.1, 3.2\n"
        "- **Kind:** product\n"
        "- **Asked:** 2026-10-03T13:12:00Z by implementer `codex`, run r-20261003T1312Z-7f3a, task 3.1\n"
        "- **Criteria:** C-1a2b3c4d (auth › Login › Unverified account)\n\n"
        "### Context\n"
        'The scenario says "WHEN a user logs in" but does not cover unverified accounts.\n\n'
        "### Options\n"
        "1. Block login until verified.\n"
        "2. Allow login, restrict features.\n\n"
        "### Answer\n"
        "<!-- write below this line -->\n"
    )


def test_raise_question_changes_only_index_and_appended_section(tmp_path: Path):
    ask(tmp_path, question())
    path = tmp_path / "questions.md"
    # a human answers Q-001 and adds free text everywhere the harness does not own
    edited = path.read_bytes().replace(
        b"<!-- write below this line -->\n", b"<!-- write below this line -->\nOption 1, per design.md.\n\n\nNotes: ok"
    )
    edited = edited.replace(b"- **Status:** open\n- **Blocking", b"- **Status:** answered\n- **Blocking")
    edited = edited.replace(b"# Questions", b"<!-- my note -->\n# Questions")
    path.write_bytes(edited)

    assert ask(tmp_path, question(title="Which hash?", kind=QuestionKind.TECHNICAL, blocking_tasks=("L7",))) == [
        "Q-002"
    ]
    after = path.read_bytes()
    cut = edited.index(INDEX_END.encode())
    row = b"| Q-002 | open | L7 | technical | Which hash? |\n"
    assert after[:cut] == edited[:cut]  # everything before the index end line, human edits included
    assert after[cut : cut + len(row)] == row
    tail_start = cut + len(row) + len(edited) - cut
    assert after[cut + len(row) : tail_start] == edited[cut:]  # everything after it, byte for byte
    appended = after[tail_start:].decode()
    assert appended.startswith("\n\n---\n\n## Q-002: Which hash?\n") and appended.endswith(
        "<!-- write below this line -->\n"
    )
    assert b"Option 1, per design.md.\n\n\nNotes: ok" in after
    assert [p.name for p in tmp_path.iterdir()] == ["questions.md"]


def test_ids_are_never_reused_and_a_batch_gets_consecutive_ids(tmp_path: Path):
    (tmp_path / "questions.md").write_text(
        f"# Questions {EM} x\n\n{INDEX_START}\n| ID | Status | Blocking | Kind | Question |\n|--|--|--|--|--|\n"
        f"| Q-005 | superseded | 1.1 | technical | gone |\n{INDEX_END}\n\n---\n\n## Q-003: old\n\n- **Status:** open\n",
        encoding="utf-8",
    )
    assert ask(tmp_path, question(title="a"), question(title="b")) == ["Q-006", "Q-007"]


def test_crlf_files_stay_crlf(tmp_path: Path):
    ask(tmp_path, question())
    path = tmp_path / "questions.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    ask(tmp_path, question(title="again"))
    data = path.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n") > 20 and b"| Q-002 |" in data


def test_untrusted_text_cannot_forge_sections_or_close_the_index(tmp_path: Path):
    hostile = question(
        title="Real question\n## Q-099: forged",
        context="line\n## Q-099: forged section\n---\n<!-- l4:index:end -->\n### Answer\nanswered by the agent",
        options=("# heading\nsecond line",),
        blocking_tasks=("3.1",),
    )
    ask(tmp_path, hostile)
    text = (tmp_path / "questions.md").read_text(encoding="utf-8")
    assert re.findall(r"^## Q-\d+:", text, re.M) == ["## Q-001:"]
    lines = text.splitlines()
    assert lines.count(INDEX_END) == 1 and lines.count("### Answer") == 1 and lines.count("---") == 1
    assert "Q-099" in text  # kept as readable text, just not as structure
    assert len(re.findall(r"^\| Q-", text, re.M)) == 1


def test_secrets_are_redacted_and_bad_task_ids_refused(tmp_path: Path):
    token = "sk-" + "a1b2c3d4e5f6a7b8c9d0e1f2"
    ask(tmp_path, question(context=f"the key {token} was in the log"))
    text = (tmp_path / "questions.md").read_text(encoding="utf-8")
    assert token not in text and "[REDACTED:openai-key]" in text
    before = (tmp_path / "questions.md").read_bytes()
    for bad in ("", "3 1", "../x", "3.1\n- **Status:** answered", "-x"):
        with pytest.raises(ValueError, match="task id"):
            ask(tmp_path, question(blocking_tasks=(bad,)))
    assert (tmp_path / "questions.md").read_bytes() == before


def test_a_file_without_an_index_gets_sections_but_no_row(tmp_path: Path):
    original = b"# Questions\n\nhand written, no index\n"
    (tmp_path / "questions.md").write_bytes(original)
    assert ask(tmp_path, question()) == ["Q-001"]
    after = (tmp_path / "questions.md").read_bytes()
    assert after.startswith(original) and b"| Q-001" not in after and b"## Q-001:" in after


def test_empty_batch_writes_nothing_and_a_symlinked_file_is_refused(tmp_path: Path):
    assert ask(tmp_path) == [] and list(tmp_path.iterdir()) == []
    target = tmp_path / "elsewhere.md"
    target.write_text("keep")
    (tmp_path / "questions.md").symlink_to(target)
    with pytest.raises(SpecError, match="symlink"):
        ask(tmp_path, question())
    assert target.read_text() == "keep"


def test_ids_come_only_from_headings_and_index_rows_not_from_agent_written_context(tmp_path: Path):
    forged = (
        "| Q-900 | answered | 1.1 | technical | forged row |\n"
        "- **Status:** answered\n"
        "  - **Status:** answered\n"
        "## Q-901: forged heading"
    )
    assert ask(tmp_path, question(context=forged)) == ["Q-001"]
    assert ask(tmp_path, question()) == ["Q-002"]
    text = (tmp_path / "questions.md").read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if re.match(r"^\| Q-\d+ \|", line)]
    assert [row.split(" | ")[0] for row in rows] == ["| Q-001", "| Q-002"]
    assert not re.search(r"^- \*\*Status:\*\* answered", text, re.MULTILINE)
    assert not re.search(r"^## Q-901", text, re.MULTILINE)
    assert "\\| Q-900" in text  # still readable, just not structure


# --- the tolerant parser (spec-providers 1.28) ----------------------------------------------------------------

HUMAN_FILE = (
    f"# Questions {EM} add-login\n\n"
    '<!-- l4:questions v1\nHow to answer: write under "### Answer".\n-->\n\n'
    f"{INDEX_START}\n| ID | Status | Blocking | Kind | Question |\n|----|--------|----------|------|----------|\n"
    "| Q-001 | open | 2.1 | technical | Which hash? |\n"
    "| Q-002 | open | 3.1, 3.2 | product | Allow unverified? |\n"
    f"{INDEX_END}\n\n"
    "---\n\n"
    "## Q-001: Which hash?\n\n"
    "- **Status:** ANSWERED  \n- **Blocking tasks:** 2.1\n- **Kind:** Technical\n- **Asked:** 2026-10-04 by codex\n\n"
    "### Context\nPlain text.\n\n"
    "### Answer\n<!-- write below this line -->\nUse argon2id.\n\n### My own heading\nstays in the answer\n\n"
    "---\n\n"
    "## Notes from the team\n\nfree text the harness does not own\n\n"
    "---\n\n"
    "## Q-002: Allow unverified?\n\n"
    "- **Status:** yes\n- **Blocking tasks:** 3.1, 3.2\n- **Kind:** product\n\n"
    "### Clarifier suggestion\n_confidence: low_\nOption 1.\n\n"
    "### Answer\n<!-- write below this line -->\n"
)


def test_parse_grammar_tolerant_status_and_missing_index():
    parsed = QuestionsFile.parse(HUMAN_FILE)
    q1, q2 = parsed.questions
    assert (q1.id, q1.title, q1.status, q1.kind) == (
        "Q-001",
        "Which hash?",
        QuestionStatus.ANSWERED,
        QuestionKind.TECHNICAL,
    )
    assert q1.blocking_tasks == ("2.1",) and q1.asked == "2026-10-04 by codex"
    assert q1.answer_text == "Use argon2id.\n\n### My own heading\nstays in the answer"
    assert (q2.id, q2.status, q2.blocking_tasks, q2.suggestion_text) == (
        "Q-002",
        QuestionStatus.OPEN,
        ("3.1", "3.2"),
        "_confidence: low_\nOption 1.",
    )
    assert [(i.kind, i.question_id) for i in parsed.issues] == [("unknown_status", "Q-002")]
    data = HUMAN_FILE.encode()
    # the spans point at the bytes they name
    assert data[q1.status_value.start : q1.status_value.end] == b"ANSWERED"
    assert data[parsed.index.start : parsed.index.end].startswith(b"| ID |")
    assert data[q1.section.start :].startswith(b"## Q-001:") and data[q1.section.end :].startswith(b"\n---\n\n## Notes")
    assert data[q2.suggestion.heading.start :].startswith(b"### Clarifier suggestion")
    assert data[q2.answer.body.start : q2.answer.body.end] == b"<!-- write below this line -->\n"
    # the team's own section is not a question and is not part of Q-001's answer
    assert "free text" not in q1.answer_text


def test_a_missing_index_is_reported_and_a_bytes_str_input_agree():
    without = HUMAN_FILE.replace(INDEX_START, "").replace(INDEX_END, "")
    parsed = QuestionsFile.parse(without.encode())
    assert parsed.index is None and [q.id for q in parsed.questions] == ["Q-001", "Q-002"]
    assert QuestionsFile.parse(HUMAN_FILE) == QuestionsFile.parse(HUMAN_FILE.encode())
    empty = QuestionsFile.parse("")
    assert empty.questions == () and empty.index is None and empty.issues == ()


def test_status_values_are_case_insensitive_and_may_carry_decoration():
    for written, expected in (
        ("Answered", QuestionStatus.ANSWERED),
        ("`accepted`", QuestionStatus.ACCEPTED),
        ("ANSWERED-BY-CLARIFIER", QuestionStatus.ANSWERED_BY_CLARIFIER),
        ("dismissed (not needed)", QuestionStatus.DISMISSED),
        ("Superseded by Q-004", QuestionStatus.SUPERSEDED),
    ):
        text = f"## Q-001: t\n\n- **Status:** {written}\n- **Blocking tasks:** 1.1\n"
        assert QuestionsFile.parse(text).questions[0].status is expected, written


def test_a_hostile_answer_cannot_end_its_own_section_inside_a_code_fence():
    text = (
        "## Q-001: t\n\n- **Status:** answered\n- **Blocking tasks:** 1.1\n\n### Answer\n"
        "```\n## Q-999: not a question\n### Context\n```\nreal text\n"
    )
    parsed = QuestionsFile.parse(text)
    assert [q.id for q in parsed.questions] == ["Q-001"] and "real text" in parsed.questions[0].answer_text


def test_a_harness_written_fence_line_cannot_open_a_fence(tmp_path: Path):
    ask(tmp_path, question(context="The test calls:\n```python\nclient.get(...)\n~~~"))
    ask(tmp_path, question(title="Second", blocking_tasks=("1.2",)))
    data = (tmp_path / "questions.md").read_bytes()
    parsed = QuestionsFile.parse(data)
    assert [q.id for q in parsed.questions] == ["Q-001", "Q-002"]
    assert parsed.get("Q-001").answer is not None and parsed.issues == ()
    assert blocked_tasks(parsed.questions, ["1.2"]) == {"1.2"}


def test_an_unclosed_fence_in_a_human_answer_ends_at_the_next_question():
    text = (
        "## Q-001: a\n\n- **Status:** answered\n- **Blocking tasks:** 1.1\n\n### Answer\n"
        "Call it like this:\n```python\nclient.get(...)\n\n---\n\n"
        "## Q-002: b\n\n- **Status:** open\n- **Blocking tasks:** 1.2\n\n### Answer\n<!-- write below -->\n"
    )
    parsed = QuestionsFile.parse(text)
    assert [q.id for q in parsed.questions] == ["Q-001", "Q-002"]
    assert "client.get" in parsed.questions[0].answer_text
    assert parsed.questions[1].answer is not None
    assert blocked_tasks(parsed.questions, ["1.1", "1.2"]) == {"1.2"}


def test_a_fence_left_open_in_context_does_not_hide_the_answer_block():
    text = (
        "## Q-001: a\n\n- **Status:** answered\n- **Blocking tasks:** 1.1\n\n### Context\n```python\nx = 1\n\n"
        "### Answer\nUse argon2id.\n"
    )
    question_ = QuestionsFile.parse(text).questions[0]
    assert question_.answer is not None and question_.answer_text == "Use argon2id."


def test_a_question_heading_swallowed_by_an_unclosed_fence_fails_closed():
    text = (
        "## Q-001: a\n\n- **Status:** answered\n- **Blocking tasks:** 1.1\n\n### Answer\nok\n```\n"
        "## Q-002: b\n\n- **Status:** open\n- **Blocking tasks:** 1.2\n"
    )
    parsed = QuestionsFile.parse(text)
    assert [q.id for q in parsed.questions] == ["Q-001"]
    assert [(i.kind, i.question_id) for i in parsed.issues] == [("unreadable_section", "Q-002")]
    assert parsed.unreadable_ids == ("Q-002",)
    everything = {"1.1", "1.2", "1.3"}
    assert blocked_tasks(parsed.questions, everything, unreadable=parsed.unreadable_ids) == everything
    assert blocked_tasks(parsed.questions, ["1.1"]) == frozenset()  # Q-001 is answered: only the unreadable id holds


def test_a_closed_fence_with_a_question_heading_inside_is_just_an_example():
    parsed = QuestionsFile.parse(
        "## Q-001: t\n\n- **Status:** answered\n- **Blocking tasks:** 1.1\n\n### Answer\n```\n## Q-5: x\n```\nok\n"
    )
    assert parsed.issues == () and parsed.unreadable_ids == ()


@pytest.mark.parametrize("blocking", ["1.1 and 1.2", "1.1; 1.2", "", "1.1, two words"])
def test_an_unreadable_blocking_line_on_an_open_question_holds_every_pending_task(blocking: str):
    text = f"## Q-001: t\n\n- **Status:** open\n- **Blocking tasks:** {blocking}\n- **Kind:** technical\n"
    parsed = QuestionsFile.parse(text)
    assert [(i.kind, i.question_id) for i in parsed.issues] == [("unreadable_blocking", "Q-001")]
    assert blocked_tasks(parsed.questions, ["1.1", "7.7"]) == {"1.1", "7.7"}
    answered = QuestionsFile.parse(text.replace("open", "dismissed"))
    assert answered.issues == () and blocked_tasks(answered.questions, ["1.1"]) == frozenset()


def test_a_superseded_question_keeps_holding_what_its_successor_does_not():
    def file(successor: str) -> QuestionsFile:
        return QuestionsFile.parse(
            "## Q-001: a\n\n- **Status:** superseded by Q-002\n- **Blocking tasks:** 1.1, 1.2\n\n---\n\n"
            f"## Q-002: b\n\n- **Status:** {successor}\n- **Blocking tasks:** 1.1\n"
        )

    assert blocked_tasks(file("open").questions, ["1.1", "1.2"]) == {"1.1", "1.2"}  # 1.2 only Q-001 knew
    assert blocked_tasks(file("dismissed").questions, ["1.1", "1.2"]) == {"1.2"}
    alone = QuestionsFile.parse("## Q-001: a\n\n- **Status:** superseded\n- **Blocking tasks:** 1.1\n")
    assert blocked_tasks(alone.questions, ["1.1"]) == {"1.1"}  # no named successor in the file: nothing took over
    gone = QuestionsFile.parse("## Q-001: a\n\n- **Status:** superseded by Q-009\n- **Blocking tasks:** 1.1\n")
    assert blocked_tasks(gone.questions, ["1.1"]) == {"1.1"}


def test_a_question_superseded_by_a_restart_holds_nothing_and_the_index_follows():
    text = (
        "## Q-001: a\n\n- **Status:** open\n- **Blocking tasks:** 1.1\n\n---\n\n"
        "## Q-002: b\n\n- **Status:** open\n- **Blocking tasks:** 1.2\n"
    )
    file = QuestionsFile.parse(text).supersede_by_restart("Q-001")
    one = file.get("Q-001")
    assert one is not None and one.status is QuestionStatus.SUPERSEDED and one.superseded_by is None
    assert "- **Status:** superseded by restart\n" in file.data.decode()
    assert "| Q-001 | superseded |" in file.data.decode()  # the index row follows (the file has no index: one is added)
    assert blocked_tasks(file.questions, ["1.1", "1.2"]) == {"1.2"}  # a plain `superseded` would still hold 1.1


def test_a_stale_index_row_is_refreshed_and_only_that_row_changes(tmp_path: Path):
    ask(tmp_path, question(), question(title="Second"), question(title="Third"))
    path = tmp_path / "questions.md"
    data = path.read_bytes().replace(b"- **Status:** open", b"- **Status:** dismissed", 1)  # Q-001 only, by hand
    data = data.replace(b"| Q-003 |", b"| Q-009 |")  # Q-003 has no row any more: it stays without one
    file = QuestionsFile.parse(data)
    refreshed = file.refresh_index()
    assert refreshed.data.count(b"| Q-001 | dismissed |") == 1 and b"| Q-001 | open |" not in refreshed.data
    assert refreshed.data.count(b"| Q-002 | open |") == 1
    after_rows = refreshed.data.split(b"<!-- l4:index:end -->", 1)[1]
    assert after_rows == data.split(b"<!-- l4:index:end -->", 1)[1]  # the sections are byte-identical
    assert b"| Q-003 |" not in refreshed.data
    assert refreshed.refresh_index().data == refreshed.data  # idempotent
    assert QuestionsFile.parse(b"## Q-001: t\n\n- **Status:** dismissed\n").refresh_index().index is None


# --- answer semantics (spec-providers 1.29) -------------------------------------------------------------------


def one(status: str, *, answer: str = "", suggestion: str | None = None, tasks: str = "1.1") -> "object":
    parts = [f"## Q-001: t\n\n- **Status:** {status}\n- **Blocking tasks:** {tasks}\n- **Kind:** technical\n\n"]
    if suggestion is not None:
        parts.append(f"### Clarifier suggestion\n{suggestion}\n\n")
    parts.append(f"### Answer\n<!-- write below this line -->\n{answer}\n")
    return QuestionsFile.parse("".join(parts))


def test_answered_semantics_and_blocked_tasks():
    answered = one("answered", answer="Use argon2id.").questions[0]
    assert is_answered(answered) and effective_answer(answered) == "Use argon2id." and answered_by(answered) == "human"
    # a draft is never consumed, and it is reported
    draft = one("open", answer="Use argon2id.")
    assert not is_answered(draft.questions[0]) and effective_answer(draft.questions[0]) is None
    assert [(i.kind, i.question_id) for i in draft.issues] == [("unsubmitted_answer", "Q-001")]
    assert one("open").issues == ()  # the placeholder comment alone is not an answer
    # accepted and answered-by-clarifier use the suggestion
    accepted = one("accepted", suggestion="Use bcrypt.", answer="ignored").questions[0]
    assert is_answered(accepted) and effective_answer(accepted) == "Use bcrypt." and answered_by(accepted) == "human"
    clar = one("answered-by-clarifier", suggestion="Use bcrypt.").questions[0]
    assert effective_answer(clar) == "Use bcrypt." and answered_by(clar) == "clarifier"
    # nothing to consume: not answered, and the file says why
    for blank in (one("answered"), one("accepted"), one("answered-by-clarifier", suggestion="")):
        assert not is_answered(blank.questions[0]), blank
        assert [i.kind for i in blank.issues] == ["empty_answer"]
    # dismissed unblocks without an answer
    dismissed = one("dismissed").questions[0]
    assert is_answered(dismissed) and effective_answer(dismissed) is None and answered_by(dismissed) == "human"
    assert answer_sha256(dismissed) is None
    assert answer_sha256(answered) == hashlib.sha256(b"Use argon2id.").hexdigest()
    assert answer_sha256(one("answered", answer="Use argon2id.   \n\n").questions[0]) == answer_sha256(answered)


def test_blocked_tasks_are_held_per_question():
    text = (
        "## Q-001: a\n\n- **Status:** open\n- **Blocking tasks:** 1.1, 1.2\n\n---\n\n"
        "## Q-002: b\n\n- **Status:** dismissed\n- **Blocking tasks:** 2.1\n\n---\n\n"
        "## Q-003: c\n\n- **Status:** superseded by Q-004\n- **Blocking tasks:** 3.1\n\n---\n\n"
        "## Q-004: d\n\n- **Status:** maybe\n- **Blocking tasks:** 3.1, 9.9\n"
    )
    questions = QuestionsFile.parse(text).questions
    assert blocked_tasks(questions, ["1.1", "2.1", "3.1", "4.1"]) == {"1.1", "3.1"}  # 1.2 is done, 9.9 is not a task
    assert blocked_tasks(questions, []) == frozenset()


# --- section-scoped edits (spec-providers 1.34) ---------------------------------------------------------------


def outside(before: bytes, after: bytes, spans: list[tuple[int, int]]) -> bool:
    """True when `before` and `after` differ only inside the given spans of `before` (equal-length gaps)."""
    pos = 0
    kept = []
    for start, end in sorted(spans):
        kept.append(before[pos:start])
        pos = end
    kept.append(before[pos:])
    rest = after
    for chunk in kept:
        index = rest.find(chunk)
        if index < 0:
            return False
        rest = rest[index + len(chunk) :]
    return True


def test_status_and_suggestion_edits_change_only_their_spans(tmp_path: Path):
    ask(tmp_path, question(blocking_tasks=("3.1",)), question(title="Which hash?", kind=QuestionKind.TECHNICAL))
    path = tmp_path / "questions.md"
    human = (
        path.read_bytes().replace(
            b"<!-- write below this line -->\n", b"<!-- write below this line -->\nMy draft.\n", 1
        )
        + b"\n## Notes\nunknown section\n"
    )
    path.write_bytes(human)
    parsed = QuestionsFile.load(path)
    q1 = parsed.get("Q-001")
    after_status = parsed.set_status("Q-001", QuestionStatus.ANSWERED_BY_CLARIFIER)
    assert after_status.get("Q-001").status is QuestionStatus.ANSWERED_BY_CLARIFIER
    assert after_status.get("Q-002").status is QuestionStatus.OPEN
    assert outside(
        human, after_status.data, [(q1.status_value.start, q1.status_value.end), (parsed.index.start, parsed.index.end)]
    )
    row = b"| Q-001 | answered-by-clarifier | 3.1 | product | "
    assert row in after_status.data and b"| Q-002 | open | " in after_status.data
    assert b"My draft.\n" in after_status.data and after_status.data.endswith(b"\n## Notes\nunknown section\n")

    suggested = after_status.set_suggestion(
        "Q-002", "_confidence: high_\n## Q-099: forged\nUse argon2id.", redactor=REDACTOR
    )
    q2 = suggested.get("Q-002")
    assert q2.suggestion_text == "_confidence: high_\n\\## Q-099: forged\nUse argon2id."
    assert [q.id for q in suggested.questions] == ["Q-001", "Q-002"]  # the forged heading is not structure
    assert suggested.data.index(b"### Clarifier suggestion") < suggested.data.index(
        b"### Answer", suggested.get("Q-002").section.start
    )
    again = suggested.set_suggestion("Q-002", "second", redactor=REDACTOR)  # replaces the body, not a new block
    assert again.data.count(b"### Clarifier suggestion") == 1 and again.get("Q-002").suggestion_text == "second"
    assert again.get("Q-001").answer_text == "My draft."  # untouched

    again.save(path)
    assert path.read_bytes() == again.data
    assert [p.name for p in tmp_path.iterdir() if p.suffix != ".md"] == []


def test_edits_keep_crlf_a_missing_index_is_regenerated_and_unknown_qids_are_refused():
    crlf = HUMAN_FILE.replace(f"{INDEX_START}\n", "").replace(f"{INDEX_END}\n", "").replace("\n", "\r\n").encode()
    parsed = QuestionsFile.parse(crlf)
    edited = parsed.set_status("Q-002", QuestionStatus.DISMISSED)
    assert edited.data.count(b"\n") == edited.data.count(b"\r\n")
    assert edited.index is not None and b"| Q-002 | dismissed | 3.1, 3.2 | product | Allow unverified? |" in edited.data
    assert edited.data.index(b"l4:index:start") < edited.data.index(b"## Q-001")
    assert edited.get("Q-001").answer_text == parsed.get("Q-001").answer_text
    with pytest.raises(SpecError, match="Q-077"):
        parsed.set_status("Q-077", QuestionStatus.OPEN)
    with pytest.raises(SpecError, match="Q-077"):
        parsed.set_suggestion("Q-077", "x", redactor=REDACTOR)
    no_status = QuestionsFile.parse("## Q-001: t\n\n- **Blocking tasks:** 1.1\n")
    with pytest.raises(SpecError, match="Status"):
        no_status.set_status("Q-001", QuestionStatus.DISMISSED)


def test_a_suggestion_is_added_to_a_section_that_has_no_answer_block():
    head = (
        f"{INDEX_START}\n| ID | Status | Blocking | Kind | Question |\n|----|--------|----------|------|----------|\n"
    )
    rows = "| Q-001 | open | 1.1 |  | t |\n| Q-002 | open |  |  | u |\n"
    before = (
        head
        + rows
        + f"{INDEX_END}\n\n## Q-001: t\n\n- **Status:** open\n- **Blocking tasks:** 1.1\n\n---\n\n## Q-002: u\n"
    )
    out = QuestionsFile.parse(before).set_suggestion("Q-001", "maybe", redactor=REDACTOR)
    assert out.data.decode() == before.replace("1.1\n\n---", "1.1\n\n### Clarifier suggestion\nmaybe\n\n---")


def test_a_bom_stays_first_when_the_index_is_inserted():
    bom = b"\xef\xbb\xbf"
    titled = QuestionsFile.parse(bom + b"# Questions\n\n## Q-001: t\n\n- **Status:** open\n")
    out = titled.set_status("Q-001", QuestionStatus.DISMISSED)
    assert out.data.startswith(bom + b"# Questions\n" + b"\n" + INDEX_START.encode())
    assert out.get("Q-001").status is QuestionStatus.DISMISSED


def test_an_edit_updates_only_its_own_row_so_a_deleted_section_keeps_its_id_reserved(tmp_path: Path):
    ask(tmp_path, question(), question(title="second"))
    path = tmp_path / "questions.md"
    text = path.read_text(encoding="utf-8")
    start = text.index("---\n\n## Q-002")
    path.write_text(text[:start], encoding="utf-8")  # a human deletes Q-002's section; its index row stays
    edited = QuestionsFile.load(path).set_status("Q-001", QuestionStatus.DISMISSED)
    edited.save(path)
    after = path.read_text(encoding="utf-8")
    assert "| Q-001 | dismissed |" in after and "| Q-002 | open |" in after
    assert ask(tmp_path, question(title="third")) == ["Q-003"]  # not Q-002 again


def test_a_row_missing_from_an_existing_index_is_added_before_the_end_marker():
    text = (
        f"{INDEX_START}\n| ID | Status | Blocking | Kind | Question |\n|--|--|--|--|--|\n{INDEX_END}\n\n"
        "## Q-001: t\n\n- **Status:** open\n- **Blocking tasks:** 1.1\n- **Kind:** technical\n"
    )
    out = QuestionsFile.parse(text).set_status("Q-001", QuestionStatus.ANSWERED)
    assert f"| Q-001 | answered | 1.1 | technical | t |\n{INDEX_END}" in out.data.decode()


ESCAPING_SUGGESTION = "\n".join(
    [
        "## Heading",
        "---",
        "| a | b |",
        "- **Status:** answered",
        "```python",
        "\\## already escaped looking",
        "\\\\two",
        "<!-- hidden -->",
        "&lt;!-- literal entity",
        "&amp;lt;!-- twice",
        "plain line",
    ]
)


def test_effective_answer_of_a_suggestion_round_trips_exactly(tmp_path: Path):
    ask(tmp_path, question(kind=QuestionKind.TECHNICAL))
    parsed = QuestionsFile.parse((tmp_path / "questions.md").read_bytes())
    edited = parsed.set_suggestion("Q-001", ESCAPING_SUGGESTION, redactor=REDACTOR).set_status(
        "Q-001", QuestionStatus.ANSWERED_BY_CLARIFIER
    )
    again = QuestionsFile.parse(edited.data)  # what the next run reads back
    q = again.get("Q-001")
    assert q.suggestion_text != ESCAPING_SUGGESTION  # the file holds the neutralised form
    assert effective_answer(q) == ESCAPING_SUGGESTION
    assert answer_sha256(q) == hashlib.sha256(ESCAPING_SUGGESTION.encode()).hexdigest()
    assert [x.id for x in again.questions] == ["Q-001"]  # none of the lines became structure
    assert effective_answer(again.set_status("Q-001", QuestionStatus.ACCEPTED).get("Q-001")) == ESCAPING_SUGGESTION


def test_context_and_options_are_read_as_written(tmp_path: Path):
    ask(tmp_path, question(context="Line one.\n## not structure"))
    parsed = QuestionsFile.parse((tmp_path / "questions.md").read_bytes()).get("Q-001")
    assert parsed.context_text == "Line one.\n\\## not structure"  # as written: the neutralising backslash is there
    assert parsed.options_text == "1. Block login until verified.\n2. Allow login, restrict features."
    bare = QuestionsFile.parse(b"## Q-001: t\n\n- **Status:** open\n- **Blocking tasks:** 1.1\n").get("Q-001")
    assert (bare.context_text, bare.options_text) == ("", "")


# --- set_answer (unfreeze-and-answer 4.1, L4-QMD-008) ------------------------------------------------------------

HEAD = (
    f"# Questions {EM} t\n\n{INDEX_START}\n| ID | Status | Blocking | Kind | Question |\n"
    "|----|--------|----------|------|----------|\n"
)
TWO = (
    "# Questions " + EM + " t\n\n"
    f"{INDEX_START}\n| ID | Status | Blocking | Kind | Question |\n|----|--------|----------|------|----------|\n"
    "| Q-001 | open | 1.1 | technical | t |\n| Q-002 | open | 1.2 | product | u |\n"
    f"{INDEX_END}\n\n---\n\n"
    "## Q-001: t\n\n- **Status:** open\n- **Blocking tasks:** 1.1\n- **Kind:** technical\n\n"
    "### Context\nWhich hash?\n\n### Answer\n<!-- write below this line -->\n\n---\n\n"
    "## Q-002: u\n\n- **Status:** open\n- **Blocking tasks:** 1.2\n- **Kind:** product\n\n"
    "### Answer\n<!-- write below this line -->\nold draft\n"
)


@pytest.mark.parametrize("eol", ["\n", "\r\n"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_set_answer_replaces_only_the_answer_body_and_keeps_line_endings_and_bom(eol: str, bom: bytes):
    before = bom + TWO.replace("\n", eol).encode()
    parsed = QuestionsFile.parse(before)
    out = parsed.set_answer("Q-002", "Use argon2id.\nCost 3.")
    assert out.get("Q-002").answer_text.replace("\r\n", "\n") == "Use argon2id.\nCost 3."
    assert out.get("Q-001").answer_text == ""
    assert out.data.startswith(bom)
    assert out.data.count(b"\r\n") == (out.data.count(b"\n") if eol == "\r\n" else 0)
    old = parsed.get("Q-002").answer
    cut = old.body
    assert out.data[: cut.start] == before[: cut.start]  # everything before the body, byte for byte
    assert out.data[cut.start :].decode().replace("\r\n", "\n") == (
        "<!-- write below this line -->\nUse argon2id.\nCost 3.\n"
    )
    assert out.data[cut.start :].count(b"\r\n") == (3 if eol == "\r\n" else 0)
    assert b"old draft" not in out.data


def test_set_answer_keeps_what_follows_the_block_and_the_other_questions():
    out = QuestionsFile.parse(TWO).set_answer("Q-001", "Use argon2id.")
    assert out.data.decode() == TWO.replace(
        "### Answer\n<!-- write below this line -->\n\n---",
        "### Answer\n<!-- write below this line -->\nUse argon2id.\n\n---",
        1,
    )
    assert out.get("Q-001").answer_text == "Use argon2id."


def test_set_answer_keeps_a_blank_line_before_a_later_subsection():
    text = (
        HEAD
        + "| Q-001 | open | 1.1 |  | t |\n"
        + INDEX_END
        + "\n\n## Q-001: t\n\n- **Status:** open\n- **Blocking tasks:** 1.1\n\n"
        "### Answer\n<!-- write below this line -->\n\n### Clarifier suggestion\nmaybe\n"
    )
    out = QuestionsFile.parse(text).set_answer("Q-001", "yes")
    assert out.data.decode() == text.replace("line -->\n\n###", "line -->\nyes\n\n###")
    assert out.get("Q-001").suggestion_text == "maybe" and out.get("Q-001").answer_text == "yes"


def test_set_answer_adds_the_block_at_the_end_of_a_section_that_has_none():
    before = TWO.replace("### Answer\n<!-- write below this line -->\n\n---", "---", 1)
    out = QuestionsFile.parse(before).set_answer("Q-001", "Use argon2id.")
    assert out.get("Q-001").answer_text == "Use argon2id."
    assert out.get("Q-002").answer_text == "old draft"
    assert out.data.decode() == before.replace(
        "Which hash?\n\n---", "Which hash?\n\n### Answer\nUse argon2id.\n\n---", 1
    )


def test_set_answer_adds_the_block_to_a_last_section_without_a_final_line_end():
    text = (
        HEAD
        + "| Q-001 | open | 1.1 |  | t |\n"
        + INDEX_END
        + "\n\n## Q-001: t\n\n- **Status:** open\n- **Blocking tasks:** 1.1"
    )
    out = QuestionsFile.parse(text).set_answer("Q-001", "yes")
    assert out.data.decode() == text + "\n\n### Answer\nyes\n"
    assert out.get("Q-001").answer_text == "yes"


def test_set_answer_without_the_comment_line_writes_the_text_alone_and_an_unknown_id_is_refused():
    text = (
        HEAD
        + "| Q-001 | open | 1.1 |  | t |\n"
        + INDEX_END
        + "\n\n## Q-001: t\n\n- **Status:** open\n- **Blocking tasks:** 1.1\n\n### Answer\nold\n"
    )
    out = QuestionsFile.parse(text).set_answer("Q-001", "new")
    assert out.data.decode() == text.replace("old", "new")
    with pytest.raises(SpecError, match="Q-077"):
        QuestionsFile.parse(text).set_answer("Q-077", "x")


def test_set_answer_then_set_status_changes_only_status_answer_and_row():
    parsed = QuestionsFile.parse(TWO)
    out = parsed.set_answer("Q-002", "Allow it.").set_status("Q-002", QuestionStatus.ANSWERED)
    q2 = parsed.get("Q-002")
    spans = [
        (q2.status_value.start, q2.status_value.end),
        (q2.answer.body.start, q2.answer.body.end),
        (parsed.index.start, parsed.index.end),
    ]
    assert outside(TWO.encode(), out.data, spans)
    assert b"| Q-002 | answered | 1.2 | product | u |" in out.data
    assert effective_answer(out.get("Q-002")) == "Allow it."


# --- unfreeze-option-form 1.1 (L4-IMP-004): option 1 is an edit with or without backticks --------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Edit `src/x.test.ts`: change", "Edit `src/x.test.ts`: change"),
        ("Edit src/x.test.ts: change", "Edit `src/x.test.ts`: change"),
        ("Edit ./x.py: y", "Edit `./x.py`: y"),
        ("Edit conftest.py: add the line", "Edit `conftest.py`: add the line"),
        ("  Edit src/x.py: change the key  ", "Edit `src/x.py`: change the key"),
        ("  Edit `src/x.py`: change the key  ", "Edit `src/x.py`: change the key"),
        ("Edit src/x.py: change `a`: to `b`", "Edit `src/x.py`: change `a`: to `b`"),
        ("Edit the test: assert 2", None),  # a bare token without a slash or a dot is no file
        ("Edit `the test`: assert 2", None),  # a backticked path is one token
        ("Edit src/x.py:12: change", None),  # a colon in the bare path
        ("Edit src/x.py:", None),
        ("Edit src/x.py: ", None),  # nothing after the colon and the space
        ("Edit `src/x.py`: ", None),
        ("Edit `src/x.py`:change", None),  # the colon is followed by a space
        ("Leave it", None),
        ("", None),
        ("edit src/x.py: change", None),
    ],
)
def test_edit_option_reads_both_forms_and_returns_the_backticked_one(text: str, expected: str | None):
    assert edit_option(text) == expected


OPEN_TECHNICAL = (
    "# Questions\n\n"
    f"{INDEX_START}\n| ID | Status | Blocking | Kind | Question |\n|----|--------|----------|------|----------|\n"
    "| Q-001 | open | 1.1 | technical | t |\n"
    f"{INDEX_END}\n\n"
    "---\n\n## Q-001: t\n\n- **Status:** open\n- **Blocking tasks:** 1.1\n- **Kind:** technical\n\n"
    "### Context\nThe frozen test is wrong.\n\n"
    "### Options\n1. Edit src/app.test.ts: seed the issued secret\n2. Edit `src/other.test.ts`: other\n\n"
    "### Answer\n<!-- write below this line -->\n"
)


def test_option_suggestion_is_the_backticked_option_one_of_an_open_technical_question_without_a_block():
    q = QuestionsFile.parse(OPEN_TECHNICAL).get("Q-001")
    assert option_suggestion(q) == "Edit `src/app.test.ts`: seed the issued secret"
    assert accept_text(q) == "Edit `src/app.test.ts`: seed the issued secret"


def test_option_suggestion_takes_the_backticked_option_as_it_is():
    text = OPEN_TECHNICAL.replace("1. Edit src/app.test.ts:", "1. Edit `src/app.test.ts`:")
    assert option_suggestion(QuestionsFile.parse(text).get("Q-001")) == "Edit `src/app.test.ts`: seed the issued secret"


@pytest.mark.parametrize("written", ["Take option 2", "(empty)"])
def test_a_written_suggestion_block_is_never_replaced_by_option_one(written: str):
    parsed = QuestionsFile.parse(OPEN_TECHNICAL).set_suggestion("Q-001", written, redactor=REDACTOR)
    q = parsed.get("Q-001")
    assert option_suggestion(q) is None
    assert accept_text(q) == written


def test_option_suggestion_is_none_for_a_product_an_answered_and_a_non_edit_question():
    product = OPEN_TECHNICAL.replace("**Kind:** technical", "**Kind:** product")
    assert option_suggestion(QuestionsFile.parse(product).get("Q-001")) is None
    answered = OPEN_TECHNICAL.replace("**Status:** open", "**Status:** answered")
    assert option_suggestion(QuestionsFile.parse(answered).get("Q-001")) is None
    no_edit = OPEN_TECHNICAL.replace("1. Edit src/app.test.ts: seed", "1. Keep the test: seed")
    q = QuestionsFile.parse(no_edit).get("Q-001")
    assert option_suggestion(q) is None and accept_text(q) == ""
    bare = OPEN_TECHNICAL[: OPEN_TECHNICAL.index("### Options")] + OPEN_TECHNICAL[OPEN_TECHNICAL.index("### Answer") :]
    assert option_suggestion(QuestionsFile.parse(bare).get("Q-001")) is None  # no options at all


def test_option_suggestion_reads_option_one_only_never_a_later_option():
    later = OPEN_TECHNICAL.replace("1. Edit src/app.test.ts: seed the issued secret", "1. Leave it")
    assert option_suggestion(QuestionsFile.parse(later).get("Q-001")) is None


def test_option_suggestion_of_a_kind_that_is_unknown_is_none():
    unknown = OPEN_TECHNICAL.replace("**Kind:** technical", "**Kind:** odd")
    assert option_suggestion(QuestionsFile.parse(unknown).get("Q-001")) is None


# --- unfreeze-option-form 2.1 (L4-QMD-008): the block is derived by the edit, never by the load ----------------------

SECOND = (
    "\n---\n\n## Q-002: u\n\n- **Status:** open\n- **Blocking tasks:** 1.2\n- **Kind:** technical\n\n"
    "### Options\n1. Edit src/b.test.ts: other\n\n### Answer\n<!-- write below this line -->\n"
)


def test_with_option_suggestion_adds_the_block_before_the_answer_and_changes_nothing_else():
    before = OPEN_TECHNICAL + SECOND
    parsed = QuestionsFile.parse(before)
    out = parsed.with_option_suggestion("Q-001", redactor=REDACTOR)
    block = "### Clarifier suggestion\nEdit `src/app.test.ts`: seed the issued secret\n\n"
    assert out.data.decode() == before.replace("### Answer\n", block + "### Answer\n", 1)
    q1 = out.get("Q-001")
    assert q1.suggestion_text == "Edit `src/app.test.ts`: seed the issued secret" and q1.status is QuestionStatus.OPEN
    assert out.get("Q-002").suggestion is None  # the other question is not derived
    assert QuestionsFile.parse(before).get("Q-001").suggestion is None  # the input is not changed
    assert out.data.index(b"### Clarifier suggestion") < out.data.index(b"### Answer")


def test_with_option_suggestion_keeps_crlf_and_the_bom():
    before = ("\ufeff" + (OPEN_TECHNICAL + SECOND)).replace("\n", "\r\n").encode("utf-8")
    out = QuestionsFile.parse(before).with_option_suggestion("Q-001", redactor=REDACTOR)
    assert out.data.startswith(b"\xef\xbb\xbf") and out.data.count(b"\n") == out.data.count(b"\r\n")
    block = b"### Clarifier suggestion\r\nEdit `src/app.test.ts`: seed the issued secret\r\n\r\n"
    assert out.data == before.replace(b"### Answer\r\n", block + b"### Answer\r\n", 1)


def test_with_option_suggestion_is_the_file_itself_when_the_question_takes_no_option():
    for text in (
        OPEN_TECHNICAL.replace("**Kind:** technical", "**Kind:** product"),
        OPEN_TECHNICAL.replace("1. Edit src/app.test.ts: seed", "1. Keep it: seed"),
        OPEN_TECHNICAL.replace("**Status:** open", "**Status:** answered"),
    ):
        parsed = QuestionsFile.parse(text)
        assert parsed.with_option_suggestion("Q-001", redactor=REDACTOR) is parsed
    written = QuestionsFile.parse(OPEN_TECHNICAL).set_suggestion("Q-001", "(empty)", redactor=REDACTOR)
    assert written.with_option_suggestion("Q-001", redactor=REDACTOR) is written
    with pytest.raises(SpecError, match="Q-077"):
        written.with_option_suggestion("Q-077", redactor=REDACTOR)


def test_with_option_suggestion_redacts_like_every_text_the_harness_writes():
    secret = "plainvalue-8f3k2m9x1q7z"
    text = OPEN_TECHNICAL.replace("seed the issued secret", f"seed {secret}")
    out = QuestionsFile.parse(text).with_option_suggestion("Q-001", redactor=Redactor({"token": secret}))
    assert secret not in out.data.decode().split("### Clarifier suggestion")[1].split("### Answer")[0]


def test_the_load_never_derives_the_block(tmp_path: Path):
    (tmp_path / "questions.md").write_text(OPEN_TECHNICAL, encoding="utf-8")
    loaded = QuestionsFile.load(tmp_path / "questions.md")
    assert loaded.get("Q-001").suggestion is None and loaded.get("Q-001").suggestion_text == ""
    assert loaded.data.decode() == OPEN_TECHNICAL
