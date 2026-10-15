# ruff: noqa: F811
"""Review round 4, area Z5: `l4 plan`, `l4 status` and the doctor read the plan files from the target the step reads
(LOW-5), `l4 yolo draft` syncs before it reads phases (4)."""

import json

from l4.config.redaction import load_app_config
from l4.vcs.git import Git
from l4.yolo.commands import auto_merge_plan_active, plan_lines

from .yolo_cmd_world import A, B, ev, plan_doc, world  # noqa: F401

ACTIVATED = dict(plan_digest="x", digests={}, by="a", reason="r", limits={})


def fetch_plan(world, plan_id="p1"):
    world.clone.run("fetch", "origin", f"+refs/l4/plans/{plan_id}:refs/l4/plans/{plan_id}")


def behind_target(world, doc=None):
    """The target has the plan file; the clone's HEAD is a local branch (older commit) that lacks it."""
    world.pull()
    world.clone.run("checkout", "--quiet", "-b", "local")
    world.push_plan(doc)
    world.clone.run("fetch", "--quiet", "origin")
    assert not (world.app.repo / ".l4/plans/p1.json").exists()


def ahead_of_target(world, doc=None):
    """The clone's HEAD (a local branch) has a plan file the target does not."""
    world.pull()
    world.clone.run("checkout", "--quiet", "-b", "local")
    plan = world.app.repo / ".l4/plans/p1.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(json.dumps(doc or plan_doc()), encoding="utf-8")
    world.clone.run("add", "-A")
    world.clone.run("commit", "--quiet", "-m", "local plan")
    world.clone.run("fetch", "--quiet", "origin")


def plan_json(world, capsys):
    capsys.readouterr()
    assert world.l4_raw("plan", "--json") == 0
    out = capsys.readouterr().out
    return {u["unit"]: u for u in json.loads(out)["units"]}


def test_l4_plan_holds_units_by_the_plan_file_of_the_target_not_the_working_tree(world, capsys):
    behind_target(world)
    world.seed("p1", ev("plan.activated", **ACTIVATED), ev("unit.dispatched", unit=A))
    fetch_plan(world)
    rows = plan_json(world, capsys)
    assert "waits for" in rows[B]["reason"] and rows[B]["actionable"] is False


def test_l4_plan_does_not_hold_by_a_plan_file_only_the_working_tree_has(world, capsys):
    ahead_of_target(world)
    world.seed("p1", ev("plan.activated", **ACTIVATED), ev("unit.dispatched", unit=A))
    fetch_plan(world)
    rows = plan_json(world, capsys)
    assert "plan" not in rows[B]["reason"] and "waits for" not in rows[B]["reason"]


def test_the_status_line_counts_units_by_the_plan_file_of_the_target(world):
    behind_target(world)
    world.seed("p1", ev("plan.activated", **ACTIVATED))
    fetch_plan(world)
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    assert plan_lines(app.repo, git, {}, cfg) == ["plan p1: active, 0/2 integrated, $0.00/$40.00"]


def test_the_merge_mode_comes_from_the_plan_file_of_the_target(world):
    behind_target(world, plan_doc(merge="auto"))
    world.seed("p1", ev("plan.activated", **ACTIVATED))
    fetch_plan(world)
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    assert auto_merge_plan_active(app.repo, git, cfg) is True


# --- 4: l4 yolo draft syncs before it reads the phases ---------------------------------------------------------

UNIT_REF = "refs/remotes/origin/l4/openspec/add-b"
OLD = "the phases may be old"


def push_unit_branch(world):
    """A unit branch and a lock ref that exist on the origin only: what a fresh clone has not fetched."""
    seeder = world.remote_clone()
    seeder.run("fetch", "--quiet", "origin")
    seeder.run(
        "push",
        "--quiet",
        "origin",
        "origin/main:refs/heads/l4/openspec/add-b",
        "origin/main:refs/l4/locks/openspec/add-b",
    )
    assert world.clone.rev_parse(UNIT_REF) is None


def seen_at_discover(world, monkeypatch):
    """What the clone had when draft first read the phases."""
    import l4.yolo.commands as commands

    seen = {}
    real = commands.discover

    def discover(cfg, git, providers, wanted=()):
        seen["branch"] = git.rev_parse(UNIT_REF)
        seen["lock"] = git.rev_parse("refs/l4/locks/openspec/add-b")
        return real(cfg, git, providers, wanted)

    monkeypatch.setattr(commands, "discover", discover)
    return seen


def test_draft_fetches_the_unit_refs_before_it_reads_the_phases(world, monkeypatch, capsys):
    push_unit_branch(world)
    seen = seen_at_discover(world, monkeypatch)
    assert world.l4("draft", "p1") == 0
    assert seen["branch"] is not None and seen["lock"] is not None
    assert OLD not in capsys.readouterr().out


def test_draft_with_no_origin_goes_on_and_says_the_phases_may_be_old(world, monkeypatch, capsys):
    world.clone.run("remote", "remove", "origin")
    assert world.l4("draft", "p1") == 0
    out = capsys.readouterr().out
    assert [line for line in out.splitlines() if OLD in line] == [
        "draft: no origin to fetch from: the phases may be old"
    ]
    assert (world.app.repo / ".l4/plans/p1.json").exists()


def test_draft_whose_fetch_fails_goes_on_and_says_the_phases_may_be_old(world, capsys):
    world.clone.run("remote", "set-url", "origin", str(world.root / "no-such-remote"))
    assert world.l4("draft", "p1") == 0
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if OLD in line]
    assert (
        len(lines) == 1
        and lines[0].startswith("draft: could not fetch from origin")
        and "wrote .l4/plans/p1.json" in out
    )
