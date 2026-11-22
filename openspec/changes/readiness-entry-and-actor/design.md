## Context

Read at 0.4.59 (`62188257`):

- `src/l4/yolo/readiness.py:265-266` `_entry(model)` is `json.dumps(model.model_dump(by_alias=True), indent=2,
  sort_keys=True)`. It is the `ENTRY` data block of a unit subject (`:368`), of a batch (`:405`) and of a part of a batch
  (`:486`). `PlanUnit` declares `id, depends_on, acceptance_profile` and `PlanBatch` declares `id, depends_on,
  acceptance_profile, units` (`src/l4/yolo/model.py:37-47`). With sorted keys a batch entry prints, per unit,
  `acceptance_profile`, `depends_on`, `id` (checked with a probe on a three-unit batch: the list `["openspec:a"]` of
  unit `b` comes right after `"id": "openspec:a"` and before `"id": "openspec:b"`).
- `PROMPT_VERSION = 4` (`readiness.py:77`). `material_key` hashes the version, a fingerprint of the templates and the
  schema, the kind and the subject's `key_text` (`:574-580`). `key_text` holds the `ENTRY` block, so a new key order
  changes every material key whether or not the version moves.
- The version decides currency in three places: the CI step (`cycle.py:1144-1148` `_reviewed_current`), the status and
  the activation (`commands.py:508` in `_review_view`, with `prompt_matters`), and the stale lines
  (`staleness.py:207-211`, `review prompt <old> at the review, <new> in this harness: every subject is judged again`).
  It filters what is reused: `findings.prior_entries` (`findings.py:113`), `history` (`:132`), `failed_before`,
  `kept_keys`, `latest_incomplete` (`:158-195`), `batches_in_parts` (`:512-516`) and the dry-run cache
  (`review_worktree.py:85`, `:126`). `rounds_not_ready` counts over every version (`findings.py:319-342`).
- The CI step reviews a plan only while `_reviewable` (`cycle.py:921-924`): before the activation, or stopped with
  `inputs_changed`. An active plan is checked against the plan digest and the unit digests frozen at the activation
  (`cycle.py:1243-1258`, `_inputs_changed` `:1187-1201`). Neither reads the prompt version or a material key.
  `l4 yolo status` passes `prompt_matters=False` for an active plan (`commands.py:1784-1788`).
- An acceptance holds while the latest entry has the same `material` and `findings_sha` (`accept.py:175-188`). A force
  acceptance holds on the plan digest and the unit digests (`accept.py:320-337`).
- `l4.actor.actor(environ, stdin_tty)` (`src/l4/actor.py:9-16`): `("agent", <marker>)` when one of `AGENT_MARKERS` is
  set, else `("person", None)` with a terminal on stdin, else `("agent", None)`.
- `run_activate` (`commands.py:1254-1379`) records `plan.activated{..., by, reason, ...}` (`:1362-1366`) and asks no
  actor. `run_resume` records `actor`, `marker`, `agent_key` only with an `--extend-…` (`:1576-1579`). `run_cancel`
  records `{by, reason}` (`:1398`). `run_waive` records `actor`, `marker` (`:2786-2795`). The fold keeps
  `activated_by` (`state.py:152`); `l4 yolo status` prints `activated by <by>` (`commands.py:2183-2184`). The report
  names nobody (`report.py:123-141`).
- `l4 yolo go` stops an agent at the activation, "activation is a person's decision" (`go.py:328-344`, L4-YOLO-086).
- `l4 retry`, `l4 resume` and `l4 restart` pass `by=None` from the command. The sweep passes `by="member"`
  (`ci/sweeper.py:756`, `:765`), a spec-edit push `by="push"` (`orchestrator.py:797`, `:807`). The orchestrator writes
  `by` and `signal` when set (`orchestrator.py:707`, `restart.py:198`).
- Doctor: CFG-002 fails an empty `roles.judges` (`doctor/checks_config.py:32-53`). Nothing checks a chain of one.
  `l4 init` writes `judges: ["claude-code"]` (`init/init.py:68`). A `warn` check never changes the exit code
  (`doctor/registry.py:166-168`). CFG-013 is not used anywhere.
- The pin. Vendored: `harness.version` and `harness.commit` of `.l4/config.yaml` (`init/upgrade.py:1-6`). Fetched:
  `harness.commit`, and `harness.version` only when `--harness-ref` is a `vX.Y.Z` tag (`upgrade.py:398-437`). Action:
  no version or commit in the config; the pin is `uses: <owner>/<repo>/.github/actions/l4@<sha> # <ref>`
  (`ci/github.py:317-321`). `init/action.py:93-109` `read_pin` parses YAML, which drops the comment. The vendored and
  fetched shims (`.l4/bin/l4`) run the pinned harness.
- `l4.ci.pin_guard` compares the running commit with the workflow pin in a GitHub job only (`pin_guard.py:56-71`).
  `l4.ci.relay.lenient_settings` reads a few config keys with no schema (`relay.py:42-100`). `in_ci_job`
  (`ci/detect.py:7-10`). `version_at_least` (`versions.py:24-34`) is None when a side does not parse.
- The CLI builds every command in `cli.py:540-563`; `call()` runs `dispatch` inside `run_guarded` or `with_outcome`, so an
  `L4Exit` raised there is exit 2 with its text. The MCP server runs every tool as an `l4` subprocess
  (`mcp/tools.py:88-110`).

## Goals / Non-Goals

**Goals:** a judge reads each unit's id before its prerequisites; the upgrade is explicit and costs one review per
plan before activation; an active plan is untouched; the ledger and the status say whether a person or an agent took a
person-level plan action; doctor says what a single judge costs; an older CLI does not write for a newer pin by
accident.

**Non-Goals:** an actor policy for `l4 yolo activate` (D6); a CI-side notice about older writers (D5); a check of a
newer CLI (D5); a guard in CLIs older than this one; ordering of the plan file itself.

## Decisions

### D1. The key order of a plan entry

`_entry(model)` renders `_ordered(model.model_dump(by_alias=True))` with `json.dumps(..., indent=2)` and no
`sort_keys`. `_ordered(value)`: a mapping becomes a new mapping whose keys are `id` (when present), then `depends_on`
(when present), then every other key in sorted order, each value ordered the same way; a list keeps its order with each
item ordered; any other value is itself. The order is explicit, not the models' declared order, so a new field cannot
move `id` or `depends_on`. A batch entry then reads:

```json
{
  "id": "b1",
  "depends_on": [],
  "acceptance_profile": "none",
  "units": [
    {
      "id": "openspec:a",
      "depends_on": [],
      "acceptance_profile": "all"
    },
    {
      "id": "openspec:b",
      "depends_on": [
        "openspec:a"
      ],
      "acceptance_profile": "all"
    }
  ]
}
```

Nothing else of the prompt changes: the templates, the notes, the data blocks and the order of the sections stay.

Rejected: a sentence in the prompt that says the list belongs to the id above it (the reader that misread JSON will
misread the note too); one line per unit (`- openspec:b depends on openspec:a`): clearer, but the entry would no longer
be the plan's JSON, and the judge's findings quote it.

### D2. Prompt version 5, and what the upgrade does

`PROMPT_VERSION = 5`, with the comment line `5: the plan entry shows id, then depends_on, then the other keys (0.4.60)`.
The material keys change with the entry anyway (D1). The version bump is what makes a review of 0.4.59 stale before
the activation, so the plan is reviewed with the fixed material. Without the bump a review of 0.4.59 would stay current,
and the next change of any one unit would judge every unit again at once, under keys nobody expects to move.

What a consumer sees after it moves its pin from 0.4.59 (checked with a probe on a ledger whose review has an older
prompt version, as SCN-YOLO-181 does, and by reading the lines above):

- **A plan reviewed and not activated** (`new`, `admitted`, `reviewed`, `refused`):
  - `l4 yolo status` shows `review: stale (the review prompt changed)` and the line `review prompt 4 at the review, 5 in
    this harness: every subject is judged again`.
  - `l4 yolo activate` is refused with that line and `Fix: l4 yolo review <plan>`.
  - The next CI run reviews it (one plan per run). Every subject is judged again: no entry of version 4 is reused, the
    cost is charged to `plan:review`. `l4 yolo go` asks CI for that review.
  - A `plan.accepted` made on the 0.4.59 review no longer holds (its material differs). `l4 yolo status` says why
    (`other material: ... the review prompt changed`). The rounds of `yolo.review.accept_after_rounds` are kept, because
    they count unit digests over every version, so the person can accept again at once.
  - A force acceptance still holds (it is bound to digests), so a force-accepted plan activates without a new review.
  - A `plan.review_incomplete` of version 4 is ignored (no kept answers, no `failed_before`, no `incomplete` line), and
    so are the dry-run cache lines of version 4.
  - `l4 yolo findings` shows the history of version 5 only, as for every earlier bump.
- **A plan stopped with `inputs_changed`**: as above; CI reviews it.
- **A plan stopped with `unit_rejected`**: status and activation treat the review as stale (`commands.py:1784-1786`,
  and `_review_view`'s default in `run_activate`), but CI never reviews such a plan (`_reviewable`). A spec fix leads to
  `inputs_changed` and a CI review, as today. A configuration fix with an unchanged spec is re-activated with
  `l4 yolo activate` alone (`cycle.py:1325-1331`); after the upgrade that refusal said `Fix: l4 yolo review <plan>`,
  and CI never makes that review (probed: the activation exits 2 with the version line; `l4 yolo review p1` exits 0
  with `The configuration: nothing to review` and asks CI for nothing (`commands.py:1072-1080`); the status's `Next:`
  says to fix the cause and activate (`commands.py:1626-1632`)). So for a plan stopped with `unit_rejected` whose review
  is stale, the activation's fix, that `l4 yolo review` message and the status's `Next:` line name
  `l4 yolo review <plan> --local` (or `--worktree --record`), which judge here and record (SCN-YOLO-307). The same
  dead end exists today for a plan file changed during such a stop, and the new fix text covers it too.
- **An active or waiting plan**: no stop, no review, no new event. `_reviewable` is false, and the checks of the active
  plan read digests only. `l4 yolo status` shows the review as it was made (`prompt_matters=False`), with no prompt
  change. The frozen acceptances and the running units are unchanged. If the plan is later stopped with
  `inputs_changed`, its new review judges every subject at version 5.
- **A completed or cancelled plan**: nothing.
- **A person whose `l4` is 0.4.60 while the repository still pins 0.4.59**: that CLI calls every 0.4.59 review stale,
  while the pinned CI calls it current and judges nothing; a `--local` review by the newer CLI records version 5, which
  the pinned CI then calls stale and judges again. The way out is the pinned `l4` (`.l4/bin/l4`, or the pinned
  install). L4-OPS-026 checks only an older CLI; whether a newer one should warn is an open question (D5).

How it fails safe: a stale review can only stop an activation or cost a review; it can never let a plan activate
on material no judge saw.

### D3. The actor of a plan event

`run_activate`, `run_resume` (every resume, not only an extension) and `run_cancel` compute
`who = accepting.actor(ctx.app.environ, _stdin_tty())` once, as `run_waive` does, and record `actor=who[0]`,
`marker=who[1]` and `harness_version=l4.__version__`. On `plan.resumed` with an extension `agent_key` stays as it is.
The harness's own `plan.resumed{by: harness}` (`cycle.py`) is unchanged.

The fold: `PlanState.activated_actor: str | None` and `activated_marker: str | None`, set by `plan.activated` from
`data.get("actor")` and `data.get("marker")` (None when absent), beside `activated_by`.

Shown:

- `l4 yolo status`: `activated by <by> (<kind>)`, where `<kind>` is `person`, `agent: <marker>`, or `agent: no terminal`
  (an agent kind with no marker: the caller had no terminal on stdin). An event without `actor` prints
  `activated by <by>` as today, never `person`. `--json` adds `activated_actor` and `activated_marker`.
- `l4 yolo status` also prints `  resumed by <by> (<kind>)` for the latest `plan.resumed` after the latest
  `plan.activated` whose `by` is not `harness`, when it has `actor`; `--json` has `resumed: {by, actor, marker, at}`.
- The plan report: `- Activated by: <by> (<kind>)` after `- Merge:` when the plan was activated, and
  `- Cancelled by: <by> (<kind>)` when it is cancelled (the same rule for an event without `actor`).

No refusal is added. How it fails safe: the fields are records; a missing field shows less, never "person".

### D4. The actor of a unit command

`run_retry`, `run_resume` (unit) and `run_restart` compute `actor(app.environ, sys.stdin.isatty())` and pass it down:
`retry_unit(..., actor=...)`, `resume_unit(..., actor=...)`, `restart_unit(..., actor=...)` to the orchestrator's
`resume(..., actor=...)` and the restart writer. The event gets `actor` and `marker` beside `reason`, `by` and `signal`.
The sweep (labels) and the spec-edit path pass nothing, so their events are unchanged. `run.started` already records
`harness_version`. The fold ignores the new fields. `l4 status` shows nothing new (a non-goal).

### D5. The older CLI

One module, `src/l4/cli_pin.py`:

- `pinned_version(repo, environ, config_path) -> Pin | None`, `Pin(version, source)`:
  1. The base branch: `forge.base_branch` of the lenient read of the working tree's config (`lenient_settings`), else
     `main`.
  2. The files are read at `refs/remotes/origin/<base>` when it resolves (`git show <ref>:<path>`, at most 1 MB each),
     else from the working tree. No fetch and no network: every l4 command that reads the base fetches it, so the
     ref is as fresh as the last command or `git pull`. `source` names where: `harness.version at origin/main`, or
     `the uses: line of .github/workflows/l4.yml in the working tree`.
  3. The delivery as `lenient_settings` derives it (`harness.delivery`, else `fetched` for a `harness.repository`, else
     `action` when the workflow uses the setup action, else `vendored`).
  4. `vendored` or `fetched`: `harness.version`, when it is `X.Y.Z` or `vX.Y.Z` (`relay.LENIENT_KEYS` gains
     `harness.version`; a text form `lenient_settings_text(text, workflow_text)` serves the ref read).
  5. `action`: the raw workflow text, the first line that matches
     `uses:\s*[\w.-]+/[\w.-]+/\.github/actions/l4@[0-9a-f]{40}\s+#\s*v?(\d+\.\d+\.\d+)\b`. A copy of the action
     (`./.github/actions/l4`, pinned by its `commit` input) and a line without such a comment give no version: a sha
     can say "differs", never "older".
  6. Anything else: None.
- `check(name, options, app) -> None`, called in `cli.py`'s `call()` before `dispatch`, so a refusal is exit 2 through
  the existing handlers and nothing of the command runs:
  - in a CI job (`in_ci_job`): return;
  - `kind = WRITES.get(name)` with the option predicate below; None: return;
  - `pin = pinned_version(...)`; None, or `version_at_least(__version__, pin.version)` not False: return;
  - `refuse` without `--allow-older-cli`: raise `L4Exit(USAGE_ERROR, text)`;
  - otherwise print the warning to stderr (so `--json` keeps one document on stdout) and return.

The commands:

| kind | commands |
|---|---|
| `refuse` | `run` (not `--dry-run`), `verify`, `archive`, `resume`, `retry`, `restart`, `plan --sweep`, `questions accept` and `questions answer` (not `--no-push`), `yolo review --local`, `yolo review --worktree --record`, `yolo accept` (not `--withdraw`), `yolo waive` (not `--withdraw`), `yolo activate`, `yolo resume`, `yolo go` |
| `warn` | `yolo cancel`, the `--withdraw` forms of `yolo accept` and `yolo waive`, `questions accept|answer --no-push`, `feedback add`, `feedback submit`, `feedback withdraw`, `yolo draft`, `lessons promote` |
| none | every other command: the read-only ones, `upgrade`, `init`, `doctor`, `setup`, `ci …`, `mcp …`, `skills …`, `probe`, `kg …`, `s1`, `simulate`, `eval`, `unlock` |

A stop or a withdrawal only makes things stricter, and a person must always be able to stop a plan, so it warns and
runs. A command that writes only a local file warns: CI's pinned harness reads that file.

Texts (`<cmd>` is the command name as typed, `<v>` the CLI's version, `<p>` the pin, `<source>` as above):

- refusal: `<cmd>: this l4 is <v>, older than the harness this repository pins (<p>, <source>): it would apply the rules
  of <v> to the repository's units and plans` and `Fix: <install>, or pass --allow-older-cli to run this l4 anyway`;
- warning: `warning: this l4 is <v>, older than the harness this repository pins (<p>, <source>); <install>`;
- `<install>`: `use .l4/bin/l4 (it runs the pinned harness)` when `.l4/bin/l4` exists in the working tree; else, for an
  action pin, `install it: uv tool install --force git+https://github.com/<owner>/<repo>@v<p>`; else
  `install l4 v<p>`.

`--allow-older-cli` is a common option of every command (`cli._common`, `_COMMON_KEYS`), so the MCP server, `go` and a
script can pass it the same way. It is read only by `check`.

**Warn or refuse.** Recommended: refuse (above). The pin is the repository's contract: CI runs it, and a person command
applies the same rules locally (a retry decides the phase edge, an activation what is frozen, accept and waive the
accept rules). An older CLI applies rules the pin has since fixed. A warning on stderr is lost in an agent's or a
script's output; the evidence is that nobody noticed twice. A false refusal costs one flag, and a stop is never
refused. The alternative (warn only) is the same table with every `refuse` read as `warn`; the delegate may pick it.

**What it cannot catch.** A CLI older than 0.4.60 has no guard. The two cases of the evidence would not have been
caught; the guard protects from the next pin move on, once a person's CLI is 0.4.60 or later. A stale
`refs/remotes/origin/<base>` can hold an older pin (no refusal, never a false one). A pin without a version (a copy of
the action, a fetched pin by commit) is not checked. The pinned harness could tell from `run.started{harness_version}`
of a local command that an older CLI wrote to a unit; that notice is an open question.

Open questions:

- **Refuse or warn.** Recommended: refuse, as above.
- **A newer CLI.** A CLI newer than the pin applies newer rules too (D2's last case). Recommended: the same check
  prints a warning, never a refusal, when the CLI is newer than the pin, because a newer CLI is how a person moves the
  pin (`l4 upgrade`) and a refusal would block that path.
- **A notice in CI.** Recommended: in a later release, the plan step logs one line when a unit's latest person command
  (`run.started{command: retry|restart|resume}`) recorded a `harness_version` older than the running harness, and
  `l4 status --unit` shows it; this is the only check that can see a CLI older than 0.4.60.

How it fails safe: an unknown pin or an unreadable file is "no pin", so the check never blocks a command it cannot
judge; a known older CLI cannot write without an explicit flag; CI is untouched.

### D6. An actor policy for `l4 yolo activate`

Fact: `l4 yolo activate` has no actor check (`commands.py:1254-1379`). `l4 yolo go` stops an agent before it activates
(L4-YOLO-086), and the skill tells an agent to hand the activation to a person (L4-SKL-004). The command itself lets an
agent activate. 0.4.60 only records the kind (D3). Open question for the owner: refuse an agent in `l4 yolo activate`
unless a key on the base branch allows it, as `yolo.extend_by_agents` does for limits. Recommended: yes, in a later
release, default false, after 0.4.60's records show how often agents activate; the refusal text names the key and the
person's command.

### D7. Doctor CFG-013

`_cfg_013` in `doctor/checks_config.py`, registered as `Check("CFG-013", "A judge chain has a fallback", "warn", ...,
CONFIG_SCOPES)`:

- `judges = list(dict.fromkeys(cfg.roles.judges))`, `plan = list(dict.fromkeys(cfg.roles.plan_judges))`.
- No judge: `skip` (`roles.judges is empty: CFG-002 says so`).
- Problems, joined by `; `:
  - one judge: `roles.judges has one profile (<name>): unit verification has no fallback judge when it fails`, and,
    when `plan` is empty, `, and a judge for plan readiness reviews only belongs in roles.plan_judges, which unit
    verification never reads: do not cut roles.judges for a review`;
  - `plan` with one profile: `roles.plan_judges has one profile (<name>): the plan review has no fallback judge (it does
    not fall back to roles.judges)`.
- Problems: `CheckResult("fail", text, "add a second judge profile, of another vendor where you can, to the chain
  named; put a judge for plan reviews only in roles.plan_judges")`. Else `pass` with `roles.judges has <n> profiles`
  and, when set, `; roles.plan_judges has <m>`.

A fresh `l4 init` writes one judge, so it warns: that is intended, and it does not change the exit code.

## Risks / Trade-offs

- Every plan reviewed under 0.4.59 and not activated costs one more full review, and an accepted subject needs a new
  acceptance. The CHANGELOG says so.
- A judge may still misread a list; the order removes the misreading the evidence shows, not every misreading.
- The guard adds one `git show` of two small files to the guarded commands.
- Refusing an older CLI can stop a person in a hurry; the refusal names the flag and the install line.
- A CLI newer than the pin and a pin older than 0.4.60 disagree about the currency of a 0.4.59 review (D2); the
  CHANGELOG tells the person to use the pinned `l4`.
- The guard runs in the CLI entry every `main([...])` test of the harness goes through; a test whose repository pins
  a version above `l4.__version__` would now exit 2. None was found (`harness.version` in the test configurations is
  `0.1.0` or written by `l4 init`; the workflow pins in tests carry `v0.3.0` to `v0.4.19`), and task 5.2 runs the
  command tests to catch one.

## Migration

- Ledgers of 0.4.59 fold unchanged: every new field is optional and read with `.get`.
- An older harness ignores the new fields. A 0.4.59 CI reading a 0.4.60 plan review sees version 5 and treats the
  review as stale, which is the safe side.
- No configuration key is added or changed.
