## Why

A TypeScript consumer's task 1.1 had a reviewed text that told the red step to add an edge to the module-graph data
file `test/arch/modules.ts`. The red step did. Verification step 1 then ran the pre-existing tests with the unit's test
and support files at their base version (L4-VER-038): it reverted five files, that one among them, so the base graph
forbade the import the unit's code needs, and the unchanged base test `test/arch/repo.test.ts` (a `deepEqual` of the
graph's violations against `[]`) failed. Round 1 was FAIL. The fix chore found nothing to fix (every test passes at
head) and committed only its `tasks.md` tick. Round 2 failed the same way, and the unit escalated `same_failure` with
the text `round 2 failed the same way as round 1: finding <id>`. A person tagged the task `[test-infra]`; the next round
listed the file `kept at head for the run (task 1.1: [test-infra])` and passed.

What exists at 0.4.59 (verified in code):

- `verifier/base_tests.py` `kept_files` keeps a file of the revert set at head only when only people changed it, when
  `integrity._allowance` covers every harness commit that changed it (a `[test-infra]` task, or a `task.unfrozen` of
  the same task whose `paths` names it), or when a person changed it last and it is no support file. Every other file
  is reverted.
- The task text names the file, but nothing records that as an allowance. `implementer/unfreeze.py` `named_by_task`
  lists a named manifest path that red changed under `kept`, and `run_green` records it as
  `task.unfrozen{reason: "named_by_task", paths: [], kept: [...], source, red_sha}`. With the default globs
  `test/arch/modules.ts` matches `**/test/**` and no support glob, so the manifest's kind is `test` and the `kept`
  reason is `a red test of this task`. The verifier's own rule (`support_base.is_support_file`: a name that does not
  look like a test module) calls it a support file. Checked with a probe of both rules.
- The asymmetry: an existing *test* that the reviewed text names and red changes in place is allowed in step 1
  (`tests.superseded{reason: named_by_task}`, L4-IMP-082, L4-IMP-089). A named *support* file is not.
- The blocker's detail is `<id> (<first line of the message, 150 characters>)` per test. It does not say which files
  the run reverted, so neither the fix chore nor the person can tell that the test passes at head. Step 1's failure
  stops the ladder before step 3, so the round's `failures` map (L4-VER-069, L4-VER-078) has no record and the fix
  chore gets no failure block (L4-IMP-102).
- A fix chore whose step changes nothing falls through to the gate, which passes at head, and commits its tick
  (`tdd.run_single`: only a step whose every edit the guard put back is `nothing changed`). The `same_failure`
  escalation of the next round names the finding id only.

## What Changes

- **SLIPPABLE.** Step 1 keeps at head, for the run of the base's tests, a support file that exists at the base when
  every harness commit that changed it is the red commit of a task whose reviewed text names it: a
  `task.unfrozen{reason: named_by_task}` of that unit, task and red commit lists the path. At most three such files per
  task, and at most 40 changed lines in each. The file is listed under `## Pre-existing tests changed with an allowance (L4-VER-031)` with the task and the
  reviewed text's source (L4-VER-079). Only `kept_files` reads this rule. The comparison of pre-existing tests
  (L4-VER-030) and every other reader of `_allowance` are unchanged.
- The base-tests blockers lead with the reverted support files and the tasks whose commits changed them. Each failing
  base test gets a record in the round's `failures` map under the gate `base-tests`, with the bounded, redacted excerpt
  of L4-VER-078. A fix task for `a pre-existing test fails on the unit's code` therefore carries the failure block of
  L4-IMP-102 into its proposal, its prompt and its questions (L4-VER-080).
- A `same_failure` escalation of a round whose blockers hold a base-tests finding leads with the way out, then the
  support files the run reverted and the tasks that changed them. The way out is a person's `[test-infra]` tag on that
  task when the change is intended, or a fix of the code, then `l4 retry` (L4-VER-081).
- The skill's spec-writing rules say: a red step may change a support file a test reads only when its task line names
  that file's path; the verifier then keeps that change for the run of the base's tests and lists it.

Non-goals: a support file that red added (it does not exist at the base, so the run sets it aside), an ignore file, a
test module (L4-IMP-082 and L4-IMP-089 cover named tests), a fix or follow-up unit's task (no reviewed text), a task
that finished as already satisfied (no green step, so no record), and the general rule for a fix chore that changes
nothing. That rule belongs to the fix-chore work of this release.

## Capabilities

### New Capabilities

- `base-tests-named-support`: L4-VER-079 (a named support file that red changed stays at head for the run, listed),
  L4-VER-080 (the base-tests blocker names the reverted support files, and its tests reach the fix task with their
  failure text), L4-VER-081 (a repeated base-tests failure escalates with the files and the way out).

### Modified Capabilities

- L4-VER-038: a fifth kind of file stays at head (L4-VER-079).
- L4-VER-069: the `failures` map gains the gate value `base-tests`. Readers that filter by gate ignore it.
- L4-IMP-102: the finding `a pre-existing test fails on the unit's code` names every record of the gate `base-tests`.
- L4-OPS-007 (`same_failure`): a leading text for a base-tests finding.

## Impact

- `src/l4/verifier/base_tests.py` (`kept_files`, a new `_named_red_change`, `check_base_tests`, `_emit`),
  `src/l4/verifier/integrity.py` (`Outcome.failures`), `src/l4/verifier/gates.py` (`failure_records(..., unit_gate=)`),
  `src/l4/verifier/failures.py` (`shown_failure_ids`), `src/l4/verifier/ladder.py` (`integrity()`),
  `src/l4/verifier/fixloop.py` (`repeated_failure` or its caller).
- `plugins/l4/skills/l4/references/spec.md`, `docs/runbook.md` (the row of `a pre-existing test fails on the unit's
  code`), `docs/SPEC.md` (L4-VER-079..081, SCN-VER-312..321 and 324..328, change-table row 136), `CHANGELOG.md`.
- Ledger: `verify.base_tests` gains `support_reverted` (at most 20 entries). No new event, no configuration key.
- Cost: the run of the base's tests is the same run, and a kept file is one fewer file reverted. A named file that passes
  every other condition needs the base's report: with no baseline and no earlier round's evidence, step 1 runs the
  merge base's setup and test gate once (as it already does when its own run is not all green).
