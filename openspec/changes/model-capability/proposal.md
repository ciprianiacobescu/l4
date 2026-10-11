## Why

A model that is too weak for a task costs attempts, money and a person's time, and today nobody can see it happen.

From the code [V]:
- **A failed attempt does not name the model.**
  - `task.attempt_failed{task, phase, attempt, reason}` names no profile (`src/l4/implementer/loop.py:233`).
  - `agent.finished` names the resolved model but not the profile (`src/l4/implementer/tdd.py:565`).
  - `breaker.tripped{reason: max_task_attempts}` names neither (`loop.py:238`).
  - Who ran a step is only in the `step.started` event before it (`workbench.py:414`), so every reader must join by
    order.
- **A person gets the unit without the history.**
  - A question in `questions.md` says `Asked: <when> by <profile>, run <id>, task <key>` (`loop.py:112`).
  - The halted note says `task X: max_task_attempts (3) reached in green; last failure: ...`.
  - Neither says which models tried before, how often, or how they failed. So the person cannot tell a weak model from
    a vague spec.
- **Nothing adds it up across units.** Whether a free model fails 4 of its last 10 green phases is invisible. Only
  `l4 eval` measures profiles, offline, on 4 seed units (`docs/eval.md`).
- **A weak model is never replaced.** A role chain falls back to its next profile only on a limit, an unavailable
  login or a failed probe (`orchestrator.switch_profile`, `orchestrator.py:657`). A weak model spends
  `max_task_attempts` (3) in one phase, and the unit halts for a person (L4-IMP-008).

The maintainer asked for "at least traceability and visibility, even if [the result is a] question to [a] human", and
for an automatic escalation from a weak model to a stronger one (for example from Codex to Claude Sonnet 5.5).

## What Changes

**M1: traceability and visibility. Always on, with no config.**
- **Self-contained ledger events.** Every agent step outcome records its profile, adapter, model, an outcome class and
  the L4-IMP-008 failure fingerprint. Old ledgers still fold.
- **The model trail of a unit.** For each task and phase it lists which profiles ran, in order: why each was chosen,
  how many attempts, which outcomes and the last fingerprint. It appears in `l4 status --unit` and in the MR/PR note.
- **Every hand-off to a person carries the trail.** That covers a question in `questions.md` (a new `Tried:` line), the
  halted section and the escalated section. A person sees "oc-free tried 3×, tests failed the same way" before
  reading the question.
- **A scoreboard across units.** `l4 models` gives per-profile rates by role and phase. It is computed from the ledgers
  in git alone (L4-STA-001 keeps them in the unit's spec folder), so it needs no new state and works on a hosted
  runner too. Each CI run also writes `.l4-out/models.json`.
- **Doctor row CAP-001.** It warns when a profile in a chain fails too often. It never fails the job.

**M2: escalation within a task. Opt-in, `escalation.enabled`.**
- The implementer chain doubles as a ladder, weakest first, for example
  `roles.implementer: [oc-free, codex, codex-high, claude-sonnet]`, where `claude-sonnet` has
  `model: claude-sonnet-5-5`.
- After `escalation.after` capability failures (default 2) in one phase, the next attempt runs on the next available
  rung. It gets a fresh session and the same "previous attempt" note a limit fallback gives today.
- Limits keep their own fallback. A `blocked` result with questions still goes to a person and never up the ladder.
- When two rungs fail with the same fingerprint, escalation stops. The person gets one question with the trail,
  because two models failing the same way points at the spec or a test.
- The vendor veto covers every profile that ran an implementer step of the unit, the escalated rungs included. A
  failed rung's edits can survive into the next attempt. So a ladder spanning two vendors needs a judge chain with a
  third vendor.
- A per-unit cap and the existing cost budget bound it.
- The unit halts for a person only when the top rung also fails, and the trail says so.

**M3: demotion. Opt-in, `escalation.demote_at`.**
- A rung whose capability failure rate over its recent phases reaches the threshold is skipped for new tasks of that
  role. They start on the next rung.
- The rate is computed from the ledgers over a `lookback` window, so a demoted profile is tried again once its old
  failures age out.
- The top rung is never demoted.

## Capabilities

### New Capabilities

- `model-capability`: outcome classes and self-contained step events, the unit's model trail and where it is shown,
  the trail on every human hand-off, the cross-unit scoreboard and its doctor row, escalation up the implementer
  chain, and demotion.

### Modified Capabilities

None as an OpenSpec delta. The SPEC lines this change amends are listed in design.md: L4-IMP-008, L4-STA-001's event
list, L4-QMD-001's question format, the halted and escalated notes, §3.2 config, §15 doctor rows, and the selection
rules of L4-AVL.

## Impact

- New code: `src/l4/capability/` (outcome classes, trail, scoreboard, ladder, demotion) and the CLI command
  `l4 models`.
- Code changes:
  - `src/l4/implementer/tdd.py`, `loop.py` and `workbench.py`: the event fields, and the escalation trigger.
  - `src/l4/orchestrator.py`: `switch_profile` gains a capability reason.
  - `src/l4/state/fold.py`: reading older events.
  - `src/l4/specs/questions.py`: the `Tried:` line.
  - `src/l4/archive.py` and the note renderers: "Models tried".
  - `src/l4/doctor/`: CAP-001.
  - `src/l4/config/schema.py`: `capability:` and `escalation:`.
  - The verifier's vendor veto: every vendor whose work was accepted.
- Docs: `docs/SPEC.md` (amendments, delivery row 15), `docs/eval.md` (live rates next to eval rates), `docs/quickstart.md`
  (an escalation example).
- Simulation: new scenarios for an escalation, a blocked step that does not escalate, and a halt with the trail.
- Live evidence: on the GitLab dummy repository, a unit where a free model fails and the trail appears in `questions.md`
  and in the MR note (M1); a unit that escalates to a stronger rung and passes (M2).
- Unchanged:
  - the availability fallback on limits (L4-AVL);
  - `max_task_attempts` on the top rung;
  - judge selection, apart from the veto;
  - `l4 eval`.
