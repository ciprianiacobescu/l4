# The skill warns about scenarios the zero-value check cannot prove

## Why

A consumer unit's first task failed red four times, on two implementer models, with the same `not discriminating`
criteria. They were exactly the four scenarios of the spec that describe behaviour the change must keep (a rejected
key still gets 401, a valid key still 200, no key no validation, a bypass path served) [V: the criterion ids computed
with `l4.specs.criteria`]. Such a criterion passes at the base, so L4-IMP-002 proves it only by zeroing every public
function of the modules its tests import and seeing one test fail by assertion. The code under test was a middleware
and a route nested inside `create_app() -> FastAPI`, the module's only public function: zeroed, `create_app` returns
`None`, the tests' app builder fails with an `AttributeError` (an error, not an assertion), and nothing else in the
module can be zeroed. No test an implementer can write makes those criteria pass, so the attempts were spent for
nothing. The spec was written by an agent with the skill, and nothing in the skill warned about this.

## What Changes

- `plugins/l4/skills/l4/references/spec.md` gains one rule, **unchanged behaviour**: a scenario that already holds at
  the base is proven only when zeroing the public functions its tests import makes one fail by assertion, so test a
  public module-level function and assert the type of its result before using it; code nested in a factory cannot be
  zeroed, so its unchanged cases stay with the existing tests and the design's failure cases; logic a test checks
  belongs in a project module (tests that import no project module are held for a person, L4-IMP-062).
- L4-ADO-014 lists the rule and raises the word cap of `references/spec.md` from 450 to 530; SCN-ADO-41 and the two
  docs tests that count the words follow; a new scenario names the rule.

## Impact

- Docs and tests only: `plugins/l4/skills/l4/references/spec.md`, `docs/SPEC.md`, `tests/unit/docs/test_adoption_docs.py`,
  `tests/unit/docs/test_unfreeze_and_answer_docs.py`. No change to how red judges a criterion.
