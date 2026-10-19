# ruff: noqa: F811
"""The messages of a stale review and of a plan file that is not on origin (yolo-guardrails D1 M1 to M5; L4-YOLO-068,
SCN-YOLO-177 to -183): each names the cause, the digests, the files and the exact fix."""

import json

from l4.vcs.names import unit_branch  # noqa: F401
from l4.yolo.digest import plan_digest
from l4.yolo.readiness import PROMPT_VERSION

from .test_yolo_commands_activate import fake_judge
from .yolo_cmd_world import A, B, ev, forge, plan_doc, world  # noqa: F401

FOLDER_A, FOLDER_B = "openspec/changes/add-greeting", "openspec/changes/add-b"
PLAN = ".l4/plans/p1.json"


def origin_sha(world) -> str:
    return world.remote.rev_parse("main") or ""


def reviewed_with_revs(world, *, version: int | None = None, revs: bool = True):
    """The pushed plan, reviewed as it is on origin now, with the revisions the review read."""
    world.push_plan()
    sha = origin_sha(world)
    event = world.reviewed()
    if revs:
        event.data["target_rev"] = sha
        event.data["unit_revs"] = {A: sha, B: sha}
    if version is not None:
        event.data["prompt_version"] = version
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), event)
    return sha


def refused(world, capsys, *argv) -> str:
    capsys.readouterr()
    assert world.l4("activate", "p1", "--reason", "go", *argv) == 2
    return capsys.readouterr().err


def edit_b(world, text="## 1. B\n\n- [ ] 1.1 Add `count()` and `reset()`\n") -> str:
    world.push({f"{FOLDER_B}/tasks.md": text}, "edit b")
    return origin_sha(world)


def test_a_local_review_records_target_rev_and_unit_revs(world, monkeypatch):
    world.push_plan()
    fake_judge(monkeypatch, {})
    assert world.l4("review", "p1", "--local") == 0
    reviewed = next(e for e in world.events() if e.type == "plan.reviewed")
    sha = origin_sha(world)
    assert reviewed.data["target_rev"] == sha and reviewed.data["unit_revs"] == {A: sha, B: sha}


def test_a_stale_activation_names_the_spec_its_digests_and_files(world, capsys):
    old = reviewed_with_revs(world)
    before = world.digest(B)
    new = edit_b(world)
    err = refused(world, capsys)
    after = world.digest(B)
    assert f"activate: the review of p1 is stale against origin/main ({new[:7]}):\n" in err
    assert (
        f"  {B}: spec digest {before[:8]} at the review, {after[:8]} now on origin/main ({new[:7]}); "
        f"changed: {FOLDER_B}/tasks.md\n"
    ) in err
    assert err.rstrip().endswith("Fix: l4 yolo review p1")
    assert old != new and not [e for e in world.events() if e.type == "plan.activated"]


def test_a_stale_activation_names_the_plan_file(world, capsys):
    reviewed_with_revs(world)
    before = plan_digest(world.plan_text)
    new = world.push_plan(plan_doc(limits={"max_cost_usd": 99}))
    err = refused(world, capsys)
    assert (
        f"  plan file {PLAN}: digest {before[:8]} at the review, {plan_digest(world.plan_text)[:8]} "
        f"now on origin/main ({new[:7]})"
    ) in err


def test_a_stale_activation_names_an_unpushed_commit_and_the_push(world, capsys):
    reviewed_with_revs(world)
    world.pull()
    repo = world.app.repo
    proposal = repo / FOLDER_A / "proposal.md"
    base = proposal.read_text(encoding="utf-8") if proposal.exists() else ""
    for text, push in ((base + "\npushed\n", True), (base + "\npushed\nunpushed\n", False)):
        proposal.write_text(text, encoding="utf-8")
        world.clone.run("add", str(proposal))
        world.clone.run("commit", "-q", "-m", "edit")
        if push:
            world.clone.run("push", "-q", "origin", "HEAD:main")
    err = refused(world, capsys)
    head, tip = world.clone.rev_parse("HEAD") or "", origin_sha(world)
    assert (
        f"  local: origin/main ({tip[:7]}) is 1 commit behind HEAD ({head[:7]}); they differ in {FOLDER_A}: "
        f"push, then review"
    ) in err
    assert err.rstrip().endswith("Fix: git push origin HEAD:main, then l4 yolo review p1")


def test_status_shows_the_same_causes(world, capsys):
    reviewed_with_revs(world)
    capsys.readouterr()
    assert world.l4("status", "p1", "--json") == 0
    assert "stale" not in json.loads(capsys.readouterr().out)["plans"][0]["review"]
    new = edit_b(world)
    assert world.l4("status", "p1") == 0
    out = capsys.readouterr().out
    assert "  review: stale\n" in out
    line = f"{B}: spec digest "
    assert any(x.startswith("    " + line) and f"({new[:7]})" in x and "changed:" in x for x in out.splitlines())
    assert world.l4("status", "p1", "--json") == 0
    review = json.loads(capsys.readouterr().out)["plans"][0]["review"]
    assert review["state"] == "stale" and len(review["stale"]) == 1 and review["stale"][0].startswith(line)


def test_a_prompt_change_names_both_versions(world, capsys):
    reviewed_with_revs(world, version=PROMPT_VERSION - 1)
    err = refused(world, capsys)
    assert (
        f"  review prompt {PROMPT_VERSION - 1} at the review, {PROMPT_VERSION} in this harness: every subject is "
        "judged again"
    ) in err
    assert err.rstrip().endswith("Fix: l4 yolo review p1")


def test_an_older_review_without_revisions_names_no_file(world, capsys):
    reviewed_with_revs(world, revs=False)
    before = world.digest(B)
    new = edit_b(world)
    err = refused(world, capsys)
    assert (
        f"  {B}: spec digest {before[:8]} at the review, {world.digest(B)[:8]} now on origin/main ({new[:7]})\n" in err
    )
    assert "changed:" not in err


def test_review_names_the_stale_causes_before_it_asks_ci(world, capsys):
    reviewed_with_revs(world)
    new = edit_b(world)
    capsys.readouterr()
    assert world.l4("review", "p1", "--no-run") == 0
    out = capsys.readouterr().out
    assert out.startswith(f"p1: the recorded review is stale against origin/main ({new[:7]}):\n  {B}: spec digest ")
    assert out.index("the recorded review is stale") < out.index("review requested")
    assert "local:" not in out


# --- the plan file that is not on origin (M5, SCN-YOLO-182) ---------------------------------------------------------


def commit_plan_locally(world, *, stage: bool = True) -> None:
    world.pull()
    path = world.app.repo / PLAN
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan_doc(), indent=2), encoding="utf-8")
    if stage:
        world.clone.run("add", PLAN)
        world.clone.run("commit", "-q", "-m", "plan")


def test_a_plan_file_only_in_head_says_push(world, capsys):
    commit_plan_locally(world)
    capsys.readouterr()
    assert world.l4("check", "p1") == 2
    err = capsys.readouterr().err
    sha = origin_sha(world)
    assert f"check: no plan file {PLAN} on origin/main ({sha[:7]})\n" in err
    assert err.rstrip().endswith("Fix: git push origin HEAD:main, then run the command again")


def test_a_plan_file_only_in_the_working_tree_says_commit_and_push(world, capsys):
    commit_plan_locally(world, stage=False)
    capsys.readouterr()
    assert world.l4("check", "p1") == 2
    err = capsys.readouterr().err
    assert err.rstrip().endswith(f"Fix: commit and push {PLAN}, then run the command again")


def test_no_plan_file_anywhere_keeps_the_old_text(world, capsys):
    capsys.readouterr()
    assert world.l4("check", "p1") == 2
    err = capsys.readouterr().err.strip()
    assert err.endswith(f"check: no plan file {PLAN} on origin/main ({origin_sha(world)[:7]})") and "Fix:" not in err
