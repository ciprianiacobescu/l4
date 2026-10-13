# Operating L4: state, questions, resume

## Reading state

- **`l4 status`** shows every unit: phase, tasks, open questions, the last verdict, and feedback counts. `l4 plan`
  shows the next action of each unit.
- **The PR's sticky note** (by the harness's bot) says what waits for a person: questions, *Your feedback*, a halt or
  an escalation, and what to do about it.
- **In the unit's spec folder:**
  - `verification.md` is the last round's verdict;
  - `questions.md` holds the questions;
  - `feedback.md` holds the feedback.

  The ledgers under `.l4/` are the harness's record. Read them; never edit them.
- **Phases** in order: `implementing` → `implemented` → `verifying` → `fixing` → `verified` → `in_review`, then
  `merged`. `awaiting_human` means a question waits for you. `escalated` and `halted` need a person (see Resume).

## Answering `questions.md`

`l4 questions answer` is not built yet: edit the file by hand on the unit branch, then commit and push. The harness
reads only answers whose Status says they are submitted.

1. Find the section `## Q-NNN: …`, write your answer under `### Answer`, below the `<!-- write below this line -->`
   comment.
2. Set that section's `- **Status:**` to:
   - `answered`: your own answer;
   - `accepted`: take the clarifier's suggestion as written (only when the section has one);
   - `dismissed`: the question no longer matters.

   `open` is never read; a filled Answer under `open` gets a reminder in the note.
3. Leave the index table, the ids and every other section alone.
4. Then:

   ```sh
   git add <spec folder>/questions.md
   git commit -m "answer Q-NNN"
   git push
   ```

   Do not put `L4-Run:` in the message: those pushes are skipped.

**Verdict questions** (`Kind: verdict`, "Criterion C-… is disputed: accept as satisfied?"):
- The answer's **first word** must be `accept` or `reject` (any case), then your reason.
- A `reject` fails that criterion and starts a fix round. To pin down exactly what is wrong, end the reason with a
  `WHEN … THEN …` sentence: it becomes a regression scenario that the fix must make true.
- Before rejecting, check that the criterion id in the question is the one you mean (`verification.md` maps ids to
  `Req N.M`).
- The unit moves on only when **every** open verdict question in the file is answered.

## Resume an escalated or halted unit

The note names the reason. Only a member (Developer on GitLab, write access on GitHub) can resume.

- **Escalated at the feedback limit** ("feedback round limit reached (N)"):
  - add the label `l4:resume` to the PR, which gives one more feedback round; or
  - run `l4 resume --unit FW:NAME --reason "…" --extend-feedback-rounds N` (needs the forge token in the environment).
- **Escalated at the fix-round limit:** the label gives one more fix round, or use `--extend-fix-rounds N`. Each flag
  is refused for the other kind of stop.
- **Halted** (a guard, a stuck task, a budget): fix the cause the note names, then `l4 resume --unit … --reason "…"`
  or the label.
- **Then start a run.** Neither the label nor `l4 resume` starts one, so dispatch it or wait for the schedule:
  - GitHub: `gh workflow run l4.yml --ref <base branch>`;
  - GitLab: run the pipeline on the base branch.
- **Do not raise `feedback.max_rounds` or `verifier.max_fix_rounds`** to unblock one unit: that changes every unit.

## Merging

- The harness never merges. A person merges the ready PR with any method.
- The next base run detects the merge:
  - **OpenSpec:** it opens an archive PR unless the merge already archived the change;
  - **Kiro:** it runs the done-gate on the base and records it.
