"""L4-EVAL-006: the reference implementer replays through the real implement path, so the judge of a judge cell sees
harness-made commits, trailers and ledger, not a hand-built branch."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from l4 import services
from l4.cli import main
from l4.eval.cellconfig import REFERENCE_PROFILE, render_config
from l4.eval.replay import materialize_reference, reference_profile
from l4.eval.seeds import load_seed_set
from l4.eval.workspace import Identity, make_workspace

from ..specs.fixcli import patch_openspec


@pytest.fixture(autouse=True)
def no_verifier_or_clarifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(services.HOOKS, "verify", "l4_test_no_verifier:verify_hook")
    monkeypatch.setitem(services.HOOKS, "clarify", "l4_test_no_clarifier:clarify_hook")


def _git(cwd: Path, *args: str) -> str:
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("unit_id", ["add-shelf-code", "add-late-fee"])
def test_the_replay_profile_takes_a_unit_through_red_and_green(
    seeds_root: Path, tmp_path: Path, setup_command: str, unit_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_openspec(monkeypatch)  # the pinned OpenSpec is not installed here; the intake validates the unit (L4-ADO-007)
    # the Purpose of `add-late-fee` has 40 characters (L4-OSP-007 wants 50): the seeds are frozen by `seed_set_sha256`
    # (L4-EVAL-022), so the rule is switched off here and the seed is left to the eval owner
    monkeypatch.setattr("l4.orchestrator.purpose_issues", lambda unit_dir, specs_root: [])
    seeds = load_seed_set(seeds_root)
    unit = seeds.unit(unit_id)
    ws = make_workspace(seeds, unit, tmp_path / "ws", identity=Identity("t", "t@example.invalid"))
    ref = materialize_reference(unit, tmp_path / "reference")
    base = {"profiles": {"judge": {"adapter": "fake", "vendor": "someone"}}}
    cfg = render_config(base, "judge", "judge", ref_impl=reference_profile(ref))
    cfg["sandbox"] = {"mode": "none", "allow_none": True}
    cfg["gates"]["setup"] = [setup_command]
    (tmp_path / "cfg.yaml").write_text(yaml.safe_dump(cfg))
    (tmp_path / "home").mkdir()
    environ = {
        "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path / "home"), "L4_CACHE": str(tmp_path / "cache"),
        "L4_HOME": str(tmp_path / "l4home"), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
    }  # fmt: skip
    argv = ["run", "--config", str(tmp_path / "cfg.yaml"), "--unit", f"openspec:{unit_id}", "--repo", str(ws.repo)]
    assert main(argv, environ=environ) == 0

    outcome = json.loads((ws.repo / ".l4-out" / "outcome.json").read_text())
    assert outcome["units"][0]["phase_after"] == "implemented"
    assert outcome["units"][0]["profiles"]["implementer"] == REFERENCE_PROFILE
    log = _git(ws.origin, "log", "--format=%s%n%b%x00", f"main..l4/openspec/{unit_id}")
    assert "L4-TDD: red" in log and "L4-TDD: green" in log
    assert f"L4-Agent: {REFERENCE_PROFILE}" in log and f"L4-Unit: openspec:{unit_id}" in log
    ledger_path = f"openspec/changes/{unit_id}/.l4/ledger/"
    names = _git(ws.origin, "ls-tree", "--name-only", f"l4/openspec/{unit_id}", ledger_path).split()
    events = [
        json.loads(line)
        for name in names
        for line in _git(ws.origin, "show", f"l4/openspec/{unit_id}:{name}").splitlines()
    ]
    steps = [(e["phase"], e["attempt"], e["status"]) for e in events if e["type"] == "step.finished"]
    assert steps == [("red", 1, "ok"), ("green", 1, "ok")]
    assert [e["type"] for e in events if e["type"] in ("task.red_ok", "task.done")] == ["task.red_ok", "task.done"]
