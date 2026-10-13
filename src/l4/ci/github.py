"""The GitHub Actions workflow `l4 init --ci github` writes (forge-and-ci 2.14, 2.15): the M1.1 single routed job.

The structure is fixed in the template. Values from the config are written as JSON strings (valid YAML), so a branch
name or a runner tag cannot add a key. With no `ci.runner_tags` the job runs on a GitHub-hosted runner and gets the
setup step and the tool cache (L4-PRV-023); a self-hosted rendering has neither. M1: forge-and-ci 2.16 (per-unit
matrix jobs), `workflow_dispatch` inputs.
"""

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Literal

from l4.agents.credentials import credential_variable
from l4.config.schema import L4Config
from l4.provision.catalog import adapters_in_use

WORKFLOW_RELPATH = ".github/workflows/l4.yml"
HOSTED_RUNNER = "ubuntu-24.04"
# one number for `timeout-minutes` and the job env `L4_JOB_TIMEOUT_MINUTES` the soft deadline reads (L4-GHP-003)
JOB_TIMEOUT_MINUTES = 180
CACHE_ACTION = "actions/cache/{op}@55cc8345863c7cc4c66a329aec7e433d2d1c52a9 # v6.1.0"
# Only user-local tool directories. Never a credential path (`l4.config.defaults.CREDENTIAL_PATHS`): the login of
# opencode and kiro-cli lives under ~/.local/share/<tool>, so those two directories are left out on purpose.
CACHE_PATHS = (
    "~/.local/bin", "~/.local/share/l4", "~/.local/share/claude", "~/.local/share/uv", "~/.cache/l4/installers",
    "~/.cache/uv",
)  # fmt: skip
# The agent CLIs and bwrap, at the paths `l4 doctor --ci --fix` installs into. The setup action restores this cache
# (`.github/actions/l4/action.yml`, step `clipaths`, the output `clis-cache-paths`) and the workflow's save step reads
# that output; no workflow repeats the list. This tuple is the source the tests hold the action's list to.
# Not cached: `uv`, `uvx` and `l4` in ~/.local/bin (the harness cache holds them; `!` patterns remove earlier matches),
# npm's download cache `~/.cache/l4/npm` (353 MB, redundant once the installed copies under ~/.local/share/l4 are
# cached; it made the CLI cache twice as big and 12 s to restore) and `~/.cache/l4/locks`.
CLI_CACHE_PATHS = (
    "~/.local/bin", "!~/.local/bin/uv", "!~/.local/bin/uvx", "!~/.local/bin/l4",
    "~/.local/share/l4", "~/.local/share/claude", "~/.cache/l4/installers",
)  # fmt: skip
# GitHub's published SSH host keys (api.github.com/meta, 2026-10-11), pinned for the fetched harness's deploy key
# (L4-GHP-010): the clone checks the host against these and nothing else.
HOST_KEYS = (
    "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl",
    "github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=",  # noqa: E501
    "github.com ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCj7ndNxQowgcQnjshcLrqPEiiphnt+VTTvDP6mHBL9j1aNUkY4Ue1gvwnGLVlOhGeYrnZaMgRK6+PKCUXaDbC7qtbW8gIkhL7aGCsOr/C56SJMy/BCZfxd1nWzAOxSDPgVsmerOBYfNqltV9/hWCqBywINIR+5dIg6JTJ72pcEpEjcYgXkE2YEFXV1JHnsKgbLWNlhScqb2UmyRkQyytRLtL+38TGxkxCflmO+5Z8CSSNY7GidjMIZ7Q4zMjA2n1nGrlTDkzwDCsw+wqFPGQA179cnfGWOWRVruj16z6XyvxvjJwbz0wQZ75XK5tKSb7FNyeIEs4TT4jk+S4dhPeAUC5y+bDYirYgM4GC7uEnztnZyaVWQ7B381AK4Qdrwt51ZqExKbQpTUNn+EjqoTwvqNj4kqx5QUCI0ThS/YkOxJCXmPUWZbhjpCg56i+2aB6CmK2JGhn57K5mj0MNdBXA4/WnwH6XoPWJzK5Nyu2zB3nAZp+S5hpQs+p1vN1/wsjk=",  # noqa: E501
)  # fmt: skip
_CACHE_KEY_PREFIX = "l4-tools-${{ runner.os }}-${{ runner.arch }}-${{ steps.l4key.outputs.image }}-"


def cache_key(cfg: L4Config) -> str:
    """The tool cache key. A vendored harness (under .l4/vendor/ in the repository): a new pin or a new uv version is a
    new key. A fetched one is in no file of the checkout: its pinned commit stands in for the hash."""
    if cfg.harness.repository is not None:
        return f"{_CACHE_KEY_PREFIX}harness-{cfg.harness.commit}"
    return (
        _CACHE_KEY_PREFIX
        + "${{ hashFiles('.l4/vendor/src/l4/provision/catalog.py', '.l4/vendor/src/l4/ci/templates/l4-setup.sh') }}"
    )


def expression_string(text: str) -> str:
    """`text` as a GitHub expression string literal: single quotes, a `'` inside doubled."""
    return "'" + text.replace("'", "''") + "'"


def _job_condition(base: str) -> str:
    """The job `if:` (L4-GHP-006): the `L4-Run:` skip applies to a push on any branch but the base, where a merge or
    archive commit that carries the trailer must still reach the sweeper. Written as a JSON string (valid YAML)."""
    return json.dumps(
        "${{ github.event_name != 'push' || github.ref_name == "
        + expression_string(base)
        + " || !contains(github.event.head_commit.message, 'L4-Run: ') }}"
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


UPLOAD_STEP = """\
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        if: ${{ always() }}
        with:
          name: l4-out
          path: .l4-out/
          retention-days: 7"""


def _upload_step(cfg: L4Config) -> str:
    """The step that uploads `.l4-out` (prompts and agent transcripts, secrets masked), or nothing when
    `ci.upload_artifacts` is false: on a public repository any signed-in user can download the artifact."""
    return UPLOAD_STEP if cfg.ci.upload_artifacts else ""


def _schedule_block(cfg: L4Config) -> str:
    """The `schedule:` trigger from `ci.schedule` (the cron as a JSON string), or nothing when it is null."""
    if cfg.ci.schedule is None:
        return ""
    return f"  schedule:\n    - cron: {json.dumps(cfg.ci.schedule)}"


def _environment_block(name: str | None) -> str:
    if name is None:
        return ""
    return (
        "    # The forge token and the agent credentials are secrets of this GitHub Environment;\n"
        "    # repository secrets resolve too. Set ci.github_environment to null in .l4/config.yaml to leave it out.\n"
        f"    environment: {json.dumps(name)}"
    )


def _harness_key_step(cfg: L4Config) -> str:
    """The deploy-key step of a harness fetched over ssh (L4-GHP-010): with the secret set, the key goes to
    `$RUNNER_TEMP` (0600, which the sandbox hides), GitHub's host keys beside it, and `GIT_SSH_COMMAND` to the later
    steps. The secret is in this step's env alone and is never echoed."""
    if cfg.harness.repository is None or not cfg.harness.repository.startswith("ssh://"):
        return ""
    hosts = " ".join(f"'{key}'" for key in HOST_KEYS)
    ssh = (
        "ssh -i $RUNNER_TEMP/l4-harness-key -o IdentitiesOnly=yes "
        "-o UserKnownHostsFile=$RUNNER_TEMP/l4-known-hosts -o StrictHostKeyChecking=yes"
    )
    return f"""\
      - name: harness deploy key
        env:
          L4_HARNESS_SSH_KEY: ${{{{ secrets.L4_HARNESS_SSH_KEY }}}}
        run: |
          if [ -n "$L4_HARNESS_SSH_KEY" ]; then
            umask 077
            printf '%s\\n' "$L4_HARNESS_SSH_KEY" > "$RUNNER_TEMP/l4-harness-key"
            chmod 600 "$RUNNER_TEMP/l4-harness-key"
            printf '%s\\n' {hosts} > "$RUNNER_TEMP/l4-known-hosts"
            echo "GIT_SSH_COMMAND={ssh}" >> "$GITHUB_ENV"
          fi"""


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
          key: {cache_key(cfg)}"""
    return {
        "HOSTED_ENV": (f"      L4_SELF_PROVISION: ${{{{ vars.L4_SELF_PROVISION || '{rendered}' }}}}"),
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
        "JOB_TIMEOUT": str(JOB_TIMEOUT_MINUTES),
        "BASE": json.dumps(cfg.forge.base_branch),
        "BASE_ENV": json.dumps(cfg.forge.base_branch),
        "IF": _job_condition(cfg.forge.base_branch),
        "PREFIX": json.dumps(f"{cfg.forge.branch_prefix}**"),
        "RUNS_ON": runs_on,
        "TOKEN_ENV": cfg.forge.token_env,  # an environment variable name: the schema admits letters, digits, _
        "DOCTOR": "doctor --ci --fix" if hosted else doctor_command(cfg, "github"),
        "SCHEDULE": _schedule_block(cfg),
        "UPLOAD": _upload_step(cfg),
        "ENVIRONMENT": _environment_block(cfg.ci.github_environment),
        "CREDENTIAL_ENV": "\n".join(f"      {name}: ${{{{ secrets.{name} }}}}" for name in credential_secrets(cfg)),
        "HARNESS_KEY": _harness_key_step(cfg),
        "HOSTED_ENV": "", "HOSTED_SETUP": "", "HOSTED_SAVE": "",
        **(_hosted_blocks(cfg) if hosted else {}),
    }  # fmt: skip
    return _fill("l4.github.yml", values)


def _fill(template: str, values: dict[str, str]) -> str:
    text = files("l4.ci").joinpath("templates", template).read_text(encoding="utf-8")
    for key, value in values.items():
        # a block that is empty takes its whole line with it
        text = text.replace(f"@@{key}@@" if value else f"@@{key}@@\n", value)
    return text


ACTION_PATH = ".github/actions/l4"
_ACTION_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


@dataclass(frozen=True)
class ActionPin:
    """What the action-form workflow pins (adoption-kit D4, D5). `copy`: the consumer holds its own copy of the action
    (`uses: ./.github/actions/l4`), which fetches the harness over ssh at `sha`, so the `commit` input is the pin;
    otherwise `uses: <repository>/.github/actions/l4@<sha> # <ref>` is."""

    repository: str  # owner/repo of the harness, which holds the action
    sha: str
    ref: str | None = None
    copy: bool = False

    def __post_init__(self) -> None:
        # these reach the YAML as plain text, so each is checked against the shape it must have
        if not _ACTION_REPO.match(self.repository):
            raise ValueError(f"the action repository must look like owner/repo, not {self.repository!r}")
        if not _FULL_SHA.match(self.sha):
            raise ValueError(f"the pin must be a full commit sha (40 lowercase hex digits), not {self.sha!r}")
        if self.ref is not None and not _REF.match(self.ref):
            raise ValueError(f"the ref must be a tag or branch name, not {self.ref!r}")

    @property
    def ssh_url(self) -> str:
        return f"ssh://git@github.com/{self.repository}.git"


def _action_step(cfg: L4Config, pin: ActionPin, *, hosted: bool) -> str:
    inputs: list[tuple[str, str]] = []
    if pin.copy:
        inputs += [
            ("source", "repository"),
            ("repository", pin.ssh_url),
            ("commit", pin.sha),
            ("ssh-key", "${{ secrets.L4_HARNESS_SSH_KEY }}"),
        ]
    if hosted:  # the repository variable L4_SELF_PROVISION stays the switch, as in the vendored form
        rendered = "true" if cfg.ci.self_provision is True else "auto"
        inputs.append(("self-provision", f"${{{{ vars.L4_SELF_PROVISION || '{rendered}' }}}}"))
    else:  # a self-hosted runner keeps its own CLIs; there is no cache service to rely on
        inputs.append(("clis", "none"))
    uses = (
        f"./{ACTION_PATH}"
        if pin.copy
        else f"{pin.repository}/{ACTION_PATH}@{pin.sha}" + (f" # {pin.ref}" if pin.ref else "")
    )
    lines = [f"      - id: l4\n        uses: {uses}\n        with:"]
    lines += [f"          {name}: {value if value.startswith('$') or name == 'clis' else json.dumps(value)}"
              for name, value in inputs]  # fmt: skip
    return "\n".join(lines)


def _clis_save_step(hosted: bool) -> str:
    if not hosted:
        return ""
    return f"""\
      - name: save agent CLI cache
        if: >-
          ${{{{ success() && github.ref_name == env.L4_BASE_BRANCH && steps.l4.outputs.clis-cache-hit != 'true'
          && steps.l4.outputs.clis-cache-paths != '' }}}}
        uses: {CACHE_ACTION.format(op="save")}
        with:
          path: ${{{{ steps.l4.outputs.clis-cache-paths }}}}
          key: ${{{{ steps.l4.outputs.clis-cache-key }}}}"""


def render_github_action_ci(cfg: L4Config, pin: ActionPin) -> str:
    """The action form of the workflow (L4-ACT-004): the same job as `render_github_ci`, the harness from the setup
    action. `doctor --ci --fix` on a hosted runner, `doctor_command` on a self-hosted one, as in the other form."""
    tags = list(cfg.ci.runner_tags)
    hosted = not tags
    return _fill(
        "l4.github-action.yml",
        {
            "JOB_TIMEOUT": str(JOB_TIMEOUT_MINUTES),
            "BASE": json.dumps(cfg.forge.base_branch),
            "BASE_ENV": json.dumps(cfg.forge.base_branch),
            "IF": _job_condition(cfg.forge.base_branch),
            "PREFIX": json.dumps(f"{cfg.forge.branch_prefix}**"),
            "RUNS_ON": json.dumps(["self-hosted", *tags]) if tags else HOSTED_RUNNER,
            "TOKEN_ENV": cfg.forge.token_env,
            "DOCTOR": "doctor --ci --fix" if hosted else doctor_command(cfg, "github"),
            "SCHEDULE": _schedule_block(cfg),
            "UPLOAD": _upload_step(cfg),
            "ENVIRONMENT": _environment_block(cfg.ci.github_environment),
            "CREDENTIAL_ENV": "\n".join(f"      {n}: ${{{{ secrets.{n} }}}}" for n in credential_secrets(cfg)),
            "ACTION_STEP": _action_step(cfg, pin, hosted=hosted),
            "CLIS_SAVE": _clis_save_step(hosted),
        },
    )
