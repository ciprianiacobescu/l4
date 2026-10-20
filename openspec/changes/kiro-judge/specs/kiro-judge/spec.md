## Purpose

kiro-cli answers as a judge, a clarifier and a readiness reviewer: tool-less, with the prompt on stdin and a validated
JSON reply, its credits recorded, its vendor taken from its model, and its failures read for what they are. By
default it runs Kiro's `auto` model, whose possible vendors are the makers of the models Kiro may route it to.

## ADDED Requirements

### Requirement: L4-KJD-001 A Kiro judge runs a tool-less harness agent with no trust flag
In judge mode (`PermissionPolicy("judge")`) the kiro-cli adapter SHALL write, before each call, a fresh `KIRO_HOME` at
`<step private dir>/kiro-home` that holds only `agents/l4-judge-<12 hex>.json` and `settings/cli.json`. The agent file
SHALL have `tools: []`, `allowedTools: []`, `toolAliases: {}`, `mcpServers: {}`, `includeMcpJson: false`,
`resources: []`, `hooks: {}`, `toolsSettings: {}`, `prompt: null` and `model` equal to the profile's model, or `auto`
when the profile has none (L4-KJD-012). The settings file SHALL be `{"chat.disableInheritingDefaultResources": true,
"chat.agentEngine": "v2", "chat.enableAutoAgentUpgrade": false, "app.disableAutoupdates": true}`. The argv SHALL be
exactly `kiro-cli chat --no-interactive --v2 --agent <name> --model <model> --output-format stream-json`, where
`<model>` is the agent file's `model`: it SHALL NOT carry `--trust-tools` with any value, `--trust-all-tools` or the
prompt. The judge SHALL run this agent whatever `options.agent` says, in the empty `judge-cwd`, with `KIRO_HOME` set and
`KIRO_LOG_LEVEL` unset. No permission-policy table SHALL hold a trust list for the judge.

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

#### Scenario: SCN-KJD-03 (−) A configured agent is ignored and a model-less judge runs auto
- **GIVEN** a judge profile with `options: {agent: my-agent}`, and another judge profile with no `model`
- **WHEN** a judge call is made for each
- **THEN** the first runs `--agent l4-judge-<hex>` (never `my-agent`)
- **AND** the second raises no adapter error, its argv holds `--model auto`, and its agent file's `model` is `auto`

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
that detail. A judge run that holds a `tool_call` update, that has a `runStarted` whose engine is not `v2` (every
`runStarted` counts, and one that names no engine is not `v2`), that holds a `runError`, or whose served model
contradicts a pinned model (L4-KJD-015) SHALL end as `error` and SHALL NOT give a verdict.

#### Scenario: SCN-KJD-06 (+) A reply with a sentence before the JSON is the verdict
- **GIVEN** the fixture `kiro-cli/2.32.0/judge-pass.stream.jsonl`, whose final text is `Here is my verdict:` and a
  valid judge-verdict object
- **WHEN** a judge call is parsed with the judge schema and no session file
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
  `runStarted.engine` is `v3`; a valid stream whose session file names `model_id` `claude-haiku-4.5` for a profile
  pinned to `claude-sonnet-4.5`
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
The vendor of a kiro-cli profile with a pinned model SHALL be the vendor of its model's family (`claude-` anthropic,
`gpt-` and `o<digit>` openai, `gemini-` google, `deepseek-` deepseek, `glm-` zhipu, `minimax-` minimax, `qwen`
alibaba, `kimi-` moonshot), with provenance `declared`; a model of no known family SHALL keep the declared vendor. A
kiro-cli profile with no model or `auto` SHALL be routed (L4-KJD-014): its vendors SHALL be the possible vendors of
L4-KJD-013 with provenance `routed`, and a `vendor:` on it SHALL be ignored (it loads, and doctor notes that it is
ignored). A kiro-cli profile whose `vendor:` contradicts its pinned model's family SHALL fail to load, naming the
family's vendor; `vendor: unknown` (in any letter case) makes no claim, so it SHALL load and the family's vendor SHALL
count. Under `verifier.independence: different_model`, models SHALL be compared after normalisation that
also folds a `.` between digits to `-`.

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
- **AND** `{adapter: kiro-cli, model: claude-sonnet-4.5, vendor: unknown}` loads with vendor `anthropic` (declared)

#### Scenario: SCN-KJD-16 (−) No model or auto is routed, whatever vendor says
- **GIVEN** kiro-cli profiles with `vendor: zhipu` and no model, and with `model: auto` and `vendor: zhipu`, and no
  recorded model listing
- **WHEN** the configuration is loaded and their vendor is resolved
- **THEN** both load, both have provenance `routed`, and their vendors are the built-in set `anthropic`, `minimax`,
  `zhipu`, not the declared `zhipu` alone

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
and an empty working directory, and SHALL read the reply text of L4-KJD-003. A profile with no model SHALL run it with
`model: auto` in the agent file and `--model auto`. Its failures SHALL be classified by L4-KJD-006.

#### Scenario: SCN-KJD-22 (+) The hello runs the judge invocation
- **GIVEN** a kiro-cli profile on `glm-5`, a kiro-cli profile with no model, and a probe runner that answers the 2.28.0
  `hello.stream.jsonl`
- **WHEN** the hello step runs for each
- **THEN** it passes, the argv is the judge argv followed by the hello prompt, with no trust flag, the working
  directory was empty, and the env's `KIRO_HOME` held only the judge agent and the settings
- **AND** the model-less profile's agent file has `"model": "auto"` and its argv holds `--model auto`

#### Scenario: SCN-KJD-23 (−) A hello with an invalid key is an auth failure
- **GIVEN** the probe runner answering `auth-invalid-key.stream.jsonl` with exit 1
- **WHEN** the hello step runs
- **THEN** it fails with `failure_class` `auth`

### Requirement: L4-KJD-008 kiro-cli serves the roles that use the tool-less judge contract
kiro-cli SHALL be one of the adapters that serve `roles.judges` (step 9 and the plan-readiness review),
`roles.clarifier`, the `s1_judge` stand-in, the escalation keeper and the step-9 preflight: it SHALL be in
`JUDGE_ADAPTERS` (`l4/config/roles.py`), so that the load check of L4-CFG-006 passes a kiro-cli profile in
`roles.judges`, `roles.verifier_agent`, `roles.clarifier` and `roles.s1_judge` (see the modified L4-CFG-006 in
`specs/judge-role-config/`). The delegate role SHALL NOT serve kiro-cli.

#### Scenario: SCN-KJD-24 (+) A kiro-cli profile answers the clarifier and the readiness review
- **GIVEN** `roles.clarifier: [kiro-clar]` and `roles.judges: [kiro-judge]` with kiro-cli profiles replaying valid
  replies, `kiro-clar` with no model (auto)
- **WHEN** a clarifier pass and a plan-readiness review run
- **THEN** both select the kiro-cli profile and use its validated reply

#### Scenario: SCN-KJD-25 (−) The delegate does not take a kiro-cli profile
- **GIVEN** a base with the delegate role (0.4.20) and `roles.delegate: [kiro-x, opus]` with `kiro-x` a kiro-cli
  profile
- **WHEN** the delegate is selected
- **THEN** `kiro-x` is skipped as an adapter that does not serve the role and `opus` is selected, and the delegate's
  adapter list is unchanged by this change

### Requirement: L4-KJD-009 Doctor checks Kiro judge profiles
Doctor CFG-011 SHALL check the kiro-cli profiles of `roles.judges` and `roles.clarifier`. A profile with no model or
`model: auto` SHALL NOT fail the check: its line SHALL name `auto`, its possible vendors and their source (the latest
recorded model listing with its date, or the built-in set), and SHALL say that a pinned model makes the served model
checkable. A pinned profile's line SHALL name its model and vendor. Every line SHALL say that the profile runs a
tool-less harness agent with the prompt on stdin and no trust flag. CFG-011 SHALL warn for such a profile that sets
`options.agent`, or whose `min_version` is unset or below `2.32.0`. For every kiro-cli profile that a role names, a
`vendor:` on a profile with no model or `auto` SHALL be noted in the message as ignored, without failing the check.

#### Scenario: SCN-KJD-26 (−) CFG-011 passes an auto judge and warns on the agent and the version
- **GIVEN** judge profiles `{adapter: kiro-cli, vendor: zhipu}` and `{adapter: kiro-cli, model: glm-5, options:
  {agent: mine}}`, a clarifier profile `{adapter: kiro-cli, model: glm-5, min_version: "2.28.0"}`, and no recorded
  model listing
- **WHEN** `l4 doctor` runs
- **THEN** CFG-011 names the first profile with `auto`, the possible vendors `anthropic, minimax, zhipu` from the
  built-in set, the note that its `vendor: zhipu` is ignored and that a pinned model makes the served model checkable,
  and it is not an error
- **AND** CFG-011 lists warnings for `options.agent` and for the version below 2.32.0
- **AND** with the second and third profiles fixed and `min_version: "2.32.0"` on all three, CFG-011 passes, naming
  `glm-5 (zhipu)` for the pinned ones

### Requirement: L4-KJD-010 Kiro judge behaviour is pinned by recorded fixtures and a replay scenario
The harness SHALL keep the kiro-cli 2.32.0 shapes of this change under `tests/fixtures/recorded/kiro-cli/2.32.0/`,
with a README that says how each was made and which one is synthetic or reconstructed until the live run replaces it.
The simulation SHALL be able to replay a judge's stream through the real kiro-cli adapter, and the scenario
`happy-kiro-judge` SHALL pass.

#### Scenario: SCN-KJD-27 (+) The simulation replays a Kiro judge through the real adapter
- **GIVEN** the scenario `happy-kiro-judge` (the `happy-kiro` unit, its judge a kiro-cli profile with no model
  replaying `judge-pass.stream.jsonl` through `KiroCliAdapter`)
- **WHEN** `l4 simulate happy-kiro-judge` runs
- **THEN** it exits 0 with `verify.verdict PASS`, `verify.judge` with the judge profile and `credits`, `budget.cost`
  with `role: judge`, and `availability.model_unverified` for the judge
- **AND** the replayed call's argv and stdin are those of L4-KJD-001 and L4-KJD-002, with `--model auto`

### Requirement: L4-KJD-011 A Kiro judge is proven live on the owner's dummy repository
The change SHALL be proven in CI on the owner's dummy repository, never on a consumer, with a non-Anthropic implementer
(an opencode-go DeepSeek profile that declares `vendor: deepseek`) in two legs: a kiro-cli judge with no model (`auto`,
the default) and a kiro-cli judge pinned to `claude-sonnet-5.5`. Each leg SHALL reach a verdict from the kiro-cli
judge. The evidence under `docs/live/kiro-judge/` SHALL hold, per leg, the redacted judge stream, the `verify.judge`
and `budget.cost` events, the independence line, the CLI version, the `model_id` of the run's session file, any
fallback notice and any standard-error warning about the model, and the answers to the open kiro-cli questions of the
design, among them whether `chat --list-models --format json` carries a status field. The CI job SHALL NOT run
`kiro-cli whoami` and SHALL NOT print account data. The recorded judge stream SHALL replace the synthetic fixture, and
the recorded listing the reconstructed one.

#### Scenario: SCN-KJD-28 (+) CI runs reach a verdict from an auto and from a pinned Kiro judge
- **GIVEN** the owner's dummy repository with the `KIRO_API_KEY` secret, an opencode-go DeepSeek implementer with
  `vendor: deepseek`, `l4 doctor --live` passing CFG-011 and LIVE-001, and in turn `roles.judges: [kiro-auto]` (no
  model) and `roles.judges: [kiro-sonnet]` (`model: claude-sonnet-5.5`)
- **WHEN** the CI job runs the unit to verification in each leg
- **THEN** each round has a verdict from the kiro-cli judge, `verify.judge` with `credits` and `budget.cost{role:
  judge}`
- **AND** the auto leg's independence line names `kiro-auto routed: <the listed vendors> (auto)`, or `kiro-auto
  <vendor> (served <model>)` with a vendor other than `deepseek` when the session file named a concrete model
- **AND** the pinned leg's line names `kiro-sonnet anthropic`
- **AND** in both legs the `auth` step passed on the credential variable (`auth_method: env`), so `whoami` never ran

#### Scenario: SCN-KJD-29 (−) A Claude implementer leaves the Kiro judges unused
- **GIVEN** the same repository with a claude-code implementer and in turn `roles.judges: [kiro-auto]` and
  `roles.judges: [kiro-sonnet]` only
- **WHEN** the unit reaches verification
- **THEN** it waits with `no independent verifier` in both legs (`anthropic` is among the auto judge's possible
  vendors) and the ledger has no `verify.judge` event

### Requirement: L4-KJD-012 A kiro-cli profile with no model runs auto
A kiro-cli profile with no `model` SHALL run Kiro's `auto` model, passed explicitly as `--model auto`, in every mode:
judge, clarifier, readiness review, hello, implementer and read-only. A `model` that is `auto` in any letter case SHALL
be passed as `auto`. A pinned model SHALL be passed as it is. An implementer step that runs a configured
`options.agent` SHALL also get `--model auto` when its profile has no model.

#### Scenario: SCN-KJD-30 (+) The implementer and the judge run auto by default
- **GIVEN** a profile `{adapter: kiro-cli}` with no model, a profile `{adapter: kiro-cli, model: AUTO, options: {agent:
  mine}}`, and a recording process runner
- **WHEN** an implement-mode and a judge-mode request run for the first, and an implement-mode request for the second
- **THEN** each argv holds `--model auto` exactly once, the judge's agent file has `"model": "auto"`, and the
  implementer prompts are still the last argv entry
- **AND** the second profile's implementer argv holds `--agent mine`

### Requirement: L4-KJD-013 The possible vendors of auto come from Kiro's model list
For a kiro-cli profile on `auto`, the probe's `auth` step SHALL, after the login check passes (also when a credential
variable decides it), list the models once with `kiro-cli chat --list-models --format json` in the profile's probe
environment with a private `KIRO_HOME` (the login stays in the CLI data store) and within the step timeout, and SHALL
record in that step's result, cached with the other probe results, the possible vendors, the
Active model ids and the source `listed`. The possible vendors and the model ids SHALL be the union of the listing's
and the built-in set's, so that a vendor Kiro removed from the Active list, or a restricted listing, never shrinks the
set. A listed model SHALL be Experimental when its `description` contains
`experimental`, `preview` or `excluded model` in any letter case; `auto` SHALL be skipped; every other listed model,
one with no description included, SHALL be Active. The possible vendors SHALL be the makers of the Active models by the
family table of L4-KJD-005; an Active model of no known family SHALL add `unknown`. When the listing fails (a non-zero
exit, a timeout, no JSON object with a `models` list, or no Active model), the `auth` step SHALL still pass and SHALL
record the built-in set (vendors `anthropic`, `minimax` and `zhipu` and the Active ids of the kiro-cli 2.32.0 listing
of 2026-10-19) with the source `built-in` and the reason; `l4 probe` and doctor SHALL say which source counts. A
pinned profile SHALL NOT be listed. The probe SHALL keep nothing of `whoami` but whether a login is present: never the
account e-mail.

#### Scenario: SCN-KJD-31 (+) The possible vendors come from the Active models
- **GIVEN** a kiro-cli profile with no model, a passing login check, and the listing answering exit 0 with
  `kiro-cli/2.32.0/list-models.json`
- **WHEN** the `auth` step runs
- **THEN** it passes and records the vendors `anthropic`, `minimax`, `zhipu` (the listing's, which here equal the
  built-in set), the 12 Active ids from
  `claude-sonnet-5.5` to `glm-5`, none of `auto`, `claude-opus-5.5`, `gpt-5.6-sol`, `deepseek-3.2`, `minimax-m2.1`,
  `qwen3-coder-next` and `kimi-k3`, and the source `listed`
- **AND** the `auth` step of a profile pinned to `glm-5` runs no listing

#### Scenario: SCN-KJD-32 (−) A failed listing uses the built-in set
- **GIVEN** a kiro-cli profile with no model, a passing login check, and the listing answering exit 1 with
  `error: service error` on standard error
- **WHEN** the `auth` step runs
- **THEN** it passes and records the vendors `anthropic`, `minimax`, `zhipu` with the source `built-in` and a reason
  naming the failed listing, and `l4 probe` names the set as built-in
- **AND** the built-in set equals the set computed from `kiro-cli/2.32.0/list-models.json`

#### Scenario: SCN-KJD-33 (−) A listed model of no known family makes auto never independent
- **GIVEN** a listing whose Active models are `glm-5` and `some-new-model`, the latter with no description
- **WHEN** the `auth` step records the set and a judge on `auto` is checked against any implementer
- **THEN** the vendors are `anthropic`, `minimax`, `unknown` and `zhipu` (the union with the built-in set), and the
  judge is vetoed with `has no known vendor`

#### Scenario: SCN-KJD-34 (−) The account e-mail of whoami is never kept
- **GIVEN** a kiro-cli profile with a file login and no credential variable set, and `whoami --format json` answering
  exit 0 with `accountType` `ApiKey` and a non-empty `email` string
- **WHEN** the `auth` step runs and its result is cached and shown
- **THEN** it passes, and neither its result, the cached probe report, the `l4 probe` line nor any ledger event holds
  the key `email` or that string

### Requirement: L4-KJD-014 An auto profile is independent only of vendors Kiro cannot route it to
A kiro-cli profile on `auto` that reports no served model (L4-KJD-015) SHALL have provenance `routed`, and its vendors
SHALL be its possible vendors: those recorded by that profile's latest probe, whatever their age, else the built-in
set. Wherever the independence rule applies (the step-9 judges, `roles.verifier_agent`, the escalation keeper and the
step-9 preflight), a profile that is not routed SHALL have its one vendor, and:
- under `different_vendor`, a judge SHALL be vetoed for a unit when its vendors and any implementer's vendors share a
  vendor, or either holds `unknown`;
- under `different_model`, when the judge or an implementer is routed, the judge SHALL be vetoed when the other
  party's model, normalised and taken after its last `/`, is among the routed party's normalised Active ids, when the
  other party's vendor is unknown, or when both are routed;
- after `select_judge` selects a routed judge, it SHALL check that judge again against the set its own probe recorded,
  and SHALL skip it and select the next judge when that set vetoes it.
When the judge is independent and any party is routed, the independence status SHALL be `routed (unverified)`; with no
routed party, `declared (unverified)` and `verified` keep their meaning. A routed party SHALL read `<profile> routed:
<vendors, sorted, comma-separated> (auto)` in the independence line and SHALL carry its possible vendors in the
independence record. The clarifier, the readiness review and the `s1_judge` stand-in have no implementer to be
independent of and SHALL serve an `auto` profile as any other.

#### Scenario: SCN-KJD-35 (+) An auto judge is selected for a DeepSeek implementer
- **GIVEN** `roles.judges: [kiro-auto]` with `{adapter: kiro-cli}` (no model), no recorded model listing, and a unit
  implemented by `{adapter: opencode, model: opencode-go/deepseek-v4.1-flash, vendor: deepseek}`
- **WHEN** a judge is selected and the round's independence is assessed with no served model
- **THEN** `kiro-auto` is selected, and the line reads `independence: routed (unverified): kiro-auto routed:
  anthropic, minimax, zhipu (auto), <implementer> deepseek (declared)`

#### Scenario: SCN-KJD-36 (−) An auto judge is vetoed for a GLM or a Claude Code implementer
- **GIVEN** the same judge, and in turn a unit implemented by `{adapter: kiro-cli, model: glm-5}` and a unit
  implemented by a claude-code profile
- **WHEN** a judge is selected for each
- **THEN** `kiro-auto` is vetoed as sharing the vendor (`zhipu`, then `anthropic`), and with no other judge the unit
  waits with `no independent verifier`, and no judge is called

#### Scenario: SCN-KJD-37 (−) A listing that grew vetoes the judge after its probe
- **GIVEN** the same judge with no recorded model listing and a unit implemented by the DeepSeek profile, and a probe
  whose listing has `deepseek-3.2` with the description `DeepSeek V3.2` among its Active models
- **WHEN** a judge is selected
- **THEN** the walk passes `kiro-auto` on the built-in set, its probe records `deepseek` among its vendors,
  `select_judge` skips it as not independent and selects the next judge or waits with `no independent verifier`, and
  no `kiro-auto` judge call is made

#### Scenario: SCN-KJD-38 (−) An auto implementer is routed too
- **GIVEN** a unit implemented by `{adapter: kiro-cli}` (no model), no recorded model listing, and `roles.judges:
  [cc-judge, kiro-auto, codex-judge]` (claude-code, kiro-cli with no model, codex)
- **WHEN** a judge is selected
- **THEN** `cc-judge` (`anthropic`) and `kiro-auto` (both routed) are vetoed, `codex-judge` (`openai`) is selected, and
  the line names `<implementer> routed: anthropic, minimax, zhipu (auto)`

#### Scenario: SCN-KJD-39 (−) Under different_model a listed model or an unknown vendor vetoes an auto judge
- **GIVEN** `verifier.independence: different_model`, the auto judge with no recorded model listing, and in turn units
  implemented by `{adapter: opencode, model: openrouter/anthropic/claude-sonnet-4.5, vendor: anthropic}`, by
  `{adapter: opencode, model: opencode-go/deepseek-v4.1-flash}` with no vendor, and by `{adapter: claude-code, model:
  claude-opus-4-1}`
- **WHEN** a judge is selected for each
- **THEN** the first two veto the auto judge (`claude-sonnet-4-5` is an Active id; the vendor is unknown), and the third
  does not (`claude-opus-4-1` is not an Active id)

### Requirement: L4-KJD-015 The served model of a Kiro judge run
The kiro-cli adapter SHALL report the served model (`model_resolved`) of a judge-mode run on `auto` when the run's
session file `<KIRO_HOME>/sessions/cli/<sessionId>.json` (a regular file of at most 1 MiB) names a concrete model id in
`session_state.rts_model_state.model_info.model_id`, that is one that is neither empty nor `auto`; a fallback notice
that names the model that continued SHALL count the same once its shape is recorded. For a profile on `auto`, a reported
model SHALL make the judge's provenance `served` and its vendor the served model's family; a served model whose vendor
is an implementer's, or unknown, SHALL drop the verdict as `model_mismatch`, and the next independent judge SHALL be
asked, as for any judge that reports its served model. For a pinned model, a session file or notice that names another
model (after normalisation), or a standard-error warning that Kiro could not set the requested model, SHALL end the run
as `error` with a detail that starts with `model_mismatch:` and no verdict, and the judge SHALL record it as
`model_mismatch`: the profile SHALL be skipped for the round and cooled as for any model mismatch, and the next
independent judge SHALL be asked. A pinned run with no session file and no such warning SHALL block nothing. For a
pinned model the session file SHALL only detect a mismatch: one that names the pinned model (after normalisation) SHALL
report no served model, and the judge's provenance SHALL stay `declared` (the session file is the CLI's own selection,
an echo of the configuration, not a server report). A session file that is missing, unreadable, larger than 1 MiB or
names no concrete model SHALL report no served model.

#### Scenario: SCN-KJD-40 (−) A served model of the implementer's vendor drops an auto judge's verdict
- **GIVEN** `roles.judges: [kiro-auto, oc-judge]`, a unit implemented by the DeepSeek profile, `kiro-auto` (no model)
  answering a valid verdict whose session file names `model_id` `deepseek-3.2`, and `oc-judge` independent
- **WHEN** step 9 runs
- **THEN** `kiro-auto`'s verdict is dropped as `model_mismatch` (`served deepseek-3.2: vendor deepseek is not
  independent`), `availability.model_mismatch` is written, `oc-judge` is asked, and the verdict is `oc-judge`'s
- **AND** with the session file naming `claude-sonnet-5.5`, `kiro-auto`'s verdict stands and the line names
  `kiro-auto anthropic (served claude-sonnet-5.5)`
- **AND** with the session file naming `auto`, or with none, the verdict stands and the line names `kiro-auto routed:
  anthropic, minimax, zhipu (auto)`

#### Scenario: SCN-KJD-41 (−) A pinned model that Kiro could not set is a model mismatch
- **GIVEN** `roles.judges: [kiro-sonnet, oc-judge]` with `kiro-sonnet` pinned to `claude-sonnet-5.5`, a unit implemented
  by the DeepSeek profile, and `kiro-sonnet` answering a valid verdict with exit 0 and a standard-error line saying
  that the model `claude-sonnet-5.5` could not be set
- **WHEN** step 9 runs
- **THEN** `kiro-sonnet` gives no verdict, its judge status is `model_mismatch`, `availability.model_mismatch` names
  `kiro-sonnet`, the profile cools with kind `model_mismatch`, and the verdict is `oc-judge`'s
- **AND** the same run with an empty standard error and no session file gives `kiro-sonnet`'s verdict
