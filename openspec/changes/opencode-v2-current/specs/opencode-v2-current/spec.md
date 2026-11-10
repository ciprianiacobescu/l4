## Purpose

The OpenCode 2 adapter is supported on the version a live check ran on. An implementer is offered only the tools L4
names, its shell cannot start the OpenCode CLI, and a profile that needs no stored login shares no data home with any
other run. Every fact the check did not record stays on its named fallback.

## ADDED Requirements

### Requirement: L4-OCV-015 An OpenCode v2 implementer's permissions are an allow-list
For an implementer step without `options.tools`, the v2 `permissions` array SHALL start with `{"action": "*",
"resource": "*", "effect": <refuse>}`, where refuse is `ask` for an `opencode/` model and `deny` otherwise (L4-OCV-005).
The rules of L4-OCV-005 SHALL follow in their order. So every action that no later rule names starts refused: OpenCode's
own tools (`worktree_create`, `worktree_list`, `session_move`, `session_rename`, `models`, the MCP resource tools,
`execute`, `experimental_image_generate`) and any tool a later version adds. The `options.tools` array, whose first rule
is already `*:* deny`, and the judge arrays SHALL NOT change. Two tools stay offered, as a stated residual:
- `worktree_remove`, which OpenCode gates with `edit` [V], and which the agent sandbox's read-only git common directory
  makes fail [I];
- `skill`, which OpenCode offers in every mode [V], and which finds no skill under L4's isolation [V once; U6].

#### Scenario: SCN-OCV-29 (+) An implementer's rules start with a refuse-all
- **GIVEN** `cli_major: 2` implementers on `opencode-go/deepseek-v4.1-flash` and on `opencode/big-pickle`, and the
  result directory `/tmp/l4-step/result`
- **WHEN** their configurations are built
- **THEN** the first rule is `*:* deny` for the first and `*:* ask` for the second
- **AND** the rules after it are the 0.4.55 array in its order, with the OpenCode CLI denies after the git denies

#### Scenario: SCN-OCV-30 (−) OpenCode's own tools and an unknown tool are refused to an implementer
- **GIVEN** the paid implementer array of SCN-OCV-29, and the actions `opencode_worktree_create`,
  `opencode_worktree_list`, `opencode_session_move`, `opencode_session_rename`, `opencode_models`,
  `opencode_list_mcp_resources`, `opencode_read_mcp_resource`, `execute`, `experimental_image_generate` and
  `a_tool_added_later`
- **WHEN** a call of each action on the resource `calc.py` is matched against the array (a rule matches when its
  action and its resource both match, `*` spanning any text; the last matching rule decides)
- **THEN** only the first rule matches each, so each ends at `deny`
- **AND** `edit`, `read`, `glob` and `grep` on `calc.py`, and `shell` running `ls`, end at `allow`

#### Scenario: SCN-OCV-31 (−) options.tools and judge mode keep their arrays
- **GIVEN** a `cli_major: 2` implementer with `options.tools: [read, edit]`, a paid judge and a free judge
- **WHEN** their configurations are built
- **THEN** each array equals the 0.4.55 array: one `*` rule, the first, and nothing else changed

#### Scenario: SCN-OCV-32 (+) The recorded runs on 2.2.6 are ok
- **GIVEN** `live-judge` and `live-judge-free` (judge, bound 3), and `live-implement` (implementer, bound 200, with
  its result file), each with its export
- **WHEN** each is parsed
- **THEN** each is `ok` with no denial
- **AND** the usage (input, output, cache read) equals the export's `info.tokens`: 756, 44, 0; 1247, 43, 128; and 2773,
  278, 7936

### Requirement: L4-OCV-016 The agent's shell may not start the OpenCode CLI
Wherever a v2 configuration allows `shell`, it SHALL deny `shell` for `opencode*`, `opencode2*` and `*bin/opencode*`,
right after the git denies. That is an implementer without `options.tools`, or one whose `options.tools` names `bash`.
- A path pattern SHALL NOT refuse a command only because a path in it holds `/opencode`.
- The denies are a guard. The agent sandbox is the boundary (L4-SEC-005).
- v1's configuration SHALL stay byte-identical (L4-OCV-005).

#### Scenario: SCN-OCV-33 (+) The shell may not start the OpenCode CLI
- **GIVEN** the default `cli_major: 2` implementer configuration, and one with `options.tools: [bash, read]`
- **WHEN** they are built, and these commands are matched against their `shell` rules (`*` spans any text, the last
  matching rule decides): `opencode2 api GET /api/project`, `opencode serve --service`,
  `/home/u/.local/bin/opencode2 run x` and `node_modules/.bin/opencode --version`
- **THEN** each array holds `shell:opencode* deny`, `shell:opencode2* deny` and `shell:*bin/opencode* deny` after the
  git denies, and each command ends at `deny`
- **AND** `ruff check src/l4/agents/opencode_v2.py`, `cat src/l4/agents/opencode.py` and
  `ls tests/fixtures/recorded/opencode` end at `allow`

#### Scenario: SCN-OCV-34 (−) No CLI deny without a shell, and none in v1
- **GIVEN** a `cli_major: 2` implementer with `options.tools: [read, edit]`, a `cli_major: 2` judge, and a
  `cli_major: 1` implementer
- **WHEN** their configurations are built
- **THEN** the first two hold no `shell` rule that names `opencode`
- **AND** the v1 `OPENCODE_CONFIG_CONTENT` is byte-identical to 0.4.55's

#### Scenario: SCN-OCV-35 (+) The recorded refused CLI call is a denial and the step goes on
- **GIVEN** `live-cli-denied` with its export and its result file
- **WHEN** it is parsed as an implementer step
- **THEN** it is `ok`
- **AND** `permission_denials` is `[{tool_name: shell, tool_input: {command: "opencode2 api GET /api/project"}}]`

### Requirement: L4-OCV-017 A v2 profile that needs no stored login has a private data home
A `cli_major: 2` profile needs no stored login when its credential variable is `OPENCODE_API_KEY` (L4-PRV-028) or its
model is an `opencode/` model. Such a profile SHALL get these private directories:
- the run and its `session export`: `XDG_DATA_HOME` set to `<step dir>/opencode2-data`, made empty and 0700 before the
  run and kept for the export;
- the hello: an empty 0700 `data` directory in its own scratch directory.

Its auth step SHALL start no process. The run and the export SHALL also get `UV_PYTHON_INSTALL_DIR` and `UV_TOOL_DIR`,
set to the directories the agent sandbox binds for them. A profile with a stored login SHALL keep the real data home.

#### Scenario: SCN-OCV-37 (+) An api-key or free profile runs and exports with a private data home
- **GIVEN** a `cli_major: 2` implementer with `auth: api_key` on `opencode-go/deepseek-v4.1-flash`, another on
  `opencode/big-pickle`, a fake process runner, and a symlink planted at `<step dir>/opencode2-data`
- **WHEN** each runs
- **THEN** the run and the export have `XDG_DATA_HOME` = `<step dir>/opencode2-data`, which was empty and 0700 when
  the run started; the link was removed and its target is untouched
- **AND** a file the fake run wrote there is still there when the export starts
- **AND** both have `UV_PYTHON_INSTALL_DIR` and `UV_TOOL_DIR` set to the directories `l4.sandbox.home` binds

#### Scenario: SCN-OCV-38 (−) A profile with a stored login keeps the real data home
- **GIVEN** a `cli_major: 2` profile on `opencode-go/deepseek-v4.1-flash` with no `auth`, and one on `openrouter/x`
- **WHEN** the run, the export, the hello and the auth step are built
- **THEN** no call sets `XDG_DATA_HOME`, `UV_PYTHON_INSTALL_DIR` or `UV_TOOL_DIR`

#### Scenario: SCN-OCV-39 (+) The hello of such a profile uses a private data home, and its auth step starts nothing
- **GIVEN** the two profiles of SCN-OCV-37, with `OPENCODE_API_KEY` set for the first
- **WHEN** they are probed
- **THEN** each hello's `XDG_DATA_HOME` is an empty 0700 `data` directory in its scratch directory, gone after the
  hello
- **AND** the first's auth step passes with `auth_method: env`, the second's is skipped, and neither starts a process

### Requirement: L4-OCV-018 Such a profile's sandbox does not bind the real OpenCode data and config homes
The agent sandbox of a profile of L4-OCV-017 SHALL NOT bind any of its own credential paths that is, contains or lies
inside `~/.local/share/opencode` or `~/.config/opencode`. It SHALL hide them like another adapter's login (L4-SEC-005).
Its other credential paths SHALL stay bound read-write. Every other profile SHALL bind exactly what it bound before.

#### Scenario: SCN-OCV-40 (+) Such a profile's sandbox hides the real data and config homes
- **GIVEN** an agent spec for the api-key profile of SCN-OCV-37, with `~/.local/share/opencode`, `~/.config/opencode`
  and `~/.cache/opencode` present
- **WHEN** the bwrap argv is built
- **THEN** `~/.local/share/opencode` and `~/.config/opencode` are covered by a tmpfs and never bound
- **AND** `~/.cache/opencode` is bound read-write

#### Scenario: SCN-OCV-41 (−) v1 profiles and stored-login v2 profiles bind as before
- **GIVEN** agent specs built through `agent_spec` for a `cli_major: 1` profile with `auth: api_key` on
  `opencode-go/deepseek-v4.1-flash`, one with a subscription, and a `cli_major: 2` profile on `openrouter/x`
- **WHEN** each bwrap argv is built
- **THEN** each equals, element for element, the argv of the same spec with `hide_own_homes` at its default, and binds
  all three opencode login paths
- **AND** `tests/unit/sandbox/test_probe_parity.py` passes unchanged

#### Scenario: SCN-OCV-42 (−) A configured login path inside a hidden home is hidden too
- **GIVEN** `sandbox.credential_paths.opencode` set to `~/.local/share/opencode/auth.json`, `~/.cache/opencode` and
  `/opt/oc-login`, and the api-key profile of SCN-OCV-37
- **WHEN** the bwrap argv is built
- **THEN** `auth.json` is covered by `/dev/null` and not bound
- **AND** `~/.cache/opencode` and `/opt/oc-login` are bound

### Requirement: L4-OCV-019 OpenCode v2 is supported on its live-checked pin
`OPENCODE2_VERSION` SHALL be `2.2.6`. The v2 adapter SHALL NOT be marked experimental, and SHALL NOT be announced with
`agent.experimental`. The v1 reason of L4-OCG-002 SHALL end `or set options.cli_major: 2 to run OpenCode 2`. The live
recordings of 2.2.6 SHALL be kept under `tests/fixtures/recorded/opencode/2.2.6/`, beside the 2.0.32 recordings.
`recorded_versions.json` SHALL list both. The rows of L4-OCV-013 that no live run recorded SHALL keep their named
fallbacks.

#### Scenario: SCN-OCV-43 (+) The pin is 2.2.6 and the recordings are compared within the major
- **GIVEN** the catalog, `prereqs.sh` and the packaged `recorded_versions.json`
- **WHEN** they are read, and LIVE-005 runs with `opencode2` printing `opencode v2.2.6` and then `opencode v2.2.7`
- **THEN** `OPENCODE2_VERSION` is `2.2.6`, and the install command and `prereqs.sh` name `@opencode/cli@2.2.6`
- **AND** `recorded_versions.json` lists `2.0.32` and `2.2.6` under `opencode`
- **AND** `2.2.6` gives no warning, and `2.2.7` warns `unrecorded version`, naming `2.0.32, 2.2.6`

#### Scenario: SCN-OCV-26 (−) The v2 adapter is not announced as experimental
- **GIVEN** a role chain whose selected profile is `cli_major: 2`, and a `cli_major: 1` profile whose `opencode`
  prints `opencode v2.2.6`
- **WHEN** the first is selected twice in one run, and the second is probed
- **THEN** no `agent.experimental` event is recorded
- **AND** the second fails `binary` with a reason ending `or set options.cli_major: 2 to run OpenCode 2`

## MODIFIED Requirements

### Requirement: L4-OCV-002 (amendment) The pin moves to 2.2.6
The harness SHALL pin `@opencode/cli` at `OPENCODE2_VERSION`, which SHALL be `2.2.6` (L4-OCV-019). The install, the
link, PRQ-20 and `ci.cli_versions` are otherwise unchanged.

#### Scenario: SCN-OCV-04 (+) Both majors live side by side
- **GIVEN** role chains with a `cli_major: 1` and a `cli_major: 2` opencode profile, and neither CLI installed
- **WHEN** `l4 doctor --fix` runs
- **THEN** `opencode-ai@1.18.34` is in `$L4_HOME/npm` and `@opencode/cli@2.2.6` is in `$L4_HOME/npm-opencode2`
- **AND** on the harness path `opencode --version` is `1.18.34`, and `opencode2 --version` is `opencode v2.2.6`

#### Scenario: SCN-OCV-02 (−) A v2 profile with only v1 installed fails at binary by name
- **GIVEN** a `cli_major: 2` profile, an `opencode` that prints `1.18.34`, and an `opencode2` that prints `1.18.34`
- **WHEN** the profile is probed
- **THEN** the `binary` step fails with `… install @opencode/cli@2.2.6 (l4 doctor --fix installs it user-locally) or
  remove options.cli_major`, and no `auth`, `quota` or `hello` step runs

### Requirement: L4-OCV-003 (amendment) The data home is redirected only for a profile that needs no stored login
`XDG_DATA_HOME` SHALL NOT be redirected for a profile with a stored login. For a profile of L4-OCV-017 it SHALL be that
profile's private data home.

#### Scenario: SCN-OCV-06 (+) Each v2 argv carries --standalone and a private state directory
- **GIVEN** a `cli_major: 2` profile with a stored login, and one that needs none
- **WHEN** the run, the hello, the auth step and the export are built
- **THEN** each argv holds `--standalone` right after its subcommand words, and each environment's `XDG_STATE_HOME` is
  a directory of that call alone
- **AND** for the first, no call sets `XDG_DATA_HOME`
- **AND** for the second, the run and the export share one private data home, and the hello has its own

### Requirement: L4-OCV-005 (amendment) The implement rules gain a refuse-all and the CLI denies
The implement-mode rules SHALL be preceded by `*:* <refuse>` (L4-OCV-015). They SHALL hold the OpenCode CLI denies after
the git denies wherever `shell` is allowed (L4-OCV-016). A v2 deny drops the tool from the request [V, 2.2.6]: the
fallback `tools_by_permission` is now recorded behaviour.

#### Scenario: SCN-OCV-09 (+) The native rules equal the recorded normalisation of today's rules
- **GIVEN** the recorded v2 normalisation of the implement, judge-paid and judge-free configurations
- **WHEN** the v2 configuration of each mode is built for the same result directory
- **THEN** the judge `permissions` equal the recorded arrays, with the `list` and `doom_loop` rules and repeated
  identical rules removed
- **AND** the implement `permissions` are that recorded array, with `*:* deny` before it, the three OpenCode CLI denies
  after its git denies, and the `skill` and `subagent` rules at its end

#### Scenario: SCN-OCV-45 (+) The recorded tools-permission run had no shell tool
- **GIVEN** `live-tools-permission` (`options.tools: [read, edit]`, a prompt asking for `ls -la`) with its export and
  its result file
- **WHEN** it is parsed as an implementer step
- **THEN** it is `ok` with no denial and no `tool_use` of `shell`: the denied tool was not offered

### Requirement: L4-OCV-006 (amendment) A bounded run's outcome is recorded
A run at its step bound SHALL stay not `ok`, whatever the export says. A recorded bounded run exported `succeeded` [V,
2.2.6], so the bound rule SHALL decide before the export.

#### Scenario: SCN-OCV-44 (+) The recorded bounded judge is a step_bound error though its export says succeeded
- **GIVEN** `live-bounded` (bound 2: a `skill` call that ended `Unable to load skill read`, then the forced summary),
  with its export (`outcome: succeeded`)
- **WHEN** it is parsed as a judge with bound 2
- **THEN** the status is `error` with the detail `step_bound: opencode2 stopped at agents.build.steps 2`
- **AND** the `skill` call is not a denial

### Requirement: L4-OCV-007 (amendment) The export decides a run that lost its final stop
When a v2 run has no final `step_finish` of reason `stop`, the exported outcome SHALL decide. On 2.2.6, 22 of 23
finished runs ended with a final stop. The one that did not was disturbed by its own shell starting the OpenCode CLI
[V].

#### Scenario: SCN-OCV-36 (−) The recorded run the CLI disturbed is decided by its export
- **GIVEN** `live-cli-disturbed`, whose last `step_finish` has reason `tool-calls` and is followed by a `step_start`,
  with its export (`succeeded`, one `synthetic` message) and its result file
- **WHEN** it is parsed with the export, and again with the export unavailable
- **THEN** the first is `ok`
- **AND** the second is `error` `opencode2 session export failed (no export) and the stream has no final stop`

### Requirement: L4-OCV-008 (amendment) A multi-step export's layout is recorded
v2 usage SHALL be summed over the export's assistant messages. A multi-step export holds one assistant message per
finished step, and their sum equals `info.tokens` [V, 23 exports of 1 to 23 steps].

#### Scenario: SCN-OCV-46 (+) A recorded multi-step export sums to info.tokens
- **GIVEN** `live-implement.export.json` (four assistant messages) and `live-cli-disturbed.export.json` (four assistant
  messages and one `synthetic` message)
- **WHEN** `usage_from_export` reads each
- **THEN** the sums equal `info.tokens` (2773, 278, 7936 and 3722, 1039, 15616)
- **AND** the context peak is the largest per-message `input + cache.read + cache.write` (2851 and 5155)

### Requirement: L4-OCV-009 (amendment) A status-less v2 error is classed by its words
A v2 `error` event without `status` SHALL be classed as today: `auth` by the auth wording, retryable by the server-side
words, else a named `error`.

#### Scenario: SCN-OCV-47 (−) The recorded no-route error is a retryable error, whatever the export says
- **GIVEN** `live-error-no-route` (exit 1, one `error` event `provider.no-route` with no `status`) and its export
  (`outcome: failed`)
- **WHEN** it is parsed as a judge
- **THEN** the status is `error` with the detail `opencode2 reported an error (provider.no-route), retryable`
- **AND** it is marked transient, and no limit is set

### Requirement: L4-OCV-013 (amendment) The recorded rows are [V] and the open rows are known fallbacks
Each [U] row SHALL keep its named fallback and its pin test. A row that a live run recorded SHALL be marked [V] with its
`live-` fixture. The adapter's support SHALL NOT wait for the open rows (L4-OCV-019): U1, U3, U4, U6 and U10, and U8 for
a profile with a stored login.

#### Scenario: SCN-OCV-48 (+) The SPEC and the runbook name each fallback that stays
- **GIVEN** L4-OCV-013 in `docs/SPEC.md` and runbook section 10.9
- **WHEN** they are read
- **THEN** rows U2, U5, U7, U9 and U11 are marked [V] with a `live-` fixture, and rows U1, U3, U4, U6 and U10 keep [U]
  and their fallback's name
- **AND** U8 applies to a profile with a stored login only, and neither text calls the adapter experimental
