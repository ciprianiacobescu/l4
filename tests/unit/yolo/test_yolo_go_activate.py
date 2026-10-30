# ruff: noqa: F811
"""`l4 yolo go` (L4-YOLO-086): the activation, the part a person's run reaches."""

import json

from l4.yolo.digest import plan_digest
from l4.yolo.findings import findings_sha
from l4.yolo.readiness import PROMPT_VERSION

from .yolo_actor import agent, person  # noqa: F401
from .yolo_cmd_world import A, B, ev, forge, plan_doc, world  # noqa: F401
from .yolo_review_events import FAILURES, TESTABILITY, two_rounds


def reviewed(world):
    """Plan `p1` pushed, the checkout up to date, admitted and reviewed READY at the digests of the origin."""
    world.push_plan()
    world.pull()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())


def test_a_person_activates_a_reviewed_ready_plan(world, forge, person, capsys):
    """SCN-YOLO-200 (the part after the push)."""
    reviewed(world)
    forge.script_start_run("started")
    assert world.l4("go", "p1", "--reason", "ship it") == 0
    out = capsys.readouterr().out
    assert person == ["Type the plan id (p1) to activate p1"]  # B1: a person types the plan id before activation
    assert person.kwargs[0].get("err") is True
    activated = [e for e in world.events() if e.type == "plan.activated"]
    assert len(activated) == 1 and activated[0].data["reason"] == "ship it"
    lines = out.splitlines()
    heads = [line.split(":")[0] for line in lines if not line.startswith(" ") and not line.startswith("Next:")]
    assert heads == ["preflight", "push", "check", "review", "findings", "accept", "activate"]
    assert "preflight: ok" in lines[0] and "activate: done" in out
    assert "check: ok: admitted at origin/main " in out
    assert "review: ok: reviewed at " in out and "accept: skipped" in out
    assert [line for line in lines if line.startswith("Next:")] == ["Next: l4 yolo status p1"]
    assert lines[-1] == "Next: l4 yolo status p1"
    assert "  p1: activated on main" in out  # what `l4 yolo activate` printed, indented under the step
    assert [c.args for c in forge.called("start_run")] == [("main",)]


def test_a_forbidden_path_warning_is_printed_under_the_check_step(world, forge, person, capsys):  # SCN-YOLO-248
    world.push(
        {
            "openspec/changes/add-b/tasks.md": "## 1. B\n\n- [ ] 1.1 Edit `app/migrations/0001_initial.py`\n",
            "app/migrations/0001_initial.py": "# migration\n",
        },
        "unit b names an existing migration",
    )
    reviewed(world)
    forge.script_start_run("started")
    assert world.l4("go", "p1", "--reason", "ship it") == 0
    out = capsys.readouterr().out
    assert "check: ok: admitted at origin/main " in out
    assert f"  warning: forbidden_path: {B}: task 1.1 names app/migrations/0001_initial.py," in out


def test_a_test_path_warning_is_printed_under_the_check_step(world, forge, person, capsys):  # SCN-YOLO-256
    world.push(
        {"openspec/changes/add-b/tasks.md": "## 1. B\n\n- [ ] 1.1 Write `docs/client/fixtures/*.json`\n"},
        "unit b delivers docs fixtures",
    )
    reviewed(world)
    forge.script_start_run("started")
    assert world.l4("go", "p1", "--reason", "ship it") == 0
    out = capsys.readouterr().out
    assert "check: ok: admitted at origin/main " in out
    assert f"  warning: test_path: {B}: task 1.1 names docs/client/fixtures/," in out


def test_a_second_run_reports_the_active_plan(world, forge, person, capsys):
    reviewed(world)
    forge.script_start_run("started")
    assert world.l4("go", "p1", "--reason", "ship it") == 0
    capsys.readouterr()
    head = world.store().read().head
    assert world.l4("go", "p1", "--reason", "ship it") == 0
    out = capsys.readouterr().out
    assert "activate: ok: active since " in out and "review: skipped" in out
    assert out.splitlines()[-1] == "Next: l4 yolo status p1"
    assert world.store().read().head == head


def next_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("Next:")]


def kinds(world, kind):
    return [e for e in world.events() if e.type == kind]


def another_plan_active(world) -> None:
    """Plan `p2`, with a unit of its own, active on the same target."""
    other = plan_doc({"openspec:elsewhere": []}, plan_id="p2")
    world.push({".l4/plans/p2.json": json.dumps(other)})
    world.seed("p2", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"))
    world.pull()


def test_an_agent_stops_at_the_activation_with_the_persons_command(world, forge, monkeypatch, capsys):
    """SCN-YOLO-227."""
    reviewed(world)
    agent(world, monkeypatch)
    before = world.store().read().head
    assert world.l4("go", "p1", "--reason", "ship it") == 27
    out = capsys.readouterr().out
    assert "activate: person: activation is a person's decision" in out
    assert next_lines(out) == ["Next: a person runs: l4 yolo go p1 --reason 'ship it'"]
    assert out.splitlines()[-1] == next_lines(out)[0]
    assert kinds(world, "plan.activated") == [] and world.store().read().head == before
    assert forge.called("start_run") == []


def test_an_agent_is_told_the_activation_would_be_refused(world, forge, monkeypatch, capsys):
    """SCN-YOLO-228. A person decides cancelling a plan, so the agent's next line is a person's step."""
    reviewed(world)
    another_plan_active(world)
    agent(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 28
    out = capsys.readouterr().out
    assert "activate: stopped: plan p2 is already active, waiting or stopped on main" in out
    assert "cancelling plan p2 is a person's decision" in out
    assert next_lines(out) == [
        "Next: a person runs: l4 yolo cancel p2 --reason TEXT (stop here: cancelling a plan is a person's decision)"
    ]
    assert kinds(world, "plan.activated") == [] and world.events("p2")[-1].type == "plan.activated"


def test_the_agents_cancel_step_is_the_bare_command_in_json(world, forge, monkeypatch, capsys):
    reviewed(world)
    another_plan_active(world)
    agent(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R", "--json") == 28
    doc = json.loads(capsys.readouterr().out)
    assert doc["next_command"] == "l4 yolo cancel p2 --reason TEXT" and doc["exit"] == 28
    assert doc["steps"][-1]["status"] == "stopped"


def test_a_person_refused_by_another_active_plan_gets_the_cancel_command(world, forge, person, capsys):
    reviewed(world)
    another_plan_active(world)
    assert world.l4("go", "p1", "--reason", "R") == 28
    out = capsys.readouterr().out
    assert "activate: stopped: activate: plan p2 is already active, waiting or stopped on main" in out
    assert next_lines(out) == ["Next: l4 yolo cancel p2 --reason TEXT"]
    assert kinds(world, "plan.activated") == [] and person == ["Type the plan id (p1) to activate p1"]


def test_a_refusal_without_a_cancel_text_keeps_the_go_command(world, forge, person, monkeypatch, capsys):
    reviewed(world)

    def refuse(*args, **kwargs):
        from l4.exitcodes import ExitCode, L4Exit

        raise L4Exit(ExitCode.USAGE_ERROR, "activate: the target main is not on origin")

    monkeypatch.setattr("l4.yolo.commands.run_activate", refuse)
    assert world.l4("go", "p1", "--reason", "R") == 28
    assert next_lines(capsys.readouterr().out) == ["Next: l4 yolo go p1 --reason R"]


def holding(subject, findings, material, *, reason="keep it"):
    return ev(
        "plan.accepted", subject=subject, material=material, findings=findings, findings_sha=findings_sha(findings),
        reason=reason, by="alex@example.com", actor="person", marker=None, verdict="NEEDS_REVISION",
        prompt_version=PROMPT_VERSION,
    )  # fmt: skip


def test_a_persons_run_activates_with_the_reason_and_the_typed_plan_id(world, forge, person, capsys):
    """SCN-YOLO-229."""
    world.push_plan()
    world.pull()
    two_rounds(world, [TESTABILITY, FAILURES], unit=B)
    world.seed("p1", holding(B, [TESTABILITY, FAILURES], "m2"))
    forge.script_start_run("started")
    assert world.l4("go", "p1", "--reason", "ship it") == 0
    out = capsys.readouterr().out
    assert person == [
        "Type the plan id (p1) to activate p1"
    ]  # the acceptance was recorded before; this is the only ask
    (activated,) = kinds(world, "plan.activated")
    assert activated.data["reason"] == "ship it" and list(activated.data["accepted"]) == [B]
    assert f"accepted: {B} by alex@example.com (person): keep it" in out
    assert "accept: ok: 1 acceptance(s) hold" in out


def test_a_wrong_plan_id_activates_nothing(world, forge, person, monkeypatch, capsys):
    """B1: SCN-YOLO-229. A wrong answer stops with 29, records nothing and starts no run."""
    reviewed(world)
    monkeypatch.setattr("l4.yolo.commands.click.prompt", lambda text, **kw: "nope")
    before = world.store().read().head
    assert world.l4("go", "p1", "--reason", "R") == 29
    out = capsys.readouterr().out
    assert "activate: stopped: go: the plan id was not typed: nothing was recorded" in out
    assert next_lines(out) == ["Next: l4 yolo go p1 --reason R"] and out.splitlines()[-1] == next_lines(out)[0]
    assert kinds(world, "plan.activated") == [] and world.store().read().head == before
    assert forge.called("start_run") == []


def test_yes_activates_a_person_without_a_prompt(world, forge, person, capsys):
    reviewed(world)
    forge.script_start_run("started")
    assert world.l4("go", "p1", "--reason", "R", "--yes") == 0
    assert person == [] and len(kinds(world, "plan.activated")) == 1
    assert "activate: done" in capsys.readouterr().out


def test_no_terminal_and_no_yes_stops_with_29_before_activating(world, forge, person, monkeypatch, capsys):
    """The run began on a terminal (a person); the terminal is gone when activation asks."""
    reviewed(world)
    asks = iter([True])
    monkeypatch.setattr("l4.yolo.commands._stdin_tty", lambda: next(asks, False))
    before = world.store().read().head
    assert world.l4("go", "p1", "--reason", "R") == 29
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert lines[-2].startswith("activate: stopped: go: no terminal to ask the plan id on")
    assert next_lines(out) == ["Next: l4 yolo go p1 --reason R"] and lines[-1] == next_lines(out)[0]
    assert person == [] and kinds(world, "plan.activated") == [] and world.store().read().head == before


def test_an_agent_goes_as_far_as_it_may(world, forge, monkeypatch, capsys):
    """SCN-YOLO-236 (the agent half; the MCP half is in tests/unit/mcp)."""
    world.push({".l4/config.yaml": "yolo:\n  review:\n    accept_by_agents: true\n"}, "agents may accept")
    world.push_plan()
    world.pull()
    two_rounds(world, [TESTABILITY], unit=B)
    agent(world, monkeypatch)  # click.prompt fails the test if called
    before = world.store().read().head
    assert world.l4("go", "p1", "--reason", "R", "--accept-findings") == 29
    assert next_lines(capsys.readouterr().out) == ["Next: l4 yolo go p1 --reason R --accept-findings --yes"]
    assert world.store().read().head == before
    assert world.l4("go", "p1", "--reason", "R", "--accept-findings", "--yes") == 27
    out = capsys.readouterr().out
    (accepted,) = kinds(world, "plan.accepted")
    assert accepted.data["subject"] == B and accepted.data["actor"] == "agent"
    assert next_lines(out) == ["Next: a person runs: l4 yolo go p1 --reason R"]
    assert kinds(world, "plan.activated") == []


def test_without_the_key_the_agent_hands_the_acceptance_to_a_person(world, forge, monkeypatch, capsys):
    world.push_plan()
    world.pull()
    two_rounds(world, [TESTABILITY], unit=B)
    agent(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R", "--accept-findings") == 27
    assert next_lines(capsys.readouterr().out) == ["Next: a person runs: l4 yolo go p1 --reason R --accept-findings"]
    assert kinds(world, "plan.accepted") == []


def test_a_harness_fault_in_a_called_command_is_exit_1_with_the_document(world, forge, person, monkeypatch, capsys):
    """D9: exit 1 keeps its meaning; it is not a refusal (28)."""
    reviewed(world)

    def fault(*args, **kwargs):
        from l4.exitcodes import ExitCode, L4Exit

        raise L4Exit(ExitCode.INTERNAL_ERROR, "git fetch failed: the network is down")

    monkeypatch.setattr("l4.yolo.commands.run_activate", fault)
    assert world.l4("go", "p1", "--reason", "R", "--json") == 1
    doc = json.loads(capsys.readouterr().out)
    assert doc["exit"] == 1 and doc["next_command"] == "l4 yolo go p1 --reason R --json"
    assert doc["steps"][-1]["name"] == "activate" and "the network is down" in doc["steps"][-1]["detail"]
    assert kinds(world, "plan.activated") == []
