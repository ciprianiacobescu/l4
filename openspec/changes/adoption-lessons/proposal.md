## Why

On 2026-10-15, L4 v0.4.0 was adopted on its first real consumer. That was a public Python monorepo on GitHub, with
an integration branch `staging`, the action copy form, an OpenCode DeepSeek implementer and a Claude judge. The
adoption worked, but only through hand work and workarounds that every adopter would repeat:

- **Setup.**
  - The default branch had to be added to the environment `l4` by hand.
  - A push from a laptop ignored the keychain.
  - A GitHub push error spoke GitLab's token rules.
- **Existing specs.** The 26 existing changes needed a hold-only "backlog" plan. It is reported as `refused` on every
  status. It fails open for every new spec, and it would cost a judge review if admission ever accepted it.
- **Feedback arrives late.**
  - OpenSpec intake refusals showed 1 finding of 8, cut at 300 characters, with no way out.
  - The readiness review's size budgets showed up only as NEEDS_REVISION after a CI round.
  - One plan took eight review rounds, for kinds of findings that a short checklist would have prevented.
  - A single OpenSpec unit outside any plan is strictly validated only after its implementation is paid for.
- **Gaps nobody saw.**
  - L4's PRs never run the repository's own CI. Its jobs that the gates do not mirror (a Postgres conformance job,
    helm and docker checks) are never checked under `merge: auto`.
  - System One was off, so every implementer question would go to a person.
  - A System One key in the config never reaches the GitHub job.
  - After an upgrade, the cron on the default branch would run the old harness pin.
  - A repository file named `l4_trace.py` can replace the harness's evidence plugin under `python -m pytest`.

`design.md` gives each lesson's current state with file and line, the fix, its cost, and the lessons rejected with
evidence.

## What Changes

- **Gates.** A gate does not start when the worktree root holds a module named like an evidence plugin. No change to
  the gate's import path: `PYTHONSAFEPATH` and the console-script form were both rejected by a probe.
- **GitHub setup and pushes.**
  - `l4 setup github` covers the default branch and checks the workflow file there.
  - A laptop push keeps the person's git credentials.
  - A refused push names the forge's own token rules.
  - CI reports a harness pin that differs from the base's.
- **Intake.**
  - A single OpenSpec unit is validated strictly before any agent runs, including the Purpose rule of L4-OSP-007.
  - Intake findings are shown in full, with a hint for a delta on a missing capability.
- **Before the push.** `validate_plan.py` checks deltas against the baseline and the review's size budgets, in step
  with the harness. `l4 yolo check` prints the budget overruns.
- **Holding units.**
  - `yolo.hold` (unit ids or patterns) holds units that no plan lists. It costs nothing and replaces the backlog plan.
    `["*"]` makes units opt-in by plan.
  - `l4 init --hold-existing` writes it.
  - A plan that holds units says so in `l4 status`.
- **Doctor.** `l4 doctor --adoption` names CI jobs the gates do not mirror and the effect of the workflow token. A
  doctor row says when System One is off, what that costs, and what to add.
- **System One.**
  - `l4 init` enables Laya by default (`--s1 jev` or `--s1 none` otherwise).
  - Runner provisioning installs Laya wherever a profile uses it. On GitHub it is cached apart from the CLIs.
  - The workflow names System One keys, for example the consumer's Jev key.
- **Skill and docs.** A short spec-writing reference in the skill, and the adoption docs corrected in 14 places.

Not in this change:
- a merge precondition on the repository's CI (the self-hosting proposal's phase 3);
- the self-healing dispatch on pin skew (L4-SELF-010);
- deferring intake until a dependency's archive;
- keyless Jev;
- anything about overriding or accepting review findings (the review-resolution change).

## Capabilities

### New Capabilities

- `adoption-lessons`: the gate's plugin-shadow guard, the GitHub setup of an integration base, push credentials and
  messages, pin skew, CI-mirror and System One doctor rows, strict OpenSpec intake for single units with full findings,
  the plan validator's baseline and budget checks, `yolo.hold`, `l4 init --hold-existing`, Laya as the default System
  One, installed and cached on runners, System One keys in the workflow, and the spec-writing reference. The
  requirements are split into five capability files: forge, intake, plans, system-one and guidance.

### Modified Capabilities

None as an OpenSpec delta: `openspec/specs/` holds no baseline for these areas. `docs/SPEC.md` gains L4-ADO-001..019
and SCN-ADO-01..54, and amends L4-OSP-007, L4-GHP-011 and §3.2 (task 9.1).

## Impact

- **Code:**
  - `src/l4/gates/runner.py`, `src/l4/gates/trace.py`;
  - `src/l4/forge/gitlab.py`, `src/l4/forge/pushfail.py` and their callers;
  - `src/l4/setup/github.py`;
  - `src/l4/doctor/checks_config.py`, `checks_ci.py`, `checks_s1.py`;
  - `src/l4/ci/github.py`, a new `src/l4/ci/repo_jobs.py`;
  - `src/l4/specs/openspec.py`, `src/l4/orchestrator.py`;
  - `src/l4/yolo/plans.py`, `cycle.py`, `readiness.py`, `commands.py`, `src/l4/planner.py`, `src/l4/sim/dryrun.py`;
  - `src/l4/config/schema.py`, `src/l4/init/init.py`, `src/l4/init/upgrade.py`, `src/l4/cli.py`;
  - `src/l4/provision/catalog.py`;
  - `.github/actions/l4/action.yml` and its copy.
- **Scripts:** `scripts/validate_plan.py` and its skill copy, `scripts/runner/prereqs.sh`.
- **Skill:** `references/spec.md` (new), `SKILL.md`, `adopt.md`, `plan.md`.
- **Docs:** `docs/SPEC.md`, `README.md`, `docs/quickstart.md`, `docs/runbook.md`, `docs/yolo-mode.md`,
  `docs/free-resources.md`, `docs/live/adoption-lessons/`.
- **Config:** a new optional key, `yolo.hold`. The schema is strict, so the order is: release, pin move, config edit.
- **Live:** the consumer or the public dummy, for the setup rows, the hold, pin skew and the Jev key.
