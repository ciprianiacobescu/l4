# S1 evidence records (M1.6b)

| date | status | files |
|---|---|---|
| 2026-10-08 (Laya round 2) | **stopped at the shortcut check, no training, no scoring.** First data set with sample-consumer (private, GitLab 119) units: 2129 rows, 39 units (27 / 6 / 6). The token `inventory` decides `relevant` at 0.938 on the test split (rule: 0.9). 0 Jev requests, no gate, no comparison; the engine order of 2026-10-07 stands | `laya-round-2.md`, `manifest-2026-10-08.json`, `shortcuts-2026-10-08.json` |
| 2026-10-07-tev1 | **addendum** to the 2026-10-05-live record (same `test.jsonl`, no new data): Ollama's `tev1` scored in one pass, 147 of 147 rows; the report adds it to base Laya, tuned Laya and Jev. Not a gate: tev1 is not a trained checkpoint | `compare-2026-10-07-tev1.*`, `slices-2026-10-07-tev1.*` |
| 2026-10-05-live | **current** (M1.6 live exit, step 4). Real data: 14 dummy-agentic units on main and the unit branches (12 gave items; `show-item-count`, `show-subtotal` dropped as `baseline_failed`), including the live unit `add-bulk-discount` with its human label, + 8 `py_multi` units. Split seed 1607 (1606 refused by the export). Gate **FAILED**: not deployable | `canary-`, `manifest-`, `shortcuts-`, `train-`, `train-log-`, `thresholds-`, `gate-`, `gate-log-`, `compare-`, `slices-2026-10-05-live.*` |
| 2026-10-05 | superseded by the live record. Real data: 8 dummy-agentic units found on the MR heads (7 gave items; `add-shipping-fee` was dropped as a checker disagreement) + 8 `py_multi` units. Gate **FAILED**: not deployable | `canary-`, `manifest-`, `shortcuts-`, `train-`, `thresholds-`, `gate-`, `compare-`, `slices-2026-10-05.*`; scripts in `scripts/s1/evidence/` |
| 2026-10-04 | **VOID**: shortcut evidence (one synthetic repository, a test split of the templates the checkpoint learned). Kept as history only; the JSON files are left byte-identical on purpose (their sha256s are referenced elsewhere) | `train-`, `thresholds-`, `gate-`, `compare-2026-10-04.*` |

Project keys in the slices (the root commit of each repository, `l4/s1/items.project_key`):

* `project:git-35b5a131ecf1` = `example-group/dummy-agentic` (root `35b5a131`): **real** units written by agents (Codex, OpenCode, Claude
  Code) through the harness and opened as MRs !1 (merged), !4, !5, !8, !10, !12, !15 (+ the fix unit inside !15).
* `project:git-4103b23e74dd` = sample-consumer (GitLab 119, **private**: committed records carry aggregate numbers only).
* `project:git-e13e7b2e670c` = `tests/fixtures/py_multi` built by `tests/unit/evidence/_multi.py` (root `e13e7b2e`): **synthetic**.

`<scratch>` below is the session scratchpad (`/tmp/claude/.../scratchpad`); paths of that form inside the
JSON files and the canary log are left as written.

## How the 2026-10-05 record was made

1. `git clone git@gitlab.example.com:example-group/dummy-agentic.git <scratch>/m16-dummy` (read-only: push URL set to
   `/nonexistent/read-only`), then one local branch per open MR head (`l4/openspec/{add-average-price, add-vat,
   add-is-empty, add-money-format, add-split-amount, add-shipping-fee}`, `l4/kiro/add-loyalty-points`; not the archive
   branch). MR heads checked against the GitLab API (Mintkey `example-gitlab`, read-only listing).
2. `L4_S1_CANARY_ROOTS=<scratch> l4 s1 canary --repo <scratch>/m16-pymulti --also-repo <scratch>/m16-dummy --seed 1606
   --target 500 --test-command "<m16 .venv python> -m pytest -q -p no:cacheprovider --junitxml=.l4-out/junit.xml -o
   pythonpath=src" --out <scratch>/m16-run/canary.jsonl` (349 s): 1198 items, **exit 2** (quotas unmet, below).
3. `l4 s1 export --source canary.jsonl --out ds --seed 1606`: 1036 rows. `laya-evals validate` (laya 0.3.24) exits 0
   for each split.
4. Shortcut check on the export, **before training** (`scripts/s1/evidence/shortcut_check.py`, `stump_maxacc.py`,
   `bow_lr.py`; output `shortcuts-2026-10-05.json`).
5. `laya_tune.py train --base typed-decisions@7b928d82... --seed 1606 --device mps` (full train split, 2 epochs), then
   `laya_tune.py gate`.
6. `l4 s1 score` for `laya` (base), `laya-tuned` (the failed-gate checkpoint, score-only path) and `jev`
   (`jev-1.13.0`, `--gate gate.json --max-requests 60`), then `l4 s1 report --gate gate.json --profile laya-tuned`.
7. `scripts/s1/evidence/slices.py` (run with `uv run python` in the harness project): real vs synthetic, untouched (`mutation:none`) vs mutated, on all scored rows and
   on the 60 rows all three engines scored (`slices-2026-10-05.*`).

Not committed (they carry source text of the repositories or raw engine answers); pinned by sha256:

| file | sha256 |
|---|---|
| `canary.jsonl` | `cb65aff78f831b13fca2b10f732d862c2671d4cbc228ef969c4d3cc445a485bc` |
| `train.jsonl` | `e314ef9ce0d3c941d002ac05bd8f2b46a540293447abbd38e09a4a9c90ccdaa5` |
| `calib.jsonl` | `702ce63bfac051c1482a58c7abea92bc614ad45feeb090b922f65e63226dce95` |
| `test.jsonl` | `6c4bedce043c7ad5a79e6094b1bae7dfa216bda3cbf3528ffb3c55ee9380864c` |
| `scores-base.jsonl` | `24005310fc26c3a4a569d7319c484a3228e6d78b633f20332495e06e014b5736` |
| `scores-tuned.jsonl` | `81bdca940ced5f9ffdd135671861ff592b22e650e3124b85ff7924bc8dd56cf1` |
| `scores-jev.jsonl` | `8608c7476862919d2fdd074e344722670780bc624ad7c664d98f305cb79d29dc` |

Jev answers are in `scores-jev.jsonl` only, which nothing in the training path reads (TypeSafe MCA §2.3(b)); the
export's label sources are `deterministic:scope`, `deterministic:diff-coverage` and `deterministic:tests-ran`, nothing
else. The ledgers and `verification.md`/`verdict.json` files inside the dummy-agentic units are part of the unit
ranges but are **not** a label source.

`scripts/s1/evidence/` holds the scripts that produced `shortcuts-` and `slices-2026-10-05.*` (`bow_lr.py` needs scikit-learn: `uv run --isolated --no-project --with scikit-learn python bow_lr.py ds out.json`). They are evidence
tooling, not harness code, and have no tests of their own; `slices.py` reuses `l4.s1.report`'s outcome and metric code.

## How the 2026-10-05-live record was made (M1.6 live exit, step 4)

1. Fresh `py_multi` (`tests/unit/evidence/_multi.py` `build_repo`, root `e13e7b2e`) and a fresh SSH clone of
   dummy-agentic at `main` `b98d1d0` (push URL `/nonexistent/read-only`), one local branch per unit branch
   (`l4/openspec/{add-average-price, add-vat, add-is-empty, add-money-format, add-split-amount, add-shipping-fee,
   add-cart-clear, add-item-count, show-subtotal, add-cent-rounding, add-bulk-discount}`, `l4/kiro/add-loyalty-points`;
   no archive branch). `add-bulk-discount` was fetched at `ad2000c`, after the human verdicts of step 3.
2. `L4_CACHE=<run>/l4cache L4_S1_CANARY_ROOTS=<scratch> l4 s1 canary --repo <py_multi> --also-repo <dummy> --seed 1606
   --target 600 --test-command "<harness .venv python> -m pytest -q -p no:cacheprovider --junitxml=.l4-out/junit.xml -o
   pythonpath=src" --out canary.jsonl` (462 s): 1380 items, **exit 2** (quotas unmet, verbatim in the canary log).
3. The runner's `$L4_CACHE/s1-calibration.jsonl`, copied read-only (`mk-ssh.sh`, `sudo cat`; sha256 equal on both
   sides): 19 items, 38 answers, 1 label (`human:verdict`), 4 v1 lines.
4. `l4 s1 export --source canary.jsonl --source runner-s1-calibration.jsonl --seed 1607`. Seed 1606 was refused by
   the export itself (`l4/file-relevant@1: no test row with label false`); the rule was the first seed from 1606 whose
   export passes the export's own checks. No engine answer was read to choose it, and no other seed was scored.
   1239 rows: train 873, calib 195, test 147 (units 16 / 3 / 3). `laya-evals validate` 0.3.24 exits 0 for each split.
5. Shortcut check on the export, before training (`scripts/s1/evidence/shortcut_check.py`, run with the harness
   Python; the system `python3` is too old for its annotations).
6. `laya_tune.py train --base typed-decisions@7b928d828b7b0e022f929d9bd2e44165aa270148 --epochs 2 --micro-batch 1
   --grad-accum 16 --seed 1606 --device mps --out <run>/l4cache/s1/checkpoints/m16live-2026-10-05`, then
   `laya_tune.py gate --gate-policy scripts/s1/gates.json`.
7. `l4 s1 score --gate gate.json` for `laya`, `laya-tuned` (score-only path) and `jev` (`--max-requests 60`, key from
   Mintkey into the child environment only; `laya-serve` from `scripts/s1/.venv/bin` on `PATH`), then
   `l4 s1 report --gate gate.json --profile laya-tuned` and `scripts/s1/evidence/slices.py --real git-35b5a131ecf1
   --synthetic git-e13e7b2e670c`.

Not committed (source text of the repositories, raw engine answers, the weights); pinned by sha256:

| file | sha256 |
|---|---|
| `canary.jsonl` | `04734461d4416705b64aa63e42e3c031720494f23cc35415c4189dacc463da8a` |
| `runner-s1-calibration.jsonl` | `54dc64b6f39407a77912300f4be8239e250a2cf9a97bb91f0192ea4f4bc649fe` |
| `train.jsonl` | `41bb45313b2b2045ef00e1fa583f3600230e79bdebe37c7ff1ea2f749c0f5b88` |
| `calib.jsonl` | `5c16ea9c1829f6482c6fb4f4050e345a45ad2c29de136134bc7050c37e231f34` |
| `test.jsonl` | `ae31fe7faea073674d6a2604d66b01c5eb6a03d6f2560670d3e5506c9a804a78` |
| `scores-base.jsonl` | `5ddac570d9650cbf2835cbdaba52859083aa3028fff60455497dc373eb5a28fd` |
| `scores-tuned.jsonl` | `cd6943f1cee931d7d6c615650665e1590cab53faf8fa4842d8909e0da971dc95` |
| `scores-jev.jsonl` | `b5014987c01a4705d6658a5e4632c62244dc612a3792d23dc1579a7c4ac0beba` |
| `model.safetensors` (checkpoint `m16live-2026-10-05`, gate failed) | `12507d7eec8a69e3bb8541dc4d97720c926fd9b2047b65d0b7d68fa8ceff3acf` |

## How the 2026-10-07-tev1 addendum was made (harness m1.14, `engine: ollama`)

Inputs are the 2026-10-05-live files above, unchanged (`test.jsonl`, `gate.json`, the three `scores-*.jsonl`, sha256s as pinned there).

1. Profile (config `score-config.yaml`, nothing else in it): `ollama-tev1: {backend: system-one, engine: ollama, model: tev1, base_url: http://192.0.2.10:11434}`;
   Ollama 0.40.0 on the maintainer's MacBook, `tev1:latest`, the scoring ran on that Mac against its own LAN address.
2. `l4 s1 --config score-config.yaml --profile ollama-tev1 --dataset test.jsonl --gate gate.json --out scores-tev1.jsonl score`
   (about 3 minutes, 147 asked, 0 failed). `--gate gate.json` is the tuned Laya's FAILED live gate and is passed only
   because `score` refuses the test split without one; tev1 was never trained on any of this data. The "GATE FAILED"
   banner in the report is about the tuned checkpoint.
3. `l4 s1 --config score-config.yaml --dataset test.jsonl --gate gate.json --profile laya-tuned report scores-base.jsonl scores-tuned.jsonl scores-jev.jsonl scores-tev1.jsonl`
   -> `compare-2026-10-07-tev1.{md,json}` (the paths inside are rewritten to `<scratch>`).
4. `uv run python scripts/s1/evidence/slices.py test.jsonl laya=scores-base.jsonl tuned=scores-tuned.jsonl jev=scores-jev.jsonl tev1=scores-tev1.jsonl --real git-35b5a131ecf1 --synthetic git-e13e7b2e670c --json ...`
   -> `slices-2026-10-07-tev1.{md,json}` (the `common` section is the 60 rows Jev scored, the first 60 rows).

Not committed (raw engine answers); pinned by sha256:

| file | sha256 |
|---|---|
| `scores-tev1.jsonl` | `0a7849391048076effda473b52114619ca8c392a7d858272bf2bbc2aac8ceede` |

Result (accuracy / ECE / Brier, all 342 answers of the split; Jev on its 137 of the 60-row cap): base Laya 0.447 / 0.247 / 0.395,
tev1 0.681 / 0.262 / 0.317, Jev 0.708 / 0.224 / 0.269 (n-weighted ECE and Brier; per question in `compare-2026-10-07-tev1.md` and in
[free-resources.md](../free-resources.md) section 13). tev1 beats base Laya on accuracy for all 7 questions; its calibration is better on 4
questions and worse on the three change-covered ones. Latency per row, median / p90 / max: Laya 836 / 1204 / 1383 ms, tev1 1239 / 1649 /
4422 ms, Jev 262 / 326 / 413 ms (from the `latency_ms` of the score files; Laya and tev1 measured on the Mac, not on the runner).
The split has 3 units, so the intervals are optimistic. Decision: tev1 second in `s1_judge` (after Laya) and in `verifier.s1.shadow`, not first.
