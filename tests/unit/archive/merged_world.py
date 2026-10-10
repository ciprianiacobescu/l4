"""A merged unit as the sweeper meets it: real git (a bare origin, the checkout of main, a merge commit, a lock ref with
the pending ledger), the fake GitLab, and an OpenSpec provider whose `archive` moves the folder the way the CLI does."""

import shutil
from collections.abc import Callable
from pathlib import Path

from l4.config.schema import L4Config
from l4.context import AppContext
from l4.forge.gitlab import GitLabForge
from l4.postmerge import PostMergeArchiver
from l4.redact import Redactor
from l4.specs.base import ArchiveRefused, ArchiveReport, Framework, UnitRef
from l4.specs.openspec import OpenSpecProvider
from l4.state.ledger import LedgerWriter, ledger_path
from l4.state.pending import PendingLedger
from l4.vcs.git import Git

from ..forge.conftest import API, PROJECT, TOKEN, FakeGitLab

RUN = "r-20261004T0900Z-aaaa"
SWEEP_RUN = "r-20261005T1000Z-bbbb"
DONE = "# Tasks\n\n- [x] 1.1 first\n- [x] 1.2 second\n"
PROPOSAL = (
    "# Proposal: average unit price\n\n## Why\nSales reports need the average price paid per unit in a cart, so that "
    "the report can show it next to the subtotal.\n\n## What Changes\n- Add the average unit price.\n\n"
    "## Capabilities\n\n### New Capabilities\n- `cap-add-x`: figures computed from a cart.\n\n"
    "### Modified Capabilities\n\n## Impact\n`src/pricing/cart.py`.\n"
)
DELTA = (
    "## Purpose\nStats.\n\n## ADDED Requirements\n\n### Requirement: Average\nThe cart SHALL average.\n\n"
    "#### Scenario: Two\n- **WHEN** two\n- **THEN** one\n"
)


class FakeArchiveProvider(OpenSpecProvider):
    """`archive` as the CLI does it (the folder moves under `changes/archive/<date>-<name>/`, every delta capability
    gets its `spec.md`), minus node. `stray` makes it touch a file it must not."""

    stray: str | None = None
    refuse_with: Exception | None = None

    def archive(self, unit: UnitRef) -> ArchiveReport:
        gate = self.done_gate(unit)
        if not gate.passed:
            raise ArchiveRefused(f"{unit.id} is not done: {'; '.join(gate.reasons)}")
        if self.refuse_with is not None:
            raise self.refuse_with
        dated = f"2026-10-05-{unit.name}"
        root = self._repo / "openspec"
        (root / "changes" / "archive").mkdir(parents=True, exist_ok=True)
        shutil.move(str(unit.path), root / "changes" / "archive" / dated)
        for delta in sorted((root / "changes" / "archive" / dated / "specs").glob("*/spec.md")):
            target = root / "specs" / delta.parent.name / "spec.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(delta, target)
        if self.stray:
            (self._repo / self.stray).parent.mkdir(parents=True, exist_ok=True)
            (self._repo / self.stray).write_text("changed by the archive\n")
        return ArchiveReport(dated, True)


class MergedWorld:
    def __init__(
        self, tmp_path: Path, raw: Callable[..., str], git_environ: dict[str, str], gitlab: FakeGitLab
    ) -> None:
        self.tmp, self.raw, self.gitlab = tmp_path, raw, gitlab
        self.environ = {**git_environ, "L4_CACHE": str(tmp_path / "cache")}
        self.repo = tmp_path / "work"
        self.origin = tmp_path / "origin.git"
        self.git = Git(self.repo, environ=self.environ)
        self.cfg = L4Config.model_validate({"version": 1})
        self.provider_class: type[FakeArchiveProvider] = FakeArchiveProvider
        self.provider_options: dict[str, object] = {}
        self.name = "add-x"
        self.unit_id = f"openspec:{self.name}"
        self.merge_sha = ""

    # --- setup ------------------------------------------------------------------------------------------------

    def build(self, *, tasks: str = DONE, archive_in_merge: bool = False, pending: bool = True) -> "MergedWorld":
        raw, repo = self.raw, self.repo
        repo.mkdir()
        raw(repo, "init", "-q")
        (repo / "README.md").write_text("hello\n")
        raw(repo, "add", "-A")
        raw(repo, "commit", "-q", "-m", "init")
        raw(self.tmp, "init", "-q", "--bare", str(self.origin))
        raw(repo, "remote", "add", "origin", str(self.origin))
        raw(repo, "push", "-q", "origin", "main")
        self.merge_unit(self.name, tasks=tasks, archive_in_merge=archive_in_merge, pending=pending)
        return self

    def merge_unit(
        self, name: str, *, tasks: str = DONE, archive_in_merge: bool = False, pending: bool = True,
        run_id: str = RUN,
    ) -> str:
        """A unit implemented on its branch, handed off, and merged into main by a human (merge commit)."""
        raw, repo = self.raw, self.repo
        branch = f"l4/openspec/{name}"
        unit_id = f"openspec:{name}"
        raw(repo, "checkout", "-q", "-b", branch)
        unit = repo / "openspec" / "changes" / name
        (unit / "specs" / f"cap-{name}").mkdir(parents=True)
        (unit / "tasks.md").write_text(tasks)
        (unit / "specs" / f"cap-{name}" / "spec.md").write_text(DELTA)
        (unit / "proposal.md").write_text(PROPOSAL)
        writer = LedgerWriter.open(unit, unit_id, run_id, redactor=Redactor({}))
        writer.append("phase.changed", **{"from": "verified"}, to="verified", trigger="verify_pass")
        run_file = ledger_path(unit, run_id)
        raw(repo, "add", "-A")  # the hand-off commit H holds the ledger as it is now
        raw(repo, "commit", "-q", "-m", "hand off\n\nL4-Run: " + run_id)
        writer.append("phase.changed", **{"from": "verified"}, to="in_review", trigger="hand_off_pushed")
        writer.finish(0)
        raw(repo, "push", "-q", "origin", branch)
        if pending:
            ref = f"refs/l4/locks/openspec/{name}"
            PendingLedger(self.git, lock_ref=ref, unit=unit_id, run_id=run_id).publish(run_file)
        raw(repo, "checkout", "-q", "--", ".")
        raw(repo, "checkout", "-q", "main")
        raw(repo, "merge", "-q", "--no-ff", "-m", "Merge", branch)
        if archive_in_merge:
            raw(repo, "rm", "-q", "-r", f"openspec/changes/{name}")
            raw(repo, "commit", "-q", "--amend", "-m", "Merge, archived")
        raw(repo, "push", "-q", "origin", "main")
        self.merge_sha = raw(repo, "rev-parse", "HEAD").strip()
        raw(repo, "push", "-q", "origin", f":{branch}")  # the project deletes merged source branches
        raw(repo, "fetch", "-q", "--prune", "origin")
        return self.merge_sha

    def app(self, run_id: str = SWEEP_RUN) -> AppContext:
        return AppContext(
            repo=self.repo, config_path=None, log_format="human", verbosity=0, run_id=run_id, environ=self.environ,
            redactor=Redactor({}),
        )  # fmt: skip

    def forge(self) -> GitLabForge:
        return GitLabForge(API, PROJECT, TOKEN, transport=self.gitlab.transport(), sleep=lambda s: None)

    def merged_mr(self, name: str | None = None, *, sha: str | None = "merge") -> int:
        """The MR the human merged, as the forge lists it."""
        name = name or self.name
        pr = self.forge().create_pr(f"l4/openspec/{name}", "main", f"[l4] {name}: x", "b", draft=False)
        self.gitlab.merge(pr.number, self.merge_sha if sha == "merge" else sha)
        return pr.number

    def provider_for(self, path: Path) -> FakeArchiveProvider:
        provider = self.provider_class(path, self.environ)
        for key, value in self.provider_options.items():
            setattr(provider, key, value)
        return provider

    def archiver(self) -> PostMergeArchiver:
        return PostMergeArchiver(self.cfg, self.app(), self.git, self.forge(), provider_for=self.provider_for)

    def ref(self, name: str | None = None) -> UnitRef:
        name = name or self.name
        return UnitRef(Framework.OPENSPEC, name, self.repo / "openspec" / "changes" / name)

    def advance_base(self) -> str:
        """Someone else's merge lands on main."""
        (self.repo / "other.txt").write_text("other\n")
        self.raw(self.repo, "add", "-A")
        self.raw(self.repo, "commit", "-q", "-m", "other work")
        self.raw(self.repo, "push", "-q", "origin", "main")
        return self.raw(self.repo, "rev-parse", "HEAD").strip()

    # --- looking -----------------------------------------------------------------------------------------------

    def remote_branches(self) -> list[str]:
        out = self.raw(self.origin, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
        return sorted(out.split())

    def archive_commits(self, branch: str) -> list[str]:
        return self.raw(self.origin, "log", "--format=%H", f"main..{branch}").split()

