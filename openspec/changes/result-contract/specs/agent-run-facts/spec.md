## Purpose

An agent adapter reports what the harness needs to repair a result object (the agent's final message, and why a
finished run gave no usable result), and `agent.finished` records how large the agent's context grew in one call, for
every adapter whose stream shows it.

## ADDED Requirements

### Requirement: L4-FAC-010 A finished run reports its final message and why its result is not usable
`RunResult` SHALL have the fields `last_message` and `result_problem`.

`last_message` SHALL be the agent's text after its last tool call, or `None` when the adapter cannot tell:
- opencode: the `text` parts after the last `tool_use` event, joined;
- kiro-cli: the `agent_message_chunk` text after the last `tool_call` update, joined (`runFinished.finalText` holds the
  text of the whole run);
- codex: the last `agent_message`;
- claude-code: the `result` of the final result event;
- command: `None`.
`final_text` MUST keep its meaning (the opencode judge reads it).

`result_problem` SHALL be set when the run finished but its result channel gave no usable object, and `None`
otherwise:
- `attach_file_result` (opencode, kiro-cli, command): `missing` when there is no file, `not_json` when the file is not
  JSON, `not_object` when the JSON is not an object, and, for a request with a schema, `invalid` with the object in
  `rejected` when the object breaks the schema; with no schema in the request a missing file keeps the status `ok`,
  and every other problem keeps `error`;
- codex `_attach_result`: `missing`, `not_json` or `invalid`; claude-code `_attach_structured`: `missing` or
  `invalid`; both keep the status `error` and set `rejected` for an invalid object, as the judge path needs.
The status and the detail that an adapter reports today MUST NOT change.

#### Scenario: SCN-FAC-16 (+) A prompt-contract adapter hands over the object as written; a native one keeps its schema check
- **GIVEN** an implementer request with no result schema to `attach_file_result`, and in turn a file `{"status": "red"}`, no file, and a file `not json`
- **WHEN** the result is attached
- **THEN** the first is `ok` with `structured == {"status": "red"}` and no `result_problem`, the second is `ok` with `result_problem: "missing"`, and the third is `error` with `result invalid: not JSON` and `result_problem: "not_json"`
- **AND** with the canonical schema, codex and claude-code still return `error` with the same detail as today, `rejected` holding the refused object and `result_problem: "invalid"`, and the recorded opencode replay of an invalid file with a schema is still `error`

#### Scenario: SCN-FAC-17 (+) Each adapter reports the text after the last tool call
- **GIVEN** the recorded streams of each adapter: an opencode run with text before and after its last `tool_use`, a kiro-cli run whose `finalText` holds all of its text, a codex run with two `agent_message` items, a claude-code result event, and a command run
- **WHEN** they are parsed
- **THEN** `last_message` is the opencode text after the last tool call, the kiro-cli text after the last `tool_call` (shorter than `finalText`), the last codex message, the claude-code `result`, and `None` for the command run; `final_text` is unchanged for each

### Requirement: L4-FAC-011 agent.finished records the peak per-call context where the stream shows it
`Usage` SHALL have the fields `context_peak_tokens` and `context_peak_percent`, and `agent.finished` SHALL record each
one when it is set:
- opencode: `context_peak_tokens`, the largest `tokens.input + tokens.cache.read + tokens.cache.write` of the run's
  `step_finish` events;
- claude-code: `context_peak_tokens`, the largest `input_tokens + cache_read_input_tokens +
  cache_creation_input_tokens` of the `message.usage` of the run's `assistant` events;
- kiro-cli: `context_peak_percent`, the largest `metadata.contextUsagePercentage`.
codex, command and the fake adapter MUST NOT report a peak: codex reports one usage total for the whole turn.
`input_tokens`, `output_tokens` and `cached_input_tokens` MUST keep their meaning. The `agent.finished` progress line
SHALL end with `, context peak <n>k tokens` or `, context peak <p>%` when the event has the field, and SHALL stay as
before without it.

#### Scenario: SCN-FAC-18 (+) The peak per-call context of opencode, claude-code and kiro-cli
- **GIVEN** an opencode stream with three `step_finish` events whose `input + cache.read + cache.write` are 9000, 21600 and 15000, the recorded claude-code stream `red-ok.jsonl`, and a kiro-cli stream with `contextUsagePercentage` 1.1 and 3.6
- **WHEN** each run is parsed and its step records `agent.finished`
- **THEN** opencode records `context_peak_tokens: 21600` with `input_tokens` unchanged, claude-code records the largest per-call sum of its `assistant` events, kiro-cli records `context_peak_percent: 3.6`, and the progress lines end with `, context peak 21.6k tokens` and `, context peak 3.6%`

#### Scenario: SCN-FAC-19 (−) No peak where the stream does not show one
- **GIVEN** a codex run, a command run, and an `agent.finished` event of an older ledger
- **WHEN** the steps record `agent.finished` and the progress log reads the older event
- **THEN** no `context_peak_tokens` or `context_peak_percent` is recorded for codex and command, and the progress line of the older event is the line of today
