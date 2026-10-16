# Writing a spec that passes the readiness review

The judge reads each unit's folder and the folders it depends on, never the code. Each rule below prevents one finding
kind. Fix these before the first review. On a finding, fix all of a unit's files together (spec, proposal, tasks,
design agree): a fix in one file often raises a consistency finding in another.

- **testability.** Every SHALL has a scenario, failure and "nothing to do" cases included. A scenario is decidable by a
  test that always runs: no wall-clock bound without a tolerance, no outcome that depends on a person.
- **contradiction.** Proposal, design, specs and tasks say the same thing. Use no line-number anchors: they go stale.
- **interfaces.** Name every helper one unit gives another, with its signature, in the spec, not only in `tasks.md`.
- **missing_dependency.** Add `depends_on` when two units edit one function or file section, or when a document
  describes what another unit creates.
- **failure_cases.** Say what happens when a stage does not run, raises, or gets bad input.
- **feasibility.** Use only tools the runner has. Say in prose what is already delivered; ticked tasks are done. When a
  spec relies on code already on the base branch, name it in the spec (module, function, values) instead of adding a
  dependency.
- **material_cut.** Stay inside the review budgets (`yolo.review.max_file_chars`, `max_folder_chars`,
  `max_dependency_chars`; `validate_plan.py` prints overruns: a unit's own folder over the budget is an error, a dependency's folder a
  warning). Move background to `docs/`.
- **OpenSpec form.**
  - Where `openspec/specs/<cap>/` does not exist on the base branch, write `## ADDED Requirements` and a `## Purpose`.
  - A MODIFIED block keeps every scenario name of the requirement it replaces.
  - Keep each requirement statement short.

Before the push, run both:

```sh
openspec validate <change> --strict   # or --all --strict; or: npx --yes @fission-ai/openspec@1.14.0 validate --all --strict
python3 <skill dir>/scripts/validate_plan.py
```

Then check the whole plan with `l4 yolo review <id> --worktree` (see `plan.md`).
