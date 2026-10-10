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
| Q-001 | open | 1.1 | technical | `is_empty` interface |
<!-- l4:index:end -->

---

## Q-001: `is_empty` interface

- **Status:** open
- **Blocking tasks:** 1.1
- **Kind:** technical
- **Asked:** 2026-10-04T11:01Z by codex, run r-20261004T1101Z-aea2, task 1.1

### Context
The design leaves open whether callers should use `cart.is_empty()` or `cart.is_empty`. The spec names `Cart.is_empty()`; confirm that it should be a method.

### Options
1. Use a method: `cart.is_empty()`
2. Use a property: `cart.is_empty`

### Clarifier suggestion
confidence: high · kind: technical (S1 p=0.00) · needs a human

Make it a method: `cart.is_empty()`, i.e. `def is_empty(self) -> bool: return not self.items`. The spec delta says `Cart.is_empty()`, and the design says to follow `Cart`'s own conventions. `Cart` gives its derived values as plain methods (`subtotal()`, `total()`). The only `@property` in the file is on `LineItem`, not `Cart`.

Citations:
- `specs/cart-state/spec.md#L9`: "`Cart.is_empty()` SHALL return True when the cart holds no line items and False otherwise."
- `design.md#L4`: "Follow the existing conventions of `Cart` in `src/pricing/cart.py`."
- `src/pricing/cart.py#L34-L35`: "def subtotal(self) -> Decimal: return sum((item.total for item in self.items), Decimal(0))"

### Answer
<!-- write below this line -->
