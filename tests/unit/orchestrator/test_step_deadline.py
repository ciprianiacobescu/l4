"""The step deadline end to end (L4-IMP-066 to L4-IMP-069): a real `l4 run` of the fixture unit with the fake agent."""

import json
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from l4 import deadline, orchestrator
from l4.agents.fake import Step
from l4.redact import Redactor
from l4.state.ledger import LedgerWriter

from ..implementer.conftest import IMPL, blocked_step, green_step, red_step, result
from .conftest import BRANCH, UNIT, UNIT_DIR
from .test_fallback import TWO, limited
from .test_reentry import CLARIFIER_ROLE

BUDGET = {"L4_JOB_TIMEOUT_MINUTES": "180", "L4_JOB_STARTED_AT": "2025-12-31T23:50:00Z"}
MARGIN_S = 1200  # the default `ci.soft_deadline_margin`


def budget(tdd_repo, fake_clock, left_at_start: float) -> None:
    """The job's budget (180 minutes) and its start, so that `left_at_start` seconds of soft time are left when the
    run starts, on the fake clock as it is now."""
    elapsed = 180 * 60 - MARGIN_S - left_at_start
    tdd_repo.environ["L4_JOB_TIMEOUT_MINUTES"] = "180"
    started = fake_clock.now() - timedelta(seconds=elapsed)
    tdd_repo.environ["L4_JOB_STARTED_AT"] = started.strftime("%Y-%m-%dT%H:%M:%SZ")


def no_budget(tdd_repo) -> None:
    tdd_repo.environ.pop("L4_JOB_TIMEOUT_MINUTES", None)
    tdd_repo.environ.pop("L4_JOB_STARTED_AT", None)


def advance(fake_clock, seconds: float):
    """A step lever: the fake agent "works" for `seconds` on the fake clock."""
    return lambda req: fake_clock.advance(timedelta(seconds=seconds))


def fire(req) -> None:
    deadline.current().fire()


def run_ids(run) -> set[str]:
    """The ids of the runs the unit's ledger holds now: take them right after an earlier run."""
    return {e["run_id"] for e in run.ledger()}


def new_events(run, old: set[str], event_type: str | None = None) -> list[dict]:
    """The events of the runs that are not in `old`."""
    return [e for e in run.ledger() if e["run_id"] not in old and (event_type is None or e["type"] == event_type)]


def seed_timed(tdd_repo, raw, rows: list[tuple[str, float]]) -> None:
    """Earlier `step.timed` records on the unit's branch, as an earlier run of the unit would have left them."""
    clone = tdd_repo.repo.parent / "seed-clone"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    writer = LedgerWriter.open(clone / UNIT_DIR, UNIT, "r-20251231T0000Z-5eed", redactor=Redactor({}))
    for phase, seconds in rows:
        extra = {"round": 1} if phase == "verify" else {"task": "1.1", "attempt": 1}
        writer.append("step.timed", phase=phase, seconds=seconds, **extra)
    writer.finish(0)
    raw(clone, "add", "-A")
    raw(clone, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "seed the step records")
    raw(clone, "push", "-q", "origin", BRANCH)


@pytest.fixture(autouse=True)
def no_token_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("l4.config.preflight.require_token_in_ci", lambda cfg, environ: None)


def test_run_started_records_the_job_budget_and_start(run_l4, tdd_repo, fake_clock):
    """SCN-IMP-334: `job_timeout_s` is the budget before the margin; neither key without a budget."""
    tdd_repo.environ.update(BUDGET)
    run = run_l4([red_step(), green_step()])
    started = run.events("run.started")[0]
    assert started["job_timeout_s"] == 10800
    assert started["job_started_at"] == "2025-12-31T23:50:00Z"
    assert run.code == 0


def test_run_started_has_neither_key_without_a_budget(run_l4, tdd_repo, fake_clock):
    run = run_l4([red_step(), green_step()])
    started = run.events("run.started")[0]
    assert "job_timeout_s" not in started and "job_started_at" not in started


def test_run_started_has_the_budget_but_no_start_when_the_start_is_unknown(run_l4, tdd_repo, fake_clock):
    tdd_repo.environ["L4_JOB_TIMEOUT_MINUTES"] = "180"
    run = run_l4([red_step(), green_step()])
    started = run.events("run.started")[0]
    assert started["job_timeout_s"] == 10800 and "job_started_at" not in started


# --- before each step: the estimate, the hand-back (L4-IMP-067, L4-IMP-069) --------------------------------------


def test_a_green_that_does_not_fit_is_not_started(run_l4, tdd_repo, fake_clock):
    """SCN-IMP-335 and SCN-IMP-342: the red took 1410 s and ended at minute 155; 300 s of soft time are left."""
    budget(tdd_repo, fake_clock, left_at_start=180 * 60 - MARGIN_S - (155 * 60 - 1410))
    run = run_l4([red_step(on_start=advance(fake_clock, 1410)), green_step()])
    assert len(run.adapter.requests) == 1  # the green is never requested from the adapter
    [reached] = run.events("deadline.reached")
    assert reached["when"] == "before" and reached["phase"] == "green" and reached["task"] == "1.1"
    assert reached["left_s"] == 300 and reached["estimate_s"] == 1410 and reached["first"] is False
    want = "soft deadline: task 1.1 green not started (300 s left, step estimated 1410 s); the next run continues it"
    assert run.outcome["units"][0]["exit_reason"] == want
    assert run.code == 10
    [timed] = run.events("step.timed")
    assert (timed["phase"], timed["task"], timed["attempt"], timed["seconds"]) == ("red", "1.1", 1, 1410)


def test_the_hand_back_is_pushed_and_exits_10(run_l4, tdd_repo, fake_clock):
    """SCN-IMP-342: the unit stays `implementing`; origin holds the ledger of the hand-back; no failed attempt."""
    budget(tdd_repo, fake_clock, left_at_start=1700)
    run = run_l4([red_step(on_start=advance(fake_clock, 1410)), green_step()])
    assert run.code == 10
    assert run.outcome["units"][0]["phase_after"] == "implementing"
    types = [e["type"] for e in run.branch_ledger()]
    assert "deadline.reached" in types and "lock.released" in types
    [finished] = [e for e in run.branch_ledger() if e["type"] == "run.finished"]
    assert finished["exit_code"] == 10 and finished["reason"].startswith("soft deadline:")
    assert "task.attempt_failed" not in types
    assert types.index("deadline.reached") < types.index("lock.released") < types.index("run.finished")
    assert run.events("phase.changed")[-1]["to"] == "implementing"


def test_the_next_run_continues_at_green(run_l4, tdd_repo, fake_clock):
    """SCN-IMP-343: one red commit, one green commit, and the green run has no second red."""
    budget(tdd_repo, fake_clock, left_at_start=1700)
    first = run_l4([red_step(on_start=advance(fake_clock, 1410)), green_step()])
    assert first.code == 10
    no_budget(tdd_repo)
    second = run_l4([green_step()])
    assert second.code == 0
    assert len(second.adapter.requests) == 1  # only the green
    kinds = [s.split("(")[0] for s in second.subjects() if not s.startswith("chore")]
    assert kinds == ["test", "feat"]


def test_the_first_step_of_a_run_always_starts(run_l4, tdd_repo, fake_clock):
    """SCN-IMP-336: 400 s left and a recorded red of 1800 s; the unit's first step starts."""
    budget(tdd_repo, fake_clock, left_at_start=100000)
    first = run_l4([red_step(on_start=advance(fake_clock, 1800))])  # the script ends after the red
    assert first.events("step.timed")[0]["seconds"] == 1800
    old = run_ids(first)
    budget(tdd_repo, fake_clock, left_at_start=400)
    second = run_l4([green_step()])
    assert second.code == 0 and len(second.adapter.requests) == 1
    assert not new_events(second, old, "deadline.reached")


@pytest.mark.parametrize(
    ("seeded", "left_at_start", "deferred", "estimate"),
    [([300, 5000], 3000, True, 3600), ([120], 1000, False, 600)],
    ids=["the cap", "the floor"],
)
def test_the_estimate_reads_the_units_recorded_steps(
    run_l4, tdd_repo, raw, fake_clock, seeded, left_at_start, deferred, estimate
):
    """SCN-IMP-337: the red of 200 s was measured in this run; the green is the run's second step."""
    run_l4([])  # leaves the unit's branch with a ledger and no commit of a step
    seed_timed(tdd_repo, raw, [("green", float(s)) for s in seeded])
    budget(tdd_repo, fake_clock, left_at_start=left_at_start)
    run = run_l4([red_step(on_start=advance(fake_clock, 200)), green_step()])
    reached = run.events("deadline.reached")
    if deferred:
        assert len(run.adapter.requests) == 1 and run.code == 10
        assert reached[-1]["estimate_s"] == estimate and reached[-1]["phase"] == "green"
    else:
        assert run.code == 0 and not reached


def test_no_budget_no_check(run_l4, tdd_repo, fake_clock):
    """SCN-IMP-338."""
    no_budget(tdd_repo)
    run = run_l4([red_step(on_start=advance(fake_clock, 99999)), green_step()])
    assert run.code == 0 and len(run.adapter.requests) == 2
    assert not run.events("deadline.reached") and not run.events("step.timed")


def test_every_started_step_records_step_timed(run_l4, tdd_repo, fake_clock):
    budget(tdd_repo, fake_clock, left_at_start=100000)
    run = run_l4([red_step(on_start=advance(fake_clock, 100)), green_step(on_start=advance(fake_clock, 250))])
    assert run.code == 0
    timed = [(e["phase"], e["task"], e["attempt"], e["seconds"]) for e in run.events("step.timed")]
    assert timed == [("red", "1.1", 1, 100), ("green", "1.1", 1, 250)]


def test_a_resumed_green_is_checked_before_its_baseline(run_l4, tdd_repo, fake_clock, monkeypatch):
    """SCN-IMP-360, first part: a committed red, 300 s left, and the run's first step already taken."""
    first = run_l4([red_step()])  # the red commit and its `task.red_ok`; the script ends before the green
    old = run_ids(first)
    budget(tdd_repo, fake_clock, left_at_start=300)
    real = orchestrator.run_unit_in_worktree

    def after_another_step(*args, **kwargs):
        deadline.current().started = 1  # a unit ran before this one in the run
        return real(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "run_unit_in_worktree", after_another_step)
    second = run_l4([green_step()])
    assert second.code == 10 and not second.adapter.requests
    assert not new_events(second, old, "task.red_resumed")
    assert not [e for e in new_events(second, old, "gate.finished") if e["name"] == "baseline"]
    [reached] = new_events(second, old, "deadline.reached")
    assert reached["when"] == "before" and reached["phase"] == "green" and reached["left_s"] == 300


def test_a_step_after_a_fall_back_is_checked(run_l4, tdd_repo, fake_clock):
    """SCN-IMP-360, second part: a green hits a usage limit with 300 s left; the next profile's `run_task` is
    deferred before it runs a gate."""
    budget(tdd_repo, fake_clock, left_at_start=2000)
    run = run_l4(
        [red_step(on_start=advance(fake_clock, 100)), limited(on_start=advance(fake_clock, 1600)), green_step()], **TWO
    )
    assert run.code == 10 and len(run.adapter.requests) == 2  # the third step is never requested
    [reached] = run.events("deadline.reached")
    assert reached["when"] == "before" and reached["phase"] == "green" and reached["left_s"] == 300
    types = [e["type"] for e in run.ledger()]
    after_limit = types[types.index("availability.fallback") :]
    assert "gate.finished" not in after_limit and "task.red_resumed" not in after_limit


def test_a_resumed_red_without_red_ok_runs_red_under_one_mark(run_l4, tdd_repo, raw, fake_clock):
    """The top check marks green (the branch holds the red commit), `resume_red` finds no `task.red_ok` for it, and
    the loop's red check replaces the mark: the first `step.timed` is the red's."""
    first = run_l4([red_step()])
    old = run_ids(first)
    clone = tdd_repo.repo.parent / "edit-clone"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    for path in (clone / UNIT_DIR / ".l4" / "ledger").glob("*.jsonl"):
        edited = []
        for line in path.read_text().splitlines():
            body = json.loads(line)
            if body["type"] == "task.red_ok":
                body["base"] = "0" * 40  # the record no longer matches the red commit's parent
            edited.append(json.dumps(body))
        path.write_text("\n".join(edited) + "\n")
    raw(clone, "add", "-A")
    raw(clone, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "break the red record")
    raw(clone, "push", "-q", "origin", BRANCH)
    budget(tdd_repo, fake_clock, left_at_start=100000)
    second = run_l4([red_step()])
    timed = new_events(second, old, "step.timed")
    assert timed and timed[0]["phase"] == "red" and timed[0]["attempt"] == 1
    assert not new_events(second, old, "task.red_resumed")


def test_a_verification_round_that_does_not_fit_is_not_started(run_l4, tdd_repo, raw, fake_clock, install_hooks):
    """SCN-IMP-361: a recorded round of 7000 s, 6800 s left, and the round is not the run's first step."""
    run_l4([])
    seed_timed(tdd_repo, raw, [("verify", 7000.0)])

    def verify(ctx):
        raise AssertionError("the round must not start")

    install_hooks(verify=verify)
    budget(tdd_repo, fake_clock, left_at_start=6900)
    run = run_l4([red_step(on_start=advance(fake_clock, 50)), green_step(on_start=advance(fake_clock, 50))])
    assert run.code == 10
    [reached] = run.events("deadline.reached")
    assert reached["when"] == "before" and reached["phase"] == "verify" and reached["round"] == 1
    assert reached["left_s"] == 6800 and reached["estimate_s"] == 7000
    assert run.outcome["units"][0]["phase_after"] == "verifying"
    assert run.outcome["units"][0]["exit_reason"].startswith("soft deadline: round 1 verify not started")


# --- a step stopped at the deadline (L4-IMP-068, L4-IMP-069) ------------------------------------------------------


def test_an_agent_stopped_at_the_deadline_is_handed_back(run_l4, tdd_repo, fake_clock, raw):
    """SCN-IMP-339 end to end: the red is the run's first step, the green is stopped, its half-written file is lost."""
    budget(tdd_repo, fake_clock, left_at_start=100000)
    run = run_l4(
        [
            red_step(on_start=advance(fake_clock, 100)),
            Step(writes={"src/pytdd/pricing.py": IMPL, "half.txt": "x"}, structured=result("green"), on_start=fire),
        ],
    )
    assert run.code == 10
    assert not raw(tdd_repo.origin, "log", "--format=%H", BRANCH, "--", "half.txt").strip()
    assert "half.txt" not in raw(tdd_repo.origin, "ls-tree", "-r", "--name-only", BRANCH)
    assert [e["status"] for e in run.events("step.finished") if e["phase"] == "green"] == ["deadline"]
    [reached] = run.events("deadline.reached")
    assert (reached["when"], reached["during"], reached["phase"], reached["task"], reached["attempt"]) == (
        "during", "agent", "green", "1.1", 1,
    )  # fmt: skip
    assert reached["first"] is False and reached["ran_s"] == 0 and reached["estimate_s"] == 600
    assert reached["left_at_start_s"] > 0 and "round" not in reached and "gate" not in reached
    assert not run.events("task.attempt_failed") and not run.events("agent.idle")
    assert run.outcome["units"][0]["exit_reason"] == (
        "soft deadline: task 1.1 green stopped (agent); the next run runs it again"
    )
    assert run.outcome["units"][0]["phase_after"] == "implementing"


def _fire_on(marker: Path) -> threading.Thread:
    """Fire the run's deadline as soon as a real gate (a child process) has written `marker`."""

    def go() -> None:
        end = time.monotonic() + 60
        while not marker.exists() and time.monotonic() < end:
            time.sleep(0.02)
        while deadline.current() is None and time.monotonic() < end:
            time.sleep(0.02)
        current = deadline.current()
        if current is not None:
            current.fire()

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    return thread


def test_a_gate_stopped_at_the_deadline_is_handed_back(run_l4, tdd_repo, fake_clock, tmp_path):
    """SCN-IMP-340 end to end: the red's test gate is a command that writes a marker and then sleeps."""
    marker, script = tmp_path / "gate-marker", tmp_path / "gate.py"
    script.write_text(f"import time\nopen({str(marker)!r}, 'w').close()\ntime.sleep(60)\n")
    budget(tdd_repo, fake_clock, left_at_start=100000)
    _fire_on(marker)
    run = run_l4([red_step()], test={"command": f"{sys.executable} {script}"})
    assert run.code == 10
    [reached] = run.events("deadline.reached")
    finished = run.events("gate.finished")
    assert finished and reached["when"] == "during" and reached["during"] == "gate"
    assert reached["gate"] == finished[-1]["name"] and finished[-1]["status"] == "fail"
    assert (reached["phase"], reached["task"], reached["attempt"], reached["first"]) == ("red", "1.1", 1, True)
    assert not run.events("task.red_committed") and not run.events("task.attempt_failed")
    assert run.outcome["units"][0]["exit_reason"].startswith("soft deadline: task 1.1 red stopped (gate ")


def test_a_stopped_clarifier_records_the_units_phase(run_l4, tdd_repo, fake_clock, install_hooks):
    """SCN-IMP-363: a CLI clarifier stopped while no step is current: the unit's phase, no task, `first: false`."""
    from pathlib import Path as _Path

    from l4.agents.base import RunResult
    from l4.llm.agent_judge import AgentJudge

    class Stopped:
        def capabilities(self):
            return type("Caps", (), {"schema_mode": "native"})()

        def run(self, req) -> RunResult:
            return RunResult(status="cancelled", raw_events_path=_Path("/dev/null"))

    def clarify(ctx):
        deadline.current().fire()  # the deadline reaches the clarifier's call
        AgentJudge(Stopped(), lambda prompt, schema, timeout: object()).complete_structured("s", [], {"type": "object"})

    install_hooks(clarify=clarify)
    budget(tdd_repo, fake_clock, left_at_start=100000)
    run = run_l4([blocked_step()], roles=CLARIFIER_ROLE)
    assert run.code == 10
    [reached] = run.events("deadline.reached")
    assert reached["when"] == "during" and reached["during"] == "judge"
    assert reached["phase"] == "clarifying" and reached["first"] is False and "task" not in reached
    assert (
        run.outcome["units"][0]["exit_reason"]
        == "soft deadline: clarifying stopped (judge); the next run runs it again"
    )
    assert run.outcome["units"][0]["phase_after"] == "clarifying"


def test_a_stop_during_the_idle_grace_is_a_hand_back(run_l4, tdd_repo, fake_clock):
    """SCN-IMP-362 end to end: the step has gone idle and the deadline fires: no `agent.idle`, no attempt."""
    budget(tdd_repo, fake_clock, left_at_start=100000)
    run = run_l4([red_step(), green_step(idle_s=600, on_start=fire)])
    assert run.code == 10
    assert not run.events("agent.idle") and not run.events("task.attempt_failed")
    [reached] = run.events("deadline.reached")
    assert reached["during"] == "agent" and reached["phase"] == "green"
