Every implementer group is one implementer step, run in order in one worktree. Group B8 is the orchestrator's, and
no implementer runs it. Each implementer step follows these rules:
- Read `proposal.md`, `design.md` and `specs/opencode-v2-adapter/spec.md` of this change and the rows of
  `docs/plan/opencode-v2.md` that the task names. `opencode-major-gate` (row 51) is merged before B1: use its
  `l4.versions.major_of`, `catalog.major_problem` and the `unsupported_version` class.
- Write the named tests first. Run them and see them fail for the reason the task names. Then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>`. Then run
  `.venv/bin/ruff check <changed files>` and `.venv/bin/ruff format --check <changed files>`.
- Stage explicit paths only (never `git add -A` or a bare directory). Commit messages: `opencode-v2 B<n>: …`, with no
  trailer and no local path.
- Never write a `while pgrep …` loop or any loop that waits on a process name. Never start an `opencode` or
  `opencode2` binary from a test. Tests use the recorded fixtures and fake runners only.
- Name no consumer repository. Write "a consumer repository" when one is meant.
- **Do not write a parser for an unverified ([U]) shape from a guess.** Design D13 lists them (U1–U11). Until B8 has
  recorded a fixture for one, it stays on its named fallback, and a test pins that fallback by name (the fallback's
  name appears in the test function's name or docstring and in a code comment at the branch).
- Fixture files hold no local path. Before committing one, `grep -rnE '/private/|/Users/|/home/[a-z]|/var/folders/'`
  and `grep -rn "$USER"` over it must print nothing.
- v1 is unchanged. `tests/unit/agents/test_opencode.py` and the other v1 tests pass without edits, except where a
  task names an edit.

## 1. Group B1: v2 fixtures and recorded versions per major (L4-OCV-012, part)

Depends on: `opencode-major-gate` merged.

- [ ] 1.1 Fixtures. The orchestrator passes the directory of the raw outputs recorded in an isolated HOME as `OC2_RAW`.
  Write a throwaway scrub script outside the repository. It replaces:
  - every occurrence of `$(dirname "$OC2_RAW")` and of its `/private`-prefixed or unprefixed twin with `/tmp/l4-oc2`;
  - any `/Users/<name>` or `/home/<name>` prefix with `/home/user`;
  - the private LAN address in `baseURL` with `192.0.2.1`.

  Copy each source to `tests/fixtures/recorded/opencode/2.0.32/<target>` through it:

  | Source in `OC2_RAW` | Target |
  |---|---|
  | `x5-v2-version.stdout` | `version.stdout.txt` |
  | `v2-hello-rep-3.jsonl` | `hello-ok-step-finish.jsonl` |
  | `v2-hello-rep-1.jsonl` | `hello-ok-no-step-finish.jsonl` |
  | `v2-stdin-hello-1.jsonl` | `hello-ok-stdin-no-step-finish.jsonl` |
  | `v2-hello-standalone.jsonl` | `hello-think-leak.jsonl` |
  | `v2-text-1.jsonl` | `text-no-step-finish.jsonl` |
  | `v2-text-1.export.json` | `text-no-step-finish.export.json` |
  | `v2-judgepaid-free.jsonl` | `error-403-free-tier-denied-tools.jsonl` |
  | `x5-v2-hello-steps1-1.jsonl` | `error-403-free-tier-network.jsonl` |
  | `v2-ask.jsonl`, `v2-ask.stderr` | `ask-loop-unbounded.jsonl`, `ask-loop-unbounded.stderr.txt` |
  | `v2-ask-steps3.jsonl`, `v2-ask-steps3.stderr` | `ask-loop-steps3.jsonl`, `ask-loop-steps3.stderr.txt` |
  | `v2-impl.jsonl` | `implement-deny-continues.jsonl` |
  | `x5-v2-auth-list.json` | `auth-list-empty.json` |
  | `x5-v2-auth-list-env.json` | `auth-list-env-key.json` |
  | `v2-norm-implement-paid.json`, `v2-norm-judge-paid.json`, `v2-norm-judge-free.json`, `v2-norm-readonly-paid.json`, `v2-norm-implement-provider.json` | `config-normalised-implement.json`, `-judge-paid.json`, `-judge-free.json`, `-read-only.json`, `-implement-tools.json` |
  | `x6-v2-native-steps-config.json`, `x6-v2-v1steps-config.json` | `config-steps-native.json`, `config-steps-v1-form.json` |

  Add `README.md` there. It gives one line per file: what was run (mode, model, the config shape), "recorded in an
  isolated HOME, 2026-10-19, @opencode/cli 2.0.32, no key", and the matrix row of `docs/plan/opencode-v2.md`. Then
  run the two grep checks from the rules. They must print nothing.
- [ ] 1.2 Tests first:
  - `tests/unit/test_recorded_versions.py`: after `.venv/bin/python -m l4.recordedversions --write`,
    `recorded_versions.json` lists `2.0.32` under `opencode`.
  - New `tests/unit/test_recorded_versions_major.py` (SCN-OCV-24, unit part): `unrecorded("opencode", "2.0.33")` is
    `["2.0.32"]`, `unrecorded("opencode", "1.18.35")` is `["1.18.33", "1.18.34"]`, `unrecorded("opencode", "2.0.32")`
    is None, and a version whose major has no recording at all (`"3.0.0"`) gives the full list.

  Code: `src/l4/recordedversions.py` (`unrecorded` filters `known` by `major_of`) and the regenerated
  `src/l4/recorded_versions.json`.
- [ ] 1.3 Run `pytest tests/unit/test_recorded_versions.py tests/unit/test_recorded_versions_major.py
  tests/unit/doctor/test_live_005.py` and the ruff checks. Commit.

  Done when: the fixture directory holds the files of 1.1 and the README, both grep checks are empty, and the tests
  pass.

## 2. Group B2: selection and configuration checks (L4-OCV-001)

Depends on: B1.

- [ ] 2.1 Tests first, `tests/unit/config/test_opencode_cli_major.py` (SCN-OCV-03, SCN-OCV-25):
  - `options.cli_major` absent → 1; `2` accepted; `3`, `"2"` and `true` refused.
  - `options.steps: {judge: 3, implement: 200}` accepted on `cli_major: 2`. Values outside judge 2..20 and implement
    10..2000 refused.
  - On a `cli_major: 2` profile, these are refused with the exact messages of design D1:
    - `options.provider`;
    - the model `azure-cognitive-services/m` and the model `google-vertex-anthropic/m`;
    - `options.tools: [list]`.
  - `options.steps` on a profile without `cli_major: 2` is refused.
  - No message holds a configured value: assert the model id's second part is absent from it.

  Code: `src/l4/config/schema.py` (`OpencodeOptions.cli_major`, `OpencodeSteps`, `opencode_option_problems`).
- [ ] 2.2 Tests first, `tests/unit/test_versions_major.py` (extend A's file):
  - `catalog.profile_cli(profile)` gives `("opencode", 1)` for a profile without `cli_major` and `("opencode2", 2)`
    for `cli_major: 2`.
  - `major_problem` for a v1 profile now ends `or set options.cli_major: 2` (no "when supported").
  - For a v2 profile whose `opencode2` prints `1.18.34`, it gives exactly the v2 reason of L4-OCV-001.

  Update A's tests that pinned the old ending. Code: `src/l4/provision/catalog.py` (`profile_cli`, `major_problem`
  taking the expected major and binary).
- [ ] 2.3 Run `pytest tests/unit/config tests/unit/test_versions_major.py tests/unit/availability/test_probes_opencode.py
  tests/unit/doctor` and the ruff checks. Commit.

  Done when: these pass and every v1 test passes unchanged.

## 3. Group B3: provisioning, prereqs.sh, and the doctor's binary per profile (L4-OCV-002, L4-OCV-012 doctor part)

Depends on: B2 (`profile_cli`, `cli_major`).

- [ ] 3.1 Tests first, `tests/unit/provision/test_catalog.py`, `test_plan.py` and `test_install.py` (SCN-OCV-04,
  SCN-OCV-05):
  - `OPENCODE2_VERSION == "2.0.32"`, and `catalog_pins()` holds `agent:opencode2` and `npm:opencode2 =
    @opencode/cli`.
  - `required_tools` yields `opencode` only for `cli_major: 1` profiles and `opencode2` (binary `opencode2`) only for
    `cli_major: 2` profiles.
  - `clis_cache_hash` differs with and without a v2 profile.
  - `install_planned` with fakes runs `npm install --prefix <l4_home>/npm-opencode2 … @opencode/cli@2.0.32` and links
    only `<prefix>/node_modules/.bin/opencode2` as `~/.local/bin/opencode2`, never `opencode`, with
    `replace_files=False` (a regular file there is never replaced).
  - `harness_path` does not contain `npm-opencode2`.
  - The pin drift test reads `OPENCODE2_VERSION` from `prereqs.sh`. Its regex becomes `^([A-Z0-9]+)_(VERSION|MIN)=`.

  Code: `src/l4/provision/catalog.py`, `runner.py` (`Paths.npm_prefix_opencode2`, `plan_fixes` uses the tool's
  major), `install.py` (`_install_agent` for `opencode2`, through A's guarded `_link`; `manual_command` for
  `opencode2`).
- [ ] 3.2 Tests first, `tests/unit/runner/test_prereqs_steps.py`:
  - `OPENCODE2_VERSION=${OPENCODE2_VERSION:-2.0.32}` is in the top block.
  - `step PRQ-20 "OpenCode v2 …" check_opencode2 apply_opencode2` runs under `if [ "$WITH_OPENCODE2" = 1 ]`, and
    `--with-opencode2) WITH_OPENCODE2=1` is parsed.
  - `apply_opencode2` installs into `$L4_HOME/npm-opencode2` and links only `.bin/opencode2`.
  - `check_opencode2` with a stub printing `opencode v2.0.32` returns 0, and with `1.18.34` returns non-zero.
  - `bash -n` passes.

  Code: `scripts/runner/prereqs.sh` (and its header's usage lines).
- [ ] 3.3 Tests first, `tests/unit/doctor/test_checks_env_004.py` and `tests/unit/doctor/test_live_005.py`
  (SCN-OCV-24):
  - a v2 profile is checked through `opencode2` with major 2, and a v1 profile through `opencode`;
  - LIVE-005 gives the per-major lists of SCN-OCV-24.

  Code: `src/l4/doctor/checks_env.py` and `checks_agents.py` use `profile_cli`. Also `src/l4/eval/env.py` if it maps
  an adapter to a binary.
- [ ] 3.4 Run `pytest tests/unit/provision tests/unit/runner tests/unit/doctor` and the ruff checks. Commit.

  Done when: these pass, and no v1 provisioning test needed an edit beyond the drift regex.

## 4. Group B4: the v2 command layer (L4-OCV-001 adapter part, -003, -004, -005, -006 configuration part)

Depends on: B2. B3 is not needed, but run B4 after B3 so the groups stay in order.

- [ ] 4.1 Tests first, new `tests/unit/agents/test_opencode_v2_command.py`:
  - SCN-OCV-06: `v2_argv` for `run`, `auth list` and `session export` puts `--standalone` right after the subcommand
    words. The environments built for run, hello, export and auth each have their own `XDG_STATE_HOME` under the
    call's private directory, and none sets `XDG_DATA_HOME`.
  - SCN-OCV-07: `v2_argv(exe, "debug", "config")` and `v2_argv(exe, "models")` raise `AdapterError`.
  - SCN-OCV-08: the implementer argv is exactly `[exe, "run", "--standalone", "--format", "json", "-m", model,
    "--title", "l4 implementer <stem>"]`. `--pure` and `--dir` appear in no v2 argv. The environment has the five
    switches.
  - SCN-OCV-09: for result dir `/tmp/l4-step/result`, `config_content_v2` of implement (paid), judge (paid), judge
    (`opencode/big-pickle`) and read-only equals the recorded `config-normalised-*.json` `permissions` with the
    `list` and `doom_loop` rules and repeated identical rules removed, followed in implement and read-only by
    `skill` and `subagent` at the refuse value. The document has `snapshots: false`, `share: "disabled"`,
    `update: "disable"` and none of `permission`, `tools`, `snapshot`, `autoupdate`.
  - SCN-OCV-10: the free judge's rules are `*:* deny`, `read:* ask`, `shell:* ask`.
  - SCN-OCV-11: `options.tools: [read, edit]` gives `*:* deny`, `read:* allow`, `edit:* allow`, and no `shell` allow.
    The recorded `config-normalised-implement-tools.json` does allow `shell`: assert that too, as the reason.
  - SCN-OCV-12: `agents.build.steps` is 3 for judge mode and the hello, 200 for implement, and 400 with
    `options.steps.implement: 400`.
  - The recorded `config-steps-native.json` and `config-steps-v1-form.json` both hold `agents.build.steps == 3`.
    This pins D5's equivalence.

  Code: new `src/l4/agents/opencode_v2.py` (`v2_argv`, `isolation_env_v2`, `config_content_v2`, `step_bound(policy,
  options)`, and `OpenCodeV2Adapter` with `name = "opencode"`, `experimental = True`, `build_command`).
- [ ] 4.2 Tests first, `tests/unit/agents/test_factory.py` (or the file where `Factory.build` is tested):
  - SCN-OCV-01: a profile without `cli_major` builds `OpenCodeAdapter`, and its `build_command` and `config_content`
    are byte-identical to before. Pin them with literal expected strings taken from the current code before editing.
  - `cli_major: 2` builds `OpenCodeV2Adapter`.
  - SCN-OCV-26: selecting a v2 profile twice records one `agent.experimental`.

  Code: `src/l4/agents/factory.py` (`build`).
- [ ] 4.3 Run `pytest tests/unit/agents tests/unit/availability` and the ruff checks. Commit.

  Done when: these pass. `OpenCodeV2Adapter.run` may raise `NotImplementedError("B6")` until B6. The parser is B5's.

## 5. Group B5: the v2 parser (L4-OCV-006 detection, -007, -008, -009, -011)

Depends on: B1 (fixtures), B4 (module), and the shared judge slicer of the `kiro-judge` change (row 50, its task
2.1): `l4.agents.contract.attach_judge_reply(result, text, schema)`. The v2 judge reply goes through that function
with the v2 reply text (`last_message` after `strip_leading_think`). Never write a second slicer. If the
orchestrator says `kiro-judge` is not in the base yet, add `attach_judge_reply` to `src/l4/agents/contract.py`
exactly as that task defines it (the same signature, docstring and messages, moved from
`OpenCodeAdapter._attach_judge_reply`), and make `OpenCodeAdapter._attach_result` call it, so the later merge sees the
same change.

- [ ] 5.1 Tests first, new `tests/unit/agents/test_opencode_v2_parse.py`, all from the B1 fixtures:
  - SCN-OCV-13: `ask-loop-steps3.jsonl` parsed as judge with `step_bound=3` and exit 0 → `permission_blocked` with 2
    denials. Test it with `export=None` (no export was recorded for that run) and again with a synthetic export saying
    `outcome: "succeeded"`: the bound rule comes first, so both give the same status. Without denials (a synthetic copy with the
    `tool_use` lines removed) → `error` with a detail starting `step_bound:`. Name it
    `test_bounded_run_is_never_ok_not_ok_named`.
  - SCN-OCV-14: `text-no-step-finish.jsonl` with `text-no-step-finish.export.json` → `ok` when the result attaches.
    The same with `hello-ok-step-finish.jsonl` and no export → `ok` by the v1 rule (`export_decides`).
  - SCN-OCV-15: `text-no-step-finish.jsonl` with `export=None, export_problem="exit 1"` → `error` naming the export.
  - SCN-OCV-16: the export with `outcome` set to `"failed"` → `error` naming `failed` (`not_ok_named`).
  - SCN-OCV-17: usage from the export: 3310, 78, 605, cost 0.0, peak 3915. With no export, the stream's
    `step_finish` sums (`sum_messages` names the export path).
  - SCN-OCV-18: `error-403-free-tier-denied-tools.jsonl` and `error-403-free-tier-network.jsonl` → `auth`, no limit
    (`auth_by_status`).
  - SCN-OCV-19 (`status_only`): a synthetic v2 event `{"type":"error","error":{"type":"unknown","message":"retry in
    9h9m42s","status":429,"response":{"body":"retry in 9h9m42s"}}}` → `rate_limited`, limit kind `rate_limit`,
    `resets_at is None`. 402 → `quota`, kind `credits`. 503 → `error` with `, retryable`. Mark it in the test's
    docstring as a fallback pin, not a recorded shape.
  - SCN-OCV-20: `implement-deny-continues.jsonl` → one denial `{tool_name: "shell", tool_input: {...}}`.
    `ask-loop-unbounded.jsonl` → 30 denials.
  - SCN-OCV-23 (unit part): `strip_leading_think("The user just wants exact reply.</think>L4-OK") == "L4-OK"`.
    `"<think>a</think>b"` is unchanged, and `"no tags"` is unchanged.
  - Exit 1 with the A stderr fixture still gives `unsupported_version`.
  - The judge reply is taken from `last_message`: a stream with prose holding `{` before a rejected tool call and a
    JSON reply after it gives `ok`.

  Code: `src/l4/agents/opencode_v2.py` (`_scan_v2`, `strip_leading_think`, `parse` per design D7, `_classify_v2`,
  `usage_from_export`) and `src/l4/availability/limits.py` (`_opencode_v2`, chosen by shape: `error.status` present
  and no `error.data`; no text fallback for it). The v1 `_opencode` is unchanged.
- [ ] 5.2 Run `pytest tests/unit/agents tests/unit/availability/test_limits.py` and the ruff checks. Commit.

  Done when: these pass, and `rg -n "U1|status_only|export_decides|not_ok_named|auth_by_status|sum_messages|strip_leading_think" src/l4/agents/opencode_v2.py src/l4/availability/limits.py`
  shows each fallback named at its branch.

## 6. Group B6: wiring the run and the probe (L4-OCV-001 probe part, -007 run part, -010, -011 hello)

Depends on: B3, B5.

- [ ] 6.1 Tests first, `tests/unit/agents/test_opencode_v2_run.py`, with a fake `ProcRunner` that writes the B1
  fixtures as the run's stdout and stderr:
  - `run()` starts the run argv and then `session export <sid> --standalone` through the same wrap, with stdin closed
    and a 60 s timeout. It saves the export as `<stem>.export.json` beside the raw events, and passes it to `parse`.
  - A fake export that exits 1 yields SCN-OCV-15 end to end.
  - The credential loader wraps only the run argv, never the export.
  - The step's `XDG_STATE_HOME` directory exists and is empty before the run.
- [ ] 6.2 Tests first, `tests/unit/availability/test_probes_opencode_v2.py`:
  - SCN-OCV-02: `opencode2` printing `1.18.34` fails `binary` with the v2 reason, and no hello runs.
  - SCN-OCV-21: `auth-list-env-key.json` passes `opencode-go`.
  - SCN-OCV-22: `auth-list-empty.json` fails an `openrouter/…` profile. The `opencode` entry's `needs_auth`
    fails with its message (call the parser directly for this one, since free models skip the step).
  - The auth argv is `[exe, "auth", "list", "--standalone", "--format", "json"]`.
  - SCN-OCV-23: `hello-think-leak.jsonl` passes the v2 hello. `hello-ok-no-step-finish.jsonl` passes.
    `error-403-free-tier-network.jsonl` fails with class `auth`.
  - The hello argv carries `--standalone`, `--title "l4 hello"`, the prompt, and no `--pure`.
  - The hello's config carries `agents.build.steps == 3`.

  Code: `src/l4/agents/opencode_v2.py` (`run`, `probe_opencode_v2`, `_auth_providers_v2`, `_hello_v2`).
- [ ] 6.3 Run `pytest tests/unit/agents tests/unit/availability tests/unit/doctor tests/unit/provision` and the ruff
  checks. Then run the whole unit suite once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit`. Commit.

  Done when: the whole unit suite passes.

## 7. Group B7: docs (no new code)

Depends on: B6.

- [ ] 7.1 `docs/SPEC.md`:
  - Add **L4-OCV-001…013** (the requirement texts of the spec, in §8.3 after L4-OCG-004) and SCN-OCV-01…26 in Part
    II in the `#### SCN-OCV-01 (+) <title> · L4-OCV-001` form with **Given**, **When**, **Then**. Each [U] fact
    (D13) carries `[U]` with its fallback's name.
  - §8.3 adapter table: add a new row line `| \`opencode\` (\`options.cli_major: 2\`, experimental) | … |` directly
    after the existing `opencode` row. Fill every column from design D2–D11, with the labels of
    `docs/plan/opencode-v2.md`. Do not edit the v1 row's line again, and do not edit the `kiro-cli` row (the
    `kiro-judge` change edits it).
  - L4-FAC-002: add a separate table under the existing one, titled "OpenCode v2 (`options.cli_major: 2`,
    L4-OCV-007)", with the rows `ok`, `permission_blocked`, `quota`/`rate_limited`, `auth`, `error`, `timeout`, from
    design D6, D7 and D9. Leave the existing table's lines unchanged.
  - L4-FAC-007: append "Recorded versions are compared within one major (L4-OCV-012)."
  - The change table: add row 52 as its own new line after row 51: `| 52 | \`opencode-v2\` | an \`opencode\` profile
    opts in to OpenCode 2 with \`options.cli_major: 2\` (default 1, never automatic): \`@opencode/cli@2.0.32\` as
    \`opencode2\` in its own prefix, \`--standalone\` and a private state directory on every call, a native
    configuration with the same rules and per-role step bounds (judge 3, implementer 200), status from the exit code,
    the error event and \`session export\`, v2 errors, limits, denials and \`auth list\` JSON; every unverified fact on a
    named fallback until a live run records it (L4-OCV-001…013; \`openspec/changes/opencode-v2/\`) | a unit on the
    owner's dummy repository runs end to end with a v2 implementer and a v2 free judge, and every [U] row has a
    fixture or a LIVE check |`.

  Run `.venv/bin/python scripts/check_spec.py docs/SPEC.md`, which must exit 0.
- [ ] 7.2 `CHANGELOG.md` `## 0.4.20 (unreleased)` (create it if missing): under `### Added`, one line each for the
  opt-in v2 adapter (experimental), `opencode2` provisioning and PRQ-20, and the step bounds. Under `### Changed`,
  one line saying the agent-CLI cache is rebuilt once (the new pins in `catalog_hash`).
- [ ] 7.3 `docs/runbook.md`: a short section "OpenCode v2 (experimental)". It covers: how to opt in, what
  `l4 doctor --fix` installs, that `opencode` stays v1, the reasons a v2 profile is refused at load, and what
  `step_bound:` and `opencode2 session export failed` mean. Also: `docs/runner/README.md` (or the prereqs usage
  text) names `--with-opencode2`; `docs/plan/opencode-v2.md` §5 marks A and B1–B7 done.
- [ ] 7.4 Run `scripts/check_spec.py docs/SPEC.md` and `openspec validate opencode-v2 --strict`. Commit.

## 8. Group B8 (orchestrator): live validation in CI

Depends on: B7. **Run by the orchestrator, not an implementer.** Use the owner's dummy repository only, never a
consumer repository. Put the key in a masked CI secret `OPENCODE_API_KEY` from the owner's key store, and never echo
it. Never copy a CLI login. Scrub every recorded file as in B1.1 before it enters the repository. Each fixture lands
in `tests/fixtures/recorded/opencode/2.0.32/live-<name>.*`, with a line in that directory's README. The results go in
`docs/live/opencode-v2/README.md` (labels [V]/[I]/[U], no local paths). Before starting, check that the runner's
network is not refused by the free tier (row 24). If it is, use paid `opencode-go/` profiles for every step and
leave the free-judge rows open.

- [ ] 8.1 orchestrator: prepare the dummy repository.
  - Profiles: `oc2-impl` (`cli_major: 2`, `opencode-go/deepseek-v4.1-flash`, `auth: api_key`), `oc2-judge-free`
    (`cli_major: 2`, a free `opencode/` model), and `oc1-hello` (`cli_major: 1`, the same Go model).
  - A two-task spec.
  - `l4 doctor --fix` (or PRQ-20) installs `opencode2` on the runner.

  Record `live-version.stdout.txt` and the `l4 doctor` output.
- [ ] 8.2 orchestrator: run the unit end to end. Keep every v2 step's raw events, stderr and export. This records:
  - U5: the count of runs with and without a final `step_finish`, as `live-step-finish-census.json`;
  - U7: every `outcome` value seen;
  - U11: a multi-step implementer export, as `live-implement.export.json`;
  - one judge call forced over its bound with `options.steps.judge: 2` and a prompt that asks it to read a file. Its
    export outcome goes in `live-bounded.export.json`;
  - U9: five hellos (`live-hello-N.jsonl`), and one direct isolated `--standalone` run with `agents.build.steps: 1`,
    to settle whether step 1 becomes the summary step.
- [ ] 8.3 orchestrator: U1. **Never burst the free tier.** Its answer to traffic it dislikes is to refuse the whole
  network ("abusive traffic from this IP address", row 24). That would take away every free `opencode/` profile of
  the runner, and the owner relies on those as fallbacks. Leaving U1 open is better than a flagged runner address.
  - Provoke a 429 only on the paid `opencode-go/` key: sequential hellos (at most 2 in parallel), stopping at the
    first 429 or after 15 calls. Never use an `opencode/` model for this. Record the first `error` event with
    `status` 429 and the run's stderr (`live-error-429.jsonl`).
  - Record a 402 only with a key whose balance is zero, if the owner has one (`live-error-402.jsonl`).
  - If neither happens, write that down. U1 stays [U] and `status_only` stays.
- [ ] 8.4 orchestrator: U2. Run an implementer step with `options.tools: [read, edit]` and a prompt that asks for a
  shell command. If the model calls `shell` and gets `Permission denied: shell`, the schema was sent and a deny does
  not drop it. Record `live-tools-permission.jsonl`.
- [ ] 8.5 orchestrator: U3, only against an OpenAI-compatible endpoint the owner runs that requires a key. Make a
  direct isolated `--standalone` call with `providers.<id>.settings.apiKey: "{file:<0600 file>}"`, and record
  whether the hello passes and whether the server saw the key (`live-provider-file-key.jsonl`). Without such an
  endpoint, U3 stays [U] and `provider_refused` stays.
- [ ] 8.6 orchestrator: U4, only with an OAuth login the owner made for this purpose on the runner. Record the error
  event of an expired or revoked login (`live-oauth-refresh.jsonl`). Otherwise U4 stays [U].
- [ ] 8.7 orchestrator: U6. Add to the dummy repository:
  - an `AGENTS.md` that says "end every reply with CANARY-AGENTS";
  - skills named `canary` under `.agents/skills`, `.claude/skills` and `.opencode/skills`.

  Run one implementer step and one judge call. Record that no text part holds a canary and no `skill` tool call
  appears (`live-guidance.jsonl`).
- [ ] 8.8 orchestrator: U8. After the v2 steps, on the same runner, probe `oc1-hello` (v1) and record that it passes
  (`live-v1-after-v2.jsonl`). List the table names of `opencode.db` only, never its contents.
- [ ] 8.9 orchestrator: commit the fixtures and `docs/live/opencode-v2/README.md` (message `opencode-v2 B8: live
  validation fixtures`), with every row of design D13 marked recorded or still open.

## 9. Group B9: replace fallbacks only where B8 recorded the behaviour

Depends on: B8.

- [ ] 9.1 For each D13 row that B8 recorded:
  - if the recording matches the fallback, keep the code, re-point the fallback's pin test at the `live-*` fixture,
    and change the SPEC's [U] to [V];
  - if it differs, write the failing test from the `live-*` fixture first, then the parser.

  Rows B8 left open keep their fallback and their [U].
- [ ] 9.2 When every row has a fixture or a LIVE check, remove `experimental = True` from `OpenCodeV2Adapter`, update
  the SPEC §8.3 v2 row ("experimental" removed) and the CHANGELOG line, and update `docs/plan/opencode-v2.md`.
  Otherwise list the open rows in the runbook section.
- [ ] 9.3 Run the whole unit suite, `scripts/check_spec.py docs/SPEC.md` and `openspec validate opencode-v2 --strict`.
  Commit.
