## 1. The refresh outside CI (L4-CLI-005)

- [ ] 1.1 Read `src/l4/vcs/refresh.py` (`refresh_in_ci`, `unit_refspecs`, the once-per-process set),
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
