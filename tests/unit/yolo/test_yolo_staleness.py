"""The staleness module on a scratch git repository with a bare origin (yolo-guardrails D1, D2; L4-YOLO-068)."""

import pytest

from l4.vcs.git import Git
from l4.vcs.names import unit_branch
from l4.yolo import staleness as st
from l4.yolo.digest import MISSING, file_digests, plan_digest, unit_digest
from l4.yolo.model import PlanEvent, PlanState
from l4.yolo.readiness import PROMPT_VERSION

from .yolo_review_world import World, make_cfg, plan_of

FOLDER = "openspec/changes/a"
UNIT = "openspec:a"
PLAN_PATH = ".l4/plans/p1.json"
TARGET = "refs/remotes/origin/main"


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    bare = tmp_path / "origin.git"
    Git(tmp_path, environ=w.git.env).run("init", "--quiet", "--bare", "-b", "main", str(bare))
    w.git.run("remote", "add", "origin", str(bare))
    return w


def push(w: World, files: dict[str, str], message: str = "c") -> str:
    sha = w.commit(files, message)
    w.git.run("push", "--quiet", "origin", "HEAD:main")
    return sha


def test_file_digests_leave_out_the_harness_files_and_read_task_marks_as_open(world):
    first = world.commit(
        {
            f"{FOLDER}/tasks.md": "- [ ] 1.1 T\n",
            f"{FOLDER}/spec.md": "s\n",
            f"{FOLDER}/verification.md": "v\n",
            f"{FOLDER}/.l4/x": "x\n",
        }
    )
    second = world.commit({f"{FOLDER}/tasks.md": "- [x] 1.1 T\n"})
    before = file_digests(world.git, first, FOLDER)
    assert sorted(before) == ["spec.md", "tasks.md"]
    assert file_digests(world.git, second, FOLDER)["tasks.md"] == before["tasks.md"]
    assert unit_digest(world.git, first, FOLDER) == unit_digest(world.git, second, FOLDER)


def test_changed_files_lists_added_removed_and_changed_sorted_and_relative(world):
    first = world.commit({f"{FOLDER}/tasks.md": "- [ ] 1.1 T\n", f"{FOLDER}/b.md": "b\n", f"{FOLDER}/c.md": "c\n"})
    (world.repo / FOLDER / "c.md").unlink()
    second = world.commit({f"{FOLDER}/b.md": "b2\n", f"{FOLDER}/a.md": "a\n", f"{FOLDER}/tasks.md": "- [x] 1.1 T\n"})
    assert st.changed_files(world.git, first, second, FOLDER) == [f"{FOLDER}/a.md", f"{FOLDER}/b.md", f"{FOLDER}/c.md"]
    ticked = world.commit({f"{FOLDER}/tasks.md": "- [-] 1.1 T\n"})
    assert st.changed_files(world.git, second, ticked, FOLDER) == []
    assert st.changed_files(world.git, "0" * 40, ticked, FOLDER) is None
    assert st.changed_files(world.git, None, ticked, FOLDER) is None
    assert st.changed_files(world.git, first, ticked, "openspec/changes/none") == []


def test_divergence_equal_ahead_behind_and_diverged(world):
    base = push(world, {f"{FOLDER}/proposal.md": "p\n", "other.txt": "o\n"})
    assert st.divergence(world.git, TARGET, [FOLDER]) is None
    assert st.divergence(world.git, "refs/remotes/origin/nope") is None
    ahead = world.commit({f"{FOLDER}/proposal.md": "p2\n"})
    d = st.divergence(world.git, TARGET, [PLAN_PATH, FOLDER, "other.txt"])
    assert (d.head, d.origin, d.ahead, d.behind, d.paths) == (ahead, base, 1, 0, (FOLDER,))
    assert st.divergence_text(d, "main") == (
        f"origin/main ({base[:7]}) is 1 commit behind HEAD ({ahead[:7]}); they differ in {FOLDER}"
    )
    assert st.divergence_verb(d) == "push"
    assert st.divergence_fix(d, "main", "l4 yolo review p1") == "git push origin HEAD:main, then l4 yolo review p1"
    none = st.divergence(world.git, TARGET, [PLAN_PATH])
    assert (
        none.paths == ()
        and st.divergence_text(none, "main") == f"origin/main ({base[:7]}) is 1 commit behind HEAD ({ahead[:7]})"
    )
    # behind: origin moves on in another clone
    world.git.run("reset", "--quiet", "--hard", base)
    other = world.root / "other"
    world.git.run("clone", "--quiet", str(world.root / "origin.git"), str(other))
    og = Git(other, environ=world.git.env)
    og.run("config", "user.name", "t")
    og.run("config", "user.email", "t@example.com")
    (other / "n1.txt").write_text("1\n")
    (other / "n2.txt").write_text("2\n")
    og.run("add", "-A")
    og.run("commit", "--quiet", "-m", "n")
    og.run("push", "--quiet", "origin", "HEAD:main")
    world.git.run("fetch", "--quiet", "origin")
    b = st.divergence(world.git, TARGET)
    assert (b.ahead, b.behind) == (0, 1)
    assert st.divergence_text(b, "main") == f"origin/main ({b.origin[:7]}) is 1 commit ahead of HEAD ({b.head[:7]})"
    assert st.divergence_verb(b) == "pull"
    assert st.divergence_fix(b, "main", "run the command again") == "git pull --ff-only, then run the command again"
    both_head = world.commit({"mine.txt": "m\n"})
    both = st.divergence(world.git, TARGET)
    assert (both.ahead, both.behind) == (1, 1)
    assert st.divergence_text(both, "main") == (
        f"HEAD ({both_head[:7]}) and origin/main ({both.origin[:7]}) have diverged: 1 commit only on HEAD, "
        f"1 only on origin/main"
    )
    assert st.divergence_verb(both) == "pull, then push"
    assert st.divergence_fix(both, "main", "go") == "git pull --rebase, then git push origin HEAD:main, then go"


def test_plurals_and_the_and_k_more_cut(world):
    push(world, {"a.txt": "a\n"})
    world.commit({"p1.txt": "1\n"})
    world.commit({"p2.txt": "2\n"})
    paths = ["p1.txt", "p2.txt", "p3.txt", "p4.txt", "p5.txt"]
    world.commit({f"{p}": "x\n" for p in paths})
    d = st.divergence(world.git, TARGET, paths)
    assert d.ahead == 3 and len(d.paths) == 5
    text = st.divergence_text(d, "main")
    assert "is 3 commits behind HEAD" in text and text.endswith("they differ in p1.txt, p2.txt, p3.txt and 2 more")


def test_unit_change_and_plan_change_labels_where_and_missing(world):
    cfg = make_cfg()
    old = push(world, {f"{FOLDER}/spec.md": "one\n", f"{FOLDER}/tasks.md": "- [ ] 1.1 T\n"})
    new = push(world, {f"{FOLDER}/spec.md": "two\n"})
    d_old, d_new = unit_digest(world.git, old, FOLDER), unit_digest(world.git, new, FOLDER)
    text = st.unit_change(world.git, cfg, UNIT, FOLDER, d_old, d_new, old, TARGET, "at the review")
    assert text == (
        f"spec digest {d_old[:8]} at the review, {d_new[:8]} now on origin/main ({new[:7]}); changed: {FOLDER}/spec.md"
    )
    assert st.unit_change(world.git, cfg, UNIT, FOLDER, d_old, d_new, None, TARGET, "frozen at the activation") == (
        f"spec digest {d_old[:8]} frozen at the activation, {d_new[:8]} now on origin/main ({new[:7]})"
    )
    gone = st.unit_change(world.git, cfg, UNIT, FOLDER, d_old, MISSING, old, TARGET, "at the rejection")
    assert (
        gone == f"spec digest {d_old[:8]} at the rejection; its folder {FOLDER} has no files on origin/main ({new[:7]})"
    )
    assert st.plan_change("a" * 16, "b" * 16, "main", new, "at the review") == (
        f"digest aaaaaaaa at the review, bbbbbbbb now on origin/main ({new[:7]})"
    )
    # a unit with a branch on origin is read there
    branch = unit_branch(UNIT, cfg.forge.branch_prefix)
    world.git.run("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}")
    world.git.run("fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    text = st.unit_change(world.git, cfg, UNIT, FOLDER, d_old, d_new, old, TARGET, "at the review")
    assert f"now on its branch {branch} ({new[:7]})" in text


def reviewed_state(world, cfg, plan, text, *, at: str, version: int = PROMPT_VERSION):
    return PlanState(
        plan_id="p1",
        review_plan_digest=plan_digest(text),
        review_prompt_version=version,
        review_digests={UNIT: unit_digest(world.git, at, FOLDER)},
        review={UNIT: "READY"},
    )


def test_stale_reasons_in_order_and_empty_for_a_current_review(world):
    cfg, plan = make_cfg(), plan_of({UNIT: []})
    text = '{"plan": 1}\n'
    base = push(world, {PLAN_PATH: text, f"{FOLDER}/spec.md": "one\n"})
    state = reviewed_state(world, cfg, plan, text, at=base)
    event = PlanEvent("plan.reviewed", "2026-10-14T10:00:00Z", {"unit_revs": {UNIT: base}})
    now = {UNIT: unit_digest(world.git, base, FOLDER)}
    folders = {UNIT: FOLDER}
    args = (world.git, cfg, plan, text, PLAN_PATH, state, [event], now, TARGET, folders)
    assert st.stale_reasons(*args) == []
    # the five causes
    state.review_prompt_version = PROMPT_VERSION - 1
    new_text = '{"plan": 2}\n'
    new = push(world, {PLAN_PATH: new_text, f"{FOLDER}/spec.md": "two\n"})
    local = world.commit({f"{FOLDER}/proposal.md": "unpushed\n"})
    now = {UNIT: unit_digest(world.git, new, FOLDER), "openspec:b": "c" * 16}
    state.review = {}
    plan2 = plan_of({UNIT: [], "openspec:b": []}, batches=[("b1", [UNIT, "openspec:b"])])
    lines = st.stale_reasons(world.git, cfg, plan2, new_text, PLAN_PATH, state, [event], now, TARGET, folders)
    d_old, d_new = state.review_digests[UNIT][:8], now[UNIT][:8]
    assert lines[0] == (
        f"review prompt {PROMPT_VERSION - 1} at the review, {PROMPT_VERSION} in this harness: every subject is "
        "judged again"
    )
    assert lines[1] == (
        f"plan file {PLAN_PATH}: digest {plan_digest(text)[:8]} at the review, {plan_digest(new_text)[:8]} "
        f"now on origin/main ({new[:7]})"
    )
    assert lines[2] == (
        f"{UNIT}: spec digest {d_old} at the review, {d_new} now on origin/main ({new[:7]}); changed: {FOLDER}/spec.md"
    )
    assert lines[3] == "openspec:b: not judged by the review"
    assert lines[4] == "batch:b1: not judged by the review"
    assert lines[5].startswith("local: origin/main (") and lines[5].endswith(
        f"; they differ in {FOLDER}: push, then review"
    )
    assert f"HEAD ({local[:7]})" in lines[5] and len(lines) == 6
    # a prompt change that does not matter is not named
    quiet = st.stale_reasons(
        world.git, cfg, plan2, new_text, PLAN_PATH, state, [event], now, TARGET, folders, prompt_matters=False
    )
    assert all(not line.startswith("review prompt") for line in quiet)


def test_unit_revs_and_frozen_rev(world):
    cfg = make_cfg()
    sha = push(world, {f"{FOLDER}/spec.md": "x\n"})
    assert st.unit_revs(world.git, cfg, [UNIT], TARGET) == {UNIT: sha}
    assert st.unit_revs(world.git, cfg, [UNIT, "openspec:z"], TARGET, {UNIT: FOLDER}) == {UNIT: sha}
    events = [
        PlanEvent("plan.reviewed", "t", {"units": {UNIT: {"digest": "d1"}}, "unit_revs": {UNIT: "s1"}}),
        PlanEvent("plan.reviewed", "t", {"units": {UNIT: {"digest": "d2"}}, "unit_revs": {UNIT: "s2"}}),
    ]
    assert st.frozen_rev(events, UNIT, "d1") == "s1"
    assert st.frozen_rev(events, UNIT, "d2") == "s2"
    assert st.frozen_rev(events, UNIT, "zz") is None
    assert st.frozen_rev([PlanEvent("plan.reviewed", "t", {"units": {UNIT: {"digest": "d1"}}})], UNIT, "d1") is None
