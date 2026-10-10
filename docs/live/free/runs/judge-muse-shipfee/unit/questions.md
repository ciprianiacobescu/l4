# Questions — add-shipping-fee

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
| Q-001 | open | none | verdict | Finding F-5175c35c: Missing free-shipping threshold for subtotal >= 50.00 |
| Q-002 | open | none | verdict | Finding F-d7b153ad: Missing ValueError for negative subtotal |
<!-- l4:index:end -->

---

## Q-001: Finding F-5175c35c: Missing free-shipping threshold for subtotal >= 50.00

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8).

Title: Missing free-shipping threshold for subtotal >= 50.00
Detail: Spec requires RO/DE orders with subtotal 50.00 or more ship free (0.00), but implementation ignores subtotal and always returns 4.99/9.99.
Suggested fix: Add check returning Decimal 0.00 quantized when subtotal >= 50.00 for RO/DE after negative check.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
---

## Q-002: Finding F-d7b153ad: Missing ValueError for negative subtotal

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8).

Title: Missing ValueError for negative subtotal
Detail: Spec requires negative subtotal SHALL raise ValueError checked first, but implementation has no ValueError check; RO/DE returns fee, other raises Unsupported.
Suggested fix: Raise ValueError when subtotal is negative before country lookup.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
