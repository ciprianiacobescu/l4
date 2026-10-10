# openspec/specs/*/spec.md after: openspec archive add-farewell --yes --json
## ---- openspec/specs/greeting/spec.md
# greeting Specification

## Purpose
The greeting capability produces a friendly greeting for a named user of the CLI.

## Requirements

### Requirement: Greet by name
The system SHALL greet the user by the name given on the command line, trimming surrounding whitespace.

#### Scenario: Named greeting
- **WHEN** the user runs `greet " Ada "`
- **THEN** the output is `Hello, Ada!`

### Requirement: Shout
The system SHALL print the greeting in upper case when `--shout` is given.

#### Scenario: Shouted greeting
- **WHEN** the user runs `greet Ada --shout`
- **THEN** the output is `HELLO, ADA!`
## ---- openspec/specs/farewell/spec.md
# farewell Specification

## Purpose
The farewell capability says goodbye to a named user of the greeter command line tool.

## Requirements

### Requirement: Say goodbye
The system SHALL print `Goodbye, <name>!` for `farewell <name>`.

#### Scenario: Named farewell
- **WHEN** the user runs `farewell Ada`
- **THEN** the output is `Goodbye, Ada!`
