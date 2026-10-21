"""`ci.schedule` and `ci.upload_artifacts` reach an adopted repository through `l4 upgrade` (adoption-kit L4-ACT-004,
baseline gaps 4 and 5): the config key is changed, the workflow is re-rendered."""

from pathlib import Path

import yaml

from l4.cli import main

SHA = "d" * 40
WORKFLOW = ".github/workflows/l4.yml"


def adopt(target: Path, environ) -> None:
    flags = ("--action", "--action-repo", "o/harness", "--harness-commit", SHA)
    assert main(["init", "--repo", str(target), "--ci", "github", *flags], environ=environ) == 0


def set_ci(target: Path, **keys) -> None:
    config = target / ".l4/config.yaml"
    document = yaml.safe_load(config.read_text())
    document["ci"].update(keys)
    config.write_text(yaml.safe_dump(document, sort_keys=False))


def upgrade(target: Path, environ) -> None:
    assert main(["upgrade", "--repo", str(target), "--harness-commit", SHA], environ=environ) == 0


def test_upgrade_moves_the_schedule_with_the_config(target: Path, git_environ):
    """The way to change the schedule of an adopted repository: the config key, then `l4 upgrade`."""
    adopt(target, git_environ)
    workflow = target / WORKFLOW
    on = lambda: yaml.safe_load(workflow.read_text())[True]  # noqa: E731 - PyYAML reads the key `on` as a boolean
    assert on()["schedule"] == [{"cron": "*/30 * * * *"}]
    set_ci(target, schedule="0 6 * * 1")
    upgrade(target, git_environ)
    assert on()["schedule"] == [{"cron": "0 6 * * 1"}]
    set_ci(target, schedule=None)
    upgrade(target, git_environ)
    assert "schedule" not in on()


def test_upgrade_drops_and_restores_the_upload_with_the_config(target: Path, git_environ):
    adopt(target, git_environ)
    workflow = target / WORKFLOW
    assert "upload-artifact" in workflow.read_text()
    set_ci(target, upload_artifacts=False)
    upgrade(target, git_environ)
    assert "upload-artifact" not in workflow.read_text()
    set_ci(target, upload_artifacts=True)
    upgrade(target, git_environ)
    assert "upload-artifact" in workflow.read_text()


# --- `l4 upgrade` refreshes the copy of the setup action (baseline gap 6) -------------------------------------------


def adopt_copy(target: Path, environ) -> None:
    flags = ("--action", "--action-copy", "--action-repo", "o/harness", "--harness-commit", SHA)
    assert main(["init", "--repo", str(target), "--ci", "github", *flags], environ=environ) == 0


def test_upgrade_in_copy_mode_refreshes_the_action_and_says_so(target: Path, git_environ, capsys):
    from l4.init.action import packaged_action

    adopt_copy(target, git_environ)
    action = target / ".github/actions/l4/action.yml"
    action.write_text("name: stale\n")
    capsys.readouterr()
    upgrade(target, git_environ)
    assert action.read_bytes() == packaged_action()
    out = capsys.readouterr().out
    assert "changed .github/actions/l4/action.yml" in out and "up to date" not in out


def test_upgrade_recreates_a_missing_copy_and_dry_run_writes_nothing(target: Path, git_environ, capsys):
    adopt_copy(target, git_environ)
    action = target / ".github/actions/l4/action.yml"
    action.unlink()
    assert main(["upgrade", "--repo", str(target), "--harness-commit", SHA, "--dry-run"], environ=git_environ) == 0
    assert not action.exists() and "would change .github/actions/l4/action.yml" in capsys.readouterr().out
    upgrade(target, git_environ)
    assert action.exists()


def test_upgrade_with_a_current_copy_changes_nothing(target: Path, git_environ, capsys):
    adopt_copy(target, git_environ)
    capsys.readouterr()
    upgrade(target, git_environ)
    assert ".github/actions/l4/action.yml" not in capsys.readouterr().out


def test_upgrade_of_a_published_action_writes_no_copy(target: Path, git_environ):
    adopt(target, git_environ)
    upgrade(target, git_environ)
    assert not (target / ".github/actions").exists()
