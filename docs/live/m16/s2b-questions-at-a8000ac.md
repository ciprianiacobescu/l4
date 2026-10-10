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
| Q-001 | answered | 1.1 | ambiguous | Does the bulk threshold count units or distinct lines? |
| Q-002 | open | none | verdict | Finding F-7026922b: Unrelated change to LOW_STOCK_THRESHOLD (5 -> 3) |
| Q-003 | open | none | verdict | Finding F-72872195: Out-of-scope, untested new module src/pricing/receipt.py |
| Q-004 | open | none | verdict | Hold H-f427d7fb: scope: `src/inventory/stock.py` changes module `inventory`, which the spec does not name |
| Q-005 | open | none | verdict | Hold H-2426ce7a: diff coverage: changed code not run by any test: `src/pricing/receipt.py::<module>`, `src/pricing/receipt.py::format_... |
<!-- l4:index:end -->

---

## Q-001: Does the bulk threshold count units or distinct lines?

- **Status:** answered
- **Blocking tasks:** 1.1
- **Kind:** ambiguous
- **Asked:** intake (open questions in design.md)

### Context
Does the bulk threshold count units or distinct lines?

Listed under "Open questions" in design.md.
Open-question-hash: 5f73f7096b761709

### Clarifier suggestion
confidence: medium · kind: product (S1 p=n/a) · needs a human

The project owner needs to decide this. Whether a big order means many units or many different products is a pricing rule, and design.md leaves it open on purpose. Suggested answer: count units, meaning the sum of line-item quantities. That matches the cart page, which already shows the cart's item count as the sum of quantities. So one line of 10 × Pen reaches the threshold, and so do 10 separate lines of quantity 1. Both spec scenarios (10 items at 2.50 each → 2.50, 9 items → 0.00) hold either way.

Citations:
- `openspec/specs/cart-page/spec.md#L9`: "The cart page SHALL show the sum of the quantities of its line items in an element with `data-testid="item-count"`, as the text `Items: N`." (shows: The existing cart-page spec defines a cart's item count as the sum of its line-item quantities.)

### Answer
<!-- write below this line -->
units: the threshold counts units, the sum of the quantities of the cart's line items (10 units on one line qualify).

---

## Q-002: Finding F-7026922b: Unrelated change to LOW_STOCK_THRESHOLD (5 -> 3)

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it.

Title: Unrelated change to LOW_STOCK_THRESHOLD (5 -> 3)
Detail: The change lowers the inventory low-stock threshold from 5 to 3 in src/inventory/stock.py. No part of the bulk-discount proposal, design, spec or tasks mentions this. It changes which stock quantities count as low (for example, 3 and 4 are no longer low). The stock tests still pass, which suggests they read the constant rather than pinning the value, so this behaviour change goes undetected.
Suggested fix: Revert the change to src/inventory/stock.py, or propose it as its own change.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
---

## Q-003: Finding F-72872195: Out-of-scope, untested new module src/pricing/receipt.py

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it.

Title: Out-of-scope, untested new module src/pricing/receipt.py
Detail: A 77-line receipt formatter was added. The spec does not ask for it, and the gate report lists no tests for it. It also leaves out the new bulk discount: the discount line it prints is only subtotal - total.
Suggested fix: Remove src/pricing/receipt.py from this change, or specify and test it in a separate change.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
---

## Q-004: Hold H-f427d7fb: scope: `src/inventory/stock.py` changes module `inventory`, which the spec does not name

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
After round 1 the verifier cannot decide on its own: scope: `src/inventory/stock.py` changes module `inventory`, which the spec does not name

Answer `accept` if the unit can go on as it stands, or `reject` and say why.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
---

## Q-005: Hold H-2426ce7a: diff coverage: changed code not run by any test: `src/pricing/receipt.py::<module>`, `src/pricing/receipt.py::format_...

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
After round 1 the verifier cannot decide on its own: diff coverage: changed code not run by any test: `src/pricing/receipt.py::<module>`, `src/pricing/receipt.py::format_line`, `src/pricing/receipt.py::format_receipt`, `src/pricing/receipt.py::format_total`

Answer `accept` if the unit can go on as it stands, or `reject` and say why.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
