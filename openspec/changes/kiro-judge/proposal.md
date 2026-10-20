## Why

A project that runs kiro-cli has no way to use it as a judge. `JUDGE_ADAPTERS` is `claude-code`, `codex`, `opencode` and
`fake` (`src/l4/llm/agent_judge.py`), so a `roles.judges` or `roles.clarifier` profile with `adapter: kiro-cli` is
skipped by `Factory.for_role(..., serves=JUDGE_ADAPTERS)`. SPEC 8.3 says so: "`kiro-cli` judge, reader | [U] … (Kiro
judges nothing yet, K13)". A team whose only paid agent subscription is Kiro must still buy a second CLI to get a
verdict, although Kiro serves several vendors' models (Anthropic Claude, OpenAI GPT, DeepSeek, Zhipu GLM, MiniMax,
Qwen, Kimi).

Five things block a safe Kiro judge today:

1. **The judge has no tool-less mode.** `TRUST_TOOLS["judge"]` is `"read"` on the default agent (K4), so the judge
   loads the user's `~/.kiro` (MCP servers, skills, steering, `settings/permissions.yaml`, which auto-approves shell
   commands, C9) and is offered every tool. `--trust-tools=` with an empty list trusted every tool on kiro-cli 2.28.0
   (C7 [V]); on 2.32.0 it parses to a trust set holding the empty name (`allowed_tools: {""}` [V trace]), and whether
   that still trusts everything is unknown. The only safe judge offers the model no tool at all.
2. **The prompt is one argv entry** (`MAX_ARG_BYTES = 100_000`). A step-9 judge prompt runs to about 150 kB (a diff
   part of 120,000 characters plus the spec, the gate report and the schema), which Linux refuses as one argument
   (128 KiB per entry) and which any local user can read in `ps`.
3. **Kiro has no native JSON schema.** The reply must be a prompt contract: a strict JSON reply, sliced and validated,
   with the judge's existing repair round.
4. **Independence is wrong for Kiro.** The served model is never reported, so the profile's declared `vendor:` counts.
   A profile `{adapter: kiro-cli, model: claude-sonnet-4.5, vendor: alibaba}` passes as independent of a Claude Code
   implementer today, although both answers come from a Claude model. A profile with no model (`auto`, Kiro picks)
   counts as its declared vendor, although Kiro may route it to any Active model of the account (Anthropic, MiniMax
   and Zhipu on the 2026-10-19 list). The owner decided on 2026-10-19 that kiro-cli works by default with `auto`, so
   such a profile must be usable, and safe: its independence must rest on every vendor `auto` may reach.
5. **Failures are misread.** An invalid or expired login (`runError` "The bearer token included in the request is
   invalid", HTTP 403 [V 2.32.0]) is an `error` and so a failed judge, not an unavailable profile; a `/usage` answer of
   "Invalid token" is exit 0 and reads as `quota_unrecognised`; a hello runs on the default agent with the user's MCP
   servers (about 2.7 times the cost of a small agent, C11) and passes its prompt as an argument.

kiro-cli 2.32.0 was examined for this change in an isolated home with no login and a fake key (design §2): the CLI
reads a piped prompt whole when no argument is given, a custom agent with `"tools": []` sends no tool specification
with the request, a private `KIRO_HOME` holds the agents, the settings and the sessions, and a setting turns off the
steering, skills and `AGENTS.md` that custom agents otherwise inherit.

## What Changes

- **A tool-less harness agent for every judge call** (L4-KJD-001, D1). A judge-mode run writes a fresh private
  `KIRO_HOME` in the step's private directory holding one agent `l4-judge-<12 hex>` (`tools: []`, `allowedTools: []`,
  `mcpServers: {}`, `includeMcpJson: false`, `resources: []`, `hooks: {}`, `prompt: null`, the profile's `model`) and
  `settings/cli.json` (`chat.disableInheritingDefaultResources: true`, `chat.agentEngine: "v2"`,
  `chat.enableAutoAgentUpgrade: false`, `app.disableAutoupdates: true`). The argv is
  `kiro-cli chat --no-interactive --v2 --agent l4-judge-<hex> --model <M> --output-format stream-json` (`<M>` the
  profile's model or `auto`) with **no trust flag at all** (never `--trust-tools`, never `--trust-all-tools`). The
  judge always runs this agent;
  `options.agent` is ignored for the role. The working directory is the empty `judge-cwd`. `TRUST_TOOLS["judge"]` goes.
- **The prompt goes on stdin** (L4-KJD-002, D2): no argv entry, no 100 kB cap, the prompt then EOF.
- **The reply is a prompt contract read from the stream** (L4-KJD-003, D3). The text of `runFinished` (or the joined
  `agent_message_chunk` text when `finalTextTruncated` is true) is sliced from the first `{` to the last `}` and
  validated by one helper shared with opencode. A missing or invalid object takes the existing path: the deterministic
  `judge_repair`, then one repair call (`run_judge`, `MAX_CALLS = 2`). A judge run that calls a tool, runs another
  engine than `v2`, or whose session file names another model than a pinned profile's is an `error`, never a verdict.
- **Credits are recorded for judge calls** (L4-KJD-004, D4): `verify.judge` gets `credits`, and `budget.cost{credits,
  credits_source: kiro.stream, role: judge|clarifier}` is written; credits never join the dollar total.
- **A kiro-cli profile's vendor comes from its model** (L4-KJD-005, D5). `claude-*` is `anthropic`, `gpt-*` is
  `openai`, `deepseek-*` `deepseek`, `glm-*` `zhipu`, `minimax-*` `minimax`, `qwen*` `alibaba`, `kimi-*` `moonshot`,
  `gemini-*` `google`. A `vendor:` that contradicts the model's family is a configuration error, as for claude-code
  and codex. No model, or `auto`, is routed (L4-KJD-014): its vendors are those `auto` may reach, and its `vendor:` is
  ignored. A model of no known family keeps the declared vendor. Under `different_model`, `claude-sonnet-4.5` and
  `claude-sonnet-4-5` are one model.
- **`auto` by default** (L4-KJD-012, D13): a kiro-cli profile with no model runs `--model auto`, explicitly, in every
  mode (judge, clarifier, readiness, hello, implementer, read-only).
- **The possible vendors of `auto`** (L4-KJD-013, D14): the `auth` probe step of an `auto` profile lists the models
  (`kiro-cli chat --list-models --format json`) once per probe cycle and records the makers of the Active ones (an
  entry whose description says Experimental, preview or Excluded Model is not Active, and Auto does not route to
  those); a failed listing records the built-in set `anthropic`, `minimax`, `zhipu` of the 2026-10-19 list and says
  so. The probe never keeps the account e-mail of `whoami`.
- **Independence of an `auto` profile** (L4-KJD-014, D14): an `auto` judge is vetoed when an implementer's vendor is
  among its possible vendors, or unknown (with a DeepSeek implementer it is selected; with a GLM or a Claude one it is
  not), and symmetrically for an `auto` implementer; a selected `auto` judge is checked again against its own probe's
  listing; the verdict's independence reads `routed (unverified)`, naming the possible vendors.
- **The served model of a Kiro judge** (L4-KJD-015, D15): when the session file names a concrete model, an `auto`
  judge's served model is checked like a Claude Code judge's (a served model of an implementer's vendor drops the
  verdict and the next judge is asked); for a pinned model, another named model or Kiro's warning that it could not
  set the model ends the run as `model_mismatch`.
- **Failures are classified** (L4-KJD-006, D6): an invalid, expired or missing login is `auth` (the next judge, the
  auth cool-down), an agent that is not found (exit 4) or a missing input is a configuration `error`, credits and
  throttling keep their rules, and `/usage` saying "Invalid token" fails the quota probe as `auth`.
- **The hello of a kiro-cli profile runs the judge invocation** (L4-KJD-007, D7): the tool-less agent, an empty
  directory and a private `KIRO_HOME`, so a hello neither loads the user's MCP servers nor costs their context. Its
  25-byte prompt stays an argument: the probe runner has no stdin, and task 11 proves stdin for the judge.
- **kiro-cli joins `JUDGE_ADAPTERS`** (L4-KJD-008, D8). The judges, the plan-readiness review, the clarifier and the
  `s1_judge` stand-in all use the same `AgentJudge` contract, so all of them accept a kiro-cli profile. The delegate
  role (`delegate-answers`, which ships after this change, in 0.4.20 [owner decision 2026-10-19: kiro-judge is 0.4.19,
  before the delegate]) is to stay `claude-code` and `codex` only: it needs a read-only mode with tools, which this
  change does not define for Kiro. Its rebase carries SCN-KJD-25.
- **Doctor CFG-011** (L4-KJD-009, D9): a kiro-cli judge or clarifier profile on `auto` passes, naming its possible
  vendors and their source and saying that a pinned model makes the served model checkable; a `vendor:` on an `auto`
  profile is noted as ignored; a judge or clarifier profile with `options.agent`, or without `min_version` of at least
  2.32.0, is a warning. `LIVE-001` already runs the judges' probe ladder under `--live`: its `auth` step now lists the
  models of an `auto` profile and its hello is the judge invocation.
- **Recorded fixtures and a replay scenario** (L4-KJD-010, D10): `tests/fixtures/recorded/kiro-cli/2.32.0/` with the
  shapes recorded for this change (design §2.4) and a judge run; the simulation gets a judge replayed through the real
  kiro-cli adapter (`happy-kiro-judge`).
- **Live proof** (L4-KJD-011, D11): CI runs on the owner's dummy repository with an opencode-go DeepSeek implementer
  and two kiro-cli judges in turn, `auto` (the default) and `claude-sonnet-5.5`, record the judge streams, the
  credits, the verdicts, the session file's model and the listing; the job never runs `whoami`.
- **Docs** (D12): SPEC 8.1, 8.3 (the adapter row and the guidance table), 10.1, the doctor table, the events, the
  requirements L4-KJD-001..015 with SCN-KJD-01..41, the change table (row 50), the runbook, the skill's adopt and Kiro
  references, and CHANGELOG `## 0.4.19 (unreleased)`.

## Capabilities

### New Capabilities

- `kiro-judge`: kiro-cli as a tool-less judge, clarifier and readiness reviewer: the harness agent, the stdin
  transport, the reply contract, credits, vendor by model family, `auto` by default with its possible vendors and its
  served model, failure classes, the hello, doctor CFG-011, fixtures and the live proof.

### Modified Capabilities

None as delta specs: the SPEC sections named under Docs are edited by the docs task.

## Impact

- Code: `src/l4/agents/kiro_cli.py` (judge mode, hello, classification), `src/l4/agents/contract.py` (the shared reply
  slicer), `src/l4/agents/opencode.py` (uses it), `src/l4/llm/agent_judge.py` (`JUDGE_ADAPTERS`),
  `src/l4/availability/vendor.py`, `src/l4/config/schema.py`, `src/l4/verifier/selection.py` (vendor and model
  rules, the routed rule), `src/l4/agents/factory.py` (the recorded set of an `auto` profile),
  `src/l4/availability/fallback.py` (the `auth` probe text), `src/l4/availability/quota.py` (`/usage` auth text),
  `src/l4/verifier/judge.py`, `src/l4/verifier/ladder.py`, `src/l4/clarifier/backend.py`,
  `src/l4/clarifier/clarifier.py` (credits), `src/l4/doctor/checks_config.py` (CFG-011), `src/l4/sim/` (judge replay).
  No new runtime dependency.
- Behaviour that changes for existing configurations:
  - a kiro-cli profile whose `vendor:` contradicts its pinned model's family no longer loads (exit 3, the message
    names the family's vendor);
  - a kiro-cli profile with no model now runs `--model auto` explicitly in every mode; an implementer with
    `options.agent` and no model no longer gets the model named in that agent file (fix: name it in the profile);
  - a kiro-cli profile with no model or `auto` is routed: its declared `vendor:` is ignored, and it is independent of
    no profile whose vendor `auto` may reach (Anthropic, MiniMax, Zhipu on the 2026-10-19 list), so a unit whose
    implementer and only judge both run `auto` waits with `no independent verifier` (fix: pin one side's model);
  - every kiro-cli hello runs the tool-less harness agent, and the `auth` probe step of an `auto` profile lists the
    models;
  - a Kiro auth failure moves to the next profile instead of counting as a failed attempt.
  The CHANGELOG names each one with its fix.
- Not changed: the prompt transport of the implementer and read-only Kiro invocations (it stays an argument there,
  K18; only `--model auto` is added), the delegate role, and the claude-code, codex and opencode judges (opencode only
  moves its slicer into the shared helper).
