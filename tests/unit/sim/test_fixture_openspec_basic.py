import json
import re

from l4.sim.scenarios import fixture_root
from l4.specs.criteria import openspec_criteria
from l4.specs.openspec import parse_openspec_tasks
from l4.verifier.judge import JudgeVerdict, parse_judge_output

from ._fixture_helpers import apply, gate, payload, seed_copy

F = "openspec-basic"
CHANGE = "openspec/changes/add-greeting"


def test_seed_repo_fails_gate_then_passes_with_payloads(tmp_path):
    repo = seed_copy(F, tmp_path / "repo")
    code, report = gate(repo)
    assert (code, report.total) == (0, 0)  # nothing to run yet: the red step must add the tests

    apply(F, repo, {"tests/test_greet.py": "greet_red_tests.py", "src/greeter.py": "greet_red_stub.py"})
    code, report = gate(repo)  # red 1.1
    assert code == 1 and report.ids_with("passed") == set() and len(report.ids_with("failed")) == 2
    assert all("NotImplementedError" in report.tests[i].message for i in report.ids_with("failed"))
    assert not report.collection_errors

    apply(F, repo, {"src/greeter.py": "greet_impl.py"})
    code, report = gate(repo)  # green 1.1
    assert code == 0 and len(report.ids_with("passed")) == 2

    apply(F, repo, {"tests/test_farewell.py": "farewell_red_tests.py", "src/greeter.py": "farewell_red_stub.py"})
    code, report = gate(repo)  # red 1.2: the earlier tests still pass, the new one fails
    assert code == 1 and len(report.ids_with("passed")) == 2 and len(report.ids_with("failed")) == 1

    apply(F, repo, {"src/greeter.py": "farewell_impl.py"})
    code, report = gate(repo)  # green 1.2
    assert code == 0 and len(report.ids_with("passed")) == 3


def test_a_module_that_does_not_import_is_a_collection_failure(tmp_path):
    repo = seed_copy(F, tmp_path / "repo")
    (repo / "tests" / "test_broken.py").write_text("import nothing_here\n")
    code, report = gate(repo)
    assert code == 1 and report.collection_errors == ["test_broken"] and report.total == 0


def test_the_change_has_two_tasks_and_three_criteria(tmp_path):
    change = seed_copy(F, tmp_path / "repo") / CHANGE
    tasks = parse_openspec_tasks((change / "tasks.md").read_bytes())
    assert [(t.key, t.done) for t in tasks] == [("1.1", False), ("1.2", False)]
    ids = [c.id for c in openspec_criteria(change)]
    assert ids == ["C-9618b9f5", "C-6057a7e3", "C-49a0a655"]


def test_scripted_tests_trace_real_criteria_by_name_and_red_stubs_only_raise():
    ids = {c.removeprefix("C-") for c in ("C-9618b9f5", "C-6057a7e3", "C-49a0a655")}
    names = re.findall(
        r"def (test_l4_c_([0-9a-f]{8})_\w+)\(", payload(F, "greet_red_tests.py") + payload(F, "farewell_red_tests.py")
    )
    assert {hex_id for _, hex_id in names} == ids
    for stub in ("greet_red_stub.py", "farewell_red_stub.py"):
        bodies = re.findall(r"def \w+\(name\):\n    (.*)", payload(F, stub))
        assert "raise NotImplementedError" in bodies
        for body in bodies:  # a stub is a signature and `raise NotImplementedError`; anything else is real code
            assert body == "raise NotImplementedError" or body.startswith(("if not", "return"))


def test_pass_all_is_a_valid_verdict_for_every_criterion():
    verdict = parse_judge_output(payload(F, "pass_all.json"))
    assert isinstance(verdict, JudgeVerdict)
    assert [c.id for c in verdict.criteria] == ["C-9618b9f5", "C-6057a7e3", "C-49a0a655"]
    assert {c.verdict for c in verdict.criteria} == {"pass"}
    final = payload(F, "farewell_impl.py")
    for criterion in verdict.criteria:  # the cited quotes are really in the final code
        assert criterion.evidence[0].quote in final
    assert json.loads(payload(F, "pass_all.json"))["findings"] == []


def test_payloads_and_seed_are_listed():
    root = fixture_root(F)
    assert sorted(p.name for p in root.joinpath("payloads").iterdir()) == [
        "clarifier_answer.json", "fail_greet.json", "farewell_impl.py", "farewell_red_stub.py",
        "farewell_red_tests.py", "greet_impl.py", "greet_red_stub.py", "greet_red_tests.py",
        "judge_pass.copilot.jsonl", "pass_all.json", "questions_answered.md",
    ]  # fmt: skip
