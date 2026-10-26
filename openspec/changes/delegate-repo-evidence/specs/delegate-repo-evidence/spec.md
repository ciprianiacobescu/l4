## Purpose

The delegate may cite the files a repository keeps under its own `.l4/` folder, and still never what the harness or
the asker wrote.

## ADDED Requirements

### Requirement: Only the harness's `.l4/` files are harness-written
A `checked` entry SHALL be harness-written when its file is `questions.md` or `verification.md`, when its path has a
`.l4` part below the repository root (a unit folder's `.l4/`), when it is under the repository's `.l4/vendor/`,
`.l4/ci/` or `.l4/bin/`, or when its path starts with `.l4-out/`. Any other path under the repository's `.l4/`, such
as `.l4/config.yaml`, `.l4/gates/` and `.l4/plans/`, SHALL be checked as a repository file. The discard reason SHALL be
`checked <ref> cites a harness-written file (questions.md, verification.md, the harness's .l4/ files): not evidence`,
and the prompt (`delegate@5`) SHALL name both sets.

#### Scenario: a gate script is evidence
- **WHEN** a reply cites `.l4/gates/test.sh:44` with a quote that is at that line at the unit head
- **THEN** the entry resolves and the reply is kept

#### Scenario: a unit's ledger is not
- **WHEN** a reply cites `openspec/changes/<unit>/.l4/ledger/r-1.jsonl:3`
- **THEN** the reply is discarded with the harness-written reason
