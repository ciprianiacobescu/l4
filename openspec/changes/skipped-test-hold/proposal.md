## Why

Verification step 3 raises a deterministic major finding, `existing tests are skipped in a changed test file`, for every
old test that the step-3 gate report holds as `skipped` when the unit changed the test's file. It compares nothing with
the base. A deterministic finding has no override: `apply_finding_verdicts` waives only findings whose source is
`judge`, so a person cannot say that the skip is fine. The round fails, a fix unit is made, and the fix unit cannot fix
it.

A consumer hit this. A unit changed one assertion inside each of several tests that a docker-compose stack gates
(`pytest.mark.skipif(os.getenv("...") != "true")`). The gate sandbox has no stack, so the tests were skipped before the
unit and are skipped now; the unit added and changed no skip. Verification raised the major, a fix unit was made, and
every way out is bad: moving the tests to another file breaks the unit's own red test (it reads the files by path),
ignoring the files in the gate drops their other tests, and reverting the edits breaks a criterion. The fix unit's only
task asked a technical question and is blocked on it; two of three fix rounds are used.

Verified at `next-int` (50bb9526):

- `src/l4/evidence/testsran.py:113-122` raises the major for `touched`, the old skipped ids whose file is changed; no
  base information is read.
- `src/l4/verifier/verdicts.py` `apply_finding_verdicts` waives judge findings only; `settle_holds` (`:287-325`) is the
  one path by which a person's `reject` of a hold becomes a finding.
- A plain fix chore cannot edit a test file: `run_single` puts the test paths back (`src/l4/implementer/tdd.py:4075-4086`,
  `freeze_test_paths`) and fails the attempt with `nothing changed: the guard put back every edit` (`:4096`). So no fix
  unit can make a skipped test run, whatever the finding says. Only a person's commit can.

## What Changes

- A skip that predates the unit is a hold, not a finding. For each old skipped test in a changed test file the harness
  decides, from a base report with statuses (the base's tests on the base's code: step 1's own reference, an earlier
  round's record, or at most one run of the base's test gate in a worktree) and from the base and head blobs of the
  file, whether the test was skipped at the base too and the unit added or changed no skip construct that can affect it
  and no support or runner-configuration file (L4-VER-092). When so, the tests of the file are one hold, asked as a
  verdict question, whose accept is bound to the file's content. When not, or when this cannot be shown (no base
  report), the finding stays deterministic as today.
- A person answers the hold. `accept` says the tests were run where they can run (or are known to pass there) and waives
  the hold for this content of the file. `reject: <reason>` is the person's finding: a fix unit cannot change test files,
  so no task is derived from it, the round escalates with `skipped_tests_rejected`, and the way out is the person's own
  commit on the unit branch followed by `l4 retry` (L4-VER-093).
- The hold is a person's decision. The delegate never answers it, with or without a call, and an accept or reject that a
  model wrote (`by` is not `human`) is not in force (L4-VER-094).
- A unit that already has a fix unit for the old finding can be moved on. A person's own tick of the fix unit's blocked
  task does not work: step 1 blocks any non-harness commit on a fix unit's folder (`a protected path was changed`), and
  on the old harness the fresh round raises the same major and spends the last fix round. So `l4 retry` is accepted for
  a unit in `fixing` whose open fix unit waits only on questions; the harness then ticks those tasks `already-done` in
  its own commits, marks their questions `superseded by retry`, ends the fix unit and verifies the parent in a fresh
  round under the pin, where the finding is a hold (L4-VER-095). The person upgrades the pin first.

Non-goals: skip detection for any language other than Python (the check maps JUnit ids to `.py` files only); a skip
that comes from production code the unit changed or from a module the test imports (the rule says so in the question and
does not tell them apart, D1); changing what a fix chore may edit; a per-hold override for a skip the unit added.

## Capabilities

### New Capabilities

- `skipped-test-hold`: L4-VER-092 (a skip that predates the unit is a hold), L4-VER-093 (the question, the accept's
  binding, the reject and its escalation), L4-VER-094 (a person decides it), L4-VER-095 (retrying a `fixing` unit whose fix unit waits on a person).

### Modified Capabilities

Amended in place in `docs/SPEC.md`, each with a pointer to the new requirements; no change for a skip the unit added.

- The step 3 row of the verification ladder (`docs/SPEC.md` step table, "every test added in the unit executed"): the
  old skipped tests of a changed file are findings or holds by L4-VER-092.
- L4-VER-013, paragraph "Holds are decisions too": a fourth hold kind, `skipped`, whose `reject` is the person's finding.
- L4-DLG-024: the delegate answers no skipped-test hold.
- The `evidence` object of `verdict.json` (`l4/evidence@1`): hold kind `skipped`; `tests_ran.summary.skipped_predating`.
- The Evidence section of `verification.md`: the line for skipped tests the unit did not introduce.
- `docs/runbook.md`: section 7.1 (the hold's answer), a new 7.3.4 (`skipped_tests_rejected`), the retry of a `fixing`
  unit in 7.1 and section 8, and the 0.4.x known limit; `CHANGELOG.md`.

## Impact

- `src/l4/verifier/scan.py` (`skip_constructs`, `collected_tests`, `shared_scopes`), `src/l4/verifier/base_tests.py`
  (`SkipLookup`, the `skipped` key of the step 1 record), `src/l4/implementer/workbench.py` (`base_skips`),
  `src/l4/evidence/skippred.py`, `src/l4/evidence/testsran.py` (`check_tests_ran`, `TestsSummary`),
  `src/l4/evidence/collect.py` (`Hold.kind`, `collect_evidence`, `Evidence`), `src/l4/evidence/report.py`,
  `src/l4/verifier/ladder.py` (`_collect_step`, `_finalize`), `src/l4/verifier/verdicts.py` (`HoldKind`, `hold_kind`,
  `hold_subjects`, `_hold_question`, `_hold_finding`), `src/l4/verifier/fixunit.py`, `src/l4/verifier/fixloop.py`
  (`_no_task_cause`), `src/l4/state/next_step.py`, `src/l4/state/retry.py`, `src/l4/orchestrator.py` (`resume`),
  `src/l4/state/fold.py`, `src/l4/specs/questions.py`, `src/l4/delegate/run.py` (`_without_a_call`),
  `src/l4/delegate/reply.py`, `src/l4/delegate/prompt.py`.
- `docs/SPEC.md`, `docs/runbook.md`, `CHANGELOG.md`. No change to the skill, to `src/l4/s1/` or to the configuration.
- Ledger and files: one new value of `holds[].kind` in `verdict.json`, three new optional keys in `tests_ran.summary` (`skipped_predating`, `skipped_source`, `skipped_note`), one optional
  `skipped` list in `integrity.base_tests`, one new escalation code, one new optional key `close_fix_unit` on `unit.retried`, one new question Status text. An older reader ignores the key and shows the code as an unknown reason. `human.void` is an
  existing event.
- Behaviour: a unit whose changed test file holds tests that were skipped before it stops failing and waits for a person's
  answer instead (at most one extra run of the base's test gate in a round, when no step 1 reference or earlier record has the statuses) (NEEDS_HUMAN, exit 11). A person who does not want to answer sees the hold, as for any hold. Nothing
  changes for a skip the unit added or changed, for a new file, or for a file the harness cannot compare.
