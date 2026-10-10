# Questions — add-cent-rounding

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
| Q-001 | open | 1.1 | technical | Should `round_cents` take and return `Decimal` or `float`? Follow the amount type that `Cart.subtot… |
<!-- l4:index:end -->

---

## Q-001: Should `round_cents` take and return `Decimal` or `float`? Follow the amount type that `Cart.subtot…

- **Status:** open
- **Blocking tasks:** 1.1
- **Kind:** technical
- **Asked:** intake (open questions in design.md)

### Context
(technical) Should `round_cents` take and return `Decimal` or `float`? Follow the amount type that `Cart.subtotal` and `Cart.total` in `src/pricing/cart.py` use.

Listed under "Open questions" in design.md.
Open-question-hash: baef679cba780ea4

### Clarifier suggestion
confidence: high · kind: technical (S1 p=0.01) · needs a human

Use `Decimal`. `round_cents(amount: Decimal) -> Decimal` should take and return a `Decimal`, the same type `Cart.subtotal()` and `Cart.total()` return. Round with `amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`, which is exactly how `Cart.total()` rounds. In tests, pass `Decimal("2.675")` and expect `Decimal("2.68")`. A float can't hold 2.675 exactly, so it wouldn't reliably round up to 2.68.

Citations:
- `src/pricing/cart.py#L38-L39`: "def subtotal(self) -> Decimal: return sum((item.total for item in self.items), Decimal(0))" (shows: Cart.subtotal is declared to return a Decimal and sums in Decimal.)
- `src/pricing/cart.py#L44`: "def total(self) -> Decimal:" (shows: Cart.total is declared to return a Decimal.)
- `src/pricing/cart.py#L54`: "return max(total, Decimal(0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)" (shows: Cart.total rounds to cents by quantizing a Decimal to 0.01 with ROUND_HALF_UP.)

### Answer
<!-- write below this line -->
