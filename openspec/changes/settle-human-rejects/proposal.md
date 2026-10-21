## Why

A unit on a consumer repository looped with no way out (seen on 0.4.5). Verification round 3 raised a hold ("the diff
is longer than 120000 characters: the judge saw only the start"). The person rejected it (Q-004) with a reason in
prose, with no `WHEN ... THEN ...`. `_hold_finding` (`src/l4/verifier/verdicts.py`) made it a human-source major
finding that no fix task can be derived from, so the round escalated with `no_convertible_finding`
(`src/l4/verifier/fixloop.py`, `decide_fix`).

1. **The reject outlives the feedback that answers it.** The person then gave the concrete fixes with `l4 feedback`
   (kind `behaviour`). The next run spawned a feedback-only fix unit (`fix.spawned{feedback_only: true, consumed: []}`).
   It completed, round 4 judged both feedback items fixed, every gate and all 31 criteria passed. But
   `effective_verdicts` drops a reject only when its question is in `fix.spawned.consumed`, and a feedback-only spawn
   lists none (the human finding was skipped by the planner, so no candidate consumed it). The reject of Q-004 stayed
   in force, `settle_holds` added the human finding again, the verdict was FAIL, and the unit escalated with the same
   cause.
2. **The status line does not say what to do.** `l4 status` said `Next: l4 retry --unit U --reason TEXT`. A retry
   repeats the same verdict, so the line sent the person into a loop.
3. **The answer cannot be replaced on purpose.** `l4 questions answer Q-004` refuses ("Q-004 is answered ... edit its
   section by hand"). The harness already records a changed verdict answer as a new `human.verdict` (the latest per
   target wins), but the only way to change one is a hand edit that the command line does not explain.

## What Changes

- **A feedback-only fix unit consumes the rejects its round could not convert** (L4-VER-016). At read time,
  `effective_verdicts` drops a `reject` whose `human.verdict` comes before (ledger order) a `fix.spawned` with
  `feedback_only: true`; this covers ledgers written by 0.4.5 and older. At write time, the `consumed` of a
  feedback-only `fix.spawned` lists the questions of the rejects in force that the round listed as not converted. A
  hold that is raised again in a later round has no verdict in force, so it is asked again as a new hold question.
- **The escalation names its way out** (L4-OPS-022). For the cause `no_convertible_finding`, `l4 status --unit`, the
  refusal of `l4 run --unit` and the sticky note say: give the fix the human's finding asks for as feedback
  (`l4 feedback add --unit U --kind behaviour --when ... --then ... --text ...`, then the git lines `add` prints), then
  `l4 retry --unit U --reason TEXT`; a retry alone repeats the same verdict. Other causes keep their text.
- **A verdict answer can be replaced on purpose** (L4-QMD-010). `l4 questions answer Q-NNN --unit U --text TEXT
  --replace` rewrites the answer of an answered verdict question, keeps the previous answer in the section (in an HTML
  comment, so no reader of the answer sees it), and says "answer replaced" in the commit. Without `--replace` the
  refusal stays and its `Fix:` line names the flag for a verdict question. A clarification answer is never replaced
  this way (L4-QMD-006 is unchanged).
- **Docs.** `docs/SPEC.md`, the runbook procedure for an escalated unit with this cause, the skill reference, and
  `CHANGELOG.md` (`## 0.4.6 (unreleased)`).

Not in this change:
- a way to consume a reject that was not recorded before a feedback-only spawn (it stays in force: design D2);
- a change of `_hold_finding` or of the fix planner's choice of what is convertible.

## Capabilities

### New Capabilities

- `reject-settlement`: what a feedback-only fix unit consumes, at read and at write time, and the new hold question
  (L4-VER-016).
- `escalation-next-step`: the next step of a unit escalated with `no_convertible_finding` (L4-OPS-022).
- `verdict-answer-replace`: `l4 questions answer --replace` for a verdict question (L4-QMD-010).

### Modified Capabilities

None as an OpenSpec delta: `openspec/specs/` holds no baseline. `tasks.md` section 4 holds the `docs/SPEC.md` work.
