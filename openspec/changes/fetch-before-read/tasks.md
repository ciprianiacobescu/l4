## 1. The refresh outside CI (L4-CLI-005)

- [x] 1.1 Read `src/l4/vcs/refresh.py` (`refresh_in_ci`, `unit_refspecs`, the once-per-process set),
  `src/l4/state/status.py` (`refresh_refs`, `_DENIED`), `src/l4/state/retry.py` (`fetch_unit_refs`, its credentials
  `fetch_auth_config(cfg, app.environ, origin_url(...))`) and every caller of `refresh_refs` (`grep -rn "refresh_refs("
  src/l4`). Write the tests first (`tests/unit/vcs/test_refresh.py`, `tests/unit/state/test_status_branch.py`,
  `tests/unit/state/test_resume.py`, the run-unit and dry-run tests that pin "outside CI nothing is fetched": find them
  with `grep -rln "nothing is fetched\|SCN-CLI-12\|no fetch" tests/unit`): SCN-CLI-15, -16, -17, -18, -12 (amended), with
  real git (a bare origin and a clone, as the vcs tests build them). Then make the refresh fetch outside a CI job too
  (same refspecs and `--prune`, once per process, the local credentials as `fetch_unit_refs`), keep "no origin remote →
  no fetch", add a `fetch: bool` (False = `--no-fetch`), and give `refresh_refs` the local failure rules: `status`
  (`tolerate_denied`) tolerates every git error outside a CI job with the warning; the others raise one explained
  `L4Exit` (exit 3 for a credential or permission failure, using the same markers the push explanation uses; else 1)
  whose message names the reason and `--no-fetch`. In a CI job the behaviour is unchanged. Update the module docstring.
  Update every test that pinned the old local rule to the new one; say which in the Result.

  Result: `l4.vcs.refresh.refresh_in_ci` is now `refresh_remote_refs(git, *, branch_prefix, run_id, config, remote,
  fetch=True)`: it no longer reads the environment (the caller decides), fetches the unit branches, the lock refs and the
  plan refs with `--prune` once per process, returns False for `fetch=False` and for a checkout without `origin`.
  `mark_refreshed(git, run_id)` is new: `fetch_unit_refs` (retry, restart, questions, yolo) calls it outside a CI job, so
  the refresh that follows does not fetch a second time, and `l4 restart`'s `prune=False` is not undone by it (in a CI
  job `fetch_unit_refs` is unchanged and the refresh still fetches, as before). `refresh_refs` (state/status.py) takes
  `fetch: bool = True`, uses `fetch_auth_config(cfg, environ, origin_url(...))` outside a CI job (the CI call is
  unchanged) and has the local failure rules: `tolerate_denied` (status) warns `could not refresh from the forge
  (<reason>); showing local refs` for any git error, every other caller raises one `L4Exit` (exit 3 when
  `is_permission_failure`, the markers of the push explanation, else 1) with the reason (first line of git's stderr,
  redacted, 200 characters) and `pass --no-fetch to read the local refs`. In a CI job nothing changed. `snapshots` takes
  `fetch` too. Deviations: (1) the function was renamed (it is no longer "in CI"); (2) `l4 archive --unit` is not in
  L4-CLI-005's list; here it kept reading the local refs (`fetch=in_ci_job(...)`), which the follow-ups below replace; (3) the module docstring of refresh.py is updated, the "outside CI" docstring of
  `fetch_unit_refs` too. Tests: failed before (ImportError for the new names; 16 failures in test_status_branch,
  test_fetch_before_read, test_spec_edited), pass now: tests/unit/vcs/test_refresh.py and test_refresh_github.py
  (rewritten for the new function: fetch outside CI, `fetch=False`, once per process, `mark_refreshed`, a pushed and a
  deleted branch), test_status_branch.py (SCN-CLI-15, -17, -18, SCN-CLI-12 amended; `test_deleted_remote_unit_branch_is_pruned_before_fold`
  now expects the prune on a person's computer too; the `_refuse` helper patches `refresh_remote_refs`),
  tests/unit/orchestrator/test_fetch_before_read.py (new: SCN-CLI-18 for run, run --dry-run and resume, exit 3 for a
  refused credential, SCN-CLI-19 the sandbox refusal comes before the fetch), test_spec_edited.py (SCN-CLI-20). The
  `--no-fetch` scenarios (SCN-CLI-16) come with the flag in 2.1. test_resume, test_retry, test_restart, test_run_unit
  and test_dryrun pass unchanged.

## 2. The flag and the run

- [x] 2.1 Write the tests first (the CLI tests of `status`, `plan`, `resume`, `run`; find them under tests/unit with
  `grep -rln "def test_.*status\|invoke(.*\"plan\"" tests/unit | head`): `--no-fetch` is accepted by `l4 status`,
  `l4 plan`, `l4 resume` and `l4 run` (including `--unit` and `--dry-run`) and reaches the refresh; SCN-CLI-19 (a local
  `run --unit` that cannot sandbox fetches nothing: the preflight comes first) and SCN-CLI-20 (a local `run --unit`
  takes a spec edit pushed from another clone). Then add the flag in `src/l4/cli.py` the way the other flags are added
  (`_flag`), with help text `Read the local refs; fetch nothing from the forge.`, and pass it through. `l4 retry` and
  `l4 restart` keep their own fetch (`fetch_unit_refs`); their later refresh must not fetch a second time in the same
  process if the refspecs are covered (keep it simple: one fetch per command is the goal; say in the Result what you
  did).

  Result: `--no-fetch` (`_no_fetch()` in `_SPECS`, a `_flag` with the help text `Read the local refs; fetch nothing from
  the forge.`) is on `status`, `plan`, `resume`, `run` (so also `run --unit` and `run --dry-run`) and, after the
  follow-ups below, `archive`. Each handler takes
  `no_fetch: bool = False` (`run_status`, `run_plan`, `run_resume`, `run_command`, `run_dry`) and passes
  `fetch=not no_fetch` to `refresh_refs` or `snapshots` (the plan's second `snapshots` after a sweep too, which the
  once-per-process set makes a no-op). The flag is honoured in a CI job as well; nothing makes it a default there.
  `l4 retry` and `l4 restart` keep their own fetch (`fetch_unit_refs`, which marks the process as refreshed outside a CI
  job in 1.1), so they fetch once per command; `l4 restart` still keeps the tracking ref of a deleted branch. SCN-CLI-19
  is pinned by the existing SCN-SEC-107/-108 tests (they replace `refresh_refs` and fail if it runs before the sandbox
  preflight) and by `test_scn_cli_19_a_local_run_that_cannot_sandbox_fetches_nothing` (written in 1.1: an unreachable
  origin is not named in the refusal). Tests, failing before the flag existed (click usage error, exit 2) and passing
  now: `test_scn_cli_16_no_fetch_reads_the_local_refs` (the tracking ref does not move, an unreachable origin is not
  asked), `test_the_help_of_every_command_that_fetches_names_no_fetch`, the `--no-fetch` branches added to
  `test_deleted_remote_unit_branch_is_pruned_before_fold` and `test_scn_cli_18_an_offline_plan_...`,
  `test_no_fetch_reaches_the_refresh` (status, plan, resume, run --unit, run --dry-run: `fetch=True` without the flag,
  `fetch=False` with it), `test_a_dry_run_with_no_fetch_exits_as_it_does_with_the_local_refs`, and the two retry/restart
  once-per-command tests (these passed from 1.1 on: they pin what 1.1 did). SCN-CLI-20 is in test_spec_edited.py (1.1).

## 3. Checks

- [x] 3.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you
  changed or added plus the test files that import a module you changed (`grep -rl` under tests/unit), in as few
  sequential runs as the time limit allows (never two at once); not whole directories. Many tests run commands with a
  local origin: report every test that now fetches where it did not and how you adapted it. Run ruff check and ruff
  format on the changed files. Report the counts. Do not edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md (a docs pass
  does that).

  Result: Sequential runs, one at a time, never a directory. (a) After 2.1: planner/test_plan_cli, test_plan_exit_and_probe,
  cli/test_main, state/test_status_events, test_status_activity, test_spec_edit_parked, test_fold_operator,
  orchestrator/test_reentry, ci/test_sweeper, specs/test_questions_cli: 279 passed, 1 failed
  (`test_handler_options_reach_the_handler`, which pins the exact kwargs of `plan`: it now also expects `no_fetch`, and
  one more assertion that `--no-fetch` arrives as True). (b) yolo/test_yolo_cycle_run, test_yolo_cycle_planner,
  test_yolo_cycle_active, test_yolo_cycle_final_review, ci/test_pin_guard, forge/test_ci_run_state: 84 passed, 24 failed
  (16 in cycle_run, 8 in cycle_planner): their stand-ins for `snapshots` and `refresh_refs` took a fixed signature and
  got `fetch=`; they now take `**_` (also in yolo/test_yolo_review_y1.py, the same stand-in); no behaviour changed.
  (c) after the fixes: yolo/test_yolo_cycle_run, test_yolo_cycle_planner, test_yolo_review_y1, test_yolo_go_review,
  test_yolo_review_z1, test_yolo_review_z2: 123 passed. (d) final run of the files this change added or changed plus
  the ones around the refresh: vcs/test_refresh, vcs/test_refresh_github, state/test_status_branch,
  orchestrator/test_fetch_before_read, state/test_spec_edited, test_resume, test_retry, test_restart, sim/test_dryrun,
  orchestrator/test_run_unit, cli/test_main: 213 passed. Earlier, before 2.1, test_resume, test_retry, test_restart,
  test_run_unit and test_dryrun passed unchanged (122), so no test that runs commands against a local origin needed
  more than the three edits above; none of them fetched where it did not before in a way that mattered (a fetch from the
  local bare origin or the sim remote changes nothing). Tests changed: test_status_branch.py (the prune test, the `_refuse`
  patch target), vcs/test_refresh.py and test_refresh_github.py (new function), cli/test_main.py, the three yolo stand-ins.
  Not run (time): the rest of tests/unit/yolo, tests/unit/ci beyond the files above, tests/unit/archive, the live tests.
  `ruff check` and `ruff format --check` pass on every file this change touches (three untouched test files elsewhere
  were already unformatted before it).

  Result (follow-ups): (1) `l4 archive` fetches like the others: `run_archive` takes `no_fetch` and passes
  `fetch=not no_fetch` (the `in_ci_job` special case and its import are gone), and `archive` has `--no-fetch` in
  `_SPECS`. Tests (test_status_branch.py, on `unit_repo` with a second clone that pushes a spec edit): a local archive
  moves the tracking ref (failed before), `--no-fetch` leaves it and asks an unreachable origin nothing (passed before
  the change only because the flag was a usage error that fetched nothing; it pins the final behaviour), an offline
  archive exits 1 with the reason and `--no-fetch` (failed before); `archive` is also in the parametrised
  `test_no_fetch_reaches_the_refresh` (`fetch=True` without the flag, `False` with it; failed before). (2)
  `fetch_unit_refs` adds `PLAN_REFSPEC` to its refspecs, so `retry`, `restart`, `questions` and the `yolo` commands that
  call it bring `refs/l4/plans/*` too; `prune` is unchanged (`restart` keeps `prune=False` and the tracking ref of a
  deleted branch; the plan refs are forced, so a rewound or rewritten plan ref is overwritten with or without
  `--prune`). Tests in test_fetch_before_read.py, failing before: a retry-style fetch outside a job brings a plan ref
  the clone did not have, with the refspec in the argv; a restart-style fetch (`prune=False`) brings the plan ref, keeps
  the pruned branch's tracking ref, and force-updates the plan ref to a commit that is not a descendant and back.
  One finding: `stopped_plan_holding` already read the forge's plan ledger before this, because `PlanStore.read` fetches
  `refs/l4/plans/<id>` itself (the existing SCN-OPS-45 tests cover it); what the follow-up changes is the local
  `refs/l4/plans/*` that the later readers (`read_local`, the plan commands' holds) see after a retry or restart, so
  there is no separate test of `stopped_plan_holding` that would fail without the change. Run, one pytest process:
  vcs/test_refresh, state/test_status_branch, orchestrator/test_fetch_before_read, state/test_retry, state/test_restart,
  specs/test_questions_cli, ci/test_sweep_cli, ci/test_sweeper_kiro, cli/test_dispatch, cli/test_main,
  yolo/test_yolo_review_z4: 343 passed. No existing test needed a change. ruff check and format pass on the touched files.

  Result (review fixes): (1) The help of `--no-fetch` is `Read the local refs for the state; a run's worktree still
  fetches the unit.` (the test checks it on status, plan, resume, run and archive). The stop message after a failed
  local fetch is per command through `refresh_refs(..., stop_hint=)` and `snapshots(..., stop_hint=)`: `status` warns
  as before; `plan` and `run --dry-run` keep `pass --no-fetch to read the local refs`; `run` and `resume`
  (`RUN_NEEDS_FORGE_HINT`) say `a run needs the forge (its worktree fetches the unit); fix the connection, or read the
  local state with l4 status --no-fetch`. Checked in the code: `run --dry-run` makes no worktree (sim/dryrun.py reads
  from the main checkout), but `archive` does (`postmerge` cuts the archive worktree with `ensure_from_base`, which
  fetches the base branch), so it has its own text, `ARCHIVE_NEEDS_FORGE_HINT` (`an archive needs the forge (its
  worktree fetches the base branch); ...` the same way on). The flag is not passed into the worktree manager.
  specs/fetch-before-read/spec.md: L4-CLI-005 and SCN-CLI-18 say this, `archive` is in its command lists, and new
  SCN-CLI-21 (`--no-fetch` in a job) and SCN-CLI-22 (the token variable) are added. (2) `--no-fetch` in a CI job:
  `refresh_refs` raises `L4Exit` exit 2, `--no-fetch is for a person's computer: a CI job must not read stale refs
  (L4-CLI-003)`; tested for status, plan, archive (unit_repo) and run, run --dry-run, resume (tdd_repo, with the CI
  variables a job has). (3) `STATUS_FETCH_TIMEOUT_S = 15.0` sits next to `QUICK_TIMEOUT_S` in `l4.forge.base`;
  `Git.fetch` and `refresh_remote_refs` take a `timeout`, and `refresh_refs` passes it only for `tolerate_denied`
  (status) outside a CI job; tests: the timeout reaches `Git.run` (test_refresh.py) and status gets 15.0 where plan and
  a status in a job get none. A timeout is a `GitError("timed out")`, so the existing fallback shows it as the reason.
  (4) A refused credential (exit 3) appends `<VAR> is set, so git uses it instead of your credential helper: check or
  unset it` when `forge.token_env` is set in the environment, and nothing when it is not; the test also checks that
  the value is not printed. Finding: the push explanation (`forge/pushfail.py`) has no such sentence in this tree (it
  only says `<VAR> is not set` when it is empty), so the wording is the coordinator's, not copied. (5) New test that
  `refresh_refs` outside a job passes the helper built from the origin URL (a github.com origin gives
  `x-access-token`, where the CI call would give GitLab's `oauth2`; the token value is not in argv);
  `test_the_help_of_every_command_that_fetches_names_no_fetch` has `archive`; the comment at sim/runner.py now says what
  the extra `git fetch` is for. No existing test changed. Run, one pytest process: vcs/test_refresh,
  vcs/test_refresh_github, state/test_status_branch, orchestrator/test_fetch_before_read, state/test_resume,
  ci/test_sweep_cli, cli/test_main, cli/test_dispatch, yolo/test_yolo_cycle_run, yolo/test_yolo_cycle_planner: 208
  passed. Observation, not changed: the worktree manager of `run`, `resume` and `archive` gets `fetch_auth_config(cfg,
  environ)` without the origin URL, so on a laptop with a GitHub origin its fetch picks GitLab's username for the
  token; the state fetch of this change uses the origin URL.

