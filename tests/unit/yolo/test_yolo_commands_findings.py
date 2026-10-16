# ruff: noqa: F811
"""`l4 yolo findings` and the one-line views (L4-YOLO-021; SCN-YOLO-43, -44, -45, -46): from the ledger, no model, no
write."""

import json

from .yolo_cmd_world import A, B, plan_doc, world  # noqa: F401
from .yolo_review_events import FAILURES, INTERFACES, OUTCOME, TESTABILITY, entry, review, two_rounds


def seeded(world, units, **kwargs):
    world.push_plan(**kwargs)
    world.seed("p1", review(world, "2026-10-14T10:00:00Z", units))
    return world.store().read().head


def test_each_major_finding_comes_with_how_to_resolve_it(world, capsys):
    """SCN-YOLO-43."""
    head = seeded(world, {A: entry(world, A, "NEEDS_REVISION", [TESTABILITY, OUTCOME], "ma1")})
    assert world.l4("findings", "p1") == 0
    out = capsys.readouterr().out
    assert f"{A}: NEEDS_REVISION" in out
    assert "[major/testability] no scenario gives an input and an output" in out
    assert (
        "Resolve: Give the scenario concrete inputs and outputs in openspec/changes/add-greeting/specs/*/spec.md" in out
    )
    assert "1 minor finding (--all shows it)" in out
    assert "the outcome could be clearer" not in out
    assert f"{B}:" not in out  # READY subjects are not listed
    assert world.store().read().head == head  # nothing is written


def test_the_change_since_the_previous_judgement_is_shown(world, capsys):
    """SCN-YOLO-44."""
    world.push_plan()
    world.seed(
        "p1",
        review(world, "2026-10-14T10:00:00Z", {A: entry(world, A, "NEEDS_REVISION", [TESTABILITY, FAILURES], "m1")}),
    )
    world.seed(
        "p1",
        review(world, "2026-10-14T11:00:00Z", {A: entry(world, A, "NEEDS_REVISION", [TESTABILITY, INTERFACES], "m2")}),
    )
    assert world.l4("findings", "p1", A) == 0
    out = capsys.readouterr().out
    assert "since the previous judgement: 1 new, 1 repeated, 1 gone" in out
    assert "persistent: testability ×2" in out


def test_status_shows_the_most_severe_finding_and_names_the_findings_command(world, capsys):
    """SCN-YOLO-45: the judge's order is minor X then major Y."""
    seeded(world, {A: entry(world, A, "NEEDS_REVISION", [OUTCOME, TESTABILITY], "ma1")})
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert f"{A}: NEEDS_REVISION: testability: no scenario gives an input and an output" in out
    assert "outcome could be clearer" not in out
    assert "l4 yolo findings p1" in out
    assert "l4 yolo review p1 --worktree" in out


def test_a_missing_dependency_names_the_plan_entry_to_add(world, capsys):
    """SCN-YOLO-46: B does not depend on A in the plan."""
    missing = {"criterion": "missing_dependency", "severity": "major", "text": f"it calls a helper that {A} defines"}
    seeded(world, {B: entry(world, B, "NEEDS_REVISION", [missing], "mb1")}, doc=plan_doc({A: [], B: []}))
    assert world.l4("findings", "p1") == 0
    out = capsys.readouterr().out
    assert f'Resolve: add "{A}" to depends_on of {B} in .l4/plans/p1.json (batch b1)' in out


def test_a_plan_with_no_review_says_so_and_exits_0(world, capsys):
    world.push_plan()
    assert world.l4("findings", "p1") == 0
    assert "p1: no review yet (l4 yolo review p1, or --worktree before the push)" in capsys.readouterr().out


def test_an_unknown_plan_or_subject_exits_2(world, capsys):
    seeded(world, {A: entry(world, A, "NEEDS_REVISION", [TESTABILITY], "ma1")})
    assert world.l4("findings", "nope") == 2
    assert "no plan" in capsys.readouterr().err
    assert world.l4("findings", "p1", "openspec:zzz") == 2
    assert "openspec:zzz" in capsys.readouterr().err


def test_a_batch_is_named_with_its_prefix(world, capsys):
    batch = {"verdict": "NEEDS_REVISION", "digest": None, "material": "mbatch", "findings": [FAILURES]}
    world.push_plan()
    world.seed("p1", review(world, "2026-10-14T10:00:00Z", {}, {"b1": batch}))
    assert world.l4("findings", "p1", "batch:b1") == 0
    assert "batch:b1: NEEDS_REVISION" in capsys.readouterr().out


def test_all_lists_the_ready_subjects_and_the_minor_findings(world, capsys):
    seeded(world, {A: entry(world, A, "NEEDS_REVISION", [TESTABILITY, OUTCOME], "ma1")})
    assert world.l4("findings", "p1", "--all") == 0
    out = capsys.readouterr().out
    assert f"{B}: READY" in out and "the outcome could be clearer" in out


def test_json_has_the_schema_and_the_findings(world, capsys):
    seeded(world, {A: entry(world, A, "NEEDS_REVISION", [TESTABILITY], "ma1")})
    assert world.l4("findings", "p1", "--json") == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "l4/yolo-findings@1" and doc["plan"] == "p1"
    assert [s["subject"] for s in doc["subjects"]] == [A]
    assert doc["subjects"][0]["findings"][0]["id"].startswith("F-")


def test_json_of_a_plan_with_no_review_has_no_subject(world, capsys):
    world.push_plan()
    assert world.l4("findings", "p1", "--json") == 0
    assert json.loads(capsys.readouterr().out)["subjects"] == []


def test_the_accept_line_appears_for_a_person_after_two_versions(world, capsys, monkeypatch):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)
    world.push_plan()
    two_rounds(world, [TESTABILITY])
    assert world.l4("findings", "p1") == 0
    assert f"accept: l4 yolo accept p1 {A} --reason TEXT" in capsys.readouterr().out


def test_an_agent_is_told_acceptance_is_a_persons_decision(world, capsys, monkeypatch):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: False)
    world.push_plan()
    two_rounds(world, [TESTABILITY])  # the rounds condition is met
    assert world.l4("findings", "p1", "--json") == 0
    subj = json.loads(capsys.readouterr().out)["subjects"][0]
    assert subj["accept_available"] is False
    assert subj["accept_refusal"]["why"] == "acceptance is a person's decision"
    assert "a person runs: l4 yolo accept p1" in subj["accept_refusal"]["fix"]
    assert world.l4("findings", "p1") == 0
    assert "accept: not available: acceptance is a person's decision (a person runs:" in capsys.readouterr().out


def test_one_round_is_told_how_many_versions_are_needed(world, capsys, monkeypatch):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)
    seeded(world, {A: entry(world, A, "NEEDS_REVISION", [TESTABILITY], "ma1")})
    assert world.l4("findings", "p1", "--json") == 0
    subj = json.loads(capsys.readouterr().out)["subjects"][0]
    assert subj["accept_available"] is False
    assert "was judged not READY on 1 version; 2 are needed" in subj["accept_refusal"]["why"]


def test_an_available_acceptance_has_no_refusal_and_a_ready_subject_has_none(world, capsys, monkeypatch):
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: True)
    world.push_plan()
    two_rounds(world, [TESTABILITY])
    assert world.l4("findings", "p1", "--json", "--all") == 0
    by = {s["subject"]: s for s in json.loads(capsys.readouterr().out)["subjects"]}
    assert by[A]["accept_available"] is True and by[A]["accept_refusal"] is None
    assert B not in by or by[B]["accept_refusal"] is None
