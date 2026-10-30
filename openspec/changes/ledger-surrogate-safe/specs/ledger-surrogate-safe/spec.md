## Purpose

No value of a ledger event can make the ledger write fail.

## ADDED Requirements

### Requirement: L4-OBS-006 A ledger line is always valid UTF-8
`Ledger.append` SHALL write every str of an event's payload, keys and values and nested ones, that holds a lone
surrogate in a display form without surrogates: a surrogate that `os.fsdecode` made from a byte 0x80..0xFF as `\xNN`,
any other lone surrogate as `\uXXXX`. A line SHALL always encode as UTF-8; a payload without a surrogate SHALL be
written unchanged. [V, a guard event that carried a file name that is not UTF-8 made the ledger write raise
`UnicodeEncodeError` on Linux]

#### Scenario: SCN-OBS-07 (−) A path that is not UTF-8 does not crash the ledger
- **GIVEN** an event whose `path` is `os.fsdecode(b"src/t\xff.py")` and whose nested list holds `"\ud800"`
- **WHEN** it is appended to the ledger
- **THEN** the line is written, reads back with `path` equal to `src/t\xff.py` (a backslash, `x`, `f`, `f`) and the list
  item equal to `\ud800` as text, and the next event gets the next sequence number

#### Scenario: SCN-OBS-08 (+) Other text is written unchanged
- **WHEN** an event with UTF-8 text (`ü`, `→`, an emoji) is appended
- **THEN** the line holds those characters byte for byte as before this change
