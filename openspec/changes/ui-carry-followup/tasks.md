Read `design.md` first (D1-D5). Requirements: L4-VER-096..098, scenarios SCN-VER-412..426 (`specs/ui-carry-followup/spec.md`).
R1 (group 1) and R2 (groups 2 and 3) need nothing of each other. Run single test files only
(`uv run --frozen pytest <file> -q -p no:cacheprovider`), never a directory, never two runs at once, and never a wait loop
on `pgrep`. Every group writes its tests first, runs them and sees them fail, then changes the code.

## 1. A follow-up reads its merged parent's criteria at the base's wording (L4-VER-096, D1)

- [x] 1.1 Tests first, in a new `tests/unit/specs/test_parent_text.py` for the pure function and a new
  `tests/unit/verifier/test_family_parent_text.py` for the family (a temporary git repo as `test_fixloop_kiro.py` builds one):
  SCN-VER-412 (the reworded scenario takes the base's text and keeps its id, alias, capability, requirement, scenario,
  `source_path`, `source_line`; both real shapes: a path and a count), SCN-VER-413 (renamed requirement, a duplicate base id,
  an equal text, an empty base text, no base commit or unreadable git, a Kiro follow-up: all unchanged), SCN-VER-414 (the own
  delta wins and is not carried), SCN-VER-415 (the judge prompt, the writer prompt and the red step read the same text; an
  accept bound to the old `text_sha256` is not in force).
- [x] 1.2 Then add `read_at_base(parent, base)` (pure, beside `unchanged_ids` in `src/l4/specs/criteria.py`) and call it in
  `FamilyProvider.merged_parent_criteria` (`src/l4/verifier/fixloop.py`) for an OpenSpec family, with `base_rev` a lazily read,
  once-per-provider argument that `family_of` passes. Share the base-commit rule of `discrimination.unit_base` and
  `preconditions.check_preconditions` in one helper that the three call (for the verifier the commit is the merge base of
  `refs/remotes/origin/<base_branch>` and `HEAD`). A failure to read gives `None` and no rewrite.
- [x] 1.3 Read how a task's workbench gets its `provider` in `src/l4/orchestrator.py`, `src/l4/services.py` and
  `src/l4/implementer/` and say where it differs from `family_of`'s. If the red step of a follow-up's task reads a plain
  provider, give it the same family (or the same rewrite) so `tdd.unchanged_on_base` and step 4 read one text (L4-IMP-093);
  add a test for it. Do not widen anything else of the red step. Also read the other callers of `family_of`
  (`src/l4/delegate/run.py`, `src/l4/verifier/legacy.py`, `fixloop.py` `:346` and `:489`): they build the family without
  `bring_in_base` before them, so say whether the base commit they read can be older than the verifier's, and make them read
  the same commit or nothing.
- [x] 1.4 Run `tests/unit/specs/test_criteria.py`, `test_base_criteria_at.py`, `test_followup_marker.py`,
  `tests/unit/verifier/test_fixloop.py`, `test_fixloop_kiro.py`, `test_fixloop_own_criteria.py` and `test_ui_flow.py`, one at
  a time: nothing of them changes.

## 2. The rule for a test file the unit only added tests to (L4-VER-097, L4-VER-098, D2)

- [ ] 2.1 Tests first, in a new `tests/unit/verifier/test_carry_appended.py` (pure functions over two texts, a name list and
  the facts of the diff): SCN-VER-416..420 and 422..425 one case per row of D4: the real shape (+11/-0, an `it` between two
  tests, at the end of a `describe`, at the end of the file); a deleted blank line or comment; a line added inside the traced
  test, inside another old test, a new test nested in an old one; a hook, an import, a constant, a `vi.mock`, a `describe`
  wrapper, a template-literal title, an `.each` table; a new test with an old title; an unclosed string, JSX text with an
  apostrophe, a traced test whose first line is not a call line; and for Python a function, a method of an old class, a
  redefinition of an old name, a decorator, a nested def, a changed line, a syntax error, blank and comment lines. Also a
  reading of ids of the form `<dotted path>::C-... title` through `test_locate.window`.
- [ ] 2.2 Then add `src/l4/verifier/carry_appended.py` (new): `appended_only(path, base_text, head_text, traced, names,
  stat)` for JavaScript and TypeScript and for Python, returning a bool and never raising (any failure is `False`); the
  closed-block scanner; move `_test_names_of` from `src/l4/implementer/tdd.py` to `test_locate` (the red step imports it
  from there; its tests stay green). Reuse `test_locate.window` and `outside_tests` and `scan._qualified`; do not change their
  behaviour for their other callers.
- [ ] 2.3 Run `tests/unit/implementer/test_test_locate.py`, `test_red_preexisting_tests.py` (it holds the
  `named_other_changed` tests) and `tests/unit/verifier/test_scan.py`, one at a time.

## 3. The carry and what it records (L4-VER-097, D2)

- [ ] 3.1 Tests first, in `tests/unit/verifier/test_ui_step.py` (`carried_from_base(..., appended=...)`: a changed file that
  the predicate accepts is carried; one it refuses is not; every other condition still decides per file: SCN-VER-423) and
  `tests/unit/verifier/test_ui_flow.py` (the ladder: step 1's record lists F in `reverted`, lists it not,
  names a tracing test in `failing`, `not_run` or `flaky`: SCN-VER-416, 421; `verify.generated{appended}`; the row of
  `_generated_rows`; a reused round keeps the outcome: SCN-VER-426), and `tests/unit/verifier/test_report_m15.py` for the row.
- [ ] 3.2 Then `carried_from_base` (`src/l4/verifier/ui_step.py`) takes an optional predicate `appended(test_id, file)` that
  accepts a changed file (default: none), `ladder._generate_step` builds it from `git diff --name-status` and `--numstat`
  (`src/l4/verifier/playwright.py` beside `unit_changed_files`), the blobs of `base_sha` and the head read through git, the
  step-3 reports (`run.report`, `run.e2e`) and step 1's `reverted`, `failing`, `not_run` and `flaky`. These last four are not
  in the `events` that `_generate_step` receives (`verify_unit` reads them at `ladder.py:750`, before step 1 emits
  `verify.base_tests`): return them from `base_tests.check_base_tests` (`Outcome`) into a `_Run` field in `ladder.integrity()`
  and read that field; do not re-read the ledger; `GeneratedOutcome` and the
  `verify.generated` event carry `appended`; `report._generated_rows` writes the row of SCN-VER-426. A file that is changed and
  neither unchanged nor accepted keeps the criterion a gap.
- [ ] 3.3 Run `test_ui_step.py`, `test_ui_flow.py`, `test_report_m15.py`, `test_resume.py` and `test_fixunit.py`, one at a time.

## 4. Documents (after 1-3, by the orchestrator)

- [ ] 4.1 `docs/SPEC.md`: L4-VER-086 (condition 3: `or meets L4-VER-097/098`; the "Residual risk" and "restated" sentences:
  a parent scenario that a later change reworded is read at the base's wording, L4-VER-096); L4-FBK-010 (the family's parent
  criteria at the base's wording for an OpenSpec follow-up); the step 5 row of the ladder; the `verify.generated` entry of 12.1
  (`appended`); change-table row 141 and a new row for this change, marked SLIPPABLE; the three requirements and SCN-VER-412..426.
  Run `uv run --frozen python scripts/check_spec.py docs/SPEC.md`.
- [ ] 4.2 `docs/runbook.md`: the paragraph that starts `From 0.4.60 a UI criterion that the unit did not change`; `CHANGELOG.md`
  (Changed: both rules; Upgrade: an accept bound to the old text of a rewritten criterion is asked once more).
- [ ] 4.3 Checks: `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files changed;
  `openspec validate ui-carry-followup --strict`.
