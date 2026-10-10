import subprocess
from pathlib import Path

from l4.eval.seeds import load_seed_set
from l4.eval.workspace import Identity, make_workspace

ID = Identity("CiprianSpot", "maintainer@example.invalid")


def _git(cwd: Path, *args: str) -> str:
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout.strip()


def test_a_workspace_is_a_bare_mirror_and_a_fresh_clone(seeds_root: Path, tmp_path: Path) -> None:
    seeds = load_seed_set(seeds_root)
    ws = make_workspace(seeds, seeds.unit("add-shelf-code"), tmp_path / "a", identity=ID)
    assert ws.origin.name == "origin.git" and _git(ws.origin, "rev-parse", "--is-bare-repository") == "true"
    assert (ws.repo / ".git").is_dir()
    assert _git(ws.repo, "remote", "get-url", "origin") == str(ws.origin)
    assert _git(ws.repo, "status", "--porcelain") == ""
    assert _git(ws.repo, "rev-parse", "HEAD") == _git(ws.origin, "rev-parse", "main")
    assert _git(ws.repo, "branch", "--show-current") == "main"


def test_two_calls_do_not_share_a_git_dir_and_hash_alike(seeds_root: Path, tmp_path: Path) -> None:
    seeds = load_seed_set(seeds_root)
    one = make_workspace(seeds, seeds.unit("add-shelf-code"), tmp_path / "a", identity=ID)
    two = make_workspace(seeds, seeds.unit("add-shelf-code"), tmp_path / "b", identity=ID)
    assert one.repo / ".git" != two.repo / ".git"
    assert one.origin != two.origin
    assert (_git(one.repo, "rev-parse", "origin/main")) == _git(two.repo, "rev-parse", "origin/main")
    other = make_workspace(seeds, seeds.unit("add-tip-amount"), tmp_path / "c", identity=ID)
    assert _git(other.repo, "rev-parse", "origin/main") != _git(one.repo, "rev-parse", "origin/main")


def test_the_commit_has_the_identity_and_fixed_dates(seeds_root: Path, tmp_path: Path) -> None:
    seeds = load_seed_set(seeds_root)
    ws = make_workspace(seeds, seeds.unit("add-tip-amount"), tmp_path / "a", identity=ID)
    assert _git(ws.repo, "log", "-1", "--format=%an <%ae>|%cn <%ce>|%aI|%cI") == (
        "CiprianSpot <maintainer@example.invalid>|CiprianSpot <maintainer@example.invalid>|"
        "2026-10-07T00:00:00Z|2026-10-07T00:00:00Z"
    )
    assert _git(ws.repo, "config", "user.email") == ID.email  # the harness commits in this clone


def test_the_unit_is_on_main_and_nothing_that_gives_the_answer(seeds_root: Path, tmp_path: Path) -> None:
    seeds = load_seed_set(seeds_root)
    ws = make_workspace(seeds, seeds.unit("add-reorder-quantity"), tmp_path / "a", identity=ID)
    files = _git(ws.repo, "ls-files").splitlines()
    assert "openspec/changes/add-reorder-quantity/tasks.md" in files
    assert "openspec/changes/add-reorder-quantity/specs/reorder-quantity/spec.md" in files
    assert "pyproject.toml" in files and "uv.lock" in files and "src/pricing/money.py" in files
    assert not any("expected.json" in f or "reference" in f or "hidden_check" in f for f in files)
    assert not any(f.startswith("openspec/changes/add-") and "reorder" not in f for f in files)  # no other unit
    assert not (ws.repo / "src" / "inventory" / "reorder.py").exists()


def test_a_second_unit_is_a_seed_for_nobody_else(seeds_root: Path, tmp_path: Path) -> None:
    seeds = load_seed_set(seeds_root)
    ws = make_workspace(seeds, seeds.unit("add-late-fee"), tmp_path / "a", identity=ID)
    changes = sorted(p.name for p in (ws.repo / "openspec" / "changes").iterdir())
    assert changes == ["add-late-fee"]


def test_the_workspace_directory_is_made_fresh(seeds_root: Path, tmp_path: Path) -> None:
    seeds = load_seed_set(seeds_root)
    target = tmp_path / "a"
    target.mkdir()
    (target / "stale.txt").write_text("old")
    ws = make_workspace(seeds, seeds.unit("add-shelf-code"), target, identity=ID)
    assert not (target / "stale.txt").exists() and ws.repo.is_dir()


def test_a_finder_file_is_not_committed(seeds_root: Path, tmp_path: Path) -> None:
    import shutil

    copy = tmp_path / "seeds"
    shutil.copytree(seeds_root, copy)
    for folder in (copy / "base", copy / "base" / "src", copy / "units" / "add-shelf-code"):
        (folder / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
    seeds = load_seed_set(copy)
    ws = make_workspace(seeds, seeds.unit("add-shelf-code"), tmp_path / "w", identity=ID)
    assert ".DS_Store" not in _git(ws.repo, "ls-files")
    clean = make_workspace(load_seed_set(seeds_root), load_seed_set(seeds_root).unit("add-shelf-code"), tmp_path / "x",
                           identity=ID)  # fmt: skip
    assert _git(ws.repo, "rev-parse", "HEAD") == _git(clean.repo, "rev-parse", "HEAD")
