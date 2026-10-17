Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only.

## 1. Package data

- [x] 1.1 Test: the installed package's skill files (importlib.resources) are byte-equal to `plugins/l4/skills/l4`;
  a built wheel holds them.
- [x] 1.2 `pyproject.toml` force-include of the skill into the wheel and the sdist.

## 2. Command (L4-SKL-003)

- [x] 2.1 Tests: SCN-SKL-04..06 with a temporary HOME and PATH; the symlink refusal; `l4 skills status`.
- [x] 2.2 `src/l4/skills_cli.py`: targets, `auto` detection, manifest, update and refusal rules, `--project`,
  `--dry-run`, `--force`; `l4 skills install|status` in `cli.py`.

## 3. Doctor and init

- [x] 3.1 Tests: SCN-SKL-08; `l4 init`'s notes name `l4 skills install`.
- [x] 3.2 Doctor row SKL-003; the init note.

## 4. Docs

- [ ] 4.1 `docs/SPEC.md` (L4-SKL-001's "Not yet built" note, L4-SKL-003, SCN-SKL-04..07, the CLI table, the change row),
  README and `docs/quickstart.md` lead with `uv tool install … && l4 skills install`, the skill's `adopt.md`,
  `CHANGELOG.md` under `## 0.4.14 (unreleased)`.
