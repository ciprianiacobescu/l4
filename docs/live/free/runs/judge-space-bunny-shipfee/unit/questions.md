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
| Q-001 | open | none | verdict | Finding F-a82d3464: Free-shipping threshold for RO/DE subtotals of 50.00 or more is not implemented |
| Q-002 | open | none | verdict | Finding F-5a4c0955: Negative subtotal does not raise ValueError |
<!-- l4:index:end -->

---

## Q-001: Finding F-a82d3464: Free-shipping threshold for RO/DE subtotals of 50.00 or more is not implemented

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8).

Title: Free-shipping threshold for RO/DE subtotals of 50.00 or more is not implemented
Detail: The requirement states "an order to `RO` or `DE` whose subtotal is 50.00 or more ships free (fee 0.00)", but the committed function never reads `subtotal`: it looks up the country in a two-entry table and returns the fee. shipping_fee(Decimal("50.00"), "RO") therefore returns 4.99 and shipping_fee(Decimal("50.00"), "DE") returns 9.99. No criterion covers the threshold (both criteria are explicitly below it), so this is invisible to the traceability matrix and to the gate report, but it is a normative SHALL in the same requirement the implementation claims to satisfy. `subtotal` is an unused parameter, which is the direct cause.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
---

## Q-002: Finding F-5a4c0955: Negative subtotal does not raise ValueError

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it.

Title: Negative subtotal does not raise ValueError
Detail: The requirement says "The subtotal is checked first: a negative subtotal SHALL raise ValueError". The committed implementation performs no subtotal check at all, so shipping_fee(Decimal("-1.00"), "RO") returns Decimal("4.99") instead of raising. "checked first" also implies ordering that the code does not implement: for an unknown country with a negative subtotal the requirement implies ValueError, while the code raises UnsupportedShippingCountry because the country lookup happens first and the subtotal is never consulted. No listed criterion covers this.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
