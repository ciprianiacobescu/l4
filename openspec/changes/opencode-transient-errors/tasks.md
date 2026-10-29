## 1. Classify (L4-AVL-002, L4-AVL-005)

- [ ] 1.1 Write the tests first (patterns: `tests/unit/availability/conftest.py` `make_ctx`/`FakeRun`; `opencode_hello`
  in `tests/unit/availability/test_hello_failure_class.py`; `error_run` in
  `tests/unit/availability/test_probes_opencode_v2.py`; the recorded fixture
  `tests/fixtures/recorded/opencode/1.18.33/error-upstream-503.jsonl`). Then make the change of design D1 in both
  OpenCode hellos. Cases: SCN-AVL-28 (v1 fixture → transient, reason names 503); v2 with no `status` and "overloaded"
  → transient; a bracketed `[401]` → auth; 429 in the text and credits stay limits; `[400]` → other.

## 2. Retry the hello (L4-AVL-006)

- [ ] 2.1 Write the tests first (follow `test_a_529_hello_is_retried_once` in `tests/unit/availability/test_probes.py`,
  which records waits through `sleep=waits.append`). Then add `hello_retry` (design D2) and use it in both OpenCode
  hellos; copy `hello_retry_wait_s` in `to_event`. Cases: SCN-AVL-29, SCN-AVL-30, SCN-AVL-31 for v1 and v2; a deadline
  that fires during the wait stops the second hello (`DeadlineReached` passes through); the selection does not cache
  the transient result and shows `hello_retry_wait_s` in `availability.selected`. Give every existing test that now
  reaches a transient hello a `sleep=` (no real 20 s sleeps in the suite).

## 3. The run path (L4-AVL-006)

- [ ] 3.1 Write the tests first (the tests of `_classify_error`: grep it under `tests/unit/agents`; the in-run retry of
  `l4.llm.agent_judge`: grep `availability.transient` under `tests/unit`). Then make the change of design D3 for v1 and
  v2. Cases: a bracketed `[502]` → `transient` True, detail keeps ", retryable"; a bracketed `[401]` → status `auth`;
  a 429 → limit, not transient; SCN-AVL-32 through `AgentJudge` with a fake OpenCode adapter run.

## 4. Checks

- [ ] 4.1 Run `tests/unit/availability`, `tests/unit/agents` and `tests/unit/llm` once with pytest (never in a loop) and
  wait for them to finish. Run ruff check and ruff format on the changed files. Report the counts.
