# M1.14 — `l4 eval`, the regression gate, and the magnitude status enum (planned 2026-10-07)

## Goal

The handbook review (`docs/research/08-understanding-harness-engineering.md`, HB-X8, section 16 "harness changes alter
quality" and section 39 "every component is a hypothesis to re-test") found that no template change, CLI pin bump or
profile change is ever measured: the free-model measurement of 2026-10-06 (`docs/free-resources.md`,
`docs/live/free/`) was a one-off set of shell scripts. M1.14 turns that method into a command and a gate, and fixes
the one defect the method exposed in the last live run (magnitude-qwen wrote `"status": "red"`, the phase name, in 2
of 3 red attempts, `docs/live/magnitude/`, `docs/live/m113/`). Harness `main` is at `d475e6b`. **44 build lines**, test
first: each new test is seen failing for the stated reason before the code is written; a line that passes at once is a
pin and is recorded as `already satisfied`.

* **E1** `l4 eval`: a fixed seed set run through the real implement and verify paths, one profile at a time per role,
  scored into a scorecard (JSON and markdown) that records enough environment to be compared (handbook section 38).
* **E2** `l4 eval --compare <old scorecard>`: per-profile deltas, a non-zero exit when a pass rate drops past a
  threshold, and the practice of running it on template bumps and CLI pin bumps (SPEC 20, template lock).
* **M1** the implementer result prompt shows the allowed `status` values next to the phase line, and the retry prompt
  after `result invalid` carries the validation error and the allowed values.

Labels: [V] read in code or files at `d475e6b`; [I] inferred; [U] not checked (a build line settles it first).

## Decisions

* **D1 Seeds live in this repository, under `tests/eval/seeds/`, not on a pinned dummy-agentic ref.** The dummy is on
  GitLab (network, a runner, a moving `main`), its history carries units that already have branches and MRs, and the
  free run had to push a non-actionable seed branch to it to stay clear of a live session [V `docs/live/free/README.md`].
  In-repo seeds are offline, versioned with the harness, hashable (`seed_set_sha256`), and need no write access to any
  project. The cost is that the toy base project is a copy of the dummy's pattern, not the dummy itself. The three
  free-run units (`docs/live/free/seeds/`: `add-shelf-code`, `add-tip-amount`, `add-reorder-quantity`) are copied in,
  so their recorded results are the first comparison point.
* **D2 A cell is one fresh run.** A cell is (role, profile, unit, k-index): a fresh `git clone` of a local bare
  mirror of the seeded base, a rendered scratch config with `forge.type: local` and `ci.platform: local` (the
  `docs/live/free/tools/cfg.tmpl.yaml` pattern), a private `L4_CACHE`, then the real `l4 run --unit openspec:<id>` as a
  child process. The adapter, bubblewrap, gates, ladder, independence and ledger code paths are the production ones;
  only the forge is the in-memory `LocalForge` [V `forge/local.py`]. The scorecard reads the child's ledger and
  `outcome.json`, never its own timers except for wall time.
* **D3 One profile at a time per role.** An implementer cell sets the implementer chain to `[P]` with no fallback, so
  a 429 is an error in the scorecard and not a silent switch to another model. A judge cell sets the judge chain to
  `[J]` and nothing else. A judge cell needs a unit already implemented: the seed carries a *reference
  implementation* (the files of a known red and a known green commit) that a deterministic `command` profile
  (`python -m l4.eval.replay`) writes through the real implement path, so the commits, trailers and ledger are
  harness-made [I; line 8 settles it].
* **D4 The designed-defect unit** is `add-late-fee`, modelled on the shipping-fee case (the recorded implementation
  ignores the order subtotal, so one criterion is not met; expected judge verdict `NEEDS_HUMAN`, recorded results in
  `docs/live/free/README.md`). It is judge-only: its reference implementation is the defective one, and no implementer
  is scored on it.
* **D5 A cell's outcome has three kinds, and only two count.** `pass`/`fail` count towards a pass rate. `invalid`
  (HTTP 429, endpoint unavailable, vendor veto, missing login, runner busy, time-out of the cell) does not: it is
  listed with its error and excluded from the rate, so a rate-limited free model is not read as a regression.
  `compare` refuses to gate on a profile whose `invalid` share is above half of its cells.
* **D6 The expected verdicts are data, recorded with the seed**: `expected.json` per unit holds `implementer:
  {outcome: pass}` and `judge: {verdict, min_findings?}`. Changing one is a seed-set change and changes
  `seed_set_sha256`, so the gate refuses to compare across it (line 33).
* **D7 Exit code 15, `REGRESSION`**, is new: a gate that exits 1, 2 or 3 would read as a harness fault (SPEC L4-CLI-001,
  [V `exitcodes.py`: 1 internal, 2 usage, 3 doctor, 10 to 14 designed stops]). 15 enters `SEVERITY_ORDER` after 14 and
  stays out of `CI_ALLOWED`.

## Facts this plan rests on

* **M1 root cause, two paths** [V]. A prompt-contract adapter (opencode, kiro-cli, command) validates the result file in
  `agents/contract.py::attach_file_result` against the schema, so an invalid result becomes
  `RunResult.status = "error"` with `detail = "result invalid: " + "; ".join(problems[:3])`, and `implementer/tdd.py`
  (line 521) turns it into `the agent step ended with status error: result invalid: ...`. A native adapter's result goes
  through `implementer/result.py::parse_result` and gives `the agent's result is invalid: ...` (line 526).
* **The validation message names no allowed value** [V `schemacheck.py:51`]: `$.status: not one of the allowed values`.
  `implementer-result.schema.json` has `status` in `done | blocked | failed | partial` and `phase` in
  `red | green | single`, which is how a model that has just read `# Phase: RED` writes `status: "red"`.
* **The result schema sits at the very end of the prompt** [V `implementer/prompt.py:185-187`: `# Output`, compact
  `json.dumps` of `RESULT_SCHEMA`], far from the `# Phase:` line of the phase template.
* **The retry carries the headline and no excerpt for these failures** [V]. `loop.py::run_task` feeds `failure =
  outcome.reason` and `excerpt = outcome.excerpt` to `_retry_reason`; `tdd.py` lines 776, 801 and 1059 build
  `RedOutcome("failed", step.reason)` and `GreenOutcome("failed", step.reason)` without `excerpt=`. M1.11 W1 built the
  excerpt for gate failures only (`implementer/excerpt.py`). So the retry prompt shows the headline in the `previous
  attempt` data block, and nothing else. The headline is right but has no allowed values.
* **Template lock** [V `templatelock.py`, `tests/unit/test_template_lock.py`]: a body change without a version bump
  fails; `uv run python -m l4.templatelock --write` regenerates `templates.lock.json`. Current versions: contract 7, red
  5, green 3, single 2, single_tests 3, judge 6, clarifier 4, testwriter per kind.
* **Environment record sources** [V]: `templatelock.current()` (versions and sha256 of every prompt),
  `recordedversions.load()` (the CLI versions with recorded fixtures), `versions.parse_version` (CLI `--version`
  output), `buildinfo.harness_commit()` (None in a checkout: `git rev-parse HEAD` is used instead).
* **Free-run scripts to reuse** [V `docs/live/free/tools/`]: `driver.sh` (fresh copy of a seeded origin per run, idle wait,
  429 stops the queue, `timeout 50m`), `summarize.py` (ledger events `step.finished`, `agent.finished`,
  `verify.judge`, `verify.verdict`, `budget.cost`), `cfg.tmpl.yaml`. The eval re-implements their approach in Python
  under test; it does not shell out to them.
* **Runner rule** (operator): a cell on the runner starts only when the runner is quiet, because another workflow runs
  sample-consumer CI jobs there. Line 22 gives the harness a hook for that; the check script itself stays outside
  the repository.

## Build lines

Each line is `n. [SPEC id] test first (the failure seen) -> build`. Paths are under `src/l4/` unless they start with
`tests/` or `docs/`.

### E1 `l4 eval`

**Seeds**

1. **[L4-EVAL-001, SCN-EVAL-01]** `tests/unit/eval/test_seeds.py`: `load_seed_set(tests/eval/seeds)` returns the base
   project and 4 units, each with a `proposal.md`, a `tasks.md` with one task, a spec delta with exactly 2 scenarios
   and distinct WHENs, an `expected.json` and a `reference/` of red and green files (red: ImportError, the module is
   absent) -> `eval/seeds.py` (dataclasses `SeedUnit`, `SeedSet`), the 3 free-run units copied from
   `docs/live/free/seeds/`, the new `add-late-fee`, and the base project (a dependency-free pricing toy,
   `pyproject.toml` with pytest only).
2. **[L4-EVAL-001]** same file: `seed_set_sha256` is a sha256 over the sorted relative paths and bytes of the seed
   directory, so it changes when a byte of `expected.json` changes and not when the directory is copied (red: no
   function) -> `eval/seeds.py::seed_set_sha256`.
3. **[L4-EVAL-002, SCN-EVAL-02]** `tests/unit/eval/test_seed_validity.py`: every unit passes the harness's own OpenSpec
   detector and `tasks` parser; every criterion has a scenario; `expected.json` validates against
   `eval/expected.schema.json`; the base project's gate command (the `gates.test` of the scratch config) is green on
   the base and each unit's reference green, and red on the reference red (red: the reference files do not exist yet)
   -> reference files per unit; the schema. This is the guard that a seed cannot rot into an unsolvable unit.
4. **[L4-EVAL-003]** `tests/unit/eval/test_defect_unit.py`: the `add-late-fee` reference green passes its own written
   tests (so the gates are green) and fails the second scenario when run against a reviewer's hidden check
   (`reference/hidden_check.py`, never copied into the worktree): the defect is real and deterministic, not left to a
   judge's reading (red: no unit) -> the unit and `hidden_check.py`; `expected.json` records `judge.verdict:
   NEEDS_HUMAN`.

**Cells and config**

5. **[L4-EVAL-004, SCN-EVAL-03]** `tests/unit/eval/test_cellconfig.py`: `render_config(base_cfg, role, profile,
   ref_judge, ref_impl)` returns a config whose implementer chain is exactly `[P]` for an implementer cell and whose
   judge chain is exactly `[J]` for a judge cell, with `forge.type: local`, `ci.platform: local`, `s1_judge: []`,
   `verifier.s1.enabled: false`, `verifier.max_fix_rounds: 0`, `clarifier.s1_standin: none`; it never carries a
   fallback profile; a profile missing from `--config` raises a usage error naming it (red: no module) ->
   `eval/cellconfig.py`. The values are the ones the free run set by hand [V `docs/live/free/README.md`].
6. **[L4-EVAL-004]** same file: the implementer's vendor equal to the judge's vendor makes the cell `invalid:
   vendor_veto` before anything starts, with no agent call, and a profile whose vendor is undeclared is `invalid:
   vendor_unknown`; the reference profile `eval-reference` declares vendor `eval-reference` so it never vetoes a
   judge -> `eval/cellconfig.py::precheck`.
7. **[L4-EVAL-005]** `tests/unit/eval/test_workspace.py`: `make_workspace(seed, unit, dir)` builds a bare mirror and a
   fresh clone per call, commits the base with the committer identity of the repo's git config, and leaves the unit's
   OpenSpec change on `main` as a non-actionable seed for any other unit (two calls do not share a `.git`; a clone's
   `origin/main` hash equals the first call's for identical inputs; red: no module) -> `eval/workspace.py`. Seeds are
   committed with fixed author and committer dates so two runs hash alike.
8. **[L4-EVAL-006, SCN-EVAL-04]** `tests/unit/eval/test_replay.py` and `test_judge_cell_setup.py`: the `eval-reference`
   `command` profile (`python -m l4.eval.replay`) writes the unit's reference red files, then green files, on the two
   implement steps and a valid result JSON each time; `l4 run` with only that profile takes the unit to `verifying`
   with trailers and ledger of a normal run (red: no replay module). If the command adapter's sandbox cannot read the
   seed directory or the step cannot call it twice (the [U] of D3), the replay copies the reference into
   `agent-tmp` before the step and the line is re-planned in the progress file, not skipped -> `eval/replay.py`.
9. **[L4-EVAL-007]** `tests/unit/eval/test_cellrun.py`: `run_cell` builds the workspace and config, calls an injected
   `runner(argv, env, cwd, timeout)` and returns `CellRaw(returncode, ledger_events, outcome_json, log_text, wall_s)`;
   `L4_CACHE` is a path under the cell directory; a runner that raises `TimeoutExpired` gives `invalid: cell_timeout`
   and keeps the log; nothing under the repository's own `.l4` or the user's real cache is touched (red: no module) ->
   `eval/cellrun.py`. The injected runner keeps every unit test offline and fast.

**Scoring**

10. **[L4-EVAL-008, SCN-EVAL-05]** `tests/unit/eval/test_score_impl.py`: `score_implementer(events, expected)` from
    hand-written ledgers returns `outcome pass` when red and green both ended `ok`, `fail` (with `halted_at: red|green`
    and the breaker reason) after `breaker.tripped`, and `attempts: {red: n, green: n}` counted from `task.attempt_failed`
    plus the one that ended the phase; a `blocked` result is `fail` with `blocked: true` (red: no scoring) ->
    `eval/score.py`.
11. **[L4-EVAL-008, SCN-EVAL-06]** `tests/unit/eval/test_score_judge.py`: `score_judge(events, expected)` returns the
    verdict from `verify.verdict`, `agreement: true|false` against `expected.judge.verdict`, the finding count and the
    worst severity, and the schema-invalid replies as errors; an unparsable judge reply (as Nemotron 3.5 Lightning gave
    twice per unit) is `fail` with `error: schema`, not `invalid` (red: no scoring) -> `eval/score.py`. A judge that
    holds back a deliberately defective unit scores as agreement, a judge that PASSes it as a miss.
12. **[L4-EVAL-009]** `tests/unit/eval/test_errors.py`: error classes `schema` (`result invalid`, schema-invalid judge
    reply), `rate_limit` (`api_status` 429 or the limit statuses of `RoleLimit`), `unavailable` (400 "Endpoint is
    unavailable", 403 geo block), `timeout` (agent status `timeout` or the cell timeout), `login` (auth failure),
    `other`; each from a recorded ledger line or log excerpt, with the redactor applied to the detail kept in the
    scorecard (red: no classifier) -> `eval/errors.py`. `rate_limit`, `unavailable`, `login` and the cell timeout make a
    cell `invalid` (D5); `schema` and an agent `timeout` count as failures.
13. **[L4-EVAL-010]** `tests/unit/eval/test_cost.py`: cost is the sum of `budget.cost{usd}` plus judge and clarifier
    costs from the ledger, `null` (not 0) for a cell whose agent reports none, and `0.0` only for a profile declared
    free in its options; tokens summed from `agent.finished` (red: no module) -> `eval/score.py::cost_of`.

**Scorecard**

14. **[L4-EVAL-011, SCN-EVAL-07]** `tests/unit/eval/test_scorecard.py`: `build_scorecard(cells, env, seeds)` is
    deterministic: the same cells in any order give byte-identical canonical JSON (sorted keys, cells sorted by role,
    profile, unit, k, no wall-clock timestamp inside the body except `env.started_at`, which is excluded from
    `scorecard_sha256`); it validates against `eval/scorecard.schema.json` (`l4/eval-scorecard@1`) (red: no module)
    -> `eval/scorecard.py`.
15. **[L4-EVAL-011]** same file: the per-profile aggregate holds, per (role, profile): `cells`, `pass`, `fail`, `invalid`,
    `pass_rate = pass / (pass + fail)` or `null` when that is 0, `median_wall_s`, `attempts_mean` per phase,
    `agreement_rate` (judge), `cost_usd` total or `null`, and `errors` counted by class; a profile with 2 pass, 1 fail
    and 1 invalid gives `0.6667` (rounded to 4 places) and `invalid: 1` (red: no aggregate) -> `eval/scorecard.py`.
16. **[L4-EVAL-012, SCN-EVAL-08]** `tests/unit/eval/test_env.py`: `capture_env(...)` records `harness_commit` (`git
    rev-parse HEAD` plus `dirty: true|false`, or `buildinfo.harness_commit()` when vendored), `templates` (the output of
    `templatelock.current()`), `templates_lock_sha256`, `cli_versions` (each used profile's CLI `--version` through the
    adapter's own probe, parsed with `versions.parse_version`, and whether `recordedversions.unrecorded` flags it), the
    profiles' `model` and `vendor` and options (no `auth` secrets, no env values), `seed_set_sha256`, `k`, the
    cell timeout, and the machine class (`platform.platform()`, CPU count, a `runner: true|false` flag from `--runner`)
    (red: no module) -> `eval/env.py`. No value of an environment variable enters the scorecard (Redactor test with a
    planted secret).
17. **[L4-EVAL-013]** `tests/unit/eval/test_render.py`: `render_markdown(scorecard)` is pure and golden-tested: a header
    with the environment, the per-profile table (role, profile, pass rate, agreement, attempts, median wall, cost,
    invalid, errors), then one line per cell with the verdict and the error class; cells with `invalid` are listed
    under their own heading so a reader sees why a rate is based on fewer cells (red: no module) ->
    `eval/render.py`.

**Command**

18. **[L4-EVAL-014, SCN-EVAL-09]** `tests/unit/cli/test_eval_cli.py`: `l4 eval --config <profiles.yaml> --impl P1
    [--impl P2] --judge J1 [--judge J2] --ref-judge R [--unit <id>] [--k N] --out <dir> [--cell-timeout 50m] [--runner]`
    parses; `--impl` and `--judge` repeat; at least one of them is required, and `--ref-judge` is required when
    `--impl` is given (an implementer cell ends in a verdict by a fixed judge, otherwise "pass" could not be told from
    "wrote something"); an unknown unit id is a usage error (exit 2) (red: `HANDLERS` has no `eval`) -> `commands.py`
    `"eval": "l4.eval.run:run_eval"`, `cli.py` `_SPECS` entry, `OWNING_CHANGE`, `eval/run.py` option parsing.
19. **[L4-EVAL-014]** `tests/unit/eval/test_run_matrix.py`: the matrix is implementer cells (profile x unit x k, units
    that are not judge-only) then judge cells (profile x unit x k), run strictly one cell at a time (no concurrency: a
    parallel run would change wall time and the runner's load), each cell's directory under `<out>/cells/<role>-
    <profile>-<unit>-k<n>/` holding `cfg.yaml`, `run.log`, the ledger copy and `result.json`; `--dry-run` prints the
    matrix and writes nothing (red: no runner loop) -> `eval/run.py`.
20. **[L4-EVAL-015, SCN-EVAL-10]** same file: a `rate_limit` or `unavailable` cell marks the profile blocked for this run
    and the remaining cells of that profile are written as `invalid: skipped_after_rate_limit` without starting (the
    behaviour of `driver.sh`'s `blocked-models`), and a second `--resume` run with the same `--out` skips cells that
    already have a `result.json` with the same `cell_key` and `seed_set_sha256` and runs the rest (red: no skip) ->
    `eval/run.py`.
21. **[L4-EVAL-016]** `tests/unit/eval/test_run_files.py`: `<out>/scorecard.json` and `<out>/scorecard.md` are written
    atomically after every cell (a killed run leaves a valid partial scorecard with `complete: false`), `scorecard.json`
    is the only file `--compare` reads, and no file under `<out>` holds a raw prompt or an unredacted log tail (the
    redactor runs over each kept `run.log` first) (red: no writer) -> `eval/run.py`.
22. **[L4-EVAL-017]** `tests/unit/eval/test_idle_hook.py`: `--idle-check <argv>` runs before each cell with no shell;
    exit 0 starts the cell, any other exit waits (injected sleep, `--idle-wait 30m` bound) and past the bound the cell
    is `invalid: runner_busy` and the run stops (the stop is exit 12, waiting for capacity); the hook's output is
    never forwarded to the scorecard beyond its exit code (red: no hook) -> `eval/run.py`. The repository's own check
    is `scripts/dev/l4_idle.py`, passed by the operator; the harness does not import it.
23. **[L4-EVAL-018, SCN-EVAL-11]** `tests/unit/eval/test_offline.py`: with a socket-denying fixture, building the
    matrix, rendering configs, scoring, writing the scorecard and `--compare` open no socket; the only network in a real
    run is the agent CLIs' own, and `--dry-run` proves it by running none (red: no check) -> a guard fixture and a
    `no network from the harness` comment at the eval entry. The scratch config uses `gates.setup: uv sync --frozen
    --offline`, so a cell never reaches an index; a cold cache is `invalid: setup_offline_cache_cold` with the one-line
    fix `l4 eval --warm-cache`, which is the only eval path allowed to use the network (line 24).
24. **[L4-EVAL-019]** `tests/unit/eval/test_warm.py`: `l4 eval --warm-cache` runs `uv sync --frozen` once in the base
    project of the seed set into `L4_CACHE`'s eval area and nothing else; it is refused together with `--impl`/`--judge`
    (red: no flag) -> `eval/run.py`.
25. **[L4-EVAL-020, SCN-EVAL-12]** `tests/integration/test_eval_fake.py`: an end-to-end run with the scripted `fake`
    adapter [V `agents/fake.py`: `Step(writes=…, structured=…)`] as the implementer and a scripted judge: a seed unit
    goes red, green, verdict PASS; a scripted wrong-status result (`status: "red"`) is a `schema` failure that then
    succeeds on the retry; a scripted 429 gives `invalid`; `scorecard.json` matches a golden file after masking
    `wall_s` and `env.started_at`, and no real CLI is started (red: no integration path) -> any remaining wiring.

### E2 Regression gate

26. **[L4-EVAL-021, SCN-EVAL-13]** `tests/unit/eval/test_compare.py`: `compare(old, new, max_drop)` returns per (role,
    profile) `old_rate`, `new_rate`, `delta`, `agreement_delta`, `attempts_delta`, `wall_delta_pct`, `cost_delta`, and a
    `status` of `ok`, `regressed`, `improved`, `new`, `gone` or `unrated`; `regressed` when `old_rate - new_rate >
    max_drop` (strictly greater) (red: no module) -> `eval/compare.py`. The default `--max-drop` is `0.20`: with 4 units
    and k=1 one lost cell is 0.25 and fails, and the doc says what that sample size can and cannot see.
27. **[L4-EVAL-021]** same file: a judge profile also regresses when `agreement_rate` drops by more than `max_drop`, or
    when it passes the designed-defect unit that the old scorecard held back (a missed defect is a regression at any
    threshold) (red: no judge rule) -> `eval/compare.py`.
28. **[L4-EVAL-022]** same file: only cells present in both scorecards enter the rate (matched by `cell_key` =
    role, profile, unit, k), so a profile that lost its rate-limited cells is not compared on the others; a profile whose
    `invalid` share is above half in either scorecard is `unrated` and does not fail the gate, and is printed as such
    (red: no matching) -> `eval/compare.py`.
29. **[L4-EVAL-023, SCN-EVAL-14]** `tests/unit/eval/test_compare_env.py`: the delta report starts with an environment diff:
    harness commit, each template whose version or sha256 differs, each CLI version, model, the profile options, the
    machine class; a changed `seed_set_sha256` or `scorecard schema` is refused (exit 2, "the scorecards measure
    different seed sets") unless `--allow-seed-change` is passed, in which case no `regressed` status is reported, only
    deltas (red: no diff) -> `eval/compare.py`.
30. **[L4-EVAL-024, SCN-EVAL-15]** `tests/unit/cli/test_eval_compare_cli.py`: `l4 eval --compare <old> [--new <file> | runs
    and then compares]`; with `--new` it reads two files and runs no agent; the printed report is the markdown of the
    deltas, `--json` prints the machine form; the exit is 0 when nothing regressed, 15 when a profile `regressed` or a
    defect was newly missed, 2 for a missing or invalid file (red: no exit code) -> `exitcodes.py` (`REGRESSION = 15`,
    added to `SEVERITY_ORDER` after 14, absent from `CI_ALLOWED`), `eval/run.py`. `tests/unit/cli/test_exitcodes.py`'s
    severity and allowed tables are updated in the same commit, and `ci map-exit` maps 15 to itself.
31. **[L4-EVAL-024]** same file: a run of `--compare` where an old scorecard's profile is absent in the new run (the
    operator evaluated a subset) prints `gone` for it and does not fail; `--require-all` makes `gone` a failure (red:
    no flag) -> `eval/compare.py`.
32. **[L4-EVAL-025]** `tests/unit/eval/test_baseline_ref.py`: `--compare` accepts a path, and `--baseline-dir <dir>`
    picks the newest `scorecard.json` there whose `seed_set_sha256` matches; with none it exits 2 with the sentence "no
    baseline for this seed set: run `l4 eval ... --out <dir>` and commit the scorecard" (red: no lookup) ->
    `eval/compare.py`. Baselines are committed under `docs/live/eval/` by the operator after a live run, never
    generated in CI.
33. **[L4-EVAL-026]** `tests/unit/eval/test_doctor_row.py`: `l4 doctor` gets a warning (not a failure) row `EVAL-001`
    when `docs/live/eval/` holds a baseline whose `templates` differ from `templatelock.current()`: "a template changed
    since the last eval baseline: run `l4 eval --compare`" (red: no row) -> `doctor/` row, in the style of the existing
    ENV rows. It is a reminder, never a gate, so a template bump never turns doctor red.

### M1 Magnitude status enum

34. **[L4-IMP-004 amend, SCN-IMP-M1]** `tests/unit/implementer/test_result_values_line.py`: rendering a red prompt with
    `result_path` set contains a line `result values: ...` immediately after the `# Phase: RED` section (no other
    section between them) that names `status` as one of `done | blocked | failed | partial` and `phase` as `"red"`,
    and says `status` is never the phase name; the same for green (`"green"`) and single (`"single"`, `single_tests`);
    the values come from `RESULT_SCHEMA` (a test swaps the schema's enum and the line follows), never from a literal
    (red: no line) -> `implementer/prompt.py::result_values_line(schema, phase)` and a `{result_values}` placeholder in
    `templates/red.md`, `green.md`, `single.md`, `single_tests.md`. Whether the renderer substitutes by `str.replace` or
    `format` is [U] and is read first.
35. **[L4-IMP-004 amend]** same file: a native adapter (`result_path` None, the schema enforced by the CLI) gets the same
    line, because the values are true for it and the line is one sentence; the `# Output` section is unchanged for both
    (red: line absent) -> `implementer/prompt.py`. The dynamic part is the schema read, so a later enum edit cannot
    leave the prompt stale.
36. **[L4-IMP-004 amend]** `tests/unit/test_template_lock.py` (existing) fails on the template body change as the lock
    requires (red: body changed, version unchanged) -> bump `red.md` to 6, `green.md` to 4, `single.md` to 3,
    `single_tests.md` to 4 (the `contract` template is not edited), then `uv run python -m l4.templatelock --write`.
    `tests/unit/implementer/test_prompt.py` golden sections are updated in the same commit.
37. **[L4-IMP-008 amend, SCN-IMP-M2]** `tests/unit/test_schemacheck.py`: an enum failure reads `$.status: not one of the
    allowed values (done, blocked, failed, partial)`, built from the schema's own constants, so no agent-written value
    enters the message (red: the message names no value) -> `schemacheck.py`. The agent's own bad value is not echoed,
    because the message goes into a prompt and a ledger and the existing rule is "names paths, never values"
    [V `implementer/result.py:25`]. A test pins that a 10,000-character bad value does not appear.
38. **[L4-IMP-008 amend]** `tests/unit/implementer/test_result_retry.py`: a scripted adapter that writes `status: "red"`
    and then a valid result: the second prompt's `previous attempt` data block contains `result invalid` and `$.status:
    not one of the allowed values (done, blocked, failed, partial)`, and, after the block, the `result values:` line of
    line 34 again, for both the prompt-contract path (`agents/contract.py` detail, tdd line 521) and the native path
    (`parse_result`, line 526) (red: only the headline is carried, and no values) -> `implementer/tdd.py`: a
    `StepOutcome("failed", ..., excerpt=result_values_line(...))` for both reasons, and `RedOutcome`/`GreenOutcome` lines
    776, 801, 1059 pass `excerpt=step.excerpt`. This extends M1.11 W1's excerpt path, which covered gate failures only.
39. **[L4-IMP-008 amend]** same file: the ledger's `task.attempt_failed` still holds the headline only and
    `excerpt_lines` counts the added line; the excerpt itself is not committed (the existing rule that an excerpt is
    agent-influenced output, here it is harness text, and stays out of the ledger for symmetry) (red: `excerpt_lines`
    is 0) -> nothing new beyond line 38.
40. **[L4-IMP-008 amend]** `tests/unit/agents/test_contract.py` (existing): the three `result invalid:` details (not JSON,
    not an object, schema problems) keep their text and `result missing:` is untouched, so the contract tests of the
    three adapters and the recorded fixtures stay green (pin, expected `already satisfied`) -> none.
41. **[SCN-IMP-M3]** `tests/unit/implementer/test_status_is_phase.py`: a result whose `status` equals its `phase` name
    gets, in the reason only, the sentence `status is the outcome of the step (done, blocked, failed, partial); "red"
    is the phase and belongs in "phase"` (red: the generic message only), and a result whose `status` is any other
    unknown word does not (the hint is for the observed mistake) -> `implementer/result.py::parse_result` and
    `agents/contract.py` share one `phase_hint(parsed)`.

### Docs, practice, close

42. **[L4-EVAL-027]** `docs/eval.md`: what the eval measures and what it does not (4 units, k=1, one environment: it
    sees a lost cell and a missed defect, not a 5 point drift); the seed layout; how to add a unit (and why that changes
    the gate's baseline); the exact command lines for a free-model implementer run and a judge run; the runner rule
    (use `--idle-check` with `scripts/dev/l4_idle.py`, run as `gitlab-runner`, never copy or refresh CLI logins, never
    print the Mintkey secrets `magnitude-api-key` and `typesafe-jev-api-key`); and the **practice**: run `l4 eval
    --compare docs/live/eval/<baseline>/scorecard.json` (a) on every bump of a template version, (b) on every CLI pin
    bump (`recorded_versions.json`, `docs/runner/README.md`), (c) before removing a free model from a chain, and commit
    the new scorecard as the next baseline when the gate passes or the regression is accepted with a note.
43. **[SPEC 2.1, 20 amend]** `docs/SPEC.md`: a row for `l4 eval` in 2.1, the new exit code 15 in L4-CLI-001's table, a
    new item 6 in section 20 (the eval set and the regression gate) beside the template-lock item 3, and in item 3 the
    sentence "a template change that passes the lock is not thereby shown to be no worse: run `l4 eval --compare`";
    `src/l4/templatelock.py`'s docstring gets the same pointer; `docs/research/08-understanding-harness-engineering.md`
    HB-X8 row gets "built in M1.14 (tier I and J, k and ablations still open)"; `docs/free-resources.md` section 11.2
    gets a pointer to `docs/eval.md` for repeating the magnitude measurement. A grep test pins that every command in
    `HANDLERS` has a row in 2.1 (`tests/unit/test_spec_commands.py`, red when `eval` is missing).
44. **[close]** `uv run pytest -q` (in the tool's background mode, not piped into `tail` in an `&&` chain), `uv run ruff
    check .`, `uv run python -m l4.templatelock --write` clean, `tests/unit/test_template_lock.py` and
    `tests/unit/test_recorded_versions.py` green, then `docs/plan/m114-progress.md`. The branch is `m114` in
    `/Users/USER/src/l4-wt/m114`; nothing is pushed.

## Coverage

| Item | Lines |
|---|---|
| E1 fixed seed set, expected verdicts, designed defect | 1-4 |
| E1 one profile per role, real code paths, local forge | 5-9, 25 |
| E1 per-cell scoring: pass/halt, attempts, wall, verdict, agreement, errors, cost | 10-13 |
| E1 scorecard JSON and markdown, environment record (handbook 38) | 14-17 |
| E1 command, matrix, resume, 429 stop, offline, idle hook | 18-24 |
| E2 deltas, threshold, exit code, env diff, baselines | 26-32 |
| E2 doctor reminder and the written practice | 33, 42, 43 |
| M1 allowed values next to the phase line, templates bumped | 34-36 |
| M1 retry carries error and allowed values (both result paths) | 37-41 |
| close | 44 |

## Live exit (not a build line; the orchestrator runs it when `l4_idle.py` says quiet)

1. `l4 eval --warm-cache`, then one implementer cell per free profile of the 2026-10-06 run (Muse Spark, Big Pickle,
   MiMo, Nemotron 3 Ultra, LongCat, Space Bunny) with `--ref-judge laya-local`, and the judge cells of the same
   profiles on the 4 units. The recorded results of that run (6 of 8 passed red and green on attempt 1; all 6 judges
   agreed on `add-shipping-fee` NEEDS_HUMAN) are the expectation, and any difference is reported as a finding, not
   adjusted away.
2. One magnitude-qwen implementer cell after the M1 prompt change, to see whether the enum error disappears (2 of 3 red
   attempts wrote `status: "red"` before). A single cell is an observation, not a rate.
3. Commit the scorecards under `docs/live/eval/<date>/` and run `l4 eval --compare` of the run against itself (exit 0)
   and against a copy with one profile's passes edited down (exit 15), to prove the gate on real files.

## Not in this plan

* Hidden held-out acceptance tests for the implementer (HB-X8 tier I as the handbook states it) and replay of
  human-labelled live units for the judge and clarifier: both need maintainer-written oracles. Line 4's
  `hidden_check.py` is the one exception, for one unit.
* `--k` above 1 is built (line 18) but statistics (confidence intervals, a significance test) are not: the gate is a
  threshold on a rate, and the doc says so.
* Ablation flags, a clarifier eval, a fix-loop eval, and CI scheduling of the eval.
* A fallback chain inside a cell (D3).
