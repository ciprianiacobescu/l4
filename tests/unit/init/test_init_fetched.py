"""The harness fetched at run time (github-parity L4-GHP-010, D10): `l4 init --harness-repo`, `l4 upgrade
--harness-commit`. An adopted repository holds the config, the shim, the setup script and the CI file, and no harness
code."""

from pathlib import Path

import pytest
import yaml

from l4.ci.render import render_fetched_shim, render_setup
from l4.cli import main
from l4.config.loader import load_config
from l4.init.init import plan_init

SHA = "a" * 40
NEW = "b" * 40
REPO = "git@github.com:o/harness.git"
WORKFLOW = ".github/workflows/l4.yml"


def init(target: Path, environ, *flags: str) -> int:
    return main(["init", "--repo", str(target), "--ci", "github", *flags], environ=environ)


def upgrade(target: Path, environ, *flags: str) -> int:
    return main(["upgrade", "--repo", str(target), *flags], environ=environ)


def files_under(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git/" not in f"{p}/"}


def test_an_adopted_repository_holds_no_harness_code(target: Path, git_environ):
    """SCN-GHP-13"""
    before = files_under(target)
    assert init(target, git_environ, "--harness-repo", REPO, "--harness-commit", SHA) == 0
    added = files_under(target) - before
    assert {".l4/config.yaml", ".l4/bin/l4", ".l4/bin/l4-setup", WORKFLOW} <= added
    assert not [p for p in files_under(target) if p.startswith(".l4/vendor")]
    assert not (target / ".l4/vendor").exists()
    cfg = load_config(target)
    assert (cfg.harness.repository, cfg.harness.commit) == ("ssh://git@github.com/o/harness.git", SHA)
    assert (target / ".l4/bin/l4").read_text() == render_fetched_shim()
    assert (target / ".l4/bin/l4-setup").read_text() == render_setup()
    assert (target / ".l4/bin/l4").stat().st_mode & 0o777 == 0o755


def test_plan_lists_no_vendor_path(target: Path, git_environ):
    plan = plan_init(target, git_environ, force=False, ci="github", fetched=("https://github.com/o/harness.git", SHA))
    paths = [f.path for f in plan.files]
    assert paths[:4] == [".l4/config.yaml", ".l4/bin/l4", ".l4/bin/l4-setup", WORKFLOW]
    assert not any("vendor" in p for p in paths)
    assert plan.vendor is None and not plan.vendor_exists
    config = yaml.safe_load(plan.files[0].data)
    assert config["harness"]["repository"] == "https://github.com/o/harness.git"
    assert config["harness"]["commit"] == SHA


def test_gitignore_does_not_name_a_vendor_venv(target: Path, git_environ):
    assert init(target, git_environ, "--harness-repo", REPO, "--harness-commit", SHA) == 0
    ignore = (target / ".gitignore").read_text()
    assert ".l4-out/" in ignore and "vendor" not in ignore


def test_the_commit_defaults_to_the_running_harness(target: Path, git_environ, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("l4.init.init.harness_commit", lambda: NEW)
    assert init(target, git_environ, "--harness-repo", REPO) == 0
    assert load_config(target).harness.commit == NEW


def test_an_unknown_running_commit_asks_for_harness_commit(
    target: Path, git_environ, monkeypatch: pytest.MonkeyPatch, capsys
):
    monkeypatch.setattr("l4.init.init.harness_commit", lambda: None)
    assert init(target, git_environ, "--harness-repo", REPO) == 2
    assert "--harness-commit" in capsys.readouterr().err
    assert not (target / ".l4").exists()


@pytest.mark.parametrize(
    "flags",
    [
        ("--harness-repo", REPO, "--harness-commit", SHA, "--vendor"),
        ("--harness-repo", "http://insecure/x.git", "--harness-commit", SHA),
        ("--harness-repo", "https://user:pw@h.example/x.git", "--harness-commit", SHA),
        ("--harness-repo", REPO, "--harness-commit", "abc123"),
        ("--harness-commit", SHA),
    ],
    ids=["with-vendor", "http", "credential", "short-sha", "commit-without-repo"],
)
def test_refusals_write_nothing(target: Path, git_environ, flags):
    assert init(target, git_environ, *flags) == 2
    assert not (target / ".l4").exists()


def adopt_fetched(target: Path, environ) -> None:
    assert init(target, environ, "--harness-repo", REPO, "--harness-commit", SHA) == 0


def test_upgrade_rewrites_only_the_commit_and_never_vendors(target: Path, git_environ):
    adopt_fetched(target, git_environ)
    config = target / ".l4/config.yaml"
    old = config.read_text().replace("roles:", "# humans own this\nroles:", 1)
    config.write_text(old)
    (target / ".l4/bin/l4").write_text("#!/bin/sh\n# an old shim\n")
    (target / ".l4/bin/l4-setup").write_text("#!/bin/bash\n# old\n")
    (target / WORKFLOW).write_text("# stale\n")
    assert upgrade(target, git_environ, "--harness-commit", NEW) == 0
    assert config.read_text() == old.replace(f"commit: {SHA}", f"commit: {NEW}")
    assert (target / ".l4/bin/l4").read_text() == render_fetched_shim()
    assert (target / ".l4/bin/l4-setup").read_text() == render_setup()
    assert "stale" not in (target / WORKFLOW).read_text()
    assert not (target / ".l4/vendor").exists()


def test_upgrade_defaults_to_the_running_commit(target: Path, git_environ, monkeypatch: pytest.MonkeyPatch):
    adopt_fetched(target, git_environ)
    monkeypatch.setattr("l4.init.upgrade.harness_commit", lambda: NEW)
    assert upgrade(target, git_environ) == 0
    assert load_config(target).harness.commit == NEW


def test_upgrade_with_an_unknown_commit_asks_for_it(target: Path, git_environ, monkeypatch, capsys):
    adopt_fetched(target, git_environ)
    monkeypatch.setattr("l4.init.upgrade.harness_commit", lambda: None)
    assert upgrade(target, git_environ) == 2
    assert "--harness-commit" in capsys.readouterr().err
    assert load_config(target).harness.commit == SHA


def test_upgrade_refuses_a_bad_commit(target: Path, git_environ):
    adopt_fetched(target, git_environ)
    assert upgrade(target, git_environ, "--harness-commit", "nothex") == 2
    assert load_config(target).harness.commit == SHA


def test_a_vendored_adoption_refuses_harness_commit(target: Path, harness_repo: Path, git_environ):
    argv = ["init", "--repo", str(target), "--harness", str(harness_repo), "--ci", "gitlab", "--vendor"]
    assert main(argv, environ=git_environ) == 0
    before = (target / ".l4/config.yaml").read_bytes()
    assert upgrade(target, git_environ, "--harness", str(harness_repo), "--harness-commit", NEW) == 2
    assert (target / ".l4/config.yaml").read_bytes() == before
