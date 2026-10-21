## Why

A live run with L4 0.4.3 on a public consumer repository stopped where a stronger model, or one line from a person,
could have finished the task.

1. **The chain did not help.** The implementer chain was `roles.implementer: [deepseek]` (OpenCode,
   `opencode-go/deepseek-v4.1-flash`, a cheap model). The red step of task 4.1 failed three times:
   - attempt 1 wrote a test that calls a function with a keyword that the function does not have yet (`TypeError`);
   - the harness's failure reason said exactly what to do: "A parameter that does not exist yet needs a guarded stub
     ..., not a TypeError" (`src/l4/implementer/result.py:127-128`);
   - attempt 2 returned an invalid result (`summary` missing, `notes_for_verifier` over 2000 characters);
   - attempt 3 made the same `TypeError` as attempt 1.

   The unit halted (`max_task_attempts (3) reached in red`) and the delivery plan stopped. Today a chain moves to its
   next profile only on a limit, a failed probe or a missing login (L4-AVL-006, `orchestrator.switch_profile`,
   `src/l4/orchestrator.py:920-932`). A model that fails the same step again and again keeps all its attempts. A
   chain with a stronger second profile would not have changed the result.
2. **The person's words did not reach the model.** The recovery was `l4 retry --reason TEXT`, then `l4 yolo resume`.
   The retry gives the same model new attempts. The reason is recorded as `unit.retried{reason}`
   (`src/l4/orchestrator.py:456`), but no prompt reads it (`src/l4/implementer/tdd.py:597-602` builds the data blocks
   from answers, lessons, accepted findings and a limit fallback only). The person who saw the failure had no way to
   tell the model what to do differently.

## What Changes

- **Escalation along the implementer chain.** A new key `implementer.escalate_after` (default `2`, `0` = never). When
  one profile has failed `escalate_after` attempts of one phase (red, green) of a task, the next usable profile of
  `roles.implementer` takes that phase. The new profile starts in a fresh session. Its prompt lists the earlier
  profile's failure reasons in the "previous attempt" block that a limit fallback already uses.
- **Attempts are counted per profile.** A profile that has a usable profile after it gets `escalate_after` failed
  attempts in the phase. The last usable profile gets `max_task_attempts`, as today. The unit halts only when that
  profile has used them. The consumer's chain is now `[deepseek, glm]` (two cheap OpenCode Go models, one key): with
  the defaults the phase has at most 2 + 3 = 5 failed attempts, and with a stronger third profile (for example a
  Claude Code subscription profile) 2 + 2 + 3 = 7. The step keys keep counting across profiles.
- **By profile, not by adapter.** Two profiles of the same adapter, provider or vendor family are two rungs: a move
  between them is an escalation, because the model differs. Cool-downs and probe results are already keyed per model
  and per profile.
- **The escalation lasts for the task.** The task keeps the profile for its later phases. The next task starts again
  on the run's profile (cheap first). A new run starts every task on the run's profile.
- **What counts.** Every failed attempt counts against the profile that made it: a failed harness check, an invalid
  result, an agent run that ends with an error. A limit is not a failure (L4-AVL-006 as today). A `blocked` result
  goes to a person and never escalates.
- **No escalation that breaks verification.** A profile is not taken when no profile of `roles.judges` (and of a
  non-empty `roles.verifier_agent`) would stay independent of the unit's implementer profiles with it. When no later
  profile is usable, the task stays on its profile. Nothing parks the unit.
- **Records.** `implementer.escalated{task, phase, from, to, failures, attempt}`, or
  `implementer.escalation_skipped{task, phase, from, reason}`. The selection records
  `availability.selected{escalated_from}`. `task.attempt_failed` gains `profile`, and `breaker.tripped` gains
  `profiles`. The halt detail names the profiles when more than one profile ran the phase. Progress lines show the
  move. Doctor CFG-009 warns when `escalate_after` can never act, or when two profiles of the chain run the same
  model.
- **A person's retry note reaches the implementer.** `l4 retry --reason TEXT` and `l4 resume --reason TEXT` on a unit
  that halted on a task record which task the note is for (`unit.retried{reason, note_task, note_fix_unit}`). Every
  later step of that task gets a data block "A person's note on this retry", until the task is done or a newer note
  replaces it. The text is the recorded reason: redacted, at most 300 characters. `prompt.rendered` records
  `retry_note{event, ts, sha256}`. `l4 retry` prints the task that the note goes to, and `l4 status --unit` says so
  for a halted unit.
- **Docs.** `docs/SPEC.md` rows, the runbook (7.2, 4.2, 10.4, 11), the skill (`adopt.md`: a cheap-first chain with a
  stronger escalation profile and judges of a third vendor; `operate.md`: the retry note), `l4 retry --help`, and a
  CHANGELOG section 0.4.4.

Not in this change:
- escalation in a fix unit (the fix loop gives no escalation hook, `src/l4/verifier/fixloop.py:361`);
- the rest of `model-capability` (L4-CAP-001..010): outcome classes, failure fingerprints and the "two profiles fail
  the same way" stop, the trail and the `Tried:` line, `l4 models`, CAP-001, demotion (design D2 says how this change
  relates to L4-CAP-007);
- a note from `l4 restart --reason`, `l4 yolo resume --reason`, an operator label, a plan's own retry or a spec push
  (design D10);
- `l4 retry --profile`, which would choose the profile of the retried task;
- a breaker for `budgets.max_cost_usd_per_unit` (the key exists, no code reads it: design D7);
- the doctor row CFG-003, which the SPEC lists and the doctor does not register.

## Capabilities

### New Capabilities

- `implementer-escalation`: a task phase that fails repeatedly on one profile moves to the next usable profile of the
  implementer chain, with the attempt rules, the independence rule, the records and what a person sees
  (L4-IMP-017, L4-IMP-018).
- `operator-retry-note`: the reason of `l4 retry` and `l4 resume` reaches the implementer of the halted task
  (L4-OPS-018). The runbook and the skill teach the note and a cheap-first chain (L4-OPS-019).

### Modified Capabilities

None as an OpenSpec delta: `openspec/specs/` holds no baseline (only `.gitkeep`). Section 6 of `tasks.md` holds the
`docs/SPEC.md` work:
- the new requirements L4-IMP-017, L4-IMP-018, L4-OPS-018 and L4-OPS-019, with SCN-IMP-176..185 and SCN-OPS-28..33;
- the amendments of L4-IMP-004, L4-IMP-008, L4-AVL-006, L4-OPS-001, L4-OPS-006, L4-STA-001 (event list), §2.1, §3.2,
  §15 (CFG-009), and §21 (row 24, and row 15 `model-capability`).

## Impact

- **Code:**
  - `src/l4/implementer/loop.py` (per-profile counts, the escalation hook, the records, the halt detail),
    `src/l4/implementer/tdd.py` (the previous-attempt block of an escalation, the note block, `prompt.rendered`),
    `src/l4/implementer/workbench.py` (`PreviousAttempt`), and a new `src/l4/implementer/retrynote.py`;
  - `src/l4/agents/factory.py` and `src/l4/availability/fallback.py` (a selection after a given profile that never
    parks);
  - `src/l4/orchestrator.py` (the escalation hook, the task's own profile, `switch_profile`, `resume` passes the
    note binding);
  - `src/l4/state/fold.py` (`halt_task`, `escalated_from`), `src/l4/state/retry.py`, `src/l4/state/resume.py`,
    `src/l4/state/status.py`, `src/l4/progress.py`, `src/l4/cli.py`;
  - `src/l4/config/schema.py` (`implementer.escalate_after`), `src/l4/doctor/checks_config.py` (CFG-009).
- **Docs:** `docs/SPEC.md`, `docs/runbook.md`, `plugins/l4/skills/l4/references/adopt.md` and `operate.md`,
  `CHANGELOG.md`.
- **Config:** a new optional key `implementer.escalate_after` (default `2`). The schema is strict, so the order is:
  release, pin move, config edit. A chain of two or more profiles changes behaviour with no config edit: set
  `escalate_after: 0` to keep the old behaviour.
- **Ledger:** new events `implementer.escalated` and `implementer.escalation_skipped`. New fields:
  `availability.selected.escalated_from`, `task.attempt_failed.profile`, `breaker.tripped.profiles`,
  `unit.retried` and `unit.resumed` `note_task` and `note_fix_unit`, `prompt.rendered.retry_note`. An older ledger
  folds and reads as before: an event without the new fields carries no escalation and no note.
