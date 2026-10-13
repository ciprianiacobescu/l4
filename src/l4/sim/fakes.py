"""The scripted agent of `l4 simulate` (SPEC L4-SIM-002): a `FakeAdapter` that picks its next step by what the prompt
asks for, not by call order.

A step says `when: {phase, task}`; both are read from the prompt the implementer renders (`# Phase: RED|GREEN`,
`# Task <key>`), so a scenario names the work, not the sequence. A step answers once. A request nothing matches fails
the run loudly, naming what was asked and what is left (SCN-SIM-N5, N6). The judge, clarifier and S1 profiles are the
same adapter in judge mode: the scripted verdict is the structured reply. `ProfileRouter` is the one adapter a
scenario registers (judges are limited to the `fake` adapter name), and sends each call to the agent of its profile.
M1: the shared `Clock` is `l4.availability.cooldown.FakeClock` (M1.2); this module builds none.
"""

import copy
import json
import os
import re
import signal
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any

from l4.agents.base import AdapterError, AgentCaps, ProbeCtx, ProbeResult, ProbeStep, RunRequest, RunResult
from l4.agents.fake import FakeAdapter
from l4.agents.fake import Step as FakeStep
from l4.clarifier.router import ROUTER_INSTRUCTION
from l4.config.schema import Profile
from l4.sim.scenarios import Step, When
from l4.specs.openspec import CliResult, OpenSpecCli

PROFILE_OPTION = "sim_profile"  # `Profile.options[PROFILE_OPTION]`: which scripted agent answers for the profile

_PHASE = re.compile(r"^# Phase: (RED|GREEN)\b", re.MULTILINE)
_TASK = re.compile(r"^# Task (\S+)\s*$", re.MULTILINE)


def asked_for(prompt: str) -> When:
    """What the implementer prompt asks for; both fields are None for a prompt that is not one (a judge's)."""
    phase, task = _PHASE.search(prompt), _TASK.search(prompt)
    return When(phase=phase.group(1).lower() if phase else None, task=task.group(1) if task else None)  # type: ignore[arg-type]


def _matches(wanted: When, asked: When) -> bool:
    return all(w is None or w == a for w, a in ((wanted.phase, asked.phase), (wanted.task, asked.task)))


class ScriptedAgent:
    name = "fake"

    def __init__(
        self,
        steps: Sequence[Step] = (),
        *,
        verdict: Mapping[str, Any] | str | None = None,
        probes: Mapping[ProbeStep, ProbeResult] | None = None,
        run_number: int | None = None,
    ) -> None:
        """`run_number` is set only in the child process of a killing scenario: a step whose `kill.run` equals it ends
        the process with SIGKILL. Without it (in-process runs) `kill` is ignored, so a test can never kill itself."""
        self._run_number = run_number
        self._steps = list(steps)
        self._verdict = verdict
        self._probes = dict(probes or {})
        self.requests: list[RunRequest] = []
        self.matched: list[When] = []  # what each answered step was asked for, in order

    def capabilities(self) -> AgentCaps:
        return AgentCaps("native", True, True, True, True, False, False, True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        return self._probes.get(step) or ProbeResult(step, True)

    def _judge(self, req: RunRequest) -> RunResult:
        if self._verdict is None:
            raise AdapterError("a judge was asked but the scenario scripts no verdict for this profile")
        verdict = json.loads(self._verdict) if isinstance(self._verdict, str) else copy.deepcopy(dict(self._verdict))
        return FakeAdapter([FakeStep(structured=verdict)]).run(req)

    def run(self, req: RunRequest) -> RunResult:
        self.requests.append(req)
        if req.permission_policy.mode == "judge":
            return self._judge(req)
        asked = asked_for(req.prompt)
        index = next((i for i, s in enumerate(self._steps) if _matches(s.when, asked)), None)
        if index is None:
            left = [s.when.model_dump(exclude_none=True) for s in self._steps]
            raise AdapterError(
                f"no scripted step matches phase={asked.phase!r} task={asked.task!r}; steps left: {left or 'none'}"
            )
        step = self._steps.pop(index)
        self.matched.append(asked)
        base: dict[str, Any] = {"status": "done", "phase": asked.phase, "task_ids": [asked.task], "criteria_ids": []}
        base["summary"] = f"{asked.phase} done"
        structured = {**base, **step.result} if step.result is not None else base
        fake = FakeStep(status=step.status, structured=structured, writes=step.write, delay_s=step.delay_s)
        kill = step.kill if step.kill is not None and step.kill.run == self._run_number else None
        if kill is not None and kill.at == "start":
            self._die(kill.after_s)
        result = FakeAdapter([fake]).run(req)
        if kill is not None:
            self._die(kill.after_s)  # long enough for the snapshot timer to fire once, if the scenario wants it
        return result

    @staticmethod
    def _die(after_s: float) -> None:
        time.sleep(after_s)
        os.kill(os.getpid(), signal.SIGKILL)


class ScriptedS1(ScriptedAgent):
    """The stand-in S1 judge of `clarifier.s1_standin: llm_boolean`, which is asked two questions of opposite polarity:
    "is this a product decision?" (yes sends the question to a human) and "does the citation support the answer?" (yes
    accepts it). `agrees` is whether S1 sides with the clarifier: the first is then answered no and the second yes."""

    def __init__(self, agrees: bool) -> None:
        super().__init__()
        self._agrees = agrees

    def _judge(self, req: RunRequest) -> RunResult:
        is_router_question = ROUTER_INSTRUCTION in req.prompt
        answer = not self._agrees if is_router_question else self._agrees
        return FakeAdapter([FakeStep(structured={"answer": answer})]).run(req)


class ProfileRouter:
    """The `fake` adapter of a scenario: every profile is adapter `fake` (a judge profile may be nothing else), and the
    profile's `options.sim_profile` names the `ScriptedAgent` that answers for it."""

    name = "fake"

    def __init__(self, agents: Mapping[str, ScriptedAgent]) -> None:
        self.agents = dict(agents)

    def _agent(self, profile: Profile) -> ScriptedAgent:
        key = profile.options.get(PROFILE_OPTION)
        if key not in self.agents:
            raise AdapterError(f"the scenario scripts no agent for profile {key!r}")
        return self.agents[key]

    def capabilities(self) -> AgentCaps:
        return AgentCaps("native", True, True, True, True, False, False, True)

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        return self._agent(profile).probe(profile, step, ctx)

    def run(self, req: RunRequest) -> RunResult:
        return self._agent(req.profile).run(req)


@contextmanager
def fake_openspec_cli() -> Iterator[None]:
    """`openspec validate` without node or the pinned package: a unit validates when its `tasks.md` and a spec delta
    exist. Nothing else the CLI does is called by a simulated run. Process-wide for the duration of the block."""

    def run_json(self: OpenSpecCli, *args: str) -> CliResult:
        name = args[1]
        valid = any((self._repo / "openspec" / "changes" / name).glob("specs/*/spec.md"))
        return CliResult(args, 0, {"items": [{"id": name, "valid": valid, "issues": []}]})

    original = OpenSpecCli.run_json
    OpenSpecCli.run_json = run_json  # type: ignore[method-assign]
    try:
        yield
    finally:
        OpenSpecCli.run_json = original  # type: ignore[method-assign]
