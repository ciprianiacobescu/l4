import pytest

from l4.vcs.git import Git
from l4.vcs.wip import WipMismatch, restore_wip, snapshot_wip, wip_ref

UNIT = "openspec:add-login"
BINARY = bytes(range(256)) * 4 + b"\x00\xff"


@pytest.fixture
def repo(make_repo, git_environ, raw):
    path = make_repo("work")
    (path / "src").mkdir()
    (path / "src" / "keep.py").write_text("keep = 1\n")
    (path / "src" / "edit.py").write_text("edit = 1\n")
    (path / "src" / "gone.py").write_text("gone = 1\n")
    (path / "blob.bin").write_bytes(b"\x00\x01old")
    raw(path, "add", "-A")
    raw(path, "commit", "-q", "-m", "seed files")
    return path


@pytest.fixture
def git(repo, git_environ) -> Git:
    return Git(repo, environ=git_environ)


def dirty(repo) -> None:
    (repo / "src" / "edit.py").write_text("edit = 2\n")  # modified
    (repo / "src" / "gone.py").unlink()  # deleted
    (repo / "src" / "new.py").write_text("new = 1\n")  # untracked
    (repo / "blob.bin").write_bytes(BINARY)  # binary, modified
    (repo / "fresh.bin").write_bytes(b"\xff\x00" * 100)  # binary, untracked


def state(git: Git) -> dict[str, str]:
    return {
        "status": git.run("status", "--porcelain=v1", "--untracked-files=all").stdout,
        "head": git.run("rev-parse", "HEAD").stdout,
        "stash": git.run("stash", "list").stdout,
        "index": git.run("write-tree").stdout,
        "branch": git.run("rev-parse", "--abbrev-ref", "HEAD").stdout,
    }


def test_snapshot_leaves_worktree_untouched(repo, git):
    dirty(repo)
    before = state(git)
    files_before = {
        p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts
    }
    sha = snapshot_wip(git, UNIT)
    assert state(git) == before  # real index, HEAD, stash and status are exactly as they were
    after = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert after == files_before
    assert sha and git.run("rev-parse", wip_ref(UNIT)).stdout.strip() == sha
    assert git.run("rev-parse", f"{sha}^").stdout == before["head"]  # one commit on top of HEAD
    assert "GIT_INDEX_FILE" not in git.env
    contents = {
        "src/edit.py": b"edit = 2\n", "src/new.py": b"new = 1\n", "blob.bin": BINARY, "fresh.bin": b"\xff\x00" * 100,
    }  # fmt: skip
    for path, data in contents.items():
        assert git.run_bytes("show", f"{sha}:{path}") == data
    assert git.run("cat-file", "-e", f"{sha}:src/gone.py", check=False).returncode != 0  # the deletion is in it
    assert git.run("ls-tree", "-r", "--name-only", f"{sha}").stdout.split() == sorted(
        ["README.md", "blob.bin", "fresh.bin", "src/edit.py", "src/keep.py", "src/new.py"]
    )


def test_a_clean_worktree_makes_no_snapshot_and_keeps_the_old_one(repo, git):
    assert snapshot_wip(git, UNIT) is None
    assert git.rev_parse(wip_ref(UNIT)) is None
    (repo / "src" / "edit.py").write_text("edit = 9\n")
    first = snapshot_wip(git, UNIT)
    git.run("checkout", "--", "src/edit.py")
    assert snapshot_wip(git, UNIT) is None
    assert git.run("rev-parse", wip_ref(UNIT)).stdout.strip() == first


def test_each_snapshot_moves_the_ref_and_builds_on_head(repo, git):
    (repo / "a.txt").write_text("1")
    first = snapshot_wip(git, UNIT)
    (repo / "a.txt").write_text("2")
    second = snapshot_wip(git, UNIT)
    assert first != second and git.run("rev-parse", f"{second}^").stdout == git.run("rev-parse", "HEAD").stdout
    assert git.run("rev-parse", wip_ref(UNIT)).stdout.strip() == second


def test_restore_reproduces_content(repo, git):
    dirty(repo)
    expected = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}
    status = git.run("status", "--porcelain=v1", "--untracked-files=all").stdout
    sha = snapshot_wip(git, UNIT)
    git.run("reset", "--hard", "-q")
    git.run("clean", "-fdq")
    assert git.run("status", "--porcelain").stdout == ""  # a fresh worktree: all the work is gone
    restore_wip(git, sha)
    restored = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert restored == expected
    assert not (repo / "src" / "gone.py").exists()
    assert git.run("status", "--porcelain=v1", "--untracked-files=all").stdout == status  # unstaged again, as before
    assert git.run("diff", "--cached", "--name-only").stdout == ""
    assert git.run("rev-parse", "HEAD").stdout == git.run("rev-parse", f"{sha}^").stdout


def test_restore_works_in_a_linked_worktree(repo, git, raw, tmp_path):
    linked = tmp_path / "linked"
    raw(repo, "worktree", "add", "-q", "-b", "l4/openspec/add-login", str(linked))
    inside = git.at(linked)
    (linked / "src" / "edit.py").write_text("edit = 5\n")
    (linked / "untracked.txt").write_text("u")
    sha = snapshot_wip(inside, UNIT)
    assert sha and git.run("status", "--porcelain").stdout == ""  # the main worktree is not involved
    inside.run("checkout", "--", "src/edit.py")
    (linked / "untracked.txt").unlink()
    restore_wip(inside, sha)
    assert (linked / "src" / "edit.py").read_text() == "edit = 5\n" and (linked / "untracked.txt").read_text() == "u"


def test_restore_refuses_a_snapshot_taken_on_another_head(repo, git, raw):
    (repo / "a.txt").write_text("1")
    sha = snapshot_wip(git, UNIT)
    (repo / "a.txt").unlink()
    (repo / "b.txt").write_text("2")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "moved on")
    with pytest.raises(WipMismatch, match="not taken on this worktree"):
        restore_wip(git, sha)
    assert not (repo / "a.txt").exists()  # nothing was written


def test_harness_excludes_stay_out_of_the_snapshot(repo, git, tmp_path):
    excludes = tmp_path / "excludes"
    excludes.write_text(".l4-out/\n__pycache__/\n")
    (repo / ".l4-out").mkdir()
    (repo / ".l4-out" / "junit.xml").write_text("<x/>")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "__pycache__").mkdir()
    (repo / "pkg" / "__pycache__" / "m.pyc").write_bytes(b"\x00")
    (repo / "real.py").write_text("x = 1\n")
    sha = snapshot_wip(git, UNIT, config=(("core.excludesFile", str(excludes)),))
    listed = git.run("ls-tree", "-r", "--name-only", sha).stdout.split()
    assert sorted(listed) == ["README.md", "blob.bin", "real.py", "src/edit.py", "src/gone.py", "src/keep.py"]


def test_unit_ref_is_local_and_validated():
    assert wip_ref("kiro:user-auth") == "refs/l4/wip/kiro/user-auth"
    with pytest.raises(ValueError):
        wip_ref("not-a-unit")
    with pytest.raises(ValueError):
        wip_ref("openspec:../x")


def test_restore_with_an_exclude_leaves_that_path_alone_and_restores_the_rest(repo, git):
    (repo / "ledger.jsonl").write_text("one\n")
    git.run("add", "ledger.jsonl")
    git.run("commit", "-q", "-m", "ledger")
    dirty(repo)
    expected = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}
    sha = snapshot_wip(git, UNIT, exclude="ledger.jsonl")
    git.run("reset", "--hard", "-q")
    git.run("clean", "-fdq")
    (repo / "ledger.jsonl").write_text("one\ntwo\n")  # a line written since the snapshot
    restore_wip(git, sha, exclude="ledger.jsonl")
    assert (repo / "ledger.jsonl").read_text() == "one\ntwo\n"
    expected[(repo / "ledger.jsonl").relative_to(repo)] = b"one\ntwo\n"
    restored = {p.relative_to(repo): p.read_bytes() for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert restored == expected and not (repo / "src" / "gone.py").exists()
    assert git.run("diff", "--cached", "--name-only").stdout == ""


def _files(repo) -> dict[str, bytes]:
    found = (p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts)
    return {p.relative_to(repo).as_posix(): p.read_bytes() for p in found}


def _set_aside_and_restore(repo, git, exclude: str) -> None:
    sha = snapshot_wip(git, UNIT, update_ref=False, exclude=exclude)
    git.run("checkout", "HEAD", "--", ".", f":(exclude){exclude}")  # what `Workbench.at_clean_head` does meanwhile
    git.run("clean", "-fdq", "-e", f"/{exclude}")
    with (repo / exclude).open("a") as ledger:
        ledger.write("two\n")  # a line written while the work is set aside
    restore_wip(git, sha, exclude=exclude)


@pytest.mark.parametrize("swap", ["dir_to_file", "file_to_dir"])
def test_restore_with_an_exclude_puts_back_a_directory_and_a_file_that_swapped_places(repo, git, swap):
    ledger = "spec/.l4/ledger/run.jsonl"
    (repo / ledger).parent.mkdir(parents=True)
    (repo / ledger).write_text("one\n")
    git.run("add", "-A")
    git.run("commit", "-q", "-m", "ledger")
    if swap == "dir_to_file":  # src/ (three tracked files) becomes a file named src
        for name in ("keep.py", "edit.py", "gone.py"):
            (repo / "src" / name).unlink()
        (repo / "src").rmdir()
        (repo / "src").write_text("now a file\n")
    else:  # the tracked file blob.bin becomes a directory
        (repo / "blob.bin").unlink()
        (repo / "blob.bin").mkdir()
        (repo / "blob.bin" / "x.py").write_text("x = 1\n")
    expected = _files(repo) | {ledger: b"one\ntwo\n"}
    _set_aside_and_restore(repo, git, ledger)
    assert _files(repo) == expected
    assert git.run("diff", "--cached", "--name-only").stdout == ""


def test_restore_with_an_exclude_leaves_no_emptied_directory_behind(repo, git):
    ledger = "ledger.jsonl"
    (repo / ledger).write_text("one\n")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "only.py").write_text("only = 1\n")
    git.run("add", "-A")
    git.run("commit", "-q", "-m", "seed")
    (repo / "pkg" / "only.py").unlink()
    (repo / "pkg").rmdir()
    _set_aside_and_restore(repo, git, ledger)
    assert not (repo / "pkg").exists()
    assert (repo / ledger).read_text() == "one\ntwo\n"
