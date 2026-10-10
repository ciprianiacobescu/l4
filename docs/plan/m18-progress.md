# M1.8 progress (easy adoption)

Build of `docs/plan/m18-plan.md`, branch `m18`, from `e6dbea2` (plan) on `8f604a5`. Commits carry no trailers and are
authored by the configured identity. "Seen fail" means the test was run before the code and failed (a missing module
counts for the new files). Line 4 is a pinning test: its behaviour came from line 3, so it passed at first run (the
orchestrator and planner needed no code). Nothing was pushed.

| line | commit | note |
|---|---|---|
| 1 R1 red advice by exception kind | 6f79d4b | import errors, `TypeError`, others; each advice once |
| 2 R2 per-phase attempts | 4cf4c0c | `breaker.tripped{phase}`, halt reason names the phase; SPEC L4-IMP-008 |
| 3 R4 chain with no cool-down is due now | 0d46a41 | `WaitingCapacity.unready`; a limit keeps its reset; the old "default cool-down" test now says due now |
| 4 R4 end to end | 366d346 | tests only (see above) |
| 5 R5 `availability.unavailable` | 5d31cda, 12efbb1 | also for an optional role; one factory test expected no event on a failed selection and was updated |
| 6, 7 R5 `exit_reason`, R3 "Waiting for capacity" note | 7e379bf | `_park`; cleared by `CAPACITY_RESTORED`; the stub-based `test_park_retry.py` gained the fields `_park` now reads |
| 8 R6 title dedupe | d0d4505 | `proposal_title(unit_dir, name)` |
| 9 A6 `extra_` keys | f172a30 | `tdd.extra_test_globs`, `tdd.extra_test_support_globs`, `odd.extra_forbidden_paths`; SPEC 3.2 block and L4-CFG-001 |
| 10 A6 CFG-005 | df53f17 | |
| 11 A7 step 8 | 9dd9f06 | `not_run` without a `backend: system-one` profile; preflight text |
| 12 A4 scopes, `--adoption`, `--no-gates` | bd0b10e | `doctor_scopes()`; `--no-gates` alone is exit 2 |
| 13 A5 init and an ignored `.serena/` | 4cdf887 | `src/l4/memory/ignore.py`, uses `git check-ignore -v` |
| 14 A5 MEM-002 | 9c619b6 | the carve-out is applied to a real `.gitignore` and checked with real git |
| 15 A11 job reader, CI-002 | f6efa57 | `src/l4/ci/gitlab_jobs.py` (also used by `merge_include` and `setup gitlab`) |
| 16 A3 `dry_run_gates` | ca4cd43 | detached worktree of HEAD under `$L4_CACHE/adoption/<sha12>`, removed in `finally` |
| 17 A3 GATE-001 | 2bb5f46 | scope `adoption`, error |
| 18 A2/A3 suggestions | 11ef868 | `src/l4/gates/suggest.py`, `src/l4/gates/pyproject.py`; a failing `ruff check` is run once more narrowed inside the dry run |
| 19 A3 template doctor line | 85d06ba | the injection test runs the line under `sh -c` |
| 20 A2 ecosystem | 7c19077 | `src/l4/init/ecosystem.py` |
| 21, 22 A2 config gates, TODO lines, notes | 3c80810 | |
| 23 A2 sample-consumer shape, offline | f5275a2 | |
| 24 A1 `merge_include` | fd95589 | 18 tests, each asserting the parsed-document property |
| 25 A1 wiring, `--no-ci-edit` | 18a6296 | the edit is in `InitPlan`; the init tests that expected "never edited" were rewritten |
| 26 A8 `.l4-out/.gitignore` | 911e12a | `seal_out_dir` in `fsutil`, called by `with_outcome`, `write_outcome`, `write_ci_outputs` |
| 27 A10 `AdminApi` | 8584133 | |
| 28 A10 project and base | 43cef8e | |
| 29 A10 token and variable | fd933ed | |
| 30 A10 `--secret` | 7abac9f | |
| 31 A9 schedule | 139de1a | |
| 32 A11 runners and include | 712261c | |
| 33 A10 the command, SPEC | fea0bf1 | L4-INS-006, SCN-INS-15..17, `test_dispatch.py` |
| 34 A3 check pipeline | 5cba009 | |
| 35 A10 end to end | a1d89e8 | |
| 36 A13 `l4 ci watch`, `--watch` | 3446701 | |
| 37 A10 `mk-l4-setup-gitlab.sh` | 13eca4a | |
| 38 A12 `mk-gitlab-api.sh` | af2ae13 | |
| E close-out | fc35560 | quickstart, README, SPEC doc changes, ticks |

## Counts

Full suite in five chunks (background), collected == passed + skipped (+ the known strict xfail) in every chunk:

| chunk | collected | passed | skipped | xfailed |
|---|---|---|---|---|
| agents, availability, llm | 481 | 476 | 5 | 0 |
| verifier, implementer, gates | 1088 | 1084 | 3 | 1 |
| orchestrator, archive, state, vcs, specs | 547 | 545 | 2 | 0 |
| every other `tests/unit` dir and `test_*.py` | 1750 | 1745 | 5 | 0 |
| contract, scenarios, integration, live | 122 | 59 | 63 | 0 |
| **total** | **3988** | **3909** | **78** | **1** |

The xfail is `test_residual_a_forgery_that_never_names_the_plugin_still_passes` (m16 plan Risks, strict). The first
run of the first chunk had one failure (a factory test that expected no event on a failed selection, fixed in 12efbb1);
the chunk was run again in full. `uv run ruff check .` is clean and `scripts/check_spec.py docs/SPEC.md` exits 0.
`l4 simulate --all` (5 pass, 16 pending) matches the base `8f604a5` except `stuck-clarifier-answers`, whose events no
longer hold `verify.step{step 8, status unavailable}` (A7: step 8 is `not_run` for an adapter profile on `s1_judge`).

## Deviations from the plan

* **Line 4 needed no code** (see above); line 3's `retry_after = now` already did it.
* **A dry run narrows a failing `ruff check` itself** (`GateRun.narrowed`, `narrowed_ok`): the worktree is gone when
  the suggestions are made, so the narrowed command must run inside the dry run.
* **`doctor --no-gates` without `--adoption` is exit 2.**
* **The template's `l4` job and the init `test` job**: `ci.runner_tags` is read by `merge_include` and CI-002; the shipped
  template still writes `tags: [agentic]` literally (deferred in the plan), so CI-002 errors when `ci.runner_tags`
  differs from it.
* **Forge-and-ci 2.19 is ticked for CI-002 only**; CI-003 of that task is still open (annotated in `tasks.md`).
* **`l4 ci watch` takes `--interval` and `--timeout` as durations** (`15s`, `90m`), not numbers.
* **The wrapper `mk-l4-setup-gitlab.sh` fetches `--mk-secret` values with curl and one page of the secret list** (limit
  200) instead of `mintkey_secret.py`, so the Mintkey agent key can go to curl on stdin and the fakes can serve it.
* **The live protocol was not run**: it needs the maintainer's Mintkey stack, a new scratch project on the live GitLab
  and a runner; nothing here touched GitLab, a runner or a CLI login. Steps 0 (local suite, simulate) are done above.

## Facts that stay unchecked (the plan's [U] items)

Whether a plain Maintainer PAT may list runners and create schedules (the code turns a 403 on runners into a WARN row
and a 403 on schedules into exit 1 with the reason); whether the schedule's owner may run pipelines on the protected
branch; push-to-create. All three are for the live protocol.

## Owed

SPEC edits made: §2.1 rows (`setup gitlab`, `ci watch`, `doctor --adoption`), L4-INS-006 and SCN-INS-15..17, L4-INS-002,
L4-CFG-001, L4-DOC-001 and the doctor table (CFG-005, CI-002, MEM-002, GATE-001), L4-IMP-008, L4-AVL-007/008, step 8,
16.3, L4-NFR-001, L4-ARC-002, the `init` row (`--no-ci-edit`). Not made: a schema for the event `availability.unavailable`
(12.1 lists it; no schema exists for any event).
