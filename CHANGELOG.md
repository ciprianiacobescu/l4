# Changelog

All releases of the L4 harness. Consumers pin a release tag `vX.Y.Z` (or the moving major tag `v0`). The source of a
release is the tag `src-vX.Y.Z` on `amaster`; the release commit on branch `release` holds only the shipped paths.

The harness is before 1.0. Each entry says what was added, what changed in behaviour and what was fixed, so a
consumer can decide when to move its pin (`l4 upgrade --harness-ref vX.Y.Z`).

## 0.4.5 (unreleased)

### Fixed
- A rejected verification hold of a kind the harness cannot derive a task from (for example `the diff is longer than
  120000 characters`) whose reason ends with a sentence `WHEN … THEN …` is now a behaviour finding with a fix task, not
  an escalation (`no finding of this round can be converted into a fix task`). Without the scenario the unit still
  escalates, and the question of such a hold no longer promises a fix unit: it asks the reason to end with the scenario.
  Scope and coverage holds are unchanged.
- `l4 feedback add --unit U` no longer needs the unit's own branch checked out: a detached HEAD, or a local branch of
  another name, at the head of `origin/<unit branch>` is accepted (L4's worktree cache may hold the branch). The command
  says which branch the feedback goes to and prints `git push origin HEAD:<unit branch>`. From any other commit the
  refusal says how to get there, including `git switch --detach origin/<unit branch>` and `git worktree list`.

## 0.4.4 (2026-10-16)

### Added
- Escalation along `roles.implementer`: `implementer.escalate_after` (default 2, `0` turns it off). After that many
  failed attempts of one task phase on one profile, the next usable profile of the chain takes the phase, in a fresh
  session, with the reasons of the earlier failures. The harness records `implementer.escalated` or
  `implementer.escalation_skipped`. A move never parks a unit and never takes a profile that would leave no independent
  judge. `task.attempt_failed` and `breaker.tripped` name the profiles; the halt detail lists them.
- The retry note: the `--reason` of `l4 retry` and `l4 resume` on a unit halted on `max_task_attempts` reaches the
  implementer of that task, as a capped and redacted data block, until the task is done. `prompt.rendered` records
  `retry_note`. `l4 status --unit` prints a `Retry note:` line.
- Doctor check CFG-009 (warn): an escalation that cannot act (`escalate_after` not below `max_task_attempts`, or two
  profiles with the same adapter and model).
- New progress lines for the escalation, the failed attempt with its profile, the halt with its profiles and the retry
  note.
- The runbook and the skill (`adopt.md`, `operate.md`) teach the cheap-first chain and the note.
- `agent.finished` records `context_peak_tokens` (OpenCode, Claude Code: the largest input of one call, cache
  included) or `context_peak_percent` (Kiro CLI), and the progress line ends with `, context peak <n>k tokens` or
  `, context peak <p>%`. Codex and a command give none. `RunResult` has the new fields `last_message` and
  `result_problem`.
- The ledger event `result.normalized{task, phase, attempt, source, fixes}` and its progress line
  `L4 repaired the result (…)`. The event holds no text of the agent.

### Changed
- A chain of two or more profiles moves a failing task phase to the next profile by default. Each profile has its own
  attempts; the last one has `max_task_attempts`. Set `implementer.escalate_after: 0` for the old behaviour. The tasks
  of a fix unit do not move.
- The config key needs the 0.4.4 pin before the config edit (the schema is strict).
- The `# Output` section of a prompt-contract step (OpenCode, Kiro CLI, command) is the locked template `output@1`
  (`template_version` ends with `+output@1`). It asks for `status` and `summary` first, names `criteria_ids`,
  `suppressions` and `notes_for_verifier` as optional, shows a smaller schema and no longer asks for the fields that the
  harness derives (`phase`, `task_ids`, `files_changed`, `tests_added`). The prompt of Codex and Claude Code does not
  change.
- The harness repairs the result object of a step before it validates it (`result.normalized`): a missing `summary`, a
  `status` that is not allowed, a text over its limit, a malformed question, suppression or criterion id, and the
  fields that the harness derives. The harness never adds a question, never changes `blocked` and never adds a
  suppression. It can take the object from the last JSON object in the agent's final message, never from a file of the
  worktree.
- An attempt fails for its result only when the agent delivered no result object
  (`the agent's result is invalid: no result was delivered`). A `blocked` result with no question is not a failed
  attempt: it keeps raising one question made from its summary.
- The red check no longer reads the `tests_added` list of the agent. It uses the tests that the JUnit diff finds.

## 0.4.3 (2026-10-16)

### Fixed
- `l4 questions accept` and `answer` pushed the answer to the unit branch and relied on that push to start a run.
  GitHub runs a push with the workflow file of the pushed branch, which still pinned the old harness after the base had
  moved its pin: the pin guard (CFG-008) did no work and the unit did not resume. The push also started the
  repository's own CI on a unit that was in the middle of TDD, and its red tests left a misleading red check on the
  pull request. The commit now carries `[skip ci]` and the command starts a run on the base branch, as `l4 retry` does
  (`--no-run` skips it; a refused start prints how to start one by hand and exits 0).
- `l4 upgrade` now names the open unit branches on origin (from the remote-tracking refs it has, no network) whose own
  workflow copy pins another harness than the new one, and says that a push to one of them does no work and that runs
  start on the base.
- The runbook (7.1) and the skill say to start a run on the base after a hand-edited answer is pushed.
- A Python support file named in the heading of a task's section in `tasks.md` (for example `## 1. Root conftest.py`) now opens in green like one named in the task line, under the same trust check (an active plan or the base branch); a heading of another section, a glob or `../` opens nothing.

## 0.4.2 (2026-10-16)

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
- The green prompt template is version 5: it names the files of "Files this task names" and says how to change them.
- Every command and option that is not implemented says `(not yet implemented)` in `l4 --help` (`l4 unlock`,
  `l4 status --rebuild`, `l4 resume --extend-iterations`, `--extend-cost`, `l4 run --time-budget`,
  `l4 verify --dry-run`). Each one still exits 2. The runbook lists the same set.
- The `cache.seeded` ledger event records its digest as `digest` (it was `key`, which default secret scanners report
  as an API key in a consumer repository's archived ledgers). Readers accept both.
- The note of a blocked green question never offers an edit that the harness refuses.
- The text of a unit pull request and of an archive pull request says who merges it: a person, or the harness when the
  unit is in an active delivery plan with `merge: auto` (it said the harness never merges it).

### Fixed
- `validate_plan.py` read a comment after a key with a nested block (`hold:   # note`) as the key's value, so it
  ignored `yolo.hold` and reported the held units as uncovered.

## 0.4.1 (2026-10-16)

Review resolution and the lessons of the first adoption on a real consumer repository. This release added features
and changed the readiness review.

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
