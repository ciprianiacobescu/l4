# Escalate and note: a failing task moves up the implementer chain, and a person's retry note reaches the model

Status: design draft, 2026-10-16. Harness at 0.4.3 (branch `fix-044`, 4707c13f). Markers: **[V]** verified (read in the
code at the cited line, or run), **[I]** inferred (follows from the code, not run end to end), **[G]** a chosen number
with no measurement behind it.

## 0. The answer in eight lines

1. Today a chain moves to its next profile only on a limit, a failed probe or a missing login. A profile that fails
   the same step keeps all its `max_task_attempts`, then the unit halts (section 1.1) [V].
2. Decision: `implementer.escalate_after` (default 2, `0` = never). After that many failed attempts of one phase on one
   profile, the next usable profile of `roles.implementer` takes the phase, with the earlier failure reasons (D1).
3. Attempts are counted per profile. A profile with a usable profile after it gets `escalate_after` failures. The last
   usable profile gets `max_task_attempts`. The step keys keep counting. The consumer's chain now is
   `[deepseek, glm]` (two cheap OpenCode Go models): at most 2 + 3 = 5 failed attempts per phase; with a stronger third
   profile, 2 + 2 + 3 = 7 (D3).
   Escalation is by profile, not by adapter or vendor: a move between two profiles of the same adapter, provider or
   vendor family is an escalation, because the model differs (D5).
4. The task keeps the new profile for its later phases. The next task, and every task of a new run, starts on the
   run's profile (D8).
5. The selection never parks the unit and never takes a profile that would leave no independent judge (D5, D6).
6. The reason of `l4 retry` and `l4 resume` is the person's note. On a unit halted on a task, the command records the
   task, and every later step of that task gets the block "A person's note on this retry" until the task is done (D10
   to D12).
7. Labels, a plan's retry, a spec push, `l4 restart` and `l4 yolo resume` give no note (D10).
8. This change builds a reduced L4-CAP-007 of the proposed `model-capability` change, with the names that this
   request gives, and amends its SPEC row (D2).

## 1. Current state

### 1.1 The chain and the attempts

- `run_task` counts failures per phase (`failures = {"red": 0, "green": 0, "single": 0}`) and stops when the current
  phase reaches `implementer.max_task_attempts` (`src/l4/implementer/loop.py:195-208`) [V]. The step key counts
  attempts per phase in `attempts` (`loop.py:197`) [V].
- Each failure records `task.attempt_failed{task, phase, attempt, reason, excerpt_lines}` (`loop.py:252-255`). The
  halt records `breaker.tripped{reason: "max_task_attempts", task, phase, attempts, last_failure}` and returns the
  detail `task <k>: max_task_attempts (<n>) reached in <phase>; last failure: <reason>` (`loop.py:256-261`) [V]. No
  record names the profile that failed [V].
- The orchestrator calls `run_task(wb, task)` for each task with one workbench (`src/l4/orchestrator.py:884-918`) [V].
  `wb.selected` is the run's profile, chosen once per run by `_select()` (`orchestrator.py:801-805`) [V].
- A limit raises `RoleLimit` out of `run_task` (`src/l4/implementer/tdd.py:674-675`, `LIMIT_STATUSES` at `tdd.py:110`)
  [V]. `_fall_back` discards the step's changes, calls `switch_profile`, builds a new workbench and calls `run_task`
  again (`orchestrator.py:903-905, 968-976`) [V]. The new call starts with fresh counters, so a limit consumes no
  attempt (L4-AVL-006, L4-AVL-011) [V].
- `switch_profile` cools the profile of `_select()` and sets the run's `_selected` to the next profile, so every later
  task uses it (`orchestrator.py:920-932`) [V]. The workbench is rebuilt because the sandbox's visible login and the
  commit trailers follow `wb.selected` (`orchestrator.py:968-976`, `workbench.py:136, 185-188`) [V].
- The next profile gets a "previous attempt" block: `PreviousAttempt{profile, limit_kind, task}`
  (`src/l4/implementer/workbench.py:112-118`), rendered as "The agent before you (profile X) stopped on a Y limit ..."
  (`tdd.py:519-533`) [V].
- The fix loop calls `run_task(wb, task)` too and handles a limit on its own (`src/l4/verifier/fixloop.py:343-374`)
  [V].

### 1.2 What a failed attempt is today

- A harness check that does not pass (gates, criteria, guards) returns `failed` and counts (`loop.py:233, 242, 249-251`)
  [V].
- An invalid result counts too. A prompt-contract adapter's `result invalid` and a result that `parse_result` rejects
  both end the step as `failed` with the `result values:` line as excerpt (`tdd.py:676-686`) [V]. Attempt 2 of the live
  case is this path. `implementer.result_repair_attempts` is in the schema only: no code reads it
  (`src/l4/config/schema.py:505`, `grep -rn result_repair_attempts src/l4`) [V].
- An agent run that ends with any status other than `ok` and a limit status also counts as failed (`tdd.py:676-680`)
  [V].
- A `blocked` result raises questions and returns `blocked`: it does not count (`loop.py:218-227, 239-241`) [V].
- L4-IMP-008's failure fingerprint and same-error detection are not built (`loop.py:8-9`, "M1: ... identical-diff and
  same-error detection") [V].

### 1.3 Selection

- `Factory.for_role` walks the whole `roles.<role>` chain and records `availability.selected` with `fallback_from:
  chain[0]` when the index is 1 or more (`src/l4/agents/factory.py:155-180`) [V].
- `FallbackSelector.select` takes `required`, `serves` and `constraints` (`src/l4/availability/fallback.py:278-330`)
  [V]. When nothing is usable it records `availability.unavailable` and raises `WaitingCapacity` for a required role,
  `RoleUnavailable` for an optional one (`fallback.py:535-545`) [V]. The eval reads `availability.unavailable` as "no
  profile could serve the role" (`src/l4/eval/cellresult.py:44-52`) [V].
- The fold adds every `availability.selected` profile to `profiles_used[role]` and keeps `fallback_from[role]`
  (`src/l4/state/fold.py:265-273`) [V].

### 1.4 Independence

- The verifier selects judges and the `verifier_agent` with `independence_constraint(cfg, implementers)`, where
  `implementers` is `profiles_used["implementer"]` or the whole chain (`src/l4/verifier/ladder.py:1224, 1234, 1282`)
  [V]. The constraint is static: it compares declared vendors (or models) and probes nothing
  (`src/l4/verifier/selection.py:46-67`) [V].
- So every profile that ran an implementer step vetoes the judges of its vendor. A required role with no independent
  profile parks the unit (`select_judge`, `selection.py:84-92`) [V].
- The SPEC lists doctor CFG-003, "verifier independence satisfiable in the worst case" (`docs/SPEC.md:4057`), but the
  doctor does not register it (`src/l4/doctor/checks_config.py` registers CFG-002, 004, 005, 006, 007, 008) [V].

### 1.5 The retry reason today

- `l4 retry` calls `retry_unit(..., reason=reason)` with no `by` and no `signal` (`src/l4/state/retry.py:192-206`) [V].
  `Orchestrator.resume` records `unit.retried{reason[:300], by?, signal?}` and commits it to the unit branch
  (`orchestrator.py:421-480`, the append at `:456`) [V]. `l4 resume` does the same with `unit.resumed`
  (`src/l4/state/resume.py:90-95`) [V].
- Other writers of the same events use their own words:
  - a member's label: `reason: "label <name>", by: "member"` (`src/l4/ci/sweeper.py:759-762`);
  - a plan's retry: `reason: "the target moved; verify again (plan <id>)", by: "plan"` (`src/l4/yolo/cycle.py:1461`);
  - a spec push: `reason: "spec edited", by: "push"` (`orchestrator.py:539, 560`) [V].
- The ledger redacts every string value at write time (`src/l4/state/ledger.py:3, 208`) [V].
- The prompt's data blocks are answers, lessons, accepted review findings and the limit block (`tdd.py:597-602`). No
  code reads `unit.retried.reason` for a prompt [V, `grep -rn "unit.retried" src/l4`].
- `prompt.rendered` records `sources` (the unit-folder paths of `collect_sources`), `answers` and `lessons`
  (`tdd.py:606-611`, `src/l4/implementer/prompt.py:292`) [V].

### 1.6 Cost controls

- A plan's `limits.max_cost_usd` is checked by the plan step before it runs a unit (`src/l4/yolo/cycle.py:588, 1098,
  1625`, `src/l4/yolo/limits.py`) [V]. It does not stop a run in the middle.
- `budgets.max_cost_usd_per_unit` is in the schema (`schema.py:689`) and no code reads it. The runbook says so
  (`docs/runbook.md:1389`) [V].

### 1.7 The proposed `model-capability` change

`openspec/changes/model-capability/` (SPEC §21 row 15, "proposed") specifies outcome classes, fingerprints, a model
trail, `l4 models`, CAP-001, demotion, and opt-in escalation L4-CAP-007 (`escalation.enabled`, `escalation.after`,
per-rung attempts, `capability.escalated`, a stop when two rungs fail with the same fingerprint) [V]. None of it is
built: there is no `src/l4/capability/` [V].

## 2. Decisions

### D1. The trigger and what counts

- A **failed attempt** is one that `run_task` counts today (section 1.2): a harness check that does not pass, an
  invalid result, an agent run that ends `error`, `timeout` or another non-limit status. It counts against the profile
  of the workbench that ran it.
- A limit is not a failed attempt. It keeps its own fallback (L4-AVL-006).
- A `blocked` result is not a failed attempt. It goes to a person and never escalates. So does the hang question of a
  frozen test (`loop.py:243-248`).
- **Trigger.** After a failed attempt, `run_task` asks for an escalation when all of these hold:
  1. the run gave an escalation hook (only the unit's own task loop does, D4);
  2. `implementer.escalate_after` is at least 1 and less than `implementer.max_task_attempts`;
  3. the current profile has failed at least `escalate_after` attempts of this phase of this task;
  4. `roles.implementer` lists a profile after the current one.
- When condition 3 holds and the hook finds no profile, the task stays, and `run_task` asks again after each later
  failure of the same profile (a cooling profile can come back). Each refusal is one
  `implementer.escalation_skipped` (D13). At most `max_task_attempts - escalate_after` refusals per profile and phase
  can happen.

### D2. Relation to L4-CAP-007

This change builds the part of L4-CAP-007 that the live case needs, and it uses the names of this request. It differs
from L4-CAP-007 as follows:

| L4-CAP-007 (proposed) | This change | Why |
|---|---|---|
| `escalation.enabled` (default off), `escalation.after` | `implementer.escalate_after` (default 2, `0` off) | The request names the key and the default. A chain of one profile does not change. `0` restores today's behaviour. D6 removes the main risk of a default-on move, a park for lack of an independent judge. |
| trigger: `after` capability failures, a repeated fingerprint, or two invalid results | trigger: `escalate_after` failed attempts (D1) | No fingerprint and no outcome class exists (section 1.2). An invalid result is a failed attempt already. |
| `error` never escalates | an agent run that ends `error` counts | The harness has no outcome classes: an `error` run is a failed attempt today. A broken CLI on one profile is a fair reason to try the next. |
| per-rung attempts (SCN-CAP-20) | per-profile attempts (D3) | The same rule. |
| `capability.escalated{..., reason, fingerprint}` | `implementer.escalated{task, phase, from, to, failures, attempt}` | The request names the event. No fingerprint exists. |
| `escalation.max_per_unit` | none | Escalations are bounded per phase by the length of the chain (D3). Each task starts on the run's profile. |
| the veto parks the unit (`required_role_unavailable`) | the escalation does not take such a profile (D6) | A default-on rule must not create a new kind of stop. |
| a stop and a question when two rungs fail with the same fingerprint | not in this change | It needs fingerprints. |

Task 6.5 amends SPEC §21 row 15 and the `model-capability` proposal so that the SPEC promises escalation once.

### D3. Attempt arithmetic

**Rule.** For one task and one phase:
- each profile has its own count of failed attempts;
- a profile that has failed `escalate_after` attempts moves the phase to the next usable profile (D1, D5);
- the unit halts when the current profile has failed `max_task_attempts` attempts. That happens only on a profile that
  had no usable profile after it, or when escalation is off;
- the step key `<task>/<phase>/<attempt>` keeps counting across profiles, so that no two steps share a key (prompt
  files, WIP snapshots, `step.started`);
- `task.attempt_failed.attempt` is that step attempt number, and the event gains `profile`.

So the failed attempts of one phase are at most `escalate_after × (k − 1) + max_task_attempts`, where `k` is the number
of profiles that ran the phase.

**The worked example.** The consumer's chain is now `roles.implementer: [deepseek, glm]`: two cheap OpenCode Go
profiles with the same adapter and the same `OPENCODE_API_KEY` (`opencode-go/deepseek-v4.1-flash` and
`opencode-go/glm-5.3-flash`, the second verified to answer by the coordinator). An owner may add a stronger last
profile, for example a Claude Code subscription profile `claude-sonnet`. With the defaults (`escalate_after: 2`,
`max_task_attempts: 3`):

| Step | Profile | Result | Failures of the profile | Next |
|---|---|---|---|---|
| `4.1/red/1` | deepseek | `TypeError` in the new test | 1 | retry on deepseek |
| `4.1/red/2` | deepseek | invalid result | 2 = `escalate_after` | escalate to glm |
| `4.1/red/3` | glm | red committed | – | green on glm (D8) |
| (if glm fails) `4.1/red/3..5` | glm | 3 failures | 3 = `max_task_attempts`; glm is last | halt: `... reached in red on deepseek (2), glm (3); last failure: ...` |
| (with `claude-sonnet` last) `4.1/red/3..4` | glm | 2 failures | 2 = `escalate_after` | escalate to claude-sonnet |
| (with `claude-sonnet` last) `4.1/red/5..7` | claude-sonnet | 3 failures | 3 = `max_task_attempts` | halt: `... on deepseek (2), glm (2), claude-sonnet (3); ...` |

So `[deepseek, glm]` gives at most 5 failed attempts per phase, and `[deepseek, glm, claude-sonnet]` at most 7, of
which only the last 3 run on the paid profile.

**Why not "`max_task_attempts` bounds the total".** Then the defaults give the second profile one attempt (2 + 1 = 3),
and a third profile none. One attempt with no retry is a weak answer to the live case, and an owner would have to
raise `max_task_attempts`, which also gives every single-profile chain more attempts. The per-profile rule gives the
last profile today's full budget and changes nothing for a chain of one profile. It is also the rule of SCN-CAP-20 in
`model-capability`.

**`escalate_after` not below `max_task_attempts`.** The profile's own breaker trips first, so nothing escalates. That
is not a config error: a strict error would reject configs that set `max_task_attempts: 1` or `2` and rely on the
default. Doctor CFG-009 warns about it (D13).

### D4. Where the escalation happens

`run_task` cannot change its own profile: the profile is the workbench's, and the sandbox login and the trailers
follow it (section 1.1). Re-entering `run_task` from the orchestrator would lose the counters, the attempt numbers and
the last failure's excerpt. So the orchestrator gives `run_task` a hook:

```python
@dataclass(frozen=True)
class EscalationRequest:
    task: str
    phase: Literal["red", "green"]
    profile: str                                # the profile that failed
    failures: tuple[tuple[str, str], ...]       # (profile, reason) of every failed attempt of this phase, oldest first
    attempt: int                                # the attempt number of the next step

Escalate = Callable[[Workbench, EscalationRequest], Workbench | str]   # a new workbench, or why there is none

def run_task(wb: Workbench, task: Task, *, escalate: Escalate | None = None) -> TaskOutcome: ...
```

- `run_task` keeps all its state: `failures` (now per profile), `attempts`, `red`, `retry` (the last failure with its
  excerpt and guard notes, `loop.py:182-190`). On a new workbench it goes on with the next attempt of the same phase.
  A committed red stays.
- `run_task` records `implementer.escalated` or `implementer.escalation_skipped` with `wb.emit`, so the event has the
  workbench's context.
- `Orchestrator._escalate(wb, request)`:
  1. folds the ledger again and takes the unit's implementer profiles (`UnitState.profiles_used["implementer"]`, plus
     `wb.selected`);
  2. selects the next profile (D5) with the independence constraint (D6);
  3. on success, builds a workbench for the selected profile as `_fall_back` does (`_workbench(selected=…)`, the same
     baselines and static baselines), sets its `previous_attempt` to the escalation block (D9), stores the selection
     as the task's own profile (`_task_selected`) and returns the workbench;
  4. on failure, returns the reason.
- `_implement` passes `escalate=self._escalate` and clears `_task_selected` when `run_task` returns or raises.
- `_select()` and `ctx.shared["implementer"]` keep returning the run's profile. The task's profile is never visible
  outside the task. The fix loop reads `ctx.shared["implementer"]` (`fixloop.py:295-296`), so a fix unit starts on the
  run's profile.
- **Fix units do not escalate.** `fix_hook` calls `run_task(wb, task)` with no hook (`fixloop.py:361`). Nothing changes
  there. A fix unit's attempts are counted per profile like any other, which gives the same numbers as today because
  its profile does not change.

### D5. The selection of the next profile

- A new method `Factory.next_profile(role, unit, after, *, constraints)` walks the profiles of `roles.<role>` that come
  after `after`, in order, with the usual checks (`serves`, cool-down, the probe ladder or its cache, the concurrency
  gate, the constraints). The first usable profile wins.
- **It never parks the unit.** It selects with `required=False`. When nothing is usable it raises `RoleUnavailable`
  and records no `availability.unavailable`: the eval would read that event as "no implementer could serve"
  (section 1.3). It does not re-probe a remembered auth refusal (that re-probe is for a required role that has nothing
  else, `fallback.py:320-329`).
- **It records the move as a selection.** `availability.selected{role, selected, escalated_from: <after>, skipped,
  probes, cached}` with no `fallback_from`. So the fold adds the new profile to `profiles_used` (and the judge veto
  sees it, D6). The fold leaves `fallback_from[role]` as it is for an event with `escalated_from`. The console line
  ends `→ selected, escalated from <after>`.
- **No cool-down.** The profile that failed is not cooled and not marked unusable. The next task can select it.
- **Trailers.** The escalated workbench's `Selected` has `fallback_from = None`. Its commits carry `L4-Agent:
  <profile>/<model>` (`src/l4/vcs/trailers.py:38`) and no `L4-Fallback-From`, which stays a mark of a limit fallback.
- A busy profile is waited for as in every selection (L4-FAC-008, `availability.login_lock_wait`) [I].
- **By profile, not by adapter.** The walk goes over profile names. Two profiles of the same adapter, the same
  provider or the same vendor family (`deepseek` and `glm` on OpenCode Go; or a small and a large Claude model) are two
  rungs. A move between them is an escalation, because the model differs. The parts that could mix them up are keyed
  apart already:
  - a cool-down is keyed by `(adapter, model)` (`src/l4/availability/cooldown.py:78-84`, L4-AVL-004), so a limit on
    deepseek does not cool glm [V];
  - a probe result is keyed by the profile and a digest of its settings, the model included (`fallback.py:43-53`) [V];
  - an API-key OpenCode profile is not gated by the login lock unless it sets `max_concurrency`
    (`src/l4/agents/gate.py:123-130`), and the steps of one task run one after the other anyway [V];
  - the trailers and the events name the profile and its model (`L4-Agent: <profile>/<model>`).
  When the provider's limit is per account and not per model, glm can hit the same limit at its first step. It then
  cools on its own key, as any profile does [I].
- Two profiles with the same adapter **and** the same model are two names for one model. An escalation between them
  changes nothing but the session. Doctor CFG-009 warns about it (D13).

### D6. Independence

- The escalated profile ran an implementer step, so the existing veto keeps its vendor's judges out (section 1.4). No
  verifier code changes.
- **The keeper.** The escalation adds one constraint: a candidate profile `P` is not taken when, for `roles.judges` or
  for a non-empty `roles.verifier_agent`, no profile of that chain (with an adapter that can judge, as
  `ladder.py:1225` filters) passes `independence_constraint(cfg, [*implementers, P])`. The reason is `no profile of
  roles.judges would be independent of <P> (verifier.independence: <mode>)`. With `verifier.independence: none`, or a
  `roles.judges` with no judge profile, the keeper takes every candidate.
- The keeper is static, like the veto. A judge that is cooling or logged out at verification time can still park the
  unit, as today.
- CFG-003 stays not built (proposal, "Not in this change"). The runbook and the skill say: give the judges a vendor
  that no implementer profile of the chain has (L4-OPS-019).
- **The example chain.** `[deepseek, glm]` declares the vendors `deepseek` and `zhipu`. A judge chain of
  `[claude-judge]` (anthropic) stays independent for both, so the keeper takes glm. With `claude-sonnet` (anthropic)
  as the third profile, `[claude-judge]` alone would lose its independence, so the keeper does not take
  `claude-sonnet`. The judges then need a fourth vendor too, for example `[claude-judge, codex-judge]` (openai). A
  vendor-family switch (two Claude models) adds no vendor, so it never changes what the keeper allows.

### D7. Cost

- A stronger profile usually costs more per step. Per phase the number of failed attempts is at most
  `escalate_after × (k − 1) + max_task_attempts` (D3). A chain of one profile keeps today's bound.
- What is enforced [V, section 1.6]: a plan's `limits.max_cost_usd`, checked by the plan step before each unit run. A
  run that escalates is not stopped in the middle. `budgets.max_cost_usd_per_unit` is not enforced.
- Each step records `budget.cost{usd, profile, task}` with the profile that ran it (`tdd.py:664-671`), so the cost of an
  escalated step is charged to the plan as before. A subscription profile reports a nominal cost; Codex reports tokens
  only (L4-IMP-009).
- An owner who wants a lower bound sets `escalate_after: 0`, or a lower `max_task_attempts`.

### D8. How long an escalation lasts

- **The rest of the task, in this run.** The task keeps the escalated profile for its later phases (red, then green).
  A task whose red step the first profile failed `escalate_after` times usually needs the stronger profile for green
  too, and green is often the harder step. The failure counts stay per phase.
- **The next task** starts on the run's profile again: the cheapest usable profile first.
- **A new run** starts every task on the run's profile. An answered question, a retry and a WIP resume all start a new
  run. `l4 retry` gives new attempts (L4-OPS-001), and a retried task starts cheap again, with the person's note (D11).
- **A limit on an escalated step** (`RoleLimit`): `switch_profile` cools the profile that ran the step, which is the
  task's profile, not the run's. The run's selection then follows L4-AVL-006 (the chain from its start, cooling
  profiles skipped). The task goes on in a fresh `run_task` with fresh counts on that selection, as after any limit
  today. Its escalation ends. A later escalation of the same task skips the cooling profile.
- **A `blocked` result on an escalated step** goes to a person as today. Its question's `Asked:` line names the
  escalated profile (`loop.py:118-119` uses `wb.selected`).

### D9. What the new profile is told

- `PreviousAttempt` gains `why: Literal["limit", "escalation"] = "limit"`, `phase: str | None = None` and
  `failures: tuple[tuple[str, str], ...] = ()`. `limit_kind` becomes optional. An existing limit block does not
  change.
- For an escalation, `_previous_attempt_block` renders, for the steps of the same task **and phase** only:

  ```
  <l4:data kind="previous-attempt" profile="deepseek" reason="escalation" phase="red">
  The agent before you (profile deepseek) failed the red step of this task 2 times, so the harness gave the step to you.
  Its uncommitted changes were discarded; the commits already on the branch are kept. You start from the checkout as it
  is now, in a new session, with no transcript of those attempts. The harness rejected them for these reasons, oldest
  first:
  1. (deepseek) <reason 1>
  2. (deepseek) <reason 2>
  </l4:data>
  ```

- Each reason is the failure headline that `task.attempt_failed.reason` records, cut at 1000 characters [G]. The
  list has at most `max_task_attempts` entries for each earlier profile. The text goes through `defuse`, and the whole
  prompt is redacted before it is sent (`tdd.py:604`).
- The last failure, with its excerpt and guard notes, is still the section "Your previous attempt was rejected"
  (`prompt.py:223-227`), because `run_task` keeps `retry` (D4).
- The block names no transcript and no agent output beyond the harness's own reasons.

### D10. Which reasons are a person's note

| Command or writer | Event | A note? | Why |
|---|---|---|---|
| `l4 retry --reason TEXT` | `unit.retried` | yes | a person (or an agent for one) wrote the text after reading the stop |
| `l4 resume --reason TEXT` | `unit.resumed` | yes | the same command for `halted` and `escalated` (L4-OPS-001) |
| label `l4:retry`, `l4:resume` | `unit.retried{by: member}` | no | the text is the harness's `label <name>` |
| a plan's retry | `unit.retried{by: plan}` | no | the harness's text |
| a spec push | `unit.retried{by: push}` | no | the harness's `spec edited`; the spec itself is the person's text |
| `l4 restart --reason TEXT` | `unit.restarted` | no | see below |
| `l4 yolo resume --reason TEXT` | `plan.resumed` on the plan ref | no | see below |

- **`l4 restart`.** A restart starts the unit over from the base. It drops the old `.l4/` (L4-OPS-004 step 3), so no
  halted task is left to bind the note to. Its reason says why the old attempt was dropped, and it is posted as the
  closing comment of the old PR (`src/l4/state/restart.py:340`). A note for every task of a new attempt would be
  unreviewed spec text in every prompt. The reviewed channel for that is the spec, which the restart keeps.
- **`l4 yolo resume`.** Its reason goes to the plan's own ledger (`src/l4/yolo/commands.py:1059`), not to the unit's.
  It refuses while the stopped unit is `halted` and names `l4 retry` first (`commands.py:461-466`). So the unit's note
  always comes from that retry.
- **Explicit marking.** Only the two commands write the binding fields of D11. The rule does not infer a note from a
  missing `by`, so a new writer of `unit.retried` adds no note by accident. An event of an older ledger has no binding
  and gives no note.
- **No actor rule.** An agent may run `l4 retry` with a note. The note unfreezes nothing, reopens nothing and changes no
  check. The verifier judges the work against the spec.

### D11. Which task the note is for, and for how long

- **The fold** gains `halt_task` and `halt_fix_unit`: the `task` and `fix_unit` of the last
  `breaker.tripped{reason: "max_task_attempts"}`. A `unit.retried`, `unit.resumed` or `unit.restarted` clears them.
  A fix unit's step records `fix_unit` through the workbench's event context (`workbench.py:185-188`) [I].
- **The binding.** `retry_unit` and `resume_unit`, called by the commands, read the state before they record. When
  the unit is `halted` with `halt_reason: max_task_attempts` and a `halt_task`, the event gets `note_task` and
  `note_fix_unit` (when set). Otherwise the event gets neither, and the command says that the note reaches no step.
- **The reach.** A step of task `T` (of fix unit `F`, or of the unit itself) gets the note of the latest event of the
  unit's ledger that has `note_task`, when:
  - its `note_task` is `T` and its `note_fix_unit` is `F` (both absent for the unit itself);
  - no `task.done` of `T` (with the same `fix_unit`) comes after it;
  - no `unit.restarted` comes after it.
  Every step of `T` gets it: red, green, single, every attempt, every profile, every run, until one of these ends it.
- **A newer note replaces an older one**, also when it is for another task. A label retry adds no note and does not
  end the latest one.
- **Rejected: "the next task after the note" for a stop that names no task** (`baseline_failed`, `secret_in_push`,
  `escalated`, `waiting_capacity`, `in_review`). Such a note could reach a task much later, after a verification round
  or a spec push, when its words are old. A person who wants to steer the next step after such a stop has the reviewed
  channels: an answer to a question, or the spec.
- The note is read from the ledger files in the worktree, as `_ledger_events` reads them (`tdd.py:1114-1115`). The
  retry's commit holds the event, and the run starts at the branch head [I].

### D12. The block and its record

- **Heading and text.** One data block, last of the data blocks (after the previous-attempt block):

  ```
  # A person's note
  <l4:data source="retry note">
  A person's note on this retry: <reason>
  </l4:data>
  ```

  `data_block` defuses `<l4:data` in the text (`prompt.py:86-103`), and `_require_wrapped` checks the block
  (`prompt.py:91-97`). The harness contract already says that a data block is information, not instructions.
- **Length.** The text is the recorded `reason`, which `Orchestrator.resume` cuts at 300 characters
  (`orchestrator.py:456`). The block cuts it at 300 again, for a ledger written by hand. `l4 retry` and `l4 resume`
  print `<command>: the reason is longer than 300 characters; the implementer reads the first 300` (`retry:` or
  `resume:`) when they cut it.
- **Redaction.** The ledger redacts the reason at write time (`ledger.py:208`), and the prompt is redacted before it is
  sent (`tdd.py:604`).
- **Record.** `prompt.rendered` gains `retry_note: {event, ts, sha256}`: the event type, the event's `ts`, and the
  sha256 of the text inside the block. It is a field of its own, as `answers` and `lessons` are, and not an entry of
  `sources`: `sources` lists unit-folder files (`prompt.py:292`), and a reader would look for a file.
- **Section order (L4-IMP-004).** `render_prompt` (`prompt.py:214-288`) keeps its order, and the note is the last data
  block: contract; unit context; task; criteria; the data blocks (answered questions, lessons, accepted review
  findings, previous attempt, **the person's note**); "Your previous attempt was rejected"; for green, the unfrozen
  tests and the files the task names; for red, the stale tests; the phase; the gate command; the output contract.

### D13. What a person sees

- **Progress lines** (`src/l4/progress.py`):
  - `implementer.escalated`: `task 4.1 red: escalated from deepseek to claude-sonnet after 2 failed attempts`;
  - `implementer.escalation_skipped` (warning): `task 4.1 red: deepseek failed 2 attempts; no later profile can take
    it (<reason>); it stays on deepseek`;
  - `task.attempt_failed` with `profile`: `task 4.1 red attempt 2 failed on deepseek: <reason>`; without it, as today;
  - `breaker.tripped` with `profiles` of two or more entries: `halted: max_task_attempts (task 4.1: deepseek 2,
    claude-sonnet 3)`; otherwise as today;
  - `availability.selected` with `escalated_from`: `implementer: claude-sonnet ok (...) → selected, escalated from
    deepseek`;
  - `prompt.rendered` with `retry_note`: `task 4.1 red: the prompt holds the person's retry note of <ts>`.
- **`breaker.tripped`** gains `profiles: [{profile, failures}]` in the order the profiles ran the phase. `attempts`
  stays the number of failed attempts of the phase (all profiles).
- **The halt detail.** With one profile it is unchanged (tests assert it verbatim: `tests/unit/archive/test_hooks.py:213`,
  `tests/unit/state/test_status_reason.py:7, 27`). With two or more it is `task <k>: max_task_attempts (<n>) reached
  in <phase> on <p1> (<f1>), <p2> (<f2>); last failure: <reason>`. The profiles come before the last failure, so they
  survive the 300-character cut of `phase.changed.detail` and most of the 60-character `REASON` column.
- **`l4 status --unit`** of a unit `halted` with `max_task_attempts` and a `halt_task` prints, before `Next:`:
  `Retry note: the --reason of l4 retry goes to the implementer of task <k>` (and `of <fix unit>`). `--json` carries
  `halt_task` and, when set, `halt_fix_unit`.
- **`l4 retry` and `l4 resume`** print, after the retry line, `note: the reason goes to the next steps of task <k>`, or
  `note: the stop names no task, so no implementer step reads the reason`.
- **`l4 retry --help`**: `--reason TEXT  Why the unit can continue. For a unit halted on a task, the implementer of
  that task also reads it (at most 300 characters).`
- **Doctor CFG-009 (warn).** It fails when `roles.implementer` has two or more profiles and `escalate_after` is not 0
  and not below `max_task_attempts`: `implementer.escalate_after (2) is not below implementer.max_task_attempts (2):
  no task moves to <second profile>`. The fix line: `set implementer.escalate_after below max_task_attempts, or 0 when
  you do not want escalation`. It also fails when two profiles of `roles.implementer` have the same adapter and the
  same model: `profiles <a> and <b> run the same model (<model>): a move from <a> to <b> changes nothing`. A chain of
  one profile passes with `one implementer profile: a task that fails stays on it`.

### D14. Docs

- SPEC: L4-IMP-017 and L4-IMP-018 in §7.6 after L4-IMP-008; L4-OPS-018 and L4-OPS-019 in §12.4 after L4-OPS-017; the
  amendments listed in the proposal; scenarios in §23.7 and §23.19; CFG-009 in §15; §21 row 24 and the row 15 note.
- Runbook:
  - 7.2: the `max_task_attempts` row gains the profile breakdown and says that the `--reason` of `l4 retry` goes to the
    implementer of that task. A NOTE explains escalation and `escalate_after`.
  - 4.2: the new lines.
  - 10.4: the `l4 retry` row.
  - 11: the limits: no escalation in a fix unit; `max_cost_usd_per_unit` still not enforced.
- Skill:
  - `adopt.md`: a cheap-first chain of two OpenCode Go profiles (`deepseek`, `glm`, one `OPENCODE_API_KEY`), an
    optional stronger last profile (a Claude Code subscription profile), judges of another vendor than every
    implementer profile, and `max_task_attempts`/`escalate_after` (example in L4-OPS-019);
  - `operate.md`: write the `--reason` of a retry for the implementer of the halted task.
- CHANGELOG: a section `0.4.4` with Added (escalation, the note, CFG-009) and Changed (a chain of two or more profiles
  escalates by default; `escalate_after: 0` keeps the old behaviour).

## 3. Cases

| Case | Result |
|---|---|
| `[deepseek, glm]`, deepseek fails red 2 times | glm (same adapter, same key, another model) takes red attempt 3 with both reasons; `implementer.escalated{from: deepseek, to: glm, failures: 2, attempt: 3}` |
| glm then fails 3 times | halt after attempt 5; the detail names `deepseek (2), glm (3)` |
| red passes on glm | green runs on glm; task 4.2 starts on deepseek |
| `[deepseek, glm, claude-sonnet]`, judges `[claude-judge, codex-judge]`, glm also fails 2 times | claude-sonnet takes attempts 5..7; halt after 7 names all three |
| `[deepseek, glm, claude-sonnet]`, judges `[claude-judge]` only | glm is taken; claude-sonnet is not (keeper); after glm's 2nd failure `escalation_skipped` names the judge rule; glm goes on to 3 |
| `[deepseek]` only | no escalation and no event; halt after 3, detail unchanged |
| `escalate_after: 0`, or `max_task_attempts: 2` with the default | no escalation; CFG-009 warns for the second |
| two profiles with the same adapter and model | the move happens (by profile); CFG-009 warns that it changes nothing |
| glm is cooling | `implementer.escalation_skipped`; deepseek goes on; asked again after attempt 3 fails; halt after 3 deepseek failures |
| a limit on deepseek (OpenCode Go) | deepseek cools on `(opencode, opencode-go/deepseek-v4.1-flash)`; glm is not cooled; the limit fallback (L4-AVL-006) selects glm, which consumes no attempt |
| deepseek returns `blocked` | a question, no escalation |
| glm hits a usage limit in red attempt 3 | glm cools; the task restarts on the run's profile (deepseek) with fresh counts; a later escalation skips glm while it cools |
| a fix unit's task fails 3 times on deepseek | no escalation (no hook); halt as today |
| `l4 retry --reason "<advice>"` after the red halt of 4.1 | `unit.retried{reason, note_task: "4.1"}`; every later step of 4.1 has the note; 4.2 does not |
| a member adds `l4:retry` instead | no note |
| `l4 retry` on a unit halted with `baseline_failed` | no binding; the command says that no step reads the reason |
| the reason holds a token value | the ledger and the prompt hold it masked |
| the reason holds `</l4:data>` | defused; the block stays one block |

## 4. Risks

- **Default-on changes behaviour.** A chain of two or more profiles that an owner wrote as a fallback order now also
  moves on failures. The second profile may cost more or do worse. The CHANGELOG says so under Changed, and
  `escalate_after: 0` keeps the old behaviour [I].
- **Two cheap profiles of one provider.** `deepseek` and `glm` share one OpenCode Go key. When the provider limits the
  account and not the model, both can be limited on the same day. Each then cools on its own key and the chain moves
  on as for any limit [I].
- **The stronger profile's quota.** Escalations spend a subscription's usage windows. A limit then cools the profile,
  and the task falls back to the run's profile (D8). A day of failing tasks can empty a window [I].
- **The keeper is static** (D6). It cannot know that a judge will be cooling at verification time.
- **The note is text a person did not review in the spec.** It is bound to one task, capped, redacted, in a data block,
  recorded in the ledger and named in `prompt.rendered`. It cannot unfreeze a file or change a check, and the verifier
  judges against the spec [I].
- **Two meanings of "escalated".** The unit phase `escalated` (verification gave up) and the event
  `implementer.escalated` (a task moved to another profile) share a word. The event name is namespaced, and the docs
  say "moves to the next profile" in prose.
- **Fresh counts after a limit** (D8) can give the cheap profile `escalate_after` more attempts after the stronger
  profile hit a limit. That is today's limit rule. Every such loop needs a new limit, so it is bounded by the cool-downs
  [I].

## 5. Not verified

- The live failure sequence is taken from the request's account of the consumer run. This design did not read that
  consumer's ledger [I].
- That a fix unit's `breaker.tripped` carries `fix_unit` in a real fix round (it comes from `event_context`) [I].
- How long an escalation selection waits for a busy shared login in CI (L4-FAC-008) [I].
- Whether a stronger profile passes the live task 4.1. Task 7.3 runs the live check [G].
- That `opencode-go/glm-5.3-flash` answers with the consumer's `OPENCODE_API_KEY`: the coordinator verified it; this
  design did not run it. The vendor `zhipu` for glm is the declared value of the skill's existing glm example
  (`adopt.md`), not a served-model check [I].
