# Changelog

All releases of the L4 harness. Consumers pin a release tag `vX.Y.Z` (or the moving major tag `v0`). The source of a
release is the tag `src-vX.Y.Z` on `amaster`; the release commit on branch `release` holds only the shipped paths.

The harness is before 1.0. Each entry says what was added, what changed in behaviour and what was fixed, so a
consumer can decide when to move its pin (`l4 upgrade --harness-ref vX.Y.Z`).

## 0.4.17 (unreleased)

### Fixed
- An `accept` of a held check now binds to the step the person looked at (L4-IMP-065). On 0.4.16 a task held with a `harness`
  question discarded the step's changes, and an accept covered a criterion only while its candidate tests were among the test
  ids the question named, so the next agent wrote the test again under another name and a new question was raised for the same
  criterion, without end. Now the held step is saved first, as `.l4/held/<task>-<check>.patch` in the unit folder (binary-safe,
  with the agent's result beside it), committed with the questions commit, and `question.raised` records `patch_sha256`. The
  question's Context shows the source of each named test, redacted and cut to 40 lines. The next run after an `accept` starts no
  agent for that step: it checks the digest, applies the patch, runs the guards, gates and checks an agent's changes get, records
  `held.replayed` and counts the criteria for those tests. A missing patch, a different digest or a patch that does not apply gives
  a new question that says why, never a pass. `retry` deletes the patch and runs an agent with the note; a replay deletes it in the
  step's commit; a restarted unit or a reopened task drops it. The question lists every changed path and shows the redacted diff of every changed path; a cut says that the cut lines are replayed
  too and names the patch path. The accept takes effect only through the replay of exactly that saved step: once the replay is used up
  (it failed a gate or the check refuted a criterion; a failed replay counts as an attempt), it covers nothing, and a later step
  that meets the same inconclusive check is held again with a new question. A reopened task drops every earlier accept. A later agent
  attempt gets a notice (data block `accepted tests`) that the earlier accept was for the earlier step only. All four held checks (`pre_satisfied`, `vacuity`, `at_red`, `tests`) do this. A
  question raised by 0.4.16 has no patch and keeps the old behaviour.
- The runbook and the skill no longer say that `l4 questions answer`, `accept`, `l4 retry` and `l4 restart` always start a run:
  they do when the forge token is set, and otherwise print `start a run with: …`.

## 0.4.16 (2026-10-18)

### Fixed
- `yolo.hold` holds a unit that a delivery plan only excludes: listing a held unit in a plan's `exclude` released it, so after
  a plan review the held units ran. Only the units a plan plans (a batch's units) follow the plan; an excluded unit that
  `yolo.hold` matches stays `held by yolo.hold`, and `l4 plan` / `l4 yolo status` say so. The coverage check still counts a held
  unit as covered (L4-ADO-011).
- Review of the zero-value work (L4-IMP-060..062): a missing test is the agent's (no proof) when the innermost frame of
  its own files is not an import of other code (also a `conftest.py` the unit added that stops pytest);
  the keep loop reads module-level calls of pre-existing test-support modules, and a test that failed by assertion in any
  pass counts as a proof.
- The GitHub setup action installs the harness again with `source: action` (the default for a published
  harness): since 0.4.14 the build reads the l4 skill from `plugins/l4/skills/l4` (L4-SKL-003), which the action's
  build copy and cache key left out, so every run failed with "Forced include not found". The copy and the key now
  hold the skill, and a test keeps them in step with every `force-include` of pyproject.toml.
- A check that could not run no longer fails the agent. The pre-satisfied zero-value run, the base run, run (b), the
  `test-at-red` run, the verifier's audit and the extra-proof runs are judged against the real run, per test: a test
  that failed by assertion is a proof, one that passed or failed another way is no proof, and one the run did not run
  (no report, no test collected, its module failed to import only there, skipped only there) is inconclusive. In 0.4.14
  and 0.4.15 a decorator factory zeroed to `None` broke the import of the modules that apply it, pytest stopped with
  45 collection errors and ran 0 tests, and the message said "its tests still pass"; the unit halted after nine red
  attempts on four profiles (L4-IMP-060).
- Zeroing keeps what imports need: a public function annotated to return a callable or a class keeps its body when a
  module of the varied set applies it at import time (a decorator or decorator factory, or a module-level or
  class-level call), and when a run leaves a candidate inconclusive the functions its tracebacks call, and those called
  by the module-level statements of the production module whose import failed, are kept real and the run is made again,
  at most twice (`zero.kept` records them). Every variant run goes on past collection errors
  (`--continue-on-collection-errors`), so the base run of a unit that adds a module no longer stops at the first test
  file that imports it (L4-IMP-061).
- In a zero-value run a test the unit's own files made unrunnable (it skips itself on the zero answer, its test or
  support file raises at collection, a `parametrize` over a production answer loses its id) is no proof, so the
  attempt fails as on 0.4.15; only a production module that failed to import leaves a criterion inconclusive and holds
  the task. An agent can no longer turn "not discriminating" into a held task, and an `accept` covers only the tests
  the question named.
- Every excerpt in the committed ledger, `questions.md` and the console is redacted before it is cut, so no prefix of a
  secret survives.
- A failing assertion in the setup of a fixture counts as a failure on the zero values when the fixture is in a test
  or support file the unit added or changed; in a file that was there before it is inconclusive (L4-IMP-002).
- The verifier no longer rejects an audit test, or ignores a person's or a chore's test, because a zero-value run
  could not run it: the audit records it `inconclusive` (no finding, listed in `verification.md`), and an extra test
  says why it has no proof (L4-VER-050).
- The console no longer says `(expected: zero values must fail)` for a zero-value run that ran no test, and the
  artefacts line says `not uploaded` when `ci.upload_artifacts` is false in GitHub Actions (L4-IMP-064).

### Changed
- An inconclusive check holds the task: no attempt is used, no profile escalates, the step's changes are discarded,
  one question of the new kind `harness` is raised and the unit waits in `awaiting_human` (exit 11); a delivery plan
  waits without chaining runs. A person answers `accept: <why>` (the next run counts those criteria on the evidence of
  the real run when the check is inconclusive again; audited as `via: human_override`) or `retry: <note>` (the check
  runs again, for example after an L4 upgrade). A criterion a run shows to be not discriminating still fails the
  attempt, and the message lists the inconclusive ones apart. The discrimination check of a test chore that cannot
  decide holds the chore the same way. An agent may answer only where
  `clarifier.answer_by_agents` is true on the base branch; its answer is recorded `by: agent` and labelled
  `agent_override`, never as a person's (L4-IMP-063, L4-IMP-017, L4-QMD-004, L4-QMD-009).
- A criterion whose every test imports no project module and reads a dependency's version (a version pin) is no longer
  passed: it is inconclusive ("its tests import no project module: the zero-value check cannot judge them"), the task is
  held with a `harness` question, and nothing is recorded `via: not_applicable` any more (old ledgers are still read). A
  person's `accept` counts it (L4-IMP-062).
- `gate.finished` and `task.attempt_failed` carry an `excerpt` of at most 600 characters (the `E` lines and the deepest
  repository location, redacted) in the committed ledger, for a repository that uploads no job artifacts
  (L4-IMP-064).
- `l4 status --unit`, `l4 plan` and the waiting detail of a plan name a harness question: `Cause:` quotes the check's
  reason, `Next:` the two answers, and the plan says `harness check inconclusive: Q-NNN` (L4-OPS-006).

## 0.4.15 (2026-10-18)

### Added
- `l4 mcp serve [--repo PATH]...` makes L4 an MCP server over stdio (newline-delimited JSON-RPC 2.0, protocol revision
  2025-11-25; no new runtime dependency). Its tools manage delivery plans and debug units: `l4_status`, `l4_doctor`,
  `l4_plan_status`, `l4_plan_check`, `l4_plan_findings`, `l4_plan_report`, `l4_questions`, `l4_question`,
  `l4_unit_events`, `l4_verification` (read) and `l4_plan_draft`, `l4_plan_review`, `l4_question_answer`, `l4_retry`,
  `l4_plan_resume` (write). Each tool runs the `l4` command it names in a repository the instance was started for, as an
  agent (`AI_AGENT=l4-mcp`), so every CLI rule for agents holds; `l4 yolo activate`, `cancel` and `l4 run` are not
  tools. Several `--repo` give every tool a required `repo` argument; a repository that was not named is refused.
- `l4 mcp install --client claude-code|cursor|vscode|kiro|codex|opencode [--project] [--repo PATH] [--name NAME]
  [--dry-run]` writes the client's documented MCP configuration (one entry per repository, other servers kept, atomic,
  an unparseable file refused).
- `l4 status --unit U --events [--type T] [--last N] [--json]` and `--verification` read a unit's ledger events and
  `verification.md`. The tool `l4_plan_check` runs 0.4.14's `l4 yolo check PLAN --worktree` before the push.

### Fixed
- `l4 resume` and `l4 yolo resume` refuse `--extend-cost` of `nan` or `inf` with a usage error (exit 2); the MCP tools
  refuse a non-finite number the same way.
- `l4 mcp serve`: a timed-out or cancelled call now kills its whole process group after the grace period, also when
  the command itself exited and a descendant ignored SIGTERM; the protocol is read and written as UTF-8 under any
  locale (a non-UTF-8 locale used to kill the server on `tools/list`); progress notifications carry a rising
  `progress` value; `initialize` and each tool name the served repositories, so a client with several instances can
  tell them apart.
- `l4 mcp install --client claude-code` prints the `claude mcp add` line shell-quoted, so a path with a space works.
- `l4 mcp serve`: the tool commands run with `python -P`, so a file of the served repository named `yaml.py`,
  `click.py` or an `l4` package can no longer run in place of a dependency; a stopped call's process group keeps its
  grace period after the command exited, so a descendant can clean up before it is killed; no progress notification
  follows the response of its call.
- `l4 mcp install --project` writes what each client can use: Cursor `--repo ${workspaceFolder}` (Cursor documents no
  working directory for servers), VS Code, OpenCode, Codex and Claude Code `l4 mcp serve` (they start in the project
  or set `CLAUDE_PROJECT_DIR`); Kiro, which documents neither, is refused with a hint to use the user scope. A Codex
  entry lists `forge.token_env` of `.l4/config.yaml` (else the default `L4_FORGE_TOKEN`) under `env_vars`, because Codex
  starts a server with an allowlisted environment. An existing user-scope entry whose `--repo` is a client variable is
  refused like another repository's entry instead of being rewritten. The quickstart says a project file serves a
  worktree only for a session started inside it (Claude Code desktop worktree sessions use the main checkout's file).

## 0.4.14 (2026-10-17)

### Added
- `l4 yolo check <plan> --worktree` checks a delivery plan before the push, with the installed `l4`. It reads the plan
  files and the units from the working tree, runs the admission of `l4 yolo check`, and adds the checks across all plan
  files that only `scripts/validate_plan.py` ran (`uncovered`, `covered_twice`). It prints the findings, the order and the
  budget warnings, writes nothing, and exits 0 or 2. `l4 yolo draft` and `l4 yolo review --worktree` name it in their
  hints. The script stays for an agent or a CI step without the harness, and a parity test holds the two together.
- `l4 skills install` puts the `l4` skill into the skill folder of every coding agent, with no network and no clone:
  the skill now ships inside the wheel and the sdist. User scope writes `~/.claude/skills/l4`, `~/.agents/skills/l4`
  (and `~/.codex/skills/l4` when that folder exists), `~/.config/opencode/skills/l4` and `~/.kiro/skills/l4`;
  `--project` writes `.claude/`, `.agents/`, `.opencode/` and `.kiro/` `skills/l4` in the repository. `--agent auto`
  (the default) takes the agents whose home folder or CLI (`claude`, `codex`, `opencode`, `kiro-cli`) is present. Each
  copy has a manifest `.l4-skill.json`; a rerun updates an untouched copy, refuses an edited one (exit 2) unless
  `--force`, and never follows a symbolic link. `--dry-run` prints the plan. `l4 skills status` lists the copies with
  version, `current` or `old`, and edited files. Doctor row SKL-003 warns about an installed skill older than `l4`, and
  `l4 init` names the command (L4-SKL-003).

### Fixed
- A delivery plan no longer starts a run every minute for a unit that waits for capacity. A plan step that dispatches a
  unit in `waiting_capacity` starts no next run, and a unit that parks twice for the same profiles with none cooling
  (an expired provider key, a missing binary) stops the plan with `capacity_needs_fix`; the stop names the profiles,
  their failures and the fix, and `l4 yolo resume` goes on after it (L4-YOLO-035). A park with a cooling profile still
  waits for its reset.

## 0.4.13 (2026-10-17)

### Added
- `ci.toolchains` provides the toolchains a polyglot repository's gates need. The generated GitHub workflow (action,
  copy and plain forms) sets up Go, Node and pnpm before L4 with `actions/setup-go`, `actions/setup-node` and
  `pnpm/action-setup`, pinned by commit sha and with their own dependency caches off; each entry takes exactly one of
  `version` and `version_file` (pnpm: `version`). Without it the workflow is unchanged. New default caches `gobuild`
  (`GOCACHE`) and `pnpm` (the store directory); with a `go` entry the gates run with `GOTOOLCHAIN=local` and
  `GOFLAGS=-mod=readonly`. Doctor row TOOL-001 names a gate command whose first word is not on the gate PATH (a warning
  in `l4 doctor --adoption`, an error in a CI run), and `l4 init` proposes `ci.toolchains` from `go.work`/`go.mod`,
  `.nvmrc`/`engines.node` and `packageManager: pnpm@X`.

### Fixed
- A repository that adopts L4 with finished Kiro specs is no longer stopped by them. Doctor's SPEC-002 was an error and
  intake rejected the unit for history L4 never runs: a done leaf without a `_Requirements:_` line, or with a
  reference no criterion has, a `## Task Dependency Graph` whose block is a mermaid diagram, a whole-requirement
  reference such as `_Requirements: 1_`, `## Requirement N` with `### Acceptance Criteria` (one heading level higher
  than `### Requirement N` with `#### Acceptance Criteria`), and a number inside a word such as `ADR-0014.8` or
  `AC3`. Now a done leaf's missing or unresolvable link and a graph block that is not JSON are warnings (the tasks run
  in document order); a pending leaf keeps its rule, and a JSON graph that is wrong stays an error. A reference `N`
  resolves when requirement `N` has criteria, both heading levels are read, and a number counts as a reference only
  when it stands alone. SPEC-004 lists the pending leaves only.

## 0.4.12 (2026-10-17)

### Changed
- A delivery plan with `merge: auto` now squash-merges each verified unit by default, and deletes the merged branches.
  Behaviour change on upgrade: the harness used to push the unit head to the target as a fast-forward and never deleted a
  branch. Now it calls the forge's merge, pinned to the verified head, so the target gets one commit (the PR title and
  ` (#<pr>)`, with the trailers `L4-Unit`, `L4-Verified-Head` and `L4-Run`; `unit.merged` records `merge_commit`,
  `method` and `raced`), and, once the forge shows the PR merged, it keeps the verified head at
  `refs/l4/merged/<framework>/<name>` and deletes the unit branch under a lease (and the archive branch after the archive
  merge). A branch a person pushed to after the merge stays (`unit.branch_kept`); a plan step also cleans up to five
  branches of earlier merges. The lock ref is not deleted. The forge's token must be allowed to merge PRs; a forge that
  refuses a squash stops the plan with `merge_refused`. To keep the old behaviour set `yolo.merge.method: fast-forward`
  and `yolo.merge.delete_branches: false`. The evidence link in a PR body now names the head commit, not the branch
  (L4-YOLO-008, L4-YOLO-032, L4-YOLO-033).
- The archive step no longer builds a worktree for a merged unit whose folder is already archived on the base.
- The hand-off refreshes the PR body's evidence link only while the body is still the harness's own; a body a person
  edited stays.

## 0.4.11 (2026-10-17)

### Fixed
- A test of a context manager can prove its criterion. The zero-value run rewrote a `@contextmanager` function (or its
  red stub) to `return None`, so every `with` raised a `TypeError` before the test body ran, and no test could fail by
  assertion: on a consumer repository a unit halted after five red attempts on `search_phase`. Now a context manager's
  zero value enters and yields the zero value of what it yields, a generator yields nothing, and a function annotated
  to return a context manager or an iterator returns a null one. The `vacuous` message says how to test a context
  manager.
- A test gate reads every report it lists. With several reports in `gates.test.reports`, the harness read only the
  first one that existed, so the tests of the other suites were invisible to red, green and the verifier (on a
  consumer repository with three Python projects, the 423 tests of two suites). Now every listed report must exist (else
  `report missing: <report>`), and the reports are merged; a test in two reports keeps its worse result.

- Doctor's CI-003 no longer lists a job that a `typecheck` or `build` gate mirrors: verification runs those gates in
  every round, but the row counted them only when a `yolo.profiles` entry named them. It also ignores `uv run`'s
  `--directory`, `--project`, `--package`, `--frozen`, `--locked` and `--no-sync` options when it compares commands.

### Changed
- The adoption docs and the `l4 init` note name the public harness first: the plain `--action` form needs no deploy
  key for any repository. The copy form and the deploy key are for a private harness.

## 0.4.10 (2026-10-17)

### Fixed
- A finding a person rejects with a `WHEN … THEN …` becomes a fix task even when it cites no criterion and the parent
  has several requirements. The fix-unit planner put a scenario under the cited criterion's requirement, else the
  parent's only one, and dropped it otherwise, so the unit escalated with `no finding of this round can be converted
  into a fix task`. That is the path the 0.4.8 runbook gives for `task <key> is ticked as already satisfied, but its
  text is not done`: on a consumer repository, the reject of that finding stopped the delivery plan. Now the scenario
  goes under an ADDED requirement of its own, `<finding title> — finding <id>`, in the parent's first capability by
  name, as a feedback item's does. A judge's spec-gap suggestion that no person asked for is unchanged.

## 0.4.9 (2026-10-17)

### Fixed
- The zero-value run finds the modules a test imports in a workspace layout. It looked each import up under the
  repository root and `src/` only, so in a uv workspace, where each member keeps its code under
  `packages/<name>/src/<namespace>/<name>/`, it found no module to vary and refused every test of existing behaviour
  with `no project source module is imported by those tests`. On a consumer repository, four of six units lost a red
  attempt to it, and one unit then proved a scenario that pins existing behaviour with tests of the new path. Now an
  import is also looked up under every directory named `src` and every directory with a `pyproject.toml`,
  `setup.py` or `setup.cfg` (and its `src`), from git's tracked and not-ignored files. The head stubs of run (b),
  the verifier's audit sampling and the proof of tests people wrote use the same lookup.

## 0.4.8 (2026-10-17)

### Fixed
- A task that an earlier task already did no longer writes a copy of tests that exist. A red step had to add new test
  functions even when an earlier task of the unit had written and proved the tests of every criterion it cites, so
  each such task added a near-copy of them (on a consumer repository, four classes that assert one contract, and about
  4,400 test lines across four units). Now a red step may add no test and report `criteria_ids` and
  `tdd_exemption: {reason: "already_satisfied by <task>"}`. The passing tests that already trace those criteria are
  then its proof, confirmed as new tests are (the earlier red, the zero-value run, the base run), and the task is
  committed `already satisfied` with no test change.
- A test fixture shaped like a token no longer halts the unit. A red step wrote a redaction test whose fixture spells
  a token whole, as the file's existing tests do; the push scan refused the push and the unit halted with `secret in
  the outgoing commits`, and the plan stopped. Now each implementer step's changes are read for secrets before any
  gate or commit: a hit discards the attempt and tells the agent to build such a value from parts at run time
  (`"mk_" + "agent_" + "A" * 24`), and the next attempt gets that advice. The contract template says the same up
  front. The push scan stays as the last net.
- The confirmation by an earlier red holds for tests in a class. It turned `pkg.tests.test_x.TestY::test_z` into the
  path `pkg/tests/test_x/TestY.py`, found no file, and confirmed nothing, so every such criterion took the zero-value
  run and the base run.

### Added
- The judge checks each task ticked as already satisfied against its own text. The prompt lists those tasks with the
  criteria and tests that proved them, and the reply answers `satisfied: [{task, holds, evidence}]`. A `holds: false`
  is a major finding (`task <key> is ticked as already satisfied, but its text is not done`) that goes to a person.
  Before, a task whose criteria an earlier step satisfied was ticked although its own work (a README line) was never
  done, and the round passed. The judge prompt is `judge@9`.
- The red prompt says when to add no test, and that `already_satisfied` needs the task's own text to be true. The
  skill's `spec.md` has a **tasks** rule: put a behaviour's tests in the task that implements it, write no gate-only
  task, and give a document edit a check that a red step can test.

## 0.4.7 (2026-10-17)

### Fixed
- A unit whose verification passed because a person accepted a hold is merged again by a `merge: auto` plan. The hold
  (for example `the diff is longer than 120000 characters`) was accepted, and the next round reused the judged steps
  without calling the judge. That round did not carry the judge's answers to the plan's accepted review findings, so
  the merge guard found none and the plan waited with `accepted_finding_open`, every finding `no answer recorded`. A
  resumed round now records the answers of the round it reuses again, with `reused_from`.
- A judge reply that leaves out an accepted finding or a feedback item it was asked about is asked once more. The
  second call names the missing ids. A valid second reply is the verdict (`reply: retried`). A broken second reply
  keeps the first verdict. Before, the reply counted as valid, the finding was `not answered`, and a feedback item
  counted as not addressed.

### Added
- `l4 yolo waive PLAN F-id --reason TEXT [--withdraw] [--yes] [--no-run]`: a person (or an agent, when
  `yolo.review.accept_by_agents` is true on the base branch) waives an accepted finding of an active plan on record.
  The merge guard counts it as answered and the harness merges the unit itself, through its guarded merge. The
  report and `l4 yolo status` show the waiver.
- For a plan that waits with `accepted_finding_open`, `l4 yolo status` names the ways out in its `Next:` line:
  `l4 retry` when the verifier gave no answer, `l4 feedback add` when the code must change, `l4 yolo waive` when the
  finding needs no handling.

## 0.4.6 (2026-10-17)

### Fixed
- A unit no longer loops on a rejected verification hold after the fix was given as feedback. The round raised a hold
  (for example `the diff is longer than 120000 characters`), a person rejected it in prose with no `WHEN … THEN …`, and
  the round escalated with `no finding of this round can be converted into a fix task`. The person then gave the fix
  with `l4 feedback`, the feedback fix unit finished and round 4 judged every item fixed, but the old reject stayed in
  force: the same hold came back, the verdict was FAIL, and a retry repeated it. Now a feedback-only fix unit consumes
  the rejects its round could not convert: the verifier drops a reject recorded before a `fix.spawned` with
  `feedback_only: true` (so a ledger written by 0.4.5 and older needs no repair), and new ledgers list those
  questions in `fix.spawned.consumed` and mark the event `lists_unconverted: true`, so that only the listed rejects end.
  A hold that is raised again is asked as a new question on the fixed code.
- The escalation `no_convertible_finding` now names its way out. `l4 status --unit`, `l4 status --json`, the refusal of
  `l4 run --unit` and the note on the merge request say that a retry alone repeats the same verdict, and to give the fix
  as feedback (`l4 feedback add --unit U --kind behaviour --when … --then … --text …`, then the git lines) before
  `l4 retry`. Other causes keep their text. The runbook has the procedure (7.3.1).
- `l4 questions answer Q-NNN --unit U --text TEXT --replace` replaces the answer of an answered verdict question on
  purpose. Before, the command refused it and the only way was a hand edit that nothing explained. The new answer is
  recorded as a new verdict (the latest per target wins); the previous answer stays in a comment under it, and the
  commit says `(answer replaced)`. Without `--replace` the refusal stays and its `Fix:` line names the flag. A
  clarification answer is still changed by hand (L4-QMD-006).
- `l4 yolo status` no longer shows a dependency where there is none. A plan runs one unit at a time, and a unit with no
  prerequisite left said `waits for <unit> (not integrated)`, the same words as a real dependency. It now says
  `waits for its turn: <unit> runs first (one unit at a time)`.

## 0.4.5 (2026-10-16)

### Added
- A heartbeat line while an agent step runs: `task <k> <phase> attempt <n>: <profile> working 6m, 14 tool calls, last
  activity 20s ago`, with `, <m> tool calls open for <t>` while a tool call is open. The key `implementer.heartbeat`
  sets the interval (default `2m`, minimum `30s`, `0` turns it off). The line holds counts and times only, and no text
  of the agent.
- `implementer.idle_timeout` (default `10m`, minimum `1m`, `0` turns it off) and the ledger event `agent.idle`: an agent
  that prints nothing for that time and has no open tool call is stopped, and the attempt fails with a reason that names
  the key.
- `l4 status` has the column `LAST`. `l4 status --unit` has the lines `Last activity:` and `Open run:` (with the CI link
  of the run), and `--json` has `last_activity` and `open_run`. `l4 yolo status` shows `last activity` and `open run`
  of the current unit. The event `run.started` records the CI link, as `run.started.ci_url`.
- The red gate line `red: <n> new tests fail, as intended`, and `gate.finished.red_new_failing`.
- The job summary of GitHub Actions lists each finished task.
- The runbook procedure 4.6 `Is the job stuck?`.

### Changed
- An idle agent gets SIGINT and 5 seconds before the kill, and is not stopped while a claude-code, codex or kiro-cli
  tool call is open.
- The failure reasons of an idle stop and of the step time limit (30 minutes) name the cause.
- The step start line is at INFO.
- The new keys need the 0.4.5 pin before the config edit (the schema is strict).

### Fixed
- A person's answer can now open a pre-existing test that the task must change. Before, the test path freeze put such
  a test back in every green attempt, even after a person accepted the harness's own question that named the file and
  the edit (the unit halted on `green broke existing tests`, and no `task.unfrozen` was recorded). Now an answer
  (`accepted` or `answered`, on the same conditions as for a red test or a support file) that names a tracked test file
  that the red step did not touch opens it for that task's green. It is recorded in `task.unfrozen`, listed in the green
  prompt, accepted by the verifier, and `l4 questions show` says that an accept unfreezes the pre-existing test. The
  red tests of the task and the ignore files stay frozen.
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
