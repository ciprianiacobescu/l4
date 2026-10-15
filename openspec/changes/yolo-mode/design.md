## Context

Baseline: `amaster` e63a9b02 (0.3.0). What exists and is reused (verified in the code on 2026-10-14):

| Area | What exists | File |
| --- | --- | --- |
| Integration branch | `forge.base_branch` is the start of new unit branches, the PR base, and the branch the GitHub and GitLab jobs run on (L4-OPS-016). Validated live with `l4/main` while `amaster` is the default. | `config/schema.py:622`, `vcs/worktree.py`, `ci/templates/*` |
| Unit state | Git-backed JSONL ledger per unit, folded state, pending ledger in `refs/l4/locks/<fw>/<name>`. | `state/ledger.py`, `state/fold.py` |
| Atomic ref writes | `l4 restart` writes refs with `git push --atomic` and `--force-with-lease` (H1 fix). | `state/restart.py` |
| Base merge before verify | The verifier merges the base into the unit branch first, so the verified head contains the base tip of that run. | `verifier/basemerge.py`, `vcs/merge.py` |
| Review re-entry | A commit by a person after the hand-off is found (`foreign_tail`); the strict harness-commit rule. | `state/review.py` |
| Merge observation | The sweeper lists merged PRs by head branch and matches the ledger's PR URL. It does not check the PR destination. | `ci/sweeper.py:283-310` |
| Post-merge | The OpenSpec archive PR (`PostMergeArchiver`), the Kiro done-gate. `archive.auto_merge_archive_pr` is in SPEC, not built. | `postmerge.py` |
| Continuation | `dispatch_continuation(base)` and `start_run(ref)` (workflow_dispatch / pipeline API). | `orchestrator.py:1385`, `forge/*` |
| CI job | `l4 plan --sweep`, then `l4 run`. GitHub: `concurrency: l4` (one job at a time), 180 min job timeout, `ci.time_budget`. | `ci/templates/l4.github.yml:59-61` |
| Operator verbs | `l4 retry`, `l4 restart` (resets the unit's counters except `cost_usd`, `iteration`, `restarts`: `fold.py:352`). | `state/retry.py`, `state/restart.py` |
| Spec push re-entry | A person's change to the unit folder re-enters the unit (`spec_edited`, L4-OPS-014); Kiro reopen (L4-OPS-015). | `orchestrator.py:416-505` |

Spike on 2026-10-14 (GitHub, the test repository, throwaway branches, since deleted): a draft PR `spike/ff-head →
spike/ff-base`; `git push origin <head>:refs/heads/spike/ff-base` (no force) → the PR was `closed`, `merged: true`,
`merge_commit_sha == <head>`, `merged_by` = the pusher, within 5 s. A push of a commit that did not contain the base tip
was refused: `! [rejected] … (non-fast-forward)`.

## Goals / Non-Goals

**Goals**
- Units that depend on each other run in order; a unit starts only when the units it needs are merged into the target.
- With two opt-ins, a reviewed and activated plan runs to the end without a person between units, and stops safely and
  visibly when anything is not right.
- Every plan decision is in a git ref, reproducible from that ref and the target branch.
- No CI template change.

**Non-Goals**
- More than one active unit (`max_active_units` is fixed at 1), several repositories, several plans active on one
  target at the same time.
- Automatic promotion of the integration branch, deployment, rollback.
- Merging through the forge API (squash, rebase, protected targets that require a pull request).
- Importing receipts of earlier plans (`external_dependencies` must be empty).

## Decisions

### D1. The plan file

`.l4/plans/<plan-id>.json` on the base branch. `<plan-id>` matches `^[a-z0-9][a-z0-9-]{0,62}$` and the file name.

```json
{
  "schema": "l4/delivery-plan@1",
  "plan_id": "checkout-v2",
  "target": "staging",
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

- `target` MUST equal `forge.base_branch`. There is no fallback to `main`, to the default branch or to the checkout.
- `merge`: `human` (ordering only) or `auto` (D8). `auto` also needs `forge.merge_policy: auto`.
- `promotion` is optional handoff metadata; only `mode: manual` is valid.
- `acceptance_profile` (unit and batch) is optional; it names a profile of `yolo.profiles` (D9) or `all` (every
  configured gate). A unit's default is `all`; a batch's default is `none` (no batch check).
- `limits`: every field is optional; a missing field is unlimited, except `max_unit_attempts`, whose default is 2.
- Unknown fields are refused (strict schema). `external_dependencies` that is not empty is refused with
  `external dependencies are not supported in this version`.

Module `src/l4/yolo/model.py`:

```python
class PlanUnit(_Strict): id: str; depends_on: list[str] = []; acceptance_profile: str = "all"
class PlanBatch(_Strict): id: str; depends_on: list[str] = []; acceptance_profile: str = "none"; units: list[PlanUnit]
class PlanLimits(_Strict): max_cost_usd: float | None = None; max_unit_attempts: int = 2; max_runs: int | None = None; deadline: datetime | None = None
class Promotion(_Strict): mode: Literal["manual"]; target_branch: str
class Plan(_Strict): schema_: Literal["l4/delivery-plan@1"] (alias "schema"); plan_id: str; target: str; merge: Literal["human", "auto"]; promotion: Promotion | None = None; limits: PlanLimits = PlanLimits(); external_dependencies: list[dict] = []; batches: list[PlanBatch]

def load_plan(text: str, *, file_name: str | None = None) -> Plan | PlanInvalid   # PlanInvalid(errors: list[str])
def plans_on(git: Git, rev: str, plans_dir: str) -> dict[str, tuple[str, str]]       # plan_id -> (path, blob sha)
```

### D2. Admission (deterministic)

`src/l4/yolo/admit.py`:

```python
@dataclass(frozen=True) class Finding: code: str; subject: str; text: str
@dataclass(frozen=True) class Admission: ok: bool; findings: tuple[Finding, ...]; order: tuple[str, ...]
def admit(plan: Plan, *, known_units: Mapping[str, UnitInfo], cfg: L4Config, held=None, state=None, archived=frozenset()) -> Admission
@dataclass(frozen=True) class UnitInfo: id: str; folder: str; open_questions: tuple[str, ...]; phase: str | None; intake_ok: bool
```

Checks, each a `Finding` code:
- `duplicate_id` (unit or batch ids), `unknown_unit` (not found by the providers on the target head),
  `unknown_dependency`, `self_dependency`, `cycle` (named path), `unknown_profile`, `empty_plan`, `target_mismatch`
  (`plan.target != forge.base_branch`), `merge_policy` (`merge: auto` while `forge.merge_policy` is `human`),
  `open_questions` (a unit has open questions), `intake` (the unit fails the existing intake checks), `finished`
  (a unit is already `merged`/`archived`: it cannot be planned), `external_dependencies`.
- The graph has one node per unit and one per batch. A unit waits for its `depends_on` units and for every unit of the
  batches its batch `depends_on`. A batch node waits for all of its units. A cycle anywhere is `cycle`.
- `order`: a topological order; among nodes ready at the same time, batch position, then unit position.
- `state` is the plan's own folded ledger. A planned unit in `state.merged` or `state.integrated` is done by the plan:
  no `finished`, `unknown_unit`, `open_questions` or `intake` finding for it (its change may be archived), and it stays a
  node of the graph. Every call that has the ledger passes it (the step's re-admission, `check`, `review`, `activate`);
  a plan without a state, or with nothing merged, is checked as before. `archived` holds the changes archived at the target
  (`plans.archived_changes`: `<root>/changes/archive/<date>-<name>` as `openspec:<name>`); an excluded id in it is known.
  The review does not ask the judge about a done unit.

`next_eligible(plan, plan_state, unit_phase) -> Eligibility` (also in `admit.py`, pure):

```python
@dataclass(frozen=True) class Eligibility: unit: str | None; waiting: Mapping[str, str]  # unit -> reason
```

A unit is eligible when it is not integrated, every unit it depends on (directly and through batch prerequisites) is
integrated (D9), and every prerequisite batch is accepted. Reasons: `waits for <unit> (not integrated)`, `waits for
batch <id> (acceptance)`. With `merge: human`, "integrated" is "merged into the target" (D9).

`unit_blocker(plan, state, unit)` is that rule for one unit. `next_eligible` never chooses a current unit that has a
blocker (it waits with the reason), the activation clears `current` when the unit has one under the new plan
(`plan.activated{current}`; the fold keeps the key's value, and an older event keeps the old rule), and the step does not
merge a unit that has one.

### D3. Input digests

`src/l4/yolo/digest.py`: `unit_digest(git, rev, folder) -> str` (sha256 hex, 16 chars).

- Hash every file under the unit folder at `rev`, sorted by path, as `path\0content\0`.
- Excluded: `.l4/**`, `verification.md`, `questions.md`, `feedback.md`: the harness writes them, or they are a
  person's input that the unit's own state machine handles (open questions make the plan wait, D10).
- In `tasks.md` (OpenSpec and Kiro) every checkbox marker `- [ ]`, `- [x]`, `- [X]`, `- [~]`, `- [-]` is normalised to
  `- [ ]` before hashing, so L4's progress marks are not an amendment.
- `plan_digest(plan_text) -> str` over the plan file bytes.

The digest of a unit is taken on the unit branch when it exists, else on the target head. Tests: a harness tick of a
task, a new `verification.md`, a new `.l4/ledger.jsonl` line → same digest; one changed word in `spec.md` or
`requirements.md` → different digest.

### D4. Plan state: the ref `refs/l4/plans/<plan-id>`

`src/l4/yolo/store.py`, `src/l4/yolo/state.py`.

- The ref points at a commit chain. Each commit's tree has `ledger.jsonl` (all plan events), and may have
  `report.md` and `receipts/<unit-name>.json`. Commits are made with git plumbing (`hash-object`, `mktree`,
  `commit-tree`) in the repository, without a worktree.
- `PlanStore(git, plan_id, config)`:
  - `read() -> PlanRead(head: str | None, events: list[PlanEvent], files: dict[str, str])` (after fetching the ref);
  - `append(events, *, files=None, expect: str | None) -> str`: one commit on top of `expect`, pushed with
    `git push --atomic --force-with-lease=refs/l4/plans/<id>:<expect or empty> origin <new>:refs/l4/plans/<id>`.
    A lost lease raises `PlanMoved`: the caller reads again and decides again. This is the fenced plan claim; it works
    across hosts because the git server checks the lease.
  - `list_plans(git) -> list[str]` from `git ls-remote origin refs/l4/plans/*`.
- Events (`PlanEvent(type, at, data)`; `by` and `run` in `data` where known):
  `plan.admitted{plan_digest, order}`, `plan.refused{findings}`, `plan.reviewed{plan_digest, units: {id: {verdict,
  digest, findings}}, batches: {...}}`, `plan.activated{plan_digest, digests: {unit: digest}, limits, by, reason}`,
  `unit.dispatched{unit, run}`, `unit.merge_requested{unit, head, target_before}`, `unit.merged{unit, head, pr,
  merge_commit}`, `unit.merge_refused{unit, reason}`, `unit.postcheck{unit, revision, profile, status, detail}`,
  `unit.integrated{unit, revision}`, `batch.accepted{batch, revision}` / `batch.failed{batch, revision, detail}`,
  `plan.waiting{reason, unit}`, `plan.stopped{reason, detail, unit}`, `plan.resumed{by, reason, extend}`,
  `plan.cancelled{by, reason}`, `plan.charged{unit, cost_usd, runs, attempts}`, `plan.completed{revision}`.
- `fold_plan(events) -> PlanState`:

```python
class PlanState(BaseModel):
    plan_id: str; status: Literal["new", "refused", "admitted", "reviewed", "active", "waiting", "stopped", "cancelled", "completed"]
    plan_digest: str | None; digests: dict[str, str]; review: dict[str, str]  # unit/batch -> verdict
    integrated: dict[str, str]; merged: dict[str, str]; accepted_batches: dict[str, str]; failed_batches: dict[str, str]
    current: str | None  # the unit dispatched and not yet integrated
    stop_reason: str | None; stop_detail: str | None
    used: Usage  # cost_usd, runs, attempts per unit; never reset (resume and restart keep it)
    extended: Usage  # what `plan.resumed{extend}` added to the limits
```

### D5. Readiness review (semantic, in CI)

`src/l4/yolo/readiness.py`. The judge role (the first available profile of `roles.judges`) reviews:
- each unit: the unit folder at the target head, the plan entry, the units it depends on (names and their folders);
- each batch with more than one unit: all its units' folders together.

Prompt template `src/l4/yolo/prompts/readiness.md`; output schema `src/l4/yolo/schemas/readiness.schema.json`:

```json
{"verdict": "READY|NEEDS_REVISION|BLOCKED", "findings": [{"criterion": "outcome|testability|interfaces|failure_cases|feasibility|duplicate_scope|contradiction|missing_dependency|batch_acceptance", "severity": "blocking|major|minor", "text": "…"}], "assumptions": ["…"], "missing": ["…"]}
```

`review_plan(app, cfg, plan, units) -> ReviewResult(units: dict[str, Verdict], batches: dict[str, Verdict])`. Rules:
- Structural validity alone never gives READY: an empty or unparsable answer is `BLOCKED` with `schema_invalid`.
- A `blocking` finding makes the verdict at least NEEDS_REVISION whatever the model said.
- The reviewer never answers a product question: an open question stays a question (admission refuses open questions).
- One review per plan digest and unit digests: the CI step reviews a plan when its latest `plan.reviewed` is for other
  digests.
- The adapter call reuses the judge's adapter machinery (`agents/factory.py`, the prompt contract of the judge), with
  the judge's tool restrictions (read-only).

### D6. Activation and operator commands

`src/l4/yolo/commands.py`, CLI group `l4 yolo`:

| Command | Effect |
| --- | --- |
| `l4 yolo check PLAN` | Load and admit at the target head; print findings and the order. Exit 0 / 2. No write. |
| `l4 yolo review PLAN [--no-run]` | Ask CI to review it now (start_run); with `--local`, run the review here. |
| `l4 yolo activate PLAN --reason TEXT [--no-run]` | Refused unless: admitted, the latest review is for the current plan and unit digests, every unit and batch is READY, `merge`/`merge_policy` agree, the target exists on `origin`, no other plan is active on the target. Then `plan.activated` with the frozen digests and limits, and `start_run(target)`. |
| `l4 yolo status [PLAN] [--json]` | Plan status, each unit (phase, waits for, integrated revision), batches, usage against limits, stop reason, and `Next:`. |
| `l4 yolo cancel PLAN --reason TEXT` | `plan.cancelled`. No new dispatch or merge. A unit already running finishes its run; it is not merged. |
| `l4 yolo resume PLAN --reason TEXT [--extend-cost USD] [--extend-runs N] [--extend-attempts N] [--extend-deadline ISO]` | From `stopped` or `waiting`: refused while the cause is still there (D10 says what clears each one); else `plan.resumed`, then `start_run`. `inputs_changed` needs a new review and a new activation instead. |
| `l4 yolo report PLAN` | Print `report.md` of the ref (complete or partial). |

Every write goes through `PlanStore.append` with the lease. Model calls happen only in CI (and in `review --local`).

### D7. Binding to the target, and the destination check

- The plan's `target` is the configured base branch; `check`, `activate` and every CI step refuse a mismatch
  (`target_mismatch`). A missing target on `origin` refuses activation and stops an active plan (`target_missing`).
- **Fix for every adopter** (`ci/sweeper.py` `_own_mr`): a merged PR counts for the unit only when `pr.base_branch ==
  forge.base_branch`. Otherwise it is logged and the unit's cause says `merged into <x>, not the base <base>`
  (`halt_detail` of a `plan.waiting` for plan units; a `log.warning` and the `l4 status --unit` Cause line for others).
  The unit stays `in_review`.

### D8. The guarded merge (`merge: auto`)

`src/l4/yolo/merge.py`:

```python
@dataclass(frozen=True) class MergeOutcome: status: Literal["merged", "stale", "refused", "not_ready"]; head: str | None; target_before: str | None; pr: int | None; detail: str
def merge_guarded(app, cfg, git, forge, snapshot: UnitSnapshot) -> MergeOutcome
def confirm_merged(forge, git, cfg, pr: int, head: str, *, wait_s: float = 30) -> bool
```

Preconditions, checked in this order (each failure is `not_ready` with a detail, nothing is pushed):
1. The unit is `in_review`, its last verdict is PASS, it has no open question and no unresolved feedback.
2. No person's commit after the hand-off (`review.py` `foreign_tail` is empty); otherwise the review re-entry already
   sends the unit to `verifying`.
3. The PR exists, is open, and its base is the target.
4. The target tip (`git ls-remote origin refs/heads/<target>`) is an ancestor of the unit head
   (`git merge-base --is-ancestor`). If not: `stale`. The plan step then sends the unit to `verifying` with the
   trigger `retry_requested` (the verifier merges the base in and verifies again), and records nothing else.

Then:
- record `unit.merge_requested{head, target_before}` (plan ref, leased);
- `git push origin <head>:refs/heads/<target>` (no force, the job's token). The server refuses unless the target tip
  is still an ancestor of `<head>`: the freshness of head and base is enforced by the git server, not by a read before
  the push;
- a refusal: `non-fast-forward` → `stale` (as above, once per unit attempt; a second one stops the plan with
  `merge_refused`); any other refusal (protected branch, permission) → `refused`, `plan.stopped{merge_refused,
  detail}`;
- success: `confirm_merged` polls `get_pr` until `merged` (GitHub and GitLab mark the PR merged when its head lands on
  its base) for up to 30 s. The target tip equal to `<head>` is the proof; the PR state is recorded when seen, and the
  sweeper records the unit's `merged` as today (`in_review → merged`).
- record `unit.merged{head, pr, merge_commit}`.

The implementer and the judge never see the forge token (existing role isolation). The merge is done by the harness
process in the CI job, after the agents of the run have exited.

### D9. Post-merge acceptance, integration, archive

- `yolo.profiles` in `.l4/config.yaml`: `{name: [gate kinds]}`, kinds from `setup`, `build`, `lint`, `typecheck`,
  `test`, `e2e`, `extra:<name>`. `all` is every configured gate; `none` is no check (valid for batches only).
- `src/l4/yolo/postcheck.py`: `run_profile(app, cfg, git, revision, profile) -> ProfileResult(status: pass|fail|error,
  gates: list[GateResult], detail)`. A detached worktree at `revision` in the harness cache, the existing gate runner
  and sandbox; the worktree is removed after. A profile with no gate to run is an `error`, never a pass.
- After `unit.merged`, the same CI step runs the unit's profile on the merged target revision →
  `unit.postcheck{status}`. Pass → `unit.integrated{revision}`. Fail or error → `plan.stopped{postcheck_failed}`.
- With `merge: human`, the step observes the merge (the sweeper's `merged`), checks that the merged PR's base is the
  target, runs the unit's profile, and records `unit.integrated` the same way.
- When every unit of a batch is integrated, the batch profile runs on the target tip → `batch.accepted` or
  `batch.failed` (stops the plan).
- **OpenSpec archive of a plan unit with `merge: auto`.** The archive PR that the sweeper opens after the merge is
  merged by the harness with the same fast-forward guard (`merge_archive_guarded`). A refusal is recorded as
  `archive.failed` with the reason; the plan does not wait for the archive (the code is integrated). Kiro: the
  done-gate, as today.
- **One archive PR at a time counts only PRs to the base** (all adopters, with D7): `open_archive_pr` waits only for
  an open archive PR whose base is `forge.base_branch`. An archive PR left open against an older base (after a change
  of `forge.base_branch`) no longer blocks every later archive; it is logged once per sweep.

### D10. One plan step per CI run; waits and stops

`src/l4/yolo/cycle.py`: `yolo_step(app, cfg, git, found) -> YoloStep`, called at the start of `run_command`, after
`discover` and the follow-ups:

```python
@dataclass(frozen=True) class YoloStep: allow: frozenset[str] | None; actions: tuple[str, ...]; start_next_run: bool
```

- `allow` is `None` when no plan file is on the target (nothing changes), else the set of unit ids `l4 run` may
  dispatch in this run. A unit listed in a plan file on the target is **held by that plan**: only the plan's own step
  dispatches it, and only while the plan is active and the unit is eligible. Until then it waits with the reason
  `held by plan <id> (<status>)`, whatever the plan's status (new, refused, reviewed, stopped, cancelled). This lets a
  person push the specs and the plan in one commit without the units starting on their own. To release a unit, remove
  it from the plan file (a plan change, so a new review). While a plan is active, units outside every plan get no new
  agent work either (`not in the active plan <id>`); with no active plan they run as today. The sweep in
  `l4 plan --sweep` still observes every unit (merges, closed PRs, labels, CI duty).
- Admission needs the intake result of units that have not run yet: the step uses the providers' side-effect-free
  validation (the checks `orchestrator._validate_kiro` and `_lint_scenarios` run, without writing a ledger).
- Per run, the step does the first of these that applies, then returns:
  1. For each plan file without a current review: admit, then review it (`plan.admitted`/`plan.refused`,
     `plan.reviewed`). One plan per run.
  2. For the active plan (at most one per target):
     - a frozen unit digest differs (on its branch or on the target, D3) → `plan.stopped{inputs_changed, unit}`;
     - a limit is reached (D11) → `plan.stopped{limit_<name>}`;
     - the current unit is `halted`, `escalated`, `abandoned` or `rejected` → `plan.stopped{unit_<phase>, unit}`;
     - the current unit is `awaiting_human`, `clarifying` or `waiting_capacity` → `plan.waiting` (once per cause);
     - the current unit is `in_review` with a PASS and `merge: auto` → D8, then D9 in the same step;
     - the current unit is `merged` (by D8 or by a person) and not integrated → D9;
     - all units of a batch integrated and the batch not accepted → the batch profile;
     - otherwise the eligible unit (D2) → `allow = {unit}` and `unit.dispatched`; a new unit branch starts from the
       target head as today.
  3. Every unit integrated and every batch with a profile accepted → `plan.completed`, the report (D12).
- After a plan step that wrote a record and left work, `start_run_next` is true; `run_command` then calls
  `start_run(target)` once at the end (the existing continuation path, also outside a soft deadline). The job's
  `concurrency: l4` queues it.
- `l4 run --unit U` while a plan is active: a plan unit that is not the eligible one, or a unit outside the plan, exits
  13 before the lease with `run: U waits for <reason> (plan <id>)` or `run: U is not in the active plan <id>`, and
  writes nothing.
- The 0.3.0 verbs still work on a plan unit. `l4 retry` and `l4 restart` act on the unit; the plan sees the new phase
  at its next step. A restart counts as an attempt (`plan.charged{attempts}`).

What clears each stop for `l4 yolo resume`:

| Stop | Cleared when |
| --- | --- |
| `unit_halted`, `unit_escalated` | The unit is no longer halted or escalated (`l4 retry` moved it). |
| `unit_abandoned` | The PR was reopened, or the unit was restarted. |
| `unit_rejected` | Never: the spec must change, so a new review and activation. |
| `merge_refused` | The operator says so (`--reason`); the next step tries the merge again once. |
| `postcheck_failed`, `batch_failed` | A new commit on the target (a person's fix) or `--reason`; the check runs again. |
| `limit_*` | The matching `--extend-*` raises the limit above the usage. |
| `inputs_changed` | Not by resume: run `l4 yolo review` and `l4 yolo activate` again (usage is kept). |
| `target_missing` | The target exists again. |

### D11. Limits

Charged by the plan step from the unit ledgers (`cost_usd` of the unit's fold, which survives a restart; runs: one per
dispatched run; attempts: 1 + restarts of the unit). Checked before every dispatch and every merge. Limits and usage
are in the plan ledger only, so a unit restart or a plan resume never resets them. `--extend-*` is recorded in
`plan.resumed{extend}`.

### D12. Status, report, receipts

- `l4 yolo status` and `l4 status` (one `PLAN` line above the table while a plan is active: `plan <id>: active, unit
  U (in_review), 2/5 integrated, $12.40/$40`).
- `l4 plan` shows, for a plan unit that waits, the reason `waits for openspec:a (not integrated)` instead of its next
  action, and for a unit outside an active plan `not in the active plan <id>`.
- On `plan.completed`, and on every stop, the step writes `report.md` into the plan ref and into `.l4-out/yolo/`:
  repository, target and its revision, the promotion target and the sentence `Promotion to <main> was not performed`,
  each unit with its PR, merge commit, post-merge result and usage, each batch result, the stop reason if any.
- `receipts/<unit-name>.json` per integrated unit: `receipt_id` (`<plan>/<unit>/<attempt>`), `unit_id`, `plan_id`,
  `repository`, `target`, `plan_digest`, `spec_digest`, `pr`, `reviewed_head`, `merge_commit`,
  `integrated_revision`, `postcheck`, `confirmed_at`. Receipts are written once; a second write for the same id is a
  no-op.

### D13. `merge: human` is the dependency feature

A `merge: human` plan needs no `merge_policy: auto`. It activates the same way and orders the work the same way; the
unit PRs wait for a person as today. A person who merges a plan unit's PR into the target lets its successors start at
the next run (the sweep sees the merge, D9 records `unit.integrated` after the profile).

### D14. `merge_policy: auto` outside a plan

`l4 doctor` reports `forge.merge_policy: auto has no effect without an active plan with merge: auto` as a warning.
The harness never merges a unit that is not in an active `merge: auto` plan, whatever `merge_policy` says. SPEC line
717's "auto: v1.1" becomes "auto: only for units of an active `merge: auto` plan (L4-YOLO-008)".

## Risks / Trade-offs

- **A wrong READY.** The review is a model judgement. Mitigations: admission is deterministic and runs first; a
  blocking finding cannot become READY; activation is a person's decision after reading the review; the verifier and
  the post-merge profile still gate every merge.
- **Unattended merges of wrong code.** The same gates and judge as a human-merged PR, plus the post-merge profile and
  the batch profile. The plan stops at the first failure, including later independent units. Promotion stays manual.
- **Fast-forward history.** The integration branch gets the unit branch's commits (no squash). Accepted for an
  integration branch; the promotion to `main` can squash.
- **Throughput.** One unit at a time, one step per run. A plan of N units takes about 3N runs. Accepted for v1.
- **Protected targets.** A target that requires a pull request refuses the push: `merge_refused` names the rule.
  API merge is a later change.
- **A unit branch runs its own pinned harness** (0.3.0 gotcha). The plan step runs in the base checkout (the target's
  harness), so the plan logic is always the target's version; a unit run may use an older pin until the base merge.
- **Both forges, one mechanism.** The design uses only git and calls that exist on both forges. GitLab was checked the
  same way on 2026-10-14 (vps5, project `ai-cici/l4-yolo-dummy`, MR !1): the MR was `merged` within 5 s of the push,
  `merge_commit_sha` = the head. Both forges are validated live in task group 9.

## Migration Plan

- No change for a repository without a plan file. `forge.merge_policy: auto` stays accepted and does nothing outside a
  plan (doctor warns).
- The `_own_mr` destination check changes behaviour for a PR merged into another branch: it no longer counts. Before,
  such a unit went to `merged` although its code was not on the base.
- SPEC gets a new section 12.5 (L4-YOLO-001..016) and SCN-YOLO-01..; the runbook gets "8. Delivery plans".

## Open Questions

- None blocking. Later: API merge for protected targets; parallel independent units; receipts as inputs of later plans.

## Revisions after the review of waves 1 and 2 (2026-10-14)

An independent review of wave 1 found 22 defects (15 reproduced); the wave-2 agents reported where their contracts
disagreed. These decisions replace the text above where they differ.

- **R1. Usage is charged per attempt (D11).** A restart starts a new unit ledger, so a unit fold's `cost_usd` and
  `restarts` cover the current attempt only. The attempt number of a unit is 1 + the number of its
  `refs/l4/attempts/<fw>/<name>/*` refs on `origin` (fetched by the step). `plan.charged{unit, attempt, cost_usd,
  runs}` carries the totals of that attempt; the fold keeps the maximum per (unit, attempt) and sums them. Attempts used
  by a unit = the highest attempt number charged. The review's cost is charged as `plan.charged{unit: "plan:review",
  attempt: 0, …}` by the CI step and by `review --local`; status and report skip keys that start with `plan:`.
  The attempts of a unit in a plan are counted from the refs it had at the activation: `plan.activated{attempt_base:
  {unit: n}}` records them (the first record of a unit stands on a re-activation), and the attempt in the plan is 1 +
  refs − base, so a restart before the plan is not an attempt of the plan. Every stop writes the live `plan.charged` of
  the unit's current attempt before `plan.stopped`, and the step, `l4 yolo resume` and `l4 yolo status` compute the live
  attempt and cost with the same functions (`limits.live_attempt`, `limits.live_state`).
- **R2. The activated plan is frozen (D4, D10).** `plan.activated` freezes the plan digest as `activated_digest`.
  `plan.admitted`, `plan.refused` and `plan.reviewed` recorded while the plan is activated (active, waiting, stopped)
  change only the review fields, never `activated_digest`, `order` or the status. A plan file whose digest differs from
  `activated_digest` stops the plan with `inputs_changed` (subject `plan`). `plan.stopped` and `plan.resumed` before any
  activation are ignored by the fold.
- **R3. Shared rules, one implementation each.** `yolo/limits.py` evaluates the effective limits (frozen + extended,
  the extended deadline included: `PlanState.extended_deadline`) and which one is reached; the step and `l4 yolo resume`
  both use it. `digest.current_unit_digest(git, cfg, unit_id, folder, target_ref)` takes the digest on
  `refs/remotes/origin/<unit branch>` when it exists, else on the target (D3); the review, activation and the
  `inputs_changed` check all use it. A revision that does not exist raises; it never gives the empty-set digest.
- **R4. Task markers are normalised with the providers' own patterns** (`tasks_merge` Kiro and OpenSpec forms: `-*+`
  and numbered bullets, no space, NBSP, BOM). Exclusions apply at any depth for the judge and for the digest alike.
- **R5. The guarded merge (D8) adds a fifth precondition:** the head to push equals the `ls-remote` tip of the unit
  branch and the PR head sha. The step records `unit.merge_requested` with the lease BEFORE the push (re-reading the
  plan: a cancelled or stopped plan does not merge), then pushes, then records `unit.merged`. `confirm_merged` accepts
  "the head is an ancestor of the target tip".
- **R6. `merge_archive_guarded`** also requires: every commit on the archive branch after the target tip is a strict
  harness commit, the archive PR is open with the target as its base, and the target is `forge.base_branch`.
- **R7. Post-merge profiles (D9).** `all` leaves out e2e gates that need an app server (`gates.e2e.serve`) and says so
  in the detail; a profile that names `e2e` while `serve` is set is refused at admission (`unsupported_profile`). A
  profile passes only when at least one required gate other than `setup` ran and passed; otherwise it is `error`.
- **R8. Holding (D10).** A unit listed in a plan file is held while the file is on the target, cancelled plans
  included; removing the unit from the file (or the file) releases it. An invalid plan file still holds the unit ids
  that can be read from its JSON (`batches[].units[].id`); a file that is not JSON holds nothing and is reported by
  `l4 plan` and `l4 yolo status`. A unit listed in two plan files is a finding (`held_by_other_plan`) for the second.
- **R9. Readiness (D5).** A judge timeout or error records no review (the next run tries again). Material cut by the
  size limits makes the verdict at least NEEDS_REVISION with a finding that names what was left out. File names, unit
  ids and batch ids reach the prompt only inside `<l4:data>` blocks.
- **R10. Every merged, non-integrated plan unit is post-checked (D9)**, not only the current one; a person's merge of a
  non-current unit in a `merge: human` plan is integrated by the next step.
- **R11. Stop reasons** add `unit_missing` (the unit is no longer among the units of the target; cleared when it is
  back). `plan.admitted` and `plan.activated` carry `merge`. The CI review records a `batches` entry for every batch
  with more than one unit.
- **R12. Limits are validated:** `max_unit_attempts >= 1`, `max_cost_usd >= 0`, `max_runs >= 1`, and a `deadline`
  with a time zone.

## Additions for the scenario (2026-10-15)

### D15. Plan graph tooling: exclusions, `l4 yolo draft`, the validator, the skill reference

The person asked that a plan "support updates via LLM and skills, plus deterministic validation". Every spec of the
repository should be in a plan, or deliberately outside all plans.

- **Exclusions.** `Plan.exclude: list[PlanExclusion]`, where `PlanExclusion(_Strict)` is `id: str` and
  `reason: str` (`min_length=1`, `max_length=200`). It is part of the plan file and so of the plan digest. Admission
  adds `excluded_and_planned`, `duplicate_id` for a repeated exclusion, and `unknown_unit` for an excluded id that no
  provider knows. `plans.holds_of` and `readable_unit_ids` leave excluded ids out: an excluded unit is not held by the plan.
  While a plan is active on the target the unit still gets no new agent work, like any unit outside the plan (D10);
  while no plan is active (review, activation, after completion) it runs as without a plan.
  `l4 yolo status` lists the exclusions with their reasons.
- **Derived units.** `<parent>-fix-<n>` and `<parent>-followup-<n>` (the `fixmark` and `followup` name patterns) are
  covered when their parent is listed, so that feedback on a planned unit does not make the repository uncovered.
  They may still be listed explicitly.
- **`l4 yolo draft`** (`yolo/draft.py`, wired in `yolo/commands.py` and `cli.py`). It uses the same providers as
  admission (`discover`, `plans.unit_infos` for the phase) on the working tree. It reads every plan file of the working
  tree to know what is listed. It writes JSON with `indent=2` and a final newline, keeping the key order of an existing
  file (`--update` loads it as a dict, appends, and dumps it). It never orders units and never adds `depends_on`: an
  ordering is a claim about the specs, which the person or the agent must make with evidence.
- **`validate_plan.py`** (stdlib only, one file, two byte-equal copies; a unit test compares them).
  - **Discovery mirrors the providers.**
    - OpenSpec units are the directories `<openspec root>/changes/<name>` where `<name>` matches
      `^[a-z0-9]+(?:-[a-z0-9]+)*$` and is not `archive`, with no symlink on the path.
    - Kiro units are the directories `<kiro root>/<name>` where `<name>` matches `^[A-Za-z0-9][A-Za-z0-9._-]*$`,
      holding at least one regular file of `requirements.md`, `bugfix.md`, `design.md` or `tasks.md`.
    - The frameworks and the two roots come from `.l4/config.yaml` (`spec.frameworks`, `spec.openspec.root`,
      `spec.kiro.root`). A small reader handles the block style that `l4 init` writes, falling back to the defaults
      (both frameworks, `openspec`, `.kiro/specs`) with a warning on anything else.
    - `--frameworks`, `--openspec-root` and `--kiro-root` override the config.
    - A unit test checks the script's discovery against the providers' `list_units` on fixture repositories.
  - **The schema check** repeats `model.py`'s rules by hand: required and unknown fields, types, the schema id,
    `plan_id` and the file name, `merge`, `promotion.mode`, the limit ranges, and a deadline with a time zone. A unit
    test runs every fixture through both `load_plan` and the script and requires the same verdict.
  - **The graph is admission's graph.** A unit waits for its `depends_on` and for the batch nodes its batch depends
    on; a batch waits for its units. The cycle text and the dispatch order are those of `admit._find_cycle` and
    `admit._topological` (heap on `(batch position, unit position)`). A unit test compares the order with
    `admit.plan_order` for each valid fixture.
  - **Waves:** the wave of a unit is 1 plus the highest wave of what it waits for, through batch nodes, and 1 when it
    waits for nothing. Waves show what could run together; the plan still dispatches one unit at a time in the order.
  - **Output.** Each problem is one line `<plan id>: <code>: <subject>: <text>`, or `<code>: <subject>: <text>` for
    the coverage problems. `--json` prints `{"ok", "problems": [{plan, code, subject, text}],
    "plans": {id: {"order", "waves"}}, "units": [...]}`.
  - **What only `l4 yolo check` can do:** open questions, intake, finished units, profiles, the target against
    `forge.base_branch`, and the merge policy. The script says so in its `--help`.
- **The skill reference `references/plan.md`** (about 120 lines, in the style of `operate.md`) covers:
  - When to make a plan, and when not: one spec, or specs with no order, need none.
  - **Create:** `l4 yolo draft <id>`, then read each spec's proposal or requirements and tasks. Add a dependency only
    when a spec uses something another spec introduces or changes: a module, a function, a data field, a file, an
    endpoint, a config key. Two specs that change the same code in conflicting ways are ordered too. Give one line of
    evidence per dependency in the commit message. Prefer fewer edges. Batches group units for an acceptance profile.
    `exclude` takes a reason that a person can check.
  - **Validate:** the script, then `l4 yolo check`. Fix every problem and never silence one.
  - **Hand off:** commit and push the plan file only. A person reviews it (`l4 yolo review`) and activates it.
  - **Update:** a new spec means `l4 yolo draft <id> --update`, then the same steps. An active plan stops when its
    file changes; it needs a new review and activation, and its usage is kept. A spec with no order to the active
    plan can go into a new plan instead.
  - **Never:** activate, resume or cancel for a person; write `refs/l4/plans/*`; set `merge: auto` unless asked and
    `forge.merge_policy` is `auto`; edit a unit's spec to make a plan valid.

### D16. OpenCode's own key (`OPENCODE_API_KEY`)

Found while preparing the scenario: an `opencode-go/…` implementer with `auth: api_key` cannot log in from CI. Today
`credential_variable("opencode", "api_key")` is None. The agent environment carries no credential (L4-SEC-001), and
the adapter writes a key file only for a custom provider. So the key never reaches OpenCode, on either forge.

A local check under an empty HOME, with OpenCode 1.18.33 [V, 2026-10-15]:
- with `OPENCODE_API_KEY` set, `opencode auth list` shows "OpenCode Go" and "OpenCode Zen" (environment), and
  `opencode run --pure -m opencode-go/deepseek-v4.1-flash` answers;
- without it, the run fails with `UnknownError: Unexpected server error`, not a 401.

So the auth step must check that the variable is there before any model call.

- `credentials.profile_credential_variable(profile)` returns `OPENCODE_API_KEY` for an `opencode` profile with
  `auth: api_key`, a model starting with `opencode/` or `opencode-go/`, and no `options.provider`. For any other
  profile it returns `credential_variable(profile.adapter, profile.auth)`. Every caller that has a profile uses it:
  - `credential_loader`;
  - `probes.credential_env` and `login_failed`;
  - `provision/readiness.py`;
  - `ci/github.credential_secrets`;
  - the doctor rows.

  `credential_variable` stays for the callers that have no profile.
- `opencode.py` `run` puts `credential_loader(req)` in front of the argv, as `codex.py` does. `isolation_env` sets
  no variable of that name.
- `probe_opencode`, auth step: for such a profile, `credential_auth` decides (presence passes with
  `auth_method: env`; absence fails naming the variable) before `opencode auth list`. The hello adds the one-entry
  `credential_env` to its environment.
- `DEFAULT_REDACT_ENV` gains `OPENCODE_API_KEY`. `refreshable_login` is unchanged: an `api_key` profile takes no
  login lock (a test pins it).
- `hosted_login_problem` is None for such a profile: the secret is the login on a hosted runner. The setup steps for
  an unset variable name `l4 setup github --secret OPENCODE_API_KEY=<ENV>`.
