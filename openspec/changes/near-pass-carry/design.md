## Context

`_run_task` (`src/l4/implementer/loop.py`) runs a task's attempts. For green it calls `run_green(wb, task, red,
attempt=..., previous_failure=retry)`; on a `failed` outcome it builds `retry = _retry_reason(failure, wb, excerpt)`,
counts the failure, emits `task.attempt_failed{task, phase, attempt, profile, reason, excerpt_lines, excerpt?}`, and may
escalate: `_escalate_while_due` returns a different `Workbench` (another selected profile), so state that must survive
an escalation lives in `_run_task`'s locals. When the profile is spent the loop ends and the halt reason is
`task <k>: max_task_attempts (<n>) reached in <where>; last failure: <failure>`, with `breaker.tripped{reason, task,
phase, attempts, profiles, last_failure}`.

`run_green` (`src/l4/implementer/tdd.py`): the agent step (`step_or_replay`), the freeze put back, setup, the test gate,
`green_failures`; when that gave no failure, `worse_static_gates(wb, base, "green")` (L4-IMP-096) and
`restore_replay(wb, "static gates")`; then the test-at-red run, the replay checks, `stop_on_unsafe` and
`outside_links_reason`; on any reason `wb.discard_changes()` and `GreenOutcome("failed", reason, ...)`.

`capture` (`src/l4/implementer/held_patch.py`) takes a step's changes as bytes: `git add -A` with `wb.exclude_config`,
`git diff --cached --binary DIFF_FLAGS HEAD -- . :(exclude)<ledger>`, `git reset -q`. `replay_step` applies such bytes
with `wb.git.run_input_bytes(*GIT_PLAIN, *APPLY_FLAGS, "-", data=patch)`.

`agent_step` takes `base = wb.head()` first (the protected-path revert resets to it), builds the prompt, runs the agent
under `wb.wip_snapshots`, then runs its guards.

## Goals / Non-Goals

**Goals:** the attempt after a near pass starts from the near pass's changes, once, across an escalation; the halt
reason names a near pass.

**Non-Goals:** carrying a diff whose tests fail; carrying across runs; red and single steps; a configuration key; a
second agent turn inside an attempt.

## Decisions

### D1. What a near pass is

In `run_green`, a near pass is the outcome where `green_failures` gave no reason, `worse_static_gates` gave a reason,
`restore_replay(wb, "static gates")` gave none (`stuck` is None), and the final reason is that static-gate reason alone
(`stop_on_unsafe` and `outside_links_reason` gave none). A step that was a replay (`wb.replay_question` set) is never a
near pass: a replayed step is a person's accept, not an agent's starting point.

### D2. What is kept

A frozen dataclass `NearPass(task: str, attempt: int, profile: str, patch: bytes, patch_sha256: str, files:
tuple[str, ...], gates: tuple[str, ...])` (`gates`: the names of the failed static gates, `lint`/`typecheck`, in
order, each once). In `run_green`, at a near pass and before `wb.discard_changes()`, take the patch with a helper
`step_patch(wb) -> bytes` factored out of `capture` (same `git add -A` / `diff --cached` / `reset` and the same
exclusions; `capture` then calls it), and the changed paths. `GreenOutcome` gains `near_pass: NearPass | None = None`.
An empty patch is no near pass.

### D3. Where it is carried

`_run_task` keeps `carry: NearPass | None`. After a failed green outcome: `carry = done.near_pass` (a new near pass
replaces the old one; an attempt that is not a near pass leaves `carry` None after its own use, see D4). The next
`run_green` call gets `carry=carry`, and `carry` is set to None right after the call returns (once). Escalation does
not touch it, so a moved phase starts from it. A red step that runs again (red is None again) clears it. `run_green`
passes it to `step_or_replay`, which passes it to `agent_step` only on the agent path: when `find_replay` finds a step to
replay, the near pass is not applied and `task.near_pass_dropped{task, attempt, from_attempt, reason: "replay"}` is
recorded.

### D4. How it is applied

In `agent_step`, after `base = wb.head()` and before the prompt is built: when `carry` is set and `carry.task ==
task.key`, apply `carry.patch` with the same `git apply` call `replay_step` uses. On success record
`task.near_pass_applied{task, attempt, from_attempt, from_profile, patch_sha256, files}` (paths only, at most 50, as
other events cap them). On a `GitError`, `wb.discard_changes()`, record `task.near_pass_dropped{..., reason: <the
error's first line, cut at 300>}` and go on as if there were no carry. No replay guard is armed (this is not a person's
accept): the agent edits on top of it, and every guard and check after the step runs as for any agent step.

### D5. The prompt

When a carry was applied, `_prompt` adds a data block `near pass` (`<l4:data kind="near-pass" ...>` as the other
blocks; text defused like `_previous_attempt_block`'s):

"Attempt <n> of this task (profile <p>) passed every test of the test gate, and its <gate list> gate(s) failed; their
output is under the previous failure. Its changes are in the checkout as uncommitted changes on the red commit. Fix what
those gates report and keep the rest unless a fix needs it. You start in a new session, with no transcript of that
attempt."

When a carry was applied, `_escalation_block` and `_previous_attempt_block` say "Its uncommitted changes from attempt
<n> are in the checkout (see the near pass block)" instead of "Its uncommitted changes were discarded"; without a carry
their text is unchanged. Pass a flag (or the carry) down; do not read global state.

### D6. The halt

`_run_task` keeps `nearest: dict[str, tuple[int, str]]` (phase → attempt, profile of the newest near pass in this run).
`task.attempt_failed` gets `near_pass: True` for a near pass (absent otherwise). At the halt, when `nearest` has the
phase, append `; nearest: attempt <n> (<profile>) passed every test and failed only its lint or type gates` to the
reason, and add `near_pass: {"attempt": n, "profile": p}` to `breaker.tripped`.

### D7. A deadline or an exception

A `DeadlineReached` or any exception out of `run_green` leaves `carry` unused; the next run starts from the red commit
(in-memory only). A patch is held in memory, never written to the repository, the ledger or the logs (the ledger holds
its sha256 and paths).

## Risks / Trade-offs

- The next agent may keep a wrong approach because it starts from it. Bounded: one attempt, and the prompt allows any
  change a fix needs.
- The patch is taken after the static gates ran: a linter that writes files (`--fix`) has its writes in it. That tree
  was not tested, but the next attempt's test gate tests it.
- A run that ends between the near pass and the next attempt (soft deadline) loses it.
