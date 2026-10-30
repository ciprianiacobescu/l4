## 1. The pass bound (L4-DLG-003)

- [x] 1.1 Read `src/l4/delegate/run.py` (the pass loop, `if self.calls >= self.cfg.max_questions_per_run: break`),
  `Orchestrator._delegate` and `_drive` (src/l4/orchestrator.py, `code = self._drive(); code = self._delegate(code)`),
  and `planner.py` (where the action `delegate` is named). Decide the signal for "no step of the unit ran in this run
  before the pass" from what the orchestrator already knows (for example a step counter or the planner's action of the
  run's first iteration); write it into this task's result. Write the tests first (the delegate run tests; find them
  with `grep -rln "max_questions_per_run" tests/unit`): SCN-DLG-123, -124, -125. Then pass the flag into the pass,
  skip the cap when it is set, and record the bound (`cap`, `none_due`, `deadline`, `cost`) on the event that ends the
  pass (add a field to the existing event if there is one; else a `delegate.pass` event, data only, no fold change).
  The soft-deadline and cost paths are unchanged.

  Result: The signal for "no step of the unit ran in this run before the pass" is `Orchestrator.idle_run()` (the existing
  `is_idle_run` on the run's ledger as it stands: no `agent.finished`, `gate.finished`, `delegate.asked`, `budget.cost`,
  no clarifier call that was made, no phase change but into a wait). The orchestrator puts it in `HookContext.shared`
  as `idle_run` (next to `job_remaining_s`); `_Pass.run` reads it once, before it writes anything, and skips the
  `max_questions_per_run` check when it is true (`self.only`). No pass-end event existed, so a new data-only event
  `delegate.pass{bound, delegate_only}` is appended when the loop ends (not when nothing is due); `bound` is the first
  of `deadline` (a soft-deadline deferral), `cost` (a `limit_reached` refusal for the unit's cost cap or the plan's
  share, told apart by `limits.is_cost_reason`), `cap` (the loop broke on the cap), else `none_due`. The soft-deadline
  and cost paths are unchanged (a delegate-only pass past the deadline defers each remaining question, as a capped one
  does). The fold ignores the event. No deviation. Tests (test_pass.py, SCN-DLG-123, -124, -125 twice, and a
  `none_due` case for a working run): all five failed first (no `delegate.pass` event, the second run stopped at the
  cap) and pass now; test_pass.py, test_delegate_hook.py and test_limits.py pass (48).

## 2. The short quote (reply checks)

- [ ] 2.1 Write the tests first (`tests/unit/delegate/test_reply*.py`): SCN-DLG-126 for a `path:line` ref and a `spec:`
  ref; a long quote that is not on the line keeps `does not resolve`. Then make `_resolves` (src/l4/delegate/reply.py)
  give the reason (for example return a reason string instead of a bool, or check the length before calling it), keep
  it retryable, and add the minimum to the `checked` rule in `src/l4/delegate/prompt.py` ("`quote` is at least 12
  characters, copied word for word"). Update any prompt snapshot test.

## 3. Checks

- [ ] 3.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you changed or added plus the test files that import a module you changed (`grep -rl` for the module name under tests/unit), in one pytest invocation; not whole directories (a combined run follows after the merge). Run ruff check and ruff format on the changed files. Report the counts. Do not edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md (a docs pass does that).
