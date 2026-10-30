## Purpose

No step and no commit of a unit can hide Python code from the harness's checks and from the judge behind a source
encoding the harness does not read.

## ADDED Requirements

### Requirement: L4-SEC-042 A Python file that a unit changes must be UTF-8
After every agent step (red, green, a chore of any kind, a refactor, a test chore, and a replayed held step), a Python
file (`.py`, `.pyi`) that the step added or changed SHALL be put back to the step's base (a new file removed), recorded
as `guard.violation{path, rule: "python encoding", why, action}`, and SHALL fail the attempt with the advice `Python
files must stay UTF-8: do not add a coding cookie that names another encoding. The harness put the file back: write the
change again without the cookie (a file that already declared another encoding must be converted to UTF-8, or left
unchanged).`, when its declared encoding is not `utf-8`, `utf-8-sig` or `ascii` (`tokenize.detect_encoding` on the first
two lines, `\r\n` and a lone `\r` counted as line ends, as the compiler does; ASCII is a subset of UTF-8 and hides
nothing), or when it is `unreadable`.

No file is read whole and none is skipped by size: at most `COOKIE_PREFIX_BYTES + 1` (64 KiB + 1) bytes are read, from
the work tree through a reader that never follows a link and from a blob by a stream that stops after them. When the
prefix ends inside line 1 or line 2: if that line, after `[ \t\f]*`, starts with `#` or is blank, the file is
`unreadable` (a comment or blank line longer than the prefix, behind which a cookie may sit) and is a violation like any
other encoding; if it starts with code, no cookie can sit on it (and none on line 2 after a line 1 of code), so the file
is decided from the complete lines before it and the byte-order mark, and the cut bytes are never decoded.

A Python-named symbolic link is followed inside the work tree (a chain, a linked directory; at most 40 links). When the
link, a link on the way or the file it ends at changed in the step, the file it ends at is checked the same way, and on a
violation every changed path of the chain and the file itself are put back, one `guard.violation` each, whose `why` names
the link and the file. The file a link ends at is matched to the changed paths by file identity (`st_dev`, `st_ino`), not
by name, since a file system that ignores case or Unicode normalisation gives one file several names; a changed path that
was removed cannot be the target of a link that still resolves. A link that does not end at a regular file of the work
tree (dangling, a directory, a loop, outside the tree) is not followed: Python cannot import it as a file, so it cannot
hide source. A Python file that cannot be read (a directory without read permission, a FIFO or a device) is `unreadable`
and put back like the rest; a restore that fails raises to the attempt, and the ledger restore and the environment check
of the step still run.

The verifier SHALL report ONE blocker that lists every Python file the unit's diff (base..head) adds or changes,
whoever committed it, that is not UTF-8 in this sense (at most five rows are shown, then `(+N more)`), with the title `a
Python file declares a non-UTF-8 encoding` and the detail `<path>: <encoding>[, ...]. <advice>` (the finding reads `a
Python file declares a non-UTF-8 encoding: <path>: <encoding>[, ...]. <advice>`), the advice naming the fix (convert each
file to UTF-8 and remove the coding cookie). Every git path and link target is decoded with `os.fsdecode`, so names that
are not UTF-8 stay distinct and a link finds its own target; a name is shown with its invalid bytes as `\xNN`.

The verifier follows every Python-named link of the tree at head the same way. A link is touched by base..head when the
link, a link on the way or its target is added, changed or deleted (a target that is renamed, case only included, counts
as deleted), or when its target, folded for case and Unicode normalisation (`NFC`, `casefold`), is the folded name of a
changed path. A touched link is checked at the file it ends at (`<link>: <encoding> (link to <file>)`); when its literal
target is not a regular file of the tree and was not deleted, the one regular file with the same folded name is taken for
it. A touched link that ends at no regular file of the tree at head (dangling, a directory, a loop, outside the tree, a
target that was deleted or renamed, several files with the same folded name) is the row `<link>: link that cannot be
checked`; this also applies when only a link in the chain changed. A link that base..head did not touch is not looked at.
The note of the check never says that a file is UTF-8 that it did not read.

The verifier's test writer SHALL refuse generated test code (audit and e2e) for which the bytes it would write (the
marker on line 1, then the code) declare another encoding, with the reason `the test declares the encoding <encoding>;
write UTF-8 without a coding cookie`, and `write_test_file` SHALL refuse to write such a file.

#### Scenario: SCN-SEC-110 (−) Red cannot hide a return in a pre-existing test
- **GIVEN** a pre-existing `tests/test_a.py::test_existing` and a red step that adds `# coding: utf-7` as line 1 and
  `  # +AAo-    return` to a line of `test_existing`, plus a new failing test
- **WHEN** the step ends
- **THEN** `tests/test_a.py` is put back, `guard.violation{rule: "python encoding"}` is recorded and the attempt fails
  with the advice

#### Scenario: SCN-SEC-111 (−) Green cannot hide code in a product file
- **WHEN** a green step writes `src/app/x.py` with a `# coding: utf-7` cookie
- **THEN** the file is put back and the attempt fails, as in SCN-SEC-110

#### Scenario: SCN-SEC-112 (−) The verifier blocks such a file from anyone
- **GIVEN** the unit's diff adds `# coding: utf-7` to `tests/test_a.py` in a person's commit
- **WHEN** the integrity checks run
- **THEN** a blocker names `tests/test_a.py: utf-7` and the fix

#### Scenario: SCN-SEC-113 (+) UTF-8 files are unaffected
- **WHEN** a step writes a file with no cookie, with `# -*- coding: utf-8 -*-`, with `# coding: ascii`, or with a
  byte-order mark
- **THEN** nothing is put back and the verifier reports nothing

#### Scenario: SCN-SEC-114 (+) A non-Python file is unaffected
- **WHEN** a step writes `docs/a.md` whose first line reads `# coding: utf-7`
- **THEN** nothing is put back and the verifier reports nothing

#### Scenario: SCN-SEC-115 (−) Padding over a size limit does not hide a cookie
- **GIVEN** a step that writes SCN-SEC-110's test file padded to more than 8 MiB, or a file whose first line is a
  comment of 9 MiB followed by `# coding: utf-7` on line 2
- **WHEN** the guard and the verifier run
- **THEN** the first file is put back as `utf-7` and the second as `unreadable`, and the verifier reports both (neither
  file is read whole or skipped); a file whose long first line is code is not a violation

#### Scenario: SCN-SEC-116 (−) A link to a cookie file is followed
- **GIVEN** `pkg/x.py` is a link to `notes.txt`, which holds `# coding: utf-7` and hidden code, and the step adds both; or
  the link is in the base and the step only changes `notes.txt`; or the link goes through another link or a linked
  directory
- **WHEN** the guard and the verifier run
- **THEN** the changed paths of the chain and the file are put back, one `guard.violation` each whose `why` names the link
  and the file, and the verifier reports `pkg/x.py: utf-7 (link to pkg/notes.txt)`; a touched Python-named link that ends
  at no regular file of the tree is reported as `pkg/x.py: link that cannot be checked`, also when its target was
  deleted, was renamed (case only too), has several folded matches, or when only a link of the chain changed. A link
  that names `NOTES.txt` while git tracks `notes.txt` finds it on a case-insensitive file system, at the guard (by
  identity) and at the verifier (by folded name)

#### Scenario: SCN-SEC-117 (−) The test writer refuses a cookie
- **GIVEN** a reply whose code is `# coding: utf-7` and a test with a hidden `return`
- **WHEN** the writer checks the reply (audit or e2e)
- **THEN** the reply is invalid with the reason `the test declares the encoding utf-7; write UTF-8 without a coding
  cookie`, and `write_test_file` raises instead of writing the file

#### Scenario: SCN-SEC-118 (−) Names that are not UTF-8 stay distinct
- **GIVEN** `a.py` is a link to `\xff.txt` (a utf-7 file) next to a clean file named U+FFFD, or `test_\xfe.py` (utf-7) and
  `test_\xff.py` (clean) in one commit
- **WHEN** the verifier runs
- **THEN** the link is resolved to `\xff.txt` and `test_\xfe.py` is checked and reported; neither is merged with the other
  name

#### Scenario: SCN-SEC-119 (−) A file the guard cannot open is put back
- **GIVEN** a step writes a utf-7 test into a directory without read permission
- **WHEN** the guard runs
- **THEN** the file is put back as `unreadable` and recorded; a directory, a link and a missing file give no verdict
