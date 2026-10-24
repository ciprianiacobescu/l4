# Tasks: unchanged-behaviour-scenarios

## 1. The skill's spec checklist has the unchanged-behaviour rule (L4-ADO-014)

- [ ] 1.1 Tests first: in `tests/unit/docs/test_adoption_docs.py` and `tests/unit/docs/test_unfreeze_and_answer_docs.py`
  the word cap of `references/spec.md` becomes `<= 530`, and `test_adoption_docs.py` gains an assertion that the file
  holds `**unchanged behaviour.**`, `zero`, `module-level` and `create_app()`. Then add this bullet to
  `plugins/l4/skills/l4/references/spec.md` right after the `testability` bullet, word for word:
  `- **unchanged behaviour.** A scenario that already holds at the base is proven only if zeroing the public functions
  its tests import makes one fail by assertion. Test a public module-level function and assert its result's type
  before using it; code nested in a factory (\`create_app()\`) cannot be zeroed, so leave those cases to existing tests
  and design.md's failure cases. Logic a test checks belongs in a project module.`
  (wrapped at the file's line width; the backticks are literal).
- [ ] 1.2 `docs/SPEC.md`: L4-ADO-014's list gains "unchanged-behaviour scenarios on public module-level functions
  (L4-IMP-002)" and its cap becomes 530 words; SCN-ADO-41's Then says 530; a new scenario
  "#### SCN-ADO-55 (+) The skill warns about scenarios the zero-value check cannot prove · L4-ADO-014" (Given the skill
  files, When an agent reads `references/spec.md`, Then it finds the unchanged-behaviour rule, which names the
  zero-value check, public module-level functions and factories); a change-table row 73
  (`unchanged-behaviour-scenarios`); a `### Changed` line in CHANGELOG 0.4.30. Run `scripts/check_spec.py docs/SPEC.md`
  and `tests/unit/docs`.
