# Questions — add-vat

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
| Q-001 | answered | 1.1, 1.2 | ambiguous | Scenarios "Romanian customer" and "Romanian customer, current rate" conflict |
| Q-002 | answered | none | verdict | Finding F-366420f0: VAT ignores any applied discount code |
| Q-003 | answered | none | verdict | Criterion C-5427d9c3 (vat › VAT by country › Romanian customer, current rate): accept as satisfied? |
| Q-004 | answered | none | verdict | Criterion C-3d5b62ab (vat › VAT by country › German customer): accept as satisfied? |
| Q-005 | answered | none | verdict | Criterion C-e28fa9b2 (vat › VAT by country › Unsupported country): accept as satisfied? |
<!-- l4:index:end -->

---

## Q-001: Scenarios "Romanian customer" and "Romanian customer, current rate" conflict

- **Status:** answered
- **Blocking tasks:** 1.1, 1.2
- **Kind:** ambiguous
- **Asked:** intake lint (L4-ODD-004)
- **Criteria:** C-4a683d3d (vat › VAT by country › Romanian customer), C-5427d9c3 (vat › VAT by country › Romanian customer, current rate)

### Context
These two scenarios have the same GIVEN and WHEN and different THEN, so the implementer cannot satisfy both.
- vat › VAT by country › Romanian customer (specs/vat/spec.md:11)
  WHEN a customer from `RO` has a cart subtotal of 100.00
  THEN the total with VAT is 119.00
- vat › VAT by country › Romanian customer, current rate (specs/vat/spec.md:15)
  WHEN a customer from `RO` has a cart subtotal of 100.00
  THEN the total with VAT is 121.00
Which behaviour is wanted? Answer below and set Status to answered. If one scenario is wrong, delete it from the spec on this unit branch in the same commit; a change on the base branch does not reach this unit.

### Clarifier suggestion
confidence: medium · kind: product (S1 p=n/a) · needs a human

The project owner needs to decide this. It is a legal VAT rate, and the documents don't say which scenario is right. My suggestion is to keep "Romanian customer, current rate" (100.00 -> 121.00) and delete "Romanian customer" (119.00) from specs/vat/spec.md on this unit branch. As far as I know, Romania's standard VAT rate went from 19% to 21% on 1 Aug 2025, so 19% looks out of date. The owner should confirm the rate. They should also say whether any orders from before the change still need 19%. If they do, the spec needs a date-based rate rule.

Citations:
- `specs/vat/spec.md#L11-L13`: "#### Scenario: Romanian customer - **WHEN** a customer from `RO` has a cart subtotal of 100.00 - **THEN** the total with VAT is 119.00"
- `specs/vat/spec.md#L15-L17`: "#### Scenario: Romanian customer, current rate - **WHEN** a customer from `RO` has a cart subtotal of 100.00 - **THEN** the total with VAT is 121.00"
- `specs/vat/spec.md#L9`: "SHALL return the cart subtotal plus VAT at the rate of the customer's country"

### Answer
<!-- write below this line -->
RO: 21 % (the standard rate since 2025-08-01; the 119.00 scenario was outdated and is removed from the spec in this commit). DE: 19 %. Any other country raises UnsupportedCountry. No date-based rate rule is needed.

---

## Q-002: Finding F-366420f0: VAT ignores any applied discount code

- **Status:** answered
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 1, verifier

### Context
The judge raised a major finding in round 1, and no deterministic check confirms it. It reports behaviour that no scenario pins down.

Title: VAT ignores any applied discount code
Detail: total_with_vat starts from self.subtotal() and never uses the discounted total that Cart.total() computes. If a discount code has been applied, the VAT total is worked out on the pre-discount amount, so a customer would pay VAT on money they were not charged. The proposal says 'the cart total shown to the customer includes VAT', but the requirement says 'cart subtotal plus VAT', and no scenario covers a discounted cart. Two reasonable implementations give different answers. Example: with 10% off and RO, the committed code gives 121.00, while VAT on the discounted total gives 108.90.
Suggested fix: Get the owner to decide whether VAT applies before or after discounts. Then add a scenario with a discount applied, and base total_with_vat on total() if that is the intended behaviour.

Answer `accept` to waive the finding, or `reject` and say why: a rejected finding is fixed by a fix unit.

### Options
1. accept
2. reject: <reason>

### Answer
<!-- write below this line -->
reject: WHEN a 10 % discount code is applied to a RO cart with subtotal 100.00 THEN total_with_vat is 108.90

---

## Q-003: Criterion C-5427d9c3 (vat › VAT by country › Romanian customer, current rate): accept as satisfied?

- **Status:** answered
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 3, verifier
- **Criteria:** C-5427d9c3 (vat › VAT by country › Romanian customer, current rate)

### Context
Criterion C-5427d9c3 (vat › VAT by country › Romanian customer, current rate) is needs human after round 3.

Scenario:
\- **WHEN** a customer from `RO` has a cart subtotal of 100.00
\- **THEN** the total with VAT is 121.00

Why: uncovered: no adequate discriminating test traces it
Judge: pass
Tracing tests: none
Ignored tests: none

Answer `accept` if the criterion is satisfied as it stands, or `reject` and say why.
If the code is right and the scenarios are incomplete, `reject` with a scenario: WHEN ... THEN ...

### Options
1. accept
2. reject: <reason>, or WHEN ... THEN ... for a spec gap

### Answer
<!-- write below this line -->
accept: satisfied. tests/test_vat.py::test_cart_total_with_vat_for_supported_countries[RO-expected_total0] checks a RO cart of 100.00 gives 121.00 and passes; the M1.1 harness wrote it red then green before criterion tags existed, so it carries no l4 mark. The judge passed the criterion.
---

## Q-004: Criterion C-3d5b62ab (vat › VAT by country › German customer): accept as satisfied?

- **Status:** answered
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 3, verifier
- **Criteria:** C-3d5b62ab (vat › VAT by country › German customer)

### Context
Criterion C-3d5b62ab (vat › VAT by country › German customer) is needs human after round 3.

Scenario:
\- **WHEN** a customer from `DE` has a cart subtotal of 100.00
\- **THEN** the total with VAT is 119.00

Why: uncovered: no adequate discriminating test traces it
Judge: pass
Tracing tests: none
Ignored tests: none

Answer `accept` if the criterion is satisfied as it stands, or `reject` and say why.
If the code is right and the scenarios are incomplete, `reject` with a scenario: WHEN ... THEN ...

### Options
1. accept
2. reject: <reason>, or WHEN ... THEN ... for a spec gap

### Answer
<!-- write below this line -->
accept: satisfied. tests/test_vat.py::test_cart_total_with_vat_for_supported_countries[DE-expected_total1] checks a DE cart of 100.00 gives 119.00 and passes; the M1.1 harness wrote it red then green before criterion tags existed, so it carries no l4 mark. The judge passed the criterion.
---

## Q-005: Criterion C-e28fa9b2 (vat › VAT by country › Unsupported country): accept as satisfied?

- **Status:** answered
- **Blocking tasks:** none
- **Kind:** verdict
- **Asked:** round 3, verifier
- **Criteria:** C-e28fa9b2 (vat › VAT by country › Unsupported country)

### Context
Criterion C-e28fa9b2 (vat › VAT by country › Unsupported country) is needs human after round 3.

Scenario:
\- **WHEN** a customer from `US` has a cart subtotal of 100.00
\- **THEN** `UnsupportedCountry` is raised

Why: uncovered: no adequate discriminating test traces it
Judge: pass
Tracing tests: none
Ignored tests: none

Answer `accept` if the criterion is satisfied as it stands, or `reject` and say why.
If the code is right and the scenarios are incomplete, `reject` with a scenario: WHEN ... THEN ...

### Options
1. accept
2. reject: <reason>, or WHEN ... THEN ... for a spec gap

### Answer
<!-- write below this line -->
accept: satisfied. tests/test_vat.py::test_cart_total_with_vat_rejects_unsupported_country and test_vat_rate_rejects_unsupported_country check that US raises UnsupportedCountry and pass; the M1.1 harness wrote them red then green before criterion tags existed, so they carry no l4 mark. The judge passed the criterion.
