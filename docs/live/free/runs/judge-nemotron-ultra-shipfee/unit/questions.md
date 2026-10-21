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
| Q-001 | open | none | verdict | Finding F-a0fac71a: Negative subtotal does not raise ValueError |
| Q-002 | open | none | verdict | Finding F-92a05baf: Free shipping threshold not implemented |
<!-- l4:index:end -->

---

## Q-001: Finding F-a0fac71a: Negative subtotal does not raise ValueError

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8). It reports behaviour that no scenario pins down.

Title: Negative subtotal does not raise ValueError
Detail: The spec requires that a negative subtotal SHALL raise ValueError, but the shipping_fee function does not validate the subtotal parameter at all; it is accepted and ignored.
Suggested fix: WHEN subtotal is negative THEN the function returns the country fee without raising ValueError

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
---

## Q-002: Finding F-92a05baf: Free shipping threshold not implemented

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8). It reports behaviour that no scenario pins down.

Title: Free shipping threshold not implemented
Detail: The spec requires that orders to RO or DE with subtotal 50.00 or more ship free (fee 0.00), but the shipping_fee function always returns the base country fee regardless of subtotal.
Suggested fix: WHEN subtotal is 50.00 or more for RO or DE THEN the function returns the country fee instead of 0.00

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
