# Design: repair and propose

The base is branch f445-repair (merged at the start of this change): `l4.verifier.repairs.repair_candidates`,
`l4.implementer.repaircheck` (the pure structural check), `run_single(kind="repair")` through `tdd._run_repair` (scope
re-derived from git, review, gate, proofs), the `single_repair` prompt, the judge's "Repaired tests" block, the
traceability rule for repaired tests (`proved`, `sha10`) and the verifier's re-check. This change keeps all of it and
changes what happens at the end of a step that passes: it is held as a proposal, and only a person's accept turns it
into a commit.

## D1 Threat model: the checks are a filter, the person is the boundary

The structural check, the location rules of a candidate and the two proofs keep bad proposals away from a person: an
edit that removes a check, adds a skip, reads the environment, changes another test or passes without the product
fails the attempt and is never shown. They are not a security boundary: three reviews showed that a determined edit can
pass them and still check nothing. The boundary is a person's `accept` of the exact bytes, bound by digests from the
proposal to the commit to the verifier (D4, D6). A bypass of the filter costs a person's time on a bad proposal, which
they answer `retry`; it never reaches the branch unseen. Reviews of this change judge it on that model: a finding is a
way to commit a test edit that no person accepted, or that differs from the one they accepted, or a way for a proposal
to misstate what it does (a diff that is not the patch, evidence that is not the run's).

## D2 A passing repair step is held, not committed

`_run_repair` runs as before up to the commit. When the step is an agent's (no replay, `wb.replay_question` is None)
and every check passed, it builds `HeldCheck(task, "green", "repair", criteria=(), tests=<the repaired test ids in
gate form, sorted>, reason=<one line: the repair passed its checks and waits for a person>, runs=<the gate runs it
made>, kept=())`, `capture`s it while the edit is in the work tree, discards the changes and returns
`GreenOutcome("held", held=...)`. The loop raises the question as for every hold (`_raise_held`): no attempt is
counted and no profile is escalated. `held.Check` gains `"repair"`; `held_patch.CHECKS["single"]` becomes
`("tests", "repair")`; `_LABEL["repair"] = "repair proposal"`.

A step that fails a check fails the attempt as in the first design (the attempts, the escalation to a person with the
note that the test may be right and the code wrong). The hold happens only when there is something worth a person's
look.

## D3 What the question shows

`held_question` for check `repair` has its own head and options (the other checks are unchanged):

- the title `Task <task>: a repair of the unit's own failing tests waits for a person`;
- per repaired test: its id, the kind and first line of the failure that made it a candidate (from the round's
  `failures`), the gate it failed in;
- the evidence: the gate run that passed the repaired tests (its name and that they passed), how each was proved
  (`zero_value` for a unit-gate test, `base` for an e2e test), and the sentence "the structural rules of a repair
  held: only these tests' definitions changed, no check was removed, no skip was added, no product code changed";
- the changes and the diff of each file (`_source_lines`, as for every saved step), and the patch path;
- options: `accept: apply this edit` (option 1) and `retry: <note>`; the accept line says that the next run applies
  exactly the saved patch with no agent, runs the gate and the proofs again, commits it as this unit's repair, and that
  the next round's judge sees the test before and after; the person-only line replaces "an agent only where
  `clarifier.answer_by_agents` is true": "Only a person can accept a repair of a test; no agent or delegate answer
  applies it."

The raise (`question.raised`) records, besides the saved-step digests of `write_held`, `repair_blobs`: path ->
`[blob before, blob after]` for each file the patch changes, from `expected_state` (a temporary index: the step base,
the patch applied, `ls-files -s`), never from the work tree. A patch whose expected state cannot be computed, or that
changes a path outside the repaired tests' files, or a link, is not offered: the attempt fails ("the repair could not
be saved for a person to review").

## D4 Person only

- `held.accepted_overrides(..., check="repair")` counts an `accept` only when its `question.answered` record has
  `by: human`. `agent` (an agent through `l4 questions` where `clarifier.answer_by_agents` allows it) and `delegate`
  never count for `repair`, whatever the config says. The other checks keep their rule.
- `find_replay` for check `repair` therefore finds no valid override for such an answer: it queues nothing, and the
  hold stays. The run records `held.accept_ignored{question, task, check: repair, by}` once, and `l4 status` keeps the
  question as a person's.
- The delegate (`DelegatePass._without_a_call`) escalates a harness question whose raise has `check: repair`, with the
  reason "a repair of a test is a person's decision", without a model call.
- `l4 questions accept|answer` by an agent refuses a harness question whose raise (the unit's ledger at the folder's
  head) has `check: repair`, whatever `clarifier.answer_by_agents` says: "an agent may not accept Q-00N: a repair of a
  test is a person's decision" (exit as for the other agent refusals). With no readable raise the CLI keeps today's
  rule; the override rule above still holds.

## D5 Accept replays, then commits

On the next run, `run_single(kind="repair")` → `_run_repair` → `step_or_replay(wb, "single", task, ...)` finds the
accepted repair question (`find_replay`, unchanged: digest of the saved patch and result, `git apply --check`, stale
after `unit.restarted` or `tasks.reopened`) and `replay_step` applies it. Everything after the step runs again on the
replayed edit: the scope (re-derived from git), `_repair_review` (the structural check), the gate the tests failed in,
the proofs, the static gates. A failure fails the attempt (the accept is used up, as for every replay, and the next
attempt is an agent's again). On pass, the commit carries `L4-TDD: exempt` and the ledger
`task.repaired{task, base, files, tests, ids, proved, sha10, question, patch_sha256}`; `question` and `patch_sha256`
are the replay's. A repair step that is a replay never holds again.

A `retry` answer drops the saved step (existing `drop_held`) and the next step is an agent's, with the note.

## D6 The verifier accepts exactly the accepted edit

For an exempt commit that changes a test file which a `task.repaired` of the same unit and task names
(`_allowed_in_step`), `check_test_paths` also requires, per file (a new `_repair_acceptance`):

1. the event names a `question` and a `patch_sha256`;
2. a `question.raised{kind: harness, check: repair, task, id: question}` of the unit's ledger with the same
   `patch_sha256` and `repair_blobs` naming the file;
3. a `question.answered{id: question, by: human}` after that raise;
4. a `held.replayed{question, patch_sha256}` with the same digest;
5. the commit's parent blob of the file is `repair_blobs[path][0]` and the commit's blob is `repair_blobs[path][1]`.

A file for which any of these fails is a blocker "a repaired test differs from the edit a person accepted" naming the
file, the task, the commit and the first condition that failed. A `task.repaired` with no `question` (the first design,
never released) is the same blocker. The structural re-check of the first design (`_repair_problems`) stays: defence in
depth, and the same rules a person was told held.

## D7 Restart, reopen, retry

A repair question is a harness question: a restart sets an open one to `superseded by restart` (L4-OPS-004), and
`find_replay` treats a raise before `unit.restarted` or a `tasks.reopened` of the task as stale (drops the saved step).
An answered accept of a superseded attempt is not replayed. Nothing new is needed; scenarios pin it.

## D8 What a plan sees

The task is blocked by a person's question, so the unit waits (`awaiting_human`); the plan waits for it like any other
person's question. The cost of the design is the wait; the gain is that the edit, its diff and its evidence are ready,
and one `l4 questions accept` applies it.
