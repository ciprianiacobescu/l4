# A ledger line is always valid UTF-8

## Why

A file name that is not valid UTF-8 (possible on Linux) reaches Python as a str with lone surrogates (`os.fsdecode`).
When such a str is a value of a ledger event, `Ledger.append` (`l4.state.ledger`) serialises with
`ensure_ascii=False` and encodes the line as UTF-8, which raises `UnicodeEncodeError` [V, the CI of 0.4.45 on Linux:
the python-encoding guard's event crashed the step until the guard named the file in a display form]. 0.4.45 fixed
that one event; every other event that carries a path (the protected-path guard, the test-path freeze, the gate
configuration guard, the planted-link refusal, a scan finding) can still crash a step, or a run, on such a name.

## What changes

- `Ledger.append` writes every str of the payload (keys and values, nested) that holds a lone surrogate in the display
  form of `l4.security.pyencoding.shown`: a byte 0x80..0xFF that `os.fsdecode` escaped is written as `\xNN`, and any
  other lone surrogate as `\uXXXX` text. A line is then always valid UTF-8, every reader gets a str without surrogates,
  and the JSONL mirror and the observers get the same values. Text without a surrogate is unchanged byte for byte.
- No other format change: the redaction runs first, as today, and the sequence number rule is unchanged.

## Impact

- Code: `l4.state.ledger` (`append`), `l4.security.pyencoding` (a helper for any str, if `shown` alone does not cover
  every lone surrogate).
- Spec: L4-OBS-006 added; SCN-OBS-07..08; change-table row 106.
- Not in this change: the display of such names in a merge request comment or a job summary (they read the ledger's
  values, which no longer hold surrogates).
