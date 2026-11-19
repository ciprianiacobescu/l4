## ADDED Requirements

### Requirement: L4-FAC-023 An opencode profile declares its model's output limit
An `opencode` profile SHALL accept `options.max_output_tokens`, the model's output limit for every request the profile
makes (every role and mode, and the hello). The value SHALL be a whole number from 1024 to 256000; anything else (a
`bool`, a float, a string, a number outside the range) SHALL be refused at load with `options.max_output_tokens: must be
a whole number from 1024 to 256000`, which never holds the value. With `options.provider`, the key SHALL NOT be above
the output of the model's entry in `options.provider.models` (OpenCode asks for the smaller of the two); with the
profile's `context_window`, the key SHALL be below it. Without the key, the adapters SHALL run exactly as before: no
variable, no configuration block, byte-identical configurations.

For OpenCode 1, a profile with the key SHALL export `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=<n>` to the run, in every
mode, and to the hello, and not to the `auth` probe step; its `OPENCODE_CONFIG_CONTENT` SHALL be unchanged. OpenCode 1
asks for `min(model.limit.output, n)`, or `n` when the catalog does not know the model's limit [V src, 1.18.33].

A run whose `length_stop` is set SHALL carry a hint after its detail, joined by `; ` (the hint alone when the detail is
empty): `the reply stopped at its output limit: OpenCode 1 asks for at most 32000 output tokens unless
options.max_output_tokens is set (up to the model's own maximum)` (v1, no key), `the reply stopped at its output limit:
OpenCode 2 asks for the model's known output limit, else 32000 tokens, unless options.max_output_tokens is set (up to the
model's own maximum)` (v2, no key), or `the reply stopped at its output limit (options.max_output_tokens <n>, or less
when the model or the context allows less)` (either major, key set). A run with `api_status` 400, and a hello whose error
event has status 400 and is not a `grammar binding failed` error, on a profile with the key SHALL carry, joined the same
way, `options.max_output_tokens is set: a provider refuses a maximum output above the model's own (HTTP 400)`. `parse()`
SHALL stay pure: the adapters' `run()` add the hints after it.

`l4 doctor` PRV-001 SHALL note a v1 profile in a role chain whose `options.provider` model entry has an `output` above
32000 and that has no key: `<profile> asks for at most 32000 output tokens although its model entry allows <output>
(OpenCode 1's default): set options.max_output_tokens to use it`. The note SHALL NOT change the check's status.

#### Scenario: SCN-FAC-52 (+) An OpenCode 1 profile with the key exports the variable to its run and its hello
- **Given** an `opencode` profile on `opencode-go/deepseek-v4.1-flash` with `options.max_output_tokens: 65536`
- **When** it runs as an implementer, as a judge and as the read-only delegate, and when its hello runs
- **Then** each child environment holds `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX=65536`, and each
  `OPENCODE_CONFIG_CONTENT` equals the one of the same profile without the key
- **And** the `auth` probe step's environment does not hold the variable

#### Scenario: SCN-FAC-53 (+) Without the key an OpenCode 1 run is unchanged, and a custom provider keeps its entry
- **Given** the profile of SCN-FAC-52 without the key, and a custom-provider profile whose model entry is `{context:
  262144, output: 65536}` with `options.max_output_tokens: 65536`
- **When** each runs
- **Then** the first has no `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX` and its configuration is byte-identical to 0.4.58's
- **And** the second's `provider.<id>.models.<model>.limit` is `{context: 262144, output: 65536}` and its variable is
  `65536`

#### Scenario: SCN-FAC-54 (−) A value that is not a whole number from 1024 to 256000 is refused without the value
- **Given** `options.max_output_tokens` set to `1023`, `256001`, `0`, `-1`, `true`, `65536.0` or `"65536"`
- **When** the configuration loads
- **Then** it is refused with `options.max_output_tokens: must be a whole number from 1024 to 256000`
- **And** `1024`, `32000` and `256000` load

#### Scenario: SCN-FAC-55 (−) A key above a custom provider's model output, or not below context_window, is refused
- **Given** a custom-provider profile whose model entry's `output` is 16384 with `options.max_output_tokens: 32000`, and
  a profile with `context_window: 65536` and `options.max_output_tokens: 65536`
- **When** the configuration loads
- **Then** the first is refused with `options.max_output_tokens is above the output of the model's entry in
  options.provider.models (OpenCode asks for the smaller): raise the entry's output or lower the key`
- **And** the second with `options.max_output_tokens must be below context_window (the prompt and the reply share the
  window)`, while `16384` with that entry and `65535` with that window load

#### Scenario: SCN-FAC-56 (+) A length stop names the key
- **Given** a v1 judge run and a v2 judge run whose last `step_finish` reason is `length` (no export for v2, `exit 1`),
  once on a profile without the key and once with `options.max_output_tokens: 65536`
- **When** each run ends
- **Then** `length_stop` is set, the status is `error`, and the detail is today's detail followed by the v1 no-key text,
  the v2 no-key text, and twice the key text with `65536`
- **And** `parse()` alone still returns today's detail, and a run that stopped for another reason gets no hint

#### Scenario: SCN-FAC-57 (−) A 400 on a profile with the key names the key, in the run and at the hello
- **Given** a v1 run and a v2 run whose `error` event has status 400, and a v1 and a v2 hello that fail the same way,
  each on a profile with the key
- **When** each ends
- **Then** each detail or hello reason ends with `; options.max_output_tokens is set: a provider refuses a maximum
  output above the model's own (HTTP 400)`
- **And** without the key the texts are today's, and a status other than 400 gets no clause

#### Scenario: SCN-FAC-58 (+) Doctor notes a custom provider that the default caps
- **Given** two v1 custom-provider profiles in `roles.judges`, one whose model entry's `output` is 65536 without the key,
  one whose entry's `output` is 16384
- **When** `l4 doctor` runs PRV-001
- **Then** its message holds `<first> asks for at most 32000 output tokens although its model entry allows 65536
  (OpenCode 1's default): set options.max_output_tokens to use it`, and no such note for the second
- **And** the check's status is what it would be without the note

### Requirement: L4-OCV-020 An OpenCode 2 profile's output limit is its model's limit.output in the native configuration
For a `cli_major: 2` profile with `options.max_output_tokens: n`, `config_content_v2` SHALL append, after `agents`,
`providers: {<provider>: {models: {<model id>: {limit: {output: n}}}}}`, where `<provider>` is the profile model's part
before the first `/` and `<model id>` everything after it, and nothing else in that block (no `context`, no `input`, no
package, settings or name). The run, the hello and the `auth list` step SHALL get that configuration. Without the key the
configuration SHALL be byte-identical to the one before this requirement.

OpenCode 2 has no output variable; its loader merges a configured model's limit over the catalog's (`{...catalog.limit,
...config.limit}`), and its request asks for `min(limit.output > 0 ? limit.output : 32000, 256000)`, lowered to fit the
context and never below 1024 [V src, 2.2.6]. So the key replaces the catalog's output limit (it may raise or lower it).
No other configuration the run reads sets it: the configuration home is an empty directory of the step, project
configuration is off, and `options.provider` is refused on v2 (L4-OCV-001). That the overlay keeps a built-in
provider's own settings and login and reaches the request is inferred from the loader [I] until a live run records it.

#### Scenario: SCN-OCV-49 (+) An OpenCode 2 profile with the key renders its model's limit.output after agents
- **Given** a `cli_major: 2` profile on `opencode-go/deepseek-v4.1-flash` with `options.max_output_tokens: 65536`
- **When** its implementer and its judge configurations are rendered
- **Then** each is the configuration without the key with `"providers": {"opencode-go": {"models":
  {"deepseek-v4.1-flash": {"limit": {"output": 65536}}}}}` as its last key, and the order of the other keys is unchanged

#### Scenario: SCN-OCV-50 (+) The model id keeps everything after the provider's slash
- **Given** a `cli_major: 2` profile on `openrouter/anthropic/claude-sonnet-5.5` with `options.max_output_tokens: 64000`
- **When** its configuration is rendered
- **Then** the block is `{"openrouter": {"models": {"anthropic/claude-sonnet-5.5": {"limit": {"output": 64000}}}}}`

#### Scenario: SCN-OCV-51 (+) Without the key the configuration holds no providers block
- **Given** the profile of SCN-OCV-49 without the key, in implement and judge mode, on a paid and on a free model
- **When** its configuration is rendered
- **Then** it has no `providers` key and is byte-identical to 0.4.58's

#### Scenario: SCN-OCV-52 (+) The hello and auth list carry the same overlay
- **Given** the profile of SCN-OCV-49
- **When** its hello and its `auth list` step run
- **Then** each `OPENCODE_CONFIG_CONTENT` holds the same `providers` block, and the hello's environment holds no
  `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`

## MODIFIED Requirements

### Requirement: L4-OCV-005 (amendment, the providers block)
For a v2 profile, `OPENCODE_CONFIG_CONTENT` SHALL be the native v2 shape of L4-OCV-005 and SHALL hold a `providers` key
only as L4-OCV-020 says, after `agents`. The rest of L4-OCV-005 is unchanged.

#### Scenario: SCN-OCV-51 is the scenario of this amendment (see above)
- **Given** a v2 profile without `options.max_output_tokens`
- **When** its configuration is rendered
- **Then** it has no `providers` key

### Requirement: L4-VER-071 (amendment, the remedy)
The last sentence of L4-VER-071's remedy SHALL read: a reasoning model whose thinking alone fills its limit is not helped
by fewer criteria: it is discarded after its batches, and the remedy is a reasoning cap (`options.provider`), a larger
output limit on an opencode profile (`options.max_output_tokens`, L4-FAC-023), or a judge with a larger output limit.

#### Scenario: SCN-FAC-56 is the scenario of this amendment (see above)
- **Given** a judge run on an opencode profile whose reply stopped at its output limit
- **When** it ends
- **Then** its detail names `options.max_output_tokens`
