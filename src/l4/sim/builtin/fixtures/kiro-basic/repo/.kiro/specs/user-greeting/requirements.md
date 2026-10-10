# Requirements Document

## Introduction

A tiny greeter library.

## Requirements

### Requirement 1: Greetings

**User Story:** As a user, I want to be greeted by name, so that the library feels friendly.

#### Acceptance Criteria

1. WHEN greet is called with a non-blank name, THE Greeter SHALL return "Hello, <name>!".
2. WHEN greet is called with a blank name, THE Greeter SHALL raise ValueError.

### Requirement 2: Farewells

**User Story:** As a user, I want a goodbye by name, so that I can end a conversation politely.

#### Acceptance Criteria

1. WHEN farewell is called with a name, THE Greeter SHALL return "Goodbye, <name>!".
