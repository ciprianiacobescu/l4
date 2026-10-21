# M1.14 progress (branch `m114`, nothing pushed)

All 44 build lines of [m114-plan.md](m114-plan.md) are implemented. The live exit (the plan's "Live exit" section) was
**not run**: it needs the runner to be quiet and real agent logins, so there is no live baseline under `docs/live/eval/`.

## Commits (after the plan commit `12bfb76`)

| Lines | Commit |
|---|---|
| 1-4 seeds | a107a05 |
| 5-8 cell config, workspace, replay | b2b1f05 |
| 9-13 run_cell, scoring, errors, cost | a6c2d10 |
| 14-17 scorecard, env, render | 8a46c72 |
| 18-21 command, matrix, resume, files | fe05df1 |
| 22-24 idle hook, offline, warm cache | 529b36a |
| 25 integration | 0655768 |
| 26-31 compare, exit 15 | cad7fdc |
| 32-33 baseline lookup, EVAL-001 | 47db13e |
| 34-41 M1 | 34d8018 |
| 42-43 docs, SPEC | d216140 |
| follow-up test fix | see `git log` (last commit) |

## Verification (line 44), run on macOS with the machine shared with other workflows

Chunks, collected == passed + skipped + xfailed:

| Chunk | Collected | Passed | Skipped | xfailed |
|---|---|---|---|---|
| agents, availability, llm | 563 | 558 | 5 | 0 |
| verifier, implementer, gates | 1371 | 1367 | 3 | 1 |
| orchestrator, archive, state, vcs, specs | 602 | 600 | 2 | 0 |
| every other tests/unit dir + tests/unit/test_*.py | 2188 | 2183 | 5 | 0 |
| contract, scenarios, integration, live | 123 | 60 | 63 (live, `L4_LIVE` unset) | 0 |

The second chunk's first run had one failure (`test_decided_tests_chore.py` asserted the old template versions); fixed
and that file re-run green (1367 = 1366 + the fixed one). `uv run ruff check .` clean, `scripts/check_spec.py
docs/SPEC.md` clean (177 requirements, 340 scenarios, none uncovered), `l4.templatelock --write` leaves no diff,
`test_template_lock.py` and `test_recorded_versions.py` green.

## Deviations and findings

* **[U] settled**: the replay profile works through the real implement path (checked in-process with `sandbox: none`);
  under bubblewrap `--ro-bind / /` makes any path outside `/tmp` readable, so `--out` must not be under `/tmp`
  (documented in eval.md). Not exercised under bwrap (macOS).
* **[U] settled**: contract `{gate}`/`{ledger}` use `str.replace`; the phase body had no substitution, `{result_values}`
  is a `str.replace` too.
* Line 7: only the unit's own change is committed on `main` of the workspace (no other unit as a seed).
* Uv cache: a private `L4_CACHE` per cell would start `uv sync --offline` cold. The build pointed every cell at the
  shared `<L4_CACHE>/eval/uv`, which `l4 run`'s preflight refuses (outside the cell's runner cache, exit 2 on every live
  cell; found in review). Fixed: each cell gets a private, dereferenced copy at `$L4_CACHE/eval-uv`
  (`cellrun.seed_uv_cache`); `render_config(uv_cache=)` takes that path.
* A run that parks before its first push (a 429 on the first step) leaves its ledger only in the cell's worktree;
  `run_cell` reads that too (found by the integration test).
* The message of an enum failure has no `$.` prefix (`status: not one of ...`, as the code always had); the plan wrote
  `$.status`.
* The retry's `result values:` line sits inside the "previous attempt" data block, after the headline (it is the
  step's `excerpt`), not after the block.
* `tests/unit/agents/test_contract.py` did not exist; it was created as the line-40 pin.
* SPEC 2.1 had no row for `upgrade`; added, because the new `test_spec_commands.py` pins every handler.
* New `ExitCode.REGRESSION = 15`: also added to `ci map-exit` meanings; `outcome.schema.json` is unchanged (eval writes
  no outcome).
* Several tests were written and the code right after in one step (lines 5 uv_cache addition, 20-24 partly built
  with their tests in the same sitting); red was seen for the module-missing cases and for line 38 (code reverted and
  the test failed), lines 20 (4 of 7), 22, 24, 26 onwards were run red before the code except where the test passed at
  once (pins): 20 three, 23 four of five, 40 all (already satisfied), 3 and 4 seeds (the seed data existed first).
* Not done: the live exit (warm cache, per-profile cells, magnitude cell, committed scorecards under `docs/live/eval/`).
* Findings of the golden: a scripted wrong-status result costs one attempt and gives one `schema` error in the cell.

## Adversarial review (2026-10-07), fixes `m1.14(fix): ...`

Each fix was test-first (the new test seen failing for the stated reason, then the code):

* **Blocker, uv cache** (`8c5307e`): every live cell exited 2 at `l4 run`'s preflight (the shared uv cache was outside
  the cell's `L4_CACHE`) and scored `fail`. Shown with an in-process smoke that keeps the rendered config; the
  integration test now keeps the rendered `caches` too. After the fix the smoke passes a cell with a real
  `uv sync --frozen --offline` from the private copy, and a cold cache is `invalid: setup_offline_cache_cold`.
* **Harness exits** (`d9e8a60`): an `l4 run` exit 1, 2 or 3 is `invalid: harness_error`, not a failure of the model.
* **Gate on missing data** (`087a7dc`): an incomplete scorecard is refused, a comparison with no rated row exits 2
  (nothing compared) instead of 0, `--baseline-dir` never picks the new scorecard (or a copy) as its own baseline, and a
  newly missed defect regresses also when the baseline's cell was invalid or the profile is otherwise unrated.
* **Resume** (`9364b74`): an `invalid` cell (busy runner, 429, harness error) runs again; a cell measured in another
  environment (`env_sha256` in `result.json`) is not reused; untracked files do not make the harness dirty.
* **Small** (`fef054d`): `--max-drop` outside 0..1 (and nan) is exit 2; `.DS_Store` is never a seed.
* **M1** (see `git log`): the phase hint and the values line read the phase names from the schema's `phase` enum.
