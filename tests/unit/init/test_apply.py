import os
import stat
from pathlib import Path

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.init.init import apply_plan, plan_init


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(root).parts
    }


def run(target: Path, harness: Path, environ, *, force: bool = False) -> None:
    apply_plan(target, plan_init(target, environ, force=force, harness=harness))


def test_apply_writes_the_files_with_the_right_modes(target: Path, harness_repo: Path, git_environ):
    run(target, harness_repo, git_environ)
    assert (target / ".l4/config.yaml").is_file() and (target / ".l4/ci/l4.gitlab-ci.yml").is_file()
    shim = target / ".l4/bin/l4"
    assert stat.S_IMODE(shim.stat().st_mode) == 0o755 and os.access(shim, os.X_OK)
    assert (target / ".l4/vendor/pyproject.toml").is_file()
    assert (target / ".gitignore").read_text() == ".l4-out/\n.l4/vendor/.venv/\n"
    assert not [p for p in (target / ".l4").rglob("*") if p.name.startswith(".vendor-") or p.suffix == ".l4tmp"]


def test_existing_config_without_force_exits_2_and_changes_nothing(target: Path, harness_repo: Path, git_environ):
    (target / ".l4").mkdir()
    (target / ".l4/config.yaml").write_text("version: 1\n")
    (target / ".gitignore").write_text("node_modules/\n")
    before = snapshot(target)
    with pytest.raises(L4Exit) as err:
        run(target, harness_repo, git_environ)
    assert err.value.code == ExitCode.USAGE_ERROR and ".l4/config.yaml" in str(err.value)
    assert snapshot(target) == before  # bytes unchanged and nothing new written


@pytest.mark.parametrize("path", [".l4/bin/l4", ".l4/ci/l4.gitlab-ci.yml", ".l4/vendor"])
def test_any_existing_file_or_the_vendor_dir_blocks_without_force(
    path: str, target: Path, harness_repo: Path, git_environ
):
    target_path = target / path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.mkdir() if path.endswith("vendor") else target_path.write_text("mine\n")
    before = snapshot(target)
    with pytest.raises(L4Exit) as err:
        run(target, harness_repo, git_environ)
    assert path in str(err.value) and snapshot(target) == before


def test_force_replaces_the_files_and_the_whole_vendor_tree(target: Path, harness_repo: Path, git_environ):
    run(target, harness_repo, git_environ)
    (target / ".l4/vendor/stale.py").write_text("old\n")
    (target / ".l4/config.yaml").write_text("version: 1\n# edited\n")
    run(target, harness_repo, git_environ, force=True)
    assert not (target / ".l4/vendor/stale.py").exists()
    assert "edited" not in (target / ".l4/config.yaml").read_text()
    assert (target / ".l4/vendor/src/l4/cli.py").is_file()
    assert [p.name for p in (target / ".l4").iterdir() if p.name.startswith(".vendor")] == []


def test_second_init_does_not_duplicate_entries(target: Path, harness_repo: Path, git_environ):
    run(target, harness_repo, git_environ)
    run(target, harness_repo, git_environ, force=True)
    assert (target / ".gitignore").read_text().splitlines() == [".l4-out/", ".l4/vendor/.venv/"]


def test_gitignore_keeps_what_is_there_and_its_line_endings(target: Path, harness_repo: Path, git_environ):
    (target / ".gitignore").write_bytes(b"dist/\r\n.l4-out/")  # CRLF, no final newline, one entry already there
    run(target, harness_repo, git_environ)
    assert (target / ".gitignore").read_bytes() == b"dist/\r\n.l4-out/\r\n.l4/vendor/.venv/\r\n"


def test_a_symlinked_l4_directory_is_refused_before_anything_is_written(
    target: Path, harness_repo: Path, git_environ, tmp_path: Path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / ".l4").symlink_to(outside)
    with pytest.raises(L4Exit):
        run(target, harness_repo, git_environ, force=True)
    assert list(outside.iterdir()) == []


def test_a_failed_vendor_collection_writes_nothing(target: Path, harness_repo: Path, git_environ, raw):
    raw(harness_repo, "rm", "-q", "uv.lock")
    raw(harness_repo, "commit", "-q", "-m", "drop the lock")
    before = snapshot(target)
    with pytest.raises(L4Exit) as err:
        run(target, harness_repo, git_environ)
    assert err.value.code == ExitCode.USAGE_ERROR and "uv.lock" in str(err.value)
    assert snapshot(target) == before and not (target / ".l4").exists()


def test_a_failed_vendor_swap_puts_the_old_tree_back_and_writes_nothing_else(
    target: Path, harness_repo: Path, git_environ, monkeypatch: pytest.MonkeyPatch
):
    """Regression: the second `os.replace` failing used to strand the old tree and leave a half-written init."""
    run(target, harness_repo, git_environ)
    (target / ".l4/vendor/mine.py").write_text("old\n")
    (target / ".l4/config.yaml").write_text("version: 1\n# edited\n")
    before = snapshot(target)
    real = os.replace

    def replace(src, dst, *args, **kwargs):
        if Path(src).name.startswith(".vendor-") and Path(dst).name == "vendor":
            raise OSError("disk full")
        return real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(OSError, match="disk full"):
        run(target, harness_repo, git_environ, force=True)
    monkeypatch.undo()
    assert snapshot(target) == before
