## Why

The judge never sees the unit's answered questions. The implementer does: every answered question that holds its
task reaches its prompt as an `<l4:data kind="answer">` block (L4-CLR-006, `implementer/tdd.py` `_answers`). The judge's
prompt (`verifier/judge.py` `build_judge_prompt`, called from `verifier/ladder.py` `_judge_step`) holds the family's
spec files (`read_sources`: `proposal.md`, `design.md`, `requirements.md`, `bugfix.md`, the spec deltas), the criteria,
the diff, the gate report, the conventions, the owner changes, the round outputs, the feedback, accepted and satisfied
blocks, the done tasks and the implementer's notes. No answer is in it [V, code read on the 0.4.27 tree].

So when an answer settles or narrows what the spec says ("exit 1, not 2", "reuse the existing helper", "the empty
list is valid input"), the implementer follows the answer and the judge judges the spec text alone. A criterion the
answer narrowed can fail or come back `insufficient_evidence`, and an input the answer settled comes back as a
`spec_gap` finding. Either way the unit goes to `NEEDS_HUMAN`, and a person or the delegate is asked again about a
decision already made. The delegate live test of 2026-10-19 named this gap, and the delegate change left it out of its
scope as "a separate change" (`openspec/changes/delegate-answers/design.md`). How often it costs a round is not
measured [I].

## What Changes

- **The answers block** (L4-VER-065): every judge prompt of a round (whole diff, part, follow-up) carries one
  `<l4:data kind="answer">` block per answered question of the unit's family: `technical`, `product` and `ambiguous`
  questions, and a question of unknown kind. Each block holds the question's title and options as asked, marked as the
  implementer's text, and the effective answer, redacted and bounded. `verdict` and `harness` questions, dismissed,
  superseded and open questions are left out: a person's verdict already reaches the aggregation (L4-VER-013), and a
  harness question is a check of the harness's own.
- **The judge's rule** (L4-VER-066): where an answer settles or narrows what a criterion asks, the judge judges that
  criterion as the answer reads it and names the answer's id in the criterion's reason. An answer never makes a
  criterion pass without evidence, never outweighs a failing gate, and adds no criterion. An input an answer settles
  is no `spec_gap`. The judge prompt becomes `judge@13`.
- **The record**: the round's `verify.judge` event lists the answers shown, by id and `answer_sha256`.

## Impact

- Code: `src/l4/verifier/judge.py` (`SYSTEM`, `PROMPT_VERSION`, `build_judge_prompt(answers=…)`, an `AnswerRef` and its
  renderer), `src/l4/verifier/ladder.py` (`_judge_step` reads the family's questions files and charges the block to
  the judge's context budget), `src/l4/templatelock.py` output (the judge template's version and hash).
- Docs: `docs/SPEC.md` (L4-VER-001's list, L4-VER-065, L4-VER-066, SCN-VER-232 to SCN-VER-238, change-table row 69),
  `CHANGELOG.md` (0.4.28).
- No new configuration key. No ledger schema change beyond one optional field of `verify.judge`.
- A unit with no answered question gets the same judge prompt as before apart from the version and the rule's text,
  so its prompt hash changes once.
