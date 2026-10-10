
from l4.sim.builtin.manifest import BUILTIN, scenario_text
from l4.sim.runner import run_scenario
from l4.sim.scenarios import load_scenario

READY = sorted(name for name, entry in BUILTIN.items() if entry.ready)


def test_all_ready_scenarios_twice_identical():
    """SCN-SIM-01: two runs of every ready scenario give the same normalised event sequences."""
    assert READY, "no ready built-in scenario"
    for name in READY:
        scenario = load_scenario(scenario_text(name), source=f"{name}.yaml")
        first, second = run_scenario(scenario), run_scenario(scenario)
        assert first.status == second.status == "pass", name
        assert first.events, name
        assert first.events == second.events, name


def test_a_scripted_quota_makes_the_primary_probe_report_the_exhausted_window():
    from l4.sim.runner import scripted_agents

    scenario = load_scenario(scenario_text("quota-fallback"), source="quota-fallback.yaml")
    agents = scripted_agents(scenario)
    primary = agents["primary"].probe(None, "quota", None)  # type: ignore[arg-type]
    assert primary.ok is False and primary.limit is not None
    assert primary.limit.kind == "usage_limit" and "100% used" in (primary.reason or "")
    assert primary.detail["windows"][0]["window_minutes"] == 300 and primary.detail["quota_used_percent"] == 100.0
    assert agents["secondary"].probe(None, "quota", None).ok is True  # type: ignore[arg-type]
