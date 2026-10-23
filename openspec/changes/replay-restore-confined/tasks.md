Every task follows these rules:
- Read `proposal.md`, `design.md` and `specs/replay-restore-confined/spec.md` of this change first. Every text and
  signature is in `design.md` (D1, D2 and "Contracts"). Do not change one without the orchestrator.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>` and `.venv/bin/ruff format --check <changed files>`. A task that edits
  `docs/SPEC.md` also runs `PYTHONPATH=src .venv/bin/python scripts/check_spec.py docs/SPEC.md`, and the output must
  be clean.
- Work only in this branch's worktree, with its own `.venv` (`uv sync --inexact`). Never change git configuration.
  Never push.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `replay-restore-confined <n.m>:
  …`, with no trailer and no local path.
- Run pytest in the foreground, never in the background. Never wait on a process with `while pgrep …` (it matches
  itself), and never kill processes by pattern.

Test world: `tests/unit/implementer/test_held_guard_links.py` (`make_bench`, `replayed`, `make_outside`, `state`, `PATCH`,
`BASE`, the racing test), `tests/unit/implementer/test_held_*.py` (the replay tests).

## 1. The confined base restore (D1, D2; L4-IMP-086)

- [x] 1.1 Tests first in `tests/unit/implementer/test_held_guard_links.py`: SCN-IMP-412 (a tracked file not in the patch,
  changed by a "gate", is back to its base content and mode, `git diff --quiet <base> -- <path>` succeeds, and the
  recorded git argv of the restore holds no `checkout`, `restore`, `reset --hard`, `stash` or `clean`; record by
  wrapping `ReplayGuard._git` and `Git.run` with monkeypatch); a base link not in the patch that a gate replaced by a file
  comes back as the link with its target; an executable base file comes back executable; a submodule entry (mode
  160000, made with `git update-index --add --cacheinfo 160000,<sha>,<path>` at the base) that a gate turned into a file
  fails with the Contracts text. Mark the existing racing test with `# SCN-IMP-411`.
- [x] 1.2 `held_patch.py`: `_base_entry`, `_NotRestorable`, and the new branch of `_restore_one` (D1); `restore` maps
  `_NotRestorable` to the failure text. Run `tests/unit/implementer/test_held_guard_links.py` and every
  `tests/unit/implementer/test_held_*.py`.

## 2. Docs

- [x] 2.1 `docs/SPEC.md`: L4-IMP-086 after L4-IMP-085, SCN-IMP-411 and SCN-IMP-412 after SCN-IMP-410, and change row 66
  `replay-restore-confined` after row 65. `check_spec.py` clean.
