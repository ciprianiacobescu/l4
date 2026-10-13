"""A scenario world for the operator commands (L4-OPS-001..004): the `openspec-basic` fixture with a bare remote, a
unit that `failing_reds` halts, and helpers that stamp the stops the sim cannot reach cheaply (an escalation, a wait
for capacity) as a harness commit with crafted ledger events, and a person's push to the unit branch."""

from datetime import UTC, datetime
from itertools import count

import pytest
import yaml

from l4.orchestrator import run_command
from l4.redact import Redactor
from l4.sim.builtin.manifest import scenario_text
from l4.sim.fakes import ProfileRouter, fake_openspec_cli
from l4.sim.remote import SimRepo
from l4.sim.runner import CONFIG_FILE, _events, scripted_agents, sim_app, sim_config, sim_environment
from l4.sim.scenarios import load_scenario
from l4.state.ledger import LedgerWriter
from l4.vcs.git import BOT_IDENTITY, Git
from l4.vcs.trailers import CommitTrailers

UNIT = "openspec:add-greeting"
NAME = "add-greeting"
BRANCH = "l4/openspec/add-greeting"
UNIT_REL = "openspec/changes/add-greeting"
_STAMPS = count(1)


def happy():
    return load_scenario(scenario_text("happy-openspec"), source="happy-openspec.yaml")


def failing_reds():
    """Three red steps that add no test: `max_task_attempts` is reached and the breaker halts the unit."""
    scenario = happy()
    steps = scenario.profiles["implementer"].steps
    dud = steps[0].model_copy(update={"write": {}})
    scenario.profiles["implementer"].steps = [dud, dud, dud]
    return scenario


@pytest.fixture
def world(tmp_path):
    sim = SimRepo.create("openspec-basic", root=tmp_path / "world")
    root = sim.root.resolve()
    (root / CONFIG_FILE).write_text(yaml.safe_dump(sim_config(happy())), encoding="utf-8")
    app = sim_app(root)
    remote = Git(sim.remote, environ=sim_environment(root))

    def run(scenario):
        with fake_openspec_cli():
            return run_command(sim_app(root), adapters={"fake": ProfileRouter(scripted_agents(scenario))})

    world = type("World", (), {})()
    world.sim, world.app, world.remote, world.run = sim, app, remote, run
    return world


def events(remote: Git) -> list[dict]:
    """The unit branch's ledger plus the pending ledger of its lock ref, as `l4 status` folds them."""
    return _events(remote, UNIT, UNIT_REL, "l4/")


def fetch(world) -> None:
    """The operator's `l4 retry` fetches the unit branches itself; a test that moved the remote behind its back does the
    same before it calls the library function."""
    Git(world.app.repo, environ=world.app.environ).run("fetch", "--quiet", "origin", "--prune")


def stamp(world, *rows: tuple[str, dict]) -> str:
    """A harness commit (bot author and committer, `L4-Run` trailer) on the unit branch whose ledger file holds `rows`
    after `run.started`: the stop or the park that the test needs, in the shape the fold reads."""
    n = next(_STAMPS)
    run_id = f"r-{datetime.now(UTC):%Y%m%dT%H%M}Z-{n:04x}"
    stage = world.sim.root / f"stage-{n}"
    git = Git(world.sim.root, environ=world.app.environ).at(world.sim.root)
    git.run("clone", "--quiet", "--branch", BRANCH, str(world.sim.remote), str(stage))
    inside = git.at(stage)
    now = datetime.now(UTC)  # later than the runs before it, earlier than the run after it: the fold sorts by time
    writer = LedgerWriter.open(stage / UNIT_REL, UNIT, run_id, redactor=Redactor({}), clock=lambda: now)
    for kind, data in rows:
        writer.append(kind, **data)
    writer.finish(0)
    inside.run("add", "-A")
    inside.commit(f"chore({NAME}): stamp [skip ci]", CommitTrailers(UNIT, run_id, 9, "verifying"), BOT_IDENTITY)
    inside.run("push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}")
    sha = inside.rev_parse("HEAD")
    fetch(world)
    return sha


def escalate(world, *, reason: str = "fix_rounds_exhausted", detail: str = "fix rounds used 3/3", spawned: int = 0):
    """The unit is `escalated` from `verifying` (after `spawned` fix units that count against the limit)."""
    rows = [("fix.spawned", {"fix_unit": f"{NAME}-fix-{i}", "round": i}) for i in range(1, spawned + 1)]
    rows.append(
        ("phase.changed", {"from": "verifying", "to": "escalated", "trigger": "verify_fail_exhausted",
                           "exit_code": 13, "reason": reason, "detail": detail})
    )  # fmt: skip
    return stamp(world, *rows)


def person_pushes(world, files: dict[str, str], message: str = "a person's change") -> str:
    """A person pushes `files` (paths from the repository root) to the unit branch."""
    sha = world.sim.human_commit(files, message, BRANCH)
    fetch(world)
    return sha
