# Questions — add-greeting

<!-- l4:questions v1
How to answer: write under "### Answer" and set **Status** to `answered`.
To accept the clarifier's suggestion as-is, set **Status** to `accepted`.
Status values: open · answered · accepted · answered-by-clarifier · dismissed · superseded
Kind values: technical · product · ambiguous · verdict. For a `verdict` question, start the answer with `accept` or
`reject`, then give your reason.
Do not change question IDs. Commit and push to the l4/… branch to resume the run. -->

<!-- l4:index:start -->
| ID | Status | Blocking | Kind | Question |
|----|--------|----------|------|----------|
| Q-001 | answered | 1.1 | ambiguous | Should a greeting trim the name? |
<!-- l4:index:end -->

---

## Q-001: Should a greeting trim the name?

- **Status:** answered
- **Blocking tasks:** 1.1
- **Kind:** ambiguous
- **Asked:** 2026-01-01T00:00Z by implementer, run r-20260101T0000Z-0000, task 1.1

### Context
The scenario says "Hello, <name>!" but does not say what happens to surrounding spaces.

### Options
1. trim it
2. keep it as given

### Answer
<!-- write below this line -->
Trim it: `greet("  Ada ")` is `Hello, Ada!`.
