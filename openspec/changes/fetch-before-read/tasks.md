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
  L4-CLI-005's list and has no `--no-fetch`, so `run_archive` passes `fetch=in_ci_job(...)` and keeps reading the local
  refs on a person's computer; (3) the module docstring of refresh.py is updated, the "outside CI" docstring of
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

- [ ] 2.1 Write the tests first (the CLI tests of `status`, `plan`, `resume`, `run`; find them under tests/unit with
  `grep -rln "def test_.*status\|invoke(.*\"plan\"" tests/unit | head`): `--no-fetch` is accepted by `l4 status`,
  `l4 plan`, `l4 resume` and `l4 run` (including `--unit` and `--dry-run`) and reaches the refresh; SCN-CLI-19 (a local
  `run --unit` that cannot sandbox fetches nothing: the preflight comes first) and SCN-CLI-20 (a local `run --unit`
  takes a spec edit pushed from another clone). Then add the flag in `src/l4/cli.py` the way the other flags are added
  (`_flag`), with help text `Read the local refs; fetch nothing from the forge.`, and pass it through. `l4 retry` and
  `l4 restart` keep their own fetch (`fetch_unit_refs`); their later refresh must not fetch a second time in the same
  process if the refspecs are covered (keep it simple: one fetch per command is the goal; say in the Result what you
  did).

## 3. Checks

- [ ] 3.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you
  changed or added plus the test files that import a module you changed (`grep -rl` under tests/unit), in as few
  sequential runs as the time limit allows (never two at once); not whole directories. Many tests run commands with a
  local origin: report every test that now fetches where it did not and how you adapted it. Run ruff check and ruff
  format on the changed files. Report the counts. Do not edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md (a docs pass
  does that).
