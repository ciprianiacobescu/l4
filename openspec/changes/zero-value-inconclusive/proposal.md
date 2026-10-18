## Why

On a consumer repository (harness 0.4.14; the code is unchanged in 0.4.15) a delivery plan halted on one unit after
about two and a half hours: task 3.1 failed nine red attempts on four implementer profiles, was escalated three times
and stopped at `max_task_attempts`, and task 2.2 failed the same way before it. No agent could have passed. An
investigator reproduced it with the 0.4.14 library against a clone (the evidence is summarised in `design.md`):

1. **The pre-satisfied check broke the imports it measured.** `test-presatisfied` zeroes every public function of the
   modules the tests import and of the modules changed since the unit base. A decorator factory
   `traced(name) -> Callable[[_F], _F]` has no entry in the zero-value table, so it became `return None`. Another module
   applies `@telemetry.traced("…")` while its class body runs, so importing it raised
   `TypeError: 'NoneType' object is not callable`. pytest stopped with `Interrupted: 45 errors during collection`,
   exit 2, and ran 0 tests.
2. **The base run stopped at the first collection error.** `test-base-run` swaps the production files back to the unit
   base and sets the added ones aside. A test file that imports an added module then fails collection, and without
   `--continue-on-collection-errors` pytest collects nothing (exit 2). Only `discriminate_extra` passes the flag.
3. **"Could not run" was reported as "does not discriminate".** `confirm_pre_satisfied` only checks
   `report is None`. A readable report with collection errors and no test case leaves every criterion unconfirmed
   with no reason, and the message says "its tests still pass … when the functions they use answer the zero value".
   `run_with_code_of` returns `{}` for an empty report, and the base run calls that "the gate wrote no readable
   report". The red attempt fails as the agent's: it uses an attempt, escalates the profile, and the unit halts. The
   console line says `gate test-presatisfied fail (expected: zero values must fail) (exit 2, 0 tests …)`.
4. **The same gap sits in every variant run.** The verifier's audit calls the same `confirm_pre_satisfied` (false
   minor rejections); the zero-value run of `discriminate_extra` would break the same way; `test-zero` (run (b)) and
   `test-at-red` have the same classification gap.
5. **No evidence reached a person.** The consumer sets `ci.upload_artifacts: false`, so no gate log was kept. The
   ledger events carry only a log path (`excerpt_lines: 0`), and the console still printed `(CI: job artifacts)`.
6. **Two proof rules were missing.** A test whose fixture asserts (`assert telemetry.init(...) is True`) fails in SETUP
   on the zero values (a JUnit `error` with an assertion), which `fails_on_zero` does not count. And a criterion whose
   test checks a fact about a dependency (a version pin) passes on the zero values and at the base alike, so no check
   can ever confirm it.

## What Changes

- **One classifier for every variant run** (L4-IMP-060). The zero-value runs, the base run, `test-at-red`, the
  audit's run and the extra-proof runs are judged against the real run, per test: a test that failed by assertion is a
  proof; one that passed, or failed by another error, is no proof; a test the run did not run (no report, no test
  collected, its module failed to import only there, skipped only there) is **inconclusive**. Its reason quotes the
  first `E` line of the collection error, bounded and redacted. Every variant run passes
  `--continue-on-collection-errors`; `run_with_code_of` returns the gate result, so "no tests" and "no report" differ.
- **Zeroing keeps what imports need** (L4-IMP-061). When every public function is zeroed, one annotated to return a
  callable or a class keeps its body. When a zero-value run still leaves candidates inconclusive, the harness reads
  the tracebacks, keeps the zeroed functions called on the failing lines, and runs again, at most twice, recording
  `zero.kept`.
- **Proof rules** (L4-IMP-002, L4-IMP-062). A setup-phase assertion counts as a failure on the zero values when the
  asserting fixture is in a test or support file the unit added or changed; elsewhere it is inconclusive. A criterion
  whose every test reads a dependency and no project code is recorded as **discrimination not applicable**
  (`via: not_applicable`), and the judge sees the label.
- **The base run confirms or says nothing** (L4-IMP-003). Only the zero-value run can show that a test does not
  discriminate; a base run that cannot run a candidate leaves it inconclusive.
- **An inconclusive check never counts against the agent** (L4-IMP-063, L4-IMP-017). When every unconfirmed criterion
  is inconclusive, the task is held with one question of the new kind `harness`: no attempt is used, no profile
  escalates, the unit waits in `awaiting_human`, and a plan waits without chaining runs. The answer `accept: …`
  takes the already-satisfied claim on the evidence of the real run (audited: `via: human_override`, the question and
  the answer digest); `retry: …` runs the check again, for example after an L4 upgrade. A person answers, or an agent
  where `clarifier.answer_by_agents` is true on the base (L4-QMD-004, L4-QMD-009). A criterion that a run shows to be
  not discriminating still fails the attempt as today.
- **Evidence without artifacts** (L4-IMP-064). `gate.finished` and `task.attempt_failed` carry a bounded, redacted
  excerpt (the `E` lines) in the committed ledger; `check.inconclusive` records the hold; the gate line of a run that
  ran no test drops `(expected: …)`; the artefacts line says when nothing was uploaded.
- **Status says it is the harness** (L4-OPS-006). `l4 status --unit`, `l4 plan` and the plan's waiting detail name the
  harness question and the two answers.
- **The verifier tells inconclusive from rejected** (L4-VER-050, L4-VER-051, L4-VER-009). An audit test whose
  zero-value run is inconclusive is recorded `inconclusive`, with no finding; an extra test says why it has no proof; a
  test chore whose check cannot decide is held with a harness question; unproven pre-satisfied evidence is labelled for the
  judge.

Not in this change:
- a gate-logs-only upload (`ci.upload_artifacts: gates`): the ledger excerpt now carries the evidence that was missing,
  a gate log of a public repository holds test output that redaction may not fully cover, and the key would change
  from a boolean to a union in an urgent release;
- a skipped base run (a changed manifest, a symlink, no unit base) stays what it is today; only runs that were made
  are classified (see the open questions in `design.md`);
- other languages: the zero-value run stays Python-only.

## Capabilities

### New Capabilities

- `variant-runs`: one classification of every variant run against the real run, keep-going, and zeroing that keeps
  imports working (L4-IMP-060, L4-IMP-061, L4-IMP-062).
- `held-checks`: an inconclusive check holds the task with a `harness` question instead of failing the attempt, and
  the evidence reaches the ledger and the status (L4-IMP-063, L4-IMP-064).
- `verifier-variants`: the audit and the extra proofs use the same classification, and the judge sees unproven
  pre-satisfied evidence (L4-VER-050, L4-VER-051).

### Modified Capabilities

None as an OpenSpec delta with a baseline: `openspec/specs/` holds none, so the MODIFIED blocks restate the changed
clauses of L4-IMP-002, L4-IMP-003, L4-IMP-017, L4-QMD-004, L4-QMD-009, L4-OPS-006 and L4-VER-009, and `tasks.md`
group 8 edits `docs/SPEC.md`, the normative text.

## Impact

- `src/l4/gates/junit.py` (collection details, the setup phase), a new `src/l4/gates/collection.py` (the audit's
  extraction, moved), a new `src/l4/implementer/variant.py` (the classifier), `src/l4/implementer/stubs.py`,
  `src/l4/implementer/discrimination.py`, `src/l4/implementer/base_run.py`, a new `src/l4/implementer/held.py`,
  `src/l4/implementer/tdd.py`, `src/l4/implementer/loop.py`, `src/l4/implementer/workbench.py`,
  `src/l4/implementer/earlier_red.py`, `src/l4/specs/questions.py`, `src/l4/specs/questions_cli.py`,
  `src/l4/clarifier/clarifier.py`, `src/l4/implementer/unfreeze.py`, `src/l4/verifier/audit.py`,
  `src/l4/verifier/ladder.py`, `src/l4/verifier/traceability.py`, `src/l4/verifier/types.py`,
  `src/l4/verifier/report.py`, `src/l4/verifier/verdicts.py`, `src/l4/verifier/judge.py`, `src/l4/progress.py`,
  `src/l4/orchestrator.py`, `src/l4/planner.py`, `src/l4/state/next_step.py`, the job summary writer; tests under
  `tests/unit/`.
- `docs/SPEC.md` (L4-IMP-060..064, L4-VER-050..051, the MODIFIED clauses, L4-STA-001's records, §6.2's kind list,
  SCN-IMP-300..319, SCN-VER-150..155, the change row), `docs/runbook.md`, `CHANGELOG.md` (`## 0.4.16 (unreleased)`).
- No configuration key is added. `questions.md` gains the kind `harness`; a harness before 0.4.16 reads such a
  question as one of no known kind (it blocks its task while open).
