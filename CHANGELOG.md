# Changelog

All releases of the L4 harness. Consumers pin a release tag `vX.Y.Z` (or the moving major tag `v0`). The source of a
release is the tag `src-vX.Y.Z` on `amaster`; the release commit on branch `release` holds only the shipped paths.

The version numbers follow semantic versioning for 0.x: a new feature or a change of behaviour is a minor release, a
fix is a patch release. Release 0.4.1 added features and should have been 0.5.0 (see its entry).

## 0.5.0 (unreleased)

### Added
- `l4 questions`: list the open questions of a unit, `show` one, `accept` the clarifier's suggestion or `answer` it
  with a text. The command edits `questions.md` on the unit branch, commits and pushes, which resumes the unit in CI.
  `--no-push` shows the change and writes nothing. An agent follows the same rule as `l4 yolo accept`
  (`clarifier.answer_by_agents`). Before, the command was listed in `l4 --help` but stopped with exit 2.
- A test-support file that the task's own reviewed text names (for example `` `conftest.py` ``) can be changed in the
  green step of that task. The file must keep its old statements, must not redefine a name and must not patch the
  code of the unit. The red tests of the task stay frozen. The run records `task.unfrozen{reason: "named_by_task"}`.
- A person's answer can unfreeze a named test-support file (never an ignore file).
- `l4 yolo findings --json` gives `accept_refusal {why, fix}` for a subject that cannot be accepted, and the text view
  prints `accept: not available: <why> (<fix>)`.

### Changed
- The `cache.seeded` ledger event records its digest as `digest` (it was `key`, which default secret scanners report
  as an API key in a consumer repository's archived ledgers). Readers accept both.
- The note of a blocked green question never offers an edit that the harness refuses.

### Fixed
- `validate_plan.py` read a comment after a key with a nested block (`hold:   # note`) as the key's value, so it
  ignored `yolo.hold` and reported the held units as uncovered.

## 0.4.1 (2026-10-16)

Review resolution and the lessons of the first adoption on a real consumer repository. This release added features
and changed the readiness review; by the rule above it should have been 0.5.0.

### Added
- `l4 yolo findings`: the findings of the latest review with a `Resolve:` line per criterion, and the criteria that come
  back (`persistent`).
- `l4 yolo review --worktree`: review the working tree before a push (dry by default; `--record` writes the review to
  the ledger and judges again everything the ledger does not hold).
- `l4 yolo accept` with conditions (two judged versions of the text, no blocking finding) and a reason that the
  implementer and the verifier receive; the merge guard keeps an accepted finding open until the verifier answers it.
- `yolo.review` budgets (`max_file_chars`, `max_folder_chars`, `max_dependency_chars`), `accept_after_rounds`,
  `accept_by_agents`; `yolo.hold` and `l4 init --hold-existing`.
- System One keys rendered into the workflow; Laya as the default System One (`l4 init --s1 laya|jev|none`).
- The pin guard: a run whose harness pin differs from the base branch's workflow does no work and warns.
- Doctor adoption checks; `validate_plan.py` uses the review's budgets and file set.

### Changed
- The readiness review judges only material it has not judged (the material key covers the text, the templates and
  the schema); minor-only findings count as READY; dependency material is shown spec first.
- The judge prompt is version 8. No `l4 eval --compare` baseline was made for it.
- Every material key changed, so each subject is judged once more after the upgrade.

## 0.4.0 (2026-10-15)

### Added
- Delivery plans (`l4 yolo`): plans of OpenSpec and Kiro units with dependencies, a readiness review by the judge in
  CI, activation by a person, a guarded fast-forward merge into an integration branch, `l4 yolo draft`, the plan
  validator and the plan skill reference.
- `OPENCODE_API_KEY` for OpenCode's own providers.
- The experience graph (manual `l4 kg` and `l4 lessons promote`).

### Changed
- Worktrees and unit locks are keyed by repository.

## 0.3.0 (2026-10-14)

### Added
- Operator commands: `l4 retry`, `l4 restart`, the causes shown in `l4 status`, `same_failure`, a spec push that
  re-enters the unit, Kiro reopen.
- The GitLab base branch; `l4 upgrade --action-repo`.

### Changed
- The repository is `OWNER/l4`.

## 0.2.1 (2026-10-13)

### Fixed
- Coverage survives a test that replaces `sqlite3.connect`.
- The GitHub workflow uploads `.l4-out`.
- Corrections in the runbook.

## 0.2.0 (2026-10-13)

### Added
- Human feedback (`l4 feedback`).
- The adoption kit: the harness as a GitHub setup action.
- The `l4` skill.
