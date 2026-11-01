## 1. The configuration, prompt and schema (D4, D7)

- [ ] 1.1 Write the tests first (tests/unit/delegate/test_prompt.py, tests/unit/config/ or wherever `DelegateCfg` is
  tested): `delegate.batch_size` defaults to 6, refuses 0 and 21; `batch_schema()` accepts `{results: [result]}` with 1..N
  items and refuses an extra key; `build_batch_prompt` holds the unit's specification once, each question's block and
  verdict material under `# Question Q-NNN`, the previous-discard reason of the question that has one, the earlier
  answers without the batch's questions, ends `Decide questions … now.`, redacts every text, and its digest is the
  sha256 of the system and user text as sent. Then implement `DelegateCfg.batch_size`, `BATCH_SYSTEM`,
  `build_batch_prompt`, `batch_schema`, `delegate-batch.schema.json` (packaged like `delegate-result.schema.json`) and
  `BATCH_MAX_CHARS`, and the doctor's DLG settings line.

## 2. The batched pass (D1, D2, D3, D5, D6)

- [ ] 2.1 Write the tests first (tests/unit/delegate/test_batch.py, using the fixtures of test_pass.py and the verdict
  questions of tests/unit/verifier/test_verdicts.py or test_delegate_fix_unit.py): SCN-DLG-127 to SCN-DLG-133. Then
  implement the batch forming in `_Pass.run`, `_ask_batch` (the limit path to the next profile, the per-status
  outcomes, the per-result checks), the money fit, the per-question `delegate.asked`, the single `budget.cost` with the
  per-result shares, `delegate.pass{calls}`, and `max_turns`/`max_budget_usd` for a batch.
- [ ] 2.2 The existing delegate, verifier and orchestrator tests: those that have two or more verdict questions due in
  one pass and test one call per question get `delegate.batch_size: 1` with a comment naming why; any other failure is
  a defect of 2.1.

## 3. Checks

- [ ] 3.1 SPEC.md (L4-DLG-028; L4-DLG-003's flood paragraph, L4-DLG-004, L4-DLG-005, L4-DLG-009; the `delegate.asked`
  record; §3.2 `delegate.batch_size`; SCN-DLG-127..133; row 116), CHANGELOG, the delegate, verifier-delegate and
  orchestrator-delegate suites, the docs tests, ruff, `openspec validate delegate-batch --strict`.
