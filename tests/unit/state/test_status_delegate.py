"""`l4 status` names the delegate's answers and escalations (delegate-answers 14.1; L4-DLG-011; SCN-DLG-32): the REASON
of the table, the `Delegate:` lines of `--unit` and the `--json` fields; a repository without the delegate prints and
carries nothing more."""

import json
from pathlib import Path

from .test_status_branch import IMPLEMENTING, run_cli

WAITING = ("phase.changed", {"from": "implementing", "to": "awaiting_human", "trigger": "questions_blocking"})
QUESTIONS = (
    "# Questions\n\n---\n\n## Q-003: Which rate?\n\n- **Status:** answered\n- **Blocking tasks:** 1.1\n"
    "- **Kind:** technical\n\n### Context\nx\n\n### Answer\n<!-- write below this line -->\n21%\n\n---\n\n"
    "## Q-004: Which tier?\n\n- **Status:** open\n- **Blocking tasks:** 1.1\n- **Kind:** product\n\n"
    "### Context\nx\n\n### Answer\n<!-- write below this line -->\n"
)
REASON = "no document decides which tier"
DECIDED = [
    ("question.raised", {"id": "Q-003", "kind": "technical"}),
    ("question.raised", {"id": "Q-004", "kind": "product"}),
    ("delegate.result", {
        "question": "Q-003", "id": "Q-003", "status": "answered", "kind": "technical", "decision": "answer",
        "model": "claude-opus-5-5", "cli": "claude-code", "profile": "delegate-opus", "cost_usd": 0.42, "called": True,
    }),
    ("question.answered", {"id": "Q-003", "by": "delegate"}),
    ("delegate.result", {
        "question": "Q-004", "id": "Q-004", "status": "escalated", "kind": "product", "model": "gpt-6.1-sol",
        "cli": "codex", "reason": REASON, "cost_usd": 0.1, "called": True,
    }),
]  # fmt: skip


def push(unit_repo, trailers, *events, questions=QUESTIONS):
    def work(repo: Path) -> None:
        unit_repo.write_ledger(repo, *IMPLEMENTING[:3], *events, WAITING)
        (repo / "openspec/changes/add-x/questions.md").write_text(questions)

    unit_repo.push_unit_branch(work, trailers)


def test_the_table_reason_of_an_escalation(unit_repo, trailers, capsys):
    push(unit_repo, trailers, *DECIDED)
    code, out, _ = run_cli(unit_repo, capsys, "status")
    assert code == 0
    assert "Q-004 needs a person (the delegate escalated)" in out


def test_the_delegate_lines(unit_repo, trailers, capsys):
    push(unit_repo, trailers, *DECIDED)
    _, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x")
    assert "Delegate: Q-003 answered by the delegate (claude-opus-5-5 via claude-code, $0.42)" in out
    assert f"Delegate: Q-004 escalated by the delegate: {REASON}" in out
    assert out.index("Delegate: Q-004") < out.index("Next:")  # the step stays last


def test_a_delegates_unfreeze_is_a_status_line(unit_repo, trailers, capsys):  # SCN-DLG-55, review 2 N2
    unfrozen = ("task.unfrozen", {
        "task": "1.1", "paths": ["tests/test_a.py"], "reason": "delegate_answer", "by": "delegate",
        "question": "Q-003", "model": "claude-opus-5-5", "profile": "delegate-opus", "red_sha": "a" * 40,
    })  # fmt: skip
    push(unit_repo, trailers, *DECIDED, unfrozen)
    _, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x")
    assert "Delegate: task 1.1 unfrozen tests/test_a.py by Q-003 (delegate_override, claude-opus-5-5)" in out
    assert out.index("Delegate: task 1.1") < out.index("Next:")


def test_a_deferred_question_shows_the_time(unit_repo, trailers, capsys):
    deferred = ("delegate.result", {
        "question": "Q-004", "id": "Q-004", "status": "deferred", "reason": "all_profiles_cooling",
        "retry_after": "2026-10-19T10:00:00Z", "called": False,
    })  # fmt: skip
    push(unit_repo, trailers, DECIDED[0], DECIDED[1], deferred)
    _, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x")
    assert "Delegate: Q-004 deferred by the delegate until 2026-10-19T10:00:00Z" in out
    assert "needs a person" not in out  # a deferral is not an escalation


def test_the_json_fields(unit_repo, trailers, capsys):  # SCN-DLG-32
    push(unit_repo, trailers, *DECIDED)
    _, out, _ = run_cli(unit_repo, capsys, "status", "--json")
    (unit,) = json.loads(out)["units"]
    assert unit["reason"] == "Q-004 needs a person (the delegate escalated)"
    answered, escalated = unit["delegate"]
    assert (answered["question"], answered["status"], answered["model"], answered["cli"], answered["cost_usd"]) == (
        "Q-003", "answered", "claude-opus-5-5", "claude-code", 0.42,
    )  # fmt: skip
    assert (escalated["question"], escalated["status"], escalated["reason"]) == ("Q-004", "escalated", REASON)
    assert escalated["text"] == f"Q-004 escalated by the delegate: {REASON}"


def test_a_unit_the_delegate_never_saw_shows_nothing_more(unit_repo, trailers, capsys):
    push(unit_repo, trailers, questions=QUESTIONS.replace("answered", "open", 1))
    _, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x")
    assert "Delegate:" not in out and "needs a person" not in out
    _, raw, _ = run_cli(unit_repo, capsys, "status", "--json")
    assert "delegate" not in json.loads(raw)["units"][0]


def test_the_line_of_a_kiro_answer_names_its_credits(unit_repo, trailers, capsys):  # SCN-DLG-70
    kiro = ("delegate.result", {
        "question": "Q-003", "id": "Q-003", "status": "answered", "kind": "technical", "decision": "answer",
        "model": "claude-sonnet-4.5", "cli": "kiro-cli", "profile": "delegate-kiro", "cost_usd": None,
        "credits": 1.84, "counted_usd": 3.0, "called": True,
    })  # fmt: skip
    push(unit_repo, trailers, DECIDED[0], DECIDED[1], kiro, DECIDED[3], DECIDED[4])
    _, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x")
    assert (
        "Delegate: Q-003 answered by the delegate (claude-sonnet-4.5 via kiro-cli, 1.84 credits; counted at $3.00)"
        in out
    )
    _, js, _ = run_cli(unit_repo, capsys, "status", "--json")
    row = next(r for r in json.loads(js)["units"][0]["delegate"] if r["question"] == "Q-003")
    assert row["credits"] == 1.84 and row["counted_usd"] == 3.0
