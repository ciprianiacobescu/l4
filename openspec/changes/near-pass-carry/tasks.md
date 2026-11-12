## 1. The near pass is kept (D1, D2)

- [ ] 1.1 Write the tests first in a new `tests/unit/implementer/test_near_pass_carry.py`, with the fixtures of
  `tests/unit/implementer/conftest.py` (`make_bench`, `red_step`, `green_step`, `result`) and the pattern of
  `tests/unit/implementer/test_static_gates_first.py` (a lint command that fails only on the step's change, `sh -c 'if
  grep -q LINTBAD <file>; then echo bad; exit 1; fi'`):
  - a green step whose test gate passes and whose lint fails: `GreenOutcome.status == "failed"`, `near_pass` set with the
    attempt, the profile, `gates == ("lint",)`, a non-empty patch whose sha256 is `patch_sha256`, and the changed paths;
    the work tree is back at the red commit afterwards;
  - SCN-IMP-543: a green step whose test gate fails: `near_pass` is None; a green step whose test gate passes, whose lint
    fails and whose `outside_links_reason` (monkeypatch it) gives a reason: `near_pass` is None; a replayed step
    (`wb.replay_question` set, or build it as `test_held_accept.py` does): `near_pass` is None.
  - `capture` still produces the same patch bytes as before for a held step (the existing held tests cover it: run them).
  Run them and see them fail.
- [ ] 1.2 Then add `NearPass` and `step_patch` (in `src/l4/implementer/held_patch.py`, `capture` calling `step_patch`) and
  the near-pass outcome in `run_green` (`src/l4/implementer/tdd.py`). Run the new tests and
  `uv run --frozen pytest tests/unit/implementer/test_held_accept.py tests/unit/implementer/test_held_check.py
  tests/unit/implementer/test_replay_green_freeze.py tests/unit/implementer/test_static_gates_first.py
  tests/unit/implementer/test_tdd_green.py -q`.

## 2. It is applied once to the next attempt (D3, D4, D5)

- [ ] 2.1 Write the tests first in `test_near_pass_carry.py`:
  - SCN-IMP-541: drive `run_task` (`l4.implementer.loop`) with a fake implementer whose first green step writes the code
    plus a `LINTBAD` marker and whose second green step only removes the marker (read the work tree in the fake to
    assert that attempt 1's code is there when attempt 2 starts): the task is done after attempt 2; the ledger holds
    `task.attempt_failed{near_pass: true}` for attempt 1 and `task.near_pass_applied{from_attempt: 1}` before attempt 2's
    `step.started`; attempt 2's published prompt (`*.prompt.md` next to the agent logs) holds the `near pass` block naming
    attempt 1, its profile and `lint`, and not the words `were discarded`;
  - SCN-IMP-542: two profiles and `escalate_after: 1` (see `tests/unit/implementer/test_escalation.py` for the setup): the
    second profile's first step sees the first profile's changes, and its escalation block says they are in the checkout;
  - SCN-IMP-544: attempt 2 (from a near pass) fails its test gate → attempt 3's work tree is the red commit's (no
    `task.near_pass_applied` for attempt 3); a variant where attempt 2 is itself a near pass → attempt 3 starts from
    attempt 2's changes (`from_attempt: 2`);
  - SCN-IMP-546: a near pass, then a found replay → `task.near_pass_dropped{reason: "replay"}` and the replay runs; a near
    pass whose patch does not apply (monkeypatch `wb.git.run_input_bytes` to raise `GitError` for the apply) →
    `task.near_pass_dropped` with the error, the attempt runs from the red commit, and its prompt has no `near pass` block.
  Run them and see them fail.
- [ ] 2.2 Then thread the carry: `_run_task` (`src/l4/implementer/loop.py`) → `run_green(..., carry=)` →
  `step_or_replay(..., carry=)` → `agent_step(..., carry=)`, the apply and its events, the `near pass` block in `_prompt`,
  and the conditional text of `_escalation_block` and `_previous_attempt_block`. Run the new tests and
  `uv run --frozen pytest tests/unit/implementer/test_loop.py tests/unit/implementer/test_escalation.py
  tests/unit/implementer/test_escalate_spent_profiles.py tests/unit/implementer/test_prompt.py
  tests/unit/implementer/test_retry_note_prompt.py tests/unit/implementer/test_liveness_step.py -q`.

## 3. The halt names the near pass (D6)

- [ ] 3.1 Write the test first (SCN-IMP-545): a task whose green attempt is a near pass and whose later attempts fail
  until the profile is spent: the halt reason ends with the `nearest:` text and `breaker.tripped` holds `near_pass`; a
  task with no near pass has today's reason and no `near_pass` field. Run it and see it fail.
- [ ] 3.2 Then add `nearest`, the `near_pass` field of `task.attempt_failed` and the halt text in `_run_task`. Run
  `uv run --frozen pytest tests/unit/implementer -q -k "loop or escalat or breaker or halt"` and every test that pins the
  halt reason (`grep -rn "max_task_attempts (" tests/unit`).

## 4. The specification

- [ ] 4.1 `docs/SPEC.md` already holds L4-IMP-100, SCN-IMP-541..546 and change-table row 130. Check them against the code;
  fix the code or tell the orchestrator where they differ. If the ledger event list of the SPEC (§ the event table; find
  it with `grep -n "task.attempt_failed" docs/SPEC.md`) names fields per event, add `near_pass` there and the two new
  events. Run `uv run --frozen python scripts/check_spec.py` and `uv run --frozen pytest tests/unit/docs -q`.
- [ ] 4.2 `uv run --frozen ruff check .` and `uv run --frozen ruff format --check` on the files you changed.
