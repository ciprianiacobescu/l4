"""PlanStore: the plan ref as a leased commit chain (L4-YOLO-006, L4-YOLO-015, SCN-YOLO-12)."""

import json
import stat

import pytest

from l4.yolo.model import PlanMoved
from l4.yolo.store import PlanStore, list_plans, plan_ref, receipt_path

from .yolo_ledger_world import ev, make_clone, make_origin, sh


@pytest.fixture
def world(tmp_path):
    origin = make_origin(tmp_path)
    return origin, make_clone(tmp_path, origin, "a"), make_clone(tmp_path, origin, "b")


def test_read_of_a_missing_ref_is_empty(world):
    _, a, _ = world
    got = PlanStore(a, "p1").read()
    assert got.head is None and got.events == [] and got.files == {}


def test_append_makes_a_root_commit_then_a_chain(world):
    origin, a, _ = world
    store = PlanStore(a, "p1")
    first = store.append([ev("plan.admitted", plan_digest="d1")], expect=None)
    second = store.append([ev("plan.reviewed"), ev("plan.waiting", reason="x")], expect=first)
    assert sh(origin, "rev-parse", "refs/l4/plans/p1") == second
    assert sh(origin, "rev-list", "--parents", "-n1", second).split()[1] == first
    assert sh(origin, "rev-list", "--parents", "-n1", first).split() == [first]  # a root commit
    got = store.read()
    assert got.head == second
    assert [e.type for e in got.events] == ["plan.admitted", "plan.reviewed", "plan.waiting"]
    assert got.events[0].data == {"plan_digest": "d1"}


def test_commits_are_the_bots_and_use_no_worktree(world):
    origin, a, _ = world
    head = PlanStore(a, "p1").append([ev("plan.admitted")], expect=None)
    assert sh(origin, "log", "-1", "--format=%an <%ae>|%cn", head).startswith(
        "l4-bot <l4-bot@users.noreply.invalid>|l4-bot"
    )
    assert sh(a.repo, "status", "--porcelain") == ""
    assert not any(h[1:2] == ["commit"] for h in a.history)  # plumbing only


def test_a_second_clone_reads_what_the_first_wrote(world):
    _, a, b = world
    PlanStore(a, "p1").append([ev("plan.admitted", plan_digest="d")], expect=None)
    got = PlanStore(b, "p1").read()
    assert [e.type for e in got.events] == ["plan.admitted"]


def test_files_are_kept_across_appends_and_replaced_on_demand(world):
    _, a, _ = world
    store = PlanStore(a, "p1")
    h1 = store.append(
        [ev("plan.admitted")], files={"report.md": "one\n", "receipts/openspec-a.json": "{}\n"}, expect=None
    )
    h2 = store.append([ev("plan.reviewed")], expect=h1)
    assert store.read().files == {"report.md": "one\n", "receipts/openspec-a.json": "{}\n"}
    store.append([ev("plan.stopped")], files={"report.md": "two\n"}, expect=h2)
    assert store.read().files["report.md"] == "two\n"
    assert store.read().files["receipts/openspec-a.json"] == "{}\n"


@pytest.mark.parametrize("path", ["ledger.jsonl", "../x", "/abs", "a//b", "a b"])
def test_append_refuses_a_bad_file_path(world, path):
    _, a, _ = world
    with pytest.raises(ValueError):
        PlanStore(a, "p1").append([ev("plan.admitted")], files={path: "x"}, expect=None)


def test_append_of_nothing_is_refused(world):
    _, a, _ = world
    with pytest.raises(ValueError):
        PlanStore(a, "p1").append([], expect=None)


def test_scn_yolo_12_two_writers_do_not_both_win_from_the_same_head(world):
    origin, a, b = world
    base = PlanStore(a, "p1").append([ev("plan.admitted")], expect=None)
    sa, sb = PlanStore(a, "p1"), PlanStore(b, "p1")
    assert sa.read().head == sb.read().head == base
    won = sa.append([ev("plan.reviewed", by="a")], expect=base)
    with pytest.raises(PlanMoved):
        sb.append([ev("plan.reviewed", by="b")], expect=base)
    assert sh(origin, "rev-parse", "refs/l4/plans/p1") == won
    events = PlanStore(b, "p1").read().events
    assert [(e.type, e.data.get("by")) for e in events] == [("plan.admitted", None), ("plan.reviewed", "a")]


def test_scn_yolo_12_two_writers_racing_to_create_the_ref(world):
    origin, a, b = world
    PlanStore(a, "p1").append([ev("plan.admitted", by="a")], expect=None)
    with pytest.raises(PlanMoved):
        PlanStore(b, "p1").append([ev("plan.admitted", by="b")], expect=None)
    assert [e.data["by"] for e in PlanStore(b, "p1").read().events] == ["a"]


def test_the_loser_reads_again_and_wins(world):
    _, a, b = world
    base = PlanStore(a, "p1").append([ev("plan.admitted")], expect=None)
    PlanStore(a, "p1").append([ev("plan.reviewed")], expect=base)
    sb = PlanStore(b, "p1")
    with pytest.raises(PlanMoved):
        sb.append([ev("plan.activated")], expect=base)
    again = sb.read()
    sb.append([ev("plan.activated")], expect=again.head)
    assert [e.type for e in sb.read().events] == ["plan.admitted", "plan.reviewed", "plan.activated"]


def test_a_lost_lease_pushes_nothing(world):
    origin, a, b = world
    base = PlanStore(a, "p1").append([ev("plan.admitted")], expect=None)
    PlanStore(b, "p1").read()
    PlanStore(a, "p1").append([ev("plan.reviewed")], expect=base)
    before = sh(origin, "rev-parse", "refs/l4/plans/p1")
    with pytest.raises(PlanMoved):
        PlanStore(b, "p1").append([ev("plan.cancelled")], expect=base)
    assert sh(origin, "rev-parse", "refs/l4/plans/p1") == before


def test_the_push_is_atomic_with_a_lease_on_the_read_head(world):
    _, a, _ = world
    store = PlanStore(a, "p1")
    h1 = store.append([ev("plan.admitted")], expect=None)
    store.append([ev("plan.reviewed")], expect=h1)
    pushes = [h for h in a.history if "push" in h]
    assert pushes[0][pushes[0].index("push") + 1 :][:2] == ["--atomic", "--force-with-lease=refs/l4/plans/p1:"]
    assert f"--force-with-lease=refs/l4/plans/p1:{h1}" in pushes[1]
    assert not any(arg.startswith("+") for h in pushes for arg in h)


def test_list_plans(world):
    _, a, b = world
    assert list_plans(b) == []
    PlanStore(a, "zeta").append([ev("plan.admitted")], expect=None)
    PlanStore(a, "alpha-1").append([ev("plan.admitted")], expect=None)
    assert list_plans(b) == ["alpha-1", "zeta"]
    assert PlanStore.list_plans(b) == ["alpha-1", "zeta"]


def test_plan_ref_refuses_a_bad_id():
    assert plan_ref("p-1") == "refs/l4/plans/p-1"
    with pytest.raises(ValueError):
        plan_ref("../x")


def test_a_ledger_line_that_is_not_an_event_is_an_error(world):
    origin, a, _ = world
    store = PlanStore(a, "p1")
    store.append([ev("plan.admitted")], files={"x.txt": "y"}, expect=None)
    blob = a.write_blob(b"not json\n")
    tree = a.run("mktree", input=f"100644 blob {blob}\tledger.jsonl\n").stdout.strip()
    bad = a.run("commit-tree", tree, "-m", "bad", config=(("user.name", "t"), ("user.email", "t@t"))).stdout.strip()
    a.run("update-ref", "refs/l4/plans/p2", bad)
    a.run("push", "origin", "refs/l4/plans/p2:refs/l4/plans/p2")
    with pytest.raises(ValueError, match="line 1"):
        PlanStore(a, "p2").read()
    assert json.loads(PlanStore(a, "p1").read().events[0].to_json())["type"] == "plan.admitted"


# --- receipts (D12, L4-YOLO-015) ---------------------------------------------------------------------------------


def _receipt(attempt=1, **over):
    return {"receipt_id": f"p1/openspec:a/{attempt}", "unit_id": "openspec:a", "plan_id": "p1", "pr": 7, **over}


def test_receipt_path_replaces_the_colon():
    assert receipt_path("kiro:my-spec") == "receipts/kiro-my-spec.json"


def test_a_receipt_is_written_once_per_receipt_id(world):
    origin, a, _ = world
    store = PlanStore(a, "p1")
    head = store.write_receipt(_receipt(), expect=None, events=[ev("unit.integrated", unit="openspec:a")])
    assert json.loads(store.read().files["receipts/openspec-a.json"])["pr"] == 7
    pushes_before = sum("push" in h for h in a.history)
    again = store.write_receipt(_receipt(pr=99), expect=head)
    assert again == head and sh(origin, "rev-parse", "refs/l4/plans/p1") == head  # no new commit
    assert sum("push" in h for h in a.history) == pushes_before
    assert json.loads(store.read().files["receipts/openspec-a.json"])["pr"] == 7


def test_a_repeated_receipt_still_appends_its_events(world):
    _, a, _ = world
    store = PlanStore(a, "p1")
    head = store.write_receipt(_receipt(), expect=None)
    new = store.write_receipt(_receipt(pr=99), expect=head, events=[ev("plan.completed", revision="r")])
    assert new != head
    got = store.read()
    assert [e.type for e in got.events] == ["plan.completed"]
    assert json.loads(got.files["receipts/openspec-a.json"])["pr"] == 7


def test_another_attempt_gets_its_own_receipt_content(world):
    _, a, _ = world
    store = PlanStore(a, "p1")
    head = store.write_receipt(_receipt(1), expect=None)
    store.write_receipt(_receipt(2, pr=8), expect=head)
    assert json.loads(store.read().files["receipts/openspec-a.json"])["receipt_id"] == "p1/openspec:a/2"


def test_a_refusal_that_is_not_a_lost_lease_is_a_clear_error_not_plan_moved(world):
    origin, a, _ = world
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'no pushes today' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    with pytest.raises(Exception, match="refs/l4/plans/p1") as caught:
        PlanStore(a, "p1").append([ev("plan.admitted")], expect=None)
    assert not isinstance(caught.value, PlanMoved)
    assert "no pushes today" in str(caught.value)


def test_auth_config_is_passed_to_fetch_and_push(world):
    _, a, _ = world
    config = (("credential.helper", ""),)
    store = PlanStore(a, "p1", config, push_config=(("remote.origin.pushurl", "file:///nowhere"),))
    with pytest.raises(Exception):  # noqa: B017,PT011 - the push URL is unreachable: the push config reached git
        store.append([ev("plan.admitted")], expect=None)
    fetches = [h for h in a.history if "fetch" in h]
    assert fetches == [] or "credential.helper=" in " ".join(fetches[0])
    assert any("remote.origin.pushurl=file:///nowhere" in " ".join(h) for h in a.history if "push" in h)


def test_a_refused_ledger_push_is_worded_for_the_platform(world):
    """adoption-lessons 1.2b (L4-ADO-004): the store passes its platform to `explain_push_failure`."""
    from l4.exitcodes import L4Exit
    from l4.vcs.git import Git, GitError

    _, a, _ = world
    real = Git.run

    def refuse(self, *args, **kwargs):
        if args and args[0] == "push":
            raise GitError(["git", "push"], 128, "error: The requested URL returned error: 403")
        return real(self, *args, **kwargs)

    store = PlanStore(a, "p1", token_env="GITHUB_TOKEN", environ={"GITHUB_TOKEN": "x"}, platform="github")
    import unittest.mock as mock

    with mock.patch.object(Git, "run", refuse), pytest.raises(L4Exit) as caught:
        store.append([ev("plan.admitted")], expect=None)
    assert "contents: write" in str(caught.value)


def _counting_hook(origin, message, *, failures):
    calls = origin / "calls"
    hook = origin / "hooks" / "pre-receive"
    hook.write_text(
        f"#!/bin/sh\nn=$(cat {calls} 2>/dev/null || echo 0)\nn=$((n+1))\necho $n > {calls}\n"
        f'if [ "$n" -le {failures} ]; then echo "{message}" >&2; exit 1; fi\nexit 0\n'
    )
    hook.chmod(0o755)
    return lambda: int(calls.read_text()) if calls.exists() else 0


def test_a_server_error_on_the_plan_push_is_tried_again_and_lands_the_ref(world):
    """L4-LCK-001: every harness push is tried again, the plan ledger's too."""
    origin, a, _ = world
    waits: list[float] = []
    a._sleep = waits.append
    calls = _counting_hook(origin, "fatal error in commit_refs_rules", failures=1)
    head = PlanStore(a, "p1").append([ev("plan.admitted")], expect=None)
    assert sh(origin, "rev-parse", "refs/l4/plans/p1") == head
    assert calls() == 2 and waits == [5.0]


def test_a_server_error_that_remains_on_the_plan_push_is_the_forges_not_plan_moved(world):
    origin, a, _ = world
    a._sleep = lambda seconds: None
    calls = _counting_hook(origin, "Internal Server Error", failures=9)
    with pytest.raises(Exception, match="refs/l4/plans/p1") as caught:
        PlanStore(a, "p1").append([ev("plan.admitted")], expect=None)
    assert not isinstance(caught.value, PlanMoved) and caught.value.transient is True
    assert "the harness tried 3 times" in str(caught.value) and calls() == 3


def test_a_lost_lease_on_the_plan_push_is_plan_moved_and_is_not_tried_again(world):
    origin, a, b = world
    waits: list[float] = []
    b._sleep = waits.append
    base = PlanStore(a, "p1").append([ev("plan.admitted")], expect=None)
    PlanStore(b, "p1").read()
    PlanStore(a, "p1").append([ev("plan.reviewed")], expect=base)
    pushes = sum(1 for h in b.history if "push" in h)
    with pytest.raises(PlanMoved):
        PlanStore(b, "p1").append([ev("plan.cancelled")], expect=base)
    assert waits == [] and sum(1 for h in b.history if "push" in h) == pushes + 1
