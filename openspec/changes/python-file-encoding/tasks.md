## Context (from the adversarial review of 2026-10-30)

- Proof at the level of the pure functions: a probe script of the review (not kept in the repository)
  (`tamper.compare(...)` gives `[]`, `scan.skip_markers` nothing, the pre-existing test passes against a broken product).
- The harness decodes as UTF-8: `_preexisting_changes` (src/l4/implementer/tdd.py ~1100, `errors="replace"`),
  `integrity._text` (src/l4/verifier/integrity.py ~100), `l4.implementer.tamper`.
- The repair branch (not merged) has an `encoding_problem` helper for the same rule; write this change's own helper in a
  neutral module (for example `l4.security.pyencoding`, or next to `l4.fsutil`), since that branch is not merged yet.

## 1. The guard after a step

- [ ] 1.1 Find where every agent step's changes are checked after the step (the post-step guards: `restore_frozen`,
  `revert_protected`, `freeze_test_paths`, the planted-link refusal; find the common call path for red, green, single /
  chores and refactors in src/l4/implementer/tdd.py and src/l4/implementer/guards.py). Write the tests first: SCN-SEC-110,
  -111, -113, -114 (real files in a bench worktree, as the guard tests build them; include `.pyi`, a BOM file, a
  `# -*- coding: latin-1 -*-` file, a cookie on line 2 after a shebang). Then add a pure helper
  `declared_encoding(data: bytes) -> str` (tokenize.detect_encoding; a decode error counts as not UTF-8) and the guard:
  put back each offending Python file the step added or changed, emit `guard.violation{path, rule: "python encoding",
  action}`, fail the attempt; add the advice to `l4.implementer.guardnotes` (`_ADVICE["python encoding"]`).

## 2. The verifier

- [ ] 2.1 Write the tests first (the integrity tests): SCN-SEC-112, -113, -114 at the verifier, with a person's commit and
  a harness commit. Then add an integrity check (registered with the others) that lists every Python file added or
  changed in base..head whose head blob declares another encoding, as one blocker with the paths and encodings and the
  fix. Read blobs with the existing safe readers (regular files only, size cap).

## 3. Checks

- [ ] 3.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you
  changed or added plus the guard, integrity and tdd test files that import a module you changed, in as few sequential
  runs as fit; not whole directories. Run ruff check and ruff format on the changed files. Report the counts. Do not edit
  docs/SPEC.md, CHANGELOG.md or docs/runbook.md.
