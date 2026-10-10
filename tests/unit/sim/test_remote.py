import tempfile
from pathlib import Path

import pytest

from l4.sim.remote import BASE_BRANCH, SimRepo, write_files


def test_temp_dirs_only_and_keep_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = SimRepo.create("openspec-basic")
    assert repo.root.name.startswith("l4-sim-") and repo.root.parent == Path(tempfile.gettempdir())
    assert tmp_path not in repo.root.parents and list(tmp_path.iterdir()) == []  # nothing in the working directory
    assert (repo.clone / "tests" / "run_junit.py").is_file() and repo.remote.is_dir()
    repo.cleanup()
    assert not repo.root.exists()
    kept = SimRepo.create("openspec-basic", keep=True)
    kept.cleanup()
    assert kept.root.exists()
    SimRepo(kept.root, kept.remote, kept.clone, kept.git).cleanup()
    assert not kept.root.exists()


def test_commit_shas_are_deterministic(tmp_path):
    first = SimRepo.create("openspec-basic", root=tmp_path / "one")
    second = SimRepo.create("openspec-basic", root=tmp_path / "two")
    other = SimRepo.create("kiro-basic", root=tmp_path / "three")
    head = lambda r: r.git.run("rev-parse", "HEAD").stdout.strip()  # noqa: E731
    assert head(first) == head(second) != head(other)
    assert first.git.run("log", "--format=%an <%ae> %aI %cI %s").stdout.strip() == (
        "Sim Seed <sim-seed@example.invalid> 2026-01-01T00:01:00Z 2026-01-01T00:01:00Z seed: openspec-basic"
    )


def test_the_clone_tracks_a_bare_remote_with_the_seed_on_main(tmp_path):
    repo = SimRepo.create("kiro-basic", root=tmp_path / "w")
    assert repo.git.run("rev-parse", "--is-bare-repository").stdout.strip() == "false"
    remote = repo.git.at(repo.remote)
    assert remote.run("rev-parse", "--is-bare-repository").stdout.strip() == "true"
    assert remote.rev_parse(BASE_BRANCH) == repo.git.rev_parse("HEAD") == repo.git.rev_parse("origin/main")
    listing = repo.git.run("ls-files").stdout.split()
    assert ".kiro/specs/user-greeting/tasks.md" in listing and "tests/run_junit.py" in listing
    assert repo.git.run("status", "--porcelain").stdout == ""


def test_every_git_call_goes_through_the_hardened_wrapper_without_the_developers_config(tmp_path):
    repo = SimRepo.create("openspec-basic", root=tmp_path / "w")
    hardening = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.ext.allow=never"]
    assert repo.git.history and all(call[1:7] == hardening for call in repo.git.history)
    assert repo.git.env["GIT_CONFIG_GLOBAL"] == "/dev/null" and repo.git.env["HOME"] == str(repo.root)


def test_human_commit_lands_on_the_remote_branch_and_not_in_the_clone(tmp_path):
    repo = SimRepo.create("openspec-basic", root=tmp_path / "w")
    before = repo.git.rev_parse("HEAD")
    sha = repo.human_commit({"questions.md": "answer\n"}, "human: answer")
    remote = repo.git.at(repo.remote)
    assert remote.rev_parse("main") == sha and repo.git.rev_parse("HEAD") == before
    assert remote.run("show", "main:questions.md").stdout == "answer\n"
    assert remote.run("log", "-1", "--format=%an %s", "main").stdout.strip() == "Sim Human human: answer"
    branch_sha = repo.human_commit({"a.txt": "x"}, "on a unit branch", branch="l4/openspec/add-greeting")
    assert remote.rev_parse("l4/openspec/add-greeting") == branch_sha
    again = repo.human_commit({"a.txt": "y"}, "second", branch="l4/openspec/add-greeting")
    assert remote.run("rev-list", "--count", "l4/openspec/add-greeting").stdout.strip() == "4" and again != branch_sha


def test_write_files_refuses_paths_outside_the_repository(tmp_path):
    write_files(tmp_path, {"a/b.txt": "ok"})
    assert (tmp_path / "a" / "b.txt").read_text() == "ok"
    for bad in ("../x.txt", "/etc/passwd-copy"):
        with pytest.raises(ValueError):
            write_files(tmp_path, {bad: "x"})


def test_a_fixture_copy_skips_run_output_and_bytecode(tmp_path):
    from l4.sim.remote import _copy

    source = tmp_path / "src"
    for rel in ("keep.py", ".l4-out/l4.env", "pkg/__pycache__/x.cpython-311.pyc", "pkg/mod.py", "pkg/stale.pyc"):
        (source / rel).parent.mkdir(parents=True, exist_ok=True)
        (source / rel).write_text("x")
    _copy(source, tmp_path / "out")
    assert sorted(str(p.relative_to(tmp_path / "out")) for p in (tmp_path / "out").rglob("*") if p.is_file()) == [
        "keep.py",
        "pkg/mod.py",
    ]
