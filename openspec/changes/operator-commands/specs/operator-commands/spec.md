## Purpose

A person gets every stuck unit moving with one L4 command or one label: `retry` to continue, `restart` to start over.
The cause of every stop is recorded and shown. No git or forge work by hand is needed.

## ADDED Requirements

### Requirement: L4-OPS-001 `l4 retry` continues a stopped unit by its phase
`l4 retry --unit U --reason TEXT [--rounds N] [--no-run]` SHALL act on the unit's recorded phase as design D2 says:
- **`halted`:** back to `previous_phase`, with new task attempts.
- **`escalated`:** back to `verifying`. At the fix-round limit it first adds N fix rounds (default 1), and at the
  feedback limit it adds N feedback rounds.
- **`waiting_capacity`:** back to `previous_phase` now.
- **`in_review`:** to `verifying`.
- **`merged` with a recorded archive or done-gate failure:** that failure is cleared, and the next sweep tries again.

Every other phase, and an unstarted unit, MUST be refused with exit 2 and a message that names what moves the unit.

A retry MUST:
- record `unit.retried{reason, by, signal}`;
- commit `chore(<name>): retry [skip ci]` and push it;
- run no agent, gate or sandbox.

`l4 resume` SHALL remain as `retry` restricted to `halted` and `escalated`, with its existing flags and refusals.

#### Scenario: SCN-OPS-01 (+) An escalated unit at the fix-round limit needs no flag
- **GIVEN** a unit escalated with `fix rounds used 3/3`
- **WHEN** `l4 retry --unit U --reason "spec corrected" --no-run` runs
- **THEN** `budget.extended{fix_rounds: 1}` and `unit.retried` are recorded, the unit is `verifying`, and the push is `chore(<name>): retry [skip ci]`

#### Scenario: SCN-OPS-02 (+) A unit that waits for capacity from `fixing` continues
- **GIVEN** a unit in `waiting_capacity` with `previous_phase` `fixing` and no `retry_after`
- **WHEN** `l4 retry` runs
- **THEN** the unit is `fixing`, and `l4 plan` says `implement`

#### Scenario: SCN-OPS-03 (−) A unit that waits for an answer is refused
- **GIVEN** a unit in `awaiting_human` with open question Q-002
- **WHEN** `l4 retry` runs
- **THEN** it exits 2 with `retry: U is awaiting_human: answer Q-002 in questions.md on l4/<fw>/<name>, then push`, and records nothing

### Requirement: L4-OPS-002 A retry starts a run of the harness
After its push, `l4 retry` SHALL start the harness's CI on the base branch:
- on GitHub with a `workflow_dispatch` of `l4.yml`, where an already waiting run counts as started;
- on GitLab with `POST /projects/:id/pipeline`.

When the forge refuses or cannot start a run, the command MUST print the exact command or page that starts one, and
exit 0. `--no-run` skips the start. A label never starts a run: the sweep that reads it is already in a run.

#### Scenario: SCN-OPS-04 (+) The retry starts the workflow on GitHub
- **GIVEN** a halted unit on GitHub and a forge token that may dispatch workflows
- **WHEN** `l4 retry --unit U --reason TEXT` runs
- **THEN** a `workflow_dispatch` run of `l4.yml` on the base branch starts, and the output says `run started on <base>`

#### Scenario: SCN-OPS-05 (−) A refused start still exits 0 and says how
- **GIVEN** a token that may push but not start pipelines
- **WHEN** `l4 retry` runs
- **THEN** the retry is pushed, the output names the command that starts a run, and the exit code is 0

### Requirement: L4-OPS-003 A person's spec change after a stop is taken by the retry
When a person changed the unit folder of a `halted` or `escalated` unit after the stop, the retry SHALL send the unit
to `implementing` with the trigger `spec_edit_since_stop`. The changes count only when they are commits on the
first-parent chain after the stop commit, not made by the harness, and outside `.l4/`, `verification.md` and the index
of `questions.md`. The spec and tasks are then read from the unit branch.

#### Scenario: SCN-OPS-06 (+) A reworded requirement reaches an escalated unit
- **GIVEN** an escalated Kiro unit, and a person's commit to `requirements.md` on its branch after the escalation
- **WHEN** `l4 retry` runs
- **THEN** the unit is `implementing` (`spec_edit_since_stop`), and the next verification judges the reworded requirement

#### Scenario: SCN-OPS-07 (−) A change outside the unit folder does not count
- **GIVEN** a halted unit, and a person's commit after the halt that changes only `src/`
- **WHEN** `l4 retry` runs
- **THEN** the unit goes back to `previous_phase`, not to `implementing`

### Requirement: L4-OPS-004 `l4 restart` starts a unit over and keeps the old work
`l4 restart --unit U --reason TEXT [--no-run]` SHALL do the seven steps of design D4, in order:
1. refuse an unstarted, `merged` or locked unit, or a run with no forge token;
2. keep the old branch head as `refs/l4/attempts/<fw>/<name>/<n>`, and the lock ref as `…/<n>-locks`;
3. build the unit folder from the old branch, without `.l4/`, `verification.md` and fix-unit folders, and with the
   task boxes as the base branch has them;
4. create a new branch from the base head with `chore(<name>): restart, attempt <n> [skip ci]`, which holds the folder
   and `unit.restarted{attempt, previous_head, reason, by, signal}`;
5. push it with a lease on the old head;
6. close the old merge request with a comment that names the attempts ref;
7. start a run (L4-OPS-002).

A failed lease MUST leave the branch, the merge request and the refs as they were. The fold MUST read
`unit.restarted` as a new start.

#### Scenario: SCN-OPS-08 (+) A poisoned unit starts over with the corrected spec
- **GIVEN** an escalated unit whose branch has a person's correction to `requirements.md`
- **WHEN** `l4 restart --unit U --reason "start over" --no-run` runs
- **THEN** `refs/l4/attempts/<fw>/<name>/1` holds the old head, the merge request is closed, and the new branch has the corrected `requirements.md`, the base's task boxes, no `.l4/evidence`, and a ledger with `unit.restarted`
- **AND** `l4 plan` says `implement`

#### Scenario: SCN-OPS-09 (−) A person's push during the restart wins
- **GIVEN** a person pushes to the unit branch after the restart read its head
- **WHEN** the restart pushes the new branch
- **THEN** the lease fails, the restart exits 1 with `the branch moved: run l4 restart again`, and the merge request stays open

### Requirement: L4-OPS-005 Every stop records its cause
Each `phase.changed` into `halted` or `escalated` SHALL carry:
- `reason`: one of the codes of design D5;
- `detail`: the text a person reads.

The fold MUST keep both. The note headline, `exit_reason` and the log line `[l4] run: <unit> <phase>: <detail>` MUST
use `detail`. An escalation at the fix-round limit MUST say `fix rounds used <n>/<m>`, and no other cause may say "no
fix round is left".

#### Scenario: SCN-OPS-10 (+) A non-convertible finding is named
- **GIVEN** a FAIL round whose only finding cannot become a fix task, with fix rounds left
- **WHEN** the unit escalates
- **THEN** `phase.changed` has `reason: no_convertible_finding` and its `detail`, and the note headline is `### Escalated: <detail>`

### Requirement: L4-OPS-006 `l4 status` and `l4 plan` show the cause and the next command
The `l4 status` table SHALL have a `REASON` column after `PHASE`, cut to 60 characters. It holds `detail` for `halted`
and `escalated`, the open question ids for `awaiting_human`, `until <time>` for `waiting_capacity`, and `-` otherwise.

`l4 status --unit U` SHALL print the phase, the full cause, the run id of the stop, and `Next: <command>`. `--json`
SHALL carry `reason` and `next`. `l4 plan` SHALL use the recorded `detail` for `halted` and `escalated`.

#### Scenario: SCN-OPS-11 (+) The halt cause is in the table
- **GIVEN** a unit halted by `max_task_attempts`
- **WHEN** `l4 status` runs
- **THEN** its row has `halted` and `task 1.1: max_task_attempts (3) reached in red; …` (cut), and `l4 status --unit U` ends with `Next: l4 retry --unit U --reason TEXT`

### Requirement: L4-OPS-007 A repeated failure escalates at once
After a FAIL round, the fix loop SHALL compare the round's failure with the previous round's. The failure is the sorted
set of failed gate names, the failing test ids of a failed test gate, and the exit code of a gate with no report.

If the set is not empty, equals the previous round's, and no person's commit came between the rounds, the unit MUST
escalate with `same_failure` and `round <n> failed the same way as round <n-1>: …`. Judge findings are not part of the
set.

#### Scenario: SCN-OPS-12 (+) The same crashed test twice stops the loop
- **GIVEN** round 1 failed with the test gate's `INTERNALERROR` and no report, and a fix round ran
- **WHEN** round 2 fails with the same gate and exit code
- **THEN** the unit is `escalated` with `same_failure` after round 2, and no fix unit 2 is written

#### Scenario: SCN-OPS-13 (−) A different failure gets its fix round
- **GIVEN** round 1 failed on test A and round 2 fails on test B
- **WHEN** round 2 ends
- **THEN** a fix unit is written as before

### Requirement: L4-OPS-008 Labels `retry`, `restart` and `resume`
The sweep SHALL honour `<prefix>retry` and `<prefix>resume` as `l4 retry`, and `<prefix>restart` as `l4 restart`. It
uses the member rule of `l4:resume`, and each label event acts once. `restart` MAY be on the closed merge request of an
`abandoned` unit.

Each run that ensures its phase labels SHALL also ensure the three operator labels. A refused label MUST name the
command that works. For the token owner, that is `l4 retry --unit <unit> --reason TEXT`.

#### Scenario: SCN-OPS-14 (+) A member's restart label starts the unit over
- **GIVEN** an escalated unit with an open merge request, and a member adds `l4:restart`
- **WHEN** the next run's sweep reads it
- **THEN** the restart of L4-OPS-004 runs, and the same run's `l4 run` implements the unit again

### Requirement: L4-OPS-009 No stop is a dead end
- **A secret in the outgoing commits** SHALL halt the unit with the halt recorded. The run discards its unpushed
  commits, then records and pushes the ledger alone. `verifying` and `verified` gain the halted edge.
- **`waiting_capacity`** SHALL always record `retry_after`: now plus `availability.default_cooldown` when the cause
  gives none. It SHALL continue from every parked phase, `fixing` included.
- **A merge request closed without a merge** SHALL make the unit `abandoned` (`pr.closed`, trigger `pr_closed`), with
  a note that names `l4 restart`. A merge request reopened before a restart returns the unit to its phase.
- **A deleted unit branch** SHALL name `l4 restart` in its message.
- **A verdict question with Status `dismissed`** SHALL read as `open`, with a note and a plan reason that say a verdict
  question cannot be dismissed.

#### Scenario: SCN-OPS-15 (+) A secret halt can be retried
- **GIVEN** a run whose outgoing commits contain a secret
- **WHEN** the run ends
- **THEN** the remote branch has no new code commit, its ledger shows `halted` with `secret_in_push`, and `l4 retry` after the person's correction is accepted

#### Scenario: SCN-OPS-16 (+) A closed merge request is not a dead end
- **GIVEN** an `in_review` unit whose merge request a person closed without a merge
- **WHEN** the next sweep runs
- **THEN** the unit is `abandoned`, and `l4 restart` on it is accepted

### Requirement: L4-OPS-010 `l4 run --unit` on a stopped unit changes nothing
On a `halted` or `escalated` unit, `l4 run --unit U` SHALL exit 13 before the lease. It prints the cause and
`Next: l4 retry --unit U --reason TEXT`, and writes no ledger, no commit, no push and no label.

#### Scenario: SCN-OPS-17 (−) The resume label survives a manual run
- **GIVEN** a halted unit whose merge request carries `l4:resume`
- **WHEN** `l4 run --unit U` runs with a forge token
- **THEN** it exits 13, the branch head is unchanged, and the label is still on the merge request

### Requirement: L4-OPS-011 Local commands find the project from `origin`
When `GITHUB_REPOSITORY` is not set, the GitHub target SHALL be the `owner/name` of a github.com `origin`. When
`forge.gitlab.api_url` and `forge.gitlab.project` are not set, the GitLab target SHALL be `https://<host>/api/v4` and
the `origin` path without `.git`. Configured values win.

#### Scenario: SCN-OPS-18 (+) A laptop retry needs no project setting
- **GIVEN** a clone whose `origin` is `git@github.com:o/n.git`, a token, and no `GITHUB_REPOSITORY`
- **WHEN** `l4 retry` runs
- **THEN** it acts on `o/n` and does not exit 2

### Requirement: L4-OPS-012 The fixer runs what the verifier runs
The test gate of a fix unit's green step SHALL run with the verifier's coverage plugin. Its output goes to the step's
private folder, and only the gate's pass or fail is used.

#### Scenario: SCN-OPS-19 (+) A failure under coverage reaches the fixer
- **GIVEN** a fix task whose test passes without coverage and fails under the coverage plugin
- **WHEN** its green step runs
- **THEN** the gate fails in that step, and the attempt's retry prompt carries the gate log

### Requirement: L4-OPS-013 Documented and validated live
`docs/runbook.md` SHALL give one command and one label for each stuck situation, and its section 11 SHALL drop the
limits that this change removes.

Each requirement SHALL be proven on GitHub, with run ids and evidence under `docs/live/operator-commands/`:
- a halted unit retried by command, with a started run;
- an escalated unit retried by label;
- a restart by command, and a restart by label;
- a closed merge request made `abandoned`, then restarted;
- the `REASON` column in a CI `l4 status` step.

The GitLab pipeline start SHALL be proven by a recorded API exchange or a live call.

### Requirement: L4-OPS-014 A spec push to the unit branch re-enters the unit by itself
A person's commit on the unit branch, after the harness's last commit, that changes the unit folder outside `.l4/`,
`verification.md`, `questions.md`, `feedback.md` and fix-unit folders SHALL send the unit to `implementing` at the next
run. It applies from `intake`, `ready`, `implemented`, `verifying`, `verified`, `awaiting_human`, `clarifying`, `halted`
and `escalated`, with the trigger `spec_edited`, and the run records `unit.retried{reason: "spec edited", signal:
"spec_edit:<sha>"}`.
- **`in_review`** keeps `spec_edit_after_handoff`.
- **`fixing`** takes the edit after its fix unit ends.
- **A unit escalated at a limit** gets one round of that kind, once per head.
- **A push with no unit-folder change** keeps today's behaviour.
- The triggers of the CI workflow MUST NOT change.

#### Scenario: SCN-OPS-20 (+) A spec push to an escalated unit starts it again
- **GIVEN** a unit escalated with `fix rounds used 3/3`, and a person's push that edits `proposal.md` on its branch
- **WHEN** the next run starts
- **THEN** `budget.extended{fix_rounds: 1}` and `unit.retried{reason: "spec edited"}` are recorded, the unit is `implementing`, and no `l4 retry` was needed

#### Scenario: SCN-OPS-21 (+) A spec push to a verified unit is verified again before the hand-off
- **GIVEN** a `verified` unit, and a person's push that rewords a requirement before the hand-off
- **WHEN** the next run starts
- **THEN** the unit goes to `implementing`, then `verifying`, and it is not handed off on the old verdict

#### Scenario: SCN-OPS-22 (−) Answers are not a spec edit
- **GIVEN** a unit in `awaiting_human`, and a person's push that changes only `questions.md`
- **WHEN** the next run starts
- **THEN** the answers path decides as today, and no `spec_edited` edge is taken

### Requirement: L4-OPS-015 A changed Kiro requirement reopens its tasks
On a Kiro unit, when a spec edit (L4-OPS-014) changes acceptance criteria in `requirements.md`, the tasks that cite them
in `_Requirements:_` SHALL be set back to `[ ]` with their parents. This happens in a harness commit
`chore(<name>): reopen tasks <keys> for changed requirements <ids> [skip ci]`, with `tasks.reopened{tasks,
requirements}`, and the tasks then run test-first.
- Text is compared after whitespace normalisation.
- Added and removed criteria count as changed.
- An OpenSpec unit reopens nothing: its changed scenarios are judged by the verifier.

#### Scenario: SCN-OPS-23 (+) A reworded criterion is implemented again
- **GIVEN** a Kiro unit whose task 2.1 cites `_Requirements: 2.3_`, and a person's push that rewords criterion 2.3
- **WHEN** the next run starts
- **THEN** task 2.1 is `[ ]` again in a `chore(...): reopen tasks 2.1 for changed requirements 2.3 [skip ci]` commit, and it runs red then green

#### Scenario: SCN-OPS-24 (−) A re-wrapped line changes nothing
- **GIVEN** a person's push that only re-wraps the text of criterion 2.3
- **WHEN** the next run starts
- **THEN** no task is reopened (the unit still re-enters, by L4-OPS-014)

### Requirement: L4-OPS-016 The GitLab job uses the configured base branch and prefix
The GitLab job SHALL use `forge.base_branch` and `forge.branch_prefix`, rendered at `l4 init` and `l4 upgrade`, in the
`L4-Run:` exemption, the merge trigger, the unit-branch rule and the base checkout. It MUST NOT use the project's
default branch, and an unsafe name is refused with exit 2.

#### Scenario: SCN-OPS-26 (+) A base branch that is not the default branch works on GitLab
- **GIVEN** `forge.base_branch: l4/main` and a GitLab project whose default branch is `main`
- **WHEN** the job is rendered
- **THEN** its rules compare with `"l4/main"` and its base checkout detaches to `origin/l4/main`
