import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from l4.ci.github import doctor_command, render_github_ci
from l4.ci.lint import lint_github_yaml
from l4.config.schema import L4Config

GOLDEN = Path(__file__).resolve().parents[2] / "fixtures" / "ci" / "l4.github.default.yml"


def cfg(**sections) -> L4Config:
    return L4Config.model_validate(sections)


def parsed(config: L4Config) -> dict:
    return yaml.safe_load(render_github_ci(config))


def test_workflow_golden():
    assert render_github_ci(L4Config()) == GOLDEN.read_text()


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint is not installed")
@pytest.mark.parametrize(
    "config",
    [L4Config(), cfg(ci={"runner_tags": []}), cfg(ci={"self_provision": True}, forge={"base_branch": "release/1.x"})],
)
def test_actionlint_is_clean(config, tmp_path):
    workflow = tmp_path / ".github" / "workflows" / "l4.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(render_github_ci(config))
    labels = "".join(f"    - {tag}\n" for tag in config.ci.runner_tags)  # custom labels of a self-hosted runner
    (tmp_path / "actionlint.yaml").write_text(f"self-hosted-runner:\n  labels:\n{labels}" if labels else "{}\n")
    argv = ["actionlint", "-no-color", "-config-file", str(tmp_path / "actionlint.yaml"), str(workflow)]
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


def test_triggers_job_shape_and_steps():
    doc = parsed(L4Config())
    triggers = doc[True]  # PyYAML reads the key `on` as a boolean
    assert set(triggers) == {"push", "schedule", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main", "l4/**"]
    job = doc["jobs"]["l4"]
    assert job["if"] == "${{ !contains(github.event.head_commit.message, 'L4-Run: ') }}"
    assert job["concurrency"] == {"group": "l4", "cancel-in-progress": False}
    assert job["timeout-minutes"] == 180
    assert job["runs-on"] == ["self-hosted", "agentic"]
    checkout = job["steps"][0]
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    assert len(checkout["uses"].split("@")[1]) == 40  # pinned to a commit
    assert [s["run"] for s in job["steps"] if "run" in s] == [
        ".l4/bin/l4 doctor --ci || .l4/bin/l4 ci map-exit $?",
        ".l4/bin/l4 plan --sweep || .l4/bin/l4 ci map-exit $?",
        ".l4/bin/l4 run || .l4/bin/l4 ci map-exit $?",
        ".l4/bin/l4 status",
    ]
    assert doc["permissions"] == {
        "contents": "write", "pull-requests": "write", "statuses": "write", "actions": "write",
    }  # fmt: skip


def test_no_pull_request_trigger_so_forks_never_run_it():
    assert not {"pull_request", "pull_request_target"} & set(parsed(L4Config())[True])


def test_config_values_cannot_add_keys():
    hostile = cfg(forge={"base_branch": 'main", evil: [x'}, ci={"runner_tags": ["a, b]\nevil: yes"]})
    doc = parsed(hostile)
    assert doc[True]["push"]["branches"] == ['main", evil: [x', "l4/**"]
    assert doc["jobs"]["l4"]["runs-on"] == ["self-hosted", "a, b]\nevil: yes"]
    assert set(doc["jobs"]["l4"]) == {"if", "runs-on", "timeout-minutes", "concurrency", "env", "steps"}


def test_runner_tags_and_the_hosted_fallback():
    assert parsed(cfg(ci={"runner_tags": ["agentic", "gpu"]}))["jobs"]["l4"]["runs-on"] == [
        "self-hosted", "agentic", "gpu",
    ]  # fmt: skip
    assert parsed(cfg(ci={"runner_tags": []}))["jobs"]["l4"]["runs-on"] == "ubuntu-24.04"


def test_branch_prefix_and_token_env_follow_config():
    doc = parsed(cfg(forge={"branch_prefix": "bots/", "token_env": "MY_TOKEN"}))
    assert doc[True]["push"]["branches"][1] == "bots/**"
    assert doc["jobs"]["l4"]["env"] == {"MY_TOKEN": "${{ secrets.MY_TOKEN }}"}


def test_doctor_line_follows_self_provision():
    assert doctor_command(cfg(), "gitlab") == "doctor --ci --fix"  # auto: a persistent shell runner
    assert doctor_command(cfg(), "github") == "doctor --ci"  # auto: hosted runners are disposable
    assert doctor_command(cfg(ci={"self_provision": True}), "github") == "doctor --ci --fix"
    assert doctor_command(cfg(ci={"self_provision": False}), "gitlab") == "doctor --ci"
    assert ".l4/bin/l4 doctor --ci --fix ||" in render_github_ci(cfg(ci={"self_provision": True}))


def test_the_rendered_workflow_passes_the_policy_lint():
    assert lint_github_yaml(render_github_ci(L4Config())) == []
