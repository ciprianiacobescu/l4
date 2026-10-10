"""M1.6 Exit B, live: `l4 s1 score` against Jev and, when `L4_LAYA_URL` is set, against the Mac's `laya-serve`, on
canary items; then `report`. Needs `L4_LIVE=1`. The Jev key is `TYPESAFE_API_KEY` (CI) or comes from Mintkey through
`scripts/dev/mintkey_secret.py`; it is never printed or written. At most MAX_REQUESTS requests per test run, over all
engines."""

import importlib.util
import json
import os
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.redact import Redactor
from l4.s1 import canary as c
from l4.s1 import export, report, score
from l4.s1 import records as r

from ..evidence._multi import build_repo

pytestmark = pytest.mark.live
MAX_REQUESTS = 30
ROWS_PER_ENGINE = 15
KEY_SECRET = "typesafe-jev-api-key"


def jev_key() -> str | None:
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    path = Path(__file__).resolve().parents[3] / "scripts" / "dev" / "mintkey_secret.py"
    try:
        spec = importlib.util.spec_from_file_location("mintkey_secret", path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return str(module.secret_value(KEY_SECRET))
    except Exception:  # Mintkey down, secret missing: the test skips, it does not fail the suite
        return None


def test_score_and_report_with_jev_and_laya_on_canary_items(tmp_path: Path):
    key = jev_key()
    if key is None:
        pytest.skip("no Jev key: set TYPESAFE_API_KEY or start the Mintkey stack")
    repo = tmp_path / "repo"
    build_repo(repo)
    canary = c.Canary(repo, cfg=L4Config(), seed=11, work_dir=tmp_path / "work", redactor=Redactor({}))
    canary.units = c.find_source_units(canary.git)
    items = {}
    for unit in canary.units[:3]:
        for mutation in ("none", "untested_function", "transplant_hunk"):
            for item in canary.run(unit, mutation, 0).items:
                items[item.item_key] = item
    cal = tmp_path / "cal.jsonl"
    r.append_records([cal], list(items.values()))
    ds = tmp_path / "ds"
    export.write_dataset(export.ground_truth_rows([cal]), ds, seed=1, allow_gaps=True)  # three units only
    dataset = ds / "train.jsonl"
    assert dataset.read_text().strip()

    profiles = {"jev": {"backend": "system-one", "engine": "jev", "api_key_env": "TYPESAFE_API_KEY"}}
    env = {"TYPESAFE_API_KEY": key}
    if os.environ.get("L4_LAYA_URL"):
        profiles["laya-mac"] = {"backend": "system-one", "engine": "remote", "base_url": os.environ["L4_LAYA_URL"]}
    cfg = L4Config.model_validate({"profiles": profiles})
    redactor = Redactor.from_env(["TYPESAFE_API_KEY"], env)
    outputs, requests = [], 0
    for name in profiles:
        out = tmp_path / f"{name}.jsonl"
        summary = score.run_score(
            cfg,
            name,
            dataset,
            out,
            redactor=redactor,
            environ=env,
            max_requests=min(ROWS_PER_ENGINE, MAX_REQUESTS - requests),
        )
        requests += summary.asked
        outputs.append(out)
        assert summary.asked > 0 and summary.errors <= summary.asked // 3, summary
        assert key not in out.read_text()
    assert requests <= MAX_REQUESTS
    result = report.build_report(outputs, dataset)
    text = report.render_markdown(result)
    print(text)  # only metrics and question ids; the assert below checks that no key is in it
    assert "jev" in result["engines"] and "# S1 comparison" in text and key not in text + json.dumps(result)
