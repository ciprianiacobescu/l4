"""A unit branch handed off to review, and `pr.ready` events written where an attacker can write them: the lock ref's
pending files (the accepted residual, design D1) or the ledger in the branch tree (which is not a source of H)."""

import datetime as dt
from pathlib import Path

from l4.redact import Redactor
from l4.specs.openspec import OpenSpecProvider
from l4.state.ledger import LedgerWriter, ledger_path
from l4.state.status import load_snapshot
from l4.vcs.git import BOT_IDENTITY

from .conftest import BRANCH, UNIT_REL
from .test_status_branch import IMPLEMENTING, tick_first_task

LOCK = "refs/l4/locks/openspec/add-x"


def snap(unit_repo):
    provider = OpenSpecProvider(unit_repo.repo, unit_repo.environ)
    (ref,) = provider.list_units()
    return load_snapshot(provider, unit_repo.git, ref, branch_prefix="l4/")


def ready_file(tmp: Path, run_id: str, head: str, when: dt.datetime) -> bytes:
    """The bytes of a run's ledger file that holds one `pr.ready{head}`."""
    writer = LedgerWriter.open(tmp / UNIT_REL, "openspec:add-x", run_id, redactor=Redactor({}), clock=lambda: when)
    writer.append("pr.ready", url="u", number=1, head=head)
    writer.finish(0)
    return ledger_path(tmp / UNIT_REL, run_id).read_bytes()


def push_lock(git, files: dict[str, bytes], parent: str | None) -> str:
    """Push a lock-ref commit whose `ledger-pending/` holds `files`, with plain git."""
    entries = []
    for name, data in files.items():
        oid = git.run("hash-object", "-w", "--stdin", input=data.decode()).stdout.strip()
        entries.append(f"100644 blob {oid}\t{name}")
    sub = git.run("mktree", input="\n".join(entries) + "\n").stdout.strip()
    root = git.run("mktree", input=f"040000 tree {sub}\tledger-pending\n").stdout.strip()
    args = ["commit-tree", root, "-m", "l4: lock [skip ci]\n\nL4-Run: r-20261003T1312Z-7f3a"]
    if parent:
        args += ["-p", parent]
    sha = git.run(*args).stdout.strip()
    git.run("push", "-q", "origin", f"{sha}:{LOCK}")
    return sha


def fetch(unit_repo) -> None:
    unit_repo.git.run(
        "fetch", "-q", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*", "+refs/l4/locks/*:refs/l4/locks/*"
    )


def handed_off(unit_repo, trailers, tmp_path):
    """Work, then H (the hand-off commit with the ledger), pushed, and the genuine `pr.ready{H}` on the lock ref."""
    git = unit_repo.git
    git.run("checkout", "-q", "-b", BRANCH)
    tick_first_task(unit_repo.repo)
    git.run("add", "-A")
    git.commit("work", trailers, BOT_IDENTITY)
    unit_repo.write_ledger(
        unit_repo.repo, *IMPLEMENTING,
        ("phase.changed", {"from": "implementing", "to": "in_review", "trigger": "hand_off_pushed"}),
    )  # fmt: skip
    git.run("add", "-A")
    git.commit("docs(add-x): hand off to review", trailers, BOT_IDENTITY)
    h = git.rev_parse("HEAD")
    git.push("origin", [f"HEAD:refs/heads/{BRANCH}"])
    when = dt.datetime(2026, 10, 3, 14, 0, tzinfo=dt.UTC)
    genuine = {"r-20261003T1400Z-0001.jsonl": ready_file(tmp_path / "g", "r-20261003T1400Z-0001", h, when)}
    return h, genuine, push_lock(git, genuine, None)


def forge_in_tree(unit_repo, trailers, tmp_path, head: str, when: dt.datetime, run_id: str) -> None:
    """Commit a ledger file with a forged `pr.ready{head}` into the branch tree."""
    data = ready_file(tmp_path / "f", run_id, head, when)
    target = ledger_path(unit_repo.repo / UNIT_REL, run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    unit_repo.git.run("add", "-A")
    unit_repo.git.commit("chore: ledger", trailers, BOT_IDENTITY)
