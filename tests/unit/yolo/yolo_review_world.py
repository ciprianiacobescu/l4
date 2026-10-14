"""A small world for the yolo tests of the readiness review and the post-merge profiles: a temporary git repository
with unit folders, a config whose judge and implementer are `fake` profiles, and an `AppContext` that points the
runner cache into the temporary folder. No network, no model."""

import json
import os
from pathlib import Path

from l4.config.schema import L4Config
from l4.context import AppContext
from l4.redact import Redactor
from l4.safepath import safe_path
from l4.vcs.git import Git
from l4.yolo.model import Plan, load_plan

SPEC_A = "## ADDED Requirements\n### Requirement: A greets\nThe service SHALL greet.\n#### Scenario: hello\n- WHEN x THEN y\n"
SPEC_B = "## ADDED Requirements\n### Requirement: B uses A\nB SHALL call A.\n#### Scenario: call\n- WHEN x THEN z\n"


def environment(root: Path) -> dict[str, str]:
    return {
        "PATH": safe_path(os.environ),
        "HOME": str(root / "home"),
        "L4_CACHE": str(root / "cache"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }


def make_cfg(**over) -> L4Config:
    base = {
        "version": 1,
        "sandbox": {"mode": "none", "allow_none": True},
        "forge": {"type": "local", "base_branch": "main"},
        "ci": {"platform": "local"},
        "profiles": {
            "impl": {"adapter": "fake", "vendor": "vendor-a"},
            "judge": {"adapter": "fake", "vendor": "vendor-b"},
        },
        "roles": {"implementer": ["impl"], "judges": ["judge"]},
        "gates": {"setup": [], "test": {"command": ""}},
    }
    base.update(over)
    return L4Config.model_validate(base)


def make_app(repo: Path, root: Path) -> AppContext:
    (root / "home").mkdir(exist_ok=True)
    return AppContext(repo, None, "human", 0, "r-20261014T1000Z-0001", environment(root), Redactor({}))


class World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.repo = root / "repo"
        self.repo.mkdir()
        self.git = Git(self.repo, environ=environment(root))
        self.git.run("init", "--quiet", "-b", "main")
        self.git.run("config", "user.name", "t")
        self.git.run("config", "user.email", "t@example.com")
        self.app = make_app(self.repo, root)

    def commit(self, files: dict[str, str], message: str = "c") -> str:
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self.git.run("add", "-A")
        self.git.run("commit", "--quiet", "-m", message)
        return self.git.rev_parse("HEAD") or ""


def plan_of(units: dict[str, list[str]], *, batches: list[tuple[str, list[str]]] | None = None) -> Plan:
    """A plan whose units (id -> depends_on) sit in one batch `b1`, or in the given batches (id, unit ids)."""
    groups = batches or [("b1", list(units))]
    doc = {
        "schema": "l4/delivery-plan@1",
        "plan_id": "p1",
        "target": "main",
        "merge": "human",
        "batches": [{"id": bid, "units": [{"id": u, "depends_on": units[u]} for u in ids]} for bid, ids in groups],
    }
    plan = load_plan(json.dumps(doc))
    assert isinstance(plan, Plan), plan
    return plan
