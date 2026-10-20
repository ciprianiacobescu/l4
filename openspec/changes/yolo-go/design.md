## Context

The maintainer's request is quoted in `proposal.md`. A plan reaches activation today through a fixed sequence of
commands whose order is only taught by the docs and the skill. This change adds one command that walks that sequence,
reads where the plan is before each step, and stops at the first step that cannot pass with exactly one next command.
It adds no rule of its own about who may accept or activate, no ledger event and no configuration key: every write is
made by the existing command that makes it today, with its own refusals and lease.

Labels: [V] verified in the code at c1994292 or on the branch `force-accept` at beff92e5, [I] inferred, [G] guessed
(yolo-guardrails has no commit yet; what it adds is taken from its brief).

Builds on (merge order): force-accept (L4-YOLO-057..067: `l4 yolo accept PLAN --all --force`, a person's `--yes`,
prompts on stderr, `ReviewView.covered`/`force`), then yolo-guardrails [G] (cause-and-fix refusals with a `Fix:` line,
`review --record` refuses `HEAD != origin/<base>`, the judge allowlist at load, the plan runbook in the skill's
`operate.md`, the script `yolo_preflight.py`). The implementer rebases on both before task 1.1.

## Goals / Non-goals

Goals: one command from a committed plan to an active plan; safe to run again at any point; one machine-readable
answer to "where is the plan and what is the one next command"; agents drive the steps they may take and hand the
person the exact command for the rest.

Non-goals:
- No new decision rule. Who may accept is `accept.check` (L4-YOLO-027) and force-accept's actor rule (L4-YOLO-058);
  what activation needs is L4-YOLO-005; `go` adds only the rule that activation is a person's step (D8), which the
  docs and the skill already state and which `run_activate` does not enforce [V: `run_activate` never calls `actor`].
- `l4 yolo resume`, `cancel`, `waive`, `draft` and limits are outside `go`: a plan stopped for any reason other than
  `inputs_changed` or `unit_rejected` is a stop with the status's own next step (D5).
- The CI plan step, the review, the readiness prompt and the ledger format do not change.

## D1. The command

```
l4 yolo go PLAN --reason TEXT [--accept-findings | --force] [--yes] [--json] [--no-push] [--local] [--wait DURATION]
```

Usage rules, checked in this order before anything is read or fetched (exit 2, message on stderr, no JSON):
`PLAN` is not a plan id (`_plan_id`); `--reason` empty after strip or over `MAX_REASON` (1,000) characters;
`--accept-findings` with `--force`; `--force` with `--local` (a force acceptance reviews nothing); `--wait` not `0` and
not a duration of `config.schema.duration_seconds` (`30s`, `30m`, `1h`).

- `--reason`: one text for every write of the run. With `--accept-findings` it is the implementer's note of each
  acceptance (L4-YOLO-027 `reason`), with `--force` the force acceptance's, and the activation's `reason`. The help
  says so: write it for the implementer when accepting.
- `--accept-findings`: accept the subjects that are not READY, by the rules of `l4 yolo accept` (D7).
- `--force`: a person's force acceptance of every subject (force-accept). An agent caller (`l4.actor.actor`) with
  `--force` stops before anything is read (D7.3, exit 27).
- `--yes`: passed to `l4 yolo accept`, where it replaces the typed plan id for a person (L4-YOLO-063) and is required
  for an agent (L4-YOLO-027). For a person's `go` it also skips the plan id typed before the activation (D8).
- `--json`: D10. `--no-push`: D4. `--local`: D6. `--wait`: the bound of the CI review wait (D6), default `30m`; `0`
  asks CI and returns at once.

Handler `l4.yolo.go:run_go(app, *, plan, reason, accept_findings=False, force=False, yes=False, as_json=False,
no_push=False, local=False, wait="30m") -> CommandResult`. `yolo go` joins `_CANCELLABLE` in `cli.py` (a signal stops
it: exit 16; nothing is written by `go` itself, D11).

## D2. The loop

`go` is a loop over facts, a pure decision and one action [I: the shape that makes "continue from where it is" a
property of the code rather than of each step]:

```
preflight (D3) -> sync + read the ledger -> push (D4) -> loop: gather facts -> decide -> act
```

- **gather** (`_gather(ctx, plan_id, flags, asked, waited_out) -> Facts`): `_sync`, the plan file at
  `origin/<base>`, the fold of the ledger, the admission at the target (`_admission_at`, D5), the unit digests now
  (`_digests`), `_review_view(...)` (with force-accept's `covered`), for each problem subject `accept.check` for this
  caller and for a person, `_activation_blocker` (D8). Reads only.
- **decide** (`decide(facts) -> Action`, pure, no I/O): the first rule of D5..D8 that applies, in step order.
  `Action` is `Stop(code, step, status, detail, next_command)`, `Active(detail)` or `Do(kind, subjects)` with `kind`
  in `review_ci`, `review_local`, `accept`, `force_accept`, `activate`.
- **act**: runs the existing command for `Do` (D6..D8), records the step's status, and gathers again. A `Do` kind
  runs at most once per run; when `decide` returns a kind that already ran and the facts did not change, the run stops
  with exit 28 `no progress: <kind> ran and the plan did not change` (a guard against a loop, never expected).

Each step of `STEPS = (preflight, push, check, review, findings, accept, activate)` ends with one status:

| status | meaning |
|---|---|
| `ok` | the step's condition held; this run wrote and pushed nothing for it (a reused review, holding acceptances, an active plan) |
| `done` | this run made it hold (a push, a review recorded, acceptances recorded, the activation) |
| `skipped` | the step does not apply (nothing to accept; no review under `--force`; review, findings and accept of an active plan) |
| `pending` | waits for something outside: the CI review did not arrive within `--wait` (exit 24) |
| `stopped` | the run stops here (every other stop code) |
| `person` | the run stops here because the step is a person's (exit 27) |
| `not_reached` | after the stop |

**Reusing the commands' output.** The existing commands print with `ctx.say` (stdout) and end a refusal with
`L4Exit` [V]. Every command `go` calls runs inside `_relay(lines, to)`: `sys.stdout` is replaced by a line writer that
keeps every line in `lines` (the step's `detail`), drops lines that start with `Next:` (the run prints one next command,
D9) and forwards the rest to `to`, flushed line by line: stdout in text mode (indented two spaces), stderr in `--json`
mode while the command may prompt a person (D7), nothing otherwise. Prompts are on stderr once force-accept's task 4.1
is in (its D8: `_confirm`, `click.prompt(..., err=True)`) [V: force-accept design at 1a701099; at c1994292 the prompts
of `run_accept` still go to stdout], which is why the rebase on force-accept comes first. An `L4Exit` from a called
command becomes the stop of D9; its `Fix:` line (yolo-guardrails
gives every refusal one [G]) becomes the next command when it holds one command, else the go command again.

## D3. Preflight

The same local checks as the skill's `scripts/yolo_preflight.py` (yolo-guardrails), whose first two checks are the ones
that need no network and no harness: `plan-file` and `clean-tree`. The script's other checks (origin, HEAD against
origin, the plan and its folders on origin, the judge roles, the OpenCode major, the caller, the harness, admission, the
review) are steps of `go` itself (the push, the check, the review) or `l4 doctor`'s. One harness implementation,
`l4.yolo.preflight.problems(repo, git, plan_id, *, base_ref, openspec_root, kiro_root) -> list[Problem]`
(`Problem(code, text, fix)`), runs locally with no network, before `_sync`. The script is not changed and imports
nothing from `l4`; it runs without the harness, as `validate_plan.py` does [V]. The checks, in the script's order
(task 2.1 made this section follow the script, not the brief it was first written from):

1. `plan_missing` (script check `plan-file`): `.l4/plans/<plan>.json` is not a file in the working tree. Fix: `l4 yolo
   draft <plan>`; when `base_ref` has the file (a checkout behind origin), `git pull --ff-only origin <base>`.
   `plan_not_json` (the same check): the file is not JSON. Fix: `l4 yolo check <plan> --worktree`.
2. `clean-tree` of the script, `git status --porcelain=v1 --untracked-files=all`, split by what the entry is:
   - `dirty`: an entry that is not untracked (a tracked file differs from HEAD, staged or not). Fix: `git status`.
   - `plan_uncommitted`: an untracked file under `.l4/` (the plan file itself, or any other). Fix: `git add <path> &&
     git commit`.
   - `unit_uncommitted`: an untracked file under the folder of a unit the working tree's plan lists (folders as the
     script resolves them from `spec.openspec.root` and `spec.kiro.root`). Fix: `git add <folder> && git commit`.

An untracked file anywhere else is not a problem (a checkout may hold a person's own notes). No origin, or the base
branch not on origin, is the preflight stop too (`_sync`'s refusal, exit 20; fix `git remote add origin <url>` or `git
push -u origin <base>`). The stop prints every problem as `<code>: <text>` and the first one's fix as the next command.

Parity: `tests/unit/yolo/test_yolo_go_preflight.py` runs the script (`--json --no-fetch`) and the function on the same
fixture repositories (clean; each problem alone) and asserts that the script's check that catches a code fails exactly
when the function reports it: `plan_missing` and `plan_not_json` are `plan-file`; `dirty`, `plan_uncommitted` and
`unit_uncommitted` are `clean-tree`. The script prints check names, not codes; the script is the arbiter of pass and
fail.

## D4. Push

After preflight and `_sync` (which fetches `origin/<base>`), with `ahead = rev-list --count origin/<base>..HEAD` and
`behind = rev-list --count HEAD..origin/<base>`:

- `ahead == 0`: `ok` (`origin/<base> has HEAD`, or `the checkout is <n> commit(s) behind origin/<base>; go reads
  origin`). Nothing is pushed.
- `ahead > 0`, in this order:
  1. `behind > 0`: stop 21, `HEAD and origin/<base> have diverged`, next `git pull --rebase origin <base>`.
  2. HEAD is not the branch `<base>` (`git symbolic-ref --short HEAD`): stop 21, `go pushes only the branch <base>;
     HEAD is <branch|detached> with <n> commit(s) not on origin/<base>`, next `git switch <base>`.
  3. The plan is active or waiting (its ledger, read before the push) and a commit ahead changes the plan file or a
     unit folder of the plan (`git diff --name-only origin/<base>..HEAD`): stop 21, `pushing this stops the active
     plan <plan> with inputs_changed`, next `l4 yolo status <plan>`. A person who means it pushes by hand. (A plan
     stopped with `inputs_changed` or `unit_rejected` is not guarded: pushing the fixed spec is its way on.)
  4. `--no-push`: stop 21, next `git push origin <base>`.
  5. An agent caller and a path outside the hand-off scope (D12): stop 27, next `git push origin <base>` (a person's).
  6. The working-tree admission, as `l4 yolo check <plan> --worktree` (`_admit_worktree` plus `coverage_findings`)
     [V]: a finding stops with 22, next `l4 yolo check <plan> --worktree`. So no plan that admission refuses, and no
     spec that no plan covers (`uncovered`: it would run at once), is pushed.
  7. `git push origin refs/heads/<base>:refs/heads/<base>` with `ctx.push_cfg`, no `--force`, no
     `--force-with-lease`, hooks not skipped. A refusal stops with 21 and git's reason (`explain_push_failure`,
     redacted); a non-fast-forward refusal's next is `git pull --rebase origin <base>`, any other `git push origin
     <base>`. Then `_sync` again: `origin/<base>` is HEAD. Status `done`, `pushed <n> commit(s) to origin/<base>
     (<sha10>)`.

## D5. Check and the plan's state

`_admission_at(ctx, plan_id, rev, state)` is the body of `run_check` (the plan file at `origin/<base>`, `_read_units`,
`admit` with `_held` and `archived_at`), factored out; `run_check` calls it and prints as today. `decide`, in order:

1. Status `active` or `waiting`: `Active` (exit 0), before the admission is looked at (an active plan holds its own
   units). check is `ok` (`<plan> is <status>`); review, findings and accept are `skipped` (`the plan is active`);
   activate `ok` (`active since <at> by <by>`; waiting: `waiting: <reason>`). Next `l4 yolo status <plan>`.
2. `completed`: `Active` (exit 0), the same statuses, activate `ok` (`completed`), next `l4 yolo report <plan>`.
3. `cancelled`, or `stopped` with a reason other than `inputs_changed` and `unit_rejected`, or `unit_rejected` with the
   rejected unit's spec unchanged (R8, the rule of `run_review` [V]): stop 23 at check; detail the status's `Next:`
   line (`_next_line`), next `l4 yolo status <plan>`.
4. No plan file at `origin/<base>`, a file that is not a plan, or an admission finding: stop 22 at check with every
   finding (`_findings_text`), next `l4 yolo check <plan> --worktree`.
5. Else check `ok`: `admitted at origin/<base> <sha10>; order: <ids>`, then D6.

## D6. Review

1. `covered` (a force acceptance holds for every subject, force-accept D5): `skipped` (`force-accepted: no review is
   needed`).
2. `_review_view(...).kind == "current"`: `ok` (`reviewed at <at> (<source>): <n> READY, <m> not READY`); no
   dispatch, no judge.
3. `--force`: `skipped` (`--force accepts without a review; nothing is judged`); then D7.3. No CI run is asked: a
   force acceptance calls no model (L4-YOLO-057), and a CI review asked now would be charged for nothing.
4. `--local`: `run_review(app, plan=..., local=True)` [V: admits, judges with `prior`, records `plan.admitted` and
   `plan.reviewed`]. `L4Exit(WAITING_CAPACITY)` (no judge could run) stops with 25, next the go command without
   `--local`; any other `L4Exit` is D9's mapping. Status `done`.
5. CI: when this run pushed (D4.7) and the pushed head's message holds neither `[skip ci]` nor `[ci skip]`, the push
   starts the harness's CI on the base [V: `l4.github*.yml` `on: push: branches: [<base>]`; `l4.gitlab-ci.yml`
   `$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH == "<base>"`]: nothing is asked. Otherwise
   `start_run_result(app, cfg)` (D-contracts): `started` or `already_queued` go on; `refused`, `unsupported` or
   `unavailable` stop at once with 24, next `how_to_start(...)` (`gh workflow run l4.yml --ref <base>`, or the GitLab
   pipeline page), detail `then run the go command again`.
   Then the wait: every `POLL_S` (15 s) up to `--wait`, `PlanStore.read()` of the plan ref (one fetch), the fold and
   `_review_view` against the digests gathered before the wait. It ends when the view is `current` (status `done`,
   `reviewed in CI at <at>`), or a `plan.refused` newer than the ask is on the ledger (stop 22, its findings), or the
   bound is reached (stop 24 `pending`, `CI was asked at <time> (<answer>); no review recorded within <wait>`, next the
   go command again). `--wait 0` asks and ends at once with 24. Text mode prints one line when the wait starts
   (`review: waiting: … polling the plan ledger every 15s for up to <wait>`) and one when it ends; `--json` writes the
   first to stderr. `_sleep` and `_clock` are module attributes of `l4.yolo.go` (tests replace them); each poll calls
   `cancel.check()`.
   The ledger, not the CI API, is read: the ledger is what activation reads, and the local forge has no run API [V:
   `ci/watch.py` needs a GitLab or GitHub client]. A CI run whose judge cannot run records nothing and logs `the review
   waits` [V: `cycle._review`]; `go` then sees no review and stops at the bound. CI reviews one plan per run [V:
   `_judge_down`, L4-YOLO-004], so another plan may be reviewed first.

## D7. Findings and acceptance

Problems are `view.problems` (each not-READY subject without a holding acceptance and not cleared by force). For each
problem subject `entry = _entry_of(latest_review, subject)` and `accept.check(state, events, subject, entry, cfg,
who)` for this caller and for `("person", None)` (the refusal of an entry without `material` counts as a refusal too,
as in `run_accept` [V]).

1. No problem: findings `ok` (`every subject is READY` or `<n> READY, <a> accepted`); accept `ok` when acceptances
   hold (`<a> acceptance(s) hold`), else `skipped`; then D8.
2. Problems, no flag: stop 26 at findings; detail one line per problem (the `view.problems` text: subject, verdict,
   most severe finding). Next: when this caller may accept every problem subject, the go command with
   `--accept-findings` (an agent: and `--yes`); else `l4 yolo findings <plan>`. When a problem is BLOCKED and the
   caller is a person, the detail adds `when no model can judge it, a person may run: l4 yolo go <plan> --reason "…"
   --force` (the reviewed alternative comes first, as force-accept D10 asks).
3. `--force` (a person; an agent never reaches this: D1): when the review is current and has no problem, accept is
   `skipped` (`the review is READY: nothing to force`). Otherwise `run_accept(app, plan=..., subject=None,
   reason=..., withdraw=False, yes=yes, all_subjects=True, force=True)` inside `_relay` (text: to stdout; `--json`: to
   stderr), so the person sees force-accept's summary before its prompt. Status `done`; a wrong answer (`the plan id was
   not typed`) stops with 29; any other refusal is D9's mapping. Findings is `ok` with the problems as its detail
   (`overridden by --force`), or `skipped` when there is no review.
4. `--accept-findings`, all or nothing: when a problem subject cannot be accepted by this caller, nothing is recorded:
   - every refusal is `acceptance is a person's decision` (an agent, `accept_by_agents` false) and a person may
     accept every subject: stop 27 at accept, next `l4 yolo go <plan> --reason "…" --accept-findings` (a person's);
   - else stop 26 at findings with each subject's refusal and fix; next `l4 yolo findings <plan>`.
   An agent without `--yes`: stop 29 at accept, next the go command with `--yes` (the rule of `l4 yolo accept` for an
   agent [V]). Otherwise, for each problem subject in plan order, `run_accept(app, plan=..., subject=s, reason=...,
   withdraw=False, yes=yes)` inside `_relay`: a person sees each subject's findings and types the plan id, or passes
   `--yes`; an agent records `actor: agent` [V: `run_accept`]. One `plan.accepted` per subject, each with its own
   lease. A wrong answer stops with 29 (the subjects accepted before it stay accepted and hold: a re-run goes on from
   there); accept `done` (`accepted <n> subject(s)`), findings `ok` with the problem lines as its detail.

Not one confirmation for all subjects: calling `run_accept` per subject keeps that command the one place that decides,
shows and records an acceptance, with no new keyword on it. `--yes` removes every prompt.

## D8. Activation

Every problem is cleared (D7.1). Then:

- **An agent** (`actor` is not a person): `_activation_blocker(ctx, plan_id, parsed)` (the refusals of `run_activate`
  after the review: the target not on origin; another plan active, waiting or stopped on the target; factored out of
  `run_activate`, which calls it): a blocker stops with 28 and its text. The blocker has no `Fix:` line (it matches
  today's refusal texts), so when it is another plan holding the target, `go` reads the cancel command out of the text
  (`l4 yolo cancel <other> --reason TEXT`, `cancel_command`) and adds the line `cancelling plan <other> is a person's
  decision`: for an agent the next line is a person's step, `Next: a person runs: l4 yolo cancel <other> --reason TEXT
  (stop here: cancelling a plan is a person's decision)` (in `--json`, `next_command` is the command alone), because an
  agent never cancels or activates a plan; for a person (the refusal of `run_activate`, D9) the next command is the
  cancel command itself. Any other blocker keeps the go command. Else stop 27 at activate,
  `activation is a person's decision`, next `l4 yolo go <plan> --reason "<reason>"` (with `--local` dropped; the
  person's run needs no flag: the acceptances hold). Text: `Next: a person runs: l4 yolo go …`. Nothing is recorded.
- **A person**: `run_activate(app, plan=..., reason=..., no_run=False)` inside `_relay`. It records `plan.activated`
  with the acceptances that hold and the force items, prints them, and starts a run [V]. Before it, and only for a
  person without `--yes`, `go` asks `Type the plan id (<plan>) to activate <plan>` with `commands._confirm` (stderr,
  terminal only; owner decision, open question 3). A wrong answer, or no terminal and no `--yes`, stops with 29 at
  `activate` and the go command, recording nothing. `l4 yolo activate` itself still asks nothing [V], and
  `plan.activated` has no confirmation field. Status `done`; exit 0. A refusal is D9's mapping (28).

## D9. Stops, exit codes, next command, text output

`GoStop(IntEnum)` in `l4/yolo/go.py`, not members of `ExitCode`: `ExitCode`, `SEVERITY_ORDER`, `CI_ALLOWED`,
`most_severe` and `map_exit` stay as they are [V: `test_exitcodes` asserts `set(SEVERITY_ORDER) == {int(c) for c in
ExitCode}`]; `run_go` returns `CommandResult(code=int)` [V: `CommandResult.code: ExitCode | int`]. `go` is an
operator's command, never a CI step; `l4 ci map-exit` reports 20..29 as codes outside its table.

| exit | name | step | when | next command |
|---|---|---|---|---|
| 0 | `active` | activate | activated now, or already active, waiting or completed | `l4 yolo status <plan>` (completed: `l4 yolo report <plan>`) |
| 20 | `preflight` | preflight | D3, or no origin / no base branch on origin | the first problem's fix |
| 21 | `push` | push | D4.1..4, D4.7 refused | D4 |
| 22 | `not_admitted` | push, check or review | D4.6, D5.4, a CI `plan.refused` (D6.5) | `l4 yolo check <plan> --worktree` |
| 23 | `plan_state` | check | D5.3 | `l4 yolo status <plan>` |
| 24 | `review_pending` | review | D6.5: no review within `--wait`, or no run could be asked | the go command again (or the start command) |
| 25 | `review_failed` | review | D6.4: the judge cannot run here | the go command without `--local` |
| 26 | `findings` | findings | D7.2, D7.4 | D7 |
| 27 | `person` | push, accept or activate | the step is a person's: D4.5, D7.4, D8, `--force` by an agent (D1) | the person's command |
| 28 | `refused` | any | a called command refused (its `L4Exit` other than a lost lease), an activation blocker (D8), a lease lost three times (D11), no progress (D2) | the refusal's `Fix:` command; for another plan holding the target the cancel command (an agent: as a person's step, D8); else the go command again |
| 29 | `not_confirmed` | accept or activate | a person did not type the plan id (or has no terminal to type it on), before accepting or before activating; an agent without `--yes` at accept | the go command (an agent: with `--yes`) |

Exit 1 (a harness or network fault), 2 (D1) and 16 (a signal) keep their meaning and print no JSON.

The go command again: `l4 yolo go <plan> --reason <shlex-quoted reason>` plus the flags the caller gave
(`--accept-findings`, `--force`, `--yes`, `--json`, `--local`, `--no-push`, `--wait <given>`) in that order; a
person's command (27) has `--reason` and the flag the person's step needs, and never `--yes`, `--json` or `--no-push`.
Built by the pure `command_line(plan_id, flags, *, drop=(), add=(), person=False)`.

Text mode: one line per step as it ends, `<step>: <status>: <detail first line>`, then the relayed lines indented two
spaces; steps `not_reached` print nothing; the last line is `Next: <command>` (27: `Next: a person runs: <command>`).
Exactly one `Next:` line per run.

## D10. `--json`

stdout holds one JSON document and nothing else, printed when the run ends:

```json
{
  "schema": "l4/yolo-go@1",
  "plan": "p1",
  "step_reached": "findings",
  "steps": [
    {"name": "preflight", "status": "ok", "detail": "the tree is clean; .l4/plans/p1.json and 2 unit folder(s) are committed"},
    {"name": "push", "status": "ok", "detail": "origin/main has HEAD"},
    {"name": "check", "status": "ok", "detail": "admitted at origin/main 1a2b3c4d5e; order: openspec:a, openspec:b"},
    {"name": "review", "status": "ok", "detail": "reviewed at 2026-10-19T10:00:00Z (ci): 1 READY, 1 not READY"},
    {"name": "findings", "status": "stopped", "detail": "openspec:b: NEEDS_REVISION: testability: …"},
    {"name": "accept", "status": "not_reached", "detail": ""},
    {"name": "activate", "status": "not_reached", "detail": ""}
  ],
  "next_command": "l4 yolo go p1 --reason 'ship it' --accept-findings",
  "next_by": "caller",
  "exit": 26
}
```

- `steps` always has the seven steps in order; `step_reached` is the last step whose status is not `not_reached`;
  `exit` equals the process's exit code; `detail` is a string (several lines joined with `\n`), redacted.
- `next_by` is `person` when `next_command` is a person's step: exit 27, and exit 28 when it is the cancel command
  handed to an agent (`Stop.person_step`); else `caller` (the one who ran `go` runs it). `l4 yolo cancel` has no actor
  check, so an agent that follows a `next_by: person` command would cancel another plan: the MCP tool says agents
  never run one.
- `schema` is added to the decided keys: every JSON document of `l4 yolo` names its schema (`l4/yolo-status@1`,
  `findings.SCHEMA`) [V].
- With `--json`, what a person must read before a prompt (the relayed output of `run_accept`) and the wait's progress
  line go to stderr, with the prompt [V: force-accept D8 prompts on stderr].

## D11. Safe to re-run

- **Idempotent.** Every step first reads whether it already holds: nothing ahead (no push), a current review (no
  dispatch, no judge), holding acceptances or a covering force acceptance (no accept), an active plan (no activation).
  A second run with nothing changed records nothing (the plan ref's head does not move), pushes nothing, starts no
  judge, and asks the forge for a run only when the first run ended at 24 (the review still missing); a run that waits
  is not doubled (`already_queued`) [V: `start_run`].
- **Interrupted.** `go` writes only through the existing commands, each one leased append [V: `_append`], so the
  ledger is always at a step boundary. A run stopped anywhere (a signal, a closed terminal, a crash, between two
  per-subject acceptances) leaves what it recorded, and the next run reads it and goes on. Nothing is written during the
  CI wait.
- **Concurrent.** There is no plan lock; the plan ledger's lease is the serialisation (L4-YOLO-006) [V:
  `PlanStore.append(expect=head)`]. A command `go` calls that loses the lease raises `L4Exit(USAGE_ERROR, _MOVED)`
  [V]; `go` recognises it (`str(exc) == commands._MOVED`), gathers again and decides again: when the other writer
  recorded the same thing (the acceptance now holds, the plan is now active), the step is `ok` and the run goes on; when
  the new state needs a write, it is made again by its command (a person is asked again, for the new state). At most
  three lost leases per run; the fourth stops with 28, next the go command again. Two runs never both activate: the
  second's `run_activate` reads `active` and refuses, or loses the lease and then reads `active` (`Active`, exit 0).

## D12. Agents and MCP

An agent (any marker of `AGENT_MARKERS`, or no terminal) runs `go` with the same steps and rules; it is never asked
anything. What an agent's run does: preflight; push (D4, within the hand-off scope); check; review (CI or `--local`);
findings; accept only with `--accept-findings --yes` and `yolo.review.accept_by_agents` true at `origin/<base>` (the
rule of `run_accept`, unchanged); never `--force` (D1, exit 27); never activation (D8, exit 27).

**The agent's push (decided).** No configuration key. An agent's `go` pushes only the hand-off that the skill already
makes the agent push (`plan.md` "Hand off": `git add .l4/plans/<id>.json <the new spec folders>`, `git push` [V]):
every path that `git diff --name-only origin/<base>..HEAD` names is `.l4/plans/<plan>.json` or under the folder of a
unit this plan lists. Anything else (another plan file, `.l4/config.yaml`, code, CI files) is a person's push (exit
27). Why: (1) the skill already lets an agent push exactly this, so a key defaulting to false would stop every agent's
`go` at step (b) and bring back the multi-step sequence; (2) the risk `go` adds is one command that pushes and then
acts on what it pushed: a pushed `.l4/config.yaml` with `accept_by_agents: true` would let the same run accept for the
agent, defeating "a pushed change a person can see" (L4-YOLO-027); the scope rule closes that; (3) a key would bind
only `go`, not `git push`, so it would add friction without a boundary (the markers are not one either [V:
`l4/actor.py`]). The forge's own branch protection still decides whether the push is accepted (D4.7).

**MCP.** New tool `l4_plan_go`: words `("yolo", "go")`, `json_flag="always"`, `consts=("--no-push",)`, params `plan`
(required), `reason` (required, `--reason`), `wait` (string, `--wait`), `seconds=REVIEW_SECONDS`. No `accept_findings`,
`force`, `yes` or `local` parameter. So the tool pushes nothing of the caller's (as `l4_plan_review` promises [V]),
records nothing but what CI's review records, accepts nothing and activates nothing (the caller is an agent: D8); it
is read-mostly. Its description says that it asks CI for a review (costs judge tokens), may wait up to `wait`, never
pushes, accepts or activates, and that the result's `next_command` is a person's command when a step is a person's.
L4-MCP-003 lists it under Write.

## D13. Documentation

- `docs/yolo-mode.md`: a section "One command: `l4 yolo go`" before "Review in CI, then activate": the steps, what each
  reuses, the flags, the stop table of D9, the JSON document, re-running, what an agent's run does, and that `go`
  activates (to look without acting: `l4 yolo status`). "Review in CI, then activate" opens with "or step by step:".
- `docs/runbook.md` 12.2 starts with the paragraph "Or simply: `l4 yolo go <plan-id> --reason "<why>"`" (it runs
  the steps below and stops with one `Next:` command), a table of its exit codes, and "The steps one by one:" before
  the numbered list.
- Skill `references/operate.md`: in the plan runbook (yolo-guardrails), step 1 for a person: `or simply: l4 yolo go
  <id> --reason "…"`; in "Delivery plans", the `l4 yolo go` line; for an agent: `l4 yolo go <id> --reason "…" --json
  --wait 9m` (under a 10-minute tool limit; a `review_pending` exit means run it again later), then give the person
  `next_command` when `exit` is 27; never `--force`. `references/plan.md` "Hand off": after the commit, an agent may run
  the same command instead of `git push` and `l4 yolo check`.
- `CHANGELOG.md`: `## 0.4.19 (unreleased)` above `## 0.4.18 (2026-10-20)` (released; or into 0.4.19, when another
  change of 0.4.19 has made it), `### Added`: `l4 yolo go`, the MCP tool.
- `docs/SPEC.md`: L4-YOLO-080..091 after L4-YOLO-067 (or the last L4-YOLO requirement at the merge); SCN-YOLO-200..238
  in 23.20; row 55 of the change table; the CLI row `l4 yolo go`; one sentence in L4-CLI-001 (`l4 yolo go` alone
  exits with the stop codes 20 to 29 of L4-YOLO-087); `l4_plan_go` in L4-MCP-003.

## Contracts (what the tasks share; do not change one without the orchestrator)

How `go` reaches the existing code (the tests' patches depend on it): `go` determines the caller as
`accepting.actor(ctx.app.environ, commands._stdin_tty())` and calls `commands._sync`, `commands.run_review`,
`commands.run_accept`, `commands.run_activate` and `commands._confirm` through the module attribute (`from l4.yolo
import commands` then `commands.run_accept(...)`), never through a `from l4.yolo.commands import run_accept`, so that
a test's `monkeypatch.setattr("l4.yolo.commands.<name>", …)` reaches `go` (the `person` and `agent` helpers patch
`l4.yolo.commands._stdin_tty` and `l4.yolo.commands.click.prompt` [V]). The `_relay` writer is an `io.TextIOBase`
subclass (`writable()` true, `write` returns the length), installed with `contextlib.redirect_stdout`, so that
`click.echo` resolves it as stdout at each call.

New, `src/l4/yolo/go.py`:
- `class GoStop(IntEnum)`: `ACTIVE = 0`, `PREFLIGHT = 20`, `PUSH = 21`, `NOT_ADMITTED = 22`, `PLAN_STATE = 23`,
  `REVIEW_PENDING = 24`, `REVIEW_FAILED = 25`, `FINDINGS = 26`, `PERSON = 27`, `REFUSED = 28`, `NOT_CONFIRMED = 29`
- `STEPS`, `STATUSES` (D2); `@dataclass Step(name, status="not_reached", detail="")`
- `@dataclass GoResult(plan, steps, next_command, exit)` with `step_reached` and `as_json() -> dict` (D10)
- `@dataclass(frozen=True) Flags(reason, accept_findings, force, yes, as_json, no_push, local, wait, wait_s)`
- `@dataclass(frozen=True) Facts(actor, flags, status, stop_reason, status_next, rejected_unchanged, plan_found,
  plan_valid, admission, review_kind, review_detail, covered, problems, refusals, person_refusals, blocked,
  activation_blocker, asked, waited_out, refused_after_ask, activated_by, activated_at)`: `admission`, `problems` tuples
  of lines; `refusals`/`person_refusals`: subject -> refusal text or None; `blocked`: problem subjects whose verdict is
  BLOCKED
- `Stop(code, step, status, detail, next_command)`, `Active(detail, next_command)`, `Do(kind, subjects=())`;
  `decide(facts: Facts) -> Stop | Active | Do`
- `command_line(plan_id, flags, *, drop=(), add=(), person=False) -> str`
- `run_go(app, *, plan, reason, accept_findings=False, force=False, yes=False, as_json=False, no_push=False,
  local=False, wait="30m") -> CommandResult`
- module attributes `POLL_S = 15.0`, `_sleep = time.sleep`, `_clock = time.monotonic`, `MAX_MOVED = 3`

New, `src/l4/yolo/preflight.py`: `@dataclass(frozen=True) Problem(code, text, fix)`;
`problems(repo, git, plan_id, *, base_ref) -> list[Problem]`; codes `dirty`, `plan_missing`, `plan_uncommitted`,
`unit_uncommitted` (D3; the script's list wins at integration).

Changed (behaviour unchanged for their own commands):
- `l4.yolo.commands._admission_at(ctx, plan_id, rev, state=None) -> _AtTarget(file, plan, units, admission)`
  (`plan`, `units`, `admission` None for a file that is not a plan); `run_check` calls it.
- `l4.yolo.commands._activation_blocker(ctx, plan_id, parsed) -> str | None` (the `activate: …` text without the
  prefix); `run_activate` calls it.
- `l4.state.retry.start_run_result(app, cfg) -> tuple[str, str]`: the forge's answer (`started`, `already_queued`,
  `refused`, `unsupported`, or `unavailable` for `ForgeUnavailable`/`ForgeError`) and the line `start_run_line` prints;
  `start_run_line` returns its second item.
- CLI: `"yolo go"` in `_SPECS` (`plan` argument; `--reason` required; `--accept-findings` dest `accept_findings`;
  `--force`; `--yes`; `--json` dest `as_json`; `--no-push` dest `no_push`; `--local`; `--wait` default `30m`), in
  `_CANCELLABLE`; `HANDLERS["yolo go"] = "l4.yolo.go:run_go"`; `OWNING_CHANGE["yolo go"] = "yolo-go"`.
- MCP: `l4_plan_go` (D12).

## Where the code changed the decided design

1. "with --yes replacing the typed id where activation asks": `l4 yolo activate` asks nothing [V], so `go` asks before
   it (owner decision, open question 3): a person types the plan id, `--yes` skips it (D8).
2. "serialised by the existing plan lease/lock": there is no plan lock, only the ledger's lease [V]; a lost lease reads
   again and decides again, at most three times (D11).
3. "Each stop exits with a distinct code": L4-CLI-001's table is closed and pinned by tests [V]; the stop codes are a
   separate enum, 20..29, returned through `CommandResult(code=int)` (D9; open question 1).
4. "dispatch and wait with a bounded poll": the poll reads the plan ledger (D6.5); after `go`'s own push CI already
   runs, so nothing is dispatched; `--wait DURATION` is added as the bound.
5. "--force (a person's force-accept of everything)": a force acceptance reviews nothing, so with `--force` the review
   step is skipped and no CI review is asked (D6.3); `--force` by an agent stops before anything (D1).
6. "push only if the repo config allows the agent to push": decided as the hand-off scope rule, no key (D12; open
   question 2).
7. "the same checks as yolo_preflight.py": the script has no commit yet; D3 specifies the checks and the parity test
   makes the script the arbiter.
8. The JSON document has `schema` besides the decided keys (D10).
9. `--accept-findings` asks per subject (the existing `run_accept`), not once for all (D7.4).

## Risks

- `go` activates a plan: a person who runs it "to look" could. Mitigation: the person types the plan id first (`--yes`
  skips it); the docs name `l4 yolo status` as the look; an agent never activates (D8); open question 3.
- A long wait in a terminal or an agent's tool call. Mitigation: `--wait` bounds it; a signal stops it with nothing
  written; the skill tells an agent `--wait 9m` and to run again on 24; MCP passes the caller's `wait`.
- The relay depends on the commands' `Next:` prefix and on yolo-guardrails' `Fix:` line [G]. Mitigation: the D9 table
  falls back to the go command; the tests of tasks 4..6 pin one refusal of each called command.
- A lost lease is recognised by the text of `commands._MOVED`. Mitigation: a test pins it; the constant is shared.
- `go` fetches several times (each called command runs `_sync`) [V]: seconds per run, accepted for reuse.
- The hand-off scope may stop an agent's legitimate push (a fix of another plan's spec): it then is a person's push,
  named as such.

## Open questions (for the owner; the design follows the recommendation until answered)

1. **Stop codes 20 to 29, or the existing codes?** The brief asks for a distinct code per stop. The design keeps a
   separate `GoStop` enum (20..29) returned through `CommandResult(code=int)`: `ExitCode`, `SEVERITY_ORDER`,
   `CI_ALLOWED`, `map_exit` and their tests do not change, and L4-CLI-001 gains one sentence. The alternative reuses
   0/2/10/11/12 and lets `step_reached` tell the stops apart, at the price of "distinct". Recommendation: keep 20..29.
2. **An agent's push: the hand-off scope, or a key `yolo.push_by_agents`?** The design lets an agent's `go` push only
   the plan file and the plan's unit folders, with no key (D12). A key defaulting to false would stop every agent at
   the push the skill already makes it do; one defaulting to true would bind `go` and not `git push`. Recommendation:
   the scope rule, no key.
3. **A prompt before the activation?** Owner decision: a person types the plan id before activation; `--yes` skips
   it; no terminal and no `--yes` stops with 29 and activates nothing (D8). (The earlier recommendation was no prompt.)
