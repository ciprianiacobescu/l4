# Making and updating a delivery plan

A plan is the file `.l4/plans/<id>.json` on the base branch. It orders spec units (OpenSpec changes, Kiro specs) and
sets limits. Your job is to write that file correctly and hand it to a person. The full guide for the person is
`docs/yolo-mode.md`; stops are in `docs/runbook.md` section 12.

**When to make one.** Only when specs must run in an order. One spec, or specs with no order between them, need no
plan: they run as usual. Every spec of the repository must be in a plan or in a plan's `exclude`.

**Waves are not parallel runs.** The validator prints waves: what COULD run together because nothing orders it. The
plan still runs one unit at a time, in the printed order.

## Create

1. Start from the scaffold. It lists every spec that no plan lists, in one batch `unplanned`, with no dependencies,
   and writes nothing else (no commit, no push, no model call):

   ```sh
   l4 yolo draft <id> [--target BRANCH] [--merge human|auto]
   ```

   It refuses an existing file. It puts a finished spec into `exclude` with the reason `already <phase>` (for example
   `already merged`, `already archived`).
2. Check the state of every spec before you order it: `l4 status`, or `l4 plan`. `l4 yolo draft` fetches the unit
   refs by itself (offline it says the phases may be old); `l4 status` and `l4 plan` do not. In a fresh clone, fetch
   the harness state first (`git fetch origin '+refs/l4/*:refs/l4/*'`): without it they show old phases, for example
   `verified` for a unit that is in review or merged. A unit that is started, in review or
   has an open PR is not new work. Exclude it with a reason a person can check (`in review before the plan: PR #8`), or
   plan it knowingly and say so in the hand-off. Under `merge: auto` the plan adopts a unit in review with a PASS and
   merges it. Finished specs and specs left out on purpose go in `exclude`, never only in the hand-off message.
3. Read each spec's proposal or requirements, and its tasks. Add `depends_on: ["<unit id>"]` **only** when a spec
   uses something that another spec introduces or changes: a module, a function, a data field, a file, an endpoint, a
   config key. Two specs that change the same code in conflicting ways are ordered too. Prefer fewer edges. A guess is
   not evidence: when you cannot point to a line, add no dependency.
4. Use a batch to group units that share an acceptance check (`acceptance_profile`, a profile of `yolo.profiles`).
   Do not invent profiles.
5. Put a spec that must stay outside the plan in `exclude` with a reason that a person can check (200 characters). A
   spec meant to run alone goes there too, with that reason. An excluded unit is not held by the plan: it runs as
   without a plan while no plan is active on the target, and gets no new agent work while one is active, like every unit
   outside the plan. A spec that `yolo.hold` matches is held and counts as covered, so it needs no entry.
6. Set `limits.max_runs` and `limits.max_cost_usd`. They stop a plan whose unit makes no progress; without them only
   the attempts limit does. Allow about five runs per unit.
7. Leave `merge` as `human`. Set `merge: auto` only when the person asks for it **and** `forge.merge_policy` is `auto`.
8. Leave `promotion` out unless the person names the branch and it exists on the remote (`git ls-remote --heads origin
   <branch>`). Never invent one. `promotion` is `{"mode": "manual", "target_branch": "<branch>"}`, only a note for the
   hand-off: L4 never promotes.

Example: `add-pricing` adds a module, `use-pricing` calls it, `report-export` is independent, `legacy-import` is
deliberately outside.

```json
{
  "schema": "l4/delivery-plan@1",
  "plan_id": "pricing",
  "target": "l4/main",
  "merge": "human",
  "limits": {"max_cost_usd": 20, "max_unit_attempts": 2, "max_runs": 20},
  "external_dependencies": [],
  "batches": [
    {"id": "pricing", "depends_on": [], "units": [
      {"id": "openspec:add-pricing", "depends_on": []},
      {"id": "openspec:use-pricing", "depends_on": ["openspec:add-pricing"]}
    ]},
    {"id": "reports", "depends_on": [], "units": [
      {"id": "kiro:report-export", "depends_on": []}
    ]}
  ],
  "exclude": [
    {"id": "kiro:legacy-import", "reason": "owned by another team; its PR is open"}
  ]
}
```

Here `add-pricing` and `report-export` are in wave 1 and `use-pricing` is in wave 2; the plan still runs them one
after the other.

## Validate

Before the push, run the check from the repository root and fix every problem it prints. Never silence one: not by
deleting a dependency you cannot justify, nor by excluding a spec only to make the check pass.

```sh
l4 yolo check <id> --worktree
```

It reads the plan files and the units from the working tree, so it runs before the push and changes nothing. Without the
harness installed, run the standalone script instead: `python3 <skill dir>/scripts/validate_plan.py`. After the push,
`l4 yolo check <id>` runs the same admission on the target, as the last step of the hand-off; CI runs it and the review.

- It checks the schema, the graph (cycles, unknown units, duplicates), open questions, intake, finished units, profiles,
  the target against `forge.base_branch`, the merge policy, and the coverage across all plan files (`uncovered`,
  `covered_twice`). Exit 0, or 2 with findings; on success it prints the dispatch order. A planned unit whose change is
  archived is refused as `unknown_unit`, unless this plan already merged or integrated it.
- The script needs only Python and checks what the harness checks without a network (not open questions, intake or
  profiles). Exit 0 is valid, 1 lists problems. A planned archived unit prints `finished: <id>`: remove it.
- Errors (script, exit 1): a planned unit's own folder over the budget; a delta with no baseline or no `## Purpose`. A
  dependency's folder over the budget is only a `warning:` line (exit 0).

## Check and fix the review

Before the person reviews the plan, run the same review yourself and fix what it finds. Do not push first.

1. `openspec validate <change> --strict` (or `--all --strict`) and `python3 <skill dir>/scripts/validate_plan.py`, both clean.
2. `l4 yolo review <id> --worktree`. It reads the working tree, writes nothing and charges the plan nothing. Only changed
   units are judged again, so repeat it after each fix. Exit 0 means every subject is READY.
3. `l4 yolo findings <id> --worktree --json` (the dry run records nothing, so without `--worktree` it is empty). For each subject read `findings` (`id`, `criterion`, `severity`, `text`, `resolve`)
   and `persistent`. A persistent criterion means the same concern is coming back: fix its cause in the spec, not its
   wording.
4. Fix the specs or the plan as each `Resolve:` line says, then go to step 2. Write and fix specs by `references/spec.md`.
5. When every subject is READY, commit and push, then run `l4 yolo review <id> --worktree --record` (it refuses while
   HEAD is not `origin/<base>`; anything not already on the ledger is judged again, and that verdict is the one
   recorded: one more judging pass, cheap but not free). CI then does not judge again. `--fresh
   <subject>` is a dry-run tool only; `--record --fresh` is refused when the ledger holds that material. Hand off as below.

`--worktree` needs no sandbox for a `claude-code` or `opencode` judge: outside CI it runs unsandboxed and prints the
line that says so (the judge has no tools and runs in an empty folder). In CI it fails closed. Minor findings show
with `findings --all`. After `--worktree`, `findings <id> --worktree` (add `--json`) shows its results, and
`review <id> --worktree --json` prints the same document.

A person may need an `l4 yolo accept` when the judge keeps finding more after real fixes. It is not your tool:
- Never run it unless `yolo.review.accept_by_agents` is true in `.l4/config.yaml` on the base branch **and** the
  subject was judged not READY on two versions of its text. Then give a `--reason` that tells the implementer what to do.
- Never for a BLOCKED subject, a blocking finding, or a `material_cut` of the unit's own folder: those are fixed.
- Otherwise stop and ask the person. Print the exact command for them:
  `l4 yolo accept <id> <subject> --reason "<what the implementer should do>"`.

When no judge can run, first ask CI: `l4 yolo review <id>`. Never run `--force` (`l4 yolo accept <id> --all --force`),
not even when `accept_by_agents` is true: it accepts the plan with no model review and is a person's decision. Print
the command for the person:
`l4 yolo accept <id> --all --force --reason "<what the implementer should know>"`.

`l4 yolo waive <id> <F-id> --reason "..."` follows the same rule. It is for a plan that waits with
`accepted_finding_open` on a finding the judge found not addressed. Never waive a finding the judge did not answer:
run `l4 retry` for it. Never waive a finding whose fix the code needs: give it as feedback. Waive only after you have
read the code for that finding, and only when `accept_by_agents` allows it. Otherwise print the command for the person.

Stop and ask the person when: two rounds repeat the same criterion on the same unit; the fix needs a spec cut that
drops required behaviour; `--worktree` exits 3 (a judge with a shell and no sandbox: ask for a `claude-code` or
`opencode` judge profile). Do not shorten a spec only to fit a budget. Move background to `docs/`, or ask for a larger
`yolo.review` budget.

When a finding needs a product decision, ask the person. Working unattended, decide, and record the decision and its
reason in the change's `design.md` (create one) under `## Decisions`, so a person can review it.

## Hand off

Commit and push the plan file. When the specs it lists are new (not on the target yet), commit them in the SAME commit,
or push the plan file first: a spec that lands without a plan that holds it runs at once. Only an edit of an existing
unit's spec stays out of the plan commit. One evidence line per dependency goes in the commit message, naming the spec
file that shows it:

```sh
git add .l4/plans/<id>.json <the new spec folders, if any>
git commit -m "plan pricing: add-pricing, use-pricing, report-export

openspec:use-pricing depends on openspec:add-pricing: use-pricing's tasks call add-pricing's parse_price() (add-pricing/specs/pricing/spec.md)
exclude kiro:legacy-import: its PR is open and owned by another team"
git push
l4 yolo check <id>
```

After the commit you may run `l4 yolo go <id> --reason "…" --json --wait 9m` instead of `git push` and `l4 yolo check <id>`:
it pushes only the plan file and the folders of its units, checks, asks CI for the review and stops at the first step
a person must take (`next_command`, exit 27). It never activates for you.

Then stop. A person reads the review (`l4 yolo findings <id>`) and activates (`l4 yolo activate <id> --reason "…"`).

## Update

A new spec means `l4 yolo draft <id> --update`. It appends the new specs to the batch `unplanned` (or to `exclude`),
keeps everything else, and reports a spec that is gone as `gone: <id>` without removing it. Then move the new unit
where it belongs, add its dependencies on evidence, and validate, commit and push as above.

An **active plan stops (`inputs_changed`) when its file changes**. It needs a new review and a new activation by a
person; its usage (cost, runs, attempts) is kept. Say so in your hand-off. Keep a unit that the plan has integrated in
the file: it counts as done. A spec with no order to the active plan can go into a new plan instead, which leaves the
active file alone. Only one plan is active on a target, so a person activates the new one after the first completes.

## Never

- Activate, resume or cancel a plan for a person. Those are their decisions. Raising a plan's limit with
  `l4 yolo resume --extend-…` is one too, unless `yolo.extend_by_agents` is true in `.l4/config.yaml` on the base branch:
  otherwise print the command for the person.
- Write `refs/l4/plans/*`. It is the harness's ledger.
- Set `merge: auto` unless the person asked and `forge.merge_policy` is `auto`.
- Turn the delegate on (`delegate.enabled: true`, `roles.delegate`) for a plan. Enabling it is a configuration change on
  the base branch that a person approves; it lets a model answer the plan's questions, so say in your hand-off that the
  plan waits on a person's answer where it is off. A free-tier model in `roles.delegate` answers technical and harness
  questions only, so keep a strong profile first for a plan that raises verdict or product questions.
- Weaken or delete a requirement or scenario to silence a check or fit a budget. Fix a spec when the validator or the
  review finds a real gap in it; change the plan for a plan problem.
- Add a dependency you cannot support with a line of a spec.
