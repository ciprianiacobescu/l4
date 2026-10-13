## Why

A person cannot get a stuck unit moving with L4 commands alone. On 2026-10-13 the maintainer reported a unit in an
escalation loop on a GitLab project, and the way out needed git and forge work by hand:

- the spec correction had to be cherry-picked onto the base branch;
- the unit branch had to be deleted and its merge request closed in the forge UI;
- a local worktree had to be removed;
- a pipeline had to be started by hand.

The maintainer's words: "I cannot easily retry or resolve an escalation or an on hold ticket just by L4 commands …
I shouldn't need to do specific merges and other magic just to retry something that is stuck."

An independent review of the operations runbook (docs/runbook.md, 2026-10-13) confirmed it and found more [V, code]:

- **The cause is hard to find.** The `l4 status` table has no reason column. `halt_reason` is empty for every
  escalation by verification except the feedback limit. The escalation headline says "no fix round is left" also when
  rounds are left. Only the run that stopped a unit logs the cause.
- **`l4 resume` is not enough.** It never starts a run. The operator must know which `--extend-*` flag the cause needs.
  Outside CI it stops with exit 2 unless `GITHUB_REPOSITORY` or `forge.gitlab.api_url` and `forge.gitlab.project` are
  set, which `l4 init` never writes.
- **Some stops cannot be resumed at all.**
  - A halt for a secret in the outgoing commits never reaches the ledger, so `l4 resume` refuses the unit.
  - A unit parked in `waiting_capacity` from `fixing`, or with no recorded time, never continues in CI.
  - A merge request closed without a merge leaves the unit in `in_review` for ever.
  - A deleted unit branch stops every run with exit 1.
  - A verdict question set to `dismissed` strands the unit in `awaiting_human`.
- **A spec correction does not reach a stuck unit.** A push to a halted or escalated branch only logs a hint.
- **The same failure burns every fix round.** The loop above failed each round on one test, which a fix round could
  not repair: the implementer's gates run without the verifier's coverage measurement, so the fixer never saw the
  failure. That defect is fixed in 0.2.1, but nothing stops the next repeat.
- **`l4 run --unit` on a halted unit is a trap.** It does not resume the unit, pushes a ledger commit, and its label
  sync can remove a member's `l4:resume` label.
- **Starting over has no command.** It takes a branch delete, a closed merge request and a worktree removal.

## What Changes

- **`l4 retry --unit U --reason TEXT`: one command to try again.** It does what the unit's phase needs:
  - `halted`: resume with new task attempts.
  - `escalated`: resume, and add one round of the kind that ran out (`--rounds N` for more).
  - `waiting_capacity`: try the agents again now, from any parked phase.
  - `in_review`: verify again.
  - `merged` with a failed archive or Kiro done-gate: try the archive or the done-gate again.

  Then it starts a run of the harness's CI on the base branch (GitHub `workflow_dispatch`, GitLab pipeline API).
  `--no-run` skips that. When the forge refuses, it prints the exact way to start one. `l4 resume` stays, as `retry`
  with its old flags.
- **`l4 restart --unit U --reason TEXT`: start a unit over.** It never loses history:
  - the old unit branch is kept as `refs/l4/attempts/<fw>/<name>/<n>`;
  - the merge request is closed with a comment that names that ref;
  - a new unit branch starts from the base head, with the unit's spec as the old branch had it and its task boxes as
    the base branch has them;
  - the next run implements the unit again.
- **A spec push to the unit branch re-enters the unit by itself (option A).**
  - A person's change to the unit folder sends the unit to `implementing` at the next run, from any phase that is
    not finished, halted and escalated included. Before, that happened only in review.
  - On Kiro, the tasks that cite a changed requirement are reopened and run test-first again (option D).
  - `l4 retry` stays as the explicit way (option B).
  - The CI triggers do not change.
- **The cause is shown.**
  - `l4 status` gets a `REASON` column.
  - `l4 status --unit U` prints the cause and the exact command that moves the unit.
  - Every escalation records its cause, and the note headline names it.
- **Repeats stop early.** A verification round that fails the same way as the round before escalates at once with
  `same_failure`, instead of spending another fix round.
- **The stops that could not be resumed now can be:**
  - a secret halt is recorded;
  - `waiting_capacity` always continues once its time passes or after a retry;
  - a merge request closed without a merge makes the unit `abandoned`, which `l4 restart` brings back;
  - a deleted unit branch names `l4 restart`;
  - a `dismissed` verdict question is refused with a message.
- **Local commands find the project.** The forge target comes from the `origin` remote when it is not configured.
- **Labels for people without a local setup.** The run creates `l4:retry`, `l4:restart` and `l4:resume`, and the
  sweep honours them with the member rule of `l4:resume`. A refusal names the command that works.
- **`l4 run --unit` on a halted or escalated unit has no side effects.** It exits 13 with the cause and the command.

## Impact

- **Code:**
  - `src/l4/state/retry.py` (new, and `state/resume.py`);
  - `src/l4/state/restart.py` (new);
  - `src/l4/state/status.py` and `planner.py` (the reason);
  - `src/l4/state/lifecycle.py` (new edges: `abandoned`, implementing after a stop);
  - `src/l4/state/fold.py`;
  - `src/l4/orchestrator.py` (the secret halt, `run --unit` on a stopped unit, the recorded escalation causes);
  - `src/l4/verifier/fixloop.py` (`same_failure`);
  - `src/l4/ci/sweeper.py` and `ci/resume_label.py` (the labels, a closed merge request);
  - `src/l4/forge/{base,github,gitlab}.py` (start a run, close a merge request, the target from `origin`);
  - `src/l4/cli.py`.
- **Ledger:** new events `unit.restarted`, `unit.retried` and `pr.closed`. The fold reads a restart as a new start.
- **Lifecycle:** `abandoned` gets its first edges; `halted` and `escalated` get an edge to `implementing`.
- **Docs:** `docs/runbook.md` (the procedures become one command each), SPEC (L4-OPS-001..012, delivery row 19), and
  `plugins/l4/skills/l4/references/operate.md`.
- **Compatibility:** `l4 resume` and the `l4:resume` label keep working. The `l4 status` table gains a column.
