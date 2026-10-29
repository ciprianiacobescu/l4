import pytest

from l4.vcs.git import BOT_IDENTITY, GitError
from l4.vcs.push import (
    ForcedPushRefused,
    PushRejected,
    build_push_args,
    build_retire_args,
    is_permission_failure,
    is_transient_push_failure,
)


@pytest.mark.parametrize(
    "refspec", ["+a:b", "+HEAD:refs/heads/x", "--force", "-f", "--mirror", "--force-with-lease=x:y", "-d", "--delete"]
)
def test_forced_refspec_is_refused_before_git_runs(refspec, make_repo, git_for):
    git = git_for(make_repo(remote=True))
    before = list(git.history)
    with pytest.raises(ForcedPushRefused):
        build_push_args("origin", [refspec])
    with pytest.raises(ForcedPushRefused):
        git.push("origin", [refspec])
    assert git.history == before


def test_remote_and_refspec_shapes():
    assert build_push_args("origin", ["HEAD:refs/heads/l4/openspec/x"]) == [
        "push", "--", "origin", "HEAD:refs/heads/l4/openspec/x"
    ]  # fmt: skip
    for remote in ("", "-o", "--receive-pack=sh"):
        with pytest.raises(ForcedPushRefused):
            build_push_args(remote, ["HEAD:refs/heads/x"])
    with pytest.raises(ForcedPushRefused):
        build_push_args("origin", [])


def test_fast_forward_push_of_the_unit_branch(make_repo, raw, git_for, trailers):
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", "l4/openspec/x")
    (repo / "a.txt").write_text("a\n")
    git.run("add", "-A")
    first = git.commit("one", trailers, BOT_IDENTITY)
    git.push("origin", ["HEAD:refs/heads/l4/openspec/x"])
    assert raw(repo, "ls-remote", "origin", "refs/heads/l4/openspec/x").split()[0] == first
    (repo / "b.txt").write_text("b\n")
    git.run("add", "-A")
    second = git.commit("two", trailers, BOT_IDENTITY)
    git.push("origin", ["HEAD:refs/heads/l4/openspec/x"])
    assert raw(repo, "ls-remote", "origin", "refs/heads/l4/openspec/x").split()[0] == second


def test_non_fast_forward_is_rejected_not_forced(make_repo, raw, git_for, trailers, tmp_path):
    repo = make_repo(remote=True)
    git = git_for(repo)
    git.run("checkout", "-q", "-b", "l4/openspec/x")
    (repo / "a.txt").write_text("a\n")
    git.run("add", "-A")
    git.commit("mine", trailers, BOT_IDENTITY)
    # a human pushes a different commit to the same branch first
    human = tmp_path / "human"
    raw(tmp_path, "clone", "-q", str(tmp_path / "repo-origin.git"), str(human))
    raw(human, "checkout", "-q", "-b", "l4/openspec/x")
    (human / "h.txt").write_text("h\n")
    raw(human, "add", "-A")
    raw(human, "commit", "-q", "-m", "human")
    raw(human, "push", "-q", "origin", "l4/openspec/x")
    theirs = raw(human, "rev-parse", "HEAD").strip()

    pushes_before = sum(1 for argv in git.history if "push" in argv)
    with pytest.raises(PushRejected) as err:
        git.push("origin", ["HEAD:refs/heads/l4/openspec/x"])
    assert isinstance(err.value, GitError)
    pushes = [argv for argv in git.history if "push" in argv]
    assert len(pushes) == pushes_before + 1  # exactly one attempt, no retry with force
    assert not any(a.startswith("+") or a in ("--force", "-f", "--force-with-lease") for argv in pushes for a in argv)
    assert raw(repo, "ls-remote", "origin", "refs/heads/l4/openspec/x").split()[0] == theirs  # remote untouched


def test_push_passes_config_and_the_token_stays_out_of_argv(make_repo, raw, git_for, trailers, tmp_path):
    repo = make_repo(remote=True)
    git = git_for(repo)
    other = tmp_path / "other.git"
    raw(tmp_path, "init", "-q", "--bare", str(other))
    git.run("checkout", "-q", "-b", "l4/openspec/x")
    (repo / "a.txt").write_text("a\n")
    git.run("add", "-A")
    commit = git.commit("one", trailers, BOT_IDENTITY)
    token = "glpat-" + "k9L8m7N6" * 3
    helper = "!f() { echo username=oauth2; echo password=$L4_FORGE_TOKEN; }; f"
    git.push(
        "origin", ["HEAD:refs/heads/l4/openspec/x"],
        config=(("remote.origin.pushurl", str(other)), ("credential.helper", helper)),
    )  # fmt: skip
    assert raw(other, "rev-parse", "refs/heads/l4/openspec/x").strip() == commit  # went to the push URL
    assert raw(repo, "ls-remote", "origin", "refs/heads/l4/openspec/x").strip() == ""  # not to origin's fetch URL
    assert "$L4_FORGE_TOKEN" in " ".join(git.history[-1]) and token not in " ".join(sum(git.history, []))


def test_fetch_forwards_config(make_repo, git_for):
    git = git_for(make_repo(remote=True))
    git.fetch("origin", config=(("credential.helper", "!true"),))
    assert "credential.helper=!true" in git.history[-1]


@pytest.mark.parametrize(
    ("stderr", "rejected"),
    [
        (" ! [rejected]        HEAD -> x (non-fast-forward)\nerror: failed to push", True),
        (" ! [rejected]        HEAD -> x (fetch first)\nerror: failed to push", True),
        (" ! [remote rejected] HEAD -> main (pre-receive hook declined)", False),
        (" ! [remote rejected] HEAD -> x (protected branch hook declined)", False),
        (" ! [rejected]        HEAD -> x (already exists)", False),
        ("remote: You are not allowed to push code to this project.", False),
    ],
)
def test_only_non_fast_forward_and_fetch_first_are_a_rejection(make_repo, git_for, stderr, rejected, monkeypatch):
    """G12: a protected branch or a push rule is the forge's refusal, never a race to retry."""
    git = git_for(make_repo(remote=True))

    def refuse(self, *args, **kw):
        raise GitError(["git", "push"], 1, stderr)

    monkeypatch.setattr(type(git), "run", refuse)
    with pytest.raises(GitError) as caught:
        git.push("origin", ["HEAD:refs/heads/x"])
    assert isinstance(caught.value, PushRejected) is rejected


LOCK = "refs/l4/locks/openspec/x"
ARCHIVED = "refs/l4/archived/openspec/x/r-1"


def test_retire_arguments_are_checked_before_git_runs():
    sha = "a" * 40
    assert build_retire_args("origin", sha, LOCK, ARCHIVED) == [
        "push", "--atomic", f"--force-with-lease={LOCK}:{sha}", f"--force-with-lease={ARCHIVED}:", "--", "origin",
        f"{sha}:{ARCHIVED}", f":{LOCK}",
    ]  # fmt: skip
    for remote, ref, archived in (
        ("-o", LOCK, ARCHIVED),
        ("origin", "refs/heads/main", ARCHIVED),  # only a lock ref goes away
        ("origin", LOCK, "refs/heads/main"),  # and only to the archived namespace
        ("origin", LOCK, "+" + ARCHIVED),
        ("origin", LOCK, f"{ARCHIVED}/../../heads/x"),
    ):
        with pytest.raises(ForcedPushRefused):
            build_retire_args(remote, sha, ref, archived)
    with pytest.raises(ForcedPushRefused):
        build_retire_args("origin", "HEAD", LOCK, ARCHIVED)


def test_a_lock_ref_moves_to_the_archived_namespace_in_one_push(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    git = git_for(repo)
    sha = git.rev_parse("HEAD")
    assert sha
    git.push_lease("origin", sha, LOCK, "")
    git.retire_lock_ref("origin", sha, LOCK, ARCHIVED)
    assert raw(repo, "ls-remote", "origin", "refs/l4/*").split() == [sha, ARCHIVED]


def test_a_lock_ref_that_moved_is_not_retired(make_repo, raw, git_for, trailers):
    repo = make_repo(remote=True)
    git = git_for(repo)
    first = git.rev_parse("HEAD")
    assert first
    git.push_lease("origin", first, LOCK, "")
    (repo / "b.txt").write_text("b\n")
    git.run("add", "-A")
    second = git.commit("two", trailers, BOT_IDENTITY)
    git.push_lease("origin", second, LOCK, first)  # another run wrote the ref
    with pytest.raises(PushRejected):
        git.retire_lock_ref("origin", first, LOCK, ARCHIVED)
    assert raw(repo, "ls-remote", "origin", "refs/l4/*").split() == [second, LOCK]  # nothing moved, nothing created


TRANSIENT_MARKERS = [
    "remote: fatal error in commit_refs_rules",
    "remote: fatal error in commit_refs",
    "remote: Failed to authorize your Git request: internal API unreachable",
    "remote: Internal Server Error",
    "remote: Internal API error",
    "fatal: unable to access 'https://github.com/o/r/': The requested URL returned error: 500",
    "fatal: unable to access 'https://github.com/o/r/': The requested URL returned error: 502",
    "fatal: unable to access 'https://github.com/o/r/': The requested URL returned error: 503",
    "fatal: unable to access 'https://github.com/o/r/': The requested URL returned error: 504",
    "error: RPC failed; HTTP 500 curl 22 The requested URL returned error: 500",
    "fatal: the remote end hung up unexpectedly",
    "fatal: early EOF",
    "fatal: unable to access 'https://github.com/o/r/': Connection reset by peer",
    "fatal: unable to access 'https://github.com/o/r/': Connection timed out after 300000 milliseconds",
    "fatal: unable to access 'https://github.com/o/r/': Operation timed out after 30000 milliseconds",
    "fatal: unable to access 'https://github.com/o/r/': Failed to connect to github.com port 443",
    "fatal: unable to access 'https://github.com/o/r/': Could not resolve host: github.com",
    "fatal: unable to access 'https://github.com/o/r/': gnutls_handshake() failed: The TLS connection was non-properly",
    "fatal: unable to access 'https://github.com/o/r/': OpenSSL SSL_read: SSL_ERROR_SYSCALL, errno 54",
    "fatal: unexpected disconnect while reading sideband packet",
    "remote: Service Unavailable",
    "remote: Resource temporarily unavailable",
    "remote: Something went wrong, please try again later",
]


@pytest.mark.parametrize("stderr", TRANSIENT_MARKERS)
def test_each_server_or_network_marker_is_transient(stderr):
    assert is_transient_push_failure(stderr)
    assert is_transient_push_failure(stderr.upper())  # matched on the lowercased text


def test_githubs_real_server_error_is_transient():
    stderr = (
        "remote: fatal error in commit_refs_rules\n"
        "To https://github.com/o/r\n"
        " ! [remote rejected] HEAD -> l4/openspec/x (failure)\n"
        "error: failed to push some refs to 'https://github.com/o/r'\n"
    )
    assert is_transient_push_failure(stderr)


def test_a_permission_marker_wins_over_a_transient_one():
    stderr = "remote: Service Unavailable\nfatal: unable to access 'https://h/p.git/': 503 permission denied"
    assert "service unavailable" in stderr.lower() and is_permission_failure(stderr)
    assert not is_transient_push_failure(stderr)
    assert not is_transient_push_failure("remote: Internal Server Error\nfatal: Authentication failed for 'https://h'")


@pytest.mark.parametrize(
    "stderr",
    [
        "remote: GitLab: Push rule: commit message does not follow the pattern\n"
        " ! [remote rejected] HEAD -> x (pre-receive hook declined)",
        " ! [rejected]        HEAD -> x (non-fast-forward)\nerror: failed to push some refs",
        " ! [rejected]        HEAD -> x (fetch first)",
        " ! [remote rejected] HEAD -> x (stale info)",
        "remote: You are not allowed to push code to this project.",
        "",
    ],
)
def test_a_rule_a_moved_ref_and_a_permission_are_not_transient(stderr):
    assert not is_transient_push_failure(stderr)


def test_is_permission_failure_is_still_importable_from_the_forge_module():
    from l4.forge import pushfail

    assert pushfail.is_permission_failure is is_permission_failure
    assert pushfail.is_permission_failure("remote: Authentication failed")


HTTP_413 = (
    "error: RPC failed; HTTP 413 curl 22 The requested URL returned error: 413\n"
    "send-pack: unexpected disconnect while reading sideband packet\n"
    "fatal: the remote end hung up unexpectedly\n"
)
HTTP_400 = HTTP_413.replace("413", "400")


@pytest.mark.parametrize(
    "stderr",
    [
        HTTP_413,
        HTTP_400,
        "fatal: unable to access 'https://github.com/o/r/': The requested URL returned error: 404",
        "error: RPC failed; HTTP 422 curl 22\nfatal: the remote end hung up unexpectedly",
    ],
)
def test_an_http_4xx_is_never_transient_although_the_hang_up_after_it_is(stderr):
    """A request the server refuses by its size or its form fails the same way on every try."""
    assert "hung up unexpectedly" in stderr or "returned error: 404" in stderr
    assert not is_transient_push_failure(stderr)


def test_an_http_5xx_with_the_same_hang_up_is_still_transient():
    assert is_transient_push_failure(HTTP_413.replace("413", "502"))


def test_gitlabs_unreachable_api_before_its_hook_refusal_is_transient():
    stderr = (
        "remote: Failed to authorize your Git request: internal API unreachable\n"
        "To https://gitlab.invalid/o/r.git\n"
        " ! [remote rejected] HEAD -> x (pre-receive hook declined)\n"
    )
    assert is_transient_push_failure(stderr)


def test_githubs_older_commit_refs_message_without_rules_is_transient():
    stderr = "remote: fatal error in commit_refs\nTo https://github.com/o/r\n ! [remote rejected] HEAD -> x (failure)"
    assert is_transient_push_failure(stderr)
