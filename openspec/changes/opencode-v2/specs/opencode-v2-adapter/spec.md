## Purpose

An `opencode` profile can opt in to OpenCode 2 (`@opencode/cli`) without changing what `ok`, `auth`, a limit or a
denial means. Every v2 fact the harness has not seen with a real key sits on a named, conservative fallback until
one live run records it.

## ADDED Requirements

### Requirement: L4-OCV-001 A profile opts in to OpenCode v2 with options.cli_major
An `opencode` profile SHALL select its CLI major with `options.cli_major`, `1` or `2`, default `1`. Any other value
SHALL be a configuration error. The harness SHALL NOT switch majors automatically:
- a `cli_major: 1` profile runs `opencode` and requires major 1 (L4-OCG-002, whose reason ends `or set
  options.cli_major: 2 to run OpenCode 2 (experimental)`);
- a `cli_major: 2` profile runs `opencode2` and requires major 2. Its `binary` step fails otherwise with `opencode2
  <version> is OpenCode v<major>; this profile runs v2 (options.cli_major: 2, @opencode/cli 2.x): install
  @opencode/cli@<pin> (l4 doctor --fix installs it user-locally) or remove options.cli_major`.

At load, a `cli_major: 2` profile SHALL be refused when it sets `options.provider`, when its model's provider is
`azure-cognitive-services` or `google-vertex-anthropic` (the message names `azure` or `google-vertex`), or when
`options.tools` names `list`. A profile without `cli_major: 2` SHALL be refused when it sets `options.steps`. The v2
adapter SHALL be marked experimental, so `agent.experimental` is recorded once per profile.

#### Scenario: SCN-OCV-01 (+) A profile without cli_major runs v1 exactly as before
- **GIVEN** an `opencode` profile with no `options.cli_major`
- **WHEN** a judge call and an implementer step are built
- **THEN** the argv and `OPENCODE_CONFIG_CONTENT` are byte-identical to the current v1 adapter's, and no step bound
  is set

#### Scenario: SCN-OCV-02 (−) A v2 profile with only v1 installed fails at binary by name
- **GIVEN** a `cli_major: 2` profile, an `opencode` that prints `1.18.34`, and an `opencode2` that prints `1.18.34`
- **WHEN** the profile is probed
- **THEN** the `binary` step fails with the v2 reason above and no hello runs

#### Scenario: SCN-OCV-03 (−) Unsupported v2 profile settings are refused at load
- **GIVEN** a `cli_major: 2` profile with `options.provider`, another with the model `azure-cognitive-services/x`,
  another with `options.tools: [list]`, and a `cli_major: 1` profile with `options.steps`
- **WHEN** the configuration loads
- **THEN** each is a configuration error with its message, and the message never repeats a configured value

### Requirement: L4-OCV-002 OpenCode v2 is installed in its own prefix as opencode2
The harness SHALL pin `@opencode/cli` at `OPENCODE2_VERSION` (`2.0.32`), install it only when a `cli_major: 2`
profile is in a role chain, into `$L4_HOME/npm-opencode2` (never the v1 prefix), and link only that prefix's
`opencode2` as `~/.local/bin/opencode2`. That prefix's `.bin` SHALL NOT be on the harness path. `catalog_pins` SHALL
include `agent:opencode2` and `npm:opencode2`, and the agent-CLI cache key's `clis` list SHALL include `opencode2`
when a `cli_major: 2` profile needs it. `ci.cli_versions` SHALL accept the key `opencode2` with a version of major 2
only, and the exact pin and doctor ENV-015 SHALL apply to `opencode2` as to every agent CLI (L4-PRV-045).
`scripts/runner/prereqs.sh` SHALL pin `OPENCODE2_VERSION` in its top block and install it in PRQ-20, behind
`--with-opencode2`.

#### Scenario: SCN-OCV-04 (+) Both majors live side by side
- **GIVEN** role chains with a `cli_major: 1` and a `cli_major: 2` opencode profile and neither CLI installed
- **WHEN** `l4 doctor --fix` runs
- **THEN** `opencode-ai@1.18.34` is in `$L4_HOME/npm`, `@opencode/cli@2.0.32` is in `$L4_HOME/npm-opencode2`, and on
  the harness path `opencode --version` is `1.18.34` and `opencode2 --version` is `opencode v2.0.32`

#### Scenario: SCN-OCV-28 (−) ci.cli_versions holds opencode2 at major 2 only
- **GIVEN** `ci.cli_versions: {opencode2: "2.0.32"}`, and another configuration with `{opencode2: "1.18.34"}`
- **WHEN** each configuration loads
- **THEN** the first loads and `opencode2`'s effective pin is `2.0.32` from `ci.cli_versions`, and the second is a
  configuration error naming OpenCode 1 and L4-OCV-002

#### Scenario: SCN-OCV-05 (+) The cache key follows the v2 profile
- **GIVEN** one configuration without and one with a `cli_major: 2` profile
- **WHEN** `clis_cache_hash` is computed for each
- **THEN** the hashes differ, and both differ from the hash before this change

### Requirement: L4-OCV-003 Every OpenCode v2 call is standalone with a private state directory
Every `opencode2` invocation the harness starts (run, hello, `auth list`, `session export`) SHALL carry
`--standalone` and SHALL get an empty `XDG_STATE_HOME` of its own. One argv builder SHALL build every v2 argv and
SHALL refuse a subcommand outside that set. The harness SHALL NOT start `opencode2 debug config`, `serve`,
`service`, `api`, `pair` or `models`. `XDG_DATA_HOME` SHALL NOT be redirected.

#### Scenario: SCN-OCV-06 (+) Each v2 argv carries --standalone and a private state directory
- **GIVEN** a `cli_major: 2` profile
- **WHEN** the run, the hello, the auth step and the export are built
- **THEN** each argv holds `--standalone` right after its subcommand words, each environment's `XDG_STATE_HOME` is a
  directory of that call alone, and none sets `XDG_DATA_HOME`

#### Scenario: SCN-OCV-07 (−) A subcommand without --standalone cannot be built
- **GIVEN** the v2 argv builder
- **WHEN** it is asked for `debug config` or `models`
- **THEN** it raises `AdapterError` and nothing is started

### Requirement: L4-OCV-004 The v2 run has no v1-only flags and keeps the v1 isolation
A v2 run SHALL be `opencode2 run --standalone --format json -m <provider/model> --title "l4 <role> <stem>"`, with the
worktree (implement) or the empty judge directory (judge) as cwd and the prompt on stdin, followed by EOF. A v2 hello
SHALL be the same with `--title "l4 hello"` and the hello prompt as an argument, in an empty scratch directory with
stdin closed. The `auth list` step and the export SHALL also run with stdin closed: every v2 call SHALL see EOF on
stdin, because OpenCode 2 waits without output while stdin stays open, even with the prompt as an argument [V, 2.0.32
and 2.1.4]. Neither SHALL carry `--pure` or `--dir`. The environment SHALL add, to the allow-list, an empty
per-step `XDG_CONFIG_HOME`, the private `XDG_STATE_HOME`, `OPENCODE_DISABLE_PROJECT_CONFIG`,
`OPENCODE_DISABLE_CLAUDE_CODE`, `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS`, `OPENCODE_DISABLE_EXTERNAL_SKILLS`,
`OPENCODE_DISABLE_AUTOUPDATE` (each `1`) and `OPENCODE_CONFIG_CONTENT`.

#### Scenario: SCN-OCV-08 (+) The v2 argv and environment
- **GIVEN** a `cli_major: 2` implementer request
- **WHEN** the adapter builds its command
- **THEN** the argv is exactly the run form above, the cwd is the worktree, the prompt goes to stdin, and the
  environment holds the five switches

### Requirement: L4-OCV-005 The v2 configuration is native and keeps today's effective rules
For a v2 profile, `OPENCODE_CONFIG_CONTENT` SHALL be the native v2 shape: `$schema`, `snapshots: false`, `share:
"disabled"`, `update: "disable"`, an ordered `permissions` array, and `agents.build.steps`. It SHALL NOT contain
`permission`, `tools`, `snapshot`, `autoupdate`, or a `list` or `doom_loop` rule. Its rules SHALL be those of
design D5:
- judge mode: deny all. For an `opencode/` model, also `read` and `shell` at `ask`.
- implement mode: today's rules, with `bash` written as `shell`, the explicit `external_directory` deny before the
  result-directory allows, and `skill` and `subagent` at the profile's refuse value (`ask` for `opencode/` models,
  else `deny`).
- `options.tools`: deny all, then allow the listed tools' v2 actions.

#### Scenario: SCN-OCV-09 (+) The native rules equal the recorded normalisation of today's rules
- **GIVEN** the recorded v2 normalisation of today's implement, judge-paid and judge-free configurations
- **WHEN** the v2 configuration of each mode is built for the same result directory
- **THEN** its `permissions` equal the recorded array with the `list` and `doom_loop` rules and repeated identical
  rules removed, followed, in implement mode, by the `skill` and `subagent` rules

#### Scenario: SCN-OCV-10 (−) A free judge is never deny-all only
- **GIVEN** a `cli_major: 2` judge profile on `opencode/big-pickle`
- **WHEN** its configuration is built
- **THEN** after `*:* deny` come `read:* ask` and `shell:* ask` (a full deny gets a 403 from the free tier)

#### Scenario: SCN-OCV-11 (−) options.tools keeps its meaning on v2
- **GIVEN** a `cli_major: 2` implementer profile with `options.tools: [read, edit]`, and the recorded v2
  normalisation of the v1 form, where the permission map's allows follow the tools map's deny-all
- **WHEN** the v2 configuration is built
- **THEN** after `*:* deny` only `read` and `edit` are allowed and no rule allows `shell`, where the recorded
  normalisation would allow it again

### Requirement: L4-OCV-006 Each v2 role has a step bound and a bounded run is never ok
The v2 configuration SHALL set `agents.build.steps` to `options.steps.judge` (default 3, allowed 2..20) for every
judge-mode call and the hello, and to `options.steps.implement` (default 200, allowed 10..2000) for an implementer
step. A run whose count of `step_start` events reaches the bound SHALL NOT be `ok`. It SHALL be `permission_blocked`
when it recorded a denial, else `error` with a detail beginning `step_bound:`. A v1 profile SHALL get no bound.

#### Scenario: SCN-OCV-12 (+) The bounds per role, and a profile override
- **GIVEN** a `cli_major: 2` profile without `options.steps`, and one with `options.steps: {implement: 400}`
- **WHEN** the judge, hello and implementer configurations are built
- **THEN** the first gets 3, 3 and 200, and the second gets 3, 3 and 400

#### Scenario: SCN-OCV-13 (−) The recorded bounded ask loop is permission_blocked
- **GIVEN** the recorded v2 run with `steps: 3` (two rejected tool calls, then a summary text) as a judge call with
  bound 3
- **WHEN** it is parsed
- **THEN** the status is `permission_blocked` with the two denials, and is not `ok` even though the exit code is 0

### Requirement: L4-OCV-007 v2 status comes from the exit code, the error event, the bound and the exported outcome
A v2 run SHALL be `ok` only when the exit code is 0, there is no `error` event, the step bound was not reached,
`opencode2 session export <id> --standalone` reports `info.outcome` `succeeded`, and the result attaches (the judge's
JSON reply, taken from the text after the last tool call, or the implementer's result file). A final `step_finish`
SHALL NOT be required. Any other `outcome` SHALL be `error` naming it. When the export is unavailable, the v1 rule
(last `step_finish` reason `stop`) SHALL decide, else `permission_blocked` on denials, else `error` naming the export
failure. A run that a v1 flag rejected SHALL keep L4-OCG-003.

#### Scenario: SCN-OCV-14 (+) A recorded success without a final step_finish is ok
- **GIVEN** the recorded v2 text run whose stream ends at `text` (no `step_finish`), exit 0, and its recorded export
  with `outcome: "succeeded"`
- **WHEN** it is parsed as a run whose result attaches
- **THEN** the status is `ok`

#### Scenario: SCN-OCV-15 (−) No export and no final stop is an error that names the export
- **GIVEN** the same stream with the export unavailable (exit 1)
- **WHEN** it is parsed
- **THEN** the status is `error` and the detail names the export failure

#### Scenario: SCN-OCV-16 (−) Another outcome is never ok
- **GIVEN** the recorded export with `outcome` changed to `failed`
- **WHEN** the stream is parsed with it
- **THEN** the status is `error` and the detail names `failed`

### Requirement: L4-OCV-008 v2 usage comes from the export
For a v2 run with an export, input, output and cache-read tokens SHALL be the sums over the export's assistant
messages, cost SHALL be `info.cost` (else the messages' sum), and `context_peak_tokens` SHALL be the largest `input +
cache.read + cache.write` of one assistant message. Without an export, the stream's `step_finish` parts SHALL be
summed as in v1.

#### Scenario: SCN-OCV-17 (+) Usage from the recorded export
- **GIVEN** the recorded export (input 3310, output 78, cache read 605, cost 0)
- **WHEN** the run is parsed with it
- **THEN** the usage is 3310 in, 78 out, 605 cached, cost 0.0, context peak 3915

### Requirement: L4-OCV-009 v2 errors, limits and denials are read from the v2 shapes only
A v2 `error` event (`type`, `message`, `status`, `response.body`) SHALL be classified as follows:
- `auth`: `status` 401 or 403, `type` `provider.auth`, or the existing auth wording;
- a `credits` limit: `status` 402;
- a `rate_limit` limit with no reset: `status` 429. Its body, headers and message SHALL NOT be parsed for a reset
  (`status_only`);
- retryable: `status` ≥ 500;
- otherwise an `error` naming the type and status.

A denial SHALL be a `tool_use` in error whose text starts with `Permission denied:` or contains `cannot ask the user
for permission`.

#### Scenario: SCN-OCV-18 (+) Both recorded free-tier 403s are auth
- **GIVEN** the recorded v2 403 for denied tools and the recorded v2 403 for a flagged network
- **WHEN** each is parsed as a run and as a hello
- **THEN** each is `auth`, and neither is a limit

#### Scenario: SCN-OCV-19 (−) A v2 429 is a rate limit without a guessed reset
- **GIVEN** a v2 `error` event with `status` 429 and a body that says `retry in 9h9m42s`
- **WHEN** it is parsed
- **THEN** the status is `rate_limited` with a `rate_limit` limit whose `resets_at` is empty, so the default cool-down
  applies

#### Scenario: SCN-OCV-20 (+) The recorded v2 denials are recorded
- **GIVEN** the recorded v2 implement run (a `shell` call refused with `Permission denied: shell`) and the recorded
  ask loop
- **WHEN** they are parsed
- **THEN** `permission_denials` lists each refused call with its tool name and input

### Requirement: L4-OCV-010 v2 auth presence comes from auth list in JSON
For a provider that is not decided by `OPENCODE_API_KEY` and is not free, the v2 auth step SHALL run `opencode2 auth
list --standalone --format json`. The provider SHALL count as present when an entry's `id` equals the model's
provider and it has a connection whose status is not `needs_auth`. A `needs_auth` connection SHALL fail the step with
its message. Unparsable output SHALL fail the step as an unrecognised answer.

#### Scenario: SCN-OCV-21 (+) The recorded listing with an environment key
- **GIVEN** the recorded `auth list` JSON with `OPENCODE_API_KEY` set
- **WHEN** a profile on `opencode-go/deepseek-v4.1-flash` is checked against it
- **THEN** `opencode-go` is present

#### Scenario: SCN-OCV-22 (−) An empty listing and a needs_auth connection fail
- **GIVEN** the recorded empty listing `[]`, and the recorded `opencode` entry whose connection says `needs_auth`
- **WHEN** profiles on `openrouter/x` and `opencode/x` (the latter with no free-model skip, as a test of the parser)
  are checked
- **THEN** both fail, and the second names the `needs_auth` message

### Requirement: L4-OCV-011 A v2 reply's leaked leading reasoning is stripped
On v2 only, a text part that holds `</think>` before any `<think>` SHALL lose everything up to and including the
first `</think>`, before the hello compares its reply and before the judge reply is sliced.

#### Scenario: SCN-OCV-23 (+) The recorded leaked hello passes
- **GIVEN** the recorded v2 hello whose text is `…</think>L4-OK`
- **WHEN** the v2 hello evaluates it
- **THEN** it passes; the same text through the v1 hello still fails as `unexpected reply`

### Requirement: L4-OCV-012 The probe, the doctor and the recorded versions follow the profile's major
The probe, doctor ENV-004 and doctor LIVE-005 SHALL check the profile's own binary and major (`opencode2` and 2 for a
v2 profile). LIVE-005 SHALL compare a version only with recorded versions of the same major.

#### Scenario: SCN-OCV-24 (+) LIVE-005 per major
- **GIVEN** recordings for 1.18.33, 1.18.34 and 2.0.32, a v2 profile whose `opencode2` prints `opencode v2.0.33`,
  and a v1 profile whose `opencode` prints `1.18.35`
- **WHEN** LIVE-005 runs
- **THEN** it warns `unrecorded version` for both, naming only `2.0.32` for the first and only `1.18.33, 1.18.34` for
  the second

### Requirement: L4-OCV-013 Each unverified v2 fact sits on a named fallback until a live run records it
Each [U] fact of the v2 adapter (design D13: U1 to U11) SHALL ship with its named fallback, a unit test that pins
that fallback, and the SPEC's [U] marker. No parser for a [U] shape SHALL be written before its fixture is
recorded. The adapter SHALL stay experimental until a live CI run on the owner's dummy repository, with a real
`OPENCODE_API_KEY`, has recorded a fixture or a LIVE check for every row. A fallback SHALL be replaced only by
behaviour pinned by such a recording.

#### Scenario: SCN-OCV-25 (−) An unrecorded provider form stays refused
- **GIVEN** no recorded v2 run with a custom provider key file
- **WHEN** a `cli_major: 2` profile sets `options.provider`
- **THEN** the configuration is refused with the `provider_refused` message

#### Scenario: SCN-OCV-26 (+) The v2 adapter is announced as experimental
- **GIVEN** a role chain whose selected profile is `cli_major: 2`
- **WHEN** it is selected twice in one run
- **THEN** one `agent.experimental` event names the profile

### Requirement: L4-OCV-014 An OpenCode v2 profile does not serve the delegate in this release
A `cli_major: 2` profile in `roles.delegate` SHALL be a configuration error at load, whose message names the profile,
`roles.delegate` and L4-DLG-016, and says to remove the profile from the role or to use a `cli_major: 1` profile. The
v2 adapter SHALL refuse a read-only request (`PermissionPolicy("read_only")`) with `AdapterError` before it starts
anything. A `cli_major: 2` profile in the other roles SHALL be unaffected.

#### Scenario: SCN-OCV-27 (−) A v2 profile in roles.delegate is refused at load
- **GIVEN** `roles.delegate: [oc2]` where `oc2` is an `opencode` profile with `options.cli_major: 2`, and the same
  profile in `roles.judges`
- **WHEN** the configuration loads, and separately when the v2 adapter is given a read-only request
- **THEN** the load fails with the L4-OCV-014 message naming `oc2`; without `oc2` in `roles.delegate` it loads; the
  read-only request raises `AdapterError` and no process starts
