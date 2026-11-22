## Context

Read at 0.4.59 (`62188257`):

- `src/l4/yolo/accept.py:94-170` `check` refuses, in order: the plan status (`status_refusal`, `:80-91`); a BLOCKED
  entry (`:115-125`, "the judge could not judge it or says it cannot be built"); a blocking finding other than
  `material` (`:126-133`, "fix the spec, push it and run l4 yolo review"); a `material` finding; a READY entry; fewer
  rounds than `yolo.review.accept_after_rounds`; an agent without `yolo.review.accept_by_agents`.
- `accept.py:175-188` `holds`: an acceptance holds while the latest entry has its `material` and `findings_sha`.
- The force acceptance: `accept.py:254-317` (`_skipped`, `force_subjects`) records `skipped` per subject, `blocking`
  among them; `commands.py:505-524` (`_review_view`) clears a subject a holding force acceptance overrode "whatever a
  current review says of it" (L4-YOLO-061). A probe on 0.4.59 confirmed it: a batch with one judge `blocking`
  `missing_dependency` finding was refused by `l4 yolo accept`, force-accepted with `skipped: ["blocking", "rounds"]`,
  and activated with `accepted["batch:b1"] = {findings: [], force: true, ...}`. `_run_force_accept` refuses an agent
  before anything is fetched (`commands.py:2626-2635`, L4-YOLO-058). The plan fold ignores a `plan.force_accepted`
  whose actor is not `person` (`state.py:172-174`).
- `findings.py:26-30` `finding_id(subject, finding)` = `F-` + six hex of sha256 of subject, criterion, severity, text.
  `findings.py:39-44` `carried` is what an acceptance carries to the unit. `report.py:48-76` lists the accepted
  findings of a unit and its batch.
- The judge's criteria are an enum of the response schema (`yolo/schemas/readiness.schema.json`): `outcome`,
  `testability`, `interfaces`, `failure_cases`, `feasibility`, `duplicate_scope`, `contradiction`,
  `missing_dependency`, `batch_acceptance`. The harness adds `schema`, `unit_missing`, `completeness`
  (`findings.py:20`), `material` (`readiness.py:655`), `verdict` (`readiness.py:619`) and `parts` (`readiness.py:525`).
- The material of a subject: `readiness.py:368`, `:405`, `:486` build `ENTRY` from the plan entry and harness notes;
  `text(listed)` is called twice, once with the delivered units (`user`) and once with none (`key_text`), so the
  delivered list is shown but not keyed (`:377-379`, `:425`, `:502-506`). `material_key` (`:574-580`) hashes `key_text`, the
  prompt version and a fingerprint of the templates and the schema.
- `run_waive` (`commands.py:2720-2800`) is the model of a person's audited plan decision: the actor, the typed plan id
  or `--yes`, one leased event, `MAX_REASON = 1000` (`commands.py:2520`).

## Goals / Non-Goals

**Goals:** a person who checked a blocking finding and found it false can clear that finding alone, on the record,
without editing the spec; the clearance ends when the subject's material changes; the judge of a later review reads the
person's reason; an agent can never do it.

**Non-Goals:** major and minor findings; findings after the activation; an agent key; the PR body; unit verification.

## Decisions

### D1. The command

`l4 yolo overrule PLAN FINDING --reason TEXT [--withdraw] [--yes]`, handler `l4.yolo.commands:run_overrule`, owning
change `readiness-overrule`:

1. `--reason` stripped must not be empty and at most `MAX_REASON` characters (exit 2, the texts of `run_accept`).
2. Not `--withdraw`: `who = accepting.actor(environ, _stdin_tty())`; an agent is refused here, before anything is
   fetched, with `overrule: overruling a finding is a person's decision, never an agent's (<why>), whatever
   yolo.review.accept_by_agents says` and `Fix: a person runs, in a terminal: l4 yolo overrule <plan> <finding>
   --reason "..."` (`<why>` as in `_run_force_accept`). No key changes this.
3. `_open`, `_sync(who="overrule")`, `_valid(_file(...))`, read the plan ref, fold.
4. `--withdraw`: refused when `accepting.status_refusal(state)` refuses (after the activation: the text of an
   acceptance's withdrawal) or when `FINDING` has no overrule; else `plan.overrule_withdrawn{finding, reason, by,
   actor, marker}`. Never refused for who runs it: it only makes the activation stricter.
5. `accepting.status_refusal(state)`: the status rule of an acceptance.
6. The latest `plan.reviewed`; none: `overrule: <plan> has no review yet: run l4 yolo review <plan>`.
7. `accepting.overrule_check(review, FINDING)` (D2) gives the subject and the finding, or a `Refusal`.
8. A person sees `<finding> [<criterion>/<severity>] of <subject>: <text>` and types the plan id (`Type the plan id
   (<plan>) to overrule <finding>: the activation will not wait for it`), unless `--yes`.
9. One leased write: `plan.finding_overruled{finding, subject, criterion, severity, text, material, reason, by,
   actor: "person", marker: null, confirmed: "typed" | "--yes", judged_at, harness_version}` (`judged_at`: the entry's
   `reused_from` or the review's `at`).
10. Output: `overruled: <finding> of <subject> by <by> (person): <reason>` and `Next: l4 yolo status <plan>`.

The MCP server offers no tool for it. `l4 yolo go` never runs it. When `readiness-entry-and-actor` is in,
`yolo overrule` (not `--withdraw`) is in the `refuse` row of `cli_pin.WRITES`, and `--withdraw` in its `warn` row.

### D2. Which findings

`JUDGE_CRITERIA` in `accept.py`: the schema's enum (a test holds them equal). `overrule_check(review, finding_id)`:

- The finding is looked up in every entry of the latest `plan.reviewed` (`findings._entries`), matching
  `finding_id(subject, f)`. Not found: `overrule: <id> is not a finding of the latest review of <plan> (its blocking
  findings: <ids>, or none)` and `Fix: l4 yolo findings <plan>`.
- The entry has no `material`: the refusal of `run_accept` for an entry that predates material keys.
- `criterion` not in `JUDGE_CRITERIA`: `overrule: <id> is a harness finding (<criterion>): no judge raised it, so there
  is nothing to overrule` and `Fix: l4 yolo findings <plan>` (its `Resolve:` line says what clears it).
- `severity` other than `blocking`: `overrule: <id> is <severity>: only a blocking finding is overruled, and a
  <severity> finding is accepted` and `Fix: l4 yolo accept <plan> <subject> --reason "..."`.

An allowlist, so a criterion the harness adds later is never overrulable by default.

### D3. When an overrule holds

`overrule_holds(state, latest_review) -> dict[str, bool]`, per recorded overrule: true when the latest review's entry
of its `subject` has the overrule's `material` and holds a finding whose id is the overrule's `finding`. A new review of
changed material (the unit's spec, a prerequisite, its plan entry, the prompt version) voids it; a reuse of the same
material keeps it. A withdrawn overrule is gone. Nothing else voids it: a change of another unit or of another batch's
entry does not touch this subject's material.

### D4. The subject after its overrules

`effective(subject, entry, held) -> tuple[str, list[dict]]`, `held` the ids of holding overrules of the subject:

- `rest` = the entry's findings whose id is not in `held`.
- Nothing held for the subject: the entry's verdict and findings, unchanged.
- A finding in `rest` with a harness criterion, or with severity `blocking`: the entry's verdict, `rest`.
- Else a finding in `rest` with severity `major`: `NEEDS_REVISION`, `rest`.
- Else: `READY`, `rest` (minor findings stay, as L4-YOLO-023 keeps them).

So a judge's BLOCKED whose only blocking finding is overruled and that has no major finding is cleared, and one with a
major finding left needs an acceptance. A BLOCKED with no finding at all has nothing to overrule and stays BLOCKED.

Readers:

- `_review_view` (status, activation, `go`): for a subject not READY, `effective` decides. `READY`: cleared, listed in
  the view's `overruled`. Otherwise an acceptance clears it only when it holds and the effective verdict is
  `NEEDS_REVISION`. The problem line uses the effective findings.
- `accept.check` gets the held ids: the BLOCKED and blocking rules read the effective verdict and findings. The other
  rules are unchanged. `plan.accepted` records the entry's findings and `findings_sha` as today (so `holds` is
  unchanged) and `overruled`, the held ids it relied on. When an overrule is withdrawn, the effective verdict has a
  blocking finding again and the acceptance no longer clears the subject.

### D5. The activation and what is carried

`run_activate` records `overruled: {<id>: {subject, criterion, severity, text, reason, by, actor, at}}` for every
holding overrule of a subject of the plan, prints `overruled: <id> of <subject> by <by> (person): <reason>` per item
before the `activated on` line, and writes each accepted item's `findings` without the held ids. The fold keeps
`activated_overruled`, replaced by each activation. Nothing of an overrule reaches `.l4/review-accepted.json`, the
implementer's prompt, the verifier's judge or the merge gate: the person said the finding is false, and carrying it
would ask the implementer to answer it, which is the loop this change ends.

### D6. Where it is shown

- `l4 yolo status`: under `review:`, one line per recorded overrule of the plan's subjects, `overruled: <id> of
  <subject> by <by> (person): <reason>`, with `; no longer holds: the subject's material changed` when it does not;
  `--json`: `review.overruled` rows `{finding, subject, by, reason, holds}`.
- `l4 yolo findings`: a subject cleared by overrules reads `<subject>: <verdict> (cleared by an overrule: it does not
  stop the activation)`; an overruled finding's line ends with ` (overruled by <by> (person): <reason>)`; a blocking
  judge finding that has no overrule gets, after its `Resolve:` line, `    Or, when a person has checked that it is
  false: l4 yolo overrule <plan> <id> --reason "..." (a person's decision)`. `--json`: `overruled` per finding.
- The refusal of `l4 yolo accept` for a blocking judge finding adds that line to its fix.
- The plan report, per unit (its subject and its batch), from `activated_overruled`: `- Overruled review findings
  (<subject>):` and `  - <id> [<criterion>/<severity>] <text>: overruled by <by> (<actor>): <reason>`.

### D7. The rebuttal the judge reads

`review_plan_costed(..., overruled: Mapping[str, Sequence[Mapping[str, str]]] = {})`, subject name (`<unit id>` or
`batch:<id>`) to rows `{criterion, severity, text, reason}`. `findings.overruled_for_review(state)` builds it from
`state.overruled` (every recorded overrule, holding or not), newest first, at most `MAX_OVERRULED = 5` per subject,
`text` cut at 2,000 characters and `reason` at 1,000. The CI step (`cycle.py`), `--local` (`commands.py`) and
`--worktree` (`review_worktree.py`) pass it.

`_unit_subject`, `_batch_subject` and `_batch_part` take the rows of their subject (a part those of its batch). Their
inner `text(listed, notes)` appends to the `ENTRY` value, after the other notes, `"\n" + OVERRULED_NOTE` and one
`data_block("overruled finding", "[<criterion>/<severity>] <text>\nreason: <reason>")` per row. `user` is
`text(delivered, rows)`; `key_text` stays `text({}, ())`. So:

- an overrule never changes a material key, and a reused verdict is reused as before;
- a subject with no overrule is asked byte for byte as without this change;
- no template changes, so the fingerprint and `PROMPT_VERSION` do not move, and this change can ship or be cut alone.

`OVERRULED_NOTE = "A person overruled the findings below, which an earlier review of this subject raised, as false,
for the reasons given. Judge the text shown now. Raise such a finding again only when the text shown still has that
defect, and then say in its text why the person's reason does not apply."` The note names no unit and no batch; the
finding's text and the reason are inside data blocks (L4-YOLO-004).

The two lifetimes: the gate effect (D3) ends with the material; the rebuttal stays in the review of the subject until
the overrule is withdrawn.

### D8. Events and the fold

- `plan.finding_overruled`: `state.overruled[finding] = {**data, "at": event.at}` when `actor` is `person` and the plan
  is not final; any other actor is ignored (the command never writes one), as L4-YOLO-060 does for force. A later
  event for the same finding replaces the earlier one.
- `plan.overrule_withdrawn`: pops it.
- `plan.activated{overruled}`: `state.activated_overruled`.
- `PlanState.overruled` and `activated_overruled`: `dict[str, dict[str, Any]]`, default empty.

### D9. Why it is safe

- It is narrower than what a person can already do. A person could already clear a blocking finding with
  `--all --force`; the overrule clears one finding, not every subject, bound to the subject's material, which a
  prerequisite's change also moves, and it keeps every other finding of the subject in force. Two things are new, and
  both are a person's: an overrule survives a change of the plan file that leaves the subject's entry as it was (a
  force acceptance is voided by any change of the plan file), and the person's reason reaches later judges of the
  subject (D7).
- An agent cannot run it, whatever the configuration, and the fold ignores an event with another actor.
- A harness finding, a major or minor finding, a finding of another review and an entry without a material key are
  refused. An unknown or changed material never holds.
- It changes nothing after the activation and nothing in unit verification. A false overrule of a true finding can let
  a unit be built on a wrong plan, as a false force acceptance can today; the unit's own verification is unchanged.
- An older harness ignores the events and refuses the activation it cannot clear: the strict side.

### D10. Alternatives rejected

- **Point the refusal at `--all --force`** (no new command). Cheapest, but it clears every other non-READY subject and
  tells the implementer that no model reviewed the specification.
- **Let an acceptance take a blocking finding.** An acceptance carries its findings to the implementer and the merge
  gate; a false finding would then wait for an answer nobody can give.
- **Put the rebuttal in the material key.** An overrule would change the key, so it would void itself at the next
  review of the same text.
- **Let `yolo.review.accept_by_agents` allow it.** It overrides a blocking finding, a decision of the weight of `--force`,
  which no key gives an agent.

## Risks / Trade-offs

- A person can be wrong. The reason is on record, shown in status, findings, the activation and the report, and read
  by every later judge of the subject.
- The rebuttal can make a judge hold back a finding that a later version of the text makes real. The note tells it to
  judge the text shown and to answer the reason.
- The unit's pull request does not show the overrule (an open question).
- Six more code paths read the effective verdict; a reader that does not would be stricter, never looser.

## Migration

- No overrule in a 0.4.59 ledger: nothing changes.
- An older harness logs the two events as ignored and folds as before.
- No configuration key; the prompt version is not moved by this change.
