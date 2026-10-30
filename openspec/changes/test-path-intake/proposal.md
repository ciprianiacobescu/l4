# A task deliverable that a test glob covers is named before any run

## Why

On a consumer (2026-10-30, harness 0.4.42) a unit's task delivered JSON client fixtures under
`docs/waitlist/fixtures/*.json`. The default test globs include `**/fixtures/**` (both `tdd.test_globs` and
`tdd.test_support_globs`), so green's write of those files was restored as a test-path change ("a test file changed in
a step that may not change tests"), twice, and the unit escalated [V, the unit's ledger]. The person fixed it by setting
`tdd.test_globs` and `tdd.test_support_globs` on the base branch without `**/fixtures/**`. The retry hint the agent got
said "Tests belong in the red step", which is wrong advice for documentation.

Every input needed to see it is known before the first run: the task's text and the effective globs. Narrowing the
default globs is not done: it would stop freezing root-level and `src/**/fixtures` test data in green for every
consumer.

## What changes

- An intake warning `test_path` (never a blocker): a pending required task without the `[test-infra]` tag names a path
  (a file, a directory or a glob token) that a test or support glob of the effective config matches and that a
  scope-exempt glob also matches (default `docs/**`, `**/*.md`, `CHANGELOG*`: documentation, not a test location). The
  message names the task, the path, the glob and the fixes: a person tags the task `[test-infra]`, or the base branch's
  `tdd.test_globs` / `tdd.test_support_globs` leave the glob out. It runs where the forbidden-path intake runs (`l4
  yolo check`, `check --worktree`, `go`, the CI review, and the unit start as a warning).
- The match uses the freeze's own glob matcher, so intake and freeze cannot disagree.
- The agent's retry hint after a test-path restore of a scope-exempt path says the path is covered by a test glob, that
  no agent step after red may write it, and that the task needs a person (`[test-infra]` or the config), instead of
  "Tests belong in the red step".
- The delegate's reply check reads the effective `tdd` globs, not the defaults.

## Impact

- Code: a new `l4.yolo.testpaths` (or next to `l4.yolo.forbidden`), `l4.yolo.plans`, `l4.yolo.commands`,
  `l4.yolo.cycle`, `l4.orchestrator` (unit start, warning only), `l4.implementer.guardnotes`, `l4.delegate.reply` and
  its caller.
- Spec: L4-YOLO-094 added; L4-IMP-006 (the guard's note) amended; SCN-YOLO-256 to SCN-YOLO-260 and SCN-IMP-445 added;
  change-table row 100.
- Not in this change: the skill's offline validator (`validate_plan.py`) does not run it (as for forbidden paths); the
  freeze and the verifier still do not exempt `scope_exempt` paths (that would weaken tamper protection).
