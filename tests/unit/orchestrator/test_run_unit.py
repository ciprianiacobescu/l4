import types

import pytest

from l4.agents.fake import Step
from l4.cli import main
from l4.state.lifecycle import Trigger

from ..conftest import UNIT
from ..implementer.conftest import IMPL, KNOWN, STUB, green_step, red_step, result
from .conftest import BRANCH, UNIT_DIR, new_origin_main

TWO_TASKS = "## 1. Pricing\n\n- [ ] 1.1 Add `apply_discount`\n- [ ] 1.2 Add `shout`\n"
SHOUT_TEST = (
    f'import pytest\nfrom pytdd.pricing import shout\n\n\n@pytest.mark.l4("{KNOWN}")\ndef test_shout():\n'
    '    assert shout("ada") == "ADA"\n'
)


def red_second() -> Step:
    stub = IMPL + "\n\ndef shout(name):\n    raise NotImplementedError\n"
    return Step(
        writes={"tests/test_shout.py": SHOUT_TEST, "src/pytdd/pricing.py": stub},
        structured=result("red", task_ids=["1.2"]),
    )


def green_second() -> Step:
    done = IMPL + "\n\ndef shout(name):\n    return name.upper()\n"
    return Step(writes={"src/pytdd/pricing.py": done}, structured=result("green", task_ids=["1.2"]))


def assert_markers_are_the_only_bytes_that_changed(run) -> None:
    before = run.raw(run.tdd.origin, "show", f"main:{UNIT_DIR}/tasks.md").encode()
    after = run.pushed(f"{UNIT_DIR}/tasks.md").encode()
    assert len(before) == len(after)
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    expected = [before.index(b"- [ ] 1.1") + 3, before.index(b"- [ ] 1.2") + 3]
    assert changed == expected and {after[i] for i in changed} == {ord("x")}  # ' ' -> 'x', nothing re-serialised


def assert_red_precedes_green_per_task(run) -> None:
    """By trailer, not by subject: the red commit of each task is a strict ancestor of its green commit, and the
    `task.red_ok` event names the base that commit sits on."""
    trailer = "%(trailers:key=L4-{},valueonly,separator=%x2c)"
    fmt = f"%H%x01{trailer.format('Task')}%x01{trailer.format('TDD')}%x02"
    log = run.raw(run.tdd.origin, "log", f"--format={fmt}", f"main..{BRANCH}")
    commits: dict[tuple[str, str], str] = {}
    for record in filter(None, (r.strip("\n") for r in log.split("\x02"))):
        sha, task, tdd = (part.strip() for part in record.split("\x01"))
        if tdd:
            assert (task, tdd) not in commits  # exactly one red and one green commit per task
            commits[(task, tdd)] = sha
    assert sorted(commits) == [("1.1", "green"), ("1.1", "red"), ("1.2", "green"), ("1.2", "red")]
    for task in ("1.1", "1.2"):
        red, green = commits[(task, "red")], commits[(task, "green")]
        assert red != green
        run.raw(run.tdd.origin, "merge-base", "--is-ancestor", red, green)  # raises when it is not
    bases = {t: run.raw(run.tdd.origin, "rev-parse", f"{commits[(t, 'red')]}~1").strip() for t in ("1.1", "1.2")}
    assert {e["task"]: e["base"] for e in run.events("task.red_ok")} == bases


def test_two_task_unit_reaches_implemented(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": TWO_TASKS})
    run = run_l4([red_step(), green_step(), red_second(), green_second()])
    assert run.code == 0
    assert [s.split("(")[0] for s in run.subjects()] == ["test", "feat", "test", "feat", "chore"]
    assert run.pushed(f"{UNIT_DIR}/tasks.md").count("[x]") == 2
    assert [e["task"] for e in run.events("task.done")] == ["1.1", "1.2"]
    assert_markers_are_the_only_bytes_that_changed(run)
    assert_red_precedes_green_per_task(run)
    assert run.triggers() == ["unit_discovered_pending", "intake_all_pass", "lease_acquired", "all_leaves_done"]
    assert run.outcome["units"][0]["tasks"] == {"done": 2, "total": 2}
    # the second task's prompts carry that task, not the first
    assert all("# Task 1.2" in r.prompt for r in run.adapter.requests[2:])


def test_a_crash_between_tasks_resumes_at_the_next_one(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": TWO_TASKS})
    crashed = run_l4([red_step(), green_step(), red_second()])  # the fake's script ends: an AdapterError
    assert crashed.code == 1
    assert crashed.pushed(f"{UNIT_DIR}/tasks.md").count("[x]") == 1  # task 1.1 was pushed before the crash
    resumed = run_l4([red_second(), green_second()])
    assert resumed.code == 0
    assert resumed.pushed(f"{UNIT_DIR}/tasks.md").count("[x]") == 2
    reds = [s for s in resumed.subjects() if s.startswith("test(")]
    assert len(reds) == 2  # no duplicate red for 1.1
    assert resumed.outcome["units"][0]["phase_before"] == "implementing"


def test_rejected_unit_never_calls_agent_and_illegal_transition_raises(run_l4, tdd_repo, raw, install_hooks):
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": ""})
    rejected = run_l4([red_step()])
    assert rejected.code == 14 and rejected.adapter.requests == []
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": "- [ ] 1.1 Add `apply_discount`\n"})
    # a verify hook that answers with a trigger the lifecycle has no edge for
    install_hooks(verify=lambda ctx: Trigger.HAND_OFF_PUSHED)
    illegal = run_l4([red_step(), green_step()])
    assert illegal.code == 1
    assert illegal.triggers()[-1] == "verification_started"  # nothing was written for the refused edge
    [failed] = illegal.outcome["units"]  # HB-7: the exception ends that unit, which is still listed, with its reason
    assert "IllegalTransition" in failed["exit_reason"] and failed["phase_after"] == "verifying"


def test_sandbox_unavailable_exits_3_without_running_anything(run_l4, tdd_repo, monkeypatch):
    monkeypatch.setattr("l4.sandbox.select.resolve_tool", lambda *a, **k: None)
    run = run_l4([red_step()], sandbox={"mode": "bwrap"})
    assert run.code == 3
    assert run.adapter.requests == []  # no agent
    assert not (tdd_repo.repo / ".l4-out" / "gates").exists()  # no gate: setup and tests never started
    assert run.raw(tdd_repo.origin, "for-each-ref", "--format=%(refname)").split() == ["refs/heads/main"]


def test_a_failing_setup_exits_3_and_keeps_the_phase_so_a_rerun_resumes(run_l4):
    broken = run_l4([red_step()], setup=["false"])
    assert broken.code == 3 and broken.adapter.requests == []
    assert broken.triggers()[-1] == "lease_acquired"
    fixed = run_l4([red_step(), green_step()])
    assert fixed.code == 0
    assert fixed.outcome["units"][0]["phase_before"] == "implementing"


def test_a_stub_is_what_the_fixture_expects():
    assert "NotImplementedError" in STUB
    with pytest.raises(AssertionError):
        assert "NotImplementedError" in IMPL


def test_a_bwrap_that_exists_but_fails_its_self_test_exits_3_through_l4_run(run_l4, tdd_repo):
    fake_bin = tdd_repo.cache.parent / "fake-bin"
    fake_bin.mkdir()
    called = fake_bin / "called"
    (fake_bin / "bwrap").write_text(f"#!/bin/sh\ntouch {called}\necho 'bwrap: no permissions' >&2\nexit 1\n")
    (fake_bin / "bwrap").chmod(0o755)
    tdd_repo.environ["PATH"] = f"{fake_bin}:{tdd_repo.environ['PATH']}"
    run = run_l4([red_step()], sandbox={"mode": "bwrap"})
    assert called.exists()  # it was found and run, not merely missing
    assert run.code == 3
    assert run.adapter.requests == []
    assert not (tdd_repo.repo / ".l4-out" / "gates").exists() and not (tdd_repo.repo / ".l4-out" / "agent").exists()
    assert run.raw(tdd_repo.origin, "for-each-ref", "--format=%(refname)").split() == ["refs/heads/main"]


def test_a_forged_ledger_is_restored_before_the_final_ledger_commit_of_a_crashed_run(run_l4, monkeypatch):
    forged = '{"ts":"2026-10-03T13:00:00Z","run_id":"x","unit":"u","seq":1,"type":"phase.changed","to":"verified"}\n'

    def crash_after_the_agent(git, protected, base, **kwargs):
        (git.repo / protected.run_ledger).write_text(forged)  # the agent's edit, left behind by an early exception
        raise RuntimeError("crash before the step's own restore")

    monkeypatch.setattr("l4.implementer.tdd.revert_protected", crash_after_the_agent)
    run = run_l4([red_step()])
    assert run.code == 1
    assert all(e["unit"] != "u" and e["run_id"] != "x" for e in run.ledger())
    assert [e["rule"] for e in run.events("guard.violation")] == ["run ledger"]
    assert run.events("lock.released")  # the pushed ledger is the writer's own, to the end


# --- the sticky note of a base merge conflict (verifier 1.6, M1 form) -----------------------------------------------


class RecordingMirror:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, tuple[str, ...] | None]] = []

    def sync(self, phase, notes=None):
        self.calls.append((phase, None if notes is None else tuple(notes)))


def conflict_verify(ctx):
    from l4.vcs.merge import BaseMergeConflict

    raise BaseMergeConflict("main", "ab" * 20, ["src/pricing/cart.py", "src/pricing/tax.py"])


def test_base_conflict_sets_sticky_note_and_exits_1(run_l4, install_hooks):
    mirror = RecordingMirror()
    install_hooks(mirror=lambda ctx: mirror, verify=conflict_verify)
    run = run_l4([red_step(), green_step()])
    assert run.code == 1
    phase, notes = mirror.calls[-1]
    assert phase == "verifying" and notes is not None and len(notes) == 1
    assert "Base merge needed" in notes[0] and "`main`@`ababababab`" in notes[0]
    assert "src/pricing/cart.py, src/pricing/tax.py" in notes[0] and "exits 1" in notes[0]
    assert run.triggers()[-1] == "verification_started"  # the phase stays `verifying`
    assert run.events("verify.verdict") == []  # no verdict: a verdict on a conflict says nothing about the unit


def test_base_conflict_outcome_carries_its_own_reason_and_keeps_exit_1(run_l4, install_hooks):
    install_hooks(mirror=lambda ctx: RecordingMirror(), verify=conflict_verify)
    run = run_l4([red_step(), green_step()])
    assert run.code == 1 and run.outcome["exit_code"] == 1
    [unit] = run.outcome["units"]
    assert unit["exit_reason"] == f"base merge conflict: merge main into {BRANCH} by hand and push"


def test_next_successful_merge_clears_the_conflict_note(run_l4, install_hooks):
    mirror = RecordingMirror()
    install_hooks(mirror=lambda ctx: mirror, verify=conflict_verify)
    assert run_l4([red_step(), green_step()]).code == 1

    def merged(ctx):  # what `bring_in_base` does after a human merged the base: it clears the note
        ctx.shared["notes"] = ()
        return Trigger.VERIFY_PASS

    install_hooks(mirror=lambda ctx: mirror, verify=merged)
    again = run_l4([])
    assert again.code == 0
    sticky = [notes for _, notes in mirror.calls if notes is not None]
    last_conflict = max(i for i, notes in enumerate(sticky) if notes and "Base merge needed" in notes[0])
    assert last_conflict < len(sticky) - 1 and sticky[-1] == ()


# --- a unit parked on a dead login is due on the next run (M1.8 R4) -------------------------------------------------


def auth_park(ctx):
    from l4.availability.errors import Unready, WaitingCapacity

    raise WaitingCapacity(
        "judges", "profile claude-code failed the auth probe: claude is not logged in", ctx.services.factory.now(),
        (Unready("claude-code", "claude-code", "subscription", "auth", "claude is not logged in"),),
    )  # fmt: skip


def test_auth_park_is_due_on_the_next_run(run_l4, install_hooks, fake_clock):
    from datetime import datetime

    from l4.planner import UnitFacts, next_action

    install_hooks(mirror=lambda ctx: RecordingMirror(), verify=auth_park)
    parked = run_l4([red_step(), green_step()])
    assert parked.code == 12
    [unit] = parked.outcome["units"]
    assert unit["phase_after"] == "waiting_capacity" and unit["retry_after"] == "2026-01-01T00:00:00Z"  # not +30 min
    facts = UnitFacts(
        "openspec:add-discount-codes", "openspec", "waiting_capacity", 1, 1,
        retry_after=unit["retry_after"], previous_phase="verifying",
    )  # fmt: skip
    assert next_action(facts, fake_clock.now())[0] == "verify"
    assert fake_clock.now() >= datetime.fromisoformat(unit["retry_after"])

    install_hooks(mirror=lambda ctx: RecordingMirror(), verify=lambda ctx: Trigger.VERIFY_PASS)
    again = run_l4([])  # the login is fixed: the same instant, no waiting
    assert again.code == 0


def test_park_writes_exit_reason_to_outcome(run_l4, install_hooks, fake_clock):
    install_hooks(mirror=lambda ctx: RecordingMirror(), verify=auth_park)
    run = run_l4([red_step(), green_step()])
    assert run.code == 12
    [unit] = run.outcome["units"]
    assert unit["exit_reason"].startswith("waiting_capacity: ")
    assert "claude is not logged in" in unit["exit_reason"] and len(unit["exit_reason"]) <= 300
    assert unit["retry_after"] == "2026-01-01T00:00:00Z"


def test_a_bare_role_unavailable_also_sets_exit_reason(run_l4, install_hooks, fake_clock):
    from l4.availability.errors import RoleUnavailable

    def bare(ctx):
        raise RoleUnavailable("clarifier", "no profile")

    install_hooks(mirror=lambda ctx: RecordingMirror(), verify=bare)
    [unit] = run_l4([red_step(), green_step()]).outcome["units"]
    assert unit["exit_reason"] == "waiting_capacity: role clarifier is unavailable: no profile"


# --- the "Waiting for capacity" note on the MR (M1.8 R3) ------------------------------------------------------------


def test_auth_park_writes_sticky_with_login_steps(run_l4, install_hooks, fake_clock):
    mirror = RecordingMirror()
    install_hooks(mirror=lambda ctx: mirror, verify=auth_park)
    assert run_l4([red_step(), green_step()]).code == 12
    phase, notes = mirror.calls[-1]
    assert phase == "waiting_capacity" and notes is not None and len(notes) == 1
    note = notes[0]
    assert note.startswith("### Waiting for capacity")
    assert "`claude-code`" in note and "claude is not logged in" in note
    assert "run `claude setup-token` on a machine with a browser" in note
    assert "run a pipeline on `main`" in note and "wait for the scheduled run" in note and "l4 sweep" not in note


def quota_park(ctx):
    from datetime import timedelta

    from l4.availability.errors import WaitingCapacity

    raise WaitingCapacity(
        "judges", "profile claude-code failed the quota probe: used up", ctx.services.factory.now() + timedelta(hours=1)
    )


def test_quota_park_names_retry_after_and_the_sweep(run_l4, install_hooks, fake_clock):
    mirror = RecordingMirror()
    install_hooks(mirror=lambda ctx: mirror, verify=quota_park)
    assert run_l4([red_step(), green_step()]).code == 12
    note = mirror.calls[-1][1][0]
    assert "2026-01-01T01:00Z" in note and "The scheduled run resumes the unit" in note
    assert "setup-token" not in note  # a cool-down needs no login


def test_capacity_restored_clears_the_capacity_note(run_l4, install_hooks, fake_clock):
    mirror = RecordingMirror()
    install_hooks(mirror=lambda ctx: mirror, verify=auth_park)
    assert run_l4([red_step(), green_step()]).code == 12
    install_hooks(mirror=lambda ctx: mirror, verify=lambda ctx: Trigger.VERIFY_PASS)
    assert run_l4([]).code == 0
    sticky = [notes for _, notes in mirror.calls if notes is not None]
    assert any(n and "Waiting for capacity" in n[0] for n in sticky) and sticky[-1] == ()


def test_a_second_park_refreshes_the_note_instead_of_adding_one(run_l4, install_hooks, fake_clock):
    mirror = RecordingMirror()
    install_hooks(mirror=lambda ctx: mirror, verify=auth_park)
    assert run_l4([red_step(), green_step()]).code == 12
    assert run_l4([]).code == 12
    assert all(len(n) == 1 for _, n in mirror.calls if n)  # one section each time, which replaces the sticky note
    assert sum(1 for _, n in mirror.calls if n == ()) >= 1  # cleared by CAPACITY_RESTORED, written again by the park
    assert "Waiting for capacity" in mirror.calls[-1][1][0]


def test_run_still_fails_closed_without_bwrap(run_l4, tdd_repo, monkeypatch):
    """W2 (a): only `l4 resume` goes without a sandbox; `l4 run` keeps the fail-closed selection (exit 3)."""
    monkeypatch.setattr("l4.sandbox.select.resolve_tool", lambda *a, **k: None)
    run = run_l4([red_step()], sandbox={"mode": "auto"})
    assert run.code == 3 and run.adapter.requests == []


# --- the local preflight (local-run-preflight 2.1: L4-SEC-041, L4-YOLO-093) ---------------------------------------


def _without_bwrap(monkeypatch):
    monkeypatch.setattr("l4.sandbox.select.resolve_tool", lambda *a, **k: None)


def _nothing_else_runs(monkeypatch, *names, module="l4.orchestrator"):
    def refuse(name):
        def called(*a, **k):
            raise AssertionError(f"{name} ran before the sandbox check")

        return called

    for name in names:
        monkeypatch.setattr(f"{module}.{name}", refuse(name))


def _only_main(run):
    return run.raw(run.tdd.origin, "for-each-ref", "--format=%(refname)").split() == ["refs/heads/main"]


def test_scn_sec_107_a_local_run_without_a_sandbox_touches_nothing(run_l4, tdd_repo, monkeypatch, capsys):
    _without_bwrap(monkeypatch)
    _nothing_else_runs(monkeypatch, "refresh_refs", "discover", "perform_follow_ups", "yolo_step", "acquire_for_run")
    before = set(tdd_repo.cache.rglob("*")) if tdd_repo.cache.exists() else set()
    run = run_l4([red_step()], sandbox={"mode": "auto"})
    assert run.code == 3 and run.adapter.requests == []
    assert "bubblewrap" in capsys.readouterr().err
    assert _only_main(run)  # no lease ref, no unit branch
    assert (set(tdd_repo.cache.rglob("*")) if tdd_repo.cache.exists() else set()) == before  # no worktree, no lock
    assert run.outcome["units"] == []  # no unit was run or listed


def test_scn_sec_107_the_same_run_with_no_unit_named_refuses_too(run_l4, tdd_repo, monkeypatch):
    _without_bwrap(monkeypatch)
    _nothing_else_runs(monkeypatch, "refresh_refs", "discover", "yolo_step")
    run = run_l4([red_step()], unit=False, sandbox={"mode": "auto"})
    assert run.code == 3 and _only_main(run)


def test_scn_sec_108_on_macos_the_message_names_the_ways_out(run_l4, monkeypatch, capsys):
    _without_bwrap(monkeypatch)
    monkeypatch.setattr("l4.sandbox.select.sys", types.SimpleNamespace(platform="darwin"))
    assert run_l4([red_step()], sandbox={"mode": "auto"}).code == 3
    err = capsys.readouterr().err
    assert "no sandbox for `l4 run`" in err and "Linux machine or VM with bubblewrap" in err
    assert "`l4 ci start`" in err and "`l4 retry` for a halted or escalated unit" in err
    assert "sandbox.mode: container" in err


def test_scn_sec_109_l4_verify_refuses_the_same_way(tdd_repo, monkeypatch, capsys):
    _without_bwrap(monkeypatch)
    monkeypatch.setattr("l4.sandbox.select.sys", types.SimpleNamespace(platform="darwin"))
    _nothing_else_runs(monkeypatch, "select_runnable", "run_unit_in_worktree", module="l4.verifier.ladder")
    tdd_repo.write_config(sandbox={"mode": "auto"})
    argv = ["verify", "--unit", UNIT, "--repo", str(tdd_repo.repo)]
    assert main(argv, environ=tdd_repo.environ) == 3  # not 2 ("only an implemented unit can be verified")
    err = capsys.readouterr().err
    assert "bubblewrap" in err and "no sandbox for `l4 verify`" in err


def test_scn_yolo_255_in_a_ci_job_the_check_stays_where_it_is(run_l4, tdd_repo, monkeypatch):
    """In a job the run starts (lease, worktree, `run.started`) and then fails to select a sandbox, which is what a
    plan reads as `setup_failed`."""
    _without_bwrap(monkeypatch)
    tdd_repo.environ.update(
        {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "acme/widgets", "L4_FORGE_TOKEN": "ghp_" + "x" * 36}
    )
    run = run_l4([red_step()], sandbox={"mode": "auto"})
    assert run.code == 3 and run.adapter.requests == []
    assert run.local_events("run.started") != [] or run.events("run.started") != []


def test_ci_true_alone_is_not_a_job_so_the_local_check_applies(run_l4, tdd_repo, monkeypatch):
    _without_bwrap(monkeypatch)
    _nothing_else_runs(monkeypatch, "refresh_refs", "acquire_for_run")
    tdd_repo.environ["CI"] = "true"
    assert run_l4([red_step()], sandbox={"mode": "auto"}).code == 3


def test_mode_none_with_allow_none_still_runs_locally(run_l4):
    assert run_l4([red_step(), green_step()]).code == 0
