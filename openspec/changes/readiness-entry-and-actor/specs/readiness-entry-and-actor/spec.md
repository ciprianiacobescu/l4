## Purpose

A judge reads each unit's id before its prerequisites, and a review made with the old order is made again before an
activation; the plan ledger and the unit ledger say whether a person or an agent took a person-level action; doctor
says what a judge chain of one costs; and an `l4` older than the repository's pin does not write for it by accident.

## ADDED Requirements

### Requirement: L4-YOLO-101 The plan entry shows each id before its prerequisites
The `plan entry` data block of the readiness material (a unit subject, a batch subject and every part of a batch) SHALL
show every object of the entry with its keys in this order: `id` when present, then `depends_on` when present, then
every other key in sorted order, at every level (each unit of a batch the same); lists keep their order. The order
MUST be the harness's own rule, not the models' declared order. The rest of the prompt (templates, notes, data blocks,
the order of the sections) MUST NOT change. The readiness prompt version SHALL be 5. A review recorded with prompt
version 4 SHALL then be stale wherever L4-YOLO-004 decides currency: before the activation (`new`, `admitted`,
`reviewed`, `refused`) and for a plan stopped with `inputs_changed` or `unit_rejected`, `l4 yolo status` SHALL show
`review: stale (the review prompt changed)` with the line `review prompt 4 at the review, 5 in this harness: every
subject is judged again`, `l4 yolo activate` SHALL be refused with that line and `Fix: l4 yolo review <plan>`, and the
next review SHALL judge every subject again. An acceptance bound to a version-4 entry SHALL no longer hold (L4-YOLO-027),
the rounds counted for `yolo.review.accept_after_rounds` SHALL stay as they were, and a force acceptance that holds
SHALL still hold (L4-YOLO-060). An active or waiting plan MUST NOT be stopped, reviewed again or shown as stale because
of the version: its checks read the plan and unit digests frozen at the activation, and its status shows the review as
it was made.

#### Scenario: SCN-YOLO-283 (+) A batch entry shows each unit's id before its list
- **Given** batch `b1` with units `openspec:a`, `openspec:b` (depends on `openspec:a`) and `openspec:c` (depends on
  `openspec:b`, `acceptance_profile: none`)
- **When** the review builds the batch subject and the unit subject of `openspec:b`
- **Then** each `plan entry` block reads `id`, `depends_on`, `acceptance_profile` (and `units` last for the batch) for
  every object, the list `["openspec:a"]` comes after `"id": "openspec:b"` and before `"id": "openspec:c"`, and
  `plan.reviewed` records `prompt_version: 5`

#### Scenario: SCN-YOLO-284 (+) Only the entry changed
- **Given** the unit and the batch under the bound of SCN-YOLO-276
- **When** their prompts are built
- **Then** each prompt, with its `plan entry` block rendered back with sorted keys, is byte for byte the prompt of 0.4.58
  that SCN-YOLO-276 pins; a part of a batch shows the same entry order

#### Scenario: SCN-YOLO-285 (−) A review of 0.4.59 before the activation is judged again
- **Given** plan `p1` reviewed with prompt version 4, units A and B READY and `batch:b1` NEEDS_REVISION with an
  acceptance recorded on that review after two judged versions, and the plan not activated
- **When** `l4 yolo status p1` and `l4 yolo activate p1 --reason go` run, and then the CI plan step
- **Then** the status shows `review: stale (the review prompt changed)` and the version line; the activation exits 2
  with the line and `Fix: l4 yolo review p1` and records nothing; the plan step judges A, B and the batch (no entry is
  reused) and records `prompt_version: 5`; the acceptance no longer holds and the status says so; and a new
  `l4 yolo accept p1 batch:b1` is not refused for rounds

#### Scenario: SCN-YOLO-286 (+) A force acceptance holds across the upgrade
- **Given** plan `p1` force-accepted by a person on a version-4 review, its plan file and unit digests unchanged
- **When** `l4 yolo activate p1 --reason go` runs
- **Then** the plan is activated with no new review, as before the upgrade

#### Scenario: SCN-YOLO-287 (+) An active plan is neither stopped nor reviewed again
- **Given** plan `p1` activated on a version-4 review, its plan file and unit digests unchanged
- **When** the CI plan step runs and `l4 yolo status p1` runs
- **Then** no `plan.reviewed`, `plan.stopped` or `plan.review_incomplete` is recorded, the plan stays `active`, and the
  status shows no `(the review prompt changed)`; after a spec change of a pending unit the plan stops with
  `inputs_changed` as before, and its next review judges every subject at version 5

#### Scenario: SCN-YOLO-288 (−) Kept answers and cached answers of 0.4.59 are not reused
- **Given** plan `p1` whose latest event is a `plan.review_incomplete` of version 4 that answered A, and a dry-run cache
  whose lines are of version 4
- **When** the CI plan step reviews it, `l4 yolo status p1` runs, and `l4 yolo review p1 --worktree` runs
- **Then** A is judged again, no judge is ordered by the old failures, the status shows no `incomplete` line, and the
  dry run reuses no cached line

### Requirement: L4-YOLO-102 Plan events say who acted and with which harness
`l4 yolo activate`, `l4 yolo resume` (with or without an `--extend-…`) and `l4 yolo cancel` SHALL record, in
`plan.activated`, `plan.resumed` and `plan.cancelled`, `actor` and `marker` as `l4.actor.actor` gives them (the rule of
L4-YOLO-031) and `harness_version` (the running `l4`'s version). The harness's own `plan.resumed{by: harness}` is
unchanged. The plan fold SHALL keep `activated_actor` and `activated_marker` beside `activated_by`. `l4 yolo status`
SHALL show `activated by <by> (<kind>)`, where `<kind>` is `person`, `agent: <marker>`, or `agent: no terminal` for an
agent with no marker, and, for the latest person's `plan.resumed` after the latest activation that records `actor`,
`resumed by <by> (<kind>)`; `--json` SHALL carry `activated_actor`, `activated_marker` and `resumed` (`{by, actor,
marker, at}`). The plan report SHALL show `- Activated by: <by> (<kind>)` and, for a cancelled plan,
`- Cancelled by: <by> (<kind>)`. An event without `actor` MUST fold as before and SHALL be shown without a kind, never
as a person's. No command SHALL be refused because of the actor by this requirement.

#### Scenario: SCN-YOLO-289 (+) A person's activation records and shows the kind
- **Given** a reviewed plan `p1` and a person in a terminal with no agent marker
- **When** `l4 yolo activate p1 --reason go --no-run` runs, then `l4 yolo status p1`, `l4 yolo status p1 --json` and
  the plan report are read
- **Then** `plan.activated` holds `by`, `actor: person`, `marker: null` and `harness_version`; the status shows
  `activated by <by> (person)`, the JSON has `activated_actor: person`, and the report has `- Activated by: <by>
  (person)`

#### Scenario: SCN-YOLO-290 (+) An agent's activation says so, and is not refused
- **Given** the plan of SCN-YOLO-289, once with `CLAUDECODE=1` and once with no marker and no terminal on stdin
- **When** `l4 yolo activate p1 --reason go --no-run` runs
- **Then** it activates both times; the events hold `actor: agent` with `marker: CLAUDECODE` and with `marker: null`;
  the status shows `(agent: CLAUDECODE)` and `(agent: no terminal)`

#### Scenario: SCN-YOLO-291 (+) A resume and a cancel record the kind
- **Given** an active plan `p1` that the plan step stopped, and a person in a terminal
- **When** `l4 yolo resume p1 --reason r --no-run` runs, then `l4 yolo status p1`, and later `l4 yolo cancel p1
  --reason r` and the report
- **Then** `plan.resumed` holds `actor: person`, `marker: null` and `harness_version` with no `--extend-…`; the status
  shows `resumed by <by> (person)`; `plan.cancelled` holds `actor` and `marker`; the report shows `- Cancelled by: <by>
  (person)`

#### Scenario: SCN-YOLO-292 (−) An older ledger folds and shows no kind
- **Given** a ledger whose `plan.activated` and `plan.resumed` have no `actor`
- **When** the plan is folded and `l4 yolo status p1` runs
- **Then** the fold is the one of 0.4.59 plus `activated_actor: null`, the status shows `activated by <by>` with no
  kind and no `resumed by` line, and the JSON has `activated_actor: null`

### Requirement: L4-YOLO-103 Doctor warns about a judge chain with no fallback
`l4 doctor` SHALL have the check CFG-013 (warn, every configuration scope). It SHALL fail as a warning when
`roles.judges` names exactly one profile (counted once), with `roles.judges has one profile (<name>): unit
verification has no fallback judge when it fails`, followed, when `roles.plan_judges` is empty, by `, and a judge for
plan readiness reviews only belongs in roles.plan_judges, which unit verification never reads: do not cut roles.judges
for a review`; and when `roles.plan_judges` names exactly one profile, with `roles.plan_judges has one profile
(<name>): the plan review has no fallback judge (it does not fall back to roles.judges)`; both texts joined by `; `.
Its fix SHALL name a second judge profile in the chain named and `roles.plan_judges` for a review-only judge. It SHALL
pass with two or more judges in each chain that is set, and skip when `roles.judges` is empty (CFG-002). It MUST NOT
change doctor's exit code.

#### Scenario: SCN-YOLO-293 (−) One judge warns and says where a review-only judge goes
- **Given** `roles.judges: [j1]` and no `roles.plan_judges`, and a configuration that passes every other check
- **When** `l4 doctor` runs
- **Then** CFG-013 is a warning with both sentences of `roles.judges`, and doctor exits 0

#### Scenario: SCN-YOLO-294 (+) A second judge, or the review's own chain, changes what it says
- **Given** in turn `roles.judges: [j1]` with `roles.plan_judges: [j2, j3]`, `roles.judges: [j1, j2]` with no
  `roles.plan_judges`, and `roles.judges: [j1, j2]` with `roles.plan_judges: [j3]`
- **When** `l4 doctor` runs
- **Then** the first warns with the `roles.judges` sentence only, the second passes with `roles.judges has 2
  profiles`, and the third warns with the `roles.plan_judges` sentence only

### Requirement: L4-YOLO-104 Documentation of the entry order, the actor and the older CLI
The runbook SHALL say, in its procedure to review a plan (12.2), that a chain of one judge has no fallback, that a
judge for reviews only goes in `roles.plan_judges` and not in place of `roles.judges`, and that `l4 doctor` (CFG-013)
warns; and, in its section on preparing a computer (5), that a person command that writes is refused from an `l4`
older than the pin, how to install the pinned one, and `--allow-older-cli`. The skill's `references/plan.md` SHALL say
the same about judges where it tells what to do when no judge can run, and `references/adopt.md` SHALL say it where it
shows role chains and, in its upgrade section, that the local `l4` must be moved with the pin. The CHANGELOG SHALL have
the entries under Unreleased, with the upgrade cost of prompt version 5.

#### Scenario: SCN-YOLO-295 (+) The documentation names the chain, the doctor row and the older CLI
- **When** the runbook, the skill's `references/plan.md` and `references/adopt.md`, and the CHANGELOG are read
- **Then** the runbook names CFG-013, `roles.plan_judges` beside `roles.judges` and `--allow-older-cli`; `plan.md` and
  `adopt.md` name CFG-013 and `roles.plan_judges`; `adopt.md`'s upgrade section says to move the local `l4` too; the
  CHANGELOG's Unreleased section names prompt version 5, CFG-013, `--allow-older-cli` and the actor of `plan.activated`

### Requirement: L4-OPS-025 Unit commands say who acted
`l4 retry`, `l4 resume` and `l4 restart` SHALL record `actor` and `marker` (`l4.actor.actor`, stdin's terminal) in the
`unit.retried`, `unit.resumed` and `unit.restarted` they write, beside `reason`, `by` and `signal`. The sweep's labels
(`by: member`) and a spec-edit push (`by: push`) MUST NOT record them. The unit fold SHALL ignore both fields, and a
ledger without them SHALL fold as before.

#### Scenario: SCN-OPS-54 (+) A person's and an agent's retry record their kind
- **Given** a halted unit, once with a person in a terminal and once with `CLAUDECODE=1`
- **When** `l4 retry --unit <id> --reason r --no-run` runs, and the same for `l4 resume` and `l4 restart`
- **Then** each event holds `actor: person, marker: null`, then `actor: agent, marker: CLAUDECODE`, and the unit's
  phase after it is the one 0.4.59 gives

#### Scenario: SCN-OPS-55 (−) A label and a spec edit record no actor
- **Given** a halted unit with the `l4:retry` label, and another whose folder a person changed after the stop
- **When** the sweep and the next run take them
- **Then** `unit.retried{by: member}` and `unit.retried{by: push}` hold no `actor` and no `marker`

### Requirement: L4-OPS-026 An older l4 does not write for a newer pin
Outside a CI job, a command that records an event or pushes a commit SHALL compare the running `l4`'s version with the
version the repository pins, before it reads or writes anything else, with no fetch and no network. The pin SHALL be
read from `refs/remotes/origin/<forge.base_branch>` when that ref exists (the base branch as last fetched), else from
the working tree: for `harness.delivery` `vendored` or `fetched`, `harness.version` of `.l4/config.yaml`; for
`action`, the `# vX.Y.Z` comment of the `uses:` line of `.github/workflows/l4.yml` that names the setup action at a
40-hex sha; the configuration read without the schema. A copy of the action, a comment that is not a version, an absent
or unreadable file, and a version that does not parse SHALL give no pin, and then nothing SHALL be said. When the
running `l4` is older than the pin, these commands MUST exit 2 with `<command>: this l4 is <v>, older than the harness
this repository pins (<p>, <source>): it would apply the rules of <v> to the repository's units and plans` and a
`Fix:` line that names the pinned install (`.l4/bin/l4` when the repository has it) and `--allow-older-cli`: `run`
(not `--dry-run`), `verify`, `archive`, `resume`, `retry`, `restart`, `plan --sweep`, `questions accept` and `answer`
(not `--no-push`), `yolo review --local`, `yolo review --worktree --record`, `yolo accept`, `yolo waive`,
`yolo activate`, `yolo resume` and `yolo go`. With `--allow-older-cli`, a common option of every command, they SHALL
run and print the warning `warning: this l4 is <v>, older than the harness this repository pins (<p>, <source>)` and
the install line to stderr. A stop or a withdrawal (`yolo cancel`, `yolo accept --withdraw`, `yolo waive --withdraw`)
and a command that writes only a local file (`questions accept|answer --no-push`, `feedback add`, `feedback submit`,
`feedback withdraw`, `yolo draft`, `lessons promote`) MUST NOT be refused and SHALL print the warning. Every other
command, an `l4` of the pinned version or newer, and every command in a CI job SHALL behave as before. The warning MUST
go to stderr, so a `--json` output stays one document.

#### Scenario: SCN-OPS-56 (−) An older l4 is refused before it reads anything
- **Given** a vendored repository whose `.l4/config.yaml` at `origin/main` has `harness.version: 0.4.62`, an `l4` of
  0.4.60 run by a person outside CI, and no `.l4/bin/l4`
- **When** `l4 retry --unit <id> --reason r` runs
- **Then** it exits 2 with `retry: this l4 is 0.4.60, older than the harness this repository pins (0.4.62,
  harness.version at origin/main)` and a `Fix:` line naming `--allow-older-cli`; no ref is fetched and no event is
  written

#### Scenario: SCN-OPS-57 (+) --allow-older-cli runs it with a warning
- **Given** the repository of SCN-OPS-56
- **When** `l4 retry --unit <id> --reason r --no-run --allow-older-cli` runs
- **Then** the retry is recorded as without the guard, the warning is on stderr, and `run.started` records
  `harness_version: 0.4.60`

#### Scenario: SCN-OPS-58 (+) The action pin is read from the comment of its uses: line
- **Given** an action adoption whose workflow has `uses: <owner>/<repo>/.github/actions/l4@<40 hex> # v0.4.62`, in turn
  the same line with `# main`, with no comment, and a copy of the action (`uses: ./.github/actions/l4`)
- **When** `l4 yolo activate p1 --reason go` runs with an `l4` of 0.4.60
- **Then** the first is refused and its fix names `uv tool install --force
  git+https://github.com/<owner>/<repo>@v0.4.62`; the other three give no pin and the command runs as before

#### Scenario: SCN-OPS-59 (+) The pinned version, a newer l4 and a CI job are unchanged
- **Given** a pin of 0.4.60, then a pin of 0.4.59, with an `l4` of 0.4.60; and a pin of 0.4.62 in a job with
  `GITHUB_ACTIONS=true`
- **When** `l4 retry --unit <id> --reason r --no-run` runs
- **Then** no warning and no refusal comes from this rule in any of the three

#### Scenario: SCN-OPS-60 (+) A stop and a local write only warn; a read says nothing
- **Given** the repository of SCN-OPS-56
- **When** `l4 yolo cancel p1 --reason r`, `l4 yolo accept p1 A --withdraw --reason r`, `l4 feedback add …`,
  `l4 status`, `l4 yolo status p1`, `l4 doctor` and `l4 upgrade --dry-run` run
- **Then** the first three run and print the warning to stderr, and the last four print nothing from this rule

#### Scenario: SCN-OPS-61 (−) The base as last fetched wins over a stale working tree
- **Given** a working tree whose `.l4/config.yaml` has `harness.version: 0.4.59` and a
  `refs/remotes/origin/main` whose `.l4/config.yaml` has `0.4.62`, with an `l4` of 0.4.60; and then the same working
  tree with no `refs/remotes/origin/main`
- **When** `l4 yolo resume p1 --reason r` runs
- **Then** the first is refused, naming `harness.version at origin/main`; the second reads the working tree and runs

#### Scenario: SCN-OPS-62 (+) A JSON output stays one document
- **Given** the repository of SCN-OPS-56
- **When** `l4 yolo go p1 --reason r --json --allow-older-cli` runs
- **Then** stdout holds exactly one JSON document and the warning is on stderr
