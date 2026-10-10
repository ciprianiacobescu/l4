import tempfile
from pathlib import Path

import pytest

from l4.sim.scenarios import ScenarioError, fixture_root, load_scenario

GOOD = """\
name: demo
fixture: openspec-basic
config: {roles: {implementer: [a]}}
profiles:
  a:
    probe: {quota: {used_percent: 10}}
    steps:
      - when: {phase: red, task: "1.1"}
        write: {"tests/test_greet.py": "@fixture:greet_red_tests.py"}
        result: {status: done}
judges:
  j: {verdict: "@fixture:pass_all.json"}
s1: {default_p: 0.95}
max_runs: 2
between_runs:
  - {message: answer, write: {"questions.md": "@fixture:greet_impl.py"}}
expect:
  exit_code: 0
  final_phase: in_review
  events_include: [{type: availability.selected}]
  trailers_include: {L4-Unit: "openspec:add-greeting"}
"""


def test_a_good_scenario_loads_and_resolves_payloads():
    scenario = load_scenario(GOOD)
    assert scenario.name == "demo" and scenario.max_runs == 2
    step = scenario.profiles["a"].steps[0]
    assert step.when.phase == "red" and step.when.task == "1.1"
    assert "class GreetTests" in step.write["tests/test_greet.py"]  # the payload's text, not its name
    assert '"verdict": "pass"' in scenario.judges["j"].verdict
    assert "def greet" in scenario.between_runs[0].write["questions.md"]


def test_malformed_scenario_rejected_before_any_temp_dir(monkeypatch):
    made: list[object] = []
    monkeypatch.setattr(tempfile, "mkdtemp", lambda *a, **k: made.append(1))
    with pytest.raises(ScenarioError, match="expct"):  # a mistyped key
        load_scenario(GOOD.replace("expect:", "expct:"))
    with pytest.raises(ScenarioError, match="missing.py"):  # a payload that does not exist
        load_scenario(GOOD.replace("greet_red_tests.py", "missing.py"))
    assert made == []


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("fixture: openspec-basic", "fixture: nope", "unknown fixture"),
        ("fixture: openspec-basic", "fixture: ../x", "not a fixture name"),
        ("@fixture:pass_all.json", "@fixture:../pass_all.json", "not a payload file name"),
        ("@fixture:pass_all.json", "@fixture:sub/pass_all.json", "not a payload file name"),
        ("name: demo", "name: Demo Name", "name"),
        ("phase: red", "phase: blue", "phase"),
        ("max_runs: 2", "max_runs: 0", "max_runs"),
        ("default_p: 0.95", "default_p: 1.5", "default_p"),
        ("exit_code: 0", "exit_code: 0\n  surprise: 1", "surprise"),
    ],
)
def test_invalid_scenarios_name_the_problem(old, new, message):
    with pytest.raises(ScenarioError, match=message):
        load_scenario(GOOD.replace(old, new))


def test_yaml_that_is_not_a_mapping_or_not_yaml():
    with pytest.raises(ScenarioError):
        load_scenario("- a\n- b\n")
    with pytest.raises(ScenarioError, match="not valid YAML"):
        load_scenario("a: [")


def test_fixture_roots():
    for name in ("openspec-basic", "kiro-basic"):
        root = fixture_root(name)
        assert root.joinpath("repo").is_dir() and root.joinpath("payloads").is_dir()
    assert Path(str(fixture_root("openspec-basic"))).is_dir()
