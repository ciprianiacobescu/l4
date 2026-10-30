## 1. The rule (L4-YOLO-094)

- [x] 1.1 Read `src/l4/yolo/forbidden.py` (`forbidden_named`, `_pending`, `_negated`, `TreeIndex`), `src/l4/specs/paths.py`
  (`named_paths`), the freeze matcher `_matches` in `src/l4/implementer/guards.py`, the `[test-infra]` tag
  (`src/l4/specs/scan.py` ~304) and where the scope-exempt globs come from in the config (`SCOPE_EXEMPT` in
  `src/l4/config/defaults.py`; find the config key that overrides it). Write the tests first
  (`tests/unit/yolo/test_yolo_test_paths.py`, new, modelled on `test_yolo_forbidden_named.py`): SCN-YOLO-256 to -259 at
  the function level, plus a file token `docs/x/fixtures/a.json`, a `**/*.md` token that a test glob also matches
  (`docs/test_plan.md`), and the effective globs (a config with `tdd.test_globs` set replaces the defaults). Then add a
  pure `test_path_named(ref, test_globs, support_globs, exempt_globs) -> list[PathFinding]` (reuse `PathFinding` with a
  `kind`/`rule` that says `test_path`; warnings only) using the freeze's `_matches` (import it, or move it to a module
  both use without changing its behaviour).

  Result: New `src/l4/yolo/testpaths.py` with `test_path_named(ref, test_globs, support_globs, exempt_globs)`; it imports
  the freeze's `_matches` from `l4.implementer.guards` (not moved, behaviour unchanged) and tries it glob by glob so the
  finding can name the glob. The exempt globs are `verifier.evidence.scope_exempt` (`EvidenceCfg`, default `SCOPE_EXEMPT`). It
  reuses `forbidden.py`'s `_pending`, `_negated`, `_host_like`, `_file_like` and `named_paths`; the `[test-infra]` tag is
  `has_human_tag` (a harness-written fix-unit title never counts). A file token is matched as written; a directory token
  (no extension, or the trailing `/` that a glob token like `docs/x/fixtures/*.json` leaves) is matched as a file
  directly in it (`<dir>/_`). Test globs are tried before support globs. Deviation: `PathFinding` got a last field
  `code: str = CODE` (default `forbidden_path`, so existing callers are unchanged) instead of a `kind`, because `rule`
  must stay the glob; `message` uses it. Also, OpenSpec has no optional-task marker (only Kiro's `[ ]*`), so no
  optional-task test. New `tests/unit/yolo/test_yolo_test_paths.py` (14 tests): failed at collection (no
  `l4.yolo.testpaths`), pass now, 45 with `test_yolo_forbidden_named.py`.

## 2. Where it runs

- [x] 2.1 Write the tests first (`tests/unit/yolo/test_yolo_commands_check.py`, `test_yolo_check_worktree.py`,
  `test_yolo_go_activate.py`, and the orchestrator intake test `tests/unit/orchestrator/test_openspec_intake_validation.py`):
  SCN-YOLO-256 end to end through `l4 yolo check` (printed as `warning: test_path: <unit>: …`, exit 0) and SCN-YOLO-260
  (unit start: a logged warning, no `unit.rejected`). Then thread the warning through the same places as the
  forbidden-path warnings (`plans.intake` / `unit_infos` → `UnitInfo.warnings`, `commands.py` check/`--worktree`/`go`,
  `cycle.py` CI review, `Orchestrator` unit start), passing the effective `tdd` globs.

  Result: `testpaths.PathGlobs` (test, support, exempt; `PathGlobs.of(cfg)` reads `tdd.test_globs`,
  `tdd.test_support_globs`, with the `extra_` lists already merged, and `verifier.evidence.scope_exempt`). `unit_infos` and
  `plans._intake` take `test_paths`; its findings are appended to `UnitInfo.warnings` as `warning: test_path: <unit>: ...`
  in every phase (never a blocker), after the forbidden-path warnings. `commands._read_units` (check, go, and the other
  readers of the target; only with the intake checks), `commands._admit_worktree` (`check --worktree`) and the CI review
  in `cycle.py` pass `PathGlobs.of(cfg)`. `Orchestrator._warn_test_paths`, called next to `_forbidden_reasons` in both
  validators, logs each finding with `log.warning` at the unit start and returns nothing, so no `unit.rejected` and no
  exit code. Deviation: it only runs in the intake phases (`None`, intake, ready), like the forbidden-path check there:
  a unit already implementing is not warned again at each run (the plan side warns in every phase). `l4 yolo go` needed
  no change of its own: it prints the check step's `UnitInfo.warnings`. Tests that failed before and pass now:
  `test_scn_yolo_256_...` in `test_yolo_commands_check.py` and `test_yolo_check_worktree.py`,
  `test_a_test_path_warning_is_printed_under_the_check_step` (go), the SCN-YOLO-260 unit-start test and the phase test in
  `test_openspec_intake_validation.py`, and 6 new `unit_infos` tests in `test_yolo_plans_forbidden.py` (collection error
  before); the SCN-YOLO-257 tests (tag, narrowed globs) pass before and after by design.

## 3. The hint and the delegate

- [x] 3.1 Write the tests first (`tests/unit/implementer/test_guard_notes.py`): SCN-IMP-445 and an ordinary test path
  that keeps "Tests belong in the red step". Then make `note_of` / the `test path freeze` advice in
  `src/l4/implementer/guardnotes.py` pick the new text when a restored path matches a scope-exempt glob (pass the globs
  in from the caller that knows the config).

  Result: `note_of(event, data, forbidden, exempt, test_globs)` takes the scope-exempt globs and the test and support
  globs; `GuardNote` has `scope_exempt` and an `advice_key`, and `_ADVICE` a new entry (`DOCS_TEST_PATH`) that says the
  path is covered by a test glob (`tdd.test_globs` / `tdd.test_support_globs`), that no agent step after red may write
  it, to report blocked naming the path, and that a person must tag the task `[test-infra]` or leave the glob out of the
  `tdd` globs on the base branch. `Workbench.emit` passes `verifier.evidence.scope_exempt` and the tdd globs. Deviation:
  the spec names the freeze (`restore_test_paths`, rule `test path freeze`), but with the default globs
  `**/fixtures/**` is also a support glob, so a new `docs/x/fixtures/a.json` is removed first by `restore_frozen` as a
  `guard.violation` with no rule (hint: "protects some paths (CI files ...)") and never reaches the freeze; a test that
  drove a green step through the bench showed it. So the docs hint applies to a green put-back with rule `test path
  freeze` or no rule whose path both a scope-exempt glob and a test or support glob match (a protected path such as
  `CLAUDE.md` matches no test glob and keeps the generic hint); the note's rule then reads `test path freeze`. Phase
  `single` (fix chores) keeps the fix-task text. Tests in `test_guard_notes.py` (5 new): SCN-IMP-445 at the note level,
  an ordinary `tests/fixtures/...` path keeping "Tests belong in the red step", both beside each other, the rule-less
  support removal, the `single` phase, and the attempt-2 prompt of a bench run; all failed before (`note_of` had no
  `exempt`; the prompt showed the generic text) and pass now (25 in the file).
- [x] 3.2 Write the test first (`tests/unit/delegate/test_reply*.py`): a config whose `tdd.test_globs` leaves out
  `**/fixtures/**` makes the reply check treat `docs/x/fixtures/a.json` as no test. Then pass the effective globs from
  the caller of `check_reply` (src/l4/delegate/reply.py ~265 defaults to `d.TEST_GLOBS`; find the call in
  `src/l4/delegate/run.py`).

  Result: No source change: the only caller of `check_reply`, `l4/delegate/run.py` (~line 360), already passes
  `test_globs=tuple(cfg.tdd.test_globs)` and `support_globs=tuple(cfg.tdd.test_support_globs)` (the `extra_` lists merged),
  and nothing else in `l4.delegate` reads `d.TEST_GLOBS`; only the parameter defaults of `reply._check_reply` are the
  defaults, and no caller relies on them but tests. So the task's premise (the check reads the defaults) is already false
  in the code; I added tests that pin the behaviour instead (they cannot fail first). A new `tdd=` option on
  `tests/unit/conftest.py` `TddRepo.config` / `write_config` writes a `tdd` section. New:
  `test_the_pass_hands_the_checks_the_effective_tdd_globs_not_the_defaults` (`test_pass.py`, a run through the delegate
  with narrowed globs and `extra_test_globs`) and `test_a_chore_answer_naming_a_docs_fixture_follows_the_effective_globs`
  (`test_reply_0421.py`: escalated with the defaults, kept when the globs leave out `**/fixtures/**`). I checked the
  pass test is not vacuous by pointing `run.py` at the defaults for a moment (it failed) and restoring it. Both pass
  (44 in the two files).

## 4. Checks

- [x] 4.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you changed or added plus the test files that import a module you changed (`grep -rl` for the module name under tests/unit), in one pytest invocation; not whole directories (a combined run follows after the merge). Run ruff check and ruff format on the changed files. Report the counts. Do not edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md (a docs pass does that).

  Result: `ruff check` (src, tests/unit/yolo, tests/unit/implementer, tests/unit/delegate, the two other changed test
  files) and `ruff format --check` (556 files) are clean. Tests: the 140 test files that import a changed module (grep)
  would not fit one invocation here (no pytest-xdist, machine load 13 to 30: the 10-minute foreground cap killed the
  first runs), so I ran them in sequential invocations. (a) implementer, delegate and ci importers, 20 files: 317
  passed. (b) the changed or added yolo and orchestrator files plus `test_yolo_forbidden_named.py` and
  `test_yolo_admit_admission.py`, one invocation: 170 passed. (c) two sweeps of the yolo importers (24 files; then 12
  cycle, go, review-worktree and commands files) ran to 43 and about 60 percent before the timeout killed them: every
  test that ran passed, no failure shown, but they did not finish, so those files (and the orchestrator, state,
  planner, verifier, agents, archive, cli, gates, kg and sandbox importers) are for the combined run after the merge.
