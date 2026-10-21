import re

from l4.sim.scenarios import fixture_root
from l4.specs.base import Marker
from l4.specs.criteria import kiro_criteria
from l4.specs.detect import detect_frameworks
from l4.specs.kiro import KiroProvider, order_leaves, parse_kiro_tasks, read_waves
from l4.verifier.judge import JudgeVerdict, parse_judge_output

from ._fixture_helpers import apply, gate, payload, seed_copy

F = "kiro-basic"
SPEC = ".kiro/specs/user-greeting"


def test_tasks_and_the_fixture_agree_on_leaves_waves_optional_and_parents(tmp_path):
    repo = seed_copy(F, tmp_path / "repo")
    data = (repo / SPEC / "tasks.md").read_bytes()
    tasks = parse_kiro_tasks(data)
    assert [(t.key, t.depth, t.optional) for t in tasks] == [
        ("1", 0, False), ("1.1", 1, False), ("1.2", 1, True), ("2", 0, False), ("2.1", 1, False),
    ]  # fmt: skip
    waves = read_waves(data.decode(), {t.key for t in tasks})
    assert waves is not None and dict(waves.by_task) == {"2.1": 0, "1.1": 1}
    provider = KiroProvider(repo)
    (unit,) = provider.list_units()
    ordered = order_leaves(provider.tasks(unit))
    assert [t.key for t in ordered] == ["2.1", "1.1"]  # the graph puts the second parent's leaf first; 1.2 is optional
    assert detect_frameworks(repo).frameworks[0].value == "kiro"


def test_the_spec_is_valid_and_every_leaf_links_a_criterion(tmp_path):
    repo = seed_copy(F, tmp_path / "repo")
    provider = KiroProvider(repo, enforce=True)
    (unit,) = provider.list_units()
    report = provider.validate(unit)
    assert report.valid and not report.issues
    assert [(c.alias, c.id) for c in provider.criteria(unit)] == [
        ("Req 1.1", "C-8fd7d830"), ("Req 1.2", "C-4e4feccc"), ("Req 2.1", "C-590ae9d1"),
    ]  # fmt: skip


def test_finishing_the_required_leaves_ticks_both_parents_and_leaves_the_optional_one(tmp_path):
    repo = seed_copy(F, tmp_path / "repo")
    provider = KiroProvider(repo)
    (unit,) = provider.list_units()
    before = (repo / SPEC / "tasks.md").read_bytes()
    provider.set_marker(unit, "2.1", Marker.DONE)
    provider.set_marker(unit, "1.1", Marker.DONE)
    after = (repo / SPEC / "tasks.md").read_bytes()
    state = {t.key: t.marker_char for t in provider.tasks(unit)}
    assert state == {"1": "x", "1.1": "x", "1.2": " ", "2": "x", "2.1": "x"}
    assert len(before) == len(after) and sum(a != b for a, b in zip(before, after, strict=True)) == 4
    assert provider.done_gate(unit).passed


def test_the_gate_goes_red_then_green_in_wave_order(tmp_path):
    repo = seed_copy(F, tmp_path / "repo")
    apply(F, repo, {"tests/test_farewell.py": "farewell_red_tests.py", "src/greeter.py": "farewell_red_stub.py"})
    code, report = gate(repo)  # wave 0: farewell, red
    assert code == 1 and len(report.ids_with("failed")) == 1
    apply(F, repo, {"src/greeter.py": "farewell_impl.py"})
    assert gate(repo)[0] == 0
    apply(F, repo, {"tests/test_greet.py": "greet_red_tests.py", "src/greeter.py": "greet_red_stub.py"})
    code, report = gate(repo)  # wave 1: greet, red; the farewell test still passes
    assert code == 1 and len(report.ids_with("passed")) == 1 and len(report.ids_with("failed")) == 2
    apply(F, repo, {"src/greeter.py": "greet_impl.py"})
    code, report = gate(repo)
    assert code == 0 and len(report.ids_with("passed")) == 3


def test_scripted_tests_trace_every_criterion_by_name_and_the_verdict_covers_them(tmp_path):
    repo = seed_copy(F, tmp_path / "repo")
    ids = {c.id.removeprefix("C-") for c in kiro_criteria(repo / SPEC)}
    names = payload(F, "greet_red_tests.py") + payload(F, "farewell_red_tests.py")
    assert set(re.findall(r"def test_l4_c_([0-9a-f]{8})_", names)) == ids
    verdict = parse_judge_output(payload(F, "pass_all.json"))
    assert isinstance(verdict, JudgeVerdict) and {c.id.removeprefix("C-") for c in verdict.criteria} == ids
    for stub in ("greet_red_stub.py", "farewell_red_stub.py"):
        assert "raise NotImplementedError" in payload(F, stub)


def test_both_fixtures_share_the_gate_script():
    a = fixture_root("openspec-basic").joinpath("repo", "tests", "run_junit.py").read_text()
    b = fixture_root(F).joinpath("repo", "tests", "run_junit.py").read_text()
    assert a == b
