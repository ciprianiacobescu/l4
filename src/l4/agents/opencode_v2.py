"""OpenCode v2 adapter (`@opencode/cli` 2.0.32, binary `opencode2`; experimental, L4-OCV-001 to -014, design
`openspec/changes/opencode-v2`), selected by `options.cli_major: 2`. This module is the command layer:

    opencode2 run --standalone --format json -m <provider/model> --title "l4 <role> <stem>"   # stdin: prompt, EOF

Every v2 call is standalone (without it a per-user daemon serves a later client the first client's environment
[V, row 8]) and has an empty `XDG_STATE_HOME` of its own, so a missed flag still cannot find a shared `service.json`.
`XDG_DATA_HOME` is never redirected: the credentials and `opencode.db` live there. v2 has no `--pure` and no `--dir`;
the cwd is the worktree (implement) or the empty judge directory (judge). The configuration is the native v2 shape,
not v1's, which v2 only normalises in memory (design D5). The parser and the run are later groups (B5, B6).
"""

import json
from pathlib import Path
from typing import Any, ClassVar

from l4.agents.base import (
    AdapterError,
    AgentCaps,
    PermissionPolicy,
    ProbeCtx,
    ProbeResult,
    ProbeStep,
    RunRequest,
    RunResult,
)
from l4.agents.opencode import DISABLE_SWITCHES, FREE_PREFIX, GIT_WRITES
from l4.agents.proc import ProcRunner
from l4.config.schema import OpencodeOptions, Profile

JUDGE_STEPS = 3  # one answering step, one tolerated rejected attempt, v2's forced tool-less summary (D6)
IMPLEMENT_STEPS = 200  # about 10x the largest recorded tool-call count: only a model that never ends reaches it
STATE_DIR = "opencode2-state"  # the empty `XDG_STATE_HOME` of a run or an export, in the step's private directory
SWITCHES = (*DISABLE_SWITCHES, "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS")  # v2 reads the skills switch; ignores one more
# the only subcommands the harness starts, as words: there is no `debug config`, `serve`, `service`, `api`, `pair` or
# `models` (each starts or reaches the shared daemon)
SUBCOMMANDS = (("run",), ("auth", "list"), ("session", "export"))
# v1 tool name -> v2 permission action, for `options.tools`; `list` has none (glob and read cover it, refused at load)
TOOL_ACTIONS = {
    "bash": "shell", "edit": "edit", "write": "edit", "patch": "edit", "read": "read", "glob": "glob", "grep": "grep",
}  # fmt: skip


def v2_argv(exe: str, subcommand: str, *args: str) -> list[str]:
    """The one builder of every v2 argv: `--standalone` right after the subcommand words. `subcommand` may be one
    string of words (`"auth list"`) or the first of them. A subcommand outside `SUBCOMMANDS` raises, so nothing
    that could reach the shared daemon is ever started."""
    words = [*subcommand.split(), *args]
    for known in SUBCOMMANDS:
        if tuple(words[: len(known)]) == known:
            return [exe, *known, "--standalone", *words[len(known) :]]
    raise AdapterError(
        f"opencode2 {subcommand} is not a subcommand the harness starts (run, auth list, session export)"
    )


def isolation_env_v2(config_dir: Path, state_dir: Path, content: str) -> dict[str, str]:
    """The isolation of one v2 call: an empty `XDG_CONFIG_HOME`, the call's own `XDG_STATE_HOME` (never shared, never
    `XDG_DATA_HOME`), the five disable switches and `OPENCODE_CONFIG_CONTENT`."""
    return {
        "XDG_CONFIG_HOME": str(config_dir), "XDG_STATE_HOME": str(state_dir), **{name: "1" for name in SWITCHES},
        "OPENCODE_CONFIG_CONTENT": content,
    }  # fmt: skip


def _refuse_read_only(policy: PermissionPolicy) -> None:
    """The read-only mode serves the delegate only, and nothing of it is recorded on v2 (amendment E4, L4-OCV-014):
    a path that skipped the load check still fails closed."""
    if policy.mode == "read_only":
        raise AdapterError(
            "the OpenCode v2 adapter has no read-only mode (the delegate is not served by options.cli_major: 2, "
            "L4-OCV-014)"
        )


def step_bound(policy: PermissionPolicy, options: OpencodeOptions | None) -> int:
    """`agents.build.steps` (L4-OCV-006): `options.steps.judge` (default 3) for every judge-mode call and the hello,
    `options.steps.implement` (default 200) for an implementer step."""
    _refuse_read_only(policy)
    steps = options.steps if options is not None else None
    if policy.mode == "judge":
        return steps.judge if steps is not None and steps.judge is not None else JUDGE_STEPS
    return steps.implement if steps is not None and steps.implement is not None else IMPLEMENT_STEPS


def _rule(action: str, effect: str, resource: str = "*") -> dict[str, str]:
    return {"action": action, "resource": resource, "effect": effect}


def _permissions(
    policy: PermissionPolicy, result_dir: Path, refuse: str, options: OpencodeOptions | None
) -> list[dict[str, str]]:
    """The ordered `permissions` array (design D5): the last matching rule wins, so broad rules come first and the
    `external_directory` deny-all precedes the allows for the private result directory [pinned by a test]."""
    if policy.mode == "judge":
        if refuse == "ask":  # a full deny gets a 403 from the free tier on v2 [V]; run mode refuses an ask on the spot
            return [_rule("*", "deny"), _rule("read", "ask"), _rule("shell", "ask")]
        return [_rule("*", "deny")]
    rules: list[dict[str, str]] = []
    if options is not None and options.tools:
        # Fallback `tools_by_permission` (U2): whether a v2 deny drops the tool's schema from the request is not
        # recorded, so the intent of `options.tools` is a deny-all and the listed tools' allows. v2's own normalisation
        # of the v1 form would allow `shell` again after them [V, recorded], which is why the array is native.
        if "list" in options.tools:
            raise AdapterError("options.tools: list has no OpenCode v2 permission action (glob and read cover it)")
        actions = list(dict.fromkeys(TOOL_ACTIONS[tool] for tool in options.tools))
        rules += [_rule("*", "deny"), *(_rule(action, "allow") for action in actions)]
    else:
        actions = ["edit", "read", "glob", "grep", "shell"]
        rules += [_rule(action, "allow") for action in actions]
    if "shell" in actions:  # the harness commits, never the agent
        rules += [_rule("shell", "deny", pattern) for pattern in GIT_WRITES]
    rules += [
        _rule("external_directory", "deny"), _rule("external_directory", "allow", f"{result_dir}/**"),
        _rule("external_directory", "allow", f"{result_dir}/*"),
        _rule("webfetch", "deny"), _rule("websearch", "deny"), _rule("question", "deny"),
        # Fallback `deny_skill_and_mask` (U6): v2 has two actions v1 never named. Skills are guidance the harness does
        # not choose and a subagent is a background child session, so both get the profile's refuse value (`ask` on a
        # free model, whose tier answers a removed tool with a 403 [I, as for bash]).
        _rule("skill", refuse), _rule("subagent", refuse),
    ]  # fmt: skip
    return rules


def config_content_v2(
    policy: PermissionPolicy, result_dir: Path, model: str, options: OpencodeOptions | None = None
) -> str:
    """`OPENCODE_CONFIG_CONTENT` in the native v2 shape (L4-OCV-005): `$schema`, `snapshots`, `share`, `update`, the
    ordered `permissions` and `agents.build.steps`. No v1 key (`permission`, `tools`, `snapshot`, `autoupdate`) and no
    `list` or `doom_loop` rule, which are not v2 actions. A read-only policy raises (amendment E4)."""
    steps = step_bound(policy, options)
    refuse = "ask" if model.startswith(FREE_PREFIX) else "deny"
    config: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json", "snapshots": False, "share": "disabled", "update": "disable",
        "permissions": _permissions(policy, result_dir, refuse, options), "agents": {"build": {"steps": steps}},
    }  # fmt: skip
    return json.dumps(config, separators=(",", ":"))


class OpenCodeV2Adapter:
    name = "opencode"  # both majors are the `opencode` adapter; the factory tells them apart by `cli_major`
    model_unverified: ClassVar[bool] = True  # SPEC 8.1: run mode does not report the served model
    experimental: ClassVar[bool] = True  # announced once per profile until B9 removes it (L4-OCV-013)

    def __init__(self, runner: ProcRunner | None = None) -> None:
        self._proc = runner or ProcRunner()

    def capabilities(self) -> AgentCaps:
        return AgentCaps("prompt_contract", False, False, False, False, False, False, True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        raise NotImplementedError("B6")  # the v2 probe; the v1 probe would start the wrong binary

    def build_command(self, req: RunRequest, *, exe: str, workdir: Path | None = None) -> list[str]:
        """`workdir` is the process's cwd (the caller sets it); v2 has no `--dir`, so it is not in the argv."""
        _refuse_read_only(req.permission_policy)
        model = req.profile.model
        if not model:
            raise AdapterError("an opencode profile needs a model (provider/model)")
        title = f"l4 {req.role} {req.raw_events_path.stem}"
        return v2_argv(exe, "run", "--format", "json", "-m", str(model), "--title", title)

    def run(self, req: RunRequest) -> RunResult:
        _refuse_read_only(req.permission_policy)  # before anything is created or started
        raise NotImplementedError("B6")
