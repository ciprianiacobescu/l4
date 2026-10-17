Every task follows these rules:
- Read `design.md` first: every text, event field and signature is there (section 3, Contracts); do not change one without
  the orchestrator.
- Tests first. A ported reproduction (design appendix A gives its path and its texts) is copied into the named test file
  with its assertions turned into the expected behaviour: run it and see it fail before writing the fix, then make it
  pass. Never weaken a ported test to make it pass.
- Run only the named test files: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider <paths>`,
  then the folder of the code you changed (`tests/unit/implementer`, `tests/unit/verifier`), then `ruff check .`,
  `ruff format --check` and `mypy` on the files you changed, and `python scripts/check_spec.py docs/SPEC.md`.
- An existing test whose fake agent step rewrites a pre-existing test file only by accident (not to test tamper) is
  changed to append instead; list each such change in your commit message. The comparison is never relaxed for a test.
- Never wait on a process with `while pgrep -f ...` (it matches itself). Stage explicit paths only; never `git add -A`.
- No public name in `src/` starts with `test` or `Test` (pytest would collect it from a test module that imports it).
- Order: 1.1 first; groups 2 and 3 need 1.1 merged (2.2 needs 2.1, 3.3 needs 2.1 and 3.1); 4.1 and 4.2 need nothing of
  groups 1-3; 4.3 needs 3.1 and 4.2; 5.1 needs 4.1; group 6 needs all of 1-5; group 7 last.

## 1. The comparison (L4-IMP-045, L4-IMP-046, L4-IMP-047)

- [x] 1.1 Tests first, new `tests/unit/implementer/test_tamper_compare.py` (pure, no git): SCN-IMP-260 (the
  implementer-4 `WEAKENED` text against the fixture's base `tests/test_pricing.py`), SCN-IMP-261 (the `REBOUND_SUFFIX`
  form; the why names the line of the second `def`), SCN-IMP-262 (an assignment and an import), SCN-IMP-263 (a
  parametrize case dropped, a decorator added, a requested fixture renamed), SCN-IMP-264 (`_check` and `EXPECTED`, the
  why names each), SCN-IMP-265 (an autouse fixture and a `pytestmark` appended: every old test, naming them; a
  non-autouse fixture only a new test requests: nothing), SCN-IMP-266 (all of its edits together: nothing; and the
  SCN-IMP-46 file: nothing), SCN-IMP-267 (`TestCart.setup_method` changed, a class decorator added, a new method added),
  SCN-IMP-268 (a syntax error: every old test `unparsable`; a `before` that does not parse: nothing), SCN-IMP-269 and
  SCN-IMP-270 with `moved` (also: one added test stands for one deleted test only; a test moved into a class with the
  same definition is moved), a deleted file (`after=None`), and `names_test_id` with the cases of
  `tests/unit/verifier/test_integrity_superseded.py` (`tests.test_long::test_long`, a parametrised id, a class between
  module and function, a same-named test of another module). Then write `src/l4/implementer/tamper.py` as design D1-D3
  and section 3 say (`facts_of` with `functools.lru_cache`, `compare`, `moved`, `names_test_id`, `Facts`, `Tampered`),
  reusing `guards._bound`'s statement kinds, `guards._MODULE_HOOKS` and `scan._qualified`; and make
  `integrity._is_superseded` call `names_test_id` (its tests stay green unchanged). (L4-IMP-045, L4-IMP-046,
  L4-IMP-047)

## 2. Red (L4-IMP-048, L4-IMP-006)

- [x] 2.1 Tests first, new `tests/unit/implementer/test_red_preexisting_tests.py`: port the implementer-4 reproduction
  (`verify-implementer/repo/tests/unit/implementer/test_verify_impl4_tamper.py`; it asserts the bug today:
  `out.status == "ok" and committed == tampered` and no event) as SCN-IMP-276 (weakened) and SCN-IMP-277 (rebound): the
  outcome is `failed`, `HEAD:tests/test_pricing.py` is still the base text, one `guard.test_tamper{phase: "red", path:
  "tests/test_pricing.py", rule: "pre-existing test", action: "rejected", tests: ["test_total_adds_prices"]}`, the
  reason starts with `red changed tests that existed before this step: tests/test_pricing.py::test_total_adds_prices (`
  and has no newline, and the excerpt holds the advice of design D4. Add SCN-IMP-272 (task title `2.1 [test-infra] Share the cart fixture`), SCN-IMP-273 (task
  1.1 run to its red commit with `red_step()`, then task 1.2's red weakens `tests/test_discount.py::test_known_code`),
  SCN-IMP-275 (a red that rewrites `test_total_adds_prices` to `assert False` next to a new
  failing test: the reason still starts with `red broke existing tests: tests.test_pricing::test_total_adds_prices`,
  the excerpt holds the failure, and no `guard.test_tamper` with `rule: "pre-existing test"` is recorded, which proves
  the check runs after `classify_red`; `test_tdd_red.py` and `test_loop.py` stay green unchanged), and in `tests/unit/implementer/test_guard_notes.py` a `guard.test_tamper`
  with `action: "rejected"` gives no note. Then: `tdd.preexisting_test_changes(wb, task, base, stale)` and its call in
  `run_red` right after `classify_red` accepts (design D4: the changed `.py` test paths that existed at `base`, `compare`
  and `moved`, the `[test-infra]` and stale exceptions, one event per file, `wb.discard_changes()`, `RedOutcome("failed",
  reason, excerpt=…)`); `guardnotes.note_of` returns `None` for `action == "rejected"`. Last, SCN-IMP-271 in
  `tests/unit/orchestrator/test_stale_tests.py` with its Kiro fixtures (`start`, `push_requirements`, `lower_script`):
  the reopened red that replaces the stale `test_long` and also rewrites `tests/test_pricing.py::test_total_adds_prices`
  to `assert True` fails its attempt naming only `test_total_adds_prices`; every existing test of that file stays green
  (they are the stale allowance end to end). (L4-IMP-048, L4-IMP-006)
- [x] 2.2 Tests first, new `tests/unit/verifier/test_ladder_tamper.py`: SCN-IMP-274 with `run_l4`, `valid_spec` and the
  verifier-2 texts (appendix A): the script is `[tampering red, red_step(), green_step(), judge_step()]` where the
  tampering red is `red_step()` plus the weakened `tests/test_pricing.py`. Expect: one `task.attempt_failed` whose
  reason starts with `red changed tests that existed before this step: tests/test_pricing.py::test_total_adds_prices`,
  the second red request's prompt contains that reason and `A red step adds new tests with new names`, the verdict PASS,
  and `run.pushed("tests/test_pricing.py")` equal to the fixture's base file. No code change is expected; fix in
  `tdd.py` what this shows. (L4-IMP-048)

## 3. Step 1 (L4-VER-030, L4-VER-031, L4-VER-032)

- [x] 3.1 Tests first, new `tests/unit/verifier/test_integrity_tamper.py` on `_integrity_helpers.new_repo`: port the
  verifier-8 reproduction (`verify-verifier/rt/tests/unit/verifier/test_v8_masked_delete.py`; it only prints today) as
  SCN-VER-103 (harness, same name elsewhere: the blocker `a pre-existing test was deleted` naming
  `tests/test_cart.py::test_empty`) and SCN-VER-104 (`commit_as_human`: no finding, `human_tests` holds
  `tests/test_cart.py::test_empty deleted by <sha10>`), keeping both controls (`test_y`). Add SCN-VER-100 (the
  verifier-2 assertion `is not None` committed by `repo.commit("red", task="1.1", tdd="red")`), SCN-VER-102,
  SCN-VER-105 (and `test_integrity.py::test_a_test_moved_to_another_changed_file_is_not_deleted` stays green),
  SCN-VER-106, SCN-VER-107 (a `tests.superseded` event, a task tagged `[test-infra]` in `ctx.tasks`, a `task.unfrozen`
  of the same unit and task naming the path; the listed lines and the note's `(+2 allowed, listed)`), SCN-VER-108, and
  SCN-VER-109 (and `test_integrity.py::test_module_wide_skip_and_a_skip_call_are_blockers` stays green with its one
  finding). Then rewrite the name-set part of `integrity.check_tests` as design D5 says (`compare`, `moved`,
  `_introducers` with the facts predicate, `_by_people`, the allowances through `commits(ctx)` and the `task.unfrozen`
  events, the reported-once rule), add `Outcome.allowed_tests` and `IntegrityReport.allowed_tests`
  (`verifier/types.py`) and collect them in `run_integrity`. Every existing test of `tests/unit/verifier/
  test_integrity*.py` stays green. (L4-VER-030, L4-VER-031)
- [x] 3.2 Tests first, in `tests/unit/verifier/test_integrity_tamper.py`: SCN-VER-110 (two harness commits with
  `tdd="red"` for tasks 1.1 and 1.2; the second weakens the first's test) and SCN-VER-111 (the second appends new tests to the
  first's file: no finding). Then add part B to `check_tests` (design D6: `commit_records` and
  `is_harness`, `L4-TDD` `red` or `already-satisfied`, `[test-infra]` skipped, the first parent, tests at the base
  skipped, `tests.superseded` skipped, `moved` within the commit). (L4-VER-032)
- [x] 3.3 Tests first, in `tests/unit/verifier/test_ladder_tamper.py`: port `test_v2_weakened.py::test_v2[True]` as
  SCN-VER-101 and SCN-VER-121 with `monkeypatch.setattr("l4.implementer.tdd.preexisting_test_changes", lambda *a, **k:
  [])` (the red check of 2.1 bypassed): the verdict is FAIL, the `verify.step` of step 1 is `failed` with a note holding
  `a pre-existing test was changed`, there is no `verify.step` for step 2, and verification.md names
  `tests/test_pricing.py::test_total_adds_prices`. The control (`test_v2[False]`: the test left alone) keeps today's
  green failure `green broke existing tests` and is not ported (its fake runs out of steps). No new code is expected.
  (L4-VER-030, L4-VER-002)

- [x] 3.4 Tests first, new `tests/unit/verifier/test_integrity_support_patch.py` (owner decision 1): SCN-VER-124 (an
  autouse fixture, module-level code, a fixture an autouse fixture requests and a plain function that patch a symbol of
  a module the unit changed: the content scan blocks), SCN-VER-125 (a fixture a test requests by name: listed, no
  finding; a patch of a module the unit did not change: nothing; a person's commit: listed in `human_scan`), and in
  `test_ladder_tamper.py` the reviewer's exact `CONFTEST2` stopped by step 1. Then `opened.new_patches`,
  `check_scan` (D11), `Outcome.mocked`, `IntegrityReport.mocked_support` and the report section. (L4-VER-037)

## 4. Audit with the support files at the base (L4-VER-033, L4-VER-034, L4-VER-036)

- [x] 4.1 Tests first, new `tests/unit/verifier/test_support_base.py` (a `make_bench` worktree with a base commit and a
  head commit): SCN-VER-114 (an added `tests/conftest.py`, a changed `tests/fixtures/data.json`, a deleted
  `tests/helpers/old.py`, a symbolic link at head; inside the block and after it, also when the block raises; mode bits;
  `git status --porcelain` equal before and after; a path whose parent is a symbolic link out of the worktree is not
  touched), and `support_plan` (globs with `extra_test_support_globs`, a `.l4/` path left out, `pyproject.toml` never in
  it, `fallback` true only for a `content scan` row `ok`, the two `why_not` texts). Then write
  `src/l4/verifier/support_base.py` as design D8 says. (L4-VER-033)
- [x] 4.2 Tests first. In `tests/unit/verifier/test_ladder_tamper.py` port `test_v6_audit_support.py::test_v6_full` as
  SCN-VER-112 (`CONFTEST2` and `BROKEN_IMPL` of appendix A, with the patches written through `vars()` so that step 1's rule of 3.4 does not see them; today the original prints `FULL CODE 0 VERDICT PASS`): the
  `verify.audit` record is `failed` with `support == "base"` and `support_files == ["tests/conftest.py"]`, the verdict is
  not PASS, and `tests/conftest.py` is unchanged on the pushed branch; and SCN-VER-113 (`test_v6[False]` plus a harmless
  non-autouse `tests/conftest.py`: `accepted`, `support == "base"`, PASS). New `tests/unit/verifier/
  test_audit_support.py`: SCN-VER-115 (red adds `tests/helpers/builders.py` and a red test file that imports it with
  the import form that collects at head in the fixture repository, `from helpers.builders import …` (its `tests/` has no
  `__init__.py`) or `from tests.helpers.builders import …`: the audit test is judged from the base-support run), SCN-VER-116 (red adds a
  `tests/conftest.py` with a fixture `codes`, the writer's audit test requests `codes`: `accepted`, `support == "head"`),
  SCN-VER-117 (the same plus a `tests/helpers/setup.ts`: rejected, minor finding, the reason starts with `it does not
  run with the unit's support files at the base`), SCN-VER-118 (call `_judge_written` on a bench with a recorder in place
  of `l4.verifier.audit.confirm_pre_satisfied` that notes whether `tests/conftest.py` exists and its `extra_env`). Then:
  `audit._judge_written(..., support)` as design D8 steps 1-3, `run_audit(..., support)` and the re-entries in
  `_retry_collected` and `_lint_accepted`, `confirm_pre_satisfied(..., extra_env=None)` and `zeroed_run(...,
  extra_env=None)` in `implementer/discrimination.py`, `AuditRecord.support` and `support_files`, the two fields on
  `verify.audit` (and wherever a stored round's audit rows are read back, an old row without them still loads), and
  `ladder._audit_step` builds `support_plan(...)` and adds `support files at the base: <n>` to its
  note. `tests/unit/verifier/test_audit*.py` and `test_ladder_depth.py` stay green (an audit with no support change
  records `support: "unchanged"`). (L4-VER-033, L4-VER-034, L4-VER-036)
- [x] 4.3 Tests first, new `tests/unit/verifier/test_report_tamper.py`: SCN-VER-120 on a `VerifyResult` built in the
  test (two `AuditRecord`s, `support` `base` and `head`; an `IntegrityReport` with one `allowed_tests` line), and
  SCN-VER-123 (a rejected `AuditRecord` with the reason of design D8 step 3 is listed under `## Rejected audit tests`). Then
  `report.py`: the Audit table's `Support` column (`base`, `head`, `-` for `unchanged` or empty) and the section `##
  Pre-existing tests changed with an allowance (L4-VER-031)` after `## Test changes made by humans`; update the existing
  header assertions in `tests/unit/verifier/test_report*.py` for the new column only. (L4-VER-036)

## 5. Generated UI tests (L4-VER-035)

- [x] 5.1 Tests first, new `tests/unit/verifier/test_generate_support.py` on the `web` bench of `test_generate.py`:
  SCN-VER-119 (after `stage_base_and_head`, commit an `e2e/conftest.py` with an autouse fixture that monkeypatches
  `urllib.request.urlopen` to answer a page with `item-count">9 items<`; the writer returns `WRONG`; with
  `SupportPlan((("e2e/conftest.py", "A"),), True, "")` the outcome is `fails_at_head` with `support == "base"` and the
  file is back after the run; with an empty plan the outcome is today's (`accepted`), which shows the hole), and SCN-VER-122 (a harmless
  `e2e/conftest.py` and `GOOD`: `accepted` with `support == "base"`). Then
  `generate._discriminates` and `generate_ui_test`/`generate_ui_tests(..., support)` as design D9, the fallback run
  `e2e-head-support`, `GeneratedOutcome.support`, `verify.generated{support}`, and `ladder._generate_step` passes
  `support_plan(...)`. `tests/unit/verifier/test_generate.py` stays green with an empty plan as the default.
  (L4-VER-035)

## 6. Integration (orchestrator)

- [x] 6.1 Merge the branches of groups 1-5 (groups 3 and 4 both edit `verifier/types.py` and `verifier/report.py`, in
  different classes and sections); run `tests/unit` in full, `ruff`, `mypy`, `check_spec.py`, and
  `npx --yes @fission-ai/openspec@1.14.1 validate detect-test-tamper --strict`. Re-run the reviewer's four
  reproductions from the session scratchpad against the merged branch, unchanged and not committed, and record their new
  output lines in the merge commit message (expected: impl-4 `red: failed`; v2[True] a run that does not PASS; v6_full
  audit `failed`; v8 `SAME_NAME_ELSEWHERE=True` a blocker for the harness and a listing for a person).
- [ ] 6.2 One independent adversarial review of the whole change (session model): a weakening the comparison misses, an
  honest red it refuses, the restore of the support files after a crash, and the fallback condition. Fix confirmed
  findings with tests.

## 7. Docs

- [x] 7.1 `docs/SPEC.md`: replace the first paragraph of L4-IMP-006 (§7.5) with the MODIFIED text of
  `specs/implementer/spec.md` **without its last sentence** ("The paragraphs of L4-IMP-006 that follow …": an
  instruction to the editor, not spec text); keep the paragraphs after it, and add to the guard-notes paragraph that a
  `guard.test_tamper` with `action: "rejected"` is not a note (the failed attempt's reason and excerpt carry it); add `**L4-IMP-045**` to `**L4-IMP-048**` after
  L4-IMP-016 in §7.5 with the ADDED texts; in L4-IMP-002's red item, after "The red phase MAY change paths matching
  `tdd.test_globs` and `tdd.test_support_globs`", add "(a test that existed before the step stays as it is, L4-IMP-048)";
  in §10.2 change the three cells of the step table as the MODIFIED L4-VER-002 says; add `**L4-VER-030**` to
  `**L4-VER-036**` after L4-VER-018 in §10.4 with the ADDED texts; add the event `guard.test_tamper{phase: "red", rule:
  "pre-existing test", action: "rejected", tests, why}` next to `guard.test_tamper` in L4-STA-001's event list; add
  SCN-IMP-260..277 to §23.7 and SCN-VER-100..125 to §23.9 in the SPEC form (`#### SCN-… (±) title · L4-…`, then
  `- **Given**`, `- **When**`, `- **Then**`), each naming its requirements so every new requirement is cited; add a row
  to the change table of §21 after the last row present, numbered one more than it: `detect-test-tamper` | a red step
  that changes, rebinds or deletes a pre-existing test fails its attempt; step 1 compares pre-existing tests per test on
  the AST by file and qualified name and blocks a harness change without an allowance (people's listed); audit tests and
  a generated test's head run use the unit's support files at their base versions, with them in place only after a
  clean content scan (L4-IMP-045..048, L4-VER-030..037; `openspec/changes/detect-test-tamper/`) | the reviewer's four
  reproductions: no false PASS. `docs/runbook.md`: under the verifier's FAIL causes, the three new step-1 blockers with
  the fix (a person restores the test on the unit branch in their own commit, `git checkout <base> -- <path>`, or makes
  the wanted change in their own commit; then `l4 resume`) and the audit `support` field. `CHANGELOG.md`: a section
  `## 0.4.16 (unreleased)` above the newest section (create it when absent), with `### Fixed` entries for the four
  findings in the house style (what a consumer sees, the requirement ids). Tests: `python scripts/check_spec.py
  docs/SPEC.md` clean (no UNCOVERED, no UNDEFINED, no duplicate ids) and the docs tests under `tests/unit/` that read
  the changelog stay green. (L4-IMP-045..048, L4-VER-030..037, L4-IMP-006, L4-VER-002)

## 8. Amendment: the comparison (L4-IMP-045, L4-IMP-046, L4-IMP-047, L4-IMP-049; design D12)

Groups 8 to 13 apply the amendment of design section 6, after the adversarial review of `ae802740`. The reproductions
are in `/private/tmp/claude-501/-Users-alexandruiacobescu-gooseProjects-agentic-L4-development/95921d2c-9fc5-43bf-a16f-1c552b9ad0e8/scratchpad/review-tamper/` (named below relative to it; design 6.1 lists them). Each asserts the bug today: a port copies it into
the named test file and flips its assertion to the fixed behaviour, and must fail before the fix. Order: 8.1 then 8.2;
9.1 before 9.2-9.4, 11.1 and 12.1; 10.1 needs 9.2 for its end-to-end part; 13 last. Groups 1-7 stay as they are.

- [ ] 8.1 Tests first, new `tests/unit/implementer/test_tamper_bypass.py`: port `probes/pure_bypass.py` (it prints `[]`
  for every form) as SCN-IMP-278 at function level (the five module-level forms and `TestCart.test_empty = lambda self:
  None`: every pre-existing test of the file `changed`, `<module>` in the why; the plain `def` control stays `rebound`)
  and SCN-IMP-279 (its `INH`/`INH2`: `TestChild.test_x` changed; a `TestChild` that keeps inheriting: nothing;
  `TestChild` removed: `TestChild.test_x` deleted). In `tests/unit/implementer/test_tamper_compare.py`: port
  `probes/pure_fp.py` and `fmt/before.py` against `fmt/after.py` into the extended SCN-IMP-266 (the generator variable
  `p`, the lambda parameter `code`, the re-indented docstrings: nothing; the probe's class-wrapper refactor stays
  `deleted`), port `probes/pure_move.py` into the extended SCN-IMP-270 (not moved), and keep SCN-IMP-265 (a non-autouse
  fixture appended: nothing for the old tests; an autouse one: every test). Then `src/l4/implementer/tamper.py` as
  design D12: the `<module>` and `<Class>.<class>` parts (`guards._defines_only` plus the non-autouse-fixture rule, a
  leading docstring left out), inherited tests, locals through `symtable`, docstring normalisation (`inspect.cleandoc`,
  lines right-stripped), and `moved` on `(definition, closure)`; update the callers of `moved` in
  `tdd.preexisting_test_changes` and `integrity.check_tests`. Every test of groups 1-3 stays green. (L4-IMP-045,
  L4-IMP-046, L4-IMP-047, L4-IMP-049)
- [ ] 8.2 Tests first, in `tests/unit/implementer/test_red_preexisting_tests.py`: SCN-IMP-278 at red level on the
  bench, with the red of `rt/tests/unit/verifier/test_rv_e2e.py::test_a_code_swap_in_the_test_file` (`CODE_SWAP`): the
  outcome is `failed`, one `guard.test_tamper` for `tests/test_pricing.py` with `rule: "pre-existing test"`, and the
  reason names `test_total_adds_prices` and `<module>`. No code beyond 8.1 is expected. (L4-IMP-048, L4-IMP-049)

## 9. Amendment: step 1 runs the base's tests on the unit's code (L4-VER-038; design D13)

- [ ] 9.1 Tests first. In `tests/unit/verifier/test_support_base.py`: `unit_test_plan` (test and support globs with
  their `extra_` entries; `.l4/` paths and every `tdd.runner_config_files` path left out; an added `fixtures/cart.html`
  left out; an added `tests/fixtures/factory.py`, a changed `tests/fixtures/data.json`, a deleted test file and a
  `tests/checks.py` with no test in), `runner_support` (design D16) and `collect_only_env`. New
  `tests/unit/gates/test_trace_collect_only.py`: in a scratch project with three test files and a `conftest.py`, a
  pytest run with the `l4_trace` plugin and `L4_COLLECT_ONLY` naming one file collects only that file and still loads
  the conftest; without the variable it collects all three. Run it for three command forms (`pytest`, `pytest tests/`,
  `pytest tests/test_a.py`) and assert what each does; an explicitly named file that the hook cannot drop is recorded as
  such in the test (design D15). Then `support_base.unit_test_plan`, `runner_support`,
  `DATA_GLOBS`, `collect_only_env`, and `pytest_ignore_collect` in `src/l4/gates/pytest_trace/l4_trace.py`.
  (L4-VER-033, L4-VER-038)
- [ ] 9.2 Tests first, new `tests/unit/verifier/test_base_tests.py` (end to end with `run_l4`, `valid_spec` and the
  texts of `rt/tests/unit/verifier/test_rv_e2e.py`): port `test_b1_helper_in_another_test_file` as SCN-VER-127,
  `test_b2_fixture_in_conftest` as SCN-VER-128, `test_d_forced_fallback` as SCN-VER-131 (no `verify.step` for step 2),
  and `test_a_code_swap_in_the_test_file` as SCN-VER-126 with both text signals bypassed:
  `monkeypatch.setattr("l4.implementer.tdd.preexisting_test_changes", lambda *a, **k: [])` and the `pre-existing tests`
  entry of `l4.verifier.integrity.CHECKS` replaced by one that returns `Outcome(note="bypassed")` (the tuple holds the
  function objects, so patch the tuple). Each asserts the verdict FAIL, the step-1 note, the finding title and
  `tests.test_pricing::test_total_adds_prices` (or, for SCN-VER-131, `tests/test_pricing.py` and `KeyError`). Add
  SCN-VER-138 (the allowances and the parametrised case). Then `src/l4/verifier/base_tests.py` (`check_base_tests`,
  design D13 steps 1-9 without the repeat and the reuse: step 4's fail-closed no-report case and step 7's allowances
  are in), its call and its row in the ladder's integrity step, the `verify.base_tests` event, the evidence file, and
  the row in verification.md. The existing tests stay green, among them `tests/unit/orchestrator/test_stale_tests.py`
  and the `task.unfrozen` flows (`tests/unit/implementer/test_named_unfreeze.py` and the ladder tests that use it),
  which the allowances cover; two mechanical changes are expected and are the only assertions to update: the step-1
  note counts one more sub-check (`8 sub-checks`), and a test that asserts the exact `gate.finished` sequence of a
  verification now sees `setup-base-tests` and `base-tests` in step 1 (and `base-tests-base` when R0 runs).
  (L4-VER-038, L4-VER-036)
- [ ] 9.3 Tests first, in `tests/unit/verifier/test_base_tests.py`: SCN-VER-139 (an earlier round's `base-tests.json`
  with the same base sha and command: `base_source: "evidence"` and no `base-tests-base` gate in `gate.finished`; one
  with an empty `passed` list is not reused; a base test made flaky with a counter file: the minor finding, the row
  `ok`). Then D13 step 5 (the reuse and its trust rule) and step 6 (the repeat). (L4-VER-038, L4-VER-036)
- [ ] 9.4 Tests first: port `rt/tests/unit/verifier/test_rv_step1.py` into `tests/unit/verifier/test_integrity_tamper.py`
  (SCN-VER-137, the note of `check_tests` for only-Go/TypeScript changes) and into `test_base_tests.py` (SCN-VER-137,
  the run: a bench whose gate command `python tools/fake_runner.py` writes one JUnit case per `func Test…` in `*_test.go`
  and per `test('…')` in `*.test.ts`, passed when its body contains `3.75`; the harness red commit that weakens both
  fails both). Then the note in `integrity.check_tests`. (L4-VER-038, L4-VER-030)

## 10. Amendment: helper modules and the content scan (L4-VER-039; design D14)

- [ ] 10.1 Tests first. In `tests/unit/verifier/test_scan.py`: SCN-VER-129 at function level (`result_hooks` on each
  form, with the texts of design D14; a wrapper `pytest_runtest_call` keeps its old text). In
  `tests/unit/verifier/test_integrity_support_patch.py`: `check_scan` reads a changed `tests/checks.py` that defines no
  test (a `pytest_runtest_setup` there is a hit; the patch rule of L4-VER-037 runs on it too; a file with a test is not
  read as support). In `tests/unit/verifier/test_base_tests.py`: port `test_c_pyfunc_call_hook` and
  `test_c2_modifyitems_replaces_the_body` as SCN-VER-130 with the `content scan` entry of
  `l4.verifier.integrity.CHECKS` replaced by one that returns `Outcome(note="bypassed")`: FAIL from the run row alone.
  Then `scan.result_hooks` and the helper rule in `integrity.check_scan` (the same file set for `opened.new_patches`).
  (L4-VER-039, L4-VER-037)

## 11. Amendment: the audit (L4-VER-033, L4-VER-034; design D15)

- [ ] 11.1 Tests first. In `tests/unit/verifier/test_ladder_tamper.py`: port `test_e_patch_in_the_units_test_module`
  as SCN-VER-133, and `test_d_forced_fallback` plus `test_d2_no_fallback_still_passes` as SCN-VER-132, both with
  `l4.verifier.base_tests.check_base_tests` monkeypatched to an `ok` outcome so that the audit is reached. In
  `tests/unit/verifier/test_audit_support.py`: port `rt/tests/unit/verifier/test_rv_audit_retry.py` as SCN-VER-136
  (and its control), rewrite the tests of SCN-VER-116 and SCN-VER-117 to their new texts, and add `import_failure`
  cases on real pytest output from a scratch project (a production frame, only the audit file's frame, an `ImportError
  while importing test module` section, no frame). SCN-VER-112, -113, -115 and -118 stay green with `support: "base"`.
  Then `audit._judge_written` and its helpers as design D15 (the `unit_test_plan` revert set, `collect_only_env`, the
  zero-value run in the same block, no fallback, `import_failure`, the hold reasons, the W-D2 retry in the reverted
  mode, the `base`/`unchanged` labels), and `ladder._audit_step` builds `unit_test_plan`. (L4-VER-033, L4-VER-034,
  L4-VER-036)

## 12. Amendment: step 5 (L4-VER-035; design D16)

- [ ] 12.1 Tests first, in `tests/unit/verifier/test_generate_support.py`: port `rt/tests/unit/verifier/
  test_rv_generate_fp.py` as SCN-VER-134 (`accepted`, `fixtures/cart.html` present during the head run, no exception)
  and add SCN-VER-135 (an app whose start needs the unit's `e2e/conftest.py`: with the content scan `ok`,
  `support: "head"`; with it `skipped`, `uncollectable` with the reason; no exception either way). SCN-VER-119 and -122
  stay green. Then `generate._head_run` and `_discriminates` (catch `ServerNotReady` in the reverted run, revert
  `runner_support`, `collect_only_env` with the generated file) and `ladder._generate_step`. (L4-VER-035)

## 13. Amendment: integration, review, docs

- [ ] 13.1 Integration (orchestrator): merge groups 8-12; run `tests/unit` in full, `ruff`, `mypy`, `check_spec.py` and
  `npx --yes @fission-ai/openspec@1.14.1 validate detect-test-tamper --strict`. Re-run every reproduction of
  `review-tamper/` unchanged against the merged branch, not committed, and record their new output lines in the merge
  commit message (expected: no `PASS` verdict in `test_rv_e2e.py`; the probes print the fixed results; no exception in
  `test_rv_generate_fp.py`; the retry happens in `test_rv_audit_retry.py`; `test_rv_step1.py` reports the new note).
- [ ] 13.2 One independent adversarial review of groups 8-12 (session model): what the run of D13 reverts and what it
  may hide (a skip, a deselect, a test that only R0 holds), R0 reuse, flakiness, the audit's classification of
  collection errors, the collect-only plugin, and honest units that are refused. Fix confirmed findings with tests.
- [ ] 13.3 Docs. `docs/SPEC.md`: L4-IMP-045, -046, -047 and L4-VER-033, -034, -035, -036 read as the delta now says; add
  `**L4-IMP-049**` after L4-IMP-048 and `**L4-VER-038**`, `**L4-VER-039**` after L4-VER-037; the §10.2 cells as the
  MODIFIED L4-VER-002 says; clause (5) of L4-IMP-006 as its MODIFIED text says (without the editor's last sentence);
  `verify.base_tests` in L4-STA-001's event list; SCN-IMP-266, -270 and SCN-VER-116, -117 as rewritten; SCN-IMP-278,
  -279 in §23.7 and SCN-VER-126..139 in §23.9 in the SPEC form; the change-table row of `detect-test-tamper` names the
  run of pre-existing tests and L4-IMP-049, L4-VER-038, L4-VER-039. `docs/runbook.md`: the blockers `a pre-existing
  test fails on the unit's code` and `a pre-existing test no longer runs on the unit's code` with the fix of design D18,
  the new content-scan hits, and the audit's held reasons. `CHANGELOG.md` under `## 0.4.16 (unreleased)`: the entries
  say that step 1 now runs the base's tests on the unit's code. `python scripts/check_spec.py docs/SPEC.md` clean.
  (L4-IMP-045..049, L4-VER-030..039, L4-IMP-006, L4-VER-002)
