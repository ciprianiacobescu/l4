# Parallel work on M1.2–M1.5: ownership, shared files, contracts, merge order (2026-10-04)

M1.2, M1.3, M1.4 and M1.5 are built at the same time in four git worktrees: branches `m12`, `m13`, `m14` and `m15`,
all from one base. They are merged back to `main` one at a time. This file covers six things:

1. who owns which path;
2. how the shared files may be edited;
3. the contracts between the increments;
4. the conflicts between the four plans and how they were resolved (the plan files are already edited);
5. the merge order and the check after each merge;
6. the risks of working in parallel.

Labels:

* [V] verified at `98e4939`: in code, in git, or by a test run;
* [I] inferred;
* [U] unverified.

**Base facts**

* `main` is `98e4939`.
* M1.1 Stage C has landed: `m11-progress.md` records lines 26–41 as done, with their commits [V]. Every "after M1.1
  Stage C" gate in the four plans is therefore open, and the plans now say so (§4, item 18).
* M1.1 G13 (the M1.1 live test) has **never run** against the live server [V, m11-progress line 41]. It blocks the live
  exits (§5.3), not the merges.
* **M1.1 review fixes were being written in the working tree while this file was written** [V, `git status` and
  `git diff`].
  * 22 files were uncommitted, plus 2 new test files. Among them:
    * `orchestrator.py` (`close`);
    * `services.py` (the `H_PUSHED` key in `HookContext.shared`);
    * `cli.py` (`archive --retry`);
    * `config/defaults.py` (`RUNNER_SECRET_ENV`);
    * `ci/sweeper.py`, `archive.py`, `postmerge.py`, `forge/gitlab.py`;
    * the GitLab template (`before_script`).
  * None of them touches an anchor in §2.1. They change the base, though: branching before they are committed would
    make every branch conflict with them.
  * **The base is `main` once those fixes are committed**, not `98e4939`.
* The four plans are not committed either: `m12-plan.md` and `m15-plan.md` are modified, and `m13-plan.md`,
  `m14-plan.md` and this file are untracked [V].
  * A worktree branched from `main` would not see them.
  * **Before branching:** commit `docs/plan/m1{2,3,4,5}-plan.md` and this file on `main` in one docs-only commit. Stage
    those paths by name, never with `git add -A`. Then branch `m12`, `m13`, `m14` and `m15` from that commit.

---

## 1. Ownership: path → increment

**Rules**

* An owned path is edited only on its owner's branch.
* A non-owner that needs a change writes a one-line request in its progress file. Either the owner makes the change,
  or the merger makes it once both increments are on `main`.
* Paths edited by two or more increments are in §2. They are not listed here.

**S0, the seam commit (§3.0).** Built once on `main`, before any increment needs it. Its files and their owners after
S0:

| Path | Owner after S0 |
|---|---|
| `src/l4/versions.py` | M1.2 (additive) |
| `src/l4/verifier/testwriter.py` | M1.3 (additive); M1.5 consumes it |
| `src/l4/verifier/generated-test.schema.json` | M1.3 (additive); M1.5 consumes it |
| `tests/unit/test_versions.py`, `tests/unit/verifier/test_testwriter.py` | M1.3 |

**M1.2: availability, fallback chains, adapters**

| Path | Kind |
|---|---|
| `src/l4/availability/cooldown.py` (`CooldownRegistry`, `ProbeCache`, `Clock`, `SystemClock`, `FakeClock`, `identity_hash`) | new |
| `src/l4/availability/limits.py`, `quota.py`, `fallback.py` (with `run_probe`, the existing `HANDLERS["probe"]` target [V]) | new |
| `src/l4/availability/probes.py` | existing, rewritten |
| `src/l4/agents/opencode.py`, `kiro_cli.py`, `command.py`, `gate.py` | new |
| `src/l4/agents/factory.py` | existing, rewritten |
| `src/l4/llm/agent_judge.py` (`JUDGE_ADAPTERS`, the opencode and codex judge paths) | existing; M1.2 is the only writer |
| `src/l4/verifier/selection.py` | new |
| `scripts/runner/record-probes.sh` | new |
| tests: `tests/unit/availability/**`, `tests/unit/agents/test_{opencode,kiro_cli,command,factory_select,gate}.py`, `tests/contract/{agents,availability}/**`, `tests/unit/llm/test_judge_adapters*.py`, `tests/unit/verifier/test_selection.py`, `tests/unit/verifier/test_report_independence.py`, `tests/unit/config/test_schema_profile_reserve.py`, `tests/scenarios/test_agent_factory_scenarios.py`, `tests/live/test_m1_2_acceptance.py` | new |
| fixtures: `tests/fixtures/recorded/{kiro-cli,claude-code,codex,opencode}/**` (new files only) | new |

**M1.3: verifier depth and fix units**

| Path | Kind |
|---|---|
| `src/l4/gates/pytest_trace/l4_trace.py`, `src/l4/gates/trace.py` | new |
| `src/l4/gates/junit.py`, `src/l4/gates/runner.py`, `src/l4/sandbox/env.py` | existing; M1.3 is the only writer (additive keywords) |
| `src/l4/implementer/stubs.py`, `discrimination.py`, `templates/single.md` | new |
| `src/l4/implementer/templates/contract.md`, `red.md`, `loop.py`, `result.py` | existing; M1.3 is the only writer |
| `src/l4/verifier/{integrity,scan,traceability,audit,verdicts,evidence,fixunit,fixloop}.py` | new |
| `src/l4/verifier/aggregate.py` | existing, rewritten (M1.5 does not edit it, §4 item 4) |
| `src/l4/specs/questions.py`, `src/l4/specs/openspec.py` (`create_fix_unit`), `src/l4/security/protected.py` (`ProtectedSet.extra_dirs`), `src/l4/postmerge.py` (line 39) | existing; M1.3 is the only writer |
| tests: `tests/unit/gates/test_{pytest_trace,junit_recorded}.py`, `tests/unit/specs/test_trace_ids.py`, `tests/contract/test_openspec_fix_unit.py`, `tests/unit/implementer/test_{stubs,vacuity,presatisfied,check_criteria,already_satisfied,single_phase}.py`, `tests/unit/verifier/test_{integrity,scan,traceability,audit,verdicts,resume,fixunit,fixloop,ladder_fix}.py`, `tests/unit/planner/test_fix_units.py`, `tests/unit/orchestrator/test_fix_unit_cli.py`, `tests/fixtures/py_integrity/**`, `tests/fixtures/recorded/pytest/**`, `scripts/record_pytest_junit.sh`, `tests/live/test_m1_3_acceptance.py` | new |

**M1.4: Kiro specs, runner provisioning, GitHub, simulation, crash resume**

| Path | Kind |
|---|---|
| `src/l4/specs/kiro.py`, `src/l4/specs/detect.py` | new |
| `src/l4/specs/providers.py` | existing, rewritten |
| `src/l4/doctor/fix.py`, `checks_spec.py`, `checks_provision.py` | new |
| `src/l4/doctor/run.py`, `src/l4/doctor/checks_env.py` | existing; M1.4 is the only writer |
| `src/l4/provision/**` | new |
| `src/l4/forge/github.py`, `src/l4/forge/local.py`, `src/l4/ci/github.py`, `src/l4/ci/lint.py`, `src/l4/ci/templates/l4.github.yml` | new |
| `src/l4/forge/base.py`, `src/l4/forge/gitlab.py`, `src/l4/vcs/refresh.py`, `src/l4/init/init.py`, `src/l4/ci/templates/l4.gitlab-ci.yml` | existing; M1.4 is the only writer (M1.1 is done with them) |
| `src/l4/sim/**`, `src/l4/sim/builtin/**`, `src/l4/schema/outcome.schema.json` | new (`run_simulate` is the existing `HANDLERS["simulate"]` target [V]) |
| `src/l4/vcs/wip.py`, `src/l4/state/idempotency.py`, `reconcile.py`, `resume.py` | new (`run_resume` is the existing `HANDLERS["resume"]` target [V]) |
| `src/l4/implementer/tasks.py`, `src/l4/implementer/prompt.py`, `src/l4/log.py`, `src/l4/outcome.py`, `src/l4/exitcodes.py` | existing; M1.4 is the only writer |
| tests: `tests/unit/{specs,provision,sim}/test_<new>.py`, `tests/unit/orchestrator/test_kiro_unit.py`, `tests/unit/planner/test_next_action_optional.py`, `tests/unit/state/test_status_kiro.py`, `tests/unit/verifier/test_preconditions_optional.py`, `tests/unit/doctor/test_checks_env_004.py`, `tests/unit/forge/test_make_forge.py`, `tests/unit/vcs/test_refresh_github.py`, `tests/fixtures/specs/kiro/**`, `tests/fixtures/provision/**`, `tests/live/test_m1_4_acceptance.py` | new |

**M1.5: memory, web UI checks, System-One**

| Path | Kind |
|---|---|
| `src/l4/memory/**` (`run_lessons` is the existing `HANDLERS["lessons"]` target [V]) | new |
| `src/l4/llm/system_one.py`, `src/l4/gates/e2e.py`, `src/l4/gates/e2e_launch.py` | new |
| `src/l4/verifier/playwright.py`, `generate.py`, `s1.py` | new |
| `src/l4/verifier/e2e_trace.py` | new. In Stage C it becomes a thin wrapper over M1.3's `trace_ids`, applied to the e2e report only; it picks step 5's targets (§4, item 4) |
| `src/l4/doctor/checks_memory.py` | new |
| `src/l4/clarifier/router.py` (`build_s1_judge`), `src/l4/verifier/gates.py` (`run_e2e_gate`), `src/l4/sandbox/bwrap.py` (only if P1 holds) | existing; M1.5 is the only writer |
| `scripts/runner/prereqs.sh` | existing; M1.5 is the only writer. M1.4's drift test reads it: contract C20 |
| `scripts/runner/ci-probe-m15.sh` | new |
| tests: `tests/unit/memory/**`, `tests/integration/test_memory_flow.py`, `tests/unit/llm/test_system_one.py`, `tests/unit/gates/test_e2e.py`, `tests/unit/verifier/test_{playwright,generate,s1,e2e_trace}.py`, `tests/unit/agents/test_mcp_flags.py`, `tests/fixtures/web/**`, `tests/live/test_m1_5_acceptance.py` | new |

---

## 2. Shared files: allowed edits, anchors and exact names

### 2.0 Rules for every branch

1. **Anchors.**
   * Each increment inserts at its own anchor, written below as "after the line X".
   * The hunks of two increments in one file are always separated by **at least one line that neither changes**.
   * [V] A scratch-repo test showed that git's three-way merge is clean in that case: two inserts around one untouched
     line, or two edits with one untouched line between them. Edits on the same line or on adjacent lines conflict.
2. **Additive only.** Allowed:
   * new pydantic or dataclass fields with defaults;
   * new enum or Literal values;
   * new dict rows, hook rows and lifecycle rows;
   * new functions and methods;
   * new keyword parameters whose default keeps today's behaviour.

   Not allowed in a shared file: renames, reordering, or reformatting lines you do not change.
3. **Same-line unions.** Where two increments must change the same line, §2.2 gives the final text and the merger
   writes it.
   * Import blocks are the one general exception: take the union, then run
     `uv run ruff check --select I --fix <file>`.
4. **Module docstrings of shared files** (their "M1: …" notes) are not edited on a branch. The merger updates them in
   the merge commit.
5. **Tests.**
   * New tests go into **new modules** named for the increment's topic. Never append a test to an existing module that
     another increment also extends.
   * An existing test may be edited only to adapt an assertion that your change makes wrong.
   * Add no fixtures to an existing `conftest.py`: put them in your new module or in a new `_<topic>_helpers.py`.
   * Existing fixture repos (`tests/fixtures/py_tdd`, …) are read-only. Copy one into a new directory for a variant.
6. **No branch edits these:** `pyproject.toml`, `uv.lock`, `src/l4/commands.py`, `src/l4/cli.py`, `docs/SPEC.md`,
   `docs/live/README.md`.
   * Live evidence is written on `main` after the merge.
   * hatchling packages everything under `src/l4` [V, `pyproject.toml`], so new `.json`, `.md` and plugin files need
     no packaging edit.
7. **Live record files.**
   * Each acceptance test defaults `L4_LIVE_RECORD` to its own file, `/tmp/l4_m1_<n>_ids.json`.
   * M1.1 already uses `/tmp/l4_m1_1_ids.json` [V].

### 2.1 Per file: increment, anchor, exact names

The "group" notes refer to M1.5's split Stage C (§5.1):

* group 1 starts once M1.2 is on `main`;
* group 2 starts once M1.3 is on `main`.

Edits in a later group are made on top of the merged earlier increment, so they never run in parallel with it.

**`src/l4/config/schema.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | `Profile`, after the line `min_version: str \| None = None` | `min_remaining_percent: float \| None = Field(None, ge=0, le=100)` |
| M1.4 | `CiCfg`, after the line `continuation: …` | `self_provision: Literal["auto"] \| bool = "auto"` |
| M1.5 (A, line 3) | new classes just before `class L4Config` | `SerenaCfg`, `MemoryCfg` |
| M1.5 (A, line 3) | the line `memory: dict[str, Any] = …` | becomes `memory: MemoryCfg = Field(default_factory=MemoryCfg)` |
| M1.5 (A, line 3) | the line `OPAQUE_SECTIONS = ("archive", "memory")` | becomes `OPAQUE_SECTIONS = ("archive",)` |

**`src/l4/config/defaults.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | the `"opencode": (…)` row of `CREDENTIAL_PATHS` | adds `"~/.cache/opencode"` |
| M1.5 | end of file | `LESSONS_FILE`, `MAX_LESSONS = 40`, `MAX_LESSON_BYTES = 12000`, `SERENA_VERSION = "1.7.0"`, `LAYA_VERSION = "0.3.24"` |

**`src/l4/config/preflight.py`** (in sequence: M1.3, then M1.5 group 2)

| Inc | Anchor | Names |
|---|---|---|
| M1.3 | the optional-roles loop | `for role in ("clarifier", "s1_judge"):` becomes `("clarifier", "s1_judge", "verifier_agent")` |
| M1.5 (C, group 2) | two new statements at the end of `preflight_run_config` | (a) a non-empty `roles.verifier_agent` is required when `gates.e2e.command` is set and `verifier.playwright.enabled`; (b) a `backend: system-one` profile needs `engine ∈ {laya-local, jev, remote}`, plus `base_url` for `remote` and `api_key_env` for `jev` |

**`src/l4/services.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | inside `return Services(…)` of `build_services`, the argument line with `factory=Factory(…)` | `Factory(cfg, probe, events=ledger, adapters=adapters, availability=AvailabilityStore(cache_root(app.environ, repo=app.repo)), clock=SystemClock())` |
| M1.3 | `HOOKS`, after the `"clarify"` row | `"fix": "l4.verifier.fixloop:fix_hook",` |
| M1.3 | `Hooks`, after the `clarify` field and its comment line | `fix: Callable[["HookContext"], "FixOutcome"] \| None = None` |
| M1.4 | `build_services`, only the line `provider = providers_for(cfg, worktree, app.environ)[0]` | `provider = provider_for_unit(providers_for(cfg, worktree, app.environ), names.unit_id)` (new helper in `specs/providers.py`) |

**`src/l4/orchestrator.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | `__init__`, after the line `self._sent: set[str] = set()` | `self._previous_attempt: PreviousAttempt \| None = None` |
| M1.2 | `_implement`, a new clause after the `except BaselineFailed as exc:` block | `except RoleLimit as exc: wb = self._fall_back(exc); continue` |
| M1.2 | new method between `_implement` and `_events` | `_fall_back(self, exc: RoleLimit) -> Workbench`. It calls `switch_profile(limit, task)` (public, also `ctx.shared["fall_back"]`; takes a `RunResult` or a bare `LimitSignal`): that calls `Factory.on_limit`, sets `self._selected` and `_previous_attempt`; `_fall_back` then rebuilds the workbench. With nothing left, `WaitingCapacity` is raised. M1.3's fix loop and audit writer call `ctx.shared["fall_back"]` instead of `Factory.on_limit` |
| M1.2 | `_park` | `retry_after` in the `self._go(…)` context (that call only) |
| M1.2 | `_outcome` | one new line after `profiles \|= …`: `fallback_from`; one new keyword line after `pr_url=state.pr,`: `retry_after=state.retry_after,` |
| M1.3 | `__init__`, after the line `self._ctx = ctx` | `ctx.shared["implementer"] = self._select` (a zero-argument callable; contract C21) |
| M1.3 | `_NEEDS_A_HUMAN` | the `Phase.FIXING` row is deleted. This is the only deletion in a shared file, and no one else edits that dict |
| M1.3 | `_drive`, AWAITING_HUMAN branch | new first lines: the verdict branch (`self._verdicts_ready()`) |
| M1.3 | `_drive`, VERIFIED branch | before `return self._hand_off()`: an open fix unit fires `Trigger.MINOR_FINDINGS_FIX` |
| M1.3 | `_drive` | new `elif phase is Phase.FIXING:` just before `elif phase is Phase.REJECTED:` |
| M1.3 | `_verify` | body (go on when the target is `fixing`; copy `ctx.shared["notes"]`) |
| M1.3 | new methods after `_verify` | `_verdicts_ready`, `_open_fix_unit`, `_fix` |
| M1.3 | `run_command`, after the line `chosen = select_units(…)` | `chosen = without_fix_units(chosen, named=units)` (exit 2 for a fix unit named with `--unit`) |
| M1.4 | `run_command`, its first statement (the `for flag, deferred in (…)` loop) | becomes `if time_budget: raise L4Exit(…)` and `if dry_run or probe: return run_dry(app, units=units, probe=probe)` |
| M1.4 | `run_command`, after the line `preflight_run_config(app, cfg)` | `require_framework(cfg, app.repo, app.environ)` |
| M1.4 | `run_unit`, first statement inside `try:` | `reconcile(self.services)` |
| M1.4 | `_lint_scenarios`, after `if not self._may_commit_questions(): return` | `if s.ref.framework is not Framework.OPENSPEC: return` |
| M1.4 | `_discover`, the line `pending = any(not t.done for t in tasks)` | `… for t in required(tasks)` |
| M1.4 | `_implement`, the line `pending = [t.key for t in tasks if not t.done]` | `… for t in required(tasks) …` |
| M1.4 | `_outcome`, only the `tasks=TaskCounts(…)` argument line | counts `required(tasks)` |

**`src/l4/planner.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | `UnitFacts`, after the `answers_unblock` field | `retry_after: str \| None = None` |
| M1.2 | `facts_of`, after the line `answers_unblock=…` | `retry_after=snapshot.state.retry_after,` |
| M1.2 | `next_action` signature | `next_action(facts: UnitFacts, now: datetime \| None = None)` |
| M1.2 | `next_action`, new branch just before `if phase in _NOT_ACTIONABLE:` | the `waiting_capacity` row |
| M1.3 | `UnitFacts`, after the `unreadable` field (end) | `verdicts_open`, `verdicts_ready`, `verdicts_invalid: tuple[str, ...] = ()`; `fix_unit_of: str \| None = None`; `open_fix_unit: str \| None = None`; `fix_progress: tuple[int, int] \| None = None`; `fix_questions_open: tuple[str, ...] = ()` |
| M1.3 | `facts_of`, after the line `unreadable=…` (end) | the matching keywords |
| M1.3 | `next_action` | four edits: the fix-unit `none` row right after the `if facts.corrupt:` return; a `FIXING` branch right after the `_VERIFY` branch; the `VERIFIED` branch (an open fix unit → `implement`); the verdict lines as the first lines of the `AWAITING_HUMAN` branch |
| M1.4 | `facts_of`, only the `tasks_done=` and `tasks_total=` lines | `snapshot.tasks_done`, `snapshot.tasks_total` (required tasks) |
| M1.4 | `run_plan` | whole body: flags, CI outputs, `actionable` |

`_NOT_ACTIONABLE` is left alone by every branch. Its `fixing` and `waiting_capacity` texts become unreachable, and the
merger may update them after the last merge.

**`src/l4/state/lifecycle.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.3 | `Trigger`, after `VERIFY_NEEDS_HUMAN` | `VERDICTS_ANSWERED`, `FIX_UNIT_DONE`, `MINOR_FINDINGS_FIX`, `VERIFY_FAIL_EXHAUSTED` |
| M1.3 | `TRANSITIONS`, after the `VERIFY_NEEDS_HUMAN` row | `{AWAITING_HUMAN} VERDICTS_ANSWERED → VERIFYING`, `{FIXING} FIX_UNIT_DONE → VERIFYING`, `{VERIFIED} MINOR_FINDINGS_FIX → FIXING`, `{VERIFYING} VERIFY_FAIL_EXHAUSTED → ESCALATED, ExitCode.HALTED (13)` |
| M1.3 | the source sets of the `REQUIRED_ROLE_UNAVAILABLE` and `BREAKER_OR_BUDGET` edges | each gains `Phase.FIXING` |
| M1.4 | `Trigger`, after `PR_MERGED` | `RESUMED = "resumed"` |
| M1.4 | `TRANSITIONS`, after the `PR_MERGED` row | `_edge({Phase.HALTED}, Trigger.RESUMED, None)` |

**`src/l4/state/fold.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | `UnitState`, after `sessions` | `retry_after: str \| None = None`, `fallback_from: dict[str, str] = Field(default_factory=dict)` (role → profile) |
| M1.2 | bodies of `_phase_changed` and `_availability_selected` | reads `retry_after` and `fallback_from` |
| M1.3 | `UnitState`, after `last_verdict` | `fix_round: int = 0`, `children: list[str]`, `open_fix_unit: str \| None = None`, `verdicts_consumed: list[str]` |
| M1.3 | new functions between `_verify_verdict` and `_pr_updated` | `_fix_spawned`, `_fix_done`, `_human_verdict` |
| M1.3 | `HANDLERS`, after the `"verify.verdict"` row | `"fix.spawned"`, `"fix.done"`, `"human.verdict"` |
| M1.4 | new function after `_pr_updated` | `_unit_resumed` |
| M1.4 | `HANDLERS`, after the `"pr.updated"` row | `"unit.resumed": _unit_resumed,` |
| M1.4 | `UnitState`, after `iteration` | any new field. The fold has no breaker counter today [V], so line 42 says what it resets |

**`src/l4/state/status.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.3 | `UnitSnapshot`, after the `questions` field | `children: tuple["ChildSnapshot", ...] = ()` |
| M1.3 | new function after `load_snapshot` | `child_snapshots(…)` |
| M1.3 | the final `return UnitSnapshot(…)` of `load_snapshot` | adds `children=child_snapshots(…)` |
| M1.4 | `_read_branch` signature and its tasks line | `_read_branch(git, tracking_ref, unit_rel, *, parse_tasks: Callable[[bytes], list[Task]] = parse_openspec_tasks)` |
| M1.4 | the `_read_branch(…)` call in `load_snapshot` | passes the unit's parser |
| M1.4 | `UnitSnapshot.tasks_done` body | counts required tasks |
| M1.4 | new property after `tasks_done` | `tasks_total` |

**`src/l4/implementer/workbench.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | `Workbench`, after the line `setup_at: …` | `previous_attempt: PreviousAttempt \| None = None`. It is set by the orchestrator after `make_workbench`, so M1.2 does not change the signature of `make_workbench` |
| M1.2 | `commit()`, only the `CommitTrailers(…)` call | `fallback_from=self.selected.fallback_from` (plus the agent trailer) |
| M1.3 | `Workbench`, after the line `runner: ProcRunner = …` | `event_context: Mapping[str, Any] = field(default_factory=dict)` |
| M1.3 | the bodies of `emit()` and `run_gate()` | `emit` merges `event_context`; `run_gate` passes `trace_env()` |
| M1.3 | the end of the `make_workbench` signature and body | `event_context=None, extra_unit_dirs=(), caches=None` |
| M1.4 | new method after `publish_prompt` | `wip_snapshots(self, task: str, phase: str, attempt: int)` (a context manager) |
| M1.5 (C, group 1) | new method after `reset_agent_tmp` (the last method) | `mcp_servers(self) -> tuple[McpServer, ...]`. It runs `check_serena` once per `run_id` and caches the result |
| M1.5 (C, group 1) | inside `HARNESS_EXCLUDES` | `".serena/cache/"`, `".serena/project.local.yml"` |

**`src/l4/implementer/tdd.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | `_prompt`, the `data_blocks=` line | adds the `previous-attempt` block when `wb.previous_attempt` is set |
| M1.3 | `agent_step`, the line `extra = {c.env: …}` | `\| trace_env()` |
| M1.3 | `classify_red` signature | `failure_kinds=False, allowed_passing=()` |
| M1.3 | `run_red` body; `RedOutcome` | `RedOutcome.criteria` and status `already_satisfied`; payload fields `task.red_ok.criteria`, `.suppressions` and `task.done.suppressions` |
| M1.4 | `agent_step`, the line `wb.emit("step.started", …)` | removed; inside the existing `try:`, `run = wb.impl.run(request)` is wrapped in `with wb.wip_snapshots(task.key, role, attempt):` |
| M1.5 (C, group 1) | `_prompt`, just before `ctx = PromptContext(` | `lessons = inject_for_task(…)` |
| M1.5 (C, group 1) | `_prompt`, the `data_blocks=` line (final order below) | the lessons block |
| M1.5 (C, group 1) | `_prompt`, the `prompt.rendered` emit | `lessons=[…]` |
| M1.5 (C, group 1) | `agent_step`, inside `RunRequest(…)`, just before `stall_timeout_s=` | `mcp_servers=wb.mcp_servers(),` |

**`src/l4/specs/base.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.3 | after `class CriterionIdCollision` | `FixUnitExists`, `FixUnitInvalid` |
| M1.3 | after `class ArchiveReport`, before `class Unit` | `Finding`, `SpecDelta`, and `@runtime_checkable class FixUnitCapable(Protocol)` with `create_fix_unit`. **It is not a member of `SpecProvider`** (§4, item 7) |
| M1.4 | `Task`, after its last field | `optional: bool = False`, `wave: int \| None = None`, `links: tuple[str, ...] = ()` |
| M1.4 | `SpecProvider`, after `validate` | `def done_gate(self, unit: UnitRef) -> GateReport: ...` |

**`src/l4/specs/criteria.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.3 | end of file | `trace_ids(case) -> frozenset[str]` |
| M1.4 | after `openspec_criteria` | `kiro_criteria(unit_dir) -> list[Criterion]` |

**`src/l4/verifier/ladder.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | `verify_hook`, the lines from `judge_name = cfg.roles.judges[0]` through `selected = services.factory.for_role("judges", …)` | `selected = select_judge(services.factory, cfg, services.ref.id, implementers)`; `judge_name = selected.profile_name` |
| M1.2 | `VerifyContext`, after `judge_timeout_s` (as built: a defaulted field cannot precede the non-defaulted `judge_timeout_s`; M1.3 adds its fields after these) | `independence: Independence \| None = None`, `seat: JudgeSeat = field(default_factory=JudgeSeat)`, `next_judge: Callable[[str, RunResult \| None], tuple[LLMBackend, str]] \| None = None`. Expect merge conflicts in `ladder.py` (imports, `VerifyContext`, `_judge_step`), `verifier/types.py`, `implementer/tdd.py` and `implementer/workbench.py` (`Workbench.previous_attempt` sits next to M1.3's fields); against M1.4: `planner.py` imports, `state/ledger.py` (adjacent properties) and `tests/unit/cli/test_dispatch.py` (the expected union). M1.2 merges first; resolve by keeping both sides |
| M1.2 | `_judge_step`, only the statements from `judged = run_judge(…)` through the `raise RoleUnavailable(…)` of the `error` status | moves to the next independent judge on `RoleLimit` or `model_mismatch` |
| M1.2 | `require_independent_judge` | **stays defined** (§4, item 6) |
| M1.3 | `LADDER` | the whole tuple: steps 0, 1, 2, 3, 4, 4a, 9, 10 |
| M1.3 | `verify_unit` | body: steps 1, 4 and 4a |
| M1.3 | `_judge_step` | only the argument lines of `build_judge_prompt(` |
| M1.3 | `verify_hook`, the argument line of `make_workbench(` | `provider=FamilyProvider(…)` |
| M1.3 | `verify_hook` | the questions file joins `paths` before `_commit_evidence` |
| M1.3 | `verify_hook`, the tail from `wb.emit("verify.verdict", …)` to `return` | `after_verdict` |
| M1.3 | `run_verify`, the `dataclasses.replace(…)` line | `fix=None` |
| M1.3 | new functions after `_commit_evidence` | |
| M1.3 | `VerifyContext`, after `judge_timeout_s` | new fields |
| M1.5 (C, group 2) | `LADDER` rows | 5 and 8 (no `4e2e`, §4 item 4) |
| M1.5 (C, group 2) | step 3 | e2e inside `tests()` |
| M1.5 (C, group 2) | after step 4a | steps 5 and 8; the gate summary is rebuilt after step 5 |
| M1.5 (C, group 2) | `verify_hook` | curation after `after_verdict` (§4, item 11) |

**`src/l4/verifier/types.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | new dataclass after `class GateLine` | `Independence` |
| M1.2 | `VerifyResult`, after `judge_model` | `independence: Independence \| None = None` |
| M1.3 | new dataclasses after `class StepRecord` | its own types |
| M1.3 | `Finding`, after `suggested_fix` | `id: str = ""` |
| M1.3 | `VerifyResult`, after `guards` (end) | `integrity`, `trace`, `audit`, `human`, `fix` |
| M1.3 | the lines `StepStatus = …` and `CriterionResult = …` | values `reused`; `fail`, `disputed`, `uncovered` |
| M1.5 (C, group 2) | `CriterionOutcome`, after `counterexample` | `tests`, `s1_p` |
| M1.5 (C, group 2) | `VerifyResult`, after M1.3's fields | `generated`, `s1` |
| M1.5 (C, group 2) | `StepStatus` | value `unavailable` |

**`src/l4/verifier/report.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | after the `lines.append(f"- Judge: …")` statement | the `independence:` line |
| M1.2 | `verdict_json`, after `"judge_model"` | key `"independence"` |
| M1.3 | `TRACEABILITY_LINE` and its use | |
| M1.3 | new sections right after the `## Gates` block | Integrity, Traceability, Audit, Human verdicts |
| M1.3 | `verdict_json`, after `"holds"` | new keys |
| M1.5 (C, group 2) | | matrix columns; keys `generated` and `s1` |

**`src/l4/verifier/judge.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | the `JudgeRun.status` Literal | gains `"model_mismatch"` |
| M1.2 | `run_judge` | body |
| M1.3 | `PROMPT_VERSION`, `SYSTEM`, `build_judge_prompt` | `PROMPT_VERSION = 3`; new keyword parameters with defaults |

**`src/l4/verifier/preconditions.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.3 | only the `report = wb.provider.validate(…)` block | becomes a loop over the units of the family. Family tasks arrive through `FamilyProvider.tasks`, so M1.3 does **not** touch the `pending =` line |
| M1.4 | only the `pending = […]` line | `… for t in required(wb.provider.tasks(wb.ref)) …` |

**`src/l4/agents/base.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | `LimitSignal` | `window_minutes`, `used_percent` |
| M1.2 | `AgentCaps` | `served_model` |
| M1.5 (C, group 1) | `McpServer` | `env: tuple[tuple[str, str], ...] = ()` |

**`src/l4/agents/codex.py`, `src/l4/agents/claude_code.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 | new functions and methods only (app-server session, quota and auth probes, judge mode) | `build_command` is untouched |
| M1.5 (C, group 1) | `build_command` | the MCP branch only; an empty `mcp_servers` leaves the argv byte-identical |

**`src/l4/doctor/registry.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.4 | | `Fix`, `attach_fix`, `run_checks(…, scopes=, unit=)` |
| M1.4 and M1.5 | `CHECK_MODULES` | same-line union (§2.2) |

**`scripts/runner/sandbox-probe.sh`, `tests/unit/sandbox/test_probe_parity.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.2 (G17) | the opencode case in `m0` mode | |
| M1.5 (line 37, group 1, only if P1 holds) | the gate kind | `--tmpfs /dev/shm` |

**`tests/unit/state/test_lifecycle.py`**

| Inc | Anchor | Names |
|---|---|---|
| M1.3 | `BUILT_ROWS`, after the `VERIFY_NEEDS_HUMAN` row | its 4 rows, and `(P.FIXING, T.BREAKER_OR_BUDGET, P.HALTED, ExitCode.HALTED)` |
| M1.3 | the source tuple of the `REQUIRED_ROLE_UNAVAILABLE` generator | `P.FIXING` |
| M1.4 | `BUILT_ROWS`, after the `PR_MERGED` row | `(P.HALTED, T.RESUMED, None, None)` |
| both | the `assert not sources & {…}` line and its comment | same-line union (§2.2) |

**Existing tests that several increments break** [V, grep of `tests/unit` at `98e4939`]. One editor per assertion,
or a same-line union (§2.2):

| Test file | Who edits what | Constraint on the others |
|---|---|---|
| `tests/unit/cli/test_dispatch.py`, line `for name in ("lessons", "simulate", "unlock", "resume", "probe", "questions", "ci render"):` (it asserts these handlers are still stubs) | M1.2 removes `"probe"` (its `run_probe` module now exists); M1.4 removes `"simulate"` and `"resume"`; M1.5 removes `"lessons"` | same-line union (§2.2) |
| `tests/unit/planner/test_next_action.py`, the phase table (rows `("fixing", 2, 2, "none", "fixing")` and `("waiting_capacity", 1, 2, "none", "waiting_capacity")` are adjacent) | **no branch edits it** | M1.2: `waiting_capacity` with no `retry_after` still gives `("none", <reason containing "waiting_capacity">)`. M1.3: `fixing` with no open fix unit gives `("none", <reason containing "fixing">)`; `verified` with no open fix unit still gives `hand_off`; `awaiting_human` with no verdict facts keeps its exact reasons. New cases go in new modules |
| `tests/unit/verifier/test_ladder.py` (the `steps == {"0","2","3","9","10"}` sets and the `"traceability: not checked (M0)"` line), `tests/unit/verifier/test_report.py` (the same line) | **M1.3 only** (its ladder and `TRACEABILITY_LINE` change them) | M1.2 adds its tests in new modules and keeps these assertions passing: the `independence:` line is extra text, and `availability.selected` roles stay `{"implementer", "judges"}`. M1.5 group 2 edits them after M1.3 |
| `tests/unit/planner/test_plan_cli.py` line 68 (`--probe`, `--detailed-exitcode` "not yet"), `tests/unit/doctor/test_doctor_cli.py` line 101 (`--fix` "not yet") | **M1.4 only** | — |
| `tests/unit/planner/test_plan_cli.py` (the whole `l4/plan@1` JSON is compared) | nobody changes the shape | M1.4's `--probe` view appears only with `--probe` |
| `tests/unit/state/test_lifecycle.py` | see above | same-line union (§2.2) |

### 2.2 Same-line unions: final text

* **`src/l4/doctor/registry.py`:**

  ```python
  CHECK_MODULES = ("l4.doctor.checks_agents", "l4.doctor.checks_spec", "l4.doctor.checks_provision", "l4.doctor.checks_memory")
  ```

* **`src/l4/verifier/types.py`** (once M1.5 group 2 is in):

  ```python
  StepStatus = Literal["ok", "failed", "not_run", "reused", "unavailable"]
  ```

* **`tests/unit/state/test_lifecycle.py`:**

  ```python
  # escalated cannot be left yet; merged and abandoned are terminal
  assert not sources & {P.ESCALATED, P.MERGED, P.ABANDONED}
  ```

* **`tests/unit/cli/test_dispatch.py`** (once M1.2, M1.4 and M1.5 are all in; each branch removes only its own
  names):

  ```python
  for name in ("unlock", "questions", "ci render"):
  ```

* **`src/l4/implementer/tdd.py`** `_prompt` `data_blocks=`. M1.5 writes it on top of M1.2's version, so this is not a
  parallel conflict. The block order is: answers, lessons, previous-attempt.

---

## 3. Cross-increment interface contracts

Each contract gives:

* the provider and the consumers;
* the signature (frozen: additive changes only);
* what the consumer does until the provider is on `main`.

A consumer brings a merged provider into its branch with `git merge main`, never with a rebase.

### 3.0 S0: the seam commit (contracts that two branches would otherwise both create)

**Commit.**

* Title: `m1.x(seams): versions, tool-less test writer`.
* Built by one Sonnet implementer, from this section alone. One review on the session model.
* It adds **new files only**. A branch that merges `main` after S0 therefore never conflicts on it.
* S0 may land before branching, or while the branches start. In the second case, each branch runs `git merge main`
  before its first consuming line:
  * M1.2 line 11;
  * M1.3 line 24;
  * M1.4 G2 and line 28;
  * M1.5 line 25.

**`src/l4/versions.py`**

```python
def parse_version(text: str) -> tuple[int, int, int] | None
    # the first `\d+\.\d+(\.\d+)?` in text; missing patch -> 0; None when absent
def version_at_least(found: str, minimum: str) -> bool | None
    # None when either side does not parse
```

Test: `tests/unit/test_versions.py::test_parse_version_from_cli_output`. Cases: `codex-cli 0.160.0`,
`2.1.288 (Claude Code)`, `opencode 1.18.34`, `v22.23.0`, `kiro-cli 2.27.1`, and garbage → None. Also
`::test_version_at_least_boundaries`.

**`src/l4/verifier/generated-test.schema.json`**

* Only the keywords that `l4.schemacheck` supports [V: `type`, `required`, `properties`, `additionalProperties`,
  `pattern`, `minLength`, `maxLength`; `$id` is an annotation]:

  ```json
  {"$id": "l4/generated-test@1", "type": "object", "required": ["criterion"], "additionalProperties": false,
   "properties": {"criterion": {"type": "string", "pattern": "^C-[0-9a-f]{8}$"},
                  "code": {"type": "string", "minLength": 1, "maxLength": 20000},
                  "not_testable": {"type": "string", "minLength": 1, "maxLength": 500}}}
  ```

* "Exactly one of `code` and `not_testable`" is checked by the harness: the subset has no `oneOf`.
* Criterion ids are `C-` plus 8 hex digits for every framework [V, `criteria.criterion_id`].

**`src/l4/verifier/testwriter.py`**

```python
SCHEMA_ID = "l4/generated-test@1"; TEMPLATE = "testwriter@1"
TEST_SCHEMA: dict[str, Any]          # loaded with importlib.resources, as judge.JUDGE_SCHEMA is [V]
TestKind = Literal["audit", "e2e"]

@dataclass(frozen=True) class GeneratedTest: criterion: str; code: str
@dataclass(frozen=True) class NotTestable:  criterion: str; reason: str
@dataclass(frozen=True) class WriterReply:
    status: Literal["ok", "not_testable", "invalid", "limit", "timeout", "error"]
    test: GeneratedTest | None; not_testable: NotTestable | None; detail: str
    model: str | None; cost_usd: float | None; prompt_sha256: str

def build_writer_prompt(kind: TestKind, criterion_id: str, criterion_text: str,
                        data_blocks: Sequence[tuple[str, str]], *, retry_reason: str | None = None,
                        redact: Callable[[str], str] = lambda t: t) -> tuple[str, str]   # (system, user)
def request_test(judge: LLMBackend, *, kind: TestKind, criterion_id: str, criterion_text: str,
                 data_blocks: Sequence[tuple[str, str]], retry_reason: str | None = None,
                 redact: Callable[[str], str] = lambda t: t, timeout_s: int = 600) -> WriterReply
def test_path(kind: TestKind, criterion_id: str, *, round_no: int | None = None) -> str
    # audit: f"tests/test_l4_audit_c_{hex}_r{round_no}.py" (round_no required); e2e: f"e2e/test_l4_c_{hex}.py"
def write_test_file(worktree: Path, rel_path: str, code: str) -> Path
    # refuses absolute paths, "..", and symlinked parents (fsutil.reject_symlinks); LF, UTF-8, atomic_write_bytes
```

* `request_test` makes **one** `judge.complete_structured` call. Any retry is the caller's, through `retry_reason`.
* Status mapping:

  | `StructuredResult` | `WriterReply.status` |
  |---|---|
  | `limit`, `timeout`, `error` | the same value |
  | `schema_invalid`; both or neither of `code` and `not_testable`; `criterion != criterion_id`; `ast.parse(code)` fails | `invalid` |
  | `not_testable` given | `not_testable` |
  | otherwise | `ok` |

* Data blocks are wrapped with the existing `l4.implementer.prompt.data_block` [V], which defuses `<l4:` inside the
  text.
* The prompt is the caller's: M1.3 sends the criterion and the head source; M1.5 sends the criterion, the UI diff and
  the page snapshot. Profile selection and the path policy are the caller's too.
* Tests in `tests/unit/verifier/test_testwriter.py`:
  * `test_reply_with_code_is_ok_and_parses`;
  * `test_both_or_neither_field_is_invalid`;
  * `test_wrong_criterion_is_invalid`;
  * `test_syntax_error_is_invalid`;
  * `test_limit_and_timeout_pass_through`;
  * `test_paths_follow_the_naming_convention`;
  * `test_write_refuses_escape_and_symlinks`.

### 3.1 The contracts

| # | Provider → consumers | Signature (frozen) | Until the provider is on `main` |
|---|---|---|---|
| C1 | **Chain selection.** M1.2 → M1.3 (audit writer, fix loop), M1.5 (generator, S1 stand-in), M1.4 (dry run) | `Factory.for_role(role, unit, *, serves=None, constraints=()) -> Selected`. The new `Selected` fields have defaults: `vendor: str \| None = None`, `provenance: Literal["served","tool","declared","unknown"] = "unknown"` (`fallback_from` exists [V]). `WaitingCapacity(RoleUnavailable).retry_after: datetime`. `l4.verifier.selection.independence_constraint(cfg, implementer_profiles) -> Constraint`. `select_judge(factory, cfg, unit, implementer_profiles, *, role="judges", skip=()) -> Selected`, which raises `WaitingCapacity` with the reason `no independent verifier` | Consumers keep today's API: `require_independent_judge(cfg, implementers, cfg.roles.verifier_agent[0])`, then `factory.for_role("verifier_agent", unit, serves=JUDGE_ADAPTERS)` [V, both exist]. Once M1.2 is on `main`, they switch to `select_judge(…, role="verifier_agent")`. M1.2 does not delete `require_independent_judge` (§4, item 6) |
| C2 | **Capacity re-entry.** M1.2 → M1.3 | `UnitState.retry_after`; the planner's `waiting_capacity` row | M1.3's exhausted `verifier_agent` parks at exit 12 and does not re-enter (M1.3 risk). M1.2 merges first, so this lasts only on the branch |
| C3 | **Clock.** M1.2 → M1.4 | `l4.availability.cooldown`: `Clock` (Protocol, `now() -> datetime`, UTC-aware), `SystemClock`, `FakeClock(start)` with `.now()` and `.advance(delta)` | M1.4 builds no FakeClock. Its `quota-fallback` scenario stays `ready: False` until both are on `main` |
| C4 | **Cool-down reads.** M1.2 → M1.4 (`plan --probe`) | `CooldownRegistry(path).cooling(key, now) -> Cooldown \| None` and `.earliest_reset()`; the path is `cache_root(...)/availability.json` | `NullAvailability` says `unknown` |
| C5 | **Auth readiness.** M1.2 → M1.4 (PRV-001) | PRV-001 calls `Factory.build(profile).probe(profile, "auth", ctx)` [V, the `AgentAdapter.probe` protocol] and parses no CLI output of its own | Codex and claude go through the M0 probes. `kiro` is `unknown`, because no `kiro-cli` adapter exists before M1.2 |
| C6 | **Versions.** S0 → M1.2 line 11, M1.4 G2 and line 28 | §3.0 | (S0 lands first) |
| C7 | **Test writer.** S0 → M1.3 line 24, M1.5 line 25 | §3.0 | (S0 lands first) |
| C8 | **Traceability and aggregation.** M1.3 → M1.5 | `l4.verifier.traceability`: `TracingTest(id, status, proof, adequate)`, `CriterionEvidence`, `trace_criteria(criteria, report, ledger, cfg, *, extra_reports=(), generated=None, base=())`. Proofs: `zero_value \| pre_satisfied \| red_assertion \| pass_to_pass \| audit \| generated`. `aggregate_criterion(…, *, trace=None, human=None, require_traceability=True)`. `l4.specs.criteria.trace_ids(case)` also matches `C-<hex>`, `C_<hex>` and `c_<hex>` (any case) in test ids. That is M1.5 G5's rule, so `trace_ids` is a superset of it | M1.5 Stages A–B use the interim `trace_e2e` in `e2e_trace.py`. M1.5 group 2 replaces the `4e2e` step with M1.3's step 4, given the e2e report through `extra_reports`. Accepted generated tests enter as `TracingTest(proof="generated")`: M1.5 passes `generated={criterion: [accepted test ids]}`, and any other test of an extra report is judged like a main-report test (red proof, else ignored). Without `generated` every test of an extra report counts as generated, so the report must then hold accepted generated tests only. `base=` is the archived specs' criteria (pass-to-pass). There is **no `evidence=` keyword**. Step 5's targets stay "UI-facing criteria with no tracing test **in the e2e report**": a unit test does not count. M1.3's general `uncovered` list is not used for that. `trace_e2e` remains as a thin wrapper over `trace_ids`, applied to the e2e report only |
| C9 | **Verifier-round test commit.** M1.3 → M1.5 | `l4.verifier.evidence.commit_verifier_tests(wb, paths: Sequence[Path], round_no: int) -> str \| None`: one commit per round, `test(<unit>): verifier round <n> [skip ci]`, with `L4-Phase: verifying`, made after steps 4a and 5. Neither step commits on its own | M1.5 line 27 returns the accepted paths and commits nothing. The commit is wired in group 2 (line 34) |
| C10 | **Fix units.** M1.3 → M1.4 (sim, Kiro), M1.5 (later curation origin (a)) | `@runtime_checkable FixUnitCapable.create_fix_unit(parent: UnitRef, round: int, findings: Sequence[Finding], spec_delta: SpecDelta \| None) -> UnitRef`; `is_fix_unit(ref)`; `fix_units_of(provider, parent)`; `<fix>/.l4/fix.json` (`l4/fix-unit@1`); events `fix.spawned{parent, fix_unit, round, findings, consumed}` and `fix.done{fix_unit, round, findings}` | M1.4's `ProviderRegistry` checks only `SpecProvider` members. `KiroProvider` does not implement `FixUnitCapable`. **Ask `FamilyProvider.can_fix`, never `isinstance(provider, FixUnitCapable)`**: the wrapper has the method whatever it wraps (it raises `SpecError` for a provider without fix units), and `FamilyProvider.done_gate` is the wrapped provider's own gate per family member. `fix.spawned` also carries `verify_round` (null and `adopted: true` for an orphan fix unit recorded by the next round). `verify-fail-fix-pass` stays pending until both are on `main` |
| C11 | **Lifecycle.** M1.3 and M1.4 → the orchestrator | §2.1 lifecycle rows | — |
| C12 | **Spec model.** M1.4 → M1.3 | `Task.optional`, `Task.wave`, `Task.links`; `l4.implementer.tasks.required(tasks)`; `SpecProvider.done_gate`; `_read_branch(…, *, parse_tasks=parse_openspec_tasks)`; `providers_for` returns every detected provider (callers must not take `[0]`) | M1.3's `child_snapshots` calls `_read_branch(git, ref, rel)` with the default parser. Fix units are OpenSpec-only, so it is correct before and after M1.4. `FamilyProvider` implements `done_gate` from the start (OpenSpec has one [V, M1.1 line 32]) |
| C13 | **Workbench and gate plumbing.** M1.3 → M1.4 (WIP), M1.5 (e2e) | `Workbench.event_context`, `run_gate(…, extra_env=None)`, `build_gate_env(…, extra=None)`, `make_workbench(…, event_context=None, extra_unit_dirs=(), caches=None)`. M1.4's `wip_snapshots` emits through `wb.emit`, so fix-unit context is carried | M1.4 and M1.5 call `wb.run_gate` and `wb.emit` as they are today |
| C14 | **Prompt data blocks.** M1.2 and M1.5 → M1.4 (dry run) | Order: answers, lessons, previous-attempt. M1.4's dry-run prompt-hash test is the guard | A merge-time follow-up, not part of line 30: line 30 is in group 1, when `l4/sim/dryrun.py` may not exist on `m15` yet. When a `main` that contains M1.4 is merged into `m15` (at the latest just before M1.5's own merge), M1.5 adds the lessons block to `l4.sim.dryrun`; M1.4's prompt-hash test is the trigger. The previous-attempt block never appears in a dry run (there is no fallback there) |
| C15 | **MCP.** M1.5 → the codex and claude-code adapters | `McpServer.env`; `l4.memory.serena.mcp_server_for(adapter, worktree, tmp) -> McpServer \| None`; `mcp_timeouts(adapter)` | OpenCode and Kiro MCP are deferred (M1.5 Simplifications); no one builds them now |
| C16 | **S1.** M1.5 ← M1.2 | `open_s1_backend(cfg, role, events)` stays outside `factory.py`. The stand-in uses `for_role("s1_judge", unit, serves=JUDGE_ADAPTERS)`; after M1.2 that call skips backend profiles instead of failing | M1.5 line 28 lands in group 1, after M1.2 |
| C17 | **Doctor framework.** M1.4 → M1.5 | Checks register with `scopes` (it exists [V]: `DEFAULT_SCOPES`); `attach_fix(check_id, fix)` is optional | M1.5's checks are warnings with the default scopes and no fixes |
| C18 | **Lesson commit order.** M1.5 ↔ M1.3 | In `verify_hook`: evidence commit and push, then `after_verdict(ctx, wb, result, trigger) -> Trigger` (fix unit commit and push; four arguments as built, the call site passes the verdict's trigger), then curation (`chore(memory)`, `L4-Phase: lessons`). Curation runs only when the trigger is `VERIFY_PASS` and no fix unit was spawned in that round. M1.3's `subject_sha` ignores `L4-Phase: lessons` commits and `.serena/memories/harness/**` | M1.5 group 2 is built on top of M1.3 |
| C19 | **Simulation.** M1.4 ↔ M1.2 and M1.3 | The `BUILTIN[name] = BuiltinEntry(owner, file, ready)` manifest. Fixture gates write the trace channel that M1.3 G1 picks. Scripted tests are named `test_l4_c_<hex>_<slug>`, scripted red stubs are `raise NotImplementedError` only, and failure messages follow the shape recorded by M1.3 G1 | Whichever of M1.3 and M1.4 merges second re-baselines the expected events of the ready scenarios and flips `verify-fail-fix-pass` to ready. M1.4, which merges after M1.2, flips `quota-fallback` at its merge |
| C20 | **`prereqs.sh` pins.** M1.5 → M1.4's drift test | Pins stay in the top block as `NAME_VERSION=${NAME_VERSION:-x.y.z}` [V, the format today]. M1.5 adds `LAYA_VERSION` in that format. The drift test parses that regex and checks only the catalog tools | — |
| C21 | **The current implementer.** M1.3 fix loop ↔ M1.2 fallback | `ctx.shared["implementer"]` is the zero-argument callable `Orchestrator._select`. M1.2's `_fall_back` sets `self._selected`, so the fix loop always sees the current profile | A `RoleLimit` in a fix task propagates and parks the unit. Once M1.2 is on `main`, `fix_hook` calls `ctx.shared["fall_back"](run, task)` (`Orchestrator.switch_profile`, which also updates `_selected`, the outcome's `profiles` and `L4-Fallback-From`) and retries that task once with the returned `Selected` (M1.3 G4). Never `Factory.on_limit` directly: the next `ctx.shared["implementer"]()` would hand back the cooled profile |
| C22 | **Red and green shas in the ledger.** M1.4 → M1.3 (`verifier/integrity.py`, `already_satisfied` emitter) | M1.4 emits `task.red_ok` and `task.done` BEFORE their commits, so they travel inside the commit and a kill between steps resumes: both carry `base` (the step base, the commit's first parent) and no `sha`. The sha follows as a separate event after the commit: `task.red_committed{task, base, sha}` and `task.green_committed{task, base, sha}`. Derivation without the events: red sha = the commit with `L4-TDD: red` and `L4-Task: <key>` whose first parent is `task.red_ok.base`; green sha = the `L4-TDD: green` child of `task.done.base` | M1.3's consumers read `sha` from `task.red_ok` / `task.done` (`_green_sha`, `check_freeze`, the TDD-history check). At the merge they must read it from `task.red_committed` / `task.green_committed` (or derive it), and M1.3's already-satisfied emitter of `task.done` should carry `base` as well. Until then `check_freeze` silently skips and the TDD-history check blocks every task. A merge-time test runs a happy scenario through M1.3's integrity checks |

---

## 4. Conflicts and duplicated work between the plans, and their resolution (plans edited)

1. **`testwriter.py` would be created twice** (M1.3 D5 and M1.5 D2: "whichever lands first").
   * Two parallel branches cannot both do that: it gives an add/add conflict with different contents.
   * Resolution: S0 (§3.0). M1.3 owns the file after S0.
   * Edited: m13 D5; m15 D2 and line 25.
2. **`min_version` comparison would be written twice:** M1.2 line 11, and M1.4 G2 with line 28 (no helper exists [V]).
   * Resolution: `l4.versions` in S0.
   * Edited: m12 line 11; m14 G2 and line 28.
3. **Two FakeClocks** (M1.2 line 4 in `availability/cooldown.py`, M1.4 line 17 in `sim/fakes.py`).
   * Resolution: M1.2's is the only one, and M1.4 drops its own (C3). `quota-fallback` needs M1.2's clock anyway.
   * Edited: m14 line 17; m12 line 4.
4. **M1.5's `evidence=` keyword, its `4e2e` step and `trace_e2e` duplicate M1.3's `trace=`, step 4 and `trace_ids`.**
   M1.5's "non-UI criteria keep the M0 traceability override" is also void once M1.3 lands.
   * Resolution:
     * M1.5's Stage C is split (§5.1);
     * its ladder, aggregation and report work (lines 33–36, 38) is built on top of the merged M1.3, with C8;
     * step 5 still targets UI-facing criteria that no **e2e** test traces: a criterion covered only by a Codex unit
       test must still get a generated e2e test, or M1.5's lesson is never curated.
     * `trace_ids` covers M1.5 G5's id forms.
   * Edited: m15 lines 14, 33–36 and G5, Files, Interfaces; m13 lines 4 and 22.
5. **Two "verifier round" test commits** (M1.3 line 24, M1.5 line 27).
   * Resolution: one commit per round (C9).
   * Edited: m13 line 24; m15 line 27.
6. **M1.2 replaces `require_independent_judge`**, but M1.5 line 25 calls it, and so does M1.3's fallback for line 24.
   `tests/unit/verifier/test_independence.py` tests it [V].
   * Resolution: `verify_hook` stops calling it, but the function stays. It is deleted only after M1.5 is on `main`.
   * Edited: m12 line 32.
7. **`create_fix_unit` as a `SpecProvider` member would break M1.4's `ProviderRegistry`**, which "rejects a provider
   that lacks a member": `KiroProvider` has no fix units.
   * Resolution: a separate `FixUnitCapable` Protocol (C10).
   * For a provider without it:
     * a FAIL goes to `VERIFY_FAIL_EXHAUSTED` (escalated, exit 13);
     * convertible minors on a PASS are listed as "not converted: kiro has no fix units".
   * Edited: m13 line 31 and Files; m14 line 1.
8. **The `roles.verifier_agent` preflight check would be written twice** (M1.3 line 24 table, M1.5 line 38).
   * Resolution:
     * M1.3 adds `verifier_agent` to the optional-roles name check;
     * M1.5 adds only "non-empty when e2e and Playwright are on" and the System-One checks.
   * Edited: m13 Files; m15 line 38.
9. **M1.5 line 32 duplicates existing code.** `.serena/memories/harness/**` is already in `CONTRACT_PROTECTED_GLOBS`
   [V, `security/protected.py`].
   * Resolution: line 32 adds only the SCN-MEM-02 test.
   * Edited: m15 line 32 and Files.
10. **`subject_sha` against the `chore(memory)` commit.** Under M1.3 D4, a lessons commit would count as a new subject
    and block resume at aggregation.
    * Resolution: D4 also ignores `L4-Phase: lessons` and `.serena/memories/harness/**` (C18).
    * Edited: m13 D4.
11. **Curation on a PASS round that spawns a fix unit.** The next PASS would find the UI criterion already covered by
    the committed test, so no lesson would be curated.
    * Resolution: curation runs only on the final PASS: `VERIFY_PASS` with no fix unit spawned (C18).
    * Edited: m15 line 36; m13 line 37.
12. **M1.4's simulation fixture gate gives M1.3 no trace evidence.** It is stdlib `unittest` with no markers, so
    `happy-*` would end `NEEDS_HUMAN` once M1.3 lands.
    * Resolution: C19 (name-traced tests, `NotImplementedError` stubs, G1-shaped failure messages); the second merger
      re-baselines.
    * Edited: m14 line 19; m13 Interfaces.
13. **M1.4 G1 misses three places that count optional leaves** [V, code]:
    * `Orchestrator._discover`, `pending = any(not t.done …)`;
    * `_implement`, `pending = [t.key …]`;
    * `_outcome`, `TaskCounts`.

    Edited: m14 G1. Its tests also move to new modules (rule 2.0.5).
14. **M1.2 omits `UnitFacts.retry_after` and the `facts_of` line.** The capacity row cannot read `retry_after`
    without them.
    * Edited: m12 Files.
    * Test paths moved to new modules: `test_schema_profile_reserve.py`, `test_report_independence.py`.
15. **M1.5's probe branch `l4/probe-m15` would run the routed `l4` job.** The template runs it on any push to `l4/**`
    [V, `l4.gitlab-ci.yml` rule 3], and `l4 run` would then work on `main`'s actionable units.
    * Resolution: the branch becomes `probe/m15`, **and** its `.gitlab-ci.yml` is replaced by the probe job alone, as
      M1.4's `probe/m14` does. The rename alone is not enough, because the `l4` job comes from the included template.
    * Edited: m15 line 2 and G2.
16. **`memory` leaving `OPAQUE_SECTIONS` makes unknown `memory.*` keys a load error.**
    * No test fixture and no `l4 init` template has a `memory:` section [V].
    * The dummy-agentic `.l4/config.yaml` is [U].
    * Edited: m15 line 3 (check it before the M1.5 live run; `l4 upgrade` lists the keys).
17. **Live levers left behind by earlier protocols.**
    * M1.3 leaves `verifier.fix_minor_findings: true`, `max_fix_rounds: 1`, `audit_sample_ratio: 0.1` and
      `roles.verifier_agent: [claude-code]` in dummy-agentic.
      * With them, M1.5's lesson is never curated (item 11).
      * M1.4's spend would no longer be "one judge call".
    * M1.2 leaves `profiles.kiro`, which M1.4 also adds.
    * Resolution: the reset table in §5.3.
    * Edited: the live sections of m14 and m15.
18. **Stale gates.** "Waits for M1.1 Stage C" appeared in all four plans:
    * m12 Stage C;
    * m13 line 39;
    * m14 lines 31, 32 and Stage C;
    * the Interfaces sections.

    M1.1 Stage C has landed [V], so each was reworded as "landed (m11-progress lines 26–41, `98e4939`)".
19. **The dry-run prompt can drift from `_prompt`** (M1.4 risk).
    * Calling `_prompt` from the dry run was rejected: `Workbench.__post_init__` writes files, and `_prompt` needs git,
      the ledger and the sandbox, which would break M1.4's zero-side-effect spy test.
    * Resolution: M1.4's hash-compare test stays as the guard. M1.5 updates `l4.sim.dryrun` when it merges a `main` that
     contains M1.4 (a merge-time follow-up, C14).
    * Edited: m14 line 36; m15 line 30.
20. **Shared spots: M1.2 judge fallback and M1.3 judge prompt in `_judge_step`; M1.3 and M1.4 in `run_command`; M1.3
    and M1.4 in `preconditions`.**
    * These are not design conflicts, but they are the same functions.
    * Resolved by the §2.1 anchors. M1.3 does not touch the `pending =` line.
21. **Mid-run fallback inside the fix loop** (C21).
    * Edited: m13 G4.

Found but not cross-increment (left to the owner):

* M1.4 line 42 says "breaker counters reset in the fold", but the fold has no breaker counter [V].
* M1.2 line 29 needs the previous-attempt data in the rebuilt workbench. §2.1 pins it as `Workbench.previous_attempt`,
  set after `make_workbench`.

---

## 5. Merge order, post-merge checks and live exits

### 5.1 Before branching, and while the branches run

0. Wait until the M1.1 review fixes in the working tree are committed. Then make one docs-only commit on `main`: the
   four plans and this file, staged by path. Then:

   ```bash
   git worktree add ../l4-m12 -b m12 main
   ```

   and the same for `m13`, `m14` and `m15`. Run `uv sync` once in each worktree, so each has its own `.venv`; the uv
   cache stays shared.
1. **S0** (§3.0): one Sonnet implementer and one review, committed on `main`. Each branch merges `main` before its
   first consuming line.
2. **Keep branches fresh.** After every merge to `main`, every open branch runs `git merge main` at its next stage
   boundary. Conflicts stay small, and each is resolved with §2.
3. **M1.5 Stage C is split:**
   * **group 1**: lines 28, 29, 30, 31, 32, 37 and 39. It starts once M1.2 is merged to `main` and `main` is merged
     into `m15`.
   * **group 2**: lines 33–36 and 38. It starts once M1.3 is merged.
   * Line 40 comes last.
   * Stages A and B (owned files, plus the line 3 schema edit) do not wait.

### 5.2 Merge order

**M1.2 → M1.3 → M1.4 → M1.5.** M1.4 may overtake M1.3 when it is ready first. M1.2 is always first, and M1.5 always
last.

| # | Merge | Why at this position |
|---|---|---|
| 1 | **M1.2** | Every other increment consumes `for_role`, `Selected`, `WaitingCapacity` or `select_judge` (C1, C2). Its codex and claude adapter edits must precede M1.5's MCP branch (group 1). Its `_prompt` block precedes M1.5's lessons block. Its planner capacity row removes M1.3's exit-12 stall risk |
| 2 | **M1.3** | It is on M1.5's critical path: group 2 waits for it. It provides traceability, fix units, the verdict lifecycle and the shared verifier-round commit |
| 3 | **M1.4** | Its contracts with M1.3 are order-independent (C10, C12, C19). It may go before M1.3 if ready first; the second of the two re-baselines the simulation events and `test_lifecycle.py` |
| 4 | **M1.5** | Its Stage C is built on top of M1.2 (group 1) and M1.3 (group 2), so it merges with almost no conflict |

**Merge mechanics.** On `main`:

```bash
git merge --no-ff m1N
```

Resolve conflicts only by §2 (source and tests), then run the post-merge check. Nothing else merges until it is green.

**Post-merge check** (on `main`, after each merge):

```bash
uv sync --locked
uv run ruff check src tests && uv run ruff format --check src tests
python3 -c 'import fcntl,subprocess,sys; f=open("/tmp/l4-full-suite.lock","w"); fcntl.flock(f,fcntl.LOCK_EX); sys.exit(subprocess.call(sys.argv[1:]))' uv run pytest -q
```

[V] The lock wrapper propagates the exit code. macOS has no `flock(1)`.

Then the merged increment's local exit, **and again the local exits of every increment merged before it**:

| Increment | Local exit (offline, fakes, bare remotes) |
|---|---|
| M1.2 | `uv run pytest tests/unit/availability tests/unit/agents tests/unit/llm tests/contract/availability tests/scenarios/test_agent_factory_scenarios.py -q`: the Stage C exit (mid-run fallback, waiting for capacity, judge chain) |
| M1.3 | `uv run pytest tests/unit/gates tests/unit/implementer tests/unit/verifier tests/unit/planner tests/unit/orchestrator tests/contract/test_openspec_fix_unit.py -q`: the Stage C exit (FAIL → fix → PASS, minor spec gap, no rounds left, `[chore]`, blocked fix task, `--unit <fix>` exit 2, `l4 verify` stops at exit 10) |
| M1.4 | `uv run l4 simulate --all --json`, run twice: identical normalised events, `5 pass, 0 fail`, plus whatever became ready at this merge (C19). Also `uv run pytest tests/unit/specs tests/unit/sim tests/unit/provision tests/unit/forge tests/unit/ci tests/unit/doctor -q` |
| M1.5 | `uv run pytest tests/unit/memory tests/integration/test_memory_flow.py tests/unit/llm/test_system_one.py tests/unit/gates/test_e2e.py tests/unit/verifier -q`: Exit C (unit 1 with generated test, S1 and lesson; unit 2 with the lessons block injected) |

Once M1.3 and M1.4 are both on `main`, the M1.4 row also runs after M1.5's merge.

### 5.3 Live exits: serial, after the merges, on one runner

**Rules**

* A live exit runs after its increment is merged.
* It pins the harness with `l4 upgrade --harness <main sha right after that merge>`. Later merges therefore do not
  change a protocol that is in progress.

**Sequence**

| Step | Protocol | Gate |
|---|---|---|
| L0 | **M1.1 G13** (the M1.1 live protocol) | It has never run [V], and every later protocol needs M1.1's units `in_review` or later. It starts once the M1.1 review fixes in the working tree are committed; it blocks live exits, not merges |
| L1 | **M1.2** steps 1–4 and 6 (P1, P2, P4; P3 optional) | Step 6's cleanup (codex cool-down cleared) must pass before L2 |
| L2 | **M1.3** P1, then P2 on branch 1B | |
| L3 | **M1.4** P2 on `main` | Its P1 (`probe/m14`) floats: see below |
| L4 | **M1.5** P1, P2 (a human merge), P3 | M15-G2's probe pipeline (`probe/m15`) runs much earlier, in Stage A |

**No two protocols share a pipeline.** Each one's levers would break another's expectations:

* M1.2 P1's `claude-judge` (`min_version 99`) and its `judges` chain would change who judges M1.3's unit, and M1.3's
  1A/1B branch depends on the judge.
* M1.2 P2's `codex.min_remaining_percent: 100` would push any other unit's implementer onto OpenCode.
* M1.3 needs `fix_minor_findings: true`; M1.5 needs it `false` (§4, item 11).
* M1.4 P2 requires that no other unit is actionable in the same job (its step 1 checks).

**Pipelines that float.**

* **M1.4 P1** runs on `probe/m14`, which has no `l4` job and spends nothing. It may run in any human-wait gap of
  another protocol, once M1.4 is merged and `l4 plan` on `main` shows no actionable unit.
* **M15-G2** (`probe/m15`) may run in such a gap too, but only with nothing else running on the runner: its Laya RSS
  must be measured on an idle runner.

**Config resets** (in the protocol's own step 0 or 1 on dummy-agentic):

| Protocol | Set before it runs | Why |
|---|---|---|
| M1.2 | (written into its own steps 0, 3 and 6) | It ends with chains `implementer: [codex, opencode-free, claude-code]` and `judges: [claude-code, opencode-free, codex]`, `profiles.kiro` kept, and no codex cool-down |
| M1.3 | its step 0.4 (`verifier_agent`, `fix_minor_findings: true`, `max_fix_rounds: 1`, `audit_sample_ratio: 0.1`) | — |
| M1.4 | `verifier.fix_minor_findings: false`, `roles.verifier_agent: []`; keep `profiles.kiro` if M1.2 added it | It keeps the planned spend (one judge call), and a Kiro unit cannot take a fix unit (§4, item 7) |
| M1.5 | `verifier.fix_minor_findings: false`, `verifier.audit_sample_ratio: 0`, `roles.verifier_agent: [claude-code]`, `roles.s1_judge: [laya, claude-code]` | Lesson curation needs the round-1 PASS to be final (§4, item 11). The audit would add Claude calls |

**The runner lane.** One holder at a time. That covers:

* any pipeline on dummy-agentic;
* every `mk-ssh.sh` script: `record-probes.sh`, `sandbox-probe.sh`, `prereqs.sh --apply`/`--check`, and `l4 probe`
  reads;
* any operator command on the runner.

`concurrent = 1` serialises jobs only; `mk-ssh.sh` bypasses it.

Order during development:

1. M1.2 G14 (zero cost, about 10 min, first).
2. L0's pipelines. `mk-ssh` items run only while no L0 pipeline is running.
3. M1.2 G17.
4. M1.5 G1 `prereqs.sh --apply`. It **changes the runner**, so never during a pipeline.
5. M1.5 G2.

---

## 6. Risks of working in parallel

* **CPU and I/O on the Mac** [V: 16 cores].
  * A full suite takes about 4–5 min on one process. It spawns git and uv, and four can run at once beside the
    implementers.
  * Rule: per-line checks run targeted tests only. The full suite runs only at stage exits and before a merge, under
    the lock in §5.2 (one at a time).
  * The known flaky test `tests/unit/agents/test_proc.py::test_interrupt_sends_sigint_then_the_run_ends` (it failed in 3
    of 4 full runs, m11-progress) gets worse under load. Re-run it alone before calling a failure a regression.
* **Caches.**
  * Each worktree runs `uv sync` into its own `.venv`; uv's cache stays shared and warm.
  * Do **not** set `XDG_CACHE_HOME` for test runs: uv reads it [I], and `tests/unit/init/test_vendor.py` runs uv with
    `UV_OFFLINE=1` [V], so a cold cache would fail it.
  * Unit tests pass explicit environ dicts with a temporary `HOME`. Only 9 files under `tests/unit` read `os.environ`:
    4 of them are live-only, and the conftest reads only `PATH` [V]. So `~/.cache/l4` is not shared between the
    parallel suites [I].
  * Operator-machine live smoke tests do use `~/.cache/l4`: `uv run l4 probe --json` (M1.2), the G18 smoke test, and
    the M1.5 Stage B smoke tests. Run them one at a time, or with `L4_CACHE=/tmp/l4-cache-<inc>`.
* **Ports and `/tmp`.**
  * Tests that bind a socket use port 0: M1.5's fixture web app and `LayaServe`, M1.4's `LocalForge` if it serves.
  * Live record files have per-increment names (rule 2.0.7).
  * The suite lock file is `/tmp/l4-full-suite.lock`.
* **One CI runner** (`l4-runner`, `concurrent = 1`, 3.8 GB RAM, about 1.3 GB free [V, plans and runner
  README]). Live exits run serially after the merges (§5.3), and the Stage A probes take turns in the runner lane.
  * M15-G2's Laya measurement is only meaningful on an idle runner.
  * M1.5 G1 changes the runner: never during a pipeline.
* **Subscription quota is account-wide.**
  * The Claude `pro` and Codex windows are shared by:
    * M1.2's G18 smoke and live steps;
    * M1.3's audit and judge;
    * M1.5's generator, smoke tests and judge;
    * the operator's own use.
  * M1.2's step 2 needs claude-code to have ≥ 10 % left in every window. Do not run `L4_LIVE` smoke tests during a
    live exit.
* **Semantic conflicts that git cannot see.** A clean text merge can still be wrong. For example:
  * a new `UnitState` field the fold never sets;
  * a lifecycle row exercised by no test.

  Guards: the post-merge full suite, re-running every earlier increment's local exit, and the second merger
  re-baselining the simulation events (C19).
* **Stale branches.** A branch that does not merge `main` for long collects conflicts. Rule: `git merge main` at every
  stage boundary after any merge to `main` (§5.1, item 2).
* **Plan drift.** An implementer that changes a name pinned in §2.1 or §3 breaks the mechanical merge. Such a change
  is a request to the merger: it is recorded in the increment's progress file and in this document before anything
  depends on it.

---

## 7. Merge log

### 2026-10-04: S0, M1.2 and M1.4 into `main` (from `5851b61`)

Merge order: S0 → M1.2 → M1.4. M1.4 went ahead of M1.3 (§5.2 allows this). Nothing was pushed.

| Commit | What |
|---|---|
| `0ffd8a7` | `m1x-seams` at `5c0135e` (S0). Clean: new files only |
| `ba7847a` | `m12` at `7b4506a`. Clean textual merge. `orchestrator.py`, `workbench.py`, `ledger.py` and `ladder.py` auto-merged with main's M1.1 progress-trace fixes and were read by hand |
| `ee4bfc2` | `m14` at `72932be`. Six conflicts, all resolved additively (below) |
| `808ef7b` | integrate: `test_plan_exit_and_probe` expects M1.2's probe ladder `binary, auth, quota, hello` |
| `6bbdaff` | integrate: `archive._Mirror._labels` skips the `pr.labels` record once the ledger is finished |
| `eb4271f` | integrate: M1.4's test doubles answer `capabilities()`; the dry-run `--probe` test expects M1.2's ladder |

**M1.4 conflicts and how they were resolved**

* `config/schema.py` `Profile`: M1.4's `min_version: ToolVersion | None`, followed by M1.2's `min_remaining_percent`.
* `state/ledger.py`: both new properties, M1.2's `run_id` and M1.4's `path`.
* `orchestrator.py`: M1.2's `switch_profile`/`_fall_back` and M1.4's `_close_parents`, side by side (both added
  methods after `_implement`).
* `planner.py` imports: the union.
* `tests/unit/cli/test_dispatch.py`: the union of the removals, `("lessons", "unlock", "questions", "ci render")`.
  `lessons` goes with M1.5 (§2.2).
* This file: M1.2's C21 wording, plus M1.4's new C22 row.

**Semantic conflicts that git did not see** (found by the post-merge suite):

* M1.2's `_prompt` calls `wb.impl.capabilities()`. M1.4's duck-typed doubles had only `run`: `WriteThenSleep` in
  `test_wip_timer.py` and `Partial` in `test_reconcile.py`.
* M1.2 adds `quota` to the probe ladder, so `plan --probe` and `run --dry-run --probe` now probe it.
* M1.1's progress trace (on `main` after M1.4 branched) records `pr.labels` in the mirror. M1.4 moved a halting run's
  first push into `close()`, after `ledger.finish`, and guarded only `after_push`. The result was `LedgerClosed` in
  `test_resume.py`. Now only the record is skipped; the labels are still set.
* C22 was checked: `progress.py` reads only `task`/`tests` from `task.red_ok`/`task.done`, never `sha`.

**Suite** (`uv run pytest -q`, chunked; `test_proc.py::test_interrupt_sends_sigint_then_the_run_ends` also passed
alone in the foreground at the final head)

| Chunk | After M1.2 | After M1.4 and the fixes |
|---|---|---|
| unit agents, availability, llm | 374 passed, 4 skipped | 374 passed, 4 skipped |
| unit verifier, implementer, gates | 372 passed, 1 skipped | 392 passed, 1 skipped |
| unit orchestrator, archive, state, vcs, specs | 340 passed, 2 skipped | 448 passed, 2 skipped |
| every other unit dir and `tests/unit/test_*.py` | 745 passed, 3 skipped | 786 + 263 passed, 3 skipped |
| contract, scenarios, integration, live | 39 passed, 22 skipped | 42 passed, 29 skipped |
| **total** | **1870 passed, 32 skipped** | **2305 passed, 39 skipped, 0 failed** |

Before the integrate fixes, the M1.4 merge failed 9 tests in the suite: `test_wip_timer` 3, `test_reconcile` 3,
`test_resume` 2 and `test_dryrun` 1. A targeted run had already caught `test_plan_exit_and_probe` 1. `ruff check .`
is clean. `ruff format --check` flags 33 files: 26 were already flagged on `5851b61`, and 7 are unformatted on
their branch tip (1 from `m12`, 6 from `m14`). None comes from a conflict resolution, and none was reformatted
here.

**Local exits (offline)**

* M1.2:
  * SCN-AVL-02, 03, 08, 09, 10, 16, 17 and 19 (plus the amended 19), and SCN-FAC-06, 09 and 12;
  * `test_independence`, `test_judge_chain`, `test_selection` and the fallback, park-retry, capacity-row and
    fold-capacity tests: 96 passed after each merge.
* M1.4:
  * `l4 simulate happy-openspec happy-kiro`: 2 passed;
  * `l4 simulate --all --json`, run twice: `5 pass, 0 fail, 16 pending`, identical `events_sha256`;
  * `l4 plan --detailed-exitcode`: 10 on a copy of the `openspec-basic` fixture, 0 there without the flag, 0 on a
    repo with no unit;
  * doctor `--fix` (scratch HOME), the Kiro intake and parent tests, the crash-resume integration test and the
    dry-run prompt parity (C14): 42 passed.
* M1.1 regression: progress trace, progress, the clarifier end to end, reentry, scenario lint, open questions and
  `tests/unit/ci` (template golden): 285 passed, 2 skipped.

**Left open**

* C19: `quota-fallback` passes when it is flipped to ready, but it is **not flipped**. Its
  `availability.cooldown.until` comes from `SystemClock`, so SCN-SIM-01 (`test_all_ready_scenarios_twice_identical`)
  sees two runs differ. The fix is one of these, and the owner decides which:
  * the sim drives M1.2's `FakeClock` (C3): a clock threaded through `run_command` → `build_services`;
  * `normalize_events` placeholders `until`.
* C4: `l4.sim.availability.ProbingAvailability` builds `Factory(cfg, ctx)` without M1.2's `AvailabilityStore`, so
  `plan --probe` does not show cool-downs yet.
* Cosmetic: M1.4's `_close_parents` records `task.done{closed=…}` for a parent closed without a step. M1.1's
  `progress.py` prints it as `task N green ok: all tests passing`.

### 2026-10-04: M1.3 into `main` (built on `int-m13`, from `8dce4b0`)

Merge order: S0 → M1.2 → M1.4 → M1.3 (M1.4 overtook M1.3, §5.2). The merge was built on the branch `int-m13` in its own
worktree, from `main` at `8dce4b0`; `main` itself was not touched. Nothing was pushed.

| Commit | What |
|---|---|
| `bee1ce2` | `m13` at `891c3d5`. Twelve conflicts, all resolved additively (below) |
| `5e398db` | integrate: C22, step 1 reads the red and green shas from `task.red_committed` / `task.green_committed`; the already-satisfied events travel inside their commit |
| `d7a27e0` | integrate: C21, a limit in a fix task falls back through the orchestrator and the task is retried once |
| `15d4694` | integrate: a round resumed at aggregation keeps M1.2's independence record |
| `7f10df4` | integrate: M1.4's Kiro unit doubles tag their red tests with the Kiro criterion ids |
| `9fca1b4` | integrate: `ruff format` of the C22 condition in `check_tdd_history` |

**M1.3 conflicts and how they were resolved**

* `specs/base.py`: M1.4's `SpecProvider.done_gate`, `PROVIDER_MEMBERS` and `ProviderRegistry`, then M1.3's
  `FixUnitCapable` (a separate Protocol, C10).
* `implementer/workbench.py`: both new `Workbench` fields, M1.2's `previous_attempt` and M1.3's `event_context`.
* `implementer/tdd.py`:
  * imports: the union;
  * `run_red`: M1.3's checks and its `tampered("before the red commit")` guard, then M1.4's pre-commit block. The
    `task.red_ok` written before the commit carries M1.4's `base` and M1.3's `criteria` and `suppressions`; after the
    commit, `task.red_committed`; `manifest = replace(frozen, red_sha=sha)`;
  * `resume_red`: M1.3's read of the parent's run ledger (`ledger_rel`), matched on M1.4's task and base
    (`rev-parse <sha>~1`) plus M1.3's `fix_unit`;
  * `run_green`: M1.4's pre-commit `task.done` gains M1.3's `suppressions`, then `task.green_committed`; M1.3's
    `proved_test_files` and `run_single` follow unchanged.
* `verifier/ladder.py`:
  * imports: the union;
  * `require_independent_judge`: M1.2's body (it delegates to `independence_constraint`), plus M1.3's additive
    `*, role="judges"`. The ladder no longer calls it; it stays until M1.5 is on `main` (§4, item 6);
  * `VerifyContext`: M1.2's `independence`, `seat` and `next_judge`, then M1.3's `audit_writer` and `verifier_tests`;
  * `_judge_step`: M1.2's `_ask_judges` (judge chain, limit and served-model fallback); M1.3's inline emit block was
    the same code and was dropped; M1.3's tail is kept (`run.judged`, `_counterexample`, test adequacy);
  * `verify_hook`: M1.3's family and `consume_verdicts` prelude, M1.2's "a judge chain exists" check, `round_no`,
    M1.3's `_resumable`. A fresh round selects with `select_judge(…, skip=skip)` (M1.2). A resumed round makes no
    judge call (D4): its `Selected` is the first chain profile whose adapter can judge, built without a probe, and
    the context gets `_NoJudge()` and no `next_judge`. The workbench gets `provider=family`;
  * **C1**: the audit writer is `select_judge(services.factory, cfg, unit, implementers, role="verifier_agent")`
    instead of `require_independent_judge` plus `for_role("verifier_agent", serves=JUDGE_ADAPTERS)`; none left is
    `WaitingCapacity` with `no independent verifier`;
  * module docstring: steps 0, 1, 2, 3, 4, 4a, 9 and 10.
* `verifier/types.py`, `state/status.py`, `planner.py` imports, `tests/unit/verifier/conftest.py`: the union (M1.4's
  `run_plan` no longer uses `ExitCode`/`L4Exit`, so `planner.py` imports `plan_exit_code` only).
* `state/lifecycle.py` and `orchestrator.py` docstrings: both sides' notes (rule 2.0.4).
* `tests/unit/implementer/test_workbench.py`: both new tests.
* `tests/unit/state/test_lifecycle.py`: the §2.2 text (`assert not sources & {P.ESCALATED, P.MERGED, P.ABANDONED}`)
  plus M1.4's assertion that `halted` is left only by `resumed`.
* This file auto-merged: M1.3's review rounds had reworded C8, C10 and C18 only.

**Semantic conflicts that git did not see**

* **C22** (found by `l4 simulate happy-kiro`, which ended FAIL and then `escalated`, exit 13: "the red and green
  commits do not match the ledger"). M1.4 writes `task.red_ok` and `task.done` before their commits, with `base` and
  no `sha`, so M1.3's freeze check skipped every task and the TDD-history check blocked every task.
  `integrity._sha` now resolves the commit of either event: its own `sha`, else the `task.red_committed` /
  `task.green_committed` with the same unit, task and base, else the unit's commit for the task whose first parent is
  that base (a kill that lost the line). M1.3's already-satisfied path now writes `task.red_ok` and `task.done` with
  `base` before its commit, then both `*_committed` lines. A parent that M1.4's `_close_parents` closes with no step
  (`task.done{closed}`, a commit with `L4-Task` and no `L4-TDD`) has no TDD history to check. After the fix,
  `happy-openspec` and `happy-kiro` show the freeze and TDD-history rows `ok` (2 tasks each), not `skipped`.
  Tests: `test_integrity_c22.py` (6), `test_already_satisfied_c22.py` (1).
* **C21**: `fix_hook` catches `RoleLimit` from `run_task`, records `availability.limit` (with `fix_unit`), discards
  the step, calls `ctx.shared["fall_back"]` (`Orchestrator.switch_profile`) and retries the task once on a rebuilt
  child workbench, which keeps the baselines and carries the previous-attempt block. A second limit on the same task,
  or an empty chain (`WaitingCapacity`), parks the unit. M1.3's two fix-loop limit tests now advance the FakeClock
  past the cool-down before the next run, because a limit now records one. Tests: `test_fixloop_fallback.py` (2).
* **Resumed rounds lost the `independence:` line.** `restore_round` did not know M1.2's field; it now rebuilds
  `VerifyResult.independence` from the reused round's `verdict.json`. Test: `test_resume_independence.py` (2).
* **M1.4's Kiro doubles.** M1.3's red phase needs a tracing new test for every cited criterion (`check_criteria`), and
  the scripted red steps of `test_kiro_unit.py` (also used by the dry-run prompt parity test) had no `l4` marker:
  3 tests halted with exit 13. They now mark the tests with the Kiro ids of Req 1.1 and Req 2.1 and report
  `criteria_ids`.

**Contracts checked at this merge**

* S0: `verifier/testwriter.py`, `generated-test.schema.json`, `versions.py` and their tests are byte-identical to
  `m1x-seams` `5c0135e` (`git diff 5c0135e HEAD` on those paths is empty).
* C1: see `verify_hook` above. C2: `fixing → waiting_capacity → fixing` re-entry runs in M1.3's fix-loop limit test.
* C10: before the C22 fix, `happy-kiro`'s FAIL showed "Escalated: kiro has no fix units" and exit 13, as §4 item 7
  says. `create_fix_unit` is not a `SpecProvider` member.
* C19: the ready scenarios needed no new expected events (their `events_include` lists still hold, and they pass).
  `verify-fail-fix-pass` is **not** flipped (Left open).

**Suite** (`uv run pytest -q`, chunked, at `9fca1b4`; `test_proc.py::test_interrupt_sends_sigint_then_the_run_ends`
passed in its chunk and again alone in the foreground)

| Chunk | After M1.4 and the fixes | After M1.3 and the fixes |
|---|---|---|
| unit agents, availability, llm | 374 passed, 4 skipped | 375 passed, 4 skipped |
| unit verifier, implementer, gates | 392 passed, 1 skipped | 696 passed, 1 skipped |
| unit orchestrator, archive, state, vcs, specs | 448 passed, 2 skipped | 479 passed, 2 skipped |
| every other unit dir and `tests/unit/test_*.py` | 786 + 263 passed, 3 skipped | 1062 passed, 3 skipped |
| contract, scenarios, integration, live | 42 passed, 29 skipped | 42 passed, 40 skipped (+11: M1.3's live tests) |
| **total** | **2305 passed, 39 skipped, 0 failed** | **2654 passed, 50 skipped, 0 failed** |

A first chunked run at `5e398db` (the merge plus the C22 fix) failed 3 tests, all in chunk 3 (`test_kiro_unit` 2,
`test_dryrun_prompt_parity` 1: the Kiro doubles); the other chunks were green there. The C22 break showed first in
`l4 simulate`. `ruff check .` is clean.
`ruff format --check src tests` flags 41 files: 33 were already flagged on `8dce4b0` and 8 are unformatted on the
`m13` tip. None comes from a conflict resolution or an integrate commit, and none was reformatted here.

**Local exits (offline)**

* M1.3:
  * vacuity, pre-satisfied, stubs, criteria, already-satisfied, single-phase, red evidence, traceability, audit,
    integrity, ladder depth, verdicts, verdict re-entry, resume, the trace plugin and the recorded JUnit, plus
    `tests/contract/test_openspec_fix_unit.py` with `L4_LIVE=1` against the installed pinned OpenSpec 1.14.0: 208
    passed;
  * the fix loop end to end (`test_ladder_fix`, `test_fixloop`, `test_fixloop_fallback`, `test_fixunit`, the planner
    fix-unit rows, `run --unit <fix>` exit 2): 63 passed. Among them FAIL → `[chore]` fix unit → PASS, a rejected
    criterion → ADDED regression → `already-satisfied` → PASS (round 3), `max_fix_rounds: 0` → `escalated`, exit 13,
    and `l4 verify` stopping at `fixing` with exit 10;
  * the same two FAIL → fix → PASS flows once more with the real pinned OpenSpec instead of the stand-in (a throwaway
    test, not committed): a spy recorded `validate` and `new change` through
    `~/.local/share/l4/npm/node_modules/@fission-ai/openspec/bin/openspec.js`; both passed.
  * The progress trace of the rejected-criterion flow: `verdict NEEDS_HUMAN (round 1)`, exit 11; the answer;
    `awaiting_human → verifying (verdicts_answered)`, `verdict FAIL (round 2)`, `docs(add-discount-codes): fix unit 1`,
    `verifying → fixing`, `[add-discount-codes-fix-1] task 1.1` red with `test-presatisfied`, the
    `already satisfied` commit, `fixing → verifying (fix_unit_done)`, `verdict PASS (round 3, 3/3 criteria pass)`,
    `verifying → verified`, exit 0. With `max_fix_rounds: 0`: `verdict FAIL (round 1)`,
    `verifying → escalated (verify_fail_exhausted)`, exit 13.
* M1.2: the same set as at the last merge (SCN-AVL and SCN-FAC scenarios, `test_independence`, `test_judge_chain`,
  `test_selection`, `test_judge_run`, `test_judge_served_model`, `test_report_independence`, fallback, park-retry,
  capacity row, fold capacity): 96 passed.
* M1.4:
  * `l4 simulate happy-openspec happy-kiro`: 2 passed;
  * `l4 simulate --all --json`, run twice at `9fca1b4`: `5 pass, 0 fail, 16 pending`, identical `events_sha256`;
  * crash-resume integration, Kiro unit and parents, dry-run prompt parity, `require_framework`, doctor `--fix`, Kiro
    status, reconcile, resume, the optional-task precondition and planner rows, and `tests/unit/sim`: 122 passed.
* M1.1 regression: progress trace (`tests/unit/obs`), the clarifier end to end, reentry, scenario lint, open questions
  and `tests/unit/ci` (template golden): 305 passed, 2 skipped (the set has grown since the 285 of the last merge).

**Left open**

* **`main` moved on while this merge was built**: `0fa4ad1`, `bf85faa`, `c9e2c0d` and `6eaee92` (live fixes and the
  M1.2 live evidence) are on `main` and not on `int-m13`. A trial `git merge-tree` of `int-m13` with `main` conflicts
  in `src/l4/implementer/prompt.py` (`0fa4ad1`, the prompt-contract result schema, against M1.3's `contract@3`
  edits). That merge is not part of this one (its base is `8dce4b0`, and the counts above are for it); whoever lands
  `int-m13` on `main` resolves it, then reruns `test_prompt.py`, `test_tdd_prompt_contract.py` and
  `test_dryrun_prompt_parity.py`.
* C19: `verify-fail-fix-pass` stays pending. Flipping it is authoring, not re-baselining, all in M1.4-owned sim files:
  `ScriptedAgent._judge` answers one scripted verdict and needs a sequence (FAIL, then PASS); `fake_openspec_cli`
  answers `validate` only and needs `new change` (as `tests/unit/specs/fixcli.py` does); the YAML needs the fix
  task's steps (a `[chore]` single step, or red and green for the fix unit's task).
* Carried from the last merge: `quota-fallback` (`SystemClock` in the sim) and C4 (`ProbingAvailability` without
  `AvailabilityStore`).
* `run_single` still writes `task.done` and `task.tdd_exempt` after its commit (with `sha`), unlike C22. Step 1 skips
  exempt tasks, so nothing depends on it; a kill right after a `[chore]` commit loses those two lines.
* Progress-trace cosmetics: a verdict question prints `question Q-001 raised (verdict): None` (its `question.raised`
  has no `title`, as M1.1's own intake-lint questions do not), and an already-satisfied task prints
  `task 1.1 green ok: all tests passing`, now before its commit line.

### 2026-10-05: M1.5 into `main` (from `cce44f0`)

Merge order: S0 → M1.2 → M1.4 → M1.3 → M1.5 (M1.5 last, §5.2). `m15` had already merged `main` at `cce44f0`
(`7c6cd0b`), so the merge into `main` had no conflicts. Nothing was pushed.

| Commit | What |
|---|---|
| `7c6cd0b` | on `m15`: integrate, `main` at `cce44f0` into `m15` (security fixes, legacy rounds, live fixes). One conflict, in `workbench.py` (below) |
| `410c1aa`…`ebb24f6` | on `m15`: review minors a–g, all test-first (below) |
| `60d6d19`, `cd26132` | on `m15`: the SPEC text M1.5 owed (CLR-001..003, §3.2, §10.2 step 8, VER-008); the two SPEC-parity tests now check it |
| `19d1c01` | on `m15`: `tests/live/test_m1_5_acceptance.py` (13 tests, protocol steps 2–5; skipped unless `L4_LIVE=1`) |
| `9b59f39` | on `m15`: attack test for the conflict resolution (below) |
| `1a30eda` | `m15` at `9b59f39` into `main`, `--no-ff`. Clean |

**The `workbench.py` conflict and how it was resolved**

* `main` (the any-depth guidance fix) added `revert_unsnapshotted(self.git, …)` after the gate's
  `restore_protected`: a `**/AGENTS.md`, `**/CLAUDE.md` or `**/migrations/**` path the gate wrote outside the
  snapshot's anchored roots is put back to HEAD by git. `m15` had moved the gate body into `run_gate_spec(spec, *,
  network, tree=None)`, which the verifier also runs in the merge-base checkout (`git worktree add --detach`).
* Resolution: both act on the tree the gate ran in. `root = self.worktree if tree is None else tree`,
  `git = self.git if tree is None else self.git.at(root)`; then `restore_protected(root, …)` and
  `revert_unsnapshotted(git, …)`.
* `tests/unit/verifier/test_gate_forgery.py`: both sides' tests kept (m15's e2e one, main's two guidance-file ones).
* Template pins merged without conflict (contract 5, red 3, green 1, single 1). `m15` bumps no template.
* Checked at landing: `test_e2e_guard.py::test_a_guidance_file_below_the_root_an_e2e_test_writes_is_put_back_in_the_base_tree`
  (`9b59f39`). An e2e test run in a detached base checkout overwrites a committed `src/pytdd/AGENTS.md` and
  creates `docs/deep/CLAUDE.md`. After the gate the first is restored, the second removed, both are reported as
  `guard.violation{phase=gate}`, and the unit's worktree is untouched. Mutating the call to
  `revert_unsnapshotted(self.git, …)` makes it fail (the base tree keeps the forged text). The security tests,
  `test_gate_forgery.py` and the M1.3 attack files (bytecode, forged markers, ledger tamper, judge cwd): 238 passed.

**Review minors (each read as a diff and its tests run at landing)**

* a `410c1aa`: MCP servers only in implement mode, in both `build_command`s, and `run()` writes `mcp.json` only
  then. Mutating either adapter's condition (codex: drop `if mode == "implement"`; claude: `armed = mode != "judge"`)
  fails its test.
* b `a6ac8ba`: `laya_version` runs with `PATH`, `HOME` and `LANG` only.
* c `2af5adb`: an unwritable laya-serve log directory is `SystemOneUnavailable`; a failed request-log write is a
  warning and keeps the answer (SCN-VER-24).
* d `b769c10`: the Serena check and its startup form are keyed by (run, context, worktree).
* e `f706746`: `verify.s1` carries `checkpoint` and `server_version`; `_calibrate` runs in a `finally` around
  `_judge_step`.
* f `21d65b8`: doctor ENV-006 checks the laya 0.3.24 pin, ENV-007 the Chromium revision directories of the pinned
  Playwright (`PLAYWRIGHT_VERSION = "1.63.0"`, read as PRQ-14 does; name-only fallback without `uvx` or offline).
  Both checks are `warn` severity.
* g `ebb24f6`: the prompt-hash and `run()`-writes-the-MCP-config tests now test what their names say.
* Their test files at landing: 130 passed.

**Suite** (`uv run pytest`, chunked and sequential, at `1a30eda`; collected = passed + skipped in every chunk, no
failures, errors or deselects; `test_proc.py` passed in its chunk, so no solo re-run)

| Chunk | After M1.3 and the fixes | After M1.5 |
|---|---|---|
| unit agents, availability, llm | 375 passed, 4 skipped | 444 passed, 5 skipped |
| unit verifier, implementer, gates | 696 passed, 1 skipped | 876 passed, 3 skipped |
| unit orchestrator, archive, state, vcs, specs | 479 passed, 2 skipped | 483 passed, 2 skipped |
| every other unit dir and `tests/unit/test_*.py` | 1062 passed, 3 skipped | 1241 passed, 3 skipped |
| contract, scenarios, integration, live | 42 passed, 40 skipped | 42 passed, 53 skipped (+13: M1.5's live tests) |
| **total** | **2654 passed, 50 skipped, 0 failed** | **3086 passed, 66 skipped, 0 failed** |

The "After M1.3" column is at `9fca1b4`; `main` gained live fixes and security tests between that and `cce44f0`.
Chunks 2 and 3 were also run on `m15` at `9b59f39` before landing, with the same counts.
`ruff check .` is clean and `python3 scripts/check_spec.py docs/SPEC.md` exits 0. `ruff format --check src tests`
flags 62 files, against 47 at `cce44f0`. The M1.5 fix commits ran `ruff format` on some files they edited
(`workbench.py`, `ladder.py`, `defaults.py`, `test_ui_flow.py`, `test_lessons_and_serena.py`, `test_claude_code.py`),
so whitespace-only reflows are mixed into those diffs. Unlike earlier merges, this one does include such reflows. No
formatting was done at landing.

**Local exits (offline)**

* M1.5 Exit C: `tests/unit/verifier/test_memory_flow.py` (4: finding → lesson, the lesson in a second unit's red
  prompt). §5.2 names `tests/integration/test_memory_flow.py`, but the tests live under `tests/unit/verifier`. Also
  `tests/unit/memory`, `test_system_one.py`, `tests/unit/gates/test_e2e.py` and `tests/unit/verifier`. All of these
  are inside the chunks above and passed.
* M1.4: `l4 simulate --all --json`, run twice at `1a30eda`: `5 pass, 0 fail, 16 pending`, byte-identical output,
  identical `events_sha256`. The happy-openspec digest is `ef141bdd…` and happy-kiro's is `d78ab85d…`.
* M1.2 and M1.3: their local-exit directories are inside chunks 1–3 and passed.

**Left open**

* Jev: the code default is still `jev-latest`. SPEC §3.2's example shows `jev-1.13.0` with a "pin the versioned id"
  note.
* `decisions.criterion.accept` is documented as reserved; nothing in `src` reads it.
* `tests/live/test_m1_5_acceptance.py` has connected to GitLab with `L4_LIVE=1` but skipped all 13 tests (no
  pipelines yet). It has never run against real data, so the M1.5 live exit is still owed.
* `require_independent_judge` can now be deleted: M1.5 is on `main` (§4, item 6).
* Carried: C19 `verify-fail-fix-pass` and `quota-fallback` pending, C4 `ProbingAvailability`.
* The working tree of `main` held an untracked `.serena/memories/live/progress.md` (not this merge's; mtime
  03:28, before the merge). It was left as it was, and `m15` touches nothing under `.serena/`.

### 2026-10-05: M1.7 into `main` (merge `319eb14`, from `f48b82e`)

M1.7 (the base merge at verifier step 0) was merged between M1.5 and M1.6, so the order is S0 → M1.2 → M1.4 → M1.3 → M1.5
→ M1.7 → M1.6. `m17` was built from `cce44f0` and merged into `main` at `f48b82e`. Nothing was pushed.
The merge is `319eb14`; this entry was written afterwards, with the M1.7 follow-ups.

**Conflicts of `319eb14`** (recomputed afterwards with `git merge-tree --write-tree f48b82e 055289d` and compared with
the tree of `319eb14`; nothing else differs):

* `src/l4/sim/dryrun.py`: the import block (`m17` added `from l4.vcs.merge import base_moved`). Resolved by taking the
  import.
* `src/l4/verifier/ladder.py`, two hunks. In `VerifyContext`, `main` added `ui_writer` and `s1` and `m17` added
  `base_note`: all three kept. In the `VerifyContext(...)` call of `verify_hook`, `main` had
  `audit_writer=writer_for("verify-audit")`, `ui_writer=...` and `s1=...`, and `m17` had `audit_writer=open_writer` and
  `base_note=base.note`: `main`'s three arguments kept, `base_note=base.note` added, `m17`'s `open_writer` dropped.

| Commit | What |
|---|---|
| `73ccbcc`, `6424dad` | `l4/vcs/merge.py` (`merge_base_into`, `Escalate`, `BaseMergeConflict`) and the harness-owned `questions.md` and `tasks.md` resolvers (`l4/specs/harness_merge.py`, `questions_merge.py`, `tasks_merge.py`) |
| `54e5175`, `61c47bb`, `2d8141b` | `l4/verifier/basemerge.py` (`bring_in_base`, the first call of `verify_hook`), the step-0 note, and `subject_sha`: a merge commit is never skipped for its phase |
| `8e674fb`, `8b33511`, `b6bc46b` | the sticky note "Base merge needed", the `base merged:` and `base merge conflict` trace lines, and the dry run's "N commits behind" line |
| `7ca793b`, `055289d` | review fixes: a conflict is the unit's exit 1 and the run goes on; `questions.md` rule 4 compares the commit time of each answer's section |
| `ba54759`, `12cc820` | live-fixes on `main` after the dummy-agentic run: the vacuity message names the remedy for a zero-value scenario, and `git merge` runs with the bot identity |

**Shared files touched** (all small and additive): `src/l4/orchestrator.py` (`_verify` catches `BaseMergeConflict`),
`src/l4/verifier/ladder.py` (the seam, 7 lines), `src/l4/verifier/evidence.py` (`subject_sha`),
`src/l4/verifier/preconditions.py` (the guard text), `src/l4/progress.py`, `src/l4/sim/dryrun.py`,
`tests/unit/verifier/conftest.py` (re-exports the archive fixtures). The M1.6 join conflicted once with this set: both
sides added a `VerifyContext` field and its `verify_hook` argument in `ladder.py` (`shadow` / `base_note`), resolved in
`68e4c52`.

**Exits.** Full suite on `m17` at close-out: 2801 passed, 50 skipped; `ruff check .` clean; `check_spec.py` exit 0. The
live protocol ran on dummy-agentic through `l4-runner` and passed after the two live-fixes (`docs/live/README.md`,
M1.7).

**Follow-ups, landed with M1.6's join work.** The red template carries the zero-value remedy (`red@4`); a base merge
conflict has its own exit-summary text (`exit_reason` in `outcome.json`, read by `l4 ci map-exit`; the exit code is still
1); `l4 s1 canary` takes a unit's change as `diff(merge-base(head, base as merged), head)`; the SPEC edits M1.7 owed are
made (12.1 `base.merged` and `base.conflict`, L4-VER-011 on merge commits, the M1 form of a conflict in 12.3).

### 2026-10-05: M1.6 into `main` (from `5f45b02`)

Merge order: S0 → M1.2 → M1.4 → M1.3 → M1.5 → M1.7 → M1.6. The join review found `m16` READY against `f48b82e`. Since
then `main` had gained M1.7 (`319eb14`, the base merge of verifier step 0), its two live-fixes and the M1.7 live record
(`5f45b02`). So `main` was merged into `m16` first (`68e4c52`), and chunks 2–3 were re-run there. Then `m16` was merged
into `main` with no conflicts. Nothing was pushed.

| Commit | What |
|---|---|
| `81b9f81` | on `m16`: integrate, `main` at `f48b82e` into `m16` (the join pass; its conflicts are recorded in `m16-progress.md`, "Join pass") |
| `e91e314`…`e71a7c6` | on `m16`: join lines 12–14 and 28 (gate env, the Evidence section, ladder steps 1, 3 and 6, step 8 shadow rows) |
| `0d3994a`, `00817e2`, `6a5f7ec`, `166ec2b` | on `m16`: the join review's fixes, test-first. Unmeasured coverage is listed under "Needs attention". Step 1 blocks a module that shadows `l4_cov`/`l4_trace`, code that names the coverage output, and pytest 9 config `addopts`. Nothing is cleared or written through a symlinked `.l4-out`. A repository `coverage` module never stands in for coverage.py |
| `6d8eb51` | on `m16`: test-only. S1 shadow answers of all 0 or all 1 leave held and failing units unchanged |
| `68e4c52` | on `m16`: integrate, `main` at `5f45b02` into `m16`. One conflict, in `ladder.py` (below) |
| `597fbb0` | `m16` at `68e4c52` into `main`, `--no-ff`. Clean; its tree is `68e4c52`'s |

**The `ladder.py` conflict and how it was resolved**

* Both sides added a last field to `VerifyContext`: M1.6 `shadow: ShadowWiring | None = None`, M1.7
  `base_note: str = ""`. Both sides also added the matching keyword to `verify_hook`'s `VerifyContext(...)`. Both were
  kept. Both have defaults, and the other two constructions (`test_judge_step.py`) are positional up to `judge_timeout_s`.
* `evidence.py` auto-merged. M1.7 changed `subject_sha` (merge commits), and M1.6 added
  `result.evidence = prev.get("evidence")` to `restore_round`. The hunks are independent.
* Checked at landing by reading the code: every M1.6 Stage A input (step 1 scope, step 3 coverage sources and tests ran,
  step 6, step 8 items) takes `base_sha` from `check_preconditions`. M1.7 computes it after the base merge as
  `merge-base(origin/<base>, HEAD)`, which is the merged base head. So the commits a base merge brings never count as
  the unit's change. M1.7's `test_clean_base_merge_adds_no_integrity_finding` now also runs M1.6's new step-1 scans
  over a base merge, and it passes. No test drives M1.6's scope or coverage step through a non-trivial base merge [I].

**Suite** (`uv run pytest`, chunked and sequential, at `597fbb0`; collected = passed + skipped (+ xfailed) in every
chunk, with no failures, errors or deselects. `test_proc.py` passed in its chunk, so it was not re-run alone.)

| Chunk | Collected | After M1.6 |
|---|---|---|
| unit agents, availability, llm | 469 | 464 passed, 5 skipped |
| unit verifier, implementer, gates | 978 | 974 passed, 3 skipped, 1 xfailed |
| unit orchestrator, archive, state, vcs, specs | 508 | 506 passed, 2 skipped |
| every other unit dir and `tests/unit/test_*.py` | 1442 | 1438 passed, 4 skipped |
| contract, scenarios, integration, live | 105 | 52 passed, 53 skipped |
| **total** | **3502** | **3434 passed, 67 skipped, 1 xfailed, 0 failed** |

The xfail is `test_ladder_evidence_gaming.py` (`strict=True`). It records the SC-03-class hole: an in-process forgery
whose names are built at run time still gets `covered`. Chunks 2–3 on `m16` at `68e4c52`, before landing: 974 passed,
3 skipped, 1 xfailed; 506 passed, 2 skipped. `ruff check .` is clean, `python3 scripts/check_spec.py docs/SPEC.md`
exits 0, and `uv lock --check` passes (`coverage` 7.16.2 joins the dev group). `ruff format --check src tests` flags
63 files (62 at M1.5's landing). No formatting was done at landing.

**Local exits (offline)**

* M1.4: `l4 simulate --all --json`, run twice at `597fbb0`: `5 pass, 0 fail, 16 pending`, byte-identical output. The
  digests moved with M1.6/M1.7's new events: happy-openspec `2879eaf6…`, happy-kiro `f3928b7d…`.
* M1.6 Exit A and the join scenarios (i)–(v), plus the gaming regressions (`test_ladder_evidence*.py`,
  `test_integrity_harness_plugins.py`, `tests/unit/gates/test_l4_cov.py`): all are in chunk 2 and passed. The
  M1.2, M1.3, M1.5 and M1.7 exit directories are in chunks 1–5 and passed.

**Found at landing, not fixed (M1.6 × M1.7)**

* **The canary counts a base merge as the unit's change** [V, probe]. `find_source_units` takes base = the parent of the
  unit's first `implementing` commit and head = its last trailer commit, and `changed_files` is `git diff base head`.
  On a unit branch with an M1.7 base merge, that diff includes everything the merge brought from `main`. The probe was
  a scratch repo where `main` added `src/inventory/stock.py` after the unit's first commit and was then merged into the
  unit branch. `changed_files` listed `src/inventory/stock.py` as the unit's. The verifier does not do this, because
  its base is recomputed after the merge. So `l4 s1 canary` over branches with a base merge makes items the live
  verifier never makes, for example out-of-scope files that came from `main`. This matters for live step 4: the
  dummy-agentic branches from the M1.7 live run may carry base merges. Fix before step 4 (base = the last base-merge
  commit's second parent when there is one, test-first), or have the operator check out only branches with no
  `chore(<unit>): merge <base>@…` commit.

**Left open**

* Join lines 29 (human labels in `verify_hook`), 30 (preflight rules for `verifier.s1.shadow`, `diff_coverage.languages`
  and the checkpoint path), 39 (doctor S1-001, S1-002, COV-001) and 40 (`tests/live/test_m1_6_acceptance.py`) are not
  built (`m16-progress.md`, join deviation 6; line 1 of the progress file). `labels_from_verdicts` has no caller in
  `src`, and no `S1-002` check exists. So the M1.6 live protocol cannot yet meet step 3's `label{source:
  human:verdict}` record or step 6's "doctor S1-002 is OK".
  **Met since (live M1.6, 2026-10-05):** lines 29, 39 and 40 were built after the join (`m16-progress.md`). Step 3's
  `label{source: human:verdict}` record **was met**: job 5543 wrote one label record, `{kind: label, item_key:
  27cf4d6a…, truth: {relevant: false}, label: out_of_scope, source: human:verdict}`, for the rejected scope hold, in the
  job's `.l4-out/s1/` and the runner's `s1-calibration.jsonl`, and none for the accepted coverage hold. Line 30 stays
  partial (the checkpoint path rule is not built). Step 6 (`laya-tuned`, S1-002) was not run: the gate failed.
* The join review's residual risks stand: in-process forgery (SC-03), coverage `not_run` under the default `warn` is
  still a PASS (D4, owner decision), untested logic in scope-exempt paths or test-named production files, a coverage.py
  outside the site directories gives `not_run`, a self-hosting false positive on new `src/l4` lines that name
  `l4_cov`, and the text scan does not exclude the verifier's own audit tests in later rounds.
* `require_independent_judge` is still in `ladder.py`. It has no caller in `src` and can be deleted (§4, item 6).
* M1.7's merge (`319eb14`) has an entry in this log (added afterwards, above).

### 2026-10-05: hb (handbook adopt-now items) into `main` (merge `4c36910`, from `0890188`)

`hb` was built from `bc02d13` in `../l4-wt/hb` (HB-1 to HB-14, HB-17 and HB-X1). Since then `main` had gained the M1.5
and M1.6 live records and one code change, the M1.6 live-fix `7c7d7c9` (`l4/implementer/stubs.py`, the red guard keeps an
`if TYPE_CHECKING` import block, and its test). `hb` was merged into `main` with `--no-ff`. `git merge-tree` and the
merge both found no conflicts, so nothing was resolved by hand. The template lock (HB-11) stays consistent, because
`main` changed no template. Nothing was pushed.

| Commit | What |
|---|---|
| `c0a3a99` | HB-1: `/run` (and `/var/run`) masked in both bwrap sandboxes; probe canaries, PRQ-19, SANDBOX-002 |
| `a8047e0`, `da4b00d` | HB-3: verifier baseline from the base tree via git; the spec root (`openspec/**`, `.kiro/specs/**`) is contract-protected |
| `9ecfb18`, `93afe3f`, `3289ae1`, `6a87b88` | HB-4: outgoing commits are scanned for secrets before every unit-branch push (`guard.secret`, halt exit 13) |
| `9c64531` | HB-2: the `l4` job environment and `--environment-scope` in both CI variable scripts |
| `6eebee5` | HB-13: the Kiro judge starts in an empty directory |
| `8fcef1a`…`8262848` | HB-5: judge and audit-writer prompts are published; `prompt_sha256` hashes the document sent |
| `215861c`, `93ac499` | HB-6: `agent.finished` carries the denial count and tools; Codex `Rejected(` stderr lines become `agent.tool_rejected` |
| `ddadcb3`, `f0ff18e`, `9a971c9` | HB-7/HB-8: one failing unit does not stop the run; `exit_reason` for each halt and escalation |
| `57e9d38`, `5226ba9` | HB-9: the L4-VER-010 breaker (3 consecutive `verify.error` in `verifying` escalate) |
| `7b8f4e6` | HB-10: `run.started` records the runner and tool versions; `verdict.json` the judge template and harness commit |
| `253cea5` | HB-12: forge POST retries read the effect back after a lost response |
| `eb376f5`, `3aa5ddd`, `90a7052` | HB-11: the template lock pins each prompt body's sha256 to its version |
| `93ba338` | HB-14: docs stop claiming unbuilt items as built |
| `de4313a` | HB-17: packaged `recorded_versions.json`; doctor LIVE-005 warns on an unrecorded CLI version |
| `ce0e3c5`…`6fa9ed1` | HB-X1: Codex `-c project_doc_max_bytes=0`; a tmpfs over each existing repo guidance dir in both sandbox kinds; the Claude implementer on `--setting-sources "" --disable-slash-commands` + `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` (`--safe-mode` drops `--mcp-config`); SPEC §8.3, L4-SEC-002, L4-SEC-005 |
| `8824ba0`, `6f21ca1` | review fixes on `hb`, test-first. The guidance masks come after **every** bind, because a later bind at or above the worktree (a valid `sandbox.caches` path such as `$L4_CACHE/worktrees`) put the host directories back. The probe mirror and the parity test follow, and the probe runs Codex with the new flag. The Claude docstring is updated |
| `4c36910` | `hb` into `main`, `--no-ff`. Clean |

**Review at landing.** A one-line mutation of the Codex flag failed 4 tests (`test_codex.py` and the contract test in
all three modes). Dropping the bwrap mask emission failed the argv tests and the parity tests. Removing `.agents` from
`GUIDANCE_DIRS` or from the probe's `m0_guidance` failed parity. Building the argv for a worktree with no guidance
directory references nothing under the worktree and creates nothing there. The test now asserts this. The ledger claims
Serena only for an implement-mode request, and that request's flags keep `--mcp-config` [V `/context`, Serena
`connected`; `--bare` for api_key is I]. The judge and the reader carry no server and stay on `--safe-mode`.

**Open after landing**

* The full Claude implementer flag set was not checked as one command. A model call on the runner failed with "OAuth
  session expired" in both the control and the production argv. `/context` cannot run under `--disable-slash-commands`.
  SPEC §8.3 labels the combination I. A live implementer run is still owed, and the runner's Claude login must be
  renewed first.
* A guidance directory committed as a symlink is not masked. When its target is inside the worktree, Codex loads those
  skills. This is recorded in L4-SEC-005 as a residual: the directory is member-written. Masking the resolved target
  is the follow-up.
* `sandbox.mode: none` applies no mask, because it is an accepted-risk mode.

**Suite** (`uv run pytest`, chunked and sequential, at `4c36910`; collected = passed + skipped (+ xfailed) in every
chunk, with no failures or errors. `test_proc.py` passed in its chunk.)

| Chunk | Collected | Result |
|---|---|---|
| unit agents, availability, llm | 476 | 471 passed, 5 skipped |
| unit verifier, implementer, gates | 999 | 995 passed, 3 skipped, 1 xfailed |
| unit orchestrator, archive, state, vcs, specs | 537 | 535 passed, 2 skipped |
| every other unit dir and `tests/unit/test_*.py` | 1553 | 1548 passed, 5 skipped |
| contract, scenarios, integration, live | 122 | 59 passed, 63 skipped |
| **total** | **3687** | **3608 passed, 78 skipped, 1 xfailed, 0 failed** |

Against `hb`'s own run, chunk 2 has 7 more tests (`main`'s `test_stubs_type_checking.py`) and chunk 4 has 2 more (the
mask-ordering test, both kinds). The xfail is still `test_ladder_evidence_gaming.py` (`strict=True`). `ruff check .` is
clean, `python3 scripts/check_spec.py docs/SPEC.md` exits 0, and `uv lock --check` passes. `l4 simulate --all --json`
was run twice at `4c36910`: `5 pass, 0 fail, 16 pending`, byte-identical. happy-openspec is `355866e2…` and happy-kiro
is `577fa920…`.

### 2026-10-05: fu (M1.5/M1.6 live follow-ups F1–F8) into `main` (merge `6ef2a18`, from `7f3ec21`)

`fu` was built in `../l4-wt/fu` from `df30f81` and reviewed there; it lands at `cfb040d` (15 commits). Since then `main`
had gained `hb` (`4c36910`, merge log `7f3ec21`). `fu` was merged into `main` with `--no-ff`. Nothing was pushed.

| Commit | What |
|---|---|
| `f2bd88b`, `4824753`, `c5af8c5` | the red prompt names the e2e gate's browser-test directory, and so does the UI-criteria lesson (`red@5`); `--headed` takes no value; no "under `tests/`" ban when the directory is `tests/e2e` |
| `fa4fd91`, `c6f7803` | the canary leaves a unit's e2e test files out of the tests-ran check, and does not mutate one it does not run |
| `fbc0f85`, `5362b26`, `9088d0b`, `cfb040d` | a rejected hold is a human decision (FAIL and a fix unit, never asked again); a judge finding on a hold's subject is asked inside the hold's question and settled only by it; a coverage hold is about its functions |
| `a2395d1` | what the guards put back in a step reaches the next attempt's prompt (`implementer/guardnotes.py`) |
| `3cb8119`, `8061582` | an e2e test never proved discriminating does not count as coverage that suppresses step 5 |
| `cbbb29f`, `e0ad097` | coverage.py is checked again right after `gates.setup` (only when it has commands), so COV-001 is answered in CI |
| `bf8cff0` | docs follow the M1.6 live run (line 40 ran live; the step-3 label was met in job 5543) |
| `6ef2a18` | `fu` into `main`, `--no-ff` |

**Conflicts of `6ef2a18` and how they were resolved**

* `docs/SPEC.md` L4-IMP-004: both branches extended the same sentence after "shell redirects into tracked files". Both
  texts are kept: `hb`'s spec-root sentence first, then `fu`'s paragraph on where the red prompt puts browser tests.
* `tests/unit/implementer/test_check_criteria.py` and `test_prompt.py`: `hb` asserted `contract@6` with `red@4`, `fu`
  `contract@5` with `red@5`. Both now assert the highest of each, `contract@6+red@5`.
* `src/l4/templates.lock.json` (no textual conflict; the lock exists only on `main`): `fu`'s `red.md` body changed
  with its bump to 5, so the lock was regenerated (`uv run python -m l4.templatelock --write`). Only
  `implementer/red` changed: version 4 → 5, sha256 `8368d4c0…` → `44742995…`. The sha was re-derived by hand from
  the body after the version line, and `contract` stays at 6 with `5b7825bc…`.
* `src/l4/verifier/ladder.py`, `src/l4/implementer/tdd.py`, `docs/plan/parallel-ownership.md`: merged by git without
  conflict, because the two branches' hunks do not overlap. The merged files pass ruff and their test directories.
* `src/l4/recorded_versions.json` (HB-17): untouched, because `fu` adds no recorded fixtures.

**Found at landing, not fixed (`hb` × `fu`)**

* `guardnotes._GENERIC`, the advice for a protected-path restore, lists CI files, agent configuration, guidance files
  and `.l4/`, but not the spec root that `hb` made protected (HB-3). A spec-root restore still reaches the next prompt:
  its line names the path and the rule glob (`openspec/**`), and `contract@6` states the spec-root rule. The advice
  sentence should name the spec root too, with a test that pins it; no test pins the text today.

**Suite** (`uv run pytest`, chunked and sequential, at `6ef2a18`; collected = passed + skipped (+ xfailed) in every
chunk, with no failures or errors. A whole-suite `--collect-only` gives 3753, the sum of the chunks.)

| Chunk | Collected | Result |
|---|---|---|
| unit agents, availability, llm | 476 | 471 passed, 5 skipped |
| unit verifier, implementer, gates | 1058 | 1054 passed, 3 skipped, 1 xfailed |
| unit orchestrator, archive, state, vcs, specs | 537 | 535 passed, 2 skipped |
| every other unit dir and `tests/unit/test_*.py` | 1560 | 1555 passed, 5 skipped |
| contract, scenarios, integration, live | 122 | 59 passed, 63 skipped |
| **total** | **3753** | **3674 passed, 78 skipped, 1 xfailed, 0 failed** |

Against `hb`'s landing, chunk 2 has 59 more tests and chunk 4 has 7 more, all `fu`'s. The xfail is still
`test_ladder_evidence_gaming.py::test_residual_a_forgery_that_never_names_the_plugin_still_passes` (`strict=True`).
`ruff check .` is clean and `python3 scripts/check_spec.py docs/SPEC.md` exits 0. `l4 simulate --all --json` was run
twice at `6ef2a18`: `5 pass, 0 fail, 16 pending`, byte-identical (sha256 `a7706825…`). happy-openspec is now
`78678f73…` and happy-kiro `494f3a53…`. They differ from `hb`'s values (`355866e2…`, `577fa920…`) because `fu`
changes what a run records, the red prompt (`red@5`) among it; which event moved each hash was not traced [I].

### 2026-10-06: M1.8 (easy adoption) into `main` (merge `c8808e6`, from `f0a96d3`, onto `e7de0c6`)

Merged with `git merge --no-ff m18`; no conflicts, nothing pushed. The branch carries M1.8 plus the five review fixes
(`20c6893`, `d497554`, `162f1f0`, `2840224`, `f0a96d3`). The CI template body changed (the doctor line takes
`${L4_ADOPTION_CHECK:+--adoption}`) and the template lock was already consistent at the merge: `tests/unit/test_template_lock.py`
passes, so no `templatelock --write` was needed.

**Suite** (chunked and sequential at the merge head; collected = passed + skipped (+ xfailed) in every chunk, no failures)

| Chunk | Result |
|---|---|
| unit agents, availability, llm | 476 passed, 5 skipped |
| unit verifier, implementer, gates | 1084 passed, 3 skipped, 1 xfailed |
| unit orchestrator, archive, state, vcs, specs | 545 passed, 2 skipped |
| every other unit dir and `tests/unit/test_*.py` | 1758 passed, 5 skipped |
| contract, scenarios, integration, live | 59 passed, 63 skipped |
| **total** | **3922 passed, 78 skipped, 1 xfailed, 0 failed** |

The first run of chunk 1 had one failure, `tests/unit/agents/test_proc.py::test_interrupt_sends_sigint_then_the_run_ends`
(child killed with SIGKILL before it printed), while another suite was running. It passed 3 of 3 alone and the whole
chunk passed on a rerun: a load-sensitive test, not caused by M1.8 [I]. `ruff check .` is clean and `check_spec.py`
exits 0. `l4 simulate --all --json` twice: 5 pass, 0 fail, 16 pending, byte-identical (sha256 `2844ef62…`);
happy-openspec `78678f73…` and happy-kiro `494f3a53…` are unchanged from the fu landing.

### 2026-10-06: M1.9 (review phase) into `main` (merge `3da5fce`, from `99437aa`, onto `78048f0`)

Merged with `git merge --no-ff m19`; nothing pushed. The branch carries M1.9 (43 commits since `e7de0c6`): the review
phase (a person's commit after H, or the project's own CI red on H, takes an `in_review` unit back to `verifying`),
per-commit forbidden-path attribution, forge URL redaction (`observability.redact_forge_urls`), registration of the
`l4` pytest marker by `init`/`upgrade`, and the audit-test style conventions in the judge prompt. Nine files were
touched on both sides; six merged on their own (`docs/SPEC.md`, `openspec/changes/forge-and-ci/tasks.md`,
`src/l4/archive.py`, `src/l4/config/schema.py`, `src/l4/orchestrator.py`, `src/l4/verifier/ladder.py`) and three
conflicted. Each was resolved by keeping both sides:

| File | M1.8 (main) | M1.9 (m19) | Resolution |
|---|---|---|---|
| `src/l4/init/init.py` | `ciedit`/`ecosystem` imports; `InitPlan.notes`; `plan_init` builds the memory, CI-edit and gate-proposal notes; `run_init` prints the notes and the `next: … doctor --adoption` line | `pytest_marker` import; `InitPlan.marker`; `plan_init` registers the marker when the test gate runs pytest; `run_init` prints the marker message | all imports; `InitPlan` gains `notes` then `marker` (the constructor passes both positionally, in that order); `plan_init` computes both; `run_init` prints the notes, then the marker message, then the `next:` line |
| `tests/unit/config/test_schema.py` | three `extra_*` key tests | `test_redact_forge_urls_defaults_on` | both blocks |
| `tests/unit/init/test_init_cli.py` | five CI-include / next-command tests | `test_init_registers_the_l4_marker` | both blocks |

The auto-merged files were read for interference: `archive.py` keeps M1.8's MR title fallback
(`proposal_title(path, name)`) beside M1.9's draft flip, `ForgeUrls` comparison and new hand-off rule;
`orchestrator.py` keeps the capacity note and `exit_reason` beside the review re-entry (`_review`, `_review_noted`);
`ladder.py` keeps `has_system_one_profile` beside `test_conventions`; `schema.py` has the `extra_*` keys and
`redact_forge_urls`. `tasks.md` has no duplicate task ids, M1.8's ticks (1.19, 1.22, 2.19) and M1.9's (2.2, 2.41,
2.44) are all `[x]`. The merge commit's message carries no `# Conflicts:` lines.

Template lock: the judge (version 3 → 4) and the two `testwriter/*` entries come from m19; main changed no pinned
prompt (its CI template body is not in the lock). `templatelock.problems()` is empty at the merge, so no
`--write` was needed.

**Suite** (chunked and sequential at `3da5fce`; collected = passed + skipped + xfailed in every chunk, no failures,
no XPASS)

| Chunk | Result |
|---|---|
| unit agents, availability, llm | 476 passed, 5 skipped (481) |
| unit verifier, implementer, gates | 1109 passed, 3 skipped, 1 xfailed (1113) |
| unit orchestrator, archive, state, vcs, specs | 578 passed, 2 skipped, 1 xfailed (581) |
| every other unit dir and `tests/unit/test_*.py` | 1817 passed, 5 skipped (1822) |
| contract, scenarios, integration, live | 59 passed, 63 skipped (122) |
| **total** | **4039 passed, 78 skipped, 2 xfailed, 0 failed (4119)** |

The two strict xfails are `test_ladder_evidence_gaming.py::test_residual_a_forgery_that_never_names_the_plugin_still_passes`
and m19's `tests/unit/state/test_review.py::test_residual_an_amended_handoff_commit_is_not_seen_as_a_persons_change`.
The machine was loaded (load average 12 to 15 from other work), so chunk 2 took 22 minutes; nothing failed.
`ruff check .` is clean and `check_spec.py` exits 0. `l4 simulate --all --json` twice: 5 pass, 0 fail, 16 pending,
byte-identical (sha256 `d9eecc77…`). happy-openspec is now `d8798f00…` and happy-kiro `64dfbfab…`; they moved from
the M1.8 values (`78678f73…`, `494f3a53…`), presumably because m19 changes what a run records (`run.started.iteration`
is the run's own count, `pr.ready` carries the head); which event moved each hash was not traced [I].

Follow-up, not a merge defect: `init`'s closing line still says "then commit .l4/, .gitignore and the CI file", while
M1.9's marker registration may also write `pyproject.toml`, a `pytest.ini`-family file or `conftest.py` (the marker
message names the file).

### 2026-10-06: M1.10 (polish) into `main` (merge `20f03a4`, from `93e1381`, onto `8e1c562`)

`m110` was 33 commits ahead of main and main had not moved, so the merge was clean: no conflicts, and the merge
message carries no `# Conflicts:` lines. The tree was clean before the merge. The review fixes are in: C1 `cfa88b0`
(a shell given a command string is refused), C2 `13bda39` (`fails_at_red` fails closed) and `f5a9071` (an accepted
answer unfreezes only a test the question names); C3 and C8 passed as built.

Template lock: `templatelock --write` left no diff. `ruff check .` is clean and `check_spec.py` exits 0.

**Suite** (chunked; collected = passed + skipped + xfailed in every chunk, no failures, no XPASS)

| Chunk | Result |
|---|---|
| unit agents, availability, llm | 476 passed, 5 skipped |
| unit verifier, implementer, gates | 1153 passed, 3 skipped, 1 xfailed |
| unit orchestrator, archive, state, vcs, specs | 582 passed, 2 skipped, 1 xfailed |
| every other unit dir and `tests/unit/test_*.py` | 1859 passed, 5 skipped |
| contract, scenarios, integration, live | 59 passed, 63 skipped |
| **total** | **4129 passed, 78 skipped, 2 xfailed, 0 failed (4209)** |

`l4 simulate --all --json` twice: 5 pass, 0 fail, 16 pending, byte-identical (sha256 `00acc349…`).

### 2026-10-06: strict-author (review re-entry reads the committer) into `main` (merge `7624717`, from `c800b00`, onto `c16871c`)

Maintainer decision 2026-10-06: for the review re-entry (G1, L4-ARC-008 (d)) a commit is the harness's only when its
author **and** its committer are the bot identity **and** it carries an `L4-Run` trailer, so an amended, rebased or
cherry-picked H, or a bot commit after H that a person rebased, re-enters review. `is_harness_strict` reads it in
`after_handoff` and `handoff_commit` (and so in the archive's "is HEAD this unit's H" check). Per-commit attribution of a
change (G3: protected paths, skip markers and test deletions, scope, provenance, preconditions) keeps the author-only
`is_harness`, so a person who rebases an agent's commit cannot make its forbidden-path change read as a human's. m19's
strict xfail `test_residual_an_amended_handoff_commit_is_not_seen_as_a_persons_change` is closed: it is now
`test_an_amended_handoff_commit_is_seen_as_a_persons_change` and passes.

Main moved by one docs commit (`c16871c`, `docs/adoption/`) after the branch was cut from `4836fd4`; the merge was clean,
with no `# Conflicts:` lines. The tree was clean before the merge.

Review before the merge (mutations run on the branch, each restored):

* Committer check removed from `is_harness_strict`: the amend and the rebased-commit tests fail.
* `handoff_commit` back to the author rule: the amend test fails. `after_handoff` back to the author rule: the
  rebased-commit test fails.
* Protected-path attribution (`protected_changes_by_human`) switched to the strict rule: the laundering test fails
  (the cherry-picked agent CI edit is listed as a human's instead of a blocker).
* The other four G3 callers (`integrity._by_people`, `evidence/collect`, `provenance`, `preconditions`) switched to
  the strict rule together: 150 of their tests still pass. They are correct as built (author rule, unchanged by this
  branch), but no test pins it there; a follow-up could add a rebased-agent-commit case for each.
* Fixes made in review: `c800b00` states the strict rule in the SPEC's M1 review rows (§12, which still said "author =
  the bot identity") and in the forge-and-ci L4-ARC-008 (d) delta. The style commit was re-authored (`681dd0f` →
  `ea790d8`): the repository's `.git/config` had `user.name = user.email` (written 12:37:28 today, during the branch's
  first commit), so that commit read `user.email <maintainer@example.invalid>`. The config is `CiprianSpot` again. `c16871c`, made by
  another session meanwhile, is on main with the same wrong author name and was left as is.
* Not fixed (pre-existing presentation): `review_note` lists a foreign commit by its author, so a rebased bot commit
  after H shows as `(l4-bot)` under "were not made by the harness". An amended second H (H2) is found as foreign after
  the older H1 rather than as a lost H; it re-enters either way, but the spec-edit check then spans H1..head.

**Suite** (chunked and sequential at `7624717`; collected = passed + skipped + xfailed in every chunk, no failures,
no XPASS)

| Chunk | Result |
|---|---|
| unit agents, availability, llm | 476 passed, 5 skipped (481) |
| unit verifier, implementer, gates | 1154 passed, 3 skipped, 1 xfailed (1158) |
| unit orchestrator, archive, state, vcs, specs | 585 passed, 2 skipped (587) |
| every other unit dir and `tests/unit/test_*.py` | 1859 passed, 5 skipped (1864) |
| contract, scenarios, integration, live | 59 passed, 63 skipped (122) |
| **total** | **4133 passed, 78 skipped, 1 xfailed, 0 failed (4212)** |

Against M1.10: three new tests (rebased commit after H, forge squash commit, G3 laundering) and the m19 xfail now
passes (4129 + 3 + 1 passed, 2 → 1 xfailed). The remaining strict xfail is
`test_ladder_evidence_gaming.py::test_residual_a_forgery_that_never_names_the_plugin_still_passes`. The machine was
heavily loaded (load average up to ~400 from other work), so chunk 2 took 35 minutes; nothing failed. `ruff check .`
is clean and `check_spec.py` exits 0.

### 2026-10-07: m111 (M1.11 sample-consumer wave A) into `main` (merge `75e82d4`, from `28b8cc3`)

`m111` was built in `../l4-wt/m111` and reviewed and live-checked there (live-fix `28b8cc3`). `main` had gained only
docs commits (live evidence, adoption) since, so the merge was clean (no conflicts). It was merged with `--no-ff`, no
trailers, author `CiprianSpot`. The template lock was unchanged (`l4.templatelock --write` produced no diff). Nothing
was pushed.

**Suite** (chunked, collected = passed + skipped + xfailed in every chunk, no failures or errors):

| Chunk | Result |
|---|---|
| unit agents, availability, llm | 484 passed, 5 skipped |
| unit verifier, implementer, gates | 1256 passed, 3 skipped, 1 xfailed |
| unit orchestrator, archive, state, vcs, specs | 594 passed, 2 skipped |
| every other unit dir and `tests/unit/test_*.py` | 1892 passed, 5 skipped |
| contract, scenarios, integration, live | 59 passed, 63 skipped |
| **total** | **4285 passed, 78 skipped, 1 xfailed, 0 failed** |

`check_spec.py` exits 0. `l4 simulate --all --json` (stdout) was run twice: byte-identical. The machine was heavily
loaded (load average ~550 from other sessions), so chunk 2 took 38 minutes; nothing hung. `ruff check .` reports 6
findings, all in `docs/live/free/tools/*.py` (added by a separate docs commit, not by this merge); `src` and `tests`
are clean.

### 2026-10-07: mag (custom OpenAI-compatible provider for the opencode adapter) into `main` (merge `15e26a0`, from `92bb012`)

Why: the maintainer's MacBook serves `qwen3.6-35b-a3b:gguf:q5` over an OpenAI-compatible API (magnitude); the plan quota
is nearly spent, so a free local profile is worth having as an optional, availability-probed role member. Adds
`options.provider {id, base_url, api_key_env, models{<id>: {context, output}}}`, `options.tools`, `options.reasoning` to
an opencode profile (checked at load, value-free errors), the provider block in the isolated OpenCode config,
a restricted implement tool set (the server compiles tool schemas into a decoding grammar: 82 tools took minutes and
sometimes drew HTTP 400 `grammar binding failed`), none for judges, `reasoning_effort: none`, an unauthenticated
`GET <base_url>/models` reachability step in the hello probe (a silent laptop is unavailable, so the chain falls back),
`provider_unavailable ... retryable` error detail, and a doctor `PRV-001` note `<profile> provider <host:port>
reachable|unreachable`. SPEC §3.2 example profile `opencode-mag` and a §8.3 paragraph.

**Deviation from the task text, on purpose:** the key does NOT go in `OPENCODE_CONFIG_CONTENT` as `{env:VAR}` and the
sandbox env is NOT widened. `--setenv NAME VALUE` lands in bwrap's argv (world-readable in `/proc/<pid>/cmdline`; the
reason `l4.sandbox.env` passes no credential), and `OPENCODE_CONFIG_CONTENT` is an env value too. The harness reads
`api_key_env` from its own environment (`RunRequest.host_env`, set in `agent_step` and the judge request factory;
`build_agent_env` is unchanged), writes it to a new 0600 file `opencode-config/provider.key` in the step's private
directory, and the config says `apiKey: "{file:<path>}"` [V live, hello through the provider, 32.8 s]. The file is
removed in a `finally`. The redactor already covers it (`_env_names` recurses into `options.provider.api_key_env`; pinned
by a test). Residual: the agent itself can read that file during its step, as it can read any credential it is given.

Not verified: egress to the provider from inside bwrap (the runner reaches it, bwrap shares the net for agents);
an implement run end to end through the harness on the runner (the hello probe and the config were exercised, the
6-tool implement shape only in the investigation); `reasoning: high` with a larger `limit.output`.

**Suite** (at `0d6cf84`, main merged in; the later main commits are docs only; chunked, no `-x`)

| Chunk | Result |
|---|---|
| unit verifier | 730 passed, 3 skipped, 1 xfailed |
| unit implementer, s1, specs | 675 passed, 2 skipped |
| unit forge, doctor, orchestrator, availability, state, clarifier, agents, archive | 1322 passed, 3 skipped, 1 failed (`test_proc::test_interrupt_sends_sigint_then_the_run_ends`: SIGINT grace timing under four parallel chunks; passes alone, 11 of 11) |
| unit ci, cli, config, evidence, gates, init, live_support, llm, memory | 866 passed, 7 skipped |
| unit obs, planner, provision, runner, sandbox, security, setup, sim, vcs, `tests/unit/test_*.py`, contract, scenarios, integration, live | 733 passed, 63 skipped |
| **total** | **4327 passed (the flaky one counted from its solo run), 78 skipped, 1 xfailed, 0 failed** |

`ruff check src tests` clean; `check_spec.py` exits 0. The tree of `main` had no local changes at merge time (the
earlier dirty `docs/live` files were committed by another session meanwhile); main had moved twice (docs and the M1.11
merge), merged into the branch before landing.

## M1.12 merge (branch `m112`, merge commit `528a63e` onto `8bdaf11`)

The sample-consumer wave B findings K1-K4 and the MF-7 findings F1-F2: failed-hello classes with a shorter cache
for an auth refusal and one re-probe of it, the audit test linted in step 4a, the Codex socket limit named in the
contract, `CI_ALLOWED` and the designed-stop line, the owner's reject first in a fix task, a suggested edit that
unfreezes one test. The adversarial review added three fixes, each test first: a re-probe wrote an entry that the next
select re-probed again (a probe per select); a lint-rejected audit test held a criterion that its own tests support
(it is a minor finding like any rejected audit test); two long rejects on one task were cut at the proposal. Line 20
(the stale-include check) was not built: the adopted include was not available.

| Chunk | Result |
|---|---|
| unit agents, availability, llm | 551 passed, 5 skipped (one `test_proc` interrupt timing failure under parallel load on the first pass; passes alone and in the re-run of the chunk) |
| unit verifier, implementer, gates | 1282 passed, 3 skipped, 1 xfailed |
| unit orchestrator, archive, state, vcs, specs | 595 passed, 2 skipped |
| unit, every other directory and `tests/unit/test_*.py` | 1928 passed, 5 skipped |
| contract, scenarios, integration, live | 59 passed, 63 skipped |

`ruff check .` clean; `check_spec.py docs/SPEC.md` exits 0; `l4 simulate --all --json` twice, byte-identical;
`templatelock --write` leaves no diff.

## M1.13 merge (branch `m113`, merge commit `41d9a38` onto `5aa112b`)

The magnitude result path (a `.l4-result/result.json` alias for prompt-contract adapters, read only from the private
directory) and the sample-consumer wave C findings: W-C1 (a test-only finding on a satisfied criterion is a tests
task that must add a discriminating test), W-C2 (an escalated unit resumes with `--extend-fix-rounds` or one round per
`l4:resume` label event), W-C3 (a blocked green step's question says how a frozen test is unfrozen), W-C4 (audit writer
rules v4), W-C6 (a lasting proxy 502 is "unknown", not "busy"). The adversarial review added one fix, test first
(`0d0a3e8`): a read-only directory an agent left under the alias made `drop` raise inside the `finally` of the agent
step, which skipped `revert_protected`, so a file written at a protected path stayed in the worktree for the next commit;
`drop` now makes the directory writable and retries, and the rest of the cleanup runs even when it still fails. Checked
and found sound: an alias committed with `git add -f` does not reach the branch; a result at `agent-tmp/result.json` is
not read; a tests chore changing a non-test file fails the attempt; a resume of an escalated unit is one round per label
event, member-checked, and only the fix-round budget changes. Known limits: the title match for a test-only finding is a
word match on a judge's or human's title (a wrongly matched code finding cannot change code, so it ends in a failed
chore, not in a skipped TDD); `fix_rounds_exhausted` reads the fold's round, `decide_fix` also counts the units on disk.

| Chunk | Result |
|---|---|
| unit agents, availability, llm | 553 passed, 5 skipped (`test_proc` interrupt timing failure under load on the first pass; 11 of 11 pass alone) |
| unit verifier, implementer, gates | 1344 passed, 3 skipped, 1 xfailed |
| unit orchestrator, archive, state, vcs, specs | 600 passed, 2 skipped |
| unit, every other directory and `tests/unit/test_*.py` | 1947 passed, 5 skipped |
| contract, scenarios, integration, live | 59 passed, 63 skipped |
| **total** | **4503 passed (the flaky one from its solo run), 78 skipped, 1 xfailed, 0 failed** (4582 collected) |

`ruff check .` clean; `check_spec.py docs/SPEC.md` exits 0; `l4 simulate --all --json` twice, byte-identical (sha256
`e73c2afb...`); `templatelock --write` leaves no diff.

## M1.14 merge (branch `ollama-s1`, merge commit `3c7e39e` onto `cc03f62`)

The S1 engine `ollama`: Ollama's System One API (`POST /v1/systemone`, Ollama 0.40.0 on the maintainer's Mac,
reachable from l4-runner at `http://192.0.2.10:11434`), keyless. Profile `{backend: system-one, engine: ollama,
model: tev1, base_url: http://192.0.2.10:11434}`: `base_url` is required and a bare http(s) origin, `api_key_env` is
refused, both at config load (`Profile`). The usable-probe is `GET /api/version` (>= 0.35.0) and `GET /api/tags` listing
the model (`tev1` matches `tev1:latest`); a model that is not pulled gives the `ollama pull <model>` remedy, a down or
sleeping Mac is `unavailable` and `open_s1_backend` falls to the next S1 profile. Wire: choice criteria as an object,
score criteria as an array (the live server answers 400 `score criteria must be an array of descriptions` to the Jev
object), noul/choice/score answers parse through the Jev types unchanged (`legend` and `prompt_eval_cached_count` are
ignored). Calibration rows carry `engine: ollama`, the served model as the host lists it (`tev1:latest`, not the alias
`tev1` the reply echoes) and `server_version: ollama 0.40.0`. State budget: `verifier.s1.max_state_tokens` (like Jev;
Tev1's window is 2048 tokens). Doctor `ENV-013` (warn). SPEC §3.2, L4-FAC-004, §10.2 step 8, §10.8, the doctor table.

Adversarial finding that changed the design (measured live on 0.40.0, `/tmp` probes, 2026-10-07): the 64 KiB limit is
not on the raw body. The server answers 413 `text and schema must not exceed 64 KiB` for a body of 65 521 bytes, and the
counted size is the body's UTF-8 bytes plus 16 for every `noul` question without `criteria` (its default descriptions),
plus nothing for choice, score or given criteria. A check `len(body) <= 65536` would have let 413s through. The engine
counts the exact bytes it sends and refuses at body + 64 + 32 per question over 64 KiB with `unavailable: input too
large` (`SystemOneTooLarge`, a `SystemOneBadAnswer`: that question only, the engine stays up); the test sweeps the whole
edge for three question shapes and three glyph widths against a fake that models the measured rule, and no request is
answered 413. Second finding: on this `tev1` runner a prompt over 2048 tokens is HTTP 400 `prompt N tokens; expected
1-2048 (input is never truncated)`; that 400 maps to the same per-question error, any other 400 is a plain unavailable
that does not echo the body. Nothing is cut silently by the engine (the existing state budget still trims callers' states
first). No key is read, sent or logged (`ValueError` if one is passed; the redactor still runs on the state before the
size count and the log).

Known limits: the margin refuses up to about 200 bytes early; the 2048-token window is read from one error message and is
not probed (a `max_state_tokens` above it yields per-question refusals, not a cut); the traffic is plain HTTP on the LAN.

| Chunk | Result |
|---|---|
| unit agents, availability, llm, config, doctor, s1, clarifier | 1138 passed, 10 skipped (`test_proc` interrupt timing failed once under the load of four parallel chunks; 11 of 11 pass alone, as at M1.13) |
| unit verifier, implementer, gates | 1344 passed, 3 skipped, 1 xfailed |
| unit orchestrator, archive, state, vcs, specs | 600 passed, 2 skipped |
| unit, every other directory and `tests/unit/test_*.py`, contract, scenarios, integration, live | 1463 passed, 65 skipped |
| after the merge onto `cc03f62` (canary change, disjoint files): s1, llm, doctor, config | 474 passed, 8 skipped |
| live (`L4_LIVE=1`, the real Mac) | 2 passed |

`ruff check .` clean; `check_spec.py docs/SPEC.md` exits 0.

## kiro-e2e merge (branch `kiro-e2e`, merge commit `999d991` onto `7354176`, from `a7083db`)

Step 0 of `docs/plan/kiro-e2e.md`: K1 (the login check reads the flat `whoami --format json` answer of kiro-cli 2.27.1 and
2.28.0: logged in is exit 0 and a non-empty `accountType`; the e-mail is never kept), K2 (`~/.local/share/kiro-cli` and
`~/Library/Application Support/kiro-cli` are Kiro credential paths: mounted for Kiro, hidden from every other adapter and
gate), K4 (the judge trust list is `read`; the empty list trusted every tool), K7 (stream-json parsing, `/usage` quota,
a credits `runError` as a credits limit), K17 (SPEC rows), and `prereqs.sh` with a kiro-cli floor of 2.28.0. `main` had
not moved since the branch was cut, so the merge was clean (`--no-ff`, no `# Conflicts:` lines).

The tree of `main` was **not** clean at merge time: another workflow had `docs/free-resources.md` and
`docs/s1/README.md` modified and four untracked `docs/s1/*-2026-10-07-tev1.*` files. The merge touches none of those
paths (its 21 files are under `src/`, `tests/`, `scripts/runner/` and `docs/SPEC.md`), so git merged without touching
them; they were neither stashed nor committed and stay that workflow's.

| Check | Result |
|---|---|
| unit agents, availability, sandbox, runner, config (on the branch, before the merge) | 699 passed |
| full suite at `999d991` (`pytest -x --ignore=tests/live`, one run in the background) | 4565 passed, 19 skipped, 1 xfailed (79 min) |

`ruff check src tests` clean; `check_spec.py docs/SPEC.md` exits 0.

Live-fix on `main` after the merge (H1, `docs/live/kiro-e2e/README.md`): `15e7788` red and `3221a94` green, K3 for the
implementer: a step without `options.agent` runs `--agent l4-implement-<random> --trust-all-tools` with `KIRO_HOME` set
to a directory in the step's private directory that holds only that agent (tools `read, write, shell, glob, grep`, no
MCP server, no resources). Unit agents, availability, sandbox, implementer: 1012 passed; `l4 simulate happy-kiro` PASS.
Second live-fix: `75d7cc6` red and `1138eae` green, the red template (red@7) says that constants named by the design
or a steering file are green work; the template lock regenerated; the template-version, red-step, eval and lock
tests: 362 passed. Not checked with `l4 eval --compare`.
Full suite at `8e58e09` (both live-fixes and the M1.14 eval merge of another workflow; `--ignore=tests/live`): 4863
passed, 19 skipped, 1 xfailed, 2 failed: `test_check_criteria.py::test_contract_5_and_red_3_…[red|green]` still
pinned the red template at version 6. Fixed in `663428b` (the pin is 7); that file alone then: 8 passed. No other
source changed after `8e58e09`.

## M1.14 eval merge (branch `m114`, merge commit `a84a873` onto `11c40b5`)

`l4 eval` (SPEC §20.1, L4-EVAL-001..027, `docs/eval.md`): a seed set of 4 units in `tests/eval/seeds/` (one with a
designed defect), implementer cells (one profile writes red and green through the real `l4 run`, local forge, then a
fixed reference judge) and judge cells (a replayed reference implementation, then one judge), the canonical scorecard
`l4/eval-scorecard@1` with its environment record, `--resume`, `--warm-cache`, `--idle-check`, and the gate
`l4 eval --compare` (exit 15 `REGRESSION`). With it the M1 prompt-contract hint: the allowed result values next to the
phase line, the phase names read from the schema, enum errors that list them (magnitude-qwen's `status: red`).

Adversarial review before the merge (`docs/plan/m114-progress.md`): the blocker was that every live cell would have
exited 2 at `l4 run`'s preflight (shared uv cache outside the cell's `L4_CACHE`) and scored `fail` (`8c5307e`); five
more fixes (`d9e8a60` harness exits are `invalid`, `087a7dc` a gate cannot pass on missing data, `9364b74` resume,
`fef054d` `--max-drop` range and `.DS_Store`, `153ba67` phase names from the schema). Closed before the merge, each test
first: a cell keeps the `availability` section of `--config` (`c3091b8`: magnitude-qwen's 75 s hello needs the
project's `probe_timeout`, or every cell of it is `invalid`); the environment records the uv and OpenSpec versions and
the kept sections, and `--new` alone is exit 2 (`4df7489`); a cell whose model under test never ran is `invalid`
(`baseline_failed`, `halted_before_agent`, `judge_not_reached`), not a failure of the profile (`354e165`); baselines
live under `docs/eval/` (doctor EVAL-001, SPEC, eval.md) and `scripts/runner/eval-quiet.sh` is the runner-side idle
check (`fdb8704`). The one conflict, `tests/unit/doctor/test_doctor_cli.py` (ENV-013 of the ollama merge, EVAL-001
here), was resolved in `8ca4a18` by listing both.

Checks on the merge tree (`a84a873`, the same tree as `m114`'s head `fdb8704`), five chunks, collected = passed +
skipped + xfailed in each:

| Chunk | Collected | Passed | Skipped | xfailed |
|---|---|---|---|---|
| unit agents, availability, llm | 620 | 613 | 7 | 0 |
| unit verifier, implementer, gates | 1373 | 1369 | 3 | 1 |
| unit orchestrator, archive, state, vcs, specs | 602 | 600 | 2 | 0 |
| every other `tests/unit` directory and `tests/unit/test_*.py` | 2227 | 2222 | 5 | 0 |
| contract, scenarios, integration, live (`L4_LIVE` unset) | 123 | 60 | 63 | 0 |
| total | 4945 | 4864 | 80 | 1 |

`ruff check .` clean; `check_spec.py docs/SPEC.md` exits 0 (177 requirements, 340 scenarios, none uncovered);
`l4.templatelock --write` leaves no diff; `l4 simulate --all --json` twice: `5 pass, 0 fail, 16 pending`,
byte-identical (sha256 `44d48b0e…`). The machine was shared with two other workflows (load average 15 to 21).

After the merge, on `main`: the kiro workflow's red@7 (`1138eae`, `663428b`) and `0f2e84d` (a `harness_error` from a
failed setup gate names the setup log's last line: the first live smoke on the runner showed only "see <path>" of a
workspace the eval had already deleted; eval unit tests 233 passed). The live baseline is in `docs/eval/`.

Second live-fix on `main` after the merge: `f0c703c` (cherry-picked from `09d82cd`, test first). The first real eval
cell (2026-10-08 01:50Z, reference judge claude-code) found the runner's Claude login gone: f-muse had written red and
green, the judge failed its auth probe, and the cell was scored `endpoint_unavailable`, which blocked f-muse for the
whole run. Now an exit 12 whose unavailable role is the cell's reference (the fixed judge, or the replay of a judge
cell) is `reference_unavailable` and skips the remaining cells of that role, never blocking the profile under test; a
measured profile skipped only at its auth step is `login`. Eval, integration and compare-CLI tests on `main` at
`0de761f`: 252 passed. `ruff check .` on `main` is red only from `docs/live/kiro-e2e/h1/C/i001-repro/*.py` (committed
by the kiro workflow after this merge). The first baseline: [../eval/README.md](../eval/README.md).

## cred-lock merge (branch `cred-lock`, merge commit `0de761f` onto `3ced077`, from `339a7b9`)

The runner's Claude login for gitlab-runner was wiped at 2026-10-07 21:33:12 (`.credentials.json` rewritten with an
empty refresh token and `expiresAt: 0`), 3 s after CI l4 job 6045 started, while out-of-CI runs as gitlab-runner (the
free-model measurement, the M1.14 `l4 eval` with claude-code as the fixed judge) shared `~/.claude`. Two processes
refreshing one expired token with the same single-use refresh token make the loser clear the store [I]. The existing
per-login gate had three gaps, all confirmed: the probe ladder (login check, quota, hello), `doctor` readiness and
`doctor --live` spawned the CLI without it; a subscription login could have `max_concurrency` > 1; the lock files lived
under `$L4_CACHE/locks`, so processes with another cache locked other files.

Branch (`a341ddf`..`43643c5`, each test first): exactly one slot for claude-code, codex and kiro-cli unless
`auth: api_key` (opencode only with `auth: subscription`); the key is the resolved credential directory; the locks live in
`~/.cache/l4/locks` of the OS user (0700/0600, symlinks refused, `$L4_LOCK_DIR` for tests); held around the whole probe
ladder, the readiness probe (`Factory.holding_login`, new state `login-busy`) and each adapter run (`GatedAdapter`);
bounded wait `availability.login_lock_wait` (20m), printed and ledgered (`availability.login_wait`); a busy login is
`rate_limited` with a 2-minute reset so the chain falls back; a nested acquire in one thread raises `GateNested`;
`close_fds=True` in every spawn helper; doctor ENV-014 warns on a wiped stored login. A static test classifies every
module that spawns a process.

Adversarial review before the merge (re-derived the spawn sites from `src/l4`; same table as the branch report, plus
`verifier/ladder.py:1079`, which builds an ungated adapter on the resume path but never runs it: `_NoJudge()`,
`next_judge=None`). One defect fixed, test first (`fa97486` red, `339a7b9`): the key followed `$CLAUDE_CONFIG_DIR` /
`$CODEX_HOME` of the host environment, but every spawn environment is built from HOME (`probe_env`, `build_agent_env`)
and never carries them, so a process with one set and a process without locked different files while driving the same
`$HOME/.claude`; reproduced red by two real `l4 probe` processes (different `L4_CACHE`, XDG dirs, TMPDIR, one with
`CLAUDE_CONFIG_DIR`) on a fake `claude`, green after keying on HOME only. Also verified: the same two processes without
`$L4_LOCK_DIR` (the default `~/.cache/l4/locks`) serialise and the waiter prints `[l4] login: waited 2s …` (one-off run,
lock file removed); a SIGKILLed holder frees the login at once and a detached child in its own session keeps nothing
(new test); the agent sandbox still binds the adapter's credential paths read-write (`bwrap.py` `--bind`), so a refresh
inside a run is saved; the lock directory is under the read-only root in every sandbox and no default cache, worktree or
tmp bind is at or above it (an agent can still `flock` a lock file opened read-only: blocks others for its own run,
corrupts nothing); no `on_line` callback or thread nests a second acquire. ENV-014's hints and the runner README use
`sudo -iu gitlab-runner` (claude: run `claude`, type `/login`). SPEC L4-FAC-008 now says the key ignores those variables
and states the residual [I]: a killed `l4` frees its lock at once while an unsandboxed probe CLI it started (own session)
can outlive it by up to the probe timeout; sandboxed runs die with it (`--die-with-parent`). The lock serialises only
processes that run a harness with it: consumer repositories (and the free-model driver's `.l4/bin/l4`) need
`l4 upgrade`. Not gated: hand-run CLIs and `scripts/runner/*.sh`.

After the merge, on `main`: `6955485` (the subprocess tests wait up to 2 to 5 minutes for their children; the machine
was at load average 300 during the suite; the test file then passed alone, 22 tests).

Checks on `main` (the merge tree plus the other workflows' concurrent docs and ruff-exclude commits `b4ef7d0`,
`2736236`, `8fb471c`; none touches `src` or `tests`), five chunks, collected = passed + skipped + xfailed in each:

| Chunk | Collected | Passed | Skipped | xfailed |
|---|---|---|---|---|
| unit agents, availability, llm | 655 | 648 | 7 | 0 |
| unit verifier, implementer, gates | 1382 | 1378 | 3 | 1 |
| unit orchestrator, archive, state, vcs, specs | 602 | 600 | 2 | 0 |
| every other `tests/unit` directory and `tests/unit/test_*.py` | 2242 | 2237 | 5 | 0 |
| contract, scenarios, integration, live (`L4_LIVE` unset) | 123 | 60 | 63 | 0 |
| total | 5004 | 4923 | 80 | 1 |

`ruff check .` clean (after `8fb471c` excluded `docs/live`; before it, the only errors were the pre-existing
`docs/live/kiro-e2e/h1/C/i001-repro/*.py` and the then-untracked `docs/eval/tools/debug-cell.py`, none from this
branch); `check_spec.py docs/SPEC.md` exits 0 (177 requirements, 341 scenarios, none uncovered).

## kiro-fu merge (branch `kiro-fu`, merge commit `6b5e17e` onto `8a0482d`, from `baf0820`)

The four open findings of the Kiro end-to-end validation ([../live/kiro-e2e/README.md](../live/kiro-e2e/README.md):
the H1 re-run and H2 caveats 3, 6 and 7), each test first:

* **KF1** (`c4c4840`): the merge detector asks for `.kiro/specs/<name>` for a Kiro unit, and the sweep runs the Kiro
  done-gate (every required leaf `[x]`) on the base head of a merged Kiro unit. A pass records
  `archive.done{via: done_gate, base}` once, with no archive branch, no MR and no phase change. A refusal records
  `archive.failed` once and writes one note on the MR naming the open leaves; it runs again only when the unit's
  folder tree changes. SPEC L4-KSP-004, SCN-ARC-22.
* **KF2** (`76deff1`, `f7e7206`): a `runError` that says the request was throttled is `rate_limited` with a
  `rate_limit` signal. The profile cools for the message's own retry hint, else 2 minutes, and the next implementer
  takes the step from its last checkpoint. No attempt is consumed. A throttled hello probe is the same limit.
* **KF3** (`1ebb345`): the pre-satisfied zero-value run no longer corrupts a file reached by two names. Imports resolve
  only in exact case (`from pricing import Cart` named `Cart.py` on APFS), and each file is varied once, identified by
  device and inode. A red step with no new test id now says `no new test: …` instead of the false `tests not collected
  individually` (red@8, template lock regenerated).
* **KF4** (`075f72f`): the stream's metered credits are `budget.cost{credits, credits_source: "kiro.stream"}`. The
  `/usage` reading is on `availability.selected.probes.<profile>` (`credits_used`, `credits_included`,
  `credits_source: "kiro.usage"`). Neither is added to `usd` or to the unit's cost.

**Deviation from the brief: the Kiro lock ref is kept, not retired** [V code]. A Kiro unit's folder stays on the base,
so the unit stays listed. `load_snapshot` folds the folder's own ledger, which ends at `in_review`, together with the
lock ref's pending ledger, which holds `merged`. Retired to `refs/l4/archived/`, the unit would read `in_review` with
a merged MR, and the next sweep would merge it again onto a new lock ref (a test pins this). Retiring it needs
`load_snapshot` to read the archived ref first. The sweep never deletes the unit branch, which is the same for
OpenSpec: the forge's merge setting decides.

Adversarial review before the merge (`baf0820` added):

* KF3 re-derived on the recorded H1 state. The repro was a clone of the halted H1 worktree at `c239f8b` (after 2.1
  green), with the fake agent writing three new tagged tests, one of which also asserts a real answer. With the base
  harness `3ced077`, the zero run varied `src/pricing/Cart.py` **and** `src/pricing/cart.py`, left `cart.py` zeroed,
  and the outcome was `test code changed production files … (pre-satisfied confirmation)`. With `kiro-fu`, it varied
  `cart.py` once and restored it, and the outcome was `already_satisfied` [V]. The fix cannot let red be skipped for
  new behaviour [V code]:
  * the gate path is unchanged;
  * exact-case resolution and the inode check only drop second names of a file that is already varied;
  * a module the zero run misses makes the tests pass on the zero values, and that is rejected as `not
    discriminating`, so the change can only fail closed.
* KF2: a non-throttle `runError` is still `error` (test). The default cool-down is 2 minutes. A hint is honoured with
  no cap, the same as every other adapter's limit. `baf0820` tests KF2 end to end through `l4 run`. A throttled red
  step with `max_task_attempts: 1` falls back to the next profile, and the unit finishes:
  * no `task.attempt_failed` and no breaker;
  * the cool-down lasts until +2 minutes;
  * the fallback reason is `rate_limit`.

  With the old `error` status the same run halts (exit 13).
* KF1: a Kiro unit is recorded done only through `KiroProvider.done_gate` on the base head. The worktree `check_done`
  uses is cut from the base and removed afterwards, and it pushes nothing. The OpenSpec path is unchanged: the
  detector, `_inputs` and `_record` still use the change folder.
* Residual risks, not fixed here:
  1. Two profiles with short cool-downs can alternate within one run, because `Factory.on_limit` walks the chain again
     after each limit. This is pre-existing, and the 2-minute throttle cool-down makes it more likely. `factory.py`
     belongs to the login-lock workflow.
  2. Credits are recorded only for implementer steps (`agent_step`). A Kiro judge or verifier run records none.
  3. Re-tagging an existing test is still rejected rather than accepted as a pre-satisfied proof. The message now says
     why, and so does red@8.
  4. `ruff format` would reformat `src/l4/ci/sweeper.py` (one packed call with no `# fmt: skip`) and
     `tests/unit/archive/kiro_merged_world.py`. `ruff check` is clean.
* Not checked live: KF1, KF2, KF4. KF3 was checked on the recorded H1 state only.

Merge mechanics: `main`'s tree was clean. Two other workflows were landing on `main` at the same time. A first rehearsal
onto `6955485` (tree `03f1859`) passed the full suite: 5025 collected, 4944 passed, 80 skipped, 1 xfailed. A `git merge`
in `main`'s own tree followed, after `main` had moved to `8a0482d` (the weak-models merge). It stopped on the
`pyproject.toml` conflict at 11:51 and was aborted at 11:52:29. In that window, the weak-models workflow's chunked suite
started in `main`'s tree (11:52:22) and failed at once on the conflict markers (`TOML parse error`, exit 2, no test
ran). That workflow then moved its suite into its own worktree, and no result of it was contaminated. The merge was then
rehearsed again onto `8a0482d` in the `kiro-fu` worktree. `pyproject.toml` conflicted only on the same `docs/live`
exclude, and `main`'s line was kept. `templates.lock.json` merged cleanly (different entries). The suite below ran on
that commit, and `main` was fast-forwarded to it (`6b5e17e`, parents `8a0482d` and `baf0820`), so the tree on `main` is
the tested tree `56f0288`.

| Chunk (full suite on tree `56f0288`) | Collected | Passed | Skipped | xfailed | Failed | collected == p+s+x |
|---|---|---|---|---|---|---|
| 1 | 664 | 657 | 7 | 0 | 0 | yes |
| 2 | 1460 | 1456 | 3 | 1 | 0 | yes |
| 3 | 603 | 601 | 2 | 0 | 0 | yes |
| 4 | 2249 | 2244 | 5 | 0 | 0 | yes |
| 5 | 123 | 60 | 63 | 0 | 0 | yes |
| Total | 5099 | 5018 | 80 | 1 | 0 | yes |

Collected is pytest's own `collected N items` line of each sub-run (per directory, 8 at a time, load average 56 to 332
from the other workflows), and it equals passed + skipped + xfailed in every chunk. On `main` at `6b5e17e`: `uv run ruff
check .` reports all checks passed, and `python3 scripts/check_spec.py docs/SPEC.md` exits 0.

## weak-models merge (branch `weak-models`, merge commit `8a0482d` onto `789bae8`, from `53bb124`)

sample-consumer wave D (2026-10-08) ran its judge and its verifier agent on the free local magnitude-qwen, and
most needless `NEEDS_HUMAN` rounds came from two weak-model failures. W-D1: judge replies discarded for a trivial schema
break (an evidence quote over 300 characters, a `suggested_fix` that was a list), so no criterion got a verdict. W-D2:
audit tests that called module functions that do not exist, ran `python -m` on a module with no `__main__` guard,
forgot an import or could not be collected, each of which became a human question. The branch (`24edb70`, `ec86e2a`,
`dae471a`) adds `verifier/judge_repair.py`, a deterministic repair that never changes a criterion's id or verdict
and never guesses an enum or invents a field. `RunResult.rejected` carries the refused object out of the claude-code,
opencode and codex adapters so the repair reaches the real path. One bounded retry follows, with an 800-character error.
`verify.judge{reply}`, `judge.reply_repaired{fields}` and per-profile counts in `verification.md` and `verdict.json`
record the outcome. On the audit side, `testwriter/audit` v5 adds three static checks before any gate run. A test file
that cannot be collected goes back to the writer once and then becomes a `minor` finding, never a hold. A good audit
file that pytest never ran because of another file's collection error is run again. SPEC W-D1/W-D2 text, SCN-VER-52
and SCN-VER-53.

Adversarial review before the merge:

- **Repair safety.** Over 20 reply shapes were probed with `repair_reply` and `run_judge` and nothing was found. A
  `fail` with a 500-character quote stays `fail`. A missing, `null`, upper-case (`PASS`) or list verdict is left alone
  and goes to the retry. An unknown `verdict_override` key is dropped, never honoured. A non-dict criterion, an integer
  id, a dict-shaped `criteria`, a `null` evidence, a string `adequate`, a bad or `null` severity, a boolean
  `suggested_fix`, a list `counterexample.call` and two `riskiest_assumptions` are all left invalid. No path adds a
  criterion or a pass. A `fail` with no counterexample still aggregates to `needs_human` (`aggregate.py`).
- **Retry bound.** The retry is bounded by `MAX_CALLS = 2`. Two breaks are `discarded` (L4-VER-015).
- **Fixed in `53bb124`, each test first:**
  - Three ways to call a missing name passed the module-attribute check: `getattr(mod, "name")` (constant name, no
    default), `importlib.import_module("pkg.mod").name` and `mod = importlib.import_module(...)`. All three are now
    `invalid`.
  - False rejects of valid tests, removed:
    - a module that binds names at run time (`globals()`, `setattr(sys.modules[__name__], ...)`), which is now not
      checked;
    - a name a function declares `global`, or a top-level `for` or `with` target, which now counts as bound;
    - `from pkg import mod` of a shown package `__init__.py`, which may name an unshown submodule;
    - a name used only in annotations (`from __future__ import annotations`, a local `x: Path`), which is left to the
      collection retry;
    - `python -m` of a module that calls or raises at its top level (`raise SystemExit(main())`), or whose guard is
      compound (`if __name__ == "__main__" and ...`).
  - Each broken audit file now sees only its own pytest `ERROR collecting` section. Before, two broken files saw each
    other's errors.
  - The prompt text did not change, so the template stays at v5 and the lock has no diff.

Counter semantics, recorded here and left unchanged:

- The four outcomes are exclusive for each `verify.judge` event.
- A retry whose reply was then repaired counts as `retried`, and it still emits `judge.reply_repaired`.
- A schema break followed by a timeout or an error on the retry gets `reply: ""` and is not counted.
- A schema-valid reply that the ladder then drops for served-vendor independence keeps `valid` or `repaired` for the
  profile, while `run_judge`'s own model mismatch gets `""`.

Known limits:

- A judge on kiro-cli or the command adapter breaks through `attach_file_result` ("result invalid"), which classifies
  as an `error`, not `schema_invalid`, so it is not repaired. Neither adapter can serve the judge role today
  (`JUDGE_ADAPTERS`).
- The `python -m` and attribute checks only know the unit's changed files.
- A top-level call of any kind (`logging.basicConfig()`) satisfies the `-m` check.
- `__import__` and computed `import_module` names are not resolved.

Checks on the merge tree (`8a0482d`). The suite ran in the `weak-models` worktree detached at the merge commit,
because another workflow reset the shared `main` checkout at 11:52 while it was in use. Five chunks, collected =
passed + skipped + xfailed in each:

| Chunk | Collected | Passed | Skipped | xfailed |
|---|---|---|---|---|
| unit agents, availability, llm | 656 | 649 | 7 | 0 |
| unit verifier, implementer, gates | 1455 | 1451 | 3 | 1 |
| unit orchestrator, archive, state, vcs, specs | 602 | 600 | 2 | 0 |
| every other `tests/unit` directory and `tests/unit/test_*.py` | 2242 | 2237 | 5 | 0 |
| contract, scenarios, integration, live (`L4_LIVE` unset) | 123 | 60 | 63 | 0 |
| total | 5078 | 4997 | 80 | 1 |

Collected is from `--collect-only` on the same chunks.

`ruff check .` clean; `check_spec.py docs/SPEC.md` exits 0 (177 requirements, 343 scenarios, none uncovered);
`l4.templatelock --write` leaves no diff. The machine was shared with other workflows, with load averages up to 80
during chunk 2 (43 minutes). The kiro-fu merge (`6b5e17e`, onto `8a0482d`) and its log (`9bcfb9c`) landed on `main`
after this merge; their suite ran on a tree that includes this one.

## kiro-polish merge (branch `kiro-polish`, merge commit `44b9e65` onto `de1d801`, from `dc95fbe`)

Four findings of the Kiro H3 live re-check ([../live/kiro-e2e/README.md](../live/kiro-e2e/README.md), section H3),
each test first:

* **(d)** (`92ba694`, review fix `e3434c7`): Kiro acceptance criteria are read in the forms `1.`, `1)`, `1.1.`,
  `1.1)` and `1.1`, with or without a `-`/`*` bullet. The alias stays `Req N.M` by position and the id hashes the
  text, so the form moves neither. The ids of the H2 and H3 seed specs are pinned (`tests/fixtures/specs/kiro-seeds/`).
  SPEC-002 names the expected form when a task cites a requirement under which no criterion was read. SPEC L4-KSP-003,
  SCN-CRT-08.
* **(a)** (`2756977`): an already-satisfied task prints `task 2.2 already satisfied: 1 new test passes on the base, no
  green step`, and neither `red ok` nor `green ok`. `task.red_ok` carries `tdd: already-satisfied`. SCN-IMP-54.
* **(e)** (`dc6046c`): `step.finished{status}` is the agent's own `RunResult.status` (`rate_limited`, `quota`, `auth`,
  `error`, ...), and `error` when the step raised.
* **(b)** (`fcdddfd`, `5cf248d`, review fix `dc95fbe`): `availability.wait_in_run` (5m, `0` off) and
  `availability.wait_in_run_max_total` (15m). When a limit leaves every implementer of the chain cooling and the
  earliest cool-down ends within `wait_in_run`, the run prints `[l4] waiting Ns for <profile> (<kind>)`, sleeps,
  records `availability.wait_in_run{profile, waited_s, kind}` and selects again. The step goes on from its checkpoint
  and consumes no attempt. A 30-minute cool-down still exits 12. A YAML `wait_in_run: 0` (an int) means off. The bound
  by the job's remaining time is new code, because `run --time-budget` and L4-IMP-012 are still unimplemented:
  `ci.time_budget` minus `soft_deadline_margin` minus the time since `CI_JOB_STARTED_AT` (else the run's start), and
  `auto` reads GitLab's `CI_JOB_TIMEOUT`. SPEC L4-AVL-011, SCN-AVL-20.

Adversarial review before the merge (`e3434c7` and `dc95fbe` added):

* **(d) defect, fixed in `e3434c7`.** The branch moved ids and aliases of specs the old parser already read. A plain
  criterion with sub-numbered lines (`1. WHEN x THEN the system SHALL:` followed by indented `1.1 show a`, `1.2 show
  b`) was one criterion before (`C-85d93b03`). On the branch it became three, and a column-zero `1.5 note` line that
  the old parser ignored became a criterion too. Every later alias of that requirement shifted (`Req 1.3` became
  `Req 1.6`), which breaks `_Requirements:` links as well as frozen tests and ledgers. The requirement-number guard did
  not help, because sub-items carry the requirement's own number. Now the dotted form counts only in a requirement
  where no plain `N.`/`N)` item was read (two readings of the document). Every requirement that gave a criterion before
  gives the same criteria now, and only the requirements that read empty (the H3-A1 case) change. Two new tests pin
  the old parser's exact output, and the old parser (`main`'s `criteria.py`) was run as an oracle over every
  `requirements.md` in the repository plus both new fixtures. Every one was identical except the two dotted-only H3-A1
  copies, which it read as empty [V]. SPEC-002's hint now also fires per requirement (a cited requirement with no
  criterion read), not only when the document reads empty.
* **(b) gap, fixed in `dc95fbe`.** `run_units` built a fresh `Orchestrator` per unit, so the wait total and the run's
  start were per unit. Two throttled units of one `l4 run` could wait 2 x 15m, and without `CI_JOB_STARTED_AT` the
  second unit's job bound undercounted the elapsed time. A `RunWaits` is now created once in `run_units` and handed to
  every unit (`run_unit_in_worktree(waits=)`). Tests: both units get the same object, and a unit sees 120 s already
  waited and does not wait again under a 3m total.
* **(b) checked, no defect** [V code]:
  * The login lock is never held while sleeping. `GatedAdapter.run` releases its slot when the adapter returns, and
    `RoleLimit` is raised after that, in `agent_step`. The wait runs later, in `_fall_back`, then `switch_profile`,
    then `_wait_in_run`. The only `holding_login` user is the readiness probe, around a probe and not a sleep.
  * The loop is bounded: a non-positive wait raises, and every sleep adds at least 1 s to the run total, which
    `wait_in_run_max_total` caps.
  * A 429 with no reset cools for `default_cooldown` (30m), which is longer than `wait_in_run`, so the unit parks
    (test).
  * Scope: the wait covers implementer steps, both task steps and fix-loop steps (`ctx.shared["fall_back"]`). A judge
    or audit-writer limit goes through `next_judge`, which calls `Factory.on_limit` directly, and does not wait. The
    branch report said audit-writer limits also wait. They do not, and the brief only asks for implementers.
* **(e) checked, no defect** [V grep]. Nothing classifies on `step.finished.status`:
  * `progress.py` has no handler for it;
  * `eval/cellresult.py` reads `step.started` and `agent.finished`;
  * `state/reconcile.py` and the live acceptance test only pair `step.started` with `step.finished` by key;
  * `docs/live/free/tools/summarize.py` only prints the status;
  * `verification.md` does not read step events.
* **(a) checked, no defect.** `_done` returns `None` for `tdd: already-satisfied`, and `ProgressTrace.__call__`
  accepts that. `integrity.py` reads the commit's `L4-TDD`, not the new field.
* Residual risks, not fixed here:
  1. A login that stays busy for the whole `login_lock_wait` (20m) is a 120 s `gate.busy` cool-down, which the run now
     waits out. Each retry can then wait up to 20m for the lock again. The time-budget check runs before each sleep,
     not around the lock wait, so the job can overrun its soft deadline by up to one lock wait.
  2. A cool-down that is still live when a run starts (the first `for_role`) is not waited for. Only a limit hit
     during the run is.
  3. A dotted item whose first number is not its requirement's (`2.1.` under `Requirement 1`) is dropped silently.
     SPEC-002 only explains it when the cited requirement read no criterion at all.
  4. Kiro's documented criterion format was not fetched (the MCP servers were down for the implementer). The accepted
     forms come from the brief and the H2/H3 seeds. Kiro's own list form is `1.` [I].
  5. `availability.unavailable` is still recorded just before an `availability.wait_in_run`.
* Not checked live: all four. The H3 evidence is the baseline they fix.

Merge mechanics: `main`'s tree was clean at `de1d801`. A `land` branch was cut from `main` in the `kiro-polish`
worktree, and `git merge --no-ff kiro-polish` was run there (merge `44b9e65`, tree `b6a5c34`, parents `de1d801` and
`dc95fbe`). The suite ran on that commit in the worktree, and `main` was fast-forwarded to it, so the tree on `main` is
the tested tree.

| Chunk (tree `b6a5c34`) | Collected | Passed | Skipped | xfailed | Failed | collected == p+s+x |
|---|---|---|---|---|---|---|
| 1 unit agents, availability, llm | 664 | 657 | 7 | 0 | 0 | yes |
| 2 unit verifier, implementer, gates | 1464 | 1460 | 3 | 1 | 0 | yes |
| 3 unit orchestrator, archive, state, vcs, specs | 622 | 620 | 2 | 0 | 0 | yes |
| 4 every other `tests/unit` directory and `tests/unit/test_*.py` | 2265 | 2260 | 5 | 0 | 0 | yes |
| 5 contract, scenarios, integration, live (`L4_LIVE` unset) | 123 | 60 | 63 | 0 | 0 | yes |
| Total | 5138 | 5057 | 80 | 1 | 0 | yes |

Collected is pytest's own `collected N items` line of each chunk. Chunks 1 to 3 ran in parallel, then 4 and 5 beside
chunk 2. In that parallel run, chunk 1 had one failure,
`tests/unit/llm/test_system_one.py::test_laya_serve_stopped_and_killed_when_not_ready`. Its fake server had not written its pid within the test's 1 s
ready timeout, at a load average near 60. The branch does not touch `llm`. Chunk 1 was rerun alone and passed, and the
table shows that rerun. On `main` at `44b9e65`: `uv run ruff check .` reports all checks passed, and `python3
scripts/check_spec.py docs/SPEC.md` exits 0 (178 requirements, 347 scenarios, none uncovered).

## wave-d-fixes merge (branch `wave-d-fixes`, merge commit `861acbe` onto `03868b2`, from `42ce0de`)

Four harness findings of sample-consumer wave D
(`docs/adoption/sample-consumer/wave-d.md`, private adoption notes, not published), each test first:

* **W-D2 (safety)** (`123d6bb`, review fixes `0be1b70`, `a7fbb18`, `51b7b2f`, `42ce0de`): a cancelled CI job stops its run.
  SIGTERM, SIGHUP and SIGINT raise `RunCancelled` (a `BaseException`) in `l4 run`, `verify`, `archive` and `resume`.
  The agent or gate process group is killed, nothing is pushed (`cancel.check()` in `Git._push`, the one chokepoint of
  the unit branch, the lock ref, the pending ledger and a retire), no forge write is sent (every non-GET request), the
  local ledger records `run.cancelled`, the lease is released, and the exit code is the new 16 (`cancelled`). Inside
  GitLab CI a watchdog asks `GET $CI_API_V4_URL/job` with the job token, and whether the job's session leader exists,
  at once and then every 30 s. Either "gone" sends the process SIGTERM, and `_exit(16)` follows two minutes later.
  The unit branch is pushed with `--force-with-lease=<ref>:<last seen>` after a fast-forward check, so a branch a
  person deleted is never recreated and one a person moved is never overwritten. The lease payload records the CI job
  and pid. SPEC L4-CLI-003, SCN-CLI-08.
* **W-D1** (`feaf540`, `dc1ecf6`, review fixes `0be1b70`, `57eb068`): `gates.test_timeout` (`auto` = the smaller of
  10m and half of `gates.timeout`; `0s` off). The harness plugin `l4_trace` fails a test that runs longer with
  `l4-test-timeout:` (SIGALRM), and a test that ignores that is named on the real stderr as `L4_TEST_HANG: <nodeid>`
  with exit 70. A green attempt with a hung test fails by name, with the frame in the retry prompt. A hung frozen test
  raises one technical question at once (file, test, frame; the first option unfreezes the file). A new test that
  hangs in red is not a valid red. SPEC L4-GAT-004, SCN-GAT-04.
* **W-D6** (`f2e1b67`, review fixes `0be1b70`, `998407b`): a suppression comment, or a result-manipulating support or
  runner-config change, that only people's commits wrote is listed in `verification.md` and `verdict.json`, not a
  finding. Attribution is per commit (`_introducers`; `git blame` tells a person's line from the harness's when both
  added the same comment text). The "undeclared suppression" finding now says to remove the comment and to declare it
  only when it cannot be removed. SPEC 2.10.
* **W-D3** (`269f8e1`, pins `2baabdb`): contract v8 tells Codex to write the real-server test that a task or design
  asks for (port 0, a timeout on every blocking read, both ends closed), because the gate run executes it with
  loopback even though Codex's own sandbox cannot. In-process tests go beside it, never instead of it, and never a
  `socketpair` in place of a requested server. Prompt only: the Codex sandbox still blocks sockets.

Adversarial review before the merge (`a7fbb18`, `51b7b2f`, `57eb068`, `939a399`, `c85371c`, `42ce0de` added):

* **W-D2, the cancel as the runner does it, end to end** [V test]. `tests/unit/cancel/test_cancel_subprocess.py`
  starts `l4 run` as a real child under a `/bin/sh` that leads its own session, with a `command`-adapter agent (a
  child process that sleeps), `GITLAB_CI=true` and a job token. Four cancels: `su`'s way (SIGTERM to the shell only,
  then SIGKILL, reaped), SIGKILL of the shell alone, the runner's process-group SIGTERM, and a forge that starts
  refusing the job token while the shell lives. Each one asserts that `l4` ends (exit 16 in `outcome.json`,
  `run.cancelled` in the ledger), that the agent process is gone, that `origin`'s refs are unchanged and that the unit
  lock can be taken at once. With the watchdog switched off (`GITLAB_CI=false`) the `su` case fails: the orphan lives
  on with its agent, which reproduces job 6051.
* **W-D2 defect, fixed in `51b7b2f`.** `push_branch` leased on the remote-tracking ref first. git moves that ref on a
  push only when a configured fetch refspec covers the branch, which a `--single-branch` or shallow clone, or a remote
  set up with `git config remote.origin.url`, does not have [V probe, git 2.48]. The worktree refresh fetches with an
  explicit refspec, so the tracking ref existed and went stale after the run's first push: the second push of the run
  leased on the old value and was refused as "deleted or moved", a legitimate fast-forward. The push now moves the
  tracking ref itself. Test: a remote with no fetch refspec, three pushes. Also tested: a new process resumes from a
  branch a person added a commit to, and its push lands. Whether the runner's checkout has the refspec is not
  checked; the fix does not depend on it.
* **W-D2 gap, fixed in `a7fbb18`.** The watchdog first asked after 30 s, and a push in between two polls went
  through. A job cancelled during `l4 doctor` or `l4 plan` leaves its orphaned shell to start `l4 run`. The watchdog
  now asks at once, and `cancel.check()` in front of every push and forge write asks the session leader too (one
  local syscall). `L4_CANCEL_POLL_S` sets the interval for the harness's own tests.
* **W-D2 gaps, fixed in `42ce0de`.** The forge check fails open (a TLS, DNS or HTTP error is not a cancel) and was
  silent, so a job log could not show that only the session check was watching. The first such answer now logs
  `the job API could not be asked (...); only the session check watches whether this CI job still runs` (or `the job
  API answered HTTP <n>`), once per process. `cancel.reset()` now drops the session probe too, so a test that dies
  before stopping its watchdog cannot cancel later pushes in the same process.
* **W-D2 test, strengthened in `a7fbb18`.** `test_a_cancel_during_the_green_step_pushes_nothing_after_it` spied on
  `Git.push`, which no longer sees the unit branch (`push_branch` calls `_push`), and compared nothing after the
  cancel. It now counts every `_push` call and the origin refs at the moment of the cancel and at the end. The lock
  test now takes the lease directly.
* **W-D1 defect, fixed in `57eb068`.** The plugin stood aside whenever pytest-timeout was loaded. pytest-timeout is
  often installed with no limit set, and then the gate had no per-test limit at all, which is W-D1 again (the test hung
  to its 60 s subprocess timeout before the fix). Now the plugin stands aside only when pytest-timeout sets a limit
  (`--timeout`, `PYTEST_TIMEOUT`, the `timeout` ini value, in pytest-timeout's own order). Otherwise only tests with a
  `timeout` marker are left to it.
* **W-D1 defect, fixed in `57eb068`.** `_wrapped` called `signal.signal` on whatever thread ran the hook. An xdist
  worker on execnet's thread model runs hooks off the main thread, so every test would have errored with
  `ValueError: signal only works in main thread`, and an ITIMER with no handler would have killed the worker. Off the
  main thread the soft limit now stands aside and the hard deadline stays. The hard watchdog thread starts once per
  process, from any thread.
* **W-D1 checked, no defect** [V test]: slow but correct tests under the limit pass, and the limit is per phase, not a
  session budget (4.8 s of sleeps under a 2 s limit pass). The default is 10 minutes per test, configurable, and `0s`
  switches it off. The plugin imports only pytest and the standard library.
* **W-D6 checked, no defect** [V code + test]: `is_harness` needs the bot author and an `L4-Run` trailer, and the test
  helper's `commit()` is exactly that. `test_a_noqa_the_harness_added_is_still_undeclared_even_if_a_person_edits_the_file_later`
  and `test_a_person_and_the_harness_adding_the_same_comment_text_are_told_apart_by_line` keep an implementer's `noqa`
  a finding. An agent cannot commit as a person, because bwrap binds the git common dir read-only.
* **Merge interaction checked** [V code]: kiro-polish's in-run wait sleeps in `time.sleep`, which the cancel handler
  interrupts. Every `except BaseException` in `src/l4` re-raises. No test that kiro-polish added spies on `Git.push`.
* Residual risks, not fixed here:
  1. The watchdog's forge check trusts `GET /job`: a forge that answers 401 or 403 to a running job's token would cancel
     every run at its start. GitLab documents the endpoint for the job token; it was not called from the runner.
  2. `faulthandler`'s C backstop (limit + 2 x grace + 1 s) exits 1, not 70, so a hang that holds the GIL past the
     Python watchdog is not named by `gate_hung`.
  3. `l4 doctor --fix` and `l4 plan --sweep` are not cancellable. A cancel during them leaves the orphaned shell to run
     the next script line. `l4 run` then stops at its first check.
  4. When the run outlives the 2-minute grace, `_exit(16)` is used, and an agent outside bwrap
     (`sandbox.mode: none`) survives it.
  5. The session check is the leader's pid, not an ancestor chain or a start time: a pid reused within one poll
     would look alive.
  6. The SPEC residuals stand: a new run after a person deleted the branch starts afresh, layer 4 is only the lease
     payload, and the Codex loopback profile waits for a Linux spike.
* Not checked live: all four. What a runner check must show is in wave-d.md.

Merge mechanics: `main`'s tree was clean at `03868b2`. A `wave-d-merge` branch was cut from `main` in its own
worktree (`l4-wt/wave-d-merge`), and `git merge --no-ff wave-d-fixes` merged with no conflict (`docs/SPEC.md`,
`config/schema.py`, `implementer/tdd.py`, `implementer/workbench.py` and `orchestrator.py` auto-merged with
kiro-polish). A first suite run on an earlier merge was stopped when `c85371c` and `42ce0de` were added, and the
merge was redone: `861acbe` (parents `03868b2` and `42ce0de`), tree `84f01b0`, which is the tree `git merge-tree
--write-tree main wave-d-fixes` returns. Every chunk below ran on that tree in the worktree, and `main` was
fast-forwarded to `861acbe`, so the tree on `main` is the tested tree.

| Chunk (tree `84f01b0`) | Collected | Passed | Skipped | xfailed | Failed | collected == p+s+x |
|---|---|---|---|---|---|---|
| 1 unit agents, availability, llm | 665 | 658 | 7 | 0 | 0 | yes |
| 2 unit verifier, implementer, gates | 1496 | 1492 | 3 | 1 | 0 | yes |
| 3 unit orchestrator, archive, state, vcs, specs | 643 | 641 | 2 | 0 | 0 | yes |
| 4 every other `tests/unit` directory and `tests/unit/test_*.py` | 2306 | 2301 | 5 | 0 | 0 | yes |
| 5 contract, scenarios, integration, live (`L4_LIVE` unset) | 123 | 60 | 63 | 0 | 0 | yes |
| Total | 5233 | 5152 | 80 | 1 | 0 | yes |

Collected is the last line of a separate `--collect-only -q` run of each chunk. Chunks 2 to 5 ran in parallel in the
background and chunk 1 in the foreground (its `test_proc.py` SIGINT test needs a foreground shell), all started
at a load average near 350 (other workflows); it fell to about 15 by the end. Chunk 2 took 35 minutes, 3 took 14, 4
took 13, 5 took 2.5 and 1 took 42 s. No test failed and none was rerun.

On the merge tree: `uv run ruff check .` reports all checks passed, and `python3 scripts/check_spec.py docs/SPEC.md`
exits 0 (180 requirements, 349 scenarios, none uncovered).

## cancel-polish merge (branch `cancel-polish`, merge commit `2ee43bc` onto `a3fee70`, from `7c6935e`)

Two findings of the wave D live check on dummy-agentic ([../live/wave-d-live/README.md](../live/wave-d-live/README.md)),
each test first:

* **F4 (observability)** (`1ee6036`, review fix `7c6935e`): when the CI watchdog starts it logs one INFO line,
  `[l4] cancel: watching CI job <id> (job API every 30s + job session <sid>)`, so a normal job shows the watchdog is
  armed instead of proving it by absence. Without `CI_API_V4_URL` the middle reads `job API not used: no
  CI_API_V4_URL`. Inside GitLab CI without `CI_JOB_TOKEN` no watchdog starts (unchanged), and the line is `[l4] cancel:
  not watching CI job <id> (job API not used: no CI_JOB_TOKEN; only a signal stops this run)`. A missing `CI_JOB_ID`
  shows as `?`. The line holds the job id, the interval and the session id only: never the token, never the API URL.
  `start_watchdog` has one caller (`cli.py`, once per `run`, `verify`, `archive` or `resume`), so the line appears
  once per run. SPEC L4-CLI-003.
* **F2 (minor defect)** (`1ee6036`, review fix `7c6935e`): `l4 status` in the `after_script` of a cancelled job no
  longer ends in `internal error: GitError … HTTP Basic: Access denied`. When git's stderr for the CI refresh fetch
  says `access denied`, `authentication failed`, `HTTP Basic` or `returned error: 401`/`403` (the job token in the
  origin URL is refused once the job is cancelled), `status` logs `[l4] status: could not refresh from the forge
  (access denied: the job may be cancelled); showing local refs` once on stderr, reads the local refs, keeps stdout
  clean (the JSON or the table) and exits as it would with that data. Only `status` degrades: `plan`, `resume`, the
  orchestrator, `archive` and the dry run still raise on a refused fetch, because planning from refs known to be stale
  is how a deleted branch comes back (tested for `plan`). Every other git error still raises (a DNS failure, the 124
  timeout, a ref lock); a missing `origin` never reaches the fetch (`refresh_in_ci` returns before it). SPEC
  L4-CLI-003.

Review before the merge (`7c6935e` added):

* **F4 gap, fixed.** The finding asks for a line when the job API is not used for want of `CI_JOB_TOKEN` or
  `CI_API_V4_URL`; the branch covered only the URL, and GitLab CI without a job token still returned with no line. Now
  that case says it is not watching [V test]. Arming a session-only watchdog without a token was not done: it would
  start a watchdog thread in every test that sets `GITLAB_CI=true` alone.
* **F2 tightened.** The match read `str(exc)` as well as the stderr, and `str(exc)` is the git argv (the `-c`
  credential helper, the refspecs with the configured branch prefix). It now reads git's stderr only, so a word in the
  command line cannot pass for a refusal. With the shipped helper and prefix no needle was in the argv [V code], so this
  was not reachable as configured; a test with a needle in the argv covers it.
* **Tests strengthened.** The token test used the token `tok` and checked a substring; it now uses a distinctive token
  and also checks that the API host is absent. The "any other fetch error" test now also asserts that the fallback line
  is not printed.
* **Checked, no defect** [V code]: `run_status` makes no forge call after the fetch (`app_forge_urls` only builds
  addresses), so the fallback reaches the output; `status` is not a cancellable command, so no watchdog runs in the
  `after_script`; the console prints INFO at the default verbosity (`-q` hides the line, as it hides all INFO).
* Residual risks, not fixed here:
  1. The refusal is recognised by text. A refusal worded otherwise (for example `could not read Username` when the
     origin URL carries no credentials) still raises, as before.
  2. Not checked live: the new line in a real job trace and `l4 status` in the `after_script` of a cancelled job.
  3. The implementer saw `tests/unit/agents/test_proc.py::test_interrupt_sends_sigint_then_the_run_ends` fail twice
     with five suites in parallel and pass alone [I load-dependent]; it passed in chunk 1 below.

Merge mechanics: `main`'s tree was clean at `a3fee70` (`git status --short --untracked-files=all` empty), and `git
merge --no-ff cancel-polish` on `main` merged with no conflict: `2ee43bc` (parents `a3fee70` and `7c6935e`), tree
`7595a14`, which is the tree `git merge-tree --write-tree a3fee70 7c6935e` returns. The `cancel-polish` worktree
(`l4-wt/cancel-polish`) was detached at `2ee43bc`, and every chunk below ran there on that tree.

| Chunk (tree `7595a14`) | Collected | Passed | Skipped | xfailed | Failed | collected == p+s+x |
|---|---|---|---|---|---|---|
| 1 unit agents, availability, llm | 665 | 658 | 7 | 0 | 0 | yes |
| 2 unit verifier, implementer, gates | 1496 | 1492 | 3 | 1 | 0 | yes |
| 3 unit orchestrator, archive, state, vcs, specs | 647 | 645 | 2 | 0 | 0 | yes |
| 4 every other `tests/unit` directory and `tests/unit/test_*.py` | 2311 | 2306 | 5 | 0 | 0 | yes |
| 5 contract, scenarios, integration, live (`L4_LIVE` unset) | 123 | 60 | 63 | 0 | 0 | yes |
| Total | 5242 | 5161 | 80 | 1 | 0 | yes |

Collected is the `collected N items` header of each chunk's run. Chunks 1 and 2 started together in the background,
then 3, 4 and 5 one at a time beside chunk 2 (never more than two at once), at a load average near 15 to 23. Chunk 2 took 32 minutes, 3 took 10, 4 took 10, 5 took 77 s and 1 took 32 s.
No test failed and none was rerun.

On the merge tree: `uv run ruff check .` reports all checks passed, and `python3 scripts/check_spec.py docs/SPEC.md`
exits 0 (180 requirements, 349 scenarios, none uncovered).

## Merge log: soft-deadline, nonpython-evidence, trace-rule (2026-10-10)

The first Node project (sample-node-app: React 19, TypeScript 5.8, Vitest 4, harness `f453063`) showed four defects live, none
of them in the project:

* **Vitest red tests could not pass L4's checks.** The red retry told a Vitest agent to tag tests with
  `@pytest.mark.l4` (`implementer/result.py`), and `gates/junit.failure_kind` read only pytest-shaped messages, so every
  Vitest failure had no kind (verified: a recorded Vitest 4.1.2 report, six failures, all `None`). Four of the first
  six units halted in red (`max_task_attempts`) on LongCat and Codex alike; the two that passed did so by naming a
  thrown `Error("AssertionError: …")` or `context.annotate(id, "l4")`. **trace-rule** (`4a9089e`, `9e00476`): the
  contract, red and single-tests wording follow the test gate (`trace_rules`: the marker for a pytest gate, else the id
  in the test name, which `trace_ids` already read), the retry hint follows it too, a stub outside Python throws a
  not-implemented error (TS/JS and C# named), and `failure_kind` falls back to the JUnit `type` attribute when the
  message gives no kind (the message always wins: a .NET converter's `AssertionError: …` with `Xunit.Sdk.EqualException`
  stays an assertion). Contract v9, red v9, single_tests v5. SCN-IMP-65..70.
* **A PASS that claimed checks nobody ran.** "100.0% of the changed executable lines ran" with no Python changed
  (`collect.py` returned 100 before reading coverage), "suppressions" and "content scan" green after reading no file,
  audit sampling writing a pytest test for TypeScript and reporting its rejection as a finding, and 28 `.pyc` guard
  events from an agent importing the vendored harness. **nonpython-evidence** (`44d1d7c`, `8089ac0`, `55f94b0`): diff
  coverage `not_applicable` with "not measured: … changed code outside it" (no hold, no attention line; an empty change
  stays 100), the two integrity rows say "not checked: python only" with the files, audit sampling `not_run` when no
  `.py` changed, `PYTHONDONTWRITEBYTECODE=1` in the sandbox env and both probe scripts, COV-001 names a non-Python test
  gate (only when no project interpreter exists: a `.venv` under `make test` is still checked; review fix `55f94b0`).
  SCN-VER-55..60.
* **The soft deadline was not implemented** (L4-IMP-012): a 180-minute job running eight ~40-minute units would be
  killed mid-unit. **soft-deadline** (`33023a5`): between units, no unit starts when the soft deadline has passed or the
  longest unit so far would not fit; the units left are listed `not started: soft deadline (…)`, exit 10. The in-phase
  interrupt, WIP push and continuation stay to do. SCN-IMP-62..64. Review: the three scenario tests fail on `main` by
  assertion (all units ran) and pass on the branch [V test].

Coordination: the architecture session's planned `fix-openspec-exempt-and-nonpython-presat` touches neighbouring code;
files and SPEC id ranges were split by message beforehand (its SCN-IMP-55..58 and SCN-VER-54 left free) and it rebases
onto this merge.

Merge mechanics: `main` clean at `f453063`; `git merge --no-ff` of soft-deadline (`96fabf8`), nonpython-evidence
(`5f58a30`) and trace-rule (`27a4fba`), no conflict, tree `acfa0ff`. Every chunk ran in `l4-wt/merge-check`, detached
at `27a4fba`, with `L4_LIVE` unset.

| Chunk (tree `acfa0ff`) | Passed | Skipped | xfailed | Failed |
|---|---|---|---|---|
| 1 unit agents, availability, llm | 658 | 7 | 0 | 0 |
| 2 unit verifier, implementer, gates | 1544 | 3 | 1 | 0 |
| 3 unit orchestrator, archive, state, vcs, specs | 659 | 2 | 0 | 0 |
| 4 every other `tests/unit` directory and `tests/unit/test_*.py` | 2322 | 5 | 0 | 0 |
| 5 contract, scenarios, integration, live | 60 | 63 | 0 | 0 |
| Total | 5243 | 80 | 1 | 0 |

Chunk 2 took 33 minutes beside the others (1 and 2 together, then 3, 4 and 5 one at a time). No test failed and none
was rerun. On the merge tree `uv run ruff check .` passes and `python3 scripts/check_spec.py docs/SPEC.md` exits 0
(180 requirements, 364 scenarios, none uncovered). Residual: none of this is checked live yet; sample-node-app is upgraded
next and its halted units resumed.

## Merge log: earlier-red, vitest-polish (2026-10-10)

sample-node-app on harness `a6b440f` showed the next two defects live (the trace-rule fix itself held: red_ok on the first
attempt with the id in `it()` titles and plain `expect`):

* **A pre-satisfied criterion could not be confirmed outside Python.** MR !2: task 1.1's red wrote tests for all six
  criteria (they failed by assertion, `task.red_ok`), green made them pass, and task 2.1's red then met its criteria
  already satisfied; `confirm_pre_satisfied` (zero-value run, Python import analysis) answered "no project source module
  is imported by those tests" three times and the unit halted. MR !3 met the same and its agent asked a person.
  **earlier-red** (`950d76d` tests first, `e2eca47`, review fix `c3db74b`): before the zero-value run, a candidate
  criterion is confirmed by an earlier red of the same unit when a test tracing it is among the `discriminating` tests
  of a `red_assertion`/`zero_value` proof of an earlier `task.red_ok` (same `fix_unit` context, not listed by that
  task's `criterion.pre_satisfied`, not an `already-satisfied` event), that red's base and commit are ancestors of HEAD,
  the test file is unchanged since that commit (against the worktree), and the test passes at head. Only the remaining
  criteria reach `confirm_pre_satisfied`, which the audit still calls unchanged. The proof is `pre_satisfied` with
  `via: earlier_red`, the earlier tests as `discriminating`, `red_sha`, `red_task`. Design points from the architecture
  session (call site not inside `confirm_pre_satisfied`; ancestry, not base equality; failed-at-red only; file check;
  proof marking). Review fix: `discriminating`, not every listed test, is the evidence. SCN-IMP-71..75.
* **Vitest polish.** MR !3's first red was rejected for Testing Library's `TestingLibraryElementError` ("Unable to find
  an element …", getBy*'s presence assertion) and the retry told a Vitest agent to call `pytest.fail(...)`.
  **vitest-polish** (`02ef16c`): that type (or a message prefixed with it) is an assertion; the red retry advice follows
  the test gate, with the stub wording the prompt uses (`THROWS_NOT_IMPLEMENTED`); `_IMPORT_ADVICE` stays pytest's.
  SCN-IMP-78, 79.

Merge mechanics: `main` clean at `a6b440f`; `git merge --no-ff earlier-red` (`0762b57`) without conflict, then
`vitest-polish` (`6674782`) with one conflict in `docs/SPEC.md` (both appended scenarios after SCN-IMP-70; both kept,
SCN-IMP-72 also names the `discriminating` rule), tree `386fb1d`. `tdd.py` merged automatically (earlier-red call at
~667, `rules=` on the `classify_red` call at ~682). Chunks ran in `l4-wt/merge-check` detached at `6674782`.

| Chunk (tree `386fb1d`) | Passed | Skipped | xfailed | Failed |
|---|---|---|---|---|
| 1 unit agents, availability, llm | 658 | 7 | 0 | 0 |
| 2 unit verifier, implementer, gates | 1566 | 3 | 1 | 0 |
| 3 unit orchestrator, archive, state, vcs, specs | 659 | 2 | 0 | 0 |
| 4 every other `tests/unit` directory and `tests/unit/test_*.py` | 2322 | 5 | 0 | 0 |
| 5 contract, scenarios, integration, live | 60 | 63 | 0 | 0 |
| Total | 5265 | 80 | 1 | 0 |

No test failed and none was rerun. `ruff check .` passes; `check_spec.py` exits 0 (180 requirements, 371 scenarios,
none uncovered). Live on a6b440f already: the trace rule, Vitest failure kinds, the honest evidence rows (MR !5:
audit `not_run`, quality "not measured", suppressions "not checked") and COV-001's new skip.

## Merge log: earlier-red-append (2026-10-10)

Live on harness `43654f8`, MR !2 task 2.1 still failed "not discriminating": the earlier red's evidence was on the
branch (1.1's `task.red_ok`, `red_assertion`, discriminating tests; red commit and base ancestors of HEAD), but
`tasks.md` tells 2.1 to add its tests to 1.1's file, and the check compared that file in the worktree with the red
commit, so the step's own appended tests voided it. MR !3 (2.1 into `ErrorBoundary.test.tsx`) failed the same way.
**earlier-red-append** (`b846bfc`): the file at `HEAD` must equal the red commit's, and the step's diff of it against
`HEAD` may add lines only (`git diff --numstat`: any deleted or changed line, or a binary diff, voids it); this is the
architecture session's original point 4 plus a guard against an edit of the earlier test. Tests first: the appended
case failed before the change (1 failed), the edited-line case replaces the old any-edit case; 16 of 16 pass. SPEC
paragraph (L4-IMP-003) and SCN-IMP-73 amended. Merged as `085b5c3` (no conflict). Affected directories on the merge
(`tests/unit/implementer`, `tests/scenarios`, `tests/contract`): 562 passed, 2 skipped, 0 failed; `ruff check .` and
`check_spec.py` clean. The full suite was not rerun for this one-module change.

## Merge log: earlier-red-append2 (2026-10-10)

Live on `8464d2d`: MR !3 task 2.1 passed as already satisfied by 1.1's red (PASS 2/2), and MR !2 task 2.1 too, but MR
!2 task 3.1 then failed: 2.1's already-satisfied commit had appended its tests to 1.1's file, so the file at `HEAD` no
longer equalled 1.1's red commit. **earlier-red-append2** (`f421202`): the file must only have gained lines since the
red commit, in later commits and in this step alike (`git diff --numstat <red sha> -- file` against the worktree: no
deleted or changed line, no binary diff). Tests first (the committed-append case failed before; the committed-edit case
now changes a line). Merged as `4903214`. `tests/unit/implementer`, `tests/scenarios`, `tests/contract`: 563 passed, 2
skipped, 0 failed; ruff and check_spec clean. Residual (agreed with the architecture session, after the round): appended
lines can still change an earlier test without touching its lines (a hoisted `vi.mock`, a redefined helper, a pytest
function of the same name); the proof will carry `appended_lines` for the report.

## Merge log: base-run (2026-10-10)

Live on `3a94577`: MR !2 task 3.1 passed as already satisfied by 1.1's red (the append rule held), and MR !2 went
to verification; MR !4 task 1.2 and MR !8 task 2.1 still halted. There the criterion was made true by an earlier
task's GREEN (a shared helper; the whole-word matcher) and no earlier red ever tested it,
so neither earlier_red nor the Python-only zero-value run could confirm it. **base-run** (`ed3f331` tests first,
`714a9cd`): last in the chain earlier_red → zero-value → base run, on what the zero-value run left; the production
files changed since the UNIT base (commits and this worktree) are swapped to their base content by the existing
`run_with_code_of` (sha256 restore, fresh writes, reports put back; reused at the architecture session's request),
tests / support / exempt paths stay; a changed dependency manifest, lock file or runner config skips the run (npm,
Python, Go, Rust and .NET names); a criterion is confirmed only when one of its new tests fails BY ASSERTION at the
base (errors are inconclusive; a test that passes at the base too stays unconfirmed: the architecture session's
unverifiable path). Proof `pre_satisfied`, `via: base_run`, `base_sha`; `tampered("base run")` after it. SCN-IMP-80..86.
Merged as `fc912c3`; implementer, scenarios, contract: 572 passed, 2 skipped, 0 failed; ruff and check_spec clean (378
scenarios). Known limits (from the reuse, fail closed): a file deleted since the base is not restored for the run; a
set-aside file comes back with the default mode.
