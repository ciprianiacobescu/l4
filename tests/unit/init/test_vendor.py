import io
import os
import tarfile
from pathlib import Path

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.init import vendor
from l4.init.vendor import _read_tree, collect_vendor_source, harness_root


def test_the_copy_is_the_allow_list_at_the_pinned_commit_and_nothing_else(harness_repo: Path, git_environ, raw):
    source = collect_vendor_source(harness_repo, git_environ)
    assert source.commit == raw(harness_repo, "rev-parse", "HEAD").strip()
    assert sorted(source.files) == [
        "LICENSE", "README.md", "pyproject.toml", "src/l4/__init__.py", "src/l4/_commit.py", "src/l4/bin/tool.sh",
        "src/l4/ci/templates/l4.gitlab-ci.yml", "src/l4/cli.py", "uv.lock",
    ]  # fmt: skip
    assert source.files["src/l4/_commit.py"].data == f'COMMIT = "{source.commit}"\n'.encode()  # what ran is checkable
    for left_out in ("tests", "docs", "openspec", "scripts"):
        assert not [n for n in source.files if n.startswith(left_out + "/")]
    assert source.files["src/l4/bin/tool.sh"].executable and not source.files["src/l4/cli.py"].executable


def test_the_working_tree_is_not_what_is_copied_uncommitted_changes_are_refused(harness_repo: Path, git_environ):
    (harness_repo / "src/l4/cli.py").write_text("def main(): return 1\n")
    with pytest.raises(L4Exit, match="differ from HEAD") as err:
        collect_vendor_source(harness_repo, git_environ)
    assert err.value.code == ExitCode.USAGE_ERROR


def test_untracked_and_unrelated_changes_do_not_block_the_copy(harness_repo: Path, git_environ):
    (harness_repo / "src/l4/scratch.py").write_text("x = 1\n")  # untracked: not part of the commit
    (harness_repo / "docs/SPEC.md").write_text("edited\n")  # not copied
    source = collect_vendor_source(harness_repo, git_environ)
    assert "src/l4/scratch.py" not in source.files


def test_vendor_refuses_when_head_differs_from_pin_a_new_commit_changes_the_pin(harness_repo: Path, git_environ, raw):
    first = collect_vendor_source(harness_repo, git_environ)
    (harness_repo / "src/l4/cli.py").write_text("def main(): return 2\n")
    raw(harness_repo, "commit", "-qam", "change")
    second = collect_vendor_source(harness_repo, git_environ)
    assert second.commit != first.commit and second.files["src/l4/cli.py"].data == b"def main(): return 2\n"


def test_optional_files_are_taken_only_when_they_exist(harness_repo: Path, git_environ, raw):
    raw(harness_repo, "rm", "-q", "LICENSE")
    raw(harness_repo, "commit", "-q", "-m", "no license")
    assert "LICENSE" not in collect_vendor_source(harness_repo, git_environ).files


@pytest.mark.parametrize("missing", ["src", "pyproject.toml", "uv.lock"])
def test_a_required_path_missing_at_head_is_refused(missing: str, harness_repo: Path, git_environ, raw):
    raw(harness_repo, "rm", "-rq", missing)
    raw(harness_repo, "commit", "-q", "-m", "drop")
    with pytest.raises(L4Exit, match=missing):
        collect_vendor_source(harness_repo, git_environ)


def test_another_project_is_not_the_harness(harness_repo: Path, git_environ, raw):
    (harness_repo / "pyproject.toml").write_text('[project]\nname = "something-else"\n')
    raw(harness_repo, "commit", "-qam", "rename")
    with pytest.raises(L4Exit, match="l4harness"):
        collect_vendor_source(harness_repo, git_environ)


def test_a_directory_that_is_not_a_repo_top_is_refused(harness_repo: Path, git_environ, tmp_path: Path):
    with pytest.raises(L4Exit):
        collect_vendor_source(tmp_path, git_environ)
    with pytest.raises(L4Exit, match="top of a git repository"):
        collect_vendor_source(harness_repo / "src", git_environ)


def archive(*members: tuple[str, bytes | None, bytes]) -> bytes:
    """A tar with (name, link target or None, content) members; a link target makes it a symlink."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, link, data in members:
            info = tarfile.TarInfo(name)
            if link is not None:
                info.type, info.linkname = tarfile.SYMTYPE, link.decode()
            else:
                info.size = len(data)
            tar.addfile(info, io.BytesIO(data) if link is None else None)
    return buffer.getvalue()


def test_unsafe_tar_members_are_refused():
    assert list(_read_tree(archive(("src/a.py", None, b"x")))) == ["src/a.py"]
    for bad in (("src/link", b"/etc/passwd", b""), ("../escape", None, b"x"), ("/abs", None, b"x")):
        with pytest.raises(L4Exit):
            _read_tree(archive(bad))


def test_the_default_harness_is_the_checkout_the_package_runs_from(harness_repo: Path, monkeypatch):
    monkeypatch.setattr(vendor, "PACKAGE_FILE", harness_repo / "src" / "l4" / "__init__.py")
    assert harness_root(None) == harness_repo.resolve()
    assert harness_root(harness_repo / "elsewhere") == (harness_repo / "elsewhere").resolve()


def test_a_package_outside_a_checkout_needs_the_harness_option(tmp_path: Path, monkeypatch):
    installed = tmp_path / "site" / "lib" / "l4" / "__init__.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("")
    monkeypatch.setattr(vendor, "PACKAGE_FILE", installed)
    with pytest.raises(L4Exit, match="--harness"):
        harness_root(None)


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("L4_LIVE") != "1", reason="needs uv and a network or a warm uv cache")
def test_vendored_install_runs_offline(target: Path, app_for, git_environ):
    import subprocess

    from l4.init.init import run_init

    assert run_init(app_for(target), ci="gitlab", vendor=True, harness=vendor.harness_root(None)) == 0
    done = subprocess.run(
        [str(target / ".l4/bin/l4"), "--version"], cwd=target, capture_output=True, text=True,
        env={**os.environ, "UV_OFFLINE": "1"},
    )  # fmt: skip
    assert done.returncode == 0 and "l4" in done.stdout
