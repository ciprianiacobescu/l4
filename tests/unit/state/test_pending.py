import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.state.ledger import LedgerCorrupt, parse_ledger_files
from l4.state.pending import (
    PENDING_DIR,
    PendingLedger,
    PendingNotPublished,
    merge_ledgers,
    read_pending_files,
)
from l4.vcs.push import ForcedPushRefused, build_lease_push_args

from .conftest import UNIT_REL

UNIT = "openspec:add-x"
LOCK_REF = "refs/l4/locks/openspec/add-x"
RUN = "r-20261003T1312Z-7f3a"
OTHER_RUN = "r-20261003T1400Z-0001"


def run_file(base: Path, run_id: str = RUN, *events: tuple[str, dict]) -> Path:
    """A finished run ledger as the harness writes it: `run.started`, the events, `run.finished`."""
    from l4.redact import Redactor
    from l4.state.ledger import LedgerWriter

    writer = LedgerWriter.open(base / UNIT_REL, UNIT, run_id, redactor=Redactor({}))
    for event_type, data in events:
        writer.append(event_type, **data)
    writer.finish(0)
    return base / UNIT_REL / ".l4" / "ledger" / f"{run_id}.jsonl"


def pending_for(unit_repo, run_id: str = RUN, **options) -> PendingLedger:
    return PendingLedger(unit_repo.git, lock_ref=LOCK_REF, unit=UNIT, run_id=run_id, **options)


def remote_value(unit_repo, raw) -> str:
    out = raw(unit_repo.repo, "ls-remote", "origin", LOCK_REF).split()
    return out[0] if out else ""


def bare(unit_repo) -> Path:
    return Path(unit_repo.git.run("remote", "get-url", "origin").stdout.strip())


def test_publish_sends_the_lock_commit_its_tree_and_the_blob_to_the_remote(unit_repo, raw):
    path = run_file(unit_repo.repo, RUN, ("phase.changed", {"from": "verified", "to": "in_review"}))
    sha = pending_for(unit_repo).publish(path)
    origin = bare(unit_repo)
    assert remote_value(unit_repo, raw) == sha
    assert raw(origin, "cat-file", "-t", sha).strip() == "commit"
    listing = raw(origin, "ls-tree", "-r", sha).split("\n")
    (entry,) = [line for line in listing if line]
    blob = entry.split()[2]
    assert entry.endswith(f"\t{PENDING_DIR}/{RUN}.jsonl")
    assert raw(origin, "cat-file", "-t", blob).strip() == "blob"
    assert raw(origin, "cat-file", "blob", blob) == path.read_text()
    raw(origin, "fsck", "--connectivity-only", "--no-dangling")  # raises when an object is missing


def test_the_lock_commit_message_is_the_lck_001_json_then_skip_ci_then_the_trailers(unit_repo, raw):
    path = run_file(unit_repo.repo)
    now = datetime(2026, 10, 4, 9, 30, tzinfo=UTC)
    sha = pending_for(unit_repo, holder="runner-1:42", clock=lambda: now).publish(path)
    message = raw(bare(unit_repo), "log", "-1", "--format=%B", sha)
    first = json.loads(message.splitlines()[0])
    assert set(first) == {"unit", "run_id", "holder", "acquired_at", "expires_at", "nonce"}
    assert first["unit"] == UNIT and first["run_id"] == RUN and first["holder"] == "runner-1:42"
    assert first["acquired_at"] == "2026-10-04T09:30:00Z" and first["expires_at"] == first["acquired_at"]
    assert re.fullmatch(r"[0-9a-f]{16}", first["nonce"])
    assert "\n[skip ci]\n" in message
    assert f"\nL4-Run: {RUN}\n" in message and f"\nL4-Unit: {UNIT}\n" in message
    trailers = raw(bare(unit_repo), "log", "-1", "--format=%(trailers:key=L4-Run,valueonly)", sha).strip()
    assert trailers == RUN  # git itself parses it as a trailer
    assert raw(bare(unit_repo), "log", "-1", "--format=%an", sha).strip() == "l4-bot"


def test_a_second_run_extends_the_tree_and_the_chain(unit_repo, raw):
    first = pending_for(unit_repo).publish(run_file(unit_repo.repo, RUN))
    second = pending_for(unit_repo, OTHER_RUN).publish(run_file(unit_repo.repo, OTHER_RUN))
    origin = bare(unit_repo)
    assert remote_value(unit_repo, raw) == second
    assert raw(origin, "rev-parse", f"{second}^").strip() == first
    names = {line.split("\t")[1] for line in raw(origin, "ls-tree", "-r", second).splitlines()}
    assert names == {f"{PENDING_DIR}/{RUN}.jsonl", f"{PENDING_DIR}/{OTHER_RUN}.jsonl"}


def test_a_repeated_publish_of_a_run_replaces_its_file(unit_repo, raw):
    path = run_file(unit_repo.repo, RUN)
    pending_for(unit_repo).publish(path)
    longer = path.read_bytes() + json.dumps(ev(9, "budget.cost", usd=1)).encode() + b"\n"
    path.write_bytes(longer)
    sha = pending_for(unit_repo).publish(path)
    (entry,) = raw(bare(unit_repo), "ls-tree", "-r", sha).splitlines()
    assert raw(bare(unit_repo), "cat-file", "blob", entry.split()[2]).encode() == longer


def test_the_local_ref_is_written_only_after_the_push_succeeded(unit_repo, raw):
    path = run_file(unit_repo.repo)
    ledger = pending_for(unit_repo)
    built = ledger.build(path)
    assert unit_repo.git.rev_parse(LOCK_REF) is None  # built, not yet pushed: no ref, only objects
    ledger.push(built)
    assert unit_repo.git.rev_parse(LOCK_REF) == built.sha == remote_value(unit_repo, raw)


def test_a_prune_fetch_between_build_and_push_does_not_lose_the_commit(unit_repo, raw):
    ledger = pending_for(unit_repo)
    built = ledger.build(run_file(unit_repo.repo))
    unit_repo.git.fetch("origin", refspecs=("+refs/l4/locks/*:refs/l4/locks/*",), prune=True)  # G8's refresh
    assert unit_repo.git.rev_parse(built.sha) == built.sha  # the commit is still there: only a ref was pruned
    assert unit_repo.git.rev_parse(LOCK_REF) is None
    ledger.push(built)
    assert remote_value(unit_repo, raw) == built.sha
    origin = bare(unit_repo)
    assert raw(origin, "cat-file", "-t", built.sha).strip() == "commit"


def test_another_runner_can_fetch_the_ref_and_read_the_pending_files(unit_repo, raw, make_repo, git_for, tmp_path):
    path = run_file(unit_repo.repo, RUN, ("phase.changed", {"from": "verified", "to": "in_review"}))
    sha = pending_for(unit_repo).publish(path)
    other = tmp_path / "other"
    raw(tmp_path, "clone", "-q", str(bare(unit_repo)), str(other))
    git = git_for(other)
    assert read_pending_files(git, LOCK_REF) == {}
    git.fetch("origin", refspecs=("+refs/l4/locks/*:refs/l4/locks/*",), prune=True)
    assert git.rev_parse(LOCK_REF) == sha
    assert read_pending_files(git, LOCK_REF) == {f"{RUN}.jsonl": path.read_bytes()}


def test_a_stale_lease_is_retried_on_the_new_value_and_keeps_the_other_runners_file(unit_repo, raw):
    ledger = pending_for(unit_repo, OTHER_RUN)
    path = run_file(unit_repo.repo, OTHER_RUN)
    stale = ledger.build(path)  # built on "no ref"
    theirs = pending_for(unit_repo).publish(run_file(unit_repo.repo, RUN))  # another run got in first
    with pytest.raises(Exception) as caught:  # the stale lease is refused, never forced
        ledger.push(stale)
    assert "stale" in str(caught.value) or "rejected" in str(caught.value)
    assert remote_value(unit_repo, raw) == theirs
    assert unit_repo.git.rev_parse(LOCK_REF) != stale.sha  # a refused push leaves no local ref naming the lost commit
    final = ledger.publish(path)  # publish rebuilds on what the remote has now
    names = {line.split("\t")[1] for line in raw(bare(unit_repo), "ls-tree", "-r", final).splitlines()}
    assert names == {f"{PENDING_DIR}/{RUN}.jsonl", f"{PENDING_DIR}/{OTHER_RUN}.jsonl"}
    assert raw(bare(unit_repo), "rev-parse", f"{final}^").strip() == theirs


def test_publish_gives_up_when_the_ref_keeps_moving(unit_repo, monkeypatch):
    path = run_file(unit_repo.repo)
    ledger = pending_for(unit_repo)
    real = ledger.build
    attempts: list[str] = []

    def beaten_every_time(file):
        built = real(file)
        attempts.append(built.sha)
        rival = f"r-20261003T15{len(attempts):02d}Z-00{len(attempts):02d}"
        pending_for(unit_repo, rival).publish(run_file(unit_repo.repo, rival))  # lands after our commit was built
        return built

    monkeypatch.setattr(ledger, "build", beaten_every_time)
    with pytest.raises(PendingNotPublished):
        ledger.publish(path)
    assert len(attempts) == 3


def test_never_a_plain_or_forced_push_of_the_lock_ref(unit_repo):
    ledger = pending_for(unit_repo)
    ledger.publish(run_file(unit_repo.repo))
    pushes = [argv for argv in unit_repo.git.history if "push" in argv and f"{LOCK_REF}" in " ".join(argv)]
    assert pushes
    for argv in pushes:
        assert any(part.startswith(f"--force-with-lease={LOCK_REF}:") for part in argv)
        assert not any(part.startswith("+") for part in argv[argv.index("--") :])


def test_lease_push_arguments_are_checked_before_git_runs():
    sha = "a" * 40
    assert build_lease_push_args("origin", sha, LOCK_REF, "") == [
        "push", f"--force-with-lease={LOCK_REF}:", "--", "origin", f"{sha}:{LOCK_REF}"
    ]  # fmt: skip
    assert build_lease_push_args("origin", sha, LOCK_REF, "b" * 40)[1] == f"--force-with-lease={LOCK_REF}:{'b' * 40}"
    for remote, ref, expected in (
        ("-o", LOCK_REF, ""),
        ("origin", "refs/heads/main", ""),  # only lock refs
        ("origin", "+" + LOCK_REF, ""),
        ("origin", LOCK_REF, "not-a-sha"),
        ("origin", f"{LOCK_REF}:refs/heads/main", ""),
    ):
        with pytest.raises(ForcedPushRefused):
            build_lease_push_args(remote, sha, ref, expected)
    with pytest.raises(ForcedPushRefused):
        build_lease_push_args("origin", "HEAD", LOCK_REF, "")


# --- the fold (line 28) --------------------------------------------------------------------------------------------


def events_of(files: dict[str, bytes]):
    return parse_ledger_files(files)


def lines(*events: dict) -> bytes:
    return b"".join(json.dumps(e).encode() + b"\n" for e in events)


def ev(seq: int, type_: str = "task.done", run_id: str = RUN, **data) -> dict:
    ts = f"2026-10-03T13:12:{seq:02d}.000000Z"
    return {"ts": ts, "run_id": run_id, "unit": UNIT, "seq": seq, "type": type_, **data}


def test_a_pending_file_extends_the_branch_copy_of_its_run():
    branch = events_of({f"{RUN}.jsonl": lines(ev(1, "run.started"), ev(2, task="1.1"))})
    pending = events_of({f"{RUN}.jsonl": lines(ev(1, "run.started"), ev(2, task="1.1"), ev(3, "run.finished"))})
    merged = merge_ledgers(branch, pending)
    assert [(e.run_id, e.seq) for e in merged.events] == [(RUN, 1), (RUN, 2), (RUN, 3)]


def test_events_of_different_runs_are_all_kept_in_order():
    branch = events_of({f"{RUN}.jsonl": lines(ev(1, "run.started"))})
    pending = events_of({f"{OTHER_RUN}.jsonl": lines(ev(1, "run.started", run_id=OTHER_RUN))})
    assert [e.run_id for e in merge_ledgers(branch, pending).events] == [RUN, OTHER_RUN]


def test_a_different_payload_under_the_same_key_is_corrupt():
    branch = events_of({f"{RUN}.jsonl": lines(ev(1, "run.started"), ev(2, task="1.1"))})
    pending = events_of({f"{RUN}.jsonl": lines(ev(1, "run.started"), ev(2, task="1.2"))})
    with pytest.raises(LedgerCorrupt, match=f"{RUN}.*2"):
        merge_ledgers(branch, pending)


def test_a_different_type_or_timestamp_under_the_same_key_is_corrupt():
    branch = events_of({f"{RUN}.jsonl": lines(ev(1, "run.started"))})
    with pytest.raises(LedgerCorrupt):
        merge_ledgers(branch, events_of({f"{RUN}.jsonl": lines(ev(1, "run.finished"))}))
    late = {**ev(1, "run.started"), "ts": "2026-10-03T13:13:00.000000Z"}
    with pytest.raises(LedgerCorrupt):
        merge_ledgers(branch, events_of({f"{RUN}.jsonl": lines(late)}))


def test_torn_files_of_both_sides_are_reported():
    branch = events_of({f"{RUN}.jsonl": lines(ev(1, "run.started")) + b'{"ts": "2026'})
    pending = events_of({f"{OTHER_RUN}.jsonl": lines(ev(1, "run.started", run_id=OTHER_RUN)) + b"{"})
    assert sorted(merge_ledgers(branch, pending).torn) == sorted([f"{RUN}.jsonl", f"{OTHER_RUN}.jsonl"])


# --- the snapshot reads branch + pending (line 28) ------------------------------------------------------------------

TO_VERIFIED = [
    ("phase.changed", {"from": None, "to": "intake", "trigger": "unit_discovered_pending"}),
    ("phase.changed", {"from": "intake", "to": "verified", "trigger": "verify_pass"}),
]


def snapshot_of(unit_repo):
    from l4.specs.openspec import OpenSpecProvider
    from l4.state.status import load_snapshot

    provider = OpenSpecProvider(unit_repo.repo, unit_repo.environ)
    (ref,) = provider.list_units()
    return load_snapshot(provider, unit_repo.git, ref, branch_prefix="l4/")


def hand_off(unit_repo, trailers, tmp_path: Path) -> Path:
    """The unit branch holds the ledger as of H (verified); the rest of that run (in_review, finished) is only in a
    file outside the repository, which the test then publishes to the lock ref."""
    from l4.redact import Redactor
    from l4.state.ledger import LedgerWriter
    from l4.vcs.git import BOT_IDENTITY

    unit_repo.git.run("checkout", "-q", "-b", "l4/openspec/add-x")
    writer = LedgerWriter.open(unit_repo.unit_dir, UNIT, RUN, redactor=Redactor({}))
    for event_type, data in TO_VERIFIED:
        writer.append(event_type, **data)
    unit_repo.git.run("add", "-A")
    unit_repo.git.commit("hand off", trailers, BOT_IDENTITY)
    unit_repo.git.push("origin", ["HEAD:refs/heads/l4/openspec/add-x"])
    writer.append("phase.changed", **{"from": "verified", "to": "in_review", "trigger": "hand_off_pushed"})
    writer.finish(0)
    full = tmp_path / "full-run.jsonl"
    full.write_bytes((unit_repo.unit_dir / ".l4" / "ledger" / f"{RUN}.jsonl").read_bytes())
    unit_repo.git.run("checkout", "-q", "-f", "main")
    unit_repo.git.fetch("origin")
    return full


@pytest.mark.parametrize("source", ["branch", "worktree"])
def test_the_snapshot_folds_the_pending_tail_over_the_branch(unit_repo, trailers, tmp_path, source):
    path = hand_off(unit_repo, trailers, tmp_path)
    pending_for(unit_repo).publish(path)
    if source == "worktree":
        unit_repo.git.run("update-ref", "-d", "refs/remotes/origin/l4/openspec/add-x")
        head = unit_repo.unit_dir / ".l4" / "ledger"  # a checkout whose copy of the run stops at verified
        head.mkdir(parents=True)
        (head / f"{RUN}.jsonl").write_bytes(b"".join(path.read_bytes().splitlines(keepends=True)[:3]))
    snap = snapshot_of(unit_repo)
    assert snap.source == source
    assert snap.state.phase == "in_review" and snap.state.iteration == 1


def test_without_the_lock_ref_the_branch_alone_says_verified(unit_repo, trailers, tmp_path):
    hand_off(unit_repo, trailers, tmp_path)
    assert snapshot_of(unit_repo).state.phase == "verified"


def test_a_pending_file_that_contradicts_the_branch_makes_only_that_unit_corrupt(unit_repo, trailers, tmp_path):
    path = hand_off(unit_repo, trailers, tmp_path)
    forged = path.read_text().replace('"to": "verified"', '"to": "implemented"')
    path.write_text(forged)
    pending_for(unit_repo).publish(path)
    snap = snapshot_of(unit_repo)
    assert snap.state.phase == "corrupt" and RUN in (snap.corrupt or "")


def test_a_hook_that_declines_the_lock_ref_is_a_forge_refusal_and_is_not_retried(unit_repo, raw):
    """G12: a pre-receive hook (a push rule) says no to the ref: one attempt, a plain GitError, no new build."""
    from l4.vcs.git import GitError
    from l4.vcs.push import PushRejected

    hook = bare(unit_repo) / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'GitLab: lock refs are not allowed here' >&2\nexit 1\n")
    hook.chmod(0o755)
    path = run_file(unit_repo.repo)
    ledger = pending_for(unit_repo)
    builds: list[str] = []
    real = ledger.build
    ledger.build = lambda file: builds.append("build") or real(file)  # type: ignore[method-assign]
    with pytest.raises(GitError) as caught:
        ledger.publish(path)
    assert not isinstance(caught.value, PushRejected) and "remote rejected" in caught.value.stderr
    assert builds == ["build"] and remote_value(unit_repo, raw) == ""


def test_only_regular_run_files_are_taken_from_the_unpublished_directory(tmp_path):
    from l4.state.pending import keep_unpublished, unpublished_files

    run = "r-20261004T0900Z-aaaa"
    source = tmp_path / f"{run}.jsonl"
    source.write_text('{"x": 1}\n')
    directory = tmp_path / "cache" / "pending-unpublished" / "proj-0123456789" / "openspec" / "add-x"
    kept = keep_unpublished(directory, source)
    (kept.parent / "notes.txt").write_text("not a run file\n")
    (kept.parent / "r-20261004T0900Z-bbbb.jsonl").symlink_to(source)
    assert unpublished_files(directory) == {run: kept}
    assert unpublished_files(directory.parent / "other") == {}
