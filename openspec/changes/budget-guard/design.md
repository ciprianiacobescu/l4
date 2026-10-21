## Context

`proposal.md` describes the incident. This change makes a time budget that cannot hold one step a configuration error
that a person sees before any unit runs, names a budget that shortens the job, and makes the deadline texts name the
fix of the budget's real source. It is built for 0.4.20 on top of the released 0.4.19 (b80404db).

Labels: [V] verified in the code or tests at b80404db (file:line); [I] inferred; [U] unknown, not checked here. The
incident's own facts (the consumer's configuration and workflow, the two stops, the halt) come from the report of
2026-10-20, which the owner verified; this design does not re-read that repository.

How the incident happens in the code [V]:
- `job_budget_s` (`src/l4/orchestrator.py:1819-1827`) returns `duration_seconds(ci.time_budget)` whenever it is not
  `auto`, and reads `CI_JOB_TIMEOUT` and `L4_JOB_TIMEOUT_MINUTES` only for `auto`. 21m gives 1260 s; `job_remaining_s`
  (`:1853-1862`) takes away the 1200 s margin: 60 s usable for the whole job.
- `check_before` (`src/l4/deadline.py:177-186`) starts the first step of a run whenever any time is left, and defers any
  later step whose estimate (at least `FLOOR_S = 600`, `deadline.py:17`) exceeds the time left. With 60 s usable no
  step ever fits. The first one starts and is stopped at the deadline.
- `is_counted` (`deadline.py:282-287`) counts a stop of a run's first step. The second such stop halts the unit
  (`_repeated_stop`, `orchestrator.py:443-473`) with a text that always says `raise timeout-minutes and
  L4_JOB_TIMEOUT_MINUTES or split the task` (`:460-464`).
- [I] With the job's start known (`L4_JOB_STARTED_AT`), the first check usually finds no time left at all (checkout,
  setup and doctor take more than a minute). The run then hands back with no continuation and no plan next run
  (L4-IMP-070): the plan is stuck instead of halted. The same check (D2) catches both.
- The harness's own GitHub live test used the same value on purpose, to see the check between units: "With
  `time_budget: 21m` and a 20 m margin, the second unit waited" (`docs/live/github/README.md:71`) [V]. That record is
  history and stays; [I] it may be where the value was copied from. No fixture or simulation configuration under
  `tests/` or `src/l4/sim` sets a `ci.time_budget` at all [V: `grep -rn time_budget tests/fixtures src/l4/sim`], so
  the refusal of D2 breaks no existing world.

## Goals / Non-goals

Goals: a budget that cannot hold one step is refused, by name, before any unit runs, in `l4 doctor`, `l4 run` and
`l4 upgrade`. A budget that shortens the job is named. A halt or a no-step-fitted warning names the fix of the source
the budget really came from.

Non-goals:
- A configuration load error. It would stop `l4 status`, `l4 upgrade` and every other command on the old
  configuration, and `l4 upgrade` is how a consumer moves (D2).
- The same check for `auto` with a job timeout below margin + 10 minutes (for example `timeout-minutes: 25`). It is the
  same failure, but the brief scopes this change to an explicit `ci.time_budget`; listed in the follow-ups.
- A new configuration key, or a change to the floor, the margin or the estimate of run-continuation.
- `l4 yolo status`'s reading of `run.started.job_timeout_s` (L4-IMP-073). With a set `ci.time_budget` that value is the
  budget, not the job's timeout; a run older than its budget has passed its own soft deadline, so calling it ended is
  not wrong [I]. Unchanged.

## D1. One reading of the budget (`src/l4/ci/budget.py`)

Doctor, `l4 run`, `l4 upgrade` and the two deadline texts need the same facts: the budget, where it came from, the job's
own timeout, and the two texts. Today the budget is read only in `orchestrator.py` (`job_budget_s`, `:1819`). The doctor
must not import `orchestrator` (it is the run's whole import graph; doctor `--ci` has the `< 30 s` bound of
L4-NFR-001) [I]. So a new module holds them, imports only `l4.config.schema` (`duration_seconds`), `l4.deadline`
(`FLOOR_S`), `l4.fsutil` (`read_regular_file`, `reject_symlinks`, `UnsafeFile`) and `l4.ci.github` (`WORKFLOW_RELPATH`,
which `checks_config.py` imports already, `:17`) [V]. `l4.deadline` stays a leaf: the new module imports it, never the
reverse.

`orchestrator.job_budget_s` keeps its name and signature and returns `job_budget(cfg, environ).seconds` (or None), so
`tests/unit/orchestrator/test_soft_deadline.py:202-207` and every caller are unchanged [V]. The functions take the
configuration duck-typed (`cfg.ci.time_budget`, `cfg.ci.soft_deadline_margin`), because those tests pass a
`SimpleNamespace` (`test_soft_deadline.py:20-23`) [V].

## D2. A budget below one step: a doctor error and a refusal of `l4 run` (L4-IMP-076)

Decision:
- The rule: `ci.time_budget` is not `auto`, and `duration_seconds(time_budget) − duration_seconds(margin) < FLOOR_S`.
  Equal to the floor passes (10 minutes is one estimate).
- The text: `ci.time_budget <budget> minus soft_deadline_margin <margin> leaves <N> min, less than one step (10 min):
  set ci.time_budget: auto (the job timeout) or raise it`. `<budget>` and `<margin>` are the configured strings (`21m`,
  `20m`); `<N>` is `usable_s // 60`, and `leaves no time` replaces `leaves <N> min` when `usable_s <= 0`. `10 min` is
  `FLOOR_S // 60`.
- Doctor `CFG-012` fails with it as an error (D4): `l4 doctor` exits 3 [V: `registry.py:159,167`].
- `l4 run` refuses with `L4Exit(ExitCode.USAGE_ERROR, text)` (exit 2) right after `preflight_run_config(app, cfg)`
  (`orchestrator.py:1655`) and before `require_framework`, `refresh_refs`, `discover`, the follow-ups (`:1664`) and the
  plan step (`yolo_step`, `:1670`) [V]. Nothing is leased, written, recorded or dispatched. Exit 2 is `usage_error`,
  "Bad arguments or invalid config" (SPEC §2.2), like every other refusal of `preflight_run_config`.
- Not inside `preflight_run_config`: that function is also called by `l4 verify` (`verifier/ladder.py:1621`), the dry
  run (`sim/dryrun.py:268`) and once per unit (`orchestrator.py:1540`) [V]. `l4 verify` arms no deadline
  (run-continuation D2), and the per-unit call would refuse after the plan step had run.
- Not at configuration load: `l4 upgrade` loads the configuration strictly ("it must load as it is",
  `upgrade.py:212`) and so does `l4 status` (`state/status.py:687`) [V]. A load error would stop both on exactly the
  configuration a person needs to look at and fix.
- `run_units`, the check between units and `l4 run --dry-run` (`:1641-1644`) are unchanged.
  `test_soft_deadline.py:94` calls `run_units` with `ci.time_budget: 10m` to test a negative soft time [V]; the refusal
  sits in `run_command`, so that test keeps passing.

Why a refusal and not a run that warns and goes on: the run would start the first step, stop it, and halt the unit on
the second run, which is the incident. A red job that names the key is the cheaper outcome.

Consequence in CI [V]: both GitHub templates run `l4 doctor --ci` before `l4 plan --sweep` and `l4 run`
(`l4.github-action.yml:60-67`), and the GitLab template does the same (`l4.gitlab-ci.yml:42-44`). `l4 ci map-exit`
makes 3 a failure: exit 1 on GitHub, the code itself on GitLab, where only 10 to 13 are allowed failures (`map_exit`,
`exitcodes.py:99-123`; `CI_ALLOWED`, `:38`). So such a job fails at the doctor step, and the run's refusal is the
backstop for a person's `l4 run` and for a workflow without the doctor step.

## D3. A budget that shortens the job (L4-IMP-077)

Decision:
- The rule: `ci.time_budget` is not `auto`, the job's timeout `T` is known, and `T − budget > margin` (all in seconds).
  A set budget a little under the job's timeout (to leave room for the steps after `l4 run`) is not warned; one shorter
  by more than the margin moves the soft deadline earlier than the margin alone would.
- The job's timeout, in order: GitLab's `CI_JOB_TIMEOUT` (digits, seconds), else `L4_JOB_TIMEOUT_MINUTES` (digits,
  minutes), the same variables and order as `job_budget_s` reads for `auto` [V: `:1825-1827`]; else the first line
  matching `^\s*timeout-minutes:\s*(\d+)\s*$` of the checked-out `.github/workflows/l4.yml`, read with
  `reject_symlinks` and `read_regular_file(limit=1 MiB)`; any read error, a link, or no match gives no timeout. The
  source label is the variable's name, or `.github/workflows/l4.yml timeout-minutes`. The file is the fallback because
  `l4 doctor` on a person's machine and `l4 upgrade` have no job variables; the generated workflows write
  `timeout-minutes: 180` (`ci/github.py:22`, `templates/l4.github*.yml`) [V]. GitLab outside a job: unknown (the
  template's `timeout: 180m` can be capped by the runner) [I], so no warning.
- The text: `ci.time_budget <budget> is shorter than the job's timeout (<T> min, <source>) by more than
  soft_deadline_margin <margin>: the soft deadline comes at minute <D>, not at minute <J>; set ci.time_budget: auto (the
  job timeout) unless the job must stop early`, with `<T> = T // 60`, `<D> = max(0, budget − margin) // 60`, `<J> =
  (T − margin) // 60`. For the incident: `(180 min, L4_JOB_TIMEOUT_MINUTES)`, minute 1, not minute 160.
- Doctor: `CFG-012` fails with severity `warn` (D4). `l4 run`: one `log.warning` at the check of D2, then it goes on;
  when D2 refuses, only the refusal's text is printed.

## D4. One doctor row: `CFG-012`

`register(Check("CFG-012", "The soft deadline leaves room for a step", "error", _cfg_012, CONFIG_SCOPES))` in
`src/l4/doctor/checks_config.py`. `CONFIG_SCOPES` (`ci`, `local`, `config`) makes it run in `l4 doctor`, `--ci` and
`--adoption --no-gates` (a laptop before the first push) [V: `registry.py:27`]. One row with a result severity, as
ENV-004 does (`CheckResult.severity`, `registry.py:56`; the report takes `result.severity or severity`, `:159`) [V]:
- error only: `CheckResult("fail", error_text, FIX)`;
- warning only: `CheckResult("fail", warning_text, FIX, severity="warn")`;
- both: `CheckResult("fail", f"{error_text}; {warning_text}", FIX)` (an error);
- neither: `pass` with `ci.time_budget is auto: the job's timeout is the budget`, or `ci.time_budget <b> leaves <N> min
  after soft_deadline_margin <m>`.
`FIX` = `set ci.time_budget: auto (the job timeout), or a duration at least soft_deadline_margin plus 10m`. The job's
timeout of D3 reads `ctx.env` and `ctx.repo` (`doctor/context.py:25-28`) [V].

Why one id: it is one concern (the budget against the step floor and the job), and the incident needs both texts on one
line.

## D5. The texts name the budget's source (L4-IMP-078)

Decision:
- `Budget(seconds, source)` with `source` one of `ci.time_budget`, `CI_JOB_TIMEOUT`, `L4_JOB_TIMEOUT_MINUTES`, read in
  the order of `job_budget_s` [V: `:1822-1827`].
- `raise_fix(source)`: `raise ci.time_budget (or set it to auto)`; `raise the job's timeout (CI_JOB_TIMEOUT)`; `raise
  timeout-minutes and L4_JOB_TIMEOUT_MINUTES` for `L4_JOB_TIMEOUT_MINUTES` and for None. None cannot happen in a real
  hand-back (no budget, no deadline), but the function-level tests of `continue_left_units` call it without one
  (`test_continuation.py:153-163`) [V].
- `_repeated_stop` (`orchestrator.py:460-464`): `f"{where} does not fit in one job: {raise_fix(source)} or split the
  task, then l4 retry …"`. For `L4_JOB_TIMEOUT_MINUTES` the text is byte-identical to today, so
  `test_step_deadline.py:510-514` and the 600-character cap (`_halt(…, cap=600)`, `:473`) keep holding [V]. The source
  is `job_budget(self.cfg, self.services.app.environ)` (the orchestrator reads the same environ for the deadline,
  `:1060-1063`) [V].
- The no-step-fitted warning (`continue_left_units`, `:1798-1803`): `"%sno step fitted before the soft deadline (%.0f s
  left at the first step); {raise_fix(source)}, or split the task"`. Today it ends `raise timeout-minutes and
  L4_JOB_TIMEOUT_MINUTES or ci.time_budget, or split the task` for every source; the job form now drops `or
  ci.time_budget`. `test_continuation.py:163` asserts the old tail and changes with this task [V].
- `run.started` records `job_budget_source` beside `job_timeout_s` (`_job_facts`, `:1842-1850`, through
  `LedgerWriter.open`, `:1572`) [V], only when a budget is known. It tells a person reading the ledger where the
  budget came from; no reader depends on it.
- SPEC L4-IMP-070 and L4-IMP-071 say "the fix for the budget's source (L4-IMP-078)" where they said "the job timeout to
  raise"; L4-IMP-066 lists `job_budget_source`.

## D6. `l4 upgrade` prints the problems (L4-IMP-079)

Decision:
- `plan_upgrade` (`upgrade.py:190`) adds the lines to `UpgradePlan.notes` once, after the delivery's own plan is built,
  for all three deliveries. Today only `_plan_action` adds notes, and only when the workflow changed (`:340-347`) [V];
  the budget lines must not depend on that.
- The job's timeout is the `timeout-minutes` of the workflow the upgrade leaves: the planned `.github/workflows/l4.yml`
  bytes when the plan writes that file, else the file on disk, through the same parser as D3. The environment that
  runs `l4 upgrade` is not read: it is a person's shell or another job, not the consumer's `l4` job.
- The lines: `error: <D2 text>; until it is fixed, l4 run exits 2 and doctor CFG-012 fails`, and `warning: <D3 text>`.
  `run_upgrade` prints the notes after the files (`:518-519`) [V]; the lines do not contain `re-rendered`, which that
  loop rewrites for `--dry-run`.
- They change no file (the configuration is the person's) and the exit code stays 0: the upgrade did what it was asked,
  and refusing would block a pin move that is unrelated to the budget.

## D7. Docs, SPEC, CHANGELOG

- `docs/SPEC.md`: L4-IMP-076 to L4-IMP-079 after L4-IMP-075; SCN-IMP-385 to SCN-IMP-395 after SCN-IMP-384, before
  `### 23.8`; the texts of L4-IMP-066, L4-IMP-070 and L4-IMP-071 (D5); the `CFG-012` row after `CFG-011` in the doctor
  table; the §3.2 comment of `time_budget`; §12.1 (`job_budget_source`); change-table row 58. Row 57 is `pin-clis`, on
  its own branch, and is absent here; the table already has gaps (49, 52) [V].
- `docs/runbook.md`, the soft deadline section: the two lines that say `raise timeout-minutes and
  L4_JOB_TIMEOUT_MINUTES (or ci.time_budget)` name the fix by source, and one new bullet says what `CFG-012` and the
  refusal mean and what to set. The line that starts ``- The soft deadline is `ci.time_budget` `` stays word for word:
  `tests/unit/docs/test_run_continuation_docs.py:69` splits the runbook on it [V].
- Skill `plugins/l4/skills/l4/references/operate.md`, the error table: the `deadline_repeated` row names both fixes, and
  two rows are added (`… leaves N min, less than one step (10 min)` and `… is shorter than the job's timeout`).
- `CHANGELOG.md`: `## 0.4.20 (unreleased)` above `## 0.4.19 (2026-10-20)`, with `### Added`, `### Changed` and
  `### Fixed` (the lines are in `tasks.md`). `pin-clis` adds the same heading with `### Added` and `### Changed`;
  whoever merges second keeps one heading and merges the lists under the same subheadings.

## Contracts (the tasks share these; do not change one without the orchestrator)

- `l4.ci.budget`:
  - `BudgetSource = Literal["ci.time_budget", "CI_JOB_TIMEOUT", "L4_JOB_TIMEOUT_MINUTES"]`;
    `WORKFLOW_SOURCE = ".github/workflows/l4.yml timeout-minutes"`.
  - `@dataclass(frozen=True) class Budget: seconds: int; source: BudgetSource`.
  - `job_budget(cfg, environ) -> Budget | None` (D5 order).
  - `workflow_timeout_s(text: str) -> int | None` (D3 regex, minutes × 60).
  - `read_workflow(repo: Path) -> str | None` (D3 file rules).
  - `job_timeout(environ, workflow_text: str | None) -> tuple[int, str] | None` (seconds, source label; D3 order).
  - `too_short(cfg) -> str | None` (the D2 text), `shortens_job(cfg, timeout: tuple[int, str] | None) -> str | None`
    (the D3 text), `raise_fix(source: BudgetSource | None) -> str` (D5).
  - `upgrade_notes(cfg, workflow_text: str | None) -> tuple[str, ...]` (D6, the `error:` and `warning:` lines).
- `orchestrator.job_budget_s(cfg, environ) -> int | None` unchanged in name and result.
- Doctor: `CFG-012`, title `The soft deadline leaves room for a step`, severity `error`, `CONFIG_SCOPES`, `FIX` of D4.
- Ledger: `run.started` + `job_budget_source?: BudgetSource`.
- Texts: D2, D3, D5 and D6, word for word.

## Collisions

- `pin-clis` (0.4.20, another branch): `## 0.4.20 (unreleased)` in CHANGELOG, change-table row 57, doctor `ENV-015`
  (another row), and the same edit of `tests/unit/docs/test_yolo_guardrails_docs.py:25` (from `assert "## 0.4.20
  (unreleased)" not in changelog` to `assert changelog.index("## 0.4.20 (unreleased)") < changelog.index("## 0.4.19
  (")`). This change makes the identical edit, so the hunks are the same. `test_doctor_cli.py`'s list of registered ids
  gets `ENV-015` there and `CFG-012` here: adjacent lines, merged by hand. Ids do not overlap (pin-clis uses L4-PRV-*,
  L4-OCG-*, SCN-PRV-*, SCN-OCG-*) [V: `git diff b80404db pin-clis -- docs/SPEC.md`].
- `delegate-answers` (another branch) reads `job_remaining_s`; its result is unchanged.
- No other branch defines `CFG-012`, L4-IMP-076 to L4-IMP-079 or SCN-IMP-385 and up [V: every local branch's SPEC].

## Risks

- A consumer with such a configuration gets a red job at the doctor step after it moves to 0.4.20, where it had a halted
  unit on 0.4.19 (and "one unit per run" before). That is the purpose; the CHANGELOG says so under Changed, with the
  fix.
- A person who wants a short budget on purpose still can: any budget at least the margin plus 10 minutes passes, and a
  smaller margin is the operator's risk (L4-IMP-068).
- The workflow-file fallback reads the first `timeout-minutes:` line. A hand-written workflow with several jobs may name
  another job's timeout [I]; the generated workflows have one job [V: `l4.github.yml:27`, `l4.github-action.yml:29`].
  The worst case is a wrong warning, never a refusal (D2 does not read the job's timeout).

## Out of scope / follow-ups

- The same refusal for `auto` with a known job timeout below the margin plus 10 minutes (the job's timeout is then the
  budget, and the fix is `timeout-minutes`).
- `l4 yolo status` (L4-IMP-073) could use `job_budget_source` to tell a run's budget from its job's timeout.
- The budget lines in `l4 init` (an adoption that starts with such a value).

## Open questions (each with the recommended answer)

Every recommended answer below is taken (the owner's rule: the decision is in this design, the requirement and a
scenario).

1. A load error, a doctor error, or both? Taken: a doctor error and a refusal of `l4 run` (D2, L4-IMP-076,
   SCN-IMP-385, SCN-IMP-386); the configuration still loads (SCN-IMP-387).
2. What does `l4 run` do? Taken: refuse with the text and exit 2 before the follow-ups, the plan step and any unit
   (D2, SCN-IMP-386).
3. Only an explicit `ci.time_budget`, or every source? Taken: explicit only, as the brief words it (Non-goals,
   follow-ups).
4. Where does the job's timeout come from outside a job? Taken: the job variables, else the checked-out workflow's
   `timeout-minutes` (D3, L4-IMP-077, SCN-IMP-389); `l4 upgrade` reads only the workflow (D6, SCN-IMP-395).
5. One doctor id or two? Taken: one, `CFG-012`, with a result severity (D4, SCN-IMP-390).
6. Record the budget's source? Taken: `run.started.job_budget_source` (D5, L4-IMP-078, SCN-IMP-393).
7. Does `l4 upgrade` refuse? Taken: no, it prints and exits 0 (D6, L4-IMP-079, SCN-IMP-394).
