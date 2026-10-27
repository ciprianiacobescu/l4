# Design: a file a person changed last stays at head

## D1. The same rule as the excuse

`kept_files(ctx, paths)` reads, for each path, `who = _introducers(ctx, path, changed)` (the commits of `base..head`
that changed it, oldest first). Its order becomes:

1. `_by_people(who)`: `only people's commits changed it (<sha>, …)`, unchanged;
2. `_allowance(ctx, who, path, by_sha)`: the `[test-infra]` and `task.unfrozen` reasons, unchanged;
3. new: `_last_by_people(who)` (from `l4.verifier.integrity`, added in 0.4.33): `people changed it last (<sha>, …)`,
   every introducer's 10-character sha, the harness's included.

A path with none of them is reverted, as before. Checking the new reason last keeps every file that had a reason before
on the same reason and text; only files that were reverted before can change.

This revises 0.4.33's design D3 for `kept_files`; D3's other half (`_by_people` for the AST checks of `integrity`)
stays.

## D2. Listed as a person's

`check_base_tests` splits the kept files with `"people" in why`: allowed lines for the others, people's lines
(`human_tests`) for these. The new text contains `people`, so a file kept by D1's third reason lands in `human_tests`
as `<path> kept at head for the run (people changed it last (<sha>, <sha>))`. The filter is not changed.

## D3. What a person's last commit now does in step 1

The file runs at head, so its own tests run the content the person committed, and any other test that runs or imports
it (a wrapper that starts the package's test runner, a test that imports a helper from it) runs that content too. When
its own tests pass at head there is no person's failure line for them; the kept-file line says that a person set the
file. `split_allowed` is not changed: its person's branch still excuses a test of a person-last file that fails in the
run (now with the head version, which step 3 also runs).

## D4. Why this is safe

- A harness commit after the person's makes `_last_by_people` false: the file is reverted and judged as before.
- A support file the harness changed to skip or stub the base tests, then committed by a person, is kept, and the
  tests it skips are `not run`; a test that does not run is a blocker unless its own file has an allowance, and the
  tests the unit did not change have none.
- The AST checks of step 1 (no pre-existing test deleted, skipped, changed or rebound by a harness commit, L4-VER-030
  and L4-VER-031) still use `_by_people` and are not changed.
