"""`l4 yolo go` (L4-YOLO-080, -087, -088): the pure core: stop codes, steps, the JSON document and the command line."""

import json

from l4.exitcodes import SEVERITY_ORDER, ExitCode
from l4.yolo import go
from l4.yolo.go import Flags, GoResult, GoStop, Step


def flags(**over) -> Flags:
    base = {
        "reason": "ship it", "accept_findings": False, "force": False, "yes": False, "as_json": False,
        "no_push": False, "local": False, "wait": "30m", "wait_s": 1800,
    }  # fmt: skip
    base.update(over)
    return Flags(**base)


def test_the_stop_codes_are_twenty_to_twenty_nine_and_not_exit_codes():
    assert {s.name: int(s) for s in GoStop} == {
        "ACTIVE": 0, "PREFLIGHT": 20, "PUSH": 21, "NOT_ADMITTED": 22, "PLAN_STATE": 23, "REVIEW_PENDING": 24,
        "REVIEW_FAILED": 25, "FINDINGS": 26, "PERSON": 27, "REFUSED": 28, "NOT_CONFIRMED": 29,
    }  # fmt: skip
    assert not [c for c in ExitCode if 20 <= int(c) <= 29]
    assert SEVERITY_ORDER == (1, 16, 2, 3, 14, 15, 13, 11, 12, 10, 0)
    assert set(SEVERITY_ORDER) == {int(c) for c in ExitCode}


def result(*statuses: str) -> GoResult:
    steps = [Step(name, status) for name, status in zip(go.STEPS, statuses, strict=False)]
    steps += [Step(name) for name in go.STEPS[len(steps) :]]
    return GoResult("p1", steps, "l4 yolo status p1", 0)


def test_step_reached_is_the_last_step_reached():
    assert go.STEPS == ("preflight", "push", "check", "review", "findings", "accept", "activate")
    assert result("ok", "ok", "ok", "ok", "stopped").step_reached == "findings"
    assert result("ok", "ok", "ok", "ok", "ok", "skipped", "done").step_reached == "activate"
    assert result("stopped").step_reached == "preflight"
    assert result().step_reached == ""
    for status in ("ok", "done", "skipped", "pending", "stopped", "person", "not_reached"):
        assert status in go.STATUSES


def test_as_json_has_the_keys_and_the_seven_steps_in_order():
    one = result("ok", "ok", "ok", "ok", "stopped")
    one.steps[4].detail = "openspec:b: NEEDS_REVISION"
    one.exit = int(GoStop.FINDINGS)
    doc = one.as_json()
    assert list(doc) == ["schema", "plan", "step_reached", "steps", "next_command", "exit"]
    assert doc["schema"] == "l4/yolo-go@1" and doc["plan"] == "p1" and doc["step_reached"] == "findings"
    assert [s["name"] for s in doc["steps"]] == list(go.STEPS)
    assert all(set(s) == {"name", "status", "detail"} for s in doc["steps"])
    assert doc["steps"][4] == {"name": "findings", "status": "stopped", "detail": "openspec:b: NEEDS_REVISION"}
    assert doc["steps"][6]["status"] == "not_reached"
    assert doc["next_command"] == "l4 yolo status p1" and doc["exit"] == 26 and type(doc["exit"]) is int
    assert json.loads(json.dumps(doc)) == doc


def test_command_line_quotes_the_reason_and_repeats_the_flags():
    assert go.command_line("p1", flags(reason="a b")) == "l4 yolo go p1 --reason 'a b'"
    assert go.command_line("p1", flags(reason="R")) == "l4 yolo go p1 --reason R"
    everything = flags(
        reason="a b", accept_findings=True, force=True, yes=True, as_json=True, local=True, no_push=True, wait="1m"
    )
    assert go.command_line("p1", everything) == (
        "l4 yolo go p1 --reason 'a b' --accept-findings --force --yes --json --local --no-push --wait 1m"
    )
    assert go.command_line("p1", everything, drop=("--local", "--json")) == (
        "l4 yolo go p1 --reason 'a b' --accept-findings --force --yes --no-push --wait 1m"
    )
    assert go.command_line("p1", flags(reason="R", wait="0")) == "l4 yolo go p1 --reason R --wait 0"
    assert go.command_line("p1", flags(reason="R"), add=("--yes", "--accept-findings")) == (
        "l4 yolo go p1 --reason R --accept-findings --yes"
    )
    assert go.command_line("p1", flags(reason="it's"), add=()) == "l4 yolo go p1 --reason 'it'\"'\"'s'"


def test_a_persons_command_has_no_yes_json_or_no_push():
    everything = flags(reason="a b", accept_findings=True, yes=True, as_json=True, local=True, no_push=True, wait="1m")
    line = go.command_line("p1", everything, person=True)
    assert line == "l4 yolo go p1 --reason 'a b' --accept-findings"
    for word in ("--yes", "--json", "--no-push", "--local", "--wait"):
        assert word not in line
    assert go.command_line("p1", flags(reason="R", force=True), person=True) == "l4 yolo go p1 --reason R --force"
    assert go.command_line("p1", flags(reason="R"), add=("--accept-findings",), person=True) == (
        "l4 yolo go p1 --reason R --accept-findings"
    )
    assert go.command_line("p1", flags(reason="R", accept_findings=True), drop=("--accept-findings",), person=True) == (
        "l4 yolo go p1 --reason R"
    )
