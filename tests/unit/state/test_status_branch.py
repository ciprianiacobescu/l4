import json
from pathlib import Path

import pytest

from l4.cli import main
from l4.planner import facts_of
from l4.specs.openspec import OpenSpecProvider
from l4.state.status import load_snapshot

from .conftest import BRANCH

IMPLEMENTING = [
    ("phase.changed", {"from": None, "to": "intake", "trigger": "unit_discovered_pending"}),
    ("phase.changed", {"from": "intake", "to": "ready", "trigger": "intake_all_pass"}),
    ("phase.changed", {"from": "ready", "to": "implementing", "trigger": "lease_acquired"}),
    ("task.started", {"task": "1.1"}),
    ("task.done", {"task": "1.1"}),
]


def snapshot(unit_repo, git=None):
    provider = OpenSpecProvider(unit_repo.repo, unit_repo.environ)
    (ref,) = provider.list_units()
    return load_snapshot(provider, git or unit_repo.git, ref, branch_prefix="l4/")


def tick_first_task(repo: Path) -> None:
    tasks = repo / "openspec/changes/add-x/tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ] 1.1", "- [x] 1.1"))


def test_status_reads_unit_branch_ledger(unit_repo, trailers):
    def work(repo: Path) -> None:
        unit_repo.write_ledger(repo, *IMPLEMENTING)
        tick_first_task(repo)

    unit_repo.push_unit_branch(work, trailers)
    assert not (unit_repo.unit_dir / ".l4").exists()  # the default-branch checkout has no ledger at all

    reader = unit_repo.git.at(unit_repo.repo)
    snap = snapshot(unit_repo, reader)
    assert snap.source == "branch"
    assert snap.state.phase == "implementing" and snap.state.iteration == 1 and snap.state.tasks.done == ["1.1"]
    assert (sum(t.done for t in snap.tasks), len(snap.tasks)) == (1, 2)  # counts come from the branch's tasks.md too
    # only the local tracking ref is read: no fetch, no write
    assert {argv[7] for argv in reader.history} <= {"rev-parse", "ls-tree", "cat-file"}


def test_without_the_branch_the_working_tree_ledger_is_read(unit_repo):
    unit_repo.write_ledger(unit_repo.repo, *IMPLEMENTING[:2])
    snap = snapshot(unit_repo)
    assert snap.source == "worktree" and snap.state.phase == "ready"
    assert (sum(t.done for t in snap.tasks), len(snap.tasks)) == (0, 2)


def test_the_branch_wins_over_a_working_tree_ledger(unit_repo, trailers):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    unit_repo.write_ledger(unit_repo.repo, *IMPLEMENTING[:1], run_id="r-20261003T1400Z-0001")
    assert snapshot(unit_repo).state.phase == "implementing"


def test_a_branch_without_a_ledger_means_no_phase_yet(unit_repo, trailers):
    unit_repo.push_unit_branch(tick_first_task, trailers)
    snap = snapshot(unit_repo)
    assert snap.source == "branch" and snap.state.phase is None and sum(t.done for t in snap.tasks) == 1


def test_a_corrupt_ledger_on_the_branch_fails_closed(unit_repo, trailers):
    def damage(repo: Path) -> None:
        unit_repo.write_ledger(repo, *IMPLEMENTING)
        (next((repo / "openspec/changes/add-x/.l4/ledger").glob("*.jsonl"))).write_text("garbage\n")

    unit_repo.push_unit_branch(damage, trailers)
    snap = snapshot(unit_repo)
    assert snap.state.phase == "corrupt" and snap.corrupt and ":1 is not a ledger event" in snap.corrupt


def run_cli(unit_repo, capsys, *argv: str) -> tuple[int, str, str]:
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache")}
    code = main([*argv, "--repo", str(unit_repo.repo)], environ=environ)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_l4_status_json_and_table(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    code, out, _ = run_cli(unit_repo, capsys, "status", "--json")
    assert code == 0
    body = json.loads(out)
    assert body["schema"] == "l4/status@1"
    (unit,) = body["units"]
    assert unit["unit"] == "openspec:add-x" and unit["phase"] == "implementing" and unit["source"] == "branch"
    assert unit["spec_tasks"] == {"done": 0, "total": 2}

    code, out, _ = run_cli(unit_repo, capsys, "status")
    assert code == 0 and "openspec:add-x" in out and "implementing" in out and "branch" in out


def test_l4_status_unit_filter_unknown_unit_and_rebuild(unit_repo, capsys):
    code, out, _ = run_cli(unit_repo, capsys, "status", "--unit", "openspec:add-x", "--json")
    assert code == 0 and json.loads(out)["units"][0]["phase"] is None
    code, _, err = run_cli(unit_repo, capsys, "status", "--unit", "openspec:nope")
    assert code == 2 and "nope" in err
    code, _, err = run_cli(unit_repo, capsys, "status", "--unit", "not-an-id")
    assert code == 2
    code, _, err = run_cli(unit_repo, capsys, "status", "--rebuild")
    assert code == 2 and "not yet implemented (M1: state-vcs-locks 1.19)" in err


def test_ledger_wins_over_a_hand_edited_state_json(unit_repo, capsys):
    unit_repo.write_ledger(unit_repo.repo, *IMPLEMENTING)
    (unit_repo.unit_dir / ".l4" / "state.json").write_text('{"schema": "l4/state@1", "phase": "verified"}')
    _, out, _ = run_cli(unit_repo, capsys, "status", "--json")
    assert json.loads(out)["units"][0]["phase"] == "implementing"
    _, again, _ = run_cli(unit_repo, capsys, "status", "--json")
    assert again == out  # byte-identical across reads: the fold is a pure function of the ledger


def test_branch_tasks_parse_from_raw_bytes_like_the_worktree(unit_repo, trailers):
    """CRLF and a lone CR must survive the trip through git, or counts and line numbers differ from OpenSpec's."""
    body = b"- [ ] 1.1 first\r- [x] 1.2 hidden\r\n- [ ] 1.3 third\n\xff\xfe- [ ] 1.4 bad utf8\n"
    (unit_repo.unit_dir / "tasks.md").write_bytes(body)
    worktree = [(t.key, t.done, t.line) for t in snapshot(unit_repo).tasks]
    unit_repo.push_unit_branch(lambda repo: (repo / "openspec/changes/add-x/tasks.md").write_bytes(body), trailers)
    snap = snapshot(unit_repo)
    assert snap.source == "branch"
    assert [(t.key, t.done, t.line) for t in snap.tasks] == worktree
    assert worktree == [("1.1", False, 1), ("1.3", False, 2)]


def test_status_stdout_is_redacted(unit_repo, capsys):
    token = "tok-secretvalue-9999"
    (unit_repo.repo / "openspec/changes" / token).mkdir()
    (unit_repo.repo / "openspec/changes" / token / "tasks.md").write_text("- [ ] 1.1 a\n")
    unit_repo.environ["L4_FORGE_TOKEN"] = token
    for argv in (("status",), ("status", "--json")):
        code, out, _ = run_cli(unit_repo, capsys, *argv)
        assert code == 0 and token not in out and "[REDACTED:L4_FORGE_TOKEN]" in out


def damage_ledger(repo: Path) -> None:
    ledger = repo / "openspec/changes/add-x/.l4/ledger"
    path = next(ledger.glob("*.jsonl"))
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], "GARBAGE", *lines[1:]]) + "\n")


def second_unit(repo: Path) -> None:
    other = repo / "openspec/changes/add-other"
    other.mkdir(parents=True)
    (other / "tasks.md").write_text("- [ ] 1.1 a\n")


def test_one_corrupt_unit_does_not_take_down_plan_or_status(unit_repo, trailers, capsys):
    def work(repo: Path) -> None:
        unit_repo.write_ledger(repo, *IMPLEMENTING)
        damage_ledger(repo)

    unit_repo.push_unit_branch(work, trailers)
    second_unit(unit_repo.repo)
    code, out, err = run_cli(unit_repo, capsys, "plan", "--json")
    assert code == 0
    by_unit = {u["unit"]: u for u in json.loads(out)["units"]}
    assert by_unit["openspec:add-x"]["phase"] == "corrupt" and by_unit["openspec:add-x"]["next_action"] == "none"
    assert by_unit["openspec:add-x"]["reason"].startswith("ledger corrupt: r-20261003T1312Z-7f3a.jsonl:2 ")
    assert by_unit["openspec:add-other"]["next_action"] == "implement"
    assert "ledger corrupt" in err  # a warning on the console
    code, out, _ = run_cli(unit_repo, capsys, "status", "--json")
    assert code == 0 and {u["unit"]: u["phase"] for u in json.loads(out)["units"]}["openspec:add-x"] == "corrupt"
    code, out, _ = run_cli(unit_repo, capsys, "status")
    assert code == 0 and "corrupt" in out


def test_a_ledger_file_cannot_carry_another_units_events(unit_repo):
    unit_repo.write_ledger(unit_repo.repo, *IMPLEMENTING)
    path = next((unit_repo.unit_dir / ".l4/ledger").glob("*.jsonl"))
    path.write_text(path.read_text().replace('"unit": "openspec:add-x"', '"unit": "openspec:add-y"'))
    snap = snapshot(unit_repo)
    assert snap.state.phase == "corrupt" and "add-y" in (snap.corrupt or "")


def test_branch_reads_skip_symlinks_trees_and_oversized_blobs(unit_repo, trailers, monkeypatch):
    def work(repo: Path) -> None:
        unit_repo.write_ledger(repo, *IMPLEMENTING)
        ledger = repo / "openspec/changes/add-x/.l4/ledger"
        (ledger / "r-20261003T1500Z-0002.jsonl").symlink_to("/etc/hostname")
        (ledger / "r-20261003T1500Z-0003.jsonl").mkdir()
        (ledger / "r-20261003T1500Z-0003.jsonl" / "inner.txt").write_text("x\n")
        (ledger / "r-20261003T1500Z-0004.jsonl").write_text("x" * 5000)  # over the patched cap, and not a ledger

    unit_repo.push_unit_branch(work, trailers)
    monkeypatch.setattr("l4.state.status.MAX_LEDGER_FILE_BYTES", 4096)
    git = unit_repo.git.at(unit_repo.repo)
    snap = snapshot(unit_repo, git)
    assert snap.corrupt is None and snap.state.phase == "implementing"  # the three decoys were never parsed
    assert sum("cat-file" in argv for argv in git.history) == 2  # the one real ledger file and tasks.md


QUESTION = (
    "# Questions\n\n---\n\n## Q-001: Which rate?\n\n- **Status:** {status}\n- **Blocking tasks:** 1.1\n"
    "- **Kind:** product\n\n### Context\nx\n\n### Answer\n<!-- write below this line -->\n{answer}\n"
)


def test_questions_are_read_from_the_branch_beside_tasks_and_ledger(unit_repo, trailers):
    def work(repo: Path) -> None:
        waiting = ("phase.changed", {"from": "implementing", "to": "awaiting_human", "trigger": "questions_blocking"})
        unit_repo.write_ledger(repo, *IMPLEMENTING[:3], waiting)
        (repo / "openspec/changes/add-x/questions.md").write_text(QUESTION.format(status="answered", answer="21%"))

    unit_repo.push_unit_branch(work, trailers)
    assert not (unit_repo.unit_dir / "questions.md").exists()  # the default-branch checkout has none
    snap = snapshot(unit_repo)
    assert snap.source == "branch" and snap.questions is not None
    assert snap.questions.get("Q-001").answer_text == "21%"  # type: ignore[union-attr]
    facts = facts_of(snap)
    assert facts.answers_unblock == ("Q-001",) and facts.open_blocking_questions == ()


def test_an_open_question_on_the_branch_is_reported_as_blocking(unit_repo, trailers):
    unit_repo.push_unit_branch(
        lambda repo: (repo / "openspec/changes/add-x/questions.md").write_text(
            QUESTION.format(status="open", answer="a draft")
        ),
        trailers,
    )
    facts = facts_of(snapshot(unit_repo))
    assert facts.open_blocking_questions == ("Q-001",) and facts.answers_unblock == ()


def test_the_working_tree_questions_are_read_without_a_branch(unit_repo):
    (unit_repo.unit_dir / "questions.md").write_text(QUESTION.format(status="answered", answer="21%"))
    snap = snapshot(unit_repo)
    assert snap.source == "worktree" and facts_of(snap).answers_unblock == ("Q-001",)


def test_a_symlinked_questions_file_on_the_branch_is_not_read(unit_repo, trailers):
    def work(repo: Path) -> None:
        (repo / "secret.md").write_text(QUESTION.format(status="answered", answer="21%"))
        (repo / "openspec/changes/add-x/questions.md").symlink_to("../../../secret.md")

    unit_repo.push_unit_branch(work, trailers)
    assert snapshot(unit_repo).questions is None


def delete_remote_unit_branch(unit_repo) -> None:
    bare = unit_repo.repo.parent / "repo-origin.git"
    unit_repo.git.run("--git-dir", str(bare), "branch", "-D", "l4/openspec/add-x", check=False)  # noqa: E501


def plan_json(unit_repo, capsys, *, ci: bool, no_fetch: bool = False) -> dict:
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache")}
    if ci:
        environ["GITLAB_CI"] = "true"
    flags = ["--no-fetch"] if no_fetch else []
    assert main(["plan", "--json", *flags, "--repo", str(unit_repo.repo)], environ=environ) == 0
    return json.loads(capsys.readouterr().out)["units"][0]


def test_deleted_remote_unit_branch_is_pruned_before_fold(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    assert plan_json(unit_repo, capsys, ci=True)["phase"] == "implementing"
    delete_remote_unit_branch(unit_repo)
    # `--no-fetch` reads local refs, as in M0: the stale tracking ref still folds the old ledger
    assert plan_json(unit_repo, capsys, ci=False, no_fetch=True)["phase"] == "implementing"
    for ci in (True, False):  # the refs are refreshed first, in a job or on a person's computer (L4-CLI-005)
        unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
        delete_remote_unit_branch(unit_repo)
        entry = plan_json(unit_repo, capsys, ci=ci)
        assert (entry["phase"], entry["next_action"], entry["reason"]) == (None, "implement", "pending tasks")
        assert unit_repo.git.rev_parse("refs/remotes/origin/l4/openspec/add-x") is None


def test_l4_status_also_refreshes_in_ci(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    delete_remote_unit_branch(unit_repo)
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "c"), "GITLAB_CI": "true"}
    assert main(["status", "--json", "--repo", str(unit_repo.repo)], environ=environ) == 0
    (unit,) = json.loads(capsys.readouterr().out)["units"]
    assert unit["phase"] is None and unit["source"] == "worktree"


# --- F2: a refused job token after a cancel must not crash `l4 status` --------------------------------------------

DENIED = (
    "fetch --quiet --prune origin +refs/heads/l4/*:refs/remotes/origin/l4/* failed (128): "
    "remote: HTTP Basic: Access denied"
)


def _refuse(monkeypatch, stderr: str, argv: tuple[str, ...] = ("fetch", "--prune", "origin")) -> None:
    from l4.vcs.errors import GitError

    def refuse(*args, **kwargs):
        raise GitError(list(argv), 128, stderr)

    monkeypatch.setattr("l4.state.status.refresh_remote_refs", refuse)


def test_status_falls_back_to_local_refs_when_the_forge_denies_the_fetch(unit_repo, trailers, capsys, monkeypatch):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    _refuse(monkeypatch, "remote: HTTP Basic: Access denied\nfatal: Authentication failed")
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "c"), "GITLAB_CI": "true"}
    assert main(["status", "--json", "--repo", str(unit_repo.repo)], environ=environ) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["units"][0]["phase"] == "implementing"  # stdout stays clean JSON
    assert err.count("[l4] status: could not refresh from the forge (access denied: the job may be cancelled)") == 1
    assert "showing local refs" in err


def test_status_still_fails_on_any_other_fetch_error(unit_repo, trailers, capsys, monkeypatch):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    _refuse(monkeypatch, "fatal: unable to access: Could not resolve host")
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "c"), "GITLAB_CI": "true"}
    assert main(["status", "--repo", str(unit_repo.repo)], environ=environ) != 0
    assert "could not refresh from the forge" not in capsys.readouterr().err


def test_status_judges_the_refusal_by_what_git_said_not_by_its_command_line(unit_repo, trailers, capsys, monkeypatch):
    """The argv (config, refspecs with the branch prefix) is not git's answer: a word in it must not pass for one."""
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    argv = ("-c", "credential.helper=!echo 'HTTP Basic access denied'", "fetch", "--prune", "origin")
    _refuse(monkeypatch, "fatal: unable to access: Could not resolve host", argv)
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "c"), "GITLAB_CI": "true"}
    assert main(["status", "--repo", str(unit_repo.repo)], environ=environ) != 0
    assert "could not refresh from the forge" not in capsys.readouterr().err


def test_plan_does_not_take_the_fallback(unit_repo, trailers, capsys, monkeypatch):
    """Planning from refs known to be stale is how a deleted branch comes back: only `status` may degrade."""
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    _refuse(monkeypatch, "remote: HTTP Basic: Access denied")
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "c"), "GITLAB_CI": "true"}
    assert main(["plan", "--json", "--repo", str(unit_repo.repo)], environ=environ) != 0


def test_the_snapshot_passes_the_recorded_h_to_the_review(unit_repo, trailers, monkeypatch, tmp_path):
    """L4-ARC-008: `load_snapshot` counts the review from the `pr.ready{head}` of the lock ref's pending files."""
    import datetime as dt

    import l4.state.status as status
    from l4.vcs.git import BOT_IDENTITY

    from .conftest import BRANCH
    from .ready_world import fetch, push_lock, ready_file

    git = unit_repo.git
    git.run("checkout", "-q", "-b", BRANCH)
    tick_first_task(unit_repo.repo)
    git.run("add", "-A")
    git.commit("work", trailers, BOT_IDENTITY)
    b = git.rev_parse("HEAD")
    unit_repo.write_ledger(
        unit_repo.repo,
        *IMPLEMENTING,
        ("phase.changed", {"from": "implementing", "to": "in_review", "trigger": "hand_off_pushed"}),
    )
    git.run("add", "-A")
    git.commit("ledger", trailers, BOT_IDENTITY)
    git.push("origin", [f"HEAD:refs/heads/{BRANCH}"])
    when = dt.datetime(2026, 10, 3, 14, 0, tzinfo=dt.UTC)
    push_lock(git, {"r-20261003T1400Z-0001.jsonl": ready_file(tmp_path / "g", "r-20261003T1400Z-0001", b, when)}, None)
    git.run("checkout", "-q", "main")
    git.run("branch", "-q", "-D", BRANCH)
    fetch(unit_repo)

    seen: dict[str, object] = {}
    real = status.after_handoff

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(status, "after_handoff", spy)
    snap = snapshot(unit_repo)
    assert snap.state.phase == "in_review"
    assert seen["recorded"] == b and snap.state.ready_head == b and snap.state.ready_at == when


# --- L4-CLI-005: the commands that read a unit's state fetch first, on a person's computer too -----------------------


def spec_edit_from_another_clone(unit_repo, raw) -> str:
    """A person adds a task to the unit branch from another computer; this clone's tracking ref is behind."""
    other = unit_repo.repo.parent / "other-computer"
    bare = unit_repo.repo.parent / "repo-origin.git"
    raw(unit_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(bare), str(other))
    tasks = other / "openspec/changes/add-x/tasks.md"
    tasks.write_text(tasks.read_text() + "- [ ] 1.3 third\n")
    raw(other, "add", "-A")
    raw(other, "commit", "-q", "-m", "a spec edit")
    raw(other, "push", "-q", "origin", BRANCH)
    return raw(other, "rev-parse", "HEAD").strip()


def status_tasks(unit_repo, capsys, *flags: str, environ: dict | None = None) -> tuple[int, dict, str]:
    env = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache"), **(environ or {})}
    argv = ["status", "--unit", "openspec:add-x", "--json", *flags, "--repo", str(unit_repo.repo)]
    code = main(argv, environ=env)
    out = capsys.readouterr()
    return code, (json.loads(out.out)["units"][0]["spec_tasks"] if out.out else {}), out.err


def test_scn_cli_15_a_local_status_sees_a_remote_spec_edit(unit_repo, trailers, raw, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    head = spec_edit_from_another_clone(unit_repo, raw)
    assert unit_repo.git.rev_parse("refs/remotes/origin/l4/openspec/add-x") != head
    code, tasks, err = status_tasks(unit_repo, capsys)
    assert code == 0 and tasks == {"done": 0, "total": 3}  # the forge's head
    assert unit_repo.git.rev_parse("refs/remotes/origin/l4/openspec/add-x") == head
    assert "could not refresh" not in err


def test_ci_true_alone_is_not_a_job_so_the_refresh_fetches_as_a_laptop_does(unit_repo, trailers, raw, capsys):
    """SCN-CLI-12 (amended): `CI=true` alone fetches, with the failure rules of a person's computer."""
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    spec_edit_from_another_clone(unit_repo, raw)
    code, tasks, _ = status_tasks(unit_repo, capsys, environ={"CI": "true"})
    assert code == 0 and tasks == {"done": 0, "total": 3}
    unit_repo.git.run("remote", "set-url", "origin", str(unit_repo.repo.parent / "gone.git"))
    code, tasks, err = status_tasks(unit_repo, capsys, environ={"CI": "true"})
    assert code == 0 and tasks == {"done": 0, "total": 3} and "showing local refs" in err  # not a job: it degrades


def test_scn_cli_16_no_fetch_reads_the_local_refs(unit_repo, trailers, raw, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    stale = unit_repo.git.rev_parse("refs/remotes/origin/l4/openspec/add-x")
    spec_edit_from_another_clone(unit_repo, raw)
    code, tasks, err = status_tasks(unit_repo, capsys, "--no-fetch")
    assert code == 0 and tasks == {"done": 0, "total": 2}  # the local head
    assert unit_repo.git.rev_parse("refs/remotes/origin/l4/openspec/add-x") == stale  # git fetched nothing
    assert "could not refresh" not in err
    go_offline(unit_repo)  # and nothing is asked of an origin that cannot answer
    assert status_tasks(unit_repo, capsys, "--no-fetch")[2] == ""


def test_the_help_of_every_command_that_fetches_names_no_fetch(capsys):
    for command in ("status", "plan", "resume", "run", "archive"):
        assert main([command, "--help"], environ={}) == 0
        out = " ".join(capsys.readouterr().out.split())  # click wraps the help text: compare without the line breaks
        assert "--no-fetch" in out
        assert "Read the local refs for the state; a run's worktree still fetches the unit." in out


def go_offline(unit_repo) -> None:
    unit_repo.git.run("remote", "set-url", "origin", str(unit_repo.repo.parent / "gone.git"))


def test_scn_cli_17_an_offline_status_shows_the_local_refs_and_says_so_once(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    go_offline(unit_repo)
    code, tasks, err = status_tasks(unit_repo, capsys)
    assert code == 0 and tasks == {"done": 0, "total": 2}  # the local head, exit as with the local refs
    assert err.count("could not refresh from the forge (") == 1
    assert "gone.git" in err and "); showing local refs" in err


def test_scn_cli_17_a_refused_credential_degrades_the_same_way_on_a_laptop(unit_repo, trailers, capsys, monkeypatch):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    _refuse(monkeypatch, "remote: HTTP Basic: Access denied\nfatal: Authentication failed")
    code, tasks, err = status_tasks(unit_repo, capsys)
    assert code == 0 and tasks == {"done": 0, "total": 2}
    assert err.count("could not refresh from the forge (") == 1 and "Access denied" in err


def test_scn_cli_18_an_offline_plan_stops_before_it_folds_and_names_no_fetch(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    go_offline(unit_repo)
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache")}
    assert main(["plan", "--json", "--repo", str(unit_repo.repo)], environ=environ) == 1
    out, err = capsys.readouterr()
    assert out == "" and "gone.git" in err and "--no-fetch" in err  # nothing was folded or printed
    assert main(["plan", "--json", "--no-fetch", "--repo", str(unit_repo.repo)], environ=environ) == 0


def test_scn_cli_18_a_refused_credential_stops_a_plan_with_exit_3(unit_repo, trailers, capsys, monkeypatch):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    _refuse(monkeypatch, "remote: HTTP Basic: Access denied\nfatal: Authentication failed")
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache")}
    assert main(["plan", "--json", "--repo", str(unit_repo.repo)], environ=environ) == 3
    err = capsys.readouterr().err
    assert "Access denied" in err and "--no-fetch" in err


# --- `l4 archive` reads unit state and then writes: it fetches first like the others ---------------------------------


def archive_cli(unit_repo, capsys, *flags: str, environ: dict | None = None) -> tuple[int, str]:
    env = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache"), **(environ or {})}
    code = main(["archive", "--unit", "openspec:add-x", *flags, "--repo", str(unit_repo.repo)], environ=env)
    return code, capsys.readouterr().err


def test_a_local_archive_fetches_before_it_reads_the_unit(unit_repo, trailers, raw, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    head = spec_edit_from_another_clone(unit_repo, raw)
    assert unit_repo.git.rev_parse("refs/remotes/origin/l4/openspec/add-x") != head
    archive_cli(unit_repo, capsys)  # what it answers for an unmerged unit is not this test's business
    assert unit_repo.git.rev_parse("refs/remotes/origin/l4/openspec/add-x") == head


def test_archive_no_fetch_reads_the_local_refs(unit_repo, trailers, raw, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    stale = unit_repo.git.rev_parse("refs/remotes/origin/l4/openspec/add-x")
    spec_edit_from_another_clone(unit_repo, raw)
    go_offline(unit_repo)  # and nothing is asked of an origin that cannot answer
    _, err = archive_cli(unit_repo, capsys, "--no-fetch")
    assert unit_repo.git.rev_parse("refs/remotes/origin/l4/openspec/add-x") == stale
    assert "could not refresh" not in err


def test_a_failed_local_fetch_stops_archive_before_it_reads_with_the_hint(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    go_offline(unit_repo)
    code, err = archive_cli(unit_repo, capsys)
    assert code == 1 and "could not refresh from the forge" in err and "gone.git" in err and "--no-fetch" in err


# --- review fixes: the stop message per command, --no-fetch in a job, the status timeout ----------------------------

PLAN_HINT = "pass --no-fetch to read the local refs"


def test_an_offline_plan_names_no_fetch_as_the_way_to_read_the_local_refs(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    go_offline(unit_repo)
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache")}
    assert main(["plan", "--repo", str(unit_repo.repo)], environ=environ) == 1
    assert PLAN_HINT in capsys.readouterr().err


def test_an_offline_archive_says_its_worktree_needs_the_forge(unit_repo, trailers, capsys):
    """The post-merge archive cuts a worktree that fetches the base: `--no-fetch` alone does not make it offline."""
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    go_offline(unit_repo)
    code, err = archive_cli(unit_repo, capsys)
    assert code == 1 and "an archive needs the forge (its worktree fetches the base branch)" in err
    assert "`l4 status --no-fetch`" in err and PLAN_HINT not in err


@pytest.mark.parametrize("command", ["status", "plan", "archive"])
def test_no_fetch_in_a_ci_job_is_a_usage_error(unit_repo, trailers, capsys, command):
    """L4-CLI-003: a job must not read stale refs, and nothing makes the flag a default there."""
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    env = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache"), "GITLAB_CI": "true"}
    argv = [command, "--no-fetch", "--repo", str(unit_repo.repo), *(["--unit", "openspec:add-x"] * (command != "plan"))]
    assert main(argv, environ=env) == 2
    err = capsys.readouterr().err
    assert "--no-fetch is for a person's computer: a CI job must not read stale refs (L4-CLI-003)" in err


def test_a_status_on_a_laptop_gives_the_fetch_a_short_timeout_and_the_others_do_not(unit_repo, monkeypatch, capsys):
    from l4.forge.base import STATUS_FETCH_TIMEOUT_S

    seen: dict[str, object] = {}

    def spy(git, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return False

    monkeypatch.setattr("l4.state.status.refresh_remote_refs", spy)
    env = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache")}
    main(["status", "--repo", str(unit_repo.repo)], environ=env)
    assert seen["timeout"] == STATUS_FETCH_TIMEOUT_S == 15.0
    main(["plan", "--repo", str(unit_repo.repo)], environ=env)
    assert seen["timeout"] is None  # the default of git
    main(["status", "--repo", str(unit_repo.repo)], environ={**env, "GITLAB_CI": "true"})
    assert seen["timeout"] is None  # in a job nothing changed
