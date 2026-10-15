# ruff: noqa: F811
"""adoption-lessons 1.2 for the plan store: a denied push of the plan ref is explained for the forge of the repository
(`push_platform`), not for GitLab by default."""

import pytest
import yaml

from l4.forge.pushfail import PushFailed
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.yolo.commands import _open
from l4.yolo.model import PlanEvent

from .yolo_cmd_world import world  # noqa: F401


def denied(world, monkeypatch, store):
    real = Git.run

    def run(self, *argv, **kw):
        if argv and argv[0] == "push":
            raise GitError(list(argv), 1, "remote: Permission denied\n")
        return real(self, *argv, **kw)

    monkeypatch.setattr(Git, "run", run)
    with pytest.raises(PushFailed) as caught:
        store.append([PlanEvent("plan.cancelled", "2026-10-14T10:00:00Z", {"by": "a", "reason": "r"})], expect=None)
    return str(caught.value)


@pytest.mark.parametrize(("forge_type", "text"), [("github", "contents: write"), ("gitlab", "write_repository")])
def test_the_command_store_explains_a_denied_push_for_the_forge(world, monkeypatch, forge_type, text):
    config = yaml.safe_load(world.app.config_path.read_text(encoding="utf-8"))
    config["forge"]["type"] = forge_type
    world.app.config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    store = _open(world.app).store("p1")
    assert text in denied(world, monkeypatch, store)


def test_the_intake_is_told_the_real_base_branch(world, monkeypatch):
    """adoption-lessons 3.1: the hint names `forge.base_branch`, not "the base branch"."""
    import l4.yolo.commands as commands

    seen = {}
    real = commands.unit_infos

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(commands, "unit_infos", spy)
    world.push_plan()
    world.l4("check", "p1")
    assert seen["target"] == "main"
