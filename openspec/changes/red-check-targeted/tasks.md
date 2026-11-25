Read `design.md` first; it names the code each decision touches (D1-D9). Requirements: L4-CFG-007, L4-GAT-007..009,
L4-IMP-117..122 (`docs/SPEC.md`), scenarios SCN-CFG-08..12, SCN-GAT-12..20 and SCN-IMP-626..652. Run single test files
only (`uv run --frozen pytest <file> -q -p no:cacheprovider`), never a whole directory, never two runs at once, and never
a wait loop on `pgrep`.

Test setup: the red-step tests extend the bench of `tests/unit/implementer/test_tdd_red.py` (its `make_bench`, fake
agent steps and scripted gate reports) and the recheck tests of `tests/unit/implementer/test_step_recheck.py`, which
already script two gate runs of one step. Script `test-targeted` and `test` as two gate names with their own reports.
Build base reports with `TestReport` and `TestCase` of `l4.gates.junit`. A TypeScript repository needs no stub: use
ids such as `test/pricing.test.ts::total of two prices`. A Python bench uses `tests.test_pricing::test_total`.
Config tests load a YAML text through `l4.config.loader` as `tests/unit/config/test_gates_test_timeout.py` does.

## 1. The key and its load rule (L4-CFG-007; D1)

- [x] 1.1 Write the tests first in a new `tests/unit/config/test_gates_red_check.py`: SCN-CFG-08 (loads, and the
  default is `full`), SCN-CFG-09 (exit 2 with the two key names), SCN-CFG-10 (one configuration per command; the message
  holds no part of the command, checked with a marker word in it), SCN-CFG-11 (a bad `targeted` with `full` loads),
  SCN-CFG-12 (`-k 'slow or fast'` loads). Run it and see the new tests fail.
- [x] 1.2 Then add `red_check: Literal["full", "targeted"] = "full"` and a `model_validator(mode="after")` to
  `UnitGate` in `src/l4/config/schema.py` (D1, `ValueFree`). Run the file, then `tests/unit/config/test_loader.py`. The
  reference configuration of `docs/SPEC.md` section 3.2 already shows `red_check`, so these fail until this step is done
  and must pass after it: `tests/unit/config/test_schema.py::test_version_only_file_yields_full_defaults`,
  `tests/unit/config/test_schema.py::test_reference_config_validates_with_placeholder_commit` and
  `tests/unit/docs/test_delegate_docs.py::test_the_reference_configuration_has_the_delegate_section_and_profiles`.

## 2. The pure parts (L4-GAT-007, L4-GAT-008, L4-GAT-009, L4-IMP-117; D2-D5)

- [x] 2.1 Write the tests first in a new `tests/unit/implementer/test_red_check.py`:
  - `targeted_command` (SCN-GAT-12): the argv of `shlex.split(result)` for two files, one with a space, one with a
    quote and a `$`; the other words of the template are unchanged;
  - `with_targeted` (SCN-GAT-14): the tests, the empty collection errors, the base object unchanged;
  - `unusable` (SCN-GAT-15 to SCN-GAT-17): a table with one case per word of L4-GAT-009 and one usable report; the
    order of the checks (a report with a collection error and an old id gives `collection_errors`); `file_of_id` for
    a TypeScript id (`test/a.test.ts::x`), a dotted Python module id and an id that no listed file owns;
  - `choose` (SCN-IMP-628 to SCN-IMP-632): a table with one case per rule of L4-IMP-117 and the order of the rules (a step
    with a stub and a changed file gives `stubs`); `changed` as `{path: existed}`; the run's ledger path is ignored;
    `-x.test.ts`, 51 files and 8,000 bytes; a `.py` file with no test function is a support file; `test/data.ts` is one.
  Run the file and see the tests fail.
- [x] 2.2 Then add `src/l4/implementer/red_check.py` (`choose`, `targeted_command`, `with_targeted`, `unusable`, `Targeted`,
  `Full`), and factor `is_support_file` of `src/l4/verifier/support_base.py` into `is_support_source(cfg, path,
  source)` and a wrapper that reads the revision (D2). Run `tests/unit/implementer/test_red_check.py`, then
  `tests/unit/verifier/test_support_base.py` and `tests/unit/verifier/test_generate_support.py`, one at a time.

## 3. The red step (L4-IMP-118, L4-IMP-119, L4-IMP-120, L4-GAT-007, L4-GAT-009; D3-D6)

- [x] 3.1 Write the tests first in a new `tests/unit/implementer/test_tdd_red_targeted.py`: SCN-IMP-626, SCN-IMP-627,
  SCN-GAT-13, SCN-GAT-15 to SCN-GAT-20 (each fallback word: the gate `test` runs after `test-targeted`, the verdict is the
  `full` step's, `task.red_check_full` has `why` and a `detail` of at most 300 characters), SCN-IMP-633 (a flaky old test
  in the baseline and a whole-suite report that would fail it: no verdict about it), SCN-IMP-634 (each reason of
  `classify_red` and of the criteria checks gives the text a `full` step gives), SCN-IMP-635 (`RedOutcome.base_report` is
  the baseline), SCN-IMP-636 (`resume_red` reads `check` from `task.red_ok`, and a 0.4.60 event gives `full`), SCN-IMP-637
  (the vacuity check, with a HEAD stub), SCN-IMP-638 and SCN-IMP-639 (the ledger). The first version of SCN-IMP-648
  (a resumed targeted red whose base holds the broken old test as failing, so that green's regressed set is empty and
  nothing is recorded) was reversed in 6.1: the base is measured without the red's files. Also assert that `confirmed_by_base_run` is never
  called with the targeted run's `seconds`. Run the file and see the new tests fail.
- [x] 3.2 Then change `run_red` in `src/l4/implementer/tdd.py`: after `changed = wb.changed_files()` call `choose`
  (with `changed_paths` for the existence), run `test-targeted` instead of `test` when it says so, call `tampered`, and
  either bind `report` and `gate` to the targeted results (`with_targeted`) or reset the tree, run `test` as today and
  record `task.red_check_full`. Add `check` and `files` to `task.red_ok` and `RedOutcome.check`, and set it in
  `resume_red`. A `full` configuration must not call `choose` and must write no new key. Run the file of 3.1, then
  `tests/unit/implementer/test_tdd_red.py`, `test_step_recheck.py` and `test_tdd_green.py`, one at a time.

## 4. The switch (L4-IMP-121, L4-IMP-122; D7)

- [x] 4.1 Write the tests first in a new `tests/unit/implementer/test_tdd_green_red_check.py`: SCN-IMP-640 (a regressed
  base-passing test that fails on the run and on the re-run: `task.red_check_disabled{why: regressed}` and the
  suffix after L4-IMP-105's), SCN-IMP-641 (passes on the re-run: nothing), SCN-IMP-642 (a later red step and a fix-unit
  red run the whole suite with `why: unit_switched`; `l4 retry` and `l4 resume` keep it; a restarted unit's new ledger
  does not), SCN-IMP-643 (`ids_missing`, with the suffix for a missing id and no suggestion of an unfreeze), SCN-IMP-644 (task
  1.2 whose red ran whole, in a unit whose task 1.1 was targeted: the switch is recorded and the reason has no suffix),
  SCN-IMP-645 (once), SCN-IMP-647 (a unit whose `task.red_ok` events have no `check`: no record, no suffix), SCN-IMP-646 (verification's gate runs are the commands of 0.4.60: assert on the verifier's gate
  specs, not on a full round). Run the file and see the new tests fail.
- [x] 4.2 Then add the record and the suffix to `run_green` after the step's own re-run (D7), reading the unit's
  ledger through `_ledger_events` (the unit-wide trigger for `regressed`, the task's own `red.check` for `ids_missing`
  and for the suffix). Run the file of 4.1, then `tests/unit/implementer/test_tdd_green.py`,
  `test_attempt_renewal.py` and `test_loop.py`, one at a time.

## 5. Docs and the check

- [x] 5.1 `docs/SPEC.md` holds the requirements, the scenarios, change-table row 144, the key in section 3.2 and the
  records in section 12.1. Check them against the code and tell the orchestrator where they differ; do not edit
  `docs/SPEC.md`, `CHANGELOG.md`, `docs/runbook.md` or the skill. Run `uv run --frozen python scripts/check_spec.py
  docs/SPEC.md`.
- [x] 5.2 Add `tests/unit/docs/test_red_check_targeted_docs.py` in the style of `test_readiness_entry_and_actor_docs.py`:
  the SPEC holds each ID once as a requirement and in a scenario, the runbook and the skill name `red_check`, and no
  file of the change names a version number of the release.
- [x] 5.3 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.

## 6. Review round: the resumed base, the other green failures, and the gaps (L4-IMP-117, L4-IMP-119..122; D5, D7, D10)

- [x] 6.1 Tests first in `tests/unit/implementer/test_tdd_red_targeted.py`: SCN-IMP-648 (a resumed targeted red measures
  its base with the red's files absent, puts them back byte for byte and with their mode, and green sees the old test
  and records the switch), SCN-IMP-649 (a record the red commit does not match, or a put-back that is not exact, falls
  back to the whole run at the red commit and records `resume_files` or `resume_put_back` once), and the wiring of the
  named-test and stale-test rules from `run_red` into `choose` (SCN-IMP-630). Then `_resume_base`, `_red_files_present`,
  `_run_without` and `RedOutcome.files` in `src/l4/implementer/tdd.py` (D10).
- [x] 6.2 Tests first in `tests/unit/implementer/test_tdd_green_red_check.py` and `test_red_check.py`: SCN-IMP-650 (a
  collection error that names a file of the targeted red: `green_collection` and its suffix; another file or a whole
  red: nothing), SCN-IMP-651 (no readable report or a timeout after a targeted red: `green_no_report`, no suffix),
  SCN-IMP-652 (the switch from the ledger after the key was set back to `full`), a switch first seen on attempt 2, a
  whole red with a missing id records nothing, the folder that `l4 restart` builds has no switch, SCN-IMP-639 (a ledger
  of 0.4.60 folds; one with the new records folds as one without them), and `@` and non-ASCII bytes in
  `red_check._odd` and the 8,000-byte limit. Then `red_check.collection_names`, `_targeted_red_effect` and `_odd`.
- [x] 6.3 `docs/SPEC.md`, the delta spec, `design.md`, the changelog, the runbook and the skill say it (L4-IMP-117,
  L4-IMP-119..122, SCN-IMP-648..652).
