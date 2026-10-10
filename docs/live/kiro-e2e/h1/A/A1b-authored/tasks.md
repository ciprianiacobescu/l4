# Implementation Plan

- [ ] 1. Add bulk_savings method to Cart class
  - [ ] 1.1 Import bulk discount calculation function in cart.py
    - _Requirements: 2.1, 2.2, 2.3_
  - [ ] 1.2 Implement Cart.bulk_savings() method that iterates over items and sums discounts
    - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - [ ] 1.3 Add unit tests for Cart.bulk_savings() covering empty cart, no qualifying items, and mixed items
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ] 2. Create bulk discount rule module
  - [ ] 2.1 Create pricing/bulk_discount.py module with constants
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [ ] 2.2 Implement qualifies_for_bulk_discount() function
    - _Requirements: 1.1, 1.2, 1.3_
  - [ ] 2.3 Implement calculate_bulk_discount() function with rounding
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [ ] 2.4 Add unit tests for boundary cases (quantities 9, 10, 11)
    - _Requirements: 1.1, 1.2, 1.3_
  - [ ] 2.5 Add unit tests for rounding behavior
    - _Requirements: 1.4_
  - [ ]* 2.6 Add property-based test verifying discount correctness
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

## Task Dependency Graph

```json
{
  "waves": [
    {
      "id": 0,
      "tasks": [2.1, 2.2, 2.3, 2.4, 2.5, 2.6]
    },
    {
      "id": 1,
      "tasks": [1.1, 1.2, 1.3]
    }
  ]
}
```
