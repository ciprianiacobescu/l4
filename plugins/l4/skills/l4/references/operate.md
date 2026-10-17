# Operating L4: state, questions, retry and restart

## Reading state

- **`l4 status`** shows every unit: phase, tasks, open questions, the last verdict, the time of the last activity
  (column `LAST`), and feedback counts. `l4 status --unit FW:NAME` also shows the last activity and the open run with
  its CI link (`Last activity:`, `Open run:`). For a job that is silent, see runbook 4.6. `l4 plan`
  shows the next action of each unit.
- **The PR's sticky note** (by the harness's bot) says what waits for a person: questions, *Your feedback*, a halt or
  an escalation, and what to do about it.
- **In the unit's spec folder:**
  - `verification.md` is the last round's verdict;
  - `questions.md` holds the questions;
  - `feedback.md` holds the feedback.

  The ledgers under `.l4/` are the harness's record. Read them; never edit them.
- **Phases** in order: `implementing` → `implemented` → `verifying` → `fixing` → `verified` → `in_review`, then
  `merged`. `awaiting_human` means a question waits for you. `escalated` and `halted` need a person, `abandoned` means the PR was closed unmerged (see Retry or restart).

## Answering `questions.md`

Use the command first. It reads `questions.md` on the unit branch on `origin`, edits only the Status, the Answer and the
index row, commits (`[skip ci]`), pushes, and starts a run on the base branch, which resumes the unit.

```sh
l4 questions --unit FW:NAME                        # open questions; "draft" has an answer but is still open
l4 questions show Q-NNN --unit FW:NAME             # what accept takes, the frozen paths it unfreezes, Next: lines
l4 questions answer Q-NNN --unit FW:NAME --text "…"   # --text - reads stdin
l4 questions accept Q-NNN --unit FW:NAME           # take the clarifier's suggestion (not for a verdict question)
```

Add `--no-push` to print the diff and the commit message and write nothing, or `--no-run` to push without starting the run. For a hand edit, after the push start a run on the base (`gh workflow run l4.yml --ref <base>`, or the GitLab pipeline): a push to a unit branch runs that branch's own, possibly older, workflow copy. A refusal exits 2 with a `Fix:` line.

**Agent rule.** If you are an agent (an agent marker in the environment, or stdin is not a terminal), you may write only
a question whose kind is in `clarifier.auto_accept_kinds` (default `technical`), that is not a verdict question, and
whose answer names no frozen test path of the task it holds. Give every other question to a person: a product or
ambiguous question, a verdict question, or an answer that names a frozen path. Only a person, or
`clarifier.answer_by_agents: true` in `.l4/config.yaml` on the base branch, changes that. The key on the unit branch does
not count.

The hand edit is the fallback, for a question the command refuses. Edit the file on the unit branch, then commit and
push. The harness reads only answers whose Status says they are submitted.

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
- To change a verdict answer on purpose (a person only, unless `clarifier.answer_by_agents` is true):
  `l4 questions answer Q-NNN --unit FW:NAME --text "accept …" --replace`. It works only on an answered verdict question,
  keeps the old answer in a comment under the new one and says `(answer replaced)` in the commit. Without `--replace`
  the command refuses an answered question. A clarification answer is changed by hand (L4-QMD-006).

## Retry or restart a stuck unit

The note names the reason; so do `l4 status` (the `REASON` column) and `l4 status --unit FW:NAME`, which ends with
`Next:` and, for a unit a label moves, an `Or:` line. Only a member (Developer on GitLab, write access on GitHub) can
use a label. A command needs the forge token in the environment; the project comes from `origin`.

- **Continue where it stopped: `l4 retry --unit FW:NAME --reason "…"`**, or the label `l4:retry` on the PR.
  - Works on `halted`, `escalated`, `waiting_capacity` and `in_review` units (a merged unit: the archive retry).
    Any other phase is refused with what moves it.
  - Escalated at a round limit: it adds one fix (or feedback) round; `--rounds N` adds N.
  - If you changed the spec on the unit branch since the stop, the unit goes back to `implementing`.
  - It then starts a run on the base branch (`--no-run` skips that). A label starts none: the run that reads it
    continues the unit.
  - **The `--reason` is the implementer's note.** For a unit halted on `max_task_attempts` (the cause names a task),
    the reason of `l4 retry` goes to the implementer of that task, in every step, until the task is done. Write it for
    that implementer: say what to do differently, in at most 300 characters (the implementer reads the first 300). The
    command prints `note: the reason goes to the next steps of task <k>`. A stop that names no task gives no note.
    A label, a spec push and `l4 restart` give no note.
  - `l4 resume` and `l4:resume` still work and mean the same for `halted` and `escalated`, but start no run.
- **Escalated with `no finding of this round can be converted into a fix task`** (`no_convertible_finding`): a retry
  alone repeats the same verdict. Give the fix that the person's rejected finding asks for as feedback first
  (`l4 feedback add --unit FW:NAME --kind behaviour --when "…" --then "…" --text "…"`, then the git lines it prints),
  then `l4 retry`. The feedback fix unit ends the reject it answers, and the next round judges the fixed code. If the
  rejection was a mistake, replace the answer with `--replace` (above), then retry.
- **Start over: `l4 restart --unit FW:NAME --reason "…"`**, or the label `l4:restart`. It cuts a new branch from the
  base with the unit folder (spec, questions, feedback; task boxes as the base has them), keeps the old head as
  `refs/l4/attempts/…`, closes the old PR and starts a run. Use it for a PR closed without a merge (`abandoned`), a
  deleted branch, or a unit whose history is poisoned.
- **A spec push re-enters a unit by itself.** A commit on the unit branch that changes the unit folder (not `.l4/`,
  `verification.md`, `questions.md`, `feedback.md`) sends the unit to `implementing` at the next run, from most phases
  (during `fixing`, when the fix unit ends). On Kiro, tasks that cite a changed criterion are reopened. Add `[skip ci]`
  to an unfinished edit.
- **Do not use `l4 run --unit`** on a stopped unit: it exits 13 and changes nothing.
- **Do not raise `feedback.max_rounds` or `verifier.max_fix_rounds`** to unblock one unit: that changes every unit.

## Merging

- The harness never merges, except a unit of an active delivery plan with `merge: auto` (see Delivery plans below). A person merges the ready PR with any method.
- The next base run detects the merge:
  - **OpenSpec:** it opens an archive PR unless the merge already archived the change;
  - **Kiro:** it runs the done-gate on the base and records it.

## Delivery plans (`l4 yolo`)

A plan is `.l4/plans/<id>.json` on the base branch: units, `depends_on`, batches, limits, `merge: human|auto`. Full guide:
`docs/yolo-mode.md`; stops and how to clear them: `docs/runbook.md` section 12. Commands:

- `l4 yolo check PLAN`: admission only (cycles, unknown units, target is the base branch, open questions). Exit 0 or 2. Changes nothing.
- `l4 yolo review PLAN`: CI reviews the plan (READY / NEEDS_REVISION / BLOCKED per unit). `--local` runs it here.
  `--worktree` reviews the working tree before the push (dry, writes nothing); `--record` records a committed tree so CI
  does not review again; `--fresh SUBJECT` judges a subject again.
- `l4 yolo findings PLAN [SUBJECT] [--all] [--json]`: every blocking and major finding with its id and a `Resolve:` line,
  and what changed since the previous judgement. Reads only.
- `l4 yolo accept PLAN SUBJECT --reason "…"`: a person accepts a subject's remaining findings on record (never for
  BLOCKED, a blocking finding or a cut of the unit's folder; agents only if `yolo.review.accept_by_agents` is true on
  the base branch). Not an agent's command by default.
- `l4 yolo activate PLAN --reason "…"`: freezes the reviewed spec digests and the limits, then starts a run. Refused unless
  the review is for the current inputs, was made with the current review prompt, and everything is READY. After a
  harness upgrade CI reviews again (and charges for) every plan not yet activated and every plan stopped with
  `inputs_changed`; an active plan is not reviewed again. `merge: auto` also needs `forge.merge_policy: auto`.
  The plan file is frozen too: an edit of it, or of a unit spec, stops an active plan with `inputs_changed`.
- `l4 yolo status [PLAN] [--json]`: state, units, usage against limits, stop reason, `Next:`.
- `l4 yolo cancel PLAN --reason "…"`: no new dispatch or merge, for good.
- `l4 yolo resume PLAN --reason "…" [--extend-cost|--extend-runs|--extend-attempts|--extend-deadline]`: after the cause of a
  stop is gone (`l4 retry` the unit first for `unit_halted` / `unit_escalated`; `unit_missing` clears when the unit
  folder is back). `inputs_changed` and `unit_rejected` need `review` and `activate` again. Usage is never reset: a
  restart is a new attempt and its cost is added. A `waiting` plan continues by itself when the cause is gone.
- `l4 yolo report PLAN`: the report. Promotion of the base branch to `main` is always manual.

While a plan is active, `l4 run --unit U` exits 13 for a unit that is not the current one. A unit in a plan file on the
base branch stays held (`held by plan <id> (<status>)`), a cancelled plan included, until it is removed from the file.

## From an IDE (`l4 mcp`)

When the repository's MCP server is configured (`l4 mcp install --client <name> --repo <path>`), the same operations
are tools: `l4_status` (a unit's cause and next step), `l4_unit_events` (`type: task.attempt_failed` shows why attempts
failed), `l4_verification`, `l4_questions` / `l4_question` / `l4_question_answer`, `l4_retry`, `l4_plan_check`
(`worktree: true` before the push), `l4_plan_review`, `l4_plan_findings`, `l4_plan_status`, `l4_plan_resume`. They run the
CLI commands as an agent, so an agent still cannot answer a verdict question unless `clarifier.answer_by_agents` allows
it. With several repositories, every tool takes `repo` (folder name or path). Activating or cancelling a plan is not a
tool: a person runs `l4 yolo activate <plan> --reason "…"`.
