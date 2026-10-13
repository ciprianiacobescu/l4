import json
import re
from pathlib import Path

import pytest

from l4.cli import main

NEW_VERSION = "9.9.9"


def run(target: Path, harness: Path, environ, *flags: str) -> int:
    return main(["upgrade", "--repo", str(target), "--harness", str(harness), *flags], environ=environ)


def adopt(target: Path, harness: Path, environ) -> None:
    argv = ["init", "--repo", str(target), "--harness", str(harness), "--ci", "gitlab", "--vendor"]
    assert main(argv, environ=environ) == 0


def new_harness_commit(harness: Path, raw) -> str:
    (harness / "src/l4/cli.py").write_text("def main(): return 'new'\n")
    (harness / "src/l4/__init__.py").write_text(f'__version__ = "{NEW_VERSION}"\n')
    raw(harness, "add", "-A")
    raw(harness, "commit", "-q", "-m", "harness moves")
    return raw(harness, "rev-parse", "HEAD").strip()


def snapshot(root: Path, skip: tuple[str, ...] = ()) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git/" not in p.as_posix() + "/" and not p.relative_to(root).as_posix().startswith(skip)
    }


def humanise(config: Path) -> None:
    """The file as a maintainer leaves it: comments between the keys and after a value."""
    text = config.read_text()
    text = text.replace("roles:", "# the humans own everything below\nroles:", 1)
    config.write_text(text.replace("  - codex", "  - codex   # a comment that must stay", 1))


def test_upgrade_refreshes_vendor_and_ci_and_keeps_config_bytes(target, harness_repo, git_environ, raw):
    adopt(target, harness_repo, git_environ)
    config = target / ".l4/config.yaml"
    humanise(config)
    (target / ".gitlab-ci.yml").write_text("include:\n  - local: .l4/ci/l4.gitlab-ci.yml\n")
    (target / ".l4/ci/l4.gitlab-ci.yml").write_text("# an old template\n")
    (target / ".l4/bin/l4").write_text("#!/bin/sh\n# an old shim\n")
    (target / ".l4/vendor/stray.txt").write_text("removed by the swap\n")
    (target / ".l4/vendor/.venv").mkdir()
    before = snapshot(target, skip=(".l4/vendor/",))
    old_config = config.read_text()
    commit = new_harness_commit(harness_repo, raw)

    assert run(target, harness_repo, git_environ) == 0

    assert (target / ".l4/vendor/src/l4/cli.py").read_text() == "def main(): return 'new'\n"
    assert not (target / ".l4/vendor/stray.txt").exists()
    assert (target / ".l4/vendor/src/l4/_commit.py").read_text() == f'COMMIT = "{commit}"\n'
    assert "an old template" not in (target / ".l4/ci/l4.gitlab-ci.yml").read_text()
    assert "an old shim" not in (target / ".l4/bin/l4").read_text()
    assert ((target / ".l4/bin/l4").stat().st_mode & 0o111) != 0
    after = snapshot(target, skip=(".l4/vendor/",))
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    assert changed == {".l4/ci/l4.gitlab-ci.yml", ".l4/bin/l4", ".l4/config.yaml"}  # .gitlab-ci.yml, .gitignore stay
    new_config = config.read_text()
    old_lines, new_lines = old_config.splitlines(), new_config.splitlines()
    assert len(old_lines) == len(new_lines)
    old_version = next(line for line in old_lines if line.startswith("  version: "))
    old_commit = next(line for line in old_lines if line.startswith("  commit: "))
    assert [(a, b) for a, b in zip(old_lines, new_lines, strict=True) if a != b] == [
        (old_version, f"  version: {NEW_VERSION}"), (old_commit, f"  commit: {commit}")
    ]  # fmt: skip
    assert "# the humans own everything below" in new_config


def test_the_pins_keep_their_quotes_and_trailing_comments(target, harness_repo, git_environ, raw):
    adopt(target, harness_repo, git_environ)
    config = target / ".l4/config.yaml"
    text = config.read_text()
    text = re.sub(r"(  version: )(\S+)", r'\1"\2"  # pinned by hand', text)
    text = re.sub(r"(  commit: )(\S+)", r"\1'\2'", text)
    config.write_text(text)
    commit = new_harness_commit(harness_repo, raw)
    assert run(target, harness_repo, git_environ) == 0
    assert f'  version: "{NEW_VERSION}"  # pinned by hand\n' in config.read_text()
    assert f"  commit: '{commit}'\n" in config.read_text()


def test_dry_run_writes_nothing(target, harness_repo, git_environ, raw, capsys):
    adopt(target, harness_repo, git_environ)
    before = snapshot(target)
    new_harness_commit(harness_repo, raw)
    capsys.readouterr()
    assert run(target, harness_repo, git_environ, "--dry-run") == 0
    out = capsys.readouterr().out
    assert snapshot(target) == before
    assert ".l4/vendor/" in out and ".l4/config.yaml" in out and "would" in out


def test_no_config_exits_2(target, harness_repo, git_environ, capsys):
    assert run(target, harness_repo, git_environ) == 2
    assert "run l4 init" in capsys.readouterr().err
    assert not (target / ".l4").exists()


def test_a_config_whose_pins_cannot_be_found_is_refused_and_nothing_is_written(target, harness_repo, git_environ, raw):
    adopt(target, harness_repo, git_environ)
    config = target / ".l4/config.yaml"
    pins = r"harness:\n  version:.*\n  commit:.*\n"
    flow = re.sub(pins, "harness: {version: 0.1.0, commit: abc}\n", config.read_text())
    config.write_text(flow)
    new_harness_commit(harness_repo, raw)
    before = snapshot(target)
    assert run(target, harness_repo, git_environ) == 2
    assert snapshot(target) == before


def test_a_second_upgrade_changes_nothing(target, harness_repo, git_environ, raw, capsys):
    adopt(target, harness_repo, git_environ)
    new_harness_commit(harness_repo, raw)
    assert run(target, harness_repo, git_environ) == 0
    after = snapshot(target)
    capsys.readouterr()
    assert run(target, harness_repo, git_environ) == 0
    assert snapshot(target) == after and "up to date" in capsys.readouterr().out


def test_the_keys_the_file_lacks_are_reported_not_written(target, harness_repo, git_environ, raw, capsys):
    adopt(target, harness_repo, git_environ)
    new_harness_commit(harness_repo, raw)
    capsys.readouterr()
    assert run(target, harness_repo, git_environ) == 0
    out = capsys.readouterr().out
    assert "not in .l4/config.yaml" in out and "clarifier" in out and "sandbox" in out
    assert "clarifier" not in (target / ".l4/config.yaml").read_text()


def test_a_symlinked_ci_directory_is_refused(target, harness_repo, git_environ, raw, tmp_path):
    adopt(target, harness_repo, git_environ)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (target / ".l4/ci/l4.gitlab-ci.yml").unlink()
    (target / ".l4/ci").rmdir()
    (target / ".l4/ci").symlink_to(elsewhere)
    new_harness_commit(harness_repo, raw)
    assert run(target, harness_repo, git_environ) == 2
    assert list(elsewhere.iterdir()) == []


def test_a_broken_new_config_is_not_written(target, harness_repo, git_environ, raw):
    adopt(target, harness_repo, git_environ)
    config = target / ".l4/config.yaml"
    config.write_text(config.read_text() + "\nnot_a_key: 1\n")  # the loader is strict: the file never loaded
    new_harness_commit(harness_repo, raw)
    before = snapshot(target)
    assert run(target, harness_repo, git_environ) == 2
    assert snapshot(target) == before


@pytest.mark.parametrize("flag", ["--ci", "--vendor"])
def test_upgrade_has_only_harness_and_dry_run(flag, target, harness_repo, git_environ):
    assert main(["upgrade", "--repo", str(target), flag], environ=git_environ) == 2


def test_upgrade_registers_the_marker_once_and_reports_it(target, harness_repo, git_environ, raw, capsys):
    """P4: an adopter that started before M1.9 gets the marker at its next upgrade, once; the docstring said `upgrade`
    never touches project files, which stays true for every file but this one entry."""
    (target / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    adopt(target, harness_repo, git_environ)
    capsys.readouterr()
    (target / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')  # as before M1.9
    new_harness_commit(harness_repo, raw)
    assert run(target, harness_repo, git_environ, "--dry-run") == 0
    assert "would register the l4 pytest marker in pyproject.toml" in capsys.readouterr().out
    assert "markers" not in (target / "pyproject.toml").read_text()  # a dry run writes nothing
    assert run(target, harness_repo, git_environ) == 0
    assert "registered the l4 pytest marker in pyproject.toml" in capsys.readouterr().out
    text = (target / "pyproject.toml").read_text()
    assert text.count("l4(*ids)") == 1 and text.startswith("[tool.pytest.ini_options]\nmarkers = [")
    assert run(target, harness_repo, git_environ) == 0
    assert "pytest marker" not in capsys.readouterr().out and (target / "pyproject.toml").read_text() == text


def test_upgrade_prints_the_snippet_when_the_marker_cannot_be_registered(target, harness_repo, git_environ, capsys):
    adopt(target, harness_repo, git_environ)
    (target / "pytest.ini").write_text("[pytest]\n")
    (target / "conftest.py").write_text("def pytest_configure(config):\n    pass\n")
    capsys.readouterr()
    assert run(target, harness_repo, git_environ) == 0
    out = capsys.readouterr().out
    assert "could not register the l4 pytest marker" in out and "addinivalue_line" in out
    assert (target / "conftest.py").read_text() == "def pytest_configure(config):\n    pass\n"


def test_upgrade_leaves_pytest_configuration_alone_for_a_project_that_does_not_run_pytest(
    target, harness_repo, git_environ, capsys
):
    adopt(target, harness_repo, git_environ)
    config = target / ".l4/config.yaml"
    config.write_text(config.read_text().replace(".venv/bin/python -m pytest", "make test"))
    (target / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    capsys.readouterr()
    assert run(target, harness_repo, git_environ) == 0
    assert "markers" not in (target / "pyproject.toml").read_text() and "pytest marker" not in capsys.readouterr().out


def test_upgrade_re_renders_the_allowed_codes(target, harness_repo, git_environ, raw):
    """M1.11 W4: a project adopted before the change gets 13 (a halt) among the allowed failures from `l4 upgrade`."""
    import yaml

    adopt(target, harness_repo, git_environ)
    include = target / ".l4/ci/l4.gitlab-ci.yml"
    include.write_text(include.read_text().replace("[10, 11, 12, 13]", "[10, 11, 12]"))  # an include of M1.10
    assert yaml.safe_load(include.read_text())["l4"]["allow_failure"]["exit_codes"] == [10, 11, 12]
    new_harness_commit(harness_repo, raw)
    assert run(target, harness_repo, git_environ) == 0
    assert yaml.safe_load(include.read_text())["l4"]["allow_failure"]["exit_codes"] == [10, 11, 12, 13]


def set_forge(config: Path, **values: str) -> None:
    """Add keys to the `forge:` block the rendered config has, as a maintainer does."""
    text = config.read_text()
    assert "\nforge:\n  type: gitlab\n" in text
    lines = "".join(f"  {key}: {json.dumps(value)}\n" for key, value in values.items())
    config.write_text(text.replace("\nforge:\n  type: gitlab\n", "\nforge:\n  type: gitlab\n" + lines, 1))


def test_upgrade_re_renders_the_gitlab_job_when_the_base_or_prefix_change(target, harness_repo, git_environ, raw):
    """L4-OPS-016: the include follows `forge.base_branch` and `forge.branch_prefix`, and a second upgrade is quiet."""
    import yaml

    adopt(target, harness_repo, git_environ)
    include = target / ".l4/ci/l4.gitlab-ci.yml"
    assert yaml.safe_load(include.read_text())["l4"]["variables"]["L4_BASE_BRANCH"] == "main"
    set_forge(target / ".l4/config.yaml", base_branch="l4/main", branch_prefix="bots/")
    assert run(target, harness_repo, git_environ) == 0
    job = yaml.safe_load(include.read_text())["l4"]
    assert job["variables"]["L4_BASE_BRANCH"] == "l4/main"
    assert job["rules"][1]["if"].endswith('$CI_COMMIT_BRANCH == "l4/main"')
    assert job["rules"][2]["if"].endswith("=~ /^bots\\//")
    before = snapshot(target)
    assert run(target, harness_repo, git_environ) == 0
    assert snapshot(target) == before


def test_upgrade_refuses_an_unsafe_base_branch_and_writes_nothing(target, harness_repo, git_environ, raw, capsys):
    adopt(target, harness_repo, git_environ)
    set_forge(target / ".l4/config.yaml", base_branch="main'\n  evil: 1")
    new_harness_commit(harness_repo, raw)
    before = snapshot(target)
    capsys.readouterr()
    assert run(target, harness_repo, git_environ) == 2
    assert "base branch" in capsys.readouterr().err
    assert snapshot(target) == before
