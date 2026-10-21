# Run liveness: show that an agent works, stop one that does not, and say when a unit last moved

Status: design draft, 2026-10-16. Harness at 0.4.3 plus the change `escalate-and-note` (merged into branch `fix-044`)
and the change `result-contract` (written, not built). Line numbers are at `967c6935` (wave 1 of `result-contract` merged); they can move when its
wave 2 is merged. Markers: **[V]** verified (read in the code at the cited line, or computed from the
recorded data), **[I]** inferred (follows from the code, not run end to end), **[G]** a chosen number with no
measurement behind it, **[U]** not known.

## 0. The answer in ten lines

1. A stall watchdog exists today: 10 minutes with no stdout line kill the agent with SIGKILL, and the attempt fails
   with `status timeout: no detail`. Each agent step also stops after 30 minutes. Nobody can see either limit (1.2) [V].
2. The heartbeat is a log line every `implementer.heartbeat` (default 2m): elapsed time, tool calls, time since the
   last stream line. It holds no stream text and is not a ledger event (D3).
3. A small stream reader for each adapter counts tool calls and knows which calls are open (D2).
4. `implementer.idle_timeout` (default 10m, as today) replaces the constant. An idle agent gets SIGINT, 5 seconds,
   then SIGKILL; `agent.idle` records it; the attempt fails with a reason that names the key (D4).
5. claude-code, codex and kiro-cli show a tool call's start, so an open call holds the idle clock. OpenCode shows a
   call only at its end: a long command there is silence, as today (D5).
6. `run.started` records `ci_url`, the GitHub Actions run or the GitLab job (D6).
7. `l4 status` shows `LAST`, `Last activity:` and `Open run:` from the ledger that the fetch brought. It lags by up to
   one step, because the run's ledger reaches the branch only with a step commit (D7).
8. `l4 yolo status` shows the same for each plan (D8).
9. A red gate that fails only on new tests, in the way that red needs, prints `red: <n> new tests fail, as intended`
   (D9).
10. In GitHub Actions, each task that ends adds one line to the job summary (D10).

## 1. Current state

### 1.1 What the log shows during an agent step

- `step.started` prints `agent <phase> step started (task <k>, attempt <n>, <profile>)` at DEBUG
  (`src/l4/progress.py:264-270`) [V]. The CI templates run without `-v`, so the line is not in the CI log (runbook
  section 11) [V].
- `agent.finished` prints `agent <phase> task <k> <status> (<took>, <model>)` at INFO when the agent ends
  (`progress.py:272-286`) [V].
- Between the two lines the harness prints nothing. `wip_snapshots` takes a local snapshot every 10 minutes and logs
  only a failure (`src/l4/implementer/workbench.py:412-451`) [V].

### 1.2 The limits of one agent step today

| Limit | Where | Value | Action | What the attempt says |
|---|---|---|---|---|
| no stdout line | `STALL_TIMEOUT_S` (`src/l4/implementer/tdd.py:117`), passed at `tdd.py:672`, checked in `ProcRunner._wait` (`src/l4/agents/proc.py:116`) | 600 s | SIGKILL of the process group (`proc.py:131`), `ProcOutcome.stalled` | `the agent step ended with status timeout: no detail` (`tdd.py:708`) |
| wall clock | `RunRequest.timeout_s` default (`src/l4/agents/base.py:162`); `agent_step` does not set it (`tdd.py:665-673`) | 1800 s | SIGKILL of the group, `ProcOutcome.timed_out` | the same text |
| soft deadline | L4-IMP-012 | — | "still to do" (`docs/SPEC.md:2127-2138`); nothing sets `RunRequest.interrupt` [V, `grep`] | — |

- Every adapter maps `timed_out or stalled` to status `timeout` (`opencode.py:236`, `claude_code.py:191`,
  `codex.py:250`, `kiro_cli.py:140`, `command.py:111`) and `interrupted` to `cancelled` (`opencode.py:267`,
  `claude_code.py:218`, `codex.py:292`, `kiro_cli.py:177`, `command.py:114`) [V].
- Only the implementer sets `stall_timeout_s`; a claude-code judge turns it off (`claude_code.py:185`) [V].
- The SPEC names neither limit (`grep` of `stall`, `1800` in `docs/SPEC.md`) [V]. L4-FAC-002 says only "`timeout` |
  harness clock" and notes OpenCode gaps of 30 to 183 s (`docs/SPEC.md:2196`) [V].
- So one silent agent stops after 10 minutes, and one busy agent after 30. A task phase has at most
  `escalate_after` + `max_task_attempts` attempts (2 + 3 with the defaults, L4-IMP-017), so a busy loop can use most
  of a 180-minute job [I].

### 1.3 What each stream shows during a tool call

| Adapter | Start of a call | During the call | End of a call | Source |
|---|---|---|---|---|
| opencode | nothing | nothing | `tool_use` with `state.status` `completed` or `error` and `state.time.start`, `end` | every `tool_use` of the 56 OpenCode streams of `docs/live` and of `tests/fixtures/recorded/opencode/1.18.33` has one of the two end statuses; the event's time is after `time.end` [V] |
| claude-code | `assistant` event with a `tool_use` content block (`id`) | nothing seen | `user` event with a `tool_result` block (`tool_use_id`) | `tests/fixtures/recorded/claude-code/2.1.288/red-ok.jsonl` [V shape]; nothing during a long call [I: the recorded calls last 1 to 2 s] |
| codex | `item.started` (`item.id`, type `command_execution` or `file_change`) | nothing | `item.completed` with the same `item.id` | `tests/fixtures/recorded/codex/0.160.0/red-ok.jsonl`; all codex streams: 336 `command_execution` and 101 `file_change` starts, no other started type [V] |
| kiro-cli | `sessionUpdate` `tool_call` (`toolCallId`) | `tool_call_update` events with no `status` that carry the command's output in parts | `tool_call_update` with `status: completed` | `docs/live/artifacts/job-6211/…/2.1-red-1.jsonl`: 20 starts, 20 ends, 10 output parts, pytest output in three parts [V shape; the stream has no times] |
| command | — | the command's own stdout | — | `command.py` reads no stream [V] |

### 1.4 How long the streams were silent

- In the 56 OpenCode streams of `docs/live` (32 of them implementer steps), the longest time between two events was
  338 s. That gap holds one `task` tool call (a sub-agent) of 325 s
  (`free-impl-nemotron-lightning-shelf/…/1.1-red-3.jsonl`). The next were 305 s (model time, no tool;
  `job-5465/…/1.1-red-2.jsonl`) and 296 s (one judge call). The median longest gap of a stream was 17 s [V, computed
  from the `timestamp` fields].
- Of 212 `agent.finished` events in `docs/live`, none has status `timeout`: 193 `ok`, 12 `error`, 6
  `rate_limited`, 1 other [V]. The 10-minute watchdog never fired in the recorded runs.
- codex and kiro-cli streams carry no times [V]. The recorded claude-code streams are short (largest gap 8 s) [V].
- The public consumer repository's DeepSeek steps took 196 s to 789 s (result-contract design 1.6) [I: no
  transcripts].

### 1.5 The red gate line

`run_red` runs the test gate once after the agent (`tdd.py:772`). The gate prints `gate test fail (exit 1, 12 tests:
5 passed, 7 failed)` at INFO for every failing gate (`progress.py:321-333`) [V]. Only `test-zero` and
`test-presatisfied` get `(expected: …)` (`ZEROED_GATES`, `progress.py:20-22`) [V]. The base report is known before the
agent runs (`base_report = baseline(wb, base)`, `tdd.py:744`) [V], and `classify_red` then judges the new tests by
name and by failure kind (`tdd.py:321-356`) [V]. `task.red_ok` prints `red ok: <n> new test(s) failing as expected`
after the criteria, the pre-satisfied proofs and the static gates (`progress.py:335-341`) [V].

### 1.6 Where the run's ledger is, and when

- During `implementing`, `Workbench.commit` stages the run's ledger with each step commit
  (`workbench.py:330-336`) [V], and the step pushes the unit branch (`tdd.py` `wb.push()` after each red and green
  commit) [V]. A run pushes nothing before its first step commit (`grep` of `push(` in `orchestrator.py` and
  `implementer/`) [V].
- After the hand-off the run's file goes to the lock ref at the end of the run only (`orchestrator.py:1211-1213`,
  `_publish_pending`) [V]. The sweep publishes its own file with `run.finished` (`ci/sweeper.py:214-220`) [V].
- WIP snapshots are local refs, never pushed (`workbench.py:412-418`) [V]. The lock is a local `flock` with no remote
  lease (`src/l4/vcs/locks.py:1-6`) [V].
- `live_run(events)` finds a `run.started` with no `run.finished` (`src/l4/state/pending.py:65-70`); only
  `l4 restart` and `l4 questions` use it, on the pending ledger [V].
- `run.started` records `command`, `branch`, `base`, `source`, `iteration`, the GitLab runner and tool versions
  (`orchestrator.py:1425-1429`, `src/l4/state/environment.py:17-45`) [V]. No CI link.

### 1.7 `l4 status` today

The table has `UNIT, PHASE, REASON, ITER, TASKS, OPEN-Q, VERDICT, SOURCE` (`src/l4/state/status.py:403-427`) [V].
Outside CI the command reads the local refs and does not fetch (`status.py:1-8`, `vcs/refresh.py:35-39`); runbook 4.4
step 1 is the fetch [V]. `l4 yolo status` fetches first (`_sync`, `yolo/commands.py:182-192`) and reads every unit's
snapshot through `discover` (`_read_units`, `yolo/commands.py:239-245`) [V]. Nothing writes `$GITHUB_STEP_SUMMARY`
[V, `grep`].

## 2. Decisions

### D1. One activity watch for each agent step

- A new module `src/l4/agents/activity.py` holds `ActivityWatch`. `agent_step` makes one for each step and puts it in
  the new field `RunRequest.watch` (default `None`). Every adapter passes it to `ProcRunner.run(..., watch=req.watch,
  reader=<its reader>)`. A judge, a probe and every other caller sets no watch, so nothing changes for them.
- `ProcRunner.run` calls `watch.start(now, reader)` when the process starts: the start time, and whether the step has
  counts (a reader) or the elapsed time only (no reader, `command`). `ProcRunner._pump` (its own thread) calls
  `watch.line(text)` for each stdout line. The watch keeps, under a lock: the start time, the time of the last line,
  the line count, the tool call count, and the open calls (id to start time). It never keeps the text.
- `ProcRunner._wait` (the thread of `agent_step`) calls `watch.tick(now)` at each poll (every 50 ms). `tick` calls the
  beat callback when a beat is due. A callback that raises is logged at DEBUG and the step goes on.
- The idle rule stays in `_wait` with `stall_timeout_s`, which now comes from `implementer.idle_timeout` (D4).
  `_wait` asks the watch whether a call is open. When the rule fires, `_wait` writes the silent seconds into
  `watch.stopped_idle_s`, which `agent_step` reads after the run. No adapter changes its `RunResult`.
- Why not `RunRequest.interrupt`: an interrupted run is status `cancelled` in every adapter (1.2), and the event
  belongs to the soft deadline and to a cancel (L4-IMP-012, L4-CLI-003). Why not a new `RunResult` field: the watch
  belongs to `agent_step`, so the adapters' result parsing does not change.

### D2. A stream reader for each adapter (L4-FAC-012)

A reader is a pure function `(line) -> tuple[Signal, ...]` that reads one stdout line. A line that is not JSON gives
no signal, but it is still activity. `Signal` is `start(id)`, `end(id)` or `call` (a call that ended with no start
seen).

| Adapter | `start(id)` | `end(id)` | `call` |
|---|---|---|---|
| opencode | — | — | each `tool_use` event |
| claude-code | each `tool_use` block of an `assistant` event (`id`) | each `tool_result` block of a `user` event (`tool_use_id`) | — |
| codex | `item.started` of an item of type `command_execution`, `file_change`, `mcp_tool_call` or `web_search` (`item.id`) | `item.completed` of the same types (`item.id`) | — |
| kiro-cli | `sessionUpdate` `tool_call` (`toolCallId`) | `sessionUpdate` `tool_call_update` with `status` `completed` or `failed` (`toolCallId`) | — |
| command | no reader: the heartbeat shows the elapsed time only | | |

- The tool call count is the number of `start` and `call` signals, plus an `end` with an unknown id.
- An `end` with an unknown id opens nothing. A `start` with an id that is already open counts once.
- The codex list is closed: a `todo_list` or `reasoning` item, which can stay open for the whole turn, never holds the
  idle clock [I: such items are not in the recorded streams].
- A reader reads only the keys above. No text of the stream leaves the reader.

### D3. The heartbeat line (L4-IMP-023)

- Key `implementer.heartbeat`, `DurationOrZero`, default `2m`; `0` turns it off; a value other than `0` is at least
  `30s` [G].
- The first line comes one interval after the agent starts, then one every interval. A step that ends sooner prints
  none.
- The line is INFO on the `l4` logger, in the form of the progress trace (`[l4] <unit> [<fix unit>] <message>`):

  ```
  task 5.2 green attempt 1: deepseek working 6m, 14 tool calls, last activity 20s ago
  task 5.2 green attempt 1: deepseek working 8m, 15 tool calls, last activity 4m ago, 1 tool call open for 4m
  task 5.2 green attempt 1: my-script working 6m
  ```

  The last form is the `command` adapter. The profile is `wb.selected.profile_name`. "last activity" is the time
  since the last stdout line. The open part shows only when a call is open; its time is that of the oldest open call.
- Times: under 60 s `<s>s`; under one hour `<m>m` (whole minutes, rounded down); else `<h>h <m>m`. One helper
  `ago(seconds)` in `activity.py` serves the heartbeat, `agent.idle` and `l4 status`.
- The line is not a ledger event: a ledger line every 2 minutes would add up to 7 lines to each step and to each
  commit, with no use after the run. It is a transient record of L4-OBS-001: the console and the JSONL log.
- The `step.started` line moves from DEBUG to INFO, so that the log shows at once which step runs.
- The line holds the task, the phase, the attempt, the profile name, numbers and times. The log formatter redacts it
  again, as every line (`progress.py:3-5`) [V].

### D4. The idle watchdog (L4-IMP-024)

- Key `implementer.idle_timeout`, `DurationOrZero`, default `10m`; `0` turns the watchdog off; a value other than `0`
  is at least `1m` [G]. It replaces `STALL_TIMEOUT_S`: `agent_step` sets `stall_timeout_s` from the key, or `None`
  for `0`. The constant is removed, so there is one threshold.
- **The rule.** The agent is idle when its stdout has had no line for `idle_timeout` and the watch has no open call.
  Then `_wait` sends SIGINT to the process group, waits `INTERRUPT_GRACE_S` (5 s), and sends SIGKILL to the group if
  it still runs. `ProcOutcome.stalled` stays the flag, so every adapter still reports `timeout` (1.2).
- **The record.** After the run, when `watch.stopped_idle_s` is set, `agent_step` records
  `agent.idle{task, phase, attempt, profile, silent_s, tool_calls}` with `wb.emit` (so a fix unit's step carries
  `fix_unit`), before `agent.finished`. `silent_s` is a whole number of seconds. The event holds no stream text.
- **The attempt** fails with `the agent showed no activity for <idle_timeout> (implementer.idle_timeout), so L4
  stopped it`. A `timeout` without the idle mark fails with `the agent step reached its time limit (<timeout>)`.
  Both replace `the agent step ended with status timeout: no detail`; every other status keeps its text. Neither has
  the `result values:` excerpt.
- **What counts.** The attempt is a failed attempt as today: it counts against the profile for the escalation
  (L4-IMP-017) and against `max_task_attempts`. It is not a limit: no `RoleLimit`, no cool-down. The retry prompt
  carries the reason, so the model knows that a silent wait cost the attempt.
- **Progress.** `agent.idle` prints at WARNING: `task 2.1 red attempt 1: no activity from deepseek for 10m; L4 stopped
  it (implementer.idle_timeout)`.
- **Why 10m.** It is the threshold of today, and in 212 recorded agent runs it never fired (1.4). The longest
  recorded silence is 338 s, so 10m leaves a margin of 1.8 times. A longer default would make a hung agent cost more
  for no measured gain. `0` would leave only the 30-minute limit, which is worse than today. A project with long
  silent commands raises the key.

### D5. A long tool call is not idle when the stream shows it

- claude-code, codex and kiro-cli: an open call holds the idle clock (D2, 1.3). Its cap is the step's 30-minute
  limit. A call whose end never comes holds the clock until then [I].
- kiro-cli also prints a command's output while it runs (1.3), so a long test run there is not silence anyway [V
  shape].
- opencode: a call is seen only when it ends (1.3). A long command or a sub-agent (`task` tool) in an OpenCode step is
  silence, exactly as with today's watchdog. The recorded maximum is 325 s for a sub-agent (1.4). OpenCode's own bash
  tool has a time limit of its own [U: value not checked]. Task 7.3 measures what a long call does on OpenCode.
- command: the command's stdout is the only signal, as today.
- The harness gives the agent's pytest the per-test limit `gates.test_timeout` (`trace_env`, `tdd.py:655`; `auto` is
  the smaller of 10 minutes and half of `gates.timeout`) [V]. It bounds one test, not a whole test run.
- Not done here: process-tree activity (a live child process of the agent) for OpenCode and `command` steps (D13).

### D6. `run.started.ci_url` (L4-OPS-020)

- `run_environment` (`state/environment.py`) adds `ci_url` when it can build one, and `run.started` records it
  (`orchestrator.py:1428`):
  - GitHub Actions (`GITHUB_ACTIONS=true`): `<GITHUB_SERVER_URL>/<GITHUB_REPOSITORY>/actions/runs/<GITHUB_RUN_ID>`,
    with `/attempts/<GITHUB_RUN_ATTEMPT>` when the attempt is above 1 [recall: the URL shape; task 7.3 checks it];
  - GitLab CI (`GITLAB_CI=true`): `CI_JOB_URL`;
  - else no key.
  Each part must match a plain pattern (an `https` URL with no user part, `owner/name`, digits); else no key [G].
- The run ledger's file filter writes the forge host as `<forge>` in what the harness commits (L4-OBS-002,
  `file_filter=app_forge_urls(app, cfg).scrub`, `orchestrator.py:1428`) [V]. `GITHUB_SERVER_URL` is one of the
  variables that give the forge's hosts, and an ssh `origin` gives its https host (`src/l4/forge/urls.py:28, 76-81`)
  [V]. `l4 status` expands the placeholder as it does for `pr` (`status.py`, `urls.expand`) [V for `pr`; I for this
  key].
- The link is shown, never fetched. An older ledger has no `ci_url`, and status then shows none.

### D7. Last activity and the open run in `l4 status` (L4-OPS-020)

- `load_snapshot` (`status.py:159-208`) already merges the branch ledger and the lock ref's pending ledger
  (`status.py:175`) [V]. From those events it sets two new snapshot fields:
  - `last_activity`: the event with the newest `ts` (on a tie, the last one read): its `ts`, `type`, `task` when the
    event has one, and `run_id`;
  - `open_run`: the newest `run.started` with `command: "run"`, when the same run has no `run.finished`: its
    `run_id`, its `ts` and its `ci_url`.
- **Table:** a column `LAST` after `VERDICT`: `6m ago`, or `-` with no event.
- **`--unit`:** after `Stopped in run:`, the lines
  `Last activity: 6m ago (task.red_ok, task 2.1, run r-20261016T0953Z-0474)` and, with an open run,
  `Open run: r-20261016T1101Z-1a2b started 14m ago, no end recorded: <url>` (no `: <url>` without a link).
- **`--json`:** `last_activity{ts, type, task?, run_id}` and `open_run{run_id, started, ci_url?}`, or `null`. The
  `l4/status@1` shape gains keys only; no JSON schema file pins it (`src/l4/schema/` holds only
  `outcome.schema.json`) [V].
- **The limit, said in the runbook.** The ledger reaches the branch only with a step commit, and the lock ref only at
  the end of a run after the hand-off (1.6). So `Last activity` can be one step old (5 to 15 minutes on the consumer),
  and a run is not seen before its first step commit. A run that a cancel or a lost runner ended also has no recorded
  end; its age shows that. The live view is the CI log (the heartbeat) through the `Open run:` link, or
  `gh run list --workflow l4.yml --status in_progress`.
- "ago" is computed from the clock of the computer that runs the command. A test passes a fixed clock.

### D8. `l4 yolo status` (L4-YOLO-030)

- `_Units` gains `activity: dict[str, (last_activity, open_run)]` from the snapshots that `_read_units` already
  reads (`yolo/commands.py:239-245`) [V].
- For a plan that is `active`, `waiting` or `stopped`, `_render` adds after the units:
  `  last activity: 6m ago (task.red_ok, task 2.1, unit openspec:add-x)`, from the newer of the current unit's
  `last_activity` and the plan ledger's newest event (`PlanEvent.at`, `yolo/model.py:185-188`); and
  `  open run: … started 14m ago, no end recorded: <url>` for the current unit's open run. A plan event shows as
  `(<type>)`.
- `--json`: each plan gains `last_activity` and `open_run`. `l4/yolo-status@1` gains keys only.
- `plan_lines` of `l4 status` does not change.

### D9. The red gate line (L4-OBS-004)

- `Workbench.run_gate` and `run_gate_spec` gain `note: Callable[[TestReport], dict] | None`. When it is given and the
  report is readable, `gate.finished` gets the keys it returns.
- `run_red` passes a note for its test gate (`tdd.py:772`) that returns `{"red_new_failing": n}` when all of these
  hold, else `{}`:
  - the gate status is `fail`;
  - at least one test fails or errors;
  - every failing or erroring test is new (`new_test_ids(base_report, report)`, the helper of `classify_red`);
  - each of them failed by assertion or with `NotImplementedError` (`failure_kind` not `None` and not `other`, the
    rule of `classify_red` with `failure_kinds=True`, `tdd.py:353-356`) and none carries the hang marker;
  - the report has no collection error that the base report does not have.
- `progress._gate`: an event with `red_new_failing` prints `red: <n> new tests fail, as intended` at INFO (`red: 1 new
  test fails, as intended` for one), and the raw gate line at DEBUG. Every other gate prints as today.
- The note changes no verdict. `classify_red` still decides. A later check (criteria, pre-satisfied proofs, static
  gates) can still fail the attempt, and its line follows.
- `run_single` and `run_green` pass no note: a failing test there is a failure.

### D10. The GitHub job summary (L4-OBS-005)

- A new ledger observer `StepSummary` (`src/l4/ci/step_summary.py`) is attached next to the progress trace
  (`orchestrator.py:1428`) when `GITHUB_ACTIONS` is `true` and `GITHUB_STEP_SUMMARY` names a file.
- It appends one Markdown list line for each task that ends:
  - `task.done` (TDD): `- <unit> task <k>: done (<n> attempts, <profile>, <took>)`;
  - `task.red_ok` with `tdd: already-satisfied`: `- <unit> task <k>: already satisfied (no green step)`;
  - `task.done` with `tdd: already-done`: `- <unit> task <k>: done (closed with no open required task)`;
  - `breaker.tripped`: `- <unit> task <k>: halted (<reason code>)`.
  A fix unit's line has `[<fix unit>]` after the unit. `<n>` is the count of `step.started` events of the task in
  this run, `<profile>` the `agent` of the last one, `<took>` the time from `task.started` (D3 format).
- No text of an agent or of a person: no notes, no failure reasons, only ids, codes, numbers and the profile name.
- A failed write is logged once at WARNING; the run goes on.
- GitLab has no job summary file [I]; the observer is not attached there.

### D11. Relation to `result-contract` and `escalate-and-note`

- `escalate-and-note` is merged into the branch (`docs/SPEC.md` has L4-IMP-017..018) [V]. An idle attempt counts
  against its profile like any failed attempt.
- `result-contract` changes `agent_step` (its D2 order), `agents/base.py`, the five adapters and `progress.py`. This
  change starts after `result-contract` is merged. Its `agent_step` edit sits in step 2 of that order: a run with
  status `timeout` has no `result_problem`, so it is a failed attempt, and this change only gives that case its
  reason. `agent.idle` comes before `agent.finished`.
- Both changes add lines to `## 0.4.4 (unreleased)` of the CHANGELOG.

### D12. Docs

- SPEC: L4-IMP-023..024 in §7.7 after L4-IMP-012; L4-FAC-012 in §8.1 after L4-FAC-002 (and after L4-FAC-010..011 of
  `result-contract`); L4-OPS-020..021 in §12.4 after L4-OPS-019; L4-YOLO-030 in §12.5 after L4-YOLO-029; L4-OBS-004..005
  in §14 after L4-OBS-003; the scenarios in §23.7, §23.6.1, §23.19, §23.20 and §23.15; the amendments of the proposal;
  §21 row 26.
- Runbook: section 2 gets a row "The job runs and its log is silent"; a new procedure 4.6 "Is the job stuck?"; the
  rows of 4.2; the `LAST` column and the two lines in 4.4; `agent.idle` and `run.started.ci_url` in 4.5; two limits
  in 11.
- Skill `references/operate.md`: the `l4 status` line says that it shows the last activity and the open run.
- CHANGELOG: lines under Added and Changed of `## 0.4.4 (unreleased)`.

### D13. Not in this change

- **A remote liveness signal between step commits:** the lease heartbeat push of L4-LCK-001 (`locks.lease`, SPEC
  §12.2) or the WIP push of L4-IMP-011. Either would let `l4 status` see a run before its first step commit. Both
  need pushes during the step.
- **The soft-deadline SIGINT** of L4-IMP-012. This change uses the same signal order for an idle agent only.
- **Process-tree activity** for OpenCode and `command` steps.
- **Heartbeats for the gates** (`gates.timeout` 30m), the judges and the verifier's agent steps.
- **A forge API call** that asks whether the open run still runs.
- **A GitLab job summary.**

## 3. Cases

| Case | Today | After this change |
|---|---|---|
| An OpenCode step of 9 minutes with 30 tool calls | log silent for 9 minutes | 4 heartbeat lines, then `agent … ok` |
| An agent whose provider hangs (no line for 10m) | SIGKILL, `status timeout: no detail` | SIGINT, 5 s, SIGKILL; `agent.idle`; `no activity for 10m (implementer.idle_timeout)` |
| A codex step whose test command runs 12 minutes | killed at 10m of silence | not idle: the call is open; the heartbeat shows `1 tool call open for 12m` |
| A claude-code step with a 12-minute Bash call | killed at 10m | not idle (open call) [I: Claude Code's own Bash limit may end the call first, U] |
| An OpenCode step with a 12-minute bash call | killed at 10m | the same, and the heartbeat showed `last activity 9m ago` before |
| A kiro-cli step with a long pytest that prints | not killed (lines) | not killed; the call is also open |
| An agent busy for 30 minutes | SIGKILL, `status timeout: no detail` | the same kill; `the agent step reached its time limit (30m)` |
| `implementer.idle_timeout: 0` | — | no idle rule; the 30-minute limit stays |
| `implementer.heartbeat: 0` | — | no heartbeat line |
| A red gate where only the 7 new tests fail by assertion | `gate test fail (exit 1, …, 7 failed)` at INFO | `red: 7 new tests fail, as intended`; raw line at DEBUG |
| A red gate where a new test fails with `TypeError` | the raw line | the raw line at INFO; the attempt line follows |
| A red gate where an old test fails too | the raw line | the raw line at INFO |
| `l4 status` during `implementing`, 6 minutes after the last step commit | no time | `LAST 6m ago`; `Open run: … started 21m ago, no end recorded: <link>` |
| `l4 status` 3 minutes after a run started, before its first commit | no time | the previous run's last event; no open run yet |
| A run cancelled after its first commit | no time | `Open run:` with its age, for ever, until a later run starts [I: the cancel pushes nothing] |
| An older ledger with no `ci_url` | — | `Open run: … no end recorded` with no link |
| A task done in GitHub Actions | nothing in the summary | `- openspec:add-x task 2.1: done (2 attempts, deepseek, 11m)` |

## 4. Risks

- **An OpenCode step with one long silent call is still stopped at 10 minutes** (D5). This is today's behaviour; the
  heartbeat now shows it, the reason names the key, and a project can raise it. The recorded maximum is 325 s [V].
- **A held clock can hide a hang inside a tool call** of claude-code, codex or kiro-cli until the 30-minute limit
  (D5). A test that hangs is bounded by the per-test limit [V]; a hung non-test command is not.
- **SIGINT before SIGKILL adds up to 5 s** to an idle stop. A CLI that ignores SIGINT is killed after them, and a CLI
  that prints a line on SIGINT does not reset the stop: the kill is latched once the rule fires (task 1.2) [I].
- **`Last activity` lags by one step and can show a dead run as open** (D7). The runbook says so, and the age and the
  link let a person check.
- **`ci_url` is a link that the harness commits.** It names the repository and the run id, which the forge already
  shows on the unit branch's commits; the host is `<forge>` in the commit (D6) [I].
- **The red line can say "as intended" and the attempt can still fail** on a later check (D9). The attempt line
  follows and names the cause.
- **A heartbeat callback runs on the thread that waits for the agent.** A slow log handler delays the poll by its own
  time only; a callback error is caught (D1) [I].

## 5. Not verified

- What the claude-code and codex streams show during a call that lasts minutes: the recorded calls last seconds [I].
- Whether a kiro-cli `tool_call_update` ends a call with `failed` or another status: only `completed` was recorded
  [I].
- OpenCode's own bash time limit, and Claude Code's Bash limit, inside an implementer step [U]. Task 7.3 measures the
  OpenCode case.
- How each CLI reacts to SIGINT in the sandbox within 5 s [U].
- The GitHub Actions run URL form with `/attempts/<n>` [recall].
- The `<forge>` round trip of `ci_url` end to end (the filter reads `GITHUB_SERVER_URL` [V]); task 4.2 tests it with
  an https and an ssh `origin`.
- That INFO lines reach the GitHub and GitLab logs at once through the CI step (no buffer) [I]; task 7.3 looks at the
  times in the job log.
- The consumer's step times (196 s to 789 s) come from job logs without transcripts [I].
