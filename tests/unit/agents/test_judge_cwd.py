"""A tool-less (judge) call starts in an empty directory inside the step's private dir, an implementer call in the
worktree (docs/research/07 A1b): the CLI cannot auto-load an agent-written AGENTS.md or CLAUDE.md into the check."""

from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import CodexAdapter
from l4.agents.kiro_cli import KiroCliAdapter
from l4.agents.opencode import OpenCodeAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile
from l4.sandbox.base import SandboxSpec
from l4.sandbox.bwrap import BwrapSandbox

PROFILES = {
    "claude-code": Profile(adapter="claude-code", model="sonnet", vendor="anthropic"),
    "codex": Profile(adapter="codex", model="gpt-6-luna", vendor="openai"),
    "opencode": Profile(adapter="opencode", model="opencode/big-pickle"),
    "kiro-cli": Profile(adapter="kiro-cli", model="claude-sonnet-4.5"),  # HB-13: never run live, so pinned here
}
ADAPTERS = {
    "claude-code": ClaudeCodeAdapter, "codex": CodexAdapter, "opencode": OpenCodeAdapter, "kiro-cli": KiroCliAdapter,
}


class Spy:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, argv, env, cwd, **kw):
        self.calls.append({"argv": list(argv), "cwd": cwd})
        kw["stdout_path"].parent.mkdir(parents=True, exist_ok=True)
        kw["stdout_path"].write_text("")
        return ProcOutcome(0)


@pytest.fixture
def world(tmp_path: Path):
    for sub in ("bin", "wt", "res", "main/.git", "home"):
        (tmp_path / sub).mkdir(parents=True)
    for exe in ("claude", "codex", "opencode", "kiro-cli"):
        (tmp_path / "bin" / exe).write_text("#!/bin/sh\n")
        (tmp_path / "bin" / exe).chmod(0o755)
    (tmp_path / "wt" / "AGENTS.md").write_text("planted by an earlier agent step\n")
    return tmp_path


def make(world: Path, adapter: str, mode: str, **kw) -> RunRequest:
    return RunRequest(
        profile=PROFILES[adapter], role="x", cwd=world / "wt", prompt="p", result_path=world / "res" / "result.json",
        raw_events_path=world / "raw" / f"{mode}.jsonl", env={"PATH": str(world / "bin")},
        permission_policy=PermissionPolicy(mode), **kw,  # type: ignore[arg-type]
    )  # fmt: skip


@pytest.mark.parametrize("adapter", list(ADAPTERS))
def test_a_judge_call_runs_in_an_empty_directory_under_the_step_dir(world, adapter):
    spy = Spy()
    req = make(world, adapter, "judge")
    ADAPTERS[adapter](spy).run(req)
    (call,) = spy.calls
    assert call["cwd"] == world / "res" / "judge-cwd" and list(call["cwd"].iterdir()) == []
    assert str(world / "wt") not in call["argv"]


@pytest.mark.parametrize("adapter", list(ADAPTERS))
@pytest.mark.parametrize("mode", ["implement", "read_only"])
def test_a_call_with_file_tools_stays_in_the_worktree(world, adapter, mode):
    spy = Spy()
    ADAPTERS[adapter](spy).run(make(world, adapter, mode))
    assert spy.calls[0]["cwd"] == world / "wt"
    assert not (world / "res" / "judge-cwd").exists()


@pytest.mark.parametrize("adapter", list(ADAPTERS))
def test_the_wrapper_is_told_the_judge_directory_and_not_the_worktree_for_an_implementer(world, adapter):
    seen: list[dict] = []

    def wrap(argv, env, cwd=None):
        seen.append({"cwd": cwd})
        from l4.sandbox.base import WrappedCommand

        return WrappedCommand(["bwrap", "--", *argv], dict(env))

    for mode in ("judge", "implement"):
        ADAPTERS[adapter](Spy()).run(make(world, adapter, mode, wrap=wrap))
    assert [s["cwd"] for s in seen] == [world / "res" / "judge-cwd", None]


def test_a_stale_file_in_the_judge_directory_does_not_survive_into_the_next_call(world):
    req = make(world, "claude-code", "judge")
    ClaudeCodeAdapter(Spy()).run(req)
    (world / "res" / "judge-cwd" / "AGENTS.md").write_text("left by the previous call\n")
    ClaudeCodeAdapter(Spy()).run(req)
    assert list((world / "res" / "judge-cwd").iterdir()) == []


def test_codex_judge_may_run_outside_a_git_repository_and_the_implementer_may_not(world):
    judge, impl = Spy(), Spy()
    CodexAdapter(judge).run(make(world, "codex", "judge"))
    CodexAdapter(impl).run(make(world, "codex", "implement"))
    assert "--skip-git-repo-check" in judge.calls[0]["argv"]
    assert "--skip-git-repo-check" not in impl.calls[0]["argv"]


@pytest.mark.parametrize("adapter", ["claude-code", "codex", "kiro-cli"])
def test_through_bwrap_the_judge_chdir_is_the_empty_directory_inside_a_mounted_path(world, adapter):
    spec = SandboxSpec(
        kind="agent", worktree=world / "wt", git_common_dir=world / "main/.git", tmp_dir=world / "res",
        home=world / "home", adapter=adapter,
    )  # fmt: skip
    sandbox = BwrapSandbox("/usr/bin/bwrap")
    argvs = {}
    for mode in ("judge", "implement"):
        spy = Spy()
        req = make(world, adapter, mode, wrap=lambda argv, env, cwd=None: sandbox.wrap(argv, spec, env, cwd))
        ADAPTERS[adapter](spy).run(req)
        argvs[mode] = spy.calls[0]["argv"]
    judge, impl = argvs["judge"], argvs["implement"]
    assert judge[judge.index("--chdir") + 1] == str(world / "res" / "judge-cwd")
    assert impl[impl.index("--chdir") + 1] == str(world / "wt")
    assert ["--bind", str(world / "res"), str(world / "res")] == judge[
        judge.index(str(world / "res")) - 1 : judge.index(str(world / "res")) + 2
    ]  # the judge directory is below a read-write mount
