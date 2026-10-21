"""`ci.upload_artifacts` (adoption-kit L4-ACT-004, baseline gap 5): the `l4-out` upload step of both GitHub workflow
forms, which a public repository does not want (prompts and transcripts, secrets masked, are downloadable by any
signed-in user)."""

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


def steps(text: str) -> list[dict]:
    return yaml.safe_load(text)["jobs"]["l4"]["steps"]


def uploads(text: str) -> list[dict]:
    return [s for s in steps(text) if str(s.get("uses", "")).startswith("actions/upload-artifact@")]


def test_the_default_uploads_and_only_a_boolean_is_accepted():
    assert L4Config().ci.upload_artifacts is True
    assert L4Config.model_validate({"ci": {"upload_artifacts": False}}).ci.upload_artifacts is False
    with pytest.raises(ValidationError):
        L4Config.model_validate({"ci": {"upload_artifacts": "maybe"}})


@pytest.mark.parametrize("form", RENDERS)
def test_true_keeps_the_upload_as_the_last_step(form):
    text = RENDERS[form](cfg())
    assert len(uploads(text)) == 1
    # `.l4-out` is a hidden folder: without `include-hidden-files` upload-artifact finds nothing (live run 38330251183:
    # "No files were found with the provided path: .l4-out/. No artifacts will be uploaded.")
    assert steps(text)[-1]["with"] == {
        "name": "l4-out", "path": ".l4-out/", "include-hidden-files": True, "retention-days": 7,
    }  # fmt: skip


@pytest.mark.parametrize("form", RENDERS)
def test_false_renders_no_upload_step(form):
    text = RENDERS[form](cfg(upload_artifacts=False))
    assert uploads(text) == [] and "upload-artifact" not in text and "l4-out" not in text.replace(".l4-out", "")
    assert steps(text)[-1].get("name") == "status"  # the rest of the job is as it was


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint is not installed")
@pytest.mark.parametrize("form", RENDERS)
@pytest.mark.parametrize("upload", [True, False])
def test_actionlint_is_clean(form, upload, tmp_path):
    workflow = tmp_path / ".github" / "workflows" / "l4.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(RENDERS[form](cfg(upload_artifacts=upload, schedule=None if not upload else "0 6 * * 1")))
    (tmp_path / ".github" / "actions" / "l4").mkdir(parents=True)
    source = Path(__file__).resolve().parents[3] / ".github" / "actions" / "l4" / "action.yml"
    shutil.copy(source, tmp_path / ".github" / "actions" / "l4" / "action.yml")
    done = subprocess.run(["actionlint", "-no-color", str(workflow)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
