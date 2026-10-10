# M1.5 — memory, web UI verification and System-One judges (planned 2026-10-04)

## Goal

M1.5 lets the harness learn from its own verification: a deterministic verifier finding becomes a lesson
(L4-MEM-001…005), and that lesson is injected into later prompts and recorded in the ledger. It also lets the verifier
check UIs: a UI-facing criterion with no e2e test gets a Playwright test written by the verifier, and the test counts
only if it is proven discriminating inside the gate sandbox (L4-VER-002 steps 3 and 5, L4-VER-014). Finally it adds
System-One judgments through the TypeSafe wire: Laya runs where it fits and Jev is built but blocked on a key
(L4-FAC-004, L4-VER-002 step 8, L4-VER-008, L4-CLR-002).

## Scope

* **Lessons (SPEC §13, L4-MEM-001…005).** A deterministic verifier finding becomes a lesson in
  `.serena/memories/harness/lessons.md`. The lesson id is a hash of its dedupe key. The curation is visible in the ledger,
  and the lesson reaches the next unit's prompt as `<l4:data kind="lessons">`. Serena 1.7.0 is wired as an MCP server
  for the implementer adapters, warmed on the runner and always optional.
* **UI criteria (SPEC §10.2 steps 3 and 5, L4-VER-014).** A UI-facing criterion that no e2e test traces gets a Playwright
  test written by the verifier. The test counts only if it fails against the merge-base app and passes against the head
  app. Both apps are served by `gates.e2e.serve` inside the gate sandbox (bwrap).
* **System-One (L4-FAC-004, L4-VER-002 step 8, L4-VER-008, L4-CLR-002).** System-One judgments go through a
  TypeSafe-wire backend:
  * Laya (open weights, `laya-serve`) runs where it fits: on the runner, or on the maintainer's Mac;
  * Jev is built but blocked until there is an API key;
  * the S1 router replaces the M1.1 `llm_boolean` stand-in whenever a System-One profile is usable.

Starting point: M1.1 as built (`docs/plan/m11-progress.md`). M1.1 Stage C has landed (`98e4939`). This plan still
edits no forge, archive, CI-template or pending-ledger code.

**Parallel with M1.2, M1.3 and M1.4.** M1.5 merges last. The shared-file anchors and exact names, the contracts
(C1, C7–C9, C14–C18, C20) and the merge order are in `docs/plan/parallel-ownership.md`. **Stage C is split** (§5.1
there):
* **group 1:** lines 28, 29, 30, 31, 32, 37 and 39 start once M1.2 is merged to `main` and `main` is merged into `m15`;
* **group 2:** lines 33–36 and 38 start once M1.3 is merged;
* line 40 comes last.

Stages A and B do not wait. Line 25 needs the seam commit S0: merge `main` before it.

**Size: 40 build lines in three sequential stages.** 8 of the lines carry a gap task (M15-G1…G8); 2 of those also
reduce an existing task. The gap ids carry a `M15-` prefix so that they cannot collide with gaps of increments planned
at the same time.

## Facts this plan rests on

Labels: [V] verified, [I] inferred, [U] unverified.

* **Package pins** [V, PyPI JSON 2026-10-04]:
  * Python `playwright` 1.63.0 exists, the same version `prereqs.sh` PRQ-14 already pins for Node;
  * `pytest-playwright` 0.9.0;
  * `laya` 0.3.26 is the latest release. 0.3.24 is the release that research/03 ran locally: wire-compatible with the
    TypeSafe SDK and 15/15 byte-identical answers;
  * `serena-agent` 1.7.0 needs Python ≥3.11 and <3.15.
* **Laya checkpoints** [V, Hugging Face API 2026-10-04]:
  * `convaiinnovations/laya` holds `english` (`model.safetensors`, 842.6 MB) and `typed-decisions/model.safetensors`
    (842.6 MB) under one `apache-2.0` card;
  * both are ModernBERT with 28 layers × hidden size 1024, i.e. ModernBERT-large, 421M parameters [V README].

  So SPEC Q4 ("typed-decisions if its license and size fit") reduces to one question: does Laya fit at all. The two
  checkpoints are the same size.
* **Laya memory on the runner** [I]:
  * estimated peak RSS of `laya-serve` is 1.3–2.3 GB: about 0.85 GB of 16-bit weights, or 1.7 GB if upcast to fp32,
    plus the torch runtime;
  * `l4-runner` has 3.8 GB RAM, about 1.3 GB available and swap already in use [V, docs/runner/README.md].

  Laya on the runner is therefore [U] until the M15-G2 probe measures it. The fallback is `laya-serve` on the
  maintainer's Mac. The runner already reaches the Mac on the LAN (`192.0.2.10`, the OpenCode `magnitude` provider)
  [V, env memory]; whether it can reach a new port there is [U].
* **Laya state window**: 463 tokens on the English checkpoint [V README]. The harness counts tokens as characters ÷ 4
  [V, `router.approx_tokens`], so `max_state_tokens: 450` may overflow it [U], to be measured with Laya's tokenizer.
* **Loopback in the gate sandbox.** The gate sandbox uses `--unshare-net` [V, `bwrap.base_flags`]. bwrap brings up
  `lo` in the new network namespace [I], so a server and its tests in **one** gate spawn can talk over `127.0.0.1`.
  Chromium inside bwrap (`/dev/shm`, a read-only HOME) is [U]; spikes 2.2 has never run.
* **Already in place**:
  * `PLAYWRIGHT_BROWSERS_PATH` already reaches the gate env through the `playwright` cache mount
    [V, `build_gate_env`, `defaults.CACHES`];
  * `RunRequest.mcp_servers` exists, but neither adapter emits MCP flags yet [V, code];
  * `commands.HANDLERS["lessons"]` already names `l4.memory.cli:run_lessons` [V].
* **Live-protocol constants** [V, computed with `l4.specs.criteria.criterion_id` and sha256]:
  * the seeded criteria get the ids `C-de7f2d3f` (show-item-count) and `C-68f2e098` (show-subtotal);
  * the first lesson's id is `L-09421538` = `L-` + sha256(`ui-criterion-without-e2e-test`)[:8].

## Decisions

* **D1. Parallel lanes, single-writer integration** (the user asked for faster, parallel work). Stages run in
  sequence. Inside Stages A and B, three lanes run in parallel, and each line touches only files that its lane owns:
  * **[M]** memory and Serena;
  * **[W]** web UI and Playwright;
  * **[S]** System-One.

  Also tagged:
  * **[R]** lines are runner work. They run alongside the lanes, through `mk-ssh.sh` and one probe pipeline.
  * **[X]** lines are shared-file integrations, all of them in Stage C.

  Stage C is a single-writer pass over the shared files, in the listed order and in the two groups above. Two agents
  never edit one shared file at the same time. Group 1 is built on top of the merged M1.2, and group 2 on top of the
  merged M1.3. Line 3 (config schema) is the one shared edit in
  Stage A, because all three lanes read it.
* **D2. The verifier's test writer is tool-less.** Step 5 runs on `roles.verifier_agent` through `AgentJudge`
  (claude-code in judge mode, as for G3 and G10). It uses `l4.verifier.testwriter.request_test(kind="e2e", …)` from the
  seam commit S0 (`parallel-ownership.md` §3.0), which M1.3's audit step 4a shares. M1.3 owns that file after S0, and
  M1.5 does not create it:
  * the schema is `l4/generated-test@1`: `{criterion, code}` or `{criterion, not_testable}`;
  * the harness writes the file to a path it fixes, `e2e/test_l4_c_<hex>.py`;
  * nothing the model writes reaches the worktree any other way, so L4-VER-002a holds by construction;
  * the agentic verifier (Claude in implement mode in an agent sandbox, with healing) is deferred.
* **D3. The UI baseline is the merge-base app.** A generated test is discriminating when it fails against the
  merge-base app and passes against the head app (SWE-bench FAIL_TO_PASS). Each app is served from its own worktree by
  `gates.e2e.serve`. There are no red stubs at this baseline, because the synthetic baseline (verifier 3.3) is
  deferred.
* **D4. One gate spawn per e2e run.** A stdlib-only launcher runs inside a single gate sandbox. It starts
  `serve.command` in its own process group, polls `ready_url`, saves `GET <origin>/` as the page snapshot, runs
  `e2e.command` with `L4_E2E_BASE_URL=<origin of ready_url>`, and kills the group. The network stays unshared, and the
  server and the tests share the namespace's loopback.
* **D5. Curation origin, reduced reading of L4-MEM-002 (a).** There are no fix units yet (the M0 deferral still holds).
  So "a verifier finding whose fix later passed" is read as: a deterministic finding of a known rule, closed in the same
  round by an accepted generated test, in a round whose verdict is PASS.
  * The rules live in a registry, `LESSON_RULES`. The first rule is `ui-criterion-without-e2e-test`.
  * Lesson text is a harness template. Model text never becomes a lesson.
  * Origin (b), a guard violation repeated across runs, and origin (c), a human edit, are built as specified.
* **D6. The tag follows SPEC.** The tag is `<l4:data kind="lessons" ids="…">` as SPEC L4-MEM-003 says, not the
  `kind="lesson"` of the increment brief.
* **D7. System-One engines.**
  * `laya-local` starts `laya-serve` on a free localhost port around each S1 batch (verifier step 8, a clarifier
    pass) and stops it afterwards, so it is never resident together with Chromium or an agent. This stays within
    L4-FAC-004 "for the duration of the verify step".
  * `jev` is the hosted API, with `api_key_env`.
  * New: `remote` is any TypeSafe-wire server at `base_url`, with `api_key_env` optional. It exists for Laya on the
    Mac. Doc change owed.
* **D8. S1 never decides.** Step 8 records `p` for calibration only. The traceability-off judgment row (verifier 4.4)
  stays deferred, so a Laya `p` changes no verdict. In the clarifier, a usable System-One profile replaces the stand-in
  (clarification-loop 2.3, SPEC). Zero-shot Laya is near chance [V research/03], so auto-accepts will mostly stop. That
  is the fail-safe direction (Risks).
* **D9. Serena is advisory and runs only for the implementer.**
  * Only implement-mode requests get the MCP server. Tool-less judge, clarifier, S1 and generator calls never do.
  * A harness-side `check_serena` (an MCP `initialize` in the same agent sandbox) runs once per run. A failure records
    `memory.serena{status: failed}` and the run continues (SCN-MEM-06).
  * Lessons always travel in the prompt, so they never depend on the agent calling Serena's `initial_instructions`.

## Build list

Line format: `change-id task — what M1.5 builds`, numbered across stages, with the lane tag first.

### Stage A — runner probes and owned cores (lanes M, W, S and R in parallel)

1. [R] M15-G1 — `prereqs.sh`:
   * PRQ-13 installs Serena and also warms it: `serena --version`, plus a prefetch of the Pyright `uvx` environment into
     the runner user's uv cache;
   * PRQ-14 installs Chromium headless shell 1.63.0 into `~gitlab-runner/.cache/l4/shared/ms-playwright` (the
     `$L4_CACHE` default path), with `install-deps` as root;
   * new PRQ-18 `--with-laya`: `uv tool install 'laya[serve]==0.3.24'`, plus a prefetch of the `typed-decisions`
     checkpoint.
2. [R] spikes 2.2 (reduced) + M15-G2 — one probe pipeline on `probe/m15`. The branch is outside `l4/**`, and its
   `.gitlab-ci.yml` is replaced by the probe job alone; otherwise the routed `l4` job would run `l4 run` (template rule
   3, [V]; parallel-ownership §4, item 15). It measures Playwright, Serena and Laya
   in the exact sandbox argv of the harness and the Mac's reachability, and fixes the decisions **P1** (`/dev/shm`),
   **P2** (Laya placement) and **P3** (S1 state budget); details under M15-G2.
3. [X] bootstrap-core 1.4 delta — typed `MemoryCfg` (`enabled`, `lessons_file`, `max_lessons`, `max_bytes`, `serena`)
   and `SerenaCfg` (`enabled`, `version`, `context`), with the SPEC 3.2 defaults; `memory` leaves `OPAQUE_SECTIONS`.
   From then on, an unknown `memory.*` key is a load error (exit 2):
   * no test fixture and no `l4 init` template has a `memory:` section [V];
   * dummy-agentic's `.l4/config.yaml` is [U]. Read it, or run `l4 upgrade`, which lists unknown keys, before the live
     run.

   A test loads the SPEC 3.2 `memory:` example.
4. [M] memory-lessons 1.1, 1.2, 1.3 — `lesson_id`, `Lesson`/`LessonsFile`/`EMPTY_TEMPLATE`, tolerant `parse_lessons`
   (LF and CRLF; a non-`v1` header yields no lessons; a malformed section is skipped and reported)
5. [M] memory-lessons 1.11 — canonical `render_lessons` (id order, LF, unknown bullets kept, optional `Reinforced`
   bullet) and atomic `write_lessons`
6. [M] memory-lessons 1.4, 1.5 — `select_lessons` (globs from `l4.security.protected.glob_match`; kinds empty in M1.5,
   so kind-scoped lessons are not selected) and `build_lessons_block`. The block is defused (`<l4:` cannot close or
   open a block) and redacted.
7. [M] memory-lessons 1.6, 1.7, 1.8 — `inject_for_task` reads the worktree's lessons file, so it sees base plus own
   branch only. One `lessons.injected{ids, channel: prompt_section, bytes}` per non-empty injection. Task paths are
   the backticked paths of the task line plus the files the unit branch already changed.
8. [M] memory-lessons 1.10 — `l4 lessons list|lint` (the handler row already exists, `cli.py` untouched)
9. [S] agent-factory 6.2 — `SystemOneBackend`:
   * TypeSafe wire `POST /v1/systemone` with `{state, model, questions: {id: {type: noul|choice|score, …}}}`;
   * engines `laya-local | jev | remote` (D7);
   * the request/response log in `.l4-out/logs/system-one.jsonl`;
   * httpx `MockTransport` tests.
10. [S] agent-factory 6.3 — `LayaServe` context manager:
    * a free port and a readiness poll;
    * the server is always stopped, and killed when it never gets ready;
    * `LAYA_THREADS` and `OMP_NUM_THREADS` are pinned, for byte-identical answers.
11. [S] M15-G3 — `open_s1_backend(cfg, role="s1_judge", events)`: the first `backend: system-one` profile of the chain,
    probed. It lives outside `factory.py`, which M1.2 rewrites for fallback chains.
12. [W] M15-G4 — the e2e launcher (D4) and `run_e2e(wb, worktree) -> E2eRun(gate, report, snapshot)`
13. [W] verifier 6.1 (reduced) — UI-facing = the unit's changed files match `verifier.playwright.ui_paths`. The S1
    choice question is deferred.
14. [W] M15-G5 — `trace_e2e(criteria, e2e_report)`: a criterion is covered when an e2e test id contains its hex
    (`c_<hex>`, `C_<hex>` or `C-<hex>`). It returns the uncovered UI-facing criteria. In group 2, it becomes a thin wrapper over M1.3's `trace_ids`, still applied to the e2e report only, and it picks
    step 5's targets. The criterion evidence for aggregation comes from M1.3's step 4
    (`trace_criteria(…, extra_reports=(e2e_report,))`; parallel-ownership C8). A unit test does not make a UI criterion
    "covered" for step 5.

*Exit A:*

* unit tests pass;
* M15-G2 is recorded in `docs/runner/` with decisions P1–P3;
* `prereqs.sh --check` reports PRQ-13, PRQ-14 and (when P2 = runner) PRQ-18 as OK.

### Stage B — lanes deepen (parallel; owned files only)

15. [M] memory-lessons 3.1 (reduced, D5) + M15-G6 — `LessonCandidate`, `curate`, and `LESSON_RULES` with the rule
    `ui-criterion-without-e2e-test`: scope = the `ui_paths` globs the unit touched, title and body from a template
16. [M] memory-lessons 3.2 — `guard_violation_repeated`: the same `guard.violation` kind in at least 2 distinct
    `run_id`s of the unit's ledger, plus the `human_edit` origin
17. [M] memory-lessons 3.4, 3.5 — a duplicate key reinforces the existing lesson (count, date); over the caps, lessons
    are archived to `_archive/<id>.md`
18. [M] memory-lessons 3.11, 3.12 — `commit_memory_change`:
    * a separate commit `chore(memory): <detail> [skip ci]`;
    * trailer `L4-Phase: lessons`;
    * no commit when the bytes are unchanged;
    * a `lessons.curated{action, id}` event.
19. [M] memory-lessons 4.1, 4.2, 4.3 — `serena_argv` (the SPEC flags; `--context codex | claude-code | ide` per
    adapter), `serena_env`, `render_project_yml`, `mcp_timeouts`, and `mcp_server_for(adapter, …) -> McpServer | None`.
    * `SERENA_HOME` is **per agent step**: `<agent tmp>/serena-home` with a generated `serena_config.yml`
      (`base_modes: [editing]`).
    * The agent tmp is reset before every request (`reset_agent_tmp`), and the unit cache is never mounted into a
      sandbox. So Serena re-registers the project at every step, which takes seconds, and nothing it keeps in
      `SERENA_HOME` survives between steps.
    * The symbol cache stays in the worktree's `.serena/cache/`, and Pyright comes from the uv cache.
    * Chosen over a new `sandbox.caches.serena` entry, which would also mount into gates and change `defaults.CACHES`.
20. [M] memory-lessons 4.4, 4.6 — `check_serena`:
    * an MCP `initialize` handshake through the same agent-sandbox wrap;
    * it never raises;
    * it checks the version pin;
    * it emits `memory.serena{status, reason, startup_ms}`.
21. [S] clarification-loop 2.1 — `SystemOneJudge(backend)` implements the `S1Judge` protocol with `noul`. It returns
    `p` as given and raises `S1Unavailable` when the server is down. It lives in owned `l4/llm/system_one.py` and is
    wired into the router in line 28.
22. [S] verifier 4.1, 4.2 — step 8 in `l4/verifier/s1.py`:
    * one `noul` per criterion over a compact state: criterion text, the tracing tests with status, an excerpt;
    * the state is trimmed to the P3 budget;
    * an over-long state or a server error makes that criterion `unavailable`;
    * the step status is `unavailable`, and aggregation goes on.
23. [S] verifier 4.3 — calibration lines go to `$L4_CACHE/s1-calibration.jsonl` (L4-VER-008), plus a per-run copy
    `.l4-out/s1/<run-id>.jsonl` (a CI artefact): state sha, question, `p`, model, deterministic and judge outcome.
    Nothing is written when S1 is unavailable.
24. [W] verifier 6.2 — base and head serving:
    * a detached merge-base worktree (`Git.run("worktree", "add", "--detach", …)`);
    * the setup gate runs there;
    * `run_e2e` runs at base and at head;
    * the base worktree is removed in `finally`;
    * a serve that is never ready is an internal error (exit 1, L4-VER-010).
25. [W] verifier 3.9 (reduced, D2) — `generate_ui_test`:
    * prompt: criterion, scenario text, UI diff, page snapshot, all as `<l4:data>`;
    * the profile must pass `require_independent_judge` against the implementers (vendor rule). It exists today, and
      M1.2 keeps it. Once M1.2 is on `main`, line 34 switches to `select_judge(…, role="verifier_agent")` (C1);
    * the call is `testwriter.request_test(kind="e2e", …)` (S0), and the file path is `testwriter.test_path("e2e", …)`;
    * a test is accepted iff it collects, passes `gates.lint` on the file (the project's CI lints H), fails at base and
      passes at head;
    * one retry, which carries the reason.
26. [W] verifier 3.10 — generation is impossible after `not_testable`, two non-discriminating attempts, or an
    uncollectable test. The UI criterion stays uncovered (`needs_human`).
27. [W] verifier 6.3 + 5.3 (reduced):
    * the trace and screenshot paths of failing e2e runs are listed for the report;
    * accepted generated tests are committed once per round as `test(<unit>): verifier round <n> [skip ci]` with
      `L4-Phase: verifying`. Step 5 only returns their paths. The single per-round commit is M1.3's
      `l4.verifier.evidence.commit_verifier_tests`, which also takes the audit tests of step 4a; line 34 wires it
      (parallel-ownership C9);
    * a generated test that fails at head is kept in the evidence, not committed. Its criterion is `needs_human`;
      the panel review of L4-VER-012 is deferred.

*Exit B:*

* unit tests pass with fakes;
* `L4_LIVE=1` smoke tests on the Mac:
  * the generator schema against the real `claude`;
  * real `laya-serve`: 3 identical calls give byte-identical JSON, and the process is gone afterwards;
  * real Playwright on the fixture web app (`tests/fixtures/web/`) with `NoSandbox`: base fails, head passes.

### Stage C — integration (single writer over the shared files, in this order) and live

28. [X] clarification-loop 2.3 — `router.build_s1_judge`:
    * a usable System-One profile (`open_s1_backend`) comes first;
    * otherwise, with `s1_standin: llm_boolean`, the stand-in runs on the first **adapter** profile of `roles.s1_judge`.
      Today it takes `chain[0]`, which would make `[laya, claude-code]` unavailable. In group 1, after M1.2,
      `for_role("s1_judge", unit, serves=JUDGE_ADAPTERS)` skips a backend profile instead of failing, so no own chain
      scan is needed (C16);
    * the default stays `none`.
29. [X] M15-G7 — MCP injection:
    * `McpServer` gains `env`;
    * `CodexAdapter.build_command` emits `-c mcp_servers.<n>.command/args/env/startup_timeout_sec=30`;
    * `ClaudeCodeAdapter` writes `--mcp-config <tmp file>` and keeps `--strict-mcp-config`;
    * an empty `mcp_servers` leaves the argv byte-identical (the golden tests are unchanged).
30. [X] implementer-tdd-loop 1.13 delta — `tdd._prompt` appends the lessons block after the answers block and before
    M1.2's previous-attempt block; `prompt.rendered` gains `lessons: [ids]`, and the prompt hash covers it. Follow-up at merge
    time: when a `main` that contains M1.4 is merged into `m15`, the same block goes into M1.4's `l4.sim.dryrun` prompt,
    so M1.4's dry-run prompt-hash test stays green (C14).
31. [X] workbench delta:
    * `check_serena` once per run when `memory.serena.enabled`, called inside `Workbench.mcp_servers()` and cached per
      `run_id`. `make_workbench` stays as it is, because M1.3 extends its signature;
    * `mcp_servers` only on implement-mode requests: `tdd.agent_step` passes `mcp_servers=wb.mcp_servers()` into
      `RunRequest(…)`;
    * `HARNESS_EXCLUDES` += `.serena/cache/`, `.serena/project.local.yml`.
32. [X] memory-lessons 1.9 — `.serena/memories/harness/**` is **already** in `CONTRACT_PROTECTED_GLOBS` [V,
    `security/protected.py`]. This line only adds the SCN-MEM-02 test (an agent edit to `lessons.md` is reverted);
    `protected.py` is not edited.
33. [X] verifier 1.8 delta — step 3 also runs `gates.e2e` at head through `run_e2e` when it is configured. The gate is
    non-vacuous: it is judged on its JUnit report and a seeded smoke test.
34. [X] ladder integration (verifier 1.19 delta; group 2, on top of the merged M1.3):
    * `LADDER` gains 5 and 8 with `verify.generated{criterion, test, base, head, attempts}` and
      `verify.s1{criterion, p, model}`. There is no 4e2e row: M1.3's step 4 takes the e2e report through
      `trace_criteria(…, extra_reports=)` for the evidence. Step 5's targets are the UI-facing criteria that
      `trace_e2e` (now a thin wrapper over `trace_ids`) finds untraced **in the e2e report**; a unit test does not
      count;
    * order: 0 → 1 → 2 → 3 (with e2e) → 4 → 4a → 5 → 8 → 9 → 10;
    * after step 5, one `commit_verifier_tests` call commits the audit and generated tests (C9);
    * the judge's gate summary is rebuilt after step 5, so the judge sees the generated test's outcome;
    * aggregate rows: an accepted generated test enters M1.3's `aggregate_criterion(…, trace=)` as
      `TracingTest(proof="generated")`, with no `evidence=` keyword. A generated test failing at head, or an uncovered UI
      criterion, is `needs_human`. The "M0 traceability override" no longer exists once M1.3 lands: non-UI criteria
      follow M1.3's `require_traceability` (parallel-ownership §4, item 4).
35. [X] verifier 1.16 delta — the `verification.md` matrix gains columns for tests (generated ones marked, with base/head
    outcome), S1 p and evidence links (page snapshot, traces); `verdict.json` gains `generated` and `s1`.
36. [X] memory-lessons 3.13 (reduced) — `verify_hook`, on PASS, curates from the round's deterministic findings and
    commits `chore(memory)` **before** the hand-off. No line touches `archive.py`.
    * The call comes after M1.3's `after_verdict`, and only when the trigger is `VERIFY_PASS` and no fix unit was
      spawned in the round, i.e. on the PASS that leads to H.
    * The commit carries `L4-Phase: lessons`, which M1.3's `subject_sha` ignores (C18).
37. [X] sandbox-security delta (only if P1 says so) — the gate kind gains `--tmpfs /dev/shm`, with the parity test and
    `sandbox-probe.sh` updated.
38. [X] preflight delta (group 2):
    * `roles.verifier_agent` must be non-empty when `gates.e2e.command` is set and Playwright is enabled. The
      undefined-name check for `verifier_agent` is M1.3's (C1, parallel-ownership §4, item 8);
    * a `backend: system-one` profile needs `engine ∈ {laya-local, jev, remote}`, `base_url` for `remote` and
      `api_key_env` for `jev`;
    * any violation exits 2.
39. [X] memory-lessons 5.1 + bootstrap-core 1.16 delta (ENV-006…008, reduced) — owned `l4/doctor/checks_memory.py`
    (MEM-001 lint, Playwright browsers, Serena pin, Laya presence, all warn), plus one row in
    `doctor.registry.CHECK_MODULES`.
40. [X] M15-G8 — live acceptance test of the protocol below.

*Exit C:*

* unit tests pass;
* the fixture repo with a bare remote, `FakeAdapter`, a fake generator and a fake S1 backend shows:
  * unit 1: `verify.generated` (base fail, head pass), `verify.s1`, the commits in the order `test(…)`,
    `docs(…)`, `chore(memory)`, H, and `lessons.curated{created}`;
  * unit 2, branched after unit 1's merge: the red prompt holds `<l4:data kind="lessons" ids="L-…">`, and
    `lessons.injected` comes before the first `agent.session`.

Then the live protocol (M15-G8).

## Gaps (no existing task covers them; no tasks.md was edited)

* **M15-G1** (Stage A; runner-provisioning, script only) — Extend `scripts/runner/prereqs.sh`:
  * PRQ-14 installs the Chromium of the Python `playwright==1.63.0` with
    `PLAYWRIGHT_BROWSERS_PATH=~/.cache/l4/shared/ms-playwright` (`install-deps chromium` as root);
  * PRQ-13 adds a warm step;
  * new PRQ-18 `--with-laya` installs `laya[serve]==0.3.24` as a uv tool and prefetches `typed-decisions`.

  Each step has check, apply and re-check, and changes nothing under `--check`.
  test: tests/unit/runner/test_prereqs_steps.py::test_with_laya_and_playwright_steps_are_listed (static parse of the
  step table) — code: scripts/runner/prereqs.sh — verify: `scripts/runner/mk-ssh.sh --script scripts/runner/prereqs.sh
  -- --check --with-serena --with-playwright --with-laya` (log under docs/runner/)
  * Why: the runner-provisioning design excludes these installs. PRQ-14 installs into `~/.cache/ms-playwright`, which
    the gate sandbox does not mount; the gate mounts `$L4_CACHE/shared/ms-playwright` read-only.
* **M15-G2** (Stage A; live probe; spikes 2.2 reduced) — `scripts/runner/ci-probe-m15.sh`, one job on the branch `probe/m15`
  (tags `[agentic]`), as `gitlab-runner`. On that branch only, `.gitlab-ci.yml` holds just this job: a branch under
  `l4/**` would also run the routed `l4` job [V, template rule 3]. It runs in the runner lane with nothing else running
  on the runner, because part (c) measures RSS (parallel-ownership §5.3). Every measurement records `/usr/bin/time -v` max RSS. Parts:
  * (a) a stdlib HTTP server and a pytest-playwright smoke test inside the argv of `BwrapSandbox.build_argv` for a gate
    (`--unshare-net`), once without and once with `--tmpfs /dev/shm`;
  * (b) `serena start-mcp-server --context codex …` inside the agent argv: MCP `initialize` time and RSS;
  * (c) `laya-serve` with `typed-decisions` under 0.3.24 (0.3.26 only if 0.3.24 cannot load it): load time, max RSS,
    p50 of 5 `noul` calls, byte-identical answers, and the token count of a 450-approx-token state with Laya's tokenizer;
  * (d) a TCP connect to `192.0.2.10:<laya port>`;
  * (e) `cache_root` as the job resolves it, which shows whether `L4_CACHE` or `XDG_CACHE_HOME` is set. The PRQ-14
    browser path and the gate's read-only `playwright` mount must name the same directory before Stage C.

  test: scripts/runner/ci-probe-m15.sh (job log saved as docs/runner/ci-probe-m15-<date>-pipeline-<id>.txt) — code:
  scripts/runner/ci-probe-m15.sh — verify: the log shows (a) pass or fail per variant, (b) handshake seconds, (c) max
  RSS, load seconds and identical hashes, (d) connect ok or refused.
  * Decisions:
    * **P1**: add `--tmpfs /dev/shm` to gates only if (a) fails without it;
    * **P2**: Laya runs on the runner when its max RSS ≤ 1.2 GB with nothing else running, else on the Mac (`engine:
      remote`);
    * **P3**: the S1 state budget is the largest approx-token count whose Laya token count is ≤ 463 (expected near
      400) [U].
* **M15-G3** (Stage A; agent-factory) — `open_s1_backend(cfg, role, events) -> SystemOneBackend`:
  * the first profile of `roles.<role>` with `backend: system-one`;
  * probes: `laya-local` = `laya-serve` resolvable plus the checkpoint present; `jev` = `api_key_env` set (names only);
    `remote` = `GET <base_url>/health` returns 200 within 5 s;
  * otherwise `RoleUnavailable`, never exit 2 (S1 is an optional role);
  * one `availability.selected{role: s1_judge}` event.

  test: tests/unit/llm/test_system_one.py::test_open_s1_backend_picks_first_system_one_profile_and_degrades — code:
  src/l4/llm/system_one.py — verify: uv run pytest tests/unit/llm/test_system_one.py -q
  * Why: `Factory.build` refuses backend profiles [V, factory.py], and M1.2 owns the factory's chain walking.
* **M15-G4** (Stage A; implementer-tdd-loop gates) — `l4.gates.e2e`. A stdlib-only launcher (`e2e_launch.py`, run by
  the harness interpreter with `-I`) inside one gate spawn does the following:
  * starts `serve.command` (split with `shlex`) in its own process group, with `HOME` and `TMPDIR` set to the gate's tmp
    dir;
  * polls `ready_url` until `serve.timeout`;
  * writes `.l4-out/e2e/page.html` from `<origin>/`, capped at 200 KB;
  * runs `e2e.command` with `L4_E2E_BASE_URL=<origin>`;
  * kills the group and exits with the e2e exit code, or 97 when the server was never ready.

  `run_e2e` maps exit 97 to an internal error and parses the JUnit report non-vacuously.
  test: tests/unit/gates/test_e2e.py::test_server_and_tests_share_one_spawn_and_group_is_killed (also
  ::test_never_ready_is_internal_error, ::test_snapshot_written) — code: src/l4/gates/e2e.py, src/l4/gates/e2e_launch.py
  — verify: uv run pytest tests/unit/gates/test_e2e.py -q
  * Why: a separate serve spawn with `--unshare-net` would sit in another network namespace than the tests [I].
* **M15-G5** (Stage A; verifier) — `trace_e2e`: criterion ids are matched case-insensitively in e2e test ids, as `C-`,
  `C_` or `c_` followed by the 8 hex digits. A test tracing more than `max_criteria_per_test` criteria counts for none.
  test: tests/unit/verifier/test_e2e_trace.py::test_generated_file_name_traces_its_criterion — code:
  src/l4/verifier/e2e_trace.py — verify: uv run pytest tests/unit/verifier/test_e2e_trace.py -q
  * Why: step 4 (verifier 1.9, the pytest marker plugin) is not built yet. M1.3 builds it in parallel. A separate
    module stays out of the way of M1.3's `traceability.py`, and group 2 retires it onto M1.3's step 4 (C8).
* **M15-G6** (Stage B; memory-lessons) — `LESSON_RULES: dict[dedupe_key, LessonRule(title, body_template,
  scope_from)]` and `candidates_from_round(result, cfg) -> list[LessonCandidate]`. Only deterministic findings with a
  rule count, and only when the round verdict is PASS. First rule: `ui-criterion-without-e2e-test`, title "UI criteria
  need an end-to-end test".
  test: tests/unit/memory/test_curate.py::test_ui_gap_closed_by_generated_test_creates_L_09421538 (also
  ::test_judge_finding_never_becomes_a_lesson, ::test_needs_human_round_curates_nothing) — code: src/l4/memory/curate.py
  — verify: uv run pytest tests/unit/memory/test_curate.py -q
  * Why: origin (a) of L4-MEM-002 needs fix units, which no milestone has built (D5).
* **M15-G7** (Stage C; agent-factory) — MCP injection for `codex` and `claude-code`, as in line 29.
  test: tests/unit/agents/test_mcp_flags.py::test_codex_and_claude_mcp_flags_and_empty_list_unchanged — code:
  src/l4/agents/base.py, src/l4/agents/codex.py, src/l4/agents/claude_code.py — verify: uv run pytest tests/unit/agents -q
  * Why: no agent-factory task emits MCP flags for these two adapters [V, tasks.md grep].
* **M15-G8** (Stage C exit; live-validation) — the checks of the protocol below as code: one test per step, reading
  pipelines, jobs, MRs, branches, files and job artefacts through the read-only API, and recording ids.
  test: tests/live/test_m1_5_acceptance.py (marker `live`, needs `L4_LIVE=1`; `L4_LIVE_RECORD` defaults to
  `/tmp/l4_m1_5_ids.json`) — code: tests/live/test_m1_5_acceptance.py
  — verify: L4_LIVE=1 uv run pytest tests/live/test_m1_5_acceptance.py -m live -q

## Simplifications and deferrals

* **Lessons**
  * Channel `prompt_section` only. Deferred: Claude `--append-system-prompt` and Kiro `resources` (2.3, 2.4), task kinds
    (2.1) and `Supersedes` filtering (2.2).
  * The inbox and `lesson_proposals` quarantine (3.6, 3.7) and `l4 lessons promote` (3.8) are deferred: proposals in a
    result are ignored.
  * The union-merge repair and its test (3.9, 3.10) are deferred, but the `merge=union` attribute is seeded by hand.
  * Lessons are not given to the clarifier yet.
* **Serena**
  * `codex` and `claude-code` only. OpenCode and Kiro get the interface (below); Kiro filtering (4.5) is deferred.
  * No `print-system-prompt` injection. The contract test (4.7) is replaced by M15-G2(b).
* **UI verification**
  * Python pytest-playwright with JUnit reports. The `playwright-json` format is not parsed.
  * One page snapshot (`/`). No healing, no `flaky_repeats` for generated tests (3.2), no audit sampling (3.7, 3.8).
  * The baseline is the merge-base app (D3), not the synthetic stub baseline (3.3).
  * L4-VER-012 review becomes `needs_human`; no fix unit.
  * Generation covers UI-facing criteria only. Non-UI criteria keep the M0 traceability override.
  * UI-facing is decided by `ui_paths` only; the S1 choice question of L4-VER-014 is deferred.
* **System-One**
  * The token budget is characters ÷ 4 with the P3 cap; the model tokenizer (clarification-loop 2.2) is deferred.
  * No traceability-off judgment row (4.4). Calibration export (`laya-evals`) and the human-outcome fill are v1.1.
  * Jev is built and mock-tested but not run live (no key).
* **Init**
  * No `l4 init` or `l4 upgrade` change, because forge-and-ci is in flux. `.serena/project.yml`, the empty lessons file,
    `.gitattributes` and the config keys are seeded by hand (protocol step 1). `l4 upgrade` (M1.1 G11) already reports
    keys the file lacks.

## Files

**(a) Owned (new or mostly this increment's):**

* `src/l4/memory/{__init__,lessons,inject,curate,commit,serena,cli}.py`
* `src/l4/llm/system_one.py`: `SystemOneBackend`, `LayaServe`, `open_s1_backend`, `SystemOneJudge`
* `src/l4/gates/e2e.py`, `src/l4/gates/e2e_launch.py`
* `src/l4/verifier/{playwright,generate,s1,e2e_trace}.py`
* `src/l4/doctor/checks_memory.py`
* `scripts/runner/ci-probe-m15.sh`, `docs/runner/ci-probe-m15-*.txt`, `docs/plan/m15-progress.md`
* tests:
  * `tests/unit/memory/**`, `tests/integration/test_memory_flow.py`;
  * `tests/unit/llm/test_system_one.py`, `tests/unit/gates/test_e2e.py`;
  * `tests/unit/verifier/test_{playwright,generate,s1,e2e_trace}.py`, `tests/unit/agents/test_mcp_flags.py`;
  * `tests/fixtures/web/` (a 30-line stdlib app plus a smoke e2e test), `tests/live/test_m1_5_acceptance.py`.

**(b) Shared files, with the exact edit (additive unless marked):**

| File | Edit |
|---|---|
| `src/l4/config/schema.py` | new `SerenaCfg`, `MemoryCfg`; field `L4Config.memory: MemoryCfg`. **Not additive:** `"memory"` leaves `OPAQUE_SECTIONS` (strict validation now refuses unknown `memory.*` keys) |
| `src/l4/config/defaults.py` | constants `LESSONS_FILE`, `MAX_LESSONS=40`, `MAX_LESSON_BYTES=12000`, `SERENA_VERSION="1.7.0"`, `LAYA_VERSION="0.3.24"` |
| `src/l4/config/preflight.py` | two new checks at the end of `preflight_run_config` (line 38, group 2): non-empty `verifier_agent` when e2e is on, and the System-One profile rules. M1.3 adds the `verifier_agent` name check |
| `src/l4/clarifier/router.py` | `build_s1_judge` body (edit of one function, line 28); imports `SystemOneJudge` |
| `src/l4/verifier/ladder.py` | group 2, on top of M1.3: `LADDER` rows 5 and 8 (no 4e2e); step calls; gate summary rebuilt after step 5; one `commit_verifier_tests` call; curation call after `after_verdict` |
| `src/l4/verifier/gates.py` | new `run_e2e_gate` |
| `src/l4/verifier/aggregate.py` | **not edited**: generated tests enter M1.3's `trace=` as `TracingTest(proof="generated")` (parallel-ownership §4, item 4) |
| `src/l4/verifier/types.py` | group 2: defaulted fields `CriterionOutcome.tests`, `.s1_p`; `VerifyResult.generated`, `.s1` after M1.3's fields; `StepStatus` gains `unavailable` (final union in parallel-ownership §2.2) |
| `src/l4/verifier/report.py` | matrix columns and links (line 35) |
| `src/l4/implementer/tdd.py` | group 1: one more `data_blocks` entry in `_prompt` (order: answers, lessons, M1.2's previous-attempt); `lessons` in `prompt.rendered`; `mcp_servers=wb.mcp_servers()` in `agent_step`'s `RunRequest(…)` |
| `src/l4/implementer/workbench.py` | group 1: new method `mcp_servers()` after `reset_agent_tmp` (it calls `check_serena` once per run); two `HARNESS_EXCLUDES` entries |
| `src/l4/agents/base.py` | `McpServer.env: tuple[tuple[str, str], ...] = ()` |
| `src/l4/agents/codex.py`, `claude_code.py` | MCP branch in `build_command` (empty list: argv unchanged) |
| `src/l4/security/protected.py` | **not edited**: `.serena/memories/harness/**` is already in `CONTRACT_PROTECTED_GLOBS` [V] |
| `src/l4/doctor/registry.py` | `CHECK_MODULES` += `"l4.doctor.checks_memory"` (a same-line union with M1.4: parallel-ownership §2.2) |
| `src/l4/sandbox/bwrap.py`, `scripts/runner/sandbox-probe.sh`, `tests/unit/sandbox/test_probe_parity.py` | only if P1: gate kind `--tmpfs /dev/shm` |
| `scripts/runner/prereqs.sh` | PRQ-13 warm, PRQ-14 path, new PRQ-18 (M15-G1) |

`src/l4/sandbox/env.py`, `commands.py`, `cli.py`, `services.py`, `orchestrator.py`, `lifecycle.py`, `archive.py`, `forge/**`,
`ci/**`, `state/pending.py`, `init/**`, `aggregate.py` and `protected.py` are **not** touched. The exact anchors of the
edits above are in `docs/plan/parallel-ownership.md` §2.1. New tests go in new modules only (rule 2.0.5).

## Interfaces

**Provided to other increments:**

* `l4.memory.inject.inject_for_task(worktree, cfg.memory, task_paths, task_kinds, writer) -> Injection(block, ids,
  bytes)`. Any prompt builder can call it (later: the clarifier context, and the OpenCode or Kiro channels).
* `l4.memory.serena`:
  * `mcp_server_for(adapter, worktree, tmp) -> McpServer | None`;
  * `mcp_timeouts(adapter)`: OpenCode ≥ 20000 ms; Codex 30 s;
  * `check_serena(...) -> SerenaStatus`.

  M1.2's OpenCode adapter puts the server into `OPENCODE_CONFIG_CONTENT.mcp` with that timeout. A Kiro adapter never
  lists it under `--require-mcp-startup`.
* `l4.memory.curate.LESSON_RULES` and `curate(...)`. Fix units (when built) add the SPEC origin (a). Guard
  violations already feed origin (b).
* `l4.llm.system_one`:
  * `SystemOneBackend.ask(state, questions) -> {id: p}`;
  * `open_s1_backend`;
  * `LayaServe`;
  * `SystemOneJudge` (an `S1Judge`).

  M1.2's chain walking can absorb `open_s1_backend` unchanged.
* `l4.gates.e2e.run_e2e(...)`. The test bootstrap unit (L4-ODD-002) can reuse it.
* The naming convention `e2e/test_l4_c_<hex>.py`. Any id-based tracer (the future `traceability.py`) sees these tests.

**Needed from other increments:**

* **M1.1 Stage C**:
  * the routed job, the sweeper/archive and `l4 upgrade` (G11) for protocol steps 0–3;
  * `verify_hook` keeps committing and pushing its evidence inside the hook, before the hand-off. Line 36 relies on
    that ordering, so the `chore(memory)` commit lands before H. If M1.1 moves that commit, line 36 moves with it.
* **M1.2 (fallback chains, OpenCode)**:
  * no hard dependency;
  * if M1.2 edits `codex.py` or `claude_code.py` `build_command`, line 29 is rebased onto it (it is a separate branch on
    `req.mcp_servers`);
  * `RoleUnavailable` semantics are unchanged.
* **The seam commit S0:** `l4.verifier.testwriter` (line 25).
* **M1.3 (verifier depth, built in parallel and merged before M1.5):**
  * `trace_criteria(…, extra_reports=)` supersedes `trace_e2e` (group 2);
  * `aggregate_criterion(…, trace=)`;
  * `commit_verifier_tests`;
  * `after_verdict`;
  * the `subject_sha` rule that ignores `L4-Phase: lessons`.

  Its fix units can later turn D5 into SPEC's literal origin (a). That is a follow-up, not in this plan.
* **sandbox-security**: none beyond the P1-conditional `/dev/shm` line.

## Live exit protocol on `example-group/dummy-agentic` through `l4-runner`

Preconditions:

* The M1.1 live protocol (G13) has passed: routed job `l4`, sweeper, archive MRs. It has never run as of `98e4939`.
* The M1.2, M1.3 and M1.4 protocols have finished (parallel-ownership §5.3).
* M1.5 is built with `uv run pytest -q` green.
* The harness pinned by `l4 upgrade` is the `main` commit right after M1.5's merge. `main` is protected, so the "maintainer" steps need the Maintainer role. The operator may act
as the human (SPEC Q9).

**Pipelines.** The lesson reaches `main` only through a human merge (L4-MEM-002a: agents see base plus own branch). So
this protocol checks two harness pipelines (P1, P3) plus the merge pipeline P2, one more than the preferred two. No new
credential is needed: no TypeSafe key, and Jev is not run.

0. **Operator, runner and local.**
   * Run M15-G1 through `mk-ssh.sh`: `prereqs.sh --apply --with-serena --with-playwright` (plus `--with-laya` when
     P2 = runner), then `--check`. Expected: PRQ-13, PRQ-14 (and PRQ-18) OK.
   * Run M15-G2 (one probe pipeline) and record P1–P3 in `docs/runner/`.
   * If P2 = Mac: start Laya on the Mac:

     ```bash
     uvx --from 'laya[serve]==0.3.24' laya-serve --host 0.0.0.0 --port 8790 --model typed-decisions
     ```

     Then, from the runner (`mk-ssh.sh`), `curl -s http://192.0.2.10:8790/health` must give 200. The flag spelling is
     whatever M15-G2(c) recorded.
1. **Operator, local.**
   * On a clone of `main`, run `l4 upgrade --harness <harness>`. Expected: only `.l4/vendor/`, `.l4/ci/` and
     `.l4/bin/l4` change, plus the pins.
   * Add the seed files and the config additions below.
   * Run `uv lock` (playwright 1.63.0, pytest-playwright 0.9.0).
   * Locally, run `.venv/bin/python -m pytest -q` (the e2e tests are not collected) and
     `.venv/bin/python -m pytest e2e -q` against a manually started `python -m pricing.web.app`; both pass.
2. **Maintainer:** commit and push to `main`: "Seed the cart web page, e2e smoke test and show-item-count; enable
   lessons, Serena, Playwright and Laya (M1.5)". Expected pipeline **P1**:
   * **Doctor:** MEM-001 ok, and warn-level checks show Playwright browsers, Serena 1.7.0 and Laya present (Laya
     "remote" when P2 = Mac).
   * **Plan:** `show-item-count implement`.
   * **Implementer:**
     * ledger `memory.serena{status: ok}` before the first agent step;
     * Codex red → green for 1.1;
     * no `lessons.injected` (the lessons file is empty).
   * **Verifier, in ledger order:**
     * step 3: test and e2e gates pass (1 smoke test at head);
     * step 4 (with the e2e report): `C-de7f2d3f` uncovered and UI-facing;
     * step 5: `verify.generated{criterion: C-de7f2d3f, test: e2e/test_l4_c_de7f2d3f.py, base: fail, head: pass,
       attempts: 1|2}`;
     * step 8: one `verify.s1{criterion: C-de7f2d3f, p, model}`, and `.l4-out/s1/<run>.jsonl` (artefact) holds one line;
     * when P2 = runner, the job log shows `laya-serve` started and stopped inside step 8;
     * step 9: the judge passes.
   * **`verification.md`:** PASS. Row `C-de7f2d3f` lists the generated test with base fail / head pass and the S1 p.
   * **Branch commits, in this order:**
     1. red and green checkpoints;
     2. `test(show-item-count): verifier round 1 [skip ci]`;
     3. `docs(show-item-count): verification round 1 [skip ci]`;
     4. `chore(memory): lesson L-09421538 … [skip ci]` with trailer `L4-Phase: lessons`;
     5. hand-off commit H.
   * **Lesson:**
     * ledger `lessons.curated{action: created, id: L-09421538}`;
     * on the branch, `lessons.md` has `## L-09421538 · UI criteria need an end-to-end test`, with Scope
       `` `src/pricing/web/**` `` and Dedupe key `ui-criterion-without-e2e-test`.
   * **MR:** ready, label `l4:in_review`, head = H; the project's own `test` job on H is green (ruff and pytest, with
     the generated test linted).
   * **Job:** exit 0.
3. **HUMAN (or operator acting as the human):** merge the show-item-count MR in the UI. Expected **P2** (M1.1
   behaviour): an archive MR is opened, and `l4 run` has nothing to do. `main` now holds `lessons.md` with
   `L-09421538` and `e2e/test_l4_c_de7f2d3f.py`.
4. **Maintainer:** commit and push to `main`: "Seed show-subtotal". Expected **P3**:
   * **Plan:** `show-subtotal implement`.
   * **Lesson injection:**
     * the red prompt artefact (`.l4-out/agent/*-red-*.prompt.md`) contains `<l4:data kind="lessons"
       ids="L-09421538">`;
     * `prompt.rendered.lessons == ["L-09421538"]`;
     * ledger `lessons.injected{ids: ["L-09421538"], channel: prompt_section}`, before the first `agent.session`.
   * **Informational:**
     * if Codex wrote an e2e test whose id carries `68f2e098`, step 5 is skipped for `C-68f2e098`;
     * otherwise a second generated test is accepted and `lessons.curated{action: reinforced, id: L-09421538}` follows
       (`Reinforced: 2 · <date>`).
   * **Verdict:** PASS, MR ready, exit 0.
5. **Operator, read-only checks:**
   * the `.l4-out/s1/*.jsonl` artefacts of P1 and P3 have one line per criterion, with model, `p` and state sha;
   * no `laya-serve` process is left (`mk-ssh.sh` `pgrep -u gitlab-runner -f laya-serve` is empty);
   * the `[skip ci]` commits (checkpoints, `test(…)`, `docs(…)`, `chore(memory)`) have no `l4` job;
   * no `l4` job ran on a harness-authored commit;
   * record the peak memory lines of the job logs.
6. **Not run, recorded:** Jev. It is blocked on a human action: obtain a TypeSafe key and store it as the masked CI
   variable `TYPESAFE_API_KEY` (already in `redact_env`). Then `profiles.jev: {backend: system-one, engine: jev, model:
   jev-1.13.0, api_key_env: TYPESAFE_API_KEY}` goes first on `s1_judge`.

**Pass** = steps 2–5 behave as expected. Record every pipeline, job and MR id in `docs/live/README.md`.

* **Retry rule:** if step 5 of P1 fails twice (`not_testable` or non-discriminating), the unit ends NEEDS_HUMAN
  (exit 11) and no lesson is curated. Record the generator replies, reset the unit, and run one web pipeline. A second
  miss is a FAIL.
* **Serena:** a `memory.serena{status: failed}` does not fail the unit (SCN-MEM-06), but it fails this protocol's
  Serena check. Record the reason.

### Seed texts (operator adapts imports to the real `pricing` package; the page module below imports nothing from it)

`src/pricing/web/__init__.py`:

```python
"""The cart page served for end-to-end tests."""
```

`src/pricing/web/page.py`:

```python
"""HTML of the cart page."""

from decimal import Decimal
from html import escape

Line = tuple[str, Decimal, int]

DEMO_LINES: tuple[Line, ...] = (
    ("Pen", Decimal("1.50"), 2),
    ("Notebook", Decimal("2.00"), 3),
)


def render_page(lines: tuple[Line, ...] = DEMO_LINES) -> str:
    rows = "".join(
        f'<tr data-testid="line"><td>{escape(name)}</td>'
        f"<td>{price}</td><td>{qty}</td></tr>"
        for name, price, qty in lines
    )
    return (
        "<!doctype html><html><head><title>Cart</title></head><body>"
        f'<h1>Cart</h1><table data-testid="lines">{rows}</table>'
        "</body></html>"
    )
```

`src/pricing/web/app.py`:

```python
"""Serve the cart page: python -m pricing.web.app --port 8765"""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pricing.web.page import render_page


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            body, ctype = b"ok", "text/plain"
        elif self.path == "/":
            body, ctype = render_page().encode("utf-8"), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    port = parser.parse_args().port
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
```

`tests/test_web_page.py`:

```python
from pricing.web.page import render_page


def test_page_lists_the_demo_lines() -> None:
    html = render_page()
    assert "Pen" in html and "Notebook" in html
```

`e2e/test_smoke.py`:

```python
import os

from playwright.sync_api import Page, expect

BASE_URL = os.environ["L4_E2E_BASE_URL"]


def test_cart_page_loads(page: Page) -> None:
    page.goto(BASE_URL + "/")
    expect(page.get_by_role("heading", name="Cart")).to_be_visible()
```

`pyproject.toml`:

* add `playwright==1.63.0` and `pytest-playwright==0.9.0` to the dev dependency group;
* set `[tool.pytest.ini_options] testpaths = ["tests"]` (create the table if it is absent);
* then run `uv lock`.

`.gitattributes` (append):

```text
.serena/memories/** text eol=lf
.serena/memories/harness/lessons.md merge=union
```

`.serena/project.yml` (the keys the harness needs; Serena 1.7.0 rewrites the file into its full form at every start, which the harness tolerates: `Workbench.settle_serena_project`):

```yaml
project_name: dummy-agentic
language_servers: [python]
read_only_memory_patterns: ["(?!inbox/).*"]
ignored_memory_patterns: ["harness/_archive/.*"]
initial_prompt: "{{ embed_memory('harness/lessons') }}"
```

`.serena/memories/harness/lessons.md`:

```markdown
<!-- l4:lessons v1 — harness-owned; propose changes via .serena/memories/inbox/ -->
```

`.l4/config.yaml` additions (merge into the existing sections; `roles.s1_judge` replaces the M1.1 value):

```yaml
gates:
  e2e:
    command: .venv/bin/python -m pytest e2e -p no:cacheprovider --junitxml=.l4-out/e2e-junit.xml --output .l4-out/e2e/artifacts --tracing retain-on-failure --screenshot only-on-failure
    reports: [.l4-out/e2e-junit.xml]
    format: junit
    serve:
      command: .venv/bin/python -m pricing.web.app --port 8765
      ready_url: http://127.0.0.1:8765/health
      timeout: 60s
verifier:
  playwright:
    enabled: true
    ui_paths: ["src/pricing/web/**"]
  fix_minor_findings: false      # reset M1.3's live lever: a fix unit after round 1 would leave no PASS that curates L-09421538
  audit_sample_ratio: 0          # reset M1.3's live lever: no audit calls on top of the generator and the judge
profiles:
  laya:
    backend: system-one
    engine: laya-local           # P2 = Mac: engine: remote, base_url: http://192.0.2.10:8790
    model: typed-decisions
    vendor: convai
roles:
  verifier_agent: [claude-code]
  s1_judge: [laya, claude-code]  # claude-code is the llm_boolean stand-in only with clarifier.s1_standin: llm_boolean
                                 # (default none: an unusable Laya then means no auto-accept, NoS1)
memory:
  enabled: true
  serena: {enabled: true, version: "1.7.0", context: auto}
```

`openspec/changes/show-item-count/`:

* `.openspec.yaml`:

  ```yaml
  schema: spec-driven
  created: 2026-10-04
  ```

* `proposal.md`:

  ```markdown
  # Proposal: item count on the cart page

  ## Why
  Shoppers want to see how many items are in the cart without adding up the quantities themselves.

  ## What Changes
  - The cart page shows the total quantity of its line items as `Items: N`.

  ## Capabilities

  ### New Capabilities
  - `cart-page`: the HTML cart page served by `pricing.web.app`.

  ### Modified Capabilities

  ## Impact
  `src/pricing/web/page.py` (`render_page`), tests under `tests/`.
  ```

* `specs/cart-page/spec.md`. It has one scenario only: a criterion the served demo page cannot show (e.g. an empty
  cart) would be `not_testable` and turn the unit NEEDS_HUMAN.

  ```markdown
  # Spec Delta

  ## Purpose
  The cart page shows a shopper what the cart holds.

  ## ADDED Requirements

  ### Requirement: Item count
  The cart page SHALL show the sum of the quantities of its line items in an element with `data-testid="item-count"`, as the text `Items: N`.

  #### Scenario: Demo cart
  - **WHEN** the cart page is opened for the demo cart (2 × Pen, 3 × Notebook)
  - **THEN** the page shows `Items: 5`
  ```

* `tasks.md`:

  ```markdown
  # Tasks

  ## 1. Item count

  - [ ] 1.1 Show the item count (`Items: N`, the sum of the quantities) in `data-testid="item-count"` on the cart page in `src/pricing/web/page.py`
  ```

`openspec/changes/show-subtotal/` (step 4). The `.openspec.yaml` is the same as above. The WHEN differs on purpose from
show-item-count's, which is in the base specs once its archive MR merges (G9 keys on GIVEN + WHEN). The capability is
new, so the change does not depend on that archive MR.

* `proposal.md`:

  ```markdown
  # Proposal: subtotal on the cart page

  ## Why
  Shoppers want to see what the cart costs before discounts and VAT.

  ## What Changes
  - The cart page shows the subtotal of its line items as `Subtotal: X`.

  ## Capabilities

  ### New Capabilities
  - `cart-page-subtotal`: the subtotal line of the HTML cart page.

  ### Modified Capabilities

  ## Impact
  `src/pricing/web/page.py` (`render_page`), tests under `tests/`.
  ```

* `specs/cart-page-subtotal/spec.md`:

  ```markdown
  # Spec Delta

  ## Purpose
  The cart page shows a shopper what the cart costs before discounts and VAT.

  ## ADDED Requirements

  ### Requirement: Subtotal on the cart page
  The cart page SHALL show the sum of unit price times quantity of its line items, with two decimals, in an element with `data-testid="subtotal"`, as the text `Subtotal: X`.

  #### Scenario: Demo cart subtotal
  - **WHEN** the cart page is opened for the demo cart (2 × Pen at 1.50, 3 × Notebook at 2.00)
  - **THEN** the page shows `Subtotal: 9.00`
  ```

* `tasks.md`:

  ```markdown
  # Tasks

  ## 1. Subtotal

  - [ ] 1.1 Show the subtotal (`Subtotal: X`, two decimals) in `data-testid="subtotal"` on the cart page in `src/pricing/web/page.py`
  ```

## Risks

* **Memory on 3.8 GB.**
  * Laya's peak RSS (1.3–2.3 GB [I]) may not fit next to the runner's baseline. D7 runs it only around S1 batches, never
    with Chromium (about 0.3–0.4 GB [I]) or Serena with Pyright (about 0.4–0.6 GB [I]) next to Codex.
  * M15-G2 decides runner or Mac. With the Mac, Laya runs only while the operator keeps `laya-serve` up, and the port is
    unauthenticated on the LAN for that time.
* **Chromium in bwrap** is [U] (`/dev/shm`, read-only HOME, loopback in an unshared network). M15-G2(a) settles it
  before any line depends on it. If it fails with both variants, step 5 cannot run on the runner and the UI part of the
  exit moves to a Mac-local `l4 verify` (`NoSandbox`, not a CI pass).
* **S1 with Laya.**
  * Zero-shot Laya is near chance and over-confident [V research/03]. Step 8's `p` is calibration data only (D8).
  * In the clarifier, Laya replaces the stand-in, so M1.1 step 4a's auto-accept will probably no longer reproduce [I].
    The failure is fail-safe: questions go to a human.
  * The 463-token window [V] may cut states (P3).
* **Laya churn.** There were 34 releases in about 16 days [V PyPI]. The pin is 0.3.24, the version verified locally,
  and M15-G2 confirms that it loads `typed-decisions`.
* **Generator quality and cost.** Claude `pro` makes 1–2 generator calls per uncovered UI criterion on top of the
  judge. The tests can be brittle; mitigations are the `data-testid` wording in the specs, the page snapshot and one
  retry. A failing-at-head test never FAILs the unit (it is `needs_human`).
* **Serena** adds edit tools and a language server to the Codex step. Edits still go through the protected-path revert,
  and harness memories are read-only to Serena (`read_only_memory_patterns`). Cold Pyright via `uvx` inside the agent
  sandbox is [U] (M15-G2(b)).
* **Origin (a) is a reduced reading** of L4-MEM-002 (D5). Once fix units exist, curation must switch to their PASS.
* **Ordering against M1.1 Stage C.** If the hand-off moves out of the flow that follows `verify_hook`, the
  `chore(memory)` commit could land after H and become the MR head with `[skip ci]`, which is exactly the M1.1 hazard.
  Line 36 has a test asserting that the commit comes before H.

## Doc changes owed (no build line; SPEC.md is not edited here)

* L4-FAC-004 and the `profiles.laya` comment: `engine: remote` (any TypeSafe-wire server at `base_url`); `laya-serve`
  runs around each S1 batch.
* L4-MEM-002 (a): the M1.5 reading (D5) until fix units exist; `LESSON_RULES`; the lesson text is a harness template.
* L4-VER-014: the UI baseline is the merge-base app (D3). The e2e launcher runs serve and tests in one gate spawn, and
  `L4_E2E_BASE_URL` is the origin of `ready_url`.
* §10.2 step 5: the tool-less generator and `l4/generated-test@1`; the generated file path `e2e/test_l4_c_<hex>.py`.
* §3.2: `gates.e2e.format: junit` for pytest-playwright.
* L4-VER-008: the per-run copy `.l4-out/s1/<run-id>.jsonl`.
* §22 Q4: decided by M15-G2. `typed-decisions` and `english` are the same size and share the apache-2.0 card [V HF].
* runner README: PRQ-14 path and PRQ-18.
