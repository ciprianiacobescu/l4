## Context

The code as of 0.4.58 (`f0bc8a3c`):

- `src/l4/agents/opencode.py` (v1). `run()` builds the child environment as `{**req.env, **isolation_env(config_dir,
  config_content(...))}` and passes it to `wrap_command`, which hands every variable to bubblewrap with `--setenv`
  (`src/l4/sandbox/bwrap.py`). There is no allow-list for variables the adapter sets: `ALLOWED_PASSTHROUGH` in
  `src/l4/sandbox/env.py` filters only what comes from the host. The hello (`_hello_once`) builds its own environment
  with `probe_env(ctx, {**credential_env(...)[1], **isolation_env(...)})`. `config_content` writes a `provider` block
  only for a custom provider (`opencode_provider.provider_config`), whose model entry is `{name, tool_call, limit:
  {context, output}, options?}`.
- `src/l4/agents/opencode_v2.py`. `config_content_v2(policy, result_dir, model, options)` is the one builder of the
  native configuration: `$schema`, `snapshots`, `share`, `update`, `permissions`, `agents.build.steps`. The run, the
  hello and the `auth list` probe step all call it. `options.provider` is refused at load for `cli_major: 2`
  (L4-OCV-001, U3 `provider_refused`), so a v2 configuration never holds a `provider` or `providers` block today.
- Length stops. `parse()` of both adapters sets `RunResult.length_stop` when the last `step_finish` reason is `length`
  and the run is otherwise an `error` (L4-VER-071), with the details `the stream ended without a final stop (last reason:
  length)` (v1), `opencode2 session outcome <value>` and `opencode2 session export failed (<why>) and the stream has no
  final stop` (v2). `tests/unit/agents/test_opencode_length_stop.py` pins those details by equality, on `parse()`.
  Consumers carry `RunResult.detail` as it is: `AgentJudge.complete_structured` (`StructuredResult.detail`), the
  verifier (`JudgeRun.detail`, `batch of <n> criteria at depth <d>: <detail>`), the readiness review
  (`JudgeFailed("judge_error: <detail>")`), the implementer (`the agent step ended with status <status>: <detail>`) and
  `agent.finished{detail}`. No consumer compares a length detail's text; L4-VER-071 reads the field.
- Profile options. `OpencodeOptions` (`src/l4/config/schema.py`, strict, extra keys ignored) holds `provider`, `tools`,
  `reasoning`, `cli_major` and `steps`; `opencode_option_problems(options, model)` adds the cross-field checks and
  `Profile._opencode_options` raises them as one `ValueFree`. `Profile` itself has adapter-agnostic keys
  (`context_window`, `context_budget_tokens`, `max_concurrency`).
- Doctor. `checks_provision._provider_notes` adds one note per custom-provider profile in a role chain to PRV-001's
  message (host reachability); a note never changes the check's status.

What the CLIs do, read in their binaries (the strings of a local 1.18.33 install and of
`@opencode/cli-darwin-arm64` 2.2.6 from the npm cache) [V src]:

- v1: `function yy($, Z = V7) { return Math.min($.limit.output, Z) || Z }` with `V7 = 32000`, called as
  `maxOutputTokens(model, flags.outputTokenMax)`, and `outputTokenMax: G("OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX")`.
  Compaction: `vn(e)` is `input - (cfg.compaction?.reserved ?? min(20000, maxOut))` when the model has a
  `limit.input`, else `context - maxOut`; `vl(e)` compacts when the session's tokens reach `vn(e)`.
- v2: `cV = (e, T, o = 0) => { let a = Math.min(e.output > 0 ? e.output : 32000, 256000); if (T === undefined ||
  e.context <= 0) return a; let s = floor(e.context * (1 - o)) - T.measured - ceil(T.estimated * 1.15); return
  Math.min(a, Math.max(1024, s)) }`, used as `maxTokens: cV(model.limit, inputTokens, 0.01)` for the primary request.
  The config schema's root key is `providers` (`Y(t, Config.Provider)`), a provider's `models` is a record of
  `Config.Model`, and `Config.Model.Limit` is `{context?, input?, output?}`. The loader applies a configured model's
  limit as `A.limit = {...A.limit, ...q.limit}`. A catalog model without an output limit is `limit.output = 0`. v2 reads
  `OPENCODE_DISABLE_PROJECT_CONFIG` (`project: !b(OPENCODE_CONFIG_PROJECT_DISABLE ?? OPENCODE_DISABLE_PROJECT_CONFIG)`).

Not recorded: a v2 run whose configuration holds a `providers` overlay for a built-in provider. That the overlay keeps
the provider's own package, settings and login, keeps the catalog's context and reaches the request as `maxTokens` is
read from the loader's code, not seen in a request [I]. Task 6 records it.

Four facts differ from a first reading of the problem, and the decisions below follow them:

1. On v1 the variable is a ceiling: `min(model.limit.output, Z) || Z` cannot lift a request above a limit the catalog
   knows, and a custom provider's model entry `output` above 32000 is capped at 32000 today. The schema docstring of
   `OpencodeModelLimits` and the comment of the §3.2 example are true only below 32000.
2. v1's compaction reserve is `min(20000, maxOutputTokens)` only for a model with a catalog `limit.input`; without one
   the threshold is `context - maxOutputTokens`, the whole value.
3. v2's native key is `providers` (plural), not v1's `provider`, and a configured `limit.output` replaces the catalog's,
   so on v2 the key can raise a request above a limit the catalog knows.
4. A v2 run reads no configuration of the user's: the rendered `OPENCODE_CONFIG_CONTENT` is the only source, and
   `options.provider` is refused on v2. A "user-set `limit.output`" exists only on v1, as a custom provider's model
   entry (D2, D4).

## Goals / Non-Goals

**Goals:** an operator can lift (or lower) the output limit of an opencode profile's requests on both majors with one
key; a value the provider refuses shows at the hello, not in a lost verdict; a length stop says which key would help.

**Non-Goals:** a default above 32000; reading the model's real maximum from a catalog (`opencode models` reaches the
network on v1, and v2's `models` starts the shared daemon, L4-OCV-003); an output limit for claude-code, codex,
kiro-cli or copilot-cli; per-role limits on one profile; a new event or doctor check id; lifting the v2
`provider_refused` fallback.

## Decisions

### D1. The key: `options.max_output_tokens`, opencode only

`OpencodeOptions` gains `max_output_tokens: int | None = None`. It is the model's output limit for every request the
profile makes, in every role and mode (implementer, judge, clarifier, readiness review, delegate, hello).

- The name is the term the CLIs use (`maxOutputTokens` in both OpenCode majors; Claude Code reads
  `CLAUDE_CODE_MAX_OUTPUT_TOKENS`).
- It lives under `options`, which is adapter-scoped and checked per adapter (`options.steps` is the precedent).
- Alternative: a top-level `Profile.max_output_tokens` beside `context_window`. Rejected: top-level keys are
  adapter-agnostic, so every other adapter would accept it and silently do nothing. A later change that teaches another
  adapter can move it up then.
- Alternative: one limit per role (`options.max_output_tokens: {judge: ..., implement: ...}`). Rejected: the limit is a
  property of the model, and a different limit per role is two profiles.

### D2. The value and its checks

- A whole number from 1024 to 256000. A field validator in `mode="before"` (as `_cli_major_is_an_int` does) refuses
  anything else, a `bool`, a float and a string included, with `ValueFree("must be a whole number from 1024 to 256000")`,
  so the message is `options.max_output_tokens: must be a whole number from 1024 to 256000` and never holds the value.
  256000 is OpenCode 2's own clamp (`KC`); 1024 is its floor when it fits a request to the context (`QC`). A value below
  32000 is allowed: the key also lowers a request (a low-credit OpenRouter key, a model whose real maximum is below
  32000 and that the catalog does not know).
- With `options.provider` (v1 only; v2 refuses it), the key SHALL NOT be above the model entry's `output`:
  `options.max_output_tokens is above the output of the model's entry in options.provider.models (OpenCode asks for the
  smaller): raise the entry's output or lower the key`. OpenCode 1 takes the smaller of the two, so a larger key would be
  a silent no-op; the two numbers say the same thing, and a contradiction is a load error here (the `vendor` checks are
  the precedent). Equal is fine and is how a custom provider's `output` above 32000 takes effect (D3).
- With a custom provider's model entry, the key SHALL also be below the entry's `context` (`options.max_output_tokens
  must be below the context of the model's entry in options.provider.models (the prompt and the reply share the
  window)`): OpenCode 1 compacts at `context - min(output, key)`, so a key at or above the context leaves no room for
  the prompt. The two entry checks are both reported when both fail.
- With the profile's `context_window`, the key SHALL be below it: `options.max_output_tokens must be below
  context_window (the prompt and the reply share the window)`. On OpenCode 1 a key at or above the window makes the
  auto-compaction threshold 0 for a model without a catalog input limit (Context). This check is in
  `Profile._opencode_options` (it reads two fields of the profile), after `opencode_option_problems`.

### D3. Without the key, nothing changes

The default stays OpenCode's: no variable on v1, no `providers` block on v2, and both configurations byte-identical to
0.4.58's. A request then asks for at most 32000 output tokens on v1, and for the catalog's known output limit (else
32000) on v2.

- Why: the model's real maximum is model knowledge L4 does not have, a provider answers a larger maximum with 400, and
  OpenRouter reserves credits for it (402 on a low-credit key). The operator who knows the model sets the key; the hint
  of D6 tells them which key when it matters.
- Alternative: a large default (128000). Rejected: a 400 on every model whose maximum is lower; on v2 it would also
  override a catalog limit that is right today.
- Alternative: on v1, derive the variable from a custom provider's declared `output`. Rejected for this release: it
  changes the request of every existing custom-provider profile whose entry is above 32000, without the operator
  asking. The doctor note of D7 names those profiles, and setting the key equal to the entry's `output` opts in.

### D4. OpenCode 1: the variable

`opencode.py` gains `OUTPUT_TOKEN_ENV = "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX"` and `output_limit_env(options) ->
dict[str, str]`: `{OUTPUT_TOKEN_ENV: str(n)}` when `options` is not None and sets the key, else `{}`. `run()` merges it
into the environment after `isolation_env(...)`, in every mode (implement, judge, read-only); `_hello_once` merges it
into the hello's `probe_env` extra. The `auth` probe step (`opencode auth list`) does not get it (no model call).

- The variable reaches the CLI: the adapter's variables go through `wrap_command` and `--setenv` with no filter. A value
  in the harness's own environment never does: the agent environment is built, not inherited (L4-SEC-001), and
  `probe_env` copies only a fixed list. So the profile is the only source.
- Effect: the request asks for `min(model.limit.output, n)`, or `n` when the catalog does not know the model's limit.
  On v1 the key is a ceiling: above a limit the catalog knows, it changes nothing.
- `config_content` (v1) is unchanged, byte for byte. A custom provider's model entry keeps its `limit {context,
  output}` as before.

### D5. OpenCode 2: the model's `limit.output`

`config_content_v2` appends, when the key is set, `"providers": {<provider>: {"models": {<model id>: {"limit":
{"output": n}}}}}` after `agents`, where `<provider>` is the profile model's part before the first `/` and `<model id>`
everything after it (`openrouter/anthropic/claude-x` gives `openrouter` and `anthropic/claude-x`, as
`provider_config` splits a v1 model). Nothing else goes in the block: no `context`, no `input`, no package, settings or
name, so the catalog's context stays (the loader merges only the limit it is given, Context). Without the key, the configuration is byte-identical to 0.4.58's.

- Effect: the configured `output` replaces the catalog's (`{...catalog.limit, ...config.limit}`), then `cV` clamps it to
  256000 and fits it to the context. On v2 the key is a setter: it can raise a request above a limit the catalog knows,
  and lower it below.
- Precedence. The run reads no other configuration that could set the limit: `XDG_CONFIG_HOME` is an empty directory of
  the step, project configuration is off (v2 reads the switch), `OPENCODE_CONFIG` and `OPENCODE_CONFIG_DIR` are not in
  the built environment, and `options.provider` is refused on v2. So the key wins over the catalog and nothing else
  competes. When a later release lifts `provider_refused` (U3), the load rule of D2 holds for both majors (the key is
  at most the entry's `output`), and the overlay is the entry's own `limit` with `output` set to the key.
- The block is not limit-only [I, from the 2.2.6 binary's strings; not seen in a request]. A provider named in
  `providers` gets `activation="enabled"`. An enabled provider counts as available without a connection, and the model
  resolution can then swap the request's auth when there is no credential or key. A model the catalog does not know is
  created with the defaults `limit {context: 200000, output: 32000}`. A profile with a credential (a stored login,
  `OPENCODE_API_KEY`, the free tier's public key) does not take that branch, so the profiles of the harness are not
  affected; a profile with no credential at all could be (task 6.1 adds a no-credential hello and a stored-login
  profile to the live check).
- The run, its export and the hello get the overlay. The `auth list` step does not: it makes no model call, and what a
  configured provider entry does to the listing (which enumerates providers) is not recorded. It calls
  `config_content_v2` with `options.model_copy(update={"max_output_tokens": None})`, as v1's auth step gets no variable.
- The asymmetry is stated in the docs: v1 takes the smaller of the key and the catalog's limit; v2 takes the key. The 400
  risk is therefore any model on v2, and only a model the catalog does not know on v1.

### D6. The hello carries the limit; the hints name the key

- The hello asks with the same limit on both majors (D4, D5). With a short hello prompt `cV` gives the key itself on v2,
  and v1 asks `min(catalog, n)`. A provider that refuses the value fails the hello, so the profile is unavailable and
  the chain falls back before a long reply is lost.
- `opencode.py` gains `output_limit_hint(result, options, major)`, called by each adapter's `run()` right after
  `parse()` returns (`parse()` stays pure and its details unchanged). When `result.length_stop` is true it appends to
  `result.detail` (`<detail>` is today's text):
  - v1, no key: `<detail>; the reply stopped at its output limit: OpenCode 1 asks for at most 32000 output tokens unless
    options.max_output_tokens is set (up to the model's own maximum)`;
  - v2, no key: `<detail>; the reply stopped at its output limit: OpenCode 2 asks for the model's known output limit,
    else 32000 tokens, unless options.max_output_tokens is set (up to the model's own maximum)`;
  - either major, key `n`: `<detail>; the reply stopped at its output limit (options.max_output_tokens <n>, or less
    when the model or the context allows less)`.
  The no-key texts are conditional on purpose: a stop well below 32000 output tokens is the model's own limit, and the
  key cannot help there.
  With an empty detail the hint stands alone, without the leading `; `.
- When the run's `api_status` is 400 and the key is set, it appends `; options.max_output_tokens is set: a provider
  refuses a maximum output above the model's own (HTTP 400)`. The two hellos append the same clause to their failure
  text for an error event of status 400 when the key is set, unless the message is a custom provider's `grammar binding
  failed` (`_GRAMMAR`), which has its own cause. A 400 without the key is unchanged. A run's `provider_unavailable`
  (grammar or connection) sets no `api_status` and gets no clause.
- Alternative: the hint in `parse()` (it would need the profile, and its details are pinned by equality tests). Alternative:
  the hint at each consumer (the verifier, the readiness review, the delegate, the implementer). Rejected: four places
  for one fact; every consumer already carries `detail` as it is.

### D7. Doctor: one note, no new check

PRV-001's `_provider_notes` adds, for a v1 profile in a role chain whose `options.provider` model entry has an `output`
above 32000 and that has no key: `<profile> asks for at most 32000 output tokens although its model entry allows <output>
(OpenCode 1's default): set options.max_output_tokens to use it`. It is a note: the check's status is unchanged.
Nothing else can be checked without a model call: the model's real maximum is not known to L4, and the hello of D6 is
the live check. A bad value is a load error, which every command, `l4 doctor` included, already reports.

### D8. What is labelled how

| Fact | Label | Where it is pinned |
|---|---|---|
| v1's formula, the variable's name and the compaction threshold | [V src, 1.18.33 and 1.18.34] (the same variable, the same `Math.min($.limit.output,Z)\|\|Z` with Z=32000 and the same compaction formula in both binaries) | the env tests of task 2 pin the name; a pin move re-reads it |
| the variable limits the output on OpenCode 1 | [V live, 1.18.33]: with `1024` the reply was empty after 12 s, unset it was 800 lines | task 6.1 repeats it on the pin; raising above 32000 is not verified live |
| v2's `cV`, the `providers` root key, the optional `limit` fields, the merge | [V src, 2.2.6 binary] | the config tests of task 3 pin the shape |
| a v2 overlay on a built-in provider reaches the request, and naming a provider also enables it, lets it count as available without a connection (the request's auth can then be swapped when there is no credential or key) and gives an unknown model `limit {context: 200000, output: 32000}` | [I] (2.2.6 binary strings, not seen in a request); a profile with a credential does not take that branch | task 6.1 records it live (owner), with a no-credential hello and a stored-login profile |
| a provider answers a maximum above the model's with 400 | [I] | the hello of D6 |
| OpenRouter refuses a maximum its key's credits cannot cover with 402 | [V] `tests/fixtures/recorded/opencode/1.18.33/error-openrouter-credits-max-tokens.jsonl` (`You requested up to 32000 tokens, but can only afford 7377`) | today's credits limit (L4-AVL) |

The [I] rows are not added to L4-OCV-013's table of [U] facts: no parser depends on them, the overlay is opt-in, and a
wrong inference shows as a hello error or as a length stop that names the key's value. `test_opencode_v2_docs.py` pins that
table at U1 to U11.

## Risks / Trade-offs

- **v1 compaction comes earlier.** For a model without a catalog input limit, raising the key from 32000 to `n` lowers
  the auto-compaction threshold of an implementer's session by `n - 32000` tokens. D2 refuses a key at or above
  `context_window`; the runbook says to keep an implementer profile's key well below the window, or to set it on the
  judge profile only.
- **A value above the model's maximum.** v2 sends it for any model, v1 only for a model the catalog does not know; the
  provider answers 400. The hello catches it and the note names the key.
- **Credits.** OpenRouter reserves credits for the maximum output: a raised key on a low-credit key can turn a call into
  a 402, which L4 reads as out of credits and cools the profile for.
- **Cost of a verbose model.** A larger limit lets a model that loops or over-explains spend more per call.
- **An experimental variable.** OpenCode 1 names it `EXPERIMENTAL`; a later 1.x may drop it. The pin is fixed, and a pin
  move re-reads the variable (the env tests pin its name).
