# Operator commands, live on GitHub (L4-OPS-013)

**Dates:** 2026-10-13 and 2026-10-14.
**Repository:** `ciprianiacobescu/l4-dummy-action` (private), GitHub-hosted `ubuntu-24.04`, setup action.
**Base branch:** `forge.base_branch: l4/main` (runbook 7.15).
**Agents:**
- implementer: Kiro (`kiro-cli`, `glm-5`, API key);
- judge: Claude Code.

**Unit:** `kiro:pick-priority`, a hand-written Kiro spec with tasks that cite `_Requirements: …_`.

All lines below are from the job logs of the named runs [V].

## Proven

| What | Run | Result |
|---|---|---|
| `l4/main` as the base: the unit is cut from it, and its PR targets it | 38466427438 | PR #5 `l4/kiro/pick-priority → l4/main`, PASS 4/4 |
| A spec push on the L4 branch re-enters the unit by itself (A, L4-OPS-014) | 38467391856 | `in_review → implementing (spec_edit_after_handoff …)` |
| A changed Kiro criterion reopens the tasks that cite it (D, L4-OPS-015) | 38467391856, 38532793604, 38552554920 | `chore(pick-priority): reopen tasks 1, 1.1 for changed requirements 1.3` (then 1.2, then 1.1) |
| A spec push from `awaiting_human` | 38532440149 | `awaiting_human → implementing (spec_edited)`, then PASS, then PR ready |
| `l4:restart` on an open PR | 38468253875, 38545197350 | the old head kept as `refs/l4/attempts/kiro/pick-priority/1`, `…/1-locks` moved, PR #5 closed with a comment, attempt 2 PASS in round 1 |
| `l4 retry` from a laptop (`--no-run`, git credentials only, no project setting) | — | `phase halted → implementing (resumed)`, `chore(pick-priority): retry [skip ci]` |
| `start_run` (`GitHubForge.start_run`) through the Mintkey proxy | 38469805330 | `started`; a `workflow_dispatch` run on `l4/main` |
| `l4:retry` from `halted` | 38531726023 | `retried by a member's l4:retry label`, then red ok and green ok |
| `l4:retry` from `escalated` | 38544173984, 38554870494 | `escalated → verifying (resumed)`, then PASS round 4, then PR #7 ready |
| `same_failure` stops a repeat after one round | 38552554920 | `escalated: round 3 failed the same way as round 2: …` |
| A PR closed without a merge becomes `abandoned` | 38555079812 | `MR !7 was closed without a merge: abandoned`, note `### Abandoned: …` |
| `l4:restart` on the closed PR of an `abandoned` unit | 38555223070 | `started over … attempt 3`, PASS round 1, PR #8 ready |
| The `REASON` column in the CI `l4 status` step | every run | e.g. `halted  task 1.1: max_task_attempts (3) reached in red; …` |
| A renamed harness repository | 38531148613 | `uses: ciprianiacobescu/agent-supervisor/…` fails with `Unable to resolve action. Repository not found`; `l4 upgrade --action-repo ciprianiacobescu/l4` repins |

## Defects the live runs found, each fixed with a test

1. **Stale tests.** A test written for the old text of a changed criterion blocked the reopened task. It may now be replaced, and is recorded as `tests.superseded`.
2. **Restart and open questions.** A restart carried the old attempt's open question, which blocked the new attempt. The question is now `superseded by restart`.
3. **Partial stubs.** The zero-value variant kept the `raise NotImplementedError` after a guard, so every red test read as vacuous. The `raise` is now a zero-value `return`.
4. **Verdict questions.** A later round left an earlier round's unanswered verdict question open (`l4:needs-answers`). It is now `superseded by round <n>`.
5. **Freeze pairing.** The red-green freeze paired the first red of a reopened task with its last green, which gave a false blocker on every round. Each red now pairs with its own green.
6. **The reopened red check.** A reopened task's red step needed new tests for unchanged criteria. It now needs them only for the changed ones.
7. **`same_failure`.** It ignored deterministic findings, so a repeated integrity blocker spent every fix round. It now counts them.
8. **Expected tests.** The verifier still expected the replaced tests. It no longer expects tests that a `tests.superseded` record lists.

## Seen

**A push to an existing unit branch runs that branch's own pinned harness.** In the setup-action form, after a re-pin on the base, a push to an open unit branch still downloaded the old build (run 38552554920: `ciprianiacobescu/l4@c898f2ba`). The new pin reaches the branch only when verification merges the base in. A dispatched or scheduled run uses the new pin. This is in the runbook (7.15).

## Not live

- **The GitLab pipeline start:** a recorded API exchange in a test, not a live call.
- **`waiting_capacity` and the secret halt:** unit tests only.
