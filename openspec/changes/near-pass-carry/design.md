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
near pass: a replayed step is a person's accept, not an agent's starting point. The outside-link check runs to decide it,
so a lint-only failure with a link out of the work tree records `guard.violation{action: refused}` now too. No file of
the patch may hold text shaped like a secret: the near pass runs `worktree_secrets(wb.git, wb.redactor, <changed
files>)`, the scan `agent_step` gives a step (a lint command that writes a file can trip it after the step's own scan),
and a hit is no near pass (nothing is emitted: the scan's hits are never put in an event here). A git error while taking
the patch is no near pass either, and the changes are discarded in a `finally`.

### D2. What is kept

A frozen dataclass `NearPass(task: str, attempt: int, profile: str, patch: bytes, patch_sha256: str, files:
tuple[str, ...], gates: tuple[str, ...])` (`gates`: the names of the failed static gates, `lint`/`typecheck`, in
order, each once). In `run_green`, at a near pass and before `wb.discard_changes()`, take the patch with a helper
`step_patch(wb) -> bytes` factored out of `capture` (same `git add -A` / `diff --cached` / `reset` and the same
exclusions; `capture` then calls it), and the changed paths. `GreenOutcome` gains `near_pass: NearPass | None = None`.
An empty patch is no near pass.

### D3. Where it is carried

`_run_task` keeps `carry: NearPass | None`. After a failed green outcome: `carry = done.near_pass` (a new near pass
replaces the old one; an attempt that is not a near pass leaves `carry` None). The next `run_green` call gets
`carry=carry`, so it is applied once: whatever that attempt returns replaces it. Escalation does not touch it, so a moved
phase starts from it. `run_green` passes it to `step_or_replay`, which passes it to `agent_step` only on the agent path:
when `find_replay` finds a step to replay, or refuses one (a new hold), the near pass is not applied and
`task.near_pass_dropped{task, attempt, from_attempt, reason: "replay"}` is recorded.

A `RoleLimit` (quota, login, a silent stop) out of `run_green` ends the `_run_task`, and the orchestrator's fallback
(`_implement`) and the fix loop's (`fix_hook`) start the next profile's `run_task` for the same task. The red commit is
kept, so a patch against it still applies: `agent_step` raises the limit with the near pass it applied (`RoleLimit(run,
carried)`; `RoleLimit.carry` is None for a step that applied none, a red step's or a verifier's, and for a carry whose
patch did not apply), both callers keep it per task and pass it as `run_task(...,
carry=)`, and `_run_task` drops it when there is no red commit to resume (the red step runs again). The next attempt
starts from the same changes and `task.near_pass_applied` is recorded again with the same `from_attempt`.

### D4. How it is applied

In `agent_step`, after `base = wb.head()` and `config_grant(...)` (as `replay_step` computes the grant before it applies
a step) and inside the `try` whose `finally` runs the guards (so they run if anything after the apply raises), and before
the prompt is built: when `carry` is set and `carry.task == task.key` (the cheap guard), apply `carry.patch` with the
same `git apply` call `replay_step` uses. On success record
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
attempt." A prompt with no previous failure (the first attempt after a limit's fallback: a new `_run_task` starts with
none, and the attempt before was the limited one) says "this prompt does not hold their output: run them to read what
they report" instead of "their output is under the previous failure" (the agent may run them, L4-IMP-098).

`wb.previous_attempt` outlives the attempt that set it, so it can describe a profile whose changes were discarded while
the carry came from another. The limit and silent block of `_previous_attempt_block` therefore ALWAYS says "Its
uncommitted changes were discarded". `_escalation_block` says "Its uncommitted changes from attempt <n> are in the
checkout (see the near pass block)" only when a carry was applied and `carried.profile == previous.profile`, else its
original text, byte for byte (`test_escalation.py` pins it). The `near pass` block itself names the attempt and profile
whose changes are in the checkout. Pass the carry down; do not read global state.

### D6. The halt

`task.attempt_failed` gets `near_pass: True` for a near pass (absent otherwise). At the halt, `nearest` is built from this
run's ledger events, not from a local (a limit's fallback starts a new `_run_task`, which would lose it): the newest
`task.attempt_failed` with `near_pass: true` of this run id, the task, the phase halted in and the workbench's fix unit
(`attempt`, `profile`). When there is one, the reason becomes `task <k>: max_task_attempts (<n>) reached in <where>;
nearest: attempt <n> (<profile>) passed every test and failed only its lint or type gates; last failure: <failure>`: the
orchestrator's `_halt` cuts the reason at 300 characters, so the nearest clause comes right after `<where>`, before a
refused move's clause (`; no later profile can take it (...)`, whose reasons can be long) and the last failure, which is
what gets cut. `near_pass: {"attempt": n, "profile": p}` goes to `breaker.tripped`.

### D7. A deadline or an exception

A `DeadlineReached` or any exception out of `run_green` other than `RoleLimit` leaves `carry` unused; the next run starts
from the red commit, unless it restores an interrupted step's work in progress (`refs/l4/wip/...`), which holds the
carried changes (the snapshots are of the work tree, whatever it holds). A patch is held in memory, never written to the
repository, the ledger or the logs (the ledger holds its sha256 and paths; `NearPass.patch` is `repr=False`).

## Risks / Trade-offs

- The next agent may keep a wrong approach because it starts from it. Bounded: one attempt, and the prompt allows any
  change a fix needs.
- The patch is taken after the static gates ran: a linter that writes files (`--fix`) has its writes in it. That tree
  was not tested, but the next attempt's test gate tests it.
- A run that ends between the near pass and the next attempt (soft deadline) loses it, unless the next run restores a
  step's work in progress that held it.
