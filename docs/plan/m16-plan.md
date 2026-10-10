# M1.6 — change evidence (scope, diff coverage, tests ran) and tuning Laya on ground truth (planned 2026-10-04)

## Goal

M1.6 answers three questions about every unit with **deterministic evidence** before a PASS:

1. **Scope.** Does each changed file belong to the feature, or did the unit change another module that the spec does
   not name?
2. **Diff coverage.** Is each changed function run by the tests?
3. **Tests ran.** Did the test run pass, with no new test skipped, errored or missing?

The answers are findings in `verification.md` and **ground-truth labels**. With them M1.6 builds a labelled data set
and tunes Laya (the local System-One model) on it on the maintainer's Mac. Jev (TypeSafe's hosted System One) answers
the same questions in **shadow mode only**. It is scored against the same ground truth and is never a label, a
selection signal or a model to imitate (§"The Jev constraint").

User request (2026-10-04): "set up tuning Laya using Jev — make sure to also cover issues like: are the file changes
relevant for the feature (e.g. changing files in another module), are the changes covered by tests, did the tests run
successfully?" Under the constraint below, "using Jev" means **Jev as a scored comparison engine**, not as a teacher.

## The Jev constraint (hard, contractual)

TypeSafe's Master Customer Agreement §2.3(b) forbids using the Services or any Output "to perform model distillation,
train a model to imitate the output of the Services, or develop … a similar or competing product or service" [V,
`docs/eval-framework.md` §6.6a, read 2026-10-04]. In M1.6 this means:

* **Allowed:** Jev answers the harness's questions at inference time, in shadow mode. Its answers are scored against
  the same ground truth as Laya's, and the score appears in a comparison report.
* **Never:** a Jev answer as a training label; as a checkpoint- or epoch-selection signal; as a data-selection signal
  (for example "keep the rows Jev gets wrong"); as a calibration target; or as a gate input. The same rule covers the
  output of the LLM judges (Claude, Codex), whose terms may restrict training use as well (eval-framework §6.6a).
* **Enforced in code, not by convention** (D1):
  * three record kinds, `item`, `answer` and `label`;
  * the exporter never opens an `answer` record;
  * an allow-list of label sources, with a test showing that a row whose label source is an S1 engine is rejected;
  * a metamorphic test: changing every engine `p` leaves the export byte-identical;
  * an enforced order: the data set is hashed before any engine scores it, and the gate is recorded before any
    comparison runs.

## Scope

* **Stage A: deterministic evidence (ground truth).**
  * A **scope check** per changed file against the unit's declared scope. Its policy switch is SPEC's existing
    `sdd.scope_check`, which M1.6 makes effective.
  * **Diff coverage** of the changed functions. It comes from a harness-owned coverage.py plugin loaded into the
    verifier's test run.
  * A **tests-ran** check over the JUnit report.
  * Each check yields findings, holds and labels.
* **Stage B: S1 questions and data set.**
  * Four versioned question sets:
    * `file-relevant`;
    * `change-covered`;
    * `tests-ok`, a sanity check;
    * `criterion-satisfied@2`, the redesigned step 8 question.
  * Both engines answer in shadow, and records go to `$L4_CACHE/s1-calibration.jsonl` in the new format
    `l4/s1-calibration@2`.
  * `l4 s1 export` writes a laya-evals data set from ground truth only.
  * A seeded **canary generator** produces a balanced set of at least 500 rows from fixture repositories and from the
    history of `example-group/dummy-agentic`.
* **Stage C: the tuning loop on the Mac** (MPS; the runner has no GPU).
  * `scripts/s1/laya_tune.py` wraps Laya's Apple Silicon fine-tuning script, pinned by commit and checked by sha256.
  * Temperatures and thresholds are refitted on a held-out calibration split.
  * A `laya-evals run --min-accuracy --max-ece` gate runs on a held-out test split.
  * A comparison report scores base Laya, tuned Laya and Jev, each against ground truth.
  * A gated checkpoint can be selected per project (the `model:` path of a System-One profile) and deployed to the
    runner (`laya-local`).

Starting point: branch `m16` @`f2631bb` = `m15` (M1.5 Stages A and B, `7a3ae0a`) + `main` @`5851b61` [V, `git log`].
M1.3 (`m13` @`489b3d7`) is a separate, unmerged branch.

**Size: 40 build lines in three stages.** Each stage has **owned lines**, which build and exit locally with no
dependency, and **join lines [J]**. The join lines edit shared files (the ladder, the report, the workbench, preflight,
doctor). They run in one single-writer pass after M1.3 and M1.5 Stage C are merged to `main` and `main` is merged into
`m16`, the same pattern as M1.5's group 2. The live exit inherits that merge order (§Live exit). Gap ids carry the
prefix `M16-` so that they cannot collide with other increments.

**Join lines 12 to 14 run from the repository root.** Coverage `source` entries (`coverage_sources`, written by
`cov_env`) are paths relative to the working directory of the test run, so the step 3 gate must run `pytest` with the
repository (or worktree) root as its working directory. A gate that runs `cd backend && pytest` measures nothing under
`src/...` and the diff-coverage report has no data for it. `cov_env` does not make the paths absolute: that is not a
one-line change, because `relative_files = True` and `read_coverage` match report paths against repository-relative diff
paths, and an absolute `source` would change which path coverage.py reports (not verified).

## Facts this plan rests on

Labels: [V] verified (code, git, measurement, primary document), [I] inferred, [U] unverified, [G] a starting value to
calibrate.

* **Aggregation routes** [V, `verifier/aggregate.py` on `m16` and on `m13`]:
  * a blocking finding with `source="deterministic"` (on m13 also `"human"`) makes the unit FAIL;
  * any other blocking finding, any hold and any `needs_human` criterion make it NEEDS_HUMAN.

  On m13 every hold gets a `Kind: verdict` question (`hold_id` = `H-` plus 8 hex digits of the hold text). `accept`
  waives the hold; `reject` "leaves the unit with the human" [V, `m13 verifier/verdicts.py`]. So a **major,
  deterministic** out-of-scope finding would FAIL the unit under every policy. The `warn` policy must therefore go
  through a hold (D2).
* **`sdd.scope_check`** (`off | warn | fail`, default `warn`) is in SPEC §3.2 and in the schema, and nothing reads it
  on any branch [V, `config/schema.py:84`, eval-framework §3.2]. SPEC §26 rule 2 forbids keys that are not in §3.2.
  verifier task 2.11 is "scope check by `sdd.scope_check`" [V, `openspec/changes/verifier/tasks.md`]. m13 deferred it
  [V, m13-plan].
* **The test gate today** (step 3) fails on:
  * a non-zero exit;
  * a missing report;
  * collection errors;
  * a missing new test (`must_contain` = the ledger's red tests).

  **A skipped new test passes** [V, `verifier/gates.py`, `gates/junit.py`].
* **The m13 plumbing that M1.6 must compose with, not duplicate** [V, `m13`]:
  * `run_gate(..., extra_env=)` and `build_gate_env(..., extra=)` (C13);
  * `trace_env()` *sets* `PYTEST_ADDOPTS="-p l4_trace"` and `PYTHONPATH=<plugin dir>`;
  * `Workbench.run_gate` passes `extra_env=trace_env()` on every gate run;
  * integrity sub-checks return `Outcome(findings, note, skipped, declared)` and run from `CHECKS`;
  * `trace_criteria(...) -> list[CriterionEvidence]` with `TracingTest(id, status, proof, adequate)`.
* **The System-One backend (m15)** [V, `llm/system_one.py`, `verifier/s1.py`]:
  * `SystemOneBackend.ask` answers **noul only**;
  * calibration lines hold `state_sha256` but **not the state text**, so they cannot be exported for training;
  * `open_s1_backend` returns the first usable `backend: system-one` profile of a role;
  * `laya_env` passes `HF_HOME` through and sets `LAYA_MODELS=<model>`;
  * `S1Cfg.laya_budget()` = `min(max_state_tokens, 300)`.
* **Laya** [V, README and `docs/evals.md` at `NandhaKishorM/laya@2e4d9c87` (2026-10-03), fetched 2026-10-04]:
  * The Apple Silicon script `notebooks/laya_finetune_typed_decisions_mps.py`:
    * `snapshot_download`s `convaiinnovations/laya`, whose root checkpoint is `english`;
    * reads gold **distributions** per question (`{"probabilities": {...}}`);
    * trains with RLCD plus cross-entropy;
    * fits one temperature per type **on a slice of the training items** and removes `temperature_by_options`;
    * forces `max_len 1024` and `head_max_len 256`;
    * saves fp16 safetensors with `rl_agent_config.json`.
  * The README warns that the script's calibration samples come from its training items, so held-out evaluation is
    the caller's job.
  * laya-evals rows are `{state, questions, expected, tags?, language?, model?}`, with `expected` a label for
    `choice`, a number for `score` and `true`/`false` for `noul`. `run` gates with `--min-accuracy`, `--max-ece` and
    `--gate-policy` (per-slice rules with `min_count`), and exits 1 on a gate failure.
  * `laya-serve` honours a request's `model` only for `english`, `multilingual` and `typed-decisions`, and
    `LAYA_MODELS` is a list of names. **Whether it can serve a local checkpoint directory is [U].** So is
    `laya-evals run --model <dir>` on the torch path: only the ONNX path documents a local path.
  * Laya's `choice` `confidence` is entropy-based, not Jev's formula. `answer_confidence` is the comparable number.
* **Provenance of the base checkpoint `typed-decisions`** [V, the `LocalLLaMA/typed-decisions` dataset card]: "Gold is
  the mean of three samples from a teacher of roughly 4B-class capability". Jev 1.13.0 is listed separately as a
  zero-shot entrant that the card scored. So starting from `typed-decisions` uses no Jev output.
* **The English checkpoint**: ModernBERT-large, 421M parameters, a 512-token context, of which 463 tokens of state
  [V, research/03, README]. P3 = 300 approximate tokens (characters ÷ 4) [V, m15-progress].
* **The Mac** [V, `sysctl`/`df`, 2026-10-04]:
  * Apple M4 Max with 128 GB RAM;
  * **the data volume is 98 % full, with 91 GiB free**;
  * Laya is not installed: the HF cache entry for `convaiinnovations/laya` holds 24 KB of stubs.

  Each Laya checkpoint is 842.6 MB [V, m15-plan, HF API].
* **The runner** [V, m15-progress]:
  * P2 = runner (`engine: laya-local`);
  * `laya-serve` peaks at 2.48 GB RSS;
  * Jev was reached from the runner with HTTP 200 (pipeline 2612).

  **The Jev key was pasted into a chat and must be rotated first** (eval-framework step 15).
* **Jev cost and latency** [V, eval-framework §6.2]: about $0.045 per 1,000 requests; p50 273 ms. Identical requests
  drift by up to 0.09.
* **dummy-agentic has one package, `src/pricing`** [V, `docs/live/README.md` commit list]. The fixture `py_tdd` has
  only `pytdd`. A second module has to be seeded in both places.
* **Harness dependencies** are `click`, `httpx`, `pydantic` and `pyyaml`; `scripts/` is excluded from ruff [V,
  `pyproject.toml`]. Torch must stay out of the harness.

## Decisions

* **D1. Ground truth only; Jev is scored, never learned from.**
  * Calibration records come in three kinds:
    * `item`: the state as sent, the question set, the expected labels and `label_source`;
    * `answer`: engine, profile, served model and answers;
    * `label`: a later human label.
  * The export reads `item` and `label` records only.
  * Allowed label sources are `deterministic:<check>` and `human:<event>`. Anything else is rejected and counted:
    an engine name, `s1:*`, `judge:*`, or an unknown value.
  * The canary generator calls no engine.
  * Order: `export` writes `dataset_sha256` → `tune` → `gate` writes `gate.passed` into the checkpoint's
    `l4-train.json` → only then does `compare` run. `compare` refuses to run without a recorded gate and asserts that
    the data set sha is the same.
  * Checkpoint selection is the final epoch. Temperatures and thresholds come from the calibration split.
  * No code path in `export`, `canary`, `tune` or `gate` reads an `answer` record. An import-graph test checks this.
* **D2. The scope policy is SPEC's `sdd.scope_check`.** The task text proposed `verifier.evidence.scope_check`; M1.6
  deliberately reuses the SPEC key instead, because two keys for one concept would break §26 rule 2. The mechanics go
  under `verifier.evidence`. Per out-of-module file:

  | `scope_check` | Effect |
  |---|---|
  | `off` | Labels only |
  | `warn` (default) | One **hold**, worded and reported as *major* → NEEDS_HUMAN, and on m13 a verdict question. `accept` waives it (and is a human label *relevant*); `reject` keeps the unit with the human (human label *out_of_scope*) |
  | `fail` | A deterministic **major** finding → FAIL (a fix unit on m13) |

  Hold texts are stable per (path, module), with no counts in them, so `hold_id` survives later rounds.
* **D3. Declared scope and modules.**
  * **Declared scope** is the backticked paths, globs and dotted module names in:
    * the OpenSpec proposal's `## Impact`, `design.md` and the `tasks.md` task lines (the backtick rule of m15's
      `task_paths`);
    * Kiro's `design.md` and `tasks.md`.

    Prose without backticks declares nothing.
  * **Module of a path** = the first path component after one of `verifier.evidence.module_roots` (default `src`,
    `lib`, `packages`, `apps` [G]), otherwise the first component.
  * **File labels:**
    * `relevant`: a code file in a declared module or under a declared path;
    * `out_of_scope`: a code file in another module;
    * new test files are `relevant`;
    * a **modified pre-existing** test file takes the module(s) it imports (Python AST);
    * root files (`pyproject.toml`, `uv.lock`, …) are listed with **no label**, because the label would be noise;
    * `scope_exempt` paths, harness paths, `questions.md` and the unit's own spec directory are exempt.
* **D4. Diff coverage comes from the verifier's own test run.**
  * The harness-owned pytest plugin `l4_cov` is loaded with `-p l4_cov` (composed with m13's `-p l4_trace`, C-M16-1)
    into **the step 3 run itself**, so the suite is not run twice.
  * It uses coverage.py **from the project's environment only**, never from the harness's site-packages, to avoid ABI
    mismatches and shadowing.
  * It uses a harness-owned rc file that the repository cannot change:
    * `dynamic_context = test_function`;
    * JSON with contexts;
    * `source` = the changed top-level packages;
    * the `pragma: no cover` exclusion is **disabled**;
    * the data file goes under `.l4-out/cov/`.
  * The plugin is **fail-soft**: it never changes a test outcome. In these cases it writes `status.json` with
    `not_run` and a reason:
    * coverage.py is not importable;
    * pytest-cov is active;
    * xdist workers are running.
  * Under `diff_coverage.mode: fail`, a `not_run` becomes a hold, because the check fails closed.
  * Python only (`languages: [python]`).
* **D5. Tests ran extends step 3** (SPEC: "every test added in the unit executed"):
  * a new test that is missing, skipped or errored is a deterministic **blocker**;
  * a pre-existing test skipped at head in a file the unit changed is **major**;
  * unchanged skipped tests are only listed.

  The label is `tests_ok` = the gate passed, with no failed or errored test, and every new test passed.
* **D6. S1 states never contain their own label, except `tests-ok`.** `tests-ok` is the stated sanity question: its
  state is the JUnit summary, so a wrong answer reveals a broken engine or prompt.
  * The `change-covered` state carries the changed function, its hunk, the unit's test names and the static mentions
    of the function in those tests. It does **not** carry the per-line execution result. Otherwise the label would be
    readable from the state, and the tuned model would learn nothing usable where coverage is unavailable. This is a
    deliberate deviation from "state = … coverage facts".
  * The `file-relevant` state carries the spec summary, the path and a hunk summary, but not the computed module
    verdict.
* **D7. Like-for-like engines.**
  * Every engine gets **the identical state** at the Laya budget (`S1Cfg.laya_budget()`, 300 approximate tokens),
    cut by relevance rather than by prefix.
  * Choice questions are asked in both option orders, as two questions, and the two answers are averaged.
  * One sample per engine (shadow, cost-bounded). Jev's ±0.09 drift is reported, not averaged away.
  * The per-engine budget (`profiles.<p>.max_state_tokens`, eval-framework §4.6) is deferred.
* **D8. Three splits by unit hash.** `unit_hash` = sha256(project ‖ unit id). Canary items take their **source**
  unit's hash.
  * **Splits:** train 70 %, calib 15 % and test 15 % [G], seeded.
  * **Deviation:** the task says "thresholds per question fitted on the eval split" and "gate on the eval split".
    Fitting and gating on the same rows is optimistic, so the eval split is split by unit hash into `calib` (where
    temperatures and thresholds are fitted) and `test` (where the gate runs).
* **D9. Tuning starts from `typed-decisions`** at a pinned HF revision, with no Jev in its provenance (Facts). The
  `english` root is the fallback when T1 shows a format problem. The base is always passed explicitly: the script's
  default downloads the root.
* **D10. A tuned checkpoint is a path, guarded.**
  * `profiles.<p>.model` may be an absolute path under `$L4_CACHE/s1/checkpoints/<id>/`. Any other path exits 2 at
    preflight.
  * The `laya-local` probe accepts it only with `model.safetensors`, `rl_agent_config.json` and an `l4-train.json`
    whose sha256 values match and whose `gate.passed` is true. Only safetensors are loaded.
  * How it is served is decided by probe T1: a direct path if `laya-serve` takes one, otherwise a private `HF_HOME`
    overlay whose `typed-decisions/` is the tuned directory.
* **D11. Torch stays out of the harness.** `scripts/s1/` is its own uv project (laya 0.3.24, torch, transformers and
  safetensors, pinned). The harness's `l4 s1` commands need no torch. They talk to any engine through
  `SystemOneBackend`, which is the same code path for base Laya, tuned Laya and Jev.
* **D12. S1 decides nothing in M1.6.** Shadow answers are recorded only. A fake S1 that answers everything with 0, or
  everything with 1, must give the same verdict (a test). Fitted thresholds go to `thresholds.json` for the report and
  for the later `verifier.s1.decisions` proposal (eval-framework §4.6).

## Build list

Line format: `N. [lane] change-id task — what M1.6 builds`, then `test · code · verify`. Lanes:

* [E] evidence;
* [Q] S1 questions and data;
* [T] tuning on the Mac;
* [R] runner or live;
* [X] a shared-file edit that is safe to make now (additive);
* [J] a join line: a shared-file edit made after M1.3 and M1.5 Stage C are on `main` and `main` is merged into `m16`.

New tests go in new modules only (parallel-ownership rule 2.0.5).

### Stage A — deterministic evidence (ground truth)

1. [E] M16-G1 — fixture `tests/fixtures/py_multi/`:
   * two packages, `src/shop/` and `src/inventory/`, with pytest tests and a `.l4/config.yaml`;
   * 8 OpenSpec units, each with a real implementation commit range marked by `L4-Unit` trailers. Their texts vary;
     the Impact, design and task lines name paths;
   * the helper `build_repo(tmp)` makes the git history.

   test: tests/unit/evidence/test_py_multi.py::test_fixture_history_builds_and_tests_pass_at_every_unit_head · code:
   tests/fixtures/py_multi/**, tests/unit/evidence/_multi.py · verify: uv run pytest tests/unit/evidence -q
2. [E] verifier 2.11 (scope, part 1) — `declared_scope(unit_files, trees) -> DeclaredScope(paths, globs, modules,
   sources)` (D3).

   test: tests/unit/evidence/test_scope.py::test_impact_design_and_task_lines_declare_paths_and_modules (also
   ::test_prose_without_backticks_declares_nothing, ::test_dotted_module_declares_its_package, ::test_kiro_unit) ·
   code: src/l4/evidence/scope.py · verify: uv run pytest tests/unit/evidence/test_scope.py -q
3. [E] verifier 2.11 (part 2) — `module_of(path, roots)` and `classify_files(changed, scope, cfg) ->
   [FileScope(path, module, kind: code|test|root|exempt, label, reason)]` (D3).

   test: test_scope.py::test_other_module_is_out_of_scope_unless_named (also ::test_src_and_flat_layouts,
   ::test_modified_test_of_another_module_follows_its_imports, ::test_root_files_carry_no_label,
   ::test_unit_spec_dir_and_harness_paths_are_exempt) · code: src/l4/evidence/scope.py · verify: as line 2
4. [E] verifier 2.11 (part 3) — `check_scope(ctx: ScopeContext) -> ScopeOutcome(findings, note, skipped, holds,
   files)`. It keeps m13's `Outcome` fields (C-M16-2) and applies the D2 policy. The hold text is stable.

   test: test_scope.py::test_policy_off_warn_fail_through_aggregate_unit (`fail` → FAIL, `warn` → NEEDS_HUMAN with one
   hold per file, `off` → PASS; uses the real `aggregate_unit`), ::test_hold_text_has_no_counts · code:
   src/l4/evidence/scope.py · verify: as line 2
5. [E] M16-G2 — the pytest plugin `l4_cov` and `l4.gates.coverage` (D4):
   * `cov_env(out_dir) -> {PYTEST_ADDOPTS, PYTHONPATH, L4_COV_RC}`;
   * `write_rc(packages)`;
   * `merge_pytest_env(*envs)`: it joins `PYTEST_ADDOPTS` with spaces and `PYTHONPATH` with `os.pathsep`; for other
     keys the last value wins.

   The plugin starts coverage in `pytest_load_initial_conftests(tryfirst)` and writes JSON in
   `pytest_unconfigure(trylast)`.

   test: tests/unit/gates/test_l4_cov.py::test_real_pytest_writes_json_with_test_contexts (a real pytest subprocess
   on `py_multi`; context names map to JUnit ids) (also ::test_pragma_no_cover_is_still_measured,
   ::test_repo_coveragerc_and_pyproject_are_ignored, ::test_pytest_cov_active_is_not_run_and_tests_unchanged,
   ::test_plugin_crash_never_changes_outcomes, ::test_merge_keeps_both_plugins) · code:
   src/l4/gates/pytest_cov/l4_cov.py, src/l4/gates/coverage.py · verify: uv run pytest tests/unit/gates/test_l4_cov.py
   -q
6. [E] M16-G3 — `diff_lines(git, base, head)`: added and modified head lines per Python code file, from `git diff
   -U0 --find-renames`. Test and exempt files are dropped. `changed_functions(text, lines) ->
   [ChangedFunction(path, qualname, span, lines)]`, by `ast`; module-level lines go to `<module>`.

   test: tests/unit/evidence/test_diffcov.py::test_hunks_map_to_enclosing_functions (also ::test_rename_keeps_lines,
   ::test_deletion_only_hunk_changes_nothing, ::test_crlf) · code: src/l4/evidence/diffcov.py · verify: uv run pytest
   tests/unit/evidence/test_diffcov.py -q
7. [E] verifier 3.11 (reduced: harness-owned diff coverage instead of `gates.extra`) — `diff_coverage(changed,
   cov_json, status) -> DiffCoverage(percent, functions, status, reason)`.
   * A line is executable when it is in `executed_lines` ∪ `missing_lines`.
   * Per function: `covered` (every changed executable line ran), `partly` or `uncovered`, plus the tests that ran it
     (from the contexts).
   * Labels: `covered` → true, `uncovered` → false, `partly` → none.
   * `check_diff_coverage(dc, cfg)` returns a hold or a deterministic major per `diff_coverage.mode` when
     `percent < min_percent` (default 80 [G]). Under `fail`, `not_run` gives a hold. The hold text names the uncovered
     functions, sorted, with no percentage.

   test: test_diffcov.py::test_percent_function_labels_and_tests_from_contexts (also
   ::test_unimported_new_module_counts_as_uncovered, ::test_warn_holds_fail_fails,
   ::test_not_run_never_passes_fail_mode) · code: src/l4/evidence/diffcov.py · verify: as line 6
8. [E] verifier 1.8 delta (SPEC step 3, "every test added in the unit executed") — `check_tests_ran(report,
   new_tests, changed_test_files) -> TestsRanOutcome(findings, label, summary)` (D5).
   * New tests = the ledger's red tests ∪ the testcases of test files the unit added.
   * A JUnit classname is mapped to a file with `classname.replace(".", "/") + ".py"` [I]. This is checked against the
     recorded xunit2 reports.

   test: tests/unit/evidence/test_testsran.py::test_skipped_new_test_is_a_blocker (also
   ::test_label_true_only_when_every_new_test_passed, ::test_unchanged_skipped_test_is_listed_only,
   ::test_classname_to_file_on_recorded_xunit2) · code: src/l4/evidence/testsran.py · verify: uv run pytest
   tests/unit/evidence/test_testsran.py -q
9. [X] bootstrap-core 1.4 delta — config keys (all keys in §"Config"), with SPEC-style defaults in `defaults.py`.
   `sdd.scope_check` is now read. This is the only shared edit in Stage A, made first because every lane reads it.

   test: tests/unit/config/test_schema_evidence.py::test_m16_example_loads_and_unknown_evidence_key_exits_2 · code:
   src/l4/config/schema.py, src/l4/config/defaults.py · verify: uv run pytest tests/unit/config -q
10. [E] M16-G4 — `render_evidence_section(scope, dc, ran) -> list[str]`:
    * the "Evidence" section of `verification.md`, with majors first: a files table (path, module, label, why), the
      changed functions (status, tests) and the tests-ran summary;
    * `evidence_json(...)` (`l4/evidence@1`) for `verdict.json`.

    test: tests/unit/evidence/test_report.py::test_section_is_stable_and_lists_majors_first · code:
    src/l4/evidence/report.py · verify: uv run pytest tests/unit/evidence/test_report.py -q
11. [E] M16-G5 — `collect_evidence(wb, base, head, report, cov_dir, unit) -> Evidence`, run over `py_multi` with real
    git, real pytest plus `l4_cov`, and `NoSandbox`. There are four seeded heads:
    * an edit in another module;
    * a covering test deleted;
    * a failing test;
    * a clean head.

    test: tests/integration/test_evidence_flow.py::test_four_seeded_heads_give_expected_labels_findings_and_holds ·
    code: src/l4/evidence/collect.py · verify: uv run pytest tests/integration/test_evidence_flow.py -q
12. [J] gate env — `Workbench.run_gate(..., extra_env=None)` passes `merge_pytest_env(trace_env(), extra_env or {})`
    to m13's `run_gate(extra_env=)` (C-M16-1). `tdd.agent_step` is not touched: coverage runs in the verifier only.

    test: tests/unit/gates/test_pytest_env_merge.py::test_trace_and_cov_plugins_both_load_in_one_gate_run · code:
    src/l4/implementer/workbench.py · verify: uv run pytest tests/unit/gates -q
13. [J] ladder, steps 1, 3 and 6:
    * step 1 runs m13's `run_integrity` unchanged, then `check_scope`. Findings join step 1, holds go to
      `result.holds` (C-M16-2);
    * step 3: `run_test_gate(wb, must_contain, *, extra_env=None)` gains a passthrough to
      `wb.run_gate(..., extra_env=)`. The ladder passes `cov_env(...)` when `diff_coverage.mode != off`, then calls
      `check_tests_ran`;
    * a new `LADDER` row `6 quality` runs `check_diff_coverage`.

    `aggregate.py` is not edited.

    test: tests/unit/verifier/test_ladder_evidence.py::test_rows_1_3_6_route_findings_and_holds (fixture repo, fake
    judge) (also ::test_step3_without_coverage_passes_no_extra_env) · code: src/l4/verifier/ladder.py,
    src/l4/verifier/gates.py · verify: uv run pytest tests/unit/verifier -q
14. [J] report — `VerifyResult.evidence: dict | None = None`; the "Evidence" section after "Traceability"; the
    `verdict.json` key `evidence`.

    test: tests/unit/verifier/test_report_evidence.py::test_evidence_section_and_verdict_json · code:
    src/l4/verifier/types.py, src/l4/verifier/report.py · verify: as line 13

*Exit A (local):*

* `uv run pytest -q` is green.
* Line 11 shows four results:
  * out-of-module → `out_of_scope`, with a hold (`warn`) or a FAIL (`fail`);
  * deleted covering test → the function is `uncovered`, the percentage is below the minimum, and there is a
    hold;
  * failing test → `tests_ok = false` and a blocker;
  * clean → every file is `relevant`, every function `covered`, `tests_ok = true`, and there is no evidence finding.
* The plugin overhead is recorded in `docs/plan/m16-progress.md`: the wall time of the harness's own suite with and
  without `-p l4_cov`.

### Stage B — S1 questions, records, data set and canaries

15. [Q] M16-G6 — `SystemOneBackend.ask_typed(state, questions) -> {qid: Answer(kind, p_true | probabilities | score,
    confidence)}`. It parses noul, choice and score answers and refuses any value out of range. This is an additive
    method in M1.5's owned file; `ask` is unchanged.

    test: tests/unit/llm/test_system_one_typed.py::test_choice_and_score_parse_from_recorded_replies. The golden
    replies are recorded once from Jev and from local `laya-serve` with `L4_LIVE=1`, never printing the key · code:
    src/l4/llm/system_one.py · verify: uv run pytest tests/unit/llm -q
16. [Q] M16-G7 — the question-set registry `l4.s1.questions`. Each set has a version and a `question_sha256`.
    `expected_for(set, truth) -> {qid: label}` is the only map from a Stage A label to a training label.

    | Set | Questions | Ground truth |
    |---|---|---|
    | `l4/file-relevant@1` | noul `relevant` (true/false criteria); noul `unrelated` (the opposite); score `relatedness` 0–2 (other module / same module, path not named / path named) | line 3 |
    | `l4/change-covered@1` | noul `exercised`; noul `untested` (the opposite); score `extent` 0–3 (none / < 50 % / < 100 % / all changed lines ran) | line 7 |
    | `l4/tests-ok@2` | noul `all_passed` (sanity): true only if no test of the run was skipped, failed or errored | line 8 |
    | `l4/criterion-satisfied@2` | the SPEC noul with true/false criteria; choice {implemented, not_implemented, contradicted} in both orders (eval-framework §6.3) | m13 `CriterionEvidence` (C-M16-5), or a human verdict |

    test: tests/unit/s1/test_questions.py::test_every_question_maps_from_ground_truth_and_sha_is_stable · code:
    src/l4/s1/questions.py · verify: uv run pytest tests/unit/s1 -q
17. [Q] M16-G8 — state builders (D6, D7), all within `laya_budget()` and cut by relevance:
    * `file_state`: the spec summary (title, What Changes, Impact) + path + hunk summary;
    * `function_state`: signature + changed lines + the unit's test names + static mentions;
    * `tests_state`: the JUnit counts + the new tests with their status;
    * the criterion state uses m15's `_render`.

    test: tests/unit/s1/test_states.py::test_states_fit_budget_and_do_not_leak_their_label (the `change-covered` state
    has no executed or missing counts; the `file-relevant` state has no module verdict) · code: src/l4/s1/states.py ·
    verify: as line 16
18. [Q] verifier 4.3 (reduced) + M16-G9 — the records of `l4/s1-calibration@2`:
    * `item`: item_key, unit, unit_hash, project, run_id, round, origin `live|canary`, subject, the redacted state as
      sent, state_sha256, question_set, question_sha256, `expected`, label_source, tags;
    * `answer`: item_key, engine, profile, served model, answers, latency_ms, error;
    * `label`: item_key, label, source `human:<event>`, by, ts.

    They are appended to the runner cache and to `.l4-out/s1/<run>.jsonl`. m15's v1 lines are left alone.

    test: tests/unit/s1/test_records.py::test_item_answer_label_round_trip_and_item_without_any_answer · code:
    src/l4/s1/records.py · verify: as line 16
19. [Q] M16-G10 — `run_shadow(cfg, items, *, redactor) -> ShadowRun`:
    * the profiles are the first usable `roles.s1_judge` profile plus each profile in `verifier.s1.shadow`, opened by
      `open_s1_profile(cfg, name)` (a new helper next to `open_s1_backend`);
    * engines run **one at a time**: start, ask every item, stop. So two `laya-local` profiles (for example a tuned
      judge and the base Laya in shadow) never hold two `laya-serve` processes, and the runner stays at the 2.48 GB
      measured for one;
    * every engine gets every item (up to `max_items`, chosen in stable hash order);
    * an engine error is recorded as an `answer` with `error` and never blocks;
    * items are written even when every engine fails.

    test: tests/unit/s1/test_shadow.py::test_engines_run_one_at_a_time_with_identical_states_and_failures_recorded
    (httpx `MockTransport` for `jev` and `remote`, a fake `LayaServe` that fails if a second one starts) · code:
    src/l4/s1/shadow.py, src/l4/llm/system_one.py (additive helper) · verify: as line 16
20. [Q] verifier 4.3 (human outcome) — `labels_from_verdicts(events, hold_map, criterion_map) -> [label records]`:
    * `accept`/`reject` on a scope hold → `file-relevant` `relevant`/`out_of_scope`;
    * on a criterion verdict → `criterion-satisfied` true/false;
    * a verdict on a coverage hold gives **no** label, because `accept` there means "acceptable", not "covered".

    test: tests/unit/s1/test_labels.py::test_scope_and_criterion_verdicts_label_and_coverage_hold_does_not · code:
    src/l4/s1/labels.py · verify: as line 16
21. [Q] M16-G11 — the export guard (D1). `ground_truth_rows(paths)` reads only `item` and `label` records and
    projects each onto `{state, questions, expected, unit_hash, tags}`.
    * A label source outside the allow-list is rejected and counted.
    * An item with an empty `expected` and no human label is **skipped** and counted, not rejected (for example
      criterion items before M1.3 merges).
    * A human label overrides the deterministic one; both are kept in the tags.
    * Conflicting deterministic labels for one item_key are dropped and counted.
    * An unknown question-set version is rejected.

    test: tests/unit/s1/test_export_guard.py::test_engine_label_source_is_rejected (also
    ::test_judge_and_unknown_sources_rejected, ::test_randomised_answers_give_byte_identical_export,
    ::test_export_modules_never_import_score_or_report) · code: src/l4/s1/export.py · verify: as line 16
22. [Q] M16-G11 — `l4 s1 export --out <dir>`. It writes laya-evals JSONL (`state`, `questions`, `expected`, `tags`,
    `language: en`) and `manifest.json`, which holds:
    * counts per split, question, label, origin, mutation and label source;
    * the sha256 of every file and `dataset_sha256`;
    * the allow-list;
    * the generator versions.

    The splits follow D8. A cap of at most 2:1 per question's labels is applied by stable-hash downsampling.

    **Choice option orders.** `train.jsonl` holds both orders as two questions, which is augmentation.
    `calib.jsonl` and `test.jsonl` hold the canonical order only, so `laya-evals` scores exactly one choice question
    per item. `l4 s1 score` asks both orders and reports a canonical column and an averaged column.

    test: tests/unit/s1/test_export.py::test_no_unit_hash_in_two_splits_and_balance_cap (also
    ::test_manifest_counts_match_files) · code: src/l4/s1/export.py · verify: `uv run --project scripts/s1 laya-evals
    validate <dir>/test.jsonl` (after line 31)
23. [Q] M16-G12 — canary mutations. Each one is applied in a scratch worktree of a source unit, the project's
    `gates.test.command` is run with `l4_cov`, and the item is labelled **by the Stage A checks**. The intended labels:

    | Mutation | Intended label |
    |---|---|
    | `transplant_hunk` (a real hunk from another unit's diff in another module; preferred) | out_of_scope |
    | `template_edit` (fallback) | out_of_scope |
    | `drop_covering_test` (delete, or `@pytest.mark.skip`, the tests whose contexts cover a changed function) | uncovered (and a blocker if skipped) |
    | `untested_function` (a new function in a changed file) | uncovered |
    | `break_test` (flip one expected literal in a new test) | tests_not_ok |
    | `none` (the untouched unit) | relevant, covered, tests_ok |

    When the intended label and the check's label disagree, the item is dropped and counted as
    `checker_disagreement`, which is also a self-test of Stage A. No engine is called. The runner is `NoSandbox`, on
    the maintainer's own repositories only (an allow-list of repository roots; anything else exits 2).

    test: tests/unit/s1/test_canary.py::test_each_mutation_gives_its_intended_label_on_py_multi (also
    ::test_same_seed_same_items, ::test_disagreement_is_dropped_and_counted, ::test_no_engine_is_constructed) · code:
    src/l4/s1/canary.py · verify: uv run pytest tests/unit/s1/test_canary.py -q
24. [Q] M16-G12 — `l4 s1 canary --repo <path>... --seed N --target 600`.
    * Source units are found from `L4-Unit` trailer ranges and from `openspec/changes/archive/*`.
    * Quotas apply per (question, label). It stops when there are at least 500 items, every label holds at least 30 %
      of its question's items, and the planned test split holds at least 30 items per (question, label).
    * Items carry the tags `origin:canary`, `mutation:<m>` and `source:<unit>`.

    test: test_canary.py::test_quotas_reach_target_on_py_multi_with_small_target · code: src/l4/s1/canary.py,
    src/l4/s1/cli.py · verify: `l4 s1 canary --repo <py_multi> --seed 1606 --target 120` (counts in the progress
    file)
25. [Q] M16-G13 — scoring and the report:
    * `l4 s1 score --profile <p> --dataset <jsonl> --out <answers.jsonl>`: any System-One profile, through
      `ask_typed`, with both option orders for choice;
    * `l4 s1 report <answers>... --dataset <jsonl>`: per engine and per question, accuracy, ECE (15 bins on the
      answer confidence), Brier, n and a 95 % Wilson interval; slices by origin and mutation.

    test: tests/unit/s1/test_report.py::test_metrics_match_hand_computed_values (also
    ::test_report_reads_expected_only_as_reference) · code: src/l4/s1/score.py, src/l4/s1/report.py · verify: as line 16
26. [Q] M16-G14 — `l4 s1 audit --dataset <dir> --sample 50`. It writes a Markdown checklist of a seeded sample of the
    test split; the maintainer marks each row `agree` or `disagree: <label>`; `l4 s1 audit --import` appends
    `label{source: human:audit}` records. The noise rate is reported with a Wilson interval.

    test: tests/unit/s1/test_audit.py::test_checklist_round_trip_and_disagreement_becomes_label · code:
    src/l4/s1/audit.py · verify: as line 16
27. [X] CLI — `commands.HANDLERS["s1"] = "l4.s1.cli:run_s1_cli"`, `OWNING_CHANGE["s1"]`, and one row in the `cli.py`
    command table, as for `lessons`. Subcommands: `export`, `canary`, `score`, `report`, `audit`.

    test: tests/unit/cli/test_s1_dispatch.py::test_s1_subcommands_dispatch · code: src/l4/commands.py, src/l4/cli.py ·
    verify: uv run pytest tests/unit/cli -q
28. [J] ladder, step 8 — after M1.5's `run_s1` and `record_calibration`:
    * items are built for the four question sets from the round's evidence;
    * `run_shadow`;
    * records are appended.

    S1 decides nothing (D12).

    test: test_ladder_evidence.py::test_shadow_answers_never_change_the_verdict (a fake S1 answering 0 everywhere and
    1 everywhere gives the same verdict) (also ::test_items_written_when_every_engine_is_down) · code:
    src/l4/verifier/ladder.py · verify: uv run pytest tests/unit/verifier -q
29. [J] human labels — after M1.3's `consume_verdicts` and `after_verdict` in `verify_hook`, `labels_from_verdicts` is
    called. Its hold map comes from the round's `evidence.json`.

    test: test_ladder_evidence.py::test_reject_on_scope_hold_appends_out_of_scope_label · code:
    src/l4/verifier/ladder.py · verify: as line 28
30. [J] preflight — exit 2 when:
    * a `verifier.s1.shadow` name is not a `backend: system-one` profile;
    * `diff_coverage.languages` ⊄ {python};
    * a System-One `model:` path lies outside `$L4_CACHE/s1/checkpoints/`.

    test: tests/unit/config/test_preflight_m16.py::test_shadow_language_and_checkpoint_path_rules · code:
    src/l4/config/preflight.py · verify: uv run pytest tests/unit/config -q

*Exit B (local):*

* `l4 s1 canary` on `py_multi` and on a local clone of dummy-agentic yields **at least 500 items**, with the quotas of
  line 24 met.
* `l4 s1 export` passes `laya-evals validate` for all three splits.
* The guard tests of line 21 pass.
* **Waits for line 31:** the Laya golden reply of line 15 and the live smoke below need the Laya environment on the
  Mac. Line 31 touches only `scripts/s1/`, so it starts in parallel with Stage B.
* `L4_LIVE=1`: `l4 s1 score` on 20 canary items with the Mac's `laya-serve` (`remote`) and with Jev (key from
  Mintkey through `scripts/dev/mintkey_secret.py`, never printed). Both produce answers, and `l4 s1 report` renders.

### Stage C — the Laya tuning loop on the Mac

31. [T] M16-G15 — `scripts/s1/` as its own uv project. It pins:
    * `laya[serve]==0.3.24`, torch, transformers, safetensors and huggingface_hub, in `pyproject.toml` and `uv.lock`;
    * `vendor/laya_finetune_mps.py` (Laya @`2e4d9c87`, Apache-2.0 notice kept) and `vendor/SHA256`.

    `check_vendor.py` checks the sha.

    test: tests/unit/s1/test_tune_vendor.py::test_vendored_script_matches_pinned_sha (no torch import) · code:
    scripts/s1/** · verify: `uv sync --project scripts/s1`; disk use and time recorded in the progress file
32. [T] M16-G16 — probe T1 on the Mac, `scripts/s1/probe_t1.sh`, log saved to `docs/runner/probe-t1-<date>.txt`. It
    checks:
    * (a) the vendored script imports under laya 0.3.24 (`laya.common.build_model`, `build_sequence`,
      `proper_reward`, `render_options`, `QTYPES`, `laya.agent._fix_tokenizer_config`);
    * (b) `laya.load(<dir>)` loads a checkpoint saved by the script (`max_len 1024`) and answers within the 463-token
      window;
    * (c) `LAYA_MODELS=<dir> laya-serve` serves it, and whether it honours `model`;
    * (d) a private `HF_HOME` overlay whose `typed-decisions/` is the directory, with `HF_HUB_OFFLINE=1`;
    * (e) `laya-evals run --model <dir>`;
    * (f) a tiny training run (`--epochs 1`, 32 items), recording peak memory, seconds per item and disk.

    Decisions:
    * **T1-serve**: (c) if it works, otherwise (d);
    * **T1-eval**: (e) if it works, otherwise `laya.evals.evaluate(laya.load(dir), Dataset.from_jsonl(...))` with the
      same thresholds;
    * **T1-compat**: if (a) fails, pin the laya version the script was written for, for training only, and re-run
      (b) with the serving pin.

    test: the probe log · code: scripts/s1/probe_t1.sh · verify: the decisions recorded in `m16-progress.md`
33. [T] M16-G17 — `laya_tune.py build-items`: the train split → `build_training_item`. Gold distributions:
    * noul: `{true: 1, false: 0}`;
    * choice: one-hot;
    * score: a one-hot level.

    It refuses a data set whose `manifest.json` lists a label source outside the allow-list, a second line of defence
    after line 21.

    test: tests/unit/s1/test_tune_items.py::test_gold_from_expected_and_refuses_bad_manifest (the pure part, with no
    torch) · code: scripts/s1/laya_tune.py · verify: `uv run --project scripts/s1 python scripts/s1/laya_tune.py
    build-items --data <dir>`
34. [T] M16-G17 — `laya_tune.py train`:
    * the base comes from `--base typed-decisions@<HF revision>` (D9);
    * the vendored `train()` runs on MPS with `--micro-batch` and `--grad-accum`;
    * afterwards temperatures are **refitted on the calib split** (the vendored `fit_temperature`) and
      `temperature_by_options` is dropped;
    * per-question thresholds are fitted on calib: the lowest accept threshold whose 95 % Wilson lower bound on
      precision is at least 0.95, and the mirror for reject. They are written to `thresholds.json`;
    * `l4-train.json` records the base revision, the data set and split sha256, a label-source histogram, the seed,
      the hyperparameters, temperatures, thresholds, wall time and peak memory;
    * selection is the final epoch.

    test: tests/unit/s1/test_tune_thresholds.py::test_wilson_threshold_fit (pure Python) · code:
    scripts/s1/laya_tune.py · verify: the real run on the export of line 22
35. [T] M16-G18 — `laya_tune.py gate`: `laya-evals run test.jsonl --model <ckpt> --min-accuracy 0.85 --max-ece 0.10
    --slice tag --gate-policy scripts/s1/gates.json --json gate.json` (or the T1-eval fallback).
    * `gates.json` rules per qid have `min_count` 30 [G].
    * The tuned model must also beat base Laya on the same split by at least 0.05 noul accuracy [G].
    * `gate.passed` and the data set sha are written into `l4-train.json` **before** any comparison.
    * `gates.json` names no engine.

    test: tests/unit/s1/test_gate_policy.py::test_policy_valid_and_engine_free · code: scripts/s1/laya_tune.py,
    scripts/s1/gates.json · verify: the real gate run
36. [T] M16-G19 — the comparison: `l4 s1 score` for base Laya, tuned Laya (per T1-serve) and Jev on `test.jsonl`, then
    `l4 s1 report` → `docs/s1/compare-<date>.md`.
    * It refuses to run without `gate.json` (whether the gate passed or failed) and asserts the same
      `dataset_sha256`.
    * Cross-check: its tuned-Laya numbers for the noul and score questions, and for the canonical-order choice column,
      agree with `gate.json` within 0.01. Laya's own metric code is the independent oracle. The averaged choice column
      has no `laya-evals` counterpart and is not cross-checked.

    test: tests/unit/s1/test_compare_order.py::test_refuses_before_gate_and_on_sha_mismatch · code:
    src/l4/s1/report.py · verify: the real comparison
37. [T] M16-G20 — a checkpoint as a profile (D10): `_probe` (laya-local) and `laya_env` accept a gated path, with
    serving per T1-serve. An ungated or tampered checkpoint gives `RoleUnavailable` with the reason.

    test: tests/unit/llm/test_system_one_checkpoint.py::test_ungated_or_tampered_checkpoint_is_unusable (also
    ::test_overlay_layout_when_t1_says_overlay) · code: src/l4/llm/system_one.py · verify: uv run pytest
    tests/unit/llm -q
38. [R] M16-G21 — `scripts/s1/deploy_checkpoint.sh <id> [--dry-run]`:
    * copies the checkpoint through `mk-ssh.sh` to `~gitlab-runner/.cache/l4/s1/checkpoints/<id>/`;
    * re-checks the sha256 on the runner;
    * prints the profile snippet.

    It refuses an ungated checkpoint.

    test: tests/unit/s1/test_deploy_script.py::test_dry_run_plan_and_refuses_ungated (golden output) · code:
    scripts/s1/deploy_checkpoint.sh · verify: the real deploy, then `sha256sum` on the runner
39. [J] doctor — the owned module `l4/doctor/checks_s1.py`, all checks warn-level:
    * **S1-001**: every `verifier.s1.shadow` profile probes usable;
    * **COV-001**: coverage.py is importable in the project environment when `diff_coverage.mode != off`;
    * **S1-002**: a configured checkpoint is gated and sha-intact.

    It adds one `CHECK_MODULES` row.

    test: tests/unit/doctor/test_checks_s1.py::test_three_checks_warn_with_reasons · code: src/l4/doctor/checks_s1.py,
    src/l4/doctor/registry.py · verify: uv run pytest tests/unit/doctor -q
40. [R] M16-G22 — the live protocol below as code: one test per step, reading pipelines, jobs, MRs, artefacts and the
    runner cache read-only, and recording the ids.

    test: tests/live/test_m1_6_acceptance.py (marker `live`, `L4_LIVE=1`, `L4_LIVE_RECORD` default
    `/tmp/l4_m1_6_ids.json`) · code: the same · verify: `L4_LIVE=1 uv run pytest tests/live/test_m1_6_acceptance.py -m
    live -q`

*Exit C (local, on the Mac):*

* T1 is recorded.
* A checkpoint is trained from the export of at least 500 items.
* `gate.json` is written. Exit C requires the gate to **run**. If it fails, the progress file records the failing
  slices and the next data iteration, at most 2 iterations [G], and the checkpoint is not deployable.
* The comparison report shows the three engines on the same test split, with Wilson intervals.
* `deploy_checkpoint.sh --dry-run` passes.

## Config (proposed SPEC §3.2 additions; `sdd.scope_check` already exists)

```yaml
sdd:
  scope_check: warn              # off | warn | fail : now read (M1.6). warn = one hold per out-of-module file;
                                 # fail = deterministic major finding (D2)
verifier:
  evidence:                      # M1.6, deterministic change evidence
    module_roots: [src, lib, packages, apps]   # a module = first path component under one of these, else the first
    scope_exempt: ["docs/**", "**/*.md", "CHANGELOG*"]   # never out of scope (harness and unit-spec paths always are)
    diff_coverage:
      mode: warn                 # off | warn | fail (same meaning as scope_check)
      min_percent: 80            # [G] share of changed executable lines run by the tests
      languages: [python]        # M1.6: python only (coverage.py through the l4_cov pytest plugin)
  s1:
    shadow: []                   # System-One profiles asked IN ADDITION to roles.s1_judge, record-only, e.g. [jev]
    max_items: 60                # [G] cap on shadow items per round
profiles:
  laya-tuned:
    backend: system-one
    engine: laya-local
    model: /home/gitlab-runner/.cache/l4/s1/checkpoints/<id>   # only under $L4_CACHE/s1/checkpoints/, gated (D10)
```

`verifier.s1.shadow` defaults to empty, so nothing reaches TypeSafe unless a project opts in (data egress,
eval-framework §6.5).

## Files

**(a) Owned (new):**

* `src/l4/evidence/{__init__,scope,diffcov,testsran,report,collect}.py`. This is a package, so it avoids m13's
  `verifier/evidence.py`.
* `src/l4/gates/pytest_cov/l4_cov.py` (the only module in that directory) and `src/l4/gates/coverage.py`.
* `src/l4/s1/{__init__,questions,states,records,shadow,labels,export,canary,score,report,audit,cli}.py`. This is a
  package, distinct from m15's `verifier/s1.py`.
* `src/l4/doctor/checks_s1.py`.
* `scripts/s1/{pyproject.toml,uv.lock,laya_tune.py,check_vendor.py,probe_t1.sh,deploy_checkpoint.sh,gates.json}` and
  `scripts/s1/vendor/{laya_finetune_mps.py,SHA256,NOTICE}`.
* Tests:
  * `tests/unit/evidence/**`, `tests/unit/s1/**`;
  * `tests/unit/gates/test_{l4_cov,pytest_env_merge}.py`;
  * `tests/unit/llm/test_system_one_{typed,checkpoint}.py`;
  * `tests/unit/config/test_{schema_evidence,preflight_m16}.py`;
  * `tests/unit/cli/test_s1_dispatch.py`, `tests/unit/doctor/test_checks_s1.py`;
  * `tests/unit/verifier/test_{ladder_evidence,report_evidence}.py`;
  * `tests/integration/test_evidence_flow.py`, `tests/fixtures/py_multi/**`;
  * `tests/fixtures/recorded/system-one/{jev,laya}-typed.json`;
  * `tests/live/test_m1_6_acceptance.py`.
* `docs/plan/m16-progress.md`, `docs/s1/compare-*.md`, `docs/runner/probe-t1-*.txt`.

**(b) Shared files, with the exact edit (additive unless marked):**

| File | Edit | Line | When |
|---|---|---|---|
| `src/l4/config/schema.py` | new `DiffCoverageCfg`, `EvidenceCfg`; field `VerifierCfg.evidence`; fields `S1Cfg.shadow: list[str] = []`, `S1Cfg.max_items: int = 60` | 9 | now |
| `src/l4/config/defaults.py` | `MODULE_ROOTS`, `SCOPE_EXEMPT`, `DIFF_COVERAGE_MIN_PERCENT = 80`, `S1_MAX_ITEMS = 60`, `S1_CHECKPOINTS_DIR = "s1/checkpoints"` | 9 | now |
| `src/l4/llm/system_one.py` (owned by M1.5; M1.5 Stage C does not edit it [V, m15-plan Files]) | new `Answer`, `SystemOneBackend.ask_typed`, `open_s1_profile`; `_probe` laya-local path branch and `laya_env` (T1-serve) | 15, 19, 37 | now; a courtesy note goes into m15-progress |
| `src/l4/commands.py`, `src/l4/cli.py` | `HANDLERS["s1"]`, `OWNING_CHANGE["s1"]`; one command-table row | 27 | now |
| `src/l4/implementer/workbench.py` | `Workbench.run_gate(..., extra_env=None)`; the `run_gate(...)` call takes `merge_pytest_env(trace_env(), extra_env or {})` | 12 | join |
| `src/l4/verifier/ladder.py` | step 1 body: `check_scope` after `run_integrity`; step 3 body: `cov_env` and `check_tests_ran`; `LADDER` row `("6", "quality", …)`; step 8: `run_shadow` after `run_s1`; `verify_hook`: `labels_from_verdicts` after `after_verdict` | 13, 28, 29 | join |
| `src/l4/verifier/gates.py` (M1.5 line 33 adds `run_e2e_gate` here) | keyword `run_test_gate(..., extra_env=None)`, passed through to `wb.run_gate` | 13 | join |
| `src/l4/verifier/types.py` | `VerifyResult.evidence: dict \| None = None` (after M1.3's and M1.5's fields) | 14 | join |
| `src/l4/verifier/report.py` | an "Evidence" section after "Traceability"; the `verdict.json` key `evidence` | 14 | join |
| `src/l4/config/preflight.py` | three checks at the end of `preflight_run_config`, after M1.5's line-38 checks | 30 | join |
| `src/l4/doctor/registry.py` | `CHECK_MODULES` += `"l4.doctor.checks_s1"` (a same-line union with M1.4 and M1.5) | 39 | join |

**Not touched:** `verifier/aggregate.py` (holds and findings use the existing routes), m13's `verifier/integrity.py`
(its `CHECKS` is unchanged), `verifier/traceability.py`, `verifier/s1.py`, `clarifier/**`, `sandbox/**`, `forge/**`,
`ci/**`, `archive.py`, `orchestrator.py`, `planner.py`, `state/**`, and `pyproject.toml` (no new harness dependency;
torch lives in `scripts/s1`).

## Contracts and interfaces

**Contracts with other increments:**

* **C-M16-1, the pytest environment.**
  * `merge_pytest_env(trace_env(), cov_env(...))` gives `PYTEST_ADDOPTS="-p l4_trace -p l4_cov"`, and `PYTHONPATH`
    joins both plugin directories.
  * m13's `run_gate(extra_env=)` and `build_gate_env(extra=)` (C13) are used verbatim; M1.6 adds no second keyword.
  * Until the join, M1.6's tests call `run_gate` with `extra_env=` on a branch that has m13's signature. On m16 alone
    they set the environment through `NoSandbox` directly.
* **C-M16-2, step 1.** m13's `run_integrity` runs unchanged. The ladder then calls `check_scope`, whose `ScopeOutcome`
  carries m13's `Outcome` fields (`findings`, `note`, `skipped`, `declared`) plus `holds` and `files`. Report row
  `scope` (in the Evidence section).
* **C-M16-3, hold texts.**
  * Scope: ``scope: `<path>` changes module `<m>`, which the spec does not name``.
  * Coverage: ``diff coverage: changed code not run by any test: `<qualname>`, …`` (sorted, no percentage).

  The texts are stable, so m13's `hold_id` stays the same across rounds and an answered hold is not asked again.
* **C-M16-4, `l4/s1-calibration@2`** (D1, line 18). It is provided to any consumer. m15's v1 lines stay valid. The
  export skips them and counts them, because they hold no state text.
* **C-M16-5, criterion labels from m13.** `CriterionEvidence` gives the label:
  * covered by a passing, discriminating, adequate test → `true`;
  * a tracing test failing at head → `false` (choice: no label, because `not_implemented` and `contradicted` cannot be
    told apart);
  * uncovered → no label.

  A `human.verdict` on the criterion overrides it. Before m13 merges, criterion items carry no deterministic label.

**Provided:**

* `l4.evidence.scope`: `declared_scope`, `module_of`, `classify_files`, `check_scope`.
* `l4.evidence.diffcov`: `diff_lines`, `changed_functions`, `diff_coverage` → `DiffCoverage.functions[].tests` (the
  tests that ran each changed function). A future step 4 can use it to flag a tracing test that runs none of the
  unit's changed code (an offer to M1.3's traceability, not built here).
* `l4.evidence.testsran.check_tests_ran`.
* `l4.gates.coverage`: `cov_env`, `merge_pytest_env`, `write_rc`; and the `l4_cov` plugin.
* `l4.llm.system_one`: `ask_typed`, `Answer`, `open_s1_profile`.
* `l4.s1`: question sets, records, `run_shadow`, `labels_from_verdicts`, `ground_truth_rows`, the export, canary,
  score, report and audit.

**Needed:**

* **M1.3:**
  * `run_gate(extra_env=)`, `build_gate_env(extra=)` and `trace_env()`;
  * `run_integrity` and the step 1 row;
  * `trace_criteria` / `CriterionEvidence`;
  * `consume_verdicts`, `human.verdict`, hold verdict questions and `after_verdict`.
* **M1.5 Stage C:**
  * step 8 wired (`run_s1`, `record_calibration`, `verify.s1`);
  * `LayaServe` around the S1 batch;
  * preflight line 38;
  * `CHECK_MODULES` for `checks_memory`.
* **M1.2:** nothing hard. If `select_judge`/`for_role` replaces `open_s1_backend`, `open_s1_profile` follows it.

## Live exit protocol on `example-group/dummy-agentic` through `l4-runner`

**Preconditions:**

* M1.3 and M1.5 are merged and their live protocols have passed (M1.5's proves Laya on the runner). M1.6 is merged.
  The harness pinned by `l4 upgrade` is the `main` commit right after M1.6's merge.
* **HUMAN:** the Jev key is rotated in Mintkey (`typesafe-jev-api-key`) and copied with
  `scripts/forge/gitlab_ci_var_from_mintkey.py` into the masked variable `TYPESAFE_API_KEY` (eval-framework step 15).
* PRQ-18 (Laya) is OK on the runner. Exit C is done on the Mac.

**Why the seeds come from a human push.** Codex will not, on demand, produce an out-of-module edit or an untested
function. One deterministic path exists today:
* a unit whose `design.md` lists an open question (deterministic intake raises it, `b0a35a8` [V, live README]);
* `clarifier.auto_accept_kinds: []`, so the unit parks in `awaiting_human` [V, eval-framework lever 19];
* the human push that answers Q-001 also carries the two seeded edits. Human code on a unit branch is not reverted by
  any guard [I; checked by step 2's expectations].

**Steps:**

1. **Maintainer:** commit and push to `main`: "Seed inventory module, coverage, bulk discount unit; enable evidence
   and S1 shadow (M1.6)". The seed contents:
   * `src/inventory/{__init__,stock}.py` (`LOW_STOCK_THRESHOLD = 5`, `is_low(qty)`) and `tests/test_stock.py`;
   * `coverage` in the dev dependency group, then `uv lock`;
   * the `.l4/config.yaml` additions below;
   * `openspec/changes/add-bulk-discount/`:
     * `proposal.md`: Impact = `` `src/pricing/discounts.py` (`bulk_discount`), tests under `tests/` ``;
     * `design.md` with `## Open questions`: "Does the bulk threshold count units or distinct lines?";
     * `specs/bulk-discount/spec.md`: one requirement and two scenarios;
     * `tasks.md`: "1.1 Add `bulk_discount(cart)` in `src/pricing/discounts.py` …".

   Expected **P1**:
   * intake raises Q-001;
   * the clarifier suggests an answer and escalates;
   * `awaiting_human`, draft MR, exit 11.
2. **HUMAN (the operator may act):** one push to the unit branch. It contains:
   * `questions.md` with Q-001 answered "units", Status `answered`;
   * an edit to `src/inventory/stock.py` (`LOW_STOCK_THRESHOLD = 3`), which is out of scope;
   * a new `src/pricing/receipt.py` with **at least 40 executable lines** in three functions (`format_receipt`,
     `format_line`, `format_total`, with loops and branches) and no test. It is in scope (module `pricing`) but
     uncovered, and it is in a file the task does not name. Sizing: even if Codex writes 100 covered lines for
     `bulk_discount`, the result is 100 / 140 ≈ 71 % < 80 %, so the hold cannot depend on how much code Codex writes.

   Expected **P2**:
   * plan `implement` ("answers submitted: Q-001"), then red → green with Codex;
   * **step 1:** a scope hold on `src/inventory/stock.py`, reported as major (`warn`);
   * **step 3:** pass. Tests ran: `tests_ok = true`, and the new tests ran and passed;
   * **step 6:** diff coverage below 80 % (expected 30–70 % [I]). The three receipt functions are `uncovered`, and
     there is a hold;
   * **step 8:**
     * M1.5's criterion rows;
     * **item records** for each changed code file (at least 3), each changed function (at least 2), one `tests-ok`
       item and each criterion;
     * **answer records from both `laya-local` and `jev`** for each item (or an `error` recorded);
     * the job log shows `laya-serve` started and stopped inside step 8;
   * **`verification.md`:** an Evidence section with both majors first. The verdict is **NEEDS_HUMAN**;
   * m13 verdict questions `H-…` for both holds;
   * exit 11;
   * the `.l4-out/s1/<run>.jsonl` artefact holds the items and the answers.
3. **HUMAN:** answer `reject: inventory is not part of bulk discounts` on the scope hold and `accept: receipt helper
   lands with its own unit` on the coverage hold. Expected **P3**:
   * `human.verdict` ×2;
   * one `label{source: human:verdict, label: out_of_scope}` record for `src/inventory/stock.py`;
   * **no** label for the coverage hold;
   * the unit stays with the human (`reject`).

   **Operator:** close the MR and delete the branch.
4. **Operator, Mac:**
   * copy the runner's `$L4_CACHE/s1-calibration.jsonl` read-only through `mk-ssh.sh`;
   * `uv sync` in a fresh clone of dummy-agentic, so the canary can run its tests;
   * `l4 s1 canary --repo <py_multi> --repo <dummy-agentic clone> --seed 1606 --target 600`;
   * `l4 s1 export` over the canary file plus the copied live file. The P2 items appear in the split that their
     `unit_hash` dictates;
   * `l4 s1 audit` (50 rows, maintainer);
   * `laya_tune.py build-items | train | gate`;
   * once `gate.json` exists, whether the gate passed or failed (D1): `l4 s1 score` ×3 and `l4 s1 report` →
     `docs/s1/compare-<date>.md`. A comparison after a failed gate shows which slices to fix; it never feeds back into
     selection.

   Expected:
   * `gate.json` exists with `passed` (true or false) and is recorded in `l4-train.json` before the comparison;
   * the comparison names the same `dataset_sha256`;
   * `manifest.json` shows 0 rows from an engine or judge label source, and some rejected rows if any were planted
     (the `test_export_guard` fixture is replayed on the real file for evidence).
5. **Operator** (only if the gate passed): `deploy_checkpoint.sh <id>`, with the sha256 re-checked on the runner.
6. **Maintainer:** commit and push to `main`: the profile `laya-tuned` (path form), `roles.s1_judge: [laya-tuned]`,
   `verifier.s1.shadow: [laya, jev]`, and a small seed unit `add-free-shipping-flag` (in-scope, tested). Expected **P4**:
   * doctor S1-002 is OK;
   * `availability.selected{role: s1_judge, selected: laya-tuned}`;
   * a verdict of PASS and a ready MR;
   * answer records from `laya-tuned`, `laya` and `jev` for every item.
7. **Operator, read-only:**
   * no `laya-serve` process is left (`pgrep -u gitlab-runner -f laya-serve` is empty);
   * peak RSS lines from P2 and P4;
   * `[skip ci]` commits ran no `l4` job;
   * every id goes into `docs/live/README.md`.

**Pass** = steps 1–4 and 7 behave as expected, and steps 5–6 also pass when the gate passed. A gate failure is
recorded, not hidden. It starts the data iteration of Exit C, and steps 5–6 wait for it.

**Retry rules:**
* If Codex writes a test for the receipt functions, or step 6 still reports at least 80 % (coverage seed not
  reproduced), record it and repeat steps 1–2 with the helper in `src/pricing/receipt_debug.py`, sized at 60
  executable lines. A second miss fails the coverage part.
* If any guard reverts the human's edits in step 2, the protocol fails and the cause is recorded. That would contradict
  the [I] above.

**`.l4/config.yaml` additions for step 1:**

```yaml
sdd:
  scope_check: warn
verifier:
  evidence:
    diff_coverage: {mode: warn, min_percent: 80, languages: [python]}
  s1:
    shadow: [jev]
  fix_minor_findings: false
profiles:
  laya:
    backend: system-one
    engine: laya-local
    model: typed-decisions
    vendor: convai
  jev:
    backend: system-one
    engine: jev
    base_url: https://api.typesafe.ai
    api_key_env: TYPESAFE_API_KEY
    model: jev-1.13.0
    vendor: typesafe
roles:
  s1_judge: [laya]
clarifier:
  auto_accept_kinds: []          # Q-001 must reach a human (the seed path); restore after the protocol
```

## Simplifications and deferrals

* **Evidence**
  * Python only, for both coverage and the AST mapping of tests to modules. Other languages report `not_run` for
    coverage; scope works for any language (paths and modules).
  * No branch coverage.
  * Declared scope is read from backticks only.
  * The snapshot half of verifier 2.11 stays deferred.
  * `gates.extra` (verifier 3.11's general form) stays M2.
* **Coverage**
  * The project must provide coverage.py.
  * pytest-cov or xdist active → `not_run`. Subprocess coverage is not measured.
* **S1**
  * One sample per engine.
  * The same Laya-budget state for every engine. A per-engine budget is deferred (eval-framework §4.6).
  * The router and citation question redesigns (eval-framework §6.3) are **not** in M1.6. They belong to the clarifier
    wiring of M1.5 line 28 and its follow-up.
  * Thresholds are recorded, not applied.
* **Tuning**
  * The Mac only. No scheduled re-tuning: the loop is run by the maintainer, and a re-tune trigger such as every 20
    finished units (eval-framework §5.3) is a follow-up.
  * No ONNX export. One base, final-epoch selection.
* **Live**
  * The seeds come from a human push, not from an agent's mistake.
  * The canary set lives on the Mac, not in CI.

## Risks

* **Disk on the Mac.** The data volume is 98 % full, with 91 GiB free [V]. The estimated need is 5–10 GB [I]:
  * the `scripts/s1` environment (torch and transformers), several GB [I];
  * two Laya checkpoints of 0.84 GB each [V];
  * the script's per-epoch `checkpoint_latest` plus the final checkpoint, fp16, about 0.85 GB each [I];
  * the item cache.

  T1(f) measures it. Clean old checkpoints after each gate.
* **Training time and MPS coverage.**
  * The README gives 4–5 h on 2×T4 for 4 epochs over about 30k questions [V]. The set here is about 1.5–3k questions,
    which suggests well under an hour on an M4 Max [I]. T1(f) measures seconds per item.
  * ModernBERT operations may fall back from MPS to CPU [U].
  * MPS training is not bit-reproducible, so the seeds and `l4-train.json` are recorded.
* **Laya format and serving** [U]:
  * whether `laya-serve` and `laya-evals` take a local directory;
  * the script's `max_len 1024` against the 512-token English context;
  * the script's imports under the 0.3.24 pin.

  T1 decides each one, with a written fallback. **Laya churn:** 34 releases in about 16 days [V, m15].
* **The 300-token window.** Hunks and functions are summarised, so long functions lose content. That is label noise
  for `change-covered` and `file-relevant`. The relevance cut and the per-question slice metrics expose it.
* **Class balance.** Real units are mostly relevant, covered and ok. Canaries and the 2:1 cap balance the data;
  per-class recall is in the report.
* **Label noise.**
  * Coverage measures **execution**, not checking. "Covered" is not "verified" (m13's discrimination and audit cover
    that).
  * The scope rule depends on backticked paths. Root files are unlabelled.
  * The 50-row audit estimates the noise rate. Above 10 % [G], the canary or check is fixed before tuning.
* **Small and correlated data.**
  * There are about 8 fixture units plus about 6–8 dummy-agentic units, so the test split holds only 2–3 source units.
    Results get Wilson intervals and per-slice `min_count`, and they **do not transfer** to other projects without
    per-project tuning.
  * Template mutations invite shortcut learning. Transplanted hunks are preferred, and the `mutation:` slice shows a
    shortcut as an accuracy gap.
* **Jev.**
  * Jev is a third-party API: the states (redacted code and spec excerpts) leave the runner. `shadow` defaults to
    empty, and regulated projects keep it off.
  * Its drift (±0.09) makes single-sample scores noisy.
  * The contract risk is controlled by D1. Human misuse — tuning "until Laya beats Jev" — is out of code's reach. The
    gate never names Jev, and the comparison runs only after the gate is recorded.
* **Gaming the evidence.**
  * A `conftest.py` could overwrite `.l4-out/cov/coverage.json` after the plugin writes it. M1.6 checks the JSON's
    `meta` (coverage version, timestamp after the gate started). m13's step 1 content scan should add writes under
    `.l4-out/cov` and coverage calls in test support files. This is a request to M1.3, not built here.
  * Partial: a determined repository can still fake coverage. That is an SC-03-class hole recorded here.
* **Coverage side effects.** The plugin runs inside the authoritative step 3 run: overhead (measured in Exit A) and
  plugin bugs. It is fail-soft and tested (line 5), and `mode: off` loads nothing.
* **Merge dependency.** The join lines and the live exit wait for M1.3 and M1.5 Stage C. Both are larger than M1.6 and
  merge first. Stages A–C do not wait.
* **Runner load.** Laya (2.48 GB peak [V]) runs around step 8 only, as in M1.5. The tuned checkpoint has the same size
  [I]. With Jev at about 0.3 s per item and Laya on CPU at 0.2–0.5 s per item [V README], 60 items × 2 engines takes
  about 1 minute [I].

## Doc changes owed (no build line; SPEC.md is not edited here)

* **§3.2**:
  * the `sdd.scope_check` comment (module rule; `warn` = hold);
  * `verifier.evidence.*`, `verifier.s1.shadow` and `verifier.s1.max_items`;
  * the laya profile's `model:` path form, limited to `$L4_CACHE/s1/checkpoints/<id>` and gated.
* **§10.2:**
  * step 1: the scope definition (D3, D2);
  * step 3: a new test that is skipped or errored is a blocker (D5);
  * step 6: harness-owned diff coverage (`l4_cov`), with `gates.extra` still M2;
  * step 8: the shadow question sets (`file-relevant@1`, `change-covered@1`, `tests-ok@2`, `criterion-satisfied@2`).
* **L4-VER-008**:
  * `l4/s1-calibration@2` (`item`, `answer` and `label` records; the redacted state is stored);
  * the human outcome comes from `human.verdict` (it was "on merge");
  * the export moves from v1.1 to M1.6 (`l4 s1 export`).
* **A new requirement (proposed L4-VER-016)**, with a scenario: "No System-One engine output and no LLM-judge output is
  ever a training label, a selection signal or a data-selection signal for a System-One model; exports read ground
  truth only" (TypeSafe MCA §2.3(b)).
* **SC-16**: the gate is `laya-evals` on the unit-hash test split, with ECE ≤ 0.1 and per-question `min_count`. The
  comparison report sits beside it.
* **§15**: doctor S1-001, S1-002 and COV-001.
* **`docs/eval-framework.md`**:
  * §3.2: `sdd.scope_check` is no longer IGNORED once merged;
  * §5.5: the export and the human outcome gaps are closed;
  * §6.6: Laya is tuned on ground truth.
* **`docs/plan/parallel-ownership.md`**: an M1.6 section built from §Files and the contracts C-M16-1…5.

## Deviations, round 4

Decided by the orchestrator after the round 4 review. Each line names the code that carries it.

### The split of M1.6

* **M1.6a** is Stage A deterministic evidence (scope relevance, diff coverage, tests-ran: `l4/evidence/*`, `l4_cov`,
  config keys) plus the ladder join lines 12 to 14. The join is built later, after M1.5 lands on `main`; it is not
  built now.
* **M1.6b** is the S1 shadow, the export, the canary and the Laya tuning (`l4/s1/*`, `l4/llm/system_one.py`,
  `l4/llm/s1_checkpoint.py`, `scripts/s1/*`, join lines 28 to 30).

### Deviations

1. **Root-level files are unmeasured, never uncovered (M1.6a).** `coverage_sources` names directories only (the module
   directory of every changed code file), so a changed `setup.py`, `noxfile.py`, `manage.py` or a flat-layout `app.py`
   can never appear in the coverage report. Counting its lines as `unmeasured` pushed the percentage down (a false hold
   under `warn`, a false deterministic FAIL under `fail`). The rule chosen is the second branch of the task ("or else
   classified unmeasured"), not "measure when importable": the file is listed in `DiffCoverage.unmeasured_files` and in
   the report and `evidence.json`, gets no label (so no `change-covered` item) and stays out of the percentage.
   Consequence: a flat-layout project's root modules are not covered-checked at all in M1. Measuring them would need
   coverage `include` patterns next to `source`; that is deferred. Tests: `tests/unit/evidence/test_root_files.py`
   (flat `app.py`; src layout with a root `noxfile.py`, both modes).
2. **`file_of_test` resolves under a pytest rootdir that is a subdirectory (M1.6a).** A JUnit classname starts at the
   rootdir (`cd backend && pytest` gives `tests.test_a`), the git path is `backend/tests/test_a.py`. An exact candidate
   wins; else the one candidate ending in `/<module path>`; two such candidates are ambiguous and resolve to nothing
   (a missing attribution is a hold-free miss, a wrong one would be a false blocker). JUnit does not record the
   rootdir, so the suffix match replaces "resolve against the recorded rootdir".
3. **A failed gate can be scored (M1.6b).** `checkpoint_problem(require_passed=False)` accepts a checkpoint whose gate
   ran and failed (document intact, sha256s intact); only `run_score` asks for it (`open_s1_profile(allow_failed_gate=
   True)`). Role probes, shadow, `open_s1_profile` by default and the deploy script keep requiring `passed`. A gate that
   never ran is refused everywhere. Anywhere else a gate-failed profile raises `CheckpointGateFailed`: a
   `RoleUnavailable` subclass (so optional roles and the shadow still degrade to data) whose exit code is 2, not 12
   (`waiting_capacity` is retryable; this is not). The role-chain loop skips such a profile, and raises it (exit 2)
   when nothing else in the chain is usable. The score header records `gate_passed`; `build_report` refuses a header
   whose `gate_passed` differs from `gate.json`, and `render_markdown` puts **GATE FAILED** under the title.
4. **The gate flag is bound to the gate document (M1.6b).** `laya_tune.py gate` writes the document into the checkpoint
   as `gate.json` (besides `--json`) and stores its sha256 as `gate.document_sha256` in `l4-train.json`
   (`record_gate`). `checkpoint_problem`, `deploy_checkpoint.sh` and therefore `score` verify: the sha256, `passed`
   equal to the record's flag, and `checkpoint_sha256` equal to the weights recorded. A boolean flipped by hand is
   rejected. `gate.json` is excluded from the integrity listing (like `l4-train.json`) and is copied by the deploy
   script. **Old checkpoints without `document_sha256` are refused: gate them again.** Limit: someone who rewrites the
   record's flag, the document and the digest together is not detected (that needs a signature, not done).
5. **`tests-ok` is a sanity question, not a balanced one (M1.6b).** Each source unit yields exactly one `tests-ok=true`
   item by construction, so `quota_gaps` no longer applies `min_share` and `min_test` to `l4/tests-ok@2` (the target
   count and every other set stay). Two mutations were added. `add_passing_test` (a new passing test in a test file
   the unit added: one more new passing test) keeps the answer yes. `skip_old_test` (an existing test in a file the
   unit did not add is skipped) is a negative variant: since round 5 any skipped, failed or errored test makes
   `all_passed` false (question set `tests-ok@2`), although the run's exit is still green. Empty splits are a hard `l4 s1 export` error (exit 2) **even with `--allow-gaps`**;
   `--allow-gaps` still waives a missing label in calib or test.
6. **Minors (M1.6b).**
   * the report says `no tuned engine compared` instead of `ok` when no tuned engine took part in the cross-check;
   * `audit.py` imports `wilson` from the new `l4/s1/stats.py`, not from `report`; the import-graph test covers
     `audit` and `stats` (the module scan and the subprocess check);
   * a corrupt or non-manifest `manifest.json` exits 2 in `score` and `report` (`score.read_manifest`; before it
     was an internal error in `score`, and in `report` it silently lifted the gate order);
   * `items_from_evidence` reads the proposal (at `base`, like the declared scope), the code and the tests (at `head`)
     from git blobs (`collect.show_blob`), never from the worktree; its `wt` argument is gone;
   * SPEC §2.1 lists `l4 s1`; SPEC §3.2 lists `verifier.evidence.*`, `verifier.s1.shadow` and `verifier.s1.max_items`;
     `python3 scripts/check_spec.py docs/SPEC.md` exits 0; the schema oracle test no longer excludes these keys.
7. **Merge hazard (not touched now).** `require_independent_judge` in `ladder.py` is touched by M1.2 (`main`), M1.3
   (delegating stub), M1.5 and by the out-of-plan m16 commit `03eefe0` (`independence == 'none'` early return, with
   `tests/unit/verifier/test_generate.py`). Resolve it once, at the M1.6a merge.

## Deviations, round 5 (M1.6b evidence on real data, 2026-10-05)

1. **The canary reads units from every local branch.** `find_source_units(git, *refs)` walks `HEAD --branches` in
   topological order (`generate` passes them; the default stays `HEAD`). Open MR heads never reach `main`, so a clone
   of dummy-agentic at `main` gave one unit. Remote-tracking refs are not read: the operator picks the branches by
   checking them out (the archive branch is left out, since its archive commit carries the unit's trailer and would
   move the unit's head into `openspec/changes/archive/`). `py_multi` has one branch, so its units are unchanged.
   Tests: `test_source_units_on_every_local_branch_are_found`, `test_the_generator_reads_units_from_every_local_branch`.
2. **Items carry `project:<key>`, and `report` slices on it** next to `origin:` and `mutation:`, so real and synthetic
   source repositories are reported apart. Tags are metadata: not in a state, not in an item key. The gate's
   `SLICE_PREFIXES` are unchanged (a `project:` rule is a candidate, not adopted mid-run). Tests:
   `test_items_carry_their_project_key_as_a_tag`, `test_rows_are_also_sliced_by_project`.
3. **The canary's test command was overridden** for dummy-agentic (its configured `.venv/bin/python` does not exist in
   a scratch worktree, and `pricing` is a src layout without `pythonpath`): `--test-command "<harness python> -m pytest
   -q -p no:cacheprovider --junitxml=.l4-out/junit.xml -o pythonpath=src"` for both repositories.
4. **The clone is over SSH with the operator's key**, as for the M1.2 to M1.4 live runs; the Mintkey GitLab service
   is the REST API (`/api/v4`) only and was used for the read-only MR listing.
