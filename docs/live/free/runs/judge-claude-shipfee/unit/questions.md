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
| Q-001 | open | none | verdict | Finding F-7c9ce448: Free shipping at subtotal >= 50.00 is not implemented |
| Q-002 | open | none | verdict | Finding F-01bdf4ad: A negative subtotal does not raise ValueError and is not checked first |
<!-- l4:index:end -->

---

## Q-001: Finding F-7c9ce448: Free shipping at subtotal >= 50.00 is not implemented

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8).

Title: Free shipping at subtotal >= 50.00 is not implemented
Detail: The requirement says an order to RO or DE whose subtotal is 50.00 or more ships free (fee 0.00). shipping_fee never reads subtotal, so shipping_fee(Decimal('50.00'), 'RO') returns 4.99 instead of 0.00. No criterion scenario covers this, but the requirement text does.
Suggested fix: Return Decimal('0.00') when subtotal >= Decimal('50.00') and country is RO or DE, and add scenarios for subtotals of 50.00 and 49.99.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
---

## Q-002: Finding F-01bdf4ad: A negative subtotal does not raise ValueError and is not checked first

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8).

Title: A negative subtotal does not raise ValueError and is not checked first
Detail: The requirement says the subtotal is checked first and a negative subtotal SHALL raise ValueError. The code has no such check: shipping_fee(Decimal('-1'), 'RO') returns 4.99, and shipping_fee(Decimal('-1'), 'FR') raises UnsupportedShippingCountry instead of ValueError.
Suggested fix: Raise ValueError when subtotal < 0 before looking up the country, and add scenarios for it.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
