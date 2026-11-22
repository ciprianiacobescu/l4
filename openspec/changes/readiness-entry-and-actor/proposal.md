## Why

Four lessons of consumer plan runs on 0.4.59.

1. **The judge reads a unit's prerequisites as the previous unit's.** On a plan of ten units, one free judge raised the
   same false BLOCKING batch finding in two reviews in a row: "two units list themselves in `depends_on`". No unit does.
   One round named a unit that no list contains. A second judge found nothing in the same material. The plan entry is
   shown as `json.dumps(..., sort_keys=True)` (`src/l4/yolo/readiness.py:265`), so in a batch entry each unit prints
   `"acceptance_profile"`, then `"depends_on": [...]`, then `"id"`. A reader that reads top to bottom meets a unit's
   list before its id, right after the previous unit's id.
2. **A consumer cut `roles.judges` to one judge for a review, three times.** It believed that the readiness review has
   no fallback after a judge error. That was true before 0.4.59. Since 0.4.59 the review walks its chain, and
   `roles.plan_judges` is a chain for the review only (L4-YOLO-095). Each time a person had to put the unit judges back
   before the activation. Once a unit outside the plan went `waiting_capacity`: its single judge failed its hello.
   `l4 doctor` says nothing about a chain of one judge.
3. **An older `l4` wrote for a repository pinned to a newer harness.** Twice a person command (`l4 retry`, on the
   owner's machine) ran with CLI 0.4.54 against a repository pinned to 0.4.59. The unit ledger's `run.started`
   recorded `harness_version: 0.4.54`. Nothing warned.
4. **An activation did not say that an agent made it.** `plan.activated` records `by: <git user.email>`. That an agent
   session acting for the owner ran the command was visible only in the free-text reason. `l4 yolo waive`,
   `l4 yolo accept` and `l4 yolo resume --extend-…` already record the actor kind (`l4.actor.actor`).

What the 0.4.59 source does (read for this change; design.md has the lines):

- `_entry` sorts the keys of a plan entry. The order is the same for a unit subject, a batch and a part of a batch.
- The readiness `PROMPT_VERSION` is 4. A review of another version is stale for the CI step, `l4 yolo status` and the
  activation (L4-YOLO-004). Only plans before the activation, and plans stopped with `inputs_changed`, are reviewed by
  CI.
- CFG-002 fails an empty `roles.judges`. No check looks at a chain of one. `l4 init` writes one judge.
- `l4.ci.pin_guard` compares the running harness with the workflow's pin in a GitHub CI job only. A person's command
  compares nothing.
- `l4 yolo activate` has no actor check. `l4 yolo go` stops an agent before the activation (L4-YOLO-086), and the skill
  says activation is a person's step (L4-SKL-004).

## What Changes

- **The plan entry is shown `id` first** (L4-YOLO-101). Every object of a plan entry shows `id`, then `depends_on`, then
  the other keys in sorted order. This holds for a unit subject, a batch and each part of a batch. The readiness prompt
  version becomes 5, so a review made under 0.4.59 is stale before the activation and is made again. An active plan is
  not stopped, not reviewed again and shows no prompt change. A plan stopped with `unit_rejected`, which CI never
  reviews, is told to review with `--local`.
- **Plan events say who acted and with what harness** (L4-YOLO-102). `plan.activated`, `plan.resumed` and
  `plan.cancelled` record `actor` and `marker` as `l4 yolo waive` does, and `harness_version`. `l4 yolo status` shows
  `activated by <by> (person)`, `(agent: <marker>)` or `(agent: no terminal)`, and the latest person's resume. The plan
  report shows who activated and who cancelled. An older event shows no kind. No new refusal.
- **Unit commands say who acted** (L4-OPS-025). `unit.retried`, `unit.restarted` and `unit.resumed` that the commands
  `l4 retry`, `l4 restart` and `l4 resume` record carry `actor` and `marker`. The sweep's labels and a spec-edit push
  are unchanged.
- **Doctor CFG-013** (L4-YOLO-103) warns when `roles.judges` has one profile: unit verification then has no fallback
  judge. When `roles.plan_judges` is empty it adds that a judge for plan reviews only belongs there. It also warns when
  `roles.plan_judges` has one profile. A warning never changes doctor's exit code.
- **An older `l4` does not write for a newer pin** (L4-OPS-026). Outside a CI job, a person command that records an
  event or pushes a commit compares `l4.__version__` with the version the repository pins: `harness.version` of
  `.l4/config.yaml` (vendored, fetched), or the `# vX.Y.Z` comment of the setup action's `uses:` line (action). It reads
  them at `origin/<base>` as last fetched, else in the working tree. When the CLI is older, the command exits 2 before it
  reads or writes anything else, unless `--allow-older-cli` is given (then a warning). A stop (`l4 yolo cancel`, a
  `--withdraw`) and a command that writes only a local file warn and run. A newer CLI only warns on stderr. An unknown
  pin, an equal CLI, and every CI job change nothing.
- **Documentation** (L4-YOLO-104): the runbook, the skill and the CHANGELOG.

Non-goals:

- a refusal of `l4 yolo activate` for an agent (an open question, design D6);
- a notice from the pinned harness in CI about events an older CLI wrote (an open question, design D5);
- a check in a CLI older than 0.4.60: the guard ships in 0.4.60 and protects from the next pin move on;
- the order of anything but the plan entry; the plan file on disk;
- showing the unit events' actor in `l4 status`.

## Capabilities

### New Capabilities

- `readiness-entry-and-actor`: L4-YOLO-101 (the entry's key order and prompt version 5), L4-YOLO-102 (the actor of plan
  events), L4-YOLO-103 (doctor CFG-013), L4-YOLO-104 (documentation), L4-OPS-025 (the actor of unit commands),
  L4-OPS-026 (an older CLI).

### Modified Capabilities

These are amended in `docs/SPEC.md`:

- L4-YOLO-025: the readiness prompt version is 5.
- L4-YOLO-098: an unsplit subject keeps its prompt and key "as L4-YOLO-025 and L4-YOLO-101 make them", not "version 4".
- SCN-YOLO-56 and SCN-YOLO-276: the prompt version and the prompt of reference.
- The CLI paragraph after the command table: every command accepts `--allow-older-cli`.
- §15: the doctor table gets CFG-013.

## Impact

- Code:
  - `src/l4/yolo/readiness.py`: `_entry` and `PROMPT_VERSION`.
  - `src/l4/yolo/commands.py`: the actor and `harness_version` on `plan.activated`, `plan.resumed`, `plan.cancelled`;
    the status document and `_render`.
  - `src/l4/yolo/state.py` and `src/l4/yolo/model.py`: `activated_actor`, `activated_marker`.
  - `src/l4/yolo/report.py`: two lines.
  - `src/l4/state/retry.py`, `src/l4/state/restart.py`, `src/l4/state/resume.py`, `src/l4/orchestrator.py`: the actor
    of the command.
  - `src/l4/doctor/checks_config.py`: CFG-013.
  - `src/l4/cli_pin.py` (new): the pin read and the guard. `src/l4/cli.py`: the common option and the call.
    `src/l4/ci/relay.py`: `harness.version` in `LENIENT_KEYS`, and a text form of the lenient read.
- Tests: the files that pin prompt version 4 or the 0.4.58 material keys (tasks.md lists them).
- Docs: `docs/SPEC.md` (L4-YOLO-101..104, L4-OPS-025, L4-OPS-026, SCN-YOLO-283..295 and 307, SCN-OPS-54..62, row 135, CFG-013,
  the amendments), `docs/runbook.md`, `plugins/l4/skills/l4/references/plan.md`, `references/adopt.md`, `CHANGELOG.md`.
- Ledger: optional fields on five events. An older harness ignores them; an older ledger folds as before.
- Configuration: no new key.
- Upgrade cost: every plan reviewed under 0.4.59 and not yet activated is judged again once, in full.
