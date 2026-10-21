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
| Q-001 | open | none | verdict | Criterion C-e25f06d8 (shipping › Shipping fee › Romanian order below the free-shipping threshold): accept as satisfied? |
| Q-002 | open | none | verdict | Criterion C-1b1fbe16 (shipping › Shipping fee › German order below the free-shipping threshold): accept as satisfied? |
| Q-003 | open | none | verdict | Hold H-4c6ed6ff: the judge's reply was discarded (schema_invalid: structured output invalid: criteria[0].counterexample: expected obje... |
<!-- l4:index:end -->

---

## Q-001: Criterion C-e25f06d8 (shipping › Shipping fee › Romanian order below the free-shipping threshold): accept as satisfied?

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier
- **Criteria:** C-e25f06d8 (shipping › Shipping fee › Romanian order below the free-shipping threshold)

### Context
Criterion C-e25f06d8 (shipping › Shipping fee › Romanian order below the free-shipping threshold) is needs human after round 1.

Scenario:
\- **WHEN** an order with a subtotal of 20.00 ships to `RO`
\- **THEN** the shipping fee is 4.99

Why: the judge gave no verdict for this criterion
Judge: no verdict
Tracing tests: tests.test_shipping::test_romanian_order_below_free_shipping_threshold_has_4_99_fee (passed, zero_value)
Ignored tests: none

Answer `accept` if the criterion is satisfied as it stands, or `reject` and say why.
If the code is right and the scenarios are incomplete, `reject` with a scenario: WHEN ... THEN ...

### Options
1. accept
2. reject: <reason>, or WHEN ... THEN ... for a spec gap

### Answer
<!-- write below this line -->
---

## Q-002: Criterion C-1b1fbe16 (shipping › Shipping fee › German order below the free-shipping threshold): accept as satisfied?

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier
- **Criteria:** C-1b1fbe16 (shipping › Shipping fee › German order below the free-shipping threshold)

### Context
Criterion C-1b1fbe16 (shipping › Shipping fee › German order below the free-shipping threshold) is needs human after round 1.

Scenario:
\- **WHEN** an order with a subtotal of 20.00 ships to `DE`
\- **THEN** the shipping fee is 9.99

Why: the judge gave no verdict for this criterion
Judge: no verdict
Tracing tests: tests.test_shipping::test_german_order_below_free_shipping_threshold_has_9_99_fee (passed, zero_value)
Ignored tests: none

Answer `accept` if the criterion is satisfied as it stands, or `reject` and say why.
If the code is right and the scenarios are incomplete, `reject` with a scenario: WHEN ... THEN ...

### Options
1. accept
2. reject: <reason>, or WHEN ... THEN ... for a spec gap

### Answer
<!-- write below this line -->
---

## Q-003: Hold H-4c6ed6ff: the judge's reply was discarded (schema_invalid: structured output invalid: criteria[0].counterexample: expected obje...

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
After round 1 the verifier cannot decide on its own: the judge's reply was discarded (schema_invalid: structured output invalid: criteria[0].counterexample: expected object; criteria[1].counterexample: expected object)

Answer `accept` if the unit can go on as it stands, or `reject` and say why: a rejected hold is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
