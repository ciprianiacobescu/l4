# M1.4 — Spec frameworks, platforms and operations (planned 2026-10-04)

## Goal

The harness drives Kiro specs (`.kiro/specs/<name>/`, with waves, optional leaves and `_Requirements:_` links) next to
OpenSpec changes, finds both from files only and reports Spec Kit without driving it (SPEC 4.1, 4.5:
L4-DET-001..003, L4-KSP-001..004).
It gains a GitHub forge and GitHub Actions template at the M1.1 level, proven with a fake forge and actionlint while
the live GitHub step waits for Q5 (L4-CI-001..003, §16.2), and an `l4 doctor --fix` that provisions a shell runner
user-locally, never as root (L4-DOC-002).
Operators get tools that spend no tokens: `doctor --ci/--live/--unit`, `plan --probe/--detailed-exitcode`,
`run --dry-run`, `l4 simulate`, a JSONL log and CI output mirrors (L4-DOC-001, L4-SIM-001..003, L4-OBS-001, L4-CLI-002).
A killed job resumes from a WIP snapshot and a halted unit can be resumed by a human (L4-STA-003, L4-IMP-011,
SCN-IMP-17, SCN-RES-01).

## Build list

Line format: `change-id task — what M1.4 builds · lane`. There are five lanes:

| lane | covers |
|---|---|
| spec | Kiro, detection |
| prov | doctor, provisioning |
| gh | GitHub |
| sim | simulate, dry-run, plan, observability |
| wip | crash resume |

* Stage A edits only files its lane owns, so its five lanes run at the same time.
* Stage B integrates. Each shared file has one owner lane (see Files), and other lanes hand that owner their one-line
  deltas.
* Stage C was the set of lines that had to wait for M1.1 Stage C. That has landed (m11-progress lines 26–41,
  `98e4939`), so they wait only for their own Stage B inputs. M1.4 total: **43 build lines, 7 of which carry a gap task
  (M14-G1..G7)**.
* **Parallel with M1.2, M1.3 and M1.5.** The shared-file anchors and exact names, the contracts (C3–C6, C10–C14, C17,
  C19, C20) and the merge order (M1.2 → M1.3 → M1.4 → M1.5; M1.4 may overtake M1.3) are in
  `docs/plan/parallel-ownership.md`. G2 and line 28 need the seam commit S0 (`l4.versions`): merge `main` before them.

### Decisions behind the list

* **Lease locks (L4-LCK-001 acquire, heartbeat, takeover, fencing) are not in M1.4.** M1.1 deferred them as well
  (state-vcs-locks 2.2–2.17).
  * The lock ref is now owned by M1.1's `PendingLedger`: it holds "born expired" commits, and that code is Stage C, in
    flux [V, m11-progress line 27].
  * The reference runner has `concurrent = 1`, and the template sets `resource_group: l4` [V]. A lease would add no
    safety there.
  * The cost would be about six lines (2.2–2.8, 2.12), each touching every push path. They go to M2, together with
    GitHub matrix jobs and several runners.
* **WIP snapshots stay local.** They go to `refs/l4/wip/<fw>/<name>` in the runner's clone. This is the M1 form that
  state-vcs-locks 1.13 and 1.23 name themselves.
  * The shell runner reuses its clone [V, job 5428 "Reinitialized existing Git repository"], and G8 prunes only
    `refs/l4/locks/*`.
  * The pushed `l4-wip/` branch (4.12) needs fencing, so it waits with the lease.
* **One OpenSpec prefix: `$L4_HOME/npm`.** PRQ-08 installed OpenSpec there, and ENV-003 checks it there [V, code and
  README]. `doctor --fix` installs OpenSpec and Codex into that same prefix, as `prereqs.sh` does.
  * This deviates from runner-provisioning 1.11 and 1.13 (`$L4_CACHE/tools/<tool>-<v>`); see Doc changes owed.
  * A drift test keeps the catalog pins equal to the defaults in `scripts/runner/prereqs.sh`.
* **Simulation runs the real orchestrator.** The skeleton driver of simulation-harness 1.8 is dropped: the
  orchestrator now exists.
  * Scenarios set `sandbox: {mode: none, allow_none: true}`, which is an existing key [V, `select_sandbox`].
  * They also set `forge.type: local`, served by `LocalForge`, the fake forge of D1. With it and a fake token the real
    `l4.archive` hooks run, and a unit reaches `in_review`, not `verified`.
* **`run --dry-run` exits 0** and prints `would exit N` as its last line [I]: CI script lines stay simple.
  * In CI, the ref refresh (G8 fetch) is a read of the remote, not a dry-run violation.
* **Optional Kiro leaves (`[ ]*`) never count as pending.** A unit whose required tasks are all done plans `verify`.
* **No edits to `cli.py` or `commands.py`** [V, code]: every flag of this increment is already parsed, and the
  `simulate` and `resume` handler names are already in `HANDLERS`.

### Stage A — foundations (5 lanes in parallel; new or lane-owned files only)

1. spec-providers 1.2 — `ProviderRegistry.register/get/for_unit`, rejecting a provider that lacks a `SpecProvider`
   member. The Protocol gains `done_gate`. M1.3's `create_fix_unit` is a separate optional Protocol
   (`FixUnitCapable`) that the registry does not check; `KiroProvider` does not implement it (parallel-ownership C10). `Task` gains `optional`, `wave` and `links`, each additive with a default · spec
2. spec-providers 1.3–1.6 + 4.1 — `detect_frameworks` (`l4/specs/detect.py`), from files only:
   * signals: OpenSpec, legacy OpenSpec (reported, unsupported), Kiro (a `.kiro/specs/<name>/` holding
     requirements, bugfix, design or tasks), and Spec Kit (detected, never driven);
   * `.kiro/prompts|skills` alone and a bare `specs/` are not signals;
   * a test proves no process or socket is opened;
   * `require_framework` exits 14 under `sdd.enforce`;
   * `collect_units` namespaces the units of both providers · spec
3. spec-providers 2.1 — `KIRO_TASK_RE` and `parse_kiro_tasks`:
   * markers `' ' - ~ x X`;
   * `*` or `\*` right after `]` makes a task optional, but a space before `*` does not (SCN-TMW-03);
   * ordered bullets and empty brackets are not tasks · spec
4. spec-providers 2.2 + 2.3 — hierarchy:
   * by dotted number when any task is numbered, else by indentation, normalised into `Task.depth` so the existing
     selector works;
   * a parent's state comes from its non-optional children;
   * `KiroProvider.set_marker` writes `DONE` only, through `write_marker`, closes parents automatically, and raises
     `ParentHasOpenChildren` · spec
5. spec-providers 2.4 — `read_waves` and `order_leaves`:
   * waves come from the `## Task Dependency Graph` JSON (`{"waves":[{"id":0,"tasks":[...]}]}` [V, research/01]),
     which sets `Task.wave`;
   * an invalid graph falls back to document order with a warning;
   * pending leaves missing from the graph keep their document position · spec
6. spec-providers 2.5 — `kiro_criteria`:
   * EARS lines numbered per requirement in `requirements.md` or `bugfix.md`, alias `Req N.M`;
   * the id hashes the normalised text, so inserting a criterion shifts no id (SCN-CRT-05);
   * `_Requirements: …_` lines fill `Task.links` · spec
7. spec-providers 2.6 + 2.7 (reduced) — `KiroProvider.validate`:
   * checks file presence, task grammar, graph JSON and that links resolve;
   * a leaf without `_Requirements:_` is an error under `sdd.enforce`, unless it is TDD-exempt.

   Also `done_gate` (required leaves only) and `archive`, which only records the state (SCN-KSP-N7/N8) · spec
8. runner-provisioning 1.1 + 1.2 + 1.3 — `Paths.from_env`, `harness_path`, `find_tool`, `resolve_self_provision`
   (`auto` is false under `CI_DISPOSABLE_ENVIRONMENT=true` or `RUNNER_ENVIRONMENT=github-hosted`) and the `scrub_env`
   allow-list. Shared edit: `CiCfg.self_provision` · prov
9. runner-provisioning 1.4 + 1.5 + 1.6 — `HttpxFetcher` and `OfflineError`, `verify_sha256` and `save_installer` (never
   piped to a shell), and the catalog:
   * pins from `prereqs.sh`: uv 0.12.22, NODE_MIN 20.19.0 / Node 22.23.0, OpenSpec 1.14.0, Claude Code 2.1.288,
     Codex 0.160.0, OpenCode 1.18.34; Kiro is unpinned;
   * a drift test parses `scripts/runner/prereqs.sh`;
   * a recorded `SHASUMS256.txt` replay · prov
10. runner-provisioning 1.7 — `required_tools(cfg)` and `plan_fixes`. They give a `FixAction` of status `planned`,
    `already present`, `skipped` or `manual`. Node and OpenSpec are listed only when OpenSpec is active, an agent CLI
    only when a role chain uses it · prov
11. runner-provisioning 1.14–1.17 — the human-only parts:
    * `ROOT_PREREQS` with exact `sudo apt-get …`/`dnf` texts as `manual` actions; no argv starts with
      `sudo`/`su`/`doas`;
    * `GuardedCommandRunner` refuses `login`, `setup-token` and `auth login`;
    * `HUMAN_STEPS` per (adapter, auth);
    * `adapter_readiness` and `sanitize_status`: three states, and no e-mail is ever printed. `adapter_readiness`
      reads auth through the adapter's own `probe(profile, "auth", ctx)` (`Factory.build(profile)`) and parses no CLI
      output itself. After M1.2 lands, codex's auth is `account/read` and kiro's is `whoami` (parallel-ownership C5) ·
      prov
12. bootstrap-core 1.21 — the `--fix` framework:
    * `Fix(kind, scope, apply)`, `FixScope`, `SAFE_FIX_KINDS` and `attach_fix`;
    * fixed checks run again, so the exit code is the state after fixing;
    * under `--ci`, only `install` fixes apply;
    * a guard requires the tracked files to stay clean (SCN-DOC-03) · prov
13. bootstrap-core 1.20 + 2.14 (reduced) — `--ci` keeps the checks scoped `ci`; `--unit ID` keeps the global
    checks plus the unit-aware checks of that unit; `--live` adds the probe-cost footer and a JSON field · prov
14. forge-and-ci 2.8 — `GitHubForge` (`l4/forge/github.py`) over MockTransport:
    * `_request`: bearer token, `Link` pagination, retry on 429 and secondary rate limits, token redaction;
    * PR find, create (draft), get, list and update;
    * ready is set through the GraphQL `markPullRequestReadyForReview` · gh
15. forge-and-ci 2.9 (reduced) — `ensure_labels` and `set_managed_labels` (foreign labels kept),
    `upsert_sticky_note` (an issue comment by the token's own login), and `list_prs`/`get_pr` mapping `merged`,
    `closed`, `open` and `merge_commit_sha` · gh
16. forge-and-ci 2.14 + 2.15 + 2.17 (reduced) — `l4.ci.github.render_github_ci(cfg)`, a new module (`ci/render.py`
    is untouched), renders `l4.yml`, the M1.1 single routed job for GitHub:
    * triggers: push to the base branch and `l4/**`, schedule, `workflow_dispatch`; no `pull_request` trigger, so forks
      never run it;
    * job `if:` skips a head commit with `L4-Run: `;
    * `concurrency {group: l4, cancel-in-progress: false}`;
    * checkout with `fetch-depth: 0` and `persist-credentials: false`;
    * permissions and `timeout-minutes: 180`;
    * `runs-on: [self-hosted, <ci.runner_tags>]`, or `ubuntu-24.04` when the tags are empty;
    * steps `doctor --ci`, `plan --sweep`, `run`, each `|| l4 ci map-exit $?`;
    * `lint_github_yaml` and an `actionlint` contract test, skipped when the binary is absent · gh
17. simulation-harness 1.1 + forge-and-ci 2.12 (reduced) — `LocalForge` (`l4/forge/local.py`): the `Forge` Protocol
    in memory, optionally persisted as JSON under a directory, with a call log. Also `ScriptedAgent`, a `FakeAdapter`
    keyed by `when: {phase, task}`. **No `FakeClock` here:** the harness has one, M1.2's
    `l4.availability.cooldown.FakeClock`, which `quota-fallback` uses once both are on `main` (parallel-ownership C3).
    1.3 is absorbed: judges, the clarifier and S1 are `fake`
    adapter profiles (`JUDGE_ADAPTERS` contains `fake` [V]) · sim
18. simulation-harness 1.4 + 1.5 — the `Scenario` models (`extra="forbid"`, rejected before any temp dir), `@fixture:`
    resolution, and `SimRepo.create`: a bare remote plus a seeded clone, fixed identity and dates, every call through
    `Git` · sim
19. simulation-harness 1.6 + 2.1 — fixtures `openspec-basic` and `kiro-basic` (Kiro: two numbered parents, one
    optional leaf, a waves graph that reorders leaves), with payload files.
    * The gate is a fixture-local `tests/run_junit.py`: stdlib `unittest`, writing `.l4-out/junit.xml` in the xunit
      shape `parse_junit` reads (ids `classname::name`). The gate contract needs a JUnit report
      (`judge_test_gate`, `must_contain`), and the vendored harness runs `--no-dev`, so it has no pytest.
    * It runs with `sys.executable`. `gates.setup` is empty.
    * Compatible with M1.3's red and trace rules from the start (parallel-ownership C19):
      * scripted tests are named `test_l4_c_<hex>_<slug>`, so they trace by name;
      * scripted red stubs are only `raise NotImplementedError`;
      * failure messages follow the shape recorded by M1.3 G1.

      Whichever of M1.3 and M1.4 merges second re-baselines the expected events · sim
20. simulation-harness 1.7 (+ 1.9 part) — `compare_expect`, `format_mismatches` (the first diverging event) and
    `normalize_events` (timestamps, run ids, SHAs and `sandbox.disabled` removed) · sim
21. bootstrap-core 1.8 (reduced) — a JSONL log at `app.out_dir/logs/<run-id>.jsonl` (`.l4-out/logs`, the SPEC
    default): one redacted line per log record, plus every ledger event of the run.
    * `configure_logging` attaches the handler before any config is loaded, so a non-default `observability.log_dir`
      is not honoured yet.
    * The handler uses `app.redactor`, which `load_app_config` widens in place [V, code] · sim
22. bootstrap-core 1.17 + 1.19 — `plan_exit_code(actionable, detailed)` and `write_ci_outputs`
    (`.l4-out/l4.env` with `L4_EXIT`, `L4_UNITS_ACTIONABLE`, `L4_PHASES`, plus `$GITHUB_OUTPUT` when it is set). Also
    publishes `outcome.schema.json` · sim
23. state-vcs-locks 1.13 + 1.14 — `snapshot_wip` (a temporary index; the real index, HEAD and the stash untouched) into
    the local `refs/l4/wip/<fw>/<name>`, and `restore_wip` (`read-tree -u --reset`, then `reset -q <head>`). Covers a
    modified, a deleted, an untracked and a binary file · wip
24. state-vcs-locks 1.22 — `step_key` and `spec_files_hash` (`l4/state/idempotency.py`) · wip

*Exit A:*

* the unit tests of every lane pass, and `ruff` is clean;
* `parse_kiro_tasks` and the `kiro-basic` fixture agree on leaves, waves, optional and parents;
* `plan_fixes` on an empty `L4_HOME` lists uv, Node, OpenSpec and the role-chain CLIs as `planned`, and on the
  runner-like fixture as `already present`;
* the rendered `l4.yml` passes the golden test, and passes actionlint where the binary exists.

### Stage B — integration (shared files; one owner per file)

25. M14-G1 (gap) — route every unit through its own provider, and make optional leaves neutral · spec
26. spec-providers 1.31 + 6.2 (reduced) — `l4/doctor/checks_spec.py`:
    * SPEC-001: frameworks detected; legacy OpenSpec is an error; Spec Kit is an info row "detected, not driven";
    * SPEC-002 for Kiro units (`KiroProvider.validate`);
    * SPEC-004: Kiro leaves without `_Requirements:_`.
    These are unit-aware for `--unit` · spec
27. runner-provisioning 1.8 + 1.10 + 1.11 — the base installers:
    * uv: the saved official installer with `UV_NO_MODIFY_PATH=1` into `~/.local/bin`, run under `scrub_env`;
    * Node: the tarball checked with `verify_sha256`, extracted to `$L4_HOME/node.tmp.<pid>`, renamed atomically to
      `$L4_HOME/node`; a system Node is left alone;
    * OpenSpec: `npm install --prefix $L4_HOME/npm` with the harness Node, never `npx` and never global · prov
28. runner-provisioning 1.12 + 1.13 + 2.1 (reduced) — the agent CLI installers:
    * Claude Code: the saved installer with the version argument;
    * Codex and OpenCode: `npm install` into `$L4_HOME/npm`, linked into `~/.local/bin`;
    * Kiro: the saved `cli.kiro.dev/install`.
    After each install the version is checked against `min_version` with `l4.versions.version_at_least` (seam commit
    S0, shared with M1.2's binary probe); a CLI that is still too old is `failed` and both versions are named · prov
29. runner-provisioning 1.9 + 1.18 + 1.19 — `attach_fix` on ENV-001, ENV-003 and ENV-004, and registration of PRV-001
    and PRV-002:
    * a second `--fix` makes no download and no write;
    * `OfflineError` and `IntegrityError` become `failed` actions with the host and the manual command, exit 3;
    * nothing missing means no network at all · prov
30. M14-G2 (gap) — ENV-004 (reduced bootstrap-core 1.14) · prov
31. forge-and-ci 1.2 + 2.12 (reduced) + M14-G3 (gap) — `make_forge` chooses `gitlab`, `github` or `local`; GitHub
    credentials and ref refresh (M1.1 Stage C has landed) · gh
32. forge-and-ci 2.27 (reduced) — `l4 init --ci github|both` writes `.github/workflows/l4.yml` beside the shim and
    refuses to overwrite without `--force` (it touches `init.py`; M1.1 Stage C has landed) · gh
33. M14-G4 (gap) — the simulation driver is the real orchestrator · sim
34. simulation-harness 1.10 + 1.11 + 1.12 — the manifest of the 21 L4-SIM-003 names with owner and ready/pending
    status, and the YAML scenarios.
    * Ready: `happy-openspec`, `happy-kiro`, `stuck-clarifier-answers` (the "blocked-clarified" case) and
      `stuck-human-answers`.
    * Written, but pending on their owners' features: `quota-fallback` (needs the fallback chains of the Q9
      increment) and `verify-fail-fix-pass` (needs fix units).
    * `l4 simulate [SCENARIO…|--all] [--keep] [--json]` exits 1 on any failure; pending scenarios never change the
      exit code · sim
35. simulation-harness 2.7 (reduced) + bootstrap-core 1.17 wiring — `l4 plan`:
    * `--detailed-exitcode` (exit 10 when something is actionable);
    * the CI outputs written;
    * `--probe`, through an `AvailabilityView`: `NullAvailability` says `unknown`, or reads the cool-down cache once
      M1.2's `CooldownRegistry` (`$L4_CACHE/availability.json`) exists; `--probe` runs binary → auth → hello for the chain heads that the next action needs,
      in a scratch directory · sim
36. simulation-harness 2.5 + 2.6 + 2.8 (reduced) — `l4 run --dry-run [--probe]` (`l4/sim/dryrun.py`). It plans, then
    for each actionable unit renders the next step's prompt from the unit snapshot into
    `.l4-out/dry-run/<run-id>/<unit>/<task>-<phase>.prompt.md`, and prints:
    * the implementer argv (`build_command`) and the gate commands, with env names only;
    * the per-unit decision table;
    * `would exit N`.

    No lease, worktree, agent, push or forge write. A spy test asserts zero side effects (SCN-DRY-01/02).

    The dry run does not call `tdd._prompt`: `Workbench` writes files and `_prompt` needs git and the ledger. The
    prompt-hash test (Risks) stays as the guard. The data blocks that M1.2 (previous-attempt, never in a dry run) and
    M1.5 (lessons) add to `_prompt` reach the dry run as follows: M1.5 adds the lessons block to `l4.sim.dryrun`
    when it merges a `main` that contains M1.4 (a merge-time follow-up; parallel-ownership C14) · sim
37. M14-G5 (gap) — WIP snapshots while an agent runs, and `step.finished` · wip
38. state-vcs-locks 1.23 — `reconcile` at the start of `run_unit`. For a `step.started` with no `step.finished`:
    * a commit with that `L4-Step` exists → `MarkFinished`;
    * a WIP snapshot whose parent is the head → `RestoreWip`, then the step re-runs on the restored tree;
    * otherwise → `Rerun`.

    The result is recorded as `step.reconciled{action}` · wip

*Exit B:*

* unit tests pass;
* `l4 simulate happy-openspec happy-kiro stuck-clarifier-answers stuck-human-answers` passes. `happy-kiro` ends
  `in_review` and shows these things:
  * `task.started` for the wave-0 leaf comes first;
  * the optional leaf is never started;
  * both parents are ticked;
  * `tasks.md` differs from the seed only in marker bytes.
* on a copy of the fixture with a slow fake agent, a snapshot exists and the unit branch has no extra commit;
* `doctor --fix` against a fake fetcher installs into a temp home, and a second run makes zero fetches.

### Stage C — exit lines (M1.1 Stage C has landed)

39. M14-G6 (gap) — the GitLab template's first line becomes `l4 doctor --ci --fix` · prov
40. state-vcs-locks 1.29 + scenario `crash-mid-task-resume` — two kill points:
    * SIGKILL between steps;
    * SIGKILL mid-green after a snapshot (`wip_snapshot_interval: 1s` in the scenario config).

    For this scenario the driver runs `l4 run` as a child process, so that it can be killed. The next run reconciles, and there is exactly one green commit for the task, with no lost or duplicated marker ·
    wip
41. simulation-harness 2.2 — `l4 simulate --all` run twice gives identical normalised events (SCN-SIM-01) · sim
42. state-vcs-locks 5.8 + 5.12 (reduced) + the 1.20 row — `l4 resume --unit ID --reason TEXT` for a `halted` unit
    (SCN-RES-01):
    * a new `TRANSITIONS` row: `halted → previous_phase` on `resumed`;
    * `unit.resumed{reason}`, and the breaker counters reset in the fold;
    * a `chore(<unit>): resume [skip ci]` commit, pushed;
    * the `--extend-*` flags exit 2 "not yet" · wip
43. M14-G7 (gap) — the live acceptance test of the protocol below · all

*Exit C:* unit tests and every ready built-in scenario pass, and then the live protocol passes.

## Gaps (no existing task covers them; no tasks.md was edited)

* **M14-G1** (Stage B, spec lane; spec-providers + implementer-tdd-loop + verifier) — Route every unit through its own
  provider:
  * `providers_for` returns the providers that `detect_frameworks` finds for `spec.frameworks: auto` (or those the
    list names);
  * `run_command` alone calls `require_framework`, which exits 14 under `sdd.enforce` when nothing is detected
    (L4-DET-003 names `l4 run`). `plan` and `status` list nothing;
  * `build_services` picks the provider whose `framework` matches the unit id;
  * `status._read_branch(git, tracking_ref, unit_rel, *, parse_tasks=parse_openspec_tasks)` parses `tasks.md` with
    the unit's own framework parser. The keyword's default keeps M1.3's `child_snapshots` call working in either merge
    order. `UnitSnapshot` gains a `tasks_total` property beside `tasks_done`, both over `required()`;
  * `implementer.tasks.required(tasks)` (non-optional tasks) feeds `select_next_step`, which orders leaves by
    `(wave, document index)`, and also `tick_completed_parents`, `check_preconditions` and the snapshot task counts;
  * `collect_sources` also reads `requirements.md` and `bugfix.md`;
  * the intake lint (`scenario_conflicts`) runs for OpenSpec units only;
  * the orchestrator's own pending counts also use `required()` [V, code]:
    * `_discover` (`pending = any(not t.done …)`);
    * `_implement` (`pending = [t.key …]`);
    * the `TaskCounts` of `_outcome`. Only the `tasks=` argument line changes: M1.2 edits the lines around it;
  * `kiro.write_in_progress_marker` and `kiro.write_queued_marker` are logged once per run as ignored.

  test: tests/unit/orchestrator/test_kiro_unit.py::test_kiro_unit_runs_waves_skips_optional_and_ticks_parents (also
  tests/unit/state/test_status_kiro.py::test_kiro_tasks_parsed_from_unit_branch,
  tests/unit/planner/test_next_action_optional.py::test_open_optional_leaf_is_not_pending,
  tests/unit/verifier/test_preconditions_optional.py::test_optional_leaf_does_not_block_step_0; new modules, as
  parallel-ownership rule 2.0.5 requires) — code:
  src/l4/specs/providers.py, src/l4/services.py, src/l4/state/status.py, src/l4/implementer/tasks.py,
  src/l4/implementer/prompt.py, src/l4/verifier/preconditions.py, src/l4/orchestrator.py (lint guard and the
  `require_framework` call, through the sim lane, which owns the file) — verify: uv run pytest tests/unit/orchestrator
  tests/unit/state tests/unit/planner tests/unit/verifier -q
  * Why: `_read_branch` calls `parse_openspec_tasks`, `build_services` takes `providers_for(...)[0]`, and
    `orchestrator.py:189` lints every framework's criteria [V, code].
  * Seven places count `[ ]*` as pending: `facts_of`, `select_next_step`/`_leaves`, `tick_completed_parents`,
    `check_preconditions`, and the orchestrator's `_discover`, `_implement` and `_outcome` [V, code]. A Kiro unit with an optional leaf would therefore plan `implement` forever, with no
    eligible step.
* **M14-G2** (Stage B, prov lane; bootstrap-core 1.14 reduced) — ENV-004:
  * the binary of every profile in every role chain resolves on `harness_path`, and meets `min_version` when one is
    set (compared with `l4.versions.version_at_least` from the seam commit S0; merge `main` first);
  * error for the first profile of `implementer` and `judges`, warn for the rest (SCN-DOC-02);
  * line 29 attaches the agent-CLI `install` fix to it.

  test: tests/unit/doctor/test_checks_env_004.py::test_env_004_head_missing_is_error_fallback_missing_is_warn — code:
  src/l4/doctor/checks_env.py — verify: uv run pytest tests/unit/doctor/test_checks_env_004.py -q
  * Why: runner-provisioning 1.9 attaches installs to ENV-004, which nothing registers (`checks_agents.py`: "ENV-004 …
    is bootstrap-core's and is not registered here") [V].
* **M14-G3** (Stage B, gh lane; forge-and-ci; M1.1 Stage C has landed) — GitHub plumbing outside the client:
  * `forge_wanted` and `make_forge` choose by `forge.type`, then `ci.platform`, then `GITLAB_CI`/`GITHUB_ACTIONS`,
    then the origin host;
  * `forge.type: local` returns `LocalForge` (line 17);
  * `require_token_in_ci` also fails closed (exit 3) under `GITHUB_ACTIONS=true`;
  * `git_auth_config(token_env, username=…)`: `oauth2` for GitLab, `x-access-token` for GitHub.
    `push_auth_config(cfg, environ)` chooses the username by platform internally, so `l4.archive`, which calls it, is
    not edited;
  * `push_url` stays GitLab-only;
  * `refresh_in_ci` also runs under `GITHUB_ACTIONS=true`, because `actions/checkout` never fetches
    `refs/l4/locks/*`.

  test: tests/unit/forge/test_make_forge.py::test_platform_selection_matrix (also ::test_local_forge_for_type_local,
  tests/unit/vcs/test_refresh_github.py::test_github_actions_refreshes_lock_refs) — code: src/l4/forge/base.py,
  src/l4/forge/gitlab.py, src/l4/vcs/refresh.py — verify: uv run pytest tests/unit/forge tests/unit/vcs -q
  * Why: `forge_wanted` is `type in ("auto", "gitlab")`, the helper hard-codes `username=oauth2`, and `refresh_in_ci`
    checks `GITLAB_CI` [V, code].
* **M14-G4** (Stage B, sim lane; simulation-harness) — The simulation driver is the real orchestrator. `run_scenario`:
  * builds `SimRepo`;
  * writes a config with `sandbox: {mode: none, allow_none: true}`, `forge: {type: local}` (a `LocalForge` under the
    temp root), a fake `L4_FORGE_TOKEN`, and one `fake` profile per scripted profile;
  * plans like `run_command`, then calls `run_unit_in_worktree(..., adapters=…)` with the `ScriptedAgent`s, up to
    `max_runs` times;
  * makes a scripted human commit on the remote between runs (`between_runs:`, for `stuck-human-answers`);
  * compares with line 20.

  test: tests/unit/sim/test_driver.py::test_happy_openspec_reaches_in_review_with_the_real_orchestrator (also
  ::test_only_git_and_fixture_gates_are_spawned) — code: src/l4/sim/runner.py — verify: uv run pytest
  tests/unit/sim/test_driver.py -q
  * Why: simulation-harness 1.8 plans a skeleton driver only because the orchestrator did not exist.
  * Outside CI with no token, the forge hooks return None and the unit stops at `verified` [V, `l4.archive.forge_hook`].
* **M14-G5** (Stage B, wip lane; implementer-tdd-loop + state-vcs-locks, L4-IMP-011 reduced) — The
  `Workbench.wip_snapshots(task, phase, attempt)` context manager:
  * it emits `step.started`, which moves there from `tdd.py:265`;
  * while the agent runs, a timer takes `snapshot_wip` every `implementer.wip_snapshot_interval`, and once more when
    the agent returns with changes;
  * on exit it emits `wip.snapshot{shas}` and `step.finished{status}`. Both come from the calling thread, never from
    the timer.

  `tdd.py` wraps `wb.impl.run(request)` in it, a one-line change.

  test: tests/unit/implementer/test_wip_timer.py::test_slow_agent_step_leaves_a_local_snapshot_and_no_branch_commit (also
  ::test_step_finished_follows_every_step_started) — code: src/l4/implementer/workbench.py, src/l4/implementer/tdd.py —
  verify: uv run pytest tests/unit/implementer -q
  * Why: nothing emits `step.finished` today, and no task takes snapshots during an agent run (1.13 builds the snapshot
    function only) [V, code].
  * The context manager keeps the `tdd.py` edit to the agent call site. M1.2 edits `_prompt` (the previous-attempt
    block) and M1.5 edits `_prompt` (data blocks) in the same file, so the three edits do not overlap
    [V, m12-plan and m15-plan Files tables].
* **M14-G6** (Stage C, prov lane; forge-and-ci 1.15 delta + runner-provisioning 1.20 reduced) — The first script line
  of `l4.gitlab-ci.yml` becomes `'.l4/bin/l4 doctor --ci --fix || .l4/bin/l4 ci map-exit $?'`. `l4.yml` keeps
  `doctor --ci`, because hosted runners are disposable.
  * `resolve_self_provision` decides at run time, so the static line equals `doctor_command(cfg, "gitlab")`.

  test: tests/unit/ci/test_template.py::test_first_line_is_doctor_ci_fix (golden updated) — code:
  src/l4/ci/templates/l4.gitlab-ci.yml — verify: uv run pytest tests/unit/ci -q
  * Why: the template is static and M1.1 owns it [V]. `l4 upgrade` (M1.1 G11) re-renders it, so the line reaches
    dummy-agentic with the upgrade.
* **M14-G7** (Stage C exit, live; live-validation) — The checks of the live protocol below as code:
  * one test per step;
  * it reads pipelines, jobs, job artifacts, MRs, labels, branches, `git ls-remote` and file blobs through the read-only
    API, and records the ids.

  test: tests/live/test_m1_4_acceptance.py::test_probe_pipeline_changes_nothing_and_provisions (also
  ::test_kiro_unit_runs_waves_and_hands_off, ::test_dry_run_decision_matches_the_real_first_step; marker `live`,
  needs `L4_LIVE=1`; `L4_LIVE_RECORD` defaults to `/tmp/l4_m1_4_ids.json`) — code: tests/live/test_m1_4_acceptance.py — verify: L4_LIVE=1 uv run pytest
  tests/live/test_m1_4_acceptance.py -m live -q
  * Why: live-validation targets `add-greeting` and the M1 pipeline, not this protocol.

**Doc changes owed** (no build line; SPEC.md is not edited here):

* §15: the code's `CI-001` is the runner insteadOf check [V, `checks_ci.py`], while SPEC's `CI-001` is "CI files present,
  rendered from the pin". One of them needs renaming.
* L4-DOC-002 and runner-provisioning 1.11/1.13: the OpenSpec and Codex prefix is `$L4_HOME/npm`.
* L4-SIM-001: `run --dry-run` exits 0 and prints `would exit N`; in CI the ref refresh is allowed.
* L4-SIM-002: built-in scenarios run with `sandbox.mode: none` and `forge.type: local` against the real orchestrator.
* L4-IMP-011: M1.4 snapshots to a local ref; the `l4-wip/` push waits for fencing.
* L4-STA-001: `step.finished`, `step.reconciled` and `wip.snapshot` join the event list.
* §16.2: the single routed job is the GitHub form too.
* L4-CI-002: on GitHub, hand-off pushes use `forge.token_env` until the App of Q2 exists.
* L4-KSP-001: in M1.4 the in-progress and queued markers are not written.
* §12.0: the `halted → previous_phase` row exists; `escalated` resume waits for fix rounds.

## Simplifications / deferrals

* **Kiro**
  * Only `x` is written; `-` and `~` are read, never written.
  * The prompt lists every criterion of the unit, as OpenSpec does. `_Requirements:_` links feed validation and
    SPEC-004 only.
  * Deferred:
    * fix units as bugfix specs (2.8, 2.9), waiting for fix units;
    * the `kiro.archive_dir` move;
    * `primary_framework` (4.2);
    * the conformance suite (6.3, 6.4);
    * a `kiro-cli` agent adapter (agent-factory).
  * The clarifier context still skips only `openspec/changes/`.
  * A merged Kiro unit gets no archive MR: `MergeDetector.classify` looks only under `openspec/changes/<name>`, so it
    reports ARCHIVED [V, code]. This is correct for state-only archiving, but it is a coincidence; see Risks.
* **Detection** — Spec Kit is detected only. SPEC-002 covers Kiro units only; OpenSpec `validate --all`, SPEC-003,
  SPEC-005, SPEC-006 and SPEC-007 are deferred.
* **Provisioning**
  * Deferred:
    * `install.sh` (1.22);
    * the clean-container e2e (1.23) and the platform matrix (2.5): linux-x64 is the target, darwin is for
      development only;
    * `provision_lock` (2.2), `--fix --dry-run` (2.3), the interrupted-install matrix (2.4), the installer replays
      (2.6);
    * `docs/runner-setup.md` (1.21), and the `.bash_logout` notice in `l4 init`.
  * Root steps and logins are printed, never run.
* **Doctor** — CFG-001/003/004, ENV-005..012, GIT-*, FORGE-*, STATE-* and `doctor.schema.json` are deferred.
* **GitHub**
  * Deferred:
    * App token minting (2.11; Q2 still open), so hand-off pushes use the `forge.token_env` PAT;
    * statuses, check runs and approvals (rest of 2.9), and `workflow_dispatch` continuation (2.10);
    * per-unit matrix jobs;
    * the four-forge conformance suite (2.13), reduced to `LocalForge` + MockTransport tests;
    * the GitLab-only `push_url` workaround stays GitLab-only.
  * The live run is blocked by Q5.
* **Simulation** — Deferred:
  * `--with-repo-config` (2.12–2.14), the `release` gate (2.3) and the `NoRealAgents` socket spy (2.13). A process spy
    in M14-G4 is the reduced form.
  * 15 built-in names stay pending, with their owners.
* **Dry-run** — `run` only: `verify --dry-run` and `init --dry-run` are deferred. There is no `DryRunEffects`
  refactor of the orchestrator; the dry run is a separate read-only path. Prompts cover the next step only.
* **Plan** — `--probe` probes the chain heads only. Without M1.2's `CooldownRegistry`, availability is `unknown`; M1.2's
  in-process `ProbeCache` is not read.
* **Observability** — the full `EventLog` model is reduced to a logging handler plus a ledger mirror. The GitLab
  `artifacts:reports:dotenv` wiring is deferred, but `.l4-out/l4.env` is already inside the artifacts.
* **Crash resume**
  * The snapshot is a local ref: a new runner or a fresh clone loses it, and the step re-runs, as in M0.
  * A fresh agent session is started; session resume (L4-IMP-010) is deferred.
  * A runner lost to another one (SCN-IMP-18) waits for the pushed WIP.
* **`l4 resume`**
  * SCN-RES-01 only. RES-02 needs the budget halts (implementer-tdd-loop 1.24), RES-03 needs fix rounds.
  * Deferred: the `l4:resume` label and the member check (5.13); a local CLI user is trusted.
* **Lease locks** — see Decisions; state-vcs-locks 1.25 and 2.1–2.17 are M2.

## Files

### (a) Owned (new, or edited only by this increment)

```
src/l4/specs/kiro.py, src/l4/specs/detect.py                     # new (spec)
src/l4/specs/base.py, src/l4/specs/criteria.py                   # spec-providers-owned; additive (Task fields, registry, kiro_criteria)
src/l4/doctor/fix.py, src/l4/doctor/checks_spec.py, src/l4/doctor/checks_provision.py   # new (prov, spec)
src/l4/provision/{__init__,runner,catalog,readiness}.py          # new (prov)
src/l4/forge/github.py, src/l4/forge/local.py, src/l4/ci/github.py, src/l4/ci/lint.py   # new (gh, sim)
src/l4/ci/templates/l4.github.yml                                # new (gh)
src/l4/sim/{__init__,fakes,scenarios,remote,runner,dryrun}.py    # new (sim; ScriptedAgent and FakeClock in fakes.py)
src/l4/sim/builtin/manifest.py, src/l4/sim/builtin/scenarios/*.yaml, src/l4/sim/builtin/fixtures/{openspec-basic,kiro-basic}/
src/l4/schema/outcome.schema.json                                # new (sim)
src/l4/vcs/wip.py, src/l4/state/{idempotency,reconcile,resume}.py  # new (wip)
tests/unit/{specs,provision,doctor,forge,ci,sim,vcs,state,implementer,orchestrator,planner}/test_<new>.py
tests/fixtures/specs/kiro/, tests/fixtures/provision/ (SHASUMS256.txt, installer outputs), tests/live/test_m1_4_acceptance.py
docs/live/ (evidence rows of the protocol; live-validation)
```

### (b) Shared files: the exact, additive edit and the owning lane

| File | Edit | Lane | When |
|---|---|---|---|
| `src/l4/config/schema.py` | new field `CiCfg.self_provision: Literal["auto"] \| bool = "auto"` | prov | A (line 8) |
| `src/l4/doctor/registry.py` | `CHECK_MODULES` += `l4.doctor.checks_spec`, `l4.doctor.checks_provision` (M1.5 appends `checks_memory` too); `Fix`, `attach_fix`; `run_checks(..., scopes=, unit=)` keyword params | prov | A (12, 13) |
| `src/l4/doctor/run.py` | the `--fix` "not yet" raise is removed; `--ci`/`--unit` passed through; live cost footer | prov | A (12, 13) |
| `src/l4/doctor/checks_env.py` | new ENV-004 check function + registration | prov | B (30) |
| `src/l4/log.py` | `configure_logging` adds the JSONL file handler | sim | A (21) |
| `src/l4/outcome.py` | new `write_ci_outputs`; `with_outcome` calls it; `CommandResult.actionable: Sequence[str] = ()` | sim | A (22) |
| `src/l4/exitcodes.py` | new `plan_exit_code` | sim | A (22) |
| `src/l4/specs/providers.py` | `providers_for` returns the detected providers (OpenSpec + Kiro); signature kept | spec | B (25) |
| `src/l4/services.py` | `build_services`: the provider is the one matching the unit's framework, not `[0]` (one expression) | spec | B (25) |
| `src/l4/state/status.py` | `_read_branch(…, *, parse_tasks=parse_openspec_tasks)`; `UnitSnapshot.tasks_done` counts required tasks, and a new `tasks_total` property follows it. M1.3 adds `UnitSnapshot.children` and `child_snapshots` in the same file | spec | B (25) |
| `src/l4/implementer/tasks.py` | new `required()`; `_leaves`/`_descendants` ignore optional; leaves ordered by `(wave, index)` | spec | B (25) |
| `src/l4/implementer/prompt.py` | `collect_sources` candidates + `requirements.md`, `bugfix.md` | spec | B (25) |
| `src/l4/verifier/preconditions.py` | `pending` uses `required()` (one line) | spec | B (25) |
| `src/l4/planner.py` | `facts_of` counts required tasks (spec delta); `run_plan`: the two "not yet" raises are removed; `--detailed-exitcode`, `--probe` view, `actionable` passed to `CommandResult`. M1.2 edits `next_action` (the `waiting_capacity` row) in the same file | sim | B (35) |
| `src/l4/orchestrator.py` | `run_command`: its first statement becomes the `--dry-run`/`--probe` delegation to `l4.sim.dryrun.run_dry` (`--time-budget` stays exit 2), and `require_framework(...)` goes right after `preflight_run_config(app, cfg)`. M1.3 inserts after `chosen = select_units(...)`. Also: an early return for non-OpenSpec units in `_lint_scenarios`; `required()` in `_discover`, `_implement` and the `tasks=` line of `_outcome` (spec deltas); one `reconcile(...)` call as the first statement in `run_unit`'s `try:` (wip delta). Anchors in parallel-ownership §2.1 | sim | B (36, 25, 38) |
| `src/l4/implementer/workbench.py` | new `wip_snapshots()` context manager | wip | B (37) |
| `src/l4/implementer/tdd.py` | `step.started` emit replaced by `with wb.wip_snapshots(...):` around `wb.impl.run(request)` | wip | B (37) |
| `src/l4/state/lifecycle.py` | new `Trigger.RESUMED`; row `halted → previous_phase` | wip | C (42) |
| `src/l4/state/fold.py` | `unit.resumed` resets the breaker counters | wip | C (42) |
| `src/l4/forge/base.py` | `make_forge`/`forge_wanted`/`require_token_in_ci`/`fetch_auth_config`: `github` and `local` branches | gh | B after M1.1 C (31) |
| `src/l4/forge/gitlab.py` | `git_auth_config(token_env, username="oauth2")` keyword | gh | B after M1.1 C (31) |
| `src/l4/vcs/refresh.py` | `refresh_in_ci` also under `GITHUB_ACTIONS=true` | gh | B after M1.1 C (31) |
| `src/l4/init/init.py` | `--ci github\|both` writes `.github/workflows/l4.yml` | gh | B after M1.1 C (32) |
| `src/l4/ci/templates/l4.gitlab-ci.yml` | first script line `doctor --ci --fix` | prov | C (39) |

No edits: `src/l4/cli.py`, `src/l4/commands.py`, `src/l4/archive.py`, `src/l4/postmerge.py`, `src/l4/ci/sweeper.py`,
`src/l4/state/pending.py`, `src/l4/init/upgrade.py`, `src/l4/ci/render.py` (all in flux in M1.1 Stage C, or not
needed).

## Interfaces

**Provided to other increments**

* `l4.specs.detect.detect_frameworks(repo) -> DetectionResult` and `collect_units`; `ProviderRegistry`;
  `providers_for(cfg, repo, env) -> list[SpecProvider]` with OpenSpec and Kiro; `KiroProvider`.
* `Task.optional`, `Task.wave`, `Task.links`, and `l4.implementer.tasks.required(tasks)`. Every counter of pending
  work must use it.
* `l4.forge.github.GitHubForge` and `l4.forge.local.LocalForge`, which implement `l4.forge.base.Forge`. `make_forge`
  chooses the platform. `l4.ci.github.render_github_ci(cfg)`.
* Doctor: `Fix`, `attach_fix(check_id, fix)`, scopes `ci`/`local`/`live`, `--unit`. Later checks, for example
  GIT-001 prune and FORGE-003 create, attach their fixes here.
* `l4.provision.runner.{Paths, harness_path, find_tool, scrub_env, resolve_self_provision}`; PRV-001 and PRV-002.
* Simulation: the scenario YAML format, and the `BUILTIN[name] = BuiltinEntry(owner, file, ready)` manifest. Another
  increment adds its YAML and flips `ready`. Also `ScriptedAgent` and `run_scenario`.
* `l4.sim.dryrun.run_dry`, `l4.outcome.write_ci_outputs`, `l4.exitcodes.plan_exit_code`, and the JSONL log path.
* `l4.vcs.wip.{snapshot_wip, restore_wip}`, `Workbench.wip_snapshots()`, `l4.state.reconcile.reconcile`, and the
  `step.finished` event.
* `l4 resume` for `halted`.

**Needed from other increments**

* **The seam commit S0** (`parallel-ownership.md` §3.0): `l4.versions` (G2, line 28).
* **M1.1 (Stage C landed, `98e4939`):**
  * the routed `l4` job;
  * `l4 upgrade` (G11), which re-renders `.l4/ci/l4.gitlab-ci.yml`. Request: it also re-renders
    `.github/workflows/l4.yml` when that file exists;
  * `forge/base.py` and `init/init.py` stable before lines 31 and 32;
  * `PendingLedger` and the sweeper unchanged in behaviour.
  * Optional request: `Sweeper` skips non-OpenSpec units explicitly, instead of relying on `MergeDetector` reporting
    ARCHIVED.
* **M1.2 (availability and fallback chains, `docs/plan/m12-plan.md`):**
  * `CooldownRegistry` (`$L4_CACHE/availability.json`, read-only here) for the `AvailabilityView`. When it is absent,
    availability is `unknown`;
  * the chain walk and mid-run fallback (`orchestrator._implement`) that make `quota-fallback` ready;
  * the `KiroCliAdapter` auth probe (`whoami --format json`, logged out → "installed, not authenticated"), which PRV-001
    reuses for the `kiro` row once it lands;
  * the OpenCode adapter: the provisioning catalog installs `opencode` only when a chain names it.

  M1.2 also edits `orchestrator.py` (`_implement`, `_park`, `_outcome`), `planner.py` (`next_action`, `UnitFacts`,
  `facts_of`), `workbench.py` (`commit`) and `tdd.py` (`_prompt`). Each stays at its own anchor
  (parallel-ownership §2.1). Merge `main` into the branch; do not rebase.
* **M1.2's clock:** `quota-fallback` uses `l4.availability.cooldown.FakeClock`. M1.4 merges after M1.2, so M1.4 makes it
  ready at its merge (C3, C19).
* **M1.3 (fix units, verifier 1.18):** `verify-fail-fix-pass` becomes ready. Whichever of M1.3 and M1.4 merges second
  supplies the YAML, flips `ready`, and re-baselines the expected events of the ready scenarios: M1.3's ladder adds
  steps 1, 4 and 4a (C19). Kiro bugfix-spec fix units (2.8) come later; until then `KiroProvider` is not
  `FixUnitCapable`, and a failed Kiro unit is escalated (C10).

## LIVE exit protocol on `example-group/dummy-agentic` through `l4-runner`

**Preconditions:**

* M1.1's live protocol (G13) has passed, so its units are `in_review` or `merged` and plan `none`. It has never run as
  of `98e4939` (parallel-ownership §5.3, L0). The M1.2 and M1.3 protocols have finished.
* **Config levers from earlier protocols are reset in step 1** (parallel-ownership §5.3):
  * `verifier.fix_minor_findings: false` and `roles.verifier_agent: []`, which M1.3's protocol left as `true` and
    `[claude-code]`. This keeps the spend at one judge call; a Kiro unit cannot take a fix unit anyway;
  * if M1.2's protocol already added `profiles.kiro`, keep it and do not add it again.
* The harness pinned by `l4 upgrade` is the `main` commit right after M1.4's merge.
* No unit seeded by another increment is actionable. M1.2 and M1.5 seed OpenSpec changes in the same repository.
  Step 1's `l4 plan --json` must show `implement` for `kiro:add-loyalty-points` only; otherwise P2 waits until the other
  protocols have finished, or their units would run, and spend, in the same job.
* M1.4 is built, `uv run pytest -q` is green, and Exit C holds locally.

**No new credentials:** `L4_FORGE_TOKEN` (`l4-bot`) plus the Claude and Codex logins on the runner [V].

**Spend:** one Codex implementer run of two tasks and one Claude judge call. There is no `--probe`, no `--live`, and no
open question, so the clarifier is never called.

**Pipelines:** two, P1 on a probe branch and P2 on `main`. Humans never merge; the maintainer pushes to the protected
`main`.

0. **Operator, local.**
   * `uv run l4 simulate --all --json` twice: identical normalised events; summary `5 pass, 0 fail, 16 pending`.
   * `uvx --from actionlint-py actionlint` on `l4.ci.github.render_github_ci` of the dummy config: no finding, with a
     config file that declares the runner tags (`self-hosted-runner: {labels: [<cfg.ci.runner_tags>]}`, as
     `test_actionlint_is_clean` writes it): without one actionlint rejects the custom `agentic` label as unknown. The
     `actionlint-py` packaging is [I]; a Go `actionlint` binary does the same.
1. **Operator, local**, on a clone of dummy-agentic `main`:
   * Run `uv run --project <harness> l4 upgrade --harness <harness>`. Expected: only `.l4/vendor/`, `.l4/ci/`,
     `.l4/bin/l4` and the two pin scalars change. The template's first line now reads `doctor --ci --fix`.
   * Edit `.l4/config.yaml` and add the Kiro seed (texts below). Also reset M1.3's levers (`verifier.fix_minor_findings:
     false`, `roles.verifier_agent: []`); see Preconditions.
   * `l4 plan --json` lists `kiro:add-loyalty-points` with next action `implement` and tasks `0/4`. The optional `1.2`
     is not counted.
   * `l4 doctor`: SPEC-001 says "openspec, kiro"; SPEC-004 passes.
   * Commit C1: "M1.4: upgrade the harness, detect Kiro, seed add-loyalty-points".
2. **Operator:** push only the branch `probe/m14` = C1 + C2. C2 replaces `.gitlab-ci.yml` with the probe job and adds
   `ci/m14-probe.sh` (texts below). The branch name is outside `l4/**`, so no `l4` job runs.

   Expected P1 (push, `probe/m14`): one job `m14-probe` on runner #12, success, with every result under
   `.l4-out/probe/` in the artifacts.
   * `plan exit 10` (`--detailed-exitcode`). The JSON has `kiro:add-loyalty-points` `implement`. `plan.env` holds
     `L4_EXIT=10` and `L4_UNITS_ACTIONABLE=1` (a count; only the Kiro unit is actionable).
   * `dryrun exit 0`:
     * its last line is `would exit 0`;
     * the decision table names `kiro:add-loyalty-points`, task `2.1` (wave 0), phase red, implementer `codex`,
       availability `unknown`;
     * `.l4-out/dry-run/<run-id>/kiro-add-loyalty-points/2.1-red.prompt.md` contains `Req 1.1`;
     * the job log has no `agent.session` and no `availability.selected`.
   * `simulate exit 0`: `happy-openspec` and `happy-kiro` pass.
   * `doctor-unit exit 0`: only global and `kiro:add-loyalty-points` rows.
   * `fix1 exit 0`, with a scratch `L4_HOME`/`L4_CACHE` outside the project dir:
     * `openspec 1.14.0 → <scratch>/home/npm` is `applied`, and ENV-003 passes in the same report;
     * uv, node, claude and codex are `already present`. Only CLIs that some role chain uses are listed, and the
       runner's Node 22.23.3 satisfies NODE_MIN [V, pipeline #2525], so Node is not installed;
     * PRV-002 passes, since bubblewrap is present;
     * PRV-001 shows `claude-code ready` and `codex ready`. The `kiro` row, `installed-not-authenticated` with the
       printed `kiro-cli login` step, is [U]: it depends on M1.2's recording of a logged-out `kiro-cli whoami --format
       json` (its G14). Without that recording, the row says `unknown` and the step is not failed.
   * `fix2 exit 0`: every action is `already present`, and the fetch count is 0.
   * The script prints `refs unchanged`: `git ls-remote` of `refs/heads/l4/*` and `refs/l4/*` is the same before and
     after.
   * It prints `sudo never called`, and no token shape appears under `.l4-out/` (JSONL logs included).
   * Afterwards the operator reads the MR list: no MR for `l4/kiro/add-loyalty-points`.
3. **Maintainer:** push C1 (without C2) to `main`.

   Expected P2 (push, `main`): job `l4`.
   * **a. doctor.** The log shows `l4 doctor --ci --fix`. Every install action is `already present`, with no download
     line. PRV rows as in 2, exit 0.
   * **b. plan --sweep.** `kiro:add-loyalty-points implement`; every M1.1 unit `none`.
   * **c. run.** The Kiro unit runs first (`select_units` sorts by id, `kiro:` before `openspec:`).
     * The ledger is under `.kiro/specs/add-loyalty-points/.l4/ledger/`.
     * `task.started 2.1` comes before `task.started 1.1` (waves).
     * Commits: red, then green for 2.1; then red, then green for 1.1, with `L4-TDD` trailers and `[skip ci]`.
     * `1.2` is never started and stays `- [ ]*`. Parents `2.` and `1.` are ticked in their last child's green commit.
     * `git diff <base>..H -- .kiro/specs/add-loyalty-points/tasks.md` changes exactly four marker bytes.
     * One `step.finished` follows every `step.started`.
   * **d. verify.** Step 0 runs `KiroProvider.validate`. The gates pass. The judge gets `requirements.md` and
     `design.md` and returns a verdict for each of the 4 criteria `Req 1.1`…`Req 1.4`. Verdict PASS, and
     `.kiro/specs/add-loyalty-points/verification.md` is committed.
   * **e. hand-off.** H has no `[skip ci]`, and its own pipeline runs the project's `test` job and no `l4` job. MR
     `[l4] add-loyalty-points` is ready, labelled `l4:in_review`, with head = H. The pending ledger is in
     `refs/l4/locks/kiro/add-loyalty-points`.
   * **f. job outcome.** Exit 0. The `.l4-out/l4.env` artifact has `L4_EXIT=0` and the unit's phase `in_review`.
     `.l4-out/logs/<run-id>.jsonl` exists, with no token shape.
4. **Operator, read-only:** P1's dry-run decision (unit, task `2.1`, phase red, profile `codex`) equals P2's first
   `step.started`. P1 left no ref, branch or MR behind.
5. **Optional, HUMAN:** merge the Kiro MR with a merge commit. Expected in the next `main` pipeline:
   * the sweep records `merged` for `kiro:add-loyalty-points`;
   * no archive MR is opened (`MergeDetector` finds no `openspec/changes/add-loyalty-points`);
   * plan says `none`, exit 0.
6. **Optional, blocked by Q5 (no GitHub repository).** In a private test repo, `l4 init --ci github --vendor` and a
   `workflow_dispatch` should show:
   * the workflow is accepted;
   * `doctor --ci` on `ubuntu-24.04` reports the install actions `skipped (github-hosted)` and fails ENV-004 with
     exit 3, rendered `::error::` (SCN-DOC-06);
   * no agent spend.

   A hosted happy path needs agent credentials on GitHub, which is out of M1.4.

**Pass:** steps 0–4 behave as expected. Record pipeline, job and MR ids and the artifacts in `docs/live/README.md`.
Then delete `probe/m14`.

**Seed: `.l4/config.yaml` delta** (merge into the existing `spec:` and `profiles:` blocks; other keys unchanged):

```yaml
spec:
  frameworks: auto      # was [openspec]: detection now finds openspec/ and .kiro/specs/
profiles:
  kiro:                 # reported by PRV-001 only: in no role chain, so never installed or run
    adapter: kiro-cli
    auth: subscription
    vendor: amazon
```

**Seed: `.kiro/specs/add-loyalty-points/requirements.md`**

```markdown
# Requirements Document

## Introduction

Customers earn loyalty points on what they buy. A cart's subtotal is the sum of unit price × quantity over its line
items, before any discount code is applied. One point is awarded per whole 10.00 of the subtotal.

## Requirements

### Requirement 1

**User Story:** As a shop owner, I want customers to earn loyalty points on their cart subtotal, so that repeat purchases are rewarded.

#### Acceptance Criteria

1. WHEN a cart's subtotal is 25.00 THEN the system SHALL award 2 loyalty points
2. WHEN a cart's subtotal is 9.99 THEN the system SHALL award 0 loyalty points
3. WHEN a cart has no line items THEN the system SHALL award 0 loyalty points
4. WHEN a cart's subtotal is exactly 30.00 THEN the system SHALL award 3 loyalty points
```

**Seed: `.kiro/specs/add-loyalty-points/design.md`** (no open question, so the clarifier is never called)

```markdown
# Design Document

## Overview

`points_for(subtotal: Decimal) -> int` in `src/pricing/loyalty.py` returns `int(subtotal // Decimal("10.00"))`.
`Cart.loyalty_points()` returns `points_for` of the cart's subtotal: unit price × quantity summed over the line items,
before any discount code. Both names are exported from `pricing`.

## Error Handling

None: line items have non-negative unit prices and quantities, so a subtotal is never negative.

## Testing Strategy

pytest unit tests under `tests/`, at least one per acceptance criterion.
```

**Seed: `.kiro/specs/add-loyalty-points/tasks.md`**. The waves put the rule (2.1) before the cart method (1.1), against
document order. `1.2` is optional.

````markdown
# Implementation Plan

- [ ] 1. Loyalty points on the cart
  - [ ] 1.1 Add `Cart.loyalty_points()` returning `points_for` of the cart's subtotal (before any discount code)
    - _Requirements: 1.1, 1.2, 1.3_
  - [ ]* 1.2 Write property-based tests for `Cart.loyalty_points()`
    - _Requirements: 1.4_
- [ ] 2. Points rule
  - [ ] 2.1 Add `src/pricing/loyalty.py` with `points_for(subtotal: Decimal) -> int` (one point per whole 10.00) and export it from `pricing`
    - _Requirements: 1.1, 1.2, 1.4_

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["2.1"]}, {"id": 1, "tasks": ["1.1", "1.2"]}]}
```
````

**Probe: `.gitlab-ci.yml` on `probe/m14`** (replaces the project's file on that branch only)

```yaml
m14-probe:
  tags: [agentic]
  timeout: 30m
  variables:
    GIT_DEPTH: "0"
  script:
    - bash ci/m14-probe.sh
  artifacts:
    when: always
    paths: [.l4-out/]
    expire_in: 1 week
```

**Probe: `ci/m14-probe.sh`**

```bash
#!/usr/bin/env bash
# M1.4 probe: plan exit code, dry run, simulation, unit-scoped doctor, scratch provisioning twice. Spends no agent tokens.
set -u
L4=.l4/bin/l4
S="${CI_BUILDS_DIR:?}/.l4-m14-${CI_JOB_ID:?}"          # outside the project dir: cache_root refuses the repo
OUT=.l4-out/probe
mkdir -p "$S/shim" "$OUT"
printf '#!/bin/sh\necho "sudo $*" >> "%s/sudo.log"\nexit 1\n' "$S" > "$S/shim/sudo"; chmod +x "$S/shim/sudo"
refs() { git ls-remote origin 'refs/heads/l4/*' 'refs/l4/*' | sort; }
step() { n=$1; shift; "$@" > "$OUT/$n.out" 2> "$OUT/$n.err"; echo "$n exit $?" | tee -a "$OUT/summary.txt"; }
refs > "$OUT/refs-before.txt"
step plan "$L4" plan --json --detailed-exitcode
cp .l4-out/l4.env "$OUT/plan.env" 2>/dev/null || echo "no l4.env" | tee -a "$OUT/summary.txt"
step dryrun "$L4" run --dry-run
step simulate "$L4" simulate happy-openspec happy-kiro --json
step doctor-unit "$L4" doctor --ci --unit kiro:add-loyalty-points --json
step fix1 env L4_HOME="$S/home" L4_CACHE="$S/cache" PATH="$S/shim:$PATH" "$L4" doctor --ci --fix --json
step fix2 env L4_HOME="$S/home" L4_CACHE="$S/cache" PATH="$S/shim:$PATH" "$L4" doctor --ci --fix --json
refs > "$OUT/refs-after.txt"
if cmp -s "$OUT/refs-before.txt" "$OUT/refs-after.txt"; then echo "refs unchanged"; else echo "REFS CHANGED"; fi | tee -a "$OUT/summary.txt"
if [ -s "$S/sudo.log" ]; then echo "SUDO CALLED"; else echo "sudo never called"; fi | tee -a "$OUT/summary.txt"
if grep -rEq 'glpat-|glptt-|gldt-|password=' .l4-out; then echo "TOKEN SHAPE FOUND" | tee -a "$OUT/summary.txt"; fi
rm -rf "$S"
! grep -qE 'REFS CHANGED|SUDO CALLED|TOKEN SHAPE FOUND' "$OUT/summary.txt"
```

## Risks

* **Collisions while building.** M1.1 Stage C has landed, so lines 31, 32 and 39 no longer wait. The parallel
  increments M1.2, M1.3 and M1.5 share files with M1.4. Every shared edit stays at the anchor in
  `parallel-ownership.md` §2.1, and new tests go in new modules.
  * `tdd.py` is also edited by M1.2 and M1.5 (`_prompt`, the `RunRequest` arguments) and by M1.3 (the `extra` env
    line). M1.4 changes only the `step.started` and `wb.impl.run` lines.
  * `orchestrator.py` takes M1.4's one-line deltas through one owner. M1.2 and M1.3 edit other lines, separated by at
    least one untouched line.
* **Kiro parse divergence.** The regex is from the Kiro IDE 1.2.4 bundle [V]. Parent numbering `1.`, and waves given
  as anything other than the `{"waves":[{id,tasks}]}` form, are [I]: an unreadable graph falls back to document order,
  so live step 3c would then show 1.1 first. That is a FAIL of the waves observable, not of the unit.
* **EARS criteria and the intake lint.** The lint is guarded to OpenSpec. Without the guard, `scenario_conflicts` on
  EARS text is untested [I].
* **A merged Kiro unit classifies ARCHIVED only by accident** (no `openspec/changes/<name>`). An OpenSpec change of the
  same name would flip that. The explicit sweeper guard is requested from M1.1.
* **`doctor --ci --fix` runs in every pipeline.** With everything present it uses no network; P2 step 3a must show it.
  With a tool missing and the network down, the job stops at exit 3 by design, before any spend.
* **Codex may not implement 2.1 alone first.** The red prompt lists all four criteria (no per-task filter). An agent
  could stub `Cart.loyalty_points` in 2.1's red. The protected revert and `classify_red` still hold [V, M0], but the
  diff may be larger than the task.
* **GitHub is untested live** (Q5).
  * Custom refs and `--force-with-lease` to `refs/l4/locks/*` on GitHub are [U]; the pending ledger depends on them.
  * The PAT hand-off deviates from L4-CI-002 until the App exists.
  * The `contains(head_commit.message, 'L4-Run: ')` rule also skips a human commit that quotes the trailer [I].
* **Simulation gates run unsandboxed** (`mode: none`). They are packaged fixture gates only; `--with-repo-config` stays
  deferred, so a user's gates never run there.
* **The dry-run prompt can drift from the real one**, because it is built outside the `Workbench`. A test compares the
  dry-run red-prompt hash with the real red prompt on the fixture.
* **Crash resume is proven in simulation only.** The local WIP ref does not survive a new clone or runner. A live kill
  test is not in the protocol, because it would cost a third pipeline and a deliberately cancelled agent run.
* **Budget.** 43 of 45 lines fit only because lease locks and fencing, the WIP push, GitHub App tokens, Kiro fix units,
  `--with-repo-config` and the OpenSpec-wide SPEC checks are deferred.
