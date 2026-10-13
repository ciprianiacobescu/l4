# ruff: noqa: F811
"""`l4 restart` (L4-OPS-004, SCN-OPS-08, SCN-OPS-09): the old head is kept as a ref, the unit starts over from the base
with the old folder, the branch is replaced under a lease, and the old merge request is closed."""

import pytest

from l4.cli import main
from l4.config.defaults import cache_root
from l4.config.redaction import load_app_config
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import ForgeUnavailable
from l4.forge.local import LocalForge
from l4.planner import facts_of, next_action
from l4.specs.providers import providers_for
from l4.state import restart as restart_module
from l4.state.restart import restart_unit
from l4.state.status import load_snapshot, select_runnable
from l4.vcs.git import Git
from l4.vcs.locks import LocalFileLease
from l4.vcs.names import UnitNames

from .ops_world import (  # noqa: F401
    BRANCH,
    NAME,
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

ATTEMPTS = "refs/l4/attempts/openspec/add-greeting"
SPEC = f"{UNIT_REL}/specs/greeting/spec.md"


@pytest.fixture
def forge(monkeypatch):
    """The forge `restart` builds: one local forge that the test can read afterwards."""
    local = LocalForge()
    monkeypatch.setattr(restart_module, "make_forge", lambda *a, **k: local)
    monkeypatch.setattr("l4.state.retry.make_forge", lambda *a, **k: local)  # the run start of the command
    return local


def restart(world, **kwargs):
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), UNIT)
    kwargs.setdefault("reason", "start over")
    return restart_unit(app, cfg, git, provider, ref, **kwargs)


def remote_ref(world, ref: str) -> str | None:
    return world.remote.rev_parse(ref)


def blob(world, ref: str, path: str) -> str | None:
    done = world.remote.run("show", f"{ref}:{path}", check=False)
    return done.stdout if done.returncode == 0 else None


def open_pr(forge):
    return forge.create_pr(BRANCH, "main", "add-greeting", "body")


def poisoned(world, forge):
    """An escalated unit, with a merge request, whose branch has a person's correction to the requirements."""
    assert world.run(happy()).code == ExitCode.OK
    escalate(world, spawned=3)
    person_pushes(world, {SPEC: "## ADDED Requirements\n### Requirement: corrected\n"})
    return open_pr(forge)


def test_a_poisoned_unit_starts_over_with_the_corrected_spec(world, forge):
    """SCN-OPS-08."""
    pr = poisoned(world, forge)
    old = remote_ref(world, f"refs/heads/{BRANCH}")
    result = restart(world, by="alex", signal="label:3")
    assert (result.attempt, result.previous_head, result.attempt_ref) == (1, old, f"{ATTEMPTS}/1")
    assert result.closed_pr == pr.number and result.branch_head == remote_ref(world, f"refs/heads/{BRANCH}")
    assert remote_ref(world, f"{ATTEMPTS}/1") == old
    assert forge.get_pr(pr.number).state == "closed"
    [comment] = forge.comments(pr.number)
    assert f"{ATTEMPTS}/1" in comment and "start over" in comment
    new = result.branch_head
    assert "corrected" in blob(world, new, SPEC)
    assert "[x]" not in blob(world, new, f"{UNIT_REL}/tasks.md")  # the base's boxes: none done
    assert blob(world, new, f"{UNIT_REL}/verification.md") is None
    files = world.remote.run("ls-tree", "-r", "--name-only", new, "--", f"{UNIT_REL}/.l4").stdout.split()
    assert len(files) == 1 and files[0].startswith(f"{UNIT_REL}/.l4/ledger/")  # no evidence, one new ledger file
    subject = world.remote.run("log", "-1", "--format=%s", new).stdout.strip()
    assert subject == f"chore({NAME}): restart, attempt 1 [skip ci]"
    assert world.remote.run("rev-list", "--count", f"refs/heads/main..{new}").stdout.strip() == "1"
    [restarted] = [e for e in events(world.remote) if e["type"] == "unit.restarted"]
    assert (restarted["attempt"], restarted["previous_head"], restarted["reason"]) == (1, old, "start over")
    assert (restarted["by"], restarted["signal"]) == ("alex", "label:3")
    assert [e["type"] for e in events(world.remote)] == ["run.started", "unit.restarted", "run.finished"]


def test_the_plan_of_a_restarted_unit_is_implement(world, forge):
    poisoned(world, forge)
    restart(world)
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), UNIT)
    snapshot = load_snapshot(provider, git, ref, branch_prefix=cfg.forge.branch_prefix)
    assert snapshot.state.phase is None and snapshot.state.restarts == 1
    assert next_action(facts_of(snapshot))[0] == "implement"


def test_the_task_boxes_are_the_base_branchs_and_a_task_the_base_lacks_is_open(world, forge):
    assert world.run(happy()).code == ExitCode.OK
    tasks = f"{UNIT_REL}/tasks.md"
    old = blob(world, f"refs/heads/{BRANCH}", tasks)
    assert "[x]" in old
    person_pushes(world, {tasks: old + "- [x] 3.1 A task that only the branch has\n"})
    restart(world)
    after = blob(world, f"refs/heads/{BRANCH}", tasks)
    assert "[x]" not in after and "3.1 A task that only the branch has" in after and "- [ ] 3.1 A task" in after


def test_a_second_restart_is_attempt_two_and_the_lock_ref_is_kept_under_the_attempt(world, forge):
    poisoned(world, forge)
    first = restart(world)
    head = remote_ref(world, f"refs/heads/{BRANCH}")
    world.remote.run("update-ref", f"refs/l4/locks/openspec/{NAME}", head)  # a pending ledger the old run left
    second = restart(world, reason="again")
    assert (first.attempt, second.attempt) == (1, 2)
    assert remote_ref(world, f"{ATTEMPTS}/2") == head and remote_ref(world, f"{ATTEMPTS}/2-locks") == head
    assert remote_ref(world, f"refs/l4/locks/openspec/{NAME}") is None
    assert remote_ref(world, f"{ATTEMPTS}/1") == first.previous_head


def test_a_person_pushing_during_the_restart_wins(world, forge, monkeypatch):
    """SCN-OPS-09: the lease fails, the restart exits 1, and the merge request and the branch stay as they were."""
    pr = poisoned(world, forge)
    old = remote_ref(world, f"refs/heads/{BRANCH}")
    real = Git.replace_branch
    pushed = {}

    def late_push(self, remote, branch, expected, **kwargs):
        pushed["head"] = world.sim.human_commit({"NOTES.md": "mine\n"}, "a person's late push", BRANCH)
        return real(self, remote, branch, expected, **kwargs)

    monkeypatch.setattr(Git, "replace_branch", late_push)
    with pytest.raises(L4Exit, match="the branch moved: run l4 restart again") as caught:
        restart(world)
    assert caught.value.code == ExitCode.INTERNAL_ERROR
    assert remote_ref(world, f"refs/heads/{BRANCH}") == pushed["head"] != old
    assert forge.get_pr(pr.number).state == "open" and forge.comments(pr.number) == []
    assert remote_ref(world, f"{ATTEMPTS}/1") == old  # the attempts ref is history: it may stay


def test_an_abandoned_unit_can_be_restarted_and_its_closed_merge_request_is_left(world, forge):
    assert world.run(failing_reds()).code == ExitCode.HALTED
    stamp(world, ("phase.changed", {"from": "halted", "to": "abandoned", "trigger": "pr_closed"}))
    pr = open_pr(forge)
    forge.close_pr(pr.number, "closed by a person")
    result = restart(world)
    assert result.attempt == 1 and result.closed_pr is None
    assert forge.comments(pr.number) == ["closed by a person"]


def test_a_restart_after_the_branch_was_deleted_creates_it_from_the_base(world, forge):
    assert world.run(failing_reds()).code == ExitCode.HALTED
    pr = open_pr(forge)
    world.remote.run("update-ref", "-d", f"refs/heads/{BRANCH}")
    Git(world.app.repo, environ=world.app.environ).run("fetch", "--quiet", "--prune", "origin")
    result = restart(world)
    assert result.previous_head is None and result.attempt_ref is None and result.attempt == 1
    assert remote_ref(world, f"refs/heads/{BRANCH}") == result.branch_head
    assert world.remote.run("for-each-ref", ATTEMPTS).stdout == ""
    assert blob(world, result.branch_head, f"{UNIT_REL}/proposal.md") is not None  # the folder of the base
    assert forge.get_pr(pr.number).state == "closed"


# --- step 1: the refusals, before anything is written ---------------------------------------------------------------


def refs_of(world) -> str:
    return world.remote.run("for-each-ref", "--format=%(refname) %(objectname)").stdout


def test_an_unstarted_unit_is_refused(world, forge):
    before = refs_of(world)
    with pytest.raises(L4Exit, match=f"restart: {UNIT} is not started") as caught:
        restart(world)
    assert caught.value.code == ExitCode.USAGE_ERROR and refs_of(world) == before


def test_a_merged_unit_is_refused(world, forge, monkeypatch):
    world.run(happy())
    real = restart_module.load_snapshot

    def merged(*args, **kwargs):
        snapshot = real(*args, **kwargs)
        state = snapshot.state.model_copy(update={"phase": "merged"})
        return snapshot.__class__(**{**snapshot.__dict__, "state": state})

    monkeypatch.setattr(restart_module, "load_snapshot", merged)
    before = refs_of(world)
    with pytest.raises(L4Exit, match=f"restart: {UNIT} is merged") as caught:
        restart(world)
    assert caught.value.code == ExitCode.USAGE_ERROR and refs_of(world) == before


def test_a_locked_unit_is_refused(world, forge):
    world.run(failing_reds())
    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=cache_root(world.app.environ, repo=world.app.repo))
    lease = LocalFileLease(names.flock_path, unit=UNIT, run_id="r-20261013T1000Z-aaaa")
    lease.acquire()
    before = refs_of(world)
    try:
        with pytest.raises(L4Exit, match=f"restart: {UNIT} is locked by another run") as caught:
            restart(world)
    finally:
        lease.release()
    assert caught.value.code == ExitCode.USAGE_ERROR and refs_of(world) == before


def test_no_forge_token_is_refused(world, monkeypatch):
    world.run(failing_reds())

    def unavailable(*args, **kwargs):
        raise ForgeUnavailable("GITHUB_TOKEN is not set")

    monkeypatch.setattr(restart_module, "make_forge", unavailable)
    before = refs_of(world)
    with pytest.raises(L4Exit, match="restart: .*GITHUB_TOKEN is not set") as caught:
        restart(world)
    assert caught.value.code == ExitCode.USAGE_ERROR and refs_of(world) == before


# --- the command ---------------------------------------------------------------------------------------------------


def test_the_command_restarts_and_starts_a_run(world, forge, capsys):
    poisoned(world, forge)
    forge.script_start_run("started")
    argv = ["restart", "--unit", UNIT, "--reason", "start over", "--repo", str(world.app.repo)]
    argv += ["--config", str(world.app.config_path)]
    assert main(argv, environ=dict(world.app.environ)) == 0
    out = capsys.readouterr().out
    assert "restarted attempt 1" in out and "run started on main" in out
    assert forge.called("start_run")[0].args == ("main",)
    assert remote_ref(world, f"{ATTEMPTS}/1") is not None


def test_no_run_starts_nothing(world, forge, capsys):
    poisoned(world, forge)
    argv = ["restart", "--unit", UNIT, "--reason", "start over", "--no-run", "--repo", str(world.app.repo)]
    argv += ["--config", str(world.app.config_path)]
    assert main(argv, environ=dict(world.app.environ)) == 0
    assert forge.called("start_run") == [] and "run started" not in capsys.readouterr().out
