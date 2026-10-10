"""The `l4 run` of a killing scenario, in a process of its own (`python -m l4.sim.child <world> <run number>`).

`l4 run` cannot take scripted agents, so this entry point is `run_command` with `adapters=` and the same patch of
`openspec validate` as an in-process scenario. It reads the scenario that `l4.sim.runner` saved in the world; a step
with `kill:` for this run number ends the process with SIGKILL, which is the point of running it here.
"""

import sys
from dataclasses import replace
from pathlib import Path

from l4.exitcodes import classify_exception
from l4.orchestrator import run_command
from l4.outcome import new_run_id
from l4.sim.fakes import ProfileRouter, fake_openspec_cli
from l4.sim.runner import SCENARIO_FILE, scripted_agents, sim_app
from l4.sim.scenarios import Scenario


def main(argv: list[str]) -> int:
    root, number = Path(argv[0]), int(argv[1])
    scenario = Scenario.model_validate_json((root / SCENARIO_FILE).read_text(encoding="utf-8"))
    router = ProfileRouter(scripted_agents(scenario, number))
    try:
        with fake_openspec_cli():
            return int(run_command(replace(sim_app(root), run_id=new_run_id()), adapters={"fake": router}).code)
    except Exception as exc:  # noqa: BLE001 - the parent reads the exit code and this line
        code, message = classify_exception(exc)
        print(f"{type(exc).__name__}: {message}", file=sys.stderr)
        return int(code)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
