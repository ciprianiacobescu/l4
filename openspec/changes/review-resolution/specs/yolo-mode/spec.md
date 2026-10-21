## Purpose

A person can see every finding of a plan's readiness review with what to do about it, run the same review on the working
tree before pushing, and, when the judge keeps finding more after real attempts to fix, accept a subject's remaining
non-blocking findings on record. The judge is not asked again about material it already judged, a prerequisite's size
no longer blocks its dependents, and the accepted findings reach the implementer and the verifier.

## MODIFIED Requirements

### Requirement: L4-YOLO-004 Readiness review in CI
A CI run SHALL review a plan whose latest `plan.reviewed` is not for its current plan digest and unit digests: the judge
role reviews each unit and each batch with more than one unit, with the prompt and output schema of design D5, and the
result is recorded as `plan.reviewed`. The judge MUST be asked only about subjects whose material has no recorded
verdict (L4-YOLO-022). An empty, unparsable or schema-invalid answer MUST be BLOCKED. A blocking finding MUST make the
verdict at least NEEDS_REVISION. Material that the size limits cut from the subject's own folder MUST make the verdict
at least NEEDS_REVISION, with a finding that names what was left out; a prerequisite's cut MUST NOT (L4-YOLO-024). A
batch with no acceptance profile only groups units and states no outcome, so a `batch_acceptance` finding on it MUST be
dropped from the verdict and kept as an assumption, and its NEEDS_REVISION MUST become READY when no blocking or major
finding remains, and its BLOCKED when no finding is left at all. The judge's material for a batch shows every
prerequisite of its units that is not a unit of the batch, the way the material of a unit shows its prerequisites, and
both state that a prerequisite unit of the plan is delivered and merged into the target before any unit that depends on
it starts. The material also lists, as harness text outside the data blocks, the units already delivered on the target
(the OpenSpec changes archived at the target revision and the units a provider reads as merged or archived, without the
plan's own units, at most 60 names and then a count of the rest) and says that a dependency on one of them is satisfied
and is not a `missing_dependency`; the names reach the prompt only inside `<l4:data>` blocks. The text of every
`tasks.md` in that material MUST show each task marker as the file has it (L4-YOLO-025). File names, unit ids and batch
ids MUST reach the prompt only inside `<l4:data>` blocks. A judge that times out or fails MUST record no review: the next
run tries again (R9). One plan is reviewed per run. Every `plan.reviewed` MUST record the `prompt_version` of the
readiness prompt (an event without the key counts as 1), and a review made with a version other than the current one
MUST count as stale wherever currency is decided (the CI step, `l4 yolo status`, activation).

#### Scenario: SCN-YOLO-08 (−) An unparsable review is BLOCKED
- **GIVEN** a plan with one unit and a judge that answers `ok`
- **WHEN** the CI step reviews it
- **THEN** `plan.reviewed` records the unit as BLOCKED with `schema_invalid`

#### Scenario: SCN-YOLO-09 (−) A blocking finding overrides READY
- **GIVEN** a judge answer `{"verdict": "READY", "findings": [{"criterion": "contradiction", "severity": "blocking", "text": "…"}]}`
- **WHEN** the review is recorded
- **THEN** the unit's verdict is NEEDS_REVISION

### Requirement: L4-YOLO-005 Activation is one person's decision
`l4 yolo activate PLAN --reason TEXT` SHALL record `plan.activated` with the frozen unit digests, the plan digest, the
limits and the acceptances that hold (`accepted`), and then start a run on the target. It MUST be refused, with exit 2
and the cause, unless: the plan is admitted; the latest review is for the current digests; every unit and batch is READY,
or NEEDS_REVISION with an acceptance that holds (L4-YOLO-027); `merge` and `forge.merge_policy` agree; the target exists
on `origin`; no other plan is active on the target. Its output MUST list every accepted subject with who accepted it,
whether a person or an agent, and the reason. Nothing MUST run from a plan before activation. Activation freezes the
plan digest (`activated_digest`) with the unit digests. From then on, `plan.admitted`, `plan.refused` and
`plan.reviewed` change only the review fields, never `activated_digest`, the order or the status, and a plan file whose
digest differs from `activated_digest` MUST stop the plan with `inputs_changed` (R2).

#### Scenario: SCN-YOLO-10 (−) A plan reviewed for older inputs is refused
- **GIVEN** a plan reviewed READY, after which a person changed `spec.md` of one unit
- **WHEN** `l4 yolo activate` runs
- **THEN** it exits 2 with `review is for other inputs: run l4 yolo review <plan>`, and records nothing

#### Scenario: SCN-YOLO-11 (+) Activation freezes the inputs
- **GIVEN** a plan reviewed READY for the current digests
- **WHEN** `l4 yolo activate p1 --reason "go"` runs
- **THEN** `plan.activated{digests, limits, by, reason, accepted: {}}` is on `refs/l4/plans/p1` and a run of the harness is started on the target

#### Scenario: SCN-YOLO-32 (−) An edited plan file stops an active plan
- **GIVEN** an active plan, and a person's push that changes its file `.l4/plans/p1.json` on the target (a unit is added)
- **WHEN** the next CI run happens
- **THEN** `plan.stopped{inputs_changed, subject: plan}` is recorded, `activated_digest` and the order do not change, and nothing is dispatched or merged

## ADDED Requirements

### Requirement: L4-YOLO-021 Every finding is shown with what to do about it
`l4 yolo findings PLAN [SUBJECT] [--all] [--json] [--worktree]` SHALL print, from the latest review, with no model and no write,
each subject that is not READY with every blocking and major finding in full, its id, criterion and a `Resolve:` line,
the count of minor ones, and the change since the subject's previous judged material (new, repeated, gone, persistent
criteria). `l4 yolo status`, `l4 yolo review` and the activation refusal MUST show an item's most severe finding and
name `l4 yolo findings`.
`--worktree` SHALL read the latest dry run of `l4 yolo review --worktree` from the local cache instead of the ledger,
against the previous dry run.

#### Scenario: SCN-YOLO-43 (+) Each major finding comes with how to resolve it
- **GIVEN** a latest review where `openspec:a` is NEEDS_REVISION with a major `testability` finding and a minor `outcome` finding
- **WHEN** `l4 yolo findings p1` runs
- **THEN** it prints `openspec:a: NEEDS_REVISION`, the major finding with an id `F-` and six hex digits, its criterion and full text, `Resolve: Give the scenario concrete inputs and outputs in openspec/changes/a/specs/*/spec.md …`, and `1 minor finding (--all shows it)`; it exits 0 and the plan ref is unchanged

#### Scenario: SCN-YOLO-44 (+) The change since the previous judgement is shown
- **GIVEN** two recorded judgements of `openspec:a` with different material, the first with major findings T (testability) and F (failure_cases), the second with T (same text) and I (interfaces)
- **WHEN** `l4 yolo findings p1 openspec:a` runs
- **THEN** it prints `since the previous judgement: 1 new, 1 repeated, 1 gone` and `persistent: testability ×2`

#### Scenario: SCN-YOLO-45 (−) The line shown is the most severe one
- **GIVEN** `openspec:a` NEEDS_REVISION with the findings, in the judge's order, minor X then major Y
- **WHEN** `l4 yolo status p1` runs
- **THEN** the review line of `openspec:a` names Y, and the output names `l4 yolo findings p1`

#### Scenario: SCN-YOLO-46 (+) A missing dependency names the plan entry to add
- **GIVEN** `openspec:b` NEEDS_REVISION with a major `missing_dependency` finding whose text names `openspec:a`, a unit of the plan that is not in `openspec:b`'s `depends_on`
- **WHEN** `l4 yolo findings p1` runs
- **THEN** the `Resolve:` line says to add `"openspec:a"` to `depends_on` of `openspec:b` in `.l4/plans/p1.json` (batch `b1`)

#### Scenario: SCN-YOLO-71 (+) The results of a dry run are usable in the loop
- **GIVEN** `l4 yolo review p1 --worktree` judged `openspec:b` NEEDS_REVISION with a major `testability` finding, and recorded nothing in the plan ledger
- **WHEN** `l4 yolo findings p1 --worktree` runs, and `l4 yolo findings p1 --worktree --json`
- **THEN** the first prints `openspec:b: NEEDS_REVISION`, the finding and its `Resolve:` line, and after a second dry run with other material the change since the previous dry run; the second prints the `l4/yolo-findings@1` document; neither calls a model, and `l4 yolo review p1 --worktree --json` prints the same document alone on stdout

### Requirement: L4-YOLO-022 Material already judged is not judged again
Each subject SHALL have a material key: a hash of the prompt version, the subject kind, and the exact text the judge
would get, without the list of delivered units. A review MUST reuse, at no cost, the verdict of a recorded
`plan.reviewed` of the plan with the same key and the current prompt version, and record the entry with `material` and
`reused_from`. A verdict with a harness `schema`, `unit_missing` or `completeness` finding MUST NOT be reused.

#### Scenario: SCN-YOLO-47 (+) An unchanged unit is not judged again
- **GIVEN** a recorded review of units `a` and `b` (no dependency between them), then a commit that changes only `b`'s `spec.md`
- **WHEN** the CI step reviews the plan
- **THEN** the judge is called for `b` and for their batch only, `a`'s entry has the same verdict and findings as before and `reused_from` set, and the charged cost covers only the calls made

#### Scenario: SCN-YOLO-48 (−) A changed prerequisite makes its dependents judged again
- **GIVEN** a recorded review of `a` and of `b`, which depends on `a`, then a commit that changes `a`'s `spec.md`
- **WHEN** the CI step reviews the plan
- **THEN** the judge is called for `a` and for `b`

#### Scenario: SCN-YOLO-49 (−) A review that did not happen is not reused
- **GIVEN** a recorded review where `a` is BLOCKED with `schema_invalid`, then a commit that changes only `b`
- **WHEN** the CI step reviews the plan
- **THEN** the judge is called for `a` again

### Requirement: L4-YOLO-023 Verdict rules that a person can satisfy
After the rules of L4-YOLO-004, a NEEDS_REVISION whose findings are all minor SHALL become READY, with the findings kept.
A NEEDS_REVISION with no finding MUST get the harness finding `{criterion: "verdict", severity: "major"}` whose text
gives the judge's `missing` list. A `batch_acceptance` finding on a unit MUST be moved to the assumptions.

#### Scenario: SCN-YOLO-50 (+) Minor findings alone do not block
- **GIVEN** a judge answer `NEEDS_REVISION` with two minor findings
- **WHEN** the review is recorded
- **THEN** the unit is READY and its entry keeps both findings

#### Scenario: SCN-YOLO-51 (−) A NEEDS_REVISION without a finding gets one
- **GIVEN** a judge answer `{"verdict": "NEEDS_REVISION", "findings": [], "missing": ["the API of x"]}`
- **WHEN** the review is recorded
- **THEN** the unit is NEEDS_REVISION with one finding of criterion `verdict`, severity `major`, whose text contains `the API of x`

#### Scenario: SCN-YOLO-52 (+) Batch acceptance is not a unit's finding
- **GIVEN** a judge answer on unit `a`: `NEEDS_REVISION` with one major `batch_acceptance` finding and one minor finding
- **WHEN** the review is recorded
- **THEN** `a` is READY and the `batch_acceptance` text is in its assumptions

### Requirement: L4-YOLO-024 Review material within budgets, and a cut that says what to do
The budgets SHALL be `yolo.review.max_file_chars`, `max_folder_chars` and `max_dependency_chars` (20,000, 80,000,
20,000). A prerequisite folder MUST show proposal, requirements, `specs/**/spec.md`, bugfix, design, other files,
then `tasks.md`. A prerequisite's cut MUST NOT change the verdict and MUST be listed in `missing` with the shown and
total sizes and the budget. A cut of the subject's folder MUST give `material_cut` with the file, its size, the
budget, the configuration key and the fix.

#### Scenario: SCN-YOLO-53 (+) A prerequisite's task list is cut without blocking
- **GIVEN** unit `b` that depends on `a`, `a`'s folder with `proposal.md` of 3,000, `specs/x/spec.md` of 9,000 and `tasks.md` of 12,000 characters, the default budgets, and a judge that answers READY for `b`
- **WHEN** the plan is reviewed
- **THEN** `b`'s material holds `a`'s proposal and spec in full and the first 8,000 characters of its `tasks.md`, `b` is READY, and its `missing` holds `not shown in full: "openspec:a": openspec/changes/a/tasks.md (8000 of 12000 characters shown; dependency budget 20000)`

#### Scenario: SCN-YOLO-54 (−) The subject's own cut blocks and says how to fix it
- **GIVEN** unit `a` whose `design.md` has 26,000 characters, the default budgets, and a judge that answers READY
- **WHEN** the plan is reviewed
- **THEN** `a` is NEEDS_REVISION with a blocking `material` finding whose text says `design.md has 26000 characters`, `20000 per file`, `yolo.review.max_file_chars` and `Shorten the file`

#### Scenario: SCN-YOLO-55 (+) A raised budget shows the whole file
- **GIVEN** the unit of SCN-YOLO-54 and `yolo.review.max_file_chars: 30000`
- **WHEN** the plan is reviewed
- **THEN** `a`'s material holds the whole `design.md` and `a` has no `material` finding

### Requirement: L4-YOLO-025 The judge sees the check marks as they are
The review material SHALL show every `tasks.md` as the file has it, and say that a ticked task is delivered on the
revision shown, that the harness does not implement it again, and that the judge reviews the open tasks without a
`feasibility` or `duplicate_scope` finding only because work is done. The unit digest is unchanged (L4-YOLO-003). The
readiness prompt version MUST be 4.

#### Scenario: SCN-YOLO-56 (+) Ticked tasks reach the judge ticked, and the digest ignores them
- **GIVEN** a `tasks.md` with `- [x] 1.1 Add the parser` and `- [ ] 1.2 Add the command`
- **WHEN** the review material and the unit digest are made
- **THEN** the material holds `- [x] 1.1 Add the parser` and the note on ticked tasks, the event records `prompt_version: 4`, and the digest equals the digest of the same folder with `- [ ] 1.1 Add the parser`

### Requirement: L4-YOLO-026 A review of the working tree before the push
`l4 yolo review PLAN --worktree` SHALL review the working tree's plan file and unit folders with the same prompt,
rules and material keys, print the digests it reviewed, the verdicts, the findings (L4-YOLO-021) and the cost (`--json`:
the findings document of `l4 yolo findings --json`), write nothing to the plan ref, and exit 0 when every subject is READY or accepted, else 2. `--record` MUST record it like
`--local`, for committed paths only. Outside CI with no usable bwrap, the judge MUST run unsandboxed only when its
adapter is tool-less, and say so.

#### Scenario: SCN-YOLO-57 (+) A dry run reads the uncommitted edit and writes nothing
- **GIVEN** an uncommitted edit of `openspec/changes/a/specs/x/spec.md`
- **WHEN** `l4 yolo review p1 --worktree` runs
- **THEN** the judge's material holds the edited text, the output names the plan digest, each unit's digest, each verdict and the cost, `refs/l4/plans/p1`, `HEAD`, the index and the branch are unchanged, and the exit is 0 when every subject is READY, else 2

#### Scenario: SCN-YOLO-58 (+) A recorded review of the commit spares the CI review
- **GIVEN** a committed, unpushed edit, and `l4 yolo review p1 --worktree --record` that recorded every subject READY
- **WHEN** the commit is pushed and the CI step runs
- **THEN** the CI step calls no judge and records no `plan.reviewed`, and `l4 yolo activate p1 --reason "go"` succeeds

#### Scenario: SCN-YOLO-59 (−) A review of uncommitted text is not recorded
- **GIVEN** an uncommitted edit of a unit folder of the plan
- **WHEN** `l4 yolo review p1 --worktree --record` runs
- **THEN** it exits 2 with `review: --record needs the plan file and the unit folders committed:` and the path, and calls no judge

#### Scenario: SCN-YOLO-60 (+) Without bwrap a tool-less judge runs and says so
- **GIVEN** no `bwrap` on `PATH`, no CI variables, and a judge profile with the adapter `claude-code`
- **WHEN** `l4 yolo review p1 --worktree` runs
- **THEN** the judge runs without a sandbox and the output says `judge unsandboxed (bwrap was not found on PATH): it has no tools and runs in an empty folder`

#### Scenario: SCN-YOLO-61 (−) A judge with a shell is refused without a sandbox
- **GIVEN** no `bwrap` on `PATH` and a judge profile with the adapter `codex`
- **WHEN** `l4 yolo review p1 --worktree` runs, and when the same review runs with `CI=true`
- **THEN** both exit 3 before any judge call, the first naming a `claude-code` or `opencode` judge profile, the second as today

### Requirement: L4-YOLO-027 A person can accept a subject's remaining findings on record
`l4 yolo accept PLAN SUBJECT --reason TEXT` SHALL record `plan.accepted` of the subject's latest verdict (key,
findings, hash, reason, `by`, `actor`) after the person types the plan id. It MUST be refused for
BLOCKED, a blocking finding, the subject's `material_cut`, fewer than `yolo.review.accept_after_rounds` (2)
versions of its text not READY, an active plan and an agent unless `yolo.review.accept_by_agents` is true at
`origin/<base>`. It holds while the latest entry keeps the key and hash.

#### Scenario: SCN-YOLO-62 (+) A person accepts a unit after two attempts
- **GIVEN** `openspec:a` judged NEEDS_REVISION on two versions of its text (two unit digests), the latest with two major findings, and a terminal
- **WHEN** `l4 yolo accept p1 openspec:a --reason "keep the thresholds; test with a 3x tolerance"` runs and the person types `p1`
- **THEN** `plan.accepted{subject: openspec:a, material, findings_sha, findings, reason, by, actor: person, rounds: 2}` is recorded, and `l4 yolo activate p1 --reason "go"` succeeds, lists the acceptance and records it in `plan.activated{accepted}`

#### Scenario: SCN-YOLO-63 (−) One judgement is not enough
- **GIVEN** `openspec:a` NEEDS_REVISION on one version of its text only, judged twice (before and after a change of its prerequisite)
- **WHEN** `l4 yolo accept p1 openspec:a --reason "x"` runs
- **THEN** it exits 2 with `accept: openspec:a was judged not READY on 1 version; 2 are needed (yolo.review.accept_after_rounds)` and records nothing

#### Scenario: SCN-YOLO-64 (−) BLOCKED, a blocking finding and a cut of the subject cannot be accepted
- **GIVEN** three subjects after two rounds: one BLOCKED, one NEEDS_REVISION with a blocking finding, one with a `material_cut` of its own folder
- **WHEN** `l4 yolo accept` runs for each
- **THEN** each exits 2, names the reason and the fix (`fix the spec`, `fix the spec`, `shorten the file or raise yolo.review.max_file_chars`), and nothing is recorded

#### Scenario: SCN-YOLO-65 (−) An agent cannot accept unless the target's configuration allows it
- **GIVEN** `CLAUDECODE=1`, no terminal, `openspec:a` acceptable after two rounds, and no `yolo.review.accept_by_agents` in `.l4/config.yaml` at `origin/main`
- **WHEN** `l4 yolo accept p1 openspec:a --reason "x" --yes` runs
- **THEN** it exits 2 with `accept: acceptance is a person's decision` and the command for the person, and records nothing
- **WHEN** `yolo.review.accept_by_agents: true` is pushed to `origin/main` and the command runs again
- **THEN** `plan.accepted{actor: agent, marker: CLAUDECODE}` is recorded and `l4 yolo activate` lists it as `(accepted by an agent)`

#### Scenario: SCN-YOLO-66 (−) A change of the material voids the acceptance
- **GIVEN** an acceptance of `openspec:a`, then a pushed edit of `a`'s spec and a review that judges `a` NEEDS_REVISION again
- **WHEN** `l4 yolo activate p1 --reason "go"` runs
- **THEN** it exits 2 with the not-READY line of `openspec:a` and `the acceptance by <by> was for other material`

### Requirement: L4-YOLO-028 Accepted findings travel with the unit
The run of a plan unit with an acceptance SHALL write `.l4/review-accepted.json` in the unit folder. The implementer's
prompt MUST hold the accepted findings and the reason. The verifier's judge MUST get them and answer `accepted: [{id,
addressed, evidence}]`, a missing answer being false, recorded as `review.accepted_judged`. With `merge: auto` a unit
whose accepted finding has no `addressed: true` answer in its PASS round MUST NOT be merged: the plan waits with
`accepted_finding_open`.

#### Scenario: SCN-YOLO-67 (+) The implementer is told what was accepted
- **GIVEN** an active plan whose unit `openspec:a` was accepted with two findings and the reason R
- **WHEN** the plan dispatches `openspec:a`
- **THEN** `openspec/changes/a/.l4/review-accepted.json` is committed on the unit branch, the unit digest does not change, and the red prompt holds the block `accepted review findings` with both finding ids and texts and R

#### Scenario: SCN-YOLO-68 (+) The verifier answers each accepted finding
- **GIVEN** the unit of SCN-YOLO-67 in a verification round
- **WHEN** the judge's prompt is built and its reply has one of the two ids with `addressed: true`
- **THEN** the prompt holds `<l4:data kind="accepted">` with both ids, and the ledger holds `review.accepted_judged` with `addressed: true` for one id and `addressed: false, evidence: "not answered"` for the other

#### Scenario: SCN-YOLO-69 (−) `merge: auto` does not merge an unaddressed accepted finding
- **GIVEN** an active `merge: auto` plan whose current unit is `in_review` with a PASS and two accepted findings, one answered `addressed: false` and one with no answer recorded (as for a unit adopted in review)
- **WHEN** the CI step runs
- **THEN** nothing is pushed to the target and `plan.waiting{reason: accepted_finding_open, unit, detail}` names both ids, the evidence of the first and `no answer recorded` for the second; after a person merges the PR, the next step integrates the unit

### Requirement: L4-YOLO-029 Documentation of the resolution path
The runbook SHALL have a procedure for a plan review that is not READY, with the commands `l4 yolo findings`,
`l4 yolo review --worktree`, `--record` and `l4 yolo accept`, its conditions, and the wait `accepted_finding_open`.
`docs/yolo-mode.md` SHALL describe the review rules. The skill's `plan.md` MUST tell an agent to iterate with
`--worktree` and never to accept a finding unless the target's configuration allows it.

#### Scenario: SCN-YOLO-70 (+) The runbook has the resolution path
- **GIVEN** the runbook and the skill
- **WHEN** the docs check runs
- **THEN** the runbook names `l4 yolo findings`, `l4 yolo review <plan-id> --worktree`, `--record`, `l4 yolo accept`, `accept_after_rounds`, `accept_by_agents` and `accepted_finding_open`, and `plan.md` names `--worktree` and `accept_by_agents`
