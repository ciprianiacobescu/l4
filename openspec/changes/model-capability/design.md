## Context

From the code, on `amaster` at c9ce1fe [V]:
- **Step events.**
  - `step.started{task, phase, attempt, agent}` names the profile (`implementer/workbench.py:414`).
  - `agent.finished{task, phase, status, exit_code, detail, model, input_tokens, output_tokens, …}` names the resolved
    model but not the profile (`implementer/tdd.py:565`).
  - `task.attempt_failed{task, phase, attempt, reason, excerpt_lines}` names neither (`implementer/loop.py:233`).
  - `breaker.tripped{reason: max_task_attempts, task, phase, attempts, last_failure}` names neither (`loop.py:238`).
  - `budget.cost{usd, profile, task}` names the profile.
  - `availability.selected{role, selected, fallback_index, skipped, fallback_from}` records each selection
    (`agents/factory.py:172`).
- **Stuck detection, L4-IMP-008.**
  - It already computes a failure fingerprint, "test id + error class, or gate name + first error line, normalised",
    and counts `budgets.same_error_repeats`.
  - `max_task_attempts` (3) applies per phase.
  - A stuck task gets one "state your blocking questions" call, then `halted`.
- **Hand-offs to a person.**
  - A question in `questions.md` carries `Asked: <stamp> by <profile>, run <id>, task <key>` (`loop.py:112`,
    `specs/questions.py:132`).
  - A halt writes `halted_section(phase, reason, …)` into the MR/PR note (`orchestrator.py:740`).
- **Fallback.** `switch_profile` (`orchestrator.py:657`) moves to the next profile of the chain only on a limit. After it
  the next step starts in a fresh session, with a note saying who ran before and why (`implementer/tdd.py:458`,
  `workbench.PreviousAttempt`).
- **The vendor veto counts every implementer profile of the unit**, not only the first (`verifier/selection.py:44`,
  SCN-AVL-13).
- **Ledgers live in git.** Each run appends to `<unit>/.l4/ledger/<run-id>.jsonl` in the unit's spec folder (L4-STA-001),
  which stays on the base branch after the merge.
- **`l4 eval`** measures implementer and judge profiles offline on 4 seed units. The 2026-10-08 scorecard rates three
  free or local implementers at 100 % and shows `magnitude-qwen` needing 2.67 red attempts on average.

## Goals

- Every failed attempt is attributable to a profile and a model from the ledger line itself.
- A person who receives a unit (question, halt, escalation) sees which models tried, how often and how they failed
  before reading anything else.
- Anyone can ask "which profile fails which phase how often" and get an answer computed from git, on any machine.
- Optionally, a weak model is replaced by the next stronger one within the task, before a person is called.
- Optionally, a model that keeps failing is skipped for new tasks for a while.

## Non-Goals

- Judging a judge's quality live. A verdict has no ground truth at run time; `l4 eval` judge cells measure that
  offline. The trail does record a judge's invalid replies and errors.
- Escalating the clarifier, test writer or judges. M2 covers the implementer role's steps only: red, green, a chore's
  single phase, and the fix chores of verification.
- Automatic model selection by price or benchmark data from outside the repository.
- Changing `l4 eval`, apart from showing live rates next to its rates.

## Decisions

### D1. Outcome classes: what counts against a model

Every implementer step ends in exactly one class:

| class | when | counts against capability |
|---|---|---|
| `accepted` | the harness checks of the step pass (L4-IMP-005) | no (a success) |
| `gate_failed` | the step's tests or gates fail after the agent finished | yes |
| `invalid_result` | the result file is missing or fails its schema (L4-IMP-008 "result invalid") | yes |
| `no_progress` | identical worktree diff hash on two consecutive attempts | yes |
| `timeout` | the step's timeout or stall timeout ended it | yes |
| `asked` | `blocked` or `partial` with questions | no: it goes to a person (M2 never escalates it) |
| `limit` | a usage or rate limit (L4-AVL) | no: availability, handled by the existing fallback |
| `unavailable` | auth, probe or provider failure | no: availability |
| `error` | harness error, transient server error, sandbox failure | no: not the model's fault |

Rates are computed over capability classes only, so a quota day or a dead login never makes a model look weak.
`timeout` counts because looping without converging is a model failure. The trail shows it as its own class, so an
infrastructure timeout is still visible.

### D2. Self-contained events, back-compatible

The changes:
- `agent.finished` gains `profile`, `adapter` and `outcome`.
- `task.attempt_failed` gains `profile`, `model`, `outcome` and `fingerprint`, the L4-IMP-008 fingerprint, at most 200
  characters and redacted.
- `breaker.tripped` with a `task` gains `profiles: [{profile, model, attempts}]`.

Nothing new carries prompt text, a transcript line, a credential or an e-mail. The fold reads older events without
these fields: the profile comes from the preceding `step.started` of the same task, phase and attempt, the model from
`agent.finished`, the outcome from `status` and `reason`, and the fingerprint stays unknown. So the scoreboard covers
past units too.

Rejected: a separate `capability.jsonl`. A second record of the same facts would drift from the ledger, and the ledger
is already in git.

### D3. The trail: one fold, three places

`l4.capability.trail(events) -> list[TrailRow]` folds one unit's ledger into rows. Each row is: task, phase, rung order,
profile, model, why chosen (`first`, `fallback:<limit kind>`, `escalated:<class>`, `demoted:<profile>`), attempts,
outcome counts, the last fingerprint, and duration and cost when known. It is shown in three places:
1. `l4 status --unit U`, as text, or `--json`.
2. A **Models tried** section in the unit's MR/PR note. At most 20 rows; older ones collapse into
   "and N earlier rows".
3. Every hand-off to a person (D4).

### D4. Every hand-off to a person carries the trail

- **A question in `questions.md`** gets a line after `Asked:`. It covers the rows of the task's current phase only, for
  example:
  `Tried: oc-free (opencode/mimo-v2.6-flash-free) 3× gate_failed [tests/test_fee.py::test_late AssertionError]; codex (gpt-5.6) 1× asked`.
  When the chain had a stronger rung that never ran (escalation off, or the cap reached), the line ends with
  `; not tried: claude-sonnet`.
- **The halted and escalated sections** of the note carry the same line for the task that tripped.
- **`l4 status`** lists each unit waiting for a person with its last profile and model.

So a person reading a question can tell at once whether the model failed or the spec is unclear.

### D5. The scoreboard, from git only

`l4 models [--since DATE] [--role R] [--phase P] [--json]` folds the ledgers in the local clone:
- every spec folder's `.l4/ledger/` on the checked-out base branch, archived changes included;
- every fetched unit branch under `forge.branch_prefix`, read with `git show` without checking it out.

It prints one row per profile, role and phase:
- phases started, and phases accepted at the first attempt;
- the mean attempts to accept;
- capability failures by class;
- asked, limit and unavailable events;
- cost;
- last seen.

The same clone gives the same table. Each CI run writes `.l4-out/models.json` in the same shape for the units it ran,
so an artifact shows them without a clone. When a `docs/eval/<date>/scorecard.json` exists, its pass rate is shown
next to the live one.

Rejected: a runner-local cache file. A hosted runner has none, and a second state store would need its own
consistency rules.

### D6. Doctor row CAP-001 (warn, never fail)

For each profile in a role chain, CAP-001 looks at its last `capability.window` phases (default 10) inside
`capability.lookback` (default 14d). It warns when the capability failure rate is at least `capability.warn_at`
(default 0.5). The row names the profile, role, phase, rate and most common class, and suggests the next stronger
rung or `l4 eval`.

### D7. Escalation up the implementer chain (M2, opt-in)

`roles.implementer` is already ordered: it is the fallback order, cheapest first. With `escalation.enabled: true` the
same order is the strength order, so there is one list to maintain.

Rejected: a separate `escalation.ladder` list. Two orderings of the same profiles would drift. A limit fallback and an
escalation both move to the next profile, and only the reason differs.

**Trigger.** The task's current phase escalates when any of these holds on the current rung:
- `escalation.after` capability failures (default 2);
- the same fingerprint twice in a row;
- two `invalid_result`s.

`asked`, `limit`, `unavailable` and `error` never trigger it.

**Action.**
1. Emit `capability.escalated{task, phase, from, to, reason, attempts, fingerprint}`.
2. Select the next rung that is available, with the availability checks and cool-downs as today. Unavailable rungs are
   skipped and listed.
3. Start a fresh session with the existing PreviousAttempt note: who ran, the outcome classes, the last fingerprint.
   Never a transcript.

**Budget.**
- A lower rung gets `escalation.after` attempts. The top rung gets `max_task_attempts`, as today.
- The unit halts only when the top rung is exhausted.
- `escalation.max_per_unit` (default 3) caps escalations. When the cap is reached, the current rung continues with
  `max_task_attempts`.
- Every step still counts against `budgets.max_cost_usd_per_unit`.

**Two rungs, one failure: ask a person.** When the escalated rung fails with the same fingerprint as the rung below
it, escalation stops. Two models failing the same way points at the spec or a test, not at the model. The harness
raises one question to the person, kind `ambiguous`, blocking the task, with the full trail. The question says that two
models failed with the same fingerprint, names the fingerprint, and asks whether the spec or the test is wrong. Higher
rungs are not tried, which saves their quota.

**Session.** The escalated rung keeps the phase until it is accepted. The next task starts again at the bottom rung,
unless M3 demoted it.

**Independence.** The escalated rung becomes an implementer profile of the unit (the same record as a fallback). So
the existing veto (L4-VER-001, SCN-AVL-13) keeps any judge of its vendor out. When that leaves no judge, the unit goes
to `required_role_unavailable`, as today, and the trail says why.

### D8. Demotion (M3, opt-in)

With `escalation.demote_at` set (for example 0.6), a rung whose capability failure rate for the implementer role is at
least that value, over its last `capability.window` phases inside `capability.lookback`, is skipped when a new task
starts. The task starts on the next rung that is not demoted.
- **No new state.** The rate comes from the same fold as the scoreboard, so it is the same on every machine and in
  every run.
- **It expires.** Once the failures are older than `lookback`, the profile is tried again.
- **The top rung is never demoted.**
- **It is visible.** Demotions appear in `l4 status`, `l4 models` (a `demoted` column), CAP-001 and the trail
  (`demoted:<profile>`).
- `l4 models --forget <profile> --before <date>` adds a ledger-free marker in `.l4/capability-forget.yaml` (committed)
  that makes the fold ignore older phases. That is the human override.

## SPEC amendments required by this change

1. §7.6 L4-IMP-008: the failure fingerprint is recorded on `task.attempt_failed`. A capability failure is an outcome
   class of D1.
2. L4-STA-001's event list: the new fields of D2, and `capability.escalated`.
3. L4-QMD-001: the `Tried:` line of D4.
4. The halted and escalated sections of the MR/PR note: the `Tried:` line. The note gets a "Models tried" section (D3).
5. §3.2 config: the `capability:` block (`window`, `lookback`, `warn_at`) and the `escalation:` block (`enabled`,
   `after`, `max_per_unit`, `demote_at`).
6. §15: doctor row CAP-001.
7. L4-AVL selection: a demoted profile is skipped like a cooling one, with its own reason. An escalation is a
   selection with reason `escalated`.
8. §21: delivery row 15 `model-capability`.

## Risks

- **Escalation spends the expensive rung's quota.** A Claude subscription has usage windows. A bad day could empty them
  and park units in `waiting_capacity`. The cap and the cost budget bound one unit, not the day. CAP-001 and
  `l4 models` make it visible.
- **A vague spec looks like a weak model.** D7 stops escalating when two rungs share a fingerprint and asks the person.
  Two different failures on two rungs still escalate. A fingerprint that is too coarse, such as the same assertion
  line for different causes, can stop escalation too early. The question carries the trail, so the person can raise
  `escalation.max_per_unit` or answer.
- **Small numbers.** Ten phases is a small sample. The scoreboard shows counts next to rates, and the doctor only
  warns.
- **Old ledgers lack fingerprints**, so their rows show `fingerprint unknown`.
