Every task follows these rules:
- Read `design.md` first: D1 to D15 are the rules (D13 to D15 and the changes they make to D1, D3, D5, D7, D9 and D11
  are the owner's decision of 2026-10-19: kiro-cli works by default with `auto`), §2 the kiro-cli facts (with their
  labels), §4 the files.
- Write the named tests first, run them and see them fail for the reason the task names, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .` and
  `ruff format --check` on the files that changed. Docs tasks also run `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...` (the pattern matches itself). Never pipe a test run into `tail` in
  an `&&` chain. Stage explicit paths only; never `git add -A`.
- Never run kiro-cli with the owner's login: unit tests use recorded fixtures and recording process runners only.
  Never write an account e-mail into a test, a fixture or a log: a test that needs one builds a placeholder string at
  run time.
- Name a consumer "a consumer repository"; name the owner's test repository "the owner's dummy repository".
- Base: the branch is rebased on 0.4.19 (the delegate role) before group 7.
- Waves (each wave's tasks touch disjoint files):
  1. 0.1, 1.1 and 2.1 in parallel (done);
  2. 1.3;
  3. 3.1;
  4. 4.1;
  5. 5.1;
  6. 6.1, 7.2 and 8.1 in parallel;
  7. 7.1;
  8. 9.1;
  9. 10.1 and 10.2 in parallel;
  10. 11.1 and 12.1 (orchestrator).

## 0. Fixtures

- [x] 0.1 The kiro-cli 2.32.0 shapes (L4-KJD-010). No dependency.
  - Write `tests/fixtures/recorded/kiro-cli/2.32.0/` exactly as design §2.4 lists: `auth-invalid-key.stream.jsonl` and
    `.exit.txt`, `input-missing.stream.jsonl` and `.exit.txt`, `no-login.stdout.txt`, `.stderr.txt` and `.exit.txt`,
    `usage-invalid-key.stdout.txt`, `whoami-api-key.stdout.txt`, `version.stdout.txt`, `judge-agent.json`,
    `judge-pass.stream.jsonl` (synthetic: a `l4/judge-verdict@1` object for one criterion `C-1`, verdict `pass`,
    after the sentence `Here is my verdict:`, `meteringUsage` 0.0512, `finalTextTruncated:false`) and `README.txt`
    (how each was made: design §2.1; `judge-pass` marked synthetic until task 11.1).
  - Tests first, `tests/unit/agents/test_kiro_fixtures_2320.py`: every `.stream.jsonl` line is an object with a string
    `type` and an object `data`; `judge-agent.json` has exactly the keys and values of design D1 for
    `claude-sonnet-4.5`; the `judge-pass` final text sliced from the first `{` to the last `}` validates against the
    judge schema; the README contains `synthetic`.
  - Regenerate `src/l4/recorded_versions.json` (`uv run python -m l4.recordedversions --write`);
    `tests/unit/test_recorded_versions.py` passes.

## 1. Vendor by model family

- [x] 1.1 The vendor and model rules (L4-KJD-005, design D5). No dependency.
  - Tests first:
    - `tests/unit/availability/test_vendor_kiro.py`: `MODEL_FAMILIES` maps each prefix of D5 (including
      `us.anthropic.claude-…` and `openrouter/…/claude-…` through the last `/`); `resolve_vendor` of kiro-cli profiles:
      `claude-sonnet-4.5` with no vendor → `("anthropic", "declared")`; `qwen3-coder-next` → `alibaba`; `glm-5` →
      `zhipu`; `some-new-model` with `vendor: acme` → `("acme", "declared")`; no model with `vendor: zhipu` and `model:
      auto` → `("unknown", "unknown")` (SCN-KJD-16); an opencode profile keeps its declared vendor (unchanged).
    - `tests/unit/config/` (the file that tests `_vendor_of_the_tool`): SCN-KJD-15, the load error text and the two
      profiles that load.
    - `tests/unit/verifier/test_selection.py`, new cases: SCN-KJD-13 (veto `share the vendor`, `no independent
      verifier`), SCN-KJD-14 (the independence line), SCN-KJD-17 (`different_model`: `claude-sonnet-4.5` against
      `claude-sonnet-4-5-20250929` is vetoed; `normalise_model("claude-sonnet-4.5") == "claude-sonnet-4-5"`; a version
      such as `gpt-5.6-sol` folds to `gpt-5-6-sol` on both sides).
  - Code: `src/l4/availability/vendor.py` (`MODEL_FAMILIES`, `served_vendor` uses it, the kiro-cli branch of
    `resolve_vendor`, and `normalise_model` and `same_model` moved here from `selection.py`, which imports them, so
    that an adapter can use them without importing the verifier), `src/l4/config/schema.py` (the `Profile`
    validator), `src/l4/verifier/selection.py` (`normalise_model` folds `.` between digits; `independence_constraint`
    and `Independence.independent` compare normalised models under `different_model`).
- [x] 1.3 Rework the wave-1 vendor rule for `auto` (L4-KJD-005, L4-KJD-013, L4-KJD-014, design D5, D14). Depends on
  0.1 and 1.1; runs before 3.1. NEW (owner's decision of 2026-10-19).
  - Why: 1.1 made a kiro-cli profile with no model or `auto` vendor `unknown`, never independent. It is now routed:
    its vendors are the possible set of D14. The fixture `tests/fixtures/recorded/kiro-cli/2.32.0/list-models.json`
    (reconstructed, see its README) is already in the tree.
  - Tests first:
    - `tests/unit/availability/test_vendor_kiro.py`: the Active rule on `list-models.json` (SCN-KJD-31's sets: the 12
      Active ids, vendors `anthropic`, `minimax`, `zhipu`; `auto` and the 8 Experimental entries out; an entry with no
      description is Active); `ROUTED_DEFAULT` equals the set computed from the fixture (SCN-KJD-32, second part); an
      Active id of no known family adds `unknown` (SCN-KJD-33); `resolve_vendor` of a kiro-cli profile with no model,
      `auto`, `AUTO` or a blank model, with or without `vendor:`, is `(None, "routed")` (replaces the 1.1 cases that
      expect `("unknown", "unknown")`; SCN-KJD-16).
    - `tests/unit/config/test_kiro_vendor.py`: `{adapter: kiro-cli, vendor: zhipu}` and `{adapter: kiro-cli, model:
      auto, vendor: zhipu}` load (SCN-KJD-16); SCN-KJD-15 unchanged.
    - `tests/unit/verifier/test_selection.py` (keep its `kiro_serves_judges` fixture until 7.1): SCN-KJD-35 (the exact
      line), SCN-KJD-36, SCN-KJD-37 (a selection whose probe report's `auth` detail records a set with `deepseek`),
      SCN-KJD-38, SCN-KJD-39, SCN-KJD-33's veto text (`has no known vendor`); `test_provenance_kinds` expects `routed`
      for the model-less kiro profile; `verified` is false and `status` is `routed (unverified)` with a routed party
      and an independent judge; `to_json` carries `vendors`.
    - `tests/unit/availability/test_probes_kiro.py`: SCN-KJD-31 (a fake `ctx.run` answering `whoami` and then the
      listing with `list-models.json`; a profile pinned to `glm-5` makes no listing call), SCN-KJD-32 (the listing exits
      1 with `error: service error`: the step passes with `source: built-in` and the reason, and the step text names
      the set and `built-in`), the listing also runs when `credential_auth` passes on `KIRO_API_KEY` (no `whoami` call
      then), SCN-KJD-34 (`whoami` answers a non-empty `email` string built at run time: it is in no `ProbeResult`
      field, not in `LadderReport.to_json()`, not in the step text).
  - Code: `src/l4/availability/vendor.py` (`Provenance` gains `routed`; the Active rule; `ROUTED_DEFAULT`; the kiro-cli
    branch of `resolve_vendor`), `src/l4/verifier/selection.py` (vendor sets in `independence_constraint`,
    `independence_keeper` and `Independence`; the `different_model` routed rule; the routed lookup parameter;
    `Party.vendors`, `text()`, `to_json`, `verified`, `status`; the re-check in `select_judge`),
    `src/l4/agents/factory.py` (`Factory.routed`), `src/l4/agents/kiro_cli.py` (`probe_kiro` `auth`: the listing after
    the login check, recorded under `routed` in the step's detail), `src/l4/availability/fallback.py` (`_step_text`),
    `src/l4/verifier/ladder.py` (the preflight and `_ask_judges`' `assess_independence` pass the factory's lookup). Not
    `src/l4/config/schema.py`: the model-family validator already lets `auto` and no model load with a `vendor:`.
  - Also run `tests/unit/verifier/test_independence.py`, `test_independence_keeper.py`, `test_report_independence.py`,
    `test_resume_independence.py`, `tests/unit/agents/test_kiro_cli.py` and `tests/unit/availability/`; adapt only what
    assumed `unknown` for a model-less kiro-cli profile.

## 2. The shared judge reply

- [x] 2.1 One slicer for prompt-contract judges (L4-KJD-003, design D3 step 2). No dependency.
  - Tests first, `tests/unit/agents/test_contract_judge_reply.py`: `attach_judge_reply(result, text, schema)` with a
    fenced object, prose around an object, no object (`… missing: the reply holds no JSON object`), an object that
    breaks the schema (`… invalid: …`, `rejected` set, status unchanged), a valid object (`ok`, `structured`).
  - SCN-KJD-10: the opencode judge tests in `tests/unit/agents/test_opencode.py` pass unchanged after the move.
  - Code: move `OpenCodeAdapter._attach_judge_reply` to `src/l4/agents/contract.py` as `attach_judge_reply`, same
    messages; `opencode.py` calls it.

## 3. The Kiro judge invocation

- [ ] 3.1 The tool-less harness agent, the stdin transport and `--model auto` (L4-KJD-001, L4-KJD-002, L4-KJD-012,
  design D1, D2, D13). Depends on 0.1 and 1.3. CHANGED: no model runs `auto` instead of being refused.
  - Tests first, `tests/unit/agents/test_kiro_judge.py` with a recording process runner (as `FakeProc` in
    `test_kiro_cli.py`, also keeping `stdin`, `cwd` and `env`): SCN-KJD-01, SCN-KJD-02 (the agent file equals
    `judge-agent.json` but for the name and the model; the settings file; a leftover removed; two calls, two names),
    SCN-KJD-03 (`options.agent` ignored; no model → `--model auto` and `"model": "auto"`, no error), SCN-KJD-04
    (150,000-byte prompt on stdin, cwd `judge-cwd`, `KIRO_HOME` set, `KIRO_LOG_LEVEL` absent even when the host env has
    it), SCN-KJD-05, SCN-KJD-30 (implement and judge mode with no model, `model: AUTO` with `options.agent`).
  - Adapt `tests/unit/agents/test_kiro_cli.py`: `test_trust_tools_follow_the_permission_policy` and
    `test_read_only_and_judge_steps_keep_their_trust_lists` keep `read_only` only;
    `test_the_judge_never_gets_an_empty_trust_list` asserts no `--trust-tools` and no `--trust-all-tools` at all and
    that `"judge"` is not a key of `TRUST_TOOLS`; an implementer argv of a profile with no model now holds `--model
    auto` before `--output-format`.
  - Code, `src/l4/agents/kiro_cli.py`: `JUDGE_PREFIX = "l4-judge-"`, `judge_agent_config(name, model)`,
    `JUDGE_SETTINGS`, `write_judge_home(home, name, model) -> Path`, one helper for the effective model (the profile's,
    else `auto`; `auto` in any case → `auto`), the judge branch of `build_command` (no prompt) and `--model <effective>`
    in every branch, and in `run`: the judge home and `KIRO_HOME`, `stdin=req.prompt`, the empty-prompt refusal,
    `KIRO_LOG_LEVEL` dropped from the env; remove `TRUST_TOOLS["judge"]`. No refusal for a missing model.

## 4. The Kiro judge reply

- [ ] 4.1 Parse a judge run; the served model (L4-KJD-003, L4-KJD-015, design D3, D15). Depends on 1.3, 2.1 and 3.1.
  CHANGED: the session file gives the served model under `auto`; the stderr warning; `model_mismatch` plumbing.
  - Tests first in `tests/unit/agents/test_kiro_judge.py`: SCN-KJD-06 (the `judge-pass` fixture through `parse(…,
    judge=True, schema=JUDGE_SCHEMA)`: `ok`, the object, `model_resolved` None, credits 0.0512), SCN-KJD-07 (through
    `AgentJudge` and `run_judge` with a scripted adapter that returns the two streams parsed by `KiroCliAdapter.parse`:
    `schema_invalid` naming `max_tokens`, then the verdict with `reply: retried`), SCN-KJD-08, SCN-KJD-09 (the three
    errors; the session file written under a temporary `KIRO_HOME`; no session file → `ok`); under `auto`: a session
    file naming `claude-sonnet-5.5` → `ok` with `model_resolved` `claude-sonnet-5.5`; naming `auto`, missing, larger
    than 1 MiB or a symbolic link → `model_resolved` None; a pinned run whose stderr text holds a synthetic warning
    line (for example `warning: could not set model claude-sonnet-5.5, continuing with the default model`) → `error`
    with `model_mismatch: kiro-cli could not set claude-sonnet-5.5` and no `structured`; the same with empty stderr →
    `ok`; `capabilities().served_model` is True.
  - `tests/unit/verifier/test_selection.py`: `seat_of` gives `reports_served` True and `expect_model` the pinned model
    for kiro-cli profiles on `glm-5` and `claude-sonnet-5.5`, and None for one on `auto`.
  - `tests/unit/verifier/test_judge_served_model.py`: an `error` whose detail starts with `model_mismatch:` is
    `model_mismatch` with no verdict.
  - `tests/unit/verifier/test_judge_chain.py` (with the `kiro_serves_judges` monkeypatch of `test_selection.py` until
    7.1): SCN-KJD-40 and SCN-KJD-41 at the ladder with a scripted kiro-cli judge (`availability.model_mismatch`, the
    cool-down kind `model_mismatch`, the next judge's verdict, the independence lines).
  - Code, `kiro_cli.py`: `stream_facts` also returns `engine` (`runStarted.data.engine`), `final_truncated`,
    `stop_reason`, `all_text` (every chunk, never cleared) and the first `tool_call` tool name
    (`_meta.kiro.toolName`, else `title`); `parse(…, judge=False, kiro_home=None, model=None, stderr_text=None)`;
    `run` passes them in judge mode (the stderr file it already writes) and reads no result file then; the session
    file is read with `l4.fsutil.read_regular_file` (limit 1 MiB) and compared with `normalise_model` from
    `l4.availability.vendor` (never import `l4.verifier` from an adapter: `selection` imports `agent_judge`, which
    imports the factory and the adapters); `capabilities()` sets `served_model=True`. `src/l4/verifier/selection.py`:
    `seat_of` for a pinned kiro-cli model. `src/l4/verifier/judge.py`: `run_judge` maps the `model_mismatch:` detail.
    No fallback notice is parsed (D15).

## 5. Failure classes

- [ ] 5.1 Auth, configuration and `/usage` (L4-KJD-006, design D6). Depends on 0.1 and 4.1.
  - Tests first: in `tests/unit/agents/test_kiro_judge.py` the adapter part of SCN-KJD-18 (`auth-invalid-key` → status
    `auth`, the detail of D6, no limit kind other than none), SCN-KJD-19, SCN-KJD-20 (the 2.28.0
    `missing-agent.stream.jsonl` with exit 4 and `input-missing`), and that a throttle message that also says
    `AccessDenied` stays `rate_limited` (order: throttle, credits, auth); in
    `tests/unit/availability/test_probes_kiro.py` SCN-KJD-21 (`kiro_quota` with `usage-invalid-key`).
  - Code: `_KIRO_AUTH` and the no-stream rule in `kiro_cli.py` (`parse`, all modes); `kiro_quota` in
    `src/l4/availability/quota.py`.

## 6. The hello

- [ ] 6.1 The hello runs the judge invocation (L4-KJD-007, design D7). Depends on 3.1 and 5.1. CHANGED: a profile with
  no model runs `auto`.
  - Tests first in `tests/unit/availability/test_probes_kiro.py`: SCN-KJD-22 (a fake `ctx.run` that records argv, env
    and cwd, reads the agent file under the env's `KIRO_HOME` while it runs, and answers `2.28.0/hello.stream.jsonl`; a
    profile without a model has `"model": "auto"` and `--model auto`), SCN-KJD-23; the existing hello tests are
    adapted to the new argv. The listing of 1.3 stays in the `auth` step: the hello makes no listing call.
  - Code: `probe_kiro` hello in `kiro_cli.py`: a `tempfile.TemporaryDirectory(dir=ctx.cwd, prefix="l4-kiro-probe-")`
    with `cwd/` and the judge home, the judge argv plus the hello prompt as the last argument through `_timed` (the
    probe runner has no stdin; do not widen `Runner`), classification by D6.

## 7. Roles and credits

- [ ] 7.1 kiro-cli serves the judge roles; judge credits (L4-KJD-008, L4-KJD-004, design D4, D8). Depends on 4.1, 5.1
  and the 0.4.19 rebase.
  - Tests first:
    - `tests/unit/llm/test_judge_adapters.py`: `"kiro-cli" in JUDGE_ADAPTERS`; the escalation keeper counts a kiro
      judge.
    - `tests/unit/verifier/test_judge_run.py` and a new `tests/unit/verifier/test_judge_credits.py`: SCN-KJD-11
      (`JudgeRun.credits` sums the calls; `verify.judge.credits`; `budget.cost{credits, credits_source, role: judge}`;
      no `usd`; folded `cost_usd` unchanged).
    - `tests/unit/verifier/test_judge_chain.py`: SCN-KJD-18 at the ladder (auth → `availability.fallback` → the next
      judge's verdict).
    - `tests/unit/llm/test_agent_judge_roles.py`: SCN-KJD-24 (clarifier and readiness select a kiro-cli profile and use
      its reply, with a scripted kiro adapter; `kiro-clar` has no model).
    - The delegate's selection tests (0.4.19): SCN-KJD-25.
    - The `kiro_serves_judges` monkeypatches of 1.1, 1.3 and 4.1 are no longer needed; remove them.
  - Code: `src/l4/llm/agent_judge.py` (`JUDGE_ADAPTERS`), `src/l4/verifier/judge.py` (`JudgeRun.credits`),
    `src/l4/verifier/ladder.py` (`_ask_judges` events).
- [ ] 7.2 Clarifier credits (L4-KJD-004). Depends on 4.1.
  - Tests first in `tests/unit/clarifier/test_backend_clarifier.py` and `test_clarifier_run.py`: SCN-KJD-12.
  - Code: `src/l4/clarifier/backend.py` (`ClarifierReply.credits`), `src/l4/clarifier/clarifier.py` (the event).

## 8. Doctor

- [ ] 8.1 CFG-011 (L4-KJD-009, design D9). Depends on 1.3. CHANGED: `auto` passes with its possible vendors; the
  ignored `vendor:` note; severity warn.
  - Tests first, `tests/unit/doctor/test_checks_cfg_011.py`: SCN-KJD-26 (the built-in source with no recorded listing;
    the `listed <date>` source with a recorded one); a `vendor:` on an `auto` implementer profile is noted and does
    not fail the check; a configuration with no kiro-cli judge or clarifier profile passes with `no kiro-cli judge
    profile`; the check is registered with the config scopes and severity warn.
  - Code: `src/l4/doctor/checks_config.py` (`CFG_011`), reading the recorded set through the lookup of 1.3.

## 9. Replay in the simulation

- [ ] 9.1 A judge replayed through the real adapter (L4-KJD-010, design D10). Depends on 0.1 and 7.1. CHANGED: the
  replayed judge has no model, so it runs `--model auto` and is routed on the built-in set.
  - Tests first: `tests/unit/sim/test_happy_kiro_judge.py` (SCN-KJD-27, the argv with `--model auto`); in
    `tests/unit/sim/test_scenarios.py` (or the file that tests `load_scenario`): `replay` and `verdict` together are a
    scenario error, an unknown `adapter` under `replay` is an error; `tests/unit/sim/test_manifest.py` lists
    `happy-kiro-judge` as ready.
  - Code: `JudgeScript.replay` in `src/l4/sim/scenarios.py` (`@fixture:` resolved like `verdict`), `ReplayProc` in a
    new `src/l4/sim/replay.py`, the wiring in `src/l4/sim/fakes.py` (`ProfileRouter` returns a `KiroCliAdapter(ReplayProc)`
    for a replay judge, which reads its stream from the scenario fixture), the stream under
    `src/l4/sim/builtin/fixtures/kiro-basic/` (a copy of `judge-pass.stream.jsonl` with the verdict for the
    scenario's criteria), `src/l4/sim/builtin/scenarios/happy-kiro-judge.yaml`, the manifest entry.

## 10. Docs

- [ ] 10.1 SPEC (design D12). Depends on 1.1 to 9.1 (1.3 included). CHANGED: `auto` routed, the served model, the
  requirement and scenario ranges.
  - `docs/SPEC.md`: §8.1 "CLI judge" (kiro-cli, prompt contract on stdin); §8.3 the `kiro-cli` row (the judge argv of
    D1 with `--model auto` by default, stdin, the reply of D3, the auth rule of D6, the model listing of D14, the
    R-facts of design §2.2 with their labels, the [U] list reduced to §2.3) and the HB-X1 row "`kiro-cli` judge,
    reader" (judge: the tool-less harness agent from a private `KIRO_HOME`, `chat.disableInheritingDefaultResources`,
    empty cwd; reader: still none); §10.1 (vendor by model family for kiro-cli; `auto` routed with its possible
    vendors, the `routed (unverified)` status and the routed line; the served model of a Kiro run; model
    normalisation); §12 the `verify.judge` and `budget.cost` fields and the routed party's `vendors`; §15 the CFG-011
    row; a new §23 subsection with L4-KJD-001..015 and SCN-KJD-01..41 as in this change's spec; §21 row 50
    `kiro-judge`; K4 and K13 marked done in `docs/plan/kiro-e2e.md`, and the kiro-cli 3.0 open item of design §7 added
    there.
- [ ] 10.2 Runbook, skill, CHANGELOG (design D12). Depends on 1.1 to 9.1 (1.3 included). CHANGED: `auto` by default.
  - `docs/runbook.md`: a kiro-cli judge in the profile reference (no model runs `auto`), the CFG-011 lines and fixes,
    the independence rule for a Kiro judge on a Claude model or on `auto` (not independent of a Claude, GLM or MiniMax
    implementer; pin a model to make the served model checkable), and the auth fallback.
  - `plugins/l4/skills/l4/references/adopt.md`: a `kiro-judge` profile example with no model (`auto`) and one pinned
    (`model`, `vendor` matching the family, `min_version: "2.32.0"`), the rule "a Kiro judge's vendor is its model's
    maker; on `auto`, every maker Kiro may route it to"; `references/kiro.md`: Kiro as a judge or clarifier, `auto` by
    default.
  - `CHANGELOG.md`: `## 0.4.20 (unreleased)` with Added (the Kiro judge, clarifier and readiness reviewer; `auto` by
    default with its possible vendors and served model; CFG-011; judge credits), Changed (the vendor rule and its load
    error with the fix; `auto` is routed and its `vendor:` ignored; `--model auto` for every kiro-cli profile with no
    model, also an implementer with `options.agent` (fix: name the model in the profile); two `auto` sides are never
    independent (fix: pin one); the hello runs the tool-less agent; the `auth` probe lists the models of an `auto`
    profile), Fixed (a Kiro auth failure moves to the next profile; `/usage` "Invalid token" is an auth failure).

## 11. Live validation

- [ ] 11.1 Kiro judges in CI on the owner's dummy repository (L4-KJD-011, design D11). Orchestrator. Depends on all
  code groups, built and pinned on that repository (never a consumer). CHANGED: two legs, `auto` and
  `claude-sonnet-5.5`.
  - Confirm the runner's or hosted runner's kiro-cli version (2.32.0 or newer, below 3.0, else install 2.32.0 there
    first; design §7).
  - Configure the implementer as an opencode-go DeepSeek profile with `vendor: deepseek` (the default implementer
    model), and the judges of D11 with `auth: api_key`: `kiro-auto` (no model) and `kiro-sonnet` (`model:
    claude-sonnet-5.5`). `l4 doctor --live` passes CFG-011 and LIVE-001 for each.
  - Run the unit to a verdict in CI with `roles.judges: [kiro-auto]`, then with `roles.judges: [kiro-sonnet]`
    (SCN-KJD-28); then the negative leg (SCN-KJD-29) with a claude-code implementer and each judge, with no judge call.
  - Never run `kiro-cli whoami` and never print account data in the job (the `auth` step passes on `KIRO_API_KEY`);
    the redaction of the published streams is checked before they are committed.
  - Record, per leg: the judge's raw stream (redacted), the session file's `model_id` (under `auto`: `auto` or the
    served model), any fallback notice, any standard-error warning about the model (also try a pinned model id the
    account does not have, if the leg allows it, to see the warning of R20), and whether an agent file with `"model":
    "auto"` was accepted. Record the raw `chat --list-models --format json` output: whether it carries a status field,
    and replace the reconstructed `list-models.json` with it (README: recorded, job id). Replace
    `judge-pass.stream.jsonl` with the recorded judge stream (README: recorded, job id).
  - If the reply shape differs from design D3, a fallback notice appears, the session file under `auto` names a model
    of a vendor outside the listed set, or the listing's Active set differs from the built-in one: stop and amend the
    design before any fix.
  - Answer design §2.3 in `docs/live/kiro-judge/README.md` (served-model field, `tool_call` absence, credits per
    call, the out-of-credits wording if seen, whether `settings/cli.json` under `KIRO_HOME` was read, the `auto`
    questions); index it in `docs/live/README.md`.

## 12. Close

- [ ] 12.1 Full suite and simulation. Orchestrator. Depends on 10.1, 10.2.
  - The whole test suite in the background; `l4 simulate --all` (`happy-kiro-judge` included);
    `openspec validate kiro-judge --strict`; an independent review of the diff against this change's spec.
