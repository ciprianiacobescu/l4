## Context

L4-IMP-063 (0.4.16) holds a task when a check cannot decide. The answer `accept` is recorded as an override
(`accepted_overrides`): it covers a subject (criterion, or test id for `at_red`) only while the candidate tests are
among the tests the question named. The held step's changes are discarded, so the next step is a new agent step, and
nothing makes the agent write the same tests.

## Decisions

**D1. Save the held step as a patch before it is discarded.** At every site that returns a hold
(`_decide_pre_satisfied`, run (b) in `run_red`, `run_green` for `at_red`, `run_single` for `tests`) the step's
changes are captured while they are still in the worktree: `git add -A` (the harness excludes), `git diff --cached
--binary HEAD` without the run's ledger, then the index is reset. The bytes, the agent's result (a JSON object: the
red step reads `criteria_ids`, `tdd_exemption`, `notes_for_verifier` from it) and the redacted, cut source of each named
test travel on the `HeldCheck`. `_raise_held` writes `<unit>/.l4/held/<task>-<check>.patch` and `.json` and commits
them with `questions.md`; `question.raised` carries `patch_sha256`, `result_sha256` and the test ids. The file lives in
the unit folder's `.l4/` beside `ledger/`; `**/.l4/**` is already a protected glob. The result is in a sidecar (not in
the event) because the event stays a bounded index record; its digest is in the event, so it is as bound as the patch.
Test source: the function (decorators included) read from the worktree, redacted whole, then cut to 40 lines; a cut says
how many lines it dropped. At most 10 tests are shown, as the Tests line already does.

**D2. Replay instead of the agent step.** `step_or_replay` runs before `agent_step` in `run_red` (checks
`pre_satisfied`, `vacuity`), `run_green` (`at_red`) and `run_single` (`tests`). It looks at the newest harness
`question.raised` of the task and check. The replay applies when that question is answered `accept` by the existing
rules (`accepted_overrides`), carries a `patch_sha256`, was not replayed before (`held.replayed` for the question) and
no `unit.restarted` or `tasks.reopened` of the task follows it. The replay reads the files as regular files, checks
both digests, runs `git apply --check` and `git apply` (an empty patch applies nothing), and then does what `agent_step`
does after an agent returns: `revert_protected`, the ledger restore and the secret scan; it returns the saved result as a
`StepOutcome`, so the guards, gates and checks after it are the code an agent's step runs. A protected path in the patch
is put back with `guard.violation` and a secret fails the step, as for an agent. The override covers the patch's tests
because they are the ids the question named. Any refusal (missing, digest differs, does not apply) returns a hold whose
question says why; it has no patch and so never replays. Replaying once is what stops a failing replay from repeating:
the next attempt is an agent step (D4).

**D3. Cleanup.** `retry` (or `dismissed`) deletes the patch and sidecar in a commit `docs(<unit>): held patch dropped`
before the agent step. A replay queues the deletion in `Workbench.held_removals`; `Workbench.commit` removes the files
just before staging, so the step's commit carries it, and nothing between the replay and the commit sees the file gone
(the gates restore protected paths). A leftover (the replay failed) is queued again by the next step. Stale (restart,
reopening) drops it in a commit.

**D4. The prompt names the accepted tests.** `accepted tests` is a data block with the rule and, per accepted test
id, its source (from `held.replayed`, else the worktree). It is added for every agent step of a task whose check has an
accepted override, so a later attempt keeps the names.

**D5. The path is protected already.** `CONTRACT_PROTECTED_GLOBS` has `**/.l4/**` and the unit folder is protected: an
agent's write is put back with `guard.violation`. A test fixes it in place.

## Risks

- A patch of a held step is committed to the unit branch before a person has looked at it. It passed the agent step's
  secret scan; the replay scans it again.
- A branch that moved makes the patch not apply: a new question, never a pass.
