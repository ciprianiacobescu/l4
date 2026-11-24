Read `design.md` first (D1-D9). Requirements: L4-IMP-112..116 and L4-AVL-014..015 (`docs/SPEC.md`), scenarios
SCN-IMP-602..621 and SCN-AVL-37..43, and the amended text and scenarios the proposal lists. Run single test files only
(`uv run --frozen pytest <file> -q -p no:cacheprovider`), never a whole directory, never two runs at once, and never a
wait loop on `pgrep`. Use the fake adapter's `Step` (`tool_calls`, `stream_reader`, a `timeout` status) and the bench of
`tests/unit/implementer/test_liveness_step.py` for the step, `tests/unit/implementer/test_loop.py` (`make_bench`) for the
window, and the tests that already cover a silent stop for the fallbacks (`tests/unit/verifier/test_fixloop_fallback.py`,
`tests/unit/implementer/test_escalation.py`, `tests/unit/implementer/test_near_pass_carry.py`,
`tests/unit/orchestrator/test_escalate_spent_profiles.py`, `tests/unit/obs/test_progress.py`). `tests/unit/docs/test_run_liveness_docs.py`
reads `docs/runbook.md` and must stay green.

## 1. The step classifies a stall (L4-IMP-112, L4-IMP-114, L4-IMP-116, D1-D3)

- [ ] 1.1 Write the tests first, in `tests/unit/implementer/test_liveness_step.py` and a new
  `tests/unit/implementer/test_stall_limit.py`:
  - SCN-IMP-602, SCN-IMP-603, SCN-IMP-617, SCN-IMP-618, SCN-IMP-616: the three kinds, the fields of `agent.idle` and
    `agent.time_limit`, the `LimitSignal` (kind, source, excerpt), an adapter's own limit kept, and no `task.attempt_failed`;
  - SCN-IMP-607, SCN-IMP-608, SCN-IMP-609, SCN-IMP-610, SCN-IMP-612, SCN-IMP-621: the once-per-window rule over the three
    kinds, a 0.4.60 `agent.idle{silent: true}` (no `kind`, no `as_limit`) counted, a checkpoint ending the window and
    `task.attempts_renewed` not ending it, a chain of one unchanged, the escalation counts untouched, a silent stop with no
    `stall_plan`;
  - SCN-IMP-619: a judge, a verifier-agent call, a clarifier call and a delegate call that time out make no stall;
  - the reasons `idle: already once for this task`, `time: already once for this task` and `silent: already once for this
    task` (SCN-IMP-438 unchanged);
  - the amended SCN-IMP-202, SCN-IMP-204, SCN-IMP-427, SCN-IMP-428 and SCN-IMP-545 (a chain of one, or the task's second
    stall), and the old tests that assert an idle stop after a tool call or a time-limit stop is a failed attempt on a
    two-profile chain: change each to the case the spec now names.
  Run the files and see the new tests fail.
- [ ] 1.2 Then, in `src/l4/implementer/tdd.py`: `_silent_before` becomes `_stalled_before` (D3), `agent_step` decides the kind
  and `as_limit` (D1) in the order the design gives, writes `agent.idle` with `kind`, `as_limit` and the discard fields
  (`changed` is read after the `finally` block) and the new `agent.time_limit`, and raises `RoleLimit(run, carried)` for
  every stall that is a limit; `LimitSignal.kind` gains `idle` and `time` (`src/l4/agents/base.py`);
  `_previous_attempt_block` says the three sentences of D2. Run the files of 1.1, then
  `tests/unit/implementer/test_tdd_green.py`, `test_tdd_red.py` and `test_single_phase.py`, one at a time.

## 2. The next profile starts from a defined state (L4-IMP-113, D4)

- [ ] 2.1 Write the tests first, in `tests/unit/implementer/test_stall_limit.py` and the orchestrator's limit tests:
  SCN-IMP-604 (edits discarded, a frozen test put back by the step's cleanup, `discarded_files` and `discarded_paths`, the
  red commit kept, nothing committed), SCN-IMP-605 (the near pass handed on, the stalled edits not), SCN-IMP-606 (a red
  stall), and the same through the fix loop's first move. Run them and see the new ones fail.
- [ ] 2.2 Then make `orchestrator._fall_back`, `switch_profile` (`detail` for the three kinds, `orchestrator.py:1255`) and
  `fixloop._fall_back` (`fixloop.py:356`) carry the detail for kinds `idle` and `time`. The discard itself is the existing one;
  change nothing in `discard_changes`. Run the files of 2.1 one at a time.

## 3. A stall that cannot move stays an attempt (L4-IMP-115, L4-AVL-015, D5, D6)

- [ ] 3.1 Write the tests first, in `tests/unit/availability/test_fallback.py` (where `Factory.on_limit` is tested) and
  `tests/unit/implementer/test_stall_limit.py`: `Factory.can_replace` (SCN-AVL-39, SCN-AVL-40, SCN-AVL-41: a cooling profile,
  a profile with the same `(tool, model)`, a constraint that refuses, no probe sent, nothing recorded); SCN-IMP-611; SCN-IMP-622 (a spent profile is never picked, also with no move in the run, and for a silent stop); SCN-IMP-613
  (the soft deadline first, `_check_step` before the next step); SCN-IMP-614 and SCN-IMP-615 (the fix loop: first move, and
  a task already in `retried`); SCN-AVL-42 (the probe fails: exit 12, tree clean, no wait). Run them and see them fail.
- [ ] 3.2 Then add `Factory.can_replace` (`src/l4/agents/factory.py`), the `Workbench.stall_plan` field and
  `StallPlan` (`src/l4/implementer/workbench.py`), `LimitSignal.veto` (`src/l4/agents/base.py`), the setting of the plan in
  `Orchestrator._workbench` (the task's selection; the spent veto from `seed_attempts`) and in `fixloop._child_workbench`
  (also not replaceable for an `idle` or `time` stall of a task in `retried`, which needs the set passed in), the veto added
  to `asked` in `switch_profile`, and the `replaceable` check in `agent_step` for kinds `idle` and `time` only. Run the files of 3.1 one at a time, then
  `tests/unit/implementer/test_escalate_spent_profiles.py` and `tests/unit/orchestrator/test_escalate_spent_profiles.py`.

## 4. Cool-down, records and texts (L4-AVL-014, L4-IMP-116, D2, D7)

- [ ] 4.1 Write the tests first: SCN-AVL-37, SCN-AVL-38, SCN-AVL-43 (`tests/unit/availability/test_cooldown.py` and the
  fallback tests: kind `idle` and `time`, `default_cooldown`, the cleared hello, a reader that does not know the kinds) and
  SCN-IMP-620 (`tests/unit/obs/test_progress.py`: the `agent.idle` suffixes, the new `agent.time_limit` line, the reasons). Run
  them and see the new ones fail.
- [ ] 4.2 Then add `ProgressTrace._agent_time_limit` and the `agent.idle` suffixes (`src/l4/progress.py`). No change to
  `cooldown_until`. Run the files of 4.1 one at a time.

## 5. Checks

- [ ] 5.1 `docs/SPEC.md` holds L4-IMP-112..116, L4-AVL-014..015, SCN-IMP-602..621, SCN-AVL-37..43, change-table row 143 and
  the amended text of the proposal's list. Check them against the code and tell the orchestrator where they differ; do not
  edit `docs/SPEC.md`, `CHANGELOG.md` or `docs/runbook.md`. Run `uv run --frozen python scripts/check_spec.py docs/SPEC.md`.
- [ ] 5.2 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.
