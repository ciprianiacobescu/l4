## Purpose

An agent delivers a plan by a fixed procedure: it runs one script, does the one next command the script prints, and
stops where a person decides.

## ADDED Requirements

### Requirement: L4-SKL-004 The skill gives a runbook and an error table for delivering a plan
The skill's `references/operate.md` SHALL begin, before any other section, with the rule that origin is what counts:
CI and the harness read `origin/<base>`, never the working tree, so an agent commits and pushes before `l4 yolo review
--record`, `l4 yolo accept` or `l4 yolo activate`. It SHALL then give a numbered runbook from the draft to watching an
active plan (draft, validate, commit and push, check, review, findings, at most two rounds of spec fixes per subject,
accept what this stack cannot fix, a person activates, watch), and an error table (message, cause, fix) that covers
the refusals of `review`, `accept`, `activate`, `waive` and `resume` and the messages of L4-YOLO-068..070, L4-CFG-006
and L4-AVL-012. It MUST say that activating a plan and force-accepting are a person's decisions: the agent stops and
gives the person the exact command, and never guesses another way. Every `l4` command the error table names MUST exist
in the CLI. `SKILL.md` SHALL point to the runbook and to `scripts/yolo_preflight.py`.

#### Scenario: SCN-SKL-09 (+) The operate reference starts with origin, then the runbook and the table
- **GIVEN** the skill's `references/operate.md`
- **WHEN** it is read
- **THEN** its first section after the title states that origin is what counts, then holds a numbered runbook of ten
  steps that names `yolo_preflight.py`, "at most two rounds" and "a person activates", then an error table whose rows
  include `review: --record records what CI and l4 yolo activate read`, `activate: the review of <plan> is stale
  against origin/<base>`, `cannot judge` and `did not answer within`, and every `l4 …` command in that section
  resolves to a command of the CLI

#### Scenario: SCN-SKL-10 (+) The skill hands a person's steps to a person
- **GIVEN** `SKILL.md` and `references/operate.md`
- **WHEN** they are read
- **THEN** `SKILL.md`'s rules say to run `scripts/yolo_preflight.py <plan>` and do its `Next:` line, and that
  activating and `--force` are a person's (print the command and stop); `operate.md` gives `l4 yolo activate <plan>
  --reason` and `l4 yolo accept <plan> --all --force` only as commands for the person

### Requirement: L4-SKL-005 yolo_preflight.py prints the checks and exactly one next command
The skill SHALL ship `scripts/yolo_preflight.py`, which uses the Python standard library only and runs in the consumer
repository. It SHALL check, in order: the plan file; a clean tree; `origin/<base>` after a fetch; HEAD equal to
`origin/<base>`; the plan file and the unit folders on `origin/<base>`; the judge roles' adapters (the rule of
L4-CFG-006); the installed `opencode`'s major when an opencode profile is in a role (both `--version` forms); the
target's `yolo.review.accept_by_agents`; the caller (person or agent, by the harness's markers); the installed harness;
the admission (`l4 yolo check`); and the review state (`l4 yolo status --json`). It SHALL print each check as `ok`,
`FAIL`, `skip` or `info` and then exactly one `Next:` line: the fix of the first failing check, or the runbook's next
step for this plan and this caller. For an agent, a person's step is printed as `a person runs: …` with "stop here".
`--json` SHALL print the same as one document. It SHALL exit 0 when no check fails, 1 when a check fails, and 2 for a
usage error. Every subprocess MUST run in its own process group with a deadline. Its copies of the harness's
constants (allowlist, judge roles, agent markers, the OpenCode pin and major) MUST be held equal to the harness by a
test.

#### Scenario: SCN-SKL-11 (+) A pushed, admitted plan with no review gets the review command
- **GIVEN** a clean clone at `origin/main` with plan `p1` pushed, a `claude-code` judge whose `claude` is on PATH, and
  a harness that admits the plan and reports no review
- **WHEN** `python3 -I yolo_preflight.py p1` runs
- **THEN** every check is `ok`, `skip` or `info`, the last line is `Next: l4 yolo review p1 --worktree --record`, and
  the exit code is 0; with no judge CLI on PATH the line is `Next: l4 yolo review p1 (CI reviews origin/main at its
  next run; then run this script again)`

#### Scenario: SCN-SKL-12 (−) A dirty tree or an unpushed commit fails with its fix
- **GIVEN** an uncommitted edit of a unit folder, and in a second case a committed, unpushed plan file
- **WHEN** the script runs
- **THEN** the first prints `FAIL  clean-tree` and `Next: commit the changes git status lists, then git push origin
  HEAD:main`; the second prints `FAIL  head-is-origin: origin/main (<o7>) is 1 commit behind HEAD (<h7>)…` and
  `Next: git push origin HEAD:main, then run this script again`; both exit 1 and do not call the harness

#### Scenario: SCN-SKL-13 (−) A judge that cannot judge and an OpenCode v2 fail in the harness's words
- **GIVEN** a `kiro-cli` profile in `roles.judges`, and in a second case an opencode profile with an `opencode` on
  PATH that prints `opencode v2.0.32`
- **WHEN** the script runs
- **THEN** the first fails `judge-roles` with the text of L4-CFG-006 (without ` at $`); the second fails `opencode`
  with `opencode 2.0.32 is OpenCode v2; this profile runs v1 (opencode-ai 1.x)` and `Next: l4 doctor --fix (it
  installs opencode-ai@1.18.34 user-locally), then run this script again`; both exit 1

#### Scenario: SCN-SKL-14 (+) An agent with a READY review is told to hand activation to a person
- **GIVEN** every check ok, a current review with every subject READY, and `CLAUDECODE=1`
- **WHEN** the script runs
- **THEN** `caller` is `agent (CLAUDECODE)` and the last line is `Next: a person runs: l4 yolo activate p1 --reason
  "<why>" (stop here: activation is a person's decision)`, exit 0; for a person in a terminal it is `Next: l4 yolo
  activate p1 --reason "<why>"`

#### Scenario: SCN-SKL-15 (+) A subject past two rounds is accepted by whoever may, and the output is stable
- **GIVEN** a current review whose subject `openspec:add-greeting` is NEEDS_REVISION, `findings --json` giving
  `accept_available: true` for one caller, and for another an `accept_refusal` whose fix starts with `a person runs:`
- **WHEN** the script runs for each caller, with and without `--json`
- **THEN** the first `Next:` is `l4 yolo accept p1 openspec:add-greeting --reason "<what the implementer should do>"`,
  the second is that refusal's fix followed by ` (stop here)`; `--json` prints `schema: l4/yolo-preflight@1` with
  `checks`, `next` and `exit`; the script imports only standard-library modules
