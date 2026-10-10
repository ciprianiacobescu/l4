"""A scripted `runner` for `l4 eval`: stands in for the child `l4 run`. It reads the cell's scratch config to know
which profile runs, writes the ledger the script says onto the unit branch of the cell's `origin` (where the real run
pushes it), and returns the scripted exit code and output."""

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from l4.eval.cellrun import RunnerOutput

from ._ledgers import green_ledger

GIT_ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


def push_ledger(repo: Path, unit: str, events: Sequence[Mapping[str, Any]], report: str | None = None) -> None:
    branch = f"l4/openspec/{unit}"
    rel_dir = repo / "openspec" / "changes" / unit / ".l4" / "ledger"
    rel_dir.mkdir(parents=True, exist_ok=True)
    (rel_dir / "r-1.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    paths = [str((rel_dir / "r-1.jsonl").relative_to(repo))]
    if report is not None:
        (repo / "openspec" / "changes" / unit / "verification.md").write_text(report)
        paths.append(f"openspec/changes/{unit}/verification.md")
    for args in (["checkout", "-q", "-b", branch], ["add", "-f", *paths], ["commit", "-q", "-m", "ledger"],
                 ["push", "-q", "origin", branch]):  # fmt: skip
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@e.i", *args], cwd=repo, env=GIT_ENV,
                       check=True, capture_output=True)  # fmt: skip


class ScriptedRunner:
    """`behaviour(role, profile, unit)` returns (events, report, returncode, output); the default is a clean pass."""

    def __init__(self, behaviour: Callable[[str, str, str], tuple[list[dict], str | None, int, str]] | None = None):
        self.behaviour = behaviour or (lambda role, profile, unit: (green_ledger(), None, 0, "ok"))
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: Sequence[str], env: Mapping[str, str], cwd: Path, timeout: float) -> RunnerOutput:
        cfg = yaml.safe_load(Path(argv[list(argv).index("--config") + 1]).read_text())
        unit = argv[list(argv).index("--unit") + 1].split(":", 1)[1]
        role = "judge" if cfg["roles"]["implementer"] == ["eval-reference"] else "implementer"
        profile = cfg["roles"]["judges"][0] if role == "judge" else cfg["roles"]["implementer"][0]
        self.calls.append({"role": role, "profile": profile, "unit": unit, "env": dict(env), "timeout": timeout})
        events, report, code, output = self.behaviour(role, profile, unit)
        if events:
            push_ledger(cwd, unit, events, report)
        return RunnerOutput(code, output)
