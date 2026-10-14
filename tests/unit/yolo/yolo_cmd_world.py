"""A world for the `l4 yolo` command tests: the `openspec-basic` simulation repository (a bare origin and a clone, forge
`local`), a second unit, plan files pushed to the base branch, plan ledgers seeded on the origin, and a runner for the
CLI. No network, no model."""

import json
from pathlib import Path

import yaml

from l4.cli import main
from l4.sim.builtin.manifest import scenario_text
from l4.sim.remote import SimRepo
from l4.sim.runner import CONFIG_FILE, sim_app, sim_config
from l4.sim.scenarios import load_scenario
from l4.vcs.git import Git
from l4.yolo.digest import plan_digest, unit_digest
from l4.yolo.model import PlanEvent
from l4.yolo.store import PlanStore

A, B = "openspec:add-greeting", "openspec:add-b"
SPEC_B = (
    "## ADDED Requirements\n\n### Requirement: B counts\nThe `count()` function SHALL return 1.\n\n"
    "#### Scenario: Counting\n- **WHEN** `count()` is called\n- **THEN** it returns 1\n"
)


def plan_doc(units: dict[str, list[str]] | None = None, **over) -> dict:
    units = units if units is not None else {A: [], B: [A]}
    doc = {
        "schema": "l4/delivery-plan@1",
        "plan_id": "p1",
        "target": "main",
        "merge": "human",
        "limits": {"max_cost_usd": 40, "max_runs": 60},
        "batches": [{"id": "b1", "units": [{"id": u, "depends_on": d} for u, d in units.items()]}],
    }
    doc.update(over)
    return doc


class CmdWorld:
    def __init__(self, tmp_path: Path, *, merge_policy: str = "human") -> None:
        self.sim = SimRepo.create("openspec-basic", root=tmp_path / "world")
        root = self.sim.root.resolve()
        config = sim_config(load_scenario(scenario_text("happy-openspec"), source="happy-openspec.yaml"))
        config["forge"]["merge_policy"] = merge_policy
        (root / CONFIG_FILE).write_text(yaml.safe_dump(config), encoding="utf-8")
        self.root, self.app = root, sim_app(root)
        self.clone = Git(self.app.repo, environ=self.app.environ)
        self.clone.run("config", "user.email", "alex@example.com")
        self.remote = Git(self.sim.remote, environ=self.app.environ)
        self.unit_b()

    def unit_b(self) -> None:
        self.push(
            {
                "openspec/changes/add-b/tasks.md": "## 1. B\n\n- [ ] 1.1 Add `count()`\n",
                "openspec/changes/add-b/proposal.md": "# B\n",
                "openspec/changes/add-b/specs/b/spec.md": SPEC_B,
            },
            "unit b",
        )

    def push(self, files: dict[str, str], message: str = "change") -> str:
        return self.sim.human_commit(files, message)

    def push_plan(self, doc: dict | str | None = None, plan_id: str = "p1") -> str:
        text = doc if isinstance(doc, str) else json.dumps(doc if doc is not None else plan_doc(), indent=2)
        self.plan_text = text
        return self.push({f".l4/plans/{plan_id}.json": text}, f"plan {plan_id}")

    def pull(self) -> None:
        self.clone.run("pull", "--quiet", "--ff-only", "origin", "main")

    def store(self, plan_id: str = "p1", git: Git | None = None) -> PlanStore:
        return PlanStore(git or self.remote_clone(), plan_id)

    def remote_clone(self) -> Git:
        """A clone of its own for seeding ledgers, so that the clone under test fetches them like an operator does."""
        path = self.root / "seeder"
        if not path.exists():
            self.clone.run("clone", "--quiet", str(self.sim.remote), str(path))
        return Git(path, environ=self.app.environ)

    def seed(self, plan_id: str, *events: PlanEvent) -> str:
        store = self.store(plan_id)
        return store.append(list(events), expect=store.read().head)

    def events(self, plan_id: str = "p1") -> list[PlanEvent]:
        return self.store(plan_id).read().events

    def kinds(self, plan_id: str = "p1") -> list[str]:
        return [e.type for e in self.events(plan_id)]

    def digest(self, unit_id: str) -> str:
        name = unit_id.split(":", 1)[1]
        return unit_digest(self.remote, "main", f"openspec/changes/{name}")

    def reviewed(self, verdicts: dict[str, str] | None = None, findings: dict[str, list] | None = None) -> PlanEvent:
        """`plan.reviewed` for the pushed plan file and the units as they are on the origin now."""
        units = {A: "READY", B: "READY", **(verdicts or {})}
        return PlanEvent(
            "plan.reviewed",
            "2026-10-14T10:00:00Z",
            {
                "plan_digest": plan_digest(self.plan_text),
                "units": {
                    u: {"verdict": v, "digest": self.digest(u), "findings": (findings or {}).get(u, [])}
                    for u, v in units.items()
                },
                "batches": {"b1": {"verdict": "READY", "digest": None, "findings": []}},
            },
        )

    def l4(self, *argv: str) -> int:
        args = ["yolo", *argv, "--repo", str(self.app.repo), "--config", str(self.app.config_path)]
        return main(args, environ=dict(self.app.environ))

    def l4_raw(self, *argv: str) -> int:
        args = [*argv, "--repo", str(self.app.repo), "--config", str(self.app.config_path)]
        return main(args, environ=dict(self.app.environ))


def ev(kind: str, **data) -> PlanEvent:
    return PlanEvent(kind, "2026-10-14T10:00:00Z", data)


# --- fixtures (imported by the test modules) -----------------------------------------------------------------------

import pytest  # noqa: E402

from l4.forge.local import LocalForge  # noqa: E402
from l4.sim.fakes import fake_openspec_cli  # noqa: E402


@pytest.fixture
def world(tmp_path):
    with fake_openspec_cli():
        yield CmdWorld(tmp_path)


@pytest.fixture
def auto_world(tmp_path):
    with fake_openspec_cli():
        yield CmdWorld(tmp_path, merge_policy="auto")


@pytest.fixture
def forge(monkeypatch):
    """The forge `start_run` reaches (the operator commands share `l4.state.retry.start_run_line`)."""
    local = LocalForge()
    monkeypatch.setattr("l4.state.retry.make_forge", lambda *a, **k: local)
    return local
