## Context

Read at `next-int` (50bb9526). Labels: [V] read in code or ledger text, [I] inferred from code, not run, [U] not verified.

- `src/l4/evidence/testsran.py:113-122`: `old_skipped` is every skipped id that is not new; `touched` is the part whose
  file is in `changed` (`file_of_test`, `:46-78`, which builds `.py` paths only); each `touched` id is named in one
  `Severity.MAJOR` finding, source `deterministic`. No base data is read [V].
- `src/l4/verifier/ladder.py:970-995` (`_collect_step`) adds `ev.ran.findings` to the round. `:998-1013`
  (`_quality_step`) adds `ev.later_holds`, and returns first when diff coverage is off or has no evidence [V].
- `src/l4/evidence/collect.py:54-67` (`Hold.kind` is `scope | coverage | unsafe`), `:81-84` (`later_holds` is
  `hold_records[scope_holds:]`), `:321-341` (the tests-ran call and the `records` list) [V].
- `src/l4/verifier/verdicts.py`: a hold is a plain `str` in `result.holds`; its kind is read back from its text by
  `hold_kind` (`:110-119`: scope, judge_view, coverage, else `other`). `_hold_question` (`:751-815`), `_hold_finding`
  (`:240-284`), `settle_holds` (`:287-325`), `hold_sha256` (`:328-332`) and `subsumed_findings` (`:161-174`) all work from
  that text and from `result.hold_views` [V].
- `src/l4/verifier/ladder.py:1091-1139` (`_finalize`): the accept of a hold stays in force while its `text_sha256` equals
  `hold_sha256(hold, result.hold_views)`; `effective_verdicts` (`verdicts.py:457-506`) never reads `by` [V].

## Goals / Non-Goals

Goals: a person can waive a skip that the unit did not make; a skip the unit made stays a deterministic finding; no new
dead end (a fix unit that cannot fix); an already open fix unit for the old finding can be closed without forging
anything.

Non-goals: see the proposal. In particular, no base-side test run (D1), no non-Python skips (D1), no change to what a fix
chore may edit (D4).

## Decisions

### D1. Why no base run, and the rule that replaces it (L4-VER-092)

Question 1 of the brief: does the verifier hold a base-side report?

- Step 1's `check_base_tests` runs the gate at head with the unit's changed test and support files put back at their
  base version (`src/l4/verifier/base_tests.py:455-475`, `support_at_base`). That run, `r1`, does hold the skip status
  of those tests with the base version of their file. But it is local to the function: the only thing kept is
  `record = {base_sha, command, passed, collection_errors}` with `passed` the passed ids of `r0` (`:524-529`), and
  `_report_of(passed, errors)` rebuilds a report of passed tests only (`:383-384`). A skipped id is never stored [V].
- `r1` is not made when the unit changed no test file (`:445-451`), when a changed file is allowed and kept at head
  (`_kept`, `:441-443`), when step 1 already failed (`:431-432`), or when `gates.setup` failed (`:453-455`); the base
  reference `r0` is read only when `r1` is not all green (`:483-489`) and from a cache of passed ids [V].
- So a base report with skip status exists for some units, in step 1, and is thrown away. Using it needs a new record
  written by step 1, and still would not cover the units where it is not made. A rule that needs the same inputs in
  every unit is better.

The rule: the harness compares the **skip constructs** of the file at base and at head, on the AST, for the test in
question. This is what step 1 already does to find a skip the unit added: `scan.skip_markers(after) -
scan.skip_markers(before)` per file (`src/l4/verifier/integrity.py:355-361`, blocker `a skip or xfail marker was added`
at `:395`) [V]. That function counts markers per test name, so it misses a changed condition (the count stays 1), an
alias (`requires_stack = pytest.mark.skipif(...)`, then `@requires_stack`), `pytest.importorskip` and a condition on a
continuation line. A line-token diff of the hunks (`-U0`) misses the last one too, and flags every test of the file for
one added skip. So this change adds `scan.skip_constructs`, described in D3, and leaves `skip_markers` and the step 1
check alone.

A test T (a JUnit id of an old skipped test of a changed file P) **predates** the unit when all of these hold; the first
that fails makes T a deterministic finding as today (fail closed):

1. `changed_files` reports P with status `M` (`collect.py:118-135`: an added file is `A`; a rename keeps only its head
   path and is reported `R`, so a moved test is never predating). A new file is already the blocker `new tests were
   skipped` or `new test file ran no test` (`testsran.py:97-106`).
2. The blobs of P at base and at head are read with `show_blob` and both parse; a git error, a file over
   `MAX_SOURCE_BYTES` (`collect.py:50`) or a syntax error is a failure of this rule, never a pass.
3. T maps to a qualified name `q` of P (module, class parts of the id's classname, function without `[param]`; module
   functions and methods of module-level classes only, as `scan._qualified` does), and `q` is a test at base
   (`scan.defined_tests(base)`). A test that did not exist at base, was renamed, or moved to another class is not
   predating.
4. The unit added no skip construct in a **scope that can skip q**: `new = constructs(head) - constructs(base)`
   (multiset difference, so removing a skip never matters and one more of the same text does); `new` has no entry whose
   scope is `q`, `q`'s class, `<module>`, or a function or method of P that is not a test (a fixture, a helper,
   `setUp`). An added skip on another test of the file does not touch q.
5. When `constructs(head)` has no entry in any of those scopes, the skip comes from outside the file (a conftest, a
   fixture file, an environment the gate lacks, a plugin option). Then T predates only when the unit's diff changed no
   file that matches `tdd.test_support_globs` or `tdd.runner_config_files` (`cfg.tdd.test_support_globs`, read at
   `src/l4/implementer/tdd.py:1831`, and `cfg.tdd.runner_config_files`, read at `src/l4/verifier/base_tests.py:462`) [V]; else it stays a finding.

Residual risks, stated in the hold's question and in the runbook (L4-VER-093): the rule compares constructs, not
behaviour, so a test that did not skip at base can skip now through an unchanged construct whose condition depends on
code the unit changed (for example `skipif(not hasattr(mod, "x"))`); and a skip with no construct that a changed
non-test file introduced is only caught by rule 5's two globs. The accept is a person's statement either way.

Languages: `file_of_test` builds `.py` paths only (`testsran.py:60-70`), so the finding, and this change, exist for
Python ids only [V]. Go (`t.Skip`), Vitest and Jest (`.skip`, `xit`, `xtest`, `xdescribe`, `.todo`, `.only`) do not
matter today: a skipped Go or TypeScript id is attributed to no changed file and raises nothing, and the same would be
true of the new hold. `.only` skips the other tests of its file and would matter the day those ids map to files; the
construct table (D3) is where it would go.

### D2. Where the hold is raised, and what it carries (L4-VER-092, L4-VER-093)

`check_tests_ran` gains the keyword `predating: Collection[str] = ()`: the ids that `collect_evidence` found to predate
the unit (rules 1-5, computed there because only it has `git`, the base and the head). The ids of `touched` that are in
`predating` leave the finding and go to `TestsSummary.skipped_predating: tuple[str, ...]` (a new field with a default;
`report.py:131-132` and `:179` rebuild the summary from `verdict.json`, so both the writer and the reader convert it like
`skipped_unchanged`; an older `verdict.json` has none and reads as empty). With the default `()` the function behaves as
today, so every existing test of it stays valid.

`collect_evidence` groups `skipped_predating` by file (`file_of_test`) and makes one `Hold` per file, kind `skipped`,
subjects `(path,)`, text

    skipped: existing tests in `<path>` are skipped, and this unit did not add or change a skip that can affect them (<n> tests)

and one `hold_views` entry per hold (the mechanism of the `judge view:` and UI holds, `ladder.py:1822-1829`,
`ui_step.py:304-316`): `{"sha": sha256(text NUL head-blob-sha NUL sorted ids), "paths": sorted ids}`. The accept is then
bound to the head content of the file and to the full list of skipped ids, so a later edit of the file, or a change of
which tests are skipped, voids it and the hold is asked again (`ladder.py:1097` computes `current` from `hold_sha256`).
The text names the file and a count, not the ids, so it is stable and short; the ids are in the question (D4) through
`view["paths"]`, the way the judge-view question lists its files (`verdicts.py:821-826`, `QUESTION_MAX_PATHS`).

The hold joins the round in `_collect_step`, next to the finding it replaces, not in `_quality_step`: step 6 returns before
`later_holds` when diff coverage is `off` or measured nothing (`ladder.py:1003-1006`), and the finding was raised in that
case too. To keep `later_holds` from adding the same hold twice, `Evidence` gets `ran_holds: int` (how many of
`hold_records` come from the tests-ran check) and `later_holds` becomes `hold_records[scope_holds + ran_holds:]`; the
order of `records` is step 1 holds, then skipped holds, then coverage holds (`collect.py:331-336`). `Evidence.to_json`
already lists every record, so `verdict.json` shows `kind: "skipped"`.

`hold_kind` (`verdicts.py:110-119`) gets a branch for the text prefix `skipped: existing tests in ` and the new
`HoldKind` value `skipped`. This is what routes the question, the reject and the delegate; adding the `Hold.kind` literal
alone would leave the hold `other`, whose question asks for a WHEN THEN sentence (`verdicts.py:787-792`).
`hold_subjects` returns `()` for it. Otherwise `subsumed_findings` (`:161-174`) would treat a blocking judge finding that
names the test file as about the hold, and an accept of the skip would settle it as minor (`settle_holds`, `:296-317`): a
person's statement about skipped tests would silence a judge's finding about the file's assertions.

Other readers of the hold list [V]: `s1_labels._SET_OF` (`verifier/s1_labels.py:23`, `hold_map` `:30-45`) ignores any kind
not in `{scope, coverage}`; `s1/labels.py:30` types `HoldRef.kind` as scope or coverage and gets only those; the System-One
export reads `ev.ran.summary` counts only (`s1/items.py:128-137`), whose `skipped` and `all_passed` are unchanged. So no
S1 data changes. The canary's mutation `skip_old_test` adds a skip, which stays a finding (`s1/canary.py:550-575`).

### D3. The skip-construct rules (`scan.skip_constructs`)

`skip_constructs(source) -> Counter[tuple[str, str]] | None`: the key is `(scope, text)`, `text` the `ast.unparse` of
the construct (so line wraps and quotes do not matter, and a changed condition does); `None` when the source does not
parse. `scope` is `<module>`, a module-level class name, a module-level function name, or `Class.method`. A construct is:

| Construct | Matches (on the unparsed text) | Scope |
|---|---|---|
| marker as decorator | `mark.skip`, `mark.skipif`, `mark.xfail` (the regex of `scan._SKIP_MARK`), `unittest.skip`, `unittest.skipIf`, `unittest.skipUnless`, `unittest.expectedFailure` | the decorated function, method or class |
| marker in a `parametrize` | the same text inside `pytest.param(..., marks=...)` or `marks=[...]` of a decorator: the whole decorator is the construct | the decorated function |
| module or class mark | an assignment (also annotated) at module or class level whose value contains a marker: `pytestmark = [...]`, `requires_stack = pytest.mark.skipif(...)`; the target name is recorded as an **alias** | `<module>` or the class |
| alias use | a decorator whose unparse contains a recorded alias as a whole word (`@requires_stack`) | the decorated function or class |
| runtime call | a call to `pytest.skip`, `pytest.xfail`, `pytest.importorskip`, `<x>.skipTest`, or `raise ...SkipTest(...)`, anywhere in a module-level statement, a function body or a class body (assigned or not: `docker = pytest.importorskip("docker")`) | the enclosing function or class, else `<module>` |

`.only`, `.skip`, `.todo`, `xit`, `xtest`, `xdescribe` (Vitest, Jest) and `t.Skip` (Go) are not in the table: the
check cannot see those ids (D1). Not in the table either: a skip with no construct in the file (rule 5), `-k` and
`--deselect` options (runner configuration: rule 5), and a fixture that calls `pytest.skip` in another file.

A non-test function or method (a fixture, a helper, `setUp`) is a scope that every test of the file shares (rule 4). A
file is tested against these cases, each a scenario: an unchanged `skipif`; a condition changed on a continuation line;
an alias defined and applied; an alias newly applied to an old test; a module-level `importorskip` added; a skip added to
another test; a fixture that gained `pytest.skip`; an unparsable head.

### D4. The question, the reject, and why a reject makes no fix unit (L4-VER-093)

The brief's intended path was `reject` to a deterministic finding to a fix unit. The code says that cannot work.

- A fix chore never changes a test file. `run_single` puts the test paths back (`restore_frozen` and `freeze_test_paths`,
  `src/l4/implementer/tdd.py:4075-4086`) and an attempt whose only edits were put back fails with `nothing changed: the
  guard put back every edit` (`:4091-4096`); a test chore (`kind="tests"`) may add tests only (`:4066-4072`) [V].
- The fix unit of the consumer's case did exactly that: it asked a technical question, because the finding asks for a
  change in a test file that the chore may not make.
- A reject can only mean "make these tests run in the gate", which is a change of a test file or of the gate. So a
  deterministic finding after a reject recreates the dead end, one fix round and one question later; and a delegate that
  rejects would do it with nobody in the loop.

So a rejected skipped hold follows the `judge view:` pattern, not the scope and coverage one: `_hold_finding`
(`verdicts.py:240-257`) returns a `human` major finding with its own title `SKIPPED_REJECTED_TITLE` (`Rejected hold: a
skipped test is not accepted`), whatever the reason says, even with a `WHEN ... THEN ...`; `fixunit.py:262-266` lists it
as not converted like `JUDGE_VIEW_REJECTED_TITLE`; `fixloop._no_task_cause` (`:694-712`) names it and the round escalates
with the new code `skipped_tests_rejected`, with a `way_out` text in `src/l4/state/next_step.py:36-72` and a section
7.3.4 of the runbook: change the file in your own commit on the unit branch (remove the skip, or make the tests able to
run in the gate), then `l4 retry --unit <unit> --reason TEXT`; or replace the answer with an accept (`l4 questions answer
... --replace`) once you ran the tests. A person's commit on a test file is allowed and listed by step 1
(`integrity.py:355-395`, `Outcome.human_tests`).

The question (`_hold_question`, new branch before the generic `else`) says: which file and how many tests, the ids (from
`view["paths"]`), that the unit's diff adds or changes no skip that can affect them by the rule of D1 (not that they were
skipped at base: no base run was made), that often the cause is an environment the gate does not have, that `accept`
means the person ran them where they can run or knows they pass there and holds for this content of the file only, and
that `reject: <reason>` ends the round, because a fix unit cannot change test files.

### D5. Who may answer (L4-VER-094)

- The delegate: `delegate.kinds` includes `verdict` by default (`config/schema.py:1055`), and `check_reply` refuses a
  judge-view reject and a judge-view accept that cites no file (`delegate/reply.py:458-462`), while `_without_a_call`
  (`delegate/run.py:852-872`) keeps a question from a call when no check can be made. A skipped hold has no check a
  read-only model can make: an accept says the tests ran elsewhere, and a reject ends the round with no automatic way on.
  So the whole hold is a person's: `_without_a_call` returns `a skipped-test hold is a person's decision` for kind
  `skipped` (no call, the question is escalated like the other cases), `check_reply` refuses both decisions with status
  `escalated` as a backstop (the `hold_kind` argument exists, `reply.py:396-409`), and the delegate prompt's hold rule
  (`delegate/prompt.py:93-94`) names the kind. This differs from the brief's lean (delegate may reject) on purpose: a
  delegate reject is a unit stop with no fix.
- An agent: `l4 questions` already refuses an agent on a `verdict` question unless `clarifier.answer_by_agents` is true
  (`docs/SPEC.md` L4-QMD-009, `:1758-1764`, `src/l4/specs/questions_cli.py:488-545`) [V]. With that key set, an agent can
  write a verdict answer. `effective_verdicts` ignores `by`. So `_finalize` (`ladder.py:1098`), right after
  `effective_verdicts`, drops the verdict of any `skipped` hold whose `by` is not `human` (`agent`, `delegate`,
  `clarifier`, the values of `clarifier/actor.py:38`), and records `human.void{question, target, reason}` once per
  question (the event the regression void uses, `ladder.py:1131`). The hold is then unresolved, and because the
  consumed question is no longer waiting (`verdict_status`, `verdicts.py:369-395`) the next round asks it again [I]. The
  precedent for a model's accept that is recorded but not applied is `held_patch.py:541-551` (`held.accept_ignored`).
  A person who runs `l4 questions answer` is `by: human` (`clarifier/actor.py:106-129`).

### D6. A unit that already has a fix unit for the old finding (L4-VER-095)

State to resolve: the parent `openspec:<name>` is `fixing`; `<name>-fix-2` has one task, 1.1, the old finding, and an open
technical question Q-001 that holds it; two of three fix rounds are used.

What exists:

- `l4 retry` refuses a unit in `fixing` (`state/retry.py:61-62` lists it in `_CONTINUES`; `:80-81` says `the harness
  continues it at the next run`) [V]. `l4 resume` is for halted and escalated units. A spec push during `fixing` waits
  until the fix unit ends (runbook 7.14, and a fix unit's folder does not count as a spec edit) [V].
- `open_fix_unit` is cleared only by `fix.done` (`state/fold.py:353-355`), which `fix_hook` appends when no task of the
  fix unit is pending and none is held (`fixloop.py:434-443`); the only edge to `verifying` is `FIX_UNIT_DONE`
  (`state/lifecycle.py:143`) [V]. A pending task held by an open question makes `fix_hook` return `blocked`
  (`:440-442`), and the planner says `fixing: fix unit questions open` (`planner.py:194-199`).
- The harness's own way to finish a task with no step is `_already_done`: it ticks the box, commits with `L4-TDD:
  already-done` and writes `task.done{tdd: "already-done", reason}`; step 1's TDD history skips such a task
  (`tdd.py:3104-3122`, `integrity.py:1105-1106`) [V].

What a person can do, and does not work:

- **Tick task 1.1 by hand in `<name>-fix-2/tasks.md`.** `fix_hook` would read it as done and append `fix.done`
  (`fixloop.py:433-443`: `questions_hold` is false with no pending leaf, and `holds`, `specs/questions.py:740-762`, counts
  pending tasks only). But the next verification, under the new harness, fails at step 1: `check_protected`
  (`integrity.py:187-190`) adds `<fix dir> (touched by non-harness commit <sha>)` for every commit in `base..head` that
  touches the fix unit's folder and is not the harness's, `questions.md` apart (`verifier/provenance.py:36-42`). That is a
  blocker, `a protected path was changed`, no fix chore can repair it (a fix step cannot change that folder), and it
  spends the last fix round. [V, from the code; no run]. A person's tick is therefore not an allowed action.
- **Answer Q-001.** The task then runs, and the chore fails (`nothing changed: the guard put back every edit`), `max_task_attempts`
  halts the unit. Nothing is gained.
- **`l4 restart`.** Works, and drops the ledger, the evidence and the fix units (runbook, the CAUTION at 7.13). Too big.

So the spec adds the minimal path, built from parts that exist: `l4 retry` is accepted for a unit in `fixing` **only when
the open fix unit is waiting on a person**, that is, when its pending tasks are all held by open questions
(`questions_hold(tasks, blocked)`, the planner's own test, `planner.py:313-327`). It records `unit.retried{reason, by,
actor, close_fix_unit: <name>}` and starts a run, as for any retry (`state/retry.py:129-141`). In that run `fix_hook`
(before it selects a task) sees the event and, **in harness commits**, for each pending task of the fix unit: ticks it as
`already-done` with the reason `closed by l4 retry: <reason>` (`task.done{tdd: "already-done", closed_by: "retry"}`,
parents ticked as `_already_done` does); sets each open question that held it to Status `superseded by retry` (a new
status text, read like `superseded by restart` in `holds`: it holds no task; `specs/questions.py:275-276`, `:396`,
`:753`), recorded with `question.superseded{ids}` so that it leaves `questions.open` and `l4:needs-answers` goes
(`orchestrator.answers_recorded`, `:670-679` is the same mirror sync); then the loop proceeds to `fix.done`. The unit goes
to `verifying`, the round is fresh (`reusable` reuses only a NEEDS_HUMAN round, `verifier/evidence.py:108-116`; the last
round failed), and with the new harness the old finding is a hold. The fix round stays counted (`fix_rounds_counted`,
`fold.py:340-345`; `_used_rounds`, `fixloop.py:480-483`: the folder is on disk), so a person who then rejects the hold
has one round left; an accept needs none. A later FAIL makes `-fix-3`.

Why a harness commit and not the person's: the tick is what step 1 refuses from a person (above), and the harness writes it
with the trailers its own checks accept. Why `already-done` and not a new tdd kind: `integrity.py:1105` already skips it, and
step 0 needs every task of the family ticked (`preconditions.py:291-296`; `FamilyProvider.tasks` returns the whole family
for the parent, `fixloop.py:157-160`), so an unticked fix task would be a blocker too [V].

The question's fate (answer to (b)): Q-001 is **superseded, not left open and not answered**: its text and the fix unit's
`questions.md` stay as history, its Status becomes `superseded by retry`, it holds nothing, and it is not in
`questions.open`. If a task of the fix unit is not pending (already ticked) its question is left as it is.

Order matters, and the runbook says it: **upgrade first.** The retry needs the new `l4` (an older `l4` refuses `fixing`),
and the pin must be the release, because the fresh round runs under the pin: on the old harness it raises the same major,
the unit fails again, and the last fix round (`-fix-3`) is spent on a finding no fix can make (`l4 upgrade` moves the pin;
an `l4` older than the pin refuses state-changing commands, `CHANGELOG.md` L4-OPS-026). Steps: `l4 upgrade --harness-ref
<release>` and merge to the base; `l4 retry --unit openspec:<name> --reason "..."` from a clone on the base with the new
`l4`; the run verifies; `l4 questions answer Q-NNN --unit openspec:<name> --text "accept ..."` (or `reject: ...`) for the
hold; the next run goes on. The bound for "waiting on a person": a fix unit that is running, or has a task no question
holds, is refused with `the fix unit <name> is running: the harness continues it at the next run`, so a retry cannot throw
away work in progress.

Not verified [U]: that `Orchestrator.resume` can record `unit.retried` in `fixing` without a phase edge (`lifecycle.py:122`
lists `FIXING` for a set of edges; the implementation reads it first, task 5.1); that `question.superseded` takes a fix
unit's technical question out of the parent's `questions.open` (the fold's rule, `state/fold.py:272`, is described for
verdict questions); and the end-to-end run, which the scenarios SCN-VER-387..390 cover with fakes.

### D7. Upgrade and risks

- No key, on by default. A unit whose changed file has old skipped tests stops failing at step 3 and waits for a person
  (exit 11). A unit whose round is already FAIL for the old finding stays so until D6's retry.
- A hold is asked once per file and content; the accept is void when the file or its skipped set changes.
- A `skipped` hold in `verdict.json` read by an older harness is an `other` hold (its question asks for a WHEN THEN);
  not a supported downgrade.
- Residuals: D1's behaviour caveat; a skip the unit added in a place the table does not list (a fixture in a conftest,
  rule 5 only when conftest changed) is a hold that a person must accept; a person's own commit that adds a skip stays a
  deterministic major, as today (`integrity.py:355-361` lists it for people, and step 3 raises the finding): out of scope.
- Parallel changes may claim L4-VER-092; this branch took the next free id by reading `docs/SPEC.md` (last: L4-VER-091,
  SCN-VER-371) and the active changes.
