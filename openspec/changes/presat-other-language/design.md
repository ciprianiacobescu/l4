## Context

`run_red` (L4-IMP-002) sends the criteria whose new tests all pass at head through three checks: an earlier red of the
unit (`confirmed_by_earlier_red`), the zero-value run (`confirm_pre_satisfied`), and the base run
(`confirmed_by_base_run`), which only confirms. `combine` keeps the zero-value run's refutations, and its inconclusive
criteria that the base run did not confirm; `_decide_pre_satisfied` fails the attempt on a refuted criterion and holds
the task on an inconclusive one.

The zero-value run zeroes the public functions of Python modules. `confirm_pre_satisfied` refutes every criterion when
that scope is empty ("no project source module is imported by those tests"), and `variant.judge` refutes a criterion
whose tests all passed in the zero-value run. Neither looks at the language of the test.

`discriminate_extra` (L4-VER-050) already handles the same gap for the verifier's extra proofs: a test that no run
accepted, whose file `file_of_id` finds and whose extension is in `OTHER_LANGUAGES`, is inconclusive with `NOT_PYTHON`,
unless a run reached it (it failed there by an error).

## Goals / Non-Goals

**Goals:** a criterion whose tests a Python-only run cannot reach is never refuted by that run; the task is held for a
decision instead. Python projects behave as before.

**Non-Goals:** a zero-value run for other languages; a change to the base run, to `combine`, or to the hold and its
answers; the `zero is None` exit ("no readable report"), which keeps its rule.

## Decisions

### D1. The rule is per test, then per criterion (L4-IMP-060)

A new test of a candidate criterion is *out of reach* when `file_of_id(test, worktree_files(wb), own_test_files(wb))`
finds its file, the file ends with one of `OTHER_LANGUAGES`, and the zero-value run did not reach it. "Reached" means
the run's report holds the test with status `failed` or `error`. A test that failed by assertion is a proof anyway; a
test that failed by an error was reached, so it counts as "none" as today. An out-of-reach test is inconclusive with
`PRE_NOT_PYTHON = "the zero-value run varies Python files only, and {file} is not a Python file"`.

A criterion is then confirmed when any of its tests is a proof; inconclusive when none is and any is inconclusive
(an out-of-reach test, or one the run did not run); refuted only when every one of its tests ran and none is a proof.
So a criterion with one Python test that passed in the zero-value run and one TypeScript test is inconclusive.

*Alternative rejected:* refute a criterion only when all its tests are Python. A mixed criterion's TypeScript test
says nothing in that run, and L4-IMP-060 already makes "any inconclusive" decisive.

### D2. Both exits apply it

At the empty-scope exit no run is made: every out-of-reach test is inconclusive, so a criterion with only such tests is
inconclusive with the reason naming the first one's file. The other criteria stay refuted with today's reason. After a
zero-value run, a criterion that `variant.judge` refuted is looked at again: if any of its tests is out of reach, it
moves to inconclusive with that test's reason. A criterion that the run confirmed, or left inconclusive for its own
reason, is not touched.

### D3. A hold, never a pass

An inconclusive criterion goes to the base run, as today (the base run gets `confirmation.unconfirmed` and
`confirmation.inconclusive`). If the base run confirms it, it counts on that evidence. If not, `combine` keeps it
inconclusive and `_decide_pre_satisfied` holds the task with a `pre_satisfied` harness question whose reason is the
`PRE_NOT_PYTHON` text. Only an `accept` (a person's, or the delegate's where `delegate.kinds` allows `harness`) lets the
criterion count, on the evidence of the real run. A `retry` answer sends the step back to the implementer. A vacuous
test in a project that is not Python is therefore held, not failed at once; the question names the tests, so the person
who accepts it reads them first.

### D4. The file lookup is the one the verifier uses

`file_of_id` resolves `src.durable.queue.test.ts::name` (a reporter's dotted path) to `src/durable/queue.test.ts`, and a
plain path to itself. A test whose file is not found keeps today's rules, as in `discriminate_extra`: the empty-scope
exit still refutes it. The work tree is listed once per call (`worktree_files`), and only when a criterion was refuted.

### D5. The hold shows the evidence that was gathered

A confirmation that made no zero-value run (the empty scope, no readable report, a dependency-only criterion) says so:
`PreSatisfied.ran` is false, and the hold's `Runs:` line names `test-presatisfied` only when `ran` is true. The base run
records for a criterion it neither confirmed nor left inconclusive what it showed (`BaseRunResult.seen`: every new test
passes against the unit base code too, or its new tests fail there only by an error), and `combine` ends an inconclusive
criterion's reason with that note, after the base run's own inconclusive reason. A person who reads the question sees
that the tests pass at the unit base too, or only error there, and decides on that. The `zero is None` exit applies the
rule of the empty-scope exit, and a test the run holds as `skipped` counts as reached, like `failed` and `error`
(L4-IMP-060: a test that skipped only in the zero-value run is no proof, never inconclusive).

## Risks / Trade-offs

- An agent in a TypeScript project can turn a "not discriminating" attempt into a hold with tests that pass at head.
  The hold costs a person's or the delegate's decision, not a pass; the question lists the tests and the reason, and a
  `retry` answer sends the step back. The same trade was made for the verifier's extra proofs in change 82.
- A Python test in a mixed project whose criterion also has a TypeScript test is no longer refuted on its own. The
  criterion is held instead; L4-IMP-060 already says a criterion with an inconclusive test is inconclusive.
- A Python test whose id's head is also the dotted path of a file of another language, such as a sibling `pkg/api.js`
  of `pkg/api/js.py`, or a pytest plugin that collects `.js` files as items, is held instead of refuted. That is a
  hold, never a pass.
- Report ids built from package or namespace names (Go, Java, C#) do not resolve through `file_of_id`, so those tests
  keep today's rule. The fix covers ids that name the file (TypeScript, JavaScript and the like).
