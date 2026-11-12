## 1. The adapters say whether calls are open (D1)

- [x] 1.1 Write the test first (in `tests/unit/agents/test_base.py` or `test_activity_contract.py`): `capabilities()
  .open_calls` is False for `OpencodeAdapter`, the OpenCode 2 adapter and the command adapter, and True for claude-code,
  codex, kiro-cli, copilot-cli and the fake. Run it and see it fail.
- [x] 1.2 Then add `open_calls: bool = True` to `AgentCaps` (`src/l4/agents/base.py`) and set it to False in
  `opencode.py`, `opencode_v2.py` and `command.py` (keyword argument). Run `uv run --frozen pytest tests/unit/agents -q`.

## 2. The longest gate run (D2)

- [x] 2.1 Write the tests first (a new `tests/unit/implementer/test_idle_gate_floor.py`, with the `make_bench` fixtures of
  `tests/unit/implementer/conftest.py`): after `run_gate("baseline", <test command>)` and `run_gate("lint-baseline",
  <lint command>)` with known durations (monkeypatch the clock or the runner so `GateResult.seconds` is set), `wb.gate_peak`
  is the longer one with its name; a `test-base-run`, a `setup`, an `e2e` run, a run whose command is not the configured
  one, a run that timed out and a run stopped by the deadline do not change it. Run them and see them fail.
- [x] 2.2 Then add `gate_peak` to `Workbench` (`src/l4/implementer/workbench.py`, set to None per unit run like the other
  per-run fields) and update it in `run_gate_spec` as design D2 says. Run the new tests and
  `uv run --frozen pytest tests/unit/implementer/test_workbench*.py tests/unit/gates -q`.

## 3. The limit, the event and the texts (D3, D4, D5)

- [x] 3.1 Write the tests first in `test_idle_gate_floor.py`, building the step as `tests/unit/implementer/test_liveness_step.py`
  does (a fake adapter whose caps say `open_calls=False`, the request captured):
  - SCN-IMP-537: `stall_timeout_s == 632.0` for a peak of 381 s and `idle_timeout: 5m`; with `open_calls=True` 300.0;
  - SCN-IMP-539: no peak → 300.0; `idle_timeout: 0` → None; a peak of 1400 s → 1800.0;
  - SCN-IMP-538: a run that the watchdog stopped (`watch.stopped_idle_s` set, status `timeout`, tool calls > 0): the
    `agent.idle` event holds `limit_s: 632` and `raised_by: {"gate": "baseline", "seconds": 381}`, and the attempt's reason
    is the text of the scenario; with no raise the event has `limit_s: 300`, no `raised_by`, and today's reason;
  - SCN-IMP-540: a silent stop with two implementer profiles: `agent.idle{silent: true, limit_s: 632}` and the limit
    signal's detail `no output for 10m`;
  - the progress line (`tests/unit/test_progress*.py`, find the `agent.idle` case with `grep -rn "_agent_idle\|no activity
    from" tests/unit`): an event with `raised_by` prints `(implementer.idle_timeout, raised to 10m for the longest gate
    run)`; one without prints today's line.
  Run them and see them fail.
- [x] 3.2 Then change `agent_step` (`src/l4/implementer/tdd.py`), the silent limit text, `_previous_attempt_block` and
  `src/l4/progress.py` as D3 and D4 say. Run the new tests and `uv run --frozen pytest tests/unit/implementer/test_liveness_step.py
  tests/unit/implementer/test_step_deadline.py tests/unit/implementer/test_tdd_red.py tests/unit/agents/test_proc.py
  tests/unit/docs/test_run_liveness_docs.py -q`, then `grep -rn "no activity for\|implementer.idle_timeout), so L4" tests`
  and run those files too.

## 4. The specification

- [x] 4.1 `docs/SPEC.md` already holds L4-IMP-099, the L4-IMP-024 and L4-IMP-087 amendments, SCN-IMP-537..540 and
  change-table row 129. Check them against the code; fix the code or tell the orchestrator where they differ. Run
  `uv run --frozen python scripts/check_spec.py` and `uv run --frozen pytest tests/unit/docs -q`.
- [x] 4.2 `uv run --frozen ruff check .` and `uv run --frozen ruff format --check` on the files you changed.
