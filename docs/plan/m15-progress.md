# M1.5 progress (increment `m15`, Stages A and B)

| line | change task | status | commit | note |
|---|---|---|---|---|
| 1 | M15-G1 runner-provisioning: `prereqs.sh` PRQ-13 warm, PRQ-14 path, PRQ-18 `--with-laya` | done | 7476458, e0c5463 | applied on the runner; `--check` reports PRQ-13, 14, 18 OK (docs/runner/prereqs-2026-10-04-*-m15-*.txt) |
| 2 | spikes 2.2 (reduced) + M15-G2: `ci-probe-m15.sh`, live on `probe/m15` | done | e0c5463, 73e572b | pipeline 2549, job 5430, branch deleted. P1 no change, P2 runner (`engine: laya-local`, maintainer override 2026-10-04), P3 300 approx-tokens. Recorded in docs/runner/README.md and ci-probe-m15-2026-10-04-pipeline-2549.txt |
| 3 | bootstrap-core 1.4 delta: `MemoryCfg`, `SerenaCfg`; `memory` leaves `OPAQUE_SECTIONS` | done | 1c463b7 | SPEC 3.2 `memory:` example loads; `defaults.py` constants added. dummy-agentic's `.l4/config.yaml` not read (see open problems) |
| 4 | memory-lessons 1.1, 1.2, 1.3 | done | 536efe5 | `l4/memory/lessons.py` |
| 5 | memory-lessons 1.11 | done | 536efe5 | `render_lessons`, `write_lessons` (atomic) |
| 6 | memory-lessons 1.4, 1.5 | done | 536efe5 | `select_lessons`, `build_lessons_block` (`l4/memory/inject.py`) |
| 7 | memory-lessons 1.6, 1.7, 1.8 | done | 536efe5 | `inject_for_task`, `task_paths`; the 1.12 integration test is Exit C |
| 8 | memory-lessons 1.10 | done | 536efe5 | `l4 lessons list|lint`; `tests/unit/cli/test_dispatch.py` stub tuple loses `"lessons"` |
| 9 | agent-factory 6.2 | done | db36e3d | `SystemOneBackend`, wire + `.l4-out/logs/system-one.jsonl` |
| 10 | agent-factory 6.3 | done | db36e3d | `LayaServe` |
| 11 | M15-G3 | done | db36e3d | `open_s1_backend` |
| 12 | M15-G4 | done | 9541b0b | `l4/gates/e2e.py`, `e2e_launch.py`, `tests/fixtures/web/` |
| 13 | verifier 6.1 (reduced) | done | 94d20b8 | `l4/verifier/playwright.py` |
| 14 | M15-G5 | done | 94d20b8 | `l4/verifier/e2e_trace.py` |
| 15 | memory-lessons 3.1 (reduced, D5) + M15-G6 | done | 0bc8c44 | `l4/memory/curate.py`: `LessonCandidate`, `LESSON_RULES` (`ui-criterion-without-e2e-test`), `candidates_from_round`, `curate`, `apply_candidates` |
| 16 | memory-lessons 3.2 | done | 0bc8c44 | `guard_violation_candidates` (same `guard.violation` rule in at least 2 distinct runs); `human_edit` is an origin `curate` accepts (its caller, `l4 lessons promote`, is deferred) |
| 17 | memory-lessons 3.4, 3.5 | done | 0bc8c44 | reinforce (count + 1, date); over the caps the least recently reinforced others go to `_archive/<id>.md` |
| 18 | memory-lessons 3.11, 3.12 | done | 0bc8c44 | `l4/memory/commit.py` `commit_memory_change`; `lessons.curated{action, id, origin}` from `apply_candidates` |
| 19 | memory-lessons 4.1, 4.2, 4.3 | done | cd1c93e | `l4/memory/serena.py`: `serena_argv`, `serena_env`, `render_project_yml`, `mcp_timeouts`, `mcp_server_for`; `McpServer.env` added in `agents/base.py` (see deviations) |
| 20 | memory-lessons 4.4, 4.6 | done | cd1c93e | `check_serena` (version pin by `serena --version`, then an MCP `initialize`, both through the agent wrapper) |
| 21 | clarification-loop 2.1 | done | 6cb0f8e | `SystemOneJudge` in `l4/llm/system_one.py`; wired into the router in line 28 |
| 22 | verifier 4.1, 4.2 | done | 1723574 | `l4/verifier/s1.py` `run_s1`; own `S1Outcome` status (`StepStatus.unavailable` arrives in group 2) |
| 23 | verifier 4.3 | done | 1723574 | `record_calibration`: `$L4_CACHE/s1-calibration.jsonl` plus `.l4-out/s1/<run-id>.jsonl`; nothing for unavailable criteria |
| 24 | verifier 6.2 | done | aef3170 | `playwright.base_checkout` (detached worktree, setup there, removed in `finally`); `gates.e2e.run_gate_at` |
| 25 | verifier 3.9 (reduced, D2) | done | aef3170 | `l4/verifier/generate.py` `generate_ui_test`, `generate_ui_tests`; S0 merged from `m1x-seams` (see deviations) |
| 26 | verifier 3.10 | done | aef3170 | `not_testable`, `uncollectable`, two non-discriminating attempts, `fails_at_head`, `lint_failed`, `writer_failed`: the criterion stays uncovered |
| 27 | verifier 6.3 + 5.3 (reduced) | done | aef3170 | `playwright.failure_artifacts`; `UiGeneration.paths` is what the per-round commit (line 34) takes; no commit here |

| 28 | clarification-loop 2.3 + decision 3 (redesigned S1) | done | 5520fd3 | `build_s1_judge` opens a usable `backend: system-one` profile first (`SystemOneDecisions`), else the stand-in, else `NoS1`; `S1Judge` is now `gates/route/support/close`; the SPEC yes/no questions stay with the stand-in (`AskJudge`) |
| 29 | M15-G7 | done | 38bfc9f | `McpServer.env/startup_timeout_s/config_entry`; Codex `-c mcp_servers.<n>.*`; Claude `--mcp-config <agent tmp>/mcp.json` + `mcp__<n>` allow rule |
| 30 | implementer-tdd-loop 1.13 delta | done | 38bfc9f | `tdd._lessons`; block after answers, before previous-attempt; `prompt.rendered.lessons`; same block in `sim.dryrun` (parity test) |
| 31 | workbench delta | done | 38bfc9f | `Workbench.mcp_servers(env)`, `_SERENA_CHECKED` per run id; `HARNESS_EXCLUDES` += `.serena/cache/`, `.serena/project.local.yml` |
| 32 | memory-lessons 1.9 | done | 38bfc9f | SCN-MEM-02 test only |
| 37 | sandbox-security delta | dropped | - | P1: no change |
| 39 | memory-lessons 5.1 + bootstrap-core 1.16 delta | done | 38bfc9f | `doctor/checks_memory.py`: MEM-001, ENV-006, ENV-007, ENV-008 (Serena pin only; gitleaks half deferred), all warn |

Line 37 (`--tmpfs /dev/shm`) is dropped: P1 says no change.

## Verified facts that later lines rely on

* dummy-agentic's `.l4/config.yaml` has no `memory:` key; it loads under the new strict schema (checked against a fresh
  clone at `main`).
* P1 no change, P2 runner (`engine: laya-local`, maintainer override 2026-10-04), P3 300 approx-tokens (prose 540, JSON 340, code 300 within 463 Laya tokens).
  The effective S1 cap is `min(verifier.s1.max_state_tokens, 300)`; lines 22 and 28 must apply it.
* P2 was first recorded as the Mac; the maintainer overrode it (VM ballooning up to 10 GB, main `fad71b5`): Laya runs
  on the runner with `engine: laya-local`, nothing has to be started on the Mac, and the seeded live config uses
  `engine: laya-local`. Live S1 steps need about 2.5 GB of headroom next to the job. (`192.0.2.10:8000` accepted TCP,
  8765 and 22 refused; port 8790 was never probed. Only relevant for the `remote` escape hatch.)
* Serena inside the agent sandbox (line 19, `serena_env`): `UV_TOOL_DIR` must name a writable directory under the
  agent tmp (`uvx` dies under the read-only HOME), and a generated `serena_config.yml` needs `projects: []` next to
  `base_modes: [editing]`. The host-side Pyright warm (PRQ-13) warms the runner user's uv cache only and is invisible to the sandbox (Stage C: mount a shared read-only uv cache, or do not rely on the warm), whose `UV_CACHE_DIR` is the
  empty per-unit cache: a cold Pyright costs about 2 s with network.
* The runner reported 5 to 9 GB RAM across the runs (the README's 3.8 GB is stale), with about 1.1 GB of another user's
  OpenCode resident. Laya's 2.48 GB peak fits the ballooning VM (P2 = runner).

## Interfaces provided (as written)

* `l4.config.schema`: `MemoryCfg(enabled, lessons_file, max_lessons, max_bytes, serena: SerenaCfg(enabled, version, context))`.
* `l4.memory.lessons`: `lesson_id`, `Lesson`, `LessonsFile(lessons, header)`, `EMPTY_TEMPLATE`, `parse_lessons -> ParseResult(file, problems)`,
  `render_lessons`, `write_lessons(path, file) -> bool` (False: unchanged), `select_lessons(file, task_paths, task_kinds=())`, `lint(file, *, max_lessons, max_bytes, archived_ids=())`.
* `l4.memory.inject`: `build_lessons_block(lessons, redact=)`, `inject_for_task(worktree, cfg: MemoryCfg, task_paths, task_kinds=(), writer=None, *, redact=) -> Injection(block, ids, bytes, skipped)`,
  `task_paths(task_line, changed_files=())`, `read_lessons_file(worktree, relative)`. The caller passes `redact=app.redactor.redact_text`.
* `l4.llm.system_one`: `Question(kind, instructions, criteria=None)`; `SystemOneBackend(engine, *, model, base_url, api_key, serve, transport, log_path, redactor)`
  is a context manager (`start()`/`stop()`), `.ask(state, {id: Question}) -> {id: p}`, `.query(...) -> Reply`; `SystemOneUnavailable`;
  `LayaServe(argv, environ, *, model, threads, ready_timeout_s, stop_grace_s)` as `with ... as base_url`;
  `open_s1_backend(cfg, role="s1_judge", events=None, *, environ=None, client=None, log_path=None, redactor=None)` returns the backend **stopped**
  (the caller starts it around the S1 work) and raises `RoleUnavailable` (exit 12). The S1 log is redacted only if the caller passes `redactor=`.
* `l4.gates.e2e`: `run_e2e(wb, worktree=None, *, name="e2e", must_contain=()) -> E2eRun(gate: GateResult, snapshot: Path | None)` with `.report`;
  `e2e_configured(cfg)`, `launcher_command(gate, base_url_env)`, `SNAPSHOT_RELPATH`. A server that never gets ready raises `L4Exit(INTERNAL_ERROR)`;
  a misconfigured gate raises `L4Exit(USAGE_ERROR)`.
* `l4.verifier.playwright`: `playwright_enabled(cfg)`, `unit_changed_files(git, base_sha, head="HEAD")`, `ui_files(changed, ui_paths)`, `ui_facing_criteria(criteria, changed, ui_paths)`.
* `l4.verifier.e2e_trace`: `trace_e2e(criteria, report, *, max_criteria_per_test=3) -> list[Criterion]` (the uncovered ones), `e2e_coverage(...) -> {criterion id: [test ids]}`.

## Deviations and reconcile points

* `E2eGate` defaults to `format: playwright-json` and `reports: []`; `run_e2e` refuses both (exit 2). The hand-seeded live config
  (protocol step 1) must set `format: junit` and a `reports` entry, plus `serve.command`, `serve.ready_url` and `command`.
* `run_e2e` calls `l4.gates.runner.run_gate` itself (it needs another worktree, `network=False` and `format=junit`) and `wb._next_gate_log`.
  It will not pick up M1.3's C13 `run_gate(extra_env=)` or `event_context`: a group-2 reconcile point.
* `E2eRun` has `gate` and `snapshot`; `report` is a property of `gate.report` (plan: `E2eRun(gate, report, snapshot)`).
* `trace_e2e` returns the uncovered criteria; `e2e_coverage` is the added map.
* `open_s1_backend` walks every `backend: system-one` profile of the chain and returns the first usable one (plan: "the first"), recording the others under `skipped`.
* `l4 lessons lint` exits 3 when it finds problems (`list` exits 0 and warns on stderr).
* Memory-lessons 1.9 and 1.12 belong to Stage C (line 32 and Exit C), not built.
* Shared files touched: `config/schema.py` and `config/defaults.py` (additive, plus `OPAQUE_SECTIONS`), `tests/unit/cli/test_dispatch.py`
  (`"lessons"` left the stub tuple), `docs/runner/README.md`.

## Stage B: interfaces provided

* `l4.memory.curate`: `LessonCandidate(dedupe_key, title, scope_globs, scope_kinds, source, body, origin)`, `LESSON_RULES`, `UI_GAP_KEY`, `UI_GAP_TITLE`,
  `candidates_from_round(result, cfg, *, changed_files=(), generated_criteria=()) -> list[LessonCandidate]`,
  `guard_violation_candidates(events, *, min_runs=2)`, `curate(file, candidate, cfg: MemoryCfg, today) -> CurationResult(file, action, lesson_id, archived)`,
  `apply_candidates(worktree, cfg: MemoryCfg, candidates, writer=None, *, today=None) -> list[str]` (the changed repository-relative paths; refuses, with a
  `lessons.curated{action: refused}` event, a lessons file it could not parse in full).
* `l4.memory.commit.commit_memory_change(git, paths, *, unit, run_id, iteration, detail, identity=BOT_IDENTITY) -> str | None`.
* `l4.memory.serena`: `serena_context(adapter, configured="auto")`, `serena_argv(binary, context, project)`, `serena_env(tmp) -> dict` (writes
  `serena-home/serena_config.yml`; call it AFTER `reset_agent_tmp`), `mcp_server_for(adapter, worktree, tmp, *, cfg: SerenaCfg, binary) -> McpServer | None`,
  `mcp_timeouts(adapter) -> McpTimeouts(startup_ms)`, `render_project_yml(existing)`,
  `check_serena(binary, worktree, tmp, *, adapter, cfg, wrap, environ, events=None, timeout_s=60) -> SerenaStatus(ok, reason, startup_ms)`.
* `l4.llm.system_one.SystemOneJudge(backend)`: `.source == "system_one"`, `.ask(S1Query) -> float`, `.close()`. It starts the backend lazily.
* `l4.verifier.s1`: `effective_budget(cfg)`, `run_s1(backend, criteria, evidence: {criterion id: Evidence(tests, excerpt)}, *, budget) -> S1Outcome(criteria, status)`,
  `record_calibration(outcome, CalibrationContext(cache_file, run_file, unit, run_id, round), *, model, deterministic, judge) -> int`.
* `l4.gates.e2e.run_gate_at(wb, tree, spec, *, network) -> GateResult`; `l4.verifier.playwright`: `base_checkout(wb, base_sha)` (context manager),
  `failure_artifacts(tree, report, *, directory="test-results")`.
* `l4.verifier.generate`: `generate_ui_tests(wb, judge, gaps, *, base_sha, ui_diff, snapshot, writer_profile=None, implementer_profiles=()) -> UiGeneration(outcomes)`
  with `.paths`, `.uncovered`, `.cost_usd`; `generate_ui_test(...) -> GeneratedOutcome`; `ui_gap_finding(criterion) -> Finding` (title `UI_GAP_TITLE`);
  `require_independent_writer(cfg, implementer_profiles, profile)`.

## Stage B: deviations and reconcile points

* **S0 came from `m1x-seams`, not `main`.** The seam commit is on branch `m1x-seams` (3 commits, new files only, same base `f4f9803`); `main` does not have it.
  `m1x-seams` was merged into `m15` (a merge commit) before line 25. Nothing else of `main` was merged.
* `candidates_from_round` takes `changed_files` and `generated_criteria` keywords: `VerifyResult` has no `generated` field before group 2 and
  `types.py` is not edited in Stage B. The Stage C curation call passes `changed_files=unit_changed_files(...)` and the criteria of `UiGeneration.paths`' outcomes.
  The finding and the rule agree through `UI_GAP_TITLE`: `generate.ui_gap_finding` creates it, `LESSON_RULES` matches it.
* `McpServer.env` was added to `agents/base.py` (one additive line, planned for line 29), because `mcp_server_for` has to carry `SERENA_HOME` and `UV_TOOL_DIR`.
  Line 29 only has to emit it in the two adapters.
* memory-lessons 4.6's `test_version_mismatch_is_soft_failure` is in `tests/unit/memory/test_serena.py` (the parametrized failure test covers the rest of 4.4).
  The pin is checked with `serena --version` (through the same wrapper; the probe log shows it prints `Serena 1.7.0`): the MCP `serverInfo.version` is the MCP SDK's (1.28.1 in the probe), not Serena's.
* `SystemOneJudge` lives in `l4/llm/system_one.py` (plan, owned file), not `router.py` as the task says. `system_one` imports `S1Query` only under
  `TYPE_CHECKING` and `S1Unavailable` inside `ask()`, so the router (line 28) can import `SystemOneJudge` at module level without a cycle.
* `run_s1` has its own status type (`ok`/`unavailable`); `StepStatus.unavailable` and `CriterionOutcome.s1_p` arrive in group 2.
  After the first server error the remaining criteria are not asked (each would wait out its own timeout).
* `generate_ui_test` uses `request_test(..., kind="e2e")` from S0, writes the test into both trees, lints with `gates.lint` in the head tree (the project's commands as
  configured), and judges discrimination from the JUnit ids of the e2e runs (`e2e_coverage` of the one criterion), so no `must_contain` list is needed.
  `run_e2e` names its gates `e2e-base` and `e2e-head` there.
* `tests/unit/_web_helpers.py` and `_web_bench.py` hold the fixture-web-app helpers shared by the gate and verifier tests (moved out of `test_e2e.py`).
* Live (`L4_LIVE=1`): the real `claude` writer schema test in `tests/unit/verifier/test_generate_live.py` was run once and passed. Written, not run:
  `test_real_playwright_fails_at_base_and_passes_at_head` (needs `pytest-playwright`, which is not in `pyproject.toml`; the merger decides, rule 2.0.6) and
  `tests/unit/llm/test_system_one_live.py` (real `laya-serve`: 3 identical answers, process gone; Laya is not installed here).

## Stage B: notes for Stage C

* Line 29/30: the agent tmp is reset before every request, so call `serena_env(tmp)` (through `mcp_server_for`) after `reset_agent_tmp`.
* Line 34 (`HARNESS_EXCLUDES`): `failure_artifacts` reads the directory named by `--output` in `gates.e2e.command` (`playwright.artifact_dir`; default
  `test-results/` when there is none). The seeded command writes to `.l4-out/e2e/artifacts`, which is already harness output, so no exclude is needed
  for it; add `test-results/` only for a project that leaves the default. The e2e command has to pass `--tracing retain-on-failure --screenshot only-on-failure`.
* Line 28: build the judge as `SystemOneJudge(open_s1_backend(...))` and call `.close()` after the clarifier pass.
* Line 30 and line 28 notes on `check_serena` and the `SystemOneJudge` retry are resolved by the review fixes below.
* `verify.generated` is emitted by `generate_ui_tests` in the live protocol's shape; line 34's ladder row must not emit it again.

## Review fixes (`m1.5(fix)`)

| finding | status | note |
|---|---|---|
| S1 parser rejected real laya `usage` (blocker) | fixed | `Reply.usage` is `dict[str, Any]`, never a reason to drop an answer; golden test with the recorded raw reply; `test_system_one_live.py` goes through `SystemOneBackend.ask` |
| S1 prompts not redacted (blocker) | fixed | `SystemOneBackend.query` redacts the whole request once, wire and log alike; `redactor` is required for `SystemOneBackend` and `open_s1_backend` (Stage C passes `app.redactor`) |
| live Playwright exit cannot pass (major) | fixed | the test provisions `$L4_CACHE/shared/ms-playwright` from the host's browsers and skips with a reason otherwise. Dependencies: not added to `pyproject.toml`; run with `uv run --with playwright==1.63.0 --with pytest-playwright==0.9.0` (decide at merge whether to add an optional group). Verified: 1 passed |
| base `error` accepted as "fails" (major) | fixed | at the base only an assertion failure counts; `error`/`skipped` give the new status `base_error` (retried once with the reason, then `needs_human`) |
| e2e snapshot symlink / symlinked `.l4-out` (major, inferred) | fixed | `run_e2e` refuses a symlinked `.l4-out/e2e` (exit 1) before unlinking and returns `E2eRun.snapshot_text` (regular file, 200 KB, utf-8 `replace`) instead of a path |
| `SystemOneJudge` latch (minor) | fixed | the first failure is kept; later asks raise `S1Unavailable` without touching the backend |
| guard origin misses green-phase events (minor) | fixed | no `rule`: `guard.test_tamper` is "frozen test", `guard.violation` with `phase=green` is "frozen support file"; never the path |
| non-UTF-8 lessons file rewritten (minor) | fixed | strict decode; a `Problem` makes injection skip it and `apply_candidates` emit `lessons.curated{action: refused}` |
| `verify.generated` shape (minor) | fixed | `{criterion, test, base, head, attempts, status, reason, model}`; `GeneratedOutcome.base/head` |
| `apply_candidates` return (minor) | fixed | returns `Applied(paths, outcomes)` (callers: `.paths`) |
| base app cannot be served (minor) | fixed | `ServerNotReady(L4Exit)`; at the base it gives `base_unservable` (no retry, `needs_human`) when the head is served; a head that is never ready still exits 1 |
| exit 97 double duty (minor) | fixed | the launcher also writes `.l4-out/e2e/not-ready`; only 97 plus the marker is "not ready" |
| `LayaServe.stop` with a dead leader (minor) | fixed | always `killpg(SIGKILL)` afterwards; test with a fake that forks a worker and exits |
| `check_serena` environment (minor) | partly | uses the `environ` it is given whole; line 31 must pass `build_agent_env`. The PRQ-13 Pyright warm does not reach the sandbox (per-unit `UV_CACHE_DIR`): to be decided in Stage C (mount a read-only shared uv cache, or drop the claim) |
| README RAM figure (minor) | fixed | `docs/runner/README.md` names the three logged figures (7107, 5254, 5154 MB) |

Stage C group-2 checklist (reconcile points from Stage B, not fixed here): `E2eRun.report` is a property; `trace_e2e` returns the uncovered criteria;
`run_e2e` and `run_gate_at` bypass `Workbench.run_gate` and use `wb._next_gate_log`, so M1.3's C13 `extra_env` and `event_context` do not reach them;
`generate_ui_tests` now requires `writer_profile` and `implementer_profiles` (keyword, no defaults); `McpServer.env` was added
early in `agents/base.py`.

## Review fixes round 2 (`m1.5(fix)`)

| finding | status | note |
|---|---|---|
| step 5 overwrote or deleted an implementer's `e2e/test_l4_c_<hex>.py` (blocker) | fixed | `write_test_file` is called with the default `overwrite=None` on every attempt (replaces only a file with the generated marker); the cleanup unlinks only what this call wrote; regression test with invalid-then-good and invalid-then-wrong replies |
| P2 recorded as Mac (major) | fixed | README and this file now say P2 = runner, `engine: laya-local` (maintainer override 2026-10-04); main is not merged here, so the merger must keep this block over the Mac text |
| `Reinforced` bullet format (major) | fixed | parser reads `N · date` and `N, date`; the writer emits the design's ` · ` form; a new lesson keeps `1 · <creation date>` because the archive order (least recently reinforced) needs the date |
| `failure_artifacts` directory (minor) | fixed | `playwright.artifact_dir(gates.e2e.command)` follows `--output` |
| S1 cap import cycle (minor) | fixed | `defaults.S1_STATE_BUDGET_CAP` and `S1Cfg.laya_budget()`; the clarifier router applies it when the judge's `source` is `system_one` |
| `apply_candidates` events before writes (minor) | fixed | paths are checked and written first, events follow; an `OSError` (incl. a symlinked archive) gives `refused` and `Applied()` |
| calibration hash over the unredacted state (minor) | fixed | `SystemOneBackend.wire_state` |
| `generate_ui_tests` skipped the independence check (minor) | fixed | `writer_profile` and `implementer_profiles` are required |
| live Laya test weaker than Exit B (minor) | fixed (not run: no `laya-serve` here) | raw response bytes compared, `os.killpg(pgid, 0)` must raise `ProcessLookupError` |
| one bad answer dropped the rest of S1 (minor) | fixed | `SystemOneBadAnswer(SystemOneUnavailable)`: only that criterion is unavailable |
| forgeable not-ready marker, missing e2e executable (minor) | fixed | the launcher deletes the marker once the command has run; exit 96 plus marker is a usage error |
| dead `skipped` branch in step 5 (minor) | fixed | removed; a skipped generated test is `uncollectable` (documented, tested) |
| PRQ-14 accepted any chromium (minor) | fixed | `--dry-run` names the wanted revision directories; `--offline` keeps `--check` read-only |
| `render_project_yml` leaked `YAMLError` (minor) | fixed | `ValueError` |


## Stage C group 1 (lines 28-32, 37, 39)

Decisions applied: (1) Laya runs on the runner (`laya-local`), `remote` kept, not used live. (2) Jev profile
`{backend: system-one, engine: jev, model: jev-latest, api_key_env: TYPESAFE_API_KEY}`; the served model is recorded from the reply.
(3) S1 redesign of docs/eval-framework.md 6.3: router = `choice` in both option orders (averaged) + `internal` yes/no; citation = per-citation
`claim`, "shows" and "opposite" yes/no on a window cut around the quote; thresholds `verifier.s1.decisions.{router.technical_min 0.85,
router.internal_min 0.8, citation.support_min 0.9, citation.opposite_max 0.2, criterion.accept 0.9}` (starting values [G], `config/defaults.py`);
Jev gets `max_state_tokens` (450), Laya/remote the 300 cap (`S1Cfg.budget(engine)`). Step 8 (`verifier/s1.py`) asks true/false criteria plus the 4-way
choice, record-only; calibration rows carry `question_set`, `evidence`, `served_model`, `engine`. The clarifier records every raw p on
`clarifier.result` (`p_internal`, `citation_opposite`, `s1_model`, `s1_questions`, `s1_detail`). (4) Serena env: the MCP entry and `check_serena`
both use `serena_run_env(request_env, tmp)`, identical by construction. (5) MCA 2.3(b): every backend log line carries `engine`.

Deviations: `l4/clarifier-answer@2` (required `claim` per citation) and `clarifier@4`; `ports.render_answer_with_citations` shows the claim;
`SystemOneJudge` removed (replaced by `SystemOneDecisions`); `Workbench.mcp_servers` takes the request env; the boolean stand-in's gates are the SPEC
thresholds (`accept_threshold`, `reject_threshold`), the System-One gates are `decisions.*`.
Open: `.serena/project.yml` is never written by the harness (`render_project_yml` has no caller); `margin`/`repeats` (eval-framework 6.4) and project
policy in the criteria are not built; the clarifier's S1 rows go to the ledger (`clarifier.result`), not to `s1-calibration.jsonl`;
Claude/Codex MCP tool approval in non-interactive runs is [U] until the live run.
Doc changes owed (SPEC not edited): L4-CLR-001 (`claim`, `@2`), L4-CLR-002 rule 3-4 and L4-CLR-003 (choice design, opposite check), 3.2 (`remote`
engine, `verifier.s1.decisions`, per-engine state budget, pinned Jev model), 10.2 step 8 (criteria + choice), L4-VER-008 (served model, question set).


## Stage C group 2 (lines 33-36, 38)

| line | change task | status | commit | note |
|---|---|---|---|---|
| 33 | verifier 1.8 delta | done | b1ad3a4 | `gates.run_e2e_gate` (judged like the test gate: failing tests named, zero tests, a missing report and a collection error fail it), called from step 3 after the test gate when `gates.e2e.command` is set; its `GateLine` joins `result.gates`, its tests join `result.tests`. A server that never gets ready is exit 1 |
| 34 | verifier 1.19 delta | done | b1ad3a4 | `LADDER` 0 1 2 3 4 4a 5 8 9 10; `StepStatus` += `unavailable`; step 4 passes the e2e report as `extra_reports` with `generated=` from the ledger; step 5 `_generate_step`; step 8 `_s1_step`; calibration rows after step 9 (`_calibrate`); `CriterionOutcome.tests/s1_p`; `VerifyResult.generated/s1`; the writer role is opened lazily by `writer_for(stem)` (audit and step 5 share it); one `commit_verifier_tests` per round |
| 35 | verifier 1.16 delta | done | b1ad3a4 | matrix: `generated, base X, head Y` inside the Tests cell, an `S1 p` column when step 8 ran, an `Evidence links` column when step 5 ran (test file, traces, page snapshot); sections "Generated UI tests" and "S1"; `verdict.json` keys `generated` and `s1`, restored by `restore_round` |
| 36 | memory-lessons 3.13 (reduced) | done | a3e8baf | `l4/memory/round.py` `curate_round`, called in `verify_hook` after `after_verdict`; test `tests/unit/verifier/test_memory_flow.py::test_finding_becomes_lesson_and_is_injected_later` |
| 38 | preflight delta | done | 686a02f | `roles.verifier_agent` non-empty when `gates.e2e.command` is set and Playwright is not off; system-one profile engine/`base_url`/`api_key_env`; plus (extra) a half-configured e2e gate |

### Decisions and deviations (group 2)

* **Step 3 runs the e2e gate whenever `gates.e2e.command` is set**, also with `verifier.playwright.enabled: false`; `enabled` only governs step 5. The preflight refuses an e2e gate without `serve.command`, `serve.ready_url`, `reports` or `format: junit` (exit 2 before any agent work), where the plan only asked for the `verifier_agent` rule. `run_e2e` still refuses the same things for a caller that bypasses preflight.
* **Step 4 passes `generated=` (never `None`).** A test of the e2e report counts as `generated` only when a `verify.generated{status: accepted}` event of the ledger names it and the file at head still has the recorded `sha256`; any other e2e test is judged like a unit test (red proof, else ignored). An edited generated file is reported (minor finding) and loses the proof. `verify.generated` therefore carries `tests` and `sha256`; `GeneratedOutcome` moved to `verifier/types.py` (re-imported by `generate.py`).
* **Step 5 targets** are the UI-facing criteria that no test of the e2e report traces (`ui_step.plan_generation`; `e2e_trace` is now a wrapper over `trace_ids`, which also reads the `l4` marker). A gap adds the lesson rule's finding (`ui_gap_finding`). A gap that no accepted test closes (no writer, `not_testable`, `non_discriminating`, `fails_at_head`, ...) is a **hold** with a text that has the status and no free text, so the unit is `needs_human` even when a unit test covers the criterion (live protocol retry rule), and a human can accept it.
* `require_independent_writer` and the `writer_profile`/`implementer_profiles` arguments of `generate_ui_tests` are gone: the writer comes from `select_judge(role="verifier_agent")`, which already vetoes same-vendor profiles. `require_independent_judge` stays (parallel-ownership item 6).
* **Step 8 is `not_run`** when `verifier.s1.enabled` is off or `roles.s1_judge` is empty (no `verify.step` event, like step 4a); `unavailable` when no profile opens or the server fails for every criterion (SCN-VER-24); `ok` with a count otherwise. Excerpt per criterion: the diff chunk that shares the most words with it (deterministic). Calibration rows go to `$L4_CACHE/s1-calibration.jsonl` and `.l4-out/s1/<run-id>.jsonl` after step 9, so the row's `judge` column is the judge's word.
* Curation (line 36) also calls `guard_violation_candidates` (L4-MEM-002 b), the only place it has a caller; a PASS that spawned a fix unit curates nothing.
* `integrity.check_suppressions` excuses the paths of accepted `verify.generated` events, as it does for `verify.audit` (M1.3 file, one additive hunk).
* The generated writer code is kept in `verdict.json` only for tests that were not accepted (4 000 characters), never in `verification.md`.


## Stage C review fixes (`m1.5(fix)`)

| finding | status | note |
|---|---|---|
| (c) merge with main | done | `main` merged twice (74c76c2, then 7dbf43a); `claude_code.run` keeps main's `judge_workdir`/`wrap_command` and adds the MCP config for non-judge modes; `dryrun._prompt` passes `data_blocks` and `run_ledger`; the lessons parity test uses `same_run`. `git merge-tree HEAD main` is clean |
| (b) clarifier never auto-accepts with Jev | done by design, NOT re-run live (no Jev key here); `internal` over {question, answer, cited_text} was probed by the reviewer (0.90-0.96 technical), the shipped state also carries `claim`, and `establishes` (gate 0.8) is uncalibrated: if Jev rates it low for true answers nothing auto-accepts | `internal` moved out of the router request into the per-citation request, whose state is now `{question, answer, claim, cited_text}`; `QUESTION_SET` is `clarifier-s1@2`. Replayed-reply tests drive `Router.route` to `auto_accept` for a technical case, refuse a product case (derivable 0.10) |
| citation check never saw the answer | done | new gated question `establishes` ("does `claim`, as shown by `cited_text`, establish `answer` as the answer to `question`?"), gate `verifier.s1.decisions.citation.establishes_min` (starting value 0.8, uncalibrated); regression test with the Q-5 shape (true claim, wrong answer) |
| Serena writes into the worktree | done | `.serena/.gitignore` in `HARNESS_EXCLUDES`; `Workbench.settle_serena_project(base)` puts `.serena/project.yml` back to `base` without a violation when it holds exactly what Serena wrote at the check; anything else is still the agent's violation. Verified live against Serena 1.7.0 (codex and claude-code contexts). The seed text in the plan is not a fixed point of Serena 1.7.0 (Serena adds ~170 lines); the settle step makes the seed's form irrelevant |
| unit-2 clause of Exit C | done | `test_a_second_unit_branched_after_the_first_merged_gets_the_lesson_in_its_red_prompt` |
| gap closed by a generated test spawned a fix unit | done | `fixunit._candidates` skips a `UI_GAP_TITLE` finding whose criterion an accepted generated test closed; the finding stays in the result, so curation still sees it |
| `laya-serve` start/stop not visible | done | INFO log lines `laya-serve started: pid, port, model, laya` and `stopped: pid, exit code` (logger `l4.system_one`) |
| calibration rows could not tell checkpoints apart | done | rows carry `server_version` (the `laya` package version, read by the interpreter the `laya-serve` script names), `state_tokens`, `server_truncated`; `model` (the profile checkpoint) was already there |
| lesson scope ignored committed branch changes | done in the real run; dry run partial | `Workbench.branch_changed_files()` (merge base with `origin/<base_branch>`) joins the working-tree changes; the dry run uses the same helper on `origin/<unit branch>` but reads the lessons from the main checkout; no end-to-end dry-run parity test for it |
| Serena check cache per run only | done | keyed by `(run_id, Serena context)` |

Doc changes owed (SPEC not edited), added by the fixes: L4-CLR-002 rule 3-4 and L4-CLR-003 now differ from the SPEC also by (1) the citation state `{question, answer, claim, cited_text}`, (2) `internal` ("derivable from the project") asked per citation, not on the router state, (3) the `establishes` question and its gate `decisions.citation.establishes_min`; `S1Judge.support` takes `question=`. 10.2 step 8 / L4-VER-008: calibration rows carry `server_version`, `state_tokens`, `server_truncated`.
Left as is: `render_project_yml` still has no caller (the settle step makes the seed's form irrelevant). Not verified: that the Serena the agent's own CLI starts writes the same bytes as the check (the live protocol should show no `.serena/project.yml` `guard.violation` after a real agent step).

## Review fixes, stage C (second round)

| finding | status | note |
|---|---|---|
| e2e runs skipped the gate protections (blocker) | done | `Workbench.run_gate_spec(spec, network, tree=None)` is the one way a gate runs (unit tree or merge-base checkout): purge bytecode, snapshot/restore protected paths (`guard.violation{phase: gate}`), `trace_env()`, ledger restore, full `gate.finished` (passed/failed). `Workbench.run_gate` and `gates.e2e.run_gate_at` both go through it. `generate.py` rewrites the accepted test with the harness's bytes before hashing and committing. Tests: `tests/unit/gates/test_e2e_guard.py`, `test_gate_forgery.py` (e2e case), `test_generate.py` (self-rewrite). NOTE for the merge of main: main's `revert_unsnapshotted(self.git, self.protected, excludes=...)` is not on this branch; add its call in `run_gate_spec` (the single place) when main is merged |
| lessons built from the work-tree copy (blocker) | done | `curate_round` refuses (`lessons.curated{action: refused}`) when the lessons file differs from HEAD and restores it to HEAD (rather than leaving it uncommitted, so a later `add -A` cannot sweep it in); `integrity.check_protected` exempts `.serena/memories/harness/` by commit: only bot-identity commits with `L4-Phase: lessons` (`provenance.foreign_memory_commits`) |
| e2e gate without `trace_env()` (major) | done | same helper; tests for marker criteria reaching the e2e report and for `--strict-markers` |
| `laya_version` trampoline | done | `_script_interpreter` parses the `'''exec` form |
| s1 state budget | done | reserves `question_text(QUESTIONS)` |
| codex MCP override on argv | partial | URL credentials stripped from every value, DEL escaped. The allowlist of Serena variables was NOT done: it could not be checked against a live Serena here, and the rest of the agent env (built without credential variables, SEC-001) still shows in `ps` |
| curation failure fails a PASS | done | `curate_round` catches, logs, emits `refused`, restores the lessons file; the push stays outside the `try` |
| laya-serve log | done | `<log dir>/laya-serve.log`, redacted when the server stops |
| plan seed comment | done | comment corrected (no behaviour change) |
| `memory.serena.context` unvalidated | rejected | already `Literal["auto","claude-code","codex","ide"]` in `SerenaCfg` and covered by `test_memory_cfg.py` (`vscode` is refused) |
| `p_product` mislabel | done | `RoutingDecision.p_technical` and `clarifier.result.p_technical` added; `p_product` stays `1 - P(technical)` with a comment saying what it is |
| s1_judge stand-in test | done | now asks a question and asserts profile `c`; comment with the live `establishes` values |
| `test_proc` flake | done | root cause was the 30 s run timeout (`timed_out=True`, SIGKILL) elapsing under load before the child started, not the SIGINT grace; that test now runs with `timeout_s=300` |
