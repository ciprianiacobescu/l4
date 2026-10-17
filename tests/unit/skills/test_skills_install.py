"""`l4 skills install|status` (L4-SKL-003, SCN-SKL-04..07): the bundled skill reaches every agent's skill folder."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from l4 import skills_cli
from l4.cli import main

ROOT = Path(__file__).resolve().parents[3]
REPO_SKILL = ROOT / "plugins" / "l4" / "skills" / "l4"
MANIFEST = ".l4-skill.json"


def tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("HOME", str(home))
    env = {"HOME": str(home), "PATH": str(empty_bin)}

    class World:
        pass

    w = World()
    w.home, w.bin, w.repo, w.env = home, empty_bin, repo, env

    def run(*args: str, **kw):
        return main(["skills", *args, "--repo", str(repo)], environ={**env, **kw})

    w.run = run
    return w


# --- 1. package data -------------------------------------------------------------------------------------------------


def test_the_bundled_skill_is_byte_equal_to_the_repository_copy():  # task 1.1
    bundled = skills_cli.bundled_skill_dir()
    assert tree(bundled) == tree(REPO_SKILL)
    assert "SKILL.md" in tree(bundled)


def test_the_source_checkout_fallback_is_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(skills_cli, "_packaged_skill", lambda: None)  # no force-include (an editable install)
    assert skills_cli.bundled_skill_dir() == REPO_SKILL
    monkeypatch.setattr(skills_cli, "_SOURCE_SKILL", tmp_path / "nowhere")
    with pytest.raises(skills_cli.SkillSourceError):
        skills_cli.bundled_skill_dir()


def test_a_packaged_copy_wins_over_the_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    packaged = tmp_path / "l4"
    packaged.mkdir()
    (packaged / "SKILL.md").write_text("x")
    monkeypatch.setattr(skills_cli, "_packaged_skill", lambda: packaged)
    assert skills_cli.bundled_skill_dir() == packaged


def test_a_built_wheel_and_a_wheel_built_from_the_sdist_hold_the_skill(tmp_path: Path):  # task 1.1
    import shutil
    import zipfile

    if shutil.which("uv") is None:
        pytest.skip("uv is not installed")
    sdist_dir, wheel_dir, from_sdist = tmp_path / "sdist", tmp_path / "wheel", tmp_path / "from-sdist"
    for argv in (
        ["uv", "build", "--sdist", "--offline", "-o", str(sdist_dir), str(ROOT)],
        ["uv", "build", "--wheel", "--offline", "-o", str(wheel_dir), str(ROOT)],
    ):
        done = subprocess.run(argv, capture_output=True, text=True, check=False)
        if done.returncode != 0:
            pytest.skip(f"cannot build offline: {done.stderr[-300:]}")
    [sdist] = sdist_dir.glob("*.tar.gz")
    unpacked = tmp_path / "unpacked"
    shutil.unpack_archive(sdist, unpacked)
    [src] = unpacked.iterdir()
    done = subprocess.run(
        ["uv", "build", "--wheel", "--offline", "-o", str(from_sdist), str(src)], capture_output=True, text=True
    )
    if done.returncode != 0:
        pytest.skip(f"cannot build from the sdist offline: {done.stderr[-300:]}")
    expected = tree(REPO_SKILL)
    for folder in (wheel_dir, from_sdist):
        [wheel] = folder.glob("*.whl")
        with zipfile.ZipFile(wheel) as zf:
            prefix = "l4/_skill/l4/"
            held = {n[len(prefix) :]: zf.read(n) for n in zf.namelist() if n.startswith(prefix) and not n.endswith("/")}
        assert held == expected


# --- 2. install ------------------------------------------------------------------------------------------------------


def test_scn_skl_04_installs_for_the_agents_that_are_present(world, capsys):
    (world.home / ".claude").mkdir()
    (world.home / ".kiro").mkdir()
    assert world.run("install") == 0
    out = capsys.readouterr().out
    for agent_dir in (".claude", ".kiro"):
        target = world.home / agent_dir / "skills" / "l4"
        assert tree(target).pop(MANIFEST)
        files = {k: v for k, v in tree(target).items() if k != MANIFEST}
        assert files == tree(REPO_SKILL)
        manifest = json.loads((target / MANIFEST).read_text())
        assert manifest["name"] == "l4"
        import l4

        assert manifest["version"] == l4.__version__
        assert manifest["files"] == {k: sha(v) for k, v in tree(REPO_SKILL).items()}
        assert str(target) in out
    # nothing else is written
    assert sorted(p.name for p in world.home.iterdir()) == [".claude", ".kiro"]
    assert sorted(p.name for p in (world.home / ".claude").iterdir()) == ["skills"]
    assert sorted(p.name for p in (world.home / ".claude" / "skills").iterdir()) == ["l4"]
    assert not (world.repo / ".claude").exists()


def test_auto_detects_by_cli_on_path_and_by_the_other_home_folders(world):
    for name in ("codex", "opencode"):
        exe = world.bin / name
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
    (world.home / ".config" / "opencode").mkdir(parents=True)  # home folder of OpenCode as well
    assert world.run("install") == 0
    assert (world.home / ".agents" / "skills" / "l4" / "SKILL.md").exists()  # codex via its CLI
    assert not (world.home / ".codex").exists()
    assert (world.home / ".config" / "opencode" / "skills" / "l4" / "SKILL.md").exists()
    assert not (world.home / ".claude").exists() and not (world.home / ".kiro").exists()


def test_kiro_cli_name_and_alternative_home_folders_are_detected(world):
    exe = world.bin / "kiro-cli"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    (world.home / ".opencode").mkdir()
    (world.home / ".codex").mkdir()
    assert world.run("install") == 0
    assert (world.home / ".kiro" / "skills" / "l4" / "SKILL.md").exists()
    assert (world.home / ".config" / "opencode" / "skills" / "l4" / "SKILL.md").exists()
    assert (world.home / ".agents" / "skills" / "l4" / "SKILL.md").exists()


def test_codex_writes_both_paths_when_codex_skills_exists(world):
    (world.home / ".codex" / "skills").mkdir(parents=True)
    assert world.run("install") == 0
    assert (world.home / ".agents" / "skills" / "l4" / "SKILL.md").exists()
    assert (world.home / ".codex" / "skills" / "l4" / "SKILL.md").exists()


def test_codex_writes_only_the_open_path_when_codex_skills_is_absent(world):
    (world.home / ".codex").mkdir()
    assert world.run("install") == 0
    assert (world.home / ".agents" / "skills" / "l4" / "SKILL.md").exists()
    assert not (world.home / ".codex" / "skills").exists()


def test_auto_with_no_agent_present_exits_2_and_writes_nothing(world, capsys):
    assert world.run("install") == 2
    assert "--agent all" in capsys.readouterr().err
    assert list(world.home.iterdir()) == []


def test_an_agent_can_be_named(world):
    assert world.run("install", "--agent", "opencode") == 0
    assert (world.home / ".config" / "opencode" / "skills" / "l4" / "SKILL.md").exists()
    assert not (world.home / ".claude").exists()


def test_an_unknown_agent_is_a_usage_error(world):
    assert world.run("install", "--agent", "emacs") == 2


def test_scn_skl_05_a_rerun_after_an_upgrade_updates_in_place(world, monkeypatch, capsys):
    (world.home / ".claude").mkdir()
    (world.home / ".kiro").mkdir()
    monkeypatch.setattr(skills_cli, "__version__", "0.4.12")
    assert world.run("install") == 0
    target = world.home / ".claude" / "skills" / "l4"
    # the old install had an extra bundled file that the new l4 no longer ships, and an older SKILL.md
    (target / "references" / "gone.md").write_text("old\n")
    (target / "SKILL.md").write_text("old skill\n")
    for agent_dir in (".claude", ".kiro"):
        t = world.home / agent_dir / "skills" / "l4"
        data = {"name": "l4", "version": "0.4.12", "files": {}}
        files = {
            k: sha(v.read_bytes())
            for k, v in ((p.relative_to(t).as_posix(), p) for p in t.rglob("*") if p.is_file())
            if k != MANIFEST
        }
        if agent_dir == ".claude":
            files["SKILL.md"] = sha(b"old skill\n")
            files["references/gone.md"] = sha(b"old\n")
        data["files"] = files
        (t / MANIFEST).write_text(json.dumps(data))
    monkeypatch.setattr(skills_cli, "__version__", "0.4.13")
    capsys.readouterr()
    assert world.run("status") == 0
    assert capsys.readouterr().out.count("\told") == 2
    assert world.run("install") == 0
    for agent_dir in (".claude", ".kiro"):
        t = world.home / agent_dir / "skills" / "l4"
        assert {k: v for k, v in tree(t).items() if k != MANIFEST} == tree(REPO_SKILL)
        assert json.loads((t / MANIFEST).read_text())["version"] == "0.4.13"
    capsys.readouterr()
    assert world.run("status") == 0
    out = capsys.readouterr().out
    assert out.count("\tcurrent") == 2 and "\told" not in out


def test_a_second_run_changes_nothing(world, capsys):
    (world.home / ".claude").mkdir()
    assert world.run("install") == 0
    target = world.home / ".claude" / "skills" / "l4"
    before = {p: p.stat().st_mtime_ns for p in target.rglob("*") if p.is_file()}
    capsys.readouterr()
    assert world.run("install") == 0
    assert "unchanged" in capsys.readouterr().out
    assert {p: p.stat().st_mtime_ns for p in target.rglob("*") if p.is_file()} == before


def test_scn_skl_06_an_edited_copy_is_not_overwritten(world, capsys):
    (world.home / ".claude").mkdir()
    (world.home / ".kiro").mkdir()
    assert world.run("install") == 0
    edited = world.home / ".claude" / "skills" / "l4" / "references" / "plan.md"
    edited.write_text(edited.read_text() + "\nmy note\n")
    kiro_plan = world.home / ".kiro" / "skills" / "l4" / "references" / "plan.md"
    (world.home / ".kiro" / "skills" / "l4" / "SKILL.md").write_text("changed in kiro\n")  # also edited, by `--force`
    capsys.readouterr()
    assert world.run("install") == 2
    captured = capsys.readouterr()
    assert "references/plan.md" in captured.err + captured.out
    assert edited.read_text().endswith("my note\n")
    assert world.run("status") == 0
    assert "edited" in capsys.readouterr().out
    assert world.run("install", "--force") == 0
    assert edited.read_text() == (REPO_SKILL / "references" / "plan.md").read_text()
    assert kiro_plan.read_text() == (REPO_SKILL / "references" / "plan.md").read_text()


def test_one_edited_target_does_not_stop_the_others(world):
    (world.home / ".claude").mkdir()
    (world.home / ".kiro").mkdir()
    assert world.run("install") == 0
    (world.home / ".claude" / "skills" / "l4" / "SKILL.md").write_text("mine\n")
    (world.home / ".kiro" / "skills" / "l4" / "SKILL.md").unlink()  # missing counts as edited too
    assert world.run("install") == 2
    assert (world.home / ".claude" / "skills" / "l4" / "SKILL.md").read_text() == "mine\n"
    assert not (world.home / ".kiro" / "skills" / "l4" / "SKILL.md").exists()


def test_an_extra_file_counts_as_edited_and_force_removes_it(world, capsys):
    (world.home / ".claude").mkdir()
    assert world.run("install") == 0
    extra = world.home / ".claude" / "skills" / "l4" / "notes.md"
    extra.write_text("mine\n")
    capsys.readouterr()
    assert world.run("install") == 2
    assert "notes.md" in capsys.readouterr().err
    assert extra.exists()
    assert world.run("install", "--force") == 0
    assert not extra.exists()


def test_a_hand_copy_without_a_manifest_is_edited_unless_it_equals_the_bundle(world):
    (world.home / ".claude").mkdir()
    (world.home / ".kiro").mkdir()
    import shutil

    shutil.copytree(REPO_SKILL, world.home / ".claude" / "skills" / "l4")  # identical hand copy
    shutil.copytree(REPO_SKILL, world.home / ".kiro" / "skills" / "l4")
    (world.home / ".kiro" / "skills" / "l4" / "SKILL.md").write_text("tweaked\n")
    assert world.run("install") == 2
    assert (world.home / ".claude" / "skills" / "l4" / MANIFEST).exists()  # adopted: it equalled the bundle
    assert (world.home / ".kiro" / "skills" / "l4" / "SKILL.md").read_text() == "tweaked\n"
    assert not (world.home / ".kiro" / "skills" / "l4" / MANIFEST).exists()


def test_scn_skl_07_a_team_installs_into_the_repository(world, capsys):
    assert world.run("install", "--project", "--agent", "all") == 0
    for rel in (".claude", ".agents", ".opencode", ".kiro"):
        target = world.repo / rel / "skills" / "l4"
        assert {k: v for k, v in tree(target).items() if k != MANIFEST} == tree(REPO_SKILL)
        assert (target / MANIFEST).exists()
    assert list(world.home.iterdir()) == []  # the home folder is not touched
    assert sorted(p.name for p in world.repo.iterdir()) == [".agents", ".claude", ".git", ".kiro", ".opencode"]


def test_project_scope_uses_the_repository_root_from_a_subfolder(world):
    sub = world.repo / "pkg" / "deep"
    sub.mkdir(parents=True)
    assert (
        main(["skills", "install", "--project", "--agent", "claude-code", "--repo", str(sub)], environ=world.env) == 0
    )
    assert (world.repo / ".claude" / "skills" / "l4" / "SKILL.md").exists()
    assert not (sub / ".claude").exists()


def test_dry_run_prints_the_plan_and_writes_nothing(world, capsys):
    (world.home / ".claude").mkdir()
    assert world.run("install", "--dry-run") == 0
    out = capsys.readouterr().out
    assert "would install" in out and str(world.home / ".claude" / "skills" / "l4") in out
    assert not (world.home / ".claude" / "skills").exists()


# --- 3. safety -------------------------------------------------------------------------------------------------------


def test_a_symlinked_target_folder_is_refused(world, tmp_path, capsys):
    (world.home / ".claude" / "skills").mkdir(parents=True)
    (world.home / ".kiro").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (world.home / ".claude" / "skills" / "l4").symlink_to(elsewhere, target_is_directory=True)
    assert world.run("install", "--force") == 2
    err = capsys.readouterr().err
    assert str(world.home / ".claude" / "skills" / "l4") in err
    assert list(elsewhere.iterdir()) == []
    assert (world.home / ".kiro" / "skills" / "l4" / "SKILL.md").exists()  # the others still install


def test_a_symlinked_file_inside_the_target_is_refused_even_with_force(world, tmp_path, capsys):
    (world.home / ".claude").mkdir()
    assert world.run("install") == 0
    outside = tmp_path / "outside.md"
    outside.write_text("secret\n")
    link = world.home / ".claude" / "skills" / "l4" / "references" / "plan.md"
    link.unlink()
    link.symlink_to(outside)
    capsys.readouterr()
    assert world.run("install", "--force") == 2
    assert str(link) in capsys.readouterr().err
    assert outside.read_text() == "secret\n"
    assert link.is_symlink()


def test_a_symlinked_subfolder_inside_the_target_is_refused(world, tmp_path, capsys):
    (world.home / ".claude").mkdir()
    assert world.run("install") == 0
    elsewhere = tmp_path / "refs"
    elsewhere.mkdir()
    refs = world.home / ".claude" / "skills" / "l4" / "references"
    import shutil

    shutil.rmtree(refs)
    refs.symlink_to(elsewhere, target_is_directory=True)
    capsys.readouterr()
    assert world.run("install", "--force") == 2
    assert str(refs) in capsys.readouterr().err
    assert list(elsewhere.iterdir()) == []


def test_a_symlinked_skills_parent_folder_is_allowed(world, tmp_path):
    """dotfile managers link `~/.claude/skills`; only the `l4` folder and what is inside it must be real."""
    real = tmp_path / "dotfiles-skills"
    real.mkdir()
    (world.home / ".claude").mkdir()
    (world.home / ".claude" / "skills").symlink_to(real, target_is_directory=True)
    assert world.run("install") == 0
    assert (real / "l4" / "SKILL.md").exists()


def test_writes_are_atomic_per_file_and_leave_no_temp_files(world):
    (world.home / ".claude").mkdir()
    assert world.run("install") == 0
    names = {p.name for p in (world.home / ".claude" / "skills" / "l4").rglob("*") if p.is_file()}
    assert not [n for n in names if n.endswith(".tmp") or n.startswith(".l4-tmp")]


# --- 4. status -------------------------------------------------------------------------------------------------------


def test_status_with_nothing_installed_says_so(world, capsys):
    assert world.run("status") == 0
    assert "l4 skills install" in capsys.readouterr().out


def test_status_lists_each_target_with_version_and_state(world, capsys):
    (world.home / ".claude").mkdir()
    assert world.run("install") == 0
    assert world.run("install", "--project", "--agent", "kiro") == 0
    (world.repo / ".kiro" / "skills" / "l4" / "SKILL.md").write_text("mine\n")
    capsys.readouterr()
    assert world.run("status") == 0
    lines = capsys.readouterr().out.splitlines()
    import l4

    user = next(line for line in lines if str(world.home / ".claude" / "skills" / "l4") in line)
    assert "claude-code" in user and l4.__version__ in user and "current" in user and "edited" not in user
    project = next(line for line in lines if str(world.repo / ".kiro" / "skills" / "l4") in line)
    assert "kiro" in project and "edited" in project and "SKILL.md" in project


def test_installed_copies_feeds_doctor(world):
    (world.home / ".claude").mkdir()
    assert world.run("install") == 0
    [copy] = skills_cli.installed_copies(world.home, None)
    assert copy.agent == "claude-code" and copy.scope == "user"
    assert copy.path == world.home / ".claude" / "skills" / "l4"
