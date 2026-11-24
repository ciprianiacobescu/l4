## Context

Read at 0.4.60 (663cd6d5). Every claim of the stream brief was re-checked; the three line numbers that differ are marked.

- `src/l4/config/schema.py:216` `UnitGate.targeted: str = ""`; `docs/SPEC.md:800` documents it as `{files}` / `{grep}` for
  "red/green runs". No code reads it (`grep -rn "\.targeted" src` is empty). `schema.py:168` `TddCfg`, 207-217 `UnitGate`.
  `L4Config` is `extra: forbid` (`_Strict`), and a custom validator raises `ValueFree` so that a message never holds a
  configured value (`schema.py:53`).
- `src/l4/implementer/tdd.py:1634` `run_red`. Its order: `baseline` (1637), the agent step (1650), `enforce_red_scope`
  (1657), `ProductionGuard` (1658), `changed = wb.changed_files()` (1698), `reset = tree_before(wb)` (1700), the gate
  `test` (1701), `tampered("test run")` (1702), `report = gate.report` (1707), `new_ids` (1708), `named_tracing` (1715),
  `unchanged_on_base` (1726), `passing_now`, `confirmed_by_earlier_red` and `check_criteria` (1759-1790), the pre-satisfied confirmation and base
  run (1796-1815), `judge` and its re-run (1997-2018), the vacuity check (2039), the commit with `task.red_ok` (2102).
  The brief says the gate is at 1701: confirmed.
- `baseline` (775) raises `BaselineFailed` for a base report with a collection error (786-788). So the base report of a
  red step never has one. The eligibility rule keeps the check anyway: it is redundant today.
- `RedOutcome` (290) carries `base_report`, `new_ids`, `manifest`, `criteria`. It carries no red report. `run_green`
  judges with `red.base_report` (2289 and 2301: the brief says 2288) through `green_failures` (613). `resume_red` (2142)
  rebuilds the base report from a new full run of the red checkpoint, with the new ids taken out.
- `stubs.py:877` `enforce_red_scope`: a changed path that is a test, a support file, a runner configuration, a lock
  file, the ledger or protected is exempt (`_exempt`, 846); any other path that is not Python is put back
  (`stubs.py:893-899`), and a Python production file keeps only additions that are stubs. `RedScope` has `stub_files`,
  `stubs`, `restored`. In a TypeScript repository red therefore keeps no production file. Confirmed.
- `recheck.py:139` overlays the cases of the flaky tests on run 1's report and nothing else: it keeps run 1's
  collection errors. The brief says it "merges test reports": it merges the `tests` mapping only.
- `gates/runner.py:119` `run_gate`: `shlex.split(spec.command)`, no shell (an argument is one argv item whatever it
  holds); the listed reports are removed before the run (a report from an earlier run cannot pass for this one); a
  listed report that is missing afterwards fails the run with `report missing: <path>`, but a report that was read is
  returned whatever the exit code (`run_red` expects a failing gate).
- `workbench.py:446` `run_gate` emits `gate.finished{name, ...}` for every gate. Readers of the name: `progress.py`
  (the log line, `red_new_failing`), `orchestrator.py:261` (idle detection, any name), `delegate/prompt.py:524` (the
  newest failing gate's excerpt, any name). `_count_gate_run` (`workbench.py:469`) counts only the names `baseline`
  and `test` (L4-IMP-099): the new name `test-targeted` is not counted, and an idle floor is only ever a maximum.
- `implementer/test_locate.py:30` `file_of_id(test_id, paths, preferred)` maps a report id to one of the repository's
  paths (a path, a dotted path, a dotted Python module, a path's end), and gives None when it cannot or when several
  paths fit and `preferred` does not choose.
- `verifier/support_base.py:110` `is_support_file(git, cfg, path, rev)`: a path of `tdd.test_support_globs`, a `.py`
  file that defines no test at `rev`, or another language's file whose name does not look like a test module.

The state at the red commit: the step's new test files are committed and frozen for green (`build_manifest`), green's
gate is the whole suite, and verification runs the whole suite again (steps 1 and 3).

## Goals / Non-Goals

**Goals:** a red step that only adds test modules runs only those modules, judges them as it does today, and says in the
ledger what it ran and why. Anything the targeted run cannot decide runs the whole suite in the same step. A regression
that the targeted red let through is seen at green, recorded, and ends the unit's targeted reds.

**Non-Goals:** a targeted green or verification (both stay whole-suite); a path that redoes red after green finds that
the red tests broke an old test (see D7: it is loud, and `l4 restart` is the way out); the `{grep}` placeholder; a
doctor check (see D1); selecting tests by name; a Python step that adds a stub.

## Decisions

### D1. The key (L4-CFG-007)

`gates.test.red_check: Literal["full", "targeted"] = "full"`, on `UnitGate` next to `targeted`. It sits under
`gates.test` and not under `tdd` because its only input is the targeted command of the same section, so the load rule
is a validator of one model and needs no look at another section. `tdd.mode` decides whether red exists; this key
decides how red's test run is made.

`UnitGate` gets a `model_validator(mode="after")`. When `red_check == "targeted"`, `targeted` must: split with
`shlex.split`; hold exactly one word equal to `{files}`; hold no word that contains `{grep}` or `{files}` with other
text around it (`--include={files}` is refused: the placeholder expands to several arguments). Each failure raises
`ValueFree` with a fixed text that names `gates.test.red_check` and `gates.test.targeted` and never the command. With
`full` the `targeted` string is not checked: a 0.4.60 configuration that sets `targeted` as a comment-like value still
loads.

It is a load error and not a doctor check. A wrong `targeted` would otherwise fall back on every step, so the setting
would cost time and give nothing, and the fallback is silent in the run log. Load errors exit 2 in every command
(L4-CFG-004 rules the rest of the file). A doctor row for the command's report path was considered and left out: it
needs an unallocated doctor id and a heuristic.

Default `full`. The key is off by default because a targeted red moves where a test that the new files break becomes
visible, from red to green or to verification (D7), and that can change when a unit fails.

### D2. Eligibility (L4-IMP-117)

A new module `src/l4/implementer/red_check.py`. `choose(wb, task, base, scope, changed, listed, stale, base_report)`
returns `Targeted(files)` or `Full(why, detail)`. `run_red` calls it after `enforce_red_scope` and the production
guard are set, before the gate, with `changed = changed_paths(wb.git, base, excludes=wb.excludes)` (path to "existed at
the base"; `wb.changed_files()` has no status). It reads no model output and no clock. With
`gates.test.red_check == "full"` it is not called and nothing is recorded.

The first rule that fails gives `why`:

1. `unit_switched`: the unit's ledger holds `task.red_check_disabled` (D7).
2. `named_tests`: `listed.tests` or `listed.other` is not empty (the task names an existing test red may change).
3. `stale_tests`: `stale` is not None (a reopened task's old tests).
4. `base_collection_errors`: the base report has a collection error (redundant, see Context).
5. `stubs`: `scope.stub_files` or `scope.stubs` is not empty.
6. `restored`: `scope.restored` is not empty (red scope put something back: the step is not "only test files").
7. `existing_file_changed`: a changed path existed at the base (a modified or deleted file). The paths left out of the
   count are `wb.ledger_rel` and what `ProductionGuard._production` ignores (`__pycache__`, `.pytest_cache`,
   `.mypy_cache` and `.ruff_cache` entries and `.pyc` files).
8. `not_a_test_module`: a changed path is not a test module (below).
9. `no_test_file`: no changed path is left.
10. `too_many_files`: more than 50 paths, or paths longer than 8,000 bytes together.
11. `odd_path`: a path starts with `-` or holds a control character.

A **test module** is a path that matches a glob of `tdd.test_globs`, matches no glob of `tdd.test_support_globs` or
`tdd.runner_config_files`, and is no support file by the verifier's rule applied to the file in the work tree: for a
`.py` file the rule `is_support_file` uses (the file defines a test, by `tamper.facts_of`), for any other file a name
that looks like a test module (`_TESTISH`: `test_*`, `*_test.*`, `*.test.*`, `*.spec.*`). `is_support_file` takes a git
revision, and red has not committed. The implementer factors its body into `is_support_source(cfg, path, source)` and
keeps `is_support_file` as a wrapper, so there is one rule.

Python gets the same rules and no other. A Python red step normally adds stubs for the code it tests (`stubs.py`
keeps additive stub definitions in production `.py` files), so rule 5 sends most of them to the whole suite. A Python
step that adds only test modules is eligible, and a test that then passes falls back by D4. No language switch is
needed and none is added: a switch would only hide the rules.

Fail-safe: every rule can only send a step to the whole suite, which is today's check.

### D3. The targeted run (L4-GAT-007)

`red_check.targeted_command(template, files)`: `shlex.split(template)`, the one word `{files}` replaced by the files,
`shlex.join`. `run_gate` splits the result again, so each path is exactly one argv item: nothing in a path (a space, a
quote, `$`) is read by a shell, because no shell runs. Files are repository-relative POSIX paths, as git lists them,
sorted by their text. No `./` prefix (D2 refuses a path that starts with `-`, so an option cannot be injected).

The gate is `wb.run_gate("test-targeted", <that command>, reports=wb.cfg.gates.test.reports,
note=red_note(base_report))`, in the same sandbox, with the same environment (the trace plugin, `gates.timeout`) as the
gate `test`. The report paths are the gate's own: the runner removes them before the run and reads them after, so a
targeted command must write every report that `gates.test.reports` lists, in `gates.test.format`. When several reports
are listed the runner merges them, as for the whole suite, and a missing one is `report missing`, which D4 sends to the
whole suite. Nothing is published: red's report is not kept (`keep_tested` is green's).

After the run the step calls `tampered("targeted test run")`, the same production guard as after the whole run. A
`DeadlineReached` passes through as for any gate. A targeted run that timed out is not retried on the whole suite: it
fails the attempt with the reason of today's `no readable report` (`... timed out after <n>s`), since a new test that
hangs is red's to fix and a second, longer run would only repeat it.

### D4. When the targeted run is usable, and the fallback (L4-GAT-009)

`red_check.unusable(base_report, targeted, files, paths) -> tuple[str, str] | None` gives `(why, detail)` or None. The
run is usable only when all of these hold, checked in this order:

1. a report was read (`no_report`: the command wrote none, a report is missing or unreadable);
2. the report has no collection error (`collection_errors`);
3. no id of the report is an id of the base report (`existing_tests_ran`: a filter that matched an old file, or a
   command that ignored `{files}` and ran everything);
4. every file of the list owns at least one id and every id belongs to a file of the list, by `file_of_id(id, paths,
   preferred=files)` with `paths` the tracked paths plus the files (`file_without_tests`: the runner did not collect
   the file; `id_without_file`: an id the rule cannot place in a listed file, which also catches a targeted command
   that names tests unlike the whole suite does, see D5);
5. every id fails or errors (`new_test_not_failing`: a new test that passes or is skipped needs the pre-satisfied
   checks of L4-IMP-003, whose variant runs take the whole report).

When it is not usable and the run did not time out, the same step runs the whole suite exactly as today: the step calls
`reset()` (the `tree_before` taken before the targeted run; a False result does not stop the run: the tree then is as
a whole run after an agent step leaves it), runs the gate `test`, and goes on with that report as the step's report.
`tampered("test run")` follows it. The step records `task.red_check_full{why, detail}`. The same applies to the
eligibility reasons of D2, which run the whole suite without a targeted run.

Time. The fallback adds the whole run to the targeted one. `deadline.cap_s` (agent limit plus one `gates.timeout`) is
an estimate, not a limit: the soft deadline stops every gate through `DeadlineReached`, and `step.timed` records the
longer step. A targeted run that completes is as long as the new files, normally seconds. A repository whose targeted
command always falls back pays those seconds on every red step, and `task.red_check_full` makes it visible.

Why rule 3 is strict and not "overlay whatever ran": a targeted run that also ran old tests has no use for a rule that
trusts which ones, and the whole suite is exactly what the step wanted to avoid only when the new files are alone.
With rule 3 the two reports are disjoint, so the report of D5 has no conflict to resolve.

### D5. The report the red checks judge (L4-GAT-008, L4-IMP-119)

`red_check.with_targeted(base, targeted) -> TestReport`: `tests = {**base.tests, **targeted.tests}` (disjoint by D4
rule 3), `collection_errors = []` (rule 2 and the base's own: none), `collection_details = {}`. It is local to
`run_red`: `report` is bound to it, and the targeted gate's own report is used only by D4. `RedOutcome.base_report`
stays the measured baseline. Each reader of `report` in `run_red` and what it sees:

| Reader (663cd6d5) | Sees |
|---|---|
| `new_test_ids` (1708), `check_criteria` (1764), `over_cap_text` (1780), `no_assertion_failure`, `fails_on_zero` | the new ids and their cases: the targeted run's, as today |
| `classify_red` via `judge` (1997) | `regressed` is empty (no base id is in the targeted report), so `red broke existing tests` and `no new test: existing tests were changed` cannot fire; every other reason is judged on the new tests as today |
| `recheck_step` (2008) | not reached: it needs `verdict.regressed` |
| `named_tracing`, `named_other_changed` | nothing: D2 rule 2 |
| `passing_now` (1759), `unchanged_on_base` (1726), `confirmed_by_earlier_red` (1763, 1789) | the base's status for each old test (the targeted run did not run it), the targeted status for each new one. A full run would show head statuses for the old tests: the difference is exactly what D7 bounds |
| `confirm_pre_satisfied`, `confirmed_by_base_run` (`head_seconds=gate.seconds`), `finish_already_satisfied` | not reached with data: they need a passing new test, and D4 rule 5 sends such a step to the whole suite. So `gate.seconds` never reaches `base_run`'s bound (`BASE_RUN_FLOOR_S`, 300 s, against a short run) |
| `vacuity_check(real=report)` (2039) | runs the whole command with zeroed code, as today. It compares only the new tests with `real` and the collection errors, which the overlay holds |
| `RedOutcome` (2112) and `task.red_ok` | `base_report` (the baseline), `new_ids`, `manifest`, `criteria`: as today |

After red:

- **Green** judges with `red.base_report`, so its regressed set, its `red tests still failing` and its `new failing
  tests added` read the baseline and the whole-suite run of green itself.
- **The near-pass carry** (`_near_pass`) reads the work tree and the static gate text, not a report.
- **Verification** reads `task.red_ok` (`tests`, `frozen`, `criteria`, `notes`), the red commit, and runs steps 1 and 3
  on the whole suite.
- **The next task's baseline** (`reused_baseline`) reuses green's report (`keep_tested`), never red's.

Id stability. A targeted command that names the new tests differently from the whole suite (for example a runner that
prefixes ids with a project name only when a project filter is on) gives ids that green's whole run does not hold, so
green fails with `red tests still failing: <ids>` on every attempt, and the frozen tests cannot change. D4 rule 4
catches an id that does not map to a listed file, which is the common form. For the rest, D7 detects it at green's
first attempt, records it, and the reason of D7 tells the person. There is no redo-red path (non-goal), so the way out
is a person's answer to a question that names the test file, or `l4 restart`.

### D6. Ledger and log (L4-IMP-120)

- `gate.finished{name: "test-targeted"}` with the notes `gate.finished` has for any gate (`red_new_failing`,
  `collection_errors`, `excerpt`). The progress log shows `gate test-targeted fail (...)` and the usual `red: N new
  tests fail, as intended`.
- `task.red_ok` gains `check` (`full` or `targeted`) and, for `targeted`, `files` (at most 50). `task.red_ok` of an
  already-satisfied task is written by a step that D4 made whole-suite, so it has `check: full`. A configuration of
  `full` writes neither key: a ledger of 0.4.60 and a ledger of a `full` configuration are the same.
- `task.red_check_full{task, attempt, why, detail}`, when `red_check` is `targeted` and the step ran the whole suite.
  `why` is a word of D2 or D4; `detail` is at most 300 characters (at most five paths or ids). Not written for `full`.
- `RedOutcome.check` (`"full"` default): set by `run_red`, and by `resume_red` from the event it reads. `run_green`
  reads it, so green decides from the red commit's own record, also in a later job.
- The CI step summary and `l4 status` keep their text. `progress._red_ok` may add `(check: targeted, N files)` to its
  line.

### D7. A regression after a targeted red (L4-IMP-121, L4-IMP-122)

A targeted red can miss one thing: a new test file that breaks an old test by interaction (a shared database, a port, a
module-level mock, a snapshot directory). Green's whole run then shows an old, base-passing test failing. Green cannot
fix it: the red files are frozen. So the harness must say what happened, loudly, and stop doing it.

In `run_green`, after the step's own re-run (2292-2301), when `why.regressed` is not empty, or when `why[0]` starts
with `red tests still failing` and at least one of its ids is missing from `gate.report.tests` (not failing: absent),
and the red of this task has `check: targeted` (`red.check`): the step reads the unit's ledger (`_ledger_events`, the
unit and its fix units share it). If it holds no `task.red_check_disabled`, the step records

`task.red_check_disabled{task, attempt, why: "regressed" | "ids_missing", tests: [...], red_sha}` (at most 20 ids).

Every later `choose` call sees it (D2 rule 1) and runs the whole suite with `task.red_check_full{why:
"unit_switched"}`. It stays for the life of the unit and its fix units: `l4 retry` and `l4 resume` keep the ledger, so
they keep the switch. `l4 restart` starts the unit over on a new branch with a new ledger (`state/restart.py` step 4),
so a restarted unit reads the key again: that is the way out for a task stuck as below, and a person can also set the
key back to `full`.

The regressed test must be one that "was not new and passed in the base report": that is exactly what `green_failures`
puts in `regressed` (`base.ids_with("passed")`, minus the superseded ones). Whether it was the red files or green's own
code that broke it is not decided here: both give the same cheap, safe action (later reds run whole). A green regression
is much more often green's own code, and then the switch costs only the saving.

The reason. When the red of the task was targeted and the attempt fails with a regressed set or an id missing, the
reason gets one suffix after the existing ones (`; failed again on a re-run (L4-IMP-105): ...`): `; the red step of
this task ran only its new test files (L4-IMP-122): if no change of the code can make these tests pass, report status
blocked with a question that names the test file`. A person's answer to such a question unfreezes the named file for
green (L4-IMP-015), which is the way out for the task; `l4 restart` is the way out of a unit whose agent never asks.
The text is only a reason: the structured `regressed` marker of L4-IMP-105 is not parsed
from it. The attempt fails as today, so the loss is bounded by `implementer.max_task_attempts` and the unit's
escalation, and it is never silent: the reason, the escalation text and the event name the cause.

Why green only, and not a chore: a fix, tests or refactor chore has no red step of its own in the task, and its
regressions are its own. Why not a redo of red: a red commit is frozen state that verification and the criteria proofs
read; redoing it is a new feature with its own spec.

### D8. Upgrade and old ledgers

A 0.4.60 ledger has no `check`, `task.red_check_full` or `task.red_check_disabled`. Every reader treats a missing
`check` as `full` and a missing event as no switch. A unit in flight when the pin moves keeps its earlier reds as
`full`; with `targeted` set, its next red step decides by D2. 0.4.60 cannot load the key (`extra: forbid`), so a
consumer moves the pin first, then sets the key, and removes it before it moves the pin back. A harness that does not
know the events ignores them (the ledger fold reads unknown types as plain records, as for `task.tests_rechecked`).

### D9. How each requirement fails safe

- **L4-CFG-007**: a bad `targeted` stops the load; it never runs a wrong command.
- **L4-IMP-117**: a rule only ever sends a step to the whole suite, so a doubtful step is judged as today.
- **L4-GAT-007**: no shell reads a path, a path that could be an option is refused, and the run is bounded by
  `gates.timeout`.
- **L4-GAT-009**: a targeted run that is anything but complete is replaced by the whole suite in the same step; a new
  test that does not fail never skips the pre-satisfied proofs.
- **L4-GAT-008, L4-IMP-119**: the overlay keeps each old test's measured baseline status and adds only failing new
  tests, so no wrong test passes red through it: a wrong red is still caught by the kinds, the criteria, the vacuity
  checks and green's own whole-suite run.
- **L4-IMP-118**: the guards (`tampered`) run after each run; green and verification stay whole-suite, so a unit never
  passes on a targeted check alone.
- **L4-IMP-121, L4-IMP-122**: what a targeted red misses ends at green with a recorded cause and a switch, not in
  silence.
- Never a person-only action by an agent: nothing here activates, accepts or answers anything.

## Risks / Trade-offs

- A new test file that breaks an old test by interaction is found at green, not at red, and green cannot repair a
  frozen file. The task burns its attempts with a reason that tells the agent to ask a question that names the file, and
  a person answers it or restarts the unit. This is the price of the saving and the reason the key is off by default.
- A targeted command whose ids differ from the whole suite's fails every green of the unit; D4 rule 4 and D7 limit it
  to the first task. The runbook says to run both commands once and compare ids before the key is set.
- A repository whose targeted command never completes pays a short extra run per red step.
- Old tests are judged at red by their base status, not their head status. That is the saving, and verification and
  green run them.
