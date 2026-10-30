## 1. The ledger writes a display form of lone surrogates

- [ ] 1.1 Write the tests first: SCN-OBS-07, SCN-OBS-08 (the ledger tests' real files; read the line back with the
  ledger's own reader). Then, in `Ledger.append` (src/l4/state/ledger.py ~195), turn every str of the redacted payload
  (keys and values, nested dicts, lists and tuples) that holds a lone surrogate into its display form: reuse
  `l4.security.pyencoding.shown` for the surrogates `os.fsdecode` makes (U+DC80..U+DCFF) and write any other lone
  surrogate as `\uXXXX` text (for example with `encode("utf-8", "backslashreplace")` after the fsencode step). Leave
  text without a surrogate unchanged. Check the JSONL mirror and the observers receive the same values.

## 2. Checks

- [ ] 2.1 Run once with pytest (in the foreground, never in a loop) the ledger and state test files and
  tests/unit/security/test_pyencoding.py; ruff check and ruff format on the changed files. Report the counts. Do not
  edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md.
