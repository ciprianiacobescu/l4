## Purpose

Make it visible which model fails which task, and how, everywhere a person looks: the ledger, `l4 status`, the MR/PR
note, every question and halt, and a scoreboard across units computed from git. Optionally, replace a weak model with
the next stronger rung of the implementer chain within the task, and skip a model that keeps failing. A person is
asked only when the top rung fails or when two models fail the same way.

## ADDED Requirements

### Requirement: L4-CAP-001 Outcome classes
Every implementer step SHALL end in exactly one outcome class: `accepted`, `gate_failed`, `invalid_result`,
`no_progress`, `timeout`, `asked`, `limit`, `unavailable` or `error`, as defined in design.md D1. Only `gate_failed`,
`invalid_result`, `no_progress` and `timeout` are capability failures. Every rate in this capability MUST be computed
over capability failures and accepted steps only.

#### Scenario: SCN-CAP-01 (−) A usage limit never counts against a model
- **GIVEN** a codex step that ends with HTTP 429 and a usage-limit message
- **WHEN** its outcome is classified
- **THEN** the class is `limit`, and codex's capability failure rate for that phase is unchanged

#### Scenario: SCN-CAP-02 (−) A question is not a failure
- **GIVEN** a green step that ends `blocked` with two questions
- **WHEN** its outcome is classified
- **THEN** the class is `asked`; it is counted in the `asked` column and not in the failure rate

### Requirement: L4-CAP-002 Self-contained step events
The ledger SHALL carry these fields:
- `agent.finished`: `profile`, `adapter` and `outcome`;
- `task.attempt_failed`: `profile`, `model`, `outcome` and `fingerprint` (the L4-IMP-008 failure fingerprint, at most
  200 characters, redacted);
- `breaker.tripped` with a task: `profiles`, a list of `{profile, model, attempts}` for the tripped phase.

No new field may carry prompt text, a transcript line, a credential value or an e-mail. Reading a ledger written
before this change MUST still work:
- the profile comes from the preceding `step.started` of the same task, phase and attempt;
- the model comes from `agent.finished`;
- the outcome comes from `status` and `reason`;
- the fingerprint is `unknown`.

#### Scenario: SCN-CAP-03 (+) A failed attempt names who failed and how
- **GIVEN** profile `oc-free` (model `opencode/mimo-v2.6-flash-free`) whose green step leaves `tests/test_fee.py::test_late` failing with `AssertionError`
- **WHEN** the attempt is recorded
- **THEN** `task.attempt_failed` has `profile: oc-free`, `model: opencode/mimo-v2.6-flash-free`, `outcome: gate_failed` and `fingerprint: tests/test_fee.py::test_late AssertionError`

#### Scenario: SCN-CAP-04 (+) An old ledger still yields a trail
- **GIVEN** a ledger from before this change, with `step.started{agent: codex}` followed by `task.attempt_failed` without a profile
- **WHEN** the trail is folded
- **THEN** the row names `codex`, the model from `agent.finished`, and `fingerprint unknown`

### Requirement: L4-CAP-003 The model trail of a unit
`l4.capability.trail` SHALL fold one unit's ledger into rows. Each row holds, for one task and phase, in the order the
profiles ran:
- the profile and the model;
- why it was chosen: `first`, `fallback:<limit kind>`, `escalated:<class>` or `demoted:<profile>`;
- the number of attempts and the outcome counts;
- the last fingerprint;
- the cost, when known.

`l4 status --unit U` SHALL print the rows, and `--json` SHALL return them. The unit's MR/PR note SHALL carry a section
"Models tried" with the same rows. It has at most 20 rows; older rows collapse into one line "and N earlier rows", and
the section is redacted like the note.

#### Scenario: SCN-CAP-05 (+) Status shows who tried a task, in order
- **GIVEN** a unit where `oc-free` failed green twice (`gate_failed`) and `codex` then passed it
- **WHEN** `l4 status --unit U` runs
- **THEN** the task's green rows read `oc-free … 2× gate_failed` then `codex … escalated:gate_failed 1× accepted`, in that order

#### Scenario: SCN-CAP-06 (−) The note never carries a transcript or a secret
- **GIVEN** a failing gate log that contains a token value from `redact_env` and a long agent message
- **WHEN** the "Models tried" section is rendered
- **THEN** it contains the fingerprint with the token redacted, and no line of the agent's messages or the gate log beyond the fingerprint

### Requirement: L4-CAP-004 Every hand-off to a person carries the trail
When a unit needs a person, the trail SHALL go with it:
- **A question** written to `questions.md` (L4-QMD-001) gets a `Tried:` line after `Asked:`. It lists the trail rows of
  the blocking task's current phase: profile, model, attempts, outcome classes and last fingerprint. When the
  implementer chain has a rung that did not run for this phase, the line ends with `; not tried: <profiles>`.
- **The halted and escalated sections** of the MR/PR note carry the same `Tried:` line for the task that tripped.
- **`l4 status`** shows, for every unit waiting for a person, the last profile and model that ran.

#### Scenario: SCN-CAP-07 (+) A halt says which model gave up
- **GIVEN** escalation off, `roles.implementer: [oc-free, claude-sonnet]`, and `oc-free` failing green 3 times with the same fingerprint
- **WHEN** the unit halts on `max_task_attempts`
- **THEN** the halted section reads `Tried: oc-free (opencode/mimo-v2.6-flash-free) 3× gate_failed [<fingerprint>]; not tried: claude-sonnet`

#### Scenario: SCN-CAP-08 (+) A question names the model that asked and the attempts before it
- **GIVEN** `codex` failing green once with `gate_failed`, then ending `blocked` with one question
- **WHEN** the question is written to `questions.md`
- **THEN** its `Asked:` line names `codex`, and its `Tried:` line reads `codex (<model>) 1× gate_failed [<fingerprint>], 1× asked`

### Requirement: L4-CAP-005 The scoreboard across units
`l4 models [--since DATE] [--role R] [--phase P] [--json]` SHALL fold every ledger in the local clone: the spec
folders of the checked-out branch, archived changes included, and every fetched unit branch under
`forge.branch_prefix`, read without a checkout. It prints one row per profile, role and phase with:
- phases started;
- accepted at the first attempt;
- the mean attempts to accept;
- capability failures by class;
- `asked`, `limit` and `unavailable` counts;
- cost;
- last seen;
- and, when `docs/eval/<date>/scorecard.json` exists, that profile's eval pass rate.

It reads git only and writes nothing. Each CI run SHALL write `.l4-out/models.json` in the same shape for the units it
ran.

#### Scenario: SCN-CAP-09 (+) Two units add up
- **GIVEN** unit A where `oc-free` passed red at the first attempt and failed green twice before `codex` passed it, and unit B where `oc-free` passed both phases at the first attempt
- **WHEN** `l4 models --role implementer` runs
- **THEN** `oc-free`'s green row shows 2 phases, 1 accepted at the first attempt, 2 `gate_failed`; its red row shows 2 of 2 at the first attempt

#### Scenario: SCN-CAP-10 (−) Same clone, same table
- **GIVEN** a clone at one commit with its unit branches fetched
- **WHEN** `l4 models --json` runs twice, on two machines
- **THEN** both outputs are byte-identical

### Requirement: L4-CAP-006 Doctor row CAP-001
For each profile in a role chain, the doctor SHALL compute the capability failure rate per role and phase over its last
`capability.window` phases (default 10) that fall inside `capability.lookback` (default 14d). It SHALL report CAP-001
`warn` when the rate is at least `capability.warn_at` (default 0.5). The row names the profile, role, phase, rate,
sample size and most common class, and the next stronger rung of the chain when there is one. CAP-001 never fails.

#### Scenario: SCN-CAP-11 (+) A weak free model is flagged, the job goes on
- **GIVEN** `oc-free` with 6 capability failures in its last 10 green phases
- **WHEN** `l4 doctor --ci` runs
- **THEN** CAP-001 warns `oc-free implementer/green: 6/10 failed (gate_failed), next rung codex`, and doctor's exit code is unchanged

### Requirement: L4-CAP-007 Escalation up the implementer chain
With `escalation.enabled: true`, the order of `roles.implementer` SHALL also be the order of strength. The task's
current phase SHALL escalate to the next rung when any of these holds on the current rung:
- `escalation.after` capability failures (default 2);
- the same fingerprint twice in a row;
- two `invalid_result`s.

The outcomes `asked`, `limit`, `unavailable` and `error` MUST NOT escalate. An escalation:
1. records `capability.escalated{task, phase, from, to, reason, attempts, fingerprint}`;
2. selects the next rung that passes availability, skipping and listing unavailable ones;
3. starts it in a fresh session with the existing previous-attempt note, which gives the outcome classes and the last
   fingerprint and never a transcript.

Budgets:
- A lower rung has `escalation.after` attempts; the top rung has `max_task_attempts`.
- The unit halts only when the top rung is exhausted.
- After `escalation.max_per_unit` escalations (default 3), the current rung continues with `max_task_attempts`.
- Every step counts against `budgets.max_cost_usd_per_unit`.

When the escalated rung fails with the same fingerprint as the rung below it, escalation SHALL stop. One question goes
to the person, kind `ambiguous`, blocking the task, saying that two models failed the same way, with the fingerprint
and the trail.

With `escalation.enabled` false or unset, behaviour is as before this change, apart from L4-CAP-001..006.

#### Scenario: SCN-CAP-12 (+) A weak model is replaced within the task
- **GIVEN** `escalation.enabled: true`, `roles.implementer: [oc-free, codex, claude-sonnet]` with `claude-sonnet` on `model: claude-sonnet-5-5`, and `oc-free` failing green twice with two different fingerprints
- **WHEN** the third green attempt starts
- **THEN** `capability.escalated{from: oc-free, to: codex, reason: gate_failed}` is recorded, codex runs in a fresh session with the previous-attempt note, and the trail shows both rows

#### Scenario: SCN-CAP-13 (−) A question never climbs the ladder
- **GIVEN** `escalation.enabled: true` and `oc-free` ending green `blocked` with a question
- **WHEN** the step ends
- **THEN** no `capability.escalated` is recorded and the question goes to `questions.md` with its `Tried:` line

#### Scenario: SCN-CAP-14 (−) Two models failing the same way ask the person
- **GIVEN** `oc-free` failed green twice with fingerprint F, the phase escalated to `codex`, and codex fails with F
- **WHEN** codex's attempt is recorded
- **THEN** no escalation to `claude-sonnet` happens, and one `ambiguous` question names F, both models and their attempts, and blocks the task

#### Scenario: SCN-CAP-15 (−) The top rung exhausted halts with the whole trail
- **GIVEN** escalation through every rung, the top rung failing `max_task_attempts` times with different fingerprints
- **WHEN** the breaker trips
- **THEN** the unit is `halted`, `breaker.tripped.profiles` lists every rung with its attempts, and the halted section's `Tried:` line lists them all

### Requirement: L4-CAP-008 Escalation keeps verification independent
An escalated rung SHALL become an implementer profile of the unit for L4-VER-001, recorded the same way as a fallback
profile. So no judge that shares a vendor (or model, by `verifier.independence`) with it may judge the unit. When that
leaves no judge, the unit goes to `required_role_unavailable` as before, and the trail and the note name the escalated
rung as the cause.

#### Scenario: SCN-CAP-16 (−) The judge chain moves past the escalated vendor
- **GIVEN** `roles.judges: [claude-judge, codex-judge]` and an implementer phase escalated from `codex` to `claude-sonnet`
- **WHEN** a judge is selected
- **THEN** both are vetoed: `claude-judge` shares Anthropic with `claude-sonnet`, `codex-judge` shares OpenAI with `codex`. The unit goes to `required_role_unavailable`, and its note names both rungs

### Requirement: L4-CAP-009 Demotion
With `escalation.demote_at` set, a rung of `roles.implementer` SHALL be skipped when a task phase starts if its
capability failure rate for that phase, over its last `capability.window` phases inside `capability.lookback`, is at
least `demote_at`. The phase then starts on the next rung that is not demoted.
- The rate MUST come from the L4-CAP-005 fold, not from a separate store.
- The top rung MUST never be demoted.
- A demotion is recorded on the selection (`demoted:<profile>`) and shown by `l4 status`, `l4 models` and CAP-001.
- `l4 models --forget <profile> --before <date>` records, in the committed file `.l4/capability-forget.yaml`, that the
  fold ignores that profile's phases before the date.

#### Scenario: SCN-CAP-17 (+) A profile that keeps failing is skipped, then tried again
- **GIVEN** `demote_at: 0.6`, `lookback: 14d`, and `oc-free` with 7 capability failures in its last 10 green phases, all from last week
- **WHEN** a new task's green phase starts today, and again 15 days later with no newer `oc-free` green phases
- **THEN** today it starts on `codex` with `demoted:oc-free` on the selection; 15 days later it starts on `oc-free`

#### Scenario: SCN-CAP-18 (−) The top rung is never skipped
- **GIVEN** `demote_at: 0.5` and every rung, the top one included, above the rate
- **WHEN** a task phase starts
- **THEN** it starts on the top rung, and the trail records that every lower rung was demoted

### Requirement: L4-CAP-010 Evidence on the dummy repository
The change SHALL be shown live on the GitLab dummy repository in two runs:
1. A unit whose implementer is a free model that fails a phase. The unit's `questions.md` or halted note carries the
   `Tried:` line, and its MR note carries "Models tried".
2. With `escalation.enabled: true`, a unit that escalates from a free rung to a stronger rung and passes.

Both runs are recorded under `docs/live/` with their pipeline and job ids. They MUST use free or already-configured
credentials only.

#### Scenario: SCN-CAP-19 (+) The trail is visible live
- **GIVEN** the dummy repository and a unit whose task the configured free model fails
- **WHEN** the CI job runs
- **THEN** the MR note has "Models tried" and the question or halt carries `Tried:`, as recorded in `docs/live/`
