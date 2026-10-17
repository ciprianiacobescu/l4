## Why

A plan on a consumer repository (harness 0.4.7) delivered four units. The red step of 25 of their tasks found the work
already done and ended `already satisfied`. Three defects showed up.

1. **Every already-satisfied task wrote a new copy of tests that already existed.** A red step must add new test
   functions (`NO_NEW_TEST`, red template rule "The tests must be NEW test functions with new names"), even when an
   earlier task of the unit already wrote and proved the tests of every criterion it cites. OpenSpec does not link
   tasks to scenarios, so a one-requirement unit's tasks all cite the same criteria. In one unit, tasks 2.1 (the fix,
   already done by the green step of 1.1), 3.1 (a README line) and 4.1 (run the gates) each added a near-copy of
   1.1's test class: four classes that assert one contract. Across the four units, already-satisfied steps added
   about 4,400 lines of tests. The judge reported it as a finding.
2. **Earlier-red evidence never holds for tests in a class.** `earlier_red._test_file` turns a pytest JUnit id into a
   path by replacing dots: `packages.core.tests.test_config.TestNoteSettingsEnvNames::test_x` becomes
   `packages/core/tests/test_config/TestNoteSettingsEnvNames.py`, which does not exist. The confirmation by an
   earlier red (L4-IMP-003) then confirms nothing, and each criterion goes on to the zero-value run and the base run.
   In that unit all 15 pre-satisfied confirmations went `via: base_run` and none `via: earlier_red`. The outcome was
   right, but it took extra gate runs, and the ledger names the wrong proof.
3. **A task can be ticked without its own work.** Task 3.1 asked for "(legacy alias `X`)" in a README table. Its red
   step cited the unit's five configuration criteria, which an earlier green already satisfied, so the harness ticked
   the task `already satisfied`. The README never changed. The round passed 5/5, because no criterion covers that
   line, and nothing asked whether the task's text was done.
4. **A test fixture shaped like a token halts the unit.** In the fifth unit, a red step wrote a redaction test whose
   fixture spells a token whole (`"mk_agent_…"`), as the file's existing tests do. The push scan (L4-SEC-007) refused
   the push, which is right, but it halted the unit and stopped the plan: the agent was never told that a fixture must
   not match a token shape, and the retry that the halt offers would make the same mistake on the unit's last attempt.

## What Changes

- **A test id names its file, class or not** (L4-IMP-003). The earlier-red check finds a test's file the way the
  zero-value run does: it drops dotted parts from the end until a `.py` file exists, here at the red commit.
- **An already-satisfied task may add no test** (L4-IMP-003). A red step may add no test, change no file, and report
  `criteria_ids` and `tdd_exemption.reason` naming the earlier task or commit. Then the tests that already trace each
  cited criterion and pass at head are its proof. They go through the same confirmation as new tests: the earlier
  red, the zero-value run, then the base run. When every cited criterion is confirmed, the harness commits
  `test(<unit>): <task> already satisfied` with no test change and skips green. A cited criterion that no passing test
  traces, or that nothing confirms, fails the step with a message that names it and says to write a new test for it.
  A step that adds no test and gives no reason fails as today (`no tests added`).
- **The judge checks every task ticked as already satisfied** (L4-VER-018). The judge prompt gets a block that lists
  the unit's tasks the harness ticked `already satisfied`: each one's key, its text from `tasks.md`, the criteria it
  cited and the tests that proved them. The reply answers `satisfied: [{task, holds, evidence}]`, one entry per task:
  `holds` is true only when the diff or the gate report shows that the code and documents do what the task's text
  says. `holds: false` is a major judge finding, which goes to a person as any judge-only major finding does
  (L4-VER-013). A task left out of the reply is asked again (L4-VER-017's second call). A task still left out is a
  minor finding, so a missing answer never fails a round.
- **A step's changes are read for secrets before any gate or commit** (L4-SEC-008). The lines the worktree adds go
  through the redactor of the push scan. A hit discards the attempt with a message that names the path and the kind
  and says to build such a value from parts at run time (`"mk_" + "agent_" + "A" * 24`). The next attempt gets the
  message. The contract template says the same up front. The push scan stays as the last net.
- **Prompts and skill.** The red template says when to add no test, and that `already_satisfied` needs the task's
  own text to be true in the code: a task that asks for a change that is not there yet (a document line, say) is not
  already satisfied, whatever its criteria say. The skill's `spec.md` gets a **tasks** rule: put a behaviour's tests in
  the task that implements it, not in a "failing tests" task with a "fix" task after it. Keep gate runs out of
  `tasks.md`. Give a document edit a check that a red step can test.
- **Docs.** `docs/SPEC.md` (L4-IMP-003, L4-VER-018, the scenarios, the change row), `docs/runbook.md`, `CHANGELOG.md`
  (`## 0.4.8 (unreleased)`).

Not in this change:
- a link from an OpenSpec task to its scenarios (OpenSpec has none; a Kiro task already has `_Requirements:_`);
- `validate_plan.py` warnings for a "failing tests" task or a gate-run task (a heuristic; the skill rule comes first);
- removing the duplicate tests the four units already merged (that is the consumer's code).

## Capabilities

### New Capabilities

- `earlier-tests`: an already-satisfied red step reuses the tests that already prove its criteria, and earlier-red
  evidence holds for tests in a class (L4-IMP-003).
- `step-secrets`: an implementer step that writes a token shape fails its attempt with advice, before any gate or
  commit (L4-SEC-008).
- `satisfied-check`: the judge answers, for each task ticked as already satisfied, whether its text is done
  (L4-VER-018).

### Modified Capabilities

None as an OpenSpec delta: `openspec/specs/` holds no baseline. `tasks.md` section 3 holds the `docs/SPEC.md` work.
