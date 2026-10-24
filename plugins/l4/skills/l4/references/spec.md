# Writing a spec that passes the readiness review

The judge reads each unit's folder and the folders it depends on, never the code. Each rule prevents one finding
kind; fix them before the first review. On a finding, fix all of a unit's files together: a fix in one file often
raises a consistency finding in another.

- **testability.** Every SHALL has a scenario, failure and "nothing to do" cases included, decidable by a test that
  always runs: no wall-clock bound without a tolerance, no outcome that depends on a person.
- **unchanged behaviour.** A scenario that already holds at the base is proven only if zeroing the public functions
  its tests import makes one fail by assertion. Test a public module-level function and assert its result's type
  before using it; code nested in a factory (`create_app()`) cannot be zeroed, so leave those cases to existing tests
  and design.md's failure cases. Logic a test checks belongs in a project module.
- **contradiction.** Proposal, design, specs and tasks say the same thing; no line-number anchors (they go stale).
- **interfaces.** Name every helper one unit gives another, with its signature, in the spec.
- **missing_dependency.** Add `depends_on` when two units edit one function or file section, or when a document
  describes what another unit creates.
- **test-support files.** A task that must change a Python test-support file names it exactly, in code font:
  `conftest.py`, not "the conftest", in the task line or its section heading. Only that task's green step may change
  it, from a reviewed text (an active plan or the base branch). A data fixture or an ignore file needs a
  person's answer. `[test-infra]` does not open a support file in green.
- **existing tests and helpers.** In the task line, name an existing test to change as `path::name` (at most 5) and
  a new helper module by path: red changes the test in place and stubs the helper, green fills it in.
- **tasks.** Each task writes its own tests (red), then its code (green): no "failing tests" task before a "fix" task,
  no gates-only task. A document edit needs a scenario.
- **failure_cases.** Say what happens when a stage does not run, raises, or gets bad input.
- **feasibility.** Use only tools the runner has. Say in prose what is already delivered; ticked tasks are done. Name
  base-branch code the spec relies on (module, function, values) instead of adding a dependency.
- **material_cut.** Stay inside the review budgets (`yolo.review.max_file_chars`, `max_folder_chars`,
  `max_dependency_chars`; `validate_plan.py` prints overruns: an error for a unit's own folder, a warning for a
  dependency's). Move background to `docs/`.
- **OpenSpec form.**
  - Where `openspec/specs/<cap>/` does not exist on the base branch, write `## ADDED Requirements` and a `## Purpose`.
  - A MODIFIED block keeps every scenario name of the requirement it replaces.
  - Keep requirement statements short.

Kiro authors: see `kiro.md` for what the prompt carries.

Before the push, run:

```sh
openspec validate <change> --strict   # or --all --strict; or: npx --yes @fission-ai/openspec@1.14.0 validate --all --strict
python3 <skill dir>/scripts/validate_plan.py
```

Then check the whole plan with `l4 yolo review <id> --worktree` (see `plan.md`).
