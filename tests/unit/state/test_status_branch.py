import json
from pathlib import Path

from l4.cli import main
from l4.planner import facts_of
from l4.specs.openspec import OpenSpecProvider
from l4.state.status import load_snapshot

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


def plan_json(unit_repo, capsys, *, ci: bool) -> dict:
    environ = {**unit_repo.environ, "L4_CACHE": str(unit_repo.repo.parent / "cache")}
    if ci:
        environ["GITLAB_CI"] = "true"
    assert main(["plan", "--json", "--repo", str(unit_repo.repo)], environ=environ) == 0
    return json.loads(capsys.readouterr().out)["units"][0]


def test_deleted_remote_unit_branch_is_pruned_before_fold(unit_repo, trailers, capsys):
    unit_repo.push_unit_branch(lambda repo: unit_repo.write_ledger(repo, *IMPLEMENTING), trailers)
    assert plan_json(unit_repo, capsys, ci=True)["phase"] == "implementing"
    delete_remote_unit_branch(unit_repo)
    # a local run reads local refs, as in M0: the stale tracking ref still folds the old ledger
    assert plan_json(unit_repo, capsys, ci=False)["phase"] == "implementing"
    entry = plan_json(unit_repo, capsys, ci=True)  # in CI the refs are refreshed first
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

    monkeypatch.setattr("l4.state.status.refresh_in_ci", refuse)


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
