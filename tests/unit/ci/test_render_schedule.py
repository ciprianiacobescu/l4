"""`ci.schedule` (adoption-kit L4-ACT-004, baseline gap 4): the cron of the GitHub workflow's `schedule:` trigger, or
none. `l4 upgrade` re-renders the workflow, so the config key is the way to change it."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from l4.ci.github import ActionPin, render_github_action_ci, render_github_ci
from l4.config.schema import L4Config

PIN = ActionPin(repository="owner/harness", sha="a1" * 20, ref="v0.3.0")
RENDERS = {
    "vendored": lambda cfg: render_github_ci(cfg),
    "action": lambda cfg: render_github_action_ci(cfg, PIN),
}


def cfg(**ci) -> L4Config:
    return L4Config.model_validate({"ci": {"runner_tags": [], **ci}})


def triggers(text: str) -> dict:
    return yaml.safe_load(text)[True]  # PyYAML reads the key `on` as a boolean


def test_the_default_is_every_thirty_minutes():
    assert L4Config().ci.schedule == "*/30 * * * *"


def test_null_is_allowed_and_a_bad_cron_is_not():
    assert L4Config.model_validate({"ci": {"schedule": None}}).ci.schedule is None
    assert L4Config.model_validate({"ci": {"schedule": "0 6 * * 1"}}).ci.schedule == "0 6 * * 1"
    for bad in ("", "daily", "* * * *", "*/30 * * * * *", '0 6 * * "1"', "0 6 * * 1\nrun: x"):
        with pytest.raises(ValidationError):
            L4Config.model_validate({"ci": {"schedule": bad}})


@pytest.mark.parametrize("form", RENDERS)
def test_the_default_renders_the_thirty_minute_schedule(form):
    assert triggers(RENDERS[form](cfg()))["schedule"] == [{"cron": "*/30 * * * *"}]


@pytest.mark.parametrize("form", RENDERS)
def test_a_cron_string_is_rendered(form):
    text = RENDERS[form](cfg(schedule="17 */6 * * *"))
    assert triggers(text)["schedule"] == [{"cron": "17 */6 * * *"}]
    assert "*/30" not in text


@pytest.mark.parametrize("form", RENDERS)
def test_null_leaves_the_trigger_out(form):
    text = RENDERS[form](cfg(schedule=None))
    assert set(triggers(text)) == {"push", "workflow_dispatch"} and "schedule:" not in text and "cron" not in text


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint is not installed")
@pytest.mark.parametrize("form", RENDERS)
@pytest.mark.parametrize("schedule", [None, "0 6 * * 1"])
def test_actionlint_is_clean(form, schedule, tmp_path):
    workflow = tmp_path / ".github" / "workflows" / "l4.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(RENDERS[form](cfg(schedule=schedule)))
    (tmp_path / ".github" / "actions" / "l4").mkdir(parents=True)
    source = Path(__file__).resolve().parents[3] / ".github" / "actions" / "l4" / "action.yml"
    shutil.copy(source, tmp_path / ".github" / "actions" / "l4" / "action.yml")
    done = subprocess.run(["actionlint", "-no-color", str(workflow)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
