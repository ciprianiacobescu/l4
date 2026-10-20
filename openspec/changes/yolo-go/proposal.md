## Why

The maintainer, after a plan hand-off went wrong (harness 0.4.17/0.4.18):

> "Better still would be a single l4 yolo go <id> --reason command that runs check push → review → findings → accept →
> activate in order. It should be safe to re-run and have --json output, which would remove the multi-step sequence
> that tripped us up."

Today a person (or an agent) brings a plan from a committed file to an active plan with five to eight commands in a
fixed order, each with its own refusals and its own `Next:` line: commit, `git push`, `l4 yolo check`,
`l4 yolo review` (then wait for CI, with nothing that says when it is done), `l4 yolo status` or `l4 yolo findings`,
`l4 yolo accept` per subject (or, since force-accept, `l4 yolo accept --all --force`), `l4 yolo activate`. A step taken
out of order fails late (a review asked before the push reviews the old file; an activation before the review is
recorded is refused), a re-run of a step either repeats work (`review --local` judges again) or refuses, and no command
gives a machine-readable answer to "where is this plan, and what is the one next command".

## What Changes

- **`l4 yolo go PLAN --reason TEXT [--accept-findings | --force] [--yes] [--json] [--no-push] [--local]
  [--wait DURATION]`** (L4-YOLO-080): one command that runs, in order, preflight, push, check, review, findings,
  accept and activate, over the existing commands and their rules. Each run reads the plan's ledger and the
  repository, continues from where the plan is, and stops at the first step that cannot pass.
- **Preflight** (L4-YOLO-081): the checks of the skill's `yolo_preflight.py` (yolo-guardrails): a clean tree, the plan
  file and its unit folders committed. One harness implementation (`l4.yolo.preflight`); the script is not changed and
  a parity test keeps the two in agreement.
- **Push** (L4-YOLO-082): when HEAD (the base branch) is ahead of `origin/<base>`, a fast-forward push of the base
  branch, never forced, after the working-tree admission of `l4 yolo check --worktree`; `--no-push` stops with the push
  command. It never pushes a commit that would stop an active plan. An agent pushes only the hand-off the skill already
  gives it (the plan file and its unit folders).
- **Check** (L4-YOLO-083): admission at `origin/<base>` and the plan's state; an active plan is reported as active.
- **Review** (L4-YOLO-084): a review at the current digests is reused; otherwise CI reviews it (go asks the forge for a
  run unless its own push started one) and go polls the plan ledger until the review is recorded or `--wait` (default
  30m) ends; `--local` reviews here; `--force` reviews nothing.
- **Findings and acceptance** (L4-YOLO-085): a subject that is not READY and not accepted stops the run with its
  findings; `--accept-findings` accepts each such subject by the rules of `l4 yolo accept` (all or nothing);
  `--force` is a person's force acceptance of the whole plan (force-accept, L4-YOLO-057).
- **Activation is a person's step** (L4-YOLO-086): a person's run activates with the reason; an agent's run stops with
  `a person runs: l4 yolo go <plan> --reason "…"` after checking that the activation would not be refused.
- **One stop, one code, one next command** (L4-YOLO-087): stop codes 20 to 29, one per kind of stop, and exactly one
  `Next:` command; **`--json`** (L4-YOLO-088) prints only
  `{schema, plan, step_reached, steps: [{name, status, detail}], next_command, exit}`.
- **Safe to re-run** (L4-YOLO-089): a second run with nothing changed writes nothing, pushes nothing and judges
  nothing; an interrupted run resumes; concurrent runs are serialised by the plan ledger's lease (a lost lease reads
  again and decides again, at most three times).
- **Agents and MCP** (L4-YOLO-090): an agent runs the agent-allowed steps and stops at a person's step with the exact
  command; the MCP server offers `l4_plan_go` read-mostly (always `--no-push`; no accept, force or activation).
- **Docs** (L4-YOLO-091): `docs/yolo-mode.md`, the runbook (12.2), the skill (`operate.md`: "or simply: l4 yolo go" as
  the person's step 1; `plan.md`: the agent's use), CHANGELOG `## 0.4.19 (unreleased)`, SPEC.

## Impact

- Code: new `src/l4/yolo/go.py` (the command) and `src/l4/yolo/preflight.py` (the checks); `src/l4/cli.py`
  (`yolo go`, `_CANCELLABLE`), `src/l4/commands.py` (`HANDLERS`, `OWNING_CHANGE`), `src/l4/yolo/commands.py`
  (`_admission_at` and `_activation_blocker` factored out of `run_check` and `run_activate`, which then call them;
  behaviour unchanged), `src/l4/state/retry.py` (`start_run_result`; `start_run_line` keeps its text),
  `src/l4/mcp/tools.py` (`l4_plan_go`).
- No ledger event, no ledger key, no configuration key, no prompt version change: every write `go` causes is made by
  an existing command (`run_review --local`, `run_accept`, `run_activate`) with that command's event and lease.
- Exit codes: `l4 yolo go` alone exits with the stop codes 20 to 29 (a separate enum; `ExitCode`, `SEVERITY_ORDER`,
  `CI_ALLOWED` and `l4 ci map-exit` do not change). L4-CLI-001 says so in one sentence.
- Depends on force-accept (`--force`, a person's `--yes`, prompts on stderr, `ReviewView.covered`) and yolo-guardrails
  (`yolo_preflight.py`, the `Fix:` line of every refusal, the plan runbook in `operate.md`); merge order force-accept,
  yolo-guardrails, yolo-go.
- Spec: L4-YOLO-080 to L4-YOLO-091, SCN-YOLO-200 to SCN-YOLO-238, change-table row 55, the CLI row of `yolo go`,
  L4-CLI-001 and L4-MCP-003 name the new command and tool. Release 0.4.19.
