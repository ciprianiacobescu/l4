# Questions — add-pallet-count

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
| Q-001 | open | none | verdict | Finding F-a56f7c86: A zero or negative per_pallet is not rejected |
<!-- l4:index:end -->

---

## Q-001: Finding F-a56f7c86: A zero or negative per_pallet is not rejected

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-97b5cb90). It reports behaviour that no scenario pins down.

Title: A zero or negative per_pallet is not rejected
Detail: The proposal says a positive per_pallet is required, but the code does not check it. With per_pallet=0, Python's division raises ZeroDivisionError. With a negative per_pallet the function silently returns a negative count, e.g. pallet_count(100, -50) == -2. No scenario covers this case.
Suggested fix: WHEN the warehouse calls inventory.pallets.pallet_count(100, -50) THEN it returns -2.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
