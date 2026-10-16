## Purpose

While an implementer agent works, the CI log shows at a fixed interval that it is alive and what it did, in counts and
times only. An agent that shows no activity for too long is stopped in a way that people can see, with a reason that
names the key, and a long tool call that the stream shows as open is not taken for idle.

## ADDED Requirements

### Requirement: L4-IMP-023 A heartbeat line shows that an implementer agent works
The configuration SHALL have the key `implementer.heartbeat` (a duration or `0`, default `2m`). A value other than `0`
MUST be at least `30s`. `0` turns the heartbeat off.

While an implementer agent step runs, the harness SHALL log one INFO line on the `l4` logger every
`implementer.heartbeat`, starting one interval after the agent starts. The line SHALL have the form of the progress
trace (`<unit> [<fix unit>] <message>`) with the message
`task <k> <phase> attempt <n>: <profile> working <elapsed>, <c> tool calls, last activity <t> ago`, where `<c>` is the
count of the stream reader (L4-FAC-012) and `<t>` the time since the agent's last stdout line. When the stream shows
open tool calls, the line SHALL end with `, <m> tool call(s) open for <t>`, where `<t>` is the age of the oldest open
call. For a profile whose adapter has no stream reader (`command`), the message SHALL be
`task <k> <phase> attempt <n>: <profile> working <elapsed>`. Times SHALL be written as `<s>s` under one minute,
`<m>m` under one hour, else `<h>h <m>m`.

The heartbeat MUST NOT be a ledger event, and the line MUST NOT hold text from the agent's stream: only the task, the
phase, the attempt, the profile name, counts and times. An error in the heartbeat MUST NOT end or change the agent
step. The `step.started` progress line SHALL be printed at INFO.

#### Scenario: SCN-IMP-200 (+) Heartbeat lines while an agent works
- **GIVEN** `implementer.heartbeat: 2m`, a fixed clock, and an opencode red step of task 5.2 on the profile `deepseek` whose stream has 14 `tool_use` events in its first 6 minutes and its last line 20 seconds before the third beat
- **WHEN** the step runs for 7 minutes
- **THEN** the log has three INFO lines, the third `task 5.2 red attempt 1: deepseek working 6m, 14 tool calls, last activity 20s ago`, and the ledger has no event for them
- **AND** no line holds a word of the stream's text, and the `agent red step started (task 5.2, attempt 1, deepseek)` line is at INFO

#### Scenario: SCN-IMP-201 (−) No heartbeat when it is off or the step is short; elapsed time only for a command profile
- **GIVEN** in turn: `implementer.heartbeat: 0` and a step of 5 minutes; `implementer.heartbeat: 2m` and a step that ends after 90 seconds; `implementer.heartbeat: 2m` and a `command` profile `my-script` that runs 5 minutes
- **WHEN** each step runs
- **THEN** the first and the second log no heartbeat line, and the third logs `task 1.1 red attempt 1: my-script working 2m` and `task 1.1 red attempt 1: my-script working 4m` with no count
- **AND** a heartbeat callback that raises is logged at DEBUG and the step ends as without it

### Requirement: L4-IMP-024 An idle agent is stopped with a clear reason, and a step that reaches its time limit says so
The configuration SHALL have the key `implementer.idle_timeout` (a duration or `0`, default `10m`). A value other than
`0` MUST be at least `1m`. `0` turns the idle watchdog off. The key SHALL replace the fixed stall limit of the
implementer step: the harness MUST NOT have a second idle threshold for it.

An implementer agent is idle when its stdout has had no line for `implementer.idle_timeout` and its stream reader
(L4-FAC-012) shows no open tool call. The harness SHALL then send SIGINT to the agent's process group, and SIGKILL to
the group when it still runs 5 seconds later, also when the agent prints lines in those 5 seconds. The run's status
stays `timeout`. The harness MUST NOT use the run's
`interrupt` event for this, which is the soft deadline's and gives the status `cancelled`.

The harness SHALL then record `agent.idle{task, phase, attempt, profile, silent_s, tool_calls}` before
`agent.finished`, and the attempt SHALL fail with the reason `the agent showed no activity for <idle_timeout>
(implementer.idle_timeout), so L4 stopped it`. An attempt that ends with status `timeout` without the idle mark SHALL
fail with `the agent step reached its time limit (<limit>)`, where the limit is the step's wall-clock limit (30m).
Both are failed attempts as before: they count against the profile for the escalation (L4-IMP-017) and against
`implementer.max_task_attempts`, and they are not limits (no cool-down). The progress log SHALL print `agent.idle`
at WARNING as `task <k> <phase> attempt <n>: no activity from <profile> for <idle_timeout>; L4 stopped it
(implementer.idle_timeout)`.

While a tool call is open in the stream, the idle clock MUST NOT stop the agent; the step's wall-clock limit still
applies.

#### Scenario: SCN-IMP-202 (+) An idle agent is stopped, recorded, and counts as a failed attempt
- **GIVEN** `implementer.idle_timeout: 10m`, and a red step of task 2.1 on the profile `deepseek` whose agent prints three stream lines with no open call and then nothing
- **WHEN** 10 minutes pass with no line
- **THEN** the agent's process group gets SIGINT, and SIGKILL 5 seconds later if it still runs; the run's status is `timeout`; the ledger has `agent.idle{task: "2.1", phase: "red", attempt: 1, profile: "deepseek", silent_s: 600, tool_calls: …}` before `agent.finished`
- **AND** `task.attempt_failed` has the reason `the agent showed no activity for 10m (implementer.idle_timeout), so L4 stopped it`, the next prompt carries it, and with `escalate_after: 2` and a second profile in `roles.implementer`, two idle attempts move the phase to the second profile

#### Scenario: SCN-IMP-203 (−) An open tool call is not idle; an OpenCode silence is
- **GIVEN** `implementer.idle_timeout: 10m` and, in turn, a codex step whose stream shows `item.started` of a `command_execution` and then nothing for 12 minutes before its `item.completed`, a claude-code step with a `tool_use` block and no `tool_result` for 12 minutes, a kiro-cli step with a `tool_call` and no end for 12 minutes, and an opencode step with no line for 12 minutes
- **WHEN** the steps run
- **THEN** the codex, claude-code and kiro-cli agents are not stopped, and their heartbeat line ends with `1 tool call open for <t>`
- **AND** the opencode agent is stopped at 10 minutes as in SCN-IMP-202, because its stream shows a tool call only when the call ends

#### Scenario: SCN-IMP-204 (−) With the watchdog off, only the time limit stops the step, with its own reason
- **GIVEN** `implementer.idle_timeout: 0` and an agent that prints nothing for 20 minutes, and with the default an agent that prints one line every minute for 30 minutes
- **WHEN** the steps run
- **THEN** the first is not stopped at 20 minutes and no `agent.idle` is recorded; the second is stopped at the step's limit and its attempt fails with `the agent step reached its time limit (30m)`, with no `agent.idle`

#### Scenario: SCN-IMP-205 (−) A heartbeat or idle value below its minimum is refused
- **GIVEN** a configuration with `implementer.idle_timeout: 30s`, then one with `implementer.heartbeat: 5s`, then one with both keys `0`, then one with `10m` and `2m`
- **WHEN** the configuration loads
- **THEN** the first two fail with a message that names the key and its minimum, and the last two load

### Requirement: L4-FAC-012 Each adapter reads its own stream for tool calls, and keeps no text
The adapters `opencode`, `claude-code`, `codex` and `kiro-cli` SHALL each have a stream reader: a pure function that
reads one stdout line of the agent and returns the tool-call signals in it, `start(id)`, `end(id)` or `call` (a call
that ended with no start seen):
- opencode: `call` for each `tool_use` event (the stream shows a call only when it ends);
- claude-code: `start` for each `tool_use` block of an `assistant` event (its `id`), `end` for each `tool_result`
  block of a `user` event (its `tool_use_id`);
- codex: `start` for `item.started` and `end` for `item.completed` of an item of type `command_execution`,
  `file_change`, `mcp_tool_call` or `web_search` (its `item.id`); no other item type is a tool call;
- kiro-cli: `start` for a `sessionUpdate` `tool_call` and `end` for a `tool_call_update` with `status` `completed` or
  `failed` (its `toolCallId`).
The `command` adapter SHALL have no reader. A reader MUST return no signal, and MUST NOT raise, for a line that is not
JSON, not an object or of an unknown shape. A reader MUST NOT keep or return any text of the line.

Every adapter SHALL pass the request's activity watch and its reader to the process runner. The watch SHALL count
each stdout line as activity, count `start` and `call` signals as tool calls (and an `end` with an unknown id), and
keep the open calls by id. A request without a watch (a judge, a probe) SHALL run as before.

#### Scenario: SCN-FAC-20 (+) The readers count the tool calls of the recorded streams
- **GIVEN** the recorded streams `tests/fixtures/recorded/opencode/1.18.33/red-ok.jsonl`, `tests/fixtures/recorded/claude-code/2.1.288/red-ok.jsonl`, `tests/fixtures/recorded/codex/0.160.0/red-ok.jsonl` and `tests/fixtures/recorded/kiro-cli/2.28.0/red-tools.stream.jsonl`
- **WHEN** each stream is read line by line through its adapter's reader into a watch
- **THEN** the tool call count equals the count that the test computes from the stream (`tool_use` events; `tool_use` blocks; started `command_execution` and `file_change` items; `tool_call` session updates), and no call is open at the end
- **AND** the same stream cut just after a call's start has exactly one open call for claude-code, codex and kiro-cli, and none for opencode

#### Scenario: SCN-FAC-21 (−) A reader keeps no text and never fails on a line
- **GIVEN** a line that is not JSON, a JSON array, an event of an unknown type, a codex `item.started` of a `todo_list` item, and an `end` whose id was never started
- **WHEN** each line goes through each reader and a watch
- **THEN** no reader raises; the first four give no signal and still count as activity; the `todo_list` item opens no call; the unknown `end` counts one call and opens none
- **AND** the watch's state holds only numbers, times and call ids
