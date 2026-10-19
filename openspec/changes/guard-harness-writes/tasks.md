Every task follows these rules:
- Read `design.md` (the section the task names) and the requirement in `specs/` before you start.
- Write the named tests first and see them fail on the code as it is, then write the code. A test that ports a
  reproduction asserts the **fixed** behaviour: the reviewer's assertions are inverted. For example, "nothing was
  written outside" replaces "the file was written outside". Such a test must fail before the change.
- The reproductions, for reference: `test_verify_impl1_symlink.py` and `test_verify_impl3_config.py` under
  `$SCRATCH/l4review/verify-implementer/repo/tests/unit/implementer/`, and `r3_protected_guard.py` under
  `$SCRATCH/l4review/verify-sandbox-security/`. `$SCRATCH` is
  the review's local scratch directory, outside the repository.
  When the files are gone, the scenario texts in `specs/` hold everything a test needs.
- A gate command that plants a link is a `sh -c '… ; exec <TEST_COMMAND>'` string, where `TEST_COMMAND` comes from
  `tests/unit/conftest.py`, as in the reproductions. Outside directories are under `tmp_path`.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run `ruff check .`,
  `ruff format --check` on the files that changed, and `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...`. Stage explicit paths only. Name a consumer "a consumer
  repository".

## 1. File primitives that never follow a link (L4-SEC-020; design D1)

- [x] 1.1 Tests in `tests/unit/test_fsutil_inside.py` (new), on a `tmp_path` tree with an outside directory:
  - `linked_component` finds a linked parent, a linked last component, or nothing.
  - `remove_link` removes a link and leaves its target.
  - `read_inside` / `write_inside` / `unlink_inside` under a linked parent raise `LinkedPath`, whose `.link` is
    `"pkg"`, and the outside directory is unchanged.
  - `read_inside` of a linked last component raises `LinkedPath`.
  - `write_inside` over a link, a hard link and a FIFO replaces the name: the other file keeps its bytes, the call
    does not block (guard the test with a 5 s timeout), and the name is a regular file.
  - `read_inside` of a FIFO raises `UnsafeFile` at once.
  - Missing parents are created as real directories.
  - `mode=` is applied.
  - A directory at the name raises `UnsafeFile`, and no `.l4tmp.` file is left.
  - A `..` or absolute path raises `ValueError`.
  - A root whose absolute path holds a link (macOS `/var`) works.

  Then add `LinkedPath(UnsafeFile)`, `linked_component`, `remove_link`, `read_inside`, `write_inside`,
  `unlink_inside` and the internal `_parent_fd` to `src/l4/fsutil.py`, exactly as D1 says. Use `os.rename` with
  `src_dir_fd`/`dst_dir_fd`, not `os.replace`. On `ELOOP` or `ENOTDIR`, lstat the component before you raise
  `LinkedPath`.

## 2. The record of a refused write (L4-SEC-021; D4)

- [x] 2.1 Tests in `tests/unit/implementer/test_unsafe_record.py` (new), with `make_bench([])`:
  - `wb.refused_write(LinkedPath("src/pytdd"), path="src/pytdd/pricing.py", where="test-zero")` removes the link but
    not its target, and emits one `guard.violation{phase: "gate", rule: "planted link", path: "src/pytdd", action:
    "removed", where: "test-zero", target: "src/pytdd/pricing.py"}`.
  - A second call for the same link emits nothing.
  - `refused_write(UnsafeFile("… is a directory"), …)` emits `rule: "restore failed", action: "refused", why`.
  - `wb.unsafe_reason()` returns `""` when nothing was recorded, the two texts of D4 otherwise, and caps the list at 5
    paths with `(+N more)`.
  - `guardnotes.note_of` makes a note of both events, and `guard_note_text` carries the two new `_ADVICE` texts.
  - `run_task` clears `wb.unsafe` at the start of each attempt: a record of attempt 1 is not in attempt 2's reason.

  Then add `UnsafeWrite`, `Workbench.unsafe`, `refused_write` and `unsafe_reason` in
  `src/l4/implementer/workbench.py`, and `_ADVICE["planted link"]` and `_ADVICE["restore failed"]` (D4 texts) in
  `src/l4/implementer/guardnotes.py`. In `src/l4/implementer/loop.py`, call `wb.unsafe.clear()` next to
  `wb.guard_notes.clear()`.

## 3. The restores of the discrimination runs and the gate runner (L4-SEC-020; D2, D3)

In every task of this group: no exception may leave a `finally`, and an `UnsafeFile` goes to `wb.refused_write`.

- [x] 3.1 Port reproduction 1 (`zeroed_run`) into `tests/unit/implementer/test_planted_links.py` (new), with the
  assertions inverted. This is SCN-SEC-40. The test asserts that the outside directory is unchanged, that `src/pytdd`
  is a real directory holding the original `pricing.py`, that a `planted link` violation names `src/pytdd`, and that
  nothing raises. Then, in `src/l4/implementer/discrimination.py`:
  - add the `_put` helper (D3);
  - in `zero_values_in_place`, take canonical targets before the variant write (D2), skipping a real path that is
    outside the worktree or under the test or test-support globs;
  - read originals with `read_inside` and keep their mode;
  - write the variant and the restore with `_put`;
  - do the sha256 read-back with `read_inside`, and send a mismatch to `wb.refused_write` (`restore failed`) instead
    of raising `RuntimeError`.
- [x] 3.2 Port reproduction 3 (`run_with_code_of` with `evil.pth`) into the same file, with the assertions inverted.
  This is SCN-SEC-42. Then make the same changes to `red_code_in_place`: canonical targets, `read_inside` originals,
  `_put` for the swap and the restore, and `unlink_inside` for the set-aside of a module that green added.
- [x] 3.3 Port reproduction 4 (the report restore through a linked `.l4-out`) into the same file, with the
  assertions inverted. This is the first half of SCN-SEC-43. Also test that `_drop_bytecode` under a linked
  `__pycache__` removes the link and no outside `.pyc`. Then:
  - make the report restores of `zeroed_run` and `run_with_code_of` use `read_inside` for what they keep, and `_put` /
    `unlink_inside` to put it back;
  - make `_drop_bytecode` take `(root, rel)` and work on directory descriptors (D3).
- [x] 3.4 In the same file, test SCN-SEC-44:
  - the gate command replaces `src/pytdd/pricing.py` with a hard link to an outside file; in a second test, with a
    FIFO (`mkfifo`);
  - `zeroed_run` returns within 10 s and the outside file keeps its bytes.

  Then test SCN-SEC-48:
  - a base commit that holds `lib/app/core.py` and `src/app -> ../lib/app` (a relative link), and a test that imports
    `app.core`;
  - `confirm_pre_satisfied` varies `lib/app/core.py`, the file's bytes after the run equal its bytes before, and
    `wb.unsafe` is empty.

  Fix what fails, in `discrimination.py` only.
- [x] 3.5 Tests in `tests/unit/gates/test_runner_links.py` (new), for the second half of SCN-SEC-43:
  - `gates.runner.run_gate` with `.l4-out` linked to an outside directory that holds `junit.xml` fails with `report
    path .l4-out/junit.xml has a symbolic link at .l4-out`. The command never ran: assert that a marker file it would
    create is absent. The outside `junit.xml` keeps its bytes.
  - A command that plants the link after it wrote the report gets a failed result with that reason, and the outside
    file is not read. Assert with a non-XML outside `junit.xml` that the reason is not `report unreadable`.

  In `test_planted_links.py`, add a test that `Workbench.run_gate_spec` records and removes a linked report path
  before the gate and after it. Then:
  - in `src/l4/gates/runner.py`, use `unlink_inside` for the earlier reports and check `linked_component` before the
    parse;
  - in `Workbench.run_gate_spec`, check the report paths before the gate and in its `finally`, through
    `refused_write`.

## 4. `restore_to_base`, the production guard and the step checks (L4-SEC-020, L4-SEC-021; D4, D5)

- [x] 4.1 Add `links: Mapping[str, str]` to the fake adapter's `Step` in `src/l4/agents/fake.py`. It maps a
  worktree-relative path to a link target and is applied after `writes` and `deletes`: a file or directory at the
  path is removed first, then `os.symlink(target, path)` runs. Test it in `tests/unit/agents/test_fake.py` (a file,
  a directory and a missing path replaced by a link).
- [x] 4.2 Unit tests of `restore_to_base` in `tests/unit/implementer/test_restore_links.py` (new):
  - a linked directory that was a tree at the base comes back whole;
  - a new linked path is removed and leaves no index entries;
  - a link at the path, where the base had a link, comes back as the base's link;
  - a new directory is removed.

  Then test SCN-SEC-45: a red step with `links={"src/pytdd": str(outside)}` plus the red test. `run_red` raises no
  `GitError`, `src/pytdd` is a directory with its base files, the outside directory is unchanged, and the result is an
  outcome, not an exception. Then rewrite `restore_to_base` in `src/l4/implementer/stubs.py` as D5 says, dropping the
  `existed` parameter, and update its callers: `enforce_red_scope` (three calls), `ProductionGuard.check`, and
  `tdd.py` (the unused-stub restore). In `enforce_red_scope`, write the rebuilt file with `write_inside` and handle an
  `UnsafeFile` from it as D5 says.
- [x] 4.3 In `test_restore_links.py`, test SCN-SEC-46: build `ProductionGuard(wb, base)` after a fake red step, run a
  gate whose command replaces `src/pytdd` with a link to an outside directory that holds `pricing.py`, then call
  `guard.check("test run")` directly, and assert everything the scenario says. Then test SCN-SEC-41: port
  reproduction 2 with inverted assertions. `run_red` raises `PlantedLink` (owner decision 1: the
  unit halts) whose message starts with `a gate run put a symbolic link at src/pytdd`, writes no outside `pricing.py`, and leaves `src/pytdd` a directory and the
  worktree clean. Then change `ProductionGuard` in `src/l4/implementer/stubs.py` as D5 says (`_read` → `read_inside`, the
  link collection through `wb.refused_write`, `write_inside` for guarded files). In `tdd.py`, add `PlantedLink` and
  `stop_on_unsafe` (D4, owner decision 1) and make `tampered(where)` run `guard.check` and then `stop_on_unsafe`.
- [x] 4.4 Tests in `test_restore_links.py`:
  - green: a fake green whose code makes the `test-at-red` gate plant a link. Use a gate condition on the swapped
    content and a marker file under `tmp_path`, as reproduction 2 does. The test is unfrozen by a human answer so that
    `fails_at_red` runs (`tests/unit/implementer/test_tdd_green.py`). `run_green` raises `PlantedLink` and makes no
    commit.
  - single: a tests chore whose discrimination run plants a link raises `PlantedLink` before its commit.
  - SCN-SEC-49: a gate that replaces `src/pytdd/pricing.py` with a directory during run (b) is `restore failed`: the
    first attempt fails, the run goes on, and the second request's prompt
    (`bench.adapter.requests[1].prompt`) holds ``- `src/pytdd/pricing.py` (restore failed) refused`` and the advice
    text. The `task.attempt_failed` reason holds no note text.

  Then add `reason = stop_on_unsafe(wb) or reason` before `if reason:` in `run_green` and in `run_single`
  (`src/l4/implementer/tdd.py`).
- [x] 4.5 Tests in `tests/unit/verifier/test_planted_links_verifier.py` (new), following
  `tests/unit/verifier/test_ladder_evidence.py`, for SCN-SEC-47: the unit's code plants a link during the verifier's
  `test-extra-zero` gate. The findings hold the blocker that names the path, the verdict is FAIL, and nothing is
  written outside. Also test that an audit test file under a planted link is not removed through it: the outside file
  stays. Then use `unlink_inside` for the three removals in `src/l4/verifier/audit.py`, routing an `UnsafeFile` to
  `wb.refused_write`. In `src/l4/verifier/ladder.py` `verify_unit`, add the D4 blocker when `wb.unsafe` is not
  empty, before `_finalize` and before the `else` branch's `aggregate_unit`. The test calls the verifier's
  `discriminate_extra` and `_unsafe_findings` on a workbench, not a whole `l4 run`.
- [x] 4.6 The halt (owner decision 1; D4, SCN-SEC-54). Tests: in `tests/unit/orchestrator/test_halt_codes.py`, `l4 run`
  with a gate that plants the link ends in exit 13, `phase.changed{reason: planted_link}`, `breaker.tripped{reason:
  planted_link, links}` and one agent request. Then catch `PlantedLink` in `orchestrator._implement` (the halt code
  `planted_link`, the evidence in `breaker.tripped`) and in `verifier/fixloop.py` (`FixOutcome.code`), and read the code
  in `Orchestrator._fix`.
- [x] 4.7 No committed link that points outside the worktree (owner decision 3; D11, SCN-SEC-55, SCN-SEC-56). Tests in
  `tests/unit/implementer/test_outside_links.py` (new), with the fake adapter's `links`: red (an absolute link under a
  test path, and a `..` escape), green and a fix chore fail with the reason and a `guard.violation`, no commit is made;
  a relative link inside the worktree and a link the base holds pass. Then add `escaping_links` to `stubs.py`,
  `outside_links_reason` and its three call sites to `tdd.py`, and `_ADVICE["link outside worktree"]` to `guardnotes.py`.

## 5. The masked agent folders are protected (L4-SEC-004; D10)

- [x] 5.1 Port `r3_protected_guard.py` to `tests/unit/security/test_protected_guidance_dirs.py` (new), with the
  `make_repo` / `git_for` fixtures of `tests/unit/conftest.py` (the plant list holds `.kiro/skills/l4/SKILL.md` too,
  owner decision 4):
  - SCN-SEC-50: `revert_protected` removes the three agent-written files, each with its rule, and `git add -A`
    stages none.
  - SCN-SEC-51: `snapshot_protected` → plant → `restore_protected` + `revert_unsnapshotted` removes them.
  - SCN-SEC-52: the drift test. For every `d` in `GUIDANCE_DIRS`, `ProtectedSet().match(f"{d}/x")` is not None, and
    the `m0_guidance` list parsed from `scripts/runner/sandbox-probe.sh` equals `GUIDANCE_DIRS`.
  - SCN-SEC-53: `check_protected` on a branch where only a person's commit added `.kiro/hooks/lint.kiro.hook` lists
    it in `Outcome.human` and raises no blocker. Use `tests/unit/verifier/_integrity_helpers.py`.

  Then add `".hermes/**"`, `".kiro/hooks/**"`, `".kiro/prompts/**"` and `".kiro/skills/**"` to
  `CONTRACT_PROTECTED_GLOBS` in `src/l4/security/protected.py`, with a comment that names
  `sandbox.base.GUIDANCE_DIRS`; add `.kiro/skills` to `GUIDANCE_DIRS` and to `m0_guidance` of
  `scripts/runner/sandbox-probe.sh`; list `skills` in the Kiro test of `tests/unit/sandbox/test_bwrap_argv.py`.

## 6. What gate and runner configuration is (L4-IMP-040; D6)

- [x] 6.1 Tests in `tests/unit/config/test_gate_config_globs.py` (new):
  - the new default entries of `tdd.gate_config_globs` and `.coveragerc` in `tdd.runner_config_files`;
  - `tdd.extra_gate_config_globs` is appended once, after a set `gate_config_globs` too;
  - an unknown key is still refused.

  Then add the defaults to `src/l4/config/defaults.py` and `extra_gate_config_globs` to `TddCfg` in
  `src/l4/config/schema.py` (`_merge_extras`). `tests/unit/config/test_schema.py` compares the defaults with the
  §3.2 YAML of `docs/SPEC.md`, so in the same task, update the `tdd:` block of §3.2 in `docs/SPEC.md`: the new globs,
  `.coveragerc`, and `extra_gate_config_globs: []` with a comment. Run `tests/unit/config/test_schema.py` too.
- [x] 6.2 Tests in `tests/unit/implementer/test_gateconfig.py` (new), covering `GateConfig.of`, `kinds`,
  `view` and `changed` (design D6):
  - each table row of D6, with one file each;
  - SCN-IMP-246: `packages/api/ruff.toml` and `packages/api/pyproject.toml` `[tool.mypy]` count;
  - SCN-IMP-247: a comment line and a key reorder inside `[tool.ruff]` give no changed section;
  - the `markers` exception (owner decision 5): an added entry is no change in `pyproject.toml`, `pytest.ini`, `setup.cfg`
    and `tox.ini`; a removed or changed entry, or `asyncio_mode` or `addopts` next to a new one, is;
  - a file that stops parsing counts as changed;
  - dependency sections and `uv.lock` are free;
  - D6.1 for `npm run lint`, `pnpm test`, `sh scripts/typecheck.sh`, `.venv/bin/python -m pytest`, `make lint`,
    `tox -e lint`, `uv run poe check`, `sh -c 'ruff check . && mypy src'`, and a command that resolves to nothing.
    The `scripts` of SCN-IMP-244 are `scripts.lint`, `scripts.prelint`, `scripts.postlint` and
    `scripts/typecheck.sh`, of kind `gate`.

  Then write `src/l4/implementer/gateconfig.py` (D6, D6.1).

## 7. The configuration guard (L4-IMP-040, L4-IMP-006; D7)

- [x] 7.1 Port reproductions (a), (b) and (c) from `test_verify_impl3_config.py` into
  `tests/unit/implementer/test_gate_config_guard.py` (new), with the assertions inverted: SCN-IMP-240, SCN-IMP-241,
  SCN-IMP-242. In the same file, add SCN-IMP-26: green changes `tsconfig.json` `"strict"` and `.gitleaksignore`, and
  both are put back. Then:
  - add `revert_gate_config` to `gateconfig.py` (D7);
  - call it in `tdd.agent_step`'s `finally`, after `revert_protected` and before `restore_ledger`, with
    `phase=role`, the task's tags, and `opened=()` until task 8.1 passes the grant;
  - add `_ADVICE["gate configuration"]` and `_ADVICE["runner configuration"]` (D7 texts) to `guardnotes.py`;
  - remove `revert_gate_config` and the runner-section item from the M1 line of the `src/l4/implementer/guards.py`
    docstring.
- [x] 7.2 In `test_gate_config_guard.py`, add tests for:
  - SCN-IMP-244 through `run_green`, with `gates.lint: ["npm run lint"]` and `gates.typecheck: ["sh
    scripts/typecheck.sh"]`;
  - SCN-IMP-245;
  - SCN-IMP-246 and SCN-IMP-247 through `run_green` (the violations and the kept edit);
  - SCN-IMP-248 (with `asyncio_mode`, not a marker), SCN-IMP-254 through SCN-IMP-257 (the `markers` exception), and
    SCN-IMP-258 (the retry note names the file and the section and says how to redo a dependency);
  - one violation per kind when a step changes both `[tool.ruff]` and `[tool.pytest.ini_options]`;
  - the guard note: the second attempt's prompt (`bench.adapter.requests[1].prompt`) names the file and the section.

  Fix what fails, in `gateconfig.py` and `tdd.py` only.
- [x] 7.3 Tests in `tests/unit/implementer/test_gate_config_gate_run.py` (new):
  - SCN-IMP-243, with a red test that appends to `ruff.toml` when it runs, and a lint gate that passes only on the
    loosened file;
  - a gate that adds a new `mypy.ini` has it removed;
  - a gate that changes only a dependency section keeps it;
  - the snapshot runs for the verifier's gates too: call `wb.run_gate_spec` on a workbench as the verifier builds it.

  Then add the snapshot before the gate and the restore in the `finally` of `Workbench.run_gate_spec` (D7 "After
  every gate run"), after the protected-path restore, with `read_inside` / `write_inside` / `unlink_inside`.

## 8. Opening configuration for a task (L4-IMP-041; D8)

- [x] 8.1 Tests in `tests/unit/implementer/test_config_opened.py` (new):
  - SCN-IMP-250: a `[config]` task in green keeps its `ruff.toml` change;
  - SCN-IMP-251: a person's answer opens `pyproject.toml` for red, and `task.config_opened` is recorded before the
    agent step with the fields of L4-IMP-041;
  - SCN-IMP-252: three answers that open nothing;
  - SCN-IMP-253: green keeps `pytest.ini` frozen, and `kept` gives the reason;
  - `[test-infra]` opens runner configuration in red and in a fix chore;
  - an `accepted` suggestion whose question does not name the file opens nothing.

  Build the questions with `tests/unit/implementer/test_named_unfreeze.py` and `test_unfreeze.py` as models. Then add
  `config_opened(questions, events, scope, candidates, *, phase)` to `src/l4/implementer/unfreeze.py`, with the rules
  of `unfrozen`. In `tdd.agent_step`, compute the grant before the agent runs, emit `task.config_opened` when a path
  opened or was kept, and pass the allowed paths and tags to `revert_gate_config`.

## 9. The verifier checks configuration on the commits (L4-IMP-040; D9)

- [x] 9.1 Tests in `tests/unit/verifier/test_integrity_gate_config.py` (new), with
  `tests/unit/verifier/_integrity_helpers.py`:
  - SCN-IMP-249, the blocker half;
  - a `[config]` task's green commit passes;
  - a `[test-infra]` red commit that changed `[tool.pytest.ini_options]` passes, while the same change in a green
    commit is a blocker;
  - a commit that a `task.config_opened` names passes;
  - a person's commit gives no blocker and is in `Outcome.human_config`.

  Then add `check_gate_config` (D9), `Outcome.human_config` and its `CHECKS` row (after `content scan`) to
  `src/l4/verifier/integrity.py`. In the module docstring, drop "gate configuration and script entries (2.9)" from
  "Not built".
- [x] 9.2 Tests in the same file for the listing half of SCN-IMP-249:
  - `run_integrity` fills `IntegrityReport.human_config`;
  - `verification.md` has the `## Gate and runner configuration changed by humans (allowed, listed: L4-IMP-040)`
    section with the person's change;
  - a resumed round reads `human_config` back from the stored verdict.

  Then add `human_config` to `IntegrityReport` (`src/l4/verifier/types.py`) and to `run_integrity`, read it back in
  `src/l4/verifier/evidence.py`, and write the section in `src/l4/verifier/report.py`, next to the `human_scan`
  section.

## 10. Docs

- [x] 10.1 `docs/SPEC.md`, then run `python scripts/check_spec.py docs/SPEC.md` (it must print no problem):
  - §18, after L4-SEC-008: `**L4-SEC-020**` and `**L4-SEC-021**`, with the text of `specs/security/spec.md`.
  - L4-SEC-002's guidance list: add `.hermes/**`, `.kiro/hooks/**`, `.kiro/prompts/**`.
  - L4-SEC-004: the contract list sentence of the MODIFIED requirement.
  - §7.5, after the paragraph that ends "showed the lint output of the rebuilt file and nothing of the guard's
    change.]": `**L4-IMP-040**` and `**L4-IMP-041**`.
  - L4-IMP-006 (3): "revert changes to gate and runner configuration as L4-IMP-040 defines, unless L4-IMP-041 opens
    the file for the task".
  - §3.2 YAML: already done in 6.1; check that it is there.
  - The §10.2 step-1 row: after "gate configuration unchanged (L4-IMP-006)", add "and runner sections changed by no
    red commit without `[test-infra]` or an answer (L4-IMP-040)".
  - Part II, §23.15, after the last SCN-SEC scenario: SCN-SEC-40..53.
  - Part II, after the last SCN-IMP scenario before `### 23.8`: SCN-IMP-240..253.
  - SCN-IMP-26 stays.
  - Write every scenario in the SPEC's own form, `#### SCN-… (+|−) title · <requirement ids>` followed by
    `- **Given** …`, `- **When** …`, `- **Then** …`. Use `−` (U+2212), as the file does. The requirement ids are:
    - SCN-SEC-40, 42, 43, 44, 45, 48: L4-SEC-020.
    - SCN-SEC-41, 46, 47, 49: L4-SEC-021.
    - SCN-SEC-50, 51, 53: L4-SEC-004.
    - SCN-SEC-52: L4-SEC-004, L4-SEC-005.
    - SCN-IMP-240: L4-IMP-006, L4-IMP-040.
    - SCN-IMP-241..249: L4-IMP-040.
    - SCN-IMP-250..253: L4-IMP-041.
  - The §21 change table: a row `guard-harness-writes` after the last row present, numbered one more than it, with
    the delivered text and the exit criteria "the ported reproductions pass; a consumer repository's red step that
    edits `[tool.ruff]` has it put back".
- [x] 10.2 Write `CHANGELOG.md` under `## 0.4.16 (unreleased)`. If that section is missing, create it above the
  newest section. Add "Fixed" entries for the three findings, in consumer terms, and a "Changed" entry: red's runner
  sections and every step's gate configuration are put back unless the task has a tag or a person's answer; new
  default globs; `tdd.extra_gate_config_globs`. Then:
  - `docs/runbook.md` §7.2: one NOTE for an attempt failed by a planted link (what it means, what to fix: the test
    that makes links in the worktree), and one NOTE for a configuration file put back (how to allow it: a `[config]`
    or `[test-infra]` tag in the task title, or an answer that names the file; runner sections never in green).
  - `docs/architecture.md`, the "Post-step guards" bullet: one sentence each for configuration and for links.
