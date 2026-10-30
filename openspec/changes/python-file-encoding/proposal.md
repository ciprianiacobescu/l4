# A Python file that a unit changes must be UTF-8

## Why

An adversarial review (2026-10-30) proved, with the harness's own pure functions, that a red step can neutralise a
pre-existing test without any check noticing [V]: it adds the line `# coding: utf-7` at the top of the existing test
file and appends `  # +AAo-    return` to a line of the test. Python honours the cookie, so for pytest that comment is a
newline and a `return`, and the test passes against a broken product. The harness reads the file as UTF-8
(`_preexisting_changes` in `l4.implementer.tdd`, `_text` in `l4.verifier.integrity`, `l4.implementer.tamper`), sees only
a comment, and reports no change of the test; the skip-marker scan finds nothing, and red's own new test still fails by
assertion as red requires. The same trick hides code from the judge in any Python file, product code included: the
judge reads the diff as text. The only trace is the cookie line in the full unit diff.

## What changes

- After every agent step (red, green, a chore of any kind, a refactor), a Python file the step added or changed whose
  declared encoding (`tokenize.detect_encoding`) is not UTF-8 (`utf-8`, or `utf-8-sig` for a file with a byte-order mark)
  is put back (a new file removed) with `guard.violation{rule: "python encoding"}`, and the attempt fails with advice
  that Python files must stay UTF-8.
- The verifier's integrity checks report a blocker for every Python file that the unit's diff adds or changes, by
  anyone, whose declared encoding is not UTF-8: `a Python file declares a non-UTF-8 encoding (<path>: <encoding>)`,
  with the fix (convert it to UTF-8 and remove the cookie).
- A file with no cookie, a `# -*- coding: utf-8 -*-` cookie or a byte-order mark is unaffected.

## Impact

- Code: the implementer's post-step guards (`l4.implementer.guards` and where the steps call them), `l4.verifier.integrity`
  (a new check), `l4.implementer.guardnotes` (the advice).
- Spec: L4-SEC-042 added; SCN-SEC-110 to SCN-SEC-114 added; change-table row 104.
- Not in this change: other languages (no comparable source-encoding switch in the gated languages' compilers is known
  to the harness); files that are not Python.
