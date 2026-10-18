# Requirements Document

## Introduction
REQ-INTRO-MARKER: a tip calculator for the till.

## Requirements

### Requirement 1
**User Story:** As a cashier, I want the tip computed, so that I can charge it.

#### Acceptance Criteria
1. WHEN a bill and a tip percent are given THEN the system SHALL return the tip rounded to 2 places.
2. WHEN the tip percent is negative THEN the system SHALL raise ValueError.
