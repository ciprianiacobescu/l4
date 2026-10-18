# The L4 control loop

## Rules

1. NEVER check out, commit to, rebase or force-push a unit branch `l4/<framework>/<name>` to restart or fix work. The one
   exception is `l4 feedback add` (`references/feedback.md`).
2. NEVER edit `.l4/` files or any ledger. NEVER write `refs/l4/*` by hand.
3. Run `l4` commands from a clone on the base branch, after `git fetch`. `l4 status` and `l4 plan` read your clone's refs.
4. A unit continues from its ledger, not from a push. Commands write an event; a CI run on the base branch reads it.
5. One control loop runs for the repository, always from the base branch (also when a push to `l4/**` starts it).
6. Activating or cancelling a plan is a person's decision. Resume a plan only when the person asked.
7. Read first: `l4 status --unit U` (`l4_status`), `l4 yolo status P`. Never merge a PR.
8. A write command starts a run on the base branch only with the forge token set; else it prints `start a run with: …`.

## State model

- Base branch: specs, `.l4/config.yaml`, `.l4/plans/<plan>.json`, the pinned workflow.
- Unit branch `l4/<fw>/<name>`: code commits, `tasks.md` ticks, the unit's ledger `.l4/ledger/*.jsonl`, `questions.md`,
  `feedback.md`, `verification.md`.
- Lock ref `refs/l4/locks/<fw>/<name>`: ledger events after the hand-off commit (`ledger-pending/`, for example `pr.ready`).
- Plan ref `refs/l4/plans/<plan>`: the plan's events (`ledger.jsonl`, `report.md`).
- PR: one per unit, the same across runs and retries. `l4 restart` makes a new branch and PR.

## What to run

| Situation | Commands (exact) | Writes | Verify |
|---|---|---|---|
| `halted` | Fix the cause (`Next:` line). `l4 retry --unit U --reason "R"` | `unit.retried`; commit `chore(<name>): retry [skip ci]` on the unit branch | Output `retried: now <phase>` |
| `halted` in a stopped plan (`unit_halted`) | `l4 retry --unit U --reason "R" --no-run`, then `l4 yolo resume P --reason "R" --no-run`, then start a run | Unit branch commit, then `plan.resumed` on the plan ref | `l4 yolo status P` is `active` |
| Plan stopped on a limit (`limit_cost`, `limit_runs`, `limit_attempts`, `limit_deadline`) | `l4 yolo resume P --reason "R" --extend-cost USD` (or `--extend-runs N`, `--extend-attempts N`, `--extend-deadline ISO`) | `plan.resumed{extend}` | Resume refuses while the limit stays reached |
| `awaiting_human` | `l4 questions --unit U`, `l4 questions show Q-NNN --unit U`, `l4 questions answer Q-NNN --unit U --text "A"` | One commit `[skip ci]` to `questions.md` on the unit branch | Output `pushed <sha> to <branch>` |
| `waiting_capacity` | A person fixes the login, key, CLI or `roles`. Then `l4 retry --unit U --reason "R"` (ignores `retry_after`) | As the halted row | Phase leaves `waiting_capacity` |
| `escalated` | `l4 retry --unit U --reason "R" [--rounds N]` (at a round limit it adds N rounds). For `no_convertible_finding`, give feedback first | As the halted row | Phase is `verifying` |
| `in_review` and a person pushed a commit | Nothing: the next run sends it to `verifying` (`implementing` for a spec edit). Verify again: `l4 retry --unit U --reason "R"` | Retry commit | `l4 status --unit U` |
| A run was killed mid-step, or a command printed `start a run with: …` | `gh workflow run l4.yml --ref <base>` (GitLab: new pipeline on `<base>`) | None | The run is listed |

An agent may answer only a question of a kind in `clarifier.auto_accept_kinds` that names no frozen path (else exit 2), unless
`clarifier.answer_by_agents` is true on the base branch. Verdict questions go to a person.

## Commands

| Command | Writes to | Pushes | Starts a run (token) | Agent |
|---|---|---|---|---|
| `l4 retry` | unit branch | yes | yes | yes |
| `l4 resume` (`halted`, `escalated` only) | unit branch | yes | no | yes |
| `l4 restart` | new branch, closes the PR | yes | yes | ask first |
| `l4 questions answer` / `accept` | unit branch | yes | yes | limited (above) |
| `l4 yolo check`, `l4 yolo status`, `l4 status`, `l4 run --dry-run` | nothing | no | no | yes |
| `l4 yolo review` | plan ref (`--local`), or asks CI | with `--local` | yes | yes |
| `l4 yolo resume` | plan ref | yes | yes | only when asked |
| `l4 yolo activate`, `l4 yolo cancel` | plan ref | yes | activate yes, cancel no | NO |

## Kept, redone, lost

- Kept: every pushed red and green commit, the ticks, the ledger lines in them, `questions.md`, the PR, a person's commits.
- A halted task: earlier tasks stay; only that task gets new attempts. Its red commit stays; only green runs again.
- After a kill, timeout or cancel, the next run starts from the last pushed commit. Nothing is pushed after a cancel signal.
- Lost: the uncommitted edits of the one running agent step.
- WIP snapshots (`refs/l4/wip/…`) are local, never pushed. On a hosted runner they are gone with the machine.
- A changed criterion reopens the tasks that cite it: they are redone.

## MCP tools

Read: `l4_status`, `l4_unit_events`, `l4_verification`, `l4_questions`, `l4_question`, `l4_plan_status`, `l4_plan_check`,
`l4_plan_findings`, `l4_plan_report`. Write: `l4_question_answer`, `l4_retry`, `l4_plan_resume` (each has `no_run`),
`l4_plan_review`, `l4_plan_draft`. No tool activates or cancels a plan, restarts a unit or dispatches a run.

Full explanation and swimlane diagrams: `docs/control-loop.md` in the L4 harness repository.
