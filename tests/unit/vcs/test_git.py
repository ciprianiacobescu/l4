import os
import stat
from pathlib import Path

import pytest

from l4.vcs.git import BOT_IDENTITY, HARDENING, Git, GitError, Identity
from l4.vcs.trailers import CommitTrailers, MissingTrailer


def test_every_invocation_is_hardened(make_repo, git_environ):
    repo = make_repo()
    ambient = {
        **git_environ,
        "GIT_DIR": "/nonexistent",
        "GIT_WORK_TREE": "/nonexistent",
        "GIT_INDEX_FILE": "/nonexistent",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.hooksPath",
        "GIT_CONFIG_VALUE_0": "/tmp/evil",
        "GIT_TERMINAL_PROMPT": "1",
        "LC_ALL": "de_DE.UTF-8",
    }
    git = Git(repo, environ=ambient)
    scrubbed = (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
    )
    for name in scrubbed:
        assert name not in git.env
    assert git.env["GIT_TERMINAL_PROMPT"] == "0" and git.env["LC_ALL"] == "C"
    assert git.env["GIT_CONFIG_GLOBAL"] == git_environ["GIT_CONFIG_GLOBAL"]  # the isolation the caller gave is kept
    assert git.run("rev-parse", "--is-inside-work-tree").stdout.strip() == "true"  # GIT_DIR=/nonexistent did not win
    git.run("status", "--porcelain")
    assert git.rev_parse("HEAD") is not None
    assert len(git.history) == 3
    for argv in git.history:
        assert argv[0] == "git" and tuple(argv[1:7]) == HARDENING
    assert HARDENING == (
        "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.ext.allow=never"
    )  # fmt: skip


def plant(repo: Path) -> dict[str, Path]:
    """Hooks and an fsmonitor command that leave a marker file when git runs them."""
    marks = {name: repo.parent / f"ran-{name}" for name in ("pre-commit", "post-commit", "fsmonitor")}
    for hook in ("pre-commit", "post-commit"):
        script = repo / ".git" / "hooks" / hook
        script.write_text(f"#!/bin/sh\ntouch '{marks[hook]}'\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monitor = repo / "monitor.sh"
    monitor.write_text(f"#!/bin/sh\ntouch '{marks['fsmonitor']}'\nprintf '\\0'\n")
    monitor.chmod(0o755)
    return marks


def test_planted_hooks_never_run(make_repo, raw, git_for, trailers):
    repo = make_repo()
    marks = plant(repo)
    raw(repo, "config", "core.fsmonitor", str(repo / "monitor.sh"))
    # the plant works: plain git runs them (so the assertions below prove something)
    raw(repo, "status")
    (repo / "a.txt").write_text("a\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "plain")
    assert all(m.exists() for m in marks.values())
    for mark in marks.values():
        mark.unlink()

    git = git_for(repo)
    git.run("status")
    (repo / "b.txt").write_text("b\n")
    git.run("add", "-A")
    git.commit("through the runner", trailers, BOT_IDENTITY)
    assert not any(m.exists() for m in marks.values())
    assert any("--no-verify" in argv for argv in git.history)


def test_commit_uses_the_bot_identity_trailers_in_order_and_no_gpg(make_repo, raw, git_for):
    repo = make_repo()
    (repo / "x.txt").write_text("x\n")
    raw(repo, "config", "commit.gpgsign", "true")  # a repo that wants signing must not break the bot
    git = git_for(repo)
    git.run("add", "-A")
    full = CommitTrailers(
        unit="openspec:add-login", run_id="r-20261003T1312Z-7f3a", iteration=3, phase="implementing",
        task="2.1", tdd="green", agent="codex/gpt-x", fallback_from="claude-sonnet", step="2.1/green/1",
    )  # fmt: skip
    sha = git.commit("m0: green [skip ci]", full, Identity("l4-bot", "l4-bot@example.invalid"))
    assert sha == git.rev_parse("HEAD")
    assert raw(repo, "log", "-1", "--format=%an <%ae>|%cn <%ce>").strip() == (
        "l4-bot <l4-bot@example.invalid>|l4-bot <l4-bot@example.invalid>"
    )
    body = raw(repo, "log", "-1", "--format=%B").strip().splitlines()
    assert body[0] == "m0: green [skip ci]"
    assert body[-9:] == [
        "L4-Unit: openspec:add-login", "L4-Run: r-20261003T1312Z-7f3a", "L4-Iteration: 3",
        "L4-Phase: implementing", "L4-Task: 2.1", "L4-TDD: green", "L4-Agent: codex/gpt-x",
        "L4-Fallback-From: claude-sonnet", "L4-Step: 2.1/green/1",
    ]  # fmt: skip


def test_commit_without_mandatory_trailer_is_refused(make_repo, git_for):
    repo = make_repo()
    (repo / "x.txt").write_text("x\n")
    git = git_for(repo)
    git.run("add", "-A")
    before = list(git.history)
    for bad in (
        CommitTrailers(unit="", run_id="r", iteration=1, phase="implementing"),
        CommitTrailers(unit="u", run_id="", iteration=1, phase="implementing"),
        CommitTrailers(unit="u", run_id="r", iteration=0, phase="implementing"),
        CommitTrailers(unit="u", run_id="r", iteration=1, phase=""),
        CommitTrailers(unit="u", run_id="r", iteration=1, phase="p", task="1.1\nL4-TDD: green"),
    ):
        with pytest.raises(MissingTrailer):
            git.commit("msg", bad, BOT_IDENTITY)
    assert git.history == before  # git was never spawned


def test_failed_command_raises_git_error_with_argv_and_stderr(make_repo, git_for):
    git = git_for(make_repo())
    with pytest.raises(GitError) as err:
        git.run("rev-parse", "--verify", "nope-not-a-ref")
    assert err.value.returncode != 0 and "rev-parse" in str(err.value)
    assert git.run("rev-parse", "--verify", "nope", check=False).returncode != 0
    assert git.rev_parse("nope") is None


def test_at_returns_a_runner_with_the_same_environment(make_repo, git_for, tmp_path: Path):
    git = git_for(make_repo())
    other = git.at(tmp_path)
    assert other.env == git.env and other.repo == tmp_path and other.history == []
    assert os.environ.get("GIT_DIR") is None


def test_run_bytes_returns_stdout_untouched(tmp_path, git_for, make_repo):
    repo = make_repo()
    (repo / "f.txt").write_bytes(b"a\r\nb\rc\xff\n")
    git = git_for(repo)
    git.run("add", "f.txt")
    trailers = CommitTrailers(unit="openspec:u", run_id="r-20261003T1312Z-7f3a", iteration=1, phase="implementing")
    git.commit("m", trailers)
    assert git.run_bytes("show", "HEAD:f.txt") == b"a\r\nb\rc\xff\n"
    with pytest.raises(GitError):
        git.run_bytes("show", "HEAD:missing")
    assert git.run_bytes("show", "HEAD:missing", check=False) == b""


def test_a_git_error_made_by_one_run_counts_one_try():
    assert GitError(["git", "push"], 1, "x").tries == 1


def test_blob_prefix_reads_a_bounded_start_of_a_large_blob(make_repo, git_environ):
    repo = make_repo()
    (repo / "big.bin").write_bytes(b"0123456789" * 100_000)
    git = Git(repo, environ=git_environ)
    git.run("add", "big.bin")
    sha = git.run("rev-parse", ":big.bin").stdout.strip()
    assert git.blob_prefix(sha, 25) == b"0123456789" * 2 + b"01234"
    assert git.blob_prefix(sha, 10_000_000) == b"0123456789" * 100_000
    with pytest.raises(GitError):
        git.blob_prefix("0" * 40, 10)
