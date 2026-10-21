## Why

On a consumer repository (harness 0.4.8), the judge found that a task ticked as already satisfied had not done its
whole text (L4-VER-018: "task 2.3 is ticked as already satisfied, but its text is not done"; the help text and a
docstring were never updated). The runbook says to `reject` that finding with a `WHEN … THEN …`, and the fix unit then
does the work. The delegate did so. The next round failed, as it should, but the fix-unit planner dropped the finding
(`a scenario for it needs a requirement and the parent has several`), so no task was left, the unit escalated with
`no_convertible_finding`, and the delivery plan stopped.

The planner puts a scenario under the cited criterion's requirement, or under the parent's only requirement. The
not-done finding cites no criterion (the task's text, not a criterion, is what is missing), and the parent has eight
requirements, so the person's scenario had no home.

## What Changes

- **A rejected finding's scenario always has a home** (L4-VER-006). When a person rejected a finding that cites no
  criterion with a `WHEN … THEN …` and the parent has several requirements, the scenario goes under an ADDED
  requirement of its own, `<finding title> — finding <id>`, in the parent's first capability by name. A feedback item
  already gets its requirement this way (L4-FBK-004).
- A judge's spec-gap suggestion that no person asked for keeps today's rule: with several requirements and no
  criterion, it is listed as not converted.

## Impact

- `src/l4/verifier/fixunit.py`: `_requirement_for`.
- `docs/SPEC.md`: L4-VER-006, SCN-VER-76 and SCN-VER-77, the change row.
