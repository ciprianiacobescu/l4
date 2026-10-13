# Requirements Document

## Introduction

This document specifies the requirements for adding a low stock alert message feature to the inventory system. The feature will provide a simple message generation function that alerts when inventory levels fall below a threshold, helping warehouse staff identify items that need restocking.

## Requirements

### Requirement 1: Low Stock Message Generation

**User Story:** As a warehouse manager, I need to receive clear messages about items with low stock levels so that I can prioritize restocking activities.

#### Acceptance Criteria

1. WHEN `on_hand` is below 5 units (e.g., 2 units for "bolts"), THEN the system SHALL return the message `Restock bolts: 2 left`.

2. WHEN `on_hand` is 5 or more units (e.g., 5 or 12 units), THEN the system SHALL return `None`.

3. WHEN `on_hand` is 0 units, THEN the system SHALL return the message `Restock <name>: 0 left`.

### Requirement 2: Input Validation

**User Story:** As a system administrator, I need the system to reject invalid inventory counts so that data integrity is maintained.

#### Acceptance Criteria

1. WHEN `on_hand` is negative (e.g., -1), THEN the system SHALL raise `ValueError`.
