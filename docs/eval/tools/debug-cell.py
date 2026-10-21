"""debug-cell.py ROLE PROFILE UNIT: run one eval cell with run_cell directly and keep its workspace (on the runner, as
gitlab-runner, in the harness venv with L4_CACHE set); print the exit, the setup gate tail and the log tail."""

import os
import sys
from pathlib import Path

import yaml

from l4.eval.cellrun import Cell, run_cell, subprocess_runner
from l4.eval.run import default_seeds_dir, eval_uv_cache
from l4.eval.seeds import load_seed_set
from l4.redact import Redactor

W = "/home/gitlab-runner/l4-eval-20261008"
role, profile, unit = sys.argv[1:4]
seeds = load_seed_set(default_seeds_dir())
base = yaml.safe_load(Path(f"{W}/profiles.yaml").read_text())
cell_dir = Path(f"{W}/debug/{role}-{profile}-{unit}")
raw = run_cell(
    Cell(role, profile, unit, 0),
    seeds=seeds,
    base_cfg=base,
    cell_dir=cell_dir,
    ref_judge="claude-code",
    runner=subprocess_runner,
    environ=dict(os.environ),
    timeout_s=900,
    redactor=Redactor({}),
    uv_cache=str(eval_uv_cache(os.environ)),
)
print("returncode", raw.returncode, "invalid", raw.invalid)
print("--- setup tail\n", raw.setup_tail[-3000:])
print("--- log tail\n", "\n".join(raw.log_text.splitlines()[-15:]))
