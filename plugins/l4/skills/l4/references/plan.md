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

Before the push, run the script from the repository root and fix every problem it prints. Never silence one: not by
deleting a dependency you cannot justify, nor by excluding a spec only to make the check pass.

```sh
python3 <skill dir>/scripts/validate_plan.py
```

`l4 yolo check <id>` reads the plan file and the units from the target, so it cannot run before the push (it exits 2 for
a plan file that is not on the target). Run it after the push, as the last step of the hand-off; CI runs the same
admission and the review. Fix its findings the same way.

- The script needs only Python. It reads every `.l4/plans/*.json`, finds the units like the harness does, and checks
  the schema, the graph (cycles, unknown units, duplicates) and the coverage across all plan files (`uncovered`,
  `covered_twice`). On success it prints the dispatch order and the waves. Exit 0 is valid, 1 lists problems. A planned
  unit whose change is archived prints `finished: <id>`: remove it, because `l4 yolo check` refuses it as `unknown_unit`, unless this plan already
  merged or integrated it.
- `l4 yolo check` also checks what the script cannot: open questions, intake, finished units, profiles, the target
  against `forge.base_branch`, and the merge policy. Exit 0, or 2 with findings. It changes nothing.

## Check and fix the review

Before the person reviews the plan, run the same review yourself and fix what it finds. Do not push first.

1. `python3 <skill dir>/scripts/validate_plan.py` clean.
2. `l4 yolo review <id> --worktree`. It reads the working tree, writes nothing and charges the plan nothing. Only changed
   units are judged again, so repeat it after each fix. Exit 0 means every subject is READY.
3. `l4 yolo findings <id> --json`. For each subject read `findings` (`id`, `criterion`, `severity`, `text`, `resolve`)
   and `persistent`. A persistent criterion means the same concern is coming back: fix its cause in the spec, not its
   wording.
4. Fix the specs or the plan as each `Resolve:` line says, then go to step 2. Write and fix specs by `references/spec.md`.
5. When every subject is READY, commit, run `l4 yolo review <id> --worktree --record`, then push. CI then does not
   judge again. Hand off as below.

A person may need an `l4 yolo accept` when the judge keeps finding more after real fixes. It is not your tool:
- Never run it unless `yolo.review.accept_by_agents` is true in `.l4/config.yaml` on the base branch **and** the
  subject was judged not READY on two versions of its text. Then give a `--reason` that tells the implementer what to do.
- Never for a BLOCKED subject, a blocking finding, or a `material_cut` of the unit's own folder: those are fixed.
- Otherwise stop and ask the person. Print the exact command for them:
  `l4 yolo accept <id> <subject> --reason "<what the implementer should do>"`.

Stop and ask the person when: a finding asks for a product decision; two rounds repeat the same criterion on the same
unit; the fix needs a spec cut that drops required behaviour; `--worktree` exits 3 (no sandbox, codex judge). Do not
shorten a spec only to fit a budget. Move background to `docs/`, or ask for a larger `yolo.review` budget.

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

- Activate, resume or cancel a plan for a person. Those are their decisions.
- Write `refs/l4/plans/*`. It is the harness's ledger.
- Set `merge: auto` unless the person asked and `forge.merge_policy` is `auto`.
- Edit a unit's spec to make a plan valid. Change the plan, or ask.
- Add a dependency you cannot support with a line of a spec.
