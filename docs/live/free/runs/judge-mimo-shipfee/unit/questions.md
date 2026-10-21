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
| Q-001 | open | none | verdict | Finding F-a9b4629a: shipping_fee ignores subtotal: no free shipping at 50.00 or more |
| Q-002 | open | none | verdict | Finding F-a0fac71a: Negative subtotal does not raise ValueError |
<!-- l4:index:end -->

---

## Q-001: Finding F-a9b4629a: shipping_fee ignores subtotal: no free shipping at 50.00 or more

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a blocker finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8). It reports behaviour that no scenario pins down.

Title: shipping_fee ignores subtotal: no free shipping at 50.00 or more
Detail: The spec requirement states an order to RO or DE whose subtotal is 50.00 or more ships free (fee 0.00), but src/pricing/shipping.py never reads the subtotal argument; it only looks up the country. shipping_fee(Decimal('50.00'), 'RO') therefore returns 4.99 instead of 0.00, so checkout would overcharge shipping on qualifying orders. No criterion scenario or gate test covers this input, and no suppression comment was declared for it.
Suggested fix: WHEN subtotal is 50.00 or more and country is RO THEN shipping_fee returns Decimal('4.99') instead of Decimal('0.00').

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
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8). It reports behaviour that no scenario pins down.

Title: Negative subtotal does not raise ValueError
Detail: The spec requirement says the subtotal is checked first and a negative subtotal SHALL raise ValueError, but the committed shipping_fee ignores subtotal entirely and returns the country fee for any negative value. No criterion scenario covers negative subtotals, so no gate test exercises this path.
Suggested fix: WHEN subtotal is a negative Decimal such as Decimal('-1.00') and country is RO THEN shipping_fee returns Decimal('4.99') instead of raising ValueError.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
