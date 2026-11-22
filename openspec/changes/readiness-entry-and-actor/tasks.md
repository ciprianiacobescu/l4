Read `design.md` first. It names every function, field and rule. Read L4-YOLO-101..104, L4-OPS-025 and L4-OPS-026 in
`docs/SPEC.md` too, and the scenarios SCN-YOLO-283..295 and SCN-OPS-54..62.

Rules for every task:
- Write the tests first, run them, and see them fail.
- Then write the code, and run the tests the task names.
- Run only the test files named. Never the whole suite.
- Never use a `while pgrep` loop.

**Test techniques.**
- Readiness: `tests/unit/yolo/yolo_review_world.py` (`World`, `make_cfg`, `plan_of`) and a scripted
  `l4.agents.fake.FakeAdapter`; the prompt is `fake.requests[i].prompt`.
- Plan commands: `tests/unit/yolo/yolo_cmd_world.py` (`world`, `forge`, `ev`, `world.reviewed()`, `world.seed`,
  `world.l4(...)`) and `tests/unit/yolo/yolo_actor.py` (`person`, `agent(world, monkeypatch)`). A review of an older
  prompt version: set `event.data["prompt_version"] = PROMPT_VERSION - 1` on `world.reviewed()`, as
  `tests/unit/yolo/test_yolo_staleness_messages.py::reviewed_with_revs` does. Do not monkeypatch
  `readiness.PROMPT_VERSION`: `cycle`, `commands` and `review_worktree` import it by value.
- The CI step: `tests/unit/yolo/yolo_cycle_world.py` (`CycleWorld`), as `test_yolo_cycle_review.py` uses it.
- Unit commands: the worlds of `tests/unit/state/test_retry.py`, `test_restart.py` and `test_resume.py`.

## 1. The plan entry and prompt version 5 (D1, D2; L4-YOLO-101)

- [ ] 1.1 Write the tests first, in a new `tests/unit/yolo/test_yolo_readiness_entry_order.py`:
  - SCN-YOLO-283: the batch of the scenario. Assert the exact text of the batch's `plan entry` block (copy the JSON of
    design D1, extended to three units) and that of the unit `openspec:b`. Find the block in the prompt between the
    `plan entry` data-block markers (see `l4.implementer.prompt.data_block` for the marker text). Assert `PROMPT_VERSION == 5`.
    Run the review with the cycle world and assert `plan.reviewed{prompt_version: 5}`.
  - SCN-YOLO-283, the part: with `yolo: {review: {max_batch_chars: 1000}}` (as `test_yolo_readiness_parts.py` does),
    every part's `plan entry` block has the same order.
  - A pure test of `_ordered`: a key `zeta` added to a dict sorts after `depends_on`; a dict without `id` keeps
    `depends_on` first; a list keeps its order.

  Run it and see it fail.
- [ ] 1.2 Then change `src/l4/yolo/readiness.py`: `_ordered`, `_entry`, `PROMPT_VERSION = 5` and its comment line.
- [ ] 1.3 Update the tests that pin version 4, the old order or the 0.4.58 keys. Change only what the new order and
  version change, and say in each test's docstring why:
  - `tests/unit/yolo/test_yolo_readiness_parts.py::test_scn_yolo_276_a_unit_and_a_batch_that_fit_keep_the_prompt_and_the_keys_of_0458`
    (SCN-YOLO-276 and SCN-YOLO-284): keep the 0.4.58 prompt hashes as they are, and assert them on each prompt with
    its `plan entry` block rendered back with `json.dumps(..., indent=2, sort_keys=True)`; then assert the new
    material keys as literals taken by running the test once on your change; and `PROMPT_VERSION == 5`.
  - `tests/unit/yolo/test_yolo_readiness_incremental.py` (line ~203), `test_yolo_review7_prompt.py` (~22),
    `test_yolo_readiness_delivered.py` (~102, ~109), `test_yolo_readiness_material.py` (~213): the version.
  - `tests/unit/yolo/test_yolo_readiness_review.py` (~195): it looks for the entry rendered with `sort_keys=True`;
    render it with `readiness._entry`.

  Run `uv run --frozen pytest tests/unit/yolo/test_yolo_readiness_entry_order.py
  tests/unit/yolo/test_yolo_readiness_parts.py tests/unit/yolo/test_yolo_readiness_incremental.py
  tests/unit/yolo/test_yolo_review7_prompt.py tests/unit/yolo/test_yolo_readiness_delivered.py
  tests/unit/yolo/test_yolo_readiness_material.py tests/unit/yolo/test_yolo_readiness_review.py -q`. Then
  `grep -rn "PROMPT_VERSION\|prompt_version" tests/unit/yolo` and run every file that matches: a file that uses the
  symbol passes unchanged; fix only a literal 4.
- [ ] 1.4 The upgrade (D2), in a new `tests/unit/yolo/test_yolo_prompt_upgrade.py`, with ledgers whose review has
  `prompt_version: 4` (write `PROMPT_VERSION - 1`):
  - SCN-YOLO-285: status text and `--json` (`review.prompt_changed`); the activation refusal and that
    `world.kinds()` is unchanged; the CI step judges A, B and the batch (a fake that counts requests: 3) and the new
    `plan.reviewed` has no `reused_from`; `fold_plan(...).accepted` still holds the acceptance and
    `accept.holds(...)` is False for it, the status line says `other material`; `l4 yolo accept p1 batch:b1 --reason r`
    after a review that keeps the batch NEEDS_REVISION is not refused for rounds.
  - SCN-YOLO-286: a person force-accepts on the version-4 review, then activates: exit 0, no review requested.
  - SCN-YOLO-287: an active plan (seed `plan.activated` with the current digests). The CI step records no
    `plan.reviewed`, `plan.stopped` or `plan.review_incomplete`, the plan stays active; the status has no
    `prompt changed`. Then push a spec change of a pending unit: the step stops the plan with `inputs_changed`, and the
    next step judges every subject.
  - SCN-YOLO-288: a version-4 `plan.review_incomplete` that answered A; and a dry-run cache file with version-4 lines
    (see `review_worktree.cache_path` and `tests/unit/yolo/test_yolo_review_worktree.py`).
  - SCN-YOLO-307: seed `plan.admitted`, a version-4 `plan.reviewed`, `plan.activated` with the current digests and
    `plan.stopped{reason: unit_rejected, unit: A, digest: <A's digest>}`. The activation's refusal ends with
    `Fix: l4 yolo review p1 --local`; `l4 yolo review p1` and the status's `Next:` line name it; after
    `l4 yolo review p1 --local` (a fake judge, as `test_yolo_commands_activate.py::fake_judge`) the activation exits 0.

  SCN-YOLO-285..288 need no code beyond 1.2: a failure there is a finding; report it, do not change the rule.
  SCN-YOLO-307 needs the fix text, when the review of a plan stopped with `unit_rejected` is stale: in `run_activate`
  (the stale branch), in `run_review`'s message for that stop (`commands.py` ~1072-1080, `nothing to review`) and in
  the status's next step for it (`commands.py` ~1626-1632). Run the file.

## 2. The actor of plan events (D3; L4-YOLO-102)

- [ ] 2.1 Write the tests first, in a new `tests/unit/yolo/test_yolo_plan_actor.py`: SCN-YOLO-289, -290, -291, -292.
  Use `person` and `agent(world, monkeypatch)`; for "no marker, no terminal" set `_stdin_tty` to False with no marker.
  The report: `l4.yolo.report.render_report(...)`, as `tests/unit/yolo/test_yolo_report_delegate.py` calls it.

  Update the tests that pin the old text: `tests/unit/yolo/test_yolo_commands_activate.py` (~665,
  `"  activated by alex@example.com"` gets ` (person)`), `tests/unit/yolo/test_yolo_idle_runs.py` (~170, the status
  document gets `activated_actor` and `activated_marker`), and any other the run of 2.3 shows. Run them and see them
  fail.
- [ ] 2.2 Then change the code:
  - `src/l4/yolo/commands.py`: `run_activate`, `run_resume`, `run_cancel` record `actor`, `marker`,
    `harness_version`; `_describe` adds `activated_actor`, `activated_marker`, `resumed`; `_render` prints the kinds.
    One helper `_kind(actor, marker) -> str | None` (None for no actor) serves status and report.
  - `src/l4/yolo/model.py` (`PlanState.activated_actor`, `activated_marker`) and `src/l4/yolo/state.py` (the fold).
  - `src/l4/yolo/report.py`: the two lines.
- [ ] 2.3 Run the new file, `tests/unit/yolo/test_yolo_commands_activate.py`, `test_yolo_commands_manage.py`,
  `test_yolo_idle_runs.py`, `test_yolo_state_fold.py`, `test_yolo_contract.py`, `test_yolo_go_activate.py`,
  `test_yolo_report_delegate.py`, `test_yolo_cycle_auto.py` and `test_yolo_cycle_integration.py`.

## 3. The actor of unit commands (D4; L4-OPS-025)

- [ ] 3.1 Write the tests first, beside the existing retry, resume and restart tests: SCN-OPS-54 and SCN-OPS-55 (the
  sweep's label path: `tests/unit/ci/test_sweeper.py`; `grep -rn by=.member tests/unit` finds the cases). Run them and see them
  fail.
- [ ] 3.2 Then pass `actor` from `run_retry`, `run_resume`, `run_restart` through `retry_unit`, `resume_unit`,
  `restart_unit` and `run_unit_in_worktree` to `Orchestrator.resume` and the restart writer. Add the two fields only
  when `actor` is given. Run the tests of 3.1 and `uv run --frozen pytest tests/unit/state -q -x`.

## 4. Doctor CFG-013 (D7; L4-YOLO-103)

- [ ] 4.1 Write the tests first, in a new `tests/unit/doctor/test_checks_cfg_013.py` (copy the setup of
  `tests/unit/doctor/test_checks_cfg_011.py`): SCN-YOLO-293 (the check's result and that `exit_code` of the outcomes is
  OK when it is the only failure) and SCN-YOLO-294; `roles.judges: []` skips. Run it and see it fail.
- [ ] 4.2 Then add `_cfg_013` and `CFG_013` to `src/l4/doctor/checks_config.py`, and the line to its module
  docstring. Run the new file and `uv run --frozen pytest tests/unit/doctor tests/unit/init -q -x`: a test that pins
  the doctor rows of a fresh `l4 init` (one judge) now sees a CFG-013 warning; add it to what that test expects.

## 5. The older CLI (D5; L4-OPS-026)

- [ ] 5.1 Write the tests first, in a new `tests/unit/cli/test_cli_pin.py`, calling `l4.cli.main([...], environ=...)` in
  a temporary git repository with a bare `origin` (copy the setup of a test that runs `main` in a repository, for
  example `tests/unit/yolo/yolo_cmd_world.py`). Monkeypatch `l4.cli_pin.__version__` (or the name `check` reads) to
  `0.4.60`:
  - `pinned_version`: vendored `harness.version` at `origin/main`, in the working tree when the ref is absent
    (SCN-OPS-61); action with the four `uses:` lines of SCN-OPS-58; `harness.version: "x"` gives None; a symlinked or
    1 MB config gives None.
  - SCN-OPS-56: `retry` exits 2 with the text; `git for-each-ref` and the unit ledger are unchanged (no fetch, no
    write). Monkeypatch the handler to fail if it is called.
  - SCN-OPS-57: with `--allow-older-cli` the handler is called and stderr holds the warning.
  - SCN-OPS-59, SCN-OPS-60, SCN-OPS-62 (for 62 a handler monkeypatched to print one JSON document is enough).
  - A table test over `WRITES`: every command name in it is in `l4.commands.HANDLERS`, and every `refuse` command of
    the SPEC text of L4-OPS-026 is in it.

  Run it and see it fail.
- [ ] 5.2 Then write `src/l4/cli_pin.py` (`Pin`, `pinned_version`, `WRITES`, `check`), add `harness.version` to
  `l4.ci.relay.LENIENT_KEYS` and a `lenient_settings_text(config_text, workflow_text)` that `lenient_settings` calls,
  add `--allow-older-cli` to `cli._common` and `_COMMON_KEYS`, and call `cli_pin.check(name, kwargs, app)` in `call()`
  before `dispatch`. Run the new file, `tests/unit/ci/test_relay.py`, `uv run --frozen pytest tests/unit/cli -q -x` and
  `uv run --frozen pytest tests/unit/mcp -q -x` (the MCP tools build their argv from the command's options; the new
  common option must not appear in a tool). The check runs in every `main([...])` call of the test suite, so also run
  each of `tests/unit/yolo`, `tests/unit/state`, `tests/unit/specs`, `tests/unit/init` and `tests/unit/ci` with
  `-q -x`, one at a time: a test whose repository pins a version above `l4.__version__` now exits 2. Fix such a test's
  fixture (a pin at or below the running version), never the rule.

## 6. Documentation (L4-YOLO-104)

- [ ] 6.1 Write the test first, in a new `tests/unit/docs/test_readiness_entry_and_actor_docs.py` (SCN-YOLO-295), in
  the style of `tests/unit/docs/test_readiness_judge_chain_docs.py`. The runbook, the skill and the CHANGELOG already
  hold the text (the spec commit wrote it): check the test passes, and correct the text where it differs from what you
  built.
- [ ] 6.2 Run `uv run --frozen pytest tests/unit/docs tests/unit/skills -q`.

## 7. Checks

- [ ] 7.1 `uv run --frozen python scripts/check_spec.py docs/SPEC.md` and
  `openspec validate readiness-entry-and-actor --strict`.
- [ ] 7.2 Check the code against L4-YOLO-101..104, L4-OPS-025, L4-OPS-026 and their scenarios. Fix the code, or report
  where they differ. Do not change the requirements yourself.
- [ ] 7.3 `uv run --frozen ruff check .` and `uv run --frozen ruff format --check` on the files you changed;
  `uv run --frozen mypy` on `src/l4/yolo src/l4/cli_pin.py src/l4/doctor src/l4/state` if CI runs mypy
  (`grep -n mypy .github/workflows/*.yml pyproject.toml`).
