"""HB-4: every outgoing commit is scanned for secrets before a push (known values and token shapes), the hit names the
path and the kind and never the value."""

from pathlib import Path

from l4.redact import Redactor
from l4.vcs.secretscan import SecretHit, outgoing_secrets, worktree_secrets

ANTHROPIC = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0"
GITLAB = "glpat-" + "x1y2z3w4v5u6t7s8r9q0"
MINTKEY = "mk_" + "agent_" + "Q7w8E9r0T1y2U3i4O5p6"
BASE = "refs/remotes/origin/main"
BRANCH = "refs/remotes/origin/l4/x"


def commit(repo: Path, raw, name: str, text: str, message: str = "c") -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", message)


def scan(repo, git_for, redactor=None, exclude=(BASE,)):
    return outgoing_secrets(git_for(repo), redactor or Redactor({}), exclude=exclude)


def test_a_committed_anthropic_key_is_found_by_path_and_kind_and_the_value_is_not_in_the_hit(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    commit(repo, raw, "src/config.py", f'KEY = "{ANTHROPIC}"\n')
    hits = scan(repo, git_for)
    assert hits == [SecretHit("src/config.py", "anthropic-key")]
    assert ANTHROPIC not in repr(hits) and "A1b2C3d4" not in repr(hits)


def test_a_clean_diff_and_nothing_outgoing_give_no_hit(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    assert scan(repo, git_for) == []  # nothing outgoing
    commit(repo, raw, "src/a.py", "x = 'sk-learn'\nsk_ant_not_a_key = 1\n")
    assert scan(repo, git_for) == []


def test_known_values_are_found_by_their_name(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    commit(repo, raw, "notes.txt", "token is hunter2hunter2\n")
    hits = scan(repo, git_for, Redactor({"L4_FORGE_TOKEN": "hunter2hunter2"}))
    assert hits == [SecretHit("notes.txt", "value:L4_FORGE_TOKEN")]
    assert "hunter2" not in repr(hits)


def test_a_secret_in_an_intermediate_commit_is_found_even_if_a_later_commit_removes_it(make_repo, raw, git_for):
    """Git pushes every commit's objects, not just the net diff."""
    repo = make_repo(remote=True)
    commit(repo, raw, "a.env", f"GITLAB={GITLAB}\n")
    commit(repo, raw, "a.env", "GITLAB=\n")
    assert scan(repo, git_for) == [SecretHit("a.env", "gitlab-pat")]


def test_only_added_lines_count_never_a_removed_one(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    commit(repo, raw, "a.env", f"GITLAB={GITLAB}\n", "seed")
    raw(repo, "push", "-q", "origin", "main")
    raw(repo, "fetch", "-q", "origin")
    commit(repo, raw, "a.env", "GITLAB=\n", "remove the secret")
    assert scan(repo, git_for) == []


def test_what_origin_already_has_is_not_scanned_again(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    raw(repo, "checkout", "-q", "-b", "l4/x")
    commit(repo, raw, "old.txt", f"{ANTHROPIC}\n", "already on the forge")
    raw(repo, "push", "-q", "origin", "l4/x")
    raw(repo, "fetch", "-q", "origin")
    assert scan(repo, git_for, exclude=(BRANCH, BASE)) == []
    commit(repo, raw, "new.txt", f"{GITLAB}\n")
    assert scan(repo, git_for, exclude=(BRANCH, BASE)) == [SecretHit("new.txt", "gitlab-pat")]


def test_commits_merged_in_from_the_base_branch_are_not_ours(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    raw(repo, "checkout", "-q", "-b", "l4/x")
    commit(repo, raw, "mine.py", "x = 1\n")
    raw(repo, "checkout", "-q", "main")
    commit(repo, raw, "theirs.txt", f"{ANTHROPIC}\n", "main moved")  # a secret that is already on the base branch
    raw(repo, "push", "-q", "origin", "main")
    raw(repo, "fetch", "-q", "origin")
    raw(repo, "checkout", "-q", "l4/x")
    raw(repo, "merge", "-q", "--no-edit", "main")
    assert scan(repo, git_for) == []


def test_a_private_key_block_and_an_unknown_remote_ref_work(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    body = "MIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu"
    key = f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----\n"
    commit(repo, raw, "deploy/id_rsa", key)
    hits = scan(repo, git_for, exclude=("refs/remotes/origin/missing", BASE))  # a ref that does not exist is skipped
    assert hits == [SecretHit("deploy/id_rsa", "private-key")]


def test_a_path_is_reported_once_per_kind(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    commit(repo, raw, "a.txt", f"{ANTHROPIC}\n{ANTHROPIC}\n{GITLAB}\n")
    assert scan(repo, git_for) == [SecretHit("a.txt", "anthropic-key"), SecretHit("a.txt", "gitlab-pat")]


# L4-SEC-008: the worktree an implementer step leaves is read before any gate or commit


def edit(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def step_scan(repo, git_for, paths, redactor=None):
    return worktree_secrets(git_for(repo), redactor or Redactor({}), paths)


def test_a_token_a_step_adds_to_a_tracked_file_or_writes_in_a_new_one_is_found(make_repo, raw, git_for):
    """SCN-SEC-20: a fixture that spells a token whole."""
    repo = make_repo(remote=True)
    commit(repo, raw, "tests/test_redact.py", "def test_a():\n    assert True\n")
    edit(repo, "tests/test_redact.py", f'def test_a():\n    assert True\n\n\nSECRET = "{MINTKEY}"\n')
    edit(repo, "tests/new_fixture.py", f'TOKEN = "{GITLAB}"\n')
    hits = step_scan(repo, git_for, ["tests/test_redact.py", "tests/new_fixture.py"])
    assert hits == [SecretHit("tests/test_redact.py", "mintkey"), SecretHit("tests/new_fixture.py", "gitlab-pat")]
    assert MINTKEY not in repr(hits)


def test_a_token_already_at_head_and_one_built_from_parts_are_not_found(make_repo, raw, git_for):
    """SCN-SEC-21: only the lines the step adds count, and a value built at run time holds no shape."""
    repo = make_repo(remote=True)
    commit(repo, raw, "tests/test_redact.py", f'OLD = "{MINTKEY}"\n')
    edit(repo, "tests/test_redact.py", f'OLD = "{MINTKEY}"\nNEW = "mk_" + "agent_" + "A" * 24\n')
    assert step_scan(repo, git_for, ["tests/test_redact.py"]) == []


def test_a_known_value_a_binary_a_symlink_and_an_unlisted_path(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    edit(repo, "notes.txt", "token is hunter2hunter2\n")
    (repo / "blob.bin").write_bytes(b"\x00" + GITLAB.encode())
    (repo / "link").symlink_to(repo / "notes.txt")
    edit(repo, "unlisted.py", f'X = "{GITLAB}"\n')
    hits = step_scan(repo, git_for, ["notes.txt", "blob.bin", "link"], Redactor({"L4_FORGE_TOKEN": "hunter2hunter2"}))
    assert hits == [SecretHit("notes.txt", "value:L4_FORGE_TOKEN")]


def test_a_deleted_file_and_no_path_give_no_hit(make_repo, raw, git_for):
    repo = make_repo(remote=True)
    commit(repo, raw, "old.py", f'X = "{GITLAB}"\n')
    (repo / "old.py").unlink()
    assert step_scan(repo, git_for, ["old.py"]) == [] and step_scan(repo, git_for, []) == []
