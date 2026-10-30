## Purpose

A unit whose task delivers documentation that a test glob covers is warned about before any run, with the fix named,
and the agent's hint after such a restore names the right way out.

## ADDED Requirements

### Requirement: L4-YOLO-094 A task deliverable that a test glob covers is a warning at intake
The intake of a unit (plan check, `check --worktree`, `go`, the CI review, and the unit start) SHALL warn with
`test_path` when a pending required task without the `[test-infra]` tag names a path that a glob of the effective
`tdd.test_globs` or `tdd.test_support_globs` matches and that a scope-exempt glob also matches. A directory token or a
glob token (`docs/x/fixtures/*.json`) counts as its directory: a glob matches it when it matches a file directly in it.
The match SHALL use the matcher the freeze uses. The message SHALL name the task, the path, the glob and the fixes: a
person tags the task `[test-infra]`, or the base branch's `tdd.test_globs` / `tdd.test_support_globs` leave the glob
out. It SHALL NOT refuse the unit or change an exit code. A line that says not to touch the path gives nothing, as for
forbidden paths.

#### Scenario: SCN-YOLO-256 (−) A docs fixture task is warned about
- **WHEN** pending task 2.1 says "Write the client fixtures `docs/waitlist/fixtures/*.json`" and the globs are the defaults
- **THEN** `l4 yolo check` prints `warning: test_path: <unit>: task 2.1 names docs/waitlist/fixtures/, which the test
  glob **/fixtures/** matches …` with both fixes, exit 0

#### Scenario: SCN-YOLO-257 (+) A tagged task or narrowed globs give nothing
- **WHEN** the task carries `[test-infra]`, or the base's `tdd.test_globs` and `tdd.test_support_globs` leave out
  `**/fixtures/**`
- **THEN** there is no warning

#### Scenario: SCN-YOLO-258 (+) An ordinary test path gives nothing
- **WHEN** a task names `tests/fixtures/users.json` or `src/app/test_x.py`
- **THEN** there is no warning (no scope-exempt glob matches)

#### Scenario: SCN-YOLO-259 (+) A ticked task or a "do not" line gives nothing
- **WHEN** the task is `[x]`, or its line reads "do not change `docs/x/fixtures/a.json`"
- **THEN** there is no warning

#### Scenario: SCN-YOLO-260 (+) The unit start warns without rejecting
- **WHEN** a unit with such a task starts
- **THEN** the run logs the warning and implements; no `unit.rejected`

## MODIFIED Requirements

### Requirement: L4-IMP-006 (amendment, the guard's note after a test-path restore)
When the freeze restores or removes a path that a scope-exempt glob also matches, the agent's retry hint SHALL say that
the path is covered by a test glob, that no step after red may write it, and that the task needs a person
(`[test-infra]` on the task or the base branch's `tdd` globs), and SHALL NOT say that tests belong in the red step.
Other test-path restores keep today's hint.

#### Scenario: SCN-IMP-445 (+) The hint after a docs fixture restore names the fix
- **WHEN** green writes `docs/x/fixtures/a.json` and the freeze restores it
- **THEN** the retry hint names the test glob, says no step after red may write it and names `[test-infra]` and the
  `tdd` globs; it does not say "Tests belong in the red step"
