"""D9 `run_profile` (L4-YOLO-009): a detached worktree at a revision, the gate kinds of a profile through the existing
gate runner, `all` and `none`, a profile with nothing to run is an error, and the worktree is always removed."""

from pathlib import Path

import pytest

from l4.yolo import postcheck
from l4.yolo.postcheck import run_profile

from .yolo_review_world import World, make_cfg

JUNIT = (
    'sh -c \'mkdir -p .l4-out && printf "<testsuite tests=\\"1\\"><testcase classname=\\"a\\" name=\\"b\\"/>'
    "</testsuite>\" > .l4-out/junit.xml'"
)
HAS_MARKER = "sh -c 'test -f marker.txt'"


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.rev = w.commit({"marker.txt": "x\n", "README.md": "r\n"})
    return w


def cfg(**gates):
    return make_cfg(gates={"setup": [], "test": {"command": ""}, **gates})


def run(world, config, profile, *, rev=None, **kw):
    return run_profile(world.app, config, world.git, rev or world.rev, profile, **kw)


def leftovers(world) -> list[str]:
    listed = world.git.run("worktree", "list", "--porcelain").stdout
    extra = [line for line in listed.splitlines() if line.startswith("worktree ") and line != f"worktree {world.repo}"]
    area = world.root / "cache" / "yolo" / "postcheck"
    return extra + ([str(p) for p in area.iterdir()] if area.is_dir() else [])


def test_a_passing_profile_runs_its_gates_at_the_revision(world):
    result = run(world, cfg(lint=[HAS_MARKER]), "fast", profiles={"fast": ["lint"]})
    assert result.status == "pass" and result.profile == "fast" and result.revision == world.rev
    assert [g.name for g in result.gates] == ["lint"] and result.gates[0].status == "pass"
    assert leftovers(world) == []


def test_the_gate_sees_the_revision_not_the_checkout(world):
    old = world.rev
    world.git.run("rm", "--quiet", "marker.txt")
    new = world.commit({"other.txt": "o\n"})
    config = cfg(lint=[HAS_MARKER])
    assert run(world, config, "p", rev=old, profiles={"p": ["lint"]}).status == "pass"
    failed = run(world, config, "p", rev=new, profiles={"p": ["lint"]})
    assert failed.status == "fail" and failed.revision == new
    assert (world.repo / "other.txt").exists() and leftovers(world) == []  # the checkout is untouched


def test_a_failing_gate_fails_the_profile_and_stops_the_rest(world):
    config = cfg(lint=["sh -c 'exit 3'"], typecheck=[HAS_MARKER])
    result = run(world, config, "p", profiles={"p": ["lint", "typecheck"]})
    assert result.status == "fail"
    assert [(g.name, g.status) for g in result.gates] == [("lint", "fail")]
    assert "lint" in result.detail and "exit code 3" in result.detail
    assert leftovers(world) == []


def test_all_runs_every_configured_gate_kind_in_order(world):
    config = cfg(
        setup=[HAS_MARKER], build=[HAS_MARKER], lint=[HAS_MARKER], typecheck=[HAS_MARKER],
        test={"command": JUNIT}, extra=[{"name": "audit", "command": HAS_MARKER}],
    )  # fmt: skip
    result = run(world, config, "all")
    assert result.status == "pass", result.detail
    assert [g.name for g in result.gates] == ["setup", "build", "lint", "typecheck", "test", "extra:audit"]


def test_a_test_gate_that_runs_no_test_does_not_pass(world):
    result = run(world, cfg(test={"command": "sh -c 'true'"}), "all")
    assert result.status == "fail" and "report missing" in result.detail


def test_a_named_profile_runs_only_its_kinds(world):
    config = cfg(lint=["sh -c 'exit 1'"], typecheck=[HAS_MARKER])
    result = run(world, config, "types", profiles={"types": ["typecheck"]})
    assert result.status == "pass" and [g.name for g in result.gates] == ["typecheck"]


def test_an_extra_gate_is_named_and_a_not_required_one_does_not_fail(world):
    config = cfg(
        extra=[{"name": "slow", "command": "sh -c 'exit 1'", "required": False}, {"name": "ok", "command": HAS_MARKER}]
    )
    result = run(world, config, "p", profiles={"p": ["extra:slow", "extra:ok"]})
    assert result.status == "pass" and [(g.name, g.status) for g in result.gates] == [
        ("extra:slow", "fail"), ("extra:ok", "pass"),
    ]  # fmt: skip


@pytest.mark.parametrize(
    "profile, profiles",
    [("none", {}), ("empty", {"empty": []}), ("unset", {"unset": ["lint", "extra:nothing"]}), ("all", {})],
)
def test_a_profile_with_no_gate_to_run_is_an_error_never_a_pass(world, profile, profiles):
    result = run(world, cfg(), profile, profiles=profiles)  # nothing is configured
    assert result.status == "error" and result.gates == ()
    assert result.detail == f"profile {profile} has no gate to run"
    assert leftovers(world) == []


def test_an_unknown_profile_is_an_error(world):
    result = run(world, cfg(lint=[HAS_MARKER]), "nope", profiles={"fast": ["lint"]})
    assert result.status == "error" and "nope" in result.detail and "unknown" in result.detail


def test_a_kind_that_is_not_a_gate_kind_is_an_error(world):
    result = run(world, cfg(lint=[HAS_MARKER]), "p", profiles={"p": ["lint", "deploy"]})
    assert result.status == "error" and "deploy" in result.detail


def test_a_skipped_kind_is_named_in_the_detail_of_a_pass(world):
    result = run(world, cfg(lint=[HAS_MARKER]), "p", profiles={"p": ["lint", "build"]})
    assert result.status == "pass" and "build" in result.detail and "not configured" in result.detail


def test_an_e2e_gate_that_needs_a_server_is_an_error_not_a_pass(world):
    config = cfg(e2e={"command": "sh -c 'true'", "serve": {"command": "sleep 5", "ready_url": "http://x"}})
    result = run(world, config, "p", profiles={"p": ["e2e"]})
    assert result.status == "error" and "server" in result.detail


def test_an_unknown_revision_is_an_error_and_makes_no_worktree(world):
    result = run(world, cfg(lint=[HAS_MARKER]), "p", rev="0" * 40, profiles={"p": ["lint"]})
    assert result.status == "error" and "revision" in result.detail and leftovers(world) == []


def test_the_worktree_is_removed_when_the_gate_runner_raises(world, monkeypatch):
    seen: list[Path] = []

    def boom(spec, *, worktree, **kw):
        seen.append(worktree)
        assert worktree.is_dir() and (worktree / "marker.txt").is_file()  # it ran in the detached checkout
        raise RuntimeError("the runner crashed")

    monkeypatch.setattr(postcheck, "run_gate", boom)
    result = run(world, cfg(lint=[HAS_MARKER]), "p", profiles={"p": ["lint"]})
    assert result.status == "error" and "the runner crashed" in result.detail
    assert seen and not seen[0].exists() and leftovers(world) == []


def test_the_profiles_come_from_the_config_when_it_has_them(world):
    config = cfg(lint=[HAS_MARKER])
    object.__setattr__(config, "yolo", type("Y", (), {"profiles": {"fast": ["lint"]}})())
    assert run(world, config, "fast").status == "pass"
