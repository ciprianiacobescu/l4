from pathlib import Path

import pytest

from l4.exitcodes import ExitCode
from l4.forge.pushfail import PushFailed, explain_push_failure
from l4.vcs.git import GitError
from l4.vcs.push import BranchGone, BranchKeepsMoving, BranchMoved, BranchRewritten, PushRejected

from .conftest import TOKEN
from .test_pushurl import JOB_TOKEN, _runner_conf

BRANCH = "l4/openspec/x"


def explain(exc, environ=None, redact=lambda s: s):
    return explain_push_failure(exc, branch=BRANCH, token_env="L4_FORGE_TOKEN", environ=environ or {}, redact=redact)


def err(stderr, cls=GitError, code=128):
    return cls(["git", "push"], code, stderr)


@pytest.mark.parametrize(
    "stderr",
    [
        "remote: You are not allowed to push code to this project.\nfatal: unable to access 'https://h/p.git/': ",
        "remote: HTTP Basic: Access denied. The provided password or token is incorrect\nfatal: Authentication failed",
        "fatal: could not read Username for 'https://h': terminal prompts disabled",
        "fatal: unable to access 'https://h/p.git/': The requested URL returned error: 403",
        "remote: GitLab: You are not allowed to push code to protected branches on this project.",
    ],
)
def test_a_credential_or_permission_problem_is_exit_3(stderr):
    out = explain(err(stderr))
    assert isinstance(out, PushFailed) and out.code is ExitCode.DOCTOR_FAILED
    assert BRANCH in str(out) and "write_repository" in str(out)


def test_anything_else_is_exit_1_and_names_the_reason():
    out = explain(err("fatal: unable to access 'https://h/p.git/': Could not resolve host: h"))
    assert out.code is ExitCode.INTERNAL_ERROR and "Could not resolve host" in str(out)
    assert "write_repository" not in str(out)


def test_a_rejection_is_exit_1_and_says_nothing_is_forced():
    out = explain(err(" ! [rejected] HEAD -> x (non-fast-forward)", PushRejected, 1))
    assert out.code is ExitCode.INTERNAL_ERROR and "never forces" in str(out)


def test_the_message_is_short_and_redacted():
    out = explain(err("remote: not allowed to push\n" + "x\n" * 50 + TOKEN), redact=lambda s: s.replace(TOKEN, "[R]"))
    assert len(str(out).splitlines()) == 1 and TOKEN not in str(out)


def test_in_ci_without_the_token_and_with_the_runner_rule_the_cause_is_named(tmp_path):
    env = {**_runner_conf(tmp_path)}
    out = explain(err("remote: You are not allowed to push code to this project."), env)
    assert "L4_FORGE_TOKEN is not set" in str(out) and "job token" in str(out) and JOB_TOKEN not in str(out)
    denied = err("remote: You are not allowed to push code to this project.")
    with_token = explain(denied, {**env, "L4_FORGE_TOKEN": "x"})
    assert "is not set" not in str(with_token)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "gitlab_push"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_protected_branch_refusal_is_not_non_fast_forward():
    out = explain(err(_fixture("protected-branch.stderr.txt")))
    assert out.code is ExitCode.DOCTOR_FAILED
    assert "the forge refused the push (protected branch or push rule)" in str(out)
    assert "non-fast-forward" not in str(out) and "never forces" not in str(out)
    assert "not allowed to push code to protected branches" in str(out)  # the server's reason is named


def test_a_push_rule_refusal_without_a_permission_marker_is_exit_1_naming_the_reason():
    out = explain(err(_fixture("push-rule.stderr.txt")))
    assert out.code is ExitCode.INTERNAL_ERROR
    assert "Commit message does not follow the pattern" in str(out)
    assert "non-fast-forward" not in str(out) and "never forces" not in str(out)


def test_a_lock_ref_hook_decline_is_not_a_credential_hint():
    out = explain(err(_fixture("push-rule.stderr.txt")))
    assert "write_repository" not in str(out)


def test_only_a_real_non_fast_forward_says_so():
    out = explain(err(_fixture("non-fast-forward.stderr.txt"), PushRejected, 1))
    assert out.code is ExitCode.INTERNAL_ERROR and "non-fast-forward" in str(out) and "never forces" in str(out)


def test_a_deleted_branch_names_l4_restart():
    """L4-OPS-009: the unit branch was deleted on the forge: the message names the command that starts the unit over."""
    out = explain(err(" ! [rejected] HEAD -> x (stale info)", PushRejected, 1))
    assert out.code is ExitCode.INTERNAL_ERROR
    assert "l4 restart --unit openspec:x --reason TEXT" in str(out)
    assert "rerun the unit" not in str(out) and "never forces" in str(out)


# --- adoption-lessons 1.2 (L4-ADO-004): the forge's own token rules ---------------------------------------------------

_403 = "fatal: unable to access 'https://h/p.git/': The requested URL returned error: 403"


def _on(platform, environ=None, token_env="L4_FORGE_TOKEN"):
    return explain_push_failure(
        err(_403), branch=BRANCH, token_env=token_env, environ=environ or {}, redact=lambda s: s, platform=platform
    )


def test_github_wording_on_github():  # SCN-ADO-10
    text = str(_on("github", {"L4_FORGE_TOKEN": "x"}))
    assert "contents: write" in text and "pull-requests: write" in text
    assert "Developer role" not in text and "write_repository" not in text


def test_gitlab_wording_on_gitlab():  # SCN-ADO-11
    text = str(_on("gitlab", {"L4_FORGE_TOKEN": "x"}))
    assert "write_repository" in text and "Developer role" in text
    assert "contents: write" not in text


def test_an_unset_token_is_named_on_github_outside_ci():  # SCN-ADO-12
    text = str(_on("github", {}, token_env="GITHUB_TOKEN"))
    assert "GITHUB_TOKEN is not set" in text


def test_an_unset_token_is_named_on_gitlab_outside_ci_and_a_set_one_is_not():
    assert "L4_FORGE_TOKEN is not set" in str(_on("gitlab", {}))
    assert "is not set" not in str(_on("github", {"L4_FORGE_TOKEN": "x"}))
    assert "job token" not in str(_on("gitlab", {}))  # the runner sentence stays GitLab CI only


GITHUB_SERVER_ERROR = (
    "remote: fatal error in commit_refs_rules\n"
    "To https://github.com/o/r\n"
    f" ! [remote rejected] HEAD -> {BRANCH} (failure)\n"
    "error: failed to push some refs to 'https://github.com/o/r'\n"
)


def test_a_server_error_is_transient_exit_1_and_not_a_refusal():
    """SCN-LCK-13: GitHub's own message holds `[remote rejected]`, which is not a push rule."""
    out = explain(err(GITHUB_SERVER_ERROR, code=1))
    assert out.code is ExitCode.INTERNAL_ERROR and out.transient is True and out.refused is False
    text = str(out)
    assert text.startswith(f"push of {BRANCH} to origin failed: remote: fatal error in commit_refs_rules")
    assert "The forge failed on its side (a server or network error, not a refusal)" in text
    assert "Nothing is wrong with the branch or the credential: a later push should work" in text
    assert "the next run pushes again" not in text
    assert "write_repository" not in text and "push rule" not in text


def test_a_push_rule_is_still_a_refusal_and_not_transient():
    stderr = "remote: GitLab: Push rule: commit message does not follow the pattern\n ! [remote rejected] HEAD -> x"
    out = explain(err(stderr, code=1))
    assert out.refused is True and out.transient is False and out.code is ExitCode.INTERNAL_ERROR


def test_a_permission_failure_is_exit_3_even_beside_a_server_error_marker():
    out = explain(err("remote: Service Unavailable\nremote: You are not allowed to push code to this project."))
    assert out.code is ExitCode.DOCTOR_FAILED and out.transient is False and "write_repository" in str(out)


def test_a_moved_ref_is_never_transient():
    out = explain(err(" ! [rejected] HEAD -> x (non-fast-forward)\nremote: Internal Server Error", PushRejected, 1))
    assert out.transient is False and "never forces" in str(out)


def test_a_failure_is_not_transient_unless_the_explanation_says_so():
    assert PushFailed(ExitCode.INTERNAL_ERROR, "m").transient is False


def test_the_sweeper_does_not_count_a_transient_failure_as_definitive():
    from l4.ci.sweeper import definitive_reason

    assert definitive_reason(explain(err(GITHUB_SERVER_ERROR, code=1))) is None
    refused = explain(err(" ! [remote rejected] HEAD -> x (pre-receive hook declined)", code=1))
    assert definitive_reason(refused) is not None


def test_an_http_4xx_is_not_told_to_be_the_forges_failure():
    stderr = (
        "error: RPC failed; HTTP 413 curl 22 The requested URL returned error: 413\n"
        "send-pack: unexpected disconnect while reading sideband packet\n"
        "fatal: the remote end hung up unexpectedly\n"
    )
    out = explain(err(stderr, code=128))
    assert out.transient is False and out.refused is False and out.code is ExitCode.INTERNAL_ERROR
    assert "failed on its side" not in str(out) and "RPC failed; HTTP 413" in str(out)


def test_gitlabs_unreachable_api_is_transient_and_not_a_hook_refusal():
    stderr = (
        "remote: Failed to authorize your Git request: internal API unreachable\n"
        " ! [remote rejected] HEAD -> x (pre-receive hook declined)\n"
    )
    out = explain(err(stderr, code=1))
    assert out.transient is True and out.refused is False


def _tried(tries):
    exc = err(GITHUB_SERVER_ERROR, code=1)
    exc.tries = tries
    return str(explain(exc))


def test_no_retry_is_claimed_for_a_push_that_ran_once():
    text = _tried(1)
    assert "tried" not in text and "failed on its side (a server or network error, not a refusal)" in text
    assert "Nothing is wrong with the branch or the credential: a later push should work" in text


def test_the_number_of_tries_is_named_when_there_were_several():
    assert "the harness tried 3 times" in _tried(3)
    assert "the harness tried 2 times" in _tried(2)


# --- a refused lease of the unit branch, classified (L4-RACE-001, design D4) ------------------------------

STALE = " ! [rejected]        HEAD -> l4/openspec/x (stale info)\n"
HEAD = "a" * 40
RESTART = "l4 restart --unit openspec:x --reason TEXT"


def lease():
    return err(STALE, PushRejected, 1)


def test_a_gone_branch_keeps_the_text_of_a_deleted_one_and_names_restart():
    plain, gone = explain(lease()), explain(BranchGone(lease()))
    assert str(gone) == str(plain)  # W-D2, unchanged
    assert gone.code is ExitCode.INTERNAL_ERROR and "deleted or moved" in str(gone) and RESTART in str(gone)


def test_a_branch_that_moved_with_other_files_names_them_and_the_next_run_and_not_restart():
    out = explain(BranchMoved(lease(), HEAD, ["src/app.py"], 2))
    text = str(out)
    assert out.code is ExitCode.INTERNAL_ERROR and not out.transient and not out.refused
    assert f"a person pushed 2 commits to {BRANCH} during this run that change src/app.py" in text
    assert "merges only answers to `questions.md`" in text and "The next run starts from the forge's branch" in text
    assert "l4 restart" not in text and "never forces" not in text and "deleted" not in text


def test_one_commit_is_said_in_the_singular_and_many_paths_are_cut():
    assert "pushed 1 commit to" in str(explain(BranchMoved(lease(), HEAD, ["a.py"], 1)))
    many = [f"f{i}.py" for i in range(8)]
    text = str(explain(BranchMoved(lease(), HEAD, many, 8)))
    assert "f0.py, f1.py, f2.py, f3.py, f4.py (+3 more)" in text and "f5.py" not in text


def test_a_merge_the_harness_could_not_settle_says_so_and_names_the_files():
    out = explain(
        BranchMoved(lease(), HEAD, ["openspec/changes/x/questions.md"], 1, ["openspec/changes/x/questions.md"])
    )
    text = str(out)
    assert (
        out.code is ExitCode.INTERNAL_ERROR and "could not merge" in text and "openspec/changes/x/questions.md" in text
    )
    assert "The next run starts from the forge's branch" in text and "l4 restart" not in text


def test_a_rewritten_branch_says_so_never_forces_and_leaves_restart_to_a_person():
    out = explain(BranchRewritten(lease(), HEAD, "b" * 40))
    text = str(out)
    assert out.code is ExitCode.INTERNAL_ERROR and f"{BRANCH} was rewritten on the forge" in text
    assert "no longer contains this run's last push" in text and "never forces" in text
    assert "A person decides" in text and RESTART in text


def test_a_branch_that_appeared_where_none_was_expected_is_told_apart():
    text = str(explain(BranchRewritten(lease(), HEAD, "")))
    assert "exists on the forge, where this run expected none" in text and RESTART in text
    assert "no longer contains" not in text


def test_a_branch_that_keeps_moving_says_answers_come_faster_than_they_are_merged():
    moved = BranchMoved(lease(), HEAD, ["openspec/changes/x/questions.md"], 1)
    keeps = BranchKeepsMoving(moved, HEAD, moved.paths, 1)
    keeps.tries = 3
    out = explain(keeps)
    text = str(out)
    assert out.code is ExitCode.INTERNAL_ERROR and "the unit branch keeps moving on the forge" in text
    assert "a person's answers arrive faster than the run can merge them" in text and "tried 3 times" in text
    assert "The answers stay on the forge" in text and "l4 restart" not in text


def test_only_gone_and_rewritten_name_restart():
    cases = {
        "gone": BranchGone(lease()),
        "moved": BranchMoved(lease(), HEAD, ["src/app.py"], 1),
        "conflict": BranchMoved(lease(), HEAD, ["q.md"], 1, ["q.md"]),
        "keeps": BranchKeepsMoving(BranchMoved(lease(), HEAD, ["q.md"], 1), HEAD, ["q.md"], 1),
        "rewritten": BranchRewritten(lease(), HEAD, "b" * 40),
        "plain": lease(),
    }
    named = {name for name, exc in cases.items() if "l4 restart" in str(explain(exc))}
    assert named == {"gone", "rewritten", "plain"}  # a plain, unclassified `stale info` keeps the old text


def test_a_plain_non_fast_forward_without_stale_info_keeps_its_text():
    out = explain(err(" ! [rejected] HEAD -> x (non-fast-forward)", PushRejected, 1))
    assert "a human pushed; the next run continues from it" in str(out)


def test_the_classified_messages_are_one_redacted_line():
    out = explain(BranchMoved(lease(), HEAD, [f"src/{TOKEN}.py"], 1), redact=lambda s: s.replace(TOKEN, "[R]"))
    assert len(str(out).splitlines()) == 1 and TOKEN not in str(out) and "src/[R].py" in str(out)
