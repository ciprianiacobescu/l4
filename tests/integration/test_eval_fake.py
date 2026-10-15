"""L4-EVAL-020: `l4 eval` end to end with the scripted `fake` adapter in every agent role: the real `l4 run` of each
cell runs in this process (the injected runner), so the config, lease, worktree, gates, ladder, ledger and scorecard
are the production ones and no agent CLI is started."""

import io
import json
import sys
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any

import pytest
import yaml

from l4 import services
from l4.agents.base import LimitSignal
from l4.agents.factory import ADAPTERS
from l4.agents.fake import FakeAdapter, Step
from l4.cli import main
from l4.context import AppContext
from l4.eval.cellrun import RunnerOutput
from l4.eval.run import Deps, run_eval
from l4.eval.seeds import load_seed_set
from l4.redact import Redactor
from l4.specs.base import ValidationReport
from l4.specs.openspec import CliResult, OpenSpecCli, OpenSpecProvider

SEEDS = Path(__file__).resolve().parents[1] / "eval" / "seeds"
GOLDEN = Path(__file__).parent / "golden" / "eval_scorecard.json"
MKVENV = (
    "import os, sys\nos.makedirs('.venv/bin', exist_ok=True)\n"
    "open('.venv/bin/python', 'w').write('#!/bin/sh\\nexec %s \"$@\"\\n' % sys.argv[1])\n"
    "os.chmod('.venv/bin/python', 0o755)\n"
)


@pytest.fixture(autouse=True)
def stand_ins(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pinned OpenSpec CLI is not installed here: `validate` says valid. The clarifier is off in a cell."""
    monkeypatch.setattr(OpenSpecProvider, "validate", lambda self, unit, strict=True: ValidationReport(True, ()))
    monkeypatch.setattr(OpenSpecCli, "run_json", lambda self, *a: CliResult(a, 0, {"items": [{"valid": True}]}))
    monkeypatch.setitem(services.HOOKS, "clarify", "l4_test_no_clarifier:clarify_hook")
    # the Purpose of the seed `add-late-fee` has 40 characters (L4-OSP-007 wants 50). The seeds are frozen by
    # `seed_set_sha256` (L4-EVAL-022): the rule is switched off here and the seed is left to the eval owner
    monkeypatch.setattr("l4.orchestrator.purpose_issues", lambda unit_dir, specs_root: [])


def result(phase: str, **over: Any) -> dict[str, Any]:
    base = {"status": "done", "phase": phase, "task_ids": ["1.1"], "summary": f"{phase} done", "criteria_ids": []}
    return {**base, **over}


def judge_reply(ids: list[str], verdict: str = "pass", findings: list | None = None) -> dict[str, Any]:
    return {
        "criteria": [
            {"id": i, "verdict": verdict, "evidence": [{"kind": "file", "ref": "src/inventory/shelf.py", "quote": "x"}]}
            for i in ids
        ],
        "test_adequacy": [], "findings": findings or [],
        "riskiest_assumptions": ["the tests were not rerun", "the table is complete", "rounding is half-even"],
    }  # fmt: skip


def red_green(unit_id: str, *, wrong_first: bool = False) -> list[Step]:
    unit = load_seed_set(SEEDS).unit(unit_id)
    ids = [c.id for c in unit.criteria]
    writes_red = {rel: data.decode() for rel, data in unit.reference_red.items()}
    tests = sorted(r for r in writes_red if r.startswith("tests/"))
    red = Step(writes=writes_red, structured=result("red", criteria_ids=ids, tests_added=[f"{tests[0]}::t"]))
    green = Step(writes={r: d.decode() for r, d in unit.reference_green.items()}, structured=result("green"))
    wrong = Step(writes=writes_red, structured=result("red", status="red", criteria_ids=ids))  # the phase as status
    return [*([wrong] if wrong_first else []), red, green]


def mask(card: dict[str, Any]) -> dict[str, Any]:
    card = json.loads(json.dumps(card))
    card["env"] = "masked"
    card["scorecard_sha256"] = "masked"
    for cell in card["cells"]:
        cell["wall_s"] = 0.0
    for profile in card["profiles"]:
        profile["median_wall_s"] = 0.0 if profile["median_wall_s"] is not None else None
    return card


def test_a_seed_unit_goes_red_green_and_verdict_pass_with_a_scripted_retry_and_a_429(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shelf = load_seed_set(SEEDS).unit("add-shelf-code")
    late = load_seed_set(SEEDS).unit("add-late-fee")
    shelf_ids = [c.id for c in shelf.criteria]
    late_ids = [c.id for c in late.criteria]
    major = {"severity": "major", "title": "The fee ignores the balance", "detail": "always 200", "evidence": []}
    script = [
        # cell 1: implementer `impl` on add-shelf-code: a result with status "red", then red, green, judge PASS
        *red_green("add-shelf-code", wrong_first=True), Step(structured=judge_reply(shelf_ids)),
        # cell 2: implementer `impl429`: the first red step is rate limited
        Step(status="rate_limited", limit=LimitSignal("fake", None, "rate_limit", None, "fake.status", "429", None)),
        # cell 3: judge `judge` on the designed-defect unit (the units run in seed order): it holds the unit back
        Step(structured=judge_reply(late_ids, findings=[major])),
        # cell 4: judge `judge` on add-shelf-code (known good): PASS
        Step(structured=judge_reply(shelf_ids)),
    ]  # fmt: skip
    adapter = FakeAdapter(script)
    monkeypatch.setitem(ADAPTERS, "fake", lambda: adapter)
    mkvenv = tmp_path / "mkvenv.py"
    mkvenv.write_text(MKVENV)
    home = tmp_path / "home"
    home.mkdir()
    environ = {
        "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(home), "L4_HOME": str(tmp_path / "l4home"),
        "L4_CACHE": str(tmp_path / "cache"), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
    }  # fmt: skip
    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(yaml.safe_dump({"version": 1, "profiles": {
        "impl": {"adapter": "fake", "vendor": "fakeco"},
        "impl429": {"adapter": "fake", "vendor": "fakeco2"},
        "judge": {"adapter": "fake", "vendor": "judgeco"},
    }}))  # fmt: skip

    def in_process(argv, env, cwd, timeout):
        """The child `l4 run`, in this process, with the scratch config's sandbox and setup swapped for stand-ins."""
        path = Path(argv[argv.index("--config") + 1])
        cfg = yaml.safe_load(path.read_text())
        # only the mode: the rendered `caches` stay, so `l4 run`'s preflight sees the cell's cache as the eval wrote it
        cfg.setdefault("sandbox", {}).update(mode="none", allow_none=True)
        cfg["gates"]["setup"] = [f"{sys.executable} {mkvenv} {sys.executable}"]
        cfg["verifier"]["evidence"] = {"diff_coverage": {"mode": "off"}}
        path.write_text(yaml.safe_dump(cfg))
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(list(argv[3:]), environ=dict(env))
        return RunnerOutput(code, err.getvalue())

    app = AppContext(tmp_path / "repo", profiles, "human", 0, "r-20261007T1200Z-abcd", environ, Redactor({}))
    (tmp_path / "repo").mkdir()
    out = tmp_path / "out"
    code = run_eval(
        app, deps=Deps(runner=in_process, version_of=lambda a: "9.9.9"), impl=("impl", "impl429"), judge=("judge",),
        ref_judge="judge", units=("add-shelf-code", "add-late-fee"), k=1, out=out, seeds=SEEDS, cell_timeout="20m",
    )  # fmt: skip
    assert code == 0
    assert not adapter._script  # every scripted step was consumed, in order

    card = json.loads((out / "scorecard.json").read_text())
    assert card["complete"] is True
    cells = {c["cell_key"]: c for c in card["cells"]}
    ok = cells["implementer|impl|add-shelf-code|0"]
    assert ok["status"] == "pass" and ok["attempts"] == {"red": 2, "green": 1} and ok["verdict"] == "PASS"
    assert [e["kind"] for e in ok["errors"]] == ["schema"]  # the status "red" cost one attempt and was a schema error
    limited = cells["implementer|impl429|add-shelf-code|0"]
    assert limited["status"] == "invalid" and limited["invalid_reason"] == "rate_limited"
    held = cells["judge|judge|add-late-fee|0"]
    assert held["status"] == "pass" and held["agreement"] is True and held["verdict"] == "NEEDS_HUMAN"
    assert held["missed_defect"] is False

    masked = mask(card)
    if not GOLDEN.exists():  # first run of an intended change: write it, then read it before committing
        GOLDEN.write_text(json.dumps(masked, indent=1, sort_keys=True) + "\n")
    assert masked == json.loads(GOLDEN.read_text())
