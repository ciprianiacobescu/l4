# ruff: noqa: F811
"""`l4 yolo status` shows the newest incomplete review while the review is not current (L4-YOLO-099, SCN-YOLO-278)."""

import json

from l4.yolo.digest import plan_digest
from l4.yolo.model import PlanEvent
from l4.yolo.readiness import PROMPT_VERSION

from .yolo_cmd_world import A, B, ev, forge, plan_doc, world  # noqa: F401

FAILURES = [
    {"profile": "j1", "subject": "", "kind": "unusable", "detail": "hello refused", "material": None},
    {"profile": "j2", "subject": "batch:b1", "kind": "error", "detail": "boom", "material": "m9"},
]


def incomplete(world, at="2026-10-14T11:00:00Z", reason="no_judge", version=PROMPT_VERSION, **over):
    data = {
        "plan_digest": plan_digest(world.plan_text),
        "prompt_version": version,
        "source": "ci",
        "reason": reason,
        "answered": {A: {"verdict": "READY", "material": "ma"}, B: {"verdict": "READY", "material": "mb"}},
        "left": ["batch:b1"],
        "failures": FAILURES,
        "cost_usd": 0.3,
    }
    return PlanEvent("plan.review_incomplete", at, {**data, **over})


def seeded(world):
    world.push_plan()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]))


def test_scn_yolo_278_status_shows_the_incomplete_review_its_failures_and_a_fix(world, capsys):
    seeded(world)
    world.seed("p1", incomplete(world))
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "review: none" in out
    assert "incomplete " in out and " ago (ci, no_judge): 2 answered and kept, 1 left" in out
    assert "      j1: selection: unusable: hello refused" in out and "      j2: batch:b1: error: boom" in out
    assert "      fix: fix the judges named, `l4 doctor --live`, or set roles.plan_judges" in out
    assert world.l4("status", "p1", "--json") == 0
    review = json.loads(capsys.readouterr().out)["plans"][0]["review"]
    shown = review["incomplete"]
    assert (shown["source"], shown["reason"], shown["answered"], shown["left"]) == ("ci", "no_judge", 2, 1)
    assert shown["cost_usd"] == 0.3 and shown["at"] == "2026-10-14T11:00:00Z"
    assert [(f["profile"], f["subject"], f["kind"]) for f in shown["failures"]] == [
        ("j1", "", "unusable"),
        ("j2", "batch:b1", "error"),
    ]


def test_the_fix_line_follows_the_reason(world, capsys):
    seeded(world)
    world.seed("p1", incomplete(world, reason="timeout"))
    world.l4("status", "p1")
    assert "fix: raise yolo.review.timeout or put another judge first in roles.plan_judges" in capsys.readouterr().out
    world.seed("p1", incomplete(world, at="2026-10-14T12:00:00Z", reason="job_time", failures=[]))
    world.l4("status", "p1")
    assert "fix: give the CI job more time or lower yolo.review.timeout" in capsys.readouterr().out


def test_a_later_review_and_another_prompt_version_show_no_incomplete(world, capsys):
    seeded(world)
    world.seed("p1", incomplete(world, version=PROMPT_VERSION - 1))
    world.l4("status", "p1")
    assert "incomplete" not in capsys.readouterr().out
    world.seed("p1", incomplete(world, at="2026-10-14T12:00:00Z"), world.reviewed())
    world.l4("status", "p1")
    out = capsys.readouterr().out
    assert "incomplete" not in out and "review: current" in out
    world.l4("status", "p1", "--json")
    assert "incomplete" not in json.loads(capsys.readouterr().out)["plans"][0]["review"]


def test_status_names_a_batch_that_was_reviewed_in_parts(world, capsys):
    seeded(world)
    note = {
        "criterion": "parts",
        "severity": "minor",
        "text": "this batch was reviewed in parts: no judge saw two units",
    }
    event = world.reviewed()
    event.data["batches"]["b1"]["findings"] = [note]
    world.seed("p1", event)
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "review: current" in out
    assert "    reviewed in parts: b1 (no judge saw two units' full text together)" in out
    world.l4("status", "p1", "--json")
    assert json.loads(capsys.readouterr().out)["plans"][0]["review"]["in_parts"] == ["b1"]


def test_status_says_nothing_of_parts_for_a_batch_asked_whole(world, capsys):
    seeded(world)
    world.seed("p1", world.reviewed())
    world.l4("status", "p1", "--json")
    assert "in_parts" not in json.loads(capsys.readouterr().out)["plans"][0]["review"]
