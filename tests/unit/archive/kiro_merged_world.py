"""A merged Kiro unit as the sweeper meets it: `MergedWorld` with `.kiro/specs/<name>` instead of a change folder.
Kiro has no archive command and no archive folder, so the real `KiroProvider` is used (nothing to fake)."""

from l4.redact import Redactor
from l4.specs.base import Framework, UnitRef
from l4.specs.kiro import KiroProvider
from l4.state.ledger import LedgerWriter, ledger_path
from l4.state.pending import PendingLedger

from .merged_world import RUN, MergedWorld

REQUIREMENTS = (
    "# Requirements Document\n\n## Requirements\n\n### Requirement 1: Average\n\n"
    "**User Story:** As a buyer, I want an average, so that I can compare.\n\n#### Acceptance Criteria\n\n"
    "1. WHEN a cart has two items THEN the system SHALL return the average price.\n"
)
DESIGN = "# Design Document\n\nAdd `Cart.average`.\n"
KIRO_DONE = "# Implementation Plan\n\n- [x] 1. Average\n  - [x] 1.1 Add Cart.average\n    - _Requirements: 1.1_\n"
KIRO_OPEN = KIRO_DONE.replace("[x] 1.1", "[ ] 1.1")


class KiroMergedWorld(MergedWorld):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.unit_id = f"kiro:{self.name}"

    def build(self, *, tasks: str = KIRO_DONE, archive_in_merge: bool = False, pending: bool = True):
        return super().build(tasks=tasks, archive_in_merge=archive_in_merge, pending=pending)

    def unit_dir(self, name: str | None = None):
        return self.repo / ".kiro" / "specs" / (name or self.name)

    def merge_unit(
        self, name: str, *, tasks: str = KIRO_DONE, archive_in_merge: bool = False, pending: bool = True,
        run_id: str = RUN,
    ) -> str:
        raw, repo = self.raw, self.repo
        branch = f"l4/kiro/{name}"
        unit_id = f"kiro:{name}"
        raw(repo, "checkout", "-q", "-b", branch)
        unit = self.unit_dir(name)
        unit.mkdir(parents=True)
        (unit / "tasks.md").write_text(tasks)
        (unit / "requirements.md").write_text(REQUIREMENTS)
        (unit / "design.md").write_text(DESIGN)
        writer = LedgerWriter.open(unit, unit_id, run_id, redactor=Redactor({}))
        writer.append("phase.changed", **{"from": "verified"}, to="verified", trigger="verify_pass")
        run_file = ledger_path(unit, run_id)
        raw(repo, "add", "-A")
        raw(repo, "commit", "-q", "-m", "hand off\n\nL4-Run: " + run_id)
        writer.append("phase.changed", **{"from": "verified"}, to="in_review", trigger="hand_off_pushed")
        writer.finish(0)
        raw(repo, "push", "-q", "origin", branch)
        if pending:
            lock = f"refs/l4/locks/kiro/{name}"
            PendingLedger(self.git, lock_ref=lock, unit=unit_id, run_id=run_id).publish(run_file)
        raw(repo, "checkout", "-q", "--", ".")
        raw(repo, "checkout", "-q", "main")
        raw(repo, "merge", "-q", "--no-ff", "-m", "Merge", branch)
        raw(repo, "push", "-q", "origin", "main")
        self.merge_sha = raw(repo, "rev-parse", "HEAD").strip()
        raw(repo, "push", "-q", "origin", f":{branch}")
        raw(repo, "fetch", "-q", "--prune", "origin")
        return self.merge_sha

    def merged_mr(self, name: str | None = None, *, sha: str | None = "merge") -> int:
        name = name or self.name
        pr = self.forge().create_pr(f"l4/kiro/{name}", "main", f"[l4] {name}: x", "b", draft=False)
        self.gitlab.merge(pr.number, self.merge_sha if sha == "merge" else sha)
        return pr.number

    def ref(self, name: str | None = None) -> UnitRef:
        name = name or self.name
        return UnitRef(Framework.KIRO, name, self.unit_dir(name))

    def provider(self) -> KiroProvider:
        return KiroProvider(self.repo)

    def edit_on_main(self, name: str, filename: str, text: str) -> str:
        """Someone's commit on main that rewrites a file of the unit folder."""
        (self.unit_dir(name) / filename).write_text(text)
        self.raw(self.repo, "add", "-A")
        self.raw(self.repo, "commit", "-q", "-m", f"edit {filename}")
        self.raw(self.repo, "push", "-q", "origin", "main")
        return self.raw(self.repo, "rev-parse", "HEAD").strip()
