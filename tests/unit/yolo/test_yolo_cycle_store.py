"""review-resolution 3.5b: the plan step's `PlanStore` knows the forge a refused push is explained for."""

import l4.yolo.cycle as cycle
from l4.forge.pushfail import push_platform

from .yolo_cycle_world import CycleWorld


def test_the_plan_store_of_the_step_gets_the_platform_of_the_push(tmp_path):
    world = CycleWorld(tmp_path)
    store = cycle._store(world.app, world.cfg, world.git, "p1")
    assert store._platform == push_platform(world.cfg, world.app.environ, world.app.repo)


def test_the_platform_is_asked_with_the_config_the_environment_and_the_repository(tmp_path, monkeypatch):
    world = CycleWorld(tmp_path)
    seen = []

    def fake(cfg, environ, repo):
        seen.append((cfg, environ, repo))
        return "azure"

    monkeypatch.setattr(cycle, "push_platform", fake)
    assert cycle._store(world.app, world.cfg, world.git, "p1")._platform == "azure"
    assert seen == [(world.cfg, world.app.environ, world.app.repo)]
