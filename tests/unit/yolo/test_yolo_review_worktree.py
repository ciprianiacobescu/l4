# ruff: noqa: F811
"""`l4 yolo review PLAN --worktree` and `--record` (L4-YOLO-026, L4-YOLO-022; SCN-YOLO-57 to -60): the dry run reads the
working tree through a snapshot commit and writes nothing on origin, keeps a local cache of what it judged, reuses what
CI or an earlier run judged on the same material, and records the events CI would only on a clean tree."""

import json
from pathlib import Path

import yaml

from l4.agents.fake import FakeAdapter, Step
from l4.vcs.names import unit_branch
from l4.yolo.digest import plan_digest, unit_digest
from l4.yolo.model import PlanEvent
from l4.yolo.readiness import PROMPT_VERSION, review_plan_costed

from .yolo_cmd_world import SPEC_B, A, B, ev, forge, plan_doc, world  # noqa: F401

SPEC_A_EDIT = "\n#### Scenario: Edited at the desk\n- **WHEN** the user edits\n- **THEN** only the judge reads it\n"
FOLDER_A, FOLDER_B = "openspec/changes/add-greeting", "openspec/changes/add-b"
GAP = {"criterion": "testability", "severity": "major", "text": "no inputs"}
SPEC_FILE = f"{FOLDER_A}/specs/greeting/spec.md"


def answer(verdict="READY", findings=()):
    return {"verdict": verdict, "findings": list(findings), "assumptions": [], "missing": []}


def judge(monkeypatch, *answers, cost=0.25, spare=0):
    """The fake judge behind the real `review_plan_costed`: one scripted answer per call, in call order."""
    fake = FakeAdapter([Step(structured=a, cost_usd=cost) for a in [*answers, *[answer()] * spare]])
    real = review_plan_costed
    monkeypatch.setattr(
        "l4.yolo.review_worktree.review_plan_costed", lambda *a, **kw: real(*a, adapters={"fake": fake}, **kw)
    )
    return fake


def ready_world(world):
    """The plan pushed (unit B's delta already carries the `## Purpose` a new capability needs at intake)."""
    world.push_plan()
    world.pull()
    return world


def edit_spec(world, extra=SPEC_A_EDIT):
    path = world.app.repo / SPEC_FILE
    path.write_text(path.read_text(encoding="utf-8") + extra, encoding="utf-8")


def cache_lines(world):
    files = list(world.root.glob("**/yolo/p1/review/verdicts.jsonl")) or list(
        world.app.repo.parent.glob("**/yolo/p1/review/verdicts.jsonl")
    )
    assert files, "no local cache file"
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line]


def state_of(world):
    git = world.clone
    return (
        git.run("rev-parse", "HEAD").stdout,
        git.run("status", "--porcelain").stdout,
        git.run("diff", "--cached").stdout,
        git.run("for-each-ref", "refs/heads", "refs/l4", "refs/tags").stdout,
    )


def test_scn_yolo_57_a_dry_run_reads_the_uncommitted_edit_and_writes_nothing(world, monkeypatch, capsys):
    ready_world(world)
    edit_spec(world)
    fake = judge(monkeypatch, answer(), answer(), answer())
    before = state_of(world)
    assert world.l4("review", "p1", "--worktree") == 0
    out = capsys.readouterr().out
    assert any("Edited at the desk" in r.prompt for r in fake.requests)
    assert f"plan p1 at the working tree: plan digest {plan_digest(world.plan_text)}" in out
    assert f"  {A}: digest " in out and ", material " in out and ": READY" in out
    assert "cost: $0.75 (3 judged, 0 reused)" in out
    assert "Next:" in out
    assert world.store().read().head is None  # nothing on origin
    assert state_of(world) == before  # HEAD, status, index and refs are as they were
    assert len(cache_lines(world)) == 3


def test_the_digest_shown_is_the_snapshots(world, monkeypatch, capsys):
    ready_world(world)
    edit_spec(world)
    judge(monkeypatch, answer(), answer(), answer())
    world.l4("review", "p1", "--worktree")
    out = capsys.readouterr().out
    committed = unit_digest(world.clone, "HEAD", FOLDER_A)
    assert f"{A}: digest {committed}," not in out  # the edit changes the digest
    assert f"  {B}: digest {unit_digest(world.clone, 'HEAD', FOLDER_B)}," in out  # B is untouched


def test_a_subject_that_is_not_ready_exits_2_with_its_resolve_line(world, monkeypatch, capsys):
    ready_world(world)
    judge(monkeypatch, answer(), answer("NEEDS_REVISION", [GAP]), answer())
    assert world.l4("review", "p1", "--worktree") == 2
    out = capsys.readouterr().out
    assert f"  {B}: digest " in out and "NEEDS_REVISION" in out
    assert "[major/testability] no inputs" in out and "Resolve:" in out


def test_a_second_run_with_no_edit_makes_no_judge_call(world, monkeypatch, capsys):
    ready_world(world)
    judge(monkeypatch, answer(), answer(), answer())
    assert world.l4("review", "p1", "--worktree") == 0
    capsys.readouterr()
    again = judge(monkeypatch)  # an empty script: any call fails the test
    assert world.l4("review", "p1", "--worktree") == 0
    out = capsys.readouterr().out
    assert again.requests == [] and "cost: $0.00 (0 judged, 3 reused)" in out and "(reused)" in out


def test_an_edit_asks_the_judge_about_that_unit_and_its_batch_only(world, monkeypatch, capsys):
    ready_world(world)
    judge(monkeypatch, answer(), answer(), answer())
    world.l4("review", "p1", "--worktree")
    edit_spec(world)
    again = judge(monkeypatch, answer(), answer(), answer())  # A, then the batch; B depends on A so it is judged too
    world.l4("review", "p1", "--worktree")
    judged = len(again.requests)
    assert 1 <= judged <= 3 and capsys.readouterr().out.count("(reused)") == 3 - judged


def test_a_subject_ci_already_judged_on_the_same_material_costs_nothing(world, monkeypatch, capsys):
    ready_world(world)
    judge(monkeypatch, answer(), answer(), answer())
    world.l4("review", "p1", "--worktree")
    lines = cache_lines(world)
    by_subject = {line["subject"]: line for line in lines}
    for file in world.root.glob("**/yolo/p1/review/verdicts.jsonl"):
        file.unlink()  # the local cache is gone: only the ledger remembers
    units = {s: dict(by_subject[s]["entry"]) for s in (A, B)}
    batches = {"b1": dict(by_subject["batch:b1"]["entry"])}
    world.seed("p1", PlanEvent("plan.reviewed", "2026-10-14T11:00:00Z", {
        "prompt_version": PROMPT_VERSION, "plan_digest": "x", "units": units, "batches": batches,
    }))  # fmt: skip
    capsys.readouterr()
    again = judge(monkeypatch)
    assert world.l4("review", "p1", "--worktree") == 0
    assert again.requests == [] and "cost: $0.00 (0 judged, 3 reused)" in capsys.readouterr().out


def test_fresh_asks_the_judge_again_about_the_named_subject_only(world, monkeypatch, capsys):
    ready_world(world)
    judge(monkeypatch, answer(), answer(), answer())
    world.l4("review", "p1", "--worktree")
    capsys.readouterr()
    again = judge(monkeypatch, answer())
    assert world.l4("review", "p1", "--worktree", "--fresh", A) == 0
    assert len(again.requests) == 1 and "cost: $0.25 (1 judged, 2 reused)" in capsys.readouterr().out


def test_fresh_names_a_subject_of_the_plan(world, monkeypatch, capsys):
    ready_world(world)
    again = judge(monkeypatch)
    assert world.l4("review", "p1", "--worktree", "--fresh", "openspec:nope") == 2
    assert again.requests == [] and "openspec:nope" in capsys.readouterr().err


def test_a_unit_with_a_branch_on_origin_is_said_to_be_read_on_the_working_tree(world, monkeypatch, capsys):
    ready_world(world)
    branch = unit_branch(A, "l4/")
    world.clone.run("push", "-q", "origin", f"HEAD:refs/heads/{branch}")
    judge(monkeypatch, answer(), answer(), answer())
    world.l4("review", "p1", "--worktree")
    assert f"CI reads {A} on its branch {branch}; this review read the working tree" in capsys.readouterr().out


def test_a_plan_that_is_not_admitted_is_not_reviewed(world, monkeypatch, capsys):
    world.push_plan(plan_doc(target="release"))
    world.pull()
    fake = judge(monkeypatch)
    assert world.l4("review", "p1", "--worktree") == 2
    assert fake.requests == [] and "not admitted" in capsys.readouterr().out


def test_an_active_plan_is_not_reviewed(world, monkeypatch, capsys):
    ready_world(world)
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"))
    assert world.l4("review", "p1", "--worktree") == 2
    assert "p1 is active" in capsys.readouterr().err


def test_a_plan_file_only_in_the_working_tree_is_reviewed(world, monkeypatch, capsys):
    world.pull()
    path = world.app.repo / ".l4/plans/p1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan_doc(), indent=2), encoding="utf-8")
    world.plan_text = path.read_text(encoding="utf-8")
    judge(monkeypatch, answer(), answer(), answer())
    assert world.l4("review", "p1", "--worktree") == 0
    assert f"plan digest {plan_digest(world.plan_text)}" in capsys.readouterr().out


def test_a_judge_at_its_limit_exits_12_and_leaves_no_cache(world, monkeypatch, capsys):
    ready_world(world)

    def limited(*a, **kw):
        from l4.agents.base import RunResult
        from l4.implementer.tdd import RoleLimit

        raise RoleLimit(RunResult(status="limit", raw_events_path=Path("/dev/null"), detail="quota"))

    monkeypatch.setattr("l4.yolo.review_worktree.review_plan_costed", limited)
    assert world.l4("review", "p1", "--worktree") == 12
    assert world.store().read().head is None


def test_the_plan_review_total_is_shown_against_its_limit(world, monkeypatch, capsys):
    ready_world(world)
    world.seed("p1", ev("plan.charged", unit="plan:review", attempt=0, cost_usd=1.5, runs=0))
    judge(monkeypatch, answer(), answer(), answer())
    world.l4("review", "p1", "--worktree")
    assert "recorded review cost of the plan: $1.50 of $40.00" in capsys.readouterr().out


# --- the sandbox ------------------------------------------------------------------------------------------------------


def auto_sandbox(world, monkeypatch):
    config = yaml.safe_load(world.app.config_path.read_text(encoding="utf-8"))
    config["sandbox"] = {"mode": "auto"}
    world.app.config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr("l4.yolo.judge_sandbox._bwrap", lambda environ, repo: (None, "bwrap was not found on PATH"))


def test_scn_yolo_60_without_bwrap_a_tool_less_judge_runs_and_says_so(world, monkeypatch, capsys):
    ready_world(world)
    auto_sandbox(world, monkeypatch)
    fake = judge(monkeypatch, answer(), answer(), answer())
    assert world.l4("review", "p1", "--worktree") == 0
    out = capsys.readouterr().out
    assert len(fake.requests) == 3
    assert (
        out.count("judge unsandboxed (bwrap was not found on PATH): it has no tools and runs in an empty folder") == 1
    )
    assert {line["sandbox"] for line in cache_lines(world)} == {"none"}


def test_in_ci_the_judge_fails_closed_without_bwrap(world, monkeypatch, capsys):
    ready_world(world)
    auto_sandbox(world, monkeypatch)
    world.app.environ["CI"] = "true"
    fake = judge(monkeypatch)
    assert world.l4("review", "p1", "--worktree") == 3
    assert fake.requests == []


# --- --record ---------------------------------------------------------------------------------------------------------


def commit_edit(world):
    edit_spec(world)
    world.clone.run("add", SPEC_FILE)
    world.clone.run("commit", "-q", "-m", "edit a")


def test_scn_yolo_59_a_review_of_uncommitted_text_is_not_recorded(world, monkeypatch, capsys):
    ready_world(world)
    edit_spec(world)
    fake = judge(monkeypatch)
    assert world.l4("review", "p1", "--worktree", "--record") == 2
    err = capsys.readouterr().err
    assert "review: --record needs the plan file and the unit folders committed:" in err and SPEC_FILE in err
    assert fake.requests == [] and world.store().read().head is None


def test_record_writes_the_events_ci_would(world, monkeypatch, capsys):
    ready_world(world)
    commit_edit(world)
    judge(monkeypatch, answer(), answer(), answer())
    assert world.l4("review", "p1", "--worktree", "--record") == 0
    assert world.kinds() == ["plan.admitted", "plan.reviewed", "plan.charged"]
    admitted, reviewed, charged = world.events()
    assert admitted.data["order"] == [A, B] and admitted.data["plan_digest"] == plan_digest(world.plan_text)
    data = reviewed.data
    assert (
        data["source"] == "worktree" and data["prompt_version"] == PROMPT_VERSION and data["by"] == "alex@example.com"
    )
    assert data["sandbox"] == "none" and data["judge"] and data["cost_usd"] == 0.75
    assert data["units"][A]["digest"] == unit_digest(world.clone, "HEAD", FOLDER_A) and data["units"][A]["material"]
    assert data["batches"]["b1"]["material"]
    assert charged.data == {"unit": "plan:review", "attempt": 0, "cost_usd": 0.75, "runs": 0}
    assert "Next: git push; CI finds this review current and does not review again" in capsys.readouterr().out


def test_record_after_a_dry_run_is_all_cache_hits_at_no_cost(world, monkeypatch, capsys):
    ready_world(world)
    commit_edit(world)
    judge(monkeypatch, answer(), answer(), answer())
    world.l4("review", "p1", "--worktree")
    again = judge(monkeypatch)
    assert world.l4("review", "p1", "--worktree", "--record") == 0
    assert again.requests == []
    data = world.events()[1].data
    assert data["cost_usd"] == 0 and data["sandbox"] == "none" and "reused_from" not in data["units"][A]
    assert "plan.charged" not in world.kinds()  # nothing was spent


def test_record_of_a_not_ready_review_records_it_and_exits_2(world, monkeypatch, capsys):
    ready_world(world)
    judge(monkeypatch, answer(), answer("NEEDS_REVISION", [GAP]), answer())
    assert world.l4("review", "p1", "--worktree", "--record") == 2
    assert world.events()[1].data["units"][B]["verdict"] == "NEEDS_REVISION"


def test_record_and_fresh_need_worktree(world):
    ready_world(world)
    assert world.l4("review", "p1", "--record") == 2


# --- SCN-YOLO-58 on the CI step ------------------------------------------------------------------------------------


def test_scn_yolo_58_a_recorded_review_of_the_commit_spares_the_ci_review(tmp_path, monkeypatch):
    from l4.cli import main as cli_main
    from l4.sim.fakes import fake_openspec_cli
    from l4.yolo.state import fold_plan

    from .yolo_cycle_world import PLAN, READY, CycleWorld
    from .yolo_review_world import SPEC_A as OTHER_SPEC

    world = CycleWorld(tmp_path)
    world.plan(push=False)  # the plan file is committed here and not yet pushed
    config = world.repo / ".l4" / "config.yaml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(yaml.safe_dump(world.cfg.model_dump(mode="json", exclude_none=True)), encoding="utf-8")
    world.commit({".l4/config.yaml": config.read_text(encoding="utf-8")}, "config")
    purpose = "## Purpose\nThe capability x: it greets, and the greeting is the observable result of the plan.\n\n"
    world.commit({f"openspec/changes/{n}/specs/x/spec.md": purpose + OTHER_SPEC for n in "ab"}, "purpose")
    world.push_main()
    world.commit({"openspec/changes/a/specs/x/spec.md": purpose + OTHER_SPEC + "\nMore text.\n"}, "edit a")  # unpushed
    local = FakeAdapter([Step(structured=READY, cost_usd=0.25) for _ in range(3)])
    real = review_plan_costed
    argv = ["yolo", "review", PLAN, "--worktree", "--record", "--repo", str(world.repo)]
    monkeypatch.setattr(
        "l4.yolo.review_worktree.review_plan_costed", lambda *a, **kw: real(*a, adapters={"fake": local}, **kw)
    )
    with fake_openspec_cli():
        assert cli_main(argv, environ=dict(world.app.environ)) == 0
    assert len(local.requests) == 3
    assert world.kinds() == ["plan.admitted", "plan.reviewed", "plan.charged"]
    world.push_main()  # the push: the commit the review was made for reaches origin
    before = len(world.judge.requests)
    world.step()
    assert len(world.judge.requests) == before == 0  # the CI step called no judge
    assert world.kinds() == ["plan.admitted", "plan.reviewed", "plan.charged"]  # and recorded no new review
    state = fold_plan(PLAN, world.events())
    assert state.review_plan_digest and set(state.review.values()) == {"READY"}
