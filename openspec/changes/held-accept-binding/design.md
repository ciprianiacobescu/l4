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

## Review rounds

**D6. An accept takes effect only through the replay (content digests dropped).** Round 1 bound the accept to a per-test
source digest. Round 2 showed that no digest of "the test" can bind what the person saw: a module-level helper redefined in
the test file, a new autouse fixture in a conftest, a second definition of the name, and test ids of other languages (no
locatable source) all leave the digest equal while the behaviour changes. So content heuristics are gone from coverage
(`source_sha256` stays in the event for audit). For a question that saved its step (`patch_sha256`) the accept applies only
while that step is replayed (`Workbench.replay_question`); after the replay is used up (a failed gate, a refuted criterion)
it covers nothing, and a later agent step that meets the same inconclusive check is held again with a new question that saves
the new step. A replay that fails a gate counts as an attempt, so `max_task_attempts` bounds the cycle. A step produced by a
replay that held again for another check records `carries` (the earlier question), because it is the same saved change and
would otherwise loop between the two checks. A question of 0.4.16 (no `patch_sha256`) keeps the rule by test id. A
`tasks.reopened` of the task drops every accept raised before it.

**D7. The question shows everything the replay applies.** It lists every changed path and shows the redacted diff of every
changed path (named test files included) next to the source of the named tests; a cut says that the cut lines are replayed too
and names the patch path. A step over 200 paths or 50 files is not saved. The replay resets the environment setup, applies the
verified bytes from standard input with git settings independent of the operator's configuration (`--unified=3`, no autocrlf),
requires both digests, and commits under the profile that wrote the step.

**D8. The `accepted tests` block** no longer claims coverage for a saved step: after a used-up replay it says that the earlier
accept was for the earlier step only and a new step needs a new answer. For a question of 0.4.16 it still lists the tests
and the rule to keep them unchanged.

**D9. An explicit `saved` marker, always save, bounded questions, exact replay.** The old id-only rule was decided by a
missing digest, so a question whose step was not saved (a refusal, a very large step) fell back to it and an unseen body
could be accepted. Now every question of 0.4.17 records `saved: true|false`; only a question without the field keeps the old
rule. A step is saved whole whatever its size; a question caps each line (400 characters) and its Context (48 KB, less as `questions.md` fills), then lists
the paths and the patch path, so `questions.md` cannot pass its 2 MB limit. A refused replay raises a `saved: false` question
that offers only `retry`; an `accept` to it is ignored and the run says so. A replay commits exactly the saved patch: a `ReplayGuard`, modelled on `ProductionGuard`, snapshots the tree before the first
gate and puts every non-ignored path back to the snapshot after each gate run (`held.replay_restored`); it fails the step only
when a path cannot be put back, or when a gate replaced a parent folder of a guarded path by a link (never followed: the link is
removed, `held.replay_unsafe`); a leaf link is snapshotted and restored as a link.

**D10. The guard acts only through folder descriptors.** A path string is never resolved by the system: `confined.py` opens
each folder from the work tree root with `O_NOFOLLOW|O_DIRECTORY` and uses `dir_fd=` for every read, unlink, rmdir (fd-based
`shutil.rmtree`), mkdir, symlink and `O_EXCL|O_NOFOLLOW` creation, so a link planted before or during the restore (or one the
guard re-created itself) cannot redirect anything. The check is repeated right before each path is acted on. Only the links the
saved patch creates (`git apply --summary`, `create mode 120000`) are trusted; modes are restored; only the unit folder's own
`.l4/` is exempt. Linux and macOS both provide these primitives. The sidecar holds nothing that grows with the step. A global `core.autocrlf=true` is not defended against: a CRLF checkout can make the patch not apply, which is a
refusal, never a pass.
