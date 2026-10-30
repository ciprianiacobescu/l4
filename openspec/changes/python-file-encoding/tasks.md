## Context (from the adversarial review of 2026-10-30)

- Proof at the level of the pure functions: a probe script of the review (not kept in the repository)
  (`tamper.compare(...)` gives `[]`, `scan.skip_markers` nothing, the pre-existing test passes against a broken product).
- The harness decodes as UTF-8: `_preexisting_changes` (src/l4/implementer/tdd.py ~1100, `errors="replace"`),
  `integrity._text` (src/l4/verifier/integrity.py ~100), `l4.implementer.tamper`.
- The repair branch (not merged) has an `encoding_problem` helper for the same rule; write this change's own helper in a
  neutral module (for example `l4.security.pyencoding`, or next to `l4.fsutil`), since that branch is not merged yet.

## 1. The guard after a step

- [x] 1.1 Find where every agent step's changes are checked after the step (the post-step guards: `restore_frozen`,
  `revert_protected`, `freeze_test_paths`, the planted-link refusal; find the common call path for red, green, single /
  chores and refactors in src/l4/implementer/tdd.py and src/l4/implementer/guards.py). Write the tests first: SCN-SEC-110,
  -111, -113, -114 (real files in a bench worktree, as the guard tests build them; include `.pyi`, a BOM file, a
  `# -*- coding: latin-1 -*-` file, a cookie on line 2 after a shebang). Then add a pure helper
  `declared_encoding(data: bytes) -> str` (tokenize.detect_encoding; a decode error counts as not UTF-8) and the guard:
  put back each offending Python file the step added or changed, emit `guard.violation{path, rule: "python encoding",
  action}`, fail the attempt; add the advice to `l4.implementer.guardnotes` (`_ADVICE["python encoding"]`).

  Result: There is one common post-step path, and it has two bodies: every step kind (red, green, single, and so the
  fix, refactor and test chores, which are `run_single`) is run by `step_or_replay`, which calls either `agent_step`
  (tdd.py) or, for an accepted held step, `replay_step` (held_patch.py). Both already run the post-step guards
  (`revert_protected`, `revert_gate_config`, ...), so the guard is added once in each, right after `revert_gate_config`,
  and nothing is patched in `run_red`/`run_green`/`run_single`. New: `l4/security/pyencoding.py` (`declared_encoding`,
  `non_utf8`, `is_python_file`), `guards.revert_python_encoding` + `encoding_reason`, `_ADVICE["python encoding"]`.
  `agent_step` returns `StepOutcome("failed", reason)` right after the status/limit checks and before any result is
  read, so a `blocked` or invalid result does not excuse the file; `replay_step` does the same after the
  `held.replayed` event and drops the path from `replay_expected`/`replay_links`. Deviations: (1) `declared_encoding`
  returns `tokenize`'s name (`iso-8859-1` for `latin-1`), but every spelling of UTF-8 (`UTF8`, `utf_8`) is canonicalised
  through `codecs.lookup`, because `detect_encoding` leaves `UTF8` as written and would otherwise flag it; (2) line ends
  are normalised (`\r\n`, a lone `\r` become `\n`) before `detect_encoding`, because the compiler does that before it
  looks for the cookie, so a cookie on a CR-only second line is seen; (3) a decode error returns the name
  `undecodable`; (4) a Python file that is a symbolic link, not a regular file or over 8 MiB is skipped (the spec leaves
  non-regular files to the existing checks); a link named `x.py` pointing at a non-Python file in the tree is therefore
  not followed (known limit); (5) a pre-existing non-UTF-8 Python file that a step changes is put back too (the rule
  is on the file, not on the cookie the step added). Tests: before the change `tests/unit/implementer/test_python_encoding_guard.py`
  failed 8 of its first 10 tests with `'ok' == 'failed'` (red let the cookie in a pre-existing test through; `'blocked'`
  for the blocked step; the two UTF-8/non-Python tests passed, as they should) and `test_pyencoding.py` could not
  import; the replay test fails (the file is not removed) with the `replay_step` call taken out; after: 11 and 24 passed (SCN-SEC-110, -111, -113, -114, a new file,
  `.pyi`, a BOM, `latin-1` on line 2 after a shebang, a fix chore, a refactor chore, a test chore, a blocked step and a
  replayed step).

## 2. The verifier

- [x] 2.1 Write the tests first (the integrity tests): SCN-SEC-112, -113, -114 at the verifier, with a person's commit and
  a harness commit. Then add an integrity check (registered with the others) that lists every Python file added or
  changed in base..head whose head blob declares another encoding, as one blocker with the paths and encodings and the
  fix. Read blobs with the existing safe readers (regular files only, size cap).

  Result: New `check_python_encoding` in `l4/verifier/integrity.py`, registered last in `CHECKS` as the row
  `python encoding` (so `test_integrity.py`'s exact list of row names gained that entry; the ladder test that compares
  only the first four rows is untouched). It lists the regular files (`100644`/`100755`) that `git diff --raw
  --no-abbrev base head` shows as added or changed with a `.py`/`.pyi` name, sizes their head blobs with one
  `cat-file --batch-check` (blobs over 8 MiB, `MAX_PYTHON_BYTES`, are not read), reads each with `cat-file blob` and
  reports ONE blocker, title `a Python file declares a non-UTF-8 encoding`, detail `<path>: <encoding>` per file (at
  most 5 shown, "+N more") plus the fix (convert each file to UTF-8 and remove the coding cookie). It does not look at
  who committed, so a person's commit, a harness commit and a unit step commit all block. Deviation from "the existing
  safe readers": `integrity._blob`/`_text` use `git show` with no mode or size check, so they are not used; the new
  check takes the mode from the raw diff (links and submodules are skipped, as the spec leaves them to other checks) and
  the size from `cat-file`. A link named `x.py` that points at a non-Python file is not followed (same known limit as
  1.1). Tests (`tests/unit/verifier/test_integrity_python_encoding.py`, 13): before, the module did not import
  (`check_python_encoding` missing); my first implementation then failed 5 of 13 because `--raw` abbreviates the blob
  ids and `--batch-check` prints full ones (fixed with `--no-abbrev`); now all 13 pass (SCN-SEC-112 for a person, a
  harness and a unit step commit; SCN-SEC-113 with no cookie, a `utf-8` cookie, a BOM, a BOM plus cookie, a shebang plus
  `UTF8` cookie; SCN-SEC-114; a new `.py` and `.pyi`; an unchanged or deleted file; a link; the ladder row). With the
  updated names test: 140 passed across test_integrity, test_integrity_c22, test_ladder_fix, test_test_awareness and the
  new file.

## 3. Checks

- [x] 3.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you
  changed or added plus the guard, integrity and tdd test files that import a module you changed, in as few sequential
  runs as fit; not whole directories. Run ruff check and ruff format on the changed files. Report the counts. Do not edit
  docs/SPEC.md, CHANGELOG.md or docs/runbook.md.

  Result: Ruff check and ruff format --check are clean on the 10 changed Python files (mypy is not installed in this
  worktree's venv, so no type check was run). Pytest, one sequential run: `test_python_encoding_guard`,
  `test_pyencoding`, `test_guards`, `test_guard_notes`, `test_replay_gateconfig`, `test_gate_config_guard`,
  `test_refactor_chore`, `test_single_phase`, `test_red_preexisting_tests`, `test_held_accept`,
  `test_integrity_python_encoding` and `test_integrity`: 334 passed, 0 failed (the machine was under heavy load, 21
  minutes). Earlier sequential run of the verifier files (`test_integrity`, `test_integrity_c22`, `test_ladder_fix`,
  `test_test_awareness`, `test_integrity_python_encoding`): 140 passed. No test failed that passed before. Not run:
  the rest of the suite and the directories (as instructed); docs/SPEC.md, CHANGELOG.md and docs/runbook.md are
  untouched.
