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
from l4.vcs.repokey import repository_key

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

ATTEMPTS = "refs/l4/attempts/openspec/add-greeting"
SPEC = f"{UNIT_REL}/specs/greeting/spec.md"


@pytest.fixture
def forge(monkeypatch):
    """The forge `restart` builds: one local forge that the test can read afterwards."""
    local = LocalForge()
    monkeypatch.setattr(restart_module, "make_forge", lambda *a, **k: local)
    monkeypatch.setattr("l4.state.retry.make_forge", lambda *a, **k: local)  # the run start of the command
    return local


def restart(world, unit=UNIT, **kwargs):
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), unit)
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
    person_pushes(world, {SPEC: REWORDED_SPEC.replace("reworded", "corrected")})
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


QUESTIONS = f"{UNIT_REL}/questions.md"
_SECTION = "## {id}: {title}\n\n- **Status:** {status}\n- **Blocking tasks:** {task}\n- **Kind:** technical\n"


def questions_text() -> str:
    rows = [("Q-001", "open", "1.1", "a conflict of the old code"), ("Q-002", "answered", "1.2", "trim the name")]
    index = "".join(f"| {i} | {s} | {t} | technical | {w} |\n" for i, s, t, w in rows)
    sections = "\n---\n\n".join(
        _SECTION.format(id=i, title=w, status=s, task=t) + ("\n### Answer\nTrim it.\n" if s == "answered" else "")
        for i, s, t, w in rows
    )
    return (
        "# Questions \u2014 add-greeting\n\n<!-- l4:index:start -->\n| ID | Status | Blocking | Kind | Question |\n"
        f"|----|--------|----------|------|----------|\n{index}<!-- l4:index:end -->\n\n---\n\n{sections}"
    )


def test_a_restart_supersedes_the_open_questions_of_the_old_attempt(world, forge):
    """L4-OPS-004: a question about code that only the old attempt had must not block the new attempt."""
    assert world.run(happy()).code == ExitCode.OK
    person_pushes(world, {QUESTIONS: questions_text()})
    result = restart(world)
    text = blob(world, result.branch_head, QUESTIONS)
    assert text is not None
    assert "- **Status:** superseded by restart" in text and "| Q-001 | superseded |" in text
    assert "| Q-002 | answered |" in text and text.count("- **Status:** answered\n") == 1
    assert "Trim it." in text
    [restarted] = [e for e in events(world.remote) if e["type"] == "unit.restarted"]
    assert restarted["superseded_questions"] == ["Q-001"]
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), UNIT)
    facts = facts_of(load_snapshot(provider, git, ref, branch_prefix=cfg.forge.branch_prefix))
    assert facts.open_blocking_questions == () and next_action(facts)[0] == "implement"


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
    real = Git.restart_push
    pushed = {}

    def late_push(self, *args, **kwargs):
        pushed["head"] = world.sim.human_commit({"NOTES.md": "mine\n"}, "a person's late push", BRANCH)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Git, "restart_push", late_push)
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
    names = UnitNames.for_unit(
        UNIT,
        branch_prefix="l4/",
        cache=cache_root(world.app.environ, repo=world.app.repo),
        repo_key=repository_key(world.app.repo, world.app.environ),
    )
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


# --- review H1, M1, M6, L5: a failed restart changes nothing; the markers, the live run, the deleted branch ---------


LOCK = f"refs/l4/locks/openspec/{NAME}"


def phase_of(world) -> str | None:
    """The unit's phase as a new `l4` process folds it (the lock ref fetched as the commands do)."""
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    git.run("fetch", "--quiet", "--prune", "origin", "+refs/l4/*:refs/l4/*")
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), UNIT)
    return load_snapshot(provider, git, ref, branch_prefix=cfg.forge.branch_prefix).state.phase


def late_person_push(world, monkeypatch):
    real = Git.restart_push

    def push_first(self, *args, **kwargs):
        world.sim.human_commit({"NOTES.md": "mine\n"}, "a person's late push", BRANCH)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Git, "restart_push", push_first)


def test_a_lost_lease_leaves_the_lock_ref_and_the_phase_as_they_were(world, forge, monkeypatch):
    """H1, SCN-OPS-09: the lock ref holds the pending ledger (the `in_review` edge); a failed restart leaves it."""
    assert world.run(happy()).code == ExitCode.OK
    forge.create_pr(BRANCH, "main", "add-greeting", "body")
    lock, phase = remote_ref(world, LOCK), phase_of(world)
    assert lock is not None and phase == "in_review"
    late_person_push(world, monkeypatch)
    with pytest.raises(L4Exit, match="the branch moved") as caught:
        restart(world)
    assert caught.value.code == ExitCode.INTERNAL_ERROR
    assert remote_ref(world, LOCK) == lock and remote_ref(world, f"{ATTEMPTS}/1-locks") is None
    assert phase_of(world) == phase


def test_a_lost_lease_with_a_pending_ledger_on_an_escalated_unit(world, forge, monkeypatch):
    pr = poisoned(world, forge)
    head = remote_ref(world, f"refs/heads/{BRANCH}")
    world.remote.run("update-ref", LOCK, head)
    late_person_push(world, monkeypatch)
    with pytest.raises(L4Exit, match="the branch moved"):
        restart(world)
    assert remote_ref(world, LOCK) == head and remote_ref(world, f"{ATTEMPTS}/1-locks") is None
    assert forge.get_pr(pr.number).state == "open"


def test_a_lock_ref_that_moved_stops_the_restart_with_nothing_changed(world, forge, monkeypatch):
    """The lease on the lock ref is part of the one atomic push: a run that wrote a pending line since wins."""
    poisoned(world, forge)
    head = remote_ref(world, f"refs/heads/{BRANCH}")
    world.remote.run("update-ref", LOCK, head)
    real = restart_module._remote_refs

    def moved_after_read(git, config, pattern):
        found = real(git, config, pattern)
        if pattern == LOCK:
            identity = (("user.name", "t"), ("user.email", "t@example.com"))
            later = world.remote.run("commit-tree", "-p", head, "-m", "later", f"{head}^{{tree}}", config=identity)
            world.remote.run("update-ref", LOCK, later.stdout.strip())
        return found

    monkeypatch.setattr(restart_module, "_remote_refs", moved_after_read)
    with pytest.raises(L4Exit, match="moved"):
        restart(world)
    assert remote_ref(world, f"{ATTEMPTS}/1-locks") is None and remote_ref(world, f"refs/heads/{BRANCH}") == head


def test_a_unit_branch_checked_out_by_the_operator_does_not_break_the_restart(world, forge):
    """H1: the worktree is built apart from the unit branch, before any ref is touched."""
    assert world.run(happy()).code == ExitCode.OK
    forge.create_pr(BRANCH, "main", "add-greeting", "body")
    lock = remote_ref(world, LOCK)
    repo = Git(world.app.repo, environ=world.app.environ)
    for line in repo.run("worktree", "list", "--porcelain").stdout.splitlines()[1:]:
        if line.startswith("worktree "):
            repo.run("worktree", "remove", "--force", line.removeprefix("worktree "))
    repo.run("checkout", "-q", "-B", BRANCH, f"refs/remotes/origin/{BRANCH}")
    result = restart(world)
    repo.run("checkout", "-q", "main")
    assert remote_ref(world, f"refs/heads/{BRANCH}") == result.branch_head
    assert remote_ref(world, f"{ATTEMPTS}/1-locks") == lock and remote_ref(world, LOCK) is None


def test_a_failure_before_the_push_changes_no_remote_ref(world, forge, monkeypatch):
    """H1: the folder and the commit are built before any ref moves; a failure there leaves the remote as it was."""
    assert world.run(happy()).code == ExitCode.OK
    forge.create_pr(BRANCH, "main", "add-greeting", "body")
    before, phase = refs_of(world), phase_of(world)

    def broken(*args, **kwargs):
        raise RuntimeError("the folder cannot be built")

    monkeypatch.setattr(restart_module, "_build_folder", broken)
    with pytest.raises(RuntimeError):
        restart(world)
    assert [
        r for r in refs_of(world).splitlines() if "/attempts/" not in r
    ] == before.splitlines()  # the kept head may stay
    assert remote_ref(world, LOCK) is not None and remote_ref(world, f"{ATTEMPTS}/1-locks") is None
    assert remote_ref(world, f"refs/heads/{BRANCH}") is not None and phase_of(world) == phase


FOLLOW = "add-greeting-followup-1"
FOLLOW_REL = f"openspec/changes/{FOLLOW}"


def test_a_restarted_follow_up_unit_is_still_discovered(world, forge):
    """M1: `.l4/followup.json` and `.l4/fix.json` stay in the restarted folder; without the marker the unit vanishes."""
    from l4.state.followups import known_follow_ups

    marker = (
        '{"schema": "l4/followup@1", "parent": "openspec:add-greeting", "items": [{"id": "FB-001", "sha256": "%s"}]}'
    )
    files = {
        f"{FOLLOW_REL}/proposal.md": "## Why\nx\n",
        f"{FOLLOW_REL}/tasks.md": "- [ ] 1.1 A task\n",
        f"{FOLLOW_REL}/.l4/followup.json": marker % ("0" * 64),
        f"{FOLLOW_REL}/.l4/fix.json": '{"schema": "l4/fix-unit@1"}',
        f"{FOLLOW_REL}/.l4/ledger/old.jsonl": "{}\n",
    }
    branch = f"l4/openspec/{FOLLOW}"
    world.sim.human_commit(files, "the follow-up", branch)
    Git(world.app.repo, environ=world.app.environ).run("fetch", "--quiet", "origin")
    result = restart(world, unit=f"openspec:{FOLLOW}")
    assert blob(world, result.branch_head, f"{FOLLOW_REL}/.l4/followup.json") == marker % ("0" * 64)
    assert blob(world, result.branch_head, f"{FOLLOW_REL}/.l4/fix.json") is not None
    assert blob(world, result.branch_head, f"{FOLLOW_REL}/.l4/ledger/old.jsonl") is None  # the old evidence goes
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    git.run("fetch", "--quiet", "--prune", "origin")
    assert [k.name for k in known_follow_ups(git, cfg)] == [FOLLOW]


def test_a_restart_clears_the_local_unpublished_tails(world, forge):
    """M6: a `pending-unpublished` run file of the old attempt would be published into the new one."""
    from l4.state.pending import UNPUBLISHED_DIR

    poisoned(world, forge)
    cache = cache_root(world.app.environ, repo=world.app.repo)
    tail = cache / UNPUBLISHED_DIR / "openspec" / NAME / "r-20261013T1000Z-aaaa.jsonl"
    tail.parent.mkdir(parents=True)
    tail.write_text("{}\n")
    restart(world)
    assert not tail.exists()


def test_a_restart_is_refused_while_a_run_works_on_the_unit(world, forge, tmp_path):
    """M6: the pending ledger of the lock ref has `run.started` and no `run.finished`."""
    from l4.redact import Redactor
    from l4.state.ledger import LedgerWriter
    from l4.state.pending import PendingLedger

    poisoned(world, forge)
    run_id = "r-20261013T1000Z-bbbb"
    writer = LedgerWriter.open(tmp_path / "unit", UNIT, run_id, redactor=Redactor({}))  # never finished
    git = Git(world.app.repo, environ=world.app.environ)
    PendingLedger(git, lock_ref=LOCK, unit=UNIT, run_id=run_id).publish(writer.path)
    before = refs_of(world)
    with pytest.raises(L4Exit, match=rf"a run is working on {UNIT} \(run {run_id}\); try again when it ends") as caught:
        restart(world)
    assert caught.value.code == ExitCode.USAGE_ERROR and refs_of(world) == before


def test_the_last_known_head_of_a_deleted_branch_is_kept_as_the_attempt(world, forge):
    """L5: `l4 restart` fetches without prune; the tracking ref of a branch the forge deleted is the old work."""
    assert world.run(failing_reds()).code == ExitCode.HALTED
    open_pr(forge)
    old = remote_ref(world, f"refs/heads/{BRANCH}")
    world.remote.run("update-ref", "-d", f"refs/heads/{BRANCH}")
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    restart_module.fetch_unit_refs(app, cfg, git, prune=False)
    assert git.rev_parse(f"refs/remotes/origin/{BRANCH}") == old
    result = restart(world)
    assert (result.previous_head, result.attempt_ref) == (old, f"{ATTEMPTS}/1")
    assert remote_ref(world, f"{ATTEMPTS}/1") == old
    assert remote_ref(world, f"refs/heads/{BRANCH}") == result.branch_head
