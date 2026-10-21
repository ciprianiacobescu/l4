# Operating L4: state, questions, retry and restart

## Delivering a plan: the runbook

**Origin is what counts.** CI and the harness read `origin/<base>`, never your working tree: commit and push before
`l4 yolo review --record`, `l4 yolo accept` or `l4 yolo activate`. Run `python3 <skill dir>/scripts/yolo_preflight.py
<plan>` first; it checks this and prints the one next command.

**A person's steps.** Activating a plan and `l4 yolo accept … --all --force` are a person's decisions. An agent never
runs them and never guesses another way: it stops and gives the person the exact command, with a `--reason` to fill in.

**One command.** Steps 3 to 9 are also one command. A person: after step 2, or simply: l4 yolo go <plan> --reason "<why>"
(it pushes the base branch as a fast-forward, reviews in CI, stops at findings with the one command to accept them, and
activates). An agent: `l4 yolo go <plan> --reason "<why>" --json --wait 9m` (9 minutes fit under a 10-minute tool limit;
exit 24 means run `next_command`, then `l4 yolo go` again later: `next_command` is the command that starts a run when CI could not be asked). Read `exit`, `next_command` and `next_by` of the JSON. When `next_by` is `person` (exit 27, or exit 28 with
another plan active: activation, a push outside your hand-off, cancelling the other plan) stop and give the person that
command: as an agent never run a person's command, never unset the agent markers (`CLAUDECODE`, `AI_AGENT`, ...) and
never fake a terminal to get past a check, never `--force`, never your own `--yes` except for the acceptance of step 8.

1. Draft: `l4 yolo draft <plan>` (`--update` for a new spec); order the units by `references/plan.md`.
2. Validate: `l4 yolo check <plan> --worktree` (without the harness: `python3 <skill dir>/scripts/validate_plan.py`)
   and `openspec validate <change> --strict`. Optional: `l4 yolo review <plan> --worktree`, a dry run, to fix specs
   before the push.
3. Commit and push the plan file and the spec folders to `<base>` in one commit (`references/plan.md`, Hand off).
4. Check: `python3 <skill dir>/scripts/yolo_preflight.py <plan>`. It runs `l4 yolo check <plan>` on origin.
5. Review: `l4 yolo review <plan> --worktree --record` (a local judge records the review of what origin holds), or
   `l4 yolo review <plan>` (CI reviews it at its next run).
6. Findings: `l4 yolo findings <plan>`. Every subject READY or accepted: go to 9.
7. Fix the specs as the `Resolve:` lines say, commit, push, and go to 5. This is one round.
8. After two rounds on a subject, accept what this stack cannot fix: `l4 yolo accept <plan> <subject> --reason
   "<what the implementer should do>"`. Only a person runs it, or an agent when `yolo.review.accept_by_agents` is true at
   `origin/<base>`; otherwise stop and give the person that command. A BLOCKED subject or a blocking finding cannot be
   accepted: stop and give the person `l4 yolo findings <plan> <subject>`. When no judge can run, the person may
   force-accept the whole plan (`l4 yolo accept <plan> --all --force --reason "…"`).
9. A person activates: stop and give the person `l4 yolo activate <plan> --reason "<why>"`.
10. Watch: `l4 yolo status <plan>`; do its `Next:` line (`references/control-loop.md`).

Firm limits:
- Take at most two rounds of spec fixes per subject, then step 8, never a third.
- The same criterion back after a fix is the stop of `references/plan.md` ("two rounds repeat the same criterion").
- Never weaken a requirement to pass a review.

| Message | Cause | Fix |
|---|---|---|
| `no plan file .l4/plans/<plan>.json on origin/<base>` | The plan is not pushed. | Its `Fix:` line (push). |
| `<plan>: not admitted, nothing to review` | Admission findings. | `l4 yolo check <plan>`, fix, push. |
| `review: --record records what CI and l4 yolo activate read` | HEAD is not `origin/<base>`. | The `Fix:` line (push or pull), then `l4 yolo review <plan> --worktree --record`. |
| `review: --record: CI reads <unit> on its branch` | The unit's branch holds another spec. | Change it there (runbook 7.14), or `l4 yolo review <plan>`. |
| `review: --record needs the plan file and the unit folders committed` | Uncommitted edits. | Commit and push. |
| `review: --record --fresh …: the ledger already holds the review of this material` | A recorded verdict is not re-rolled. | Accept (step 8) or change the spec. |
| `warning: … CI reviews origin/<base>, not your commits` | Unpushed commits. | Push, then review. |
| `review: no judge could answer, nothing was recorded` | The local judge cannot run. | `l4 yolo review <plan>` (CI), and `l4 doctor`. |
| `<cli> did not answer within N s (<step> step)` | A daemon or a login prompt holds the CLI. | `l4 doctor`. |
| `kiro-cli 3.0.0 is Kiro CLI 3; L4 runs Kiro CLI 2: install kiro-cli 2.32.0 …` | A Kiro CLI 3 on the machine. | In CI `l4 doctor --ci --fix`; on a machine install the pin by the command in the message. |
| `ENV-015: kiro-cli 2.33.0 at <path>, pinned 2.32.0` | A warning: an agent CLI is not at its pin. | The command in the hint; CI: `l4 doctor --ci --fix`. |
| `ci.cli_versions: kiro-cli: 3.0.0 is Kiro CLI 3; this harness runs Kiro CLI 2 …` | The key names another major. | Use a version of the same major, and move the harness pin first. |
| `ci.cli_versions: unknown agent CLI …` or `ci.cli_versions: <key>: is not a version N.N.N` | A bad key or value. | An adapter name and `N.N.N`. |
| `<archive>: sha256 … does not match the harness's digest …` | A Kiro archive failed its check; nothing was installed. | Do not install it by hand (the message says so): report it, or hold another version in `ci.cli_versions` (one the harness holds). |
| `<archive>: sha256 … does not match the published …` | A Node archive failed its check; nothing was installed. | Run the manual command in the message. |
| `cannot download kiro-cli <v> from prod.download.cli.kiro.dev (HTTP 403): that version may no longer be served …` | The CDN does not serve that version. | Hold another version in `ci.cli_versions` (one the harness holds), or report it. |
| `profiles.<name> is in roles.<role>, but its adapter … cannot judge` | A profile that cannot judge is in a judge role. | Remove it from the role, commit, push. |
| `activate: the review of <plan> is stale against origin/<base>` | The lines name what changed. | Push when a `local:` line says so, then `l4 yolo review <plan>`. |
| `activate: <plan> has not been reviewed` | No review yet. | `l4 yolo review <plan>`. |
| `activate: the review is not READY for N item(s)` | Findings are open. | Steps 6 to 8. |
| `activate: <plan> is not admitted` | Admission findings. | `l4 yolo check <plan>`. |
| `activate: plan <other> is already active, waiting or stopped on <target>` | One plan per target. | Wait, or a person cancels it. |
| `accept: acceptance is a person's decision` | An agent without `accept_by_agents`. | Give the person the command it prints. |
| `accept: <subject> was judged not READY on N version(s); 2 are needed` | Fewer than two rounds. | One more round (step 7). |
| `accept: <subject> is BLOCKED` or `has a blocking finding` | Not acceptable. | Fix the spec, or stop and hand it to the person. |
| `accept: no terminal to ask the plan id on` | An agent without `--yes`. | An agent that may accept passes `--yes`; otherwise the person runs it. |
| `accept: --force is a person's decision` | An agent asked for `--force`. | Give the person the command. |
| `waive: a waiver is a person's decision` | An agent without `accept_by_agents`. | Give the person the command it prints. |
| `resume: <unit> is still <phase>` | The cause is still there. | Do the `Next:` line it prints. |
| `open run: … it ended without a record (…)` | The CI killed or cancelled the job (its timeout, a cancel), so the run wrote no end. The unit is where its last push left it. | `Next:` gives the command that starts a run on the base: `gh workflow run l4.yml --ref <base>` (GitLab: the new-pipeline page). Run it. |
| `nothing is running or queued on <base> …: start a run on <base>` | An active plan that the schedule does not move (idle for two periods, or no schedule can: `ci.schedule` null, or the default branch's copy of the workflow is missing or on another pin). | Run the command in `Next:`. For the default branch's copy, copy .github/workflows/l4.yml to the default branch once (or promote the base). |
| `deadline_repeated` | A step was stopped twice at the soft deadline: it does not fit in one job. | Raise `ci.time_budget` (or set it to `auto`) when the reason names it, else `timeout-minutes` and `L4_JOB_TIMEOUT_MINUTES`, or split the task, then `l4 retry --unit FW:NAME --reason "…"`. |
| `ci.time_budget … leaves N min, less than one step (10 min)` | The set budget minus `soft_deadline_margin` leaves less than one step, so no step could run; `l4 run` exits 2 and `l4 doctor` fails `CFG-012`. | Set `ci.time_budget: auto`, commit, push. |
| `ci.time_budget … is shorter than the job's timeout` | The set budget moves the soft deadline earlier than the margin alone would (a warning). | Set `ci.time_budget: auto`, unless the job must stop early. |

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
index row, commits (`[skip ci]`), pushes, and starts a run on the base branch when the forge token is set (otherwise it prints how to start one), which resumes the unit.

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

**A harness question** (`Kind: harness`: a check L4 could not decide; no attempt was used) is answered `accept: <why>` or
`retry: <note>`, and no other word. Read the source of the tests in its Context first: `accept` replays exactly that step.
L4 saved the step's changes as `.l4/held/<task>-<check>.patch` on the unit branch, and the next run applies the patch with
every guard and gate and starts no agent. The question lists every path the patch changes and shows the diff of every one
(a cut says that the cut lines are replayed too; the whole patch is on the unit branch): read it all, because `accept` replays
exactly these changes, and only through that replay. If the replay fails a gate or the check refutes a criterion, the accept is
used up: a later step that meets the same inconclusive check is held again with a new question. A reopened task drops every
earlier accept. A missing, changed or non-applying patch gives a new question that offers only `retry` (an `accept` to it covers nothing), not a pass. The replay commits exactly the saved patch: anything a test or the setup writes
while its gates run is put back.
`retry` deletes the patch and runs an agent step with your note.

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
- A hold `judge view: …` means the judge could not see all of the diff (a file longer than one part, or more than 8
  parts). Never answer it with a `WHEN … THEN …`: no fix unit can shrink a diff. `accept` only after a person checked
  the files it names; otherwise split the change into smaller units. A `reject` escalates the unit with
  `judge_view_rejected`; its way out is in `l4 status --unit` (`l4 restart` after the split, or `--replace` with an
  accept, then `l4 retry`).
- A criterion question whose `Why:` ends `its evidence was split over parts 1 and 2 of the diff: …` (harness 0.4.21 and
  later): the diff was judged in parts and no part saw all of this criterion's files. The text says whether a follow-up
  call judged them together and what it answered, or why none was made. Read the files under `Files by part` in
  `verification.md`, then answer as for any criterion.
- Before rejecting, check that the criterion id in the question is the one you mean (`verification.md` maps ids to
  `Req N.M`).
- The unit moves on only when **every** open verdict question in the file is answered.
- To change a verdict answer on purpose (a person only, unless `clarifier.answer_by_agents` is true):
  `l4 questions answer Q-NNN --unit FW:NAME --text "accept …" --replace`. It works only on an answered verdict question,
  keeps the old answer in a comment under the new one and says `(answer replaced)` in the commit. Without `--replace`
  the command refuses an answered question. A clarification answer is changed by hand (L4-QMD-006).

## Retry or restart a stuck unit

Never check out the unit branch to "restart" it. Run the commands below from a clone on the base branch (docs/control-loop.md).

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

- `l4 yolo go PLAN --reason "…" [--json] [--wait 9m]`: the one command from a committed plan to an active plan (push,
  check, review, findings, accept, activate), safe to run again; a person's run activates, an agent's stops with the
  person's command (`exit` 27, `next_command`). Never give it `--force` as an agent.
- `l4 yolo check PLAN`: admission only (cycles, unknown units, target is the base branch, open questions). Exit 0 or 2. Changes nothing.
- `l4 yolo review PLAN`: CI reviews the plan (READY / NEEDS_REVISION / BLOCKED per unit). `--local` runs it here.
  `--worktree` reviews the working tree before the push (dry, writes nothing); `--record` records a committed tree so CI
  does not review again; `--fresh SUBJECT` judges a subject again.
- `l4 yolo findings PLAN [SUBJECT] [--all] [--json]`: every blocking and major finding with its id and a `Resolve:` line,
  and what changed since the previous judgement. Reads only.
- `l4 yolo accept PLAN SUBJECT --reason "…"`: a person accepts a subject's remaining findings on record (never for
  BLOCKED, a blocking finding or a cut of the unit's folder; agents only if `yolo.review.accept_by_agents` is true on
  the base branch). Not an agent's command by default. Never run its `--all --force` form (accept the whole plan with
  no model review, even with `accept_by_agents`): when the judge cannot run, ask CI (`l4 yolo review PLAN`), then give
  the person `l4 yolo accept <id> --all --force --reason "<what the implementer should know>"`.
- `l4 yolo activate PLAN --reason "…"`: freezes the reviewed spec digests and the limits, then starts a run. Refused unless
  the review is for the current inputs, was made with the current review prompt, and everything is READY; or a
  person's `l4 yolo accept PLAN --all --force` holds for every subject (no review needed, but the findings of a current
  review on a subject it did not override still refuse; an agent never runs the force form). After a
  harness upgrade CI reviews again (and charges for) every plan not yet activated and every plan stopped with
  `inputs_changed`; an active plan is not reviewed again. `merge: auto` also needs `forge.merge_policy: auto`.
  The plan file is frozen too: an edit of it, or of a unit spec, stops an active plan with `inputs_changed`.
- `l4 yolo status [PLAN] [--json]`: state, units, usage against limits, stop reason, `Next:`.
- `l4 yolo cancel PLAN --reason "…"`: no new dispatch or merge, for good.
- `l4 yolo resume PLAN --reason "…" [--extend-cost|--extend-runs|--extend-attempts|--extend-deadline]`: on an active plan
  an `--extend-…` raises the limit (`plan.extended`) and resumes nothing; raising a limit is a person's, so an agent
  prints the command for the person unless `yolo.extend_by_agents` is true on the base branch. After the cause of a
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
`--project` entries find their repository differently per client (Claude Code `CLAUDE_PROJECT_DIR`; VS Code, OpenCode and
Codex the workspace; Cursor `--repo ${workspaceFolder}`); Kiro has no project scope (use `--repo PATH`); a worktree is
served only by a session started inside it, else by a user-scope entry with `--repo`.
