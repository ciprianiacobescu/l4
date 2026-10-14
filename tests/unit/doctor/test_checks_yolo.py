# ruff: noqa: F811
"""YOLO-001 (L4-YOLO-008, SCN-YOLO-17): `forge.merge_policy: auto` without an active `merge: auto` plan is a warning."""

import json
import os

from l4.config.schema import L4Config
from l4.doctor import checks_yolo
from l4.doctor.registry import REGISTRY
from l4.safepath import safe_path
from l4.vcs.git import Git

from ..yolo.yolo_cmd_world import A, ev, plan_doc, world  # noqa: F401


def auto_config() -> L4Config:
    return L4Config.model_validate({"forge": {"merge_policy": "auto"}})


def test_the_warning_without_a_plan(make_ctx, tmp_path):
    ctx, _ = make_ctx(cfg=auto_config(), PATH=safe_path(os.environ))  # git must run: the answer is "no plan refs"
    Git(ctx.repo, environ=ctx.env).run("init", "--quiet")
    result = checks_yolo._yolo_001(ctx)
    assert result.status == "fail"
    assert (
        result.message == "forge.merge_policy: auto has no effect without an active plan with merge: auto (L4-YOLO-008)"
    )


def test_it_is_a_warning_never_an_error():
    assert checks_yolo.YOLO_001.severity == "warn"
    assert any(c.id == "YOLO-001" for c in REGISTRY.checks())


def test_no_row_for_a_human_merge_policy(make_ctx):
    ctx, _ = make_ctx(cfg=L4Config())
    assert checks_yolo._yolo_001(ctx).status == "skip"


def test_a_plan_with_merge_auto_that_is_active_clears_it(world):
    from l4.doctor.context import DoctorContext

    doc = plan_doc({A: []}, merge="auto")
    world.push_plan(doc)
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, by="a", reason="r", limits={}))
    world.pull()
    world.clone.run("fetch", "origin", "+refs/l4/plans/p1:refs/l4/plans/p1")
    ctx = DoctorContext(
        world.app.repo, auto_config(), world.app.environ, lambda n: None, lambda *a, **k: None, (3, 12, 0)
    )
    assert checks_yolo._yolo_001(ctx).status == "pass"


def test_a_cancelled_or_human_plan_does_not(world):
    from l4.doctor.context import DoctorContext

    world.push_plan(plan_doc({A: []}))  # merge: human
    world.seed("p1", ev("plan.activated", plan_digest="x", digests={}, by="a", reason="r", limits={}))
    world.pull()
    world.clone.run("fetch", "origin", "+refs/l4/plans/p1:refs/l4/plans/p1")
    ctx = DoctorContext(
        world.app.repo, auto_config(), world.app.environ, lambda n: None, lambda *a, **k: None, (3, 12, 0)
    )
    assert checks_yolo._yolo_001(ctx).status == "fail"
    assert json.dumps(world.kinds())  # the ledger is there; only its merge mode decides
