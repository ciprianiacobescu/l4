## Context

The analysis is `docs/plan/opencode-v2.md`: a 24-row matrix recorded in an isolated HOME with `opencode-ai@1.18.34`
and `@opencode/cli@2.0.32` side by side, with the labels [V] (observed), [I] (inferred), [U] (needs a live key or a
long run) and [D] (vendor docs). This change builds on `opencode-major-gate` (row 51), which provides
`l4.versions.major_of`, `catalog.major_problem` and the `unsupported_version` failure class.

## Decisions

**D1. Opt-in by profile, never automatic** (L4-OCV-001). `OpencodeOptions` gains `cli_major: Literal[1, 2] = 1`
(strict int) and `steps: OpencodeSteps | None` (`judge: int` 2..20, `implement: int` 10..2000; both optional). The
factory builds `OpenCodeV2Adapter` for a `cli_major: 2` profile and `OpenCodeAdapter` otherwise; both have
`name = "opencode"`. Automatic switching (try v2, fall back to v1) is refused: the two majors differ in success
detection, `ask` handling and the error schema, so a silent switch would change what `ok` means mid-plan. The load
checks (`opencode_option_problems`) are:

| Profile | Refused when | Message |
|---|---|---|
| `cli_major: 2` | `options.provider` is set | `options.provider is not supported with cli_major: 2 until the {file:} key form is recorded live (L4-OCV-013, provider_refused)` |
| `cli_major: 2` | the model's provider is `azure-cognitive-services` or `google-vertex-anthropic` | `OpenCode v2 renamed provider <old> to <new>: use <new>/<model>` [D] |
| `cli_major: 2` | `options.tools` names `list` | `options.tools: list has no OpenCode v2 permission action (glob and read cover it)` [D] |
| `cli_major: 1` (or unset) | `options.steps` is set | `options.steps applies to cli_major: 2 only (v1 runs without a step bound)` |

The A gate's reason for a v1 profile drops "when supported" and ends `or set options.cli_major: 2`. A v2 profile that
finds a v1 binary at `opencode2` (or no `opencode2`) fails `binary` with `opencode2 <v> is OpenCode v<m>; this profile
runs v2 (options.cli_major: 2, @opencode/cli 2.x): install @opencode/cli@2.0.32 (l4 doctor --fix installs it
user-locally) or remove options.cli_major`.

**D2. Its own prefix, one link** (L4-OCV-002). Installing `@opencode/cli` into the v1 prefix silently takes
`.bin/opencode` [V]. So v2 goes to `$L4_HOME/npm-opencode2` (`Paths.npm_prefix_opencode2`), and only
`node_modules/.bin/opencode2` is linked, as `~/.local/bin/opencode2`, through A's guarded `_link`. That prefix's `.bin`
is never added to `harness_path`: it holds an `opencode` (v2), which must never be found as `opencode`. The sandbox
binds `$L4_HOME` read-only already (`derive_tool_paths`), so the v2 package is visible to the agent sandbox. Catalog
constants: `OPENCODE2_VERSION = "2.0.32"`, `OPENCODE2_PACKAGE = "@opencode/cli"`. `catalog_pins()` adds
`agent:opencode2` and `npm:opencode2`. `required_tools` yields the `opencode` tool when a `cli_major: 1` opencode
profile is in a role chain and the `opencode2` tool (binary `opencode2`, major 2) when a `cli_major: 2` profile is.
`clis_cache_hash` adds `opencode2` to the `clis` list when needed. `prereqs.sh` gains
`OPENCODE2_VERSION=${OPENCODE2_VERSION:-2.0.32}` and PRQ-20 behind `--with-opencode2` (a machine-wide script cannot
read a repository's profiles); the pin drift test's regex becomes `^([A-Z0-9]+)_(VERSION|MIN)=`.

**D3. `--standalone` on every call, a private state directory, no flagless subcommand** (L4-OCV-003). Without it the
first client's daemon serves later clients with its own environment, which was reproduced twice [V]. One function,
`v2_argv(exe, subcommand, *args)`, builds every v2 argv. It puts `--standalone` right after the subcommand words and
raises `AdapterError` for a subcommand outside the allowed set (`run`, `auth list`, `session export`). There is no
`debug config`, `serve`, `service`, `api`, `pair` or `models`. Each call also gets `XDG_STATE_HOME` set to an empty
directory of its own: `<step dir>/opencode2-state` for runs and exports, `<scratch>/state` for probes. A missed flag
then still cannot find a shared `service.json`. `XDG_DATA_HOME` is never redirected: it holds the credentials and
`opencode.db`, which the export reads.

**D4. argv and environment** (L4-OCV-004).
- run: `opencode2 run --standalone --format json -m <provider/model> --title "l4 <role> <stem>"`; cwd = the worktree
  (implement) or `judge_workdir` (judge); stdin = the prompt, then EOF.
- hello: `opencode2 run --standalone --format json -m <m> --title "l4 hello" "<hello prompt>"`; cwd = an empty
  scratch directory; stdin DEVNULL.
- auth: `opencode2 auth list --standalone --format json`.
- export: `opencode2 session export <session id> --standalone`, stdin DEVNULL, 60 s, through the same sandbox wrap
  and isolation environment as the run, its stdout saved privately beside the raw events as `<stem>.export.json`
  (never published: it holds the prompt).

The environment is the allow-list plus `XDG_CONFIG_HOME` (empty, per step), `XDG_STATE_HOME` (D3),
`OPENCODE_DISABLE_PROJECT_CONFIG`, `_CLAUDE_CODE`, `_CLAUDE_CODE_SKILLS`, `_EXTERNAL_SKILLS` (ignored by v2,
harmless), `_AUTOUPDATE` = `1`, and `OPENCODE_CONFIG_CONTENT`. `OPENCODE_API_KEY` comes through the credential
loader as today, and the provider-key file path is unused (D1 refuses `options.provider`).

**D5. Native configuration, not the normaliser** (L4-OCV-005). v2 normalises today's v1 configuration without a
warning [V, all six L4 shapes], so emitting v1 would work. Native is chosen because:
1. The normaliser does not infer formats inside nested agents and providers, and warns on conflicting mixes [D]. The
   step bound lives in `agents.build`, where native is the documented form.
2. The native `agents.build.steps` and the v1 `agent.build.maxSteps` resolve to the same value [V, `debug config`],
   and the v1 form stopped a run at its bound [V], so native costs nothing in certainty.
3. `list` and `doom_loop` are not v2 actions [D], and `external_directory` defaults to allow on v2 [D]. Emitting
   native makes every rule explicit and lets a contract test pin it against the recorded normalised output of
   today's shapes.
4. v2 has actions v1 never named: `skill` and `subagent`. Background child sessions could outlive the run, and skills
   are guidance the harness does not choose. They get the profile's refuse value: `deny`, or `ask` for `opencode/`
   free models, as `bash` does today, because a removed tool can trigger the free tier's 403 [V for read and bash; I
   for skill and subagent].
5. **`options.tools` would lose its meaning under the normaliser** [V]. The recorded normalisation of today's
   `options.tools` shape is a deny-all followed by the tools map's allows, then by every allow of the permission map,
   `shell:* allow` included. The last match wins, so a profile that listed only `read` and `edit` would get `shell`
   back on v2. In v1, `tools: {"*": false}` removes the unlisted tools from the request, whatever the permissions.
   Only a native array without the unlisted allows keeps that intent.
6. v1's `config_content` stays byte-identical.

`OPENCODE_CONFIG_CONTENT` for v2 holds `$schema`, `snapshots: false`, `share: "disabled"`, `update: "disable"`, the
`permissions` array (last match wins; broad rules first), and `agents: {build: {steps: N}}`. `refuse` is `ask` for an
`opencode/` model, else `deny`:

| Mode | `permissions` (in order) |
|---|---|
| judge, paid | `*:* deny` |
| judge, free | `*:* deny`, `read:* ask`, `shell:* ask` (a full deny gets 403 on v2 [V]) |
| implement | `edit:* allow`, `read:* allow`, `glob:* allow`, `grep:* allow`, `shell:* allow`, `shell:git commit* deny`, `shell:git push* deny`, `shell:git reset* deny`, `shell:git checkout* deny`, `external_directory:* deny`, `external_directory:<result-dir>/** allow`, `external_directory:<result-dir>/* allow`, `webfetch:* deny`, `websearch:* deny`, `question:* deny`, `skill:* <refuse>`, `subagent:* <refuse>` |
| implement with `options.tools` | `*:* deny` first, then for each listed tool its v2 action (`bash`→`shell`; `edit`, `write`, `patch`→`edit`; `read`, `glob`, `grep` as named) `:* allow`, then the git denies (when `shell` is allowed) and the `external_directory`, `webfetch`, `websearch`, `question`, `skill`, `subagent` rules as above (fallback `tools_by_permission`, U2) |
| read_only | as implement, but `edit:* deny` and `shell:* <refuse>` |

**D6. Step bounds per role** (L4-OCV-006). The numbers and their derivation are in `docs/plan/opencode-v2.md` §3.
- **Judge mode: 3.** A reply needs one step. The second step tolerates one rejected tool attempt (v1 tolerates none),
  and the third is v2's forced tool-less summary [D, V with `steps: 3`]. Judge mode covers every
  `PermissionPolicy("judge")` call (judges, clarifier, verifier generate/audit/test-writer, readiness, delegate) and
  the hello.
- **Implementer: 200.** About 10× the largest per-phase tool-call count recorded (19) and about 14× the largest step
  count (14). Those come from small spike repositories, so the value is per profile (`options.steps.implement`) and
  the wall-clock timeout stays the primary bound.
- **Detection.** A run reached its bound when its `step_start` count is ≥ the bound (one per step [V]). Such a run is
  never `ok`: it is `permission_blocked` when it recorded denials, else `error` with the detail
  `step_bound: opencode2 stopped at agents.build.steps <N>`, whatever the export says (U7).
- v1 gets no bound (D1 refuses `options.steps` there).

**D7. Status** (L4-OCV-007), for `OpenCodeV2Adapter.parse(lines, *, exit_code, stderr_tail, export, export_problem,
step_bound, …)`. The first rule that applies decides:
1. timed out → `timeout`; interrupted → `cancelled` (U10).
2. an `error` event → D9's classification.
3. exit ≠ 0 → A's `unsupported_version` rule on `stderr_tail`, else `error` `opencode2 exited with code N`.
4. step bound reached → D6.
5. export available: `info.outcome == "succeeded"` → attach the result (judge: the reply; implement: the result file)
   → `ok` or the result's problem. Any other outcome → `error` `opencode2 session outcome <value>` (U7).
6. export unavailable (`export is None`, with or without an `export_problem`: no session id, export exit ≠ 0,
   timeout, not JSON, no `info.outcome`): the v1 rule. A last
   `step_finish` reason `stop` → attach the result. Denials → `permission_blocked`. Else `error` `opencode2 session
   export failed (<why>) and the stream has no final stop` (U5).

The judge reply for the `{…}` slice is `last_message` (the text after the last `tool_use`), because a v2 judge may
write prose around rejected tool attempts before it answers. With no tool call it equals the whole text. The slice
and validation are the shared `l4.agents.contract.attach_judge_reply(result, text, schema)` that the `kiro-judge`
change (row 50) moves out of the v1 adapter. There is one slicer, not a v2 copy.

**D8. Usage from the export** (L4-OCV-008). Per assistant message, `tokens.input`, `tokens.output`,
`tokens.cache.read` and `tokens.cache.write` are summed. `cost` is `info.cost`, else the sum of the messages' `cost`.
`context_peak_tokens` is the largest `input + cache.read + cache.write` of one assistant message. With no export, the
stream's `step_finish` parts are summed as in v1, which may be partial. The recorded export has one assistant message
[V]. Whether a multi-step run exports one message per step is [U] (U11, fallback `sum_messages`: the sum above, which
equals `info.tokens` for one message).

**D9. Errors, limits, denials** (L4-OCV-009).
- A v2 `error` event is `{type, message, status, response.body}` [V].
- `status` 401 or 403, or `type == "provider.auth"`, or A's auth wording (`_AUTH_FAILED`) → `auth` (U4,
  `auth_by_status`). Both recorded free-tier 403s land here: denied tools, and a flagged network.
- `limits._opencode_v2(model, now, payload)`, chosen when the payload's `error` has `status` and no `data`:
  - 402 → kind `credits`, source `opencode2.status`;
  - 429 → kind `rate_limit`, no `resets_at`, source `opencode2.status`;
  - any other status → not a limit.
  - It never reads `response.body`, headers or the message for a reset (U1, `status_only`). `normalise_limit`'s text
    fallback is not used for a v2 payload.
- `status` ≥ 500 → `error` with `, retryable`. Any other → `error` `opencode2 reported an error (<type>, status <n>)`.
- Denials: a `tool_use` whose `state.status == "error"` and whose `state.error` starts with `Permission denied:` or
  contains `cannot ask the user for permission` [V]. Each gives `{tool_name, tool_input}`.

**D10. Auth** (L4-OCV-010). `opencode2 auth list --standalone --format json` gives
`[{id, name, connections: [{type, name, status?}]}]` [V]. A provider counts as having a credential when an entry's
`id` equals the model's provider and it has a connection whose `status.status` is not `needs_auth`. A `needs_auth`
connection fails with `opencode2 reports <provider> needs auth (<status.message>)`. Presence only, as in v1: the hello
stays the authoritative check. `OPENCODE_API_KEY` still decides first for `opencode/` and `opencode-go/` models
(L4-PRV-028), and free models still skip the step.

**D11. The `</think>` leak** (L4-OCV-011). 1 of 6 recorded v2 hellos was `"…</think>L4-OK"` with no opening tag [V
once; cause I]. On v2 only, a text part that holds `</think>` before any `<think>` loses everything up to and
including the first `</think>`, then is trimmed. This applies to the hello reply and to the judge reply before the
`{…}` slice: leaked reasoning with braces would otherwise break the slice. It is justified because what is removed
is, by its closing tag, reasoning and not the answer. A reply that is only reasoning still fails. A text with an
opening `<think>` is left alone.

**D12. Probe, doctor, recorded versions** (L4-OCV-012).
- `probe_opencode_v2` runs `binary` against `opencode2` with major 2, `auth` per D10, `quota` as v1 (OpenRouter
  only), and `hello` per D4 with D7's error mapping but no export (exit 0, no `error` event, the reply equals `L4-OK`
  after D11).
- ENV-004 and LIVE-005 take the binary and major from the profile (`catalog.profile_cli(profile) -> (binary,
  major)`).
- `recordedversions.unrecorded(adapter, version)` compares only against recorded versions of the same major, so
  `2.0.32` recordings never make a `1.18.35` binary "recorded", and the reverse.

**D13. [U] facts, fallbacks, experimental** (L4-OCV-013).

| # | [U] fact | Fallback (the name a test and a comment carry) | Recorded by |
|---|---|---|---|
| U1 | the 402 and 429 shapes; where `retry-after` lives | `status_only` (D9) | B8.3 |
| U2 | whether a v2 deny drops the tool's schema | `tools_by_permission` (D5) | B8.4 |
| U3 | the custom provider's `{file:}` key | `provider_refused` (D1) | B8.5 |
| U4 | the OAuth refresh failure text | `auth_by_status` (D9) | B8.6 |
| U5 | how often `step_finish` is missing on long runs | `export_decides` (D7) | B8.2 |
| U6 | guidance isolation in a real prompt | `deny_skill_and_mask` (D4, D5, L4-SEC-005 masks) | B8.7 |
| U7 | `outcome` values other than `succeeded`; a bounded run's outcome | `not_ok_named` (D6, D7) | B8.2 |
| U8 | v1 and v2 sharing `opencode.db` over time | `live_coexistence` (no code) | B8.8 |
| U9 | the `</think>` cause; whether `steps: 1` makes step 1 the summary | `strip_leading_think` (D11); judge floor 2 | B8.2 |
| U10 | SIGINT exit 130 | `harness_interrupt` (D7.1) | not recorded (the harness flag decides) |
| U11 | a multi-step export's message layout | `sum_messages` (D8) | B8.2 |

`OpenCodeV2Adapter.experimental = True`, so the factory records `agent.experimental` once per profile until B9
removes it. B9 replaces a fallback with a parser only for a row whose fixture B8 recorded, and changes that row's
[U] to [V] in the SPEC.

## Risks

- **The free tier refuses whole networks** [V on v2, row 24]: a runner whose address is flagged loses every
  `opencode/` free profile, whatever the major. The 403 is classed `auth`, so it is re-probed after
  `auth_failure_ttl`. The live validation needs a runner whose network is not flagged, or a paid `opencode-go/`
  implementer, and it must never send bursts to the free tier (B8.3 provokes a 429 only on the paid key).
- v2 is moving fast (33 releases in 5 weeks). The pin is exact, and a patch drift is a LIVE-005 warning, as for v1.
- Skill and subagent rules on a free model [I]. If B8 records a 403 caused by them, B9 drops those two rules for
  `opencode/` models.

## 0.4.28 amendment (2026-10-24)

The change was written on 2026-10-19 against the 0.4.18 tree and paused after B3. It resumes on the 0.4.27 tree
(branch `oc2-0428` from `rel-0428`). The spec commits, the analysis and B1's fixtures were carried over unchanged. B2
and B3 were not: provisioning and the major gate moved under them (`pin-clis` in 0.4.20, the Kiro and Copilot gates in
0.4.20 and 0.4.27), so they are built again from the tasks below. The old commits (`7e380398`, `51df7795` on branch
`opencode-v2`) are a reference, not a patch. Decisions E1 to E7 amend D1 to D13. Where they differ, the amendment wins.

**E1. The pin stays 2.0.32 [V, 2026-10-24].** `@opencode/cli` is at 2.1.4. The same isolated-HOME, no-key check on
2.0.32 and 2.1.4 found the same `run`, `session`, `session export` and `auth` help (`debug` gains `heap-dump`), the
same `opencode v<N>` version form, the same `auth list --standalone --format json` answer (`[]` without a key), the
same `session export` document (2.1.4 drops only `info.title`, which nothing reads), and the same event envelope (a
2.1.4 free hello gave `step_start`, `text`, `step_finish` with reason `stop`). Both versions wait without output
while stdin stays open, even with the prompt as an argument [V, both]. So every v2 call closes stdin: the run writes
the prompt and then EOF, and the hello, the auth step and the export get `DEVNULL` (L4-OCV-004). The fixtures stay
those of 2.0.32. A later pin move is a patch-drift question (LIVE-005), not this change.

**E2. The major gate is the shared one, keyed by the CLI, not the adapter.** Since 0.4.20 the gate's texts live in
`catalog.MAJOR_WORDS` and `SUPPORTED_MAJORS`, keyed `opencode`, `kiro-cli`, `copilot-cli` (L4-OCG-005, -006).
`opencode2` becomes a fourth key: `SUPPORTED_MAJORS["opencode2"] = 2` (from `OPENCODE2_VERSION`) and
`MAJOR_WORDS["opencode2"]`, whose `problem` is D1's v2 reason. `catalog.profile_cli(profile) -> (key, binary)` gives
`("opencode", "opencode")` for a v1 profile and `("opencode2", "opencode2")` for a v2 profile. Every caller that takes
an adapter for the gate (`major_problem`, `major_plan_reason`, `major_verified_text`, `major_no_version_text`,
`major_config_error`, ENV-004, LIVE-005, the probe's `binary` step, `plan_fixes`, `_verified`) takes that key instead.
For every other adapter the key equals the adapter. The v1 text's last clause changes from `OpenCode 2 support comes
in a later L4 release` to `or set options.cli_major: 2 to run OpenCode 2 (experimental)`, in the code, L4-OCG-002, the
runbook and the tests. Released CHANGELOG lines keep the old text.

**E3. `pin-clis` applies to `opencode2` as to every agent CLI**, as that change's design (§Collisions) said it would:
- `ci.cli_versions` accepts the key `opencode2`, validated against major 2 (`major_config_error` with
  `L4-OCG-001, L4-OCV-002`);
- `effective_pins` and `catalog_hash`'s overrides include it;
- the exact pin and ENV-015 check `opencode2` against its pin;
- `ADAPTER_PINS` stays keyed by adapter; a new `CLI_PINS` (`ADAPTER_PINS` plus `opencode2`) serves the per-CLI uses.
  `catalog_pins()` gains `agent:opencode2` and `npm:opencode2`.
- PRQ-20 keeps its number, behind `--with-opencode2`. The runner README's "PRQ-20 is reserved" line becomes a table
  row, and `tests/unit/docs/test_pin_clis_docs.py` is updated to read it.

**E4. The delegate is not served by a v2 profile in this release.** The read-only mode (`PermissionPolicy("read_only")`)
exists only for the delegate (L4-DLG-015, -016; `delegate/run.py` is its one caller [V]), and nothing of it is
recorded on v2: the read tools' rules, `lsp`, the Zen `bash` sentinel, the masked instruction files. A `cli_major: 2`
profile in `roles.delegate` is a configuration error at load (L4-OCV-014): `profiles.<name> is in roles.delegate,
but it runs OpenCode v2 (options.cli_major: 2), which does not serve the delegate in this release (its read-only mode,
L4-DLG-016, is not recorded on v2): remove <name> from roles.delegate or use a cli_major: 1 profile`. The v2 adapter
also raises `AdapterError` for a read-only request, so a path that skipped the load check still fails closed. So D5
loses its `read_only` row, D6's judge-mode list loses the delegate, and SCN-OCV-09 covers implement and the two judge
shapes. `config-normalised-read-only.json` stays as a recording for the change that adds a v2 delegate.

**E5. The class follows the major.** `Factory.build` builds a fresh adapter per call from `ADAPTERS[adapter]`, and
both classes are named `opencode`. It picks the class by the profile's CLI key (`profile_cli`): `opencode2` builds
`OpenCodeV2Adapter`, every other key the adapter's class, so a run with a v1 and a v2 profile gets the right class for
each. An adapter a test injects under `opencode` serves both majors unless one is injected under `opencode2`. Nothing
is cached (corrected 2026-10-24: an earlier text said `build` caches by name; it never did).

**E6. The live validation (B8) never runs on a runner that serves a consumer.** v2 migrates the runner user's
`opencode.db` in place (row 20, one trial), and `XDG_DATA_HOME` is never redirected (D3). The shared GitLab shell
runner (`concurrent = 1`, one runner user) also runs a consumer's v1 jobs. So B8 runs on an ephemeral runner (a
GitHub-hosted job) in a dummy repository. The GitHub dummies of earlier live tests are archived for deletion, so the
orchestrator names the repository to the owner before it creates or unarchives one.

**E7. Release and numbering.** The change ships in 0.4.28 (CHANGELOG `## 0.4.28 (unreleased)`), as change-table row
68, after `copilot-cli` (67). L4-OCV-001 to L4-OCV-014 and SCN-OCV-01 to SCN-OCV-28 are free in the SPEC [V]. The
`kiro-judge` dependency of B5 has shipped (`l4.agents.contract.attach_judge_reply` [V]), so B5 uses it as is.
