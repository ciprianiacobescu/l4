Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files and their folder, for example
  `.venv/bin/python -m pytest -q --no-cov tests/unit/agents` (pytest-cov is not installed: keep `--no-cov`).
  Then run `ruff check`, `ruff format --check` and `mypy` on the files that you changed.
- Never wait on a process with `while pgrep -f …`: it matches itself. Run commands in the foreground.
- A test that needs time uses a fake clock, or seconds (`0.2`) passed straight to the watch or to `ProcRunner`. The
  config minimums (`30s`, `1m`) apply to a loaded config only: a bench test sets the keys with
  `cfg.model_copy(update=…)`.
- Stage explicit paths only.
- Every key, field, event, reason, line and rule is in `design.md` (D1 to D10) and in the three spec files. Do not
  change one without the orchestrator.
- Name a consumer "a public consumer repository" and a test repository "a dummy repository". Model names and adapter
  names are fine.
- This change starts after `result-contract` (both waves) is merged into the branch. Do not edit the change folders
  of `result-contract` or `escalate-and-note`.

The fixtures:
- the recorded streams `tests/fixtures/recorded/opencode/1.18.33/red-ok.jsonl` (19 `tool_use` events),
  `tests/fixtures/recorded/claude-code/2.1.288/red-ok.jsonl` (6 calls, all closed),
  `tests/fixtures/recorded/codex/0.160.0/red-ok.jsonl` (4 started items, all completed),
  `tests/fixtures/recorded/kiro-cli/2.28.0/red-tools.stream.jsonl` (20 calls, all closed);
- the bench: `make_bench`, `red_step`, `green_step` (`tests/unit/implementer/conftest.py`), and the fake adapter's
  `Step`;
- `ProcRunner` tests start a real Python child (`tests/unit/agents/test_proc.py`, `run(...)`).

## 0. Contract (orchestrator, before wave 1)

- [ ] 0.1 Contracts with no behaviour:
  - the new module `agents/activity.py`: `Signal` (`kind: Literal["start", "end", "call"]`, `id: str | None`),
    `StreamReader = Callable[[str], tuple[Signal, ...]]`, `Beat` (`elapsed_s`, `tool_calls`, `since_last_s`,
    `open_calls`, `open_for_s`, `counts: bool`), `ActivityWatch(heartbeat_s, on_beat, clock=time.monotonic)` with
    `start(now, reader)`, `line(text)`, `tick(now)`, `has_open_call() -> bool`, `snapshot(now) -> Beat`, the attribute
    `stopped_idle_s: float | None = None`, and the readers `opencode_signals`, `claude_code_signals`,
    `codex_signals`, `kiro_signals`, each raising `NotImplementedError`; the pure helper `ago(seconds) -> str` of
    design D3, implemented (`0` → `0s`, `59` → `59s`, `60` → `1m`, `3599` → `59m`, `3600` → `1h 0m`);
  - `RunRequest.watch: ActivityWatch | None = None` (`agents/base.py`); `ProcRunner.run` accepts
    `watch=None, reader=None` and does not use them yet;
  - the fake adapter's `Step` gains `idle_s: float | None = None` (`agents/fake.py`), not used yet;
  - `ImplementerCfg.heartbeat: DurationOrZero = "2m"` and `idle_timeout: DurationOrZero = "10m"`
    (`config/schema.py`), with no minimum yet;
  - `UnitSnapshot.last_activity: Activity | None = None` and `open_run: OpenRun | None = None` (`state/status.py`),
    with the dataclasses `Activity(ts, type, task, run_id)` and `OpenRun(run_id, started, ci_url)`;
  - `Workbench.run_gate(..., note=None)` and `run_gate_spec(..., note=None)` accept a `Callable[[TestReport], dict]`
    and do not use it yet.

  Tests: the new fields default to `None`; the keys load with their defaults; `ago` gives the five values above;
  `tests/unit/agents` and `tests/unit/config` stay green. [L4-IMP-023] [L4-IMP-024] [L4-FAC-012] [L4-OPS-020]

## 1. Wave 1 (eight agents, disjoint files)

### Agent A: `agents/activity.py`

- [ ] 1.1 The four readers of design D2 and `ActivityWatch` of design D1: `start` keeps the start time and the reader
  (`counts` is `False` without one); `line` counts every line as activity (time of the last line, line count) and
  applies the reader's signals under a lock (tool calls, open calls by id); `tick`
  calls `on_beat(snapshot(now))` when a beat is due (every `heartbeat_s` from the start; none with `heartbeat_s` 0)
  and logs a callback error at DEBUG; `has_open_call`. A `Beat` renders as
  the message tail of design D3 (`beat_text(beat)`: `working 6m, 14 tool calls, last activity 20s ago[, 1 tool call
  open for 4m]`, or `working 6m` with `counts=False`).
  - Test first, in the new file `tests/unit/agents/test_activity.py`: SCN-FAC-20 (the four recorded streams, the
    counts computed in the test, no call open at the end, one open call when cut after a start); SCN-FAC-21; the beat
    times with a fake clock (no beat before the first interval, one per interval, none with 0); `beat_text` for both
    forms and for two open calls (`2 tool calls open for <oldest>`); a callback that raises does not stop `tick`.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/agents/test_activity.py`.
  [L4-FAC-012] [L4-IMP-023] [SCN-FAC-20, SCN-FAC-21]

### Agent B: `agents/proc.py`

- [ ] 1.2 `ProcRunner` with a watch (design D1, D4): `run` calls `watch.start(now, reader)` when the process starts;
  `_pump` calls `watch.line(text)` for each line; `_wait`
  calls `watch.tick(now)` at each poll; the stall rule holds while `watch.has_open_call()`; a stall sends SIGINT to
  the group, waits `INTERRUPT_GRACE_S`, then SIGKILL, keeps `ProcOutcome.stalled`, and sets
  `watch.stopped_idle_s` to the silent seconds. Once the rule has fired, the kill follows after the grace also when
  the agent prints lines in the grace (a latch, as `interrupted_at` of the interrupt path). Without a watch the stall
  rule is today's, now with SIGINT first.
  - Test first, in `tests/unit/agents/test_proc.py` (use a small stand-in object with the watch's methods, not
    `ActivityWatch`, so this agent does not wait for Agent A): a child that traps SIGINT and writes a marker file
    gets SIGINT before the kill; a child that prints a "start" line and then sleeps past `stall_timeout_s` is not
    stopped while the stand-in says a call is open (SCN-IMP-203 at runner level); a silent child with no open call
    is stopped and `stopped_idle_s` is at least the limit; a child that prints a line on SIGINT and then sleeps is
    still killed after the grace; `tick` is called while the child runs.
    `test_stall_watchdog_kills_a_silent_child` stays green.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/agents/test_proc.py`.
  [L4-IMP-024] [SCN-IMP-203]

### Agent C: the adapters (`opencode.py`, `claude_code.py`, `codex.py`, `kiro_cli.py`, `command.py`, `fake.py`)

- [ ] 1.3 Each adapter passes `watch=req.watch` and its reader (`opencode_signals`, `claude_code_signals`,
  `codex_signals`, `kiro_signals`; `None` for `command`) to `self._proc.run`. No status, detail or result changes.
  The fake adapter, for a `Step` with `idle_s`, sets `req.watch.stopped_idle_s = idle_s` (when the request has a
  watch) and returns status `timeout`.
  - Test first, in `tests/unit/agents/test_opencode.py`, `test_claude_code.py`, `test_codex.py`,
    `test_kiro_cli.py`, `test_command.py` and `test_fake.py`: the runner gets the request's watch and the right
    reader; a judge request has no watch and runs as today; the fake `Step(idle_s=600)` sets the mark. Update the
    fake `ProcRunner` classes of these files (and of `test_opencode_provider.py`) to take `watch` and `reader`.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/agents tests/contract/agents tests/unit/llm`.
  [L4-FAC-012]

### Agent D: `config/schema.py`, `state/environment.py`

- [ ] 1.4 The minimums of design D3 and D4 (`heartbeat` 0 or at least `30s`, `idle_timeout` 0 or at least `1m`, each
  error naming the key and its minimum), and `ci_url` in `run_environment` (design D6, with the patterns).
  - Test first, in the new file `tests/unit/config/test_schema_liveness.py`: SCN-IMP-205; in
    `tests/unit/state/test_run_environment.py`: SCN-OPS-36 (the environment part: GitHub with and without an attempt
    above 1, GitLab, no CI, a bad `GITHUB_REPOSITORY`, a server URL with a user part).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/config tests/unit/state/test_run_environment.py`.
  [L4-IMP-023] [L4-IMP-024] [L4-OPS-020] [SCN-IMP-205, SCN-OPS-36]

### Agent E: `state/status.py`

- [ ] 1.5 `last_activity` and `open_run` in `load_snapshot` (design D7, from the merged events), the `LAST` column,
  the two `--unit` lines after `Stopped in run:`, and the two `--json` keys, with `ci_url` expanded by
  `app_forge_urls(...).expand`. `run_status` takes a clock (default: the system clock) for the "ago" values.
  - Test first, in the new file `tests/unit/state/test_status_activity.py`: SCN-OPS-34, SCN-OPS-35, and SCN-OPS-36
    (the `--json` part). Update the tests that pin the table header (`tests/unit/state/test_status_*.py`,
    `tests/unit/cli`) to the new column.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/state tests/unit/cli`.
  [L4-OPS-020] [SCN-OPS-34, SCN-OPS-35, SCN-OPS-36]

### Agent F: `progress.py`

- [ ] 1.6 The lines of design D3, D4 and D9: `step.started` at INFO; `agent.idle` at WARNING as `task <k> <phase>
  attempt <n>: no activity from <profile> for <t>; L4 stopped it (implementer.idle_timeout)`; a `gate.finished` with
  `red_new_failing` as `red: <n> new tests fail, as intended` (one: `red: 1 new test fails, as intended`) at INFO
  and the gate line of today at DEBUG.
  - Test first, in `tests/unit/obs/test_progress.py`: the INFO step line; the `agent.idle` line; SCN-OBS-03 and
    SCN-OBS-04 at the printing level (an event without the key prints as today).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/obs`.
  [L4-IMP-023] [L4-IMP-024] [L4-OBS-004] [SCN-OBS-03, SCN-OBS-04]

### Agent G: the new `ci/step_summary.py`

- [ ] 1.7 `StepSummary(path)`, a ledger observer (design D10): it counts `step.started` per task (and keeps the last
  `agent`), keeps the `task.started` time, and appends the lines of L4-OBS-005; a write error is logged once at
  WARNING. `step_summary_for(environ) -> StepSummary | None` returns one only for `GITHUB_ACTIONS=true` and a set
  `GITHUB_STEP_SUMMARY`.
  - Test first, in the new file `tests/unit/ci/test_step_summary.py`: SCN-OBS-05 and SCN-OBS-06 at the observer
    level (events fed by hand; the file in `tmp_path`).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/ci/test_step_summary.py`.
  [L4-OBS-005] [SCN-OBS-05, SCN-OBS-06]

### Agent H: `yolo/commands.py`

- [ ] 1.8 `_Units.activity` from the snapshots of `_read_units`; `_describe` adds `last_activity` and `open_run` for a
  plan that is `active`, `waiting` or `stopped` (design D8); `_render` prints the two lines after the units.
  - Test first, in the new file `tests/unit/yolo/test_yolo_status_activity.py`: SCN-YOLO-72, with snapshots that
    carry the contract fields (Agent E fills them from a ledger; this test sets them).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/yolo`.
  [L4-YOLO-030] [SCN-YOLO-72]

## 2. Wave 2: the step and the run (two agents, after wave 1)

### Agent I: `implementer/tdd.py`, `implementer/workbench.py`

- [ ] 2.1 `agent_step` (design D3, D4, D11): it builds an `ActivityWatch` with `heartbeat_s` from
  `implementer.heartbeat` and an `on_beat` that logs the INFO line `task <k> <phase> attempt <n>: <profile>
  <beat_text>` on the `l4` logger with the unit id and the fix-unit tag; it sets `stall_timeout_s` from
  `implementer.idle_timeout` (`None` for 0) and the watch on the request; after the run, with
  `watch.stopped_idle_s` set, it records `agent.idle{task, phase, attempt, profile, silent_s, tool_calls}` before
  `agent.finished`; a `timeout` run fails with the idle reason or the time-limit reason of L4-IMP-024. Remove
  `STALL_TIMEOUT_S`.
  - Test first, in the new file `tests/unit/implementer/test_liveness_step.py` (bench): the request's watch and
    `stall_timeout_s` follow the keys, and `0` gives no stall and no beat; the `on_beat` line for a given `Beat`
    (SCN-IMP-200 at the line level, with `caplog`; no ledger event); SCN-IMP-202 with `Step(idle_s=600,
    status="timeout")` (the event, its order, the reason, the next prompt); SCN-IMP-204 with `Step(status="timeout")`
    (the time-limit reason, no `agent.idle`). Change `tests/unit/implementer/test_tdd_red.py:240-244` to the key.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer`.
  [L4-IMP-023] [L4-IMP-024] [SCN-IMP-200, SCN-IMP-202, SCN-IMP-204]
- [ ] 2.2 The red note of design D9: a pure `red_note(base_report) -> Callable[[TestReport], dict]` in `tdd.py`, which
  `run_red` passes to its test gate; `run_gate_spec` merges the returned keys into `gate.finished`. Needs 2.1 (same
  file).
  - Test first, in `test_liveness_step.py`: SCN-OBS-03 and SCN-OBS-04 at the function level (the five cases of
    SCN-OBS-04 with built reports), and one bench red step whose `gate.finished` has `red_new_failing`.
    `tests/unit/implementer/test_tdd_red.py` stays green.
  - Verify: as 2.1.
  [L4-OBS-004] [SCN-OBS-03, SCN-OBS-04]

### Agent J: `orchestrator.py`

- [ ] 2.3 Attach `step_summary_for(app.environ)` next to the progress trace in `observers=[trace]`
  (`orchestrator.py:1428`) when it returns one.
  - Test first, in the new file `tests/unit/orchestrator/test_step_summary_wiring.py`: a unit run on the fake
    adapter with `GITHUB_ACTIONS=true` and `GITHUB_STEP_SUMMARY` in `tmp_path` writes the lines of its done tasks;
    without the variables nothing is written.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/orchestrator`.
  [L4-OBS-005] [SCN-OBS-05]

## 3. Wave 3: end to end (orchestrator, after wave 2)

- [ ] 3.1 One bench test in `test_liveness_step.py` with a small test adapter that runs a Python script through a real
  `ProcRunner` with `codex_signals` and maps a stall to `timeout` (as the codex adapter does), with
  `implementer.heartbeat: 1s` and `implementer.idle_timeout: 2s` (set on the bench config with `model_copy`, which
  skips the minimums): a script that prints a codex `item.started` line and sleeps 4 s is not stopped and logs at
  least two beats; a script that prints one line and sleeps 4 s with no open call is stopped after about 2 s, the
  attempt fails with the idle reason, and `agent.idle` is recorded (SCN-IMP-202, SCN-IMP-203 end to end).
- [ ] 3.2 One test that runs `run_task` with `escalate_after: 2` and two profiles, where the first profile's red steps
  are `Step(idle_s=600, status="timeout")`: the phase moves to the second profile after two idle attempts
  (SCN-IMP-202, the escalation part).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer tests/unit/orchestrator`.
  [L4-IMP-024] [SCN-IMP-202, SCN-IMP-203]

## 4. Integration checks (orchestrator, after wave 2)

- [ ] 4.1 SCN-IMP-201 at the bench: `heartbeat: 0`, a short step, and a `command` profile (beat text with no count).
- [ ] 4.2 The `<forge>` round trip of `ci_url`: a run with `GITHUB_SERVER_URL=https://github.com` on a repository
  whose `origin` is on github.com, once as `https://github.com/owner/repo.git` and once as
  `git@github.com:owner/repo.git`, commits `<forge>/owner/repo/actions/runs/123`, and `l4 status --unit` prints the
  `https://github.com/...` link (design D6, [I] in design section 5).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer tests/unit/state tests/unit/orchestrator`.
  [L4-IMP-023] [L4-OPS-020] [SCN-IMP-201, SCN-OPS-34]

## 5. Docs (one agent, after wave 2)

- [ ] 5.1 Runbook (design D12, L4-OPS-021):
  - section 2: a row "The job runs, and its log has no new line for a long time" that leads to 4.6;
  - a new procedure `### 4.6 Is the job stuck?` after 4.5: read the heartbeat lines (`working <elapsed>, <c> tool
    calls, last activity <t> ago`, and `<m> tool call(s) open for <t>`); the limits (`implementer.idle_timeout`,
    default 10 minutes, and the 30 minutes of one agent step) and the line `no activity from <profile> for <t>`;
    `l4 status --unit` with `Last activity:` and `Open run:`, after the fetch of 4.4; on GitHub
    `gh run list --workflow l4.yml --status in_progress`; the limit that a run shows on the branch only from its
    first step commit, and that a cancelled run shows as open with its age;
  - 4.2: rows for the heartbeat line, the `agent.idle` line, `red: <n> new tests fail, as intended`, and the step
    start line, now at INFO;
  - 4.4: the `LAST` column, and the `Last activity:` and `Open run:` lines of `--unit` and the two `--json` keys;
  - 4.5: `agent.idle{task, phase, attempt, profile, silent_s, tool_calls}` and `run.started.ci_url`;
  - 11: an OpenCode or `command` step with one silent command longer than `implementer.idle_timeout` is stopped (the
    stream shows the call only at its end); `Last activity` can be one step old.
- [ ] 5.2 Skill `references/operate.md`: the `l4 status` line says that `--unit` shows the last activity and the open
  run with its CI link.
- [ ] 5.3 CHANGELOG, in `## 0.4.4 (unreleased)`:
  - Added: the heartbeat line and `implementer.heartbeat`; `implementer.idle_timeout` and `agent.idle`; the `LAST`
    column, `Last activity:` and `Open run:` of `l4 status` and `l4 yolo status`, and `run.started.ci_url`; the red
    gate line; the GitHub job summary; the runbook procedure 4.6;
  - Changed: an idle agent gets SIGINT and 5 seconds before the kill, and is not stopped while a claude-code, codex or
    kiro-cli tool call is open; the reasons of an idle stop and of the step time limit; the step start line is at
    INFO; the keys need the 0.4.4 pin before the config edit (the schema is strict).
  - Test first, in the new file `tests/unit/docs/test_run_liveness_docs.py`: SCN-OPS-37 (the needles of 5.1 and 5.2)
    and `grep`-like checks of the CHANGELOG lines (`implementer.idle_timeout`, `agent.idle`, `Open run:`).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/docs`.
  [L4-OPS-021] [SCN-OPS-37]

## 6. `docs/SPEC.md` (orchestrator)

- [ ] 6.1 §7.7: add L4-IMP-023 and L4-IMP-024 after L4-IMP-012, with the text of `specs/agent-liveness/spec.md`; add
  SCN-IMP-200..205 to §23.7. §8.1: add L4-FAC-012 after L4-FAC-011 (or after L4-FAC-002 if `result-contract` is not
  in the SPEC yet); `RunRequest` gains `watch` and the comment of `stall_timeout_s`; add SCN-FAC-20..21 to §23.6.1.
  §8.1 L4-FAC-002: the `timeout` row says "the step's limit, or `implementer.idle_timeout` (L4-IMP-024)".
  - Verify: `.venv/bin/python scripts/check_spec.py docs/SPEC.md`.
  [L4-IMP-023] [L4-IMP-024] [L4-FAC-012]
- [ ] 6.2 §12.4: add L4-OPS-020 and L4-OPS-021 after L4-OPS-019; L4-OPS-006 says that the table also has `LAST`;
  SCN-OPS-34..37 to §23.19. §12.5: add L4-YOLO-030 after L4-YOLO-029; SCN-YOLO-72 to §23.20. §14: add L4-OBS-004 and
  L4-OBS-005 after L4-OBS-003; L4-OBS-001 names the heartbeat as a transient record; SCN-OBS-03..06 to §23.15.
  - Verify: as 6.1.
  [L4-OPS-020] [L4-OPS-021] [L4-YOLO-030] [L4-OBS-004] [L4-OBS-005]
- [ ] 6.3 §3.2: `heartbeat: 2m   # a log line while an agent step runs; 0 = off (L4-IMP-023)` and
  `idle_timeout: 10m   # stop an agent with no stdout line and no open tool call; 0 = off (L4-IMP-024)` under
  `implementer`. §12.1 L4-STA-001: `agent.idle{task, phase, attempt, profile, silent_s, tool_calls}`,
  `run.started.ci_url`, `gate.finished.red_new_failing`.
  - Verify: as 6.1.
  [L4-IMP-023] [L4-IMP-024] [L4-OPS-020] [L4-OBS-004]
- [ ] 6.4 §21: add row 26 `run-liveness` with its requirement ids (L4-IMP-023..024, L4-FAC-012, L4-OPS-020..021,
  L4-YOLO-030, L4-OBS-004..005) and the live check of task 7.3.
  - Verify: as 6.1.
  [L4-IMP-023]

## 7. Orchestrator: integration, review, live check

- [ ] 7.1 Merge the waves. Run the full suite with `--no-cov`, `ruff check`, `ruff format --check` and `mypy src`. Run
  `openspec validate run-liveness --strict`.
- [ ] 7.2 Adversarial review on the session model, not by the implementers. Try to:
  - get text of the stream (a tool output, a message, a secret) into a heartbeat line, `agent.idle`, the job summary
    or `l4 status`;
  - make the watchdog stop an agent while a claude-code, codex or kiro-cli call is open, or keep an idle agent
    alive with a `todo_list` item or an `end` of an unknown id;
  - leave a process of the agent's group alive after an idle stop;
  - make a judge, a probe or a gate get a watch or a stall limit;
  - change a red verdict with `red_new_failing`, or get the red line for a `TypeError`, an old failing test or a
    collection error;
  - put a link into `ci_url` that is not the run's own (`GITHUB_REPOSITORY`, `GITHUB_SERVER_URL` with a user part,
    a `javascript:` value), or show a sweep run as the open run;
  - make an idle attempt a limit (a cool-down) instead of a failed attempt, or keep it out of the escalation count.
  Record the results in `docs/live/run-liveness/review.md`.
- [ ] 7.3 Live check on a dummy repository (the public GitHub dummy), with `opencode-go/deepseek-v4.1-flash` (key
  `OPENCODE_API_KEY`):
  1. a unit of two tasks: the job log has heartbeat lines every 2 minutes with growing counts, and their times in the
     log match the interval (no buffer); the job summary lists the tasks; the red step shows the red line;
  2. during the run, after its first step commit: `git fetch` as in runbook 4.4, then `l4 status --unit` shows
     `Last activity:` and `Open run:` with the link of the running GitHub run; after the run, no `Open run:`;
  3. on a computer with OpenCode: one `opencode run --format json` with a prompt that runs `sleep 150` and then
     `sleep 700` in its bash tool; record what the stream shows during each call, and whether OpenCode's bash tool
     ends the call on its own (design D5, [U]);
  4. a GitHub re-run of the job (attempt 2): `ci_url` ends with `/attempts/2`.
  Keep the evidence under `docs/live/run-liveness/`. Leave the dummies for the user to delete.
