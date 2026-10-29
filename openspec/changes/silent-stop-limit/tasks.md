## 1. The rule (L4-IMP-087, L4-IMP-024)

- [x] 1.1 Write the tests first (follow tests/unit/implementer/test_liveness_step.py and test_escalation.py; add
  `tool_calls` (and tokens) knobs to the fake adapter's `Step` in tests/unit/implementer/fake.py so an idle stop can
  report 0 or more tool calls; give SCN-IMP-202's existing test `tool_calls=1` if it flips). Then make design D1 in
  `agent_step` and add `silent` to the limit kind (`l4.agents.base`), with `agent.idle{silent}`. Cases: SCN-IMP-426
  at step level (RoleLimit kind silent, no attempt), SCN-IMP-427, SCN-IMP-428, SCN-IMP-429.
  Result: `agent_step` computes `silent` (status `timeout`, `watch.stopped_idle_s` set, a stream reader seen, 0 tool
  calls, more than one `roles.implementer` profile), writes it into `agent.idle{silent}` and raises `RoleLimit` with a
  `LimitSignal(kind="silent", source="run.idle", resets_at=None)` on the run after `agent.finished` and the cost
  events. Deviations from D1: `LimitSignal` has no `detail` field, so "no output for <idle_timeout>" is its
  `raw_excerpt` (and the run's `detail`, which the `RoleLimit` message and the park line show); `silent` was added to
  the `LimitSignal.kind` Literal in `l4.agents.base`. The fake adapter lives in `src/l4/agents/fake.py`, not under
  tests: its `Step` got `tool_calls`, `stream_reader`, `input_tokens` and `output_tokens`, and an idle step now starts
  the watch with a reader and feeds it the tool calls. The escalation test that stops two steps idle got `tool_calls=1`
  (SCN-IMP-202's own test runs a single profile and did not flip). Tests: 40 passed (test_liveness_step.py,
  test_fake.py).

## 2. The limit path (L4-IMP-087, L4-AVL-003/005/006)

- [x] 2.1 Write the tests first (tests/unit/orchestrator/test_fallback.py, test_escalation.py,
  tests/unit/verifier/test_fixloop_fallback.py, tests/unit/availability/test_fallback.py). Then make sure the `silent`
  kind goes through `switch_profile`/`on_limit` with `availability.default_cooldown`, clears the probe cache, records
  the cool-down and fallback with `kind/reason: silent`, and words the previous-attempt note ("the profile went silent:
  no output for <N>"). Cases: SCN-IMP-426 end to end (events, the step again on profile 2, the next task on profile 2),
  SCN-IMP-430, SCN-IMP-431, a silent fix task moves once, a judge on the same adapter and model is skipped while
  cooling.
  Result: the limit path needed no change for the cool-down, the cleared hello and the fallback: `cooldown_until`
  already gives `default_cooldown` to any kind but `credits`, `Factory.on_limit` invalidates the probe cache and
  records `availability.fallback{reason: silent}` (the run's `limit` is set, so the reason is the kind), and the
  loop's `seed_attempts` counts only `task.attempt_failed`, so a silent step is no attempt and the profile that took
  over restarts the step. What changed: `_previous_attempt_block` words a silent stop ("went silent: no output for
  <implementer.idle_timeout>, so L4 stopped it", `limit="silent"` kept on the tag; both the orchestrator and the fix
  loop use it, so no `PreviousAttempt` field was added) and the `agent.idle` progress line of a silent stop adds that
  it is a limit of the profile, not a failed attempt. SCN-IMP-430 needed no code either: after the silent `glm` the
  task restarts on the run's profile, which has the earlier failures seeded, so `_escalate_if_due` asks for the next
  usable profile and passes the cooling `glm` to `sonnet`. Tests: orchestrator test_fallback 10, orchestrator
  test_escalation 11, verifier test_fixloop_fallback 3, availability test_fallback 45, implementer test_escalation
  19, obs test_progress 35, all passed.

- [x] 2.2 Review fixes: a task's second silent stop counts as a failed attempt (an all-silent chain halts, SCN-IMP-438);
  OpenCode named in the risk text; a second limit in a fix task cools its profile; a limit the adapter found is kept;
  tests for `idle_timeout: 0`, the deadline's cancel and the kept limit.
  Result: `agent_step` calls `_silent_before` (an `agent.idle{silent: true}` of the same task and fix unit in
  `deadline.window` of the unit's ledger) before it classes a stop as silent; a later one records
  `agent.idle{silent: false, reason: "silent: already once for this task"}` and fails the attempt. The window is the
  one that counts attempts, so a task's commit, a retry, a resume or a restart gives a fresh first stop. The silent
  branch raises the run unchanged when the adapter already set `run.limit`. `Factory.cool_limited` is the first half of
  `on_limit`; the fix loop calls it for the second limit of a fix task before the unit parks (it applies to any limit
  kind, not only silent). The progress line names the reason. Proposal and design (D1, D2, D3) and the spec (L4-IMP-087,
  SCN-IMP-438) amended. Tests: test_liveness_step 32, orchestrator test_fallback 11, verifier test_fixloop_fallback 4,
  obs test_progress 35, availability test_fallback and test_review_fixes pass.

## 3. Checks

- [x] 3.1 Run only the test files you changed or added, once each (the machine is loaded; CI runs the full suite),
  then ruff check and ruff format on the changed files. Report the counts.
  Result: each changed or added test file ran once: tests/unit/implementer/test_liveness_step.py and
  tests/unit/agents/test_fake.py 40 passed, tests/unit/orchestrator/test_fallback.py 10, test_escalation.py 11,
  tests/unit/verifier/test_fixloop_fallback.py 3, tests/unit/availability/test_fallback.py 45,
  tests/unit/implementer/test_escalation.py 19, tests/unit/obs/test_progress.py 35, all passed (163 tests in 8
  files). `ruff check` and `ruff format --check` pass on the 12 changed source and test files.
