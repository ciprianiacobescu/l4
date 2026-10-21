# ruff: noqa: F811
"""`l4 retry` (L4-OPS-001, L4-OPS-003, SCN-OPS-01..03, 06, 07): the retry of each phase, the refusals with what moves
the unit, and the person's spec change since the stop."""

import pytest

from l4.cli import main
from l4.config.redaction import load_app_config
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import AmbiguousWrite, ForgeError, ForgeUnavailable
from l4.forge.local import LocalForge
from l4.specs.providers import providers_for
from l4.state.retry import retry_unit
from l4.state.status import refresh_refs, select_runnable
from l4.vcs.git import Git

from .ops_world import (  # noqa: F401
    BRANCH,
    NAME,
    REWORDED_SPEC,
    UNIT,
    UNIT_REL,
    escalate,
    events,
    failing_reds,
    happy,
    person_pushes,
    stamp,
    world,
)


def retry(world, **kwargs):
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    refresh_refs(app, cfg, git)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), UNIT)
    kwargs.setdefault("reason", "try again")
    return retry_unit(app, cfg, git, provider, ref, **kwargs)


def kinds(world):
    return [e["type"] for e in events(world.remote)]


def phase_changes(world):
    return [(e["from"], e["to"], e["trigger"]) for e in events(world.remote) if e["type"] == "phase.changed"]


def subject(world):
    return world.remote.run("log", "-1", "--format=%s", BRANCH).stdout.strip()


def test_a_halted_unit_goes_back_to_its_phase_and_records_unit_retried(world):
    assert world.run(failing_reds()).code == ExitCode.HALTED
    result = retry(world, reason="spec clarified", by="alex", signal="label:7")
    assert result.exit_code == ExitCode.OK and result.outcome.phase_after == "implementing"
    [retried] = [e for e in events(world.remote) if e["type"] == "unit.retried"]
    assert (retried["reason"], retried["by"], retried["signal"]) == ("spec clarified", "alex", "label:7")
    assert "unit.resumed" not in kinds(world)
    assert phase_changes(world)[-1] == ("halted", "implementing", "resumed")
    assert subject(world) == f"chore({NAME}): retry [skip ci]"


def test_an_escalated_unit_at_the_fix_round_limit_needs_no_flag(world):
    """SCN-OPS-01: `fix rounds used 3/3` gets one more round, then the unit is back in `verifying`."""
    world.run(failing_reds())
    escalate(world, spawned=3)
    result = retry(world)
    assert result.outcome.phase_after == "verifying"
    log = events(world.remote)
    [extended] = [e for e in log if e["type"] == "budget.extended"]
    assert extended["fix_rounds"] == 1
    assert [e["type"] for e in log if e["type"] in ("budget.extended", "unit.retried")] == [
        "budget.extended",
        "unit.retried",
    ]
    assert phase_changes(world)[-1] == ("escalated", "verifying", "resumed")
    assert subject(world) == f"chore({NAME}): retry [skip ci]"


def test_rounds_sets_the_number_of_fix_rounds(world):
    world.run(failing_reds())
    escalate(world, spawned=3)
    retry(world, rounds=2)
    assert [e["fix_rounds"] for e in events(world.remote) if e["type"] == "budget.extended"] == [2]


def test_an_escalated_unit_with_fix_rounds_left_gets_none_added(world):
    world.run(failing_reds())
    escalate(world, reason="no_fix_units", detail="the verifier made no fix unit", spawned=1)
    retry(world)
    assert "budget.extended" not in kinds(world)
    assert phase_changes(world)[-1][:2] == ("escalated", "verifying")


def test_a_unit_escalated_for_the_feedback_limit_gets_a_feedback_round(world):
    world.run(failing_reds())
    rows = [("fix.spawned", {"fix_unit": f"{NAME}-fix-{i}", "round": i, "feedback_only": True}) for i in range(1, 6)]
    stamp(
        world,
        *rows,
        ("phase.changed", {"from": "verifying", "to": "escalated", "trigger": "verify_fail_exhausted",
                           "reason": "feedback_rounds_exhausted", "detail": "feedback rounds used 5/5"}),
    )  # fmt: skip
    retry(world, rounds=2)
    [extended] = [e for e in events(world.remote) if e["type"] == "budget.extended"]
    assert extended["feedback_rounds"] == 2 and "fix_rounds" not in extended


def test_same_failure_gets_one_more_round_only_when_the_rounds_are_used_up(world):
    world.run(failing_reds())
    escalate(world, reason="same_failure", detail="round 2 failed the same way as round 1", spawned=3)
    retry(world)
    assert [e["fix_rounds"] for e in events(world.remote) if e["type"] == "budget.extended"] == [1]


def test_a_unit_waiting_for_capacity_continues_from_fixing_at_once(world):
    """SCN-OPS-02: no `retry_after` is read; the unit goes back to the phase it was parked from."""
    world.run(failing_reds())
    stamp(
        world,
        ("phase.changed", {"from": "fixing", "to": "waiting_capacity", "trigger": "required_role_unavailable"}),
    )
    result = retry(world)
    assert result.outcome.phase_after == "fixing"
    assert phase_changes(world)[-1] == ("waiting_capacity", "fixing", "capacity_restored")
    assert "unit.retried" in kinds(world) and subject(world) == f"chore({NAME}): retry [skip ci]"


def test_a_unit_in_review_goes_back_to_verifying(world):
    assert world.run(happy()).code == ExitCode.OK
    result = retry(world)
    assert result.outcome.phase_after == "verifying"
    assert phase_changes(world)[-1] == ("in_review", "verifying", "retry_requested")
    assert subject(world) == f"chore({NAME}): retry [skip ci]"


def test_a_unit_that_waits_for_an_answer_is_refused_and_nothing_is_recorded(world):
    """SCN-OPS-03."""
    world.run(failing_reds())
    stamp(
        world,
        ("question.raised", {"id": "Q-002", "kind": "blocking"}),
        ("phase.changed", {"from": "implementing", "to": "awaiting_human", "trigger": "questions_blocking"}),
    )
    before = (world.remote.run("rev-parse", BRANCH).stdout, kinds(world))
    with pytest.raises(L4Exit) as caught:
        retry(world)
    assert caught.value.code == ExitCode.USAGE_ERROR
    assert f"retry: {UNIT} is awaiting_human: answer Q-002 in {UNIT_REL}/questions.md on {BRANCH}, then push" in str(
        caught.value
    )
    assert (world.remote.run("rev-parse", BRANCH).stdout, kinds(world)) == before


@pytest.mark.parametrize(
    ("phase", "message"),
    [
        ("implementing", "the harness continues it at the next run"),
        ("verifying", "the harness continues it at the next run"),
        ("fixing", "the harness continues it at the next run"),
        ("abandoned", f"use l4 restart --unit {UNIT} --reason TEXT"),
    ],
)
def test_the_phases_that_a_retry_cannot_move_say_what_moves_them(world, phase, message):
    world.run(failing_reds())
    stamp(world, ("phase.changed", {"from": "halted", "to": phase, "trigger": "x"}))
    with pytest.raises(L4Exit, match=f"retry: {UNIT} is {phase}: ") as caught:
        retry(world)
    assert message in str(caught.value) and caught.value.code == ExitCode.USAGE_ERROR


def test_an_unstarted_unit_is_refused(world):
    with pytest.raises(L4Exit, match=f"retry: {UNIT} is not started: the next run starts it") as caught:
        retry(world)
    assert caught.value.code == ExitCode.USAGE_ERROR


# --- L4-OPS-003: a person's change to the unit folder since the stop -----------------------------------------------


def test_a_reworded_requirement_sends_an_escalated_unit_to_implementing(world):
    """SCN-OPS-06."""
    world.run(failing_reds())
    escalate(world, spawned=3)
    person_pushes(world, {f"{UNIT_REL}/specs/greeting/spec.md": REWORDED_SPEC})
    result = retry(world)
    assert result.outcome.phase_after == "implementing"
    assert phase_changes(world)[-1] == ("escalated", "implementing", "spec_edit_since_stop")


def test_a_change_outside_the_unit_folder_does_not_count(world):
    """SCN-OPS-07."""
    world.run(failing_reds())
    person_pushes(world, {"src/greeting.py": "# a fix\n"})
    result = retry(world)
    assert phase_changes(world)[-1] == ("halted", "implementing", "resumed")
    assert result.outcome.phase_after == "implementing"


def test_a_change_to_the_harness_files_of_the_unit_does_not_count(world):
    world.run(failing_reds())
    escalate(world, spawned=3)
    person_pushes(world, {f"{UNIT_REL}/verification.md": "# edited\n"})
    retry(world)
    assert phase_changes(world)[-1][2] == "resumed"


# --- merged: the archive duty ------------------------------------------------------------------------------------


def test_a_merged_unit_is_delegated_to_the_archive_retry(world, monkeypatch):
    from l4.ci.sweeper import SweepAction
    from l4.state import retry as retry_module

    world.run(happy())
    seen = {}

    def fake_sweep(app, cfg, git, rows, *, retry=False):
        seen["retry"] = retry
        return [SweepAction(UNIT, "archive_failed", "push rule")]

    real = retry_module.load_snapshot

    def merged(*args, **kwargs):
        snapshot = real(*args, **kwargs)
        state = snapshot.state.model_copy(update={"phase": "merged"})
        return snapshot.__class__(**{**snapshot.__dict__, "state": state})

    monkeypatch.setattr("l4.ci.sweeper.sweep", fake_sweep)
    monkeypatch.setattr(retry_module, "load_snapshot", merged)
    monkeypatch.setattr(retry_module, "snapshots", lambda app, cfg, units: [])
    result = retry(world)
    assert seen == {"retry": True} and result.outcome.phase_after == "merged"
    assert result.exit_code == ExitCode.HALTED and "archive_failed" in result.outcome.exit_reason


def test_a_merged_unit_with_nothing_to_retry_is_refused(world, monkeypatch):
    from l4.state import retry as retry_module

    world.run(happy())
    real = retry_module.load_snapshot

    def merged(*args, **kwargs):
        snapshot = real(*args, **kwargs)
        return snapshot.__class__(
            **{**snapshot.__dict__, "state": snapshot.state.model_copy(update={"phase": "merged"})}
        )

    monkeypatch.setattr("l4.ci.sweeper.sweep", lambda *a, **k: [])
    monkeypatch.setattr(retry_module, "load_snapshot", merged)
    monkeypatch.setattr(retry_module, "snapshots", lambda app, cfg, units: [])
    with pytest.raises(L4Exit, match="is merged: no archive or done-gate failure is recorded"):
        retry(world)


# --- L4-OPS-002: the command starts a run after the push ------------------------------------------------------------


@pytest.fixture
def forge(monkeypatch):
    local = LocalForge()
    monkeypatch.setattr("l4.state.retry.make_forge", lambda *a, **k: local)
    return local


def command(world, *extra, capsys=None):
    argv = ["retry", "--unit", UNIT, "--reason", "try again", "--repo", str(world.app.repo)]
    argv += ["--config", str(world.app.config_path), *extra]
    return main(argv, environ=dict(world.app.environ))


def test_the_retry_starts_a_run_on_the_base_branch(world, forge, capsys):
    """SCN-OPS-04."""
    world.run(failing_reds())
    forge.script_start_run("started")
    assert command(world) == 0
    assert "run started on main" in capsys.readouterr().out
    assert [c.args for c in forge.called("start_run")] == [("main",)]
    assert subject(world) == f"chore({NAME}): retry [skip ci]"


def test_a_run_that_waits_counts_as_started(world, forge, capsys):
    world.run(failing_reds())
    forge.script_start_run("already_queued")
    assert command(world) == 0
    assert "a run is already queued on main" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["refused", "unsupported"])
def test_a_refused_start_still_exits_0_and_says_how(world, forge, capsys, answer):
    """SCN-OPS-05: the retry is pushed, the output names what starts a run."""
    world.run(failing_reds())
    forge.script_start_run(answer)
    assert command(world) == 0
    out = capsys.readouterr().out
    assert "start a run with: " in out and "main" in out and "run started" not in out
    assert subject(world) == f"chore({NAME}): retry [skip ci]"


@pytest.mark.parametrize("failure", [ForgeError("HTTP 422", status=422), AmbiguousWrite("HTTP 502", status=502)])
def test_a_start_the_forge_fails_with_an_error_still_exits_0_and_says_how(world, forge, capsys, monkeypatch, failure):
    """Review M4: the push is done; a 422 (`ForgeError`) or a 502 (`AmbiguousWrite`) of the dispatch must not turn a
    successful retry into a failing command."""
    world.run(failing_reds())

    def fails(ref):
        raise failure

    monkeypatch.setattr(forge, "start_run", fails)
    assert command(world) == 0
    out = capsys.readouterr().out
    assert "start a run with: " in out and "run started" not in out
    assert subject(world) == f"chore({NAME}): retry [skip ci]"


def test_no_run_starts_nothing(world, forge, capsys):
    world.run(failing_reds())
    assert command(world, "--no-run") == 0
    assert forge.called("start_run") == [] and "run" not in capsys.readouterr().out.replace("retried", "")


def test_a_missing_token_prints_the_way_to_start_a_run(world, monkeypatch, capsys):
    from l4.forge.base import ForgeUnavailable

    def unavailable(*args, **kwargs):
        raise ForgeUnavailable("GITHUB_TOKEN is not set")

    world.run(failing_reds())
    monkeypatch.setattr("l4.state.retry.make_forge", unavailable)
    assert command(world) == 0
    assert "start a run with: " in capsys.readouterr().out


def test_the_instruction_names_the_command_of_each_forge(world):
    from l4.state.retry import how_to_start

    app, cfg = load_app_config(world.app)
    github = cfg.model_copy(update={"forge": cfg.forge.model_copy(update={"type": "github"})})
    assert how_to_start(app, github, "main") == "gh workflow run l4.yml --ref main"
    gitlab = cfg.model_copy(update={"forge": cfg.forge.model_copy(update={"type": "gitlab"})})
    gitlab.forge.gitlab.api_url, gitlab.forge.gitlab.project = "https://git.example/api/v4", "grp/proj"
    assert how_to_start(app, gitlab, "main") == "https://git.example/grp/proj/-/pipelines/new?ref=main"


def test_a_refusal_is_a_usage_error_before_any_run_start(world, forge):
    argv = ["retry", "--unit", UNIT, "--reason", "x", "--repo", str(world.app.repo)]
    argv += ["--config", str(world.app.config_path)]
    assert main(argv, environ=dict(world.app.environ)) == int(ExitCode.USAGE_ERROR)
    assert forge.called("start_run") == []


# --- L4-OPS-018: the reason reaches the implementer of the halted task ------------------------------------------------


def tripped_task(world):
    [tripped] = [e for e in events(world.remote) if e["type"] == "breaker.tripped"]
    return tripped["task"]


def test_a_retry_with_a_note_binds_the_reason_to_the_halted_task(world):
    """SCN-OPS-28: the event carries `note_task`, no `note_fix_unit` for the unit's own task."""
    world.run(failing_reds())
    task = tripped_task(world)
    retry(world, reason="add the keyword with a default", note=True)
    [retried] = [e for e in events(world.remote) if e["type"] == "unit.retried"]
    assert retried["note_task"] == task and "note_fix_unit" not in retried


def test_a_retry_that_is_not_the_command_carries_no_note(world):
    """SCN-OPS-30: a label retry, a plan's retry and the sweep call `retry_unit` without `note`."""
    world.run(failing_reds())
    retry(world, reason="a member added the label", by="alex", signal="label:7")
    [retried] = [e for e in events(world.remote) if e["type"] == "unit.retried"]
    assert "note_task" not in retried and "note_fix_unit" not in retried


def test_the_command_prints_the_note_line(world, forge, capsys):
    world.run(failing_reds())
    task = tripped_task(world)
    forge.script_start_run("started")
    assert command(world) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[-1] == f"note: the reason goes to the next steps of task {task}"
    assert out.index("run started on main") < len(out) - 1  # after the retry line (start_run_line)


def test_a_stop_that_names_no_task_gives_no_binding_and_the_line(world, forge, capsys):
    """SCN-OPS-31: `baseline_failed` and `escalated` carry no `halt_task`."""
    world.run(failing_reds())
    stamp(
        world,
        ("phase.changed", {"from": "implementing", "to": "halted", "reason": "baseline_failed", "detail": "x"}),
    )
    forge.script_start_run("started")
    assert command(world) == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "note: the stop names no task, so no implementer step reads the reason"
    )
    assert all("note_task" not in e for e in events(world.remote) if e["type"] == "unit.retried")


def test_an_escalated_unit_gets_no_binding(world):
    world.run(failing_reds())
    escalate(world, spawned=3)
    retry(world, note=True)
    [retried] = [e for e in events(world.remote) if e["type"] == "unit.retried"]
    assert "note_task" not in retried


def test_a_reason_over_300_characters_is_said_to_be_cut(world, forge, capsys):
    world.run(failing_reds())
    forge.script_start_run("started")
    argv = ["retry", "--unit", UNIT, "--reason", "x" * 301, "--repo", str(world.app.repo)]
    assert main([*argv, "--config", str(world.app.config_path)], environ=dict(world.app.environ)) == 0
    out = capsys.readouterr().out
    assert "retry: the reason is longer than 300 characters; the implementer reads the first 300" in out
    [retried] = [e for e in events(world.remote) if e["type"] == "unit.retried"]
    assert len(retried["reason"]) == 300


# --- start_run_result (yolo-go 2.2) -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer, line",
    [
        ("started", "run started on main"),
        ("already_queued", "a run is already queued on main"),
        ("refused", "start a run with: "),
        ("unsupported", "start a run with: "),
    ],
)
def test_start_run_result_gives_the_answer_and_the_line(world, forge, answer, line):
    from l4.state.retry import start_run_line, start_run_result

    app, cfg = load_app_config(world.app)
    forge.script_start_run(answer)
    got, text = start_run_result(app, cfg)
    assert got == answer and text.startswith(line)
    forge.script_start_run(answer)
    assert start_run_line(app, cfg) == text  # the line is what it was


@pytest.mark.parametrize("error", [ForgeUnavailable("no token"), ForgeError("HTTP 422", status=422)])
def test_start_run_result_is_unavailable_when_the_forge_cannot_be_asked(world, forge, monkeypatch, error):
    from l4.state.retry import start_run_line, start_run_result

    app, cfg = load_app_config(world.app)

    def fails(ref):
        raise error

    monkeypatch.setattr(forge, "start_run", fails)
    got, text = start_run_result(app, cfg)
    assert got == "unavailable" and text.startswith("start a run with: ")
    assert start_run_line(app, cfg) == text
