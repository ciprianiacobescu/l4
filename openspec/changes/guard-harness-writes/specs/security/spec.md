## Purpose

Agent-written code that a gate runs can never make the harness read, write or delete a file outside the worktree, and
can never stop a run with an error. The folders the sandbox masks are protected paths like every other agent
configuration folder.

## MODIFIED Requirements

### Requirement: L4-SEC-004 Agent changes to protected paths are reverted (part a)
The harness SHALL revert any change made by an agent to a protected path, meaning the contract list plus
`odd.forbidden_paths`, and MUST record the change as `guard.violation`. The contract list SHALL cover the CI files,
`.l4/**`, the agent configuration paths, the repository guidance files and directories of L4-SEC-002, and
`.serena/memories/harness/**`. The guidance paths SHALL include `.hermes/**`, `.kiro/hooks/**` and `.kiro/prompts/**`.
Every directory that the sandbox covers with a tmpfs (L4-SEC-005, `sandbox.base.GUIDANCE_DIRS`, mirrored in
`scripts/runner/sandbox-probe.sh`) SHALL be on the contract list. What an agent step or a gate run writes there SHALL
therefore be removed or restored by both the agent-step guard and the gate guards before anything is committed. A test
SHALL fail when the two lists differ.

#### Scenario: SCN-SEC-N4 (−) Agent edit to agent configuration is reverted
- **GIVEN** an agent step that modified `.mcp.json` and `.codex/config.toml`
- **WHEN** the protected-path guard runs
- **THEN** both files are restored to their pre-step content and two `guard.violation` events are logged

#### Scenario: SCN-SEC-50 (−) What an agent step writes under the masked Kiro and Hermes folders is removed
- **GIVEN** an agent step that creates `.hermes/hooks/on_start.json`, `.kiro/hooks/run-on-save.kiro.hook` and
  `.kiro/prompts/review.md`, none of which exist at the step base
- **WHEN** the agent-step guard runs
- **THEN** all three files are gone, each has a `guard.violation` with its rule (`.hermes/**`, `.kiro/hooks/**`,
  `.kiro/prompts/**`) and `action: removed`, and `git add -A` stages none of them

#### Scenario: SCN-SEC-51 (−) What a gate run writes there is removed too
- **GIVEN** a gate whose command writes the three files of SCN-SEC-50
- **WHEN** the gate guards run after the gate
- **THEN** all three files are gone and each has a `guard.violation` with `phase: gate`

#### Scenario: SCN-SEC-52 (+) Every directory the sandbox masks is a protected path
- **GIVEN** `GUIDANCE_DIRS` of `l4.sandbox.base` and the `m0_guidance` list of `scripts/runner/sandbox-probe.sh`
- **WHEN** the drift test runs
- **THEN** both lists name the same directories, and for each directory `d`, `ProtectedSet().match(f"{d}/x")` names a
  rule

#### Scenario: SCN-SEC-53 (+) A person's commit to `.kiro/hooks` on the unit branch is listed, not reverted
- **GIVEN** a unit branch on which only a person's commit added `.kiro/hooks/lint.kiro.hook`
- **WHEN** the verifier's protected-path check runs
- **THEN** the file stays, no blocker is raised, and `verification.md` lists it under "Protected paths changed by
  humans"

## ADDED Requirements

### Requirement: L4-SEC-020 Harness file operations in a worktree never follow a link (part a)
After agent-written code has run in a worktree (an agent step or a gate), every read, write and removal that the harness
makes there SHALL refuse a path with a symbolic link at any component below the worktree root, and SHALL never follow
one: the variant writes and restores of the zero-value runs and of the run at the red commit's code, their report
restores, the removal of earlier reports, the bytecode removal, the production guard, the red scope and the audit.

#### Scenario: SCN-SEC-40 (−) The zero-value restore writes nothing through a linked package directory
- **GIVEN** a test gate command that replaces `src/pytdd` with a link to a directory outside the worktree before it
  runs the tests
- **WHEN** `zeroed_run` varies `src/pytdd/pricing.py` and the gate runs
- **THEN** no file is created or changed in the outside directory, the link is gone, `src/pytdd/pricing.py` holds its
  original bytes in a real directory, and `guard.violation{phase: gate, rule: "planted link", path: src/pytdd}` is
  recorded

#### Scenario: SCN-SEC-42 (−) The restore at the red commit's code puts the agent's file nowhere outside
- **GIVEN** a green change that adds `src/pytdd/evil.pth` with content the agent chose, and a test gate command that
  replaces `src/pytdd` with a link to an outside directory
- **WHEN** `run_with_code_of` swaps the production files to the red commit, runs the gate and puts them back
- **THEN** the outside directory holds no `evil.pth`, and a `planted link` violation is recorded

#### Scenario: SCN-SEC-43 (−) A linked `.l4-out` receives no report and loses no file
- **GIVEN** a test gate that wrote `.l4-out/junit.xml` in run (a), and a gate command that then replaces `.l4-out` with
  a link to an outside directory that already holds a `junit.xml`
- **WHEN** `zeroed_run` restores the reports, and the next gate removes the earlier reports before it starts
- **THEN** the outside `junit.xml` keeps its bytes and is not removed, `.l4-out` is a real directory again, a `planted
  link` violation names `.l4-out`, and a gate run on its own (`gates.runner.run_gate`) with a linked report path fails
  with `report path .l4-out/junit.xml has a symbolic link at .l4-out` before its command runs

### Requirement: L4-SEC-020 A write replaces the name and is checked when it is made (part b)
The check of part a SHALL be made at the moment of the operation, relative to directory descriptors opened without
following links, never as a check before the gate. A file SHALL be written as a new file in its own directory and
renamed over its name, so that a symbolic link, a hard link or a FIFO in its place neither receives the bytes nor blocks
the harness. A link that is the last component of a path to be removed SHALL be removed itself, never its target.

#### Scenario: SCN-SEC-44 (−) A hard link or a FIFO in place of a varied file neither receives the bytes nor hangs the restore
- **GIVEN** a gate command that replaces `src/pytdd/pricing.py` with a hard link to a file outside the worktree, and in
  a second case with a FIFO
- **WHEN** the zero-value restore puts the original back
- **THEN** the outside file keeps its bytes, the restore returns within the test's timeout, and
  `src/pytdd/pricing.py` is a regular file with the original bytes

### Requirement: L4-SEC-020 A varied file is taken by its real path inside the worktree (part c)
A target that the harness varies SHALL be taken by its real path inside the worktree, resolved before the gate, so a
link that the repository holds at that moment is followed then and only then. A target whose real path is outside the
worktree, or under the test or test-support globs, SHALL NOT be varied.

#### Scenario: SCN-SEC-48 (+) A link the repository commits still works, and a test's own links count for nothing
- **GIVEN** a repository that commits `src/app` as a link to `../lib/app` inside the worktree, and a test that creates
  a link under its own `tmp_path`
- **WHEN** the zero-value run varies the module the test imports through `src/app`
- **THEN** `lib/app/core.py` is varied and put back byte for byte, and no `planted link` or `restore failed` is
  recorded

### Requirement: L4-SEC-020 `restore_to_base` survives a directory replaced by a link (part d)
`restore_to_base` SHALL remove a link at or above its path before it restores the path, SHALL check out a path that was
a directory at the base as that whole directory, and SHALL remove the index entries below a path that did not exist at
the base (`git rm -r --cached`), so that a directory a link replaced cannot make a guard raise.

#### Scenario: SCN-SEC-45 (−) A package directory that an agent step replaced with a link is put back without an error
- **GIVEN** a red agent step that replaces `src/pytdd` (a directory at the base) with a link to an outside directory
- **WHEN** the red scope guard and the production guard run
- **THEN** no `GitError` is raised, `src/pytdd` is a directory with its base content, the outside directory is
  unchanged, and the attempt ends with an outcome, not an exception

### Requirement: L4-SEC-021 A planted link is removed and recorded, and nothing is written through it (part a)
A symbolic link found on the path of an operation of L4-SEC-020 after a gate, at or above a production path in red's
production guard, or on a gate's report path SHALL be removed itself and recorded as `guard.violation{phase: gate, rule:
"planted link", path, action: removed, where}`, and the write SHALL be made once more into a real directory. A write
that still fails, or whose sha256 read-back differs, SHALL be recorded as `rule: "restore failed"`. No exception SHALL
leave a restore.

#### Scenario: SCN-SEC-46 (−) The production guard removes a link that a gate put in place of a production directory
- **GIVEN** red's guarded production files under `src/pytdd`, and a test gate command that replaces `src/pytdd` with a
  link to an outside directory that holds a `pricing.py`
- **WHEN** `ProductionGuard.check("test run")` runs
- **THEN** the outside `pricing.py` keeps its bytes, the link is gone, `src/pytdd` holds the base files and red's
  guarded versions, and both a `planted link` violation and the `gate-mutated-production` notes are recorded

### Requirement: L4-SEC-021 A refused write fails the implementer attempt before its commit (part b)
A recorded `planted link` or `restore failed` SHALL fail the implementer attempt before its commit: its changes are
discarded, its reason names the paths and says that a test may create links only in its own temporary directory, and
the next attempt's prompt carries the guard note. The run SHALL go on to the next attempt or step.

#### Scenario: SCN-SEC-41 (−) A link planted during the vacuity run fails the red attempt, and the run goes on
- **GIVEN** a red step whose test gate command replaces `src/pytdd` with a link to an outside directory only while the
  stub module holds no `NotImplementedError` (during run (b))
- **WHEN** `run_red` runs
- **THEN** it returns a failed `RedOutcome` and raises nothing (no `GitError`), the outside directory holds no
  `pricing.py`, `src/pytdd` is a directory again, the ledger has `guard.violation{rule: "planted link", path:
  src/pytdd}`, and the reason starts with `a gate run put a symbolic link at src/pytdd`

#### Scenario: SCN-SEC-49 (+) The next attempt is told what happened
- **GIVEN** a red attempt that failed for a planted link at `src/pytdd`
- **WHEN** the next red attempt's prompt is built
- **THEN** its previous-attempt block carries ``- `src/pytdd` (planted link) removed`` and the advice to create links
  only under the test's own temporary directory, and `task.attempt_failed.reason` in the ledger is the plain reason
  without the note

### Requirement: L4-SEC-021 In the verifier a refused write is a blocker (part c)
A `planted link` or `restore failed` recorded while the verifier runs a unit's code SHALL add a blocker finding that
names the paths, so the round ends FAIL.

#### Scenario: SCN-SEC-47 (−) A link planted during the verifier's discrimination run is a blocker
- **GIVEN** a unit whose test code, run by the verifier's `test-extra-zero` gate, replaces its package directory with a
  link to an outside directory
- **WHEN** the verifier runs step 4 and aggregates
- **THEN** nothing is written outside, the round's findings hold a blocker `a gate run planted a symbolic link in the
  worktree` that names the path, and the verdict is FAIL
