# Delivery plans (yolo mode)

A delivery plan lets you hand L4 a group of spec units, the order between them and the limits. You review the plan once
and activate it once. L4 then runs the units in dependency order. With the second opt-in, L4 also merges each verified
unit into the integration branch and goes on to the next one. It stops by itself, and says why, when anything is not
right.

This page is for the person who operates a plan. The commands for a stopped plan are in the
[runbook, section 12](runbook.md#12-delivery-plans). The normative text is in [SPEC 12.5](SPEC.md) (L4-YOLO-001..016).

## What it does, and what it does not do

- It runs units in order. A unit starts only when the units it needs are merged into the target and have passed their
  acceptance check.
- It runs one unit at a time.
- With `merge: auto` it merges the PR of each verified unit into the target. Nobody has to be present between units.
- It never promotes. It does not push, open a PR or merge to your production branch (`main`). You do that by hand.
- It does not deploy and it does not roll back.
- It does not use the forge merge API. It does not work with a target that requires a pull request.

## The plan file

The plan is the file `.l4/plans/<plan-id>.json` on the base branch. The name of the file is the plan id plus `.json`.
The id uses lowercase letters, digits and `-`, and starts with a letter or a digit.

```json
{
  "schema": "l4/delivery-plan@1",
  "plan_id": "checkout-v2",
  "target": "l4/main",
  "merge": "auto",
  "promotion": {"mode": "manual", "target_branch": "main"},
  "limits": {"max_cost_usd": 40, "max_unit_attempts": 2, "max_runs": 60, "deadline": "2026-10-20T18:00:00Z"},
  "external_dependencies": [],
  "batches": [
    {"id": "backend", "depends_on": [], "acceptance_profile": "all", "units": [
      {"id": "openspec:data-contract", "depends_on": [], "acceptance_profile": "all"},
      {"id": "openspec:service-api", "depends_on": ["openspec:data-contract"]}
    ]},
    {"id": "client", "depends_on": ["backend"], "units": [
      {"id": "kiro:client-flow", "depends_on": ["openspec:service-api"]}
    ]}
  ]
}
```

| Field | Meaning |
|---|---|
| `schema` | Always `l4/delivery-plan@1`. |
| `plan_id` | The id of the plan. It must match the file name. |
| `target` | The integration branch. It must be the same as `forge.base_branch`. There is no fallback to another branch. |
| `merge` | `human` or `auto`. See below. |
| `promotion` | Optional note for the hand-off. Only `mode: manual` is valid. L4 never promotes. |
| `limits` | Optional. A missing limit is unlimited, except `max_unit_attempts`, which is 2. |
| `external_dependencies` | Must be empty in this version. |
| `batches` | A batch is a group of units. A batch can depend on other batches. |
| `units[].depends_on` | Unit ids in the same plan. |
| `acceptance_profile` | A profile of `yolo.profiles` in `.l4/config.yaml`, or `all` (every configured gate), or `none`. A unit has `all` by default. A batch has `none` by default (no batch check). |

An unknown field makes the plan invalid. A unit waits for the units in its `depends_on` and for every unit of the
batches that its batch depends on.

Profiles are defined in `.l4/config.yaml`:

```yaml
yolo:
  profiles:
    smoke: [build, test]
    full: [build, lint, typecheck, test, e2e]
```

The gate kinds are `setup`, `build`, `lint`, `typecheck`, `test`, `e2e` and `extra:<name>`. A profile with no gate to run
is an error, never a pass. `none` is valid for a batch only.

## The two merge modes

**`merge: human`.** L4 only orders the work. Each unit gets its PR as usual. A person merges it into the target. At the
next run, L4 sees the merge, runs the acceptance profile of the unit on the merged target, and then lets the next unit
start. Only a merge into the target counts. A merge into another branch does not. This mode needs no extra opt-in.

**`merge: auto`.** L4 merges a verified unit by pushing the unit head to the target, without force, as a fast-forward. The
git server accepts the push only if the target tip is still part of the head. So a target that moved in the meantime is
refused by git, not by a check that could be out of date. L4 does not squash and does not rebase.

The merge happens only when all of this is true:

1. The unit is `in_review`, its last verdict is PASS, and it has no open question and no open feedback.
2. No person made a commit after the hand-off.
3. The PR is open, and its base is the target.
4. The target tip is contained in the unit head.

If the target moved, L4 sends the unit to `verifying`. The verifier merges the new base in and checks again. If this
happens twice for the same attempt, or if the push is refused for another reason (for example a protected branch), the
plan stops with `merge_refused`. After the merge, L4 runs the acceptance profile of the unit on the merged revision. A
fail or an error stops the plan with `postcheck_failed`. The archive PR of an OpenSpec unit is merged by L4 in the same
way.

L4 does not merge any unit that is not in an active plan with `merge: auto`. This is true whatever `forge.merge_policy`
says.

## The two opt-ins

Automatic merge needs two separate decisions:

1. **In the configuration:** `forge.merge_policy: auto` in `.l4/config.yaml`. Without a plan, this key does nothing, and
   `l4 doctor` warns about it.
2. **In the plan:** `"merge": "auto"`, and a person runs `l4 yolo activate`.

A plan with `merge: auto` while `forge.merge_policy` is `human` is refused at admission and at activation.

## Review in CI, then activate

1. Push the plan file to the base branch.
2. `l4 yolo check <plan>` runs the deterministic checks and prints the order of the units. The checks are: unique ids, known
   units, no cycle, known profiles, `target` equal to the base branch, no open question, the intake checks, and no unit
   that is already merged. It exits 0 or 2. It changes nothing.
3. A CI run reviews the plan. Run `l4 yolo review <plan>` to ask for it now. A judge agent reads each unit, and each
   batch with more than one unit, and gives READY, NEEDS_REVISION or BLOCKED with findings. An answer that is empty or
   not valid is BLOCKED. A blocking finding is never READY. The reviewer never answers a product question.
4. Read the review with `l4 yolo status <plan>`.
5. `l4 yolo activate <plan> --reason "<why>"` is a person's decision. It is refused unless the plan is admitted, the
   review is for the current plan and unit specs, every unit and batch is READY, `merge` and `forge.merge_policy` agree,
   the target exists on `origin`, and no other plan is active on that target. It freezes a digest of each unit's spec and
   the limits, and starts a run on the target.

Nothing runs from a plan before the activation. If a person changes the spec of a unit afterward (the harness's own
task ticks and `verification.md` do not count), the plan stops with `inputs_changed`.

## What runs in each CI run

A CI run makes at most one plan step. The step is the first of these that applies:

1. Review a plan that has no current review.
2. For the active plan: stop (a frozen spec changed, a limit is reached, the current unit is `halted`, `escalated`,
   `abandoned` or `rejected`); wait (the current unit needs an answer or capacity); merge a verified unit (`merge:
   auto`) and check it; check a merged unit; check a finished batch; or dispatch the next unit whose prerequisites are
   integrated.
3. Complete the plan and write the report.

After a step that leaves work, the run starts the next run on the target. A plan of N units takes about 3N runs. Units that
are not in the plan get no new agent work while the plan is active, but the sweep still records their merges and
closed PRs. `l4 run --unit <unit>` exits 13 for a unit that is not the current one.

## Stops and waits

A plan **waits** when the current unit needs a person's answer or has no agent available. The plan continues when the
cause is gone.

A plan **stops** on a fault: `unit_halted`, `unit_escalated`, `unit_abandoned`, `unit_rejected`, `merge_refused`,
`postcheck_failed`, `batch_failed`, `limit_cost`, `limit_runs`, `limit_attempts`, `limit_deadline`, `inputs_changed` and
`target_missing`. A stopped plan dispatches and merges nothing, including units that do not depend on the failed one. The
cause of each stop and the command that clears it are in [runbook 12.3](runbook.md#123-procedure-a-plan-is-stopped).
`l4 yolo cancel` stops the plan for good.

## Limits

`limits` has `max_cost_usd`, `max_unit_attempts` (default 2), `max_runs` and `deadline`. L4 charges the usage in the plan
ledger and checks it before each dispatch and each merge. The usage is never reset: not by a restart of a unit, not by a
resume. To allow more, use `l4 yolo resume --extend-cost`, `--extend-runs`, `--extend-attempts` or `--extend-deadline`.

## The report and the receipts

When the plan completes, and at each stop, L4 writes `report.md` into the plan ref and into `.l4-out/yolo/`. It states
the repository, the target and its revision, each unit with its PR, merge commit, post-merge result and usage, each batch
result, and the stop reason if any. It always says `Promotion to <branch> was not performed`. Read it with `l4 yolo
report <plan>`. Each integrated unit also gets one receipt, `receipts/<unit-name>.json`, in the plan ref.

## Protected targets

The merge is a push to the target. A target whose protection requires a pull request, or refuses the token of the job,
refuses the push. The plan then stops with `merge_refused` and the message of the forge. Merge through the forge API is
not in this version. Use a target that the job may push to, or use `merge: human`.

## Promotion is manual

When the plan completes, the target holds the integrated units. Review it, then promote it to `main` yourself, for
example with a PR. You can squash there. L4 never does it.

## Known limits

- One unit at a time. One active plan on a target.
- The target gets the commits of the unit branch as they are (no squash).
- GitLab is not validated live for plans. The design uses only git and forge calls that exist on both.
- A unit branch runs the harness version that it pins. The plan step runs in the checkout of the target, so the plan
  logic is always the target's version.
- Receipts of earlier plans are not imported (`external_dependencies` must be empty).

## Commands

| Command | What it does |
|---|---|
| `l4 yolo check <plan>` | Checks the plan and prints the order. Changes nothing. |
| `l4 yolo review <plan> [--local]` | Reviews the plan in CI now, or here with `--local`. |
| `l4 yolo activate <plan> --reason <text>` | Freezes the inputs and starts the plan. |
| `l4 yolo status [<plan>] [--json]` | Shows the state, the units, the usage and `Next:`. |
| `l4 yolo cancel <plan> --reason <text>` | Stops the plan for good. |
| `l4 yolo resume <plan> --reason <text> [--extend-…]` | Continues a stopped or waiting plan when the cause is gone. |
| `l4 yolo report <plan>` | Prints the report. |
