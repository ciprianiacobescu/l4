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

- After every agent step (red, green, a chore of any kind, a refactor, a test chore, and a replayed held step), a Python
  file the step added or changed whose declared encoding (`tokenize.detect_encoding`) is not UTF-8 (`utf-8`, `utf-8-sig`
  for a file with a byte-order mark, or `ascii`, a subset that hides nothing), or whose first two lines cannot be read
  within a bounded prefix (`unreadable`), is put back (a new file removed) with `guard.violation{rule: "python
  encoding"}`, and the attempt fails with advice that Python files must stay UTF-8. No file is read whole or skipped by
  size: a prefix of 64 KiB + 1 bytes decides, from the work tree (a reader that never follows a link) and from a blob
  (a stream that stops after the prefix).
- A Python-named symbolic link is followed inside the tree, chains and linked directories included: when the link or
  what it ends at changed, the file at the end is checked and the changed paths of the chain are put back. The verifier
  does the same at head and blocks a changed link that ends at no regular file (`link that cannot be checked`).
- The verifier's integrity checks report a blocker for every Python file that the unit's diff adds or changes, by
  anyone, that is not UTF-8 in this sense; the finding reads `a Python file declares a non-UTF-8 encoding: <path>:
  <encoding>[, ...]. <advice>`, the advice naming the fix (convert it to UTF-8 and remove the cookie).
- The verifier's own test writer (audit and e2e) refuses code that declares another encoding: its marker on line 1 puts a
  cookie on line 2, where Python honours it and `ast.parse` does not see it.
- A file with no cookie, a `# -*- coding: utf-8 -*-` cookie or a byte-order mark is unaffected.

## Impact

- Code: `l4.security.pyencoding` (the prefix rule, the link walk), `l4.fsutil.read_inside_prefix`, `Git.blob_prefix`, the
  implementer's post-step guards (`l4.implementer.guards`, run by `agent_step` and `replay_step`), `l4.verifier.integrity`
  (a new check), `l4.verifier.testwriter`, `l4.implementer.guardnotes` (the advice).
- Spec: L4-SEC-042 added; SCN-SEC-110 to SCN-SEC-117 added; change-table row 104.

## Not in this change

- Other languages (no comparable source-encoding switch in the gated languages' compilers is known to the harness) and
  files that are not Python.
- A file a gate run writes is checked only by the verifier row, before merge: the step guard runs after the agent, not
  after the gates.
- `.gitattributes` is not frozen. `*.py -diff` would show a diff as binary to the judge, and `working-tree-encoding`
  makes the work tree bytes differ from the blob. Both are a separate change.
- Extensionless scripts with a Python shebang, `.pyw`, files loaded through `runpy` and tracked `.pyc` files.
- A pre-existing non-UTF-8 Python file must be converted before a unit can change it: a step or a commit that changes it
  is put back or blocked.
