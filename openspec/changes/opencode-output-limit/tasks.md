Read `design.md` first: D1 to D7 are the behaviour, and the scenario ids are in `specs/opencode-output-limit/spec.md`
and `docs/SPEC.md` (L4-FAC-023, L4-OCV-020, SCN-FAC-52..58, SCN-OCV-49..52). Write each test first, run it and see it
fail, then write the code. Run only the test files named here, never the whole suite. Do not start `opencode` or
`opencode2`.

## 1. The key and its checks (D1, D2)

- [x] 1.1 Write the tests first in a new `tests/unit/config/test_opencode_output_limit.py`, built like
  `tests/unit/config/test_opencode_cli_major.py` (its `profile`, `refused` and `messages` helpers):
  - SCN-FAC-54: `max_output_tokens` of `1024`, `32000` and `256000` load and `opencode_options().max_output_tokens`
    returns them, with `cli_major` 1 and 2; `1023`, `256001`, `0`, `-1`, `True`, `65536.0` and `"65536"` are refused with
    the message `options.max_output_tokens: must be a whole number from 1024 to 256000`, and the message never holds the
    value given (assert `"256001" not in` and so on);
  - absent, `opencode_options()` is None for a profile with no options, and `.max_output_tokens` is None otherwise;
  - SCN-FAC-55: a custom-provider profile (copy the `options.provider` shape of
    `tests/unit/config/test_opencode_provider_options.py`) whose model entry is `{context: 262144, output: 16384}` with
    `max_output_tokens: 32000` is refused with `options.max_output_tokens is above the output of the model's entry in
    options.provider.models (OpenCode asks for the smaller): raise the entry's output or lower the key`; with `16384` it
    loads;
  - SCN-FAC-55: `Profile(adapter="opencode", model=..., context_window=65536, options={"max_output_tokens": 65536})` is
    refused with `options.max_output_tokens must be below context_window (the prompt and the reply share the window)`;
    `65535` loads; a profile without `context_window` is not checked;
  - the key on a profile of another adapter (`claude-code`, `options: {max_output_tokens: 1}`) still loads (other
    adapters' `options` are not read).
- [x] 1.2 Then, in `src/l4/config/schema.py`: add `max_output_tokens: int | None = None` to `OpencodeOptions` with a
  `field_validator("max_output_tokens", mode="before")` that accepts only `None` or a value whose `type(...) is int` and
  that lies in `MAX_OUTPUT_TOKENS_RANGE = (1024, 256000)` (a module constant with a comment: OpenCode 2's floor `QC` and
  clamp `KC`), else `raise ValueFree("must be a whole number from 1024 to 256000")`. Add the provider-entry rule to
  `opencode_option_problems` (after the two existing provider checks, before `_cli_major_problems`), and the
  `context_window` rule to `Profile._opencode_options` (it reads `self.context_window`; raise after the option
  problems, joined the same way). Run `uv run --frozen pytest tests/unit/config/test_opencode_output_limit.py
  tests/unit/config/test_opencode_cli_major.py tests/unit/config/test_opencode_provider_options.py -q`.

## 2. OpenCode 1: the variable (D4)

- [ ] 2.1 Write the tests first in a new `tests/unit/agents/test_opencode_output_limit.py`, with the `request`,
  `FakeProc` and fixture paths of `tests/unit/agents/test_opencode.py` (import or copy them):
  - SCN-FAC-52: a profile `Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", vendor="deepseek",
    options={"max_output_tokens": 65536})` run in implement, judge and read-only mode: each call's `env` holds
    `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX == "65536"`, and `env["OPENCODE_CONFIG_CONTENT"]` equals the one of the same
    request whose profile has no `options`;
  - SCN-FAC-53: without the key no call's `env` holds the variable; a custom-provider profile (the `mag` profile of
    `tests/unit/agents/test_opencode_provider.py`, entry `{context: 262144, output: 65536}`) with
    `max_output_tokens: 65536` keeps `provider.<id>.models.<model>.limit == {"context": 262144, "output": 65536}` and
    has the variable `"65536"`;
  - SCN-FAC-52, the hello: with the `make_ctx` fixture and `FakeRun` of `tests/unit/availability/conftest.py` (as
    `tests/unit/availability/test_probes_opencode.py` uses them), the `hello` step of the profile with the key runs with
    the variable in its environment, and the `auth` step of a profile on `google/gemini-3.5-flash` with the key does not
    (`run.calls[-1][2]` is the environment).
- [ ] 2.2 Then, in `src/l4/agents/opencode.py`: add `OUTPUT_TOKEN_ENV = "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX"` (a
  comment: OpenCode 1 reads it as `flags.outputTokenMax`, `maxOutputTokens = min(model.limit.output, value) || value`,
  default 32000 [V src, 1.18.33]; re-read it when the pin moves) and `output_limit_env(options: OpencodeOptions | None)
  -> dict[str, str]`. Merge it in `run()` after `isolation_env(...)` and in `_hello_once` into the `probe_env` extra.
  Leave `config_content` and `isolation_env` unchanged. Run the new file and `uv run --frozen pytest
  tests/unit/agents/test_opencode.py tests/unit/agents/test_opencode_provider.py tests/unit/agents/test_opencode_delegate.py
  tests/unit/availability/test_probes_opencode.py -q`.

## 3. OpenCode 2: the model's limit.output (D5)

- [ ] 3.1 Write the tests first in `tests/unit/agents/test_opencode_output_limit.py` (or a separate
  `test_opencode_v2_output_limit.py`), calling `config_content_v2` as `tests/unit/agents/test_opencode_v2_command.py`
  does:
  - SCN-OCV-49: `options={"cli_major": 2, "max_output_tokens": 65536}` on `opencode-go/deepseek-v4.1-flash`, in implement
    and judge mode: `json.loads(text)` equals the dict without the key plus `providers == {"opencode-go": {"models":
    {"deepseek-v4.1-flash": {"limit": {"output": 65536}}}}}`, `list(json.loads(text))[-1] == "providers"`, and the
    other keys keep their order;
  - SCN-OCV-50: `openrouter/anthropic/claude-sonnet-5.5` with `64000` gives `{"openrouter": {"models":
    {"anthropic/claude-sonnet-5.5": {"limit": {"output": 64000}}}}}`;
  - SCN-OCV-51: without the key, for implement and judge mode, a paid and an `opencode/` free model, the text is
    byte-identical to the text for `options=None` with the same `cli_major` handling (assert no `"providers"` in the text
    and equality with the existing pinned expectations of `test_opencode_v2_command.py`);
  - SCN-OCV-52: with the `make_ctx` fixture (as `tests/unit/availability/test_probes_opencode_v2.py` uses it), the hello
    of a `cli_major: 2` profile with the key carries the `providers` block in `OPENCODE_CONFIG_CONTENT`, and its `auth`
    step's `OPENCODE_CONFIG_CONTENT` equals the one of the same profile without the key; the run (with the `V2Proc` of
    `tests/unit/agents/test_opencode_v2_run.py`) carries the block in the run's and the export's configuration; no
    environment holds `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`.
- [ ] 3.2 Then, in `src/l4/agents/opencode_v2.py`, append the block in `config_content_v2` after `agents` when
  `options is not None and options.max_output_tokens is not None`, splitting `model` on the first `/`. In the `auth`
  step of `probe_opencode_v2`, pass `options.model_copy(update={"max_output_tokens": None})` (when `options` is not
  None) so the listing's configuration stays as without the key. Nothing else changes. Run the new tests and `uv run --frozen pytest tests/unit/agents/test_opencode_v2_command.py
  tests/unit/agents/test_opencode_v2_run.py tests/unit/agents/test_opencode_v2_allow_list.py
  tests/unit/availability/test_probes_opencode_v2.py -q`.

## 4. The hints (D6)

- [ ] 4.1 Write the tests first in `tests/unit/agents/test_opencode_output_limit.py`:
  - SCN-FAC-56, unit level: `output_limit_hint(result, options, major)` on a `RunResult(status="error",
    length_stop=True, detail=D)` appends exactly the texts of L4-FAC-023 for (major 1, no key), (major 2, no key) and
    (either major, key 65536), joined to the detail by `; `; a result with `length_stop=False` is unchanged; with
    `detail=None` or `""` the detail becomes the hint alone (no leading `; `);
  - SCN-FAC-56, run level: `OpenCodeAdapter(FakeProc(stream)).run(req)` of a judge request whose stream is the
    `stream("length")` of `tests/unit/agents/test_opencode_length_stop.py` has `length_stop` set and the detail `the
    stream ended without a final stop (last reason: length)` plus the v1 no-key text; with the key, plus the key text;
    the same for `OpenCodeV2Adapter` with a `V2Proc` whose export fails (`exit 1`); and `OpenCodeAdapter().parse(...)`
    alone still returns today's detail (the existing `test_opencode_length_stop.py` must pass unchanged);
  - SCN-FAC-57: a v1 run whose stream is one `error` event with `statusCode: 400` (build it as
    `test_a_plain_400_stays_a_generic_error` in `tests/unit/agents/test_opencode_provider.py` does) on a profile with the
    key ends `opencode reported an error (status 400); options.max_output_tokens is set: a provider refuses a maximum
    output above the model's own (HTTP 400)`; a v2 run with `{"type": "error", "error": {"type": "x", "status": 400}}`
    likewise; without the key, or with status 500 or 402, no clause; a v1 and a v2 hello whose stream is that error
    event end their `reason` with the clause when the key is set, and a v1 hello whose 400 message says `grammar binding
    failed` does not.
- [ ] 4.2 Then add `output_limit_hint` to `src/l4/agents/opencode.py` (the three length texts and the 400 clause as
  module constants, the texts exactly as in L4-FAC-023) and call it in `OpenCodeAdapter.run()` and
  `OpenCodeV2Adapter.run()` on the result of `parse()` before returning it (the v1 run's 400 is the generic branch of
  `_classify_error`, which sets `api_status`; `provider_unavailable` sets none and gets no clause); add the 400 clause
  to the failure text in `_hello_once` and `_hello_v2_once` when `status == 400`, the key is set and the message does not
  match `_GRAMMAR`. Run the new tests and
  `uv run --frozen pytest tests/unit/agents/test_opencode_length_stop.py tests/unit/agents/test_opencode.py
  tests/unit/agents/test_opencode_v2_run.py tests/unit/agents/test_opencode_v2_parse.py
  tests/unit/llm/test_agent_judge_length_stop.py tests/unit/verifier/test_judge_length_split.py
  tests/unit/availability/test_opencode_hello_retry.py -q`. Then `grep -rn "last reason: length\|no final stop\|session
  outcome" tests/unit` and run every file it lists that calls an adapter's `run()`.

## 5. The doctor note (D7)

- [ ] 5.1 Write the test first in `tests/unit/doctor/test_checks_provision.py`, next to the test that asserts `mag
  provider 192.0.2.10:10100 reachable`: SCN-FAC-58, two custom-provider judge profiles, one with model entry `output:
  65536` and no key, one with `output: 16384`; PRV-001's message holds `<first> asks for at most 32000 output tokens
  although its model entry allows 65536 (OpenCode 1's default): set options.max_output_tokens to use it` and no such
  note for the second; the first with `max_output_tokens: 65536` gets no note; the status is the same as without the
  notes.
- [ ] 5.2 Then extend `_provider_notes` in `src/l4/doctor/checks_provision.py` (after the reachability note of the
  same profile). Run `uv run --frozen pytest tests/unit/doctor/test_checks_provision.py -q`.

## 6. The live record (a person with keys; not the implementer)

- [ ] 6.1 The oracle is the lowering direction, which is cheap and does not depend on a model writing 32000 tokens. On a
  machine with `@opencode/cli` 2.2.6 and an `opencode-go/` key, for a `cli_major: 2` profile:
  - with `max_output_tokens: 1024`, one judge call whose prompt asks for a long reply (for example "write 3000 words
    about X, then the JSON") must stop with `length` and a `step_finish` `tokens.output` near 1024; the same prompt on
    the same profile without the key must not stop at 1024;
  - `l4 probe <profile> --role judges --no-cache` with `max_output_tokens: 65536` must answer the hello;
  - record the streams and exports under `tests/fixtures/recorded/opencode/2.2.6/live-output-limit*` (redacted as the
    other `live-` fixtures).
  Do the same on OpenCode 1.18.34 with a v1 profile (this also shows that the pin still reads
  `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`; nobody has read 1.18.34's binary), under `.../1.18.34/` or the v1 recorded
  folder in use. When the 1024 runs stop where they should, mark the [I] of L4-OCV-020 and of design D8 [V]. If the hello
  fails, or the 1024 run does not stop near 1024, report it and do not release that major's part.

## 7. Docs

- [ ] 7.1 `docs/runbook.md`:
  - section 7.4, the bullet `Every judge was discarded in step 9 because its reply did not fit its output limit`: end it
    with `, or, on an opencode profile, set options.max_output_tokens to the model's maximum output (10.10)`, and say
    that the failure line of such a run now names the key;
  - a new section `### 10.10 The output limit of an OpenCode profile` after 10.9 (and its line in the contents list):
    the key and its range; what each major asks for with and without it (v1 the smaller of the key and the catalog's
    limit, so the key is a ceiling; v2 the key, then at most 256000 and fitted to the context, so the key replaces the
    catalog's limit); the default unchanged; that the hello asks with the same limit, so a value the provider refuses
    fails the probe; the three load errors and their fixes as a table; the two hints of a note as a table; the risks of
    design D8 and Risks (v1 compaction for an implementer profile, 400, OpenRouter's credit reservation with the
    recorded `You requested up to 32000 tokens, but can only afford 7377`, cost); the doctor note; and that a custom
    provider's model entry `output` above 32000 needs the key on OpenCode 1. An example:
    `judge-oc: {adapter: opencode, auth: api_key, model: opencode-go/glm-5.3-flash, vendor: zhipu, options:
    {max_output_tokens: 65536}}`, with a comment to use the model's own maximum.
  - Section 10.9 gets one line pointing to 10.10 for the output limit, without the word "experimental". Do not add a row
    to its known-fallbacks table (`tests/unit/docs/test_opencode_v2_docs.py` pins U1 to U11).
  - `tests/unit/docs/test_opencode_v2_docs.py` slices "runbook 10.9" from `### 10.9 ` to `\n## 11. `, and
    `test_neither_text_calls_the_adapter_experimental` asserts that the slice never says "experimental"; 10.10 names
    `OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`. End that slice at the next `\n### 10.` heading as well (in `sections()`:
    `.split("\n### 10.10 ", 1)[0]` before `.split("\n## 11. ", 1)[0]`), so the 10.9 tests still read only 10.9. Run
    `uv run --frozen pytest tests/unit/docs/test_opencode_v2_docs.py -q` after the edit.
- [ ] 7.2 `plugins/l4/skills/l4/references/adopt.md`: a short `## 4h. An OpenCode profile's output limit` after 4g, in
  the style of 4d: the key, that the default is OpenCode's own (32000 on v1), when to set it (a judge or reviewer whose
  replies stop with `length`), to use the model's real maximum, and that the pin must be 0.4.59 or later before the key
  is added (the schema is strict).
- [ ] 7.3 `docs/SPEC.md` already holds L4-FAC-023, L4-OCV-020, the amendments of L4-OCV-005 and L4-VER-071, the §8.3
  rows, the §3.2 example, SCN-FAC-52..58, SCN-OCV-49..52 and change-table row 131, and `CHANGELOG.md` its Unreleased
  entry. Check them against the code; fix the code or tell the orchestrator where they differ. Run
  `uv run --frozen python scripts/check_spec.py docs/SPEC.md`, `uv run --frozen pytest tests/unit/docs -q` and
  `openspec validate opencode-output-limit --strict`.
- [ ] 7.4 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.
