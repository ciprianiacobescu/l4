# Design: unchanged-behaviour-scenarios

## Decisions

**D1. Teach the spec author, do not loosen the check.** L4-IMP-060 counts an error under the zero values as no proof
on purpose: otherwise an agent could turn `not discriminating` into a held task by writing tests that error. The
defect was in the spec, which asked for proofs of code the check cannot reach. The skill is where spec authors (agents
and people) learn the readiness rules, so the rule goes there, next to `testability`.

**D2. A higher word cap.** `references/spec.md` is at its cap (450 words). The new rule needs 69 words, and
every existing rule prevents a review finding, so the cap moves to 530 instead of dropping one.

## Failure cases

- The file above 530 words: the two docs tests fail and name the count.
- The rule missing from the file: the new docs assertion fails.
