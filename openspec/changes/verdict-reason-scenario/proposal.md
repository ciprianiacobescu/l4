# A reject's scenario survives the reason's cut, and fix-unit text keeps its code brackets

## Why

A consumer's delegate rejected a judge finding with a reason of 1,207 characters that ended, as the question asks, with
`WHEN after seedTwoTenants(db) the owner inserts tenant_c … THEN a test asserts that [...DEFAULT_ROLES].sort() deep-equals
["approver", "auditor", "author", "tenant_admin"] and that …`. A second reject of the same unit had 1,264 characters. The
fix unit's spec got the scenarios `THEN a` and `THEN a test asserts that [...DEFAULT_ROLES].sort() deep-equals [`, and its
proposal and task text read `(...DEFAULT_ROLES).sort() deep-equals (` [V, 0.4.45, 2026-10-31; `questions.md` holds the
whole answers, `verdict.json` the cut ones].

Causes [V, read in the 0.4.46 code]:

- `verdicts.record_human_verdicts` stores `reason=parsed[1][:1000]` in `human.verdict`, and `fixunit.when_then` reads the
  scenario from that stored reason. The question tells the person to END the reason with the `WHEN … THEN …` sentence, so
  every reason longer than 1,000 characters loses exactly the part that becomes the fix unit's check.
- `openspec._plain` (and Kiro's `_line`) turn every `[` and `]` of model-written text into `(` and `)`, so that the text
  cannot carry a `[tag]` that exempts a rule. Code in the text (`[...DEFAULT_ROLES]`, `["approver", …]`) is changed too, and
  the implementer reads a different expression from the one the person wrote.

## What changes

- `human.verdict.reason` keeps up to 4,000 characters. A longer reason that has a `WHEN … THEN …` sentence keeps that
  sentence whole (from its last `WHEN`) and cuts the text before it, marked ` … `; a sentence that is itself longer than
  the limit is cut at its end as before.
- Model- and person-written text that becomes a fix unit's heading, task or proposal line turns a bracket into a
  parenthesis only where it could form a tag: a pair whose content is letters, digits, `_`, `-` and spaces only (`[test-infra]`,
  `[ ]`), and every bracket that has no partner. Any other pair stays as written.
- Not changed: the scenario text of a fix unit's spec (already written as given), the delegate's own 1,000-character limit
  on its reply, `l4 yolo go --reason`, the rule that a human tag exempts nothing in a fix or follow-up unit.

## Impact

- Code: `l4.verifier.verdicts` (`record_human_verdicts`, a bounded reason), `l4.specs.openspec` (`_plain`),
  `l4.specs.kiro` (`_line`), one shared helper for the brackets.
- Spec: L4-VER-059 and L4-IMP-006 (7) amended; SCN-VER-262 to SCN-VER-264; change-table row 108.
