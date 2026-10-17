## Why

An independent review of 0.4.13 confirmed three gaps, each with a reproduction. All three reproduce unchanged on
0.4.14: the seven reproduction tests pass in this worktree, and the reproduction script of the third finding prints the
same output.

1. **Harness writes follow a link that a gate planted (blocker).** Gates run agent-written code with the worktree
   writable. That code can replace `src/pytdd` with a symbolic link to a directory outside the worktree. After the gate,
   the harness restores files in `finally` blocks, outside the sandbox, and these writes follow the link. The affected
   writes are the zero-value restore (`zero_values_in_place`), the restore of the code at the red commit
   (`red_code_in_place`), the report restores (`zeroed_run`, `run_with_code_of`) and the removal of old reports
   (`gates/runner.py`). The bytes land outside the worktree. For `red_code_in_place` the agent chooses the file name and
   the content. The sha256 check reads back through the same link, so it passes. The guard that should catch the link
   (`ProductionGuard.check` → `restore_to_base`) then crashes the run with
   `git rm --cached … not removing 'src/pytdd' recursively without -r`. Under bubblewrap the gate cannot write outside
   the worktree itself (`--ro-bind / /`), but it can plant the link, and the harness then does the write for it.
2. **Gate and runner configuration is not guarded (major).** `tdd.gate_config_globs` is configured and never read.
   SPEC L4-IMP-006 (3) says MUST, but `revert_gate_config` was never built (guards.py: "M1"). A green step that adds
   `ignore_errors = True` to `mypy.ini` passes its typecheck gate, and the change is committed. A red step that appends
   `[tool.ruff.lint] ignore = ["ALL"]` to `pyproject.toml` passes its own lint gate: red treats the whole file as exempt.
   A red step can also add `addopts = "-p l4hooks"` with a stub module, which green then fills with a hook that turns
   failures into passes. The verifier catches only that last route, one round later.
3. **Agent folders that the sandbox masks are not protected (major).** `.hermes`, `.kiro/hooks` and `.kiro/prompts` are
   covered by the sandbox's tmpfs (L4-SEC-005 calls them "contract-protected paths"). They are missing from
   `CONTRACT_PROTECTED_GLOBS`, so an agent's writes there survive both guards and are committed. Kiro hooks are IDE
   automation that runs commands, the same class of risk as `.claude/settings.json` hooks, which are protected.

## What Changes

- **No harness write passes through a link** (L4-SEC-020). Every read, write and removal that the harness makes in a
  worktree after agent code has run uses new primitives in `l4.fsutil`. These primitives open each path component
  relative to a directory descriptor without following links (`O_NOFOLLOW`). They write a new file and rename it over
  the name, so a symbolic link, a hard link or a FIFO in its place never receives the bytes. A target is taken by its
  real path inside the worktree, which is resolved before the gate, so a link that the repository itself commits keeps
  working. `restore_to_base` removes a link at or above the path, checks a former directory out whole, and passes `-r`
  to `git rm --cached`. It can no longer crash a run.
- **A planted link fails the attempt, never the run** (L4-SEC-021). The harness removes the link itself and records
  `guard.violation{phase: gate, rule: "planted link"}`. It writes nothing through the link, and no exception leaves a
  `finally`. The attempt is discarded before its commit, with a reason that names the path, and the next prompt says
  what happened. In the verifier, a planted link is a blocker.
- **Gate and runner configuration are put back** (L4-IMP-040, L4-IMP-006 MODIFIED). "Gate configuration" and "runner
  configuration" now have exact definitions: the gate files at any depth, the gate and runner sections of
  `pyproject.toml`, `setup.cfg`, `tox.ini` and `package.json`, and the script entries that the gate commands run. After
  every agent step, a change against the step base puts the file back to the step base. After every gate run, any
  change made during the gate is put back. Dependency sections and lock files stay free. The verifier's step 1 checks
  the same rule on the commits and lists changes that people made.
- **A task can be allowed to change configuration, and the permission is recorded** (L4-IMP-041). The task needs a
  human-written `[config]` or `[test-infra]` tag (as today), or a person's answer that names the file
  (`task.config_opened`, with the rules of L4-IMP-015). The red-to-green freeze of runner sections stays in place, and
  no tag or answer lifts it.
- **The masked agent folders are protected paths** (L4-SEC-004 MODIFIED, L4-SEC-002 list). `.hermes/**`,
  `.kiro/hooks/**` and `.kiro/prompts/**` join the contract list. A drift test makes sure that every directory the
  sandbox masks is protected.

## Impact

- `src/l4/fsutil.py` (`LinkedPath`, `linked_component`, `remove_link`, `read_inside`, `write_inside`, `unlink_inside`);
  `src/l4/implementer/discrimination.py`, `src/l4/implementer/stubs.py` (`restore_to_base`, `enforce_red_scope`,
  `ProductionGuard`), `src/l4/gates/runner.py`, `src/l4/implementer/workbench.py` (`unsafe` record, `run_gate_spec`),
  `src/l4/implementer/tdd.py`, `src/l4/implementer/loop.py`, `src/l4/implementer/guardnotes.py`,
  `src/l4/verifier/audit.py`, `src/l4/verifier/ladder.py`.
- A new `src/l4/implementer/gateconfig.py`; `src/l4/implementer/unfreeze.py` (`config_opened`);
  `src/l4/config/defaults.py` and `schema.py` (`tdd.extra_gate_config_globs`, new defaults);
  `src/l4/verifier/integrity.py` (`check_gate_config`), `types.py`, `evidence.py`, `report.py`.
- `src/l4/security/protected.py` (three globs).
- Tests under `tests/unit/` (the reviewer's reproductions, ported with their assertions inverted).
- `docs/SPEC.md` (L4-SEC-020, L4-SEC-021, L4-IMP-040, L4-IMP-041; L4-SEC-002, L4-SEC-004 and L4-IMP-006 (3) amended;
  §3.2; the §10.2 step-1 row; SCN-SEC-40..53, SCN-IMP-240..253; the change row), `docs/runbook.md`,
  `docs/architecture.md`, `CHANGELOG.md` under `## 0.4.16 (unreleased)`.
- Behaviour a consumer can notice: a red step that edits runner sections, or a step that edits gate configuration,
  without a tag or an answer, now has that file put back (`guard.violation`). A test suite that replaces a source
  directory with a link fails its attempt.
