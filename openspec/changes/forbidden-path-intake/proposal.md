# A task that names a forbidden file is refused before any run, and the note names the right fix

## Why

Twice on consumers a unit's `tasks.md` told the implementer to create a file that `odd.forbidden_paths` forbids (the
default list holds `**/migrations/**` and `infra/**`). One case was a web framework's first migration
`<app>/migrations/0001_initial.py` [V, a consumer's unit ledger of 2026-10-29]:

- the write guard removed the file after every step (`guard.violation{rule: "**/migrations/**", action: removed}`);
- the agent's retry hint was the generic one, which says neither "forbidden path" nor "ask";
- after about an hour and 7 attempts the unit raised a technical question, and the harness note on it said how to
  unfreeze the unit's test file, which cannot help: no answer lets an agent write a forbidden path;
- a person narrowed `odd.forbidden_paths` in `.l4/config.yaml` and answered.

Every input needed to see this is known before the first run: the task's text, the forbidden globs, and the tree.

## What changes

- A deterministic intake rule, in `l4.yolo.plans.intake` (plan check, review, activation, `go`, the CI review) and in
  the unit-start check (`_lint_scenarios`, phases before implementing, OpenSpec and Kiro):
  - **blocker** `forbidden_path`: a pending required task's own text (`task_text`) names a file-like path (it has an
    extension and no trailing `/`) that does not exist in the tree being checked and that an `odd.forbidden_paths`
    glob matches, unless the line says not to touch it ("do not", "don't", "never", "must not", "without" before the
    path on that line);
  - **warning**: the same match for a file that exists, a directory token, or a mention in design, proposal or spec
    deltas.
  - The message names the task, the path, the glob and the fix: set `odd.forbidden_paths` in `.l4/config.yaml` on the
    base branch to an explicit list without that glob (there is no exclusion syntax), or have a person commit the file
    on the base branch first. When the glob is also a contract glob (`.github/workflows/**`, `.gitlab-ci.yml`), the
    config option is not offered.
- The agent's retry hint for a forbidden-path removal says: no agent step may write it and no answer lifts that; do not
  write it again; if the task needs it, report blocked with a technical question naming the path and the rule.
- The harness note on a question raised after such a removal, or naming such a path, replaces the unfreeze note: a
  person commits the file on the unit branch, or narrows `odd.forbidden_paths` on the base branch, then answers.

## Impact

- Code: `l4.security.protected` (`forbidden_rule`), a path finder shared from `l4.delegate.reply.named_paths` (moved
  to a module the intake can import), `l4.yolo.plans`, `l4.yolo.admit`, `l4.orchestrator`, `l4.implementer.guardnotes`,
  `l4.implementer.workbench`, `l4.implementer.loop`, `l4.implementer.unfreeze`.
- Spec: L4-YOLO-092 added; L4-YOLO-002, L4-IMP-006, L4-IMP-015 amended; SCN-YOLO-246 to SCN-YOLO-254, SCN-IMP-423 to
  SCN-IMP-425 added; change-table row 90.
- Not in this change: the skill's offline plan validator (`validate_plan.py`) does not run the rule (deferred; it
  needs a copy of the glob compiler); the delegate is not taught to escalate such a question without a model call.
