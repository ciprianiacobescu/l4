## ADDED Requirements

### Requirement: Greet by name
The `greet(name)` function SHALL return `Hello, <name>!` for a non-blank name, and SHALL raise `ValueError` for a blank one.

#### Scenario: Named greeting
- **WHEN** `greet("Ada")` is called
- **THEN** it returns `"Hello, Ada!"`

#### Scenario: Blank name
- **WHEN** `greet("  ")` is called
- **THEN** it raises `ValueError`

### Requirement: Farewell by name
The `farewell(name)` function SHALL return `Goodbye, <name>!`.

#### Scenario: Named farewell
- **WHEN** `farewell("Ada")` is called
- **THEN** it returns `"Goodbye, Ada!"`
