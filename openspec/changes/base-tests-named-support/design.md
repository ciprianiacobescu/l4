## Context

Read at 0.4.59 (62188257):

- `src/l4/verifier/base_tests.py:189-206` `kept_files(ctx, paths)`: per path of the revert set, `who =
  _introducers(ctx, path, changed)`; kept when `_by_people(who)`, when `_allowance(ctx, who, path, by_sha)` is not
  None, or when `_last_by_people(who)` and the path is no support file (`is_support_file(..., _rev_of(ctx, path))`).
  `check_base_tests` (273-346) drops the kept paths from the plan (282), lists the kept ones that are not people's as
  `<path> kept at head for the run (<why>)` (283) under `allowed_tests`, runs the gate in `support_at_base` with one
  repeat for a failure (297-302), and builds the blocker detail from `_first_line` (214-215, 150 characters) of each
  failing id (326-328). `_emit` (349-357) writes `verify.base_tests{..., reverted, ...}`.
- `src/l4/verifier/integrity.py:283-300` `_allowance`: every harness commit of `who` must be a `[test-infra]` task's
  or must change a path that `_unfrozen_source` (271-280) finds in the `paths` of a `task.unfrozen` of the same unit
  and task. `check_tests` (379) uses it for pre-existing Python tests (L4-VER-030, L4-VER-031). `commits(ctx)`
  (791-801) gives `Commit(sha, unit, task, tdd, parent)` for the harness commits with an `L4-Task`; `tdd` is the
  `L4-TDD` trailer (`red`, `green`, `exempt`, `already-satisfied`, `already-done`). `_unit_of` (457) gives an event's
  unit.
- `src/l4/implementer/unfreeze.py:81-117` `named_by_task(text, manifest, source=...)`: for each manifest path the
  task's text names (`names_path(text, path, dot_slash=True)`), a red test (`kind == "test"`, not a helper) is kept as
  `a red test of this task`, an ignore file as `an ignore file`, a path red changed as `the red step of this task
  changed it`, a non-Python file as `not a Python file: a person decides`, and so on. Only named paths are listed.
- `src/l4/implementer/tdd.py:2211-2215`: `run_green` records `task.unfrozen{task, paths, reason: "named_by_task",
  source, red_sha, kept: [{path, why}]}` on every green attempt where `named.paths or named.kept`. `source` is
  `plan:<id>@<digest>` or `base:<sha10>` (`named_task_text`, 2457-2480). A fix or follow-up unit has no such text.
- `src/l4/implementer/guards.py:101-106` `build_manifest`: a path of `tdd.test_support_globs` (and the ignore globs)
  is `support`; a path red changed that matches `tdd.test_globs` is `test`. With the defaults
  (`src/l4/config/defaults.py:32-39`) `test/arch/modules.ts` matches `**/test/**` and no support glob: kind `test`.
- `src/l4/verifier/support_base.py:110-120` `is_support_file`: a support glob, a `.py` file that defines no test, or
  another language's file whose name does not match `_TESTISH` (54: `^test_`, `_test.`, `.test.`, `.spec.`).
  `test/arch/modules.ts` is support; `test/arch/repo.test.ts` is not.
- `src/l4/verifier/ladder.py:741-753` `integrity()` runs `run_integrity`, then `check_base_tests` and
  `record_outcome`. A failed step 1 ends the ladder (841-846): step 3 does not run, so `result.failures` stays empty.
- `src/l4/verifier/gates.py:182-230` `failure_records(unit, browser, redact, *, excerpt, collection_excerpt)`: the
  records of L4-VER-069 and L4-VER-078, gate `test` or `e2e`.
- `src/l4/verifier/failures.py:94-106` `shown_failure_ids`: the tests of a finding for the failure block. Only the
  gate titles and `new tests failed`/`errored` name any. `fixunit.py:448` cuts a chore's detail to 600 characters.
- `src/l4/verifier/fixloop.py:559-597` `repeated_failure` gives `round <n> failed the same way as round <m>:
  <set>` (the set cut at 200 characters); the caller (703-704) escalates with it as `same_failure`. Exit reasons are
  cut at 300 characters (`orchestrator.py:1755`).
- `src/l4/verifier/ladder.py:325-335` `_git_diff`: the judge's diff leaves out only the harness's bookkeeping, so a
  changed support file is in it.

## Goals / Non-Goals

**Goals:** a support file whose change the reviewed text of a task asked for does not fail the run of the base's
tests. A base-tests blocker says which files the run reverted and who changed them, and its tests reach the fix task
with their failure text. A repeated base-tests failure escalates with the way out.

**Non-Goals:** added support files, ignore files, test modules, tasks without a reviewed text, a task that finished
as already satisfied, and the general rule for a fix chore that changes nothing. No new event, no configuration key.

## Decisions

### D1. Which file stays at head (L4-VER-079, slippable)

`_named_red_change(ctx, who, path, by_sha) -> str | None` in `base_tests.py`, called by `kept_files` after
`_allowance` and before the people-last rule. It gives `task <t>: changed by its red step, named by its reviewed text
(<source>)`, or None. It holds when all of these hold:

1. `path` is a regular blob at the base and at head. An added file is set aside by the plan anyway, and a deleted one
   is not this case.
2. `path` matches no ignore glob (`guards.IGNORE_FILE_GLOBS`).
3. `is_support_file(ctx.git, ctx.cfg, path, ctx.head_sha)`, the verifier's own rule. The manifest's kind and the
   `why` string are not read: with the default globs the case of the evidence is kind `test` there.
4. `who` holds at least one harness commit, and every harness commit in it maps (`by_sha`) to a `Commit` with
   `tdd == "red"` whose task has a `task.unfrozen` event with `reason == "named_by_task"`, the same unit (`_unit_of`)
   and task, `red_sha == commit.sha`, a non-empty `source`, and the path in `paths` or in a `kept` entry's `path`. A
   person's commit in `who` needs no cover, as in `_allowance`. Matching `red_sha` means an event of an older red
   commit (a task reopened after a spec edit) covers nothing.
5. No test id of the base's test report belongs to `path` (`_in_report`). Jest runs every file under `__tests__/` and
   mocha every file under `test/`, and for a file that is not Python step 1's run is the only guard against a weakened
   test of it; `is_support_file` calls such a file support for its name alone (`src/__tests__/render.ts`,
   `test/arch/repo.ts`, `test/helpers/x.ts`). A test id belongs to a file when its class name is the file's path (with
   or without `./`; Vitest and Playwright write it so), is the file's dotted module or a class of it (a pytest id), or
   is a dotted class name that ends the path without its extension (a JVM or .NET id). `_file_of` is not used: it finds
   only Python and Go test files, and widening it would change `split_allowed`. A file no id maps to, the motivating
   data file with no tests of its own, stays eligible. The base report is step 1's base reference (the workbench
   baseline, an earlier round's evidence or a run at the merge base), fetched through a callable only when a file has
   passed every other condition, so a unit with no such file never runs the merge base for this. With no report
   (the reference gave none) nothing stays: fail closed. The evidence of an earlier round lists only the tests that
   passed at the base, which is enough: a test that failed there guards nothing.
6. `git diff --numstat <base> <head> -- <path>` counts at most `MAX_NAMED_SUPPORT_LINES = 40` added plus deleted
   lines. A binary file (`-` counts) is not kept. A rewrite of a named file is reverted as before. The bound keeps an
   added entry or edge and rules out a replaced file.
7. At most `MAX_NAMED_SUPPORT = 3` paths per (unit, task) are kept this way, in sorted path order (the bound of
   `unfreeze.MAX_PATHS_PER_QUESTION`). A later one is reverted as before, and the row's note says `<n> more support
   file(s) named by task <t> reverted (at most 3 kept)`.

The rule is in `kept_files` only. `_allowance` and `_unfrozen_source` are not changed. They are shared with
`check_tests`, and a file that matches both a test glob and a support glob could otherwise widen L4-VER-030.
`split_allowed` is not changed either: the file is kept, so the tests that read it run against the head version.

The reason string holds no `people`, so `check_base_tests` lists it with the allowances (283), under `## Pre-existing
tests changed with an allowance (L4-VER-031)` of `verification.md`. The `kept_files` docstring changes: a harness
change to a support file is now read by that listing and by the judge, whose diff holds the file (`_git_diff`).

Fail-safe: every condition is checked on git and the ledger at verification time, and each one that does not hold
reverts the file as before. Only the harness writes the ledger event, and only from a text that matched an activated
plan's digest or the base branch. An agent cannot write the event, and the verifier does not trust the agent's
record. A task whose text does not name the path, a commit of another task, a green or fix commit, and an older red
commit all keep the file reverted.

What can still pass that should not: a red step whose change to a named file goes beyond what the text asked, for
example adding a broader exemption than the one asked for, and so masks a regression that the base version would
show. The closest precedent is stricter. When a task's text opens a support file for *green*
(`implementer/opened.py` `check_opened`), green must keep every top-level statement of the red version unchanged and
in order (rule 1), may not bind again a name the red version binds or one pytest reads (rule 2), and may not patch a
symbol of a production module the unit changed (rule 3). Only a Python file can be opened that way: `named_by_task`
keeps any other as `not a Python file: a person decides`. Red's change to a named file gets none of rules 1 and 2. The
other checks of a red change are:
- for a Python support file, L4-VER-037 (rule 3's patch check, on every changed support file) and the content scan
  of L4-VER-039;
- for a file of any language, the listing with task and source, the judge's diff, and the 40-line bound of condition 5.

The evidence's file is TypeScript, so only the second group applies to it.

Why that is enough here: in red, a support change is part of writing the tests, and a person approved the text that
asks for it (an activated plan, or a spec merged to the base branch). Before this change, the revert at step 1 was the
only check that read the change's effect on the base's tests. After it, a person's `[test-infra]` tag on the task is no
longer needed for this case. That tag is a broader allowance: it covers every harness commit of the task, it has no
line bound, and the person gives it only after two FAIL rounds. This is why the requirement is slippable.
Recommended: ship it, with the bound of condition 5. If the owner wants green's rule 1 for red too, the narrower form
is to keep only a file whose base lines all survive in order (`git diff` counts no deleted line). That form may miss
the evidence's case, where adding an edge to an existing line of the graph changes that line.

### D2. What the blocker says (L4-VER-080)

`check_base_tests` computes, for the reverted files that are support files (`is_support_file` at their revision),
`support_reverted = [{"path": p, "tasks": [<task keys of the harness commits in _introducers(ctx, p, changed)>],
"people": <a person's commit changed it>}]`, sorted by path, at most 20 entries. It is recorded in `verify.base_tests`
(`_emit` gains the keyword).

When it is not empty, the detail of `a pre-existing test fails on the unit's code` and of `a pre-existing test no longer
runs on the unit's code` starts with `with the unit's test and support files at their base version (support files
reverted: <p> (task <t>[, <t2>]), ... (+<n> more); <k> files in all), these base tests fail: ` (`no longer run:` for
the second). The current list follows (`_listed` of the ids with their first lines, then the gone ids and collection
lines). At most 5 support files are named, each `(a person)` when only people's commits changed it. The lead comes
first because a chore's detail is cut at 600 characters (`fixunit.py:448`). The detail says what the run did. It does
not say that the test passes at head: step 1 never runs it there.

Fail-safe: D2 changes text and records only. The blocker, its title, its severity and the verdict are unchanged, and
so is the finding's id, which `failure_set` reads. A failing id with no case in R1 gets no record. The only reader
that acts on a `base-tests` record is the failure block, which is text for the fix chore and the person.

The records: `failure_records` gains a keyword `unit_gate: str = "test"`, which is the `gate` value of the unit side
(the 200-record cap applies to that side as before). `check_base_tests` calls it with a report that holds only the
blocked failing ids' cases of R1, `browser=None`, `unit_gate="base-tests"`, and the excerpt callables that
`ladder.tests()` passes (`case_excerpt` with `worktree=wb.worktree`, `tmp_root=wb.unit_cache / "gate-tmp"`,
`redact=wb.redactor.redact_text`). The records go into `Outcome.failures` (a new field, default empty), and
`ladder.integrity()` copies them into `result.failures` after `record_outcome`. Step 3 replaces `result.failures` as
before. It never runs after a step 1 that holds a base-tests blocker, so nothing is lost.

`shown_failure_ids` gains one branch: for `a pre-existing test fails on the unit's code` every record with `gate ==
"base-tests"`. The title moves to `failures.py` as `BASE_FAILS_TITLE`, which `base_tests.py` imports as
`FAILS_TITLE`, so `failures.py` stays free of harness imports. No other reader changes: `failing_ids`, `finding_test_ids` and `repair_candidates` filter by
gate (`test`, `e2e`), and `restore_round` copies every record. The fix task's failure block, the fix chore's prompt
block and its questions' harness note (L4-IMP-102) then hold the excerpts with no change to that code.

Redaction is that of L4-VER-078: the excerpt is redacted before and after it is cut, and the verdict is redacted
again when it is written.

### D3. The escalation (L4-VER-081)

In `fixloop.py`, when `repeated_failure` gives a detail and the round's findings hold a blocking finding titled
`FAILS_TITLE` or `GONE_TITLE`, the escalation's text is `base_tests_way_out(events, round) + "; " + detail`.
`base_tests_way_out` reads the newest `verify.base_tests` event of the unit with `round <= result.round` and its
`support_reverted` entries that name a task. It gives `base versions of support files fail a pre-existing test; tag
the task that changed one [test-infra] if its change is intended, or fix the code, then l4 retry: <p> (task <t>),
...`, at most 3 files, cut at 300 characters. It gives `""` when the event has no such entry (0.4.59 events have no
`support_reverted`), and then the text is the detail alone, as before. The code stays `same_failure`, and so do the
edge and the fold.

Where a person reads it: `fixloop.py:767-771` puts `fix.reason` into the sticky note's escalation section
(`notes.escalation_section`: `Round <n> ended FAIL: <reason cut at 300>`) and into `ctx.shared["escalation"]`, the
unit's halt detail. A later run's exit reason is `escalated: <detail>. Next: l4 retry --unit <u> --reason TEXT`, cut at
300 characters (`orchestrator.py:1755`), because `same_failure` has no way out of its own (`next_step.way_out`). The
fixed part of the lead is about 150 characters and comes first, so the 11 characters of `escalated: ` and the
`. Next:` tail leave room for it and the first file. A cut drops the later files, never the way out. `l4 status` shows
the whole detail.

Fail-safe: D3 changes the text only. The escalation still happens exactly when `repeated_failure` says so, with the same
code, edge and fold, and `l4 retry` resolves it as before. A missing or old event gives the old text.

The fix chore that changes nothing is not changed here (non-goal). After D1 the case of the evidence never reaches
it. For any other base-tests failure, D2 tells the chore what the run reverted, and D3 tells the person.

### D4. Skill text

`plugins/l4/skills/l4/references/spec.md`, bullet **test-support files** (the file is held to 530 words by
`tests/unit/docs/test_adoption_docs.py`, so the bullet is rewritten, not grown): `Name a test-support file a task must
change exactly, in code font (...), in its task line or heading, on an active plan or the base branch. Its red step
may then change it (the base-tests run keeps that); its green step only a Python file red left alone.` If D1 is cut at
integration, the second sentence is instead `Its green step may then change a Python one red left alone; a red step
that changes an existing support file needs a person's [test-infra] tag, or the base-tests run reverts it.` (check
the word count again). The `testpaths.py` remedy (L4-YOLO-094) is about documentation under a test
glob and skips code files: it is not this case and is not changed.

### D5. Upgrade

A unit in flight from 0.4.59 already has the `task.unfrozen{named_by_task}` events of its green attempts, so its next
round keeps a named support file at head. A 0.4.59 `verify.base_tests` without `support_reverted` gives no lead text
and no way-out text. A 0.4.59 verdict has no `base-tests` record, so no failure block is added. Readers that do not
know the gate value ignore it. An older harness that reads a 0.4.60 verdict ignores the records for the same reason.

## Risks / Trade-offs

- D1 trusts the reviewed text for the whole change red made to the named file. Bound: the file is listed, the judge
  reads it, at most 40 changed lines per file and three files per task, and the rule is slippable.
- `names_path` matches a mention that says "do not change `x`" too. This is the same rule that opens a named support
  file for green (L4-IMP-014).
- The lead text adds about 200 characters to the detail of a blocker, which is now cut later in the chore's 600.
