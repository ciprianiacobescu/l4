# Requirements Document

## Introduction

Login for the demo service.

## Requirements

### Requirement 1: Sign in

**User Story:** As a user, I want to sign in, so that I can see my data.

#### Acceptance Criteria

1. WHEN the user submits valid credentials, THE System SHALL open a session.
2. WHEN the user submits a wrong password, THE System SHALL show an error
   and keep the session closed.

### Requirement 2

**User Story:** As a user, I want to sign out, so that nobody else can use my session.

#### Acceptance Criteria

1. WHEN the user signs out, THE System SHALL end the session.
2. IF the session already ended, THEN THE System SHALL ignore the request.
3. WHILE offline, THE System SHALL queue the sign-out.
