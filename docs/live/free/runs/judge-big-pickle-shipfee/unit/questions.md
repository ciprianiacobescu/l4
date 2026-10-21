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
| Q-001 | open | none | verdict | Finding F-e1ceafd0: subtotal is ignored: free-shipping threshold and negative-subtotal check are missing |
<!-- l4:index:end -->

---

## Q-001: Finding F-e1ceafd0: subtotal is ignored: free-shipping threshold and negative-subtotal check are missing

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it (criterion C-e25f06d8).

Title: subtotal is ignored: free-shipping threshold and negative-subtotal check are missing
Detail: The spec's Shipping fee requirement says a subtotal of 50.00 or more to RO/DE ships free (fee 0.00) and a negative subtotal SHALL raise ValueError checked first. src/pricing/shipping.py never reads the subtotal argument: it looks up a flat fee by country and quantizes it, so shipping_fee(Decimal("50.00"), "RO") returns 4.99 instead of 0.00 and shipping_fee(Decimal("-1.00"), "RO") returns 4.99 instead of raising ValueError. Both required behaviours of the committed requirement are absent.
Suggested fix: WHEN the subtotal is 50.00 or more for RO/DE or negative for any country THEN the committed code ignores it and returns the flat country fee (or raises UnsupportedShippingCountry for other countries) instead of 0.00 or ValueError.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
