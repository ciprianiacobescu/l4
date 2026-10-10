# Spec Delta

## Purpose
The code that pick lists print for a shelf position.

## ADDED Requirements

### Requirement: Shelf code
`inventory.shelf.shelf_code(aisle: int, slot: int)` SHALL return the `str` `A<aisle>-S<slot>`, with the aisle and the
slot zero-padded to two digits, and SHALL raise `ValueError` when the aisle or the slot is below 1.

#### Scenario: The code is zero-padded
- **WHEN** a pick list asks for `inventory.shelf.shelf_code(3, 7)`
- **THEN** it returns exactly `A03-S07`

#### Scenario: An aisle below 1 is rejected
- **WHEN** a pick list asks for `inventory.shelf.shelf_code(0, 7)`
- **THEN** it raises `ValueError`
