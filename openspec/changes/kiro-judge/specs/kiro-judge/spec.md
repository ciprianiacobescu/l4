## Purpose

kiro-cli answers as a judge, a clarifier and a readiness reviewer: tool-less, with the prompt on stdin and a validated
JSON reply, its credits recorded, its vendor taken from its model, and its failures read for what they are.

## ADDED Requirements

### Requirement: L4-KJD-001 A Kiro judge runs a tool-less harness agent with no trust flag
In judge mode (`PermissionPolicy("judge")`) the kiro-cli adapter SHALL write, before each call, a fresh `KIRO_HOME` at
`<step private dir>/kiro-home` that holds only `agents/l4-judge-<12 hex>.json` and `settings/cli.json`. The agent file
SHALL have `tools: []`, `allowedTools: []`, `toolAliases: {}`, `mcpServers: {}`, `includeMcpJson: false`,
`resources: []`, `hooks: {}`, `toolsSettings: {}`, `prompt: null` and `model` equal to the profile's model. The
settings file SHALL be `{"chat.disableInheritingDefaultResources": true, "chat.agentEngine": "v2",
"chat.enableAutoAgentUpgrade": false, "app.disableAutoupdates": true}`. The argv SHALL be exactly
`kiro-cli chat --no-interactive --v2 --agent <name> --model <model> --output-format stream-json`: it SHALL NOT carry
`--trust-tools` with any value, `--trust-all-tools` or the prompt. The judge SHALL run this agent whatever
`options.agent` says, in the empty `judge-cwd`, with `KIRO_HOME` set and `KIRO_LOG_LEVEL` unset. A judge-mode request
whose profile has no model SHALL be refused before the spawn. No permission-policy table SHALL hold a trust list for
the judge.

#### Scenario: SCN-KJD-01 (+) The judge argv names the harness agent and no trust flag
- **GIVEN** a profile `{adapter: kiro-cli, model: claude-sonnet-4.5, vendor: anthropic}` and a judge-mode request
- **WHEN** the adapter runs it with a recording process runner
- **THEN** the argv after the executable is `chat --no-interactive --v2 --agent l4-judge-<12 hex> --model
  claude-sonnet-4.5 --output-format stream-json`
- **AND** no argv entry starts with `--trust-tools` or equals `--trust-all-tools`, and the prompt is not in the argv

#### Scenario: SCN-KJD-02 (+) The private KIRO_HOME holds only the judge agent and the settings
- **GIVEN** two judge calls of one step, and a leftover file `kiro-home/agents/old.json` from an earlier call
- **WHEN** each call is made
- **THEN** `kiro-home` holds exactly `agents/<name>.json` and `settings/cli.json` with the fields of this requirement,
  the leftover is gone, the two names differ, and the env's `KIRO_HOME` is that directory

#### Scenario: SCN-KJD-03 (−) A configured agent is ignored and a model-less judge is refused
- **GIVEN** a judge profile with `options: {agent: my-agent}`, and another judge profile with no `model`
- **WHEN** a judge call is made for each
- **THEN** the first runs `--agent l4-judge-<hex>` (never `my-agent`)
- **AND** the second raises an adapter error naming the missing model, and no process is started

### Requirement: L4-KJD-002 A Kiro judge gets its prompt on stdin
A judge-mode kiro-cli call SHALL pass the whole prompt on standard input followed by EOF, with no positional argument,
and SHALL NOT apply the one-argument size limit to it. An empty prompt SHALL be refused before the spawn. The
implementer and read-only modes SHALL keep their argv transport.

#### Scenario: SCN-KJD-04 (+) A large judge prompt goes on stdin
- **GIVEN** a judge-mode request whose prompt has 150,000 bytes
- **WHEN** the adapter runs it with a recording process runner
- **THEN** the runner's `stdin` is the prompt, no argv entry holds it, no adapter error is raised, and the working
  directory is the empty `judge-cwd`

#### Scenario: SCN-KJD-05 (−) The implementer keeps the argv transport
- **GIVEN** an implement-mode request with a prompt of 200,000 bytes, and one with a prompt of 10 bytes
- **WHEN** each is run
- **THEN** the first is refused as too large for one argument, and the second has the prompt as the last argv entry
  and `stdin` None, as before

### Requirement: L4-KJD-003 A Kiro judge's reply is a validated JSON object from the stream
For a judge-mode run that exits 0 with `runFinished.status` `success`, the adapter SHALL take the reply text from
`runFinished.finalText`, or from the joined `agent_message_chunk` text when `finalTextTruncated` is true, slice it from
the first `{` to the last `}`, parse and validate it against the request's schema with the helper the opencode judge
uses. A valid object SHALL be the run's `structured` result with status `ok`. A missing or invalid object SHALL give a
detail that starts with the structured-output marker (with the rejected object kept for the repair), so that the judge
takes its deterministic repair and then at most one repair call; a stop reason other than `end_turn` SHALL be named in
that detail. A judge run that holds a `tool_call` update, that ran an engine other than `v2`, or whose session file
`<KIRO_HOME>/sessions/cli/<sessionId>.json` names a `model_id` other than the profile's model SHALL end as `error`
and SHALL NOT give a verdict; a missing or unreadable session file SHALL block nothing. The adapter SHALL NOT report a
served model for a Kiro run.

#### Scenario: SCN-KJD-06 (+) A reply with a sentence before the JSON is the verdict
- **GIVEN** the fixture `kiro-cli/2.32.0/judge-pass.stream.jsonl`, whose final text is `Here is my verdict:` and a
  valid judge-verdict object
- **WHEN** a judge call is parsed with the judge schema
- **THEN** the status is `ok`, `structured` is that object, `model_resolved` is None and the credits are 0.0512

#### Scenario: SCN-KJD-07 (−) A reply with no JSON object gets one repair call
- **GIVEN** a judge whose first stream ends `runFinished{status: success, stopReason: max_tokens, finalText:
  "I think criterion 1 passes"}` and whose second stream holds a valid verdict
- **WHEN** `run_judge` runs
- **THEN** the first result is `schema_invalid` whose detail names `max_tokens`, a second call is made with the repair
  prompt, and the verdict is the second reply's with `reply: retried`

#### Scenario: SCN-KJD-08 (+) A truncated final text falls back to the message chunks
- **GIVEN** a stream whose `agent_message_chunk` texts join to a valid verdict and whose `runFinished` has
  `finalTextTruncated: true` and a cut `finalText`
- **WHEN** it is parsed as a judge run
- **THEN** the status is `ok` and `structured` is the joined object

#### Scenario: SCN-KJD-09 (−) A tool call, another engine or another selected model is never a verdict
- **GIVEN** in turn: a judge stream with a `tool_call` update for `read` before a valid verdict; a stream whose
  `runStarted.engine` is `v3`; a valid stream whose session file names `model_id` `claude-haiku-4.5` for a profile on
  `claude-sonnet-4.5`
- **WHEN** each is parsed as a judge run
- **THEN** each status is `error` with the detail `kiro-cli judge called a tool (read)`, `kiro-cli ran engine v3; a
  judge runs v2` and `model_mismatch: kiro-cli selected claude-haiku-4.5, the profile names claude-sonnet-4.5`, and
  none has `structured`
- **AND** the same valid stream with no session file is `ok`

#### Scenario: SCN-KJD-10 (+) The opencode judge reply is unchanged
- **GIVEN** the opencode judge tests of 0.4.18 (a fenced object, prose around it, no object, an invalid object)
- **WHEN** they run against the shared helper
- **THEN** each status, detail and `rejected` value is what it was

### Requirement: L4-KJD-004 The credits of a Kiro judge or clarifier call are recorded, never as dollars
When a judge call's usage carries credits, the verifier SHALL add `credits` to its `verify.judge` event and SHALL write
`budget.cost{credits, credits_source: "kiro.stream", profile, role: "judge"}`; the clarifier SHALL write the same event
with `role: "clarifier"`. Credits SHALL NOT be added to any dollar total.

#### Scenario: SCN-KJD-11 (+) The judge's credits are on the verify and budget events
- **GIVEN** a step-9 round whose kiro-cli judge answers in two calls metering 0.05 and 0.02 credits
- **WHEN** the round ends
- **THEN** `verify.judge` has `credits: 0.07`, one `budget.cost` has `credits: 0.07`, `credits_source: kiro.stream`,
  `role: judge`, no `budget.cost` of the judge has `usd`, and the unit's folded `cost_usd` is unchanged

#### Scenario: SCN-KJD-12 (+) The clarifier's credits are recorded
- **GIVEN** a clarifier pass whose kiro-cli profile answers one question metering 0.03 credits
- **WHEN** the pass ends
- **THEN** the ledger has `budget.cost{credits: 0.03, credits_source: kiro.stream, role: clarifier}` and no `usd` for it

### Requirement: L4-KJD-005 A kiro-cli profile's vendor is its model's family
The vendor of a kiro-cli profile SHALL be the vendor of its model's family (`claude-` anthropic, `gpt-` and
`o<digit>` openai, `gemini-` google, `deepseek-` deepseek, `glm-` zhipu, `minimax-` minimax, `qwen` alibaba, `kimi-`
moonshot), with provenance `declared`; a model of no known family SHALL keep the declared vendor; no model or `auto`
SHALL be vendor `unknown`, whatever `vendor:` says. A kiro-cli profile whose `vendor:` contradicts its model's family
SHALL fail to load, naming the family's vendor. Under `verifier.independence: different_model`, models SHALL be
compared after normalisation that also folds a `.` between digits to `-`.

#### Scenario: SCN-KJD-13 (−) A Kiro judge on a Claude model is not independent of a Claude Code implementer
- **GIVEN** `roles.judges: [kiro-judge]` with `{adapter: kiro-cli, model: claude-sonnet-4.5, vendor: anthropic}` and a
  unit implemented by a claude-code profile
- **WHEN** a judge is selected
- **THEN** `kiro-judge` is vetoed (`share the vendor`), and with no other judge the unit waits with `no independent
  verifier`, and no judge is called

#### Scenario: SCN-KJD-14 (+) A Kiro judge on Claude is independent of a Kiro implementer on Qwen
- **GIVEN** the same judge and a unit implemented by `{adapter: kiro-cli, model: qwen3-coder-next}` with no `vendor:`
- **WHEN** a judge is selected and the round's independence is assessed
- **THEN** `kiro-judge` is selected, and the line reads `independence: declared (unverified): kiro-judge anthropic
  (declared), <implementer> alibaba (declared)`

#### Scenario: SCN-KJD-15 (−) A vendor that contradicts the model does not load
- **GIVEN** a profile `{adapter: kiro-cli, model: claude-sonnet-4.5, vendor: amazon}`
- **WHEN** the configuration is loaded
- **THEN** loading fails with `vendor contradicts the model: claude-sonnet-4.5 is made by anthropic`
- **AND** `{adapter: kiro-cli, model: glm-5, vendor: zhipu}` and `{adapter: kiro-cli, model: some-new-model, vendor:
  acme}` load, the latter with vendor `acme` (declared)

#### Scenario: SCN-KJD-16 (−) No model or auto is vendor unknown
- **GIVEN** kiro-cli profiles with `vendor: zhipu` and no model, and with `model: auto`
- **WHEN** their vendor is resolved
- **THEN** both are `unknown`, never independent of anything

#### Scenario: SCN-KJD-17 (−) Dotted and dashed model ids are one model
- **GIVEN** `verifier.independence: different_model`, a kiro judge on `claude-sonnet-4.5` and a claude-code implementer
  on `claude-sonnet-4-5-20250929`
- **WHEN** a judge is selected
- **THEN** the kiro judge is vetoed as sharing the model

### Requirement: L4-KJD-006 Kiro authentication, configuration and quota failures are classified
A kiro-cli run SHALL end with status `auth` when a `runError` message says the bearer token is invalid, the token is
invalid or expired, access is denied, or the user is not logged in, or when it exits 1 with no stream event and its
output says that it needs authentication or `kiro-cli login`. An exit 4 or a `runError` at stage `init` or `input`
SHALL be `error` with the stage in the detail. Throttling and used-up credits SHALL keep their rules and come first. A
`/usage` answer that says the usage could not be retrieved for an authentication reason SHALL fail the quota step as an
auth failure, not as an unrecognised text.

#### Scenario: SCN-KJD-18 (−) An invalid key is an auth failure and the next judge answers
- **GIVEN** `roles.judges: [kiro-judge, oc-judge]`, both independent, and `kiro-judge` replaying
  `kiro-cli/2.32.0/auth-invalid-key.stream.jsonl` with exit 1
- **WHEN** step 9 runs
- **THEN** the kiro run's status is `auth`, `kiro-judge` cools with kind `auth`, `availability.fallback` names
  `oc-judge`, and the verdict is `oc-judge`'s

#### Scenario: SCN-KJD-19 (−) No login is an auth failure
- **GIVEN** the fixture `no-login` (stdout the spinner, stderr naming `kiro-cli login --use-device-flow`, exit 1)
- **WHEN** it is parsed as a judge run
- **THEN** the status is `auth`

#### Scenario: SCN-KJD-20 (−) A missing agent or missing input is an error with its stage
- **GIVEN** the 2.28.0 fixture `missing-agent.stream.jsonl` with exit 4, and `kiro-cli/2.32.0/input-missing.stream.jsonl`
  with exit 1
- **WHEN** each is parsed as a judge run
- **THEN** both are `error`, with `init` and `input` in their details, and neither is `auth`

#### Scenario: SCN-KJD-21 (−) An invalid token on /usage fails the quota step as auth
- **GIVEN** `/usage` answering exit 0 with `kiro-cli/2.32.0/usage-invalid-key.stdout.txt`
- **WHEN** the quota probe runs
- **THEN** the step fails with `failure_class` `auth` and the reason `kiro-cli usage: authentication failed`, not
  `quota_unrecognised`

### Requirement: L4-KJD-007 The hello of a kiro-cli profile runs the judge invocation
The hello probe of every kiro-cli profile SHALL run the tool-less harness agent of L4-KJD-001 from a private
`KIRO_HOME` in a temporary directory, with the argv of L4-KJD-001 followed by the hello prompt as its last argument
and an empty working directory, and SHALL read the reply text of L4-KJD-003. A profile with no model SHALL run it with `model: null` and no `--model`. Its failures
SHALL be classified by L4-KJD-006.

#### Scenario: SCN-KJD-22 (+) The hello runs the judge invocation
- **GIVEN** a kiro-cli profile on `glm-5` and a probe runner that answers the 2.28.0 `hello.stream.jsonl`
- **WHEN** the hello step runs
- **THEN** it passes, the argv is the judge argv followed by the hello prompt, with no trust flag, the working
  directory was empty, and the env's `KIRO_HOME` held only the judge agent and the settings

#### Scenario: SCN-KJD-23 (−) A hello with an invalid key is an auth failure
- **GIVEN** the probe runner answering `auth-invalid-key.stream.jsonl` with exit 1
- **WHEN** the hello step runs
- **THEN** it fails with `failure_class` `auth`

### Requirement: L4-KJD-008 kiro-cli serves the roles that use the tool-less judge contract
kiro-cli SHALL be one of the adapters that serve `roles.judges` (step 9 and the plan-readiness review),
`roles.clarifier`, the `s1_judge` stand-in, the escalation keeper and the step-9 preflight. The delegate role SHALL
NOT serve kiro-cli.

#### Scenario: SCN-KJD-24 (+) A kiro-cli profile answers the clarifier and the readiness review
- **GIVEN** `roles.clarifier: [kiro-clar]` and `roles.judges: [kiro-judge]` with kiro-cli profiles replaying valid
  replies
- **WHEN** a clarifier pass and a plan-readiness review run
- **THEN** both select the kiro-cli profile and use its validated reply

#### Scenario: SCN-KJD-25 (−) The delegate does not take a kiro-cli profile
- **GIVEN** a base with the delegate role (0.4.19) and `roles.delegate: [kiro-x, opus]` with `kiro-x` a kiro-cli
  profile
- **WHEN** the delegate is selected
- **THEN** `kiro-x` is skipped as an adapter that does not serve the role and `opus` is selected, and the delegate's
  adapter list is unchanged by this change

### Requirement: L4-KJD-009 Doctor checks Kiro judge profiles
Doctor CFG-011 SHALL fail (error) for a kiro-cli profile in `roles.judges` with no model or `model: auto`, naming the
profile and `kiro-cli chat --list-models`. It SHALL warn for a kiro-cli profile in `roles.judges` or
`roles.clarifier` that sets `options.agent`, or whose `min_version` is unset or below `2.32.0`. A pass SHALL name each
such profile with its model and vendor and say that it runs a tool-less harness agent with the prompt on stdin and no
trust flag.

#### Scenario: SCN-KJD-26 (−) CFG-011 fails a model-less judge and warns on the agent and the version
- **GIVEN** judge profiles `{adapter: kiro-cli, vendor: zhipu}` and `{adapter: kiro-cli, model: glm-5, options:
  {agent: mine}}`, and a clarifier profile `{adapter: kiro-cli, model: glm-5, min_version: "2.28.0"}`
- **WHEN** `l4 doctor` runs
- **THEN** CFG-011 fails with the first profile's missing model, and lists warnings for `options.agent` and for the
  version below 2.32.0
- **AND** with the first profile given `model: glm-5` and the others fixed, CFG-011 passes naming `glm-5 (zhipu)`

### Requirement: L4-KJD-010 Kiro judge behaviour is pinned by recorded fixtures and a replay scenario
The harness SHALL keep the kiro-cli 2.32.0 shapes of this change under `tests/fixtures/recorded/kiro-cli/2.32.0/`,
with a README that says how each was made and which one is synthetic until the live run replaces it. The simulation
SHALL be able to replay a judge's stream through the real kiro-cli adapter, and the scenario `happy-kiro-judge` SHALL
pass.

#### Scenario: SCN-KJD-27 (+) The simulation replays a Kiro judge through the real adapter
- **GIVEN** the scenario `happy-kiro-judge` (the `happy-kiro` unit, its judge replaying `judge-pass.stream.jsonl`
  through `KiroCliAdapter`)
- **WHEN** `l4 simulate happy-kiro-judge` runs
- **THEN** it exits 0 with `verify.verdict PASS`, `verify.judge` with the judge profile and `credits`, `budget.cost`
  with `role: judge`, and `availability.model_unverified` for the judge
- **AND** the replayed call's argv and stdin are those of L4-KJD-001 and L4-KJD-002

### Requirement: L4-KJD-011 A Kiro judge is proven live on the owner's dummy repository
The change SHALL be proven in CI on the owner's dummy repository, never on a consumer: a unit whose implementer is not
an Anthropic model reaches a verdict from a kiro-cli judge on `claude-sonnet-4.5`, and the evidence under
`docs/live/kiro-judge/` SHALL hold the redacted judge stream, the `verify.judge` and `budget.cost` events, the
independence line, the CLI version and the answers to the open kiro-cli questions of the design. The recorded judge
stream SHALL replace the synthetic fixture.

#### Scenario: SCN-KJD-28 (+) A CI run reaches a verdict from a Kiro judge
- **GIVEN** the owner's dummy repository with the `KIRO_API_KEY` secret, `roles.judges: [kiro-judge]` and a
  non-Anthropic implementer, and `l4 doctor --live` passing CFG-011 and LIVE-001
- **WHEN** the CI job runs the unit to verification
- **THEN** the round has a verdict from `kiro-judge`, `verify.judge` with `credits`, `budget.cost{role: judge}`, and
  the independence line `declared (unverified)` naming `kiro-judge anthropic (declared)`

#### Scenario: SCN-KJD-29 (−) A Claude implementer leaves the Kiro Claude judge unused
- **GIVEN** the same repository with a claude-code implementer and `roles.judges: [kiro-judge]` only
- **WHEN** the unit reaches verification
- **THEN** it waits with `no independent verifier` and the ledger has no `verify.judge` event
