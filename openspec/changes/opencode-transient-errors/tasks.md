## 1. Classify (L4-AVL-002, L4-AVL-005)

- [x] 1.1 Write the tests first (patterns: `tests/unit/availability/conftest.py` `make_ctx`/`FakeRun`; `opencode_hello`
  in `tests/unit/availability/test_hello_failure_class.py`; `error_run` in
  `tests/unit/availability/test_probes_opencode_v2.py`; the recorded fixture
  `tests/fixtures/recorded/opencode/1.18.33/error-upstream-503.jsonl`). Then make the change of design D1 in both
  OpenCode hellos. Cases: SCN-AVL-28 (v1 fixture → transient, reason names 503); v2 with no `status` and "overloaded"
  → transient; a bracketed `[401]` → auth; 429 in the text and credits stay limits; `[400]` → other.

  Result: added `error_status` (the structured integer status, else the `[NNN]` of the message as an `int`, else None)
  and `error_class` (`status_class` of a status, else `text_class` of the message) in `l4.agents.opencode`; both
  hellos (`_hello`, `_hello_v2`) use them, so the auth test reads the bracketed status too. The bracket is searched
  anywhere in the message (the recorded 1.18.33 error has it inside a JSON string, not at the start). Tests added in
  `test_hello_failure_class.py` (the recorded 503 fixture, 11 message and status cases for v1) and
  `test_probes_opencode_v2.py` (7 cases for v2); 11 of them failed before (class `other` for the 503 fixture, `[502]`,
  "overloaded", "unavailable", "connection reset", `[400]` reason without its status; v2 the same plus `[429]`), all
  pass now, and so do the 1186 tests of `tests/unit/availability` and `tests/unit/agents`.

## 2. Retry the hello (L4-AVL-006)

- [x] 2.1 Write the tests first (follow `test_a_529_hello_is_retried_once` in `tests/unit/availability/test_probes.py`,
  which records waits through `sleep=waits.append`). Then add `hello_retry` (design D2) and use it in both OpenCode
  hellos; copy `hello_retry_wait_s` in `to_event`. Cases: SCN-AVL-29, SCN-AVL-30, SCN-AVL-31 for v1 and v2; a deadline
  that fires during the wait stops the second hello (`DeadlineReached` passes through); the selection does not cache
  the transient result and shows `hello_retry_wait_s` in `availability.selected`. Give every existing test that now
  reaches a transient hello a `sleep=` (no real 20 s sleeps in the suite).

  Result: added `hello_retry(ctx, once, transient)` and `with_retry_wait` in `l4.availability.probes` (D2: the deadline
  is checked before and after the wait, the wait is `ctx.sleep or time.sleep`, a second transient answer is final).
  The v1 `_hello` and v2 `_hello_v2` each run `_hello_once` / `_hello_v2_once` through it; the answer is retryable only
  when an error event was read, its class is `transient` and the exit code is not 124. The provider key and
  reachability checks of v1 stay outside the retry. The claude hello moved onto the helper (a straight swap), so it now
  also checks the deadline around the wait and records `hello_retry_wait_s`. `to_event` copies the field next to
  `hello_ms`, and also when the hello failed. New file `test_opencode_hello_retry.py` (28 cases: helper, deadline
  before and during the wait, SCN-AVL-29/30/31 for v1 and v2, the unsupported-version hello, two selections through a
  `Factory`); 10 of them failed against a one-hello stub (no retry, no field, no deadline check), all pass now; the
  existing v2 5xx test got a `sleep=`. `tests/unit/availability` and `tests/unit/agents`: 1214 passed, no real wait.

## 3. The run path (L4-AVL-006)

- [ ] 3.1 Write the tests first (the tests of `_classify_error`: grep it under `tests/unit/agents`; the in-run retry of
  `l4.llm.agent_judge`: grep `availability.transient` under `tests/unit`). Then make the change of design D3 for v1 and
  v2. Cases: a bracketed `[502]` → `transient` True, detail keeps ", retryable"; a bracketed `[401]` → status `auth`;
  a 429 → limit, not transient; SCN-AVL-32 through `AgentJudge` with a fake OpenCode adapter run.

## 4. Checks

- [ ] 4.1 Run `tests/unit/availability`, `tests/unit/agents` and `tests/unit/llm` once with pytest (never in a loop) and
  wait for them to finish. Run ruff check and ruff format on the changed files. Report the counts.
