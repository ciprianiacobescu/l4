from datetime import timedelta

from l4.agents.base import LimitSignal, ProbeResult
from l4.agents.fake import Step
from l4.state.lifecycle import Trigger
from l4.vcs.locks import LocalFileLease
from l4.vcs.names import UnitNames

from ..implementer.conftest import blocked_step, green_step, red_step, result
from .conftest import BRANCH, UNIT, UNIT_DIR, new_origin_main


def test_l4_run_stops_at_implemented_without_hooks(run_l4):
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    assert run.triggers() == ["unit_discovered_pending", "intake_all_pass", "lease_acquired", "all_leaves_done"]
    (unit,) = run.outcome["units"]
    assert (unit["phase_before"], unit["phase_after"], unit["tasks"]) == (
        "none",
        "implemented",
        {"done": 1, "total": 1},
    )
    assert unit["profiles"] == {"implementer": "impl"} and unit["iteration"] == 1
    assert [s.split("(")[0] for s in run.subjects()[:2]] == ["test", "feat"]  # red before green on the unit branch
    assert "- [x] 1.1" in run.pushed(f"{UNIT_DIR}/tasks.md")
    assert (
        run.raw(run.tdd.origin, "log", "-1", "--format=%an <%ae>", BRANCH).strip()
        == "l4-bot <l4-bot@users.noreply.invalid>"
    )


def test_a_stop_at_implemented_is_logged_and_the_ledger_records_the_run(run_l4, capsys):
    run = run_l4([red_step(), green_step()])
    assert "stopping at implemented (no verify hook" in capsys.readouterr().err
    types = [e["type"] for e in run.ledger()]
    assert types[0] == "run.started" and types[-1] == "run.finished"
    assert "lock.acquired" in types and "lock.released" in types
    assert [e["selected"] for e in run.events("availability.selected")] == ["impl"]
    assert run.events("sandbox.disabled")[0]["mode"] == "none"
    assert run.events("run.finished")[0]["exit_code"] == 0


def test_present_hooks_called_in_lifecycle_order(run_l4, install_hooks):
    calls: list[str] = []

    class Forge:
        push_config = (("credential.helper", ""),)

        def after_push(self, phase):
            calls.append(f"forge.after_push:{phase}")

    class Mirror:
        def sync(self, phase, notes=None):
            calls.append(f"mirror.sync:{phase}")

    install_hooks(
        forge=lambda ctx: calls.append("forge.build") or Forge(),
        mirror=lambda ctx: calls.append("mirror.build") or Mirror(),
        verify=lambda ctx: calls.append("verify") or Trigger.VERIFY_PASS,
        handoff=lambda ctx: calls.append("handoff"),
    )
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    assert calls == [
        "forge.build", "mirror.build",
        "mirror.sync:intake", "mirror.sync:ready", "mirror.sync:implementing",
        "forge.after_push:implementing", "mirror.sync:implementing",  # the red checkpoint
        "forge.after_push:implementing", "mirror.sync:implementing",  # the green checkpoint
        "mirror.sync:implemented",
        "mirror.sync:verifying", "verify", "mirror.sync:verified",
        "handoff", "mirror.sync:in_review",  # no push follows: the tail of the run goes to the lock ref
    ]  # fmt: skip
    assert run.triggers()[-3:] == ["verification_started", "verify_pass", "hand_off_pushed"]
    assert run.outcome["units"][0]["phase_after"] == "in_review"
    assert not any(s.startswith("chore(") for s in run.subjects())  # nothing is committed to the branch after H
    assert all("[skip ci]" in s for s in run.subjects() if s.startswith(("test(", "feat(")))


def test_busy_unit_skipped_exit_0(run_l4, tdd_repo):
    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=tdd_repo.cache)
    other = LocalFileLease(names.flock_path, unit=UNIT, run_id="r-20261003T0000Z-0000")
    other.acquire()
    try:
        run = run_l4([red_step()])
    finally:
        other.release()
    assert run.code == 0 and run.adapter.requests == []
    assert not names.worktree.exists()  # a busy unit's files are not touched
    (unit,) = run.outcome["units"]
    assert unit["phase_after"] == "none"


def test_final_ledger_lines_are_committed_and_pushed(run_l4):
    run = run_l4([red_step(), green_step()])
    assert run.subjects()[-1] == "chore(add-discount-codes): ledger [skip ci]"
    last = run.raw(run.tdd.origin, "log", "-1", "--format=%B", BRANCH)
    assert "L4-Unit: openspec:add-discount-codes" in last and "L4-Phase: implemented" in last
    finished = run.events("run.finished")
    assert len(finished) == 1 and finished[0]["seq"] == max(e["seq"] for e in run.ledger())
    # the file on the branch is byte-identical to the one in the worktree
    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=run.tdd.cache)
    (local,) = (names.worktree / UNIT_DIR / ".l4" / "ledger").glob("*.jsonl")
    assert run.pushed(f"{UNIT_DIR}/.l4/ledger/{local.name}") == local.read_text()


def test_a_blocked_task_exits_11_and_a_rerun_without_an_answer_does_nothing(run_l4):
    first = run_l4([blocked_step()])
    assert first.code == 11
    assert first.triggers()[-1] == "questions_blocking"
    assert "## Q-001: Which rounding?" in first.pushed(f"{UNIT_DIR}/questions.md")
    assert first.outcome["units"][0]["open_questions"] == ["Q-001"]
    assert "[ ] 1.1" in first.pushed(f"{UNIT_DIR}/tasks.md")
    triggers, probes = first.triggers(), len(first.events("availability.selected"))  # the ledger is read lazily
    second = run_l4([red_step(), green_step()])  # --unit does not force a re-entry
    assert second.code == 11 and second.adapter.requests == []
    assert (
        second.triggers()[-1] == "questions_blocking" and second.outcome["units"][0]["phase_after"] == "awaiting_human"
    )
    # not even a transition or a probe: the unit stayed in awaiting_human instead of flipping through implementing
    assert second.triggers() == triggers
    assert len(second.events("availability.selected")) == probes


def test_a_required_role_that_is_unavailable_exits_12_without_an_agent_call(run_l4):
    run = run_l4([red_step()], probes={"auth": ProbeResult("auth", False, reason="logged out")})
    assert run.code == 12 and run.adapter.requests == []
    assert [e["trigger"] for e in run.local_events("phase.changed")][-1] == "required_role_unavailable"
    assert run.outcome["units"][0]["phase_after"] == "waiting_capacity"
    # nothing was done, so no unit branch exists to freeze today's copy of the spec
    assert run.raw(run.tdd.origin, "for-each-ref", "--format=%(refname)").split() == ["refs/heads/main"]
    again = run_l4([red_step(), green_step()])  # the login is back
    assert again.code == 0 and again.outcome["units"][0]["phase_after"] == "implemented"


def test_a_role_lost_after_progress_parks_the_unit_on_its_branch(run_l4, fake_clock):
    limit = LimitSignal("codex", None, "usage_limit", None, "text", "You have hit your usage limit")
    run = run_l4([red_step(), Step(status="quota", limit=limit)])
    assert run.code == 12
    assert run.triggers()[-1] == "required_role_unavailable"
    assert run.events("availability.limit")[0]["kind"] == "usage_limit"
    assert run.outcome["units"][0]["phase_after"] == "waiting_capacity"
    fake_clock.advance(timedelta(minutes=31))  # the default cool-down of the limited profile is over
    again = run_l4([green_step()])  # capacity is back: the red checkpoint is resumed at green
    assert again.code == 0
    assert "capacity_restored" in again.triggers() and again.triggers()[-1] == "all_leaves_done"
    assert [s.split("(")[0] for s in again.subjects() if not s.startswith("chore")] == ["test", "feat"]


def test_halted_when_attempts_run_out_exits_13(run_l4):
    run = run_l4([Step(structured=result("red"))], implementer={"max_task_attempts": 1})
    assert run.code == 13
    assert run.triggers()[-1] == "breaker_or_budget"
    assert run.outcome["units"][0]["phase_after"] == "halted"
    assert run.events("breaker.tripped")[0]["reason"] == "max_task_attempts"


def test_a_unit_without_tasks_is_rejected_before_any_agent_call(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {f"{UNIT_DIR}/tasks.md": "# nothing to do\n"})
    run = run_l4([red_step()])
    assert run.code == 14 and run.adapter.requests == []
    assert run.outcome["units"][0]["phase_after"] == "none"


def test_deferred_flags_exit_2(run_l4):
    run = run_l4([], "--time-budget", "1h")
    assert run.code == 2 and run.adapter.requests == []


def _nothing_started(run, tdd_repo) -> None:
    """A config error is found before the lease, the worktree and any probe."""
    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=tdd_repo.cache)
    assert not names.flock_path.exists() and not names.worktree.exists()
    assert run.adapter.requests == []


def test_a_relative_credential_path_is_a_usage_error_before_anything_starts(run_l4, tdd_repo):
    sandbox = {"mode": "none", "allow_none": True, "credential_paths": {"codex": ["relative/dir"]}}
    run = run_l4([red_step(), green_step()], sandbox=sandbox)
    assert run.code == 2
    _nothing_started(run, tdd_repo)


def test_a_cache_path_outside_the_runner_cache_is_a_usage_error_before_anything_starts(run_l4, tdd_repo):
    caches = {"x": {"path": "/somewhere/else/cache", "env": "X_CACHE"}}
    run = run_l4([red_step(), green_step()], sandbox={"mode": "none", "allow_none": True, "caches": caches})
    assert run.code == 2
    _nothing_started(run, tdd_repo)


def _set_roles(tdd_repo, **roles) -> None:
    import yaml

    path = tdd_repo.repo / ".l4" / "config.yaml"
    path.parent.mkdir(exist_ok=True)
    body = yaml.safe_load(tdd_repo.config())
    body["roles"].update(roles)
    path.write_text(yaml.safe_dump(body))


def test_empty_role_chains_are_a_configuration_error_not_a_capacity_wait(tdd_repo, monkeypatch):
    from l4.agents.factory import ADAPTERS
    from l4.agents.fake import FakeAdapter
    from l4.cli import main

    for roles in ({"implementer": []}, {"judges": []}, {"implementer": ["ghost"]}):
        _set_roles(tdd_repo, **roles)
        adapter = FakeAdapter([red_step(), green_step()])
        monkeypatch.setitem(ADAPTERS, "fake", lambda adapter=adapter: adapter)
        code = main(["run", "--unit", UNIT, "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)
        assert code == 2, roles
        names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=tdd_repo.cache)
        assert not names.flock_path.exists() and not names.worktree.exists() and adapter.requests == []


def test_nothing_to_do_exits_0_before_any_lease_worktree_probe_or_agent(run_l4, tdd_repo, capsys):
    first = run_l4([blocked_step()])
    assert first.code == 11  # awaiting a human: no unit has a next step now
    runs, probes, branch_head = len(first.events("run.started")), len(first.events("availability.selected")), first.raw(
        tdd_repo.origin, "rev-parse", BRANCH
    )
    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=tdd_repo.cache)
    before = sorted(p.name for p in names.worktree.rglob("*.jsonl"))
    capsys.readouterr()
    second = run_l4([], unit=False)  # the routed CI job: `l4 run` without --unit
    assert second.code == 0 and second.adapter.requests == []
    assert "nothing to do" in capsys.readouterr().err
    assert second.outcome["units"] == []
    assert len(second.events("run.started")) == runs  # no run opened a ledger, so no lease was taken
    assert len(second.events("availability.selected")) == probes
    assert sorted(p.name for p in names.worktree.rglob("*.jsonl")) == before  # the worktree was not recreated
    assert second.raw(tdd_repo.origin, "rev-parse", BRANCH) == branch_head


def test_an_empty_plan_takes_no_lease_at_all_on_a_fresh_runner(run_l4, tdd_repo, raw):
    """No unit directory in the repository: the cache holds neither a worktree nor a lock file afterwards."""
    raw(tdd_repo.repo, "rm", "-rq", UNIT_DIR)
    (tdd_repo.repo / "openspec" / "changes").mkdir(parents=True)  # L4-DET-003: the framework stays, the units go
    (tdd_repo.repo / "openspec" / "changes" / ".gitkeep").write_text("")
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "no units")
    run = run_l4([], unit=False)
    assert run.code == 0 and run.adapter.requests == []
    assert not (tdd_repo.cache / "worktrees").exists() and not (tdd_repo.cache / "locks").exists()


def test_run_started_records_the_runner_and_the_tool_versions(run_l4, tdd_repo):
    tdd_repo.environ["CI_RUNNER_ID"] = "12"
    tdd_repo.environ["CI_RUNNER_DESCRIPTION"] = "runner-2"
    run = run_l4([red_step(), green_step()])
    [started] = run.events("run.started")
    assert started["runner"] == {"id": "12", "description": "runner-2"}
    assert started["tools"]["git"][0].isdigit() and "python" in started["tools"]
