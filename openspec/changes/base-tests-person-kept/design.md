# Design: a file a person changed last stays at head

## D1. The same rule as the excuse

`kept_files(ctx, paths)` reads, for each path, `who = _introducers(ctx, path, changed)` (the commits of `base..head`
that changed it, oldest first). Its order becomes:

1. `_by_people(who)`: `only people's commits changed it (<sha>, …)`, unchanged;
2. `_allowance(ctx, who, path, by_sha)`: the `[test-infra]` and `task.unfrozen` reasons, unchanged;
3. new: `_last_by_people(who)` (from `l4.verifier.integrity`, added in 0.4.33) for a test module, not a support file:
   `people changed it last (<sha>, …)`, every introducer's 10-character sha, the harness's included. Support is step
   5's rule (`runner_support`), moved to `support_base.is_support_file(git, cfg, path, rev)` so both steps use one:
   one of `tdd.test_support_globs`; a `.py` file that defines no test at `rev` (or does not parse); another language's
   file whose name does not look like a test module. `rev` is head, or the base for a deleted file.

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

## D4. Why this is safe, and why only test modules

- A harness commit after the person's makes `_last_by_people` false: the file is reverted and judged as before.
- A test module: 0.4.33 already excused its failing base tests on the person's last commit (a person's line), so
  running its head version changes the line's kind, not what is accepted. The AST checks of step 1 (no pre-existing
  test deleted, skipped, changed or rebound by a harness commit, L4-VER-030 and L4-VER-031) still use `_by_people`
  and are not changed, so a harness change to a pre-existing Python test function is still a blocker.
- A support file (conftest, fixture, helper) is not kept by this rule. It can change what other files' tests check: a
  stubbed fixture makes them pass vacuously at head, which is green, not `not run`, so `split_allowed` never sees it;
  and when it is the unit's only changed test or support file, step 1 runs nothing at all. Nothing else reads a
  harness change to it, so it stays reverted unless people alone changed it or an allowance covers it.
- Residual, named and not solved here: a Go `*_test.go` file always counts as a test module by its name, and its
  package-level helpers are visible to the package's other test files; a helper the harness stubbed there, then
  committed last by a person, runs at head. A person's commit to the file is the endorsement the rule reads.
