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

- [ ] 1.1 Tests first, new `tests/unit/implementer/test_tamper_compare.py` (pure, no git): SCN-IMP-260 (the
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

- [ ] 2.1 Tests first, new `tests/unit/implementer/test_red_preexisting_tests.py`: port the implementer-4 reproduction
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
- [ ] 2.2 Tests first, new `tests/unit/verifier/test_ladder_tamper.py`: SCN-IMP-274 with `run_l4`, `valid_spec` and the
  verifier-2 texts (appendix A): the script is `[tampering red, red_step(), green_step(), judge_step()]` where the
  tampering red is `red_step()` plus the weakened `tests/test_pricing.py`. Expect: one `task.attempt_failed` whose
  reason starts with `red changed tests that existed before this step: tests/test_pricing.py::test_total_adds_prices`,
  the second red request's prompt contains that reason and `A red step adds new tests with new names`, the verdict PASS,
  and `run.pushed("tests/test_pricing.py")` equal to the fixture's base file. No code change is expected; fix in
  `tdd.py` what this shows. (L4-IMP-048)

## 3. Step 1 (L4-VER-030, L4-VER-031, L4-VER-032)

- [ ] 3.1 Tests first, new `tests/unit/verifier/test_integrity_tamper.py` on `_integrity_helpers.new_repo`: port the
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
- [ ] 3.2 Tests first, in `tests/unit/verifier/test_integrity_tamper.py`: SCN-VER-110 (two harness commits with
  `tdd="red"` for tasks 1.1 and 1.2; the second weakens the first's test) and SCN-VER-111 (the second appends new tests to the
  first's file: no finding). Then add part B to `check_tests` (design D6: `commit_records` and
  `is_harness`, `L4-TDD` `red` or `already-satisfied`, `[test-infra]` skipped, the first parent, tests at the base
  skipped, `tests.superseded` skipped, `moved` within the commit). (L4-VER-032)
- [ ] 3.3 Tests first, in `tests/unit/verifier/test_ladder_tamper.py`: port `test_v2_weakened.py::test_v2[True]` as
  SCN-VER-101 and SCN-VER-121 with `monkeypatch.setattr("l4.implementer.tdd.preexisting_test_changes", lambda *a, **k:
  [])` (the red check of 2.1 bypassed): the verdict is FAIL, the `verify.step` of step 1 is `failed` with a note holding
  `a pre-existing test was changed`, there is no `verify.step` for step 2, and verification.md names
  `tests/test_pricing.py::test_total_adds_prices`. The control (`test_v2[False]`: the test left alone) keeps today's
  green failure `green broke existing tests` and is not ported (its fake runs out of steps). No new code is expected.
  (L4-VER-030, L4-VER-002)

## 4. Audit with the support files at the base (L4-VER-033, L4-VER-034, L4-VER-036)

- [ ] 4.1 Tests first, new `tests/unit/verifier/test_support_base.py` (a `make_bench` worktree with a base commit and a
  head commit): SCN-VER-114 (an added `tests/conftest.py`, a changed `tests/fixtures/data.json`, a deleted
  `tests/helpers/old.py`, a symbolic link at head; inside the block and after it, also when the block raises; mode bits;
  `git status --porcelain` equal before and after; a path whose parent is a symbolic link out of the worktree is not
  touched), and `support_plan` (globs with `extra_test_support_globs`, a `.l4/` path left out, `pyproject.toml` never in
  it, `fallback` true only for a `content scan` row `ok`, the two `why_not` texts). Then write
  `src/l4/verifier/support_base.py` as design D8 says. (L4-VER-033)
- [ ] 4.2 Tests first. In `tests/unit/verifier/test_ladder_tamper.py` port `test_v6_audit_support.py::test_v6_full` as
  SCN-VER-112 (`CONFTEST2` and `BROKEN_IMPL` of appendix A; today it prints `FULL CODE 0 VERDICT PASS`): the
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
- [ ] 4.3 Tests first, new `tests/unit/verifier/test_report_tamper.py`: SCN-VER-120 on a `VerifyResult` built in the
  test (two `AuditRecord`s, `support` `base` and `head`; an `IntegrityReport` with one `allowed_tests` line), and
  SCN-VER-123 (a rejected `AuditRecord` with the reason of design D8 step 3 is listed under `## Rejected audit tests`). Then
  `report.py`: the Audit table's `Support` column (`base`, `head`, `-` for `unchanged` or empty) and the section `##
  Pre-existing tests changed with an allowance (L4-VER-031)` after `## Test changes made by humans`; update the existing
  header assertions in `tests/unit/verifier/test_report*.py` for the new column only. (L4-VER-036)

## 5. Generated UI tests (L4-VER-035)

- [ ] 5.1 Tests first, new `tests/unit/verifier/test_generate_support.py` on the `web` bench of `test_generate.py`:
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

- [ ] 6.1 Merge the branches of groups 1-5 (groups 3 and 4 both edit `verifier/types.py` and `verifier/report.py`, in
  different classes and sections); run `tests/unit` in full, `ruff`, `mypy`, `check_spec.py`, and
  `npx --yes @fission-ai/openspec@1.14.1 validate detect-test-tamper --strict`. Re-run the reviewer's four
  reproductions from the session scratchpad against the merged branch, unchanged and not committed, and record their new
  output lines in the merge commit message (expected: impl-4 `red: failed`; v2[True] a run that does not PASS; v6_full
  audit `failed`; v8 `SAME_NAME_ELSEWHERE=True` a blocker for the harness and a listing for a person).
- [ ] 6.2 One independent adversarial review of the whole change (session model): a weakening the comparison misses, an
  honest red it refuses, the restore of the support files after a crash, and the fallback condition. Fix confirmed
  findings with tests.

## 7. Docs

- [ ] 7.1 `docs/SPEC.md`: replace the first paragraph of L4-IMP-006 (§7.5) with the MODIFIED text of
  `specs/implementer/spec.md` **without its last sentence** ("The paragraphs of L4-IMP-006 that follow …": an
  instruction to the editor, not spec text); keep the paragraphs after it, and add to the guard-notes paragraph that a
  `guard.test_tamper` with `action: "rejected"` is not a note (the failed attempt's reason and excerpt carry it); add `**L4-IMP-045**` to `**L4-IMP-048**` after
  L4-IMP-016 in §7.5 with the ADDED texts; in L4-IMP-002's red item, after "The red phase MAY change paths matching
  `tdd.test_globs` and `tdd.test_support_globs`", add "(a test that existed before the step stays as it is, L4-IMP-048)";
  in §10.2 change the three cells of the step table as the MODIFIED L4-VER-002 says; add `**L4-VER-030**` to
  `**L4-VER-036**` after L4-VER-018 in §10.4 with the ADDED texts; add the event `guard.test_tamper{phase: "red", rule:
  "pre-existing test", action: "rejected", tests, why}` next to `guard.test_tamper` in L4-STA-001's event list; add
  SCN-IMP-260..277 to §23.7 and SCN-VER-100..123 to §23.9 in the SPEC form (`#### SCN-… (±) title · L4-…`, then
  `- **Given**`, `- **When**`, `- **Then**`), each naming its requirements so every new requirement is cited; add a row
  to the change table of §21 after the last row present, numbered one more than it: `detect-test-tamper` | a red step
  that changes, rebinds or deletes a pre-existing test fails its attempt; step 1 compares pre-existing tests per test on
  the AST by file and qualified name and blocks a harness change without an allowance (people's listed); audit tests and
  a generated test's head run use the unit's support files at their base versions, with them in place only after a
  clean content scan (L4-IMP-045..048, L4-VER-030..036; `openspec/changes/detect-test-tamper/`) | the reviewer's four
  reproductions: no false PASS. `docs/runbook.md`: under the verifier's FAIL causes, the three new step-1 blockers with
  the fix (a person restores the test on the unit branch in their own commit, `git checkout <base> -- <path>`, or makes
  the wanted change in their own commit; then `l4 resume`) and the audit `support` field. `CHANGELOG.md`: a section
  `## 0.4.16 (unreleased)` above the newest section (create it when absent), with `### Fixed` entries for the four
  findings in the house style (what a consumer sees, the requirement ids). Tests: `python scripts/check_spec.py
  docs/SPEC.md` clean (no UNCOVERED, no UNDEFINED, no duplicate ids) and the docs tests under `tests/unit/` that read
  the changelog stay green. (L4-IMP-045..048, L4-VER-030..036, L4-IMP-006, L4-VER-002)
