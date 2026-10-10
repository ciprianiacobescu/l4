"""Who made a commit, and which commit is the hand-off H (L4-ARC-008 (d))."""

from l4.vcs.authorship import HANDOFF_SUBJECT, commit_records, handoff_commit, is_harness
from l4.vcs.git import BOT_IDENTITY, Git

BOT = ("-c", f"user.name={BOT_IDENTITY.name}", "-c", f"user.email={BOT_IDENTITY.email}")


def _commit(raw, repo, subject, *, who="bot", run=True, phase="verified", files=None):
    for rel, text in (files or {subject: subject}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    raw(repo, "add", "-A")
    trailers = ["--trailer=L4-Run: r-1"] if run else []
    trailers += [f"--trailer=L4-Phase: {phase}"] if run else []
    ident = BOT if who == "bot" else ()
    raw(repo, *ident, "commit", "-q", "--allow-empty", "-m", subject, *trailers)
    return raw(repo, "rev-parse", "HEAD").strip()


def test_harness_commit_needs_bot_identity_and_l4_run(make_repo, raw, git_for):
    repo = make_repo()
    git = git_for(repo)
    base = raw(repo, "rev-parse", "HEAD").strip()
    both = _commit(raw, repo, "both", who="bot", run=True)
    bot_only = _commit(raw, repo, "bot-no-trailer", who="bot", run=False)
    trailer_only = _commit(raw, repo, "trailer-no-bot", who="human", run=True)
    records = {r[3]: r for r in commit_records(git, f"{base}..HEAD")}
    assert is_harness(records["both"]) and records["both"][0] == both
    assert not is_harness(records["bot-no-trailer"]) and records["bot-no-trailer"][0] == bot_only
    assert not is_harness(records["trailer-no-bot"]) and records["trailer-no-bot"][0] == trailer_only


def test_handoff_is_the_newest_first_parent_harness_commit_with_the_subject(make_repo, raw, git_for):
    repo = make_repo()
    git: Git = git_for(repo)
    name = "add-x"
    subject = HANDOFF_SUBJECT.format(name=name)
    assert handoff_commit(git, "HEAD", name) is None
    first = _commit(raw, repo, subject)
    # a human with the same subject and a bot with the subject but no verified phase are not H
    _commit(raw, repo, subject, who="human", run=False, files={"a": "a"})
    _commit(raw, repo, subject, phase="implementing", files={"b": "b"})
    assert handoff_commit(git, "HEAD", name) == first
    second = _commit(raw, repo, subject, files={"c": "c"})
    _commit(raw, repo, "human work", who="human", run=False)
    assert handoff_commit(git, "HEAD", name) == second
    assert handoff_commit(git, "HEAD", "other") is None
    # the scan limit
    assert handoff_commit(git, "HEAD", name, scan=1) is None


def test_a_harness_commit_is_the_bots_whatever_the_environment_says(make_repo, git_environ):
    """`GIT_AUTHOR_*` / `GIT_COMMITTER_*` in the harness's environment (a developer's shell, a CI variable) beat
    `-c user.name`: the harness's own commits would read as a person's, so every H would be `lost` (a re-verification
    on every run) and an agent's forbidden-path change would be listed as a human's instead of a blocker (G1, G3)."""
    from l4.vcs.trailers import CommitTrailers

    repo = make_repo()
    leaked = {
        **git_environ, "GIT_AUTHOR_NAME": "Dev Person", "GIT_AUTHOR_EMAIL": "dev@example.com",
        "GIT_COMMITTER_NAME": "Dev Person", "GIT_COMMITTER_EMAIL": "dev@example.com",
    }  # fmt: skip
    git = Git(repo, environ=leaked)
    (repo / "work.txt").write_text("work\n")
    git.run("add", "work.txt")
    git.commit("docs(add-x): work", CommitTrailers(unit="openspec:add-x", run_id="r-1", iteration=1, phase="verified"))
    (record,) = commit_records(git, "-1", "HEAD")
    assert is_harness(record), record
    committer = git.run("log", "-1", "--format=%cn <%ce>").stdout.strip()
    assert committer == f"{BOT_IDENTITY.name} <{BOT_IDENTITY.email}>"
