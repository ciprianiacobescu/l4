# Design Document

## Overview

Fix unit 1 of `add-low-stock-message`. The verifier found the problems below in `add-low-stock-message`; each task of tasks.md names the findings it answers, and bugfix.md says what must change and what must not.

## Findings and Decisions

### F-b7a3ac18: Feedback FB-001 (refactor): Move the on_hand validation into a small helper, _require_non_negative(o

Severity: major. Chore: a single phase, no red test.

Requested by CiprianSpot, 2026-10-13T00:50:51Z in FB-001 (refactor, src/inventory/alerts.py:2-3): Move the on_hand validation into a small helper, _require_non_negative(on_hand), and call it from low_stock_message; other inventory alerts will need the same check.

        if on_hand < 0:
            raise ValueError(f"on_hand must be non-negative, got {on_hand}")

### F-0499efa7: Feedback FB-002 (config): The low-stock threshold 5 is hard-coded; read it from LOW_STOCK_THRESHOL

Severity: major.

Requested by CiprianSpot, 2026-10-13T00:50:52Z in FB-002 (config, src/inventory/alerts.py:4): The low-stock threshold 5 is hard-coded; read it from LOW_STOCK_THRESHOLD (an integer), default 5.

        if on_hand < 5:
