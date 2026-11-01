## 1. The configuration, prompt and schema (D4, D7)

- [x] 1.1 Write the tests first (tests/unit/delegate/test_prompt.py, tests/unit/config/ or wherever `DelegateCfg` is
  tested): `delegate.batch_size` defaults to 5, refuses 0 and 21; `batch_schema()` accepts `{results: [result]}` with 1..N
  items and refuses an extra key; `build_batch_prompt` holds the unit's specification once, each question's block and
  verdict material under `# Question Q-NNN`, the previous-discard reason of the question that has one, the earlier
  answers without the batch's questions, ends `Decide questions … now.`, redacts every text, and its digest is the
  sha256 of the system and user text as sent. Then implement `DelegateCfg.batch_size`, `BATCH_SYSTEM`,
  `build_batch_prompt`, `batch_schema`, `delegate-batch.schema.json` (packaged like `delegate-result.schema.json`) and
  `BATCH_MAX_CHARS`, and the doctor's DLG settings line.
  Result: `DelegateCfg.batch_size` (5, 1..20; the default caps fit five answers), `BATCH_SYSTEM` (from `SYSTEM` with
  two asserted replacements), `build_batch_prompt` (shared `_specification`, `_answers_part`, `_verdict_part`,
  `_previous_part`; `build_prompt`'s output unchanged), `batch_schema(n)`, `delegate-batch.schema.json`,
  `BATCH_MAX_CHARS`; the doctor's limits. test_prompt 31 (8 new), test_delegate_config 23; both failed before the
  change (ImportError, the defaults).

## 2. The batched pass (D1, D2, D3, D5, D6)

- [x] 2.1 Write the tests first (tests/unit/delegate/test_batch.py, using the fixtures of test_pass.py and the verdict
  questions of tests/unit/verifier/test_verdicts.py or test_delegate_fix_unit.py): SCN-DLG-127 to SCN-DLG-133. Then
  implement the batch forming in `_Pass.run`, `_ask_batch` (the limit path to the next profile, the per-status
  outcomes, the per-result checks), the money fit, the per-question `delegate.asked`, the single `budget.cost` with the
  per-result shares, `delegate.pass{calls}`, and `max_turns`/`max_budget_usd` for a batch.
  Result: `_question` split into `_prechecks`, `_defer_for_time`, `_ask_one`, `_select_and_ask`; `_prompt` into
  `_material` and `build_prompt`; the tail of `_ask` into `_settle`; new `_batched`, `_batch_keys`, `_money_fit`,
  `_batch_prompt`, `_ask_batch`, `_share`; `limits.batch_failed`. A batch reply that is not a batch document (a schema
  break included) defers each question with `error` (then asked alone), and no question counts against the cap when the
  batch's selection finds no profile. tests/unit/delegate/test_batch.py 21 (SCN-DLG-127 with the defaults, 128..133, a
  schema break asked alone next, two results and a stray result, no attempt left, a limit moving the batch, an odd
  leftover asked alone, and the forming rules); they failed before the change.
- [x] 2.2 The existing delegate, verifier and orchestrator tests: those that have two or more verdict questions due in
  one pass and test one call per question get `delegate.batch_size: 1` with a comment naming why; any other failure is
  a defect of 2.1.
  Result: no existing test needed `batch_size: 1`; tests/unit/docs/test_delegate_docs.py and
  test_delegate_0422_docs.py list SCN-DLG-127..133 as a later change's.

## 3. Checks

- [x] 3.1 SPEC.md (L4-DLG-028; L4-DLG-003's flood paragraph, L4-DLG-004, L4-DLG-005, L4-DLG-009; the `delegate.asked`
  record; §3.2 `delegate.batch_size`; SCN-DLG-127..133; row 116), CHANGELOG, the delegate, verifier-delegate and
  orchestrator-delegate suites, the docs tests, ruff, `openspec validate delegate-batch --strict`.
  Result: L4-DLG-028 with the review fixes (D8: the money after a limit, counted once with no profile left; the deadline
  at the first survivor; a consecutive run; more than one result), L4-DLG-003/-004/-005/-009, the `delegate.asked`
  record, §3.2 `delegate.batch_size: 5`, SCN-DLG-127..133, row 116, CHANGELOG, the runbook and yolo-mode docs.
  tests/unit/delegate 307, test_delegate_fix_unit 2, test_delegate_hook 5, test_delegate_next_run 10,
  test_delegate_plan_cli 3, test_delegate_config 23, test_checks_delegate 31, tests/unit/docs 120, release notes 9;
  `scripts/check_spec.py` clean, ruff clean, `openspec validate delegate-batch --strict` valid. An independent review
  found the money after a limit (verified by its probe: $30 counted against $15) and minor order and test gaps, all
  fixed; a second pass found the no-profile-left case, fixed with a test that fails before.
