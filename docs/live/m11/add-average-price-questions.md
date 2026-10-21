# Questions — add-average-price

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
| Q-001 | accepted | 1.1 | technical | Return type of average_unit_price |
<!-- l4:index:end -->

---

## Q-001: Return type of average_unit_price

- **Status:** accepted
- **Blocking tasks:** 1.1
- **Kind:** technical
- **Asked:** 2026-10-04T10:48Z by codex, run r-20261004T1047Z-7e16, task 1.1

### Context
The design lists this as an open technical question. Should Cart.average_unit_price() return Decimal or float?

### Options
1. Decimal
2. float

### Clarifier suggestion
confidence: medium · kind: technical (S1 p=n/a) · needs a human

Return Decimal. Compute subtotal() / Decimal(total quantity), then .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), the same way Cart.total() does it. Raise ValueError when there are no items. Quantizing with ROUND_HALF_UP only works on Decimal, the subtotal is already a Decimal, and the existing tests compare money with Decimal values. In tests, compare against Decimal("2.50"), Decimal("2.00") and Decimal("0.03").

Citations:
- `specs/cart-stats/spec.md#L9`: "`Cart.average_unit_price()` SHALL return the cart subtotal divided by the total quantity of its line items, quantized to 0.01 with ROUND_HALF_UP."
- `src/pricing/cart.py#L50`: "return max(total, Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)"
- `openspec/specs/cart/spec.md#L20`: "The cart SHALL compute its subtotal as the exact Decimal sum of its line totals."

### Answer
<!-- write below this line -->
