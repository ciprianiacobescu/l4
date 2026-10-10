import json
from pathlib import Path

import pytest

from l4.cli import main


def simulate(*args: str, tmp_path: Path):
    return main(["simulate", "--repo", str(tmp_path), *args], environ={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})


def test_simulate_a_ready_scenario_and_pending_ones_in_one_run(tmp_path, capsys):
    code = simulate("happy-openspec", "quota-fallback", tmp_path=tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    assert "PASS     happy-openspec" in out
    assert "PENDING  quota-fallback  (owner: agent-factory)" in out
    assert out.strip().splitlines()[-1] == "1 passed, 0 failed, 1 pending"


def test_json_names_the_driver_the_status_and_the_owner(tmp_path, capsys):
    assert simulate("happy-openspec", "verify-fail-fix-pass", "--json", tmp_path=tmp_path) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["schema"] == "l4/simulate@1" and document["summary"] == {"pass": 1, "fail": 0, "pending": 1}
    ready, pending = document["scenarios"]
    assert (ready["driver"], ready["status"], ready["final_phase"]) == ("orchestrator", "pass", "in_review")
    assert (pending["status"], pending["owner"]) == ("pending", "verifier") and "exit_code" not in pending


def test_simulate_exit_1_on_mismatch_and_0_with_pending(tmp_path, capsys):
    broken = tmp_path / "expect-mismatch.yaml"
    from l4.sim.builtin.manifest import scenario_text

    broken.write_text(scenario_text("happy-openspec").replace("final_phase: in_review", "final_phase: escalated"))
    assert simulate(str(broken), tmp_path=tmp_path) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "final_phase: expected 'escalated', actual 'in_review'" in out
    assert out.strip().splitlines()[-1] == "0 passed, 1 failed, 0 pending"
    assert simulate("quota-fallback", tmp_path=tmp_path) == 0  # pending alone never fails the command


@pytest.mark.parametrize("args", [[], ["no-such-scenario"], ["--all", "--with-repo-config"]])
def test_usage_errors_are_exit_2(tmp_path, capsys, args):
    assert simulate(*args, tmp_path=tmp_path) == 2
    assert "simulate:" in capsys.readouterr().err


def test_a_scenario_that_names_a_missing_payload_is_rejected_before_anything_is_created(tmp_path, capsys):
    broken = tmp_path / "broken.yaml"
    from l4.sim.builtin.manifest import scenario_text

    broken.write_text(scenario_text("happy-openspec").replace("greet_impl.py", "nothing.py"))
    assert simulate(str(broken), tmp_path=tmp_path) == 2
    assert "nothing.py" in capsys.readouterr().err


def test_json_carries_a_digest_of_the_normalised_events_that_two_runs_share(tmp_path, capsys):
    digests = []
    for _ in range(2):
        assert simulate("happy-openspec", "--json", tmp_path=tmp_path) == 0
        [scenario] = json.loads(capsys.readouterr().out)["scenarios"]
        digests.append(scenario["events_sha256"])
    assert digests[0] == digests[1] and len(digests[0]) == 64
