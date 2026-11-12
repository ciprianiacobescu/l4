## Why

In a consumer's TypeScript unit, green attempt 4 of a task (claude-sonnet, about 20 minutes of agent time) passed every
test of the test gate and failed only its static gates: `pnpm run lint` (one `no-useless-assignment` in `src/main.ts`)
and `pnpm run typecheck` (one TS2322: a literal missing from a row type's union). The harness discarded its changes, as
it does for every failed attempt (`run_green` calls `wb.discard_changes()`; the next prompt gets the failure text, not
the diff). Attempt 5 started again from the red commit, had to redo the whole task plus the two one-line fixes, and
reached the 30-minute step limit. The task halted with `max_task_attempts (3) reached in green on glm (2), claude-sonnet
(3); last failure: the agent step reached its time limit (30m)`, which did not say that attempt 4 had nearly passed; the
person who retried had to read the ledger to find it. After the retry the task took seven more attempts.

## What Changes

- A green attempt whose test gate gives no failure and that fails only because a static gate that passed at the step
  base fails now (L4-IMP-096) is a near pass. Its changes are kept (the work tree's diff against the red commit, as a
  held step is captured) before the discard, with its profile, attempt and gate text, and `task.attempt_failed` carries
  `near_pass: true`.
- The next green attempt of the task in the same run starts from the red commit with those changes applied as
  uncommitted changes, whatever profile runs it (an escalation included). A `near pass` block of its prompt says which
  attempt wrote them, that every test passed and which static gates failed, and to fix what they report and keep the
  rest unless a fix needs it. The previous-attempt and escalation blocks no longer say the earlier changes were
  discarded when they are in the checkout.
- The changes are applied once. The attempt after that starts from the red commit, unless it was itself a near pass,
  whose changes then replace them. They pass every guard and check of a green step, as an agent's own changes do.
- `task.near_pass_applied` and `task.near_pass_dropped` are recorded. A held step to replay comes first and drops the
  near pass.
- A halt on `max_task_attempts` adds `; nearest: attempt <n> (<profile>) passed every test and failed only its lint or
  type gates` for the newest near pass of the phase in this run, and `breaker.tripped` carries `near_pass{attempt,
  profile}`.

Non-goals: a red step, a single (chore) step, and a green attempt whose test gate failed, however few tests failed (a
diff that still fails tests can hand the next agent wrong code); keeping a near pass across runs (a retry, a resume, the
run after a soft deadline start from the red commit).

## Capabilities

### New Capabilities

- `near-pass-carry`: L4-IMP-100, a green attempt that passed every test and failed only its static gates is the next
  attempt's start.

### Modified Capabilities

- None by amendment; L4-IMP-017 (escalation) and L4-IMP-024's previous-attempt note keep their rules, with the text
  that names the discarded changes made conditional.

## Impact

- `src/l4/implementer/tdd.py` (`run_green`, `step_or_replay`, `agent_step`, `_prompt`, `_previous_attempt_block`,
  `_escalation_block`, `GreenOutcome`), `src/l4/implementer/held_patch.py` (the diff helper shared with `capture`),
  `src/l4/implementer/loop.py` (`_run_task`: the carry, `task.attempt_failed`, the halt reason, `breaker.tripped`),
  `src/l4/implementer/prompt.py` if the block is built there.
- `docs/SPEC.md` (L4-IMP-100, SCN-IMP-541..546, change-table row 130), `CHANGELOG.md`.
- Ledger: `task.attempt_failed` and `breaker.tripped` gain an optional field; two new events.
- No configuration key changes.
