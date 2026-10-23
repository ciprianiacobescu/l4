"""A Kiro or Copilot judge replayed through the real adapter (kiro-judge D10, SCN-KJD-27; copilot-cli D18).

`ReplayProc` stands in for the process runner: it records the argv, environment, working directory and stdin of the
call and writes a recorded stream to `stdout_path` (exit 0, empty standard error, no session file, so no served model
is reported). `ReplayRouter` is the `kiro-cli` or `copilot-cli` adapter of a scenario: each replay judge profile gets
its own `KiroCliAdapter(ReplayProc(stream))` or `CopilotCliAdapter(ReplayProc(stream))`, picked by
`options.sim_profile`. Probes pass; nothing here runs a binary.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from l4.agents.base import AdapterError, AgentCaps, ProbeCtx, ProbeResult, ProbeStep, RunRequest, RunResult
from l4.agents.copilot_cli import CopilotCliAdapter
from l4.agents.kiro_cli import KiroCliAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile
from l4.sim.fakes import PROFILE_OPTION

REPLAY_EXE = "/sim/replay/kiro-cli"  # never executed: ReplayProc is the runner
REPLAY_ADAPTERS: dict[str, Any] = {"kiro-cli": KiroCliAdapter, "copilot-cli": CopilotCliAdapter}


class ReplayProc:
    def __init__(self, stream: str) -> None:
        self.stream = stream
        self.calls: list[dict] = []

    def run(
        self, argv, env, cwd: Path, *, stdout_path: Path, timeout_s: float, stdin: str | None = None,
        stderr_path: Path | None = None, **kw,
    ) -> ProcOutcome:  # fmt: skip
        self.calls.append({"argv": list(argv), "env": dict(env), "cwd": cwd, "stdin": stdin})
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(self.stream, encoding="utf-8")
        if stderr_path is not None:
            stderr_path.write_text("", encoding="utf-8")
        return ProcOutcome(0)


class ReplayRouter:
    """The `kiro-cli` or `copilot-cli` adapter of a scenario with replay judges."""

    model_unverified: ClassVar[bool] = True
    experimental: ClassVar[bool] = True

    def __init__(self, streams: Mapping[str, str], adapter: str = "kiro-cli") -> None:
        self.name = adapter
        self._cls = REPLAY_ADAPTERS[adapter]
        exe = REPLAY_EXE.replace("kiro-cli", adapter)
        self.adapters = {key: self._cls(ReplayProc(text), exe=exe) for key, text in streams.items()}

    def _adapter(self, profile: Profile) -> Any:
        key = profile.options.get(PROFILE_OPTION)
        if key not in self.adapters:
            raise AdapterError(f"the scenario replays no {self.name} stream for profile {key!r}")
        return self.adapters[key]

    def capabilities(self) -> AgentCaps:
        return self._cls().capabilities()

    def probe(self, profile: Profile, step: ProbeStep, ctx: ProbeCtx) -> ProbeResult:
        return ProbeResult(step, True)

    def run(self, req: RunRequest) -> RunResult:
        return self._adapter(req.profile).run(req)
