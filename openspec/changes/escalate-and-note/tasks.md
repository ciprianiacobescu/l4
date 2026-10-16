Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files and their folder, for example
  `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer` (pytest-cov is not installed: keep `--no-cov`).
  Then run `ruff check`, `ruff format --check` and `mypy` on the files that you changed.
- Never wait on a process with `while pgrep -f …`: it matches itself. Run commands in the foreground.
- Stage explicit paths only.
- Every event key, field, message and line is in `design.md`. Do not change one without the orchestrator.
- Name the consumer "a consumer repository". Use the profile names `deepseek`, `glm` and `claude-sonnet` and the
  judge names `claude-judge` and `codex-judge` of the design. Never use a product name of the consumer.

The fixtures:
- the bench: `make_bench` and `raw` (`tests/unit/implementer/conftest.py`), with `red_step`, `green_step`,
  `blocked_step` and `result`. A failed red is `Step(structured=result("red"))` ("no tests added"). An invalid result
  is `Step(structured={"status": "ok"})` (no `summary`).
- the run: `run_l4` and `fake_clock` (`tests/unit/orchestrator/conftest.py`). A chain of two fake profiles is the
  `TWO` config of `tests/unit/orchestrator/test_fallback.py:16`. Two fake profiles share one adapter instance, so
  `run.adapter.requests` holds the steps of both. A fake profile without a `model` has its own cool-down key
  (`fake` is in `PROFILE_KEYED`, `src/l4/availability/cooldown.py:34, 82-83`), so cooling one does not cool the other.
  When a test gives fake profiles a `model`, give each a different one, or the two share a key.

## 0. Contract (orchestrator, before wave 1)

- [ ] 0.1 Contracts with no behaviour:
  - `ImplementerCfg.escalate_after: int = Field(default=2, ge=0)` (`config/schema.py`);
  - `PreviousAttempt` gains `why: Literal["limit", "escalation"] = "limit"`, `phase: str | None = None` and
    `failures: tuple[tuple[str, str], ...] = ()`; `limit_kind` becomes `str | None` (`implementer/workbench.py`);
  - `EscalationRequest` and the `Escalate` type of design D4 in `implementer/loop.py`, and the keyword
    `run_task(wb, task, *, escalate: Escalate | None = None)`, not used yet;
  - `UnitState.halt_task: str | None = None` and `halt_fix_unit: str | None = None` (`state/fold.py`);
  - new functions that raise `NotImplementedError`: `Factory.next_profile(role, unit, after, *, constraints=())`
    (`agents/factory.py`), `independence_keeper(cfg, implementers) -> Constraint` (`verifier/selection.py`), and the
    new module `implementer/retrynote.py` with `RetryNote` (`event`, `ts`, `text`), `retry_note(events, task, fix_unit)
    -> RetryNote | None` and `note_block(note) -> tuple[str, str]`.

  Tests: the config default is 2, `0` loads, `-1` and a non-integer are refused; a `PreviousAttempt(profile, kind,
  task)` of today still renders the limit block unchanged (`tests/unit/orchestrator/test_fallback.py` stays green).
  [L4-IMP-017] [L4-OPS-018]

## 1. Wave 1: pure parts (five agents, disjoint files)

### Agent A: `agents/factory.py`, `availability/fallback.py`

- [ ] 1.1 `Factory.next_profile`: walk the profiles of `roles.<role>` after `after`, with `required=False` and the
  given constraints. On success record `availability.selected{role, selected, escalated_from: after, skipped, probes,
  cached}` with no `fallback_from`, and return a `Selected` with `fallback_from=None`. The console line ends
  `→ selected, escalated from <after>`. When nothing is usable raise `RoleUnavailable` and record no
  `availability.unavailable` (add a selector option for it). Never record a cool-down. An `after` that is the last
  profile, or not in the chain, raises `RoleUnavailable` at once.
  - Test first, in the new file `tests/unit/agents/test_factory_next_profile.py`: two profiles of one adapter
    (`opencode`, models `opencode-go/deepseek-v4.1-flash` and `opencode-go/glm-5.3-flash`) give the second; a cooling
    second gives `RoleUnavailable` and no `availability.unavailable`; a constraint veto skips a profile with its reason;
    the event has `escalated_from` and no `fallback_from`; no `availability.cooldown` is written.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/agents tests/unit/availability`.
  [L4-IMP-017] [SCN-IMP-176, SCN-IMP-180]

### Agent B: `implementer/loop.py`

- [ ] 1.2 Per-profile counts and the hook (design D1, D3, D4):
  - count failed attempts per phase for the current profile; keep `attempts` across profiles;
  - after a failed attempt, call `escalate` when the conditions of D1 hold (the chain is `wb.cfg.roles.implementer`);
  - a returned workbench: record `implementer.escalated{task, phase, from, to, failures, attempt}`, reset the count of
    the phase, go on with the next attempt on the new workbench (a committed red stays, `retry` stays);
  - a returned reason: record `implementer.escalation_skipped{task, phase, from, reason}` and go on;
  - keep a list of `(profile, reason)` per phase for `EscalationRequest.failures`;
  - the task keeps the new workbench for its later phases.
  - Test first, in the new file `tests/unit/implementer/test_escalation.py`, with a fake hook that returns a second
    bench workbench or a reason: SCN-IMP-176 at loop level (two failures, then the hook, then attempt 3 on the second
    workbench); SCN-IMP-179 (no hook call for one profile, for `escalate_after: 0`, for `max_task_attempts: 2`); a
    returned reason is asked again after the next failure; a `blocked` step and the hang question never call the hook;
    the step keys `1.1/red/1..3` are distinct.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_escalation.py
    tests/unit/implementer/test_loop.py`.
  [L4-IMP-017] [SCN-IMP-176, SCN-IMP-179]
- [ ] 1.3 The records of design D13: `task.attempt_failed` gains `profile` and its `attempt` is the step attempt;
  `breaker.tripped` gains `profiles: [{profile, failures}]`, and `attempts` is the failed attempts of the phase; the
  halt detail names the profiles only when two or more ran the phase. Needs 1.2.
  - Test first, in `test_escalation.py`: SCN-IMP-177 at loop level (`attempts: 5`, the two `profiles`, the detail).
    `tests/unit/implementer/test_loop.py`, `tests/unit/archive/test_hooks.py` and
    `tests/unit/state/test_status_reason.py` stay green (one profile: the detail of today).
  - Verify: as 1.2, and `.venv/bin/python -m pytest -q --no-cov tests/unit/archive/test_hooks.py
    tests/unit/state/test_status_reason.py`.
  [L4-IMP-018] [SCN-IMP-177]

### Agent C: `state/fold.py`

- [ ] 1.4 `halt_task` and `halt_fix_unit` from the last `breaker.tripped{reason: "max_task_attempts"}` (its `task`
  and `fix_unit`); `unit.retried`, `unit.resumed` and `unit.restarted` clear them. An `availability.selected` with
  `escalated_from` adds the profile to `profiles_used` and leaves `fallback_from` as it is.
  - Test first, in the new file `tests/unit/state/test_fold_escalation.py`: a halt on 4.1 sets `halt_task`; a fix
    unit's breaker sets `halt_fix_unit`; a retry clears both; a `breaker.tripped` with another reason sets nothing; an
    escalated selection keeps `fallback_from` of an earlier limit fallback and adds `glm` to `profiles_used`.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/state`.
  [L4-OPS-018] [L4-IMP-017]

### Agent D: `implementer/retrynote.py`, `verifier/selection.py`

- [ ] 1.5 `retry_note(events, task, fix_unit)`: the latest `unit.retried` or `unit.resumed` with a non-empty
  `note_task`; `None` when its `note_task` or `note_fix_unit` differs, when a `task.done` of that task (same
  `fix_unit`) or a `unit.restarted` comes after it, or when the reason is empty. The text is the reason cut at 300
  characters. `note_block(note)` returns `("a person's note", data_block("retry note", "A person's note on this retry:
  " + text))`.
  - Test first, in the new file `tests/unit/implementer/test_retry_note.py`: SCN-OPS-29 at function level (a done
    task ends it; a newer note for another task replaces it; a label retry without `note_task` after it does not end
    it); an event of an older ledger without `note_task` gives `None`; a fix unit's note does not reach the unit's own
    task of the same key; a 400-character reason is cut to 300; `</l4:data>` in the reason is defused.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_retry_note.py`.
  [L4-OPS-018] [SCN-OPS-29, SCN-OPS-32]
- [ ] 1.6 `independence_keeper(cfg, implementers)`: a constraint that refuses a profile P when, for `roles.judges` and
  for a non-empty `roles.verifier_agent`, no profile of that chain with an adapter in `JUDGE_ADAPTERS` passes
  `independence_constraint(cfg, [*implementers, P])`. The reason is `no profile of roles.<role> would be independent of
  <P> (verifier.independence: <mode>)`. With `verifier.independence: none`, or no judge profile, it refuses nothing.
  - Test first, in the new file `tests/unit/verifier/test_independence_keeper.py`: SCN-IMP-181 at function level
    (`[claude-judge]` refuses `claude-sonnet` after `deepseek` and `glm`, and takes `glm`; `[claude-judge,
    codex-judge]` takes `claude-sonnet`); a two-Claude chain adds no vendor; `none` takes every profile.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/verifier/test_independence_keeper.py
    tests/unit/verifier/test_selection.py`.
  [L4-IMP-017] [SCN-IMP-181]

### Agent F: `doctor/checks_config.py`

- [ ] 1.7 CFG-009 (warn) of design D13: an `escalate_after` that is neither 0 nor below `max_task_attempts` on a chain
  of two or more profiles, and two profiles of `roles.implementer` with the same adapter and model. A chain of one
  profile passes.
  - Test first, in the new file `tests/unit/doctor/test_checks_cfg_009.py`: SCN-IMP-185 (the three configs and their
    messages), and `escalate_after: 0` passes.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/doctor`.
  [L4-IMP-018] [SCN-IMP-185]

## 2. Wave 2: the run (three agents, after wave 1)

### Agent E: `implementer/tdd.py`

- [ ] 2.1 `_previous_attempt_block` renders the escalation block of design D9 for a `PreviousAttempt` with
  `why="escalation"`, for steps of the same task and phase only: the attributes `profile`, `reason="escalation"`,
  `phase`; the reasons oldest first as `<n>. (<profile>) <reason>`, each cut at 1000 characters and defused. The limit
  block does not change. Needs 0.1.
  - Test first, in `tests/unit/implementer/test_escalation.py`: the block lists both reasons of SCN-IMP-176, the
    guarded-stub advice included; a green prompt of the same task has no escalation block; a 1500-character reason is
    cut.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer`.
  [L4-IMP-017] [SCN-IMP-176, SCN-IMP-178]
- [ ] 2.2 `_prompt` adds `note_block(retry_note(_ledger_events(wb), task.key, wb.event_context.get("fix_unit")))` as
  the last data block, and `prompt.rendered` gains `retry_note: {event, ts, sha256}` only when there is a note.
  Needs 1.5.
  - Test first, in the new file `tests/unit/implementer/test_retry_note_prompt.py` (bench, with a `unit.retried` that
    has `note_task` written into the unit's ledger before the step): SCN-OPS-28 at bench level (red and green prompts
    of the task have the block; `retry_note.sha256` is the sha256 of the block text); another task has neither;
    SCN-OPS-32 (a token value of `redact_env` is masked in the prompt; one `retry note` block).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer`.
  [L4-OPS-018] [SCN-OPS-28, SCN-OPS-32]

### Agent G: `orchestrator.py`

- [ ] 2.3 The hook of design D4: `_escalate(wb, request)` refolds, takes `profiles_used["implementer"]` plus
  `wb.selected`, calls `factory.next_profile("implementer", unit, request.profile, constraints=(keeper,))`, builds the
  workbench with `_workbench(selected=…)` (the same baselines, the activated digest), sets its `previous_attempt` to
  `PreviousAttempt(request.profile, None, request.task, why="escalation", phase=request.phase,
  failures=request.failures)`, sets `_task_selected`, and returns it; on `RoleUnavailable` it returns the reason. `_implement`
  passes `escalate=self._escalate` and clears `_task_selected` after each task. `_select()` and
  `ctx.shared["implementer"]` do not change. Needs 1.1, 1.2, 1.6.
  - Test first, in the new file `tests/unit/orchestrator/test_escalation.py` with `run_l4` and a chain of two fake
    profiles: SCN-IMP-176 end to end (the events, no cool-down, the third request has the escalation block);
    SCN-IMP-177 (5 requests, the halt detail in `phase.changed`); SCN-IMP-178 (green on the second profile, its commit's
    `L4-Agent` names it and no `L4-Fallback-From`, the next task's red on the first); SCN-IMP-180 (a cooling second
    profile: `escalation_skipped`, no `waiting_capacity`); SCN-IMP-183 (a fix unit's task: no hook, no escalation).
    `tests/unit/orchestrator/test_fallback.py` and `tests/unit/verifier/test_fixloop_fallback.py` stay green.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/orchestrator tests/unit/verifier/test_fixloop_fallback.py`.
  [L4-IMP-017] [SCN-IMP-176, SCN-IMP-177, SCN-IMP-178, SCN-IMP-180, SCN-IMP-183]
- [ ] 2.4 `switch_profile` cools the task's profile when `_task_selected` is set, else the run's, and clears
  `_task_selected`. Needs 2.3.
  - Test first, in `test_escalation.py`: SCN-IMP-182 (a limit on the second profile in red attempt 3: the cool-down is
    for the second profile, the run's profile stays the first, the task goes on with fresh counts; a `blocked` step of
    the first profile raises a question and no escalation).
  - Verify: as 2.3.
  [L4-IMP-017] [SCN-IMP-182]
- [ ] 2.5 `Orchestrator.resume` and `run_unit_in_worktree` take `note_task` and `note_fix_unit` and add them to the
  `unit.retried` or `unit.resumed` event when given. Nothing else passes them yet.
  - Test first, in `tests/unit/orchestrator/test_escalation.py`: a resume with `note_task="4.1"` records it; a resume
    without records neither key.
  - Verify: as 2.3.
  [L4-OPS-018]

### Agent I: `progress.py`

- [ ] 2.6 The lines of L4-IMP-018 and the `prompt.rendered` line of design D13: `implementer.escalated`,
  `implementer.escalation_skipped` (warning), `task.attempt_failed` with `profile`, `breaker.tripped` with two or more
  `profiles`, `availability.selected` with `escalated_from`, `prompt.rendered` with `retry_note`. An event without the
  new fields prints as today.
  - Test first, in `tests/unit/obs/test_progress.py`: SCN-IMP-184 (each line, and the older `task.attempt_failed`).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/obs`.
  [L4-IMP-018] [SCN-IMP-184]

## 3. Wave 3: the commands (one agent, after wave 2)

### Agent H: `state/retry.py`, `state/resume.py`, `state/status.py`, `cli.py`

- [ ] 3.1 `retry_unit(..., note=False)` and `resume_unit(..., note=False)`: with `note=True` and a unit `halted` with
  `halt_reason: max_task_attempts` and a `halt_task`, pass `note_task` and `note_fix_unit` to `run_unit_in_worktree`.
  `run_retry` and `run_resume` pass `note=True`; the sweeper and the plan cycle do not. The commands print the `note:`
  line of L4-OPS-018, and the 300-character line when they cut the reason. Needs 1.4, 2.5.
  - Test first, in `tests/unit/state/test_retry.py` and `tests/unit/state/test_resume.py`: SCN-OPS-28 (the event and
    the line), SCN-OPS-30 (a label retry, a plan retry and a restart carry no `note_task`), SCN-OPS-31 (`baseline_failed`
    and `escalated`: no binding and the line), and the 300-character line.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/state tests/unit/ci`.
  [L4-OPS-018] [SCN-OPS-28, SCN-OPS-30, SCN-OPS-31]
- [ ] 3.2 `l4 status --unit`: the `Retry note:` line before `Next:` for a unit halted with `max_task_attempts` and a
  `halt_task`; `--json` carries `halt_task` and `halt_fix_unit`. `l4 retry --help` and `l4 resume --help` get the
  `--reason` text of design D13. Needs 1.4.
  - Test first, in `tests/unit/state/test_status_reason.py` (the line, and none for `baseline_failed`) and
    `tests/unit/cli/test_dispatch.py` (the help text).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/state tests/unit/cli`.
  [L4-OPS-018]

## 4. Integration on the run (orchestrator, after wave 3)

- [ ] 4.1 One end-to-end test in `tests/unit/orchestrator/test_escalation.py` that joins both halves: a two-profile
  run halts on 4.1 (5 failed red attempts), `l4 retry --reason TEXT` records the note, and the next run's red prompts of
  4.1 carry the note block on the first profile and, after the escalation, the note and the escalation block on the
  second.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/orchestrator tests/unit/state`.
  [L4-IMP-017] [L4-OPS-018]

## 5. Docs and skill (one agent, after wave 3)

- [ ] 5.1 Runbook:
  - 7.2: the `max_task_attempts` row shows the detail with profiles; "What to do" says to write the `--reason` for the
    implementer of that task; a NOTE explains `implementer.escalate_after`, the per-profile attempts, that a move goes
    by profile (two OpenCode Go models are two steps), and `escalate_after: 0`;
  - step 4 of "The command: `l4 retry`" says what the `--reason` is for, and step 5 names the `note:` line;
  - 4.2: the lines of L4-IMP-018 and the `prompt.rendered` line;
  - 10.4: the `l4 retry` row;
  - 11: no escalation in a fix unit; a note only for a halt on `max_task_attempts`; `max_cost_usd_per_unit` still not
    enforced, and a plan's `max_cost_usd` is checked between unit runs only.
  - Test first, in the new file `tests/unit/docs/test_escalate_and_note_docs.py`: SCN-OPS-33 (runbook part).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/docs`.
  [L4-OPS-019] [SCN-OPS-33]
- [ ] 5.2 Skill `references/adopt.md`: the cheap-first chain:

  ```yaml
  profiles:
    deepseek:      {adapter: opencode, auth: api_key, model: opencode-go/deepseek-v4.1-flash, vendor: deepseek}  # OPENCODE_API_KEY
    glm:           {adapter: opencode, auth: api_key, model: opencode-go/glm-5.3-flash, vendor: zhipu}           # the same key
    claude-sonnet: {adapter: claude-code, auth: subscription, vendor: anthropic}                                # optional, last
    claude-judge:  {adapter: claude-code, auth: subscription, vendor: anthropic}
    codex-judge:   {adapter: codex, auth: api_key, vendor: openai}                                              # CODEX_API_KEY
  roles:
    implementer: [deepseek, glm, claude-sonnet]   # cheap first; a task moves after escalate_after failures
    judges: [claude-judge, codex-judge]           # a judge must not share a vendor with an implementer that ran
  implementer:
    escalate_after: 2                             # 0: never move
    max_task_attempts: 3                          # the last profile's attempts
  ```

  With the text: escalation moves by profile, cheap first; the last profile gets `max_task_attempts`; without
  `claude-sonnet` the chain stays free of a subscription; a judge of every implementer vendor is vetoed, so keep one of
  another vendor; `escalate_after: 0` turns it off. Skill `references/operate.md`: the `--reason` of `l4 retry` is the
  implementer's note for the halted task; write what to do differently, in at most 300 characters. `SKILL.md`'s line
  about `operate.md` names the note.
  - Test first, in `test_escalate_and_note_docs.py`: SCN-OPS-33 (skill part: the needles of the example and the
    note).
  - Verify: as 5.1.
  [L4-OPS-019] [SCN-OPS-33]
- [ ] 5.3 CHANGELOG: a new section `## 0.4.4 (unreleased)` above 0.4.3:
  - Added: escalation along `roles.implementer` (`implementer.escalate_after`, `implementer.escalated`), the retry note,
    CFG-009, the new progress lines;
  - Changed: a chain of two or more profiles moves a failing task phase to the next profile by default (each profile
    has its own attempts, the last one `max_task_attempts`); set `implementer.escalate_after: 0` for the old behaviour;
    the config key needs the 0.4.4 pin before the config edit (strict schema).
  - Verify: `grep -n "## 0.4.4" CHANGELOG.md`.
  [L4-IMP-017] [L4-OPS-018]

## 6. `docs/SPEC.md` (orchestrator)

- [ ] 6.1 §7.6: add L4-IMP-017 and L4-IMP-018 after L4-IMP-008, with the text of
  `specs/implementer-escalation/spec.md`. Amend L4-IMP-008: "`max_task_attempts` reached in one phase on one profile;
  with a later usable profile the phase moves first (L4-IMP-017)". Add SCN-IMP-176..185 to §23.7.
  - Verify: `.venv/bin/python scripts/check_spec.py docs/SPEC.md`.
  [L4-IMP-017] [L4-IMP-018]
- [ ] 6.2 §8.4 L4-AVL-006: one sentence, "A chain also moves on repeated failures of one task phase (L4-IMP-017);
  that move is a selection, not a limit: nothing cools down." §7.3 L4-IMP-004: the section order with the person's
  note after the previous attempt, and `prompt.rendered{retry_note}`. §3.2 `implementer:` gets `escalate_after: 2`
  with its comment. §15: the CFG-009 row.
  - Verify: as 6.1.
  [L4-IMP-017] [L4-IMP-018] [L4-OPS-018]
- [ ] 6.3 §12.1 L4-STA-001: `implementer.escalated{task, phase, from, to, failures, attempt}`,
  `implementer.escalation_skipped{task, phase, from, reason}`, `availability.selected.escalated_from`,
  `task.attempt_failed.profile`, `breaker.tripped.profiles`, `unit.retried` and `unit.resumed`
  `{note_task, note_fix_unit}`, `prompt.rendered.retry_note`.
  - Verify: as 6.1.
  [L4-IMP-017] [L4-OPS-018]
- [ ] 6.4 §12.4: add L4-OPS-018 and L4-OPS-019 after L4-OPS-017. Amend L4-OPS-001 ("the reason of the command is also
  the implementer's note, L4-OPS-018") and L4-OPS-006 (the `Retry note:` line and `halt_task` in `--json`). §2.1: the
  `l4 retry` and `l4 resume` rows name the note. Add SCN-OPS-28..33 to §23.19.
  - Verify: as 6.1.
  [L4-OPS-018] [L4-OPS-019]
- [ ] 6.5 §21: add row 24 `escalate-and-note` with its requirement ranges and live check. Amend row 15
  `model-capability`: "M2 escalation is delivered in a reduced form by row 24 (L4-IMP-017: `implementer.escalate_after`,
  `implementer.escalated`, per-profile attempts, on by default); the fingerprint stop, the trail, demotion and the
  `escalation:` block stay proposed." Add the same note at the top of `openspec/changes/model-capability/proposal.md`.
  - Verify: as 6.1, and `openspec validate model-capability --strict`.
  [L4-IMP-017]

## 7. Orchestrator: integration, review, live check

- [ ] 7.1 Merge the waves. Run the full suite with `--no-cov`, `ruff check`, `ruff format --check` and `mypy src`. Run
  `openspec validate escalate-and-note --strict`.
- [ ] 7.2 Adversarial review on the session model, not by the implementers. Try to:
  - make an escalation park a unit (a cooling or unusable later profile, a required-role selection, a busy login);
  - make an escalation leave the verifier without an independent judge or verifier agent;
  - make the run's profile change after an escalation (`_select()`, `ctx.shared["implementer"]`, the fix loop);
  - get a note into a prompt from a label, a plan, a push, a restart, a plan resume or an old ledger;
  - get a note into another task, another fix unit's task, or a task after its `task.done`;
  - break out of the note block or leak a secret through it.
  Record the results in `docs/live/escalate-and-note/review.md`.
- [ ] 7.3 Live check on a dummy repository (the public GitHub dummy or the GitLab dummy), with
  `roles.implementer: [deepseek, glm]` (OpenCode Go, one `OPENCODE_API_KEY`) and judges of another vendor:
  1. a unit whose task the first profile fails twice: see `implementer.escalated{from: deepseek, to: glm}` and the
     escalation block in the published prompt of the third step;
  2. a unit halted on `max_task_attempts`: run `l4 retry --reason TEXT`, see the `note:` line, then the block and
     `prompt.rendered.retry_note` in the next run.
  Keep the evidence under `docs/live/escalate-and-note/`. Leave the dummies for the user to delete.
