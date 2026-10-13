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
