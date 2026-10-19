Every task follows these rules:
- Read `design.md` first: D1 to D12 are the rules, §2 the kiro-cli facts (with their labels), §4 the files.
- Write the named tests first, run them and see them fail for the reason the task names, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then `ruff check .` and
  `ruff format --check` on the files that changed. Docs tasks also run `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...` (the pattern matches itself). Never pipe a test run into `tail` in
  an `&&` chain. Stage explicit paths only; never `git add -A`.
- Never run kiro-cli with the owner's login: unit tests use recorded fixtures and recording process runners only.
- Name a consumer "a consumer repository"; name the owner's test repository "the owner's dummy repository".
- Base: the branch is rebased on 0.4.19 (the delegate role) before group 7.
- Waves (each wave's tasks touch disjoint files):
  1. 0.1, 1.1 and 2.1 in parallel;
  2. 3.1;
  3. 4.1;
  4. 5.1;
  5. 6.1, 7.2 and 8.1 in parallel;
  6. 7.1;
  7. 9.1;
  8. 10.1 and 10.2 in parallel;
  9. 11.1 and 12.1 (orchestrator).

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

## 2. The shared judge reply

- [x] 2.1 One slicer for prompt-contract judges (L4-KJD-003, design D3 step 2). No dependency.
  - Tests first, `tests/unit/agents/test_contract_judge_reply.py`: `attach_judge_reply(result, text, schema)` with a
    fenced object, prose around an object, no object (`… missing: the reply holds no JSON object`), an object that
    breaks the schema (`… invalid: …`, `rejected` set, status unchanged), a valid object (`ok`, `structured`).
  - SCN-KJD-10: the opencode judge tests in `tests/unit/agents/test_opencode.py` pass unchanged after the move.
  - Code: move `OpenCodeAdapter._attach_judge_reply` to `src/l4/agents/contract.py` as `attach_judge_reply`, same
    messages; `opencode.py` calls it.

## 3. The Kiro judge invocation

- [ ] 3.1 The tool-less harness agent and the stdin transport (L4-KJD-001, L4-KJD-002, design D1, D2). Depends on 0.1.
  - Tests first, `tests/unit/agents/test_kiro_judge.py` with a recording process runner (as `FakeProc` in
    `test_kiro_cli.py`, also keeping `stdin`, `cwd` and `env`): SCN-KJD-01, SCN-KJD-02 (the agent file equals
    `judge-agent.json` but for the name and the model; the settings file; a leftover removed; two calls, two names),
    SCN-KJD-03 (`options.agent` ignored; no model → `AdapterError`, no process), SCN-KJD-04 (150,000-byte prompt on
    stdin, cwd `judge-cwd`, `KIRO_HOME` set, `KIRO_LOG_LEVEL` absent even when the host env has it), SCN-KJD-05.
  - Adapt `tests/unit/agents/test_kiro_cli.py`: `test_trust_tools_follow_the_permission_policy` and
    `test_read_only_and_judge_steps_keep_their_trust_lists` keep `read_only` only;
    `test_the_judge_never_gets_an_empty_trust_list` asserts no `--trust-tools` and no `--trust-all-tools` at all and
    that `"judge"` is not a key of `TRUST_TOOLS`.
  - Code, `src/l4/agents/kiro_cli.py`: `JUDGE_PREFIX = "l4-judge-"`, `judge_agent_config(name, model)`,
    `JUDGE_SETTINGS`, `write_judge_home(home, name, model) -> Path`, the judge branch of `build_command` (no prompt),
    and in `run`: the judge home and `KIRO_HOME`, `stdin=req.prompt`, the refusals, `KIRO_LOG_LEVEL` dropped from the
    env; remove `TRUST_TOOLS["judge"]`.

## 4. The Kiro judge reply

- [ ] 4.1 Parse a judge run (L4-KJD-003, design D3). Depends on 1.1, 2.1 and 3.1.
  - Tests first in `tests/unit/agents/test_kiro_judge.py`: SCN-KJD-06 (the `judge-pass` fixture through `parse(…,
    judge=True, schema=JUDGE_SCHEMA)`: `ok`, the object, `model_resolved` None, credits 0.0512), SCN-KJD-07 (through
    `AgentJudge` and `run_judge` with a scripted adapter that returns the two streams parsed by `KiroCliAdapter.parse`:
    `schema_invalid` naming `max_tokens`, then the verdict with `reply: retried`), SCN-KJD-08, SCN-KJD-09 (the three
    errors; the session file written under a temporary `KIRO_HOME`; no session file → `ok`).
  - Code, `kiro_cli.py`: `stream_facts` also returns `engine` (`runStarted.data.engine`), `final_truncated`,
    `stop_reason`, `all_text` (every chunk, never cleared) and the first `tool_call` tool name
    (`_meta.kiro.toolName`, else `title`); `parse(…, judge=False, kiro_home=None, model=None)`; `run` passes them in
    judge mode and reads no result file then; the session file is read with `l4.fsutil.read_regular_file` (limit
    1 MiB) and compared with `normalise_model` from `l4.availability.vendor` (never import `l4.verifier` from an
    adapter: `selection` imports `agent_judge`, which imports the factory and the adapters).

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

- [ ] 6.1 The hello runs the judge invocation (L4-KJD-007, design D7). Depends on 3.1 and 5.1.
  - Tests first in `tests/unit/availability/test_probes_kiro.py`: SCN-KJD-22 (a fake `ctx.run` that records argv, env
    and cwd, reads the agent file under the env's `KIRO_HOME` while it runs, and answers `2.28.0/hello.stream.jsonl`; a
    profile without a model has `"model": null` and no `--model`), SCN-KJD-23; the existing hello tests are adapted to
    the new argv.
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
      its reply, with a scripted kiro adapter).
    - The delegate's selection tests (0.4.19): SCN-KJD-25.
  - Code: `src/l4/llm/agent_judge.py` (`JUDGE_ADAPTERS`), `src/l4/verifier/judge.py` (`JudgeRun.credits`),
    `src/l4/verifier/ladder.py` (`_ask_judges` events).
- [ ] 7.2 Clarifier credits (L4-KJD-004). Depends on 4.1.
  - Tests first in `tests/unit/clarifier/test_backend_clarifier.py` and `test_clarifier_run.py`: SCN-KJD-12.
  - Code: `src/l4/clarifier/backend.py` (`ClarifierReply.credits`), `src/l4/clarifier/clarifier.py` (the event).

## 8. Doctor

- [ ] 8.1 CFG-011 (L4-KJD-009, design D9). Depends on 1.1.
  - Tests first, `tests/unit/doctor/test_checks_cfg_011.py`: SCN-KJD-26; a configuration with no kiro-cli judge or
    clarifier profile passes with `no kiro-cli judge profile`; the check is registered with the config scopes.
  - Code: `src/l4/doctor/checks_config.py` (`CFG_011`).

## 9. Replay in the simulation

- [ ] 9.1 A judge replayed through the real adapter (L4-KJD-010, design D10). Depends on 0.1 and 7.1.
  - Tests first: `tests/unit/sim/test_happy_kiro_judge.py` (SCN-KJD-27); in `tests/unit/sim/test_scenarios.py` (or
    the file that tests `load_scenario`): `replay` and `verdict` together are a scenario error, an unknown `adapter`
    under `replay` is an error; `tests/unit/sim/test_manifest.py` lists `happy-kiro-judge` as ready.
  - Code: `JudgeScript.replay` in `src/l4/sim/scenarios.py` (`@fixture:` resolved like `verdict`), `ReplayProc` in a
    new `src/l4/sim/replay.py`, the wiring in `src/l4/sim/fakes.py` (`ProfileRouter` returns a `KiroCliAdapter(ReplayProc)`
    for a replay judge, which reads its stream from the scenario fixture), the stream under
    `src/l4/sim/builtin/fixtures/kiro-basic/` (a copy of `judge-pass.stream.jsonl` with the verdict for the
    scenario's criteria), `src/l4/sim/builtin/scenarios/happy-kiro-judge.yaml`, the manifest entry.

## 10. Docs

- [ ] 10.1 SPEC (design D12). Depends on 1.1 to 9.1.
  - `docs/SPEC.md`: §8.1 "CLI judge" (kiro-cli, prompt contract on stdin); §8.3 the `kiro-cli` row (the judge argv of
    D1, stdin, the reply of D3, the auth rule of D6, the R-facts of design §2.2 with their labels, the [U] list reduced
    to §2.3) and the HB-X1 row "`kiro-cli` judge, reader" (judge: the tool-less harness agent from a private
    `KIRO_HOME`, `chat.disableInheritingDefaultResources`, empty cwd; reader: still none); §10.1 (vendor by model family
    for kiro-cli, `auto` unknown, model normalisation); §12 the `verify.judge` and `budget.cost` fields; §15 the
    CFG-011 row; a new §23 subsection with L4-KJD-001..011 and SCN-KJD-01..29 as in this change's spec; §21 row 50
    `kiro-judge`; K4 and K13 marked done in `docs/plan/kiro-e2e.md`.
- [ ] 10.2 Runbook, skill, CHANGELOG (design D12). Depends on 1.1 to 9.1.
  - `docs/runbook.md`: a kiro-cli judge in the profile reference, CFG-011 and its fixes, the independence rule for a
    Kiro judge on a Claude model, and the auth fallback.
  - `plugins/l4/skills/l4/references/adopt.md`: a `kiro-judge` profile example (`model`, `vendor` matching the family,
    `min_version: "2.32.0"`) and the rule "a Kiro judge's vendor is its model's maker"; `references/kiro.md`: Kiro as a
    judge or clarifier.
  - `CHANGELOG.md`: `## 0.4.20 (unreleased)` with Added (the Kiro judge, clarifier and readiness reviewer; CFG-011;
    judge credits), Changed (the vendor rule and its load error with the fix; `auto` is vendor unknown; the hello runs
    the tool-less agent), Fixed (a Kiro auth failure moves to the next profile; `/usage` "Invalid token" is an auth
    failure).

## 11. Live validation

- [ ] 11.1 A Kiro judge in CI on the owner's dummy repository (L4-KJD-011, design D11). Orchestrator. Depends on all
  code groups, built and pinned on that repository (never a consumer).
  - Confirm the runner's or hosted runner's kiro-cli version (2.32.0 or newer, else install it there first).
  - Configure `kiro-judge` as in D11 and a non-Anthropic implementer; `l4 doctor --live` passes CFG-011 and LIVE-001.
  - Run one unit to a verdict in CI (SCN-KJD-28), then the negative leg (SCN-KJD-29) with no judge call.
  - Record the judge's raw stream (redacted) and replace `judge-pass.stream.jsonl` with it (README: recorded, job id);
    if the reply shape differs from design D3, stop and amend the design before any fix.
  - Answer design §2.3 in `docs/live/kiro-judge/README.md` (served-model field, `tool_call` absence, credits per
    call, the out-of-credits wording if seen, whether `settings/cli.json` under `KIRO_HOME` was read); index it in
    `docs/live/README.md`.

## 12. Close

- [ ] 12.1 Full suite and simulation. Orchestrator. Depends on 10.1, 10.2.
  - The whole test suite in the background; `l4 simulate --all` (`happy-kiro-judge` included);
    `openspec validate kiro-judge --strict`; an independent review of the diff against this change's spec.
