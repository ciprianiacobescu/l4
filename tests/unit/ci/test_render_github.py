import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from l4.ci.github import HOST_KEYS, JOB_TIMEOUT_MINUTES, doctor_command, expression_string, render_github_ci
from l4.ci.lint import lint_github_yaml
from l4.config.defaults import CREDENTIAL_PATHS
from l4.config.schema import L4Config

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ci"
GOLDEN = FIXTURES / "l4.github.default.yml"
BEFORE_ENVIRONMENT = (
    FIXTURES / "l4.github.no-environment.yml"
)  # the self-hosted file as it was before ci.github_environment


def cfg(**sections) -> L4Config:
    return L4Config.model_validate(sections)


def parsed(config: L4Config) -> dict:
    return yaml.safe_load(render_github_ci(config))


def test_workflow_golden():
    assert render_github_ci(L4Config()) == GOLDEN.read_text()


def test_self_hosted_default_differs_from_before_only_by_the_environment_line():
    before = BEFORE_ENVIRONMENT.read_text()
    now = render_github_ci(L4Config())
    assert "environment:" not in before and now != before
    lines = now.splitlines(keepends=True)
    at = next(i for i, ln in enumerate(lines) if ln.startswith("    runs-on:"))
    assert lines[at + 1].lstrip().startswith("#")  # a comment: the secrets belong in the environment
    env_line = next(i for i, ln in enumerate(lines) if ln.startswith("    environment:"))
    assert lines[env_line] == '    environment: "l4"\n'
    assert "".join(ln for i, ln in enumerate(lines) if not at < i <= env_line) == before


def test_environment_null_is_byte_identical_to_before():
    assert render_github_ci(cfg(ci={"github_environment": None})) == BEFORE_ENVIRONMENT.read_text()


def test_environment_follows_config_as_a_json_string_for_both_runner_kinds():
    for tags in (["agentic"], []):
        job = parsed(cfg(ci={"runner_tags": tags}))["jobs"]["l4"]
        assert job["environment"] == "l4"
        job = parsed(cfg(ci={"runner_tags": tags, "github_environment": "pipeline.prod-1"}))["jobs"]["l4"]
        assert job["environment"] == "pipeline.prod-1"
        assert "environment" not in parsed(cfg(ci={"runner_tags": tags, "github_environment": None}))["jobs"]["l4"]


def hosted_job(**ci) -> dict:
    return parsed(cfg(ci={"runner_tags": [], **ci}))["jobs"]["l4"]


def step_index(steps: list[dict], match: Callable[[dict], bool]) -> int:
    return next(i for i, st in enumerate(steps) if match(st))


def test_hosted_job_runs_setup_between_cache_steps():
    job = hosted_job()
    steps = job["steps"]
    restore = step_index(steps, lambda s: s.get("uses", "").startswith("actions/cache/restore@"))
    setup = step_index(steps, lambda s: s.get("run") == ".l4/bin/l4-setup")
    doctor = step_index(steps, lambda s: "doctor" in s.get("run", ""))
    save = step_index(steps, lambda s: s.get("uses", "").startswith("actions/cache/save@"))
    plan = step_index(steps, lambda s: "plan --sweep" in s.get("run", ""))
    assert step_index(steps, lambda s: s.get("uses", "").startswith("actions/checkout@")) == 0
    assert restore < setup < doctor < save < plan
    assert steps[doctor]["run"] == ".l4/bin/l4 doctor --ci --fix || .l4/bin/l4 ci map-exit $?"
    for index in (restore, save):
        assert len(steps[index]["uses"].split("@")[1].split()[0]) == 40  # pinned to a commit
    assert steps[restore]["id"] == "l4cache" and steps[restore]["with"]["path"] == steps[save]["with"]["path"]
    assert steps[restore]["with"]["key"] == steps[save]["with"]["key"]
    assert steps[save]["if"] == (
        "${{ success() && github.ref_name == env.L4_BASE_BRANCH && steps.l4cache.outputs.cache-hit != 'true' }}"
    )
    key_step = steps[step_index(steps, lambda s: s.get("id") == "l4key")]
    assert key_step["run"] == 'echo "image=${ImageOS:-unknown}" >> "$GITHUB_OUTPUT"'
    assert steps[restore]["with"]["key"].startswith(
        "l4-tools-${{ runner.os }}-${{ runner.arch }}-${{ steps.l4key.outputs.image }}-${{ hashFiles("
    )
    assert ".l4/vendor/src/l4/provision/catalog.py" in steps[restore]["with"]["key"]
    assert ".l4/vendor/src/l4/ci/templates/l4-setup.sh" in steps[restore]["with"]["key"]


def test_hosted_job_env_has_the_flag_and_the_base_branch():
    env = hosted_job()["env"]
    assert env["L4_SELF_PROVISION"] == "${{ vars.L4_SELF_PROVISION || 'auto' }}"
    assert env["L4_BASE_BRANCH"] == "main"
    assert hosted_job(self_provision=True)["env"]["L4_SELF_PROVISION"] == "${{ vars.L4_SELF_PROVISION || 'true' }}"
    for value in ("auto", False):
        assert hosted_job(self_provision=value)["env"]["L4_SELF_PROVISION"].endswith("|| 'auto' }}")
    doc = parsed(cfg(ci={"runner_tags": []}, forge={"base_branch": 'rel", evil: [x'}))
    assert doc["jobs"]["l4"]["env"]["L4_BASE_BRANCH"] == 'rel", evil: [x'
    assert "L4_FORGE_TOKEN" in doc["jobs"]["l4"]["env"]


def test_hosted_doctor_always_fixes_because_the_harness_decides_whether_to_install():
    for value in ("auto", False, True):
        runs = [s["run"] for s in hosted_job(self_provision=value)["steps"] if "doctor" in s.get("run", "")]
        assert runs == [".l4/bin/l4 doctor --ci --fix || .l4/bin/l4 ci map-exit $?"]


def test_job_timeout_env_comes_from_the_same_constant_as_timeout_minutes():
    """SCN-GHP-04 (L4-GHP-003): the soft deadline reads what the job is cut off at."""
    for tags in ([], ["agentic"]):
        job = parsed(cfg(ci={"runner_tags": tags}))["jobs"]["l4"]
        assert job["timeout-minutes"] == JOB_TIMEOUT_MINUTES
        assert job["env"]["L4_JOB_TIMEOUT_MINUTES"] == str(JOB_TIMEOUT_MINUTES)


def test_self_hosted_job_has_no_hosted_steps_or_env():
    job = parsed(L4Config())["jobs"]["l4"]
    assert set(job["env"]) == {"L4_FORGE_TOKEN", "L4_JOB_TIMEOUT_MINUTES", "L4_BASE_BRANCH"}
    assert not [s for s in job["steps"] if "l4-setup" in s.get("run", "") or "cache" in s.get("uses", "")]


def test_no_credential_path_is_cached():
    home = Path("/home/runner")

    def expand(raw: str) -> Path:
        return home / raw[2:] if raw.startswith("~/") else Path(raw)

    cache_step = next(s for s in hosted_job()["steps"] if s.get("uses", "").startswith("actions/cache/restore@"))
    cached = [expand(p) for p in cache_step["with"]["path"].split("\n") if p.strip()]
    assert cached, "the cache has paths"
    secrets = [expand(p) for paths in CREDENTIAL_PATHS.values() for p in paths]
    for path in cached:
        for secret in secrets:
            assert path != secret and path not in secret.parents, f"{path} caches {secret}"
    assert {str(p) for p in cached} == {
        f"/home/runner/{p}"
        for p in (
            ".local/bin", ".local/share/l4", ".local/share/claude", ".local/share/uv", ".cache/l4/installers",
            ".cache/uv",
        )
    }


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint is not installed")
@pytest.mark.parametrize(
    "config",
    [
        L4Config(),
        cfg(ci={"github_environment": None}),
        cfg(ci={"runner_tags": []}),
        cfg(ci={"runner_tags": [], "github_environment": None, "self_provision": True}),
        cfg(ci={"self_provision": True}, forge={"base_branch": "release/1.x"}),
        cfg(
            harness={"repository": "ssh://git@github.com/owner/harness.git", "commit": "ab" * 20},
            ci={"runner_tags": []},
        ),
    ],
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
    assert job["if"] == (
        "${{ github.event_name != 'push' || github.ref_name == 'main' || "
        "!contains(github.event.head_commit.message, 'L4-Run: ') }}"
    )
    assert job["concurrency"] == {"group": "l4", "cancel-in-progress": False}
    assert job["timeout-minutes"] == 180
    assert job["runs-on"] == ["self-hosted", "agentic"]
    checkout = job["steps"][0]
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    assert len(checkout["uses"].split("@")[1]) == 40  # pinned to a commit
    assert [s["run"].strip() for s in job["steps"] if "run" in s] == [
        BASE_CHECKOUT,
        ".l4/bin/l4 doctor --ci || .l4/bin/l4 ci map-exit $?",
        ".l4/bin/l4 plan --sweep || .l4/bin/l4 ci map-exit $?",
        ".l4/bin/l4 run || .l4/bin/l4 ci map-exit $?",
        ".l4/bin/l4 status",
    ]
    assert doc["permissions"] == {
        "contents": "write", "pull-requests": "write", "issues": "write", "checks": "read", "statuses": "write",
        "actions": "write",
    }  # fmt: skip


def test_no_pull_request_trigger_so_forks_never_run_it():
    assert not {"pull_request", "pull_request_target"} & set(parsed(L4Config())[True])


def test_config_values_cannot_add_keys():
    hostile = cfg(forge={"base_branch": 'main", evil: [x'}, ci={"runner_tags": ["a, b]\nevil: yes"]})
    doc = parsed(hostile)
    assert doc[True]["push"]["branches"] == ['main", evil: [x', "l4/**"]
    assert doc["jobs"]["l4"]["runs-on"] == ["self-hosted", "a, b]\nevil: yes"]
    assert set(doc["jobs"]["l4"]) == {"if", "runs-on", "environment", "timeout-minutes", "concurrency", "env", "steps"}


def test_runner_tags_and_the_hosted_fallback():
    assert parsed(cfg(ci={"runner_tags": ["agentic", "gpu"]}))["jobs"]["l4"]["runs-on"] == [
        "self-hosted", "agentic", "gpu",
    ]  # fmt: skip
    assert parsed(cfg(ci={"runner_tags": []}))["jobs"]["l4"]["runs-on"] == "ubuntu-24.04"


def test_branch_prefix_and_token_env_follow_config():
    doc = parsed(cfg(forge={"branch_prefix": "bots/", "token_env": "MY_TOKEN"}))
    assert doc[True]["push"]["branches"][1] == "bots/**"
    assert doc["jobs"]["l4"]["env"] == {
        "MY_TOKEN": "${{ secrets.MY_TOKEN }}", "L4_JOB_TIMEOUT_MINUTES": "180", "L4_BASE_BRANCH": "main",
    }  # fmt: skip


def test_doctor_line_follows_self_provision():
    assert doctor_command(cfg(), "gitlab") == "doctor --ci --fix"  # auto: a persistent shell runner
    assert doctor_command(cfg(), "github") == "doctor --ci"  # auto: hosted runners are disposable
    assert doctor_command(cfg(ci={"self_provision": True}), "github") == "doctor --ci --fix"
    assert doctor_command(cfg(ci={"self_provision": False}), "gitlab") == "doctor --ci"
    assert ".l4/bin/l4 doctor --ci --fix ||" in render_github_ci(cfg(ci={"self_provision": True}))


def test_the_rendered_workflow_passes_the_policy_lint():
    assert lint_github_yaml(render_github_ci(L4Config())) == []


def test_job_env_maps_exactly_the_chains_credentials():
    """SCN-PRV-74: a GitHub secret reaches the job only when its env names it, so the job names the forge token and the
    credential variable of every profile a role chain uses, and no other secret (L4-PRV-027)."""
    config = cfg(
        profiles={
            "claude": {"adapter": "claude-code", "auth": "subscription"},
            "claude-key": {"adapter": "claude-code", "auth": "api_key"},
            "codex-key": {"adapter": "codex", "auth": "api_key"},
            "codex-sub": {"adapter": "codex", "auth": "subscription"},
            "kiro": {"adapter": "kiro-cli", "auth": "api_key"},  # in no chain
            "free": {"adapter": "opencode", "model": "opencode/big-pickle"},
            "local": {
                "adapter": "opencode", "model": "magnitude/qwen",
                "options": {"provider": {
                    "id": "magnitude", "base_url": "http://10.0.0.5:10100/v1", "api_key_env": "MAGNITUDE_API_KEY",
                    "models": {"qwen": {"context": 32768, "output": 4096}},
                }},
            },
        },
        roles={"implementer": ["free", "codex-key", "codex-sub", "local"], "judges": ["claude", "claude-key"]},
    )  # fmt: skip
    env = parsed(config)["jobs"]["l4"]["env"]
    secrets = {name: value for name, value in env.items() if "secrets." in str(value)}
    assert secrets == {
        name: f"${{{{ secrets.{name} }}}}"
        for name in (
            "L4_FORGE_TOKEN",
            "ANTHROPIC_API_KEY",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CODEX_API_KEY",
            "MAGNITUDE_API_KEY",
        )
    }
    assert "KIRO_API_KEY" not in env  # its profile is in no chain
    assert render_github_ci(cfg()) == GOLDEN.read_text()  # no chain, no credential: the env is the forge token alone


BASE_CHECKOUT = (
    'git fetch --quiet origin "+refs/heads/$L4_BASE_BRANCH:refs/remotes/origin/$L4_BASE_BRANCH" '
    '&& git checkout --quiet --detach "origin/$L4_BASE_BRANCH" '
    '&& echo "l4: base checkout $(git rev-parse HEAD)"'
)


def test_other_branches_check_out_the_base():
    """SCN-GHP-07 (L4-GHP-005): "when `github.ref_name` is not the base branch, it fetches ... and runs `git checkout
    --detach origin/<base>`", the GitLab rule. The base reaches the shell only through the job env."""
    for tags in ([], ["agentic"]):
        for environment in ("l4", None):
            job = parsed(cfg(ci={"runner_tags": tags, "github_environment": environment}))["jobs"]["l4"]
            steps = job["steps"]
            at = step_index(steps, lambda st: "base checkout" in st.get("run", ""))
            assert "actions/checkout" in steps[at - 1]["uses"]  # right after the checkout
            assert at < step_index(steps, lambda st: ".l4/bin/" in st.get("run", ""))
            assert steps[at]["if"] == "${{ github.ref_name != env.L4_BASE_BRANCH }}"
            assert steps[at]["run"].strip() == BASE_CHECKOUT
            assert job["env"]["L4_BASE_BRANCH"] == "main"


def test_the_base_branch_is_never_interpolated_into_a_script():
    hostile = 'x"; curl evil #'
    doc = yaml.safe_load(render_github_ci(cfg(forge={"base_branch": hostile}, ci={"runner_tags": []})))
    assert doc["jobs"]["l4"]["env"]["L4_BASE_BRANCH"] == hostile
    for step in doc["jobs"]["l4"]["steps"]:
        assert hostile not in step.get("run", "")


def test_expression_string_doubles_quotes():
    assert expression_string("main") == "'main'"
    assert expression_string("it's") == "'it''s'"
    assert expression_string("a''b") == "'a''''b'"


def test_skip_rule_exempts_the_base():
    """SCN-GHP-08 (L4-GHP-006): the `L4-Run:` skip applies to every branch but the base."""
    want = (
        "${{ github.event_name != 'push' || github.ref_name == 'main' || "
        "!contains(github.event.head_commit.message, 'L4-Run: ') }}"
    )
    assert parsed(L4Config())["jobs"]["l4"]["if"] == want
    quoted = parsed(cfg(forge={"base_branch": "o'brien"}))["jobs"]["l4"]["if"]
    assert "github.ref_name == 'o''brien' ||" in quoted


COMMIT = "0123456789abcdef0123456789abcdef01234567"
SSH_HARNESS = {"repository": "ssh://git@github.com/owner/harness.git", "commit": COMMIT}


def fetched(repository: str = SSH_HARNESS["repository"], *, tags: list[str] | None = None) -> L4Config:
    return cfg(harness={"repository": repository, "commit": COMMIT}, ci={"runner_tags": tags or []})


def test_fetched_harness_key_step_and_cache_key():
    """SCN-GHP-14 (L4-GHP-010): an ssh harness gets a deploy-key step before the first `.l4/bin/` command, the secret
    only in that step's env, and the hosted cache key is the pinned commit, not the vendored files."""
    for tags in ([], ["agentic"]):
        job = parsed(fetched(tags=tags))["jobs"]["l4"]
        steps = job["steps"]
        at = step_index(steps, lambda st: st.get("name") == "harness deploy key")
        assert at < step_index(steps, lambda st: ".l4/bin/" in st.get("run", ""))
        step = steps[at]
        assert step["env"] == {"L4_HARNESS_SSH_KEY": "${{ secrets.L4_HARNESS_SSH_KEY }}"}
        assert "L4_HARNESS_SSH_KEY" not in job["env"]  # never the job env: only this step sees the key
        run = step["run"]
        assert run.count("L4_HARNESS_SSH_KEY") == 2 and 'echo "$L4_HARNESS_SSH_KEY"' not in run  # never echoed
        assert 'if [ -n "$L4_HARNESS_SSH_KEY" ]' in run and "umask 077" in run
        assert 'chmod 600 "$RUNNER_TEMP/l4-harness-key"' in run
        for host_key in HOST_KEYS:
            assert host_key in run
        assert len(HOST_KEYS) == 3 and all(k.startswith("github.com ssh-") or " ecdsa-" in k for k in HOST_KEYS)
        assert (
            'echo "GIT_SSH_COMMAND=ssh -i $RUNNER_TEMP/l4-harness-key -o IdentitiesOnly=yes '
            '-o UserKnownHostsFile=$RUNNER_TEMP/l4-known-hosts -o StrictHostKeyChecking=yes" >> "$GITHUB_ENV"'
        ) in run
    hosted = parsed(fetched())["jobs"]["l4"]["steps"]
    key = next(st for st in hosted if st.get("uses", "").startswith("actions/cache/restore@"))["with"]["key"]
    assert key.endswith(f"-harness-{COMMIT}") and "hashFiles" not in key
    save = next(st for st in hosted if st.get("uses", "").startswith("actions/cache/save@"))
    assert save["with"]["key"] == key


def test_an_https_or_vendored_harness_has_no_key_step():
    for config in (fetched("https://github.com/owner/harness.git"), L4Config(), cfg(ci={"runner_tags": []})):
        steps = parsed(config)["jobs"]["l4"]["steps"]
        assert not [st for st in steps if st.get("name") == "harness deploy key"]
        assert "L4_HARNESS_SSH_KEY" not in render_github_ci(config)
    https = parsed(fetched("https://github.com/owner/harness.git"))["jobs"]["l4"]["steps"]
    assert next(st for st in https if st.get("uses", "").startswith("actions/cache/restore@"))["with"]["key"].endswith(
        f"-harness-{COMMIT}"
    )
    vendored = parsed(cfg(ci={"runner_tags": []}))["jobs"]["l4"]["steps"]
    key = next(st for st in vendored if st.get("uses", "").startswith("actions/cache/restore@"))["with"]["key"]
    assert "hashFiles('.l4/vendor/src/l4/provision/catalog.py'" in key and "harness-" not in key


def test_the_pinned_host_keys_are_githubs_published_ones():
    assert HOST_KEYS[0] == "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
    assert [k.split()[1] for k in HOST_KEYS] == ["ssh-ed25519", "ecdsa-sha2-nistp256", "ssh-rsa"]


def test_permissions_cover_every_api_the_harness_calls_with_github_token():
    """With an explicit `permissions:` block every scope not named is `none` for GITHUB_TOKEN: the harness reads check
    runs (`checks: read`) and writes labels, comments and issue events through the Issues API (`issues: write`)."""
    permissions = parsed(cfg())["permissions"]
    assert permissions == {
        "contents": "write", "pull-requests": "write", "issues": "write", "checks": "read", "statuses": "write",
        "actions": "write",
    }  # fmt: skip
