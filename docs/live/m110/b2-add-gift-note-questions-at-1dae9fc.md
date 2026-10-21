# Questions — add-gift-note

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
| Q-001 | open | 1.1 | ambiguous | Scenarios "Gift note thanks the buyer" and "Gift note wishes the receiver well" conflict |
<!-- l4:index:end -->

---

## Q-001: Scenarios "Gift note thanks the buyer" and "Gift note wishes the receiver well" conflict

- **Status:** open
- **Blocking tasks:** 1.1
- **Kind:** ambiguous
- **Asked:** intake lint (L4-ODD-004)
- **Criteria:** C-73e52adf (receipt-gift › Gift note › Gift note thanks the buyer), C-2e20af61 (receipt-gift › Gift note › Gift note wishes the receiver well)

### Context
These two scenarios have the same GIVEN and WHEN and different THEN, so the implementer cannot satisfy both.
- receipt-gift › Gift note › Gift note thanks the buyer (specs/receipt-gift/spec.md:11)
  WHEN the receipt footer calls `pricing.gift.gift_note()`
  THEN it returns exactly `Thank you for your gift order.`
- receipt-gift › Gift note › Gift note wishes the receiver well (specs/receipt-gift/spec.md:15)
  WHEN the receipt footer calls `pricing.gift.gift_note()`
  THEN it returns exactly `Enjoy your gift.`
Which behaviour is wanted? Answer below and set Status to answered. If one scenario is wrong, delete it from the spec on this unit branch in the same commit; a change on the base branch does not reach this unit.

### Clarifier suggestion
confidence: low · kind: product (S1 p=n/a) · needs a human

This is a product decision: the exact wording of the gift note. The project owner has to pick one of the two strings, and the spec has to drop the other scenario. Suggestion: keep "Thank you for your gift order." and delete the "Gift note wishes the receiver well" scenario. The text is printed on the buyer's receipt, and the proposal calls it "the line a receipt prints for a gift order", which fits a message to the buyer. Nothing in the repository settles which one is meant.

### Answer
<!-- write below this line -->
