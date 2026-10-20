## Purpose

One command brings a delivery plan from a committed file to an active plan: it runs preflight, push, check, review,
findings, accept and activate in order over the existing commands and their rules, continues from where the plan is,
and stops at the first step that cannot pass.

## ADDED Requirements

### Requirement: L4-YOLO-080 One command runs the plan's steps in order
`l4 yolo go PLAN --reason TEXT [--accept-findings | --force] [--yes] [--json] [--no-push] [--local] [--wait DURATION]`
SHALL run the steps preflight, push, check, review, findings, accept and activate in that order. Before each step it
SHALL read whether the step already holds and SHALL NOT repeat a step that holds. Every write it causes MUST be made by
the existing command that makes it today (`l4 yolo review --local`, `l4 yolo accept`, `l4 yolo activate`) with that
command's rules, event and lease; it MUST NOT record an event of its own. `--reason` SHALL be the reason of every
acceptance and of the activation it causes. These usage errors MUST exit 2 before anything is read or fetched: a plan
id that is not one, an empty `--reason` or one over 1,000 characters, `--accept-findings` with `--force`, `--force`
with `--local`, and a `--wait` that is neither `0` nor a duration.

#### Scenario: SCN-YOLO-200 (+) A person goes from a committed plan to an active plan in one command
- **GIVEN** plan `p1` (A and B in batch `b1`) committed on the local base branch and not pushed, a forge that starts a
  run when asked, and a CI that records a review with every subject READY while `go` waits
- **WHEN** a person runs `l4 yolo go p1 --reason "ship it"`
- **THEN** the base branch is pushed, the plan is admitted at `origin/main`, the review recorded by CI is read,
  `plan.activated{reason: "ship it"}` is recorded by `l4 yolo activate`, the steps print `preflight: ok`, `push: done`,
  `check: ok`, `review: done`, `findings: ok`, `accept: skipped`, `activate: done`, the last line is
  `Next: l4 yolo status p1`, and it exits 0

#### Scenario: SCN-YOLO-201 (−) The flags are checked before anything is read
- **GIVEN** any repository
- **WHEN** `l4 yolo go p1 --reason R --accept-findings --force`, `l4 yolo go p1 --reason R --force --local`,
  `l4 yolo go p1 --reason " "`, `l4 yolo go p1 --reason <1001 characters>` and `l4 yolo go p1 --reason R --wait soon`
  run
- **THEN** each exits 2 naming the problem, nothing is fetched (`_sync` is not called) and the plan ref does not move

### Requirement: L4-YOLO-081 Preflight checks the working tree as the skill's script does
The preflight step SHALL run, with no network and before anything is fetched, the checks of the skill's
`scripts/yolo_preflight.py`: no tracked file differs from HEAD (`dirty`), the plan file exists in the working tree
(`plan_missing`; when `origin/<base>` has it the fix is `git pull --ff-only origin <base>`) and is JSON
(`plan_not_json`), the plan file is not untracked (`plan_uncommitted`), and no file under the folder of a
unit the plan lists is untracked (`unit_uncommitted`). An untracked file elsewhere MUST NOT stop it. The checks SHALL
have one implementation in the harness (`l4.yolo.preflight`); the script MUST NOT be changed to call the harness, and a
test SHALL keep the two in agreement. A problem, a repository with no `origin`, or a base branch that is not on
`origin` SHALL stop the run with exit 20, every problem, and the first one's fix as the next command.

#### Scenario: SCN-YOLO-202 (−) A tree with an uncommitted change stops at preflight
- **GIVEN** plan `p1` committed and a tracked file of the checkout changed and not committed
- **WHEN** `l4 yolo go p1 --reason R` runs
- **THEN** it exits 20 with `dirty` and `Next: git status`, nothing is fetched or pushed, and the plan ref does not move

#### Scenario: SCN-YOLO-203 (−) An untracked file in a unit folder stops it, one elsewhere does not
- **GIVEN** plan `p1` committed, and an untracked file `openspec/changes/add-b/notes.md`
- **WHEN** `l4 yolo go p1 --reason R` runs
- **THEN** it exits 20 with `unit_uncommitted` naming the folder; with the file moved to `scratch/notes.md` (outside
  every unit folder) preflight is `ok`

#### Scenario: SCN-YOLO-204 (+) The harness preflight and the skill script agree
- **GIVEN** fixture repositories: clean, and one for each problem code
- **WHEN** `l4.yolo.preflight.problems` and `python3 <skill dir>/scripts/yolo_preflight.py` run in each
- **THEN** both pass in the clean one and both fail in each other one, with the same codes where the script prints
  codes

### Requirement: L4-YOLO-082 The push is a fast-forward of the base branch and never a surprise
When HEAD is ahead of `origin/<base>`, the push step SHALL push the branch `<base>` to `origin` without `--force` or
`--force-with-lease`, after the working-tree admission of `l4 yolo check PLAN --worktree` passed, and fetch it again.
It MUST NOT push and SHALL stop with exit 21 and the command that clears the cause when: HEAD and `origin/<base>` have
diverged (`git pull --rebase origin <base>`); HEAD is not the branch `<base>` (`git switch <base>`); a plan on
`origin` that is active or waiting (this one, or another) has its plan file or one of its unit folders changed by a
commit ahead, a rename counting at its old and its new path, which would stop it with `inputs_changed` (`l4 yolo status
PLAN`); `--no-push` is given (`git push origin <base>`); git refuses the push (its
reason: the repository's own `pre-push` hooks run, so a hook that fails refuses the push). A working-tree admission finding (`uncovered` among them) MUST stop it with exit 22 before the push. For an
agent caller, a commit ahead that touches any path (a rename's old path too) other than `.l4/plans/PLAN.json` and the folders of the plan's units
MUST make the push a person's step (exit 27, `next_by` person), with `--no-push` too (the `l4_plan_go` tool always has it): `--no-push` gives an agent `git push origin <base>` as its own command (exit 21) only when the commits ahead hold nothing but the plan file and its unit folders. With nothing ahead the step SHALL be `ok` and push nothing.

#### Scenario: SCN-YOLO-205 (+) Commits ahead on the base branch are pushed as a fast-forward
- **GIVEN** two local commits on `main` ahead of `origin/main` that add plan `p1`
- **WHEN** a person runs `l4 yolo go p1 --reason R`
- **THEN** `origin/main` equals HEAD, no push used `--force`, the step prints `push: done: pushed 2 commit(s) to
  origin/main`, and the forge is not asked for a run (the push starts one)

#### Scenario: SCN-YOLO-206 (−) --no-push stops with the push command
- **GIVEN** a local commit ahead of `origin/main`
- **WHEN** `l4 yolo go p1 --reason R --no-push` runs
- **THEN** it exits 21 with `Next: git push origin main` and `origin/main` does not move; with nothing ahead,
  `--no-push` changes nothing and the run goes on

#### Scenario: SCN-YOLO-207 (−) A diverged base branch is never forced
- **GIVEN** a local commit ahead of `origin/main` and another commit pushed to `origin/main` by someone else
- **WHEN** `l4 yolo go p1 --reason R` runs
- **THEN** it exits 21 with `HEAD and origin/main have diverged` and `Next: git pull --rebase origin main`, and
  `origin/main` keeps the other commit

#### Scenario: SCN-YOLO-208 (−) Only the base branch is pushed
- **GIVEN** a checkout on branch `feature` with a commit ahead of `origin/main`
- **WHEN** `l4 yolo go p1 --reason R` runs
- **THEN** it exits 21 naming `feature` and `Next: git switch main`, and nothing is pushed

#### Scenario: SCN-YOLO-209 (−) A plan the working-tree admission refuses is not pushed
- **GIVEN** a local commit that adds plan `p1` and a new spec folder that no plan lists
- **WHEN** `l4 yolo go p1 --reason R` runs
- **THEN** it exits 22 with the `uncovered` finding and `Next: l4 yolo check p1 --worktree`, and nothing is pushed

#### Scenario: SCN-YOLO-210 (−) An agent's push outside the hand-off is a person's
- **GIVEN** an agent (`CLAUDECODE=1`) and a local commit ahead that changes `.l4/config.yaml`
- **WHEN** the agent runs `l4 yolo go p1 --reason R`
- **THEN** it exits 27, the push step is `person`, the text says `Next: a person runs: git push origin main`, and
  nothing is pushed; the same with `--no-push` (as the MCP tool runs it) exits 27 with `next_by` person, not 21 with `next_by` caller, and with only the hand-off ahead `--no-push` exits 21 with `next_by` caller

#### Scenario: SCN-YOLO-211 (+) An agent pushes the plan file and its unit folders
- **GIVEN** an agent and a local commit ahead that adds `.l4/plans/p1.json` and the folder of a unit `p1` lists
- **WHEN** the agent runs `l4 yolo go p1 --reason R`
- **THEN** the push step is `done` and `origin/main` equals HEAD

#### Scenario: SCN-YOLO-212 (−) A push that would stop the active plan is not made
- **GIVEN** plan `p1` active, and a local commit ahead that changes the specification file of one of its units
- **WHEN** `l4 yolo go p1 --reason R` runs
- **THEN** it exits 21 with `pushing this stops the active plan p1 with inputs_changed` and `Next: l4 yolo status p1`,
  and nothing is pushed

### Requirement: L4-YOLO-083 The check step admits the plan at the target and reads its state
The check step SHALL read the plan's ledger and admit the plan file at `origin/<base>` as `l4 yolo check PLAN` does. An
active or waiting plan SHALL end the run with exit 0 and its state, before admission, with nothing written; a
completed plan likewise, with `l4 yolo report PLAN` as the next command. A cancelled plan, a plan stopped for a reason
other than `inputs_changed` or `unit_rejected`, and a plan stopped with `unit_rejected` whose rejected unit's spec has
not changed MUST stop the run with exit 23, the status's own next step in the detail and `l4 yolo status PLAN` as the
next command. A missing plan file, a file that is not a plan and every admission finding MUST stop the run with exit 22,
each finding, and `l4 yolo check PLAN --worktree` as the next command.

#### Scenario: SCN-YOLO-213 (−) A plan that is not admitted at the target stops at check
- **GIVEN** plan `p1` pushed with a dependency cycle between A and B
- **WHEN** `l4 yolo go p1 --reason R` runs
- **THEN** it exits 22 with a `cycle:` line and `Next: l4 yolo check p1 --worktree`, and nothing is recorded

#### Scenario: SCN-YOLO-214 (+) An active plan is reported as active
- **GIVEN** plan `p1` active since an activation by `alex@example.com`
- **WHEN** `l4 yolo go p1 --reason R` runs twice
- **THEN** each run exits 0, check is `ok`, review, findings and accept are `skipped`, activate is `ok` with
  `active since`, the next command is `l4 yolo status p1`, and the plan ref does not move; for a completed plan the next
  command is `l4 yolo report p1`

#### Scenario: SCN-YOLO-215 (−) A cancelled plan and a plan stopped for a limit stop at check
- **GIVEN** plan `p1` cancelled, and in a second world plan `p1` stopped with `limit_runs`
- **WHEN** `l4 yolo go p1 --reason R` runs in each
- **THEN** each exits 23 with `Next: l4 yolo status p1`; the stopped plan's detail names `l4 yolo resume p1`; nothing
  is recorded

### Requirement: L4-YOLO-084 The review is reused when current, else made in CI with a bounded wait or here
The review step SHALL reuse a review at the current plan and unit digests and prompt version, with no dispatch and no
judge, and SHALL be skipped when a force acceptance holds for every subject and no review is current (a current review
is said to be there, with a note that its problems stop at findings when they do). Otherwise, with `--local` it SHALL review
here as `l4 yolo review PLAN --local` does; with `--force` it MUST NOT review or ask for a review. Else CI reviews it:
when this run pushed the base branch, the push starts the run; otherwise `go` SHALL ask the forge to start one, and when
the forge cannot, it MUST stop at once with exit 24 and the command that starts a run by hand. It SHALL then poll the
plan ledger at most every 15 seconds until the review at the current digests is recorded, a refusal newer than the ask
is recorded (exit 22) or `--wait` (default 30m; `0`: no wait) ends (exit 24, `pending`, the go command as the next
command). A judge that cannot run with `--local` MUST stop the run with exit 25 and the go command without `--local`.

#### Scenario: SCN-YOLO-216 (+) A current review is reused
- **GIVEN** plan `p1` pushed and reviewed at the current digests with every subject READY
- **WHEN** `l4 yolo go p1 --reason R` runs with a judge factory and a forge that fail the test when used
- **THEN** the review step is `ok` with the review's time, no judge is built, the forge is not asked, and the run goes
  on to the activation

#### Scenario: SCN-YOLO-217 (+) CI is asked and awaited
- **GIVEN** plan `p1` pushed and never reviewed, nothing ahead, a forge whose `start_run` answers `started`, and a CI
  that records a review at the current digests during the second poll
- **WHEN** `l4 yolo go p1 --reason R` runs
- **THEN** the forge is asked once, the ledger is read until the review is there, the review step is `done`
  (`reviewed in CI`), and the run goes on

#### Scenario: SCN-YOLO-218 (−) The wait is bounded
- **GIVEN** plan `p1` never reviewed and a CI that records nothing
- **WHEN** `l4 yolo go p1 --reason R --wait 1m` runs with a clock that advances 15 s per poll
- **THEN** it exits 24 after at most five polls, the review step is `pending`, the next command is
  `l4 yolo go p1 --reason R --wait 1m`, and nothing is recorded; with `--wait 0` it asks the forge and exits 24 at once

#### Scenario: SCN-YOLO-219 (−) No run can be asked and nothing was pushed
- **GIVEN** plan `p1` never reviewed, nothing ahead, and a forge whose `start_run` answers `unsupported`
- **WHEN** `l4 yolo go p1 --reason R` runs
- **THEN** it exits 24 at once, without polling, with the command that starts the harness's CI by hand as the next
  command

#### Scenario: SCN-YOLO-220 (+) --local reviews here, and a judge that cannot run stops it
- **GIVEN** plan `p1` pushed and never reviewed, and a local judge that answers READY for every subject
- **WHEN** `l4 yolo go p1 --reason R --local` runs
- **THEN** `plan.reviewed{source: local}` is recorded by `l4 yolo review --local` and the run goes on; with a judge that
  raises `RoleUnavailable` it exits 25 with `Next: l4 yolo go p1 --reason R` and nothing is recorded

#### Scenario: SCN-YOLO-221 (−) A refusal recorded by CI during the wait stops it
- **GIVEN** plan `p1` never reviewed and a CI that records `plan.refused` with an `open_questions` finding during the
  wait
- **WHEN** `l4 yolo go p1 --reason R` runs
- **THEN** it exits 22 with the finding and `Next: l4 yolo check p1 --worktree`

### Requirement: L4-YOLO-085 Findings stop the run unless they are accepted by the accept rules
A subject that is not READY, has no acceptance that holds and is not cleared by a force acceptance SHALL stop the run at
the findings step with exit 26, one line per such subject (its verdict and most severe finding), and as the next
command the go command with `--accept-findings` when this caller may accept every such subject, else
`l4 yolo findings PLAN`. With `--accept-findings`, `go` SHALL accept each such subject by running `l4 yolo accept`
for it with the reason and the caller's `--yes`, so that every rule of L4-YOLO-027 and L4-YOLO-063 applies; when one
subject cannot be accepted by this caller it MUST record nothing and stop (exit 27 when only a person may accept them,
else exit 26 with each refusal). An agent without `--yes` MUST stop with exit 29. With `--force` a person's run SHALL
force-accept the plan by running `l4 yolo accept PLAN --all --force` (L4-YOLO-057), and an agent's run MUST stop with
exit 27 before anything is read. A person who does not type the plan id MUST stop the run with exit 29.

#### Scenario: SCN-YOLO-222 (−) A subject that is not READY stops at findings
- **GIVEN** plan `p1` reviewed at the current digests with B NEEDS_REVISION (judged on two versions) and A READY
- **WHEN** a person runs `l4 yolo go p1 --reason R`
- **THEN** it exits 26, the findings step names B, its verdict and its most severe finding, the next command is
  `l4 yolo go p1 --reason R --accept-findings`, and nothing is recorded; when B is BLOCKED the next command is
  `l4 yolo findings p1` and the detail names `--force` as a person's way when no model can judge it

#### Scenario: SCN-YOLO-223 (+) --accept-findings accepts each subject by the accept rules and activates
- **GIVEN** plan `p1` reviewed with A and B NEEDS_REVISION, each judged not READY on two versions
- **WHEN** a person runs `l4 yolo go p1 --reason "keep the thresholds" --accept-findings` and types `p1` at each
  prompt
- **THEN** two `plan.accepted{actor: person, reason: "keep the thresholds", confirmed: typed}` are recorded by
  `l4 yolo accept`, each prompt was shown after that subject's findings, `plan.activated` lists both acceptances, and
  it exits 0; with `--yes` nothing prompts and the events record `confirmed: --yes`

#### Scenario: SCN-YOLO-224 (−) One subject that cannot be accepted means nothing is accepted
- **GIVEN** plan `p1` reviewed with A NEEDS_REVISION on two versions and B BLOCKED
- **WHEN** a person runs `l4 yolo go p1 --reason R --accept-findings --yes`
- **THEN** it exits 26 naming B's refusal (`BLOCKED`), no `plan.accepted` is recorded and nothing is activated

#### Scenario: SCN-YOLO-225 (+) --force accepts without a review and activates
- **GIVEN** plan `p1` pushed and never reviewed, and a judge factory and a forge that fail the test when used
- **WHEN** a person runs `l4 yolo go p1 --reason "the judge is down" --force` and types `p1`
- **THEN** the review step is `skipped`, `plan.admitted` and `plan.force_accepted` are recorded by
  `l4 yolo accept --all --force`, `plan.activated{review: force_accepted}` follows, no judge is built, the forge is
  asked for nothing but the activation's run, and it exits 0

#### Scenario: SCN-YOLO-226 (−) --force from an agent stops before anything
- **GIVEN** an agent (`CLAUDECODE=1`)
- **WHEN** it runs `l4 yolo go p1 --reason R --force`
- **THEN** it exits 27 before anything is fetched, the accept step is `person`, and the text says
  `Next: a person runs: l4 yolo go p1 --reason R --force`

### Requirement: L4-YOLO-086 Activation is a person's step
When every subject is READY, accepted with an acceptance that holds, or cleared by a force acceptance, a person's run
SHALL activate the plan by running `l4 yolo activate PLAN --reason TEXT`, with that command's rules, output and run
start, after the person has typed the plan id (`Type the plan id (PLAN) to activate PLAN`, a prompt on stderr, on a
terminal only; `--yes` skips it; a wrong answer or no terminal without `--yes` MUST stop with exit 29 and the go command,
recording nothing). An agent's run MUST NOT activate: it SHALL check the refusals of the activation
that remain after the review (the target on `origin`, no other plan active, waiting or stopped on the target); a
refusal MUST stop it with exit 28 and that refusal, otherwise it SHALL stop with exit 27 and
`a person runs: l4 yolo go PLAN --reason TEXT`. When the refusal is another plan holding the target, the next command
SHALL be `l4 yolo cancel OTHER --reason TEXT`, which for an agent is printed as a person's step (`a person runs:`,
cancelling a plan is a person's decision). Nothing is recorded by an agent's stop.

#### Scenario: SCN-YOLO-227 (+) An agent stops at the activation with the person's command
- **GIVEN** an agent (`CLAUDECODE=1`) and plan `p1` reviewed at the current digests with every subject READY
- **WHEN** the agent runs `l4 yolo go p1 --reason "ship it"`
- **THEN** it exits 27, the activate step is `person` with `activation is a person's decision`, the text ends with
  `Next: a person runs: l4 yolo go p1 --reason 'ship it'`, and no `plan.activated` is recorded

#### Scenario: SCN-YOLO-228 (−) An agent is told the activation would be refused
- **GIVEN** an agent, plan `p1` READY, and plan `p2` active on the same target
- **WHEN** the agent runs `l4 yolo go p1 --reason R`
- **THEN** it exits 28 with `plan p2 is already active, waiting or stopped on main`, not 27, and the text ends with
  `Next: a person runs: l4 yolo cancel p2 --reason TEXT (stop here: cancelling a plan is a person's decision)`; a
  person's run refused the same way ends with `Next: l4 yolo cancel p2 --reason TEXT`

#### Scenario: SCN-YOLO-229 (+) A person types the plan id, then the run activates with the reason
- **GIVEN** a person and plan `p1` reviewed with B accepted by a holding acceptance and A READY
- **WHEN** the person runs `l4 yolo go p1 --reason "ship it"` and types `p1` at `Type the plan id (p1) to activate p1`
- **THEN** `plan.activated{reason: "ship it"}` is recorded with B's acceptance (the event holds no confirmation field),
  the output lists `accepted: openspec:add-b by …`, the accept step is `ok` (`1 acceptance(s) hold`), and it exits 0;
  a wrong answer exits 29 with `Next: l4 yolo go p1 --reason 'ship it'` and records nothing; with `--yes` nothing is asked;
  with no terminal and no `--yes` it exits 29 before activating
