import os
import subprocess
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.doctor.context import system_context
from l4.doctor.fix import TrackedFilesChanged, apply_fixes
from l4.doctor.registry import SAFE_FIX_KINDS, Check, CheckResult, Fix, Registry, run_checks
from l4.exitcodes import ExitCode
from l4.provision.runner import FixAction


def action(tool: str, status: str = "applied") -> FixAction:
    return FixAction(tool, "test", "", (), False, status)  # type: ignore[arg-type]


class World:
    """A check that fails until its fix has run."""

    def __init__(self) -> None:
        self.fixed = False
        self.applied: list[str] = []

    def check(self, check_id: str) -> Check:
        return Check(check_id, check_id, "error", lambda c: CheckResult("pass" if self.fixed else "fail", "state"))

    def fix(self, kind="install", scope="provision", tool="t") -> Fix:
        def apply(_ctx):
            self.applied.append(tool)
            self.fixed = True
            return [action(tool)]

        return Fix(kind, scope, apply)  # type: ignore[arg-type]


def registry_with(world: World, *ids: str, fix: Fix) -> Registry:
    registry = Registry()
    for check_id in ids:
        registry.register(world.check(check_id))
        registry.attach_fix(check_id, fix)
    return registry


def test_fixed_checks_are_rerun_and_the_exit_code_is_the_state_after_fixing(make_ctx):
    ctx, _ = make_ctx()
    world = World()
    registry = registry_with(world, "T-1", fix=world.fix())
    before = run_checks(ctx, registry=registry)
    assert before[0].status == "fail"
    ran = apply_fixes(ctx, before, registry, ci=False)
    assert [o.status for o in ran.outcomes] == ["pass"]
    assert [a.status for a in ran.actions] == ["applied"]


def test_a_passing_check_reports_what_is_in_place_without_applying(make_ctx):
    """`doctor --fix` on a provisioned runner must still say `already present` (plan line 'fix2')."""
    ctx, _ = make_ctx()
    world = World()
    world.fixed = True
    fix = world.fix()
    surveyed = Fix(fix.kind, fix.scope, fix.apply, lambda _ctx: [action("uv", "already present")])
    registry = registry_with(world, "T-1", "T-2", fix=surveyed)
    ran = apply_fixes(ctx, run_checks(ctx, registry=registry), registry, ci=True)
    assert [a.status for a in ran.actions] == ["already present"]  # once, although two checks carry the fix
    assert world.applied == [] and ran.outcomes[0].status == "pass"


def test_one_fix_on_several_checks_runs_once(make_ctx):
    ctx, _ = make_ctx()
    world = World()
    registry = registry_with(world, "T-1", "T-2", "T-3", fix=world.fix())
    ran = apply_fixes(ctx, run_checks(ctx, registry=registry), registry, ci=False)
    assert world.applied == ["t"]
    assert all(o.status == "pass" for o in ran.outcomes)


def test_ci_applies_only_provisioning_fixes(make_ctx):
    ctx, _ = make_ctx()
    world = World()
    registry = registry_with(world, "T-1", fix=world.fix(kind="prune", scope="repo"))
    ran = apply_fixes(ctx, run_checks(ctx, registry=registry), registry, ci=True)
    assert world.applied == [] and ran.actions == [] and ran.outcomes[0].status == "fail"
    ran = apply_fixes(ctx, run_checks(ctx, registry=registry), registry, ci=False)
    assert world.applied == ["t"]


def test_unlisted_kinds_never_run(make_ctx):
    ctx, _ = make_ctx()
    world = World()
    registry = registry_with(world, "T-1", fix=world.fix(kind="format-disk"))
    apply_fixes(ctx, run_checks(ctx, registry=registry), registry, ci=False)
    assert world.applied == []
    assert "install" in SAFE_FIX_KINDS and "format-disk" not in SAFE_FIX_KINDS


def test_a_crashing_fix_is_reported_not_raised(make_ctx):
    ctx, _ = make_ctx()
    registry = Registry()
    registry.register(Check("T-1", "t", "error", lambda c: CheckResult("fail", "x")))

    def boom(_ctx):
        raise RuntimeError("nope")

    registry.attach_fix("T-1", Fix("install", "provision", boom))
    ran = apply_fixes(ctx, run_checks(ctx, registry=registry), registry, ci=False)
    assert [(a.status, a.message) for a in ran.actions] == [("failed", "RuntimeError")]
    assert ran.outcomes[0].status == "fail"


def test_attach_fix_needs_a_registered_check_and_refuses_a_second_fix():
    registry = Registry()
    world = World()
    with pytest.raises(KeyError):
        registry.attach_fix("T-9", world.fix())
    registry.register(world.check("T-1"))
    registry.attach_fix("T-1", world.fix())
    with pytest.raises(ValueError):
        registry.attach_fix("T-1", world.fix())


GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def git(repo: Path, *args: str) -> None:
    subprocess.run([*GIT, "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "openspec/changes/x").mkdir(parents=True)
    (root / "openspec/changes/x/tasks.md").write_text("- [ ] 1.1 a\n")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "seed")
    return root


def real_ctx(repo: Path):
    return system_context(repo, L4Config(), {**os.environ})


def test_safe_fixes_leave_tracked_files_clean(repo):
    world = World()
    registry = registry_with(world, "T-1", fix=world.fix())
    ctx = real_ctx(repo)
    (repo / "untracked.txt").write_text("new files are not tracked changes")
    ran = apply_fixes(ctx, run_checks(ctx, registry=registry), registry, ci=False)
    assert ran.outcomes[0].status == "pass"


def test_fix_touching_tracked_file_exits_1(repo):
    world = World()
    tasks = repo / "openspec/changes/x/tasks.md"

    def apply(_ctx):
        tasks.write_text("- [x] 1.1 a\n")
        world.fixed = True
        return [action("evil")]

    registry = Registry()
    registry.register(world.check("T-1"))
    registry.attach_fix("T-1", Fix("install", "provision", apply))
    ctx = real_ctx(repo)
    with pytest.raises(TrackedFilesChanged, match="openspec/changes/x/tasks.md") as err:
        apply_fixes(ctx, run_checks(ctx, registry=registry), registry, ci=False)
    assert err.value.code is ExitCode.INTERNAL_ERROR


def test_fix_editing_an_already_dirty_file_is_still_caught(repo):
    tasks = repo / "openspec/changes/x/tasks.md"
    tasks.write_text("- [ ] 1.1 a edited by a human\n")
    world = World()

    def apply(_ctx):
        tasks.write_text("- [ ] 1.1 a edited by a fix\n")
        return [action("evil")]

    registry = Registry()
    registry.register(world.check("T-1"))
    registry.attach_fix("T-1", Fix("install", "provision", apply))
    ctx = real_ctx(repo)
    with pytest.raises(TrackedFilesChanged):
        apply_fixes(ctx, run_checks(ctx, registry=registry), registry, ci=False)


def test_outside_a_git_repository_there_is_nothing_to_guard(tmp_path):
    world = World()
    registry = registry_with(world, "T-1", fix=world.fix())
    ctx = real_ctx(tmp_path)
    ran = apply_fixes(ctx, run_checks(ctx, registry=registry), registry, ci=False)
    assert ran.outcomes[0].status == "pass"
