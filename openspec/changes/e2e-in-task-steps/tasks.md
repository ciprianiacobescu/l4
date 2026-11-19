Read `design.md` first; it names the code each decision touches (D1-D9). Requirement: L4-IMP-101 and the L4-IMP-067
amendment (`docs/SPEC.md`), scenarios SCN-IMP-548..556. Run single test files only (`uv run --frozen pytest <file> -q`),
never a whole directory, never two runs at once, and never a wait loop on `pgrep`.

Test setup for every task below: `make_bench(script, e2e=e2e_config(free_port()))` (`tests/unit/_web_helpers.py`;
add `build=[...]` for a build) and the fixtures of `tests/unit/implementer/conftest.py` (`red_step`, `green_step`,
`result`, `TESTS`, `STUB`, `IMPL`). A red step that writes a browser test is
`Step(writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB, "e2e/test_layout.py": BROWSER},
structured=result("red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]))` with
`BROWSER = "def test_width():\n    assert 1508 == 1500\n"` (any parseable test function: the e2e run is stubbed). Stub
`l4.implementer.tdd.run_e2e` exactly as `stub_e2e` in `tests/unit/implementer/test_fix_chore_e2e.py` does (import it
from there, or copy it into the new module): it records the calls, returns an `E2eRun` whose report holds the statuses
you give, and can raise `ServerNotReady`. Give failing cases a `TestCase(..., message=..., detail=...)` so the excerpt
has text (extend the stub with an optional `details` mapping if needed).

## 1. Which tests are the task's (D1)

- [x] 1.1 Write the tests first in a new `tests/unit/implementer/test_e2e_task_steps.py`:
  - `task_browser_tests(wb, before, after)` after a red commit that added `e2e/test_layout.py::test_width` gives
    `(("e2e/test_layout.py", "test_width"),)`;
  - a red commit that changed only `e2e/conftest.py` and a unit test gives `()`; a `.ts` file under `e2e/` gives `()`;
  - an existing `e2e/test_old.py` with `test_a` and `test_b`, where red changes only `test_b`'s body: only `test_b`;
    where red changes a module-level constant `test_a` reads: `test_a` too (the closure);
  - `after=None` reads the work tree (an uncommitted new browser test is found).
  Run the file and see the tests fail (the name does not exist).
- [x] 1.2 Add `task_browser_tests` to `src/l4/implementer/tdd.py` (D1): `git diff --name-only --no-renames before after`
  (or against the work tree), the paths under `e2e_test_dir(wb.cfg.gates.e2e, wb.worktree)`, `.py`, not `conftest.py`
  or `__init__.py`, matching no `tdd.test_support_globs` glob, no link on the way (`linked_component`), then
  `tamper.facts_of` of the file at `before` (`git show before:path`, empty when absent) and at `after` (`git show` or the
  work-tree file, read with `read_inside`), keeping the names whose `Facts.test` is true at `after` and whose
  `(parts, closure)` differ or that are absent at `before`. Run the tests.

## 2. Green runs them last (D3, D4, D5, D6)

- [x] 2.1 Write the tests first in `test_e2e_task_steps.py`, each driving `run_red` then `run_green` (as
  `tests/unit/implementer/test_tdd_green.py` `red_green` does):
  - SCN-IMP-548: the stub reports `e2e.test_layout::test_width[chromium]` failed with message and detail
    `assert 1508 == 1500`: `GreenOutcome.status == "failed"`, the reason names `e2e.test_layout::test_width[chromium]`
    and starts with `the task's browser tests do not pass`, `outcome.excerpt` holds `assert 1508 == 1500`, the stub was
    called once with `name="e2e-task"` and `must_contain == []`, the task is not ticked; with `run_task`
    (`l4.implementer.loop`) and a second green step, the second green prompt (`bench.adapter.requests[2].prompt`) holds
    `assert 1508 == 1500`;
  - SCN-IMP-549: the stub reports it passed and `build=[f"{sys.executable} scripts/build.py"]` writes `.l4-out/built`
    (as `test_the_build_runs_before_the_e2e_gate` does): done, the build ran before the e2e stub, the e2e stub's
    `writes={"test-results/trace.zip": "x"}` and the build output are not in the green commit (`git show --stat HEAD`);
  - SCN-IMP-550: a red step with no browser test, and a bench whose `e2e` has `command` but no `serve` (pass a dict
    without `serve`): the stub is never called;
  - SCN-IMP-551: the stub raises `ServerNotReady` with a log `Error: listen EADDRINUSE`: failed, the reason starts with
    `the e2e server was not ready (see`, the excerpt holds `EADDRINUSE`;
  - SCN-IMP-552: two browser tests, the report holds only `test_a`, or holds `test_b[chromium]` as `skipped`: failed
    naming `test_b`; a report that also holds another failing e2e test that is not the task's and the task's test
    passed: done;
  - SCN-IMP-553: a green step that breaks a unit test: the stub is not called; a green step whose lint fails (the lint
    command of `tests/unit/implementer/test_static_gates_first.py`): the stub is not called and
    `GreenOutcome.near_pass` is set;
  - a gate that timed out and a report with a collection error of `e2e.test_layout`: failed with the reasons of D4;
  - SCN-IMP-555: after `run_red`, build a new `RedOutcome` with `resume_red(bench.wb, TASK)` and run `run_green` with it:
    the stub is called.
  Run them and see them fail.
- [x] 2.2 Then implement in `src/l4/implementer/tdd.py`: `_task_e2e_reason(wb, task, base, tests, keep, freeze_phase)`
  in the shape of `_e2e_chore_reason` (`_tree_state`, `run_build_only`, `run_e2e(wb, name="e2e-task")`,
  `ServerNotReady` -> `(f"the e2e server was not ready (see {name})", _log_tail(...))`, the judging of D4 in its order,
  `excerpter(wb)(report, failing)`, and `_drop_gate_output(..., freeze_phase=...)` in a `finally`); give
  `_drop_gate_output` the keyword `freeze_phase: str | None = "single"` (None: no `freeze_test_paths`); call it in
  `run_green` where D3 says, with `browser = task_browser_tests(wb, f"{red_sha}^", red_sha) if e2e_configured(wb.cfg)
  else ()` computed once before the agent step. Run the new tests and
  `uv run --frozen pytest tests/unit/implementer/test_fix_chore_e2e.py -q`, then
  `tests/unit/implementer/test_tdd_green.py`, `tests/unit/implementer/test_near_pass_carry.py`,
  `tests/unit/implementer/test_static_gates_first.py`, `tests/unit/implementer/test_replay_green_freeze.py` and
  `tests/unit/implementer/test_baseline_reuse.py`, one at a time.

## 3. The already-satisfied finish (D2)

- [x] 3.1 Write the test first (SCN-IMP-554), on the pattern of
  `tests/unit/implementer/test_already_satisfied.py::test_tests_of_existing_behaviour_are_pre_satisfied_and_commit_as_already_satisfied`:
  the same red step plus `e2e/test_existing_ui.py` with a test function, and the stub reports it failed: `run_red`
  returns `failed` naming it, HEAD did not move, no `task.done`; with the stub reporting it passed, the task is done as
  already satisfied and the commit holds the browser test file. Run it and see it fail.
- [x] 3.2 Then, in `finish_already_satisfied` (`run_red`), after the restored test run and `tampered("restored test
  run")` and before `outside_links_reason`: `task_browser_tests(wb, base, None)`; when not empty and `e2e_configured`,
  `_task_e2e_reason(..., freeze_phase=None)`, then `tampered("e2e run")`; a reason discards the changes and returns
  `RedOutcome("failed", reason, excerpt=excerpt)`. Run the test and `tests/unit/implementer/test_already_satisfied.py`,
  `tests/unit/implementer/test_already_satisfied_c22.py`, `tests/unit/implementer/test_already_satisfied_no_test.py`.

## 4. The prompts (D7)

- [x] 4.1 Write the tests first in `test_e2e_task_steps.py` (or `tests/unit/implementer/test_prompt.py`, with
  `render_prompt` and a `PromptContext`): a green context with `browser_tests=("e2e/test_layout.py::test_width",)`
  renders `# Browser tests of this task`, the sentence of D7 and the test in a `browser tests of this task` data block;
  without it, the green prompt is unchanged (compare with the text before the change); a red context with `e2e_dir`
  holds the new sentence (`frozen after this step`). Run and see them fail.
- [x] 4.2 Then add `PromptContext.browser_tests: tuple[str, ...] = ()` and the block (green only) and the sentence (red,
  in the `ctx.e2e_dir` paragraph) in `src/l4/implementer/prompt.py`; `_prompt` in `tdd.py` passes `browser_tests` for
  the green role (`f"{path}::{name}"`). No template file changes. Run the prompt tests
  (`tests/unit/implementer/test_prompt.py`, `test_prompt_context.py`, `test_prompt_cap.py`).

## 5. The run deadline (D8)

- [x] 5.1 Write the test first in `tests/unit/test_deadline.py`: `cap_s("green", 600, 1800, e2e=True) == 3600`,
  `cap_s("green", 600, 1800) == 2400`, `cap_s("red", 600, 1800, e2e=True) == 2400`, and SCN-IMP-556 through
  `check_before` with a recorded green step of 3300 s: the mark's `estimate_s` is 3300 with the e2e cap and 2400
  without. Run and see it fail.
- [x] 5.2 Then add the keyword to `cap_s` and `deadline.check` (`src/l4/deadline.py`), and pass
  `e2e=e2e_configured(wb.cfg)` from `_check_step` in `src/l4/implementer/loop.py`. Run `tests/unit/test_deadline.py`
  and `tests/unit/implementer/test_step_deadline.py`.

## 6. Checks

- [x] 6.1 `docs/SPEC.md` holds L4-IMP-101, the L4-IMP-067 amendment, SCN-IMP-548..556 and change-table row 133. Check
  them against the code and tell the orchestrator where they differ; do not edit `docs/SPEC.md`, `CHANGELOG.md` or
  `docs/runbook.md`. Run `uv run --frozen python scripts/check_spec.py docs/SPEC.md`.
- [x] 6.2 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.
