# M1.6 progress (increment `m16`: Stage A evidence, Stage B S1 questions and data set)

Part M16-A is Stage A (lines 1-14). Part M16-B is Stage B (lines 15-30), after the Stage A table. Part M16-C is Stage C (lines 31-38,
the Laya tuning loop on the Mac), after the Stage B notes. Lines 39-40 (doctor, live protocol) are not in it.
Lines 39 and 40 were built after the join: 39 (doctor S1-001, S1-002, COV-001 in `l4/doctor/checks_s1.py`, all warnings,
fe6c876) and 40 (`tests/live/test_m1_6_acceptance.py`, c1fe046, 7d12c30; skipped unless `L4_LIVE=1`). Line 40 **ran live on
2026-10-05** against `example-group/dummy-agentic` (harness `641af1f`, live-fix `7c7d7c9`): jobs 5535 (P1), 5537 (P2, halted by
the red guard), 5539 (P1 again), 5541 (P2 again), 5543 (P3) and 5545 (cleanup), and with `L4_LIVE=1` the tests gave 8
passed and 2 skipped (the two P4 tests, which need a passed gate). Steps 1-4 and 7 passed, the step 4 gate failed and
steps 5-6 were not run (`docs/live/README.md`, M1.6).

| line | change task | status | commit | note |
|---|---|---|---|---|
| 1 | M16-G1 fixture `tests/fixtures/py_multi/` | done | 8a60038 | base commit plus 8 units (spec, red and green layers under `units/NN-name/`); `build_repo` in `tests/unit/evidence/_multi.py` writes `L4-Unit` trailers via the harness's own `Git.commit`. Tests pass at every unit head |
| 2 | verifier 2.11 part 1: `declared_scope` | done | d8c9363 | `l4/evidence/scope.py` |
| 3 | verifier 2.11 part 2: `module_of`, `classify_files` | done | d8c9363 | a spec that declares nothing labels nothing (deviation 2) |
| 4 | verifier 2.11 part 3: `check_scope` | done | d8c9363 | `sdd.scope_check` off, warn, fail through the real `aggregate_unit` |
| 5 | M16-G2 `l4_cov` plugin, `l4.gates.coverage` | done | 4c17c80 | integration with a real pytest subprocess; fail-soft cases tested |
| 6 | M16-G3 `diff_lines`, `changed_functions` | done | 7dc27c8 | `l4/evidence/diffcov.py` |
| 7 | verifier 3.11 reduced: `diff_coverage`, `check_diff_coverage` | done | 7dc27c8 | same module |
| 8 | verifier 1.8 delta: `check_tests_ran` | done | 4aea975 | `l4/evidence/testsran.py` |
| 9 | bootstrap-core 1.4 delta: config keys | done | 8a60038 | `verifier.evidence.*`, `verifier.s1.shadow`, `.max_items`; `sdd.scope_check` now has a reader (line 4) |
| 10 | M16-G4 `render_evidence_section`, `evidence_json` | done | 0f38663 | `l4/evidence/report.py` |
| 11 | M16-G5 `collect_evidence` | done | 96d123a | `tests/integration/test_evidence_flow.py`: four seeded heads give the expected labels, findings and holds |
| 12 | [J] `Workbench.run_gate(extra_env=)` | done | e91e314, 0556ef2 | `run_gate`/`run_gate_spec` merge `trace_env()` with the caller's env through `merge_pytest_env`; `run_test_gate(..., extra_env=)`; test: both plugins load in one real gate run; the bwrap argv shows the plugin readable and `.l4-out/cov` under the writable worktree bind (argv only: bwrap is not on this Mac) |
| 13 | [J] ladder steps 1, 3, 6 | done | e71a7c6 | step 1: `scope_evidence` after `run_integrity` (findings and holds join the round); step 3: `cov_env` into the unit gate, then `collect_evidence` (tests-ran findings join; a BLOCKER stops the ladder, no judge call); step 6 `quality`: diff-coverage findings and holds |
| 14 | [J] `VerifyResult.evidence`, report section | done | c546103 | Evidence section after Traceability, `round-N/evidence.json` (redacted, committed with the round), `verdict.json` key `evidence`, restored on a resume |
| 15 | M16-G6 `ask_typed`, `Answer`, `parse_typed` | done | 22b2c89 | `llm/system_one.py`, additive; Jev golden recorded from pipeline 2612; the Laya golden was recorded later from a real `laya-serve` (see Review fixes) |
| 16 | M16-G7 question sets, `expected_for` | done | f143746 | `l4/s1/questions.py`, four versioned sets, sha256 per set |
| 17 | M16-G8 state builders | done | 1d5246d (+83713fd) | `l4/s1/states.py`; `tests_state` later got a `problems` argument |
| 18 | verifier 4.3 + M16-G9 records | done | f143746 | `l4/s1/records.py`, `l4/s1-calibration@2`, v1 lines skipped and counted |
| 19 | M16-G10 `run_shadow`, `open_s1_profile` | done | 22b2c89, 1d5246d | engines one at a time; `l4/s1/shadow.py` |
| 20 | verifier 4.3 human outcome `labels_from_verdicts` | done | 1d5246d | `l4/s1/labels.py` |
| 21 | M16-G11 export guard | done | f143746 | `ground_truth_rows`, allow-list, byte-identical under random answers |
| 22 | M16-G11 `l4 s1 export` | done | f143746 + this commit | `laya-evals validate` passes for all three splits (verified, see Exit B) |
| 23 | M16-G12 canary mutations | done | 83713fd | `l4/s1/canary.py`, `l4/s1/mutations.py` |
| 24 | M16-G12 `l4 s1 canary` | partial | see Review fixes | the dummy-agentic clone is not on this machine; the quotas are still unmet and the command now exits 1 (`--allow-gaps` accepts) |
| 25 | M16-G13 `score`, `report` | done | this commit | `l4/s1/score.py`, `l4/s1/report.py`; live run with Jev passed |
| 26 | M16-G14 `audit` | done | this commit | `l4/s1/audit.py` |
| 27 | [X] CLI row and handler | done | this commit | `commands.py`, `cli.py`, `tests/unit/cli/test_dispatch.py` (see deviation 14) |
| 28 | [J] ladder step 8 shadow | done | e71a7c6 | `_shadow_step`: runs only when `verifier.s1.shadow` names profiles; items and answers go to `$L4_CACHE/s1-calibration.jsonl` and `.l4-out/s1/<run>.jsonl`; `evidence.json` `items` carries the item keys; any failure is logged and the round goes on |
| 29 | [J] human labels in `verify_hook` | done | f307fc0, a899fee | `l4/verifier/s1_labels.py`: for the verdicts `consume_verdicts` records in this call, the hold map comes from the `evidence.json` of the round that raised the question (`holds[].id`, `.subjects`, `items`); a scope hold gives `label{source: human:verdict}` (accept `relevant`, reject `out_of_scope`), a coverage hold none; labels go to `$L4_CACHE/s1-calibration.jsonl` and the job's `.l4-out/s1/<run>.jsonl`. Criterion verdicts get no label yet (criterion items are not in `evidence.json`). Tests: `test_ladder_evidence.py::test_reject_on_scope_hold_appends_out_of_scope_label`, `::test_accept_on_a_coverage_hold_gives_no_label` |
| 30 | [J] preflight rules | partial | 80f52b1 | only the `verifier.s1.shadow` rule (undefined name, or not a `backend: system-one` profile; exit 2). `diff_coverage.languages` is already a `Literal["python"]` in the schema. The System-One `model:` path rule (outside `$L4_CACHE/s1/checkpoints/`) is NOT built |

## Exit A

* `uv run pytest -q` and `uv run ruff check .` are green 
  The full suite: 1728 passed, 24 skipped. Note for anyone running it: started as `cmd &` inside a non-interactive
  shell, SIGINT is ignored by the job and its children, and `tests/unit/agents/test_proc.py::
  test_interrupt_sends_sigint_then_the_run_ends` then fails (3 of 3 such runs; green when the suite runs in the
  foreground or under the tool's own background mode) [verified by the green run].
* Line 11 shows the four results:
  * edit in another module: the file is `out_of_scope`; `warn` gives one hold, `fail` one major deterministic finding;
  * covering test deleted: `cart_total` is `uncovered`, 0 % of the changed executable lines ran (below the minimum),
    one hold naming the functions, and the red tests are missing from the report (blocker);
  * failing test: `tests_ok` is false and `new tests failed` is a blocker;
  * clean head: every file `relevant`, every function `covered`, `tests_ok` true, no finding, no hold.
* Plugin overhead: the harness's own tests with and without `-p l4_cov`
  (`source = src/l4`, a 340-test subset: config, specs, state, vcs, junit, runner, scope, testsran), three rounds each
  on a loaded shared machine: 34.9, 40.1, 39.7 s without; 43.4, 41.4, 41.8 s with. That is about 4 to 10 % more wall
  time, inside the noise of the machine. `status.json` said `ok` for the with-runs. The full suite was not run twice
  (11 to 13 minutes each under load). Children that tests start without clearing `PYTEST_ADDOPTS` load the plugin too,
  so the number is slightly pessimistic.

## Deviations from the plan

1. **`coverage` is a dev dependency** (`pyproject.toml`, `uv.lock`). The plan lists `pyproject.toml` as untouched, but
   the plugin tests need a coverage.py in the interpreter that stands in for the project's environment. The harness
   still has no runtime dependency on it, and the plugin imports whatever `coverage` the project interpreter sees.
2. **A spec that names nothing yields no file label** (D3 says `out_of_scope`). Otherwise a unit whose spec has no
   backticked path would put every changed file on hold. `ScopeOutcome.skipped` is true and the note says why.
3. **The coverage hold text names `path::qualname`**, not the bare qualname of C-M16-3: `<module>` and common names
   repeat across files. It stays number-free and sorted, so `hold_id` is stable.
4. **`check_tests_ran` also blocks on a failed new test.** D5 lists missing, skipped and errored; Exit A asks for a
   blocker on a failing test. The gate reports the same failure; the duplicate is intended.
5. **The coverage output is checked by sha256**, not by the JSON `meta.timestamp` (Risks section). The plugin records
   the sha256 and coverage version in `status.json`; `read_coverage` refuses a `coverage.json` that does not match.
   A repository that rewrites both files is still not stopped (the SC-03-class hole of the plan).
6. **Function status refinements** that the plan does not spell out:
   * a change confined to a function's signature or decorators is judged by whether the function was entered (its
     first real statement), because the `def` line runs at import;
   * a file absent from the coverage report is `unmeasured` (no label, outside the percentage) and a function with no
     executable changed line is `n/a`;
   * coverage contexts name the module as pytest imported it (`test_x.test_a`), not the JUnit classname
     (`tests.test_x`); `l4.gates.coverage.junit_ids` maps one to the other by dotted suffix.
7. **Signatures widened with keywords**: `changed_functions(path, text, lines)` (path first), `diff_lines(..., exclude=)`,
   `classify_files(..., unit_dir=)`, `declared_scope(..., roots=)`, `cov_env(out_dir, packages)`,
   `write_rc(out_dir, packages)`, `check_tests_ran(..., added_test_files=, gate_passed=)`,
   `collect_evidence(..., new_tests=, gate_passed=)`.
8. **`tests/unit/config/test_schema.py` was edited** (an existing module): the SPEC 3.2 oracle test now skips
   `verifier.evidence` and `verifier.s1.shadow` / `max_items`, which SPEC does not have yet (doc changes owed). Any
   branch that edits the same lines will conflict there.
9. **Line 11 does not use `NoSandbox`.** `build_gate_env` is an allow-list (`sandbox/env.py`): `PYTEST_ADDOPTS`,
   `PYTHONPATH` and `L4_COV_RC` do not survive it. The integration test therefore starts pytest directly with the
   environment. See the next section.

## Env passthrough (for the join, line 12)

* `build_gate_env` drops every host variable that is not on `ALLOWED_PASSTHROUGH`. Until m13's `extra=` reaches it
  (`run_gate(extra_env=)`, C13), `cov_env` cannot reach a gated test run: the env passthrough is **unproven**.
* The sandboxed run also has to see the plugin directory (`l4.gates.coverage.plugin_dir()`, inside the harness
  install) and be able to write `cov_dir`. Put `cov_dir` under the worktree (`.l4-out/cov`); check that the bwrap
  mounts expose the plugin directory (the same question m13 has for `l4_trace`).

## Interfaces later parts use

See the part report; all are importable from `l4.evidence.*` and `l4.gates.coverage`.

# Part M16-B (Stage B)

## Exit B (local)

* `uv run pytest -q`: 1783 passed, 25 skipped (8m39s); `uv run ruff check .` clean.
* `laya-evals validate` (laya 0.3.24, run with `uv run --isolated --no-project --python 3.12 --with laya==0.3.24`,
  torch not needed) passes for `train.jsonl` (239 examples), `calib.jsonl` (190) and `test.jsonl` (47) of the
  `py_multi` data set, and for a synthetic criterion data set with choice questions in both orders [verified].
* `l4 s1 canary --repo <py_multi> --seed 1606 --target 120` (8 units, 6 variants, 89 s on a loaded machine):
  **502 items** (file-relevant 185: 89 relevant, 96 out of scope; change-covered 285: 91 exercised, 194 not;
  tests-ok 32: 8 pass, 24 fail). Runs: none 8, transplant 48, template 48, drop-covering-test 48,
  untested-function 48, break-test 30 (18 not applicable: no new test with an integer equality). Every run kept; no
  checker disagreement on py_multi. Export: 476 rows after the 2:1 balance cut (26 cut): train 239, calib 190,
  test 47; units per split 4 / 3 / 1.
* **Quotas not met**: the test split holds one unit of eight, so (question, label) has 1-14 items in test, not 30,
  and tests-ok has 25 % pass items (< 30 %). The count (>= 500) holds. The quotas need more source units: the
  local clone of dummy-agentic is **not on this machine** (searched `~`), so the second half of Exit B is not run.
* `L4_LIVE=1`, Jev: `tests/unit/s1/test_score_live.py` scored 12 canary rows with Jev (key from Mintkey, never printed;
  12 requests, 0 failed) and `report` rendered. Run twice (24 requests in total, 12 each). Not run with the Mac's
  `laya-serve` (Laya is not installed on this machine; set `L4_LAYA_URL` to include it).
* The Laya golden reply (`tests/fixtures/recorded/system-one/laya-typed.json`) is **not recorded**; the typed-parse
  test checks it if the file appears.

## Deviations from the plan (Stage B)

10. **`--also-repo` instead of repeating `--repo`.** The global `--repo` is a single path; canary uses it as the first
    repository and `--also-repo P` (repeatable) adds more.
11. **Canary state feeds `tests-ok` with more than the counts**: the failing or skipped tests outside the new ones are
    listed too ("Not passed"), so that two different failing runs are two different items. Allowed by D6 (tests-ok is
    the stated sanity question).
12. **`export` projects only the questions the row has a label for** (a criterion row with `satisfied: false` asks no
    choice question), so `expected` and `questions` have the same keys. `laya-evals validate` passes either way.
13. **`item:<key>` and `set:<name>` tags** are added to every exported row (the audit needs the key to write a label).
14. **`tests/unit/cli/test_dispatch.py` was edited** (a shared test): `s1` is a command that SPEC 2.1 does not list,
    so the test now compares against `SECTION_2_1 | EXTRA` and has an `ARGV` entry.
15. **`score` refuses a data set without a matching `manifest.json`** (the order rule of D1: hashed before any engine
    scores it). `report` refuses answers scored on other bytes. `score_dataset`/`run_score` themselves take any rows.
16. **Archive-only units are not source units.** `find_source_units` needs an `L4-Unit` trailer range; a unit with
    only `openspec/changes/archive/*` has no base/head. Archived change directories of trailer units are found.
17. **Balance cap per split** (not over the whole set), by the class question of each set (the first noul/choice
    question); other questions of the set are its mirror or derived (`unrelated`, `extent`).
18. **Gate command**: the canary runs the project's `gates.test.command` (default `python -m pytest -q
    -p no:cacheprovider --junitxml=.l4-out/junit.xml` from the harness interpreter) as a plain argv subprocess with a
    short environment allow-list and `cov_env`, not through `NoSandbox`/`run_gate` (same reason as line 11). Repositories
    must be under `L4_S1_CANARY_ROOTS` (default `~/src`) or the command exits 2.
19. **Full suite not run before each intermediate commit of Stage B.** Targeted tests and `ruff check .` ran before each
    commit; the full suite ran before the last commit (below).

## Doc changes owed (Stage B)

* SPEC 3.2: `verifier.evidence.*`, `verifier.s1.shadow`, `verifier.s1.max_items` (already owed from Stage A).
* SPEC 2.1 (or the architecture's command list): the `l4 s1` command and its subcommands.
* A courtesy note for m15-progress: `src/l4/llm/system_one.py` gained `Answer`, `parse_typed`, `ask_typed` and
  `open_s1_profile` (additive; `ask`, `_probe` and `open_s1_backend` are unchanged).
* Plan line 22/24: the verify command `laya-evals validate` needs only `laya` (no torch) and works today.

# Part M16-C (Stage C: the Laya tuning loop on the Mac)

| line | change task | status | commit | note |
|---|---|---|---|---|
| 31 | M16-G15 `scripts/s1/` uv project, vendored script, `check_vendor.py` | done | c9dd33d | `uv sync` in `scripts/s1`: 27 s, `.venv` 869 MB (torch 2.14.1, transformers 5.18.0, laya 0.3.24); the harness deps are untouched |
| 32 | M16-G16 probe T1 | done | c9dd33d | `scripts/s1/probe_t1.sh`, log `docs/runner/probe-t1-2026-10-04.txt`; decisions below |
| 33 | M16-G17 `laya_tune.py build-items` | done | c9dd33d | pure helpers tested without torch (`test_tune_items.py`) |
| 34 | M16-G17 `laya_tune.py train` | done | c9dd33d | real run below; thresholds fitted, all null on this data (see caveats) |
| 35 | M16-G18 `laya_tune.py gate`, `gates.json` | done | c9dd33d | real gate run; `gate.passed` written into `l4-train.json` before any comparison |
| 36 | M16-G19 comparison, `report` refuses without `gate.json` | done | 33225f8 | `docs/s1/compare-2026-10-04.md`; cross-check against `gate.json` passed (tolerance 0.01) |
| 37 | M16-G20 checkpoint as a profile | done | 33225f8 | `l4/llm/s1_checkpoint.py` + a 6-line edit to `_probe` in `system_one.py`; served for real below |
| 38 | M16-G21 `deploy_checkpoint.sh` | partial | c9dd33d | `--dry-run` tested; the real copy through `mk-ssh.sh` is NOT run (it needs the runner, and `mk-ssh.sh` piping stdin to `tar -x` is unproven) |

## Probe T1 decisions (laya 0.3.24, `docs/runner/probe-t1-2026-10-04.txt`)

* (a) the vendored script imports under 0.3.24: yes. No T1-compat pin is needed.
* (b) `laya.load(<dir>)` loads a `max_len 1024` checkpoint saved by the script and answers (state 120 tokens): yes.
* (c) `LAYA_MODELS=<dir> laya-serve`: **no**, `unknown model`; it takes registry names only.
* (d) a private `HF_HOME` overlay whose `typed-decisions/` is the directory, `HF_HUB_OFFLINE=1`: **yes**.
  **T1-serve = overlay.** `l4 s1 score` ran for real against it (laya-local profile on the tuned checkpoint).
* (e) `laya-evals run --model <dir>`: **no**, same reason. **T1-eval = fallback**: `laya_tune.py gate` runs
  `laya.evals.evaluate` over `laya.load(dir)` with the same thresholds (`_check_thresholds`, `check_policy`).
* (f) a tiny training run (12 rows, 1 epoch): 45 s including the base load, 3.8 GB peak RSS, 807 MB checkpoint.

## The real run (Mac, M4 Max, MPS; canary data set from `py_multi`, seed 1606)

> **VOID.** These numbers came from states that leaked their label, a 200-row subset and a split that depended on the
> clock. They are kept as the history of the first run only. The committed `docs/s1/*-2026-10-04.*` files are now the
> round 2 re-run (below, "Review fixes, round 3"), which is itself not deployable.

* Data: `l4 s1 canary --target 120` gave 502 items; `l4 s1 export` gave 477 rows: train 313, calib 51, test 113 (units
  5 / 1 / 2). Label sources: `deterministic:diff-coverage` 268, `deterministic:scope` 185, `deterministic:tests-ran` 24.
  No engine output was read. The manifest check passed.
* Base: `typed-decisions` @ `7b928d828b7b0e022f929d9bd2e44165aa270148`. Tune: 2 epochs, 200 train rows (569 questions),
  micro-batch 1, grad-accum 16, final epoch. **591.7 s wall on a machine with load ~165**, peak RSS 5.9 GB.
* Refit on calib: temperatures `[choice 1.0, noul 10.0, score 10.0]`.

Before and after, on `test.jsonl` (113 rows, 2 source units never seen in training), against ground truth, from
`docs/s1/gate-2026-10-04.json` (laya-evals' own metric code):

| | base `typed-decisions` | tuned |
|---|---|---|
| noul accuracy | 0.491 | 0.950 |
| ECE | 0.0995 | 0.0545 |
| Brier | 0.258 | 0.051 |
| score MAE | 1.318 | 0.249 |

Gate (`--min-accuracy 0.85 --max-ece 0.10`, per-qid rules, gain over base of at least 0.05): **passed**. A first, smaller
run (40 rows, 1 epoch, 142 s) reached noul accuracy 0.777 and ECE 0.157 and **failed** the gate, so the gate does
discriminate. Three-way comparison with Jev (113 requests, one sample each): `docs/s1/compare-2026-10-04.md`, for
example `exercised` base 0.333, Jev 0.483, tuned 0.933; `relevant` base 0.894, Jev 1.000, tuned 1.000. Jev was only
scored. It is not read by `laya_tune.py` or by anything in the training path.

## What these numbers do not show (read before trusting them)

* **The test set is the same synthetic templates as the training set.** The split is by source unit (5 / 1 / 2 of
  8), but all of them come from `py_multi` and the five mutations. Training loss reached 0.0000 on several steps.
  0.95 is evidence that the loop trains and the gate runs, not that the model generalises to real units.
* Per-mutation slices have n of 2 to 12. The tuned model gets `exercised` 0.0 on `break_test` and `none` (n = 2 each).
* The noul and score temperatures sit at the upper clamp (10.0), fitted on 51 rows from one unit. The calibrated
  ECE on test is fine, but the refit is not trustworthy. All fitted thresholds are null: the largest calib question
  has 25 rows, and a 95 % Wilson lower bound of 0.95 needs about 70 correct answers in a row.
* `gates.json` has rules for `relevant`, `unrelated`, `exercised`, `untested` only. `all_passed` has 6 test rows and
  the criterion question none, so a `min_count` of 30 could never be met and would make every gate fail.
* The canary data has no choice questions, so the choice paths (`choice_accuracy` cross-check, averaged column) were
  exercised in unit tests only.
* The quotas of Exit B are still unmet (one more reason the above is a proof of the loop, not a quality claim).

## Exit C

* T1 recorded: yes. Checkpoint trained from an export of at least 500 items: the export has 477 rows (502 items
  before the balance cut), so this is **just under** the stated 500.
* `gate.json` written and the gate ran: yes. The first run's "passed" is void (see the banner above). The round 2
  re-run (export seed 1613, full train split) passed the round 2 gate but the current gate refuses it (shortcut
  slices), so **there is no checkpoint that passes today's gate**.
* Comparison with Wilson intervals for the three engines on the same split: yes.
* `deploy_checkpoint.sh --dry-run`: passes (golden output test).

## Deviations from the plan (Stage C)

20. **The vendored script's own `train()` is wrapped, not edited.** `calib_max=0` switches off its in-train split, and
    `laya_tune.py` refits temperatures on the exported `calib` split and fits thresholds from the checkpoint's own
    answers through `laya.load`. `checkpoint_latest` and the item cache are deleted after training (disk).
21. **Serving a checkpoint needs no change to `laya_env`**: `_probe` sets `HF_HOME` to an overlay under
    `$L4_CACHE/s1/overlays/<id>` and serves it as `typed-decisions`. A gate-failed, tampered, pickled or out-of-place
    checkpoint gives `RoleUnavailable` with the reason. "Any other path exits 2 at preflight" is a join line (30).
22. **`--gate` and `--profile` on `l4 s1 report`** (additive in `cli.py`): `--profile` names the tuned profile whose
    numbers are cross-checked. `build_report(..., gate=, tuned=)` refuses a tuned profile without `gate.json` and a
    `gate.json` from another test split. A failed gate still compares and says "Not deployable".
23. **Score questions are cross-checked on MAE** (`score_mae` in the report, new), noul and canonical choice on
    accuracy. The plan said "score" without naming a metric.
24. **The gate's `improves` rule compares noul accuracy** (the only type present in every data set).
25. **`probe_t1.sh` (e) and (c) are recorded as failures, which is the answer**; (f) also needs `BASE=typed-decisions@<rev>`.
26. `uv run ruff format --check` reports 35 files in `src` and `tests` that I did not touch; I only formatted my own files.

## Doc changes owed (Stage C)

* A SPEC section for `profiles.<p>.model` as a gated checkpoint path (D10), once preflight (line 30) enforces it.
* `docs/runner/README.md`: the runner needs `laya-serve` and the `convaiinnovations/laya` bundle only for the base;
  a tuned profile needs nothing else once the directory is copied.

## Review fixes (`m1.6(fix)`)

Findings of the A-B-C review, verified one by one, with the regression test that pins each. "Open" lists what code
cannot fix.

| finding | status | where | regression test |
|---|---|---|---|
| (c) branch does not merge with main | done | merge commit `abbcc1d`; dispatch list is main's minus what m15/main implemented, `verifier.evidence` joins main's `ADDED_BEYOND_SPEC` | the two conflicted test files, full suite |
| `l4_cov` clobbered by a child pytest | done | `gates/pytest_cov/l4_cov.py` drops `L4_COV_RC` and its `-p l4_cov` from the environment after start | `test_a_child_pytest_cannot_clobber_the_parents_measurement` |
| diff coverage failed open on unmeasured files | done | `include_namespace_packages`; an unmeasured function counts as not run in the percentage and is named in the hold | `test_changed_file_in_a_namespace_subpackage_is_not_silently_unmeasured`, `test_unmeasured_function_counts_in_fail_mode...` |
| control characters in paths reached the coverage rc and holds | done | `unsafe_path` in `evidence/collect.py` (skipped, hold `unsafe path name:`), `write_rc` refuses them and escapes `$` | `test_a_newline_in_a_path_cannot_rewrite_the_coverage_rc`, `test_write_rc_refuses_unsafe_package_names` |
| declared scope read at head | done | read at `base` | `test_declared_scope_is_read_at_base_not_at_head` |
| canary states leaked their label | done | neutral names from the file's own vocabulary (`mutations.py`), no marker lines, skip reasons varied; file states carry the spec's declared scope | `test_no_state_names_its_generator_or_its_label`, `test_file_states_carry_what_the_spec_declares` |
| gate did not cover the tests-ok sanity question | done | `sanity_failures` in `laya_tune.py gate`: tuned must be at least 0.85 and at least base on `all_passed`; none measured is a failure. `break_test` falls back to an erroring or skipped test when no literal can be flipped | `test_sanity_question_is_a_hard_gate`, `test_break_test_falls_back...` |
| gate / train did not check the data set | done | `check_dataset` (split files against the manifest), `check_gate_target` (checkpoint trained on this data set and these splits) before anything is scored or recorded | `test_check_dataset_...`, `test_gate_target_...` |
| temperatures outside Laya's range | done | train applies Laya's `TEMP_MIN`/`TEMP_MAX`, records raw, applied and on-bound; the gate fails on a bound fit and on a `--max-rows` subset | `test_temperatures_are_clamped...`, `test_train_record_failures_void_a_pass` |
| report order only enforced with `--profile` | done | `score` stamps `checkpoint_id` / `checkpoint_sha256` / `checkpoint_dataset_sha256`; `build_report` refuses such a file without a `gate.json` naming that checkpoint and data set, and cross-checks it | `test_a_checkpoint_stamped_score_file_cannot_be_reported_without_its_gate` |
| split key depended on the directory name; no shared item builder | done | `l4/s1/items.py`: `project_key` (root commit) and `items_from_evidence`, which the canary and join line 28 both call | `test_project_key_does_not_depend_on_the_directory_name` |
| shadow / score aborted on unexpected errors | done (b) partly rejected | any error opening, starting or asking an engine is recorded as data (the exception type only); `score` records any unexpected error and stops | `test_any_error_from_an_engine_...`, `test_an_unexpected_error_is_recorded_stops_the_run...` |
| `l4 s1 score` unknown profile exits 12 | done | exit 2 when the name is not a `backend: system-one` profile | `test_score_with_a_profile_that_is_not_system_one_is_a_usage_error` |
| Laya golden reply not recorded | done | `tests/fixtures/recorded/system-one/laya-typed.json` from a real `laya-serve` 0.3.24; the test fails when it is missing | `test_choice_and_score_parse_from_recorded_replies` |
| `l4 s1 canary` exits 0 with gaps | done | exit 1 unless `--allow-gaps`; the 500 target is counted after the class balance | `test_canary_exits_nonzero_when_the_quotas_are_not_met` |
| deploy script key and id validation | done | `profiles:`; id must match `[A-Za-z0-9._-]+` | `test_dry_run_plan_and_refuses_ungated` |
| checkpoint probe memory and races | done | chunked hashing, overlay named by the weights' sha256, built aside and renamed, reused when intact, unreadable files are a reason | `test_overlay_is_keyed_by_the_weights_and_repaired_when_broken`, `test_unreadable_weights_are_a_reason_not_a_crash` |
| CRLF files rewritten as LF | done | `write_preserving_newlines` | `test_a_crlf_file_stays_crlf_when_a_mutation_rewrites_it` |

### Open (code cannot close these)

* **Exit B/C data set**: there is still no dummy-agentic clone on this machine, so the second source repository and
  the test-split quotas (30 per class) are not met; the canary now says so with a non-zero exit. The data set has to
  be re-exported, the checkpoint re-trained on the **full** train split (no `--max-rows`) and re-gated before any Exit C
  number is quoted: the old numbers came from states that leaked their label and from a 200-row subset, and the old
  `l4-train.json` has no raw temperatures, so the new gate refuses it.
* `--max-requests` in `score`: each row is exactly one request and `asked` counts it before it is sent; the extra
  requests in the review's Jev run could not be reproduced from the code, so no change was made beyond stopping on
  any unexpected error.

### Exit A, plugin overhead on the full suite (after the child-process fix)

One round each, the whole suite (`src/l4` as the coverage source), on a shared machine at load average 11 to 16:
774 s without the plugin, 827 s with `-p l4_cov` (about 7 % more), `status.json` `ok`. The with-plugin run is the green
run of the merged tree: 2638 passed, 43 skipped, and `ruff check .` clean. Tests that start a pytest child no longer
clobber the plugin's output, so this number is not pessimistic any more. The without-plugin run came first and had the
three `test_generate` failures that the `ladder.py` fix removed (the main-side refactor of `require_independent_judge` had
dropped the `independence: none` early return; fixed in `ladder.py`, test `test_independence_none_does_not_look_the_judge_profile_up`) plus the known background-`SIGINT` case of
`test_interrupt_sends_sigint_then_the_run_ends`, which passes in the foreground and in the tool's own background mode.

## Review fixes, round 3 (`m1.6(fix)` and `m1.x(integrate)`)

Seed of the default split: `l4 s1 export` and `l4 s1 canary` use **1606** unless `--seed` is given, and the split is now
`assign_splits` (units ranked by sha256(seed:unit), cut 70/15/15 of their count, at least one unit in calib and in
test), so a fresh `py_multi` build (pinned commit dates, same root commit every time) gives the same split every time.
The round 2 re-run used seed 1613 (5 / 1 / 2 units under the old independent buckets); under the new assignment the 8
units split 6 / 1 / 1.

| finding | status | where | regression test |
|---|---|---|---|
| (c) no clean merge with main | done | `m1.x(integrate)` commit: main's `require_independent_judge(..., *, role=)` signature with the `independence: none` early return kept; merge of main clean; the only difference from main in `ladder.py` is the two-line early return | `test_independence_none_does_not_look_the_judge_profile_up`, full suite |
| Exit B quotas, second repo | **open, data** | no clone of `example-group/dummy-agentic` here; `l4 s1 canary` keeps failing until the quotas are met (now exit 2, not 1) | `test_canary_exits_nonzero_when_the_quotas_are_not_met` |
| empty split, split depended on the build time | done | `assign_splits` by rank; `write_dataset` raises `ExportError` (CLI exit 2, names the split or the missing label, writes nothing) unless `--allow-gaps`; fixture commit dates pinned | `test_splits_are_cut_by_rank...`, `test_an_empty_split_is_an_error...`, `test_a_split_without_one_label...`, `test_export_exits_2_naming_the_split...`, `test_the_fixture_history_does_not_depend_on_the_clock` |
| leftover coverage accepted | done | `write_rc` clears status, coverage and `.coverage*`; `cov_env` returns `L4_COV_NONCE` and records it in the directory; the plugin echoes it in `status.json`; `read_coverage(cov_dir, nonce)` returns `not_run` ("coverage was not written by this run") on a mismatch | `test_leftover_coverage_never_passes_for_this_runs`, `test_cov_env_clears_the_output_of_an_earlier_round` |
| added test file that collects nothing | done | `check_tests_ran` blocker "new test file ran no test" and `tests_ok` false; only added `.py` test files that define a test function are expected to collect (`conftest.py`, helpers are not) | `test_added_test_file_that_collected_nothing_is_a_blocker`, `test_defines_tests` |
| D1 order only for tuned checkpoints | done | `build_report` refuses the calib or test file of an `l4 s1 export` for every engine without a `--gate` whose `test_sha256` is that file; `l4 s1 score` refuses calib or test for any engine but `laya-local` the same way | `test_no_engine_is_reported_on_an_exported_calib_or_test_file_before_the_gate`, `test_a_hosted_engine_does_not_score_calib_or_test_before_the_gate` |
| gate passed a template shortcut | done (a, b); (c) via (a) | `shortcut_failures`: tuned accuracy below base on any `mutation:` or `origin:` slice (any n) fails, and every label of a noul or choice question must be recalled at 0.80. Not done: varying the canary templates. The recall rule alone does not catch the case (overall `exercised=true` recall is high); the slice rule does | `test_a_template_shortcut_is_caught_on_the_slice_it_fails` |
| Exit C artefacts void | done | `docs/s1/*-2026-10-04.*` replaced by the round 2 re-run, compare header says not deployable | none (documents) |
| `evidence.json` lacked holds and item keys; step 1 needed a test run | done | `Evidence.hold_records`, `evidence_json(holds=, items=)`, `items.item_keys_by_subject`, `collect.scope_evidence` | `test_evidence_json_carries_the_holds_and_item_keys_for_a_later_verdict`, `test_a_coverage_hold_names_the_functions_it_is_about` |
| `++ ` added line dropped later hunks | done | `diff_lines` takes `+++ ` as a header only between `diff --git` and the first hunk | `test_added_line_that_looks_like_a_file_header_does_not_drop_later_hunks` |
| empty scope passed silently under `fail`; bare name declared a module | done | one hold naming the changed modules; bare identifiers declare nothing (deviation from D3's wording: dotted or path tokens only) | `test_empty_scope_under_fail_holds_instead_of_passing_silently`, `test_a_bare_module_name_in_prose_does_not_declare_the_module` |
| `gate_passed` defaulted to true | done | required keyword in `check_tests_ran` and `collect_evidence` | all callers |
| `l4 s1` exit codes | partly | unmet quotas and unusable splits exit 2. **Doc change owed (not done, SPEC is not mine):** `l4 s1` in SPEC §2.1, and `verifier.evidence.*`, `verifier.s1.shadow`, `verifier.s1.max_items` in §3.2 | |
| `laya_tune.py gate` traceback on a missing file | done | `OSError` and JSON errors exit 2 with one line | `test_gate_with_a_missing_record_exits_2_with_one_line` |
| checkpoint integrity covered two files | done | `train` records every file; `checkpoint_problem` and `deploy_checkpoint.sh` verify all of them, refuse unrecorded files and symlinks, and copy exactly the recorded files; the gate fails when the directory changed after train or during the gate. **Old checkpoints with the two-file record are refused** | `test_ungated_or_tampered_checkpoint_is_unusable`, `test_dry_run_plan_and_refuses_ungated`, `test_checkpoint_files_cover_everything_and_drift_is_named` |
| gate weaknesses | done | `gate` fetches the base at the record's revision (`--base-dir` removed, `--cache` added); the 0.85 floor applies to `noul_accuracy` and `choice_accuracy`; `_cross_check` raises when it compared nothing | `test_the_accuracy_floor_applies_to_noul_and_choice_alike`, `test_a_cross_check_that_compared_nothing_is_not_ok` |
| `scripts/s1/.cache` in the repo | done | default `--cache` is `$L4_CACHE/s1/bases`; `.gitignore` also lists the old path | `test_default_cache_is_outside_the_repository` |
| `run_score`, `Evidence.section`, `to_json` untested | done | | `test_run_score_stamps_the_checkpoint_identity_into_the_header`, the evidence flow tests |
| non-atomic writes | done for the canary file, `manifest.json` and split files, `l4-train.json`, `gate.json`, `rl_agent_config.json`, `thresholds.json`, `status.json` | `os.replace` of a sibling temp file | `test_write_atomic_leaves_no_temp_file` |

### Exit B and C after round 3

* Exit B is **not met**: the data shortfall stands (one source repository of 8 units; the tests-ok pass class has few
  distinct states). More `py_multi` units or the dummy-agentic clone are needed, then re-run the canary.
* Exit C is **not met**: no checkpoint passes the current gate, and the old artefacts are labelled as such.

## Round 4 (`m1.6(fix)`): the split, and what changed

**M1.6 is split.** M1.6a = Stage A deterministic evidence (scope relevance, diff coverage, tests-ran) plus the ladder
join lines 12 to 14 (**not built now**: it is built after M1.5 lands on `main`). M1.6b = S1 shadow, export, canary and
Laya tuning. The deviations are in `m16-plan.md`, "Deviations, round 4".

**Merge hazard: `require_independent_judge` is touched by M1.2 (`main`), M1.3 (delegating stub), M1.5 and m16
`03eefe0` (the `independence == 'none'` early return, and `tests/unit/verifier/test_generate.py`). Resolve it once at
the M1.6a merge.** It was not touched in round 4.

| finding | part | status | where | regression test |
|---|---|---|---|---|
| root-level changed file counted as uncovered | M1.6a, major | done | `collect_evidence`, `DiffCoverage.unmeasured_files`; root files are unmeasured (deviation 1) | `tests/unit/evidence/test_root_files.py` |
| `file_of_test` exact match from the repo root | M1.6a, minor | done | `testsran.file_of_test` | `test_classname_resolves_under_a_pytest_rootdir_that_is_a_subdirectory` |
| a gate-FAILED checkpoint cannot be scored | M1.6b, blocker | done | `checkpoint_problem(require_passed=)`, `open_s1_profile(allow_failed_gate=)`, `CheckpointGateFailed` (exit 2), `gate_passed` in the header, `GATE FAILED` in the report | `tests/unit/s1/test_failed_gate_scoring.py`, `test_a_failed_gate_is_scorable_but_nothing_else_may_load_it`, `test_a_role_chain_skips...` |
| gate flag not bound to the gate document | M1.6b, minor | done | `record_gate` in `laya_tune.py`, `_gate_problem`, `deploy_checkpoint.sh` | `test_the_gate_flag_is_bound_to_the_gate_document`, `test_dry_run_plan_and_refuses_ungated` |
| `tests-ok` single-valued and quota-bound; empty splits | M1.6b, deviation | done | `quota_gaps`, mutations `add_passing_test` and `skip_old_test`, `write_dataset` | `test_tests_ok_is_a_sanity_question_exempt...`, `test_passing_run_variants_change_the_tests_ok_state_and_keep_it_true`, `test_an_empty_split_is_an_error_and_writes_nothing`, `test_export_exits_2_naming_the_split_when_a_split_is_unusable` |
| `cross-check ok` with nothing compared | M1.6b, minor | done | `report._cross_check` | `test_the_gate_cross_check_says_so_when_no_tuned_engine_was_compared` |
| `audit.py` imported scoring modules | M1.6b, minor | done | `l4/s1/stats.py` | `test_export_modules_never_import_score_or_report` (now covers `audit`, `stats`) |
| corrupt manifest was an internal error | M1.6b, minor | done | `score.read_manifest` | `test_a_corrupt_manifest_is_a_usage_error_for_score_and_report` |
| items read the worktree | M1.6b, minor | done | `items.items_from_evidence` uses `collect.show_blob` | `test_a_tampered_worktree_changes_no_state` |
| SPEC §2.1 `l4 s1`, §3.2 `verifier.evidence.*`, `verifier.s1.shadow`, `.max_items` | M1.6b, doc | done | `docs/SPEC.md` (the "Doc changes owed" entry for these is closed) | `check_spec.py` exit 0, `tests/unit/config/test_schema.py` |

Full suite after round 4 (tool background mode, shared machine): 3044 passed, 54 skipped, 1504 s; `ruff check .` clean.

### Open after round 4

* Old checkpoints (no `gate.document_sha256`) are refused everywhere: they have to be gated again. The Exit B/C data
  and re-training situation of round 3 is unchanged (no second source repository on this machine).
* No Jev request was made in round 4 (no scoring run was needed to test the code; the end-to-end test uses a stub
  engine).
* A record, a `gate.json` and its digest rewritten together cannot be told from the original without a signature.
* Flat-layout root modules are not measured by diff coverage (deviation 1).

## M1.6b evidence on real data (2026-10-05)

Records: `docs/s1/*-2026-10-05.*` and `docs/s1/README.md` (how they were made, the project-key map, sha256s of the
files that are not committed). The 2026-10-04 records are marked VOID. Code changed for this run (test-first, commit
`13427c7`): the canary reads source units from every local branch, and items carry `project:<key>`, which the report
slices on (plan "Deviations, round 5").

### Data

* **Source repositories.** `example-group/dummy-agentic`, cloned read-only (SSH, the operator's key, as the live runs of
  M1.2 to M1.4 did: the Mintkey `example-gitlab` service is the REST API only, used here to list the MRs). One local
  branch per open MR head. Units found: 8 real (`add-discount-codes` !1, `add-average-price` !4, `add-vat` !5,
  `add-is-empty` !8, `add-money-format` !10, `add-split-amount` !12, `add-shipping-fee` !15 and its fix unit
  `add-shipping-fee-fix-1`); `add-loyalty-points` !13 is a Kiro unit (no `openspec/changes` directory), not a source
  unit. Plus a fresh `py_multi` (8 synthetic units).
* **Canary** (`--seed 1606 --target 500`, 349 s): **1198 items**, real 494, synthetic 704. Exit **2**: quotas not met.
  * file-relevant: real 133 true, **0 false**; synthetic 190 true, 108 false. change-covered: real 140 true, 52 false;
    synthetic 177 true, 175 false. tests-ok: real 75 true, 26 false; synthetic 92 true, 30 false.
  * gaps, verbatim: `file-relevant@1/relevant=false: share 25% below 30%`; `relevant=false: 11 in the test split, 30
    wanted`; `change-covered@1/exercised=true: 25 in the test split, 30 wanted`. The row target is met (1036 rows after
    the balance cut). Why the quotas fail: dummy-agentic is one package (`src/pricing`), every spec names it, so no
    file of it is out of scope and `template_edit`/`transplant_hunk` are not applicable to any real unit (42 runs
    each); every `relevant=false` row is synthetic. The test split holds two units, so 30 per class is out of reach.
  * `add-shipping-fee` gave no items: its untouched baseline was dropped as `checker_disagreement` (Stage A finding 2
    below), so all 48 of its runs are `baseline_failed`.
* **Export** (`--seed 1606`): **1036 rows** (balance cut 162): train 800 (11 units), calib 135 (2), test 101 (2).
  Label sources: `deterministic:diff-coverage` 544, `deterministic:scope` 324, `deterministic:tests-ran` 168, nothing
  else. `laya-evals validate` (0.3.24) exits 0 for each split (800, 135, 101 examples, 7 question ids).

| split | real rows (units) | synthetic rows (units) | relevant t/f | exercised t/f | all_passed t/f |
|---|---|---|---|---|---|
| train | 293 (add-discount-codes, add-money-format, add-split-amount, add-average-price, add-shipping-fee-fix-1) | 507 (6) | 162 / 81 | 269 / 162 | 84 / 42 |
| calib | 43 (add-vat) | 92 (shipping-rates) | 32 / 16 | 23 / 34 | 20 / 10 |
| test | 22 (add-is-empty) | 79 (cart-totals) | 22 / 11 | 25 / 31 | 8 / 4 |

In test, the real rows are: relevant 10 true, 0 false; exercised 1 true, 7 false; all_passed 4 true.

### Shortcut check, before training (`docs/s1/shortcuts-2026-10-05.json`)

Single-token stump per question, the token chosen on train, scored on test (state text only):

| question | best token | train acc | test acc | test majority |
|---|---|---|---|---|
| exercised / untested / extent | `int` | 0.821 | 0.839 | 0.446 |
| relatedness | `value` | 0.777 | 0.895 (n=19) | 0.579 |
| relevant / unrelated | `,` (`from` by balanced accuracy) | 0.798 | 0.818 | 0.667 |
| all_passed | `error` | 0.794 | 0.667 | 0.667 |

No single token reaches 0.9 (the in-sample maximum over all three splits is 0.833), so the rule did not stop training.
The rule was applied to the training set as a whole. Inside one sub-slice a token does reach it: on the real rows
alone, `__init__` decides `relatedness` (1.0 on train, n=16; 1.0 on test, n=4). That reflects the labeller's `named`
rule (`__init__.py` is relevant by module, never named in a spec; the declared scope is in the state), and
`relatedness` is a score question outside the gate policy.
`int` and `value` are generator words: `add_untested_function` writes `def <name>(value: int) -> int`. A bag-of-words
logistic regression (unigrams and bigrams, train to test) reaches 0.970 on `relevant` (path tokens such as `shop`,
`inventory`), 0.839 on `exercised` (its strongest "no" features are `int`, `value int`, `int return`) and 1.0 on
`all_passed` (the sanity question states its answer).

### Train, gate, score

* Train: full train split, 2035 items, 2 epochs, `typed-decisions@7b928d82`, MPS, **2263 s**, peak RSS 7.87 GB.
  Raw temperatures `[1.0, 6.23, 7.04]`, applied `[1.0, 5.0, 5.0]` (noul and score on Laya's clamp). All fitted
  thresholds null.
* laya-evals on `test.jsonl` (101 rows, `gate-2026-10-05.json`), base to tuned:

| metric | base Laya | tuned |
|---|---|---|
| noul accuracy | 0.574 | 0.884 |
| score MAE | 1.363 | 0.435 |
| ECE | 0.149 | 0.096 |
| Brier | 0.242 | 0.111 |
| AURC | 0.387 | 0.074 |
| mean confidence | 0.516 | 0.970 |

* **Gate: FAILED**, 11 failures (the slice and recall rules fire once per mirrored question): policy rules 3 and 4
  (`exercised`, `untested` 0.839 < 0.85, n=56) = 2; the slice rule on `mutation:add_passing_test` (`exercised`,
  `untested` 0.50 vs base 1.00, n=12) = 2, on `mutation:none` (`exercised`, `untested` 0.33 vs 1.00, n=3) = 2 and on
  `mutation:skip_old_test` (`unrelated` 0.67 vs 0.83, n=6) = 1; label recall (`exercised=true`, `untested=false` 0.68,
  n=25) = 2; temperatures 1 and 2 on the clamp = 2.
* Scored: base Laya 101 rows, tuned (score-only path, header `gate_passed: false`) 101 rows, Jev (`jev-1.13.0`)
  **60 requests**, 0 failed, 41 not asked. No other Jev request was made; the key went from Mintkey into the child
  environment only.

Accuracy per question (`docs/s1/slices-2026-10-05.md`; "common" = the 60 rows all three scored):

| question | base all (n) | tuned all (n) | base common | tuned common | Jev common (n) |
|---|---|---|---|---|---|
| exercised | 0.446 (56) | 0.839 (56) | 0.417 | 0.861 | 0.556 (36) |
| untested | 0.375 (56) | 0.839 (56) | 0.361 | 0.861 | 0.556 (36) |
| extent | 0.125 (56) | 0.839 (56) | 0.083 | 0.861 | 0.556 (36) |
| relevant | 0.939 (33) | 0.939 (33) | 0.944 | 0.944 | 1.000 (18) |
| unrelated | 0.667 (33) | 0.939 (33) | 0.667 | 0.944 | 1.000 (18) |
| relatedness | 0.421 (19) | 1.000 (19) | 0.400 | 1.000 | 1.000 (10) |
| all_passed | 0.833 (12) | 1.000 (12) | 0.667 | 1.000 | 0.500 (6) |

Real (dummy-agentic) and synthetic (`py_multi`) rows apart, all scored rows (Jev: of its 60):

| question | real base | real tuned | real Jev | synthetic base | synthetic tuned | synthetic Jev |
|---|---|---|---|---|---|---|
| exercised | 0.125 (8) | 0.875 (8) | 1.000 (4) | 0.500 (48) | 0.833 (48) | 0.500 (32) |
| relevant | 1.000 (10) | 1.000 (10) | 1.000 (6) | 0.913 (23) | 0.913 (23) | 1.000 (12) |
| unrelated | 1.000 (10) | 1.000 (10) | 1.000 (6) | 0.522 (23) | 0.913 (23) | 1.000 (12) |
| all_passed | 1.000 (4) | 1.000 (4) | 0.000 (1) | 0.750 (8) | 1.000 (8) | 0.600 (5) |

Untouched (`mutation:none`) `exercised`: real base 1/1, tuned 0/1, Jev 1/1; synthetic base 2/2, tuned 1/2, Jev 1/1.

### Findings

1. **Same failure signature as the VOID run.** Tuned is right on every template (`untested_function` 12/12,
   `template_edit` 6/6, `transplant_hunk` 18/19) and wrong on functions that ran: `add_passing_test` 6/12 wrong,
   untouched functions 2/3 wrong; 8 of its 9 `exercised` errors are false "no". The temperature refit on calib went
   above the clamp (overconfident on unseen units). The accuracy gain is template learning.
2. **Stage A defect on real data (M1.6a, open, not fixed here).** The range of `add-shipping-fee` (!15) contains its
   fix unit's change directory; `openspec/changes/add-shipping-fee-fix-1/.l4/fix.json` and `.../.openspec.yaml` are
   classified as `code` and labelled `out_of_scope` (`HARNESS_PATHS` `.l4/**` matches at the root only, and another
   change directory's non-Markdown files are not exempt). The canary dropped the unit as `checker_disagreement`; a live
   verification of `add-shipping-fee` would put a scope hold on these two harness files.
3. **Generator words** (`int`, `value`) are the strongest single tokens (above). On real data the tuned model's 7/7 on
   mutated `exercised` rows are 6 `untested_function` templates and one dropped test.
4. **The real slice cannot test file relevance**: no `relevant=false` row exists in dummy-agentic (one package).
5. **`skip_old_test` label vs question (open).** The state says `1 skipped` and lists it under "Not passed"; the
   question is "Did every test of the run pass?"; the label is `all_passed=true` (a skipped old test does not fail the
   run). Jev answers no (0/3 on that slice, so 0.50 on the sanity question); tuned Laya learned the convention. The
   question wording or the label rule has to change before `sanity_failures` can be trusted on this mutation.
6. Base Laya answers `exercised=yes` almost always (0/16 on synthetic transplants, 0/12 on untested functions) and
   puts p between 0.43 and 0.64 on every tests-ok row: it is near-uninformative on these questions.

### Exit B and C after this run

* Exit B: the 500 count is met (1036 rows, two source repositories, one real), `laya-evals validate` passes; the
  quotas are **not** met (numbers above) and `l4 s1 canary` exits 2 for it. More real units in more than one package
  are needed for `relevant=false` on real data; more units for 30 per class in test.
* Exit C: the gate ran and **failed**; there is no deployable checkpoint. Comparison with Wilson intervals for three
  engines on the same split: done (`compare-2026-10-05.md`), Jev on 60 of 101 rows.

Full suite at `13427c7` + these records (tool background mode, shared machine): **3048 passed, 54 skipped**, 1338 s;
`ruff check .` clean. Nothing pushed; the dummy-agentic clone is read-only (push URL `/nonexistent/read-only`).

## Round 5 (`m1.6(fix)`): findings of the round 4 review

| finding | part | status | where | regression test |
|---|---|---|---|---|
| A-B1 harness and change-directory files classed as code | M1.6a, blocker | done | `scope.HARNESS_PATHS` are `**/.l4/**`, `**/.l4-out/**`; `SPEC_PATHS` (`openspec/changes/**`, `.kiro/specs/**`) are `exempt` | `test_scope.py`: `test_harness_and_spec_files_in_any_change_directory_are_exempt` (the real paths of !15, from both units' ranges), `..._at_any_depth_...` |
| A-M1 `file_of_test` suffix-matched changed files only | M1.6a, major | done | `testsran.file_of_test(id, candidates, tree)`: the exact path in the head tree wins (and counts only if it is a candidate); else the one tree file ending in `/<module path>`; ambiguous gives nothing; only capitalised trailing parts are dropped as classes (`tests.test_x` is never `tests.py`). `collect_evidence` and the canary pass the head tree. | `test_testsran.py`: scenario H, the empty added file, `tests.test_x` vs `foo/tests/tests.py` |
| B-M1 `skip_old_test` labelled tests-ok TRUE | M1.6b, major | done | `TestsRanOutcome.all_passed` (label and no skipped test in the run), `labels["all_passed"]`, the S1 item truth and the canary intent use it; `skip_old_test` is negative; question set `l4/tests-ok@2` (criteria text names skipped). Stage A `tests_ok` (verdict, `verification.md`) is unchanged. | `test_all_passed_is_the_literal_question...`, `test_passing_and_skipping_variants_...`, `test_tests_ok_question_is_version_two...` |
| canary `def x(value: int) -> int` template | M1.6b, shortcut | done | `mutations.add_untested_function` copies the signature of one of the file's own functions, else draws names from its vocabulary and types from a seeded list; the body varies | `test_mutations.py`: `test_no_fixed_token_marks_...`, `..._drawn_from_the_files_own_functions` |
| coverage sources relative to the cwd | M1.6a, minor | documented | `m16-plan.md` (join lines 12 to 14 note), `cov_env` docstring. Not made absolute: it is not a one-line change (`relative_files`, path matching in `read_coverage`) and was not verified. | none |

* Real range check (read-only, `scope_evidence` on the dummy-agentic clone, range `8ff4f030..390aa7ea`): no holds and no
  findings for `add-shipping-fee-fix-1` and for `add-shipping-fee`; every `.l4/` file and `.openspec.yaml` is `exempt`.
* Effect on the 2026-10-05 data: `tests-ok@1` rows and records of that run are `tests-ok@1`; they are not comparable with
  `@2` (a skipped old test is now `false`). Finding 5 of the evidence run (skip_old_test label vs question) is closed
  by the label rule; the data has to be regenerated to carry it. The `untested_function` rows of that run keep the old
  `value: int` signature: regenerate before re-training.
* Quotas: `tests-ok` stays a sanity question exempt from share and test quotas (`quota_gaps`); `skip_old_test` adds
  false rows there, `balanced_count` is unchanged.
* Full suite (tool background mode, shared machine): **3068 passed, 54 skipped**, 1393 s; `ruff check .` clean.
* No Jev request was made. Nothing pushed.

## Round 5b (`m1.6(fix)`): scope of a fix unit (review round 5)

| finding | part | status | where | regression test |
|---|---|---|---|---|
| a harness-written fix unit declares no scope (its Impact line is "The code and the tests of `<parent>`.") | M1.6a | done | `scope.unit_declared_scope(read, unit_rel, tree, roots)`: when `<unit>/.l4/fix.json` is a valid `l4/fix-unit@1` marker the unit's scope is the union of its own and its parent's (the sibling folder `<parent>` from the `<parent>-fix-<n>` name), both read at the base. `collect.scope_evidence` and the canary's `_scope` use it. A parent never reads its fix units; a missing or invalid marker, or a parent that declares nothing, leaves the old behaviour (skipped under warn, "declares no path or module" hold under fail). | `test_scope.py`: `test_a_fix_unit_that_names_nothing_inherits_...`, `..._own_scope_is_kept_with_the_parents`, `test_a_parent_never_inherits_...`, `..._parent_that_declares_nothing_is_skipped_as_before`, `test_without_a_valid_marker_...` |

* Docs: `m16-plan.md` now says `tests-ok@2` and the round-5 rule (any skipped, failed or errored test makes
  `all_passed` false; `skip_old_test` is a negative variant).
* Nothing pushed.


# Join pass (merge of main `f48b82e`, lines 12-14 and 28)

* Merge `81b9f81`. Conflicts: `docs/SPEC.md` and `config/schema.py` (both sides added S1 keys: kept `shadow`, `max_items`
  next to main's `decisions`, plus `evidence`), `tests/unit/verifier/test_generate.py` (took main's).
  `require_independent_judge`: main's version kept, m16's `independence == "none"` early return and its test dropped
  (nothing on main needs it; the function has no caller in `src`, only `test_independence.py`).
* Integration tests: `tests/unit/verifier/test_ladder_evidence.py` (real `l4 run` on `py_multi`: (i) other-module edit,
  hold + verdict question under `warn`, deterministic major under `fail`; (ii) untested added function: `uncovered`,
  hold / major; (iii) a new test skipped in the verifier's run: FAIL, no judge call; (iv) clean: PASS, Evidence green) and
  `test_ladder_evidence_more.py` (env passed to the gate, sandbox argv, section rebuilt from `verdict.json`, shadow rows
  with answers 0 and 1 give the same verdict, (v)).

## Deviations of the join

1. **(v) is not run through `l4 run`.** The planner never verifies a fix unit alone (after a merge it is skipped) and in a
   family run the ref is the parent, so the inherited scope never matters there. (v) runs the ladder's `_scope_step` on a
   real git history whose base holds the parent and a fix unit that names nothing.
2. **(iii) needs a skip the verifier sees and the implementer's gates do not.** The implementer's green gate requires the red
   tests to pass, and step 1's integrity scan rejects a literal skip marker, so a skipped new test cannot arise in the
   simple way. The test skips when the coverage plugin is loaded (`"l4_cov" in sys.modules`) and builds the call as
   `getattr(pytest, "sk" + "ip")`.
3. **The e2e gate's report is merged into the tests-ran check.** Found by `test_memory_flow`: round 2 saw the generated
   Playwright file (`e2e/test_l4_*.py`) as "a new test file that ran no test", because the unit gate does not run it.
4. **`collect_evidence` runs inside step 3, step 6 only reports.** Reading coverage needs the report and the plugin output
   from step 3; step 6 moves the coverage findings and holds into the round. With `diff_coverage.mode: off` step 6 is
   `not_run` and the gate gets no coverage env.
5. **`tests/unit/conftest.py` `TddRepo.config` sets `diff_coverage.mode: off`.** The legacy lifecycle tests use one-scenario
   units whose second branch no test runs, which is now a (correct) diff-coverage hold that adds a second verdict question.
   They test verdict re-entry, not evidence; the evidence tests use `py_multi` with coverage on.
6. **Lines 29 (human labels in `verify_hook`) and 30 (preflight rules) are not built.** `evidence.json` already carries the
   `holds` and `items` that line 29 needs.
7. **Test-first was partial.** The `run_gate(extra_env=)` and ladder tests were written before the code but not run red
   (the suite is 10 to 16 minutes per chunk on this loaded Mac). The first full chunk run after the build had 11 legacy
   failures, each traced: 1 real defect (item 3), 8 caused by the new default evidence checks on one-scenario `py_tdd` units
   (item 5), 2 were the step `"6"` row in exact-dict asserts (gone with item 5, since a `not_run` row emits no event).

## Exit (join, local)

Run in five chunks, one after another, `collected == passed + skipped` in each: 469 = 464 + 5; 912 = 909 + 3;
485 = 483 + 2; 1438 = 1434 + 4; 105 = 52 + 53. Total 3342 passed, 67 skipped, 0 failed. `uv run ruff check .` clean;
`python3 scripts/check_spec.py docs/SPEC.md` exit 0. `ruff format --check` was not made clean for the repository (existing
debt, parallel-ownership §7).
8. **Coverage under the real sandbox is unproven here:** bwrap is Linux-only. The runs use `sandbox.mode: none`; the argv
   test shows the mounts.

# Join review (adversarial, 2026-10-05)

Every gaming attempt ran through `l4 run` on `py_multi` (real git, real pytest with `l4_cov` loaded by the gate, a scripted
agent) next to an added function `describe` that no test runs. Regression tests: `tests/unit/verifier/
test_ladder_evidence_gaming.py`, `test_integrity_harness_plugins.py`, `tests/unit/gates/test_l4_cov.py`,
`test_ladder_evidence_more.py`.

| attempt | before the review | after |
|---|---|---|
| conftest from red rewrites `coverage.json`/`status.json` at exit (nonce read from `.l4-out/cov/nonce`) | `covered`, PASS | step 1 blocker (names `.l4-out/cov`) |
| the same in production code (`src/shop/cart.py`) | `covered`, PASS | step 1 blocker |
| the same conftest written in green | removed by the green guard: `uncovered`, hold | unchanged |
| root `l4_cov.py` (shadows the plugin) | `covered` and PASS when it forges, `not_run` and PASS when empty | step 1 blocker (a module named l4_cov; also `l4_trace/__init__.py`, `.so`) |
| root `coverage.py`, `coverage/`, `src/coverage/` (shadow coverage.py; names nothing of the harness) | `covered`, PASS | `l4_cov` imports only the installed coverage.py; step 1 blocker for a top-level `coverage` |
| conftest unregisters `l4_cov` by name | `not_run`, PASS | step 1 blocker |
| the same with the name built at run time | `not_run`, PASS | unchanged (D4): `warn` PASS, now listed under Needs attention; `fail` hold |
| `pytest.ini` / pyproject `addopts = -p no:l4_cov` | step 1 blocker | unchanged |
| `pytest.toml` `addopts = ["-p", "tools.x"]` (pytest 9) | not scanned, not frozen | step 1 blocker; `pytest.toml`, `.pytest.toml`, `.pytest.ini` are runner config (SPEC 3.2) |
| `# pragma: no cover` on `describe` | `uncovered`, hold | unchanged |
| `.l4-out` or `.l4-out/cov` a symlink out of the checkout | host-side `rmtree(<target>/cov)` (even with coverage off); rc, nonce and data written there | refused before any write: `not_run` with the reason |

Fix commits: `0d3994a` (Needs attention line), `00817e2` (plugin names, coverage-output names, pytest 9 config files),
`6a5f7ec` (symlinked coverage directory), `166ec2b` (a repository `coverage` module). Test-only: `6d8eb51` (shadow
answers flipped on held and failing units).

Checked, no change needed: `build_gate_env` passes no host secret and drops the host's `PYTEST_ADDOPTS`, `PYTHONPATH`,
`L4_COV_*` and `COVERAGE_*` (the proxy variables are on main's allow-list and may carry `user:pass@`); S1 shadow answers
all 0 or all 1 give the same code, verdict and hold ids on a PASS, a scope hold, a coverage hold and a FAIL;
`require_independent_judge` (main's) keeps `test_independence.py` and `test_generate.py` green; with
`diff_coverage.mode: warn` in `TddRepo` (deviation 5) the 7 lifecycle tests that break all use `red_known_only` (the
second branch is untested: an extra coverage hold and verdict question), and an accepted coverage hold lets the unit
PASS on re-entry; the fix-loop tests that replace `verifier` (`with_verifier`) already run round 2 with coverage on.

Residual risks (not fixed):
* In-process forgery that never names the plugin, its directory or a `coverage` module still passes: a conftest from red
  that patches `coverage.Coverage.json_report` gave `covered` and PASS (probe), and so does a name built at run time
  (`xfail(strict=True)` test). This is the SC-03-class hole of the Risks section; the scans narrow it.
* Under the default `warn`, coverage that is `not_run` (plugin unregistered, xdist, tox) is no hold (D4). Owner decision.
* Untested logic in a scope-exempt path (`docs/helpers.py`) or in a production file whose name matches a test glob
  (`src/shop/describe_test.py`), imported by production code, is outside diff coverage and scope: PASS (probe).
* `main` has moved to `319eb14` (M1.7): `git merge --no-commit --no-ff main` conflicts only in `src/l4/verifier/ladder.py`,
  two hunks where both sides add a `VerifyContext` field (`shadow` / `base_note`) and its `verify_hook` argument.

Exit (review, local, at `166ec2b`): five chunks one after another, 464 + 5 skipped; 962 + 3 skipped + 1 xfailed; 483 + 2
skipped; 1435 + 4 skipped; 52 + 53 skipped. Total 3396 passed, 67 skipped, 1 xfailed (the residual above), 0 failed.
`uv run ruff check .` clean; `scripts/check_spec.py docs/SPEC.md` exit 0. Nothing pushed.

# Landing follow-ups (after `ed8084f`)

* Canary and base merges (found at landing, parallel-ownership §7) fixed in `adabd0b`: `find_source_units` takes the
  unit's base as `merge-base(head, base as merged)` when a `chore(<unit>): merge <base>@<sha> into the unit branch`
  commit with two parents is in its history (the latest one counts), so what main brought in is no item. Test:
  `tests/unit/s1/test_canary_base_merge.py` (a real repository; it fails without the fix).
* Join lines 29, 30 (shadow rule only), 39 and 40: see the table above.
* The M1.7 live run's `.serena/project.yml` guard violation: `l4 init` and `l4 upgrade` now seed the file; the live
  cause was not reproduced (docs/live/README.md, M1.7 deviations).
* Review of the follow-ups (after `e5fa777`): line 29's label is written right after `consume_verdicts` (`178f3ca`).
  Written after the judge was selected, it was lost for good when the round then ended without a judge (exit 12): the
  answer is consumed once. Tests: `test_ladder_evidence.py::test_the_label_is_written_even_when_no_judge_is_left_for_the_round`
  (failed before the move), `::test_a_forged_hold_question_the_harness_never_raised_gives_no_label` and
  `test_s1_labels.py` (a label comes only from a verdict recorded in the same call; no commit-author check exists, the
  trust is the protected `questions.md` and the ledger's `question.raised`). The merge-log entry of `319eb14` now
  names its two conflicts, and L4-VER-011 says what the code does with a merge commit (`a283c25`). The Serena write race
  is in Serena 1.7.0's source; its order on the runner is still inferred (`1957727`).
