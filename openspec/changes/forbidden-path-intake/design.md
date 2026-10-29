# Design: forbidden-path-intake

## Context (verified on amaster b4cf62b5, read-only analysis of 2026-10-29)

- `FORBIDDEN_PATHS` (src/l4/config/defaults.py) = `.github/workflows/**`, `.gitlab-ci.yml`, `**/migrations/**`,
  `infra/**`; `odd.forbidden_paths` replaces it, `extra_forbidden_paths` appends (src/l4/config/schema.py).
- `ProtectedSet.match` (src/l4/security/protected.py) walks each parent prefix: contract list first, then
  `odd_forbidden` and family globs, then unit folders, then the spec root. `_compile` has no negation.
- `revert_protected` emits `guard.violation{path, rule, action}`; `rule` is the glob string.
- Admission: `admit()` (src/l4/yolo/admit.py) turns `UnitInfo.intake_ok/detail` into the `intake` finding; it runs
  from `l4 yolo check` (and `--worktree`), `review`, `activate`, `accept --force`, the CI review and `go`.
  `plans.intake()` and `unit_infos()` (src/l4/yolo/plans.py) take no config today.
- Unit start: `run_unit` → `_lint_scenarios` → `_validate_openspec` (phases None/INTAKE/READY) or `_validate_kiro` →
  `_reject` (`unit.rejected{reasons}`, exit 14); a plan stops `unit_rejected`, and the plan step's text already names
  "a corrected configuration: `l4 yolo activate` alone".
- `named_paths(text, globs)` (src/l4/delegate/reply.py) finds bare and backticked paths; `task_text`
  (src/l4/specs/tasks_text.py) gives one task's block.
- Notes: `_with_note` (src/l4/implementer/loop.py) → `unfreeze_note` (src/l4/implementer/unfreeze.py) on every
  technical question of a green step; `note_of` in src/l4/implementer/guardnotes.py has no advice for a forbidden
  path, so `_GENERIC` is used.

## D1 Matching

`forbidden_rule(path, globs) -> str | None` in `l4.security.protected`: the first glob of `globs` that matches `path`
or a parent prefix, with the walk `ProtectedSet.match` uses (factor it out; `match` keeps its behaviour). The intake
passes `cfg.odd.forbidden_paths` (with `extra_forbidden_paths` applied as the config does) and nothing else: the
contract list, unit folders and the spec root are named by every spec.

## D2 The intake rule

`forbidden_named(unit_dir, tree_has, globs) -> list[Finding]`, pure, in a module `l4.yolo.forbidden` (or next to
`plans.intake`), where `tree_has(path) -> bool` answers whether a file or directory exists in the tree checked:
- for each pending (not `[x]`) required task, the paths `named_paths` finds in `task_text`: a file-like token (an
  extension, no trailing `/`) that `forbidden_rule` matches, that `tree_has` says is absent, and whose line has none of
  "do not", "don't", "never", "must not", "without" before it → blocker;
- the same match for an existing file, a directory token, or a path found in design.md, proposal.md or the spec
  deltas → warning;
- message: `forbidden_path: task <id> names <path>, which odd.forbidden_paths rule <glob> forbids: no agent step may
  write it. Fix: in .l4/config.yaml on the base branch, set odd.forbidden_paths to an explicit list without <glob>
  (there is no exclusion syntax), or have a person commit <path> on the base branch first.` For a contract glob
  (`.github/workflows/**`, `.gitlab-ci.yml`) the first fix is left out.

`named_paths` moves to a neutral module (e.g. `l4.specs.paths`); `l4.delegate.reply` re-exports it, so its callers and
tests keep working.

## D3 Where it runs

- Plan side: `plans.intake()` and `unit_infos()` take the forbidden globs and a `tree_has` for the revision checked
  (the workspace checkout of that revision); a blocker makes `intake_ok` false with the message as `detail`. Warnings
  are printed as `warning:` lines by `l4 yolo check` (and `--worktree`) and `l4 yolo go`, exit unchanged, as
  `budget_overruns` does.
- Unit side: `_lint_scenarios` runs it for both frameworks in the phases before implementing (`_OPENSPEC_INTAKE_PHASES`),
  on the unit's worktree; a blocker is a reject reason (exit 14). A unit already implementing is not rejected.

## D4 The retry hint

`Workbench.emit` passes the forbidden globs (`protected.odd_forbidden`) to `note_of`; a violation whose rule is one of
them gets: "`<path>` matches `odd.forbidden_paths` (`<glob>`): no agent step may write it, and no answer lifts that.
Do not write it again; if the task needs it, report blocked with a technical question naming the path and the rule."

## D5 The question note

In `_with_note`: when this attempt's guard notes hold a forbidden-path removal, or `named_paths` finds in the question's
text a path that `forbidden_rule` matches, the note is (instead of `unfreeze_note`): "Harness note: `<path>` is
forbidden by `odd.forbidden_paths` (`<glob>`). No agent may write it and no answer changes that; unfreezing a test does
not help. A person commits `<path>` on the unit branch (listed, not reverted: L4-SEC-004), or sets
`odd.forbidden_paths` in `.l4/config.yaml` on the base branch to an explicit list without `<glob>`; then answer with
`l4 questions answer Q-NNN --unit <unit> --text "..."`."

## D6 Not changed

The guard itself, `ProtectedSet.match`'s results, the delegate, and `validate_plan.py`.
