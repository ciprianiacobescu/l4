# Bugfix Requirements Document

## Bug Analysis

### Current Behavior (Defect)

1.1 Requested by CiprianSpot, 2026-10-13T00:50:51Z in FB-001 (refactor, src/inventory/alerts.py:2-3): Move the on_hand validation into a small helper, _require_non_negative(on_hand), and call it from low_stock_message; other inventory alerts will need the same check. Quoted code: if on_hand < 0: raise ValueError(f"on_hand must be non-negative, got {on_hand}") (Feedback FB-001 (refactor): Move the on_hand validation into a small helper, _require_non_negative(o; F-b7a3ac18)
1.2 Requested by CiprianSpot, 2026-10-13T00:50:52Z in FB-002 (config, src/inventory/alerts.py:4): The low-stock threshold 5 is hard-coded; read it from LOW_STOCK_THRESHOLD (an integer), default 5. Quoted code: if on_hand < 5: (Feedback FB-002 (config): The low-stock threshold 5 is hard-coded; read it from LOW_STOCK_THRESHOL; F-0499efa7)

### Expected Behavior (Correct)

2.1 WHEN the environment variable LOW_STOCK_THRESHOLD is set THEN the system SHALL use its value instead of the value written at src/inventory/alerts.py:4

### Unchanged Behavior (Regression Prevention)

The system SHALL CONTINUE TO satisfy every other acceptance criterion of add-low-stock-message.

3.1 WHEN LOW_STOCK_THRESHOLD is not set THEN the system SHALL CONTINUE TO behave as before this change
