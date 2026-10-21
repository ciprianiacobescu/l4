"""Scenario files (SPEC L4-SIM-002): strict models, `@fixture:` payload references, and the fixtures they name.

A scenario that is malformed, or that names a payload or fixture that does not exist, is rejected here, before the
runner has created a temporary directory (SCN-SIM-N7).
"""

import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

FIXTURE_PREFIX = "@fixture:"
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PAYLOAD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ScenarioError(ValueError):
    pass


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class When(_S):
    phase: Literal["red", "green"] | None = None
    task: str | None = None


class Kill(_S):
    """The run process dies of SIGKILL in run number `run` only (1-based): `after_s` seconds after the step has
    written its files (`at: end`), or before it writes anything (`at: start`, a kill between two steps)."""

    run: int = Field(ge=1)
    at: Literal["start", "end"] = "end"
    after_s: float = Field(default=0.0, ge=0)


class Step(_S):
    when: When = Field(default_factory=When)
    write: dict[str, str] = Field(default_factory=dict)  # worktree path -> text, or `@fixture:<payload file>`
    result: dict[str, Any] | None = None  # merged over the default result of the phase
    status: Literal["ok", "max_turns", "budget", "permission_blocked", "auth", "quota", "rate_limited", "error"] = "ok"
    delay_s: float = Field(default=0.0, ge=0)
    kill: Kill | None = None


class ProbeScript(_S):
    quota: dict[str, Any] | None = None


class ProfileScript(_S):
    probe: ProbeScript | None = None
    steps: list[Step] = Field(default_factory=list)


class ReplayScript(_S):
    """A judge replayed through the real kiro-cli adapter: the recorded stream it answers with."""

    adapter: Literal["kiro-cli"]
    stream: str  # the stream text, or `@fixture:<payload file>`


class JudgeScript(_S):
    verdict: str | dict[str, Any] | None = None  # JSON text, or `@fixture:<payload file>`
    replay: ReplayScript | None = None  # exclusive with `verdict`

    @model_validator(mode="after")
    def _one_answer(self) -> "JudgeScript":
        if (self.verdict is None) == (self.replay is None):
            raise ValueError("a judge scripts exactly one of verdict and replay")
        return self


class DelegateScript(_S):
    """A scripted `roles.delegate` profile (delegate-answers 16.1): the structured replies it gives, in order, one for
    each question it is asked. Each is the `l4/delegate-result@1` document as a mapping, or JSON text, or
    `@fixture:<payload file>`. A reply the pass is not asked for stays unused; one it asks for beyond the list fails
    the run loudly."""

    replies: list[str | dict[str, Any]] = Field(default_factory=list)


class S1Script(_S):
    default_p: float = Field(ge=0, le=1)


class HumanCommit(_S):
    """What a person does on the remote between two runs (an answer in `questions.md`, a spec edit)."""

    message: str = "human edit"
    branch: str = "main"  # the unit branch for an answer in `questions.md`, `main` for a spec edit
    write: dict[str, str]


class Expect(_S):
    exit_code: int | None = None
    final_phase: str | None = None
    events_include: list[dict[str, Any]] = Field(default_factory=list)
    trailers_include: dict[str, str] = Field(default_factory=dict)


class Scenario(_S):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    fixture: str
    config: dict[str, Any] = Field(default_factory=dict)
    profiles: dict[str, ProfileScript] = Field(default_factory=dict)
    judges: dict[str, JudgeScript] = Field(default_factory=dict)
    delegates: dict[str, DelegateScript] = Field(default_factory=dict)
    s1: S1Script | None = None
    max_runs: int = Field(default=1, ge=1)
    between_runs: list[HumanCommit] = Field(default_factory=list)
    expect: Expect

    @property
    def kills(self) -> bool:
        """Whether any step ends its run with SIGKILL: such a scenario runs `l4 run` in child processes."""
        return any(step.kill for script in self.profiles.values() for step in script.steps)


def fixture_root(name: str) -> Traversable:
    """`builtin/fixtures/<name>`: `repo/` is the seed tree, `payloads/` holds what `@fixture:` names."""
    if not _NAME.match(name):
        raise ScenarioError(f"not a fixture name: {name!r}")
    root = files("l4.sim.builtin").joinpath("fixtures", name)
    if not root.joinpath("repo").is_dir():
        raise ScenarioError(f"unknown fixture {name!r}")
    return root


def _payload(root: Traversable, reference: str) -> str:
    name = reference.removeprefix(FIXTURE_PREFIX)
    if not _PAYLOAD.match(name) or ".." in name:
        raise ScenarioError(f"not a payload file name: {reference!r}")
    target = root.joinpath("payloads", name)
    if not target.is_file():
        raise ScenarioError(f"{reference} names no file in the fixture's payloads")
    return target.read_text(encoding="utf-8")


def _resolved(root: Traversable, value: str) -> str:
    return _payload(root, value) if value.startswith(FIXTURE_PREFIX) else value


def resolve_payloads(scenario: Scenario, root: Traversable) -> Scenario:
    """A copy with every `@fixture:` reference in step writes, judge verdicts, delegate replies and human commits
    replaced by the file's text."""
    out = scenario.model_copy(deep=True)
    for script in out.profiles.values():
        for step in script.steps:
            step.write = {path: _resolved(root, text) for path, text in step.write.items()}
    for judge in out.judges.values():
        if isinstance(judge.verdict, str):
            judge.verdict = _resolved(root, judge.verdict)
        if judge.replay is not None:
            judge.replay.stream = _resolved(root, judge.replay.stream)
    for delegate in out.delegates.values():
        delegate.replies = [_resolved(root, r) if isinstance(r, str) else r for r in delegate.replies]
    for commit in out.between_runs:
        commit.write = {path: _resolved(root, text) for path, text in commit.write.items()}
    return out


def load_scenario(text: str, *, source: str = "<scenario>") -> Scenario:
    """Parse, validate, and resolve payloads against the fixture the scenario names."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ScenarioError(f"{source}: not valid YAML ({type(exc).__name__})") from None
    try:
        scenario = Scenario.model_validate(document)
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
        raise ScenarioError(f"{source}: {'; '.join(problems)}") from None
    return resolve_payloads(scenario, fixture_root(scenario.fixture))


def load_scenario_file(path: Path) -> Scenario:
    return load_scenario(path.read_text(encoding="utf-8"), source=path.name)
