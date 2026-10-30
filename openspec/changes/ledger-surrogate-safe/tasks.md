## 1. The ledger writes a display form of lone surrogates

- [x] 1.1 Write the tests first: SCN-OBS-07, SCN-OBS-08 (the ledger tests' real files; read the line back with the
  ledger's own reader). Then, in `Ledger.append` (src/l4/state/ledger.py ~195), turn every str of the redacted payload
  (keys and values, nested dicts, lists and tuples) that holds a lone surrogate into its display form: reuse
  `l4.security.pyencoding.shown` for the surrogates `os.fsdecode` makes (U+DC80..U+DCFF) and write any other lone
  surrogate as `\uXXXX` text (for example with `encode("utf-8", "backslashreplace")` after the fsencode step). Leave
  text without a surrogate unchanged. Check the JSONL mirror and the observers receive the same values.

  Result: tests first (3 in `tests/unit/state/test_ledger.py`, 5 in `tests/unit/security/test_pyencoding.py`); the two
  ledger tests that carry a surrogate failed on the old code with `UnicodeEncodeError: ... surrogates not allowed`, the
  helper tests with an `ImportError`. `l4.security.pyencoding` gained `has_surrogate` and `surrogate_free` (each lone
  surrogate alone: U+DC80..U+DCFF through `shown` as `\xNN`, any other as `\uXXXX`; a str without one comes back as the
  same object). `LedgerWriter.append` scans the serialised line once (`has_surrogate`); only a line that holds one is
  cleaned (payload and envelope, after the redaction) and serialised again, so a normal event pays one regex scan. The
  returned event, the observers and the JSONL mirror get the cleaned values; the caller's own objects are not changed
  (the redactor already copies). Readers of path fields (checked before choosing the place): the only equality tests
  against a path of a ledger event are `task.unfrozen{paths}` in `verifier/base_tests.py` `split_allowed` (`file in
  unfrozen`) and `task.tests_added{files}` in `verifier/ladder.py` ~507 / `traceability.extra_candidates` (`path in
  chore_files`). Both compare with a file derived from a JUnit test id (XML text, never a lone surrogate; in the ladder it is
  `discrimination._test_file`, which builds the path from the dotted id and checks `is_file`), so a path
  with a surrogate could not match before (the write crashed) and cannot match now; the miss is on the fail-closed side
  (no allowance, no extra evidence). `guard.violation{path}` is read for display, globs and counts only
  (`guardnotes.note_of`, `ci/unfixed._put_back` and its only consumer `verifier/preconditions.py` ~166, `ladder._guards`, `memory/curate`, `kg/extract` read the rule), and no
  integrity check reads outstanding `guard.violation` events. `env.rebuilt` and `tests.superseded` are read for counts
  and test ids. The writers' own in-memory comparisons (`Workbench.guard_notes`, `undone` in `tdd.py`) use the raw
  values, which the ledger change does not touch. No reader was changed.

## 2. Checks

- [x] 2.1 Run once with pytest (in the foreground, never in a loop) the ledger and state test files and
  tests/unit/security/test_pyencoding.py; ruff check and ruff format on the changed files. Report the counts. Do not
  edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md.

  Result: one run of `test_ledger.py`, `test_ledger_tamper.py`, `test_fold.py`, `test_lifecycle.py`,
  `test_status_events.py` and `tests/unit/security/test_pyencoding.py`: 117 passed. `ruff check` and `ruff format
  --check` on the four changed files are clean. SPEC.md, CHANGELOG.md and the runbook are not touched.
