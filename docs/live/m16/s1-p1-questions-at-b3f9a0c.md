# Questions — add-bulk-discount

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
| Q-001 | open | 1.1 | ambiguous | Does the bulk threshold count units or distinct lines? |
<!-- l4:index:end -->

---

## Q-001: Does the bulk threshold count units or distinct lines?

- **Status:** open
- **Blocking tasks:** 1.1
- **Kind:** ambiguous
- **Asked:** intake (open questions in design.md)

### Context
Does the bulk threshold count units or distinct lines?

Listed under "Open questions" in design.md.
Open-question-hash: 5f73f7096b761709

### Clarifier suggestion
confidence: medium · kind: product (S1 p=n/a) · needs a human

This is a product decision for the project owner. The specs don't settle it, and design.md lists it as an open question. Suggested answer: count units, meaning the sum of the quantities across line items. That matches how the cart page already counts items ("Items: N" is the sum of quantities), so a cart showing "Items: 10" would get the discount. The scenarios ("10 items at 2.50 each") work under either reading: the subtotal is 25.00 either way, so they don't decide it. Ask the owner to confirm before implementing task 1.1.

Citations:
- `openspec/specs/cart-page/spec.md#L9`: "The cart page SHALL show the sum of the quantities of its line items in an element with `data-testid="item-count"`, as the text `Items: N`." (shows: The cart page shows a cart's item count as the sum of its line-item quantities.)

### Answer
<!-- write below this line -->
