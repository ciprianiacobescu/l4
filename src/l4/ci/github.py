"""The GitHub Actions workflow `l4 init --ci github` writes (forge-and-ci 2.14, 2.15): the M1.1 single routed job.

The structure is fixed in the template. Values from the config are written as JSON strings (valid YAML), so a branch
name or a runner tag cannot add a key. M1: forge-and-ci 2.16 (per-unit matrix jobs), `workflow_dispatch` inputs.
"""

import json
from importlib.resources import files
from typing import Literal

from l4.config.schema import L4Config

WORKFLOW_RELPATH = ".github/workflows/l4.yml"
HOSTED_RUNNER = "ubuntu-24.04"


def doctor_command(cfg: L4Config, platform: Literal["github", "gitlab"]) -> str:
    """The doctor line of the generated CI file (L4-DOC-002): `--fix` when `ci.self_provision` is true, or `auto` on a
    GitLab runner (persistent shell executors); a GitHub-hosted runner is disposable, so `auto` leaves it out."""
    setting = cfg.ci.self_provision
    fix = setting is True or (setting == "auto" and platform == "gitlab")
    return "doctor --ci --fix" if fix else "doctor --ci"


def render_github_ci(cfg: L4Config) -> str:
    tags = list(cfg.ci.runner_tags)
    runs_on = json.dumps(["self-hosted", *tags]) if tags else HOSTED_RUNNER
    values = {
        "BASE": json.dumps(cfg.forge.base_branch),
        "PREFIX": json.dumps(f"{cfg.forge.branch_prefix}**"),
        "RUNS_ON": runs_on,
        "TOKEN_ENV": cfg.forge.token_env,  # an environment variable name: the schema admits letters, digits, _
        "DOCTOR": doctor_command(cfg, "github"),
    }
    text = files("l4.ci").joinpath("templates", "l4.github.yml").read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"@@{key}@@", value)
    return text
