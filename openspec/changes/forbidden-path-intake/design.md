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

`forbidden_named(ref, tree_has, globs, *, nested=None) -> list[PathFinding]`, in a module `l4.yolo.forbidden`, reads the
unit's spec files (nothing else). `tree_has(path) -> bool` answers whether the tree checked has the path; `nested(path)`
whether a tracked file ends with `/<path>`. Both come from `TreeIndex`, the tracked files of the revision checked:
`git ls-tree -r` of the revision for a revision, `git ls-files` (the index: a staged file counts) for a working-tree
check, read once and on first use. An untracked or ignored file on disk does not count. If the tree cannot be read, the
files on disk answer, and `nested` is False.

For each pending (not `[x]`, not optional) required task, the paths `named_paths` finds in `task_text`, line by line:
- nothing for a token whose first segment looks like a host (it has a dot and does not start with one:
  `github.com/org/repo/...`; `.github/...` is still checked), for a `..` path, and for a line that says not to touch
  the path or that a person delivers it: "do not", "don't", "never", "must not", "without" before the path (a `./`
  before the path does not hide it), or "a person commits", "committed by a person", "a person adds" anywhere on the
  line (case-insensitive);
- otherwise a file-like token (an extension, no trailing `/`) that `forbidden_rule` matches and `tree_has` says is
  absent is a **blocker**, unless `nested` says the same file exists one directory deeper (a monorepo: a warning);
- the same match for an existing file, a directory token, or a path found in design.md, proposal.md or the spec
  deltas is a **warning**.

The blocker message: `forbidden_path: task <id> names <path>, which odd.forbidden_paths rule <glob> forbids: no agent
step may write it. Fix: in .l4/config.yaml on the base branch, set odd.forbidden_paths to an explicit list without
<glob> (there is no exclusion syntax), or have a person commit <path> on the base branch first, or reword the task (for
example `Do not create <path>`; a person commits it).` For a contract path (`.github/workflows/**`, `.gitlab-ci.yml`)
the config fix is left out.

`named_paths` and `names_path` move to a neutral module (`l4.specs.paths`); `l4.delegate.reply` and
`l4.implementer.unfreeze` import them from there, so their callers and tests keep working.

## D3 Where it runs

- Plan side: `plans.intake()` and `unit_infos()` take the forbidden globs and a `TreeIndex` of the revision checked; a
  blocker makes `intake_ok` false with the message as `detail`, but only for a unit whose phase is none, `intake` or
  `ready`: a unit already implementing (its base-branch tasks.md is still unticked, and a person commits the file on
  the unit branch) gets the same text as a warning, so that re-activation, `accept --force` and the CI re-review are
  not blocked. Warnings are printed as `warning:` lines by `l4 yolo check` (and `--worktree`) and `l4 yolo go`, exit
  unchanged, as `budget_overruns` does.
- Unit side: the validators of `_lint_scenarios` run it for both frameworks in the phases before implementing
  (`_OPENSPEC_INTAKE_PHASES`), with the files tracked at the HEAD of the unit's worktree; a blocker is a reject reason
  (exit 14). A unit already implementing is not rejected.

## D4 The retry hint

`Workbench.emit` passes the forbidden globs (`protected.odd_forbidden`) to `note_of`; a violation whose rule is one of
them gets: "`<path>` matches `odd.forbidden_paths` (`<glob>`): no agent step may write it, and no answer lifts that.
Do not write it again; if the task needs it, report blocked with a technical question naming the path and the rule."

## D5 The question note

In `_with_note`, for a technical question, the forbidden note replaces the unfreeze note when
- (a) this attempt's guard notes hold a forbidden-path removal, or
- (b) the question names a path that `forbidden_rule` matches and that does NOT exist in the unit worktree, and its
  first option names no frozen file (a test, support or ignore file of the red step).

Otherwise the unfreeze note is kept as before: a question that only mentions an existing forbidden file (a migration
a frozen test disagrees with) is about the frozen test. The note is: "Harness note: `<path>` is forbidden by
`odd.forbidden_paths` (`<glob>`). No agent may write it and no answer changes that. A person commits `<path>` on the
unit branch (listed, not reverted: L4-SEC-004), or sets `odd.forbidden_paths` in `.l4/config.yaml` on the base branch to
an explicit list without `<glob>`; then answer with `l4 questions answer Q-NNN --unit <unit> --text "..."`." It does
not mention unfreezing (SCN-IMP-424), and for a contract path it leaves the config fix out. At most three paths are
named.

## D6 Not changed

The guard itself, `ProtectedSet.match`'s results, the delegate, and `validate_plan.py`.
