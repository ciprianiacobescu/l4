## Why

L4 runs one unit at a time to a ready PR, and a person merges every PR. Two things are missing for a batch of related
specs:

- **Dependencies between units.** On 2026-10-13 the maintainer asked: "Maybe a feature is not yet developed (in
  development) but current spec depends on it. What can we do in a deterministic way?" Today L4 has no answer. Kiro
  waves order the tasks inside one unit only. Two units that depend on each other start at the same time, and the
  second one is built against a base that does not have the first.
- **Unattended delivery.** A selected, reviewed batch of units still needs one person per PR to merge it, and nothing
  starts the next unit when a merge lands. `forge.merge_policy: auto` is accepted by the configuration and does
  nothing (SPEC line 717 marks it `v1.1`; `src/l4/config/schema.py:624` is its only reader).

A proposal for this ("YOLO mode") was written on 2026-10-14 against 8cdb2617 (0.2.1). This change adapts it to 0.3.0
(operator-commands) and to the code as it is:

- 0.3.0 already renders the configured base branch in the GitLab job (L4-OPS-016) and was validated live with a base
  branch that is not the default (`l4/main`). The proposal's first gap is closed.
- The proposal's "fenced plan claim" and "host-enforced freshness" are built from pieces that exist: refs written with
  `git push --atomic` and leases (`l4 restart`), and a fast-forward push that the git server refuses when the target
  moved. A spike on GitHub (2026-10-14, PR #9 of the test repository) showed that GitHub marks a PR merged within 5 s
  when its head is pushed to its base, with `merge_commit_sha` equal to the head, and that a stale head is refused
  (`non-fast-forward`).
- The proposal's delivered-feature catalog has no consumer and is dropped. Delivery receipts stay, as outputs.
  Importing receipts of earlier plans (`external_dependencies`) is deferred: the field is parsed and a non-empty value
  is refused.

## What Changes

- **A delivery plan file** `.l4/plans/<plan-id>.json` (schema `l4/delivery-plan@1`) names the selected units, their
  dependencies, batches, acceptance profiles, limits and the integration branch. It is committed to the base branch.
- **Admission** checks the plan deterministically: known units, resolvable dependencies, no cycle (batches included),
  known profiles, the plan's target equal to `forge.base_branch`, no open questions. **Readiness review** asks the
  judge role, in CI, whether each unit and each batch is ready (READY / NEEDS_REVISION / BLOCKED), bound to digests of
  the unit folders.
- **Activation** is one operator command: `l4 yolo activate PLAN --reason TEXT`. It freezes the reviewed inputs and the
  limits. Nothing runs from a plan before it.
- **Two merge modes.**
  - `merge: human`: L4 only orders the work. A unit starts when every unit it depends on is merged by a person into the
    target. This is the dependency feature, and it changes nothing about who merges.
  - `merge: auto`: L4 merges a verified unit into the target with a guarded fast-forward push, confirms the merge,
    runs the post-merge acceptance profile, and starts the next unit. It needs `forge.merge_policy: auto` as well
    (two opt-ins). Promotion of the integration branch to `main` is never automatic: the plan ends with a handoff
    report.
- **Plan state** lives in the ref `refs/l4/plans/<plan-id>` as a ledger, written with atomic, leased pushes. One CI run
  makes at most one plan step (one review, one unit run, or one merge with its checks) and starts the next run.
- **Stops are safe and explicit.** A unit that halts, escalates, is abandoned or rejected stops the plan. A change to a
  frozen unit folder stops the plan (`inputs_changed`). `l4 yolo cancel`, `l4 yolo resume` (limits are never reset;
  more allowance is a recorded amendment), `l4 yolo status`, `l4 yolo report`.
- **While a plan is active,** units outside it get no new agent work. The sweep still observes their merges, closed
  PRs and labels.
- **Two fixes valid without a plan.**
  - A merged PR counts for a unit only when its destination is `forge.base_branch`; otherwise the cause says
    `merged into <x>, not the base`.
  - `forge.merge_policy: auto` with no active `merge: auto` plan is reported by `l4 doctor` as having no effect.

## Capabilities

### New Capabilities

- `yolo-mode`: delivery plans with unit dependencies, readiness review, activation, guarded automatic merge into a
  configured integration branch, batch acceptance, plan-wide limits and stops, receipts and a manual-promotion handoff
  (L4-YOLO-001..016).

### Modified Capabilities

- Merge observation (`ci/sweeper.py`): the destination of a merged PR is checked (L4-YOLO-007).
- The archive of an OpenSpec unit in a `merge: auto` plan is merged by the harness (builds `auto_merge_archive_pr` for
  plan units only, L4-YOLO-009).
- `l4 run`, `l4 plan`, `l4 status`, `l4 doctor` learn about an active plan.

## Impact

- New package `src/l4/yolo/`; changes in `orchestrator.py` (`run_command`), `planner.py`, `ci/sweeper.py`,
  `postmerge.py`, `config/schema.py`, `cli.py`, `state/status.py`, `doctor`.
- No CI template change: the plan step runs inside `l4 run`, which every template already calls. Adopters get it with
  `l4 upgrade` (or a new action pin).
- SPEC: a new section with L4-YOLO-001..016 and SCN-YOLO-*; `merge_policy: auto` is no longer "v1.1".
- First forge: GitHub, validated live. GitLab marks an MR merged in the same way, but it is not validated live in this
  change; the runbook says so.
- Not in scope: parallel plan units, several repositories, automatic promotion or deployment, merging through the forge
  API (needed for targets protected with "require a pull request"; such a target refuses the push, and the plan stops
  with `merge_refused`), importing receipts of earlier plans.
