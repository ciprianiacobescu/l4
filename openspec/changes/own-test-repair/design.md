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
  held: only these tests' definitions changed and imports may have been added, no check was removed, no skip was
  added, no product code changed"; the runs named are the runs that took place;
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

What the person reads must be what the accept applies. The question's text passes through the redactor (the diffs, the
test sources, and the whole Context again when the file is written), and a reader's view (a terminal, the forge's page)
treats some characters as line breaks, hides them or reorders the text around them. An agent that writes the edit can
use either to show a person a diff that is not the patch: a comment that opens an agent-field shape (`"signature": "`)
made the redactor take every line up to the next double quote, so the weakened assert and its context vanished from
the diff, the source view and the judge's prompt. So, besides the cases above, a proposal is not offered (the same
failure, naming the file and the reason) when the text of a repaired file, before or after the patch:

- changes under the question's redaction (`redact_text(text) != text`): a repair has no business holding a secret or
  an agent field, and whatever the redactor would change is what the person would not see;
- holds a character that a view does not show as it is. The rule is by Unicode class, not a list (a list missed the
  soft hyphen, the variation selectors and the tag characters, each of which made a changed check look unchanged): a
  character that `str.isprintable()` rejects (the controls, the format characters such as U+00AD and the bidirectional
  and zero-width ones, the line and paragraph separators, private-use and unassigned code points, and every space but
  U+0020), except tab, newline, a carriage return directly before a newline and one U+FEFF at the very start of the
  text (a byte order mark); and the default-ignorable characters that it accepts: U+034F, U+115F, U+1160, U+17B4,
  U+17B5, U+180B..U+180F, U+3164, U+FE00..U+FE0F, U+FFA0, U+E0100..U+E01EF, and the blank U+2800.

The question file redacts the whole Context at once, so the rendered question (its title and Context at full size)
must not change under the redaction either: a shape that opens in one part (the failure line shown for a test, one
file's diff) and closes in another would hide what lies between, though no file alone changes. And the parts are
redacted when they are made (`capture` redacts each diff and source), in an order that is neither file's: a diff puts
an added line before a removed one, so a private-key opener added above a closer that the edit removes takes the
lines between out of the diff. So the rendered question SHALL hold no redaction mark at all (`[REDACTED`): a repair
question shows nothing redacted, or it is not offered.

Fixes outside the repair close part of the same hole for every held question and the judge. The agent-field shape of
the redactor stops at a line end (a JSON string holds no raw newline, so no real field is affected); the judge's prompt
is still redacted whole, so a multi-line shape (a private key) spanning two of its parts still hides what lies between
from the judge (a limit; the person's question is guarded above). Every line a held question shows (a diff, a test's
source, a failure line) is cut at a newline only and spells each character of the rule above as an escape (`\x0d`,
`\u00ad`), so no character in a shown line breaks it out of its code block on the forge's page. The source view
of a test (`_python_source`) takes the lines Python counts (`\r\n`, `\r`, `\n`; not `str.splitlines`, which also breaks
at a form feed and shifts the window) of the function the test id names, inside its class when the id names one
(`TestB::test_x` is not `TestA.test_x`). The first line of the failure shown per test escapes the characters above.
Confusable letters (a Cyrillic `е` for a Latin `e`) are shown as they are and are not refused: the diff shows them, and
the person reads them; this is a limit, written in the runbook.

## D4 Person only

- `held.accepted_overrides(..., check="repair")` counts an `accept` only when its `question.answered` record has
  `by: human`. `agent` (an agent through `l4 questions` where `clarifier.answer_by_agents` allows it) and `delegate`
  never count for `repair`, whatever the config says. The other checks keep their rule.
- `find_replay` for check `repair` therefore finds no valid override for such an answer: it replays nothing and leaves
  the saved step as it is. The run records `held.accept_ignored{question, task, check: repair, by}` once, and the step
  runs again as an agent's: its proposal is held by a question of its own, which only a person's accept applies.
  Nothing is committed in between. Only a forged or hand-made record gives such an answer (the CLI refuses an agent and
  the delegate escalates); keeping the task blocked on a question that already reads as answered would leave a person
  nothing to answer, so the new question is the way out, at the cost of one agent call.
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
are the replay's. A repair step that is a replay never holds again. The replay's commit stages the files with
`core.autocrlf=false` and `core.safecrlf=false`, as `capture` read them, so the committed blob is the recorded `after`
whatever the repository's line-ending settings say. It carries no `notes_for_verifier` of the saved result: the
question does not show them, and the judge would read the agent's notes as part of an edit the person did not see them
in. Its `suppressions` are the saved result's, and the question shows each (file, line, rule, reason): the verifier
reports a suppression comment that no result declared, so dropping them would turn an accepted `# noqa` into a finding.

The commit that raises a held question (of every check, not only `repair`) also stages with no line-ending conversion:
the saved patch must be the bytes its `patch_sha256` names, or a repository with `core.autocrlf=input` stores a patch
whose digest differs after a fresh checkout and the accept can never be replayed.

Before that commit the replay compares what it is about to commit with the raise's `repair_blobs`: the changed test
files are the recorded paths, and for each the blob at the step base is the recorded `before` and the blob in the work
tree the recorded `after`. Another commit of the unit may have changed a repaired file between the raise and the
replay (a later task's test step, a person's commit), and `git apply` can still apply the patch to it; the result is
then not the edit the person read. A difference fails the attempt ("a repaired file changed since a person accepted the
edit"), uses the accept up and commits nothing, so the verifier never meets a commit that D6 would block.

A `retry` answer drops the saved step (existing `drop_held`) and the next step is an agent's, with the note.

## D6 The verifier accepts exactly the accepted edit

For an exempt commit that changes a test file which a `task.repaired` of the same unit and task names
(`_allowed_in_step`), `check_test_paths` also requires, per file (a new `_repair_acceptance`):

1. the event names a `question` and a `patch_sha256`;
2. a `question.raised{kind: harness, check: repair, task, id: question}` of the unit's ledger with the same
   `patch_sha256` and `repair_blobs` naming the file;
3. a `question.answered{id: question, by: human}` after that raise;
4. a `held.replayed{question, patch_sha256}` with the same digest after that answer;
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
