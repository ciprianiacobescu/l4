Read `design.md` first. It names every function, field and rule. Read L4-YOLO-105..108 in `docs/SPEC.md` too, and the
scenarios SCN-YOLO-296..306.

This change can be cut at integration: keep its code, tests and docs in their own commits, and depend on nothing of
`readiness-entry-and-actor` except the last step of task 4.3.

Rules for every task:
- Write the tests first, run them, and see them fail.
- Then write the code, and run the tests the task names.
- Run only the test files named. Never the whole suite.
- Never use a `while pgrep` loop.

**Test techniques.**
- Plan commands: `tests/unit/yolo/yolo_cmd_world.py` (`world`, `forge`, `ev`, `world.reviewed(verdicts,
  findings)`, `world.seed`, `world.l4(...)`) and `tests/unit/yolo/yolo_actor.py` (`person`, `agent`). A batch entry:
  set `event.data["batches"]["b1"]` on `world.reviewed()`; give it a `material` (any 16 hex), as a recorded review has.
  See `tests/unit/yolo/test_yolo_commands_force_accept.py` and `test_yolo_commands_activate.py` for the shapes.
- A finding id: `l4.yolo.findings.finding_id(subject, finding)`.
- Readiness prompts: `tests/unit/yolo/yolo_review_world.py` and a scripted `FakeAdapter` (`fake.requests[i].prompt`).
- The CI step: `tests/unit/yolo/yolo_cycle_world.py`.

## 1. The rules (D2, D3, D4, D8)

- [x] 1.1 Write the pure tests first, in a new `tests/unit/yolo/test_yolo_overrule_rules.py`:
  - `accept.JUDGE_CRITERIA` equals the criterion enum of `l4/yolo/schemas/readiness.schema.json`.
  - `overrule_check`: each refusal of SCN-YOLO-298, and the subject and finding for SCN-YOLO-296.
  - `overrule_holds`: same material and finding (True); other material (False); finding gone (False); withdrawn (no
    key).
  - `effective`: the three cases of SCN-YOLO-300, a harness finding left, nothing held.
  - The fold: SCN-YOLO-303's second part; a replace; a withdrawal; `activated_overruled` from `plan.activated`.

  Run it and see it fail.
- [x] 1.2 Then change `src/l4/yolo/accept.py` (`JUDGE_CRITERIA`, `overrule_check`, `overrule_holds`, `effective`, the
  held ids in `check`), `src/l4/yolo/model.py` and `src/l4/yolo/state.py`. Run the new file and
  `tests/unit/yolo/test_yolo_accept_rules.py tests/unit/yolo/test_yolo_state_fold.py`.

## 2. The command (D1)

- [x] 2.1 Write the tests first, in a new `tests/unit/yolo/test_yolo_commands_overrule.py`: SCN-YOLO-296, -297 (the
  MCP part: `l4.mcp.tools.TOOLS` has no tool whose words are `yolo overrule`), -298 (through the command), -302 (the
  withdrawal by an agent), -303 (the first part); the reason rules (empty, 1,001 characters); `--yes` for a person
  records `confirmed: --yes`; a lost lease says the plan moved (as `test_a_lost_lease_says_the_plan_moved` of the force
  tests). Run it and see it fail.
- [x] 2.2 Then add `run_overrule` to `src/l4/yolo/commands.py`, the `yolo overrule` entry to `src/l4/cli.py` and to
  `HANDLERS` and `OWNING_CHANGE` in `src/l4/commands.py`. Run the new file, `tests/unit/cli -q -x` and
  `tests/unit/mcp/test_tools.py`.

## 3. The readers (D4, D5, D6)

- [x] 3.1 Write the tests first, in a new `tests/unit/yolo/test_yolo_overrule_activation.py`: SCN-YOLO-299, -300,
  -301, -302 (the activation part), and `l4 yolo go p1 --reason r --json` as a person after an overrule that clears
  the only problem: it does not stop at `findings`. The report: `l4.yolo.report.render_report` as
  `tests/unit/yolo/test_yolo_report_delegate.py` calls it. Run it and see it fail.
- [x] 3.2 Then change `_review_view`, `run_activate`, `_describe` and `_render` in `src/l4/yolo/commands.py`,
  `render` and the JSON of `src/l4/yolo/findings.py`, the refusal fix of `accept.check`, and `src/l4/yolo/report.py`.
  Run the new file and `tests/unit/yolo/test_yolo_commands_activate.py tests/unit/yolo/test_yolo_commands_findings.py
  tests/unit/yolo/test_yolo_commands_manage.py tests/unit/yolo/test_yolo_go_accept.py
  tests/unit/yolo/test_yolo_go_activate.py tests/unit/yolo/test_yolo_report_delegate.py`.

## 4. The rebuttal (D7)

- [x] 4.1 Write the tests first, in a new `tests/unit/yolo/test_yolo_readiness_overrule_note.py`:
  - SCN-YOLO-304 with `review_plan_costed(..., overruled={"batch:b1": [row]})`: the note and the data block after the
    plan entry in the batch prompt, and in each part with `yolo: {review: {max_batch_chars: 1000}}`; the batch's
    `material` equals the one of the same call without `overruled`; the unit prompts hold no note.
  - SCN-YOLO-305: with `overruled={}` every prompt and key equals the call without the argument.
  - Outside the data blocks the note names no unit and no batch (strip the blocks as `test_yolo_readiness_parts.py`'s
    `outside_data` does).
  - The bounds: six overrules give five blocks, newest first; a 3,000-character text and a 1,500-character reason are
    cut.
  - The CI step passes `findings.overruled_for_review(state)`: with the cycle world, an overrule in the ledger and a
    changed spec, the judge's prompt holds the note.

  Run it and see it fail.
- [x] 4.2 Then change `src/l4/yolo/readiness.py` (`OVERRULED_NOTE`, `MAX_OVERRULED`, the `overruled` parameter, the
  three subject builders), `src/l4/yolo/findings.py` (`overruled_for_review`), `src/l4/yolo/cycle.py`,
  `src/l4/yolo/commands.py` (`--local`) and `src/l4/yolo/review_worktree.py`. Run the new file and the readiness files
  named in task 1.3 of `readiness-entry-and-actor` (or, without that change, `tests/unit/yolo/test_yolo_readiness*.py`).
- [x] 4.3 When `readiness-entry-and-actor` is in: add `yolo overrule` to `cli_pin.WRITES` (`refuse`, and `warn` with
  `--withdraw`), with a row in its table test.

## 5. Documentation (L4-YOLO-108)

- [x] 5.1 Write the test first, in a new `tests/unit/docs/test_readiness_overrule_docs.py` (SCN-YOLO-306). The
  runbook, `references/plan.md` and the CHANGELOG already hold the text (the spec commit wrote it): check the test
  passes, and correct the text where it differs from what you built.
- [x] 5.2 Run `uv run --frozen pytest tests/unit/docs -q`.

## 6. Checks

- [x] 6.1 `uv run --frozen python scripts/check_spec.py docs/SPEC.md` and `openspec validate readiness-overrule
  --strict`.
- [x] 6.2 Check the code against L4-YOLO-105..108 and SCN-YOLO-296..306. Fix the code, or report where they differ. Do
  not change the requirements yourself.
- [x] 6.3 `uv run --frozen ruff check .` and `uv run --frozen ruff format --check` on the files you changed;
  `uv run --frozen mypy` on `src/l4/yolo` if CI runs mypy.
