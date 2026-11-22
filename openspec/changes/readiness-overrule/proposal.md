## Why

A person cannot overrule one BLOCKING readiness finding that they have checked and found false, short of a plan-wide
force acceptance.

On a consumer plan reviewed by one weak judge, each spec edit made to answer a false finding re-opened the subject, and
the next review raised new false findings: five rounds, seven false findings, three of them blocking, none real. The
agent that drove the plan could not accept a blocking finding, and stopped only when a person stepped in.

What the 0.4.59 source does (read for this change; design.md has the lines):

- `l4 yolo accept PLAN SUBJECT` refuses a BLOCKED subject and a subject with a blocking finding: "fix the spec, push it
  and run l4 yolo review" (`src/l4/yolo/accept.py:115-133`, L4-YOLO-027).
- `l4 yolo accept PLAN --all --force` (L4-YOLO-057) is a person's way out, and it does cover a current review's
  blocking finding: it records `skipped: ["blocking", ...]` for that subject, and the activation counts the subject as
  cleared whatever the review says of it (L4-YOLO-061, `commands.py:505-524`). A probe confirmed it on a batch whose
  only finding was a judge's blocking `missing_dependency`. The backlog's "the only path is a spec edit" is therefore not
  right. The gap is the grain:
  - the force acceptance takes every subject of the plan, so every other subject that is not READY is cleared too, with
    all its findings, true ones included;
  - it is shown and carried as "no model reviewed this specification" (L4-YOLO-062), which is wrong for a subject a
    judge did review;
  - it is voided by any change of the plan file;
  - nothing of the person's reason reaches the judge, so a later review raises the same false finding again.

## What Changes

- **`l4 yolo overrule PLAN FINDING --reason TEXT [--withdraw] [--yes]`** (L4-YOLO-105). A person overrules one finding
  of the latest review: a judge's finding (an allowlisted criterion) of severity `blocking`. It records
  `plan.finding_overruled` with the finding, its subject, the subject's material key, the reason, `by`, `actor: person`,
  `marker`, `confirmed` and `harness_version`. It is a person's decision in a terminal: an agent is refused before
  anything is fetched, whatever `yolo.review.accept_by_agents` says, as for `--force`. The MCP server offers no tool for
  it. A harness finding (`schema`, `unit_missing`, `completeness`, `material`, `verdict`, `parts`) and a finding that
  is not blocking are refused. `--withdraw` removes an overrule and is never refused for who runs it.
- **What an overrule clears** (L4-YOLO-106). It holds while the latest review's entry for the subject has the same
  material key and still holds the finding. The subject is then judged on its other findings: none blocking and none
  major, it is cleared; a major left, it needs an acceptance (L4-YOLO-027), which a BLOCKED verdict whose every blocking
  finding is overruled no longer refuses; a blocking finding left, it is not cleared. The activation records each
  overrule that holds (`plan.activated{overruled}`), and an overruled finding is never carried to the unit (no
  implementer prompt, no verifier answer, no merge wait). `l4 yolo status`, `l4 yolo findings`, the activation's output
  and the plan report show each overrule and its reason, and say when one no longer holds.
- **The judge sees the rebuttal** (L4-YOLO-107). Every later call of the subject (its parts included) shows, after the
  plan entry, the subject's overrules: the finding and the person's reason, inside data blocks, with the rule that the
  judge raises such a finding again only when the text shown still has the defect, and says why the reason does not
  apply. The note is not part of the material key, so an overrule never changes a key and the prompt version does not
  move.
- **Documentation** (L4-YOLO-108): the runbook's procedure for a review that is not READY, the skill's
  `references/plan.md`, and the CHANGELOG.

Non-goals:

- overruling a major or minor finding (an acceptance covers them);
- overruling after the activation (a waiver covers an accepted finding then, L4-YOLO-031);
- a configuration key that lets an agent overrule;
- showing the overrule in the unit's pull request body (the plan report holds it; an open question);
- any change to unit verification.

## Capabilities

### New Capabilities

- `readiness-overrule`: L4-YOLO-105 (the command and who may run it), L4-YOLO-106 (what an overrule clears and how
  long), L4-YOLO-107 (the judge sees the rebuttal), L4-YOLO-108 (documentation).

### Modified Capabilities

These are amended in `docs/SPEC.md`:

- L4-YOLO-027: a blocking finding that an overrule holds for is not a refusal.
- L4-YOLO-005: a subject an overrule clears counts as READY for the activation.
- The command table: one row.

## Impact

- Code: `src/l4/yolo/commands.py` (`run_overrule`, `_review_view`, the activation, the status), `src/l4/yolo/accept.py`
  (`overrule_check`, `overrule_holds`, `effective`), `src/l4/yolo/state.py` and `model.py` (`overruled`,
  `activated_overruled`), `src/l4/yolo/findings.py` (the lines of `l4 yolo findings`), `src/l4/yolo/readiness.py`
  (the note), `src/l4/yolo/cycle.py` and `review_worktree.py` (pass the overrules), `src/l4/yolo/report.py`,
  `src/l4/cli.py` and `src/l4/commands.py` (the command), `src/l4/cli_pin.py` (the guard's table, when the change
  `readiness-entry-and-actor` is in).
- Docs: `docs/SPEC.md` (L4-YOLO-105..108, SCN-YOLO-296..306, row 139, the command row, the amendments),
  `docs/runbook.md` 12.2a, `plugins/l4/skills/l4/references/plan.md`, `CHANGELOG.md`.
- Ledger: two new plan events (`plan.finding_overruled`, `plan.overrule_withdrawn`) and an optional `overruled` on
  `plan.activated`. An older harness ignores them, which only makes it stricter.
- Configuration: none.

This change is separable from `readiness-entry-and-actor`: it uses no field of it, and the readiness prompt version is
not moved by it. When both ship, `yolo overrule` (not `--withdraw`) joins the `refuse` row of L4-OPS-026.
