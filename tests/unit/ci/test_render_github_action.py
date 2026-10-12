"""The action form of the GitHub workflow (adoption-kit L4-ACT-004, SCN-ACT-08): github-parity's job around one
`uses:` of the setup action, no `.l4/bin/` anywhere."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from l4.ci.github import CLI_CACHE_PATHS, ActionPin, render_github_action_ci, render_github_ci
from l4.config.schema import L4Config

REPO_ROOT = Path(__file__).resolve().parents[3]
ACTION_FILE = REPO_ROOT / ".github" / "actions" / "l4" / "action.yml"
SHA = "a1" * 20
PIN = ActionPin(repository="owner/harness", sha=SHA, ref="v0.3.0")
COPY = ActionPin(repository="owner/harness", sha=SHA, copy=True)


def cfg(**sections) -> L4Config:
    return L4Config.model_validate(sections)


def parsed(config: L4Config, pin: ActionPin = PIN) -> dict:
    return yaml.safe_load(render_github_action_ci(config, pin))


def job(config: L4Config | None = None, pin: ActionPin = PIN) -> dict:
    return parsed(config or cfg(ci={"runner_tags": []}), pin)["jobs"]["l4"]


def test_the_uses_line_is_one_sha_and_the_ref_in_a_comment():
    """SCN-ACT-08: `uses: …@<sha> # <ref>`."""
    text = render_github_action_ci(L4Config(), PIN)
    assert f"      - id: l4\n        uses: owner/harness/.github/actions/l4@{SHA} # v0.3.0\n" in text
    assert ".l4/bin" not in text and "harness.commit" not in text


def test_a_pin_without_a_ref_has_no_comment():
    text = render_github_action_ci(L4Config(), ActionPin("owner/harness", SHA))
    assert f"uses: owner/harness/.github/actions/l4@{SHA}\n" in text


def test_the_job_around_the_steps_is_the_github_parity_one():
    """Triggers, permissions, environment, concurrency, timeout, the skip rule and the job env are the template's."""
    for config in (L4Config(), cfg(ci={"runner_tags": []}), cfg(ci={"github_environment": None})):
        now, before = parsed(config), yaml.safe_load(render_github_ci(config))
        assert {k: v for k, v in now.items() if k != "jobs"} == {k: v for k, v in before.items() if k != "jobs"}
        a, b = now["jobs"]["l4"], before["jobs"]["l4"]
        for key in ("if", "runs-on", "environment", "timeout-minutes", "concurrency"):
            assert a.get(key) == b.get(key), key
        assert a["env"].pop("L4_SELF_PROVISION", None) is None  # the action exports it
        b["env"].pop("L4_SELF_PROVISION", None)
        assert a["env"] == b["env"]


def test_steps_checkout_base_checkout_action_doctor_save_plan_run_status_upload():
    steps = job()["steps"]
    assert [s.get("name") or s["uses"].split("@")[0] for s in steps] == [
        "actions/checkout", "base checkout", "owner/harness/.github/actions/l4", "doctor", "save agent CLI cache",
        "plan", "run", "status", "actions/upload-artifact",
    ]  # fmt: skip
    by_name = {s.get("name"): s for s in steps}
    assert by_name["base checkout"] == {
        **job(cfg(ci={"runner_tags": []}))["steps"][1],
    }
    assert by_name["doctor"]["run"] == "l4 doctor --ci --fix || l4 ci map-exit $?"
    assert by_name["plan"]["run"] == "l4 plan --sweep || l4 ci map-exit $?"
    assert by_name["run"]["run"] == "l4 run || l4 ci map-exit $?"
    assert by_name["status"]["run"] == "l4 status" and by_name["status"]["if"] == "${{ always() }}"
    upload = steps[-1]
    assert upload["if"] == "${{ always() }}" and upload["with"]["path"] == ".l4-out/"
    assert upload["with"]["name"] == "l4-out" and upload["with"]["retention-days"] == 7


def test_base_checkout_and_checkout_are_the_template_steps():
    now, before = job()["steps"], yaml.safe_load(render_github_ci(cfg(ci={"runner_tags": []})))["jobs"]["l4"]["steps"]
    assert now[0] == before[0] and now[1] == before[1]


def test_the_action_step_takes_the_repository_variable_for_the_runner_setup():
    step = job()["steps"][2]
    assert step["id"] == "l4"
    assert step["with"] == {"self-provision": "${{ vars.L4_SELF_PROVISION || 'auto' }}"}
    rendered = job(cfg(ci={"runner_tags": [], "self_provision": True}))["steps"][2]
    assert rendered["with"]["self-provision"] == "${{ vars.L4_SELF_PROVISION || 'true' }}"


def test_the_cli_cache_is_saved_after_doctor_on_the_base_branch_when_the_key_had_no_hit():
    save = next(s for s in job()["steps"] if s.get("name") == "save agent CLI cache")
    assert save["uses"].startswith("actions/cache/save@")
    assert save["if"] == (
        "${{ success() && github.ref_name == env.L4_BASE_BRANCH && steps.l4.outputs.clis-cache-hit != 'true'"
        " && steps.l4.outputs.clis-cache-paths != '' }}"
    )
    assert save["with"]["key"] == "${{ steps.l4.outputs.clis-cache-key }}"
    assert save["with"]["path"] == "${{ steps.l4.outputs.clis-cache-paths }}"


def test_the_rendered_workflow_holds_no_literal_cli_cache_path():
    """The list lives in the action only: a copy in a consumer's workflow drifts when `l4 upgrade` moves the pin."""
    for pin in (PIN, COPY):
        text = render_github_action_ci(cfg(ci={"runner_tags": []}), pin)
        for path in CLI_CACHE_PATHS:
            assert path not in text, path


def test_the_saved_paths_are_the_ones_the_action_restores():
    """The action restores and the workflow saves: one list, or the cache never hits."""
    action = yaml.safe_load(ACTION_FILE.read_text())
    steps = {s.get("id"): s for s in action["runs"]["steps"]}
    assert steps["clis"]["with"]["path"] == "${{ steps.clipaths.outputs.paths }}"
    lines = steps["clipaths"]["run"].splitlines()
    start = lines.index("paths<<L4_CLI_PATHS") + 1
    assert lines[start : lines.index("L4_CLI_PATHS", start)] == list(CLI_CACHE_PATHS)


def test_the_saved_paths_never_include_a_credential_path():
    from l4.config.defaults import CREDENTIAL_PATHS

    secrets = [p for paths in CREDENTIAL_PATHS.values() for p in paths]
    for path in CLI_CACHE_PATHS:
        for secret in secrets:
            assert path != secret and not secret.startswith(path + "/"), f"{path} caches {secret}"


def test_a_self_hosted_job_skips_the_cli_cache_and_the_provision_variable():
    steps = parsed(L4Config())["jobs"]["l4"]["steps"]  # default: runner_tags set
    action = next(s for s in steps if s.get("id") == "l4")
    assert action["with"] == {"clis": "none"}
    assert not any("cache/save" in s.get("uses", "") for s in steps)
    assert next(s for s in steps if s.get("name") == "doctor")["run"].startswith("l4 doctor --ci")


def test_copy_uses_the_local_action_and_passes_the_repository_and_the_commit():
    """`--action-copy`: the pin is the `commit` input, the key is the deploy key secret."""
    step = job(pin=COPY)["steps"][2]
    assert step["uses"] == "./.github/actions/l4"
    assert step["with"] == {
        "source": "repository",
        "repository": "ssh://git@github.com/owner/harness.git",
        "commit": SHA,
        "ssh-key": "${{ secrets.L4_HARNESS_SSH_KEY }}",
        "self-provision": "${{ vars.L4_SELF_PROVISION || 'auto' }}",
    }
    assert "# " not in render_github_action_ci(L4Config(), COPY).split("uses: ./")[1].splitlines()[0]


def test_values_from_the_pin_cannot_add_a_key():
    with pytest.raises(ValueError, match="owner/repo"):
        ActionPin(repository="o/h\n    run: x", sha=SHA)
    with pytest.raises(ValueError, match="40"):
        ActionPin(repository="o/h", sha="abc")
    with pytest.raises(ValueError, match="ref"):
        ActionPin(repository="o/h", sha=SHA, ref="v1\nrun: x")


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint is not installed")
@pytest.mark.parametrize(
    ("config", "pin"),
    [
        (L4Config(), PIN),
        (cfg(ci={"runner_tags": []}), PIN),
        (cfg(ci={"runner_tags": []}), COPY),
        (cfg(ci={"runner_tags": [], "github_environment": None, "self_provision": True}), PIN),
        (cfg(ci={"runner_tags": []}, forge={"base_branch": "release/1.x"}), COPY),
        (cfg(ci={"runner_tags": []}), ActionPin("owner/harness", SHA)),
    ],
)
def test_actionlint_is_clean(config, pin, tmp_path):
    """SCN-ACT-08: every render passes actionlint, the copied action's inputs included."""
    workflow = tmp_path / ".github" / "workflows" / "l4.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(render_github_action_ci(config, pin))
    (tmp_path / ".github" / "actions" / "l4").mkdir(parents=True)
    shutil.copy(ACTION_FILE, tmp_path / ".github" / "actions" / "l4" / "action.yml")
    labels = "".join(f"    - {tag}\n" for tag in config.ci.runner_tags)
    (tmp_path / "actionlint.yaml").write_text(f"self-hosted-runner:\n  labels:\n{labels}" if labels else "{}\n")
    argv = ["actionlint", "-no-color", "-config-file", str(tmp_path / "actionlint.yaml"), str(workflow)]
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
