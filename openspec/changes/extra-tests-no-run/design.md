# Design: a test no run can vary is inconclusive

## D1. The condition is "no run can be made", not "the project is not Python"

`discriminate_extra` computes the zero-value scope (`imported_modules(wb, wanted) | _changed_modules(wb)`) and the
base run's files (`production_changes(wb, base_sha)`) first. When `wanted` is not empty and both are empty, it returns
`ExtraRun(rejected=wanted, inconclusive={test: NO_RUN})`, with no gate run and `runs` 0. Otherwise it goes on as
before: computing `production_changes` before the zero-value run instead of after changes nothing, because it reads the
committed diff `base..HEAD`, which the zero-value run does not touch (it puts every file back by sha256).

The gate's language (`is_python_gate`) is not the test: `make test` runs pytest in many Python projects, and a mixed
project runs both. Whether a run has anything to vary is what decides whether it can say anything, and it is what
the two runs already compute.

## D2. Inconclusive, not accepted

L4-VER-050 says a run that could not decide is no proof and no rejection, and that a test chore whose tests are all
inconclusive is held with a harness question (L4-IMP-063, `check: tests`). Making no run is the strongest form of not
deciding. Accepting the tests instead would let a chore in a project whose code is not Python pass with any test that
passes, which is the hole the chore check closes (W-C1). The hold keeps a person, or an agent where
`clarifier.answer_by_agents` allows it, in the decision, with the tests' sources in the question; `accept` replays the
saved step under every guard and gate.

## D3. The question says no run was made

`_discriminating_tests` built the hold with `runs=("test-extra-zero", "test-extra-base")` always. The question prints
them as `Runs: test-extra-zero, test-extra-base`, which would send whoever answers to look for logs that do not exist.
The hold names them only when `outcome.runs` is above 0, so this case reads `Runs: none`. The reason line carries
`NO_RUN`, which says both runs vary Python files only and there is none to vary.

## D4. What does not change

- Step 4 (`_extra_proof_step`) already writes `inconclusive: <reason>` for an inconclusive test; it now shows
  `NO_RUN` instead of `passes against the zero values and on the base`. Either way the test is no proof and a minor
  finding.
- A Python unit that changed Python production code, or whose added tests import a project module, makes the same
  runs and gets the same answers as before.
- A Python unit that changed no Python production code and whose added tests import no project module used to reject
  them; they are now inconclusive (held for a chore, an inconclusive minor finding in step 4). This follows D2, and a
  hold is no pass.

## D5. Out of scope

- A zero-value run or a base run for other languages. The base run of L4-IMP-003 (`base_run._plan`) is already
  language-neutral, but a test of a module the unit added cannot import at the base there either, and an error at
  the base is no proof (L4-VER-009). That is a separate change, with its own scenarios for compiled languages.
- A chore's attempts never escalate to the next implementer profile (`implementer.loop` returns before escalation for
  the single phase). With this change a chore whose tests no run can vary is held before it uses an attempt, so the
  stop that made the gap visible does not depend on it.
