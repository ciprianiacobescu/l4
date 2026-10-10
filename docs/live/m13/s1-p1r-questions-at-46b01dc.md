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
| Q-001 | open | none | verdict | Finding F-f2c8f81d: Free shipping at subtotal >= 50.00 not implemented |
| Q-002 | open | none | verdict | Finding F-a0fac71a: Negative subtotal does not raise ValueError |
<!-- l4:index:end -->

---

## Q-001: Finding F-f2c8f81d: Free shipping at subtotal >= 50.00 not implemented

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8).

Title: Free shipping at subtotal >= 50.00 not implemented
Detail: The requirement says an order to RO or DE with a subtotal of 50.00 or more ships free (fee 0.00). shipping_fee never reads subtotal, so shipping_fee(Decimal('50.00'), 'RO') returns 4.99 instead of 0.00. No criterion or scenario covers this, so the gate cannot catch it.
Suggested fix: Return Decimal('0.00') when subtotal >= Decimal('50.00') for a supported country, and add scenarios for the threshold.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
---

## Q-002: Finding F-a0fac71a: Negative subtotal does not raise ValueError

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8).

Title: Negative subtotal does not raise ValueError
Detail: The requirement says the subtotal is checked first and a negative subtotal SHALL raise ValueError. The code has no such check: shipping_fee(Decimal('-1'), 'RO') returns 4.99, and shipping_fee(Decimal('-1'), 'FR') raises UnsupportedShippingCountry instead of ValueError.
Suggested fix: Raise ValueError when subtotal < 0 before the country lookup, and add a scenario for it.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
