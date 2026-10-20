# ruff: noqa: F811
"""`l4 yolo go` output contract (L4-YOLO-087, L4-YOLO-088; SCN-YOLO-230, -231): one stop code and one `Next:` line
per stop, the JSON document alone on stdout, a refusal's `Fix:` line as the next command, the relay of a command's
output."""

import io
import json

import pytest

from l4.availability.errors import RoleUnavailable
from l4.exitcodes import ExitCode, L4Exit
from l4.yolo import go as yolo_go
from l4.yolo.digest import plan_digest

from .test_yolo_go_accept import both_not_ready
from .test_yolo_go_push import commit
from .yolo_actor import agent, person  # noqa: F401
from .yolo_cmd_world import A, B, ev, forge, plan_doc, world  # noqa: F401
from .yolo_review_events import TESTABILITY, two_rounds


def committed(world) -> None:
    world.push_plan()
    world.pull()


def reviewed(world) -> None:
    committed(world)
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())


def next_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("Next:")]


# --- one world per row of D9 --------------------------------------------------------------------------------------


def row_preflight(world, monkeypatch):
    committed(world)
    (world.app.repo / "openspec/changes/add-b/proposal.md").write_text("# B changed\n", encoding="utf-8")
    return ()


def row_push(world, monkeypatch):
    committed(world)
    commit(world, {"notes.md": "local\n"})
    return ("--no-push",)


def row_not_admitted(world, monkeypatch):
    world.push_plan(plan_doc({A: [B], B: [A]}))
    world.pull()
    return ()


def row_plan_state(world, monkeypatch):
    reviewed(world)
    world.seed(
        "p1", ev("plan.activated", plan_digest=plan_digest(world.plan_text), digests={}, limits={}, by="a", reason="r")
    )
    world.seed("p1", ev("plan.cancelled", by="a", reason="no"))
    return ()


def row_review_pending(world, monkeypatch):
    committed(world)
    monkeypatch.setattr("l4.yolo.go.start_run_result", lambda app, cfg: ("started", "CI started"))
    return ("--wait", "0")


def row_review_failed(world, monkeypatch):
    committed(world)

    def down(*args, **kwargs):
        raise RoleUnavailable("judges", "no profile is available")

    monkeypatch.setattr("l4.yolo.commands.review_plan_costed", down)
    return ("--local",)


def row_findings(world, monkeypatch):
    committed(world)
    two_rounds(world, [TESTABILITY], unit=B)
    return ()


def row_person(world, monkeypatch):
    reviewed(world)
    agent(world, monkeypatch)
    return ()


def row_refused(world, monkeypatch):
    reviewed(world)
    other = plan_doc({"openspec:elsewhere": []}, plan_id="p2")
    world.push({".l4/plans/p2.json": json.dumps(other)})
    world.seed("p2", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"))
    world.pull()
    agent(world, monkeypatch)
    return ()


def row_not_confirmed(world, monkeypatch):
    committed(world)
    both_not_ready(world)
    monkeypatch.setattr("l4.yolo.commands.click.prompt", lambda *a, **k: "yes")
    return ("--accept-findings",)


def row_active(world, monkeypatch):
    reviewed(world)
    world.seed(
        "p1", ev("plan.activated", plan_digest=plan_digest(world.plan_text), digests={}, limits={}, by="a", reason="r")
    )
    return ()


ROWS = [
    (20, row_preflight), (21, row_push), (22, row_not_admitted), (23, row_plan_state), (24, row_review_pending),
    (25, row_review_failed), (26, row_findings), (27, row_person), (28, row_refused), (29, row_not_confirmed),
    (0, row_active),
]  # fmt: skip


@pytest.mark.parametrize(("code", "setup"), ROWS, ids=[f"exit-{c}" for c, _ in ROWS])
def test_each_stop_has_its_own_code_and_one_next_line(code, setup, world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-230."""
    flags = setup(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "a b", *flags) == code
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert len(next_lines(out)) == 1 and lines[-1].startswith("Next:")
    for line in next_lines(out):
        if "yolo go" in line:
            assert "--reason 'a b'" in line
    assert code == 0 or code not in {int(c) for c in ExitCode} - {0}  # a stop code is no ExitCode member


# --- --json (SCN-YOLO-231) -------------------------------------------------------------------------------------------

KEYS = {"schema", "plan", "step_reached", "steps", "next_command", "exit"}


def test_the_json_document_is_the_only_thing_on_stdout(world, forge, person, capsys):
    """SCN-YOLO-231."""
    committed(world)
    two_rounds(world, [TESTABILITY], unit=B)
    assert world.l4("go", "p1", "--reason", "R", "--json") == 26
    first = capsys.readouterr()
    doc = json.loads(first.out)
    assert set(doc) == KEYS and doc["schema"] == "l4/yolo-go@1" and doc["step_reached"] == "findings"
    assert doc["exit"] == 26 and doc["next_command"] == "l4 yolo go p1 --reason R --accept-findings --json"
    status = {s["name"]: s["status"] for s in doc["steps"]}
    assert status["findings"] == "stopped" and status["accept"] == status["activate"] == "not_reached"
    assert [s["name"] for s in doc["steps"]] == list(yolo_go.STEPS)
    assert world.l4("go", "p1", "--reason", "R", "--json", "--accept-findings") == 0
    second = capsys.readouterr()
    doc = json.loads(second.out)
    assert set(doc) == KEYS and doc["exit"] == 0
    assert all(s["status"] != "not_reached" for s in doc["steps"])
    assert "[major/testability]" in second.err  # B's findings, before the prompt, on stderr
    assert len(person) == 2 and person[1] == "Type the plan id (p1) to activate p1"  # the accept, then the activation
    assert all(k.get("err") is True for k in person.kwargs)  # every prompt on stderr, stdout stays the document


# --- a refusal's Fix line --------------------------------------------------------------------------------------------


def test_a_refusals_fix_line_is_the_next_command(world, forge, person, monkeypatch, capsys):
    reviewed(world)

    def refuse(*args, **kwargs):
        raise L4Exit(ExitCode.USAGE_ERROR, "activate: nothing doing\nFix: l4 yolo review p1")

    monkeypatch.setattr("l4.yolo.commands.run_activate", refuse)
    assert world.l4("go", "p1", "--reason", "R") == 28
    assert next_lines(capsys.readouterr().out) == ["Next: l4 yolo review p1"]

    def refuse_plainly(*args, **kwargs):
        raise L4Exit(ExitCode.USAGE_ERROR, "activate: nothing doing")

    monkeypatch.setattr("l4.yolo.commands.run_activate", refuse_plainly)
    assert world.l4("go", "p1", "--reason", "R") == 28
    assert next_lines(capsys.readouterr().out) == ["Next: l4 yolo go p1 --reason R"]


def test_relayed_output_drops_next_lines_and_keeps_the_rest():
    lines: list[str] = []
    out = io.StringIO()
    with yolo_go._relay(lines, out):
        print("first")
        print("Next: l4 yolo status p1")
        print("last, no newline", end="")
    assert lines == ["first", "last, no newline"]
    assert out.getvalue() == "  first\n  last, no newline\n"
    quiet: list[str] = []
    with yolo_go._relay(quiet, None):
        print("kept")
    assert quiet == ["kept"]
