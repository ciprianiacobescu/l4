"""A unit in review as the CI duty of the sweeper meets it: real git (a bare origin, the unit branch with the harness's
hand-off commit H at its head), the pending ledger in the lock ref, an open ready MR on the fake GitLab."""

from l4.redact import Redactor
from l4.state.ledger import LedgerWriter, ledger_path
from l4.state.pending import PendingLedger
from l4.vcs.authorship import HANDOFF_SUBJECT
from l4.vcs.git import BOT_IDENTITY

from ..archive.merged_world import DELTA, DONE, PROPOSAL, RUN, MergedWorld

BOT = ("-c", f"user.name={BOT_IDENTITY.name}", "-c", f"user.email={BOT_IDENTITY.email}")


class ReviewWorld(MergedWorld):
    handoff = ""  # H
    base = ""  # the base head

    def build(self, **_: object) -> "ReviewWorld":
        raw, repo = self.raw, self.repo
        repo.mkdir()
        raw(repo, "init", "-q")
        (repo / "README.md").write_text("hello\n")
        unit = repo / "openspec" / "changes" / self.name  # the spec is on the base, as a human merged it first
        (unit / "specs" / f"cap-{self.name}").mkdir(parents=True)
        (unit / "tasks.md").write_text(DONE)
        (unit / "specs" / f"cap-{self.name}" / "spec.md").write_text(DELTA)
        (unit / "proposal.md").write_text(PROPOSAL)
        raw(repo, "add", "-A")
        raw(repo, "commit", "-q", "-m", "init")
        raw(self.tmp, "init", "-q", "--bare", str(self.origin))
        raw(repo, "remote", "add", "origin", str(self.origin))
        raw(repo, "push", "-q", "origin", "main")
        self.base = raw(repo, "rev-parse", "HEAD").strip()
        branch, unit_id = f"l4/openspec/{self.name}", self.unit_id
        raw(repo, "checkout", "-q", "-b", branch)
        (unit / "verification.md").write_text("# Verification\n")
        writer = LedgerWriter.open(unit, unit_id, RUN, redactor=Redactor({}))
        writer.append("phase.changed", **{"from": "verifying"}, to="verified", trigger="verify_pass")
        raw(repo, "add", "-A")
        raw(
            repo, *BOT, "commit", "-q", "-m", HANDOFF_SUBJECT.format(name=self.name),
            "--trailer", f"L4-Run: {RUN}", "--trailer", "L4-Phase: verified",
        )  # fmt: skip
        self.handoff = raw(repo, "rev-parse", "HEAD").strip()
        writer.append("phase.changed", **{"from": "verified"}, to="in_review", trigger="hand_off_pushed")
        writer.finish(0)
        raw(repo, "push", "-q", "origin", branch)
        PendingLedger(self.git, lock_ref=f"refs/l4/locks/openspec/{self.name}", unit=unit_id, run_id=RUN).publish(
            ledger_path(unit, RUN)
        )
        raw(repo, "checkout", "-q", "--", ".")
        raw(repo, "checkout", "-q", "main")
        raw(repo, "fetch", "-q", "origin")
        self.forge().create_pr(branch, "main", f"[l4] {self.name}: x", "b", draft=False)
        return self

    def human_commit(self, text: str = "a person") -> str:
        """A commit on the unit branch by someone who is not the harness, pushed."""
        raw, repo = self.raw, self.repo
        raw(repo, "checkout", "-q", f"l4/openspec/{self.name}")
        (repo / "human.txt").write_text(text)
        raw(repo, "add", "-A")
        raw(repo, "commit", "-q", "-m", "a person's fix")
        sha = raw(repo, "rev-parse", "HEAD").strip()
        raw(repo, "push", "-q", "origin", f"l4/openspec/{self.name}")
        raw(repo, "checkout", "-q", "main")
        raw(repo, "fetch", "-q", "origin")
        return sha
