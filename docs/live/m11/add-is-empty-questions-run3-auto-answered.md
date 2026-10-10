# Questions — add-is-empty

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
| Q-001 | answered-by-clarifier | 1.1 | technical | Should `is_empty` be a method (`cart.is_empty()`) or a property (`cart.is_empty`)? Follow the exist… |
<!-- l4:index:end -->

---

## Q-001: Should `is_empty` be a method (`cart.is_empty()`) or a property (`cart.is_empty`)? Follow the exist…

- **Status:** answered-by-clarifier
- **Blocking tasks:** 1.1
- **Kind:** technical
- **Asked:** intake (open questions in design.md)

### Context
(technical) Should `is_empty` be a method (`cart.is_empty()`) or a property (`cart.is_empty`)? Follow the existing conventions of `Cart` in `src/pricing/cart.py`.

Listed under "Open questions" in design.md.
Open-question-hash: 42ac3d7ba4bec213

### Clarifier suggestion
confidence: high · kind: technical (S1 p=0.00)

Make it a method: `def is_empty(self) -> bool`, called as `cart.is_empty()`. The spec delta requires `Cart.is_empty()` in call form. This also matches how `Cart` already works: its computed facts are plain methods (`subtotal()`, `total()`), not properties. Return True when `self.items` is empty and False otherwise.

Citations:
- `specs/cart-state/spec.md#L9`: "`Cart.is_empty()` SHALL return True when the cart holds no line items and False otherwise."
- `src/pricing/cart.py#L34-L35`: "def subtotal(self) -> Decimal: return sum((item.total for item in self.items), Decimal(0))"

### Answer
<!-- write below this line -->
