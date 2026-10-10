# M1.2 progress (increment parts M12-A: Stage A, availability core; M12-B: Stage B, adapters; M12-C: Stage C, wiring)

| line | change task | status | commit | note |
|---|---|---|---|---|
| 1 | G14 (gap) | done | cd5dd43 | `scripts/runner/record-probes.sh` + `split_recordings.py`; recordings under `tests/fixtures/recorded/{kiro-cli/2.27.1,claude-code/2.1.288,codex/0.160.0,opencode/1.18.34}/runner-*`. Found: Kiro logged out = exit 1, stdout `{"account":null}`; Claude `pro` `/usage` has no reset on a fresh session window and writes `resets Oct 8, 11:59am (UTC)` (comma, no "at"); the parser takes both forms |
| 2 | agent-factory 1.1 (delta) | done | 2c678b3 | `LimitSignal.window_minutes/used_percent`, `AgentCaps.served_model`, `Selected.vendor/provenance/request`, `WaitingCapacity`, `REQUIRED_ROLES`; `ProbeCtx` gains `min_remaining_percent`, `min_remaining_usd`, `rpc`, `now` |
| 3 | agent-factory 1.16 (+7.6) | done | 2c678b3 | `availability/cooldown.py`: `CooldownRegistry`, `AvailabilityStore` |
| 4 | agent-factory 1.17 (+8.4) | done | 2c678b3 | `ProbeCache`, `Clock`/`SystemClock`/`FakeClock`, `identity_hash` |
| 5 | agent-factory 7.5 | done | 2c678b3 | `availability/limits.py`: `normalise_limit`, `parse_reset` |
| 6 | agent-factory 7.2 | done | 2c678b3 | `availability/quota.py`: `evaluate_windows` |
| 7 | G15 (gap) | done | 2c678b3 | `Profile.min_remaining_percent` |
| 8 | agent-factory 4.3 (+4.4, 7.1 codex) | done | 2c678b3 | `availability/rpc.py` (stdio JSON-RPC session), codex auth + quota in `probes.py`/`quota.py` |
| 9 | agent-factory 2.2 | done | 2c678b3 | Claude `/usage` (+ latest `rate_limit_event` preferred) |
| 10 | G16 (gap) | done | 2c678b3 | `quota.openrouter_quota` (not called by any adapter yet: the OpenCode adapter of Stage B calls it) |
| 11 | agent-factory 1.18 | done | 2c678b3 | `min_version` through `l4.versions.version_at_least`; S0 (`m1x-seams`, `cdaebae`) was fast-forwarded into this branch before this line |
| 12 | agent-factory 1.20 | done | 2c678b3 | `ProbeLadder`, `LadderReport` in `availability/probes.py` |
| 13 | agent-factory 1.21 (+7.7, 7.8) | done | 2c678b3 | `availability/fallback.py`: `FallbackSelector` |
| 14 | agent-factory 1.22 | done | 2c678b3 | `format_selected_line`, `format_skipped_line`, `to_event` |
| 15 | agent-factory 1.23 | done | 2c678b3 | `WaitingCapacity(retry_after)` / `RoleUnavailable` |
| 16 | agent-factory 1.24 | done | 2c678b3 | `Factory.for_role(role, unit, *, serves=None, constraints=())` |
| 17 | agent-factory 1.25 | done | 2c678b3 | `Factory.on_limit(selected, run)` |
| 18 | agent-factory 8.3 (reduced) | done | 2c678b3 | `agents/gate.py`: `ConcurrencyGate`, `GatedAdapter`, `slots_for`; selector skips a busy login when a later profile is usable, else waits 120 s; profiles on one login share its slot |
| 19 | agent-factory 9.5 | done | 2c678b3 | `fallback.run_probe`, `Factory.probe_all`; exit 0 when every probed profile is usable, 12 otherwise |

## Notes

* Probe-cache policy (deviation from agent-factory 1.17 "failures cached too"): `ProbeCache` stores anything, but the
  selector (`FallbackSelector._remember`) caches a success or a failed `hello` only. A failed binary, auth or quota
  step costs no model request, so it is probed again each time: installing or logging in takes effect at once.
  A limit is remembered by the cool-down registry, never by the cache.
* `state/ledger.py` gained a `run_id` property (additive; the Factory records `recorded_by_run` from it).
* Existing tests adapted because the ladder now has the `quota` step and the chain is walked: `test_factory_select.py`
  (3 assertions), `test_probes.py` (the codex login-status and quota-skipped tests replaced), `test_s1_judge.py`,
  `test_checks_agents.py` (the probe sequence gains `quota`), `test_dispatch.py` (`probe` leaves the stub list).
* `test_proc.py::test_interrupt_sends_sigint_then_the_run_ends` fails when pytest itself runs as a background shell job
  (`cmd &`): such a job inherits SIGINT as ignored, so the child never raises KeyboardInterrupt. Reproduced and
  confirmed; run the suite in the foreground. Final foreground run at HEAD: 1584 passed, 18 skipped; ruff clean.

## Stage B (M12-B): adapters

| line | change task | status | commit | note |
|---|---|---|---|---|
| 20 | agent-factory 1.10 (+1.12) | done | 5b25d09 | `agents/opencode.py`: `build_command`, `config_content` (SPEC 8.3.1 map, `external_directory` order pinned), `isolation_env`; the per-step config dir and the judge's empty cwd live under the agent tmp; wall clock and stall watchdog through `ProcRunner` |
| 21 | agent-factory 1.11 (+3.2) | done | 5b25d09 | `OpenCodeAdapter.parse` over the recorded streams; an `error` event wins before any `step_finish`; 402 `quota`, 429 `rate_limited` (reset from the retry-after header or the Google body, else `default_cooldown`), 401 `auth`, 503 `error`; `availability.model_unverified` is written by `Factory.for_role` |
| 22 | agent-factory 1.19 + 7.1 (opencode rows) | done | 5b25d09 | `probe_opencode`: binary, auth (`opencode/*` skipped, else `auth list` presence), quota (`openrouter_quota` for OpenRouter models, else skipped), isolated hello |
| 23 | G17 | done | 5b25d09 | `~/.cache/opencode` in `CREDENTIAL_PATHS["opencode"]`; `sandbox-probe.sh` m0 mode runs opencode; `CLIS=opencode SANDBOX=m0` PASS on `l4-runner` (36.6 s, canary ok) |
| 24 | G18 | done | f0e2411 | opencode and codex judge modes, `JUDGE_ADAPTERS` = claude-code, codex, opencode, fake; smoke test `tests/unit/llm/test_judge_adapters_live.py`: opencode half PASS on the Mac (real `opencode/big-pickle`, real judge and clarifier schemas); the codex half skips there (no codex), and was run by hand on the runner (see notes) |
| 25 | agent-factory 5.1 (reduced) | done | edad28e | `agents/kiro_cli.py`; logged out reads `kiro-cli installed, not authenticated`; quota and hello skipped; exit 3 is the MCP startup error; `agent.experimental` once per Factory |
| 26 | agent-factory 5.2 | done | edad28e | `agents/command.py`; placeholders refused at config load (`config/schema.py::command_option_problems`) |

### Stage B notes

* **Zen free tier and tool-less runs (live finding, 2026-10-04).** `opencode/*` models answer 403 "free tier can only be
  used from within OpenCode" when `bash` or `read` is denied (`tools {"*": false}`, `permission {"*": "deny"}`): same on
  the Mac (1.18.33) and the runner (1.18.34). `edit: deny` and `webfetch/websearch: deny` are fine. For Zen models the
  judge and read-only modes therefore write `ask` instead of `deny` for `bash` and `read` (run mode rejects an `ask` on
  the spot, nothing runs); other providers keep the SPEC 8.3.1 `tools off` form. `big-pickle` as a tool-less judge is now
  [V] with `ask`.
* **Strict schemas need `items` on every array.** The SPEC 10.3 verdict schema leaves `findings[].evidence` as a bare
  `{"type": "array"}`; codex answered `invalid_json_schema: array schema missing items` (live, runner). `strictify_schema`
  now gives such an array the `items` of the same-named property elsewhere in the schema (`criteria[].evidence`), and
  raises `AdapterError` when there is no donor. With that, codex as a judge returned a schema-valid verdict on the
  runner (13 s, recorded as `codex/0.160.0/runner-judge-ok.*`); one earlier attempt sat 150 s at `turn.started` with no
  output (not reproduced; the judge's stall watchdog must stay armed).
* **Prompt contract wiring.** `implementer/tdd.py::_prompt` now sets `PromptContext.result_path` for an adapter whose
  `schema_mode` is `prompt_contract` (one line). The adapters never touch the prompt: it is published and hashed
  before `run`. `AgentJudge` appends the schema text to the prompt for non-native adapters.
* Deviations: see the M12-B report. `ruff format` is not applied repo-wide (38 older files differ); only `ruff check`
  gates.

## Stage C (M12-C)

`git merge main` (M1.1 Stage C) was clean; the suite was green (1735 passed) before the first Stage C edit.

| line | change task | status | commit | note |
|---|---|---|---|---|
| 27 | state-vcs-locks 1.18 (delta) | done | 7522ec1 | `UnitState.retry_after` (set by the park edge, cleared when the unit leaves `waiting_capacity`), `UnitState.fallback_from` (role to profile, dropped when a later selection has no `fallback_from`) |
| 28 | implementer-tdd-loop 1.27 (delta) | done | e545c84 | `_park` puts `retry_after` in the edge context and the log line (`WaitingCapacity.retry_after`, else the limit's own reset); `_outcome` fills `retry_after` and `profiles.fallback_from` |
| 29 | agent-factory 1.25 (consumer) + implementer-tdd-loop 2.25 (reduced) | done | e545c84 | `Orchestrator._fall_back`: `availability.limit`, discard the half-done step, `Factory.on_limit`, rebuilt `Workbench` (baselines carried over), `PreviousAttempt` block; nothing left raises `WaitingCapacity` into `_park` |
| 30 | implementer-tdd-loop 2.20 | done | e545c84 | `Workbench.commit` passes `fallback_from=selected.fallback_from`; `L4-Agent` was already there |
| 31 | forge-and-ci 2.32 (reduced) | done | 348c551 | `next_action(facts, now=None)`: `waiting_capacity` plans the previous phase's action once `retry_after` has passed (`capacity: retry_after <T> passed`), `none` before (`waiting_capacity until <T>`); no `retry_after` keeps the old row |
| 32 | verifier 1.3 | done | d390719 | `verifier/selection.py`: `independence_constraint`, `select_judge`, `vendor_provenance`; `verify_hook` uses it. `require_independent_judge` stays defined |
| 33 | verifier 1.4 | done | d390719 | every judge excluded, cooling or busy gives `WaitingCapacity` with `no independent verifier`, no judge called |
| 34 | verifier 1.10 + 1.11 (delta) | done | d390719 | `run_judge(expect_model=)` gives `model_mismatch` (verdict dropped, `availability.model_mismatch`); a limit goes through `Factory.on_limit`; both move to the next independent judge in the same round |
| 35 | G19 (gap) | done | d390719 | `Independence` record: `independence:` line in `verification.md`, `independence` object in `verdict.json` |
| 36 | clarification-loop 3.2 | done | 383d281 | `for_role` already walks the clarifier and s1_judge chains (Stage A); tests only: fallback at selection, a limit inside a batch still goes to a human |
| 37 | agent-factory 9.4 (reduced) | done | 2bf6ff8 | `tests/scenarios/test_agent_factory_scenarios.py`: SCN-AVL-02, 03, 08, 09, 10, 16, 17, 19 (and the Q9 amendment), SCN-FAC-06, 09, 12 |
| 38 | G20 (gap) | partial | 2bf6ff8 | `tests/live/test_m1_2_acceptance.py` (+ `protocol_m12.py`, unit tested). Collected and skipping: it needs the pushes of the protocol; not run against the runner |

### Stage C notes

* **Re-entry.** A unit parked before it has a branch is never pushed (accepted in the plan), so it plans as new; only a
  unit parked after progress has `retry_after` on its branch. SCN-AVL-09 (no branch) and SCN-AVL-10 (branch) test both.
* **Cool-down now outlives a run.** Every mid-run limit writes a cool-down to the runner's availability file, so
  `test_a_role_lost_after_progress_parks_the_unit_on_its_branch` needed a `FakeClock` advance (the `fake_clock` fixture
  patches `l4.services.SystemClock`).
* **`previous-attempt` block** is `<l4:data kind="previous-attempt" profile=".." limit="..">` (plan wording), built in
  `tdd._previous_attempt_block`, only for the task that fell back.
* **Provenance.** `tool` for codex and claude-code (single-vendor CLIs), `served` once the adapter reported a served
  model, `declared` for the other adapters with a `vendor:`, `unknown` without one.

## Review fixes (m1.2(fix))

| finding | status | note |
|---|---|---|
| probe cache ignored probe settings (major) | done | `probe_identity` = `identity_hash` + digest of the profile and availability settings (not timings); a changed reserve, min_version, model, ladder or hello prompt is a cache miss |
| claude-code 429 cool-down key never matched (major) | done | `record_cooldown` keys by the profile's own key unless the limit names the model the profile pins; `Factory.on_limit` raises `WaitingCapacity` rather than return the profile that hit the limit. Termination: each limit cools one more profile of a finite chain, so no extra counter |
| skipped auth/hello shown as ok (major) | done | `_step_text` prints `<step> skipped` for any skipped step |
| OpenRouter key sent to any base_url (minor) | done | only `https://openrouter.ai...` is used, else the default base |
| retry_after counted vetoed profiles (minor) | done | only profiles that reached the cooling check count |
| `for_role` vendor/provenance (minor) | done | filled in `for_role` (`l4.availability.vendor`); `select_judge` no longer sets them |
| `_selected` only set by `_fall_back` (minor) | done | public `Orchestrator.switch_profile`, exposed as `ctx.shared["fall_back"]`; `on_limit` takes a `RunResult` or a `LimitSignal` |
| codex mid-run limit without reset (minor) | done | `parse(now=)` and `parse_reset` on the message |
| weak scenario assertions, no CLI future retry_after (minor) | done | |
| quota reason names another window's reset (minor) | done | the reason adds `; cool-down follows the <window> reset` when the shown window is not the one that sets the reset |
| ladder.py anchors (minor) | done in docs | `parallel-ownership.md` 2.1 now carries the real field names, signature and the expected merge conflicts |
| probe exit code 12 for failing profiles (minor) | not changed | SPEC 2.1/2.2 edit needed (not allowed here): document that `l4 probe` exits 12 when any probed profile is failing, cooling or unsupported. The repeated `--version` calls per ladder are left (3 cheap calls) |
| TDD process deviation (minor) | recorded | Stage A landed tests and code in one commit and Stage C's scenarios after the code; the fix tests above were written first and seen failing against the old code. Before the live run, dry-run `tests/live/protocol_m12.py` against a saved real `l4 probe --json` |
| round 3: judge `error` strands the unit (major) | done | `_ask_judges` moves on to the next judge on `error` (event `availability.judge_error`); `_park` gives any required-role `RoleUnavailable` without a reset `retry_after = now + default_cooldown`; the judge prompt says "do not call any tool"; P1 retry rule for exit 12 added to the live protocol |
| round 3: C21 wording (minor) | done in docs | C21 row and m13-plan say `ctx.shared["fall_back"](run, task)`. Tell the M1.3 owner before M1.3 merges |
| round 3: lost login logged as rate_limit (minor) | done | cool-down kind `auth`, fallback reason = the run status when no limit was seen |
| round 3: step 6 of the live protocol (minor) | done | `format_probe_line` appends ` · cool-down cleared`; the step-6 command is `--no-cache --json`, saved as `L4_LIVE_PROBE_6` |
| round 3: persistent mismatch re-paid every round (minor) | partial | a mismatching judge is cooled (`model_mismatch`, `default_cooldown`). A park caused by independence exclusion calls no judge and costs nothing, so it keeps `retry_after = default_cooldown` |
| round 3: Claude event windows never used (minor) | done | windows live in a module-level map keyed by auth mode |
| round 3: `l4 probe` exit 12 for failing profiles (minor) | not changed | still needs the SPEC 2.1/2.2 probe exit rule |
| round 4: resume at `verifying` lost `profiles.implementer` / `fallback_from` (major) | done | `_outcome` reads the implementer from `state.profiles_used` and `fallback_from` from `state.fallback_from` when the run selected none; scenario test resumes at verifying after a judge park. Plan live protocol and G20 now state the same retry rule (exit 12 from a judge: no reset) |
| round 4: declared vendor labelled verified (major) | done | `resolve_vendor` (`l4.availability.vendor`): served model id gives the vendor (claude-* anthropic, gpt-*/o<digit> openai, gemini-* google, else unknown and never independent); codex and claude-code take the tool's vendor (`TOOL_VENDORS`) in `independence_constraint`, `assess_independence`, `Selected` and the ladder; a `vendor:` that contradicts the tool is rejected at config load (value-free, exit 2); only opencode, kiro-cli, command and acp use the declared vendor, reported `declared (unverified)`. `require_independent_judge` now delegates to `independence_constraint` (one rule). Test updates: claude-code/codex profiles with no or wrong `vendor:` in `test_independence.py` use opencode; served judges in `test_judge_chain.py` show the served vendor |
| round 4 review: declared vendor compared by case; served vendor computed but never enforced (major) | done | `resolve_vendor` lowercases a declared vendor (`OpenAI` on opencode was independent of codex's `openai`); `_ask_judges` drops an `ok` verdict whose served model is of an implementer's vendor or of no known vendor (`model_mismatch`, next judge, else `no independent verifier`); `Independence.status` says `not independent (<mode>)` instead of `verified`; Bedrock `<region>.anthropic.claude-*` ids are anthropic |
