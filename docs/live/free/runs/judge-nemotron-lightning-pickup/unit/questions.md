# Questions — add-pickup-notice

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
| Q-001 | open | none | verdict | Criterion C-f14cf915 (receipt-pickup › Pickup notice › The pickup notice text is exact): accept as satisfied? |
| Q-002 | open | none | verdict | Hold H-6a50c6c7: the judge's reply was discarded (schema_invalid: structured output missing: the reply holds no JSON object) |
<!-- l4:index:end -->

---

## Q-001: Criterion C-f14cf915 (receipt-pickup › Pickup notice › The pickup notice text is exact): accept as satisfied?

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier
- **Criteria:** C-f14cf915 (receipt-pickup › Pickup notice › The pickup notice text is exact)

### Context
Criterion C-f14cf915 (receipt-pickup › Pickup notice › The pickup notice text is exact) is needs human after round 1.

Scenario:
\- **WHEN** the receipt footer calls `pricing.pickup.pickup_notice()`
\- **THEN** it returns exactly `Pickup orders wait at the shop counter for seven days; bring the order number and a photo ID.`

Why: the judge gave no verdict for this criterion
Judge: no verdict
Tracing tests: tests.test_pickup::test_pickup_notice_text_is_exact (passed, zero_value)
Ignored tests: none

Answer `accept` if the criterion is satisfied as it stands, or `reject` and say why.
If the code is right and the scenarios are incomplete, `reject` with a scenario: WHEN ... THEN ...

### Options
1. accept
2. reject: <reason>, or WHEN ... THEN ... for a spec gap

### Answer
<!-- write below this line -->
---

## Q-002: Hold H-6a50c6c7: the judge's reply was discarded (schema_invalid: structured output missing: the reply holds no JSON object)

- **Status:** open
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
After round 1 the verifier cannot decide on its own: the judge's reply was discarded (schema_invalid: structured output missing: the reply holds no JSON object)

Answer `accept` if the unit can go on as it stands, or `reject` and say why: a rejected hold is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
