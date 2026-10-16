## Why

The owner of a public consumer repository asked: "How can I see if the job is stuck or not? From the logs it is hard."
The evidence (2026-10-16, design section 1) is the consumer's job logs, the code at branch `fix-044`, and the 56
recorded OpenCode streams and 212 `agent.finished` events of `docs/live`.

1. **The log is silent while an agent works.** An implementer step takes 5 to 15 minutes on a hosted runner. The
   progress trace prints the step start at DEBUG only (`src/l4/progress.py:264-270`) and one INFO line when the agent
   ends (`progress.py:272-286`). Between the two, the CI log shows nothing.
2. **A stall watchdog exists, but nobody can see it.** `STALL_TIMEOUT_S = 600.0` (`src/l4/implementer/tdd.py:117`)
   kills an agent that prints no line for 10 minutes (`src/l4/agents/proc.py:116`), with SIGKILL and no SIGINT
   first. Every adapter then reports `timeout`, and the attempt fails with `the agent step ended with status timeout:
   no detail` (`tdd.py:708`). The same text comes from the 30-minute limit of each agent step (`RunRequest.timeout_s`
   default 1800, `src/l4/agents/base.py:162`; `agent_step` does not set it). The SPEC names neither limit, no key
   changes them, and the stall rule does not know that a tool call is running. So the premise "a hung agent sits until
   the job's 180-minute limit" is not true for one step: a silent agent stops after 10 minutes and a busy one after
   30. A job can still use its 180 minutes over several attempts.
3. **A red step looks like a failure.** The red step's test gate fails on purpose, but the log prints
   `gate test fail (exit 1, 12 tests: 5 passed, 7 failed)` at INFO (`progress.py:321-333`). The line that says that
   this is correct (`task <k> red ok: <n> new test(s) failing as expected`) comes later, after the criteria and the
   static gates.
4. **`l4 status` has no time.** It shows the phase, the tasks and the questions (`src/l4/state/status.py:403-427`),
   but not when the unit last moved, nor which CI run works on it now. The only signal is the unit branch's commits:
   the run's ledger reaches the branch with each step commit (`src/l4/implementer/workbench.py:330-336`), and reaches
   the lock ref only after the hand-off (`src/l4/orchestrator.py:1211-1213`). `run.started` records no CI link
   (`src/l4/state/environment.py`).

## What Changes

- **A heartbeat line** every `implementer.heartbeat` (default `2m`, `0` = off) while an implementer agent step runs:
  `task 5.2 green attempt 1: deepseek working 6m, 14 tool calls, last activity 20s ago`. It holds counts and times
  only, never text from the stream. The harness gets the counts from the stdout lines that it already copies
  (`ProcRunner._pump`), with one small stream reader for each adapter: opencode, claude-code, codex and kiro-cli. The
  `command` adapter gets the elapsed time only. The line goes to the console and the JSONL log, not to the ledger.
  The step start line moves from DEBUG to INFO.
- **An idle watchdog that people can see.** `implementer.idle_timeout` (default `10m`, the threshold of today; `0` =
  off) replaces `STALL_TIMEOUT_S`. When the agent's stdout has no line for that long, and the stream shows no tool
  call that is still open, the harness sends SIGINT to the agent's process group, waits 5 seconds, then kills the
  group. It records `agent.idle{task, phase, attempt, profile, silent_s}`. The attempt fails with the reason `the
  agent showed no activity for 10m (implementer.idle_timeout), so L4 stopped it`. It counts like every failed attempt,
  so the escalation of `escalate-and-note` and the retry can act. A step that reaches its 30-minute limit now fails
  with `the agent step reached its time limit (30m)`.
- **Long tool calls.** claude-code, codex and kiro-cli show the start of a tool call in the stream, so the idle clock
  does not run while a call is open. The 30-minute step limit still applies. OpenCode shows a tool call only when it
  ends, so a long command in an OpenCode step is silence, as today (design D5).
- **`l4 status` shows the last activity and the open run.** The table gets a `LAST` column (for example `6m ago`).
  `l4 status --unit` gets `Last activity: 6m ago (task.red_ok, task 2.1, run <id>)` and, when the newest run has no
  recorded end, `Open run: <id> started 14m ago, no end recorded: <url>`. `--json` gets `last_activity` and
  `open_run`. The data is the unit's ledger on the branch and on the lock ref, as the fetch left them. `run.started`
  records `ci_url`: the GitHub Actions run, or the GitLab job.
- **`l4 yolo status`** shows the same two lines for each plan, from its current unit and its plan ledger.
- **A clear red line.** When the red step's test gate fails and every failing test is new and fails the way that red
  needs, the log prints `red: 7 new tests fail, as intended` at INFO. The raw gate line stays, at DEBUG.
- **A GitHub job summary.** Inside GitHub Actions, the harness writes one line for each task that ends (done, already
  satisfied, or halted) to `$GITHUB_STEP_SUMMARY`.
- **Docs.** `docs/SPEC.md` rows, a runbook procedure "Is my job stuck?", the runbook rows of 4.2, 4.4 and 4.5, one
  line in the skill's `operate.md`, and CHANGELOG lines in `## 0.4.4 (unreleased)`.

Not in this change (design D13):
- a heartbeat push to the lock ref (the lease of L4-LCK-001) or a WIP push (L4-IMP-011), which would show liveness
  between step commits;
- the SIGINT of the soft deadline (L4-IMP-012, still to do);
- process-tree activity for OpenCode and `command` steps;
- heartbeats for gates, judges and the verifier's agents;
- a GitLab job summary.

## Capabilities

### New Capabilities

- `agent-liveness`: the heartbeat line (L4-IMP-023), the idle watchdog and the time-limit reason (L4-IMP-024), and
  what each adapter's stream reader reports (L4-FAC-012).
- `run-activity-status`: the last activity and the open run in `l4 status` (L4-OPS-020), the runbook procedure "Is my
  job stuck?" (L4-OPS-021), and the same lines in `l4 yolo status` (L4-YOLO-030).
- `progress-wording`: the red gate line (L4-OBS-004) and the GitHub job summary (L4-OBS-005).

### Modified Capabilities

None as an OpenSpec delta: `openspec/specs/` holds no baseline (only `.gitkeep`). Section 6 of `tasks.md` holds the
`docs/SPEC.md` work:
- the new requirements L4-IMP-023..024, L4-FAC-012, L4-OPS-020..021, L4-YOLO-030 and L4-OBS-004..005, with
  SCN-IMP-200..205, SCN-FAC-20..21, SCN-OPS-34..37, SCN-YOLO-72 and SCN-OBS-03..06;
- the amendments of L4-FAC-001 (`RunRequest`), L4-FAC-002 (the `timeout` row), L4-OBS-001, L4-OPS-006, L4-STA-001
  (event list), §3.2 (two keys) and §21 (row 26).

## Impact

- **Code:**
  - a new `src/l4/agents/activity.py`: the watch, the stream readers, the beat text;
  - `src/l4/agents/proc.py` (the watch in `_pump` and `_wait`, SIGINT before the kill of a stall);
    `src/l4/agents/base.py` (`RunRequest.watch`); `opencode.py`, `claude_code.py`, `codex.py`, `kiro_cli.py`,
    `command.py` (pass the watch and their reader); `fake.py` (`Step.idle_s`);
  - `src/l4/implementer/tdd.py` (`agent_step`: the watch, `agent.idle`, the two reasons; `run_red`: the red note of
    the gate; `STALL_TIMEOUT_S` removed); `src/l4/implementer/workbench.py` (`run_gate` passes a note to
    `gate.finished`);
  - `src/l4/config/schema.py` (`implementer.heartbeat`, `implementer.idle_timeout`);
  - `src/l4/progress.py` (the `step.started` level, the `agent.idle` line, the red gate line); a new
    `src/l4/ci/step_summary.py` (the GitHub job summary observer), attached in `src/l4/orchestrator.py`;
  - `src/l4/state/environment.py` (`ci_url`), `src/l4/state/status.py` (`last_activity`, `open_run`),
    `src/l4/yolo/commands.py` (the plan lines).
- **Docs:** `docs/SPEC.md`, `docs/runbook.md`, `plugins/l4/skills/l4/references/operate.md`, `CHANGELOG.md`.
- **Config:** two new keys under `implementer`. The schema is strict, so a consumer moves its pin to 0.4.4 before it
  sets them.
- **Ledger:** a new event `agent.idle`; `run.started` gains `ci_url`; `gate.finished` gains `red_new_failing`. An
  older ledger folds and reads as before; its units show no `ci_url`.
- **Behaviour:** an idle agent gets SIGINT and 5 seconds before the kill. Steps of claude-code, codex and kiro-cli
  are not stopped while a tool call is open. Every other limit stays as today: 10 minutes of silence and 30 minutes
  for each step.
