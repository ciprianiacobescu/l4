import pytest

from l4.sim.builtin.manifest import BUILTIN, scenario_text
from l4.sim.scenarios import load_scenario

SPEC_NAMES = (
    "happy-openspec",
    "happy-kiro",
    "quota-fallback",
    "all-cooling-waiting-capacity",
    "midrun-limit-fallback",
    "stuck-clarifier-answers",
    "stuck-human-answers",
    "human-overrides-consumed-answer",
    "verify-fail-fix-pass",
    "fix-rounds-exhausted-escalate",
    "spec-gap-adds-scenario",
    "red-not-failing-rejected",
    "test-weakening-detected",
    "protected-file-reverted",
    "crash-mid-task-resume",
    "time-budget-continuation",
    "lock-contention",
    "s1-disagreement-needs-human",
    "judge-error-fails-closed",
    "archive-refuses-incomplete",
    "base-branch-moved-conflict",
)


def test_all_21_names_of_spec_17_present():
    assert sorted(BUILTIN) == sorted(SPEC_NAMES) and len(BUILTIN) == 21


def test_pending_is_reported_with_owner_never_as_pass():
    assert all(entry.owner for entry in BUILTIN.values())
    assert BUILTIN["quota-fallback"].owner == "agent-factory" and not BUILTIN["quota-fallback"].ready
    ready = sorted(name for name, entry in BUILTIN.items() if entry.ready)
    assert ready == [
        "crash-mid-task-resume", "happy-kiro", "happy-openspec", "stuck-clarifier-answers", "stuck-human-answers",
    ]  # fmt: skip
    assert all(BUILTIN[name].file for name in ready)  # ready needs a YAML


@pytest.mark.parametrize("name", [n for n, e in BUILTIN.items() if e.file])
def test_every_packaged_yaml_loads_against_its_fixture(name):
    scenario = load_scenario(scenario_text(name), source=name)
    assert scenario.name == name


def test_a_name_without_a_yaml_has_no_text():
    with pytest.raises(ValueError, match="agent-factory"):
        scenario_text("midrun-limit-fallback")
