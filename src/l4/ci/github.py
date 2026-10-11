"""The GitHub Actions workflow `l4 init --ci github` writes (forge-and-ci 2.14, 2.15): the M1.1 single routed job.

The structure is fixed in the template. Values from the config are written as JSON strings (valid YAML), so a branch
name or a runner tag cannot add a key. With no `ci.runner_tags` the job runs on a GitHub-hosted runner and gets the
setup step and the tool cache (L4-PRV-023); a self-hosted rendering has neither. M1: forge-and-ci 2.16 (per-unit
matrix jobs), `workflow_dispatch` inputs.
"""

import json
from importlib.resources import files
from typing import Literal

from l4.agents.credentials import credential_variable
from l4.config.schema import L4Config
from l4.provision.catalog import adapters_in_use

WORKFLOW_RELPATH = ".github/workflows/l4.yml"
HOSTED_RUNNER = "ubuntu-24.04"
CACHE_ACTION = "actions/cache/{op}@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0"
# Only user-local tool directories. Never a credential path (`l4.config.defaults.CREDENTIAL_PATHS`): the login of
# opencode and kiro-cli lives under ~/.local/share/<tool>, so those two directories are left out on purpose.
CACHE_PATHS = (
    "~/.local/bin", "~/.local/share/l4", "~/.local/share/claude", "~/.local/share/uv", "~/.cache/l4", "~/.cache/uv",
)  # fmt: skip
# the harness is vendored under .l4/vendor/ in a consumer repository: a new pin or a new uv version is a new key
CACHE_KEY = (
    "l4-tools-${{ runner.os }}-${{ runner.arch }}-${{ steps.l4key.outputs.image }}-"
    "${{ hashFiles('.l4/vendor/src/l4/provision/catalog.py', '.l4/vendor/src/l4/ci/templates/l4-setup.sh') }}"
)


def doctor_command(cfg: L4Config, platform: Literal["github", "gitlab"]) -> str:
    """The doctor line of the generated CI file (L4-DOC-002): `--fix` when `ci.self_provision` is true, or `auto` on a
    GitLab runner (persistent shell executors); a GitHub-hosted runner is disposable, so `auto` leaves it out."""
    setting = cfg.ci.self_provision
    fix = setting is True or (setting == "auto" and platform == "gitlab")
    return "doctor --ci --fix" if fix else "doctor --ci"


def credential_secrets(cfg: L4Config) -> list[str]:
    """The secrets the job must name besides the forge token (L4-PRV-027, SCN-PRV-74): the credential variable of every
    profile a role chain uses (L4-PRV-024) and an opencode provider's `api_key_env`. A GitHub secret reaches a job
    only through its `env`; an unset one maps to an empty value, which the harness treats as unset."""
    names: set[str] = set()
    for adapter, profiles in adapters_in_use(cfg).items():
        for name in profiles:
            profile = cfg.profiles[name]
            variable = credential_variable(adapter, profile.auth)
            if variable:
                names.add(variable)
            options = profile.opencode_options() if adapter == "opencode" else None
            if options is not None and options.provider is not None:  # a free model has no options at all
                names.add(options.provider.api_key_env)
    names.discard(cfg.forge.token_env)
    return sorted(names)


def _environment_block(name: str | None) -> str:
    if name is None:
        return ""
    return (
        "    # The forge token and the agent credentials are secrets of this GitHub Environment;\n"
        "    # repository secrets resolve too. Set ci.github_environment to null in .l4/config.yaml to leave it out.\n"
        f"    environment: {json.dumps(name)}"
    )


def _hosted_blocks(cfg: L4Config) -> dict[str, str]:
    """The pieces only a GitHub-hosted job has (L4-PRV-023). `doctor --ci --fix` is always on here: it installs only
    when `resolve_self_provision` says so (`L4_SELF_PROVISION`, from the repository variable), so the line is the
    same for every setting."""
    rendered = "true" if cfg.ci.self_provision is True else "auto"
    paths = "\n".join(f"            {path}" for path in CACHE_PATHS)
    cache = f"""\
        with:
          path: |
{paths}
          key: {CACHE_KEY}"""
    return {
        "HOSTED_ENV": (
            f"      L4_SELF_PROVISION: ${{{{ vars.L4_SELF_PROVISION || '{rendered}' }}}}\n"
            f"      L4_BASE_BRANCH: {json.dumps(cfg.forge.base_branch)}"
        ),
        "HOSTED_SETUP": f"""\
      - name: tool cache key
        id: l4key
        run: echo "image=${{ImageOS:-unknown}}" >> "$GITHUB_OUTPUT"
      - name: restore tool cache
        id: l4cache
        uses: {CACHE_ACTION.format(op="restore")}
{cache}
      - name: setup
        run: .l4/bin/l4-setup""",
        "HOSTED_SAVE": f"""\
      - name: save tool cache
        if: ${{{{ success() && github.ref_name == env.L4_BASE_BRANCH && steps.l4cache.outputs.cache-hit != 'true' }}}}
        uses: {CACHE_ACTION.format(op="save")}
{cache}""",
    }


def render_github_ci(cfg: L4Config) -> str:
    tags = list(cfg.ci.runner_tags)
    hosted = not tags
    runs_on = json.dumps(["self-hosted", *tags]) if tags else HOSTED_RUNNER
    values = {
        "BASE": json.dumps(cfg.forge.base_branch),
        "PREFIX": json.dumps(f"{cfg.forge.branch_prefix}**"),
        "RUNS_ON": runs_on,
        "TOKEN_ENV": cfg.forge.token_env,  # an environment variable name: the schema admits letters, digits, _
        "DOCTOR": "doctor --ci --fix" if hosted else doctor_command(cfg, "github"),
        "ENVIRONMENT": _environment_block(cfg.ci.github_environment),
        "CREDENTIAL_ENV": "\n".join(f"      {name}: ${{{{ secrets.{name} }}}}" for name in credential_secrets(cfg)),
        "HOSTED_ENV": "", "HOSTED_SETUP": "", "HOSTED_SAVE": "",
        **(_hosted_blocks(cfg) if hosted else {}),
    }  # fmt: skip
    text = files("l4.ci").joinpath("templates", "l4.github.yml").read_text(encoding="utf-8")
    for key, value in values.items():
        # a block that is empty takes its whole line with it
        text = text.replace(f"@@{key}@@" if value else f"@@{key}@@\n", value)
    return text
