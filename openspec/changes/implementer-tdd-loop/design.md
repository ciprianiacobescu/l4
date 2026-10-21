## Context

SPEC §7 specifies a strict TDD loop with a large rule surface (stubs, zero-value vacuity runs, freezes, guards, budgets, sessions). The project goal is a tool the user can add to an existing repo with a couple of commands and run on a runner that already has the tools. So the first deliverable (M1) is a thin, real loop that runs end to end on `example-group/dummy-agentic`; everything that needs per-language knowledge waits for the change-0 fixture repos (SPEC §21 row 0: "the implementer TDD loop is planned only after the fixture repos report"). M1 therefore targets a Python/pytest repo, which is also the dummy repo's stack [I].

Evidence labels: [V] verified, [I] design decision, [U] unverified, must be confirmed by a test or spike first.

## Goals

- A deterministic orchestrator that drives one unit from intake to `implemented` with a red commit before every green commit.
- Gate results that cannot be vacuous, with logs, timeouts and sandboxing.
- A design in which M2 rules (vacuity, audit, more languages) slot into named extension points without rewriting M1.
- Everything testable with the fake adapter, the fake forge and a temp git repo; the live run uses a real agent CLI.

## Non-Goals

- Verification, fix units, clarifier answers, archive and PR handling (changes 7 to 9). The orchestrator stops at `implemented` unless a verify hook is injected.
- Per-language stub allow-lists beyond Python, zero-value stub derivation, audit sampling (M2, after spikes).
- Parallel units, auto-merge.

## Decisions

### D1. Module and type names (kept identical in tasks.md)
- `l4/implementer/result.py`: `ImplementerResult` (pydantic v2 model of `l4/implementer-result@1`), `RESULT_SCHEMA_ID`, `ResultInvalid`, `parse_result(raw: str | bytes) -> ImplementerResult`, `build_repair_prompt(error: str) -> str`, `check_criteria(result, task, unit_criteria)`.
- `l4/implementer/prompt.py`: `PromptSection`, `PromptContext`, `RenderedPrompt(text, sha256, template_version, sources)`, `load_template(name, base_dir, override_dir) -> Template`, `render_prompt(role: Literal["red","green","single","stuck","repair"], ctx) -> RenderedPrompt`, `trim_context(text, budget_tokens)`.
- `l4/implementer/guards.py`: `GuardEvent(type, path, detail)`, `GuardReport(events, reverted)`, `snapshot_tree(worktree) -> TreeSnapshot`, `revert_protected_paths(...)` (delegates to `l4.security.protected`), `fold_agent_commits(git, worktree, step_base)`, `is_signature_only_stub_py(before: str | None, after: str) -> bool`, `enforce_red_scope(...)`, `FreezeManifest`, `restore_frozen(...)`, `scan_test_tamper(diff) -> list[GuardEvent]` (M2), `revert_gate_config(...)` (M2), `redact_written_files(paths, redactor)` (M2).
- `l4/implementer/tdd.py`: `Phase = Literal["red","green","single"]`, `StepContext` (unit, task(s), worktree, run_id, iteration, profile, services), `RedOutcome`, `GreenOutcome`, `run_red(step) -> RedOutcome`, `run_green(step, manifest) -> GreenOutcome`, `new_test_ids(base: TestReport, head: TestReport) -> set[str]`, `classify_red(base, head, new_ids) -> RedVerdict`, `PhaseOrderError`, M2: `vacuity_check(...)`, `derive_zero_value_stubs(...)`.
- `l4/implementer/loop.py`: `select_next_step(tasks, questions, grouping) -> Step | None`, `StuckDetector`, `BudgetState`, `run_task(step_ctx) -> TaskOutcome`, `TaskOutcome(status: Literal["done","blocked","stuck","halt","failed"], reason, questions)`, `fingerprint(failure) -> str` (M2).
- `l4/gates/junit.py`: `TestReport(tests: dict[str, TestCase], collection_errors: list[str], total: int)`, `TestCase(id, status: Literal["passed","failed","error","skipped"], message)`, `parse_junit(path: Path, max_bytes=8_000_000) -> TestReport` using `l4.security.hardening.safe_parse_xml`.
- `l4/gates/runner.py`: `GateSpec(name, command, reports, format, timeout)`, `GateResult(name, status: Literal["pass","fail"], reason, exit_code, log_path, report: TestReport | None)`, `run_gate(spec, worktree, sandbox, run_id, env) -> GateResult`, `judge_test_gate(exit_code, report, must_contain: set[str] | None) -> tuple[bool, str]`.
- `l4/gates/odd.py`: `IntakeFailure(check: Literal["valid","criteria","oracle","paths"], reason: str)`, `IntakeResult(ok, failures)`, `check_intake(unit, provider, cfg, which=shutil.which) -> IntakeResult`, `match_forbidden(paths, globs) -> list[tuple[str,str]]`. M2 files: `bootstrap.py` (`plan_bootstrap_unit`), `adopt.py` (`should_adopt`), `propose.py` (`propose_gates(repo) -> GateProposal`).
- `l4/orchestrator.py`: `Services` (dataclass whose fields use the owning changes' names: `providers: l4.specs.base.ProviderRegistry`, `ledger: l4.state.ledger.LedgerWriter`, `git: l4.vcs.git.Git`, `worktrees: l4.vcs.worktree.WorktreeManager`, `lease: l4.vcs.locks.LeaseBackend`, `pushes: l4.vcs.locks.PushCoordinator`, `sandbox: l4.sandbox.base.Sandbox`, `factory: l4.agents.factory.Factory`, `redactor: l4.redact.Redactor`, `clock`, and the optional hooks `forge`, `clarify`, `verify`, `mirror`, `handoff`, each `None` when absent), `UnitRunResult(outcome: l4.outcome.UnitOutcome, exit_code: l4.exitcodes.ExitCode)` (bootstrap-core's `UnitOutcome` is reused, never redefined), `Orchestrator(cfg, services)`, `Orchestrator.run_unit(unit_ref) -> UnitRunResult`, `build_services(app, cfg) -> Services`, `HOOKS`, and `run_command(app, unit, max_units, time_budget, dry_run, probe) -> ExitCode` (the `l4 run` handler `l4.orchestrator:run_command` in bootstrap-core `commands.HANDLERS`). Exit codes come from the `Edge.exit_code` returned by `l4.state.lifecycle.transition`; there is no separate exit table.

### D2. Lifecycle ownership
The §12.0 transition table is data owned by state-vcs-locks (`l4/state/lifecycle.py`: `transition(writer, state, trigger, **ctx) -> Edge`, `Trigger` members such as `intake_all_pass`, `intake_failed`, `lease_acquired`, `questions_blocking`, `all_leaves_done`, `breaker_or_budget`, `spec_invalid`; it appends the single `phase.changed` event and returns `Edge.exit_code`; an undeclared edge raises `IllegalTransition`). The orchestrator is the only caller. Alternatives: embed the table in the orchestrator (rejected: change 3 and the simulation harness assert edge coverage against one table).
M1 edges exercised: `intake -> ready`, `intake -> rejected`, `ready -> implementing`, `implementing -> implemented`, `implementing -> awaiting_human`, `implementing -> clarifying -> implementing | awaiting_human` (when the `clarify` hook is present), `awaiting_human -> implementing` (answers committed by a human unblock a task; walking-skeleton criterion 5), `ready | implementing | implemented | verifying -> waiting_capacity` (agent-factory returns `WaitingCapacity`, exit 12) and back to the remembered phase once `retry_after` has passed, `implementing -> halted`, `implemented -> verifying -> verified | fixing | awaiting_human | escalated` and `verified -> in_review` (via the `verify` and `handoff` hooks), plus `any non-terminal -> rejected` on spec invalidity.

### D3. Red phase mechanics (M1, Python)
1. Baseline: run the test gate at the step base once per base SHA; `base_report = parse_junit(...)`. A failing baseline is recorded; red then compares sets, so pre-existing failures are not attributed to new tests.
2. Agent runs in the agent sandbox with the red prompt (tests only plus signature-only stubs). Result parsed.
3. Guard (`enforce_red_scope`): the guard diffs the worktree against a `snapshot_tree` taken immediately before the agent call (after the harness's own writes), and never classifies harness-owned unit files as agent changes: `<unit_dir>/.l4/**` (ledger, `criteria.json`, `state.json`, evidence), `<unit_dir>/questions.md` (checked by spec-providers' section-scoped rules instead) and the task-marker bytes (checked by `check_tasks_guard`, L4-TMW-002); the agent cannot write the ledger, which only `LedgerWriter` appends. Changed paths are classified: test/test-support globs (kept); non-test files kept only if every changed file is Python and `is_signature_only_stub_py(before, after)` is true (AST: only added `def`/`class` nodes whose body is a docstring-optional `raise NotImplementedError[(...)]`); everything else is reverted with `guard.violation{phase:"red"}`. Non-Python non-test changes are reverted in M1 (the per-language table is M2 [U]).
4. Run the test gate, parse the report. `classify_red`: `new = head.ids - base.ids`; fail reasons in order: `no tests added` (no test file diff and empty `tests_added`), `tests not collected individually` (a collection error or zero new ids while test files were added), `new tests passed before implementation` (any new id with status passed), `red broke existing tests` (an id passed at base but failed/errored now; added resolution so failures are attributable to the new tests only). Valid iff every new id is `failed|error` and no regression.
5. Commit `test(<unit>): red for <task> [skip ci]` through `l4.vcs.git.Git.commit(message, trailers, identity)` with `l4.vcs.trailers.CommitTrailers(..., tdd="red")` (state-vcs-locks); red, green and questions commits are checkpoint commits, so the message carries `[skip ci]` and the push uses forge-and-ci's checkpoint arguments (L4-CI-002, forge-and-ci task 1.30 refuses a checkpoint range without it); ledger `task.red_ok` with the freeze manifest.
[U] to confirm with the Python fixture (change 0): how pytest's JUnit XML names collection errors and whether `skip`/`xfail` appear as `skipped` entries; test id normalisation `classname + "::" + name` vs `file::name` (SPEC §10 criterion tracing uses the literal ID in the case name).

### D4. Green phase mechanics (M1)
`FreezeManifest = {path: sha256}` for every test file changed or added in red and every file matching `tdd.test_support_globs` that exists at the red commit. After the green agent step: `restore_frozen` re-checks each hash and restores differing files with `git checkout <red_sha> -- <paths>` (logs `guard.test_tamper` for test files, `guard.violation` for support files); deleted frozen files are restored. Then run the test gate: every red test id must be `passed`, no id that passed at base may fail (`no new failures`). Then `provider.set_marker(unit, task, Marker.DONE)` and commit `feat(<unit>): <task title> [skip ci]` with `L4-TDD: green` (marker byte included in the same commit; checkpoint commit as in D3). M2 adds: running the red tests from a scratch checkout of the red commit, runner-config section freeze, dependency diff, lint/typecheck. Alternative: scratch-copy only (M2 keeps both: the worktree restore is simpler and gives the agent accurate feedback).

### D5. Result contract and repair
`ImplementerResult` mirrors the SPEC JSON schema exactly. Delivery order: adapter structured output, else the file at `$L4_RESULT_PATH`. On `ResultInvalid` the loop sends `build_repair_prompt(error)` in the same session up to `implementer.result_repair_attempts`; then the attempt fails. The result path is created in the sandbox temp dir (outside the worktree).

### D6. Prompts
Templates are packaged at `src/l4/implementer/templates/{contract.md,red.md,green.md,single.md,stuck.md,repair.md}` with a `version:` front-matter line; overrides are read from `.l4/prompts/` of the **base branch** (CFG-004), never the unit branch. SPEC names the directory `l4harness/prompts/`; the real package is `l4`, so the packaged location above is the resolution (SPEC amendment noted in tasks 3.4). Context trimming (`trim_context`) uses a 4-characters-per-token estimate [I] in M2.

### D7. Stuck detection and budgets
`StuckDetector` tracks per task: `attempts`, last two diff hashes (`git diff` of tracked and untracked files hashed with sha256), failure fingerprints. `BudgetState` is folded from the ledger (iterations, cost) so it survives restarts; `budget.extended` adds to limits. M1 enforces `max_task_attempts`, blocked status, identical diff hash twice, and `max_iterations_per_unit`; M2 adds fingerprints (`same_error_repeats`), cost, `no_progress_iterations` and oscillation.

### D8. Orchestrator loop (M1)
```
run_unit(ref):
  state = fold(ledger); phase = state.phase or "intake"
  res = check_intake(...)            # ODD; also before every run
  if not res.ok: transition(rejected); write unit.rejected; return exit 14
  transition(ready); lease/worktree already provided by Services
  select sandbox (fail closed: SandboxUnavailable -> exit 3)
  transition(implementing)
  loop: step = select_next_step(...)
        none and open questions -> awaiting_human (exit 11)
        none and all done -> implemented (exit 0)
        outcome = run_task(...)  # red, green (or single for exempt)
        blocked -> questions.md + commit; stuck/budget -> halted (exit 13)
```
Each step appends `step.started` / `step.finished` with the key from `l4.state.idempotency.step_key(...)` (STA-003); at run start `l4.state.reconcile.reconcile(...)` resolves unfinished steps. Alternatives: a state-machine library (rejected: the table is already data and the deps list is fixed).

Composition root (M1, cross-change review 2026-10-03). `run_command` is the `l4 run` handler. `build_services` builds the collaborators above from config: `l4.specs.detect.collect_units` plus the provider registry, `WorktreeManager.ensure(UnitNames(...))`, `l4.vcs.locks.acquire_for_run` (a busy unit is skipped with exit 0), one `LedgerWriter` per unit, `PushCoordinator` with the push arguments of the `forge` hook, `l4.agents.factory.Factory`, `l4.sandbox.select.select_sandbox` (fail closed, exit 3). Later changes plug in without editing this module: `HOOKS = {"forge": "l4.archive:forge_hook", "lessons": "l4.memory.inject:inject_for_task", "clarify": "l4.clarifier.clarifier:clarify_hook", "verify": "l4.verifier.ladder:verify_hook", "mirror": "l4.archive:mirror_hook", "handoff": "l4.archive:handoff_hook"}` is resolved lazily with bootstrap-core's dispatch rule (a `ModuleNotFoundError` for exactly that module means "absent"; any other import error is exit 1). `forge` supplies the credential helper and the checkpoint/hand-off push options (absent: plain pushes, used with local bare remotes in tests); absent `verify` stops the unit at `implemented`; `clarify` runs on `implementing -> clarifying`; `verify` drives `implemented -> verifying -> verified|fixing|awaiting_human|waiting_capacity|escalated`; `handoff` drives `verified -> in_review` (commit H, MR ready); `mirror` (`PrMirror.sync`) runs after every push and phase change. Prompts receive their `<l4:data>` blocks from the hooks: lessons from `lessons` (memory-lessons `inject_for_task`) and answered questions from the clarifier's `render_answer_blocks` (through `clarify`); absent hooks give empty sections. Before exiting, `run_command` commits the remaining ledger lines and `state.json` of each unit as a checkpoint commit (`chore(<unit>): ledger [skip ci]`) and pushes it, so the branch always carries the full ledger; it writes `outcome.json` through bootstrap-core's `with_outcome` and returns `most_severe` over the units.

### D9. Gate runner
`run_gate` spawns through `Sandbox.wrap(argv, spec, env)` in its own process group (`start_new_session=True`); on timeout sends SIGTERM to the group, waits 5 s, then SIGKILL; stdout and stderr go to `.l4-out/gates/<run-id>/<gate>.log` (redacted). `judge_test_gate`: exit code != 0 fails first; then report missing fails (`report missing: <path>`); `total == 0` fails (`vacuous: 0 tests executed`); `must_contain` ids missing fail. JUnit parsing uses `safe_parse_xml` (sandbox-security, SEC-006). Commands are executed with `shlex.split` (no shell) unless the configured command contains shell operators, in which case `sh -c` runs inside the sandbox [I].

### D10. ODD intake
`check_intake` runs all four checks without short-circuiting. Check 1 uses `provider.validate(unit, strict=True)`; check 2 uses `provider.criteria(unit)` and `provider.tasks(unit)`; check 3 verifies `gates.test.command` non-empty and the first token resolvable (`shutil.which` or relative path); check 4 extracts declared paths (provider `Unit.paths`) and matches them with `odd.forbidden_paths` using `l4.security.protected.glob_match`. Exit 14 and `unit.rejected{reasons}`.

## Risks

- R1 [U] JUnit shape for collection errors and parametrized ids; mitigated by the fixture-based unit test written first (task 1.2) and, if it differs, adapting `parse_junit` only.
- R2 [I] Signature-only stub detection in Python is AST-based; types, class bodies and decorators are rejected in M1 (strictly narrower than SPEC), which can make red fail for tasks that need new classes. Accepted for M1; the M2 table is fixed by the fixture repos.
- R3 [U] The agent CLI may behave differently under the read-only `.git` and bubblewrap sandbox (see sandbox-security R2); the live run (task 1.32) is the arbiter.
- R4 The orchestrator depends on interfaces from five other changes; mismatches are caught early by injecting fakes through `Services` and by contract tests in `tests/contract/`.
- R5 Red attribution rule "red broke existing tests" is stricter than SPEC text; recorded as an ambiguity resolution.
