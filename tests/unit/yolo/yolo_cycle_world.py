"""A world for the plan step (`l4.yolo.cycle`): a bare origin, the checkout of `main` that is the harness's repository,
OpenSpec unit folders on `main`, a plan file, the units' snapshots as `discover` would return them (built by hand, so no
OpenSpec CLI and no agent runs), a local forge and a judge that is a scripted `FakeAdapter`. No network, no model."""

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

from l4.agents.fake import FakeAdapter, Step
from l4.context import AppContext
from l4.forge.local import LocalForge
from l4.specs.base import Framework, Task, UnitRef
from l4.state.fold import LastVerdict, UnitState
from l4.state.review import AfterHandoff
from l4.state.status import UnitSnapshot
from l4.vcs.git import Git
from l4.yolo.cycle import PlanStep, yolo_step
from l4.yolo.digest import plan_digest, unit_digest
from l4.yolo.model import PlanEvent, ProfileResult
from l4.yolo.store import PlanStore

from .yolo_ledger_world import _env, make_origin, sh
from .yolo_review_world import SPEC_A, make_app, make_cfg

PLAN = "p1"
RUN = "r-20261014T1000Z-0001"
READY = {"verdict": "READY", "findings": [], "assumptions": [], "missing": []}


class StubProvider:
    """A spec provider whose validation always passes: the intake checks are not what these tests are about."""

    framework = Framework.OPENSPEC

    def validate(self, ref: UnitRef, strict: bool = True) -> SimpleNamespace:
        return SimpleNamespace(issues=[])

    def criteria(self, ref: UnitRef) -> list:
        return []

    def unit_dir(self, ref: UnitRef) -> Path:
        return ref.path


class MergingForge(LocalForge):
    """A local forge that shows a pull request as merged as soon as it is asked, the way GitHub marks the pull request
    of a branch that landed on its base."""

    def get_pr(self, number: int):
        if self._prs[number]["state"] != "merged":
            self.merge(number)
        return super().get_pr(number)


def unit_id(name: str) -> str:
    return f"openspec:{name}"


class CycleWorld:
    def __init__(
        self, root: Path, *, units: Sequence[str] = ("a", "b"), base: str = "main", merge_policy: str = "auto",
        gates: dict | None = None,
    ) -> None:  # fmt: skip
        self.root, self.base, self.units = root, base, list(units)
        self.origin = make_origin(root)
        path = root / "repo"
        subprocess.run(["git", "clone", "--quiet", str(self.origin), str(path)], check=True, capture_output=True,
                       env=_env())  # fmt: skip
        self.git = Git(path, environ=_env())
        self.repo = path
        for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
            sh(path, "config", key, value)
        sh(path, "checkout", "-q", "-b", "main")
        self.cfg = make_cfg(
            forge={"type": "local", "base_branch": base, "merge_policy": merge_policy},
            **({"gates": gates} if gates else {}),
        )
        self.app: AppContext = make_app(path, root)
        self.forge = MergingForge()
        self.commit({"README.md": "hello\n"}, "init")
        for name in self.units:
            self.commit(self.unit_files(name), f"add {name}")
        sh(path, "push", "-q", "origin", "main")
        if base != "main":
            sh(path, "push", "-q", "origin", f"main:refs/heads/{base}")
        sh(path, "fetch", "-q", "origin")
        self.profile_calls: list[tuple[str, str]] = []
        self.profile_result: Callable[[str, str], ProfileResult] = lambda revision, profile: ProfileResult(
            "pass", revision, profile
        )
        self.judge = FakeAdapter([Step(structured=READY) for _ in range(20)])

    # --- git --------------------------------------------------------------------------------------------------------

    def commit(self, files: Mapping[str, str], message: str = "c") -> str:
        for name, text in files.items():
            file = self.repo / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text, encoding="utf-8")
        sh(self.repo, "add", "-A")
        sh(self.repo, "commit", "-q", "-m", message)
        return sh(self.repo, "rev-parse", "HEAD")

    @staticmethod
    def unit_files(name: str, spec: str = SPEC_A) -> dict[str, str]:
        base = f"openspec/changes/{name}"
        return {
            f"{base}/proposal.md": f"Why: {name}.\n",
            f"{base}/specs/x/spec.md": spec,
            f"{base}/tasks.md": "- [ ] 1.1 do it\n",
        }

    def restarts(self, name: str, count: int) -> None:
        """`l4 restart` `count` times: each keeps the old head at `refs/l4/attempts/<fw>/<name>/<n>` on origin (R1), so
        the unit is on attempt 1 + count."""
        head = sh(self.repo, "rev-parse", "HEAD")
        for n in range(1, count + 1):
            sh(self.repo, "push", "-q", "origin", f"{head}:refs/l4/attempts/openspec/{name}/{n}")

    def push_main(self) -> str:
        sh(self.repo, "push", "-q", "origin", "main")
        sh(self.repo, "fetch", "-q", "origin")
        return sh(self.repo, "rev-parse", "HEAD")

    def tip(self, branch: str | None = None) -> str:
        return sh(self.origin, "rev-parse", f"refs/heads/{branch or self.base}")

    def person_moves_target(self) -> str:
        other = self.root / "other"
        if not other.exists():
            subprocess.run(["git", "clone", "--quiet", str(self.origin), str(other)], check=True, capture_output=True,
                           env=_env())  # fmt: skip
            for key, value in (("user.name", "p"), ("user.email", "p@example.invalid")):
                sh(other, "config", key, value)
        sh(other, "checkout", "-q", self.base)
        sh(other, "pull", "-q", "origin", self.base)
        (other / f"p{len(list(other.iterdir()))}.txt").write_text("person\n")
        sh(other, "add", "-A")
        sh(other, "commit", "-q", "-m", "a person's commit")
        sh(other, "push", "-q", "origin", f"HEAD:refs/heads/{self.base}")
        return sh(other, "rev-parse", "HEAD")

    def unit_branch(self, name: str, files: Mapping[str, str] | None = None) -> str:
        """A unit branch with one commit on top of the target, pushed; returns its head."""
        branch = f"l4/openspec/{name}"
        sh(self.repo, "checkout", "-q", "-b", branch, self.base if self.base == "main" else "main")
        head = self.commit(files or {f"code-{name}.py": "x = 1\n"}, f"implement {name}")
        sh(self.repo, "push", "-q", "origin", branch)
        sh(self.repo, "checkout", "-q", "main")
        sh(self.repo, "fetch", "-q", "origin")
        return head

    # --- the plan ---------------------------------------------------------------------------------------------------

    def plan(
        self, *, merge: str = "auto", deps: Mapping[str, Sequence[str]] | None = None, limits: dict | None = None,
        batches: list[dict] | None = None, target: str | None = None, promotion: str | None = "amaster",
        plan_id: str = PLAN, push: bool = True,
    ) -> str:  # fmt: skip
        deps = {"b": ["a"]} if deps is None and "b" in self.units else dict(deps or {})
        doc: dict = {
            "schema": "l4/delivery-plan@1", "plan_id": plan_id, "target": target or self.base, "merge": merge,
            "batches": batches
            or [{"id": "b1", "units": [{"id": unit_id(n), "depends_on": [unit_id(d) for d in deps.get(n, [])]}
                                       for n in self.units]}],
        }  # fmt: skip
        if promotion:
            doc["promotion"] = {"mode": "manual", "target_branch": promotion}
        if limits:
            doc["limits"] = limits
        text = json.dumps(doc, indent=2) + "\n"
        self.commit({f".l4/plans/{plan_id}.json": text}, f"plan {plan_id}")
        if push:
            self.push_main()
        return text

    # --- the plan ledger --------------------------------------------------------------------------------------------

    def store(self, plan_id: str = PLAN) -> PlanStore:
        return PlanStore(self.git, plan_id)

    def events(self, plan_id: str = PLAN) -> list[PlanEvent]:
        return self.store(plan_id).read().events

    def kinds(self, plan_id: str = PLAN) -> list[str]:
        return [e.type for e in self.events(plan_id)]

    def seed(self, *events: PlanEvent, plan_id: str = PLAN) -> None:
        store = self.store(plan_id)
        store.append(list(events), expect=store.read().head)

    def digests(self, names: Sequence[str] | None = None) -> dict[str, str]:
        return {unit_id(n): unit_digest(self.git, "origin/main", f"openspec/changes/{n}") for n in names or self.units}

    def reviewed(self, text: str | None = None, *, plan_id: str = PLAN, order: Sequence[str] | None = None) -> None:
        """admitted and reviewed (every unit READY), as the CI step leaves the ledger before an activation."""
        text = text or (self.repo / ".l4" / "plans" / f"{plan_id}.json").read_text(encoding="utf-8")
        digest = plan_digest(text)
        units = {u: {"verdict": "READY", "digest": d, "findings": []} for u, d in self.digests().items()}
        self.seed(
            ev(
                "plan.admitted",
                plan_digest=digest,
                order=list(order or [unit_id(n) for n in self.units]),
                merge=json.loads(text)["merge"],
            ),
            ev("plan.reviewed", plan_digest=digest, units=units, batches={}),
            plan_id=plan_id,
        )

    def activate(
        self,
        text: str | None = None,
        *,
        plan_id: str = PLAN,
        order: Sequence[str] | None = None,
        limits: dict | None = None,
    ) -> None:
        """reviewed and activated, as `l4 yolo activate` leaves the ledger."""
        text = text or (self.repo / ".l4" / "plans" / f"{plan_id}.json").read_text(encoding="utf-8")
        self.reviewed(text, plan_id=plan_id, order=order)
        doc = json.loads(text)
        self.seed(
            ev(
                "plan.activated",
                plan_digest=plan_digest(text),
                digests=self.digests(),
                limits=limits if limits is not None else doc.get("limits", {}),
                by="alice",
                reason="go",
            ),
            plan_id=plan_id,
        )

    # --- the units --------------------------------------------------------------------------------------------------

    def snapshot(self, name: str, phase: str | None = "implementing", **state) -> UnitSnapshot:
        ref = UnitRef(Framework.OPENSPEC, name, self.repo / "openspec" / "changes" / name)
        return UnitSnapshot(
            ref=ref, state=UnitState(unit=unit_id(name), phase=phase, **state), source="branch",
            tasks=[Task("1.1", "1.1", "do it", False, " ", 0, 1, 2)],
        )  # fmt: skip

    def in_review(self, name: str, head: str, **state) -> UnitSnapshot:
        fields = {"unit": unit_id(name), "phase": "in_review", "pr": "local://forge/pull/1",
                  "last_verdict": LastVerdict(round=1, verdict="PASS", findings=0), **state}  # fmt: skip
        ref = UnitRef(Framework.OPENSPEC, name, self.repo / "openspec" / "changes" / name)
        return UnitSnapshot(
            ref=ref, state=UnitState(**fields), source="branch", review=AfterHandoff(handoff=head, head=head),
            tasks=[Task("1.1", "1.1", "do it", True, "x", 0, 1, 2)],
        )  # fmt: skip

    def found(self, snapshots: Mapping[str, UnitSnapshot] | None = None) -> list[tuple[StubProvider, UnitSnapshot]]:
        snaps = dict(snapshots or {})
        return [(StubProvider(), snaps.get(n) or self.snapshot(n, None)) for n in self.units]

    # --- the step ---------------------------------------------------------------------------------------------------

    def step(self, snapshots: Mapping[str, UnitSnapshot] | None = None, **kw) -> PlanStep:
        def run_profile(app, cfg, git, revision, profile, **_):
            self.profile_calls.append((revision, profile))
            return self.profile_result(revision, profile)

        import l4.yolo.cycle as cycle

        original = cycle.run_profile
        cycle.run_profile = run_profile
        try:
            return yolo_step(
                self.app, self.cfg, self.git, self.found(snapshots), forge=kw.pop("forge", self.forge),
                adapters={"fake": self.judge}, confirm_wait_s=0, **kw,
            )  # fmt: skip
        finally:
            cycle.run_profile = original


def ev(kind: str, **data) -> PlanEvent:
    return PlanEvent(type=kind, at="2026-10-14T10:00:00Z", data=data)
