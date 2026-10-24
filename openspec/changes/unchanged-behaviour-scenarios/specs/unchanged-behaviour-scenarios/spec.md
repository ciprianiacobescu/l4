## Purpose

Spec authors learn from the skill that a scenario which already holds at the base must test code the red step's
zero-value check can break.

## ADDED Requirements

### Requirement: The skill's spec checklist has the unchanged-behaviour rule
`plugins/l4/skills/l4/references/spec.md` SHALL hold the rule **unchanged behaviour**, which names the zero-value check
of L4-IMP-002, says to test a public module-level function and assert its result's type before using it, says that code
nested in a factory cannot be zeroed, and says that logic a test checks belongs in a project module. The file SHALL stay
at or under 530 words.

#### Scenario: an agent reads the checklist
- **WHEN** the words of `references/spec.md` are counted and its text is read
- **THEN** it has at most 530 words and holds `**unchanged behaviour.**`, `zero`, `module-level` and `create_app()`
