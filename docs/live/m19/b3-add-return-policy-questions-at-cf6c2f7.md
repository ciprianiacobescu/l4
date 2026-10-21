# Questions — add-return-policy

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
| Q-001 | answered | 1.1 | ambiguous | Scenarios "The notice text is exact" and "The notice names the return window" conflict |
| Q-002 | accepted | 1.1 | technical | Should the acceptance test be corrected to read the constant directly? |
| Q-003 | open | 1.1 | technical | Frozen test expects a function |
<!-- l4:index:end -->

---

## Q-001: Scenarios "The notice text is exact" and "The notice names the return window" conflict

- **Status:** answered
- **Blocking tasks:** 1.1
- **Kind:** ambiguous
- **Asked:** intake lint (L4-ODD-004)
- **Criteria:** C-4204c055 (receipt-notices › Return policy notice › The notice text is exact), C-b0281470 (receipt-notices › Return policy notice › The notice names the return window)

### Context
These two scenarios have the same GIVEN and WHEN and different THEN, so the implementer cannot satisfy both.
- receipt-notices › Return policy notice › The notice text is exact (specs/receipt-notices/spec.md:12)
  WHEN the receipt footer reads `pricing.notices.RETURN_POLICY`
  THEN it equals `Items may be returned within 30 days of delivery for a refund to the original card.`
- receipt-notices › Return policy notice › The notice names the return window (specs/receipt-notices/spec.md:16)
  WHEN the receipt footer reads `pricing.notices.RETURN_POLICY`
  THEN the text contains `30 days`
Which behaviour is wanted? Answer below and set Status to answered. If one scenario is wrong, delete it from the spec on this unit branch in the same commit; a change on the base branch does not reach this unit.

### Clarifier suggestion
confidence: high · kind: technical (S1 p=n/a) · needs a human

The two scenarios don't conflict. Set `pricing.notices.RETURN_POLICY` to exactly `Items may be returned within 30 days of delivery for a refund to the original card.` That string contains `30 days`, so it meets both the exact-text scenario and the scenario that checks for the return window. Keep both scenarios and don't delete either one from the spec.

Citations:
- `specs/receipt-notices/spec.md#L9-L10`: "`pricing.notices.RETURN_POLICY` SHALL be a `str` equal to exactly `Items may be returned within 30 days of delivery for a refund to the original card.`" (shows: The requirement fixes RETURN_POLICY to an exact string, and that string includes the words '30 days'.)
- `specs/receipt-notices/spec.md#L18`: "- **THEN** the text contains `30 days`" (shows: The second scenario only requires the text to contain '30 days'.)

### Answer
<!-- write below this line -->
Keep both scenarios. They do not conflict: `RETURN_POLICY` is exactly `Items may be returned within 30 days of delivery for a refund to the original card.`, and that text contains `30 days`, so one constant satisfies both.

---

## Q-002: Should the acceptance test be corrected to read the constant directly?

- **Status:** accepted
- **Blocking tasks:** 1.1
- **Kind:** technical
- **Asked:** 2026-10-05T23:49Z by codex, run r-20261005T2348Z-cb52, task 1.1

### Context
`tests/test_notices.py` calls `RETURN_POLICY()`. The criteria require `pricing.notices.RETURN_POLICY` to be a `str`; this test would fail for the correct implementation.

### Clarifier suggestion
confidence: high · kind: technical (S1 p=0.55) · needs a human

Yes. The spec requires `pricing.notices.RETURN_POLICY` to be a `str` constant, not a function. Replace the stub in `src/pricing/notices.py` with `RETURN_POLICY = "Items may be returned within 30 days of delivery for a refund to the original card."`. In `tests/test_notices.py:8`, change `notice = RETURN_POLICY()` to `notice = RETURN_POLICY`. Leave both assertions and the `l4` marker as they are.

Citations:
- `specs/receipt-notices/spec.md#L9-L10`: "`pricing.notices.RETURN_POLICY` SHALL be a `str` equal to exactly `Items may be returned within 30 days of delivery for a refund to the original card.`" (shows: The requirement says RETURN_POLICY is a str equal to the exact policy text.)
- `proposal.md#L7-L8`: "- Add the module `pricing.notices` with the constant `RETURN_POLICY`, whose value is exactly `Items may be returned within 30 days of delivery for a refund to the original card.`" (shows: The proposal calls RETURN_POLICY a constant in the module pricing.notices.)

### Answer
<!-- write below this line -->

---

## Q-003: Frozen test expects a function

- **Status:** open
- **Blocking tasks:** 1.1
- **Kind:** technical
- **Asked:** 2026-10-05T23:51Z by codex, run r-20261005T2350Z-b29d, task 1.1

### Context
Should the red test be corrected to read RETURN_POLICY as a string constant, as the spec requires? The current test calls RETURN_POLICY().

### Clarifier suggestion
confidence: high · kind: technical (S1 p=0.50) · needs a human

Yes. The spec says `pricing.notices.RETURN_POLICY` is a `str` constant. In `tests/test_notices.py:8`, change `notice = RETURN_POLICY()` to `notice = RETURN_POLICY`. Leave the import, both assertions and the `l4` marker unchanged. In `src/pricing/notices.py`, replace the function stub with `RETURN_POLICY = "Items may be returned within 30 days of delivery for a refund to the original card."`. This matches the earlier answer Q-002.

Citations:
- `specs/receipt-notices/spec.md#L9-L10`: "`pricing.notices.RETURN_POLICY` SHALL be a `str` equal to exactly `Items may be returned within 30 days of delivery for a refund to the original card.`" (shows: The requirement says RETURN_POLICY is a str equal to the exact policy text.)
- `proposal.md#L7-L8`: "- Add the module `pricing.notices` with the constant `RETURN_POLICY`, whose value is exactly" (shows: The proposal calls RETURN_POLICY a constant in the module pricing.notices.)

### Answer
<!-- write below this line -->
