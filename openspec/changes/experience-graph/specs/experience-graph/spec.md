## Purpose

A person can read the recorded history of one repository's units across units: what keeps failing, what followed each
lesson, and how one unit got where it is. The person can also turn a recurring, recorded mistake into a lesson
through the inbox and `l4 lessons promote`. Everything is manual. Nothing reaches an agent, a prompt or a run path
unless a person promotes a lesson.

## ADDED Requirements

### Requirement: L4-KG-001 Manual only, outside every run path
`l4 kg build`, `l4 kg report`, `l4 kg why` and `l4 kg propose` SHALL run only when a person starts them.
- No module outside `src/l4/kg/` MAY import `l4.kg`. The only link MUST be the handler string in `commands.py`.
- `l4.memory.promote` and `l4.memory.inbox` MUST be imported only by `l4.memory.cli`.
- The `l4 kg` commands MUST NOT call a model, a forge API or the network.
- They MUST NOT run `git fetch`, `git push` or any git command that writes a ref, the index or a tracked file.

#### Scenario: SCN-KG-01 (+) The run path never loads the graph code
- **GIVEN** the installed harness
- **WHEN** a fresh interpreter imports `l4.cli`, `l4.orchestrator`, `l4.planner`, `l4.verifier.ladder`, `l4.state.status`, `l4.ci.sweeper`, `l4.archive`, `l4.postmerge`, `l4.memory.round`, `l4.implementer.tdd` and `l4.eval.run`
- **THEN** no `l4.kg*`, `l4.memory.promote` or `l4.memory.inbox` module is in `sys.modules`, and an AST scan finds no import of them outside the allowed modules

#### Scenario: SCN-KG-02 (−) No network, no model, read-only git
- **GIVEN** a fixture repository with units on the base branch, a unit branch and an attempts ref, `socket.socket` patched to raise, and a recording `Git`
- **WHEN** `l4 kg build`, `l4 kg report`, `l4 kg why openspec:a` and `l4 kg propose --dry-run` run
- **THEN** each exits 0, and every recorded git subcommand is one of `rev-parse`, `for-each-ref`, `ls-tree`, `cat-file`, `log`, `diff --name-only`, `check-ignore`, `ls-files`, `var`

### Requirement: L4-KG-002 Failures are contained, with the existing exit codes
An `l4 kg` command SHALL exit 0 when it finished, with every skipped input counted and shown. It SHALL exit 2 for a
usage error: an unknown id, no repository, a refused `--out`, or a cache root inside the repository. It SHALL exit 1
for an internal error. A failure MUST change no ref, no tracked file, no ledger and no `.l4/` file, and MUST NOT leave
an index that a later read takes as complete.

#### Scenario: SCN-KG-03 (−) A failed build leaves the repository and the last index as they were
- **GIVEN** a complete index, and a fault injected after `nodes.jsonl` of a new build was renamed
- **WHEN** `l4 kg build` runs
- **THEN** it exits 1, `git status --porcelain` and every ref are unchanged, and the next `l4 kg report` says `index rebuilt` and gives the same report as a clean build

### Requirement: L4-KG-003 A derived index under the cache root
The index SHALL be written to `cache_root(environ, repo) / "kg" / <first 16 hex of sha256(resolved repository path)>`,
in a folder with mode 0700, and never inside the repository. It SHALL hold:
- `nodes.jsonl` and `edges.jsonl`: sorted keys, sorted lines, LF, UTF-8;
- `manifest.json` (`l4/kg-manifest@1`): the harness version, the read refs with their shas, the counts, the skips,
  and the sha256 of the two other files.

No file MAY hold the build time. The same refs and the same harness version MUST give byte-identical files. `report`,
`why` and `propose` MUST build the index first when it is missing, incomplete, or built from refs that have moved.

#### Scenario: SCN-KG-04 (+) A rebuild is byte-identical
- **GIVEN** a fixture repository at fixed ref shas
- **WHEN** `l4 kg build` runs twice, the second time after the index folder was deleted
- **THEN** the three files are byte-identical, and the repository's `git status --porcelain` is empty

#### Scenario: SCN-KG-05 (−) A cache root inside the repository is refused
- **GIVEN** `L4_CACHE=<repo>/.cache`
- **WHEN** `l4 kg build` runs
- **THEN** it exits 2 with the L4-CFG-005 message, and nothing is written

### Requirement: L4-KG-004 Inputs are committed git objects, never fetched
The build SHALL read with `ls-tree` and `cat-file`, with the existing size caps and symlink rules, from:
- the base ref (`refs/remotes/origin/<forge.base_branch>`, else `HEAD` with a warning): the OpenSpec `changes/<name>/`
  folders, every `changes/archive/<date>-<name>/` folder, and the Kiro `.kiro/specs/<name>/` folders;
- the local unit branches `refs/remotes/origin/<branch_prefix><fw>/<name>`, each with the unit folder and its
  `<name>-fix-<n>` siblings;
- the local lock refs, merged with the branch copy as `merge_ledgers` does;
- the local attempts refs `refs/l4/attempts/<fw>/<name>/<n>`, each one as its own attempt.

The build SHALL read `.l4/ledger/*.jsonl`, `.l4/evidence/round-*/verdict.json`, `memory.lessons_file` and its
`_archive/`.

A corrupt, oversized, unreadable or non-regular input MUST be skipped and counted by reason, and MUST NOT fail the
build. An attempts ref that a `unit.restarted` event names and that is not local MUST be counted as
`attempt_not_local`, and the report MUST print the fetch command. The build MUST NOT fetch.

#### Scenario: SCN-KG-06 (+) Archived and open units are both read
- **GIVEN** an archived change `changes/archive/2026-10-05-a/` with a ledger and two verdicts on the base, and an open unit `openspec:b` whose ledger is only on `origin/l4/openspec/b`
- **WHEN** `l4 kg build` runs
- **THEN** both units are nodes, with their runs and rounds, and the coverage counts one archived unit and one branch unit

#### Scenario: SCN-KG-07 (+) A restarted unit keeps its old attempt
- **GIVEN** a unit restarted once, with `refs/l4/attempts/openspec/a/1` local and a new branch
- **WHEN** `l4 kg build` runs
- **THEN** `openspec:a@1` and `openspec:a@0` are separate attempt nodes, each with its own runs and rounds

#### Scenario: SCN-KG-08 (−) Corrupt and unsafe inputs are skipped and counted
- **GIVEN** one unit with a corrupt ledger line, and another with a symlinked `.l4/evidence/round-1`
- **WHEN** `l4 kg build` runs
- **THEN** it exits 0, the manifest has `ledger_corrupt: 1` and `not_regular: 1`, and every other unit is complete

#### Scenario: SCN-KG-09 (−) An attempt that is not local is named, never fetched
- **GIVEN** a ledger with `unit.restarted{attempt_ref: refs/l4/attempts/openspec/a/1}` and no such local ref
- **WHEN** `l4 kg report` runs
- **THEN** the coverage section has `attempt_not_local: 1` and the line `git fetch origin 'refs/l4/attempts/*:refs/l4/attempts/*'`, and no `fetch` was run

### Requirement: L4-KG-005 Typed nodes and edges, each with its source
The graph SHALL have the node and edge types of design D4. Every edge SHALL carry `src`, which is
`<sha10>:<path>#<seq>` for a ledger event or `<sha10>:<path>#/<json pointer>` for a `verdict.json` field.

A lesson SHALL be linked to a finding pattern only through its dedupe key:
- a `LESSON_RULES` key links to the recurrence key of that rule's `finding_title`;
- a `kg-*` key links to the pattern it was proposed from;
- any other lesson has no finding link.

The lesson's `Source` line MUST NOT be parsed for links.

#### Scenario: SCN-KG-10 (+) Every source pointer resolves
- **GIVEN** the index of the SCN-KG-06 fixture
- **WHEN** a test runs `git cat-file -e <sha>:<path>` for every edge's `src`, and reads the line `seq` or the JSON pointer
- **THEN** each one exists and holds the value the edge states

#### Scenario: SCN-KG-11 (−) The Source line is not a link
- **GIVEN** a hand-edited lesson whose `Source` says `verifier finding F-1234abcd (openspec:a round 1)`, and whose dedupe key is not a rule key
- **WHEN** the graph is built
- **THEN** the lesson has no edge to `F-1234abcd` or to any recurrence key

### Requirement: L4-KG-006 Recurrence across units by normalised text, labelled approximate
Recurrence SHALL be counted in distinct units, never by finding id, with the normaliser of design D5:
- **A finding's key** is the normalised title and the normalised criterion alias without its capability part. The
  second part is empty for a Kiro alias or when there is no criterion.
- **An attempt failure's class** is the first line of its `reason`, cut before the first `:` or ` (`, normalised, and
  cut to 120 characters.

Every report section that uses a key MUST say `approximate`.

#### Scenario: SCN-KG-12 (+) One mistake in two units is one recurrence
- **GIVEN** units `openspec:a` and `openspec:b`, each with a deterministic finding `UI criterion without an end-to-end test` on the scenarios `Cart › Shows count` and `Cart › Shows count`, but different criterion ids (different capability folders)
- **WHEN** the report is built with `--min-units 2`
- **THEN** one recurring-findings line names both units with `n = 2 units`

#### Scenario: SCN-KG-13 (−) The same title on different scenarios is not merged
- **GIVEN** the same finding title on `Cart › Shows count` in unit a and on `Cart › Clears` in unit b
- **WHEN** the report is built with `--min-units 2`
- **THEN** no recurring-findings line is written for that title

### Requirement: L4-KG-007 Blame from recorded fields only
Each finding, question, stop and attempt failure SHALL get exactly one blame value from design D6: `security`, `spec`,
`environment`, `verifier`, `agent`, or `unknown`. The first matching rule wins. A record that no rule matches MUST be
`unknown`. No blame MAY come from a model or from free text.

#### Scenario: SCN-KG-14 (+) A spec gap is `spec`
- **GIVEN** a `verdict.json` finding with `spec_gap: true`
- **WHEN** the graph is built
- **THEN** it has `CLASSIFIED → blame:spec`, and its capability is listed under spec-gap hotspots with `n = 1 unit`

#### Scenario: SCN-KG-15 (−) A judge finding without a spec gap is `unknown`
- **GIVEN** a judge finding (`source: judge`, `spec_gap: false`)
- **WHEN** the graph is built
- **THEN** it is `blame:unknown`

### Requirement: L4-KG-008 Lesson outcomes as recorded, as a heuristic
For each lesson, the report SHALL show:
- its injections (from `prompt.rendered{task, lessons}`), by units, runs and tasks;
- the `task.attempt_failed` of the same run and task after the injection, by failure class;
- the findings in later rounds of the same unit and attempt whose key is the lesson's linked key (L4-KG-005);
- a status: `never injected`, `injected, nothing followed`, or `injected, followed by <n> failure(s)`.

The section MUST state that it shows what followed a lesson, not what the lesson caused.

#### Scenario: SCN-KG-16 (+) The live case is visible
- **GIVEN** the events of job 5528 (`docs/live/artifacts/job-5528/l4-out/logs/r-20261005T0815Z-5946.jsonl`, which mirrors the ledger): `prompt.rendered{role: red, task: 1.1, lessons: [L-09421538]}`, then `task.attempt_failed{task: 1.1, phase: red, attempt: 1}`, then two more prompts with the lesson and no failure
- **WHEN** the report is built
- **THEN** `L-09421538` shows `injected 1 unit / 1 task / 3 prompts, followed by 1 failure (red: new tests fail with an error that is neither an assertion nor notimplementederror)`

#### Scenario: SCN-KG-17 (−) An earlier failure, or another unit's, is not counted
- **GIVEN** an attempt failure of task 1.1 before the injection, and one of another unit's task with no injection
- **WHEN** the report is built
- **THEN** the lesson shows `injected, nothing followed`

### Requirement: L4-KG-009 `l4 kg report` with n on every line
`l4 kg report [--out PATH] [--min-units N]` SHALL write markdown with the sections of design D8, in its order:
coverage, lessons, recurring attempt failures, recurring findings, gate candidates (at least `max(N, 3)` units),
spec-gap hotspots, profiles by role, and stops. N defaults to 2.
- The profiles section MUST count what the records show (runs per profile; for implementer profiles the failed
  attempts, the tasks with a failed attempt and the first-round PASS share) and MUST say that it gives no
  first-attempt pass share, because a task that passes at its first attempt leaves no record.
- Every line that carries a number MUST name its *n*, and an empty section MUST say `none (n = 0)`.
- Lines are sorted by count, then by key.
- The output goes to stdout by default. `--out` inside the repository MUST name a git-ignored path, else the command
  exits 2.

#### Scenario: SCN-KG-18 (+) Every number names its n
- **GIVEN** the SCN-KG-06 fixture
- **WHEN** `l4 kg report` runs
- **THEN** a snapshot test matches, and every line with a digit outside an id contains `n = `

#### Scenario: SCN-KG-19 (−) A report file that git would commit is refused
- **GIVEN** a repository where `docs/report.md` is not ignored
- **WHEN** `l4 kg report --out docs/report.md` runs
- **THEN** it exits 2 with `docs/report.md is not git-ignored: use .l4-out/kg/ or a path outside the repository`, and writes nothing

### Requirement: L4-KG-010 `l4 kg why ID` explains one record
`l4 kg why ID` SHALL accept a unit id, `F-<8 hex>`, `L-<8 hex>`, a run id, or `<unit>#Q-<n>`.
- **For a unit,** it MUST print the timeline of design D9, oldest first. Each line ends with its `src`. The last line
  holds the facts: stops by code, a spec edit since the last stop, and the attempt number. It names
  `l4 status --unit ID` for the next command.
- **For any other id,** it MUST print the 1-hop neighbourhood, with `src` on each edge.
- An unknown id MUST exit 2 with the accepted forms.

#### Scenario: SCN-KG-20 (+) The history of a restarted unit
- **GIVEN** a unit whose attempt 1 escalated twice with `same_failure`, was restarted, and whose attempt 2 has one FAIL round
- **WHEN** `l4 kg why openspec:a` runs
- **THEN** the timeline shows both escalations with their detail, the restart with its reason, the FAIL round of attempt 2, and the line `stops: same_failure ×2; spec edited since the last stop: no; attempt 2`

#### Scenario: SCN-KG-21 (−) An unknown id
- **GIVEN** any index
- **WHEN** `l4 kg why X-1` runs
- **THEN** it exits 2 and lists the accepted id forms

### Requirement: L4-KG-011 Redacted, local and per repository
Every text field SHALL pass `redact_text` and then `scrub_for_commit` before it enters the index, a report, `why`
output, or a proposal. The index and reports MUST stay on the person's machine. No command MAY read the index of
another repository, or combine repositories.

#### Scenario: SCN-KG-22 (+) A secret in a branch ledger is not shown
- **GIVEN** a unit branch ledger whose `task.attempt_failed.reason` holds a value of a configured redaction variable
- **WHEN** `l4 kg build` and `l4 kg report` run
- **THEN** neither the index nor the report contains the value, and both contain the redaction placeholder

#### Scenario: SCN-KG-23 (−) Two repositories never mix
- **GIVEN** repositories A and B built with the same cache root
- **WHEN** `l4 kg report` runs in B
- **THEN** the index folders differ by repo key, and the report reads only B's folder (a recording file opener shows no read under A's key)

### Requirement: L4-KG-012 `l4 kg propose` writes drafts for a person, never lessons
`l4 kg propose [--min-units N] [--dry-run]` SHALL write, for each pattern of design D10 that no lesson or
`LESSON_RULES` rule covers yet, `.serena/memories/inbox/kg-<YYYY-MM-DD>/<L-id>.md` and `<L-id>.evidence.md`.
- **The draft** is a lessons v1 file with one section, where the id is `lesson_id(dedupe key)`. Its body ends with a
  `TODO(person):` line.
- **Allowed text:** a draft MAY quote only failure classes, deterministic finding titles in their normalised form (the
  recurrence key, where a path is `<path>`, because a deterministic title can quote a path an agent chose), gate
  names, guard rule names and globs. It MUST NOT quote a judge finding, a question, an answer or an agent's output.
- **What it must not touch:** the command MUST NOT write `lessons.md`, stage, or commit.
- **Ignore warning:** it MUST warn when git does not ignore the inbox folder.

#### Scenario: SCN-KG-24 (+) A recurring red failure becomes a draft
- **GIVEN** the failure class `no new test traces <criterion>` in units a and b
- **WHEN** `l4 kg propose` runs
- **THEN** one draft with dedupe key `kg-a-no-new-test-traces-criterion` and its evidence file are in `inbox/kg-<date>/`, the draft ends with the `TODO(person):` line, `lessons.md` is unchanged, and `git diff --cached` is empty

#### Scenario: SCN-KG-25 (−) A pattern with a lesson already gets no draft
- **GIVEN** the SCN-KG-24 class, and a lesson in `lessons.md` with the same dedupe key
- **WHEN** `l4 kg propose` runs
- **THEN** no draft is written for it, and the output says `covered by L-…`

#### Scenario: SCN-KG-26 (−) Judge text never reaches a draft
- **GIVEN** a judge finding `Edge case not handled` (`source: judge`) in three units
- **WHEN** `l4 kg propose` runs
- **THEN** no file under `inbox/` contains that title, and the report still lists it under recurring findings

### Requirement: L4-KG-013 `l4 lessons promote ID` (builds L4-MEM-002's human promotion)
`l4 lessons promote ID [--from DIR] [--yes] [--no-commit]` SHALL move one inbox proposal into `memory.lessons_file`
through `apply_candidates`, with origin `human_edit`. An existing dedupe key MUST be reinforced. The caps MUST hold.

It MUST refuse with exit 2, writing nothing, when any of these is true:
- `memory.enabled` is false;
- the proposal is not exactly one valid v1 section, or its id is not `lesson_id(dedupe key)`, or a glob is invalid;
- the proposal still has a `TODO(person):` line, or an empty body;
- HEAD is detached or on a branch under `forge.branch_prefix`;
- anything is staged;
- the lessons file in the work tree differs from HEAD, or has parse problems;
- there is no terminal and no `--yes`.

It MUST print the lesson and its scope before it writes. Unless `--no-commit` is given, it MUST commit only the
lessons paths as `chore(memory): lesson <id> promoted [skip ci]`, with the person's git identity and no `L4-*`
trailer, and then delete the proposal and its evidence file.

#### Scenario: SCN-KG-27 (+) A promoted lesson reaches the next matching task through the existing injection
- **GIVEN** a draft with the TODO line replaced by advice and scope `` `src/web/**` ``, on the base branch checkout
- **WHEN** `l4 lessons promote L-… --yes` runs, and a later task's paths include `src/web/page.py`
- **THEN** `lessons.md` has the lesson, one `chore(memory)` commit by the person holds only the lessons paths, the inbox files are gone, and `inject_for_task` for that task returns the lesson's id

#### Scenario: SCN-KG-28 (−) An unfinished draft is refused
- **GIVEN** a draft that still has its `TODO(person):` line
- **WHEN** `l4 lessons promote L-… --yes` runs
- **THEN** it exits 2 with `the proposal still has its TODO(person) line`, and `lessons.md`, the index and HEAD are unchanged

#### Scenario: SCN-KG-29 (−) A promote on a unit branch is refused
- **GIVEN** HEAD on `l4/openspec/a`
- **WHEN** `l4 lessons promote L-… --yes` runs
- **THEN** it exits 2 and says that a person's commit to `.serena/memories/harness/` on a unit branch is a protected-path blocker: promote on the base branch

### Requirement: L4-KG-014 Nothing changes for a repository that does not use it
This change SHALL add no configuration key, no doctor check, no ledger event, no lifecycle edge, no prompt change and
no CI template change. Every configuration that validates today MUST still validate. `l4 lessons list` and
`l4 lessons lint` MUST keep their output. Existing tests MUST keep their assertions. Only the command tables of the
dispatch tests MAY gain rows.

#### Scenario: SCN-KG-30 (+) The existing behaviour is unchanged
- **GIVEN** the repository's existing configuration fixtures and the full unit suite
- **WHEN** the suite runs with this change
- **THEN** every existing test passes unchanged, `l4 doctor` on the dummy fixture gives the same checks as before, and `git diff` of `src/l4/config/schema.py`, `src/l4/doctor/`, `src/l4/implementer/`, `src/l4/verifier/` and `src/l4/ci/templates/` is empty
