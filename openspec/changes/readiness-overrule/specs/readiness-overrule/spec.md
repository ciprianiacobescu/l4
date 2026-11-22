## Purpose

A person who has checked a blocking readiness finding and found it false can overrule that one finding, on the record,
without editing the spec and without a plan-wide force acceptance; the overrule ends when the subject's material
changes, an agent can never make one, and the next judge of the subject reads the person's reason.

## ADDED Requirements

### Requirement: L4-YOLO-105 A person can overrule one blocking finding of a judge
`l4 yolo overrule PLAN FINDING --reason TEXT [--withdraw] [--yes]` SHALL record `plan.finding_overruled{finding,
subject, criterion, severity, text, material, reason, by, actor: person, marker: null, confirmed, judged_at,
harness_version}` in one leased write, after the person has seen the finding and typed the plan id (`--yes` replaces
the typed id, L4-YOLO-063). It MUST be refused (exit 2, nothing recorded) for every caller that `l4.actor.actor` does
not name a person, before the plan is fetched and whatever `yolo.review.accept_by_agents` says; the MCP server MUST
offer no tool that runs it, and `l4 yolo go` MUST NOT run it. It MUST also be refused, with the cause and the fix: by
the plan status rule of L4-YOLO-027; for a plan with no review; for an id that is not a finding of the latest
`plan.reviewed` (the refusal lists its blocking findings); for an entry with no material key; for a finding whose
criterion is not one of the judge's (`outcome`, `testability`, `interfaces`, `failure_cases`, `feasibility`,
`duplicate_scope`, `contradiction`, `missing_dependency`, `batch_acceptance`), so never for `schema`, `unit_missing`,
`completeness`, `material`, `verdict` or `parts`; for a finding whose severity is not `blocking` (the fix is
`l4 yolo accept`); and for an empty reason or one over 1,000 characters. `--withdraw` SHALL record
`plan.overrule_withdrawn{finding, reason, by, actor, marker}`; it MUST NOT be refused for who runs it, and is refused
after the activation and when the finding has no overrule. The plan fold MUST ignore a `plan.finding_overruled` whose
`actor` is not `person`; a later one for the same finding replaces the earlier.

#### Scenario: SCN-YOLO-296 (+) A person overrules a false blocking finding
- **Given** plan `p1` reviewed with units A and B READY and `batch:b1` NEEDS_REVISION whose only finding `F` is
  `missing_dependency`, `blocking`, "two units list themselves in depends_on", and a person in a terminal
- **When** `l4 yolo overrule p1 <F> --reason "no unit lists itself; checked the plan file"` runs and the person types
  `p1`
- **Then** it prints the finding, records `plan.finding_overruled` with `subject: batch:b1`, the entry's `material`,
  `actor: person` and `confirmed: typed`, prints `overruled: <F> of batch:b1 by <by> (person): …`, and exits 0

#### Scenario: SCN-YOLO-297 (−) An agent is refused before anything is read
- **Given** the plan of SCN-YOLO-296, `yolo.review.accept_by_agents: true` on the base, and `CLAUDECODE=1`; then no
  marker and no terminal
- **When** `l4 yolo overrule p1 <F> --reason r --yes` runs
- **Then** both exit 2 with `overruling a finding is a person's decision, never an agent's` and the person's command,
  no ref is fetched and nothing is recorded; the MCP server's tools hold none that runs `l4 yolo overrule`

#### Scenario: SCN-YOLO-298 (−) Only a judge's blocking finding of the latest review is overruled
- **Given** in turn a `schema_invalid` BLOCKED entry, a `material` finding, a `verdict` finding, a `parts` finding, a
  `major` `testability` finding, an id of an older review and an entry with no `material`
- **When** `l4 yolo overrule p1 <id> --reason r` runs
- **Then** each exits 2 with its own cause (a harness finding; `only a blocking finding is overruled` with the fix
  `l4 yolo accept p1 <subject> --reason "..."`; `not a finding of the latest review` with the blocking ids; the
  material-key text), and nothing is recorded

### Requirement: L4-YOLO-106 What an overrule clears, and how long
An overrule SHALL hold while the latest review's entry of its subject has the overrule's `material` and holds a finding
whose id is the overrule's `finding`; a review of changed material voids it, a reuse of the same material keeps it. For
the activation, the status, `l4 yolo go` and `l4 yolo accept`, a subject SHALL be judged on its findings without the
ones a holding overrule names: when one of those left is a harness finding or `blocking`, the entry's verdict stands;
else when one is `major`, the subject is NEEDS_REVISION and needs an acceptance that holds (L4-YOLO-027), which a
BLOCKED entry whose every blocking finding is overruled MUST NOT refuse for being BLOCKED; else it SHALL count as READY.
An acceptance SHALL clear a subject only while that rule makes it NEEDS_REVISION, so a withdrawn overrule makes its
blocking finding stop the activation again. `plan.accepted` SHALL record the ids it relied on as `overruled`.
`plan.activated` SHALL record `overruled: {<finding>: {subject, criterion, severity, text, reason, by, actor, at}}` for
every holding overrule of a subject of the plan, and the activation's output SHALL list each. An overruled finding MUST
NOT be carried to the unit: it is left out of the accepted items' `findings`, so the implementer's prompt, the
verifier's judge and the merge gate never see it. `l4 yolo status` (text and `--json`) SHALL list every recorded
overrule of the plan's subjects with its reason and whether it holds (`; no longer holds: the subject's material
changed`); `l4 yolo findings` SHALL mark an overruled finding and a subject it clears, and SHALL give, for a blocking
judge finding with no overrule, the overrule command as a person's way out, as SHALL the refusal of `l4 yolo accept`
for a blocking finding; the plan report SHALL list the overruled findings of each unit and its batch.

#### Scenario: SCN-YOLO-299 (+) The overruled plan activates and nothing is carried
- **Given** the overrule of SCN-YOLO-296
- **When** `l4 yolo status p1`, `l4 yolo findings p1` and `l4 yolo activate p1 --reason go --no-run` run, and the first
  unit of the plan starts
- **Then** the status lists `overruled: <F> of batch:b1 by <by> (person): …` and no problem; the findings show
  `batch:b1: NEEDS_REVISION (cleared by an overrule: …)` and the mark on `F`; the activation records `overruled` with
  `F` and no accepted item for `batch:b1`, and prints the overrule; the unit's `.l4/review-accepted.json` holds no `F`;
  the report lists `F` with the reason

#### Scenario: SCN-YOLO-300 (+) What is left decides
- **Given** in turn an entry BLOCKED with blocking `F1` overruled and major `F2`; NEEDS_REVISION with blocking `F1`
  overruled and minor `F3`; NEEDS_REVISION with blocking `F1` overruled and blocking `F4`
- **When** `l4 yolo activate p1 --reason go` runs, and for the first `l4 yolo accept p1 <subject> --reason r` after two
  judged versions
- **Then** the first is refused until the acceptance, which is not refused as BLOCKED and records `overruled: [F1]`,
  and then activates; the second activates; the third is refused naming `F4`

#### Scenario: SCN-YOLO-301 (−) A changed material ends the overrule
- **Given** the overrule of SCN-YOLO-296, then a pushed change of unit A's spec, and a new review that raises `F` again
  on the batch's new material
- **When** `l4 yolo status p1` and `l4 yolo activate p1 --reason go` run
- **Then** the status shows the overrule with `; no longer holds: the subject's material changed`, and the activation
  is refused with `F`; a review that reuses the batch's old material instead keeps the overrule

#### Scenario: SCN-YOLO-302 (−) A withdrawal by anyone makes the activation strict again
- **Given** the overrule of SCN-YOLO-300's first case and the acceptance that relied on it
- **When** an agent (`CLAUDECODE=1`) runs `l4 yolo overrule p1 <F1> --withdraw --reason r`, and then
  `l4 yolo activate p1 --reason go`
- **Then** `plan.overrule_withdrawn{actor: agent}` is recorded, and the activation is refused with `F1` although the
  acceptance still holds by its key

#### Scenario: SCN-YOLO-303 (−) No overrule after the activation, and none from another actor
- **Given** an active plan `p1`; and a ledger holding a `plan.finding_overruled` whose `actor` is `agent`
- **When** a person runs `l4 yolo overrule p1 <F> --reason r`, and the second plan is folded
- **Then** the first exits 2 with the status rule's text and records nothing; the fold of the second has no overrule

### Requirement: L4-YOLO-107 The judge of a later review reads the person's reason
Every judge call of a subject (a unit, a batch, and each part of a batch) SHALL show, at the end of its `plan entry`
section, the subject's recorded overrules that are not withdrawn, whether they hold or not, newest first and at most
five: a harness note that a person overruled these findings of an earlier review of this subject as false for the
reasons given, that the judge judges the text shown now, and that it raises such a finding again only when the text
shown still has the defect and then says why the reason does not apply; and per overrule one data block with the
finding's criterion, severity and text (at most 2,000 characters) and the reason (at most 1,000). The note MUST name
no unit and no batch outside data blocks. It MUST NOT be part of the subject's material key, MUST NOT change the
templates, and a subject with no overrule SHALL be asked byte for byte as without it; the readiness prompt version is not
changed by it.

#### Scenario: SCN-YOLO-304 (+) The next review shows the rebuttal and keeps the key
- **Given** the overrule of SCN-YOLO-296, then a pushed change of unit A's spec
- **When** the CI plan step reviews the plan
- **Then** the batch's prompt (and each part's, when it is split) holds the note and a data block with `F`'s text and
  the reason after the plan entry; the batch's material key equals the key of the same material with no overrule; A's
  and B's prompts hold no note

#### Scenario: SCN-YOLO-305 (+) A subject with no overrule is asked as before
- **Given** a plan with no `plan.finding_overruled`
- **When** the review builds its prompts
- **Then** every prompt and every material key equals the one the review builds without this change

### Requirement: L4-YOLO-108 Documentation of the overrule
The runbook's procedure for a review that is not READY (12.2a) SHALL say when a person overrules a finding (a blocking
finding of a judge that the person checked and found false), the command, what it records, that it ends when the
subject's material changes, that the next judge reads the reason, that an agent never runs it and prints the person's
command, and that `--all --force` remains the plan-wide way out. The skill's `references/plan.md` SHALL say the same
where it tells an agent not to accept a blocking finding. The CHANGELOG SHALL have the entry under Unreleased.

#### Scenario: SCN-YOLO-306 (+) The documentation names the overrule
- **When** the runbook, the skill's `references/plan.md` and the CHANGELOG are read
- **Then** each names `l4 yolo overrule`, says it is a person's decision for one blocking finding of a judge, and that
  it ends with the subject's material; `plan.md` says an agent prints the command for the person
