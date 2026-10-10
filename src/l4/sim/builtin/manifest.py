"""The 21 built-in scenarios of L4-SIM-003: who owns each, and whether it can run yet (simulation-harness D10).

A scenario is `ready` when its YAML is packaged and the features it needs are on this branch. A written scenario whose
owner has not landed is still `pending`: it is listed with its owner and never counted as a pass. Its owner adds the
YAML if needed and flips `ready`.
"""

from dataclasses import dataclass
from importlib.resources import files


@dataclass(frozen=True)
class BuiltinEntry:
    owner: str  # the change that delivers (or needs) the feature the scenario exercises
    file: str | None  # `builtin/scenarios/<file>`; None until a YAML exists
    ready: bool = False


def _entry(owner: str, name: str | None = None, *, ready: bool = False) -> BuiltinEntry:
    return BuiltinEntry(owner, f"{name}.yaml" if name else None, ready)


BUILTIN: dict[str, BuiltinEntry] = {
    "happy-openspec": _entry("simulation-harness", "happy-openspec", ready=True),
    "happy-kiro": _entry("simulation-harness", "happy-kiro", ready=True),
    "quota-fallback": _entry("agent-factory", "quota-fallback"),  # needs the fallback chains (the Q9 increment)
    "all-cooling-waiting-capacity": _entry("agent-factory"),
    "midrun-limit-fallback": _entry("agent-factory"),
    "stuck-clarifier-answers": _entry("clarification-loop", "stuck-clarifier-answers", ready=True),
    "stuck-human-answers": _entry("clarification-loop", "stuck-human-answers", ready=True),
    "human-overrides-consumed-answer": _entry("clarification-loop"),
    "verify-fail-fix-pass": _entry("verifier", "verify-fail-fix-pass"),  # needs fix units
    "fix-rounds-exhausted-escalate": _entry("verifier"),
    "spec-gap-adds-scenario": _entry("verifier"),
    "red-not-failing-rejected": _entry("implementer-tdd-loop"),
    "test-weakening-detected": _entry("implementer-tdd-loop"),
    "protected-file-reverted": _entry("implementer-tdd-loop"),
    "crash-mid-task-resume": _entry("state-vcs-locks", "crash-mid-task-resume", ready=True),
    "time-budget-continuation": _entry("forge-and-ci"),
    "lock-contention": _entry("state-vcs-locks"),
    "s1-disagreement-needs-human": _entry("verifier"),
    "judge-error-fails-closed": _entry("verifier"),
    "archive-refuses-incomplete": _entry("forge-and-ci"),
    "base-branch-moved-conflict": _entry("forge-and-ci"),
}


def scenario_text(name: str) -> str:
    """The packaged YAML of a built-in scenario; ValueError when it has none."""
    entry = BUILTIN[name]
    if entry.file is None:
        raise ValueError(f"the built-in scenario {name!r} has no YAML yet (owner: {entry.owner})")
    return files("l4.sim.builtin").joinpath("scenarios", entry.file).read_text(encoding="utf-8")
