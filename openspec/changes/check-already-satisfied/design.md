## Context

The red step of L4-IMP-002/003 must add new test functions. When the new tests pass at once, the harness confirms that
they discriminate: by an earlier red of the unit that saw tests of the same criterion fail, by the zero-value run, or by
the base run. Then it commits the task as `already satisfied`. OpenSpec tasks carry no link to scenarios, so the red
prompt lists every criterion of the unit, and the agent cites the ones "this task's requirement names". In a unit with
one requirement, every task cites all of them.

## Decisions

**D1. Reuse what exists; do not delete what was written.** A red step may add no test, and the tests that already
trace each cited criterion become its candidates. The harness never removes a test, so nothing about the frozen-test
rules changes. A step that adds tests keeps today's path.

**D2. The reason is required only when no test is added.** With new tests, the harness proves the claim from those
tests, and today's code does not read `tdd_exemption`. Requiring it there would fail steps that pass today. With no
test, the reason is the only sign that the agent meant "already done" and did not just forget the tests. So it is
required there, and it must start with `already_satisfied`.

**D3. The same confirmation, the same order.** The candidates are the passing tests that trace the criterion: the
earlier red, then the zero-value run, then the base run. These are the rules that hold for new tests. A test that an
earlier step let pass stays no evidence for the earlier red, as SCN-IMP-72 says. The base run can still confirm it,
because it swaps the unit's production changes back to the unit base.

**D4. The task-text check is the judge's, and a person decides.** Only a reader of the task's prose can tell that task
3.1 (a README line) is not done while its criteria are. The harness cannot: 2.1 (already done by 1.1's green) and 3.1
look the same to it. The judge is the independent reader. Its `holds: false` is a judge-only major finding, so
L4-VER-013 puts it to a person. A deterministic fail would loop when the task's work sits in base code that the diff
does not show.

**D5. A missing answer is minor.** The judge left optional arrays out of long prompts (0.4.6, 0.4.7). The second call
of L4-VER-017 asks again. A task that is still not answered is a minor finding, never a failed round.

**D6. Only the unit's own tasks.** A fix unit's task comes from a finding. When it ends already satisfied, the judge
judges that finding again in the same round anyway.

## Risks

- An agent may now take the no-test path for a task whose text is not done (D4 is the guard; the skill and template
  rules come first).
- The block lengthens the judge prompt by a few hundred characters per task; 25 tasks across four units were already
  satisfied, so a unit adds about 1-15 entries.
