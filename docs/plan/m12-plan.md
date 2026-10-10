# M1.2 — availability, fallback chains and more adapters (planned 2026-10-04)

## Goal

M1.2 lets a run keep going when an agent subscription is exhausted. Every role walks its chain: each profile is probed
cheapest-step-first (binary, auth, quota, hello), cool-downs are remembered, and SPEC 8.4 logs every decision. A limit
hit mid-run switches to the next profile in a fresh session. A required chain with nothing left parks the unit in
`waiting_capacity` (exit 12, `retry_after`) until `l4 plan` sends it back. The OpenCode, Kiro CLI and command adapters
join codex and claude-code. This delivers SPEC §8 (L4-FAC-001…009, L4-AVL-001…010) and the decided Q9: when Claude Code
(`pro`) is exhausted the harness falls back to Codex or OpenCode, judges keep the independence rule, and a verdict that
rests on an operator-declared OpenCode Zen vendor says `independence: declared (unverified)`.

Starting point: M0 and M1.1 as built (`docs/plan/m0-progress.md`, `docs/plan/m11-progress.md`).
`Factory.for_role` still probes only the first profile of a chain. Any probe failure is `RoleUnavailable` (exit 12),
`quota` is always `skipped`, and `min_version` is ignored [V, `src/l4/agents/factory.py`,
`src/l4/availability/probes.py`].

**Size: 38 build lines = 31 tasks + 7 gap tasks (G14–G20), in three stages.** Absorbed tasks are named inside their
line.

## Decisions

* **Chain walk without breaking callers.** `WaitingCapacity(retry_after)` subclasses `RoleUnavailable`, so every
  existing `except RoleUnavailable` keeps working (orchestrator, clarifier, router, ladder, doctor).
  * Required roles (`implementer`, `verifier_agent`, `judges`) raise `WaitingCapacity`. Optional roles (`clarifier`,
    `s1_judge`, `spec_writer`) raise `RoleUnavailable`.
  * `serves=` now skips a profile that cannot serve the role and goes on down the chain. In M1.1 it raised.
* **Per-profile reserve (G15).** A new key, `profiles.<p>.min_remaining_percent` (0–100), overrides the global
  `availability.min_remaining_percent` for that profile. It is additive: the `Profile` model stays strict.
  * Use: an operator keeps part of a subscription the maintainer also uses by hand.
  * It is also the deterministic live lever for a quota fallback (step 3).
  * SPEC 3.2 has only the global key (doc change owed).
* **An unrecognised quota answer skips the step; it never fails the profile.**
  * The runner's Claude `pro` `/usage` text is [U]: spike 05 recorded a Max plan.
  * Failing the profile on a parse miss would empty Q9's judge chain whenever claude-code is first.
  * So the step is `skipped`, with an `availability.quota_unrecognised` event. This deviates from SCN-FAC-07 for the
    quota step only. Binary, auth and hello drift still fail the profile.
* **Vendor provenance (G19).** Each vendor used in an independence check is one of four kinds:
  * `served`: the adapter reported the served model (claude-code `modelUsage`);
  * `tool`: a single-vendor CLI (codex) [I];
  * `declared`: the adapter reports no served model, as with opencode, kiro-cli and command
    (`availability.model_unverified`). The profile's own `vendor:` counts;
  * `unknown`: no `vendor:`, or `vendor: unknown`. Never independent, so SCN-AVL-19 still holds for such a profile.

  When any vendor in the check is `declared`, `verification.md` says `independence: declared (unverified)`, on both
  sides: a declared judge and a declared implementer alike.
* **Independence is conservative.** The excluded vendors are those of every implementer profile in
  `UnitState.profiles_used` (from `availability.selected`). A profile selected at `ready` that was replaced before it
  wrote a commit still excludes its vendor. That costs some judge choices but never relaxes L4-VER-001.
* **`L4-Fallback-From` names `chain[0]`, the preferred profile, whenever `fallback_index` ≥ 1** [I]. The SPEC example
  shows only index 1.
* **Mid-run limit.**
  * `Orchestrator._implement` catches `RoleLimit` from `run_task`, then:
    * `Factory.on_limit` records the cool-down, invalidates the probe cache, writes `availability.cooldown` and
      `availability.fallback`, and selects again;
    * the `Workbench` is **rebuilt**: its sandbox spec (which login is visible) and its trailers depend on `selected`;
    * a task whose red is already committed takes the existing green-only path.
  * In `verify_hook`, a judge that hits a limit or reports a mismatching served model gives way to the next independent
    judge within the same round.
* **`waiting_capacity` re-entry lives in `l4 plan`, not in `ci/sweeper.py`.** `ci/sweeper.py` is still changing in M1.1
  Stage C.
  * Once the folded `retry_after` has passed, the planner gives the previous phase's action, and `l4 run` (already in
    every job) picks the unit up. This is forge-and-ci 2.32 in reduced form.
  * A unit parked before it has a branch is never pushed (`Orchestrator._worth_pushing`), so its ledger stays local. It
    plans as new in every pipeline, and selection checks the runner's local cool-downs without sending a request.
    Accepted.
* **`l4 probe --no-cache` re-probes a cooling profile; a passing ladder clears its cool-down.** This is the operator's
  way to undo a forced or stale cool-down (live step 6). `l4 probe` is already in `commands.HANDLERS` and `cli.py` [V].
* **CFG-003 is deferred, and SPEC 3.2 conflicts with Q9.**
  * SPEC 3.2 requires a judge to remain for the **union** of the implementer chain's vendors.
  * Q9's reference chains make that union {openai, declared, anthropic}, which leaves no judge. Built as written,
    CFG-003 would reject the decided configuration (doc change owed).
  * Run-time selection already enforces independence for the profiles actually used.

## Parallel work (how this increment goes faster)

* **G14 first.** It is live, zero-cost and takes about 10 minutes through `mk-ssh.sh`, so it runs while line 2 is
  written.
* **Line 2 pins the shared types**: `LimitSignal` fields, `AgentCaps.served_model`, the `Selected` fields,
  `WaitingCapacity`. After it, Stage A (lines 3–19) and Stage B (lines 20–26) are **two parallel streams**: they share no
  file except `agents/base.py` (line 2) and one tuple entry in `config/defaults.py` (G17).
  * In Stage A, lines 3–11 are independent leaf modules (∥). Lines 12–19 follow each other: ladder → selector → lines →
    waiting → `for_role` → `on_limit` → gate → `l4 probe`.
  * In Stage B, lines 20–22 follow each other (OpenCode). Lines 23, 24, 25 and 26 are ∥.
* **Stages A and B touch none of the M1.1 Stage C files** (`forge/`, `ci/`, `archive.py`, `postmerge.py`,
  `state/pending.py`, `init/`, `vcs/git.py`). M1.1 Stage C has since landed.
* **Stage C no longer waits for M1.1: M1.1 Stage C has landed** (m11-progress lines 26–41, `98e4939`). Stage C edits
  `orchestrator.py`, `planner.py`, `verifier/ladder.py` and `verifier/judge.py`. M1.3 and M1.4, which are built in
  parallel, edit those files too, so every edit stays at the anchor given in `docs/plan/parallel-ownership.md` §2.
  * Only the live protocols stay in order: M1.1's G13 runs on `dummy-agentic` before M1.2's (same runner, same repo).
    G13 has never run (`parallel-ownership.md` §5.3, L0).
* **Parallel with M1.3, M1.4 and M1.5.** The shared-file anchors, the contracts (C1–C6, C21) and the merge order
  (M1.2 first) are in `docs/plan/parallel-ownership.md`. The version comparison of line 11 comes from the seam commit
  S0 (`l4.versions`).
  * Within Stage C: 27, 28 and 31 are ∥. Then 29 → 30. The verifier lines 32 → 33 → 34 → 35 run ∥ with 36. Line 37 comes
    after all of them, and 38 is last.
* Implementers on Sonnet per the standing rule; one review per stage on the session model.

## Build list

Line format: `change-id task — what M1.2 builds`, numbered in build order across the stages.

### Stage A — availability core (∥ Stage B once line 2 is in)

1. G14 (gap) — record the runner's probe outputs (Kiro logged out, Claude `pro` `/usage`, codex app-server, OpenCode
   version); zero cost
2. agent-factory 1.1 (delta) — pin the shared types:
   * `LimitSignal.window_minutes` and `used_percent`;
   * `AgentCaps.served_model`;
   * `Selected.fallback_from`, `vendor` and `provenance`;
   * `WaitingCapacity(RoleUnavailable).retry_after`;
   * `REQUIRED_ROLES`.
3. agent-factory 1.16 — `CooldownRegistry` in `$L4_CACHE/availability.json`:
   * key `(tool, model)`, with `*` for the whole tool;
   * `flock` plus atomic replace;
   * expired entries pruned;
   * a corrupt file is read as empty, with a warning;
   * `clear(key)`.

   Absorbs 7.6: the `availability.cooldown` event and `earliest_reset()`.
4. agent-factory 1.17 — `ProbeCache` keyed by `(profile, identity_hash)`: `availability.cache_ttl`, failures cached too,
   `invalidate`. Also `Clock`/`SystemClock`/`FakeClock` (`now()` UTC-aware, `FakeClock(start).advance(delta)`). These
   are the harness's only clock classes: M1.4's simulation uses them and builds none of its own (parallel-ownership
   C3). Absorbs 8.4: the hash covers tool, auth and credential dir, and no value is ever stored.
5. agent-factory 7.5 — `normalise_limit`:
   * structured sources first: codex `resetsAt`; claude `rate_limit_event` (`rejected` + `resetsAt`); opencode
     `statusCode` 402 → `credits` and 429 → `rate_limit`, with `limit_source`;
   * then the Google body text "retry in 9h9m42s";
   * a locale-tolerant text parser last.

   Not limits: claude 404, codex 400 and opencode `Token refresh failed: 401` stay `error` or `auth`.
6. agent-factory 7.2 — the `quota` step contract:
   * `skipped` when no zero-cost query exists;
   * the any-window rule;
   * reason `N% remaining < M%`;
   * the cool-down ends at the binding window's `resets_at`. When several windows bind, it ends at the latest of them,
     so an early re-probe does not find the weekly window still binding and cool the profile again.
7. G15 (gap) — per-profile reserve `profiles.<p>.min_remaining_percent`
8. agent-factory 4.3 — one `codex app-server` session (about 1 s, zero tokens). Absorbs 4.4, and the codex part of 7.1.
   * The auth step is `account/read`, keeping `type` and `planType`. It replaces `codex login status`.
   * The quota step is `account/rateLimits/read`:
     * the bucket whose `normalModelSlug` equals the model, else `codex`;
     * both `primary` and `secondary`;
     * also exhausted on `ordinaryUsageAllowed:false`, on `rateLimitReachedType` other than null, or on
       `spendControlReached`;
     * reset credits are never redeemed.
   * `-32600` makes quota `skipped`.
9. agent-factory 2.2 — Claude quota. 2.1 (auth) is kept as M0 built it.
   * `TZ=UTC claude -p --safe-mode --no-session-persistence --output-format json "/usage"`, parsed with spike 05's
     `USAGE_RE`:
     * windows: session, weekly (all models), weekly (model family);
     * the year is the next occurrence of the date.
   * The latest `rate_limit_event.unifiedWindows` is preferred when one is at hand.
   * With `auth: api_key`, the step is `skipped`.
   * Unrecognised text → `skipped` (see Decisions).
10. G16 (gap) — OpenRouter-backed quota (`/api/v1/credits` + `/api/v1/key`, `min_remaining_usd`, `credits_cooldown`)
11. agent-factory 1.18 — the `binary` step compares `min_version` with the `--version` output (reason
    `version X < min_version Y`) through `l4.versions.version_at_least` from the seam commit S0, which M1.4's ENV-004
    and installers use too. M0 skipped this.
12. agent-factory 1.20 — `ProbeLadder.run`:
    * steps in `availability.default_ladder` order (`mcp` and `custom` are `skipped`);
    * stop at the first failure;
    * a cool-down only from a step that returned a `LimitSignal`.
13. agent-factory 1.21 — `FallbackSelector.select`, profile by profile in chain order:
    * a profile that cannot serve the role (`serves`) is skipped, never fatal;
    * then the constraints;
    * a cooling profile is skipped without any request;
    * a fresh cached probe is used as it is;
    * otherwise the ladder runs.

    Absorbs 7.7 (optional roles) and 7.8 (an expired cool-down is re-probed).
14. agent-factory 1.22 — the exact SPEC 8.4 console lines:
    * skipped;
    * cooling (`no probe sent`);
    * ok, with `fallback #n` and `· cached`;
    * a skipped step is shown as `<step> skipped` [I].

    Plus one `availability.selected` per selection, with `quota_window`, `cached` and `fallback_from`.
15. agent-factory 1.23 — a required chain with nothing usable raises `WaitingCapacity(retry_after)`: the earliest end of
    a cool-down, else now + `default_cooldown`. An optional chain raises `RoleUnavailable`.
16. agent-factory 1.24 — `Factory.for_role(role, unit, *, serves=None, constraints=())` over the selector. It replaces the
    M0 first-profile form; `fallback_from` = `chain[0]` when the index is ≥ 1.
17. agent-factory 1.25 — `Factory.on_limit(selected, run)`:
    * records the cool-down and invalidates the probe-cache entry;
    * writes `availability.cooldown` and `availability.fallback{from, to, reason, resets_at}`;
    * selects again: the limited profile is now cooling.
18. agent-factory 8.3 (reduced) — `ConcurrencyGate`:
    * `profile.max_concurrency` flock slots (default 1 for subscription) per `(tool, identity_hash)` under
      `$L4_CACHE/locks`;
    * a wrapping adapter holds a slot around each `run`;
    * a busy profile is skipped when a later one is usable, else waited for up to 120 s.
19. agent-factory 9.5 — `l4 probe [PROFILE…] [--role R] [--json] [--no-cache]`:
    * `l4/probe@1`, which also lists the cool-downs and the path of the availability file;
    * `--no-cache` re-probes a cooling profile, and a passing ladder clears its cool-down.

*Exit:*

* unit tests pass;
* SCN-AVL-02 with `FakeClock` and fakes: codex at 100 % is skipped, its cool-down is recorded, and claude-code is
  selected with the exact lines and event;
* on the operator's machine, `uv run l4 probe --json` lists codex, claude-code and opencode with real quota windows.

### Stage B — adapters (∥ Stage A once line 2 is in)

20. agent-factory 1.10 — `OpenCodeAdapter.build_command` and env:
    * `opencode run --pure --format json -m <model> --dir <worktree> --title "l4 <unit> <task> <phase>"`, prompt on
      stdin;
    * `XDG_CONFIG_HOME` = an empty dir under the step's agent tmp; `XDG_DATA_HOME` untouched;
    * `OPENCODE_DISABLE_{PROJECT_CONFIG,CLAUDE_CODE,EXTERNAL_SKILLS,AUTOUPDATE}=1`;
    * `OPENCODE_CONFIG_CONTENT` as in SPEC 8.3.1: `snapshot:false`, `share:disabled`, the permission map, and
      `external_directory` deny-then-allow for the result dir;
    * prompt contract through `$L4_RESULT_PATH`.

    Absorbs 1.12: wall clock and stall watchdog through `ProcRunner`.
21. agent-factory 1.11 — `OpenCodeAdapter.parse`:
    * the text parts joined, cost summed;
    * `ok` only when the last reason is `stop`;
    * `tool-calls` plus a rejection error → `permission_blocked`;
    * 402 → `quota` and 429 → `rate_limited`, through line 5;
    * 401 → `auth`; 503 → `error`.

    `availability.model_unverified` is written at selection. Absorbs 3.2.
22. agent-factory 1.19 + 7.1 (opencode rows) — OpenCode probes:
    * binary;
    * auth: the free `opencode/*` models need no login → `skipped` [V, runner]. Other providers: `auth list`, presence
      only;
    * hello, isolated: empty cwd and config dir, tools off, stdin `DEVNULL`.
23. G17 (gap) — OpenCode inside the agent sandbox (`~/.cache/opencode` mounted for opencode only, the per-step config
    dir, the parity probe on the runner)
24. G18 (gap) — tool-less judge modes for opencode and codex; `JUDGE_ADAPTERS` gains both
25. agent-factory 5.1 (reduced) — `KiroCliAdapter`:
    * binary;
    * auth by `whoami --format json`, with the e-mail dropped. Logged out → `kiro-cli installed, not authenticated`;
    * quota `skipped`;
    * the argv of SPEC 8.3 with a prompt-contract result; exit 3 → MCP startup error;
    * the run is experimental: `agent.experimental` is written once.
26. agent-factory 5.2 — `CommandAdapter`:
    * `options.argv` with `{prompt_file}`, `{result_path}`, `{model}` and `{session_id}`;
    * `options.probe_argv`;
    * an unknown placeholder is refused at load;
    * prompt contract.

*Exit:*

* the replay tests over `tests/fixtures/recorded/opencode/1.18.33/` and the G14 recordings pass;
* the G18 smoke test passed on the operator's machine;
* `CLIS=opencode SANDBOX=m0` (G17) passes on `l4-runner`.

### Stage C — wiring (starts once M1.1 Stage C has landed)

27. state-vcs-locks 1.18 (delta) — the fold gains `UnitState.retry_after`, from the `phase.changed` into
    `waiting_capacity`, and `UnitState.fallback_from` per role, from `availability.selected`
28. implementer-tdd-loop 1.27 (delta):
    * `_park` puts `WaitingCapacity.retry_after` into the edge context and the log line;
    * `_outcome` fills `retry_after` and `profiles.fallback_from` (the SPEC 2.2 shape); a run that selects no implementer
      (resumed at `verifying`) takes both from the folded state (`profiles_used`, `fallback_from`).
29. agent-factory 1.25 (consumer) + implementer-tdd-loop 2.25 (reduced) — mid-run fallback in `Orchestrator._implement`:
    * `RoleLimit` → `on_limit` → a new `Selected` → a new `Workbench`;
    * the task continues from its last pushed checkpoint, in a fresh session. The prompt carries
      `<l4:data kind="previous-attempt">` (profile, limit kind, no transcript);
    * nothing left → park (line 28).
30. implementer-tdd-loop 2.20 — `L4-Fallback-From` and `L4-Agent`, from `Selected`, on every implementer commit
31. forge-and-ci 2.32 (reduced, in `planner.py`) — the `waiting_capacity` row:
    * once `retry_after` ≤ now, the next action is the previous phase's (`implement` or `verify`), with reason
      `capacity: retry_after <T> passed`;
    * before that, `none` (`waiting_capacity until <T>`);
    * `l4 run` takes it through `ACTIONABLE`. `ci/sweeper.py` is untouched.
32. verifier 1.3 — `independence_constraint` over the vendors (or models) of every implementer profile in
    `profiles_used`; `select_judge(factory, cfg, unit, implementer_profiles, *, role="judges", skip=()) -> Selected`
    walks `roles.<role>` through `for_role(constraints=…)`. It replaces `roles.judges[0]` and the
    `require_independent_judge` call in `verify_hook`. **The function `require_independent_judge` stays defined:**
    M1.3's audit fallback and M1.5's generator call it until they merge `main` after M1.2. It is removed only after M1.5
    is on `main` (parallel-ownership §4, item 6).
33. verifier 1.4 — every judge excluded or unavailable → `WaitingCapacity` with reason `no independent verifier`, exit 12,
    no judge called
34. verifier 1.10 + 1.11 (delta):
    * served-model check: claude `modelUsage` against a full model id in the profile, after normalisation (an alias such
      as `haiku` is not compared) → `availability.model_mismatch`, and the verdict is discarded;
    * a mismatch, or a limit (cool-down through `on_limit`), moves to the next independent judge in the same round.
35. G19 (gap) — vendor provenance and the `independence:` line in `verification.md` / `verdict.json`
36. clarification-loop 3.2 — the `clarifier` and `s1_judge` chains fall back at selection (Q9:
    `[claude-code, codex, opencode-free]`). A limit inside a batch keeps the M1.1 rule: the question is unavailable and a
    human answers.
37. agent-factory 9.4 (reduced) — scenario tests over `FakeAdapter` and `FakeClock` on the fixture repo:
    * SCN-AVL-02, 03, 08, 09, 10, 16, 17 and 19 (amended for Q9);
    * SCN-FAC-06, 09 and 12.
38. G20 (gap) — the live acceptance test of the protocol below

*Exit:* on the fixture repo with a bare remote:

* **Mid-run fallback.** Chain `[fake-a, fake-b]`, and fake-a returns `rate_limited` in green of task 1.1:
  * a cool-down is recorded, and `availability.fallback` is written;
  * fake-b finishes the task. fake-a's red commit is not redone;
  * the green commit carries `L4-Fallback-From: fake-a`.
* **Waiting for capacity.** With every profile cooling:
  * `waiting_capacity`, exit 12, and `outcome.json` `retry_after` = the earliest end of a cool-down;
  * with `FakeClock` past it, `l4 plan` says `implement` and `l4 run` re-enters on `capacity_restored`.
* **Judges.** A judge chain whose first profile has the implementer's vendor, and whose next one serves a mismatching
  model:
  * the third judge's verdict is used;
  * `verification.md` names the independence.

## Gaps (no existing task covers them; no tasks.md was edited)

* **G14** (Stage A, first; agent-factory, live, zero cost) — Record what the runner's CLIs answer, as the runner user
  through `scripts/runner/mk-ssh.sh --script scripts/runner/record-probes.sh`. Each item below is one call:
  * `kiro-cli --version`;
  * `kiro-cli whoami --format json`, logged out: exit code, stdout and stderr;
  * `TZ=UTC claude -p --safe-mode --no-session-persistence --output-format json "/usage"` on the `pro` plan;
  * one `codex app-server` session (`initialize`, `initialized`, `account/read`, `account/rateLimits/read`). `email`,
    `chatgptAccountId` and `accountId` are dropped before anything is written;
  * `opencode --version`.

  The script masks by shape and prints only the kept fields. Recordings go to
  `tests/fixtures/recorded/<tool>/<version>/runner-*`.

  test: tests/contract/availability/test_runner_recordings.py::test_runner_recordings_parse (Kiro →
  `installed, not authenticated`; `pro` `/usage` → windows, or `unrecognised`) — code: scripts/runner/record-probes.sh —
  verify: uv run pytest tests/contract/availability -q
  * Why: three shapes are still unrecorded:
    * the logged-out Kiro shape is [U] (SPEC 8.3, kiro row);
    * the `pro` `/usage` text is [U] (spike 05 recorded a Max plan);
    * the codex app-server recordings come from macOS, not the runner's login.
* **G15** (Stage A; agent-factory + bootstrap-core config) — `profiles.<p>.min_remaining_percent` (0–100, optional)
  overrides `availability.min_remaining_percent` for that profile's `quota` step. When the profile's value is the one
  that binds, the reason names the reserve.

  test: tests/unit/availability/test_quota.py::test_profile_reserve_overrides_global (also
  tests/unit/config/test_schema_profile_reserve.py::test_profile_reserve_bounds, a new module: parallel-ownership
  rule 2.0.5) — code: src/l4/config/schema.py,
  src/l4/availability/quota.py — verify: uv run pytest tests/unit/availability/test_quota.py tests/unit/config -q
  * Why: SPEC 3.2 has only the global key. A subscription the maintainer also uses by hand needs its own reserve, and
    live step 3 needs a deterministic exhaustion.
* **G16** (Stage A; agent-factory) — The OpenRouter quota source. It applies to a profile whose model starts
  `openrouter/` (opencode), or whose `base_url` host is `openrouter.ai`. The `quota` step reads, with the profile's key
  from the probe env:
  * `GET /api/v1/credits`: balance = `total_credits − total_usage`;
  * `GET /api/v1/key`: `limit_remaining`, `limit_reset`.

  The step fails below `availability.min_remaining_usd`, with these limit signals:
  * a balance ≤ 0 → `LimitSignal(kind=credits)`, cool-down `credits_cooldown`;
  * a binding key limit → `rate_limit`, with `resets_at` at the next `limit_reset` boundary [boundary U].

  test: tests/unit/availability/test_openrouter_quota.py::test_negative_balance_is_credits_with_credits_cooldown
  (recorded `openrouter-api/v1/get_credits.json` and `get_key.json`, through httpx `MockTransport`) — code:
  src/l4/availability/quota.py — verify: uv run pytest tests/unit/availability/test_openrouter_quota.py -q
  * Why: agent-factory 7.2 names only `min_remaining_percent`; L4-AVL-001 and 003 add this source.
  * It is not run live: the runner has no OpenRouter key, and the spike's balance was negative.
* **G17** (Stage B; sandbox-security + agent-factory) — OpenCode inside the agent sandbox:
  * `~/.cache/opencode` joins `CREDENTIAL_PATHS["opencode"]`: mounted for opencode, hidden from every other sandbox;
  * `XDG_CONFIG_HOME` is an empty dir under the step's agent tmp;
  * `SANDBOX=m0` in `scripts/runner/sandbox-probe.sh` stops skipping opencode and builds the `BwrapSandbox` argv for it.

  test: tests/unit/sandbox/test_probe_parity.py::test_opencode_m0_argv_matches (also
  tests/unit/sandbox/test_bwrap_argv.py::test_opencode_cache_hidden_from_codex) — code: src/l4/config/defaults.py,
  scripts/runner/sandbox-probe.sh — verify: uv run pytest tests/unit/sandbox -q; then on the runner
  `CLIS=opencode SANDBOX=m0 scripts/runner/mk-ssh.sh --script scripts/runner/sandbox-probe.sh` passes
  * Why: the opencode probe that passed on the runner bound all of `~/.cache` read-write [V, `sandbox-probe.sh`]. The M0
    profile never ran opencode, and `m0` mode skips it [V].
* **G18** (Stage B; agent-factory + verifier) — Tool-less judge modes for two more adapters:
  * **opencode:** `OPENCODE_CONFIG_CONTENT` with `tools {"*": false}` and `permission {"*": "deny"}`, prompt on stdin.
    The reply is sliced from the first `{` to the last `}` and validated;
  * **codex:** `codex exec --json --ephemeral -s read-only --ignore-user-config --ignore-rules --output-schema <strict>
    -o R -`, then `drop_nulls`, then validated.

  `JUDGE_ADAPTERS` becomes (claude-code, codex, opencode, fake).

  test: tests/unit/llm/test_judge_adapters.py::test_opencode_reply_sliced_and_codex_strict_schema (recorded
  `opencode/1.18.33/judge-ok-*.jsonl`). Smoke test tests/unit/llm/test_judge_adapters_live.py (`L4_LIVE=1`): the judge
  and clarifier schemas against real `opencode/big-pickle` and real codex, on the operator's machine. — code:
  src/l4/llm/agent_judge.py, src/l4/agents/opencode.py, src/l4/agents/codex.py — verify: uv run pytest tests/unit/llm -q
  && L4_LIVE=1 uv run pytest tests/unit/llm/test_judge_adapters_live.py -q
  * Why: Q9 puts opencode-free and codex behind claude-code in the judge and clarifier chains.
  * Codex as a judge is [U] (SPEC 8.1). big-pickle has never judged: the opencode judge recordings use OpenRouter
    gpt-5.4-mini.
* **G19** (Stage C; verifier) — `vendor_provenance(profile, served_model)` returns `served`, `tool`, `declared` or
  `unknown` (see Decisions). The independence record:
  * `verification.md` writes `independence: verified (<mode>)`, or `independence: declared (unverified)` when either
    side of any comparison is `declared`;
  * the line names each profile with its vendor and provenance;
  * `verdict.json` gains `independence`.

  test: tests/unit/verifier/test_report_independence.py::test_declared_vendor_marks_independence_unverified (a new
  module; also
  tests/unit/verifier/test_selection.py::test_alias_without_vendor_is_never_independent) — code:
  src/l4/verifier/selection.py, src/l4/verifier/report.py — verify: uv run pytest tests/unit/verifier -q
  * Why: Q9 (decided 2026-10-04) accepts an operator-declared vendor for OpenCode Zen. L4-FAC-003 and SCN-AVL-19 still
    call such a profile `unknown`.
* **G20** (Stage C exit, live; live-validation) — The protocol below as code: one test per step. It reads pipelines, jobs,
  MRs, branches, refs and files through the read-only API and `git ls-remote`, matches the console lines in the job
  logs by pattern, reads the `outcome.json` artefacts, and records every id.

  Retry rule (the same as in step 3): exit 13 or an upstream 429/503 from the implementer: reset the unit and start one
  web pipeline; exit 12 from a judge (`retry_after` set): no reset, one pipeline after `retry_after`; a second miss is
  a FAIL. The test reads `profiles.implementer` and `profiles.fallback_from` from the `outcome.json` of whichever run
  reaches `verified`, including one that resumed at `verifying`.

  test: tests/live/test_m1_2_acceptance.py (marker `live`, needs `L4_LIVE=1`; `L4_LIVE_RECORD` defaults to
  `/tmp/l4_m1_2_ids.json`) — code: tests/live/test_m1_2_acceptance.py
  — verify: L4_LIVE=1 uv run pytest tests/live/test_m1_2_acceptance.py -m live -q
  * Why: agent-factory 1.27 targets `l4 doctor --live` with a forced-limit fake, not this protocol.
* **Doc changes owed** (no build line; SPEC.md is not edited here):
  * **SPEC 3.2:** `profiles.<p>.min_remaining_percent` (G15).
  * **L4-FAC-003 and SCN-AVL-19:** an alias model with an operator-declared `vendor` counts as `declared`, and the
    verdict says so (Q9). With no `vendor`, the profile stays `unknown`.
  * **CFG-003 (SPEC 3.2):** the "union of vendors of the whole implementer chain" rule contradicts Q9's reference chains.
  * **L4-AVL-008:**
    * skipped steps render as `<step> skipped`;
    * `fallback_from` is `chain[0]` when `fallback_index` is ≥ 2;
    * the reason names the reserve when a profile-level reserve binds.
  * **SCN-FAC-07:** an unrecognised quota answer skips the step and does not fail the profile.
  * **§2.1 `l4 probe`:** `--no-cache` clears a cool-down after a passing ladder.
  * **L4-CI-004:** `waiting_capacity` units are resumed by `l4 plan` (no sweep needed). A unit parked before it has a
    branch plans as new.
  * **L4-VER-001:** codex's vendor provenance is `tool`.
  * **L4-FAC-008:** the slot is held around each adapter run, not for the whole unit.

## Simplifications and deferrals

**Stage A**

* **Probe steps.**
  * `mcp` and `custom` (agent-factory 7.3, 7.4) are `skipped`; `availability.custom_probes` stays an opaque list.
  * The codex `model/list` model check is deferred. The codex hello runs only on a cold cache entry.
* **Same tool, another model.** No sibling-model preference (agent-factory 2.3) beyond keying cool-downs by model.
  Chains list a sibling model explicitly when one is wanted.
* **Backends.** No LLM backends (agent-factory 1.13–1.15, 6.x): the runner has no API key. The CLI judge path (G3, G18)
  serves every judge role.
* **Doctor.** LIVE-001 inherits the chain walk (it calls `for_role`). Deferred: LIVE-002 (9.3), ENV-004/005 and CFG-003.
* **Concurrency gate.** A busy profile is skipped when a later one is usable, else waited for up to 120 s. The runner has
  `concurrent = 1`, so it is proven by unit tests only.

**Stage B**

* **OpenCode.**
  * Run mode only. `serve` mode, `session.status{retry}` and native schema (agent-factory 3.1, 3.3) are deferred.
  * Metered providers are deferred: M0's rule passes no credential variable into the sandbox (a `--setenv` value lands
    in bwrap's argv), so M1.2 OpenCode profiles are the free `opencode/*` models.
* **Kiro.**
  * `/usage` quota and stream-json parsing are deferred.
  * The run path is never exercised live (no login). It is argv-tested and marked experimental.
* **Command adapter.** No `resume_argv`. ACP (agent-factory 5.3) is deferred.

**Stage C**

* **Sessions.** Fresh sessions only; no `resume` (implementer-tdd-loop 1.22, 2.25 in full). The previous-attempt block
  carries no transcript.
* **Clarifier.** No fallback inside a batch: M1.1's "unavailable, a human answers" stays.
* **Verifier.** No `verifier_agent` role yet (verifier steps 4a and 5 are M2). `different_model` independence keeps the
  M0 behaviour.
* **Status and plan views.** `l4 status` gets no cool-down view (`l4 probe` shows them); `l4 plan` gets no availability
  view and no `--probe`.
* **Re-entry.** The sweeper itself is untouched; capacity re-entry is the planner row (line 31). Waiting for a lease
  (state-vcs-locks 2.32 second half) is M2.
* **Served-model check.** Only where the adapter reports one (claude-code). Codex and OpenCode report none.

## Files

**(a) Owned (new, or mostly this increment's)**

* `src/l4/availability/`:
  * `cooldown.py` (new: `CooldownRegistry`, `ProbeCache`, `Clock`, `identity_hash`);
  * `limits.py` (new: `normalise_limit`);
  * `quota.py` (new: codex, claude, OpenRouter readers and the threshold rule);
  * `fallback.py` (new: `FallbackSelector`, the console lines, `run_probe`);
  * `probes.py` (M0 file; the ladder and `min_version` move here).
* `src/l4/agents/`:
  * `factory.py` (chain walk, `on_limit`, `WaitingCapacity`);
  * new files: `opencode.py`, `kiro_cli.py`, `command.py`, `gate.py` (`ConcurrencyGate` and the gated adapter);
  * `codex.py` and `claude_code.py` (quota, auth and judge-mode additions only);
  * `base.py` (line 2 type additions).
* `src/l4/llm/agent_judge.py`: `JUDGE_ADAPTERS`, the opencode and codex judge paths.
* `src/l4/verifier/selection.py` (new): `independence_constraint`, `select_judge`, `vendor_provenance`.
* Scripts: `scripts/runner/record-probes.sh` (new); `scripts/runner/sandbox-probe.sh` (opencode in `m0` mode).
* Tests:
  * `tests/unit/availability/*`;
  * `tests/unit/agents/test_{opencode,kiro_cli,command,factory_select,gate}.py`;
  * `tests/contract/{agents,availability}/*`;
  * `tests/unit/llm/test_judge_adapters*.py`, `tests/unit/verifier/test_selection.py`;
  * `tests/scenarios/test_agent_factory_scenarios.py`, `tests/unit/sandbox/test_probe_parity.py` (opencode case);
  * `tests/live/test_m1_2_acceptance.py`.
* Fixtures: `tests/fixtures/recorded/kiro-cli/<v>/`, `claude-code/2.1.288/runner-usage-pro*`,
  `codex/0.160.0/runner-app-server*`, `opencode/1.18.34/`.

**(b) Shared files (additive edits only)**

| File | Edit |
|---|---|
| `src/l4/config/schema.py` | new field `Profile.min_remaining_percent: float \| None = Field(None, ge=0, le=100)` |
| `src/l4/config/defaults.py` | `CREDENTIAL_PATHS["opencode"]` gains the entry `"~/.cache/opencode"` |
| `src/l4/services.py` | `build_services` passes new kwargs `availability=AvailabilityStore(cache_root(...))` and `clock=` to `Factory(...)` (both have defaults, so other callers are unchanged) |
| `src/l4/orchestrator.py` | `_implement`: `except RoleLimit` around `run_task` → new method `_fall_back()` (line 29); `_park`: `retry_after` in the edge context; `_outcome`: `retry_after`, `profiles["fallback_from"]` |
| `src/l4/state/fold.py` | new fields `UnitState.retry_after`, `UnitState.fallback_from`; `_phase_changed` reads `retry_after`; `_availability_selected` reads `fallback_from` |
| `src/l4/planner.py` | the `waiting_capacity` row of `next_action` (line 31); `next_action` gains `now` with a default; field `UnitFacts.retry_after: str \| None = None` and the `facts_of` keyword `retry_after=snapshot.state.retry_after` (both right after `answers_unblock`) |
| `src/l4/implementer/workbench.py` | `commit()` passes `fallback_from=self.selected.fallback_from` into `CommitTrailers`; field `Workbench.previous_attempt: PreviousAttempt \| None = None` after `setup_at`, set by `_fall_back` after `make_workbench` (the `make_workbench` signature is unchanged) |
| `src/l4/implementer/tdd.py` | `_prompt` adds the `previous-attempt` data block after a fallback (new helper); M1.5 later adds its lessons block between the answers and this block |

The exact anchor of each edit is in `docs/plan/parallel-ownership.md` §2.1. M1.3 and M1.4 edit the same files in
parallel.
| `src/l4/verifier/ladder.py` | `verify_hook`: judge from `selection.select_judge`, next independent judge on `RoleLimit` or `model_mismatch` within the round; `VerifyContext` gains `independence` |
| `src/l4/verifier/judge.py` | `run_judge`: served-model check, new status `model_mismatch` |
| `src/l4/verifier/report.py`, `src/l4/verifier/types.py` | the `independence:` line and field (new row and field) |

Not touched:

* `state/lifecycle.py`: the `required_role_unavailable` and `capacity_restored` edges exist [V].
* `outcome.py`: `retry_after` exists, and `profiles` is a string map [V].
* `commands.py` and `cli.py`: the `probe` row and options exist [V].
* `exitcodes.py`, `doctor/*` and `clarifier/*` (`for_role` does the walking).
* The M1.1 Stage C files: `forge/`, `ci/`, `archive.py`, `postmerge.py`, `state/pending.py`, `init/`. M1.4 now owns
  `forge/`, `ci/` and `init/init.py` (parallel-ownership §1).

## Interfaces

**Provided to other increments**

* `l4.agents.factory`:
  * `Factory(cfg, ctx, *, events, adapters, availability, clock)`;
  * `for_role(role, unit, *, serves=None, constraints=()) -> Selected`. `Selected` carries `profile_name`, `profile`,
    `impl`, `fallback_index`, `skipped`, `probes`, `cached`, `fallback_from`, `vendor` and `provenance`;
  * `on_limit(selected, run) -> Selected`;
  * `RoleUnavailable`, `WaitingCapacity(RoleUnavailable).retry_after`, `REQUIRED_ROLES`.
* `l4.availability`:
  * `AvailabilityStore` and `CooldownRegistry` (`record`, `cooling`, `earliest_reset`, `clear`);
  * `ProbeCache`, `Clock`, `normalise_limit`, `format_skipped_line`, `format_selected_line`;
  * `l4 probe` with `l4/probe@1`.
* `l4.verifier.selection`: `independence_constraint`, `select_judge`, `vendor_provenance`.
* Adapters `opencode`, `kiro-cli` and `command`. `JUDGE_ADAPTERS` = claude-code, codex, opencode, fake.
* State and plan: `UnitState.retry_after`, `UnitState.fallback_from`, and the planner's capacity row.
* Ledger events: `availability.selected` (with `fallback_from` and `quota_window`), `availability.cooldown`,
  `availability.fallback`, `availability.model_mismatch`, `availability.model_unverified`,
  `availability.quota_unrecognised`.
* For M2: `for_role(..., constraints=…)` serves `verifier_agent`, and the gate serves `ci.max_parallel_units` > 1.

**Needed from other increments**

* **The seam commit S0** (`parallel-ownership.md` §3.0): `l4.versions` (line 11).
* **M1.1 Stage C (landed, `98e4939`):**
  * verifier `judge@2` (M1.1 line 39);
  * `l4 plan --sweep` (line 36);
  * `l4 upgrade` (G11);
  * the single routed job with `allow_failure.exit_codes [10, 11, 12]` (line 26), unchanged.
* **sandbox-security:** `SandboxSpec` mounts the selected adapter's `credential_paths` and hides the rest [V, M0 line 32].
* **state-vcs-locks:** the `waiting_capacity` edges [V].

## Live exit protocol on `example-group/dummy-agentic` through `l4-runner`

Facts relied on:

* the runner has the claude `pro` and codex logins; OpenCode's free `opencode/*` models need no login; Kiro 2.27.1 is
  installed and not logged in; there are no API keys [V, docs/runner/README.md];
* the runner's builds dir is `/home/gitlab-runner/builds/XXXXXXXXX/0/example-group/dummy-agentic` [V, job 5428 log];
* jobs set neither `L4_CACHE` nor `XDG_CACHE_HOME`, so the availability file is `~gitlab-runner/.cache/l4/availability.json`
  [I]. `l4 probe --json` prints the real path.

Two scenarios, in this order, because a forced codex exhaustion leaves a cool-down until the binding window's reset (up
to a week) in the runner's cache:

* **P1:** codex implements and the judge falls back;
* **P2:** codex is forced exhausted and the implementer falls back.

The operator acts as the human and the maintainer on the dummy repository (Q9 standing permission). Pushes to the
protected `main` need the Maintainer role.

0. **Operator, local.**
   * M1.2 is built, `uv run pytest -q` is green, G14 is recorded, and the G18 smoke test and the G17 runner probe passed.
   * M1.1's live protocol (G13) has run and passed: it never has as of `98e4939` (parallel-ownership §5.3, L0). M1.1's
     units are `in_review` or later, so they plan `none`.
   * The harness pinned by `l4 upgrade` is the `main` commit right after M1.2's merge.
   * On a clone of `main`, run `uv run --project <harness> l4 upgrade --repo <clone> --harness <harness>`.
   * Edit `.l4/config.yaml` by hand. The existing `codex` and `claude-code` profiles and the `clarifier`/`s1_judge`
     settings stay as they are:

   ```yaml
   profiles:                      # existing block: add three profiles
     claude-judge:                # P1 lever: `auth: api_key` is refused at the probe's auth step in M0, so the first
       adapter: claude-code       #   judge is skipped (zero cost, writes no cool-down, leaves claude-code free for
       auth: api_key              #   the clarifier). Live job 5462 ran this; a `min_version` floor above the installed
       vendor: anthropic          #   claude also skips it, but doctor and `--fix` then see an unusable floor.
     opencode-free:
       adapter: opencode
       model: opencode/big-pickle
       vendor: zhipu              # operator-declared [G]: OpenCode Zen does not disclose the served vendor;
                                  #   the protocol only needs it to differ from openai and anthropic
     kiro:
       adapter: kiro-cli
       vendor: amazon
   roles:                         # replaces the implementer and judges chains; clarifier per Q9
     implementer: [codex, opencode-free, claude-code]
     judges: [claude-judge, opencode-free, codex]
     clarifier: [claude-code, codex, opencode-free]
     s1_judge: [claude-code]
   ```

   * Add seed A, `add-money-format` (text below).
1. **Maintainer: push "M1.2: harness `<sha>`, fallback profiles, seed add-money-format".** Expected pipeline P1 (push,
   `main`), one job `l4`:
   * **Plan:** `add-money-format implement`; every M1.1 unit `none`.
   * **Implementer:**
     * console line `[l4] implementer: codex ok (binary 0.160.0 · auth chatgpt <plan> · quota <u>% used (<window>) ·
       hello <s>s) → selected`, with no `fallback` suffix;
     * red → green by codex. Every implementer commit has `L4-Agent: codex…` and no `L4-Fallback-From`.
   * **Judge:**
     * console lines:
       * `[l4] judges: claude-judge skipped — auth: api_key is not supported in M0 (the sandbox passes no credential
         variable)`;
       * `[l4] judges: opencode-free ok (binary 1.18.34 · auth skipped · quota skipped · hello <s>s) → selected,
         fallback #1`;
     * ledger: `availability.selected{role: judges, selected: opencode-free, fallback_index: 1, fallback_from:
       claude-judge}` and `availability.model_unverified{profile: opencode-free}`;
     * no `availability.cooldown`.
   * **Verification:** `verification.md` PASS, judge `opencode-free`, with `independence: declared (unverified)` naming
     `opencode-free zhipu (declared)` and `codex openai (tool)`.
   * **MR and job:** MR `[l4] add-money-format: …` ready, label `l4:in_review`; job exit 0.
   * **Retry rule:**
     * if the big-pickle judge's reply is invalid twice (NEEDS_HUMAN, exit 11): reset the unit (close its MR, delete its
       branch and lock ref), then start one web pipeline;
     * a second miss is a FAIL, recorded in `docs/live/`.
2. **Operator, read-only through `mk-ssh.sh` as `gitlab-runner` in the builds dir:** `.l4/bin/l4 probe claude-code
   --json`. Expected:
   * quota windows, or `quota skipped (unrecognised)`;
   * the availability file holds no cool-down;
   * one hello, about $0.01.

   Before step 3, both of these must hold:
   * the P1 log's codex quota line shows ≥ 1 % used in some window, so the 100 % reserve really binds;
   * claude-code has ≥ 10 % left in every window. Otherwise P2's judge chain would empty (opencode-free shares the
     implementer's vendor, and codex is cooling).

   If either fails, wait and repeat this step.
3. **Maintainer: push "M1.2: reserve on codex, Kiro in the chain, Q9 judges; seed add-split-amount".** Config changes:

   ```yaml
   profiles:
     codex:                         # existing entry: add one key
       min_remaining_percent: 100   # P2 lever: any used window counts as exhausted
   roles:
     implementer: [codex, kiro, opencode-free]       # claude-code left out: bounds the pro spend if OpenCode is down
     judges: [claude-code, opencode-free, codex]     # Q9 reference
   ```

   Add seed B, `add-split-amount` (text below). Expected P2:
   * **Implementer, console lines:**
     * `[l4] implementer: codex skipped — quota: <window> window <u>% used, <100-u>% remaining (resets <T>); cool-down
       recorded` (reason names the 100 % reserve);
     * `[l4] implementer: kiro skipped — auth: kiro-cli installed, not authenticated`;
     * `[l4] implementer: opencode-free ok (binary 1.18.34 · auth skipped · quota skipped · hello <s>s) → selected,
       fallback #2`.
   * **Implementer, ledger:**
     * `availability.selected{role: implementer, selected: opencode-free, fallback_index: 2, fallback_from: codex,
       skipped: [codex/quota, kiro/auth]}`;
     * `availability.cooldown{profile: codex, kind: usage_limit, until: <T>, source: codex.rateLimits}`;
     * no `codex exec` process in the job: the app-server session is the only codex call.
   * **Commits:** red → green by opencode-free in the bubblewrap sandbox. Every implementer commit has
     `L4-Agent: opencode-free/opencode/big-pickle` and `L4-Fallback-From: codex`.
   * **Judge:** `[l4] judges: claude-code ok (… quota … · hello <s>s) → selected`.
   * **Verification:** `verification.md` PASS, with `independence: declared (unverified)` naming
     `opencode-free zhipu (declared)` and `claude-code anthropic (served claude-…)`.
   * **MR:** ready, label `l4:in_review`.
   * **`outcome.json` artefact:** `units[0].profiles == {"implementer": "opencode-free", "fallback_from": "codex", …}`.
     Job exit 0.
   * **Retry rule:**
     * if big-pickle halts the unit (exit 13) or hits an upstream 429/503 (exit 12): reset the unit and start one web
       pipeline. codex is still cooling, so the fallback repeats;
     * an exit 12 from the judge (`verifying`, reason `no independent verifier` or a judge that could not answer) carries
       a `retry_after` and keeps the unit and its branch: do not reset it. Start one web pipeline after `retry_after`, or
       earlier with `l4 probe --no-cache <judge>`. The run resumes at `verifying`, selects no implementer, and its
       `outcome.json` still has `profiles.implementer` and `profiles.fallback_from`, read from the folded state;
     * a second miss is a FAIL.
4. **Operator, read-only through `mk-ssh.sh`:** `.l4/bin/l4 probe --json` in the builds dir. Expected:
   * codex: `skipped — cooling until <T> (usage_limit); no probe sent`;
   * kiro: `skipped — auth: kiro-cli installed, not authenticated`;
   * opencode-free and claude-code: ok, `· cached` within 15 min of P2;
   * claude-judge: skipped at binary;
   * no paid call when the cache is fresh.
5. **Optional, operator: exit 12.**
   * Push `roles.implementer: [codex]` plus seed C, `add-percent-of` (text below).
   * Expected P3:
     * `[l4] implementer: codex skipped — cooling until <T> (usage_limit); no probe sent`;
     * job exit 12 (allowed failure, warning);
     * the `outcome.json` artefact has `units[0].phase_after == "waiting_capacity"` and `retry_after == <T>`;
     * no branch `l4/openspec/add-percent-of` and no MR, because a unit parked before it has a branch is not pushed;
     * no agent process.
6. **Operator: cleanup.**
   * Push a config commit:
     * remove `min_remaining_percent` from codex;
     * `roles.implementer: [codex, opencode-free, claude-code]`;
     * `roles.judges: [claude-code, opencode-free, codex]`;
     * delete the `claude-judge` profile;
     * delete `openspec/changes/add-percent-of/` if step 5 ran.
   * Expected P4: plan shows no actionable unit; `nothing to do`, exit 0.
   * Then, through `mk-ssh.sh` in the builds dir: `.l4/bin/l4 probe --no-cache --json codex`, saved as
     `L4_LIVE_PROBE_6` (the G20 test reads JSON: codex `status` ok and `cooldown_cleared` true; without `--json` the
     line reads `[l4] probe: codex ok (… quota <u>% used …) · cool-down cleared`). Then `l4 probe --json`, saved as
     `L4_LIVE_PROBE_6B`, lists no cool-down.
7. **Optional, HUMAN:** merge the MRs of A and B. M1.1's machinery opens their archive MRs, one at a time.

**Pass** = steps 1–4 and 6 behave as expected. Steps 5 and 7 are optional. The SCN-AVL-08 mid-run limit and the
SCN-AVL-10 re-entry after `retry_after` cannot be forced live: a real usage limit cannot be scheduled. They are proven by
the Stage C exit on fakes. Record every pipeline, job and MR id in `docs/live/README.md`.

Spend, estimated [I]:

* codex: two hellos (P1 and the step-6 re-probe, about 19k tokens each) and one small unit, about 1–2 % of the 5-hour
  window;
* claude: one judge call ($0.06–0.16) and two or three hellos (≤ $0.03);
* OpenCode Zen: $0.

**Seed texts.** These are new modules, so they cannot conflict with M1.1's merge requests on `cart.py`. GIVEN + WHEN
pairs are distinct within each change and against the base specs (G9).

`openspec/changes/add-money-format/.openspec.yaml` (also used for `add-split-amount` and `add-percent-of`):

```yaml
schema: spec-driven
created: 2026-10-04
```

`openspec/changes/add-money-format/proposal.md`:

```markdown
# Proposal: money formatting

## Why
Receipts and reports need one way to print an amount with its currency.

## What Changes
- Add `pricing.money.format_money(amount, currency)`: the amount quantized to 0.01 with ROUND_HALF_UP, printed with two decimals and a leading `-` when negative, then a space and the currency code; a code that is not three uppercase ASCII letters raises ValueError.

## Capabilities

### New Capabilities
- `money-format`: the printed form of money amounts.

### Modified Capabilities

## Impact
New module `src/pricing/money.py`, exported from `pricing`; tests under `tests/`.
```

`openspec/changes/add-money-format/specs/money-format/spec.md`:

```markdown
# Spec Delta

## Purpose
One printed form for money amounts on receipts and reports.

## ADDED Requirements

### Requirement: Format an amount with its currency
`format_money(amount, currency)` SHALL return the `Decimal` amount quantized to 0.01 with ROUND_HALF_UP, written with exactly two decimals and a leading `-` when negative, followed by one space and the currency code. The currency code SHALL be three uppercase ASCII letters; any other code SHALL raise ValueError.

#### Scenario: Two decimals are always shown
- **WHEN** `format_money(Decimal("12.5"), "EUR")` is called
- **THEN** the result is `"12.50 EUR"`

#### Scenario: Half a cent rounds up
- **WHEN** `format_money(Decimal("0.005"), "RON")` is called
- **THEN** the result is `"0.01 RON"`

#### Scenario: Negative amounts keep their sign
- **WHEN** `format_money(Decimal("-3"), "USD")` is called
- **THEN** the result is `"-3.00 USD"`

#### Scenario: Lowercase currency code
- **WHEN** `format_money(Decimal("1"), "eur")` is called
- **THEN** ValueError is raised
```

`openspec/changes/add-money-format/tasks.md`:

```markdown
# Tasks

## 1. Money format

- [ ] 1.1 Add `src/pricing/money.py` with `format_money(amount, currency)` (ROUND_HALF_UP to 0.01, two decimals, sign kept, three uppercase letters else ValueError) and export it from `pricing`
```

`openspec/changes/add-split-amount/proposal.md`:

```markdown
# Proposal: split an amount

## Why
Group orders split one bill into equal parts that must add up to the cent.

## What Changes
- Add `pricing.split.split_amount(amount, parts)`: `parts` amounts with two decimals that differ by at most 0.01, the larger ones first, summing exactly to the amount quantized to 0.01 with ROUND_HALF_UP; a negative amount or fewer than one part raises ValueError.

## Capabilities

### New Capabilities
- `bill-split`: splitting an amount into equal parts.

### Modified Capabilities

## Impact
New module `src/pricing/split.py`, exported from `pricing`; tests under `tests/`.
```

`openspec/changes/add-split-amount/specs/bill-split/spec.md`:

```markdown
# Spec Delta

## Purpose
Equal shares of one bill that add up exactly.

## ADDED Requirements

### Requirement: Split an amount into equal parts
`split_amount(amount, parts)` SHALL return a list of `parts` `Decimal` values with two decimals whose sum equals `amount` quantized to 0.01 with ROUND_HALF_UP. The values SHALL differ by at most 0.01, and the larger values SHALL come first. A negative `amount` or a `parts` value below 1 SHALL raise ValueError.

#### Scenario: Ten into three
- **WHEN** `split_amount(Decimal("10.00"), 3)` is called
- **THEN** the result is `[Decimal("3.34"), Decimal("3.33"), Decimal("3.33")]`

#### Scenario: Even split
- **WHEN** `split_amount(Decimal("9"), 3)` is called
- **THEN** the result is `[Decimal("3.00"), Decimal("3.00"), Decimal("3.00")]`

#### Scenario: One cent in two parts
- **WHEN** `split_amount(Decimal("0.01"), 2)` is called
- **THEN** the result is `[Decimal("0.01"), Decimal("0.00")]`

#### Scenario: Zero parts
- **WHEN** `split_amount(Decimal("5"), 0)` is called
- **THEN** ValueError is raised

#### Scenario: Negative amount
- **WHEN** `split_amount(Decimal("-1"), 2)` is called
- **THEN** ValueError is raised
```

`openspec/changes/add-split-amount/tasks.md`:

```markdown
# Tasks

## 1. Split

- [ ] 1.1 Add `src/pricing/split.py` with `split_amount(amount, parts)` (two decimals, larger parts first, exact sum after ROUND_HALF_UP to 0.01, ValueError for a negative amount or fewer than one part) and export it from `pricing`
```

Seed C, step 5 only. `openspec/changes/add-percent-of/proposal.md`:

```markdown
# Proposal: percent of an amount

## Why
Reports show shares of a total.

## What Changes
- Add `pricing.percent.percent_of(amount, percent)`: `amount * percent / 100` quantized to 0.01 with ROUND_HALF_UP.

## Capabilities

### New Capabilities
- `percent-of`: a percentage of an amount.

### Modified Capabilities

## Impact
New module `src/pricing/percent.py`; tests under `tests/`.
```

`openspec/changes/add-percent-of/specs/percent-of/spec.md`:

```markdown
# Spec Delta

## Purpose
A percentage of a money amount.

## ADDED Requirements

### Requirement: Percent of an amount
`percent_of(amount, percent)` SHALL return `amount * percent / 100` as a `Decimal` quantized to 0.01 with ROUND_HALF_UP.

#### Scenario: A fifth
- **WHEN** `percent_of(Decimal("50"), Decimal("20"))` is called
- **THEN** the result is `Decimal("10.00")`

#### Scenario: Rounding
- **WHEN** `percent_of(Decimal("0.10"), Decimal("5"))` is called
- **THEN** the result is `Decimal("0.01")`
```

`openspec/changes/add-percent-of/tasks.md`:

```markdown
# Tasks

## 1. Percent

- [ ] 1.1 Add `src/pricing/percent.py` with `percent_of(amount, percent)` (ROUND_HALF_UP to 0.01)
```

## Risks

* **big-pickle as a judge is unrecorded** [U]. P1 may end NEEDS_HUMAN (retry rule). G18's smoke test is the early
  warning.
* **The `pro` `/usage` text may not parse** [U]. The quota step then says `skipped`, and the judge chain still works.
  G14 records the real text first.
* **OpenCode inside the M0 bubblewrap profile is [I]** until G17 passes on the runner: cache dir, `/proc` and
  `--clearenv`. The Stage B exit gates on it.
* **Codex's quota buckets and plan on the runner** come from macOS and Plus recordings [V there, U on the runner] until
  G14.
* **The declared vendor is the operator's word.** If OpenCode Zen served big-pickle from OpenAI or Anthropic,
  independence would be false. `verification.md` says so with `declared (unverified)`, and CFG-003 is deferred (doc
  change owed).
* **A failed cleanup leaves codex cooling until its weekly reset.** Later live runs would then fall back to OpenCode
  without a word. Step 6 must pass; `l4 probe` shows the cool-down.
* **Independence is conservative.** A profile replaced by a mid-run fallback still excludes its vendor. With Q9's chains,
  a unit touched by codex and opencode-free can only be judged by claude-code. If claude-code is cooling too, the unit
  waits (exit 12).
* **The mid-run limit shapes are not reproducible live.** The codex usage-limit `turn.failed` is [U, synthetic fixture],
  and the claude `rejected` event is derived. SCN-AVL-08 is proven on fakes only.
* **Stage C shares files with M1.3 and M1.4**, which are built in parallel: `orchestrator.py`, `planner.py`, `fold.py`,
  `workbench.py`, `tdd.py` and `verifier/*`. Each edit stays at its anchor in `parallel-ownership.md` §2.1, and M1.2
  merges first. M1.1 Stage C has already landed.
* **OpenCode Zen free models can be rate-limited or withdrawn** without notice. P2 then ends at exit 12 (retry rule).
  The chain leaves claude-code out on purpose, so no `pro` quota is spent on implementation.
