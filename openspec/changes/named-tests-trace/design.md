## Context

`run_red` (L4-IMP-002) reads the red gate's report, then checks the criteria the step cites with `check_criteria`
(`result.py`): each cited criterion needs a test among `new_tests`, the ids the base report lacks
(`new_test_ids(base_report, report)`). The check runs only when `new_ids` is not empty
(`if family and new_ids and ...`); a step with no new test goes on to the already-satisfied branch (L4-IMP-003) or to
`classify_red`, whose `if not new:` exit returns `NAMED_NOT_NEW` when red changed a named test, else `NO_NEW_TEST`.

Two exemptions exist today. `unchanged_criteria` (L4-OPS-015) exempts, for a task that a spec edit reopened only, every
id the base tests trace less the new ids of the changed criteria; `check_criteria` waives an exempt cited criterion that
no new test traces. `confirmed_by_earlier_red` (owner decision 4, L4-KSP-012) exempts a criterion an earlier red of the
unit proved with tests that pass now.

The tests the task's reviewed text names (`named_tests`, L4-IMP-082, L4-IMP-089) are found before the agent step
(`listed`). Which of them red changed is computed only after the criteria check, right before `classify_red`:
`split_named(_preexisting_changes(...), listed)[1]` gives the Python ones as `(path, name)` (`Tampered`, kind
`changed`), `named_other_changed(...)` the report ids of the others. `classify_red` excuses them as regressions;
`_unfit` makes a changed named test of another language fail by an assertion or `NotImplementedError`, and checks no
failure kind for a Python one.

The verifier counts, for an *existing criterion* (its text unchanged from the base specs), any passing tracing test
pass-to-pass (L4-VER-009): `traceability._unchanged(criteria, base)` compares `normalise(c.text)` by id, and
`ladder.traceability` reads `base` from git at the unit base (`base_criteria_at`, HB-3) for OpenSpec, or a Kiro
follow-up's merged parent criteria. An OpenSpec criterion id hashes the capability, the requirement and the scenario
NAME (`criterion_id`), not the body: a MODIFIED scenario with the same name and another body keeps its id.

`trace_rules(test_command)` picks the marker form when the command holds the word `pytest`, else the name form, whose
example is `it("C-xxxxxxxx: …")`. There is no language pack in this tree; the command is the only signal.

## Goals / Non-Goals

**Goals:** a cited criterion that a named test proves needs no copy of that test; a cited criterion that the base
already specifies and tests word for word is neither asked for a test nor held; red and the verifier agree on what is
unchanged; a Python project with a gate that is not pytest is shown a Python example.

**Non-Goals:** a change to the pre-satisfied confirmation of any other criterion, to `combine`, to the hold or its
answers; a change to L4-OPS-015's own exemption; a change to the verifier's pass-to-pass rule; green; the red
template.

## Decisions

### D1. Which named test counts, per report id

A report id `i` of a named test *counts* for the criteria it traces when every one of these holds:

1. red changed the test in place: for a Python test `(path, name)` in `split_named(...)[1]`, `i` is a report id
   `names_test_id(i, path, name)` maps to it (a parametrised test gives several ids; each is judged alone); for a test
   of another language, `i` is in `named_other_changed(...)`;
2. `base_report.tests[i]` exists and has status `passed`: the regression check of green (`green_failures`) then makes
   the test pass again, which is how L4-IMP-082's "after green it MUST pass" holds, and a test that already failed
   proves nothing by failing;
3. `fails_on_zero(report.tests[i])` (status `failed`, `failure_kind` `assertion`) and `TIMEOUT_MARKER` is not in its
   message: the test looks at the answer. An error, the stub's `NotImplementedError` and a hang (whose `Failed:
   l4-test-timeout` reads as an assertion) do not count. This is the predicate run (b) and `no_assertion_failure`
   already apply to an open criterion's tests, and it is stricter than `_unfit`, which also lets `NotImplementedError`
   through for a new test because run (b) then judges it against zeroed stubs;
4. `trace_ids(report.tests[i])` holds at least one of the unit's criteria (`family`), the same trace rule
   (L4-CRT-002) `check_criteria` applies to a new test; it counts for those of its ids that are cited;
5. it traces at most `verifier.max_criteria_per_test` of `cap_universe(wb.provider, family)`: the verifier would count a
   test over the cap for none of its criteria (L4-VER-052), and red cannot split a test it may only change.

The helper is `tdd.named_tracing(python_changed, other_changed, base_report, report, family, universe, cap) ->
NamedTracing(counted: dict[str, TestCase], refused: dict[str, str])`, keyed by report id. `refused` holds, for a changed named test that
meets 1 and 4 but not all the others, the first reason in this order: `it did not pass before this step` (2), `it
hangs at red` (3, the marker), `it does not fail by assertion at red` (3), `it traces more than <N> of this unit's
criteria` (5). A changed named test that traces none of the unit's criteria is in neither map.

*Alternative rejected:* count a named test that fails with `NotImplementedError`. The test existed and passed; failing
with the stub's error shows only that it now calls a stub, and run (b) is not a reliable second check for a test of
another language (it varies Python only). The agent is told why (D3).

### D2. Where a counted named test enters, and what follows

`run_red` computes `python_changed = split_named(_preexisting_changes(wb, task, base, stale), listed)[1]` (when
`listed.tests`) and `other_changed = named_other_changed(wb, base, listed, base_report, report)` (when `listed.other`)
once, right after the red gate's report is read and `tampered("test run")` passed, and passes the same lists to
`classify_red` later; the later computation is removed, not repeated. The work tree's test files do not change between
the two points: the variant runs swap production files and put them back byte for byte.

- The criteria block runs when `family` is not empty, the report has no collection error the base lacks, and `new_ids`
  or `counted` is not empty.
- `check_criteria` gets `named=counted` (a new keyword, default empty). A counted test adds to `tracing` only: the
  cited set is `criteria_ids` when the result lists any, else what the new tests trace together with the unit's
  criteria the counted tests trace, and the required ones in both cases as today (the same fallback, never an id outside the family, so a named test that carries an
  earlier unit's id cannot make the step fail with `criteria that are not one of this unit's`); `untraced`
  (`test.untraced`) and `over_cap_text` stay over the new tests only.
- `traced_new`, which decides which required criteria look for an earlier red, also holds what the counted tests trace.
- A counted test fails at red, so its criterion is never in `passing`: no pre-satisfied confirmation, no hold. The
  criterion is an open criterion; run (b) (`vacuity_check`) or `no_assertion_failure` sees the counted test fail by
  assertion; `proofs[c]["tests"]` and `discriminating` name it, so the verifier's `red_proofs` gives it a red proof.
- `classify_red` gets `named_proofs`, the counted ids that trace a cited criterion (the ones `check_criteria` puts in
  `tracing`; a counted test that traces only a criterion the step does not cite is no proof): its `if not new:` exit
  returns `NAMED_NOT_NEW` or `NO_NEW_TEST` only when `named_proofs` is empty too. `resume_red` holds each counted
  test (a non-new test of a proof in `task.red_ok.criteria` that is not `pre_satisfied`) as passing in the base report it
  rebuilds from the red checkpoint, so green's regression check makes it pass again after a resume too. Every other check is unchanged.
- `task.red_ok.tests` stays the new ids (it may be empty); the verifier's expected red tests (`_red_green`) and green's
  `red_ids` are unchanged, and the named test is held to pass by green's regression check (D1.2). `tests.superseded{reason:
  "named_by_task"}` is recorded as today. A step with a changed named test still never ends as already satisfied
  (L4-IMP-089).

### D3. A named test that does not count says why

The reasons stay. When the attempt fails with `no new test traces <ids>: <hint>` (either form of `check_criteria`), or
with `NAMED_NOT_NEW`, `run_red` appends, for each id in `refused` whose trace holds one of the step's cited criteria
(`criteria_ids` together with the required ones; with neither, the unit's criteria), in report id order:
`; <id>, which the task names, does not count for <criteria>: <why>`. A Python test changed so that it fails with
`TypeError` therefore reads `no new test traces C-…: tag each test …; tests.test_registry::test_lists_all, which the
task names, does not count for C-…: it does not fail by assertion at red`, which tells the next attempt to fix the
failure kind, not to add a copy.

### D4. Unchanged on the base: the verifier's rule, read the verifier's way

Two helpers move into `l4.specs.criteria`, and the verifier calls them:

- `unchanged_ids(criteria, base) -> frozenset[str]`: the ids of `criteria` that `base` holds with the same text after
  `normalise` (the body of `traceability._unchanged`, which becomes a call of it);
- `spec_baseline(git, framework, provider, rev) -> list[Criterion]`: `base_criteria_at(git, rev)` for OpenSpec (`[]`
  when `rev` is None); for Kiro the provider's `merged_parent_criteria()` when it has one (a follow-up), else `[]`.
  `ladder.traceability` computes `archived` with it, for the same result as today.

`tdd.unchanged_on_base(wb, criteria, base_report, report) -> dict[str, tuple[str, ...]]` gives, for each id in
`unchanged_ids(criteria, spec_baseline(wb.git, wb.ref.framework, wb.provider, unit_base(wb)))`, the ids of the base
report's tests whose `trace_ids` hold it, whose status is `passed` in `base_report` and in `report`, and that trace at
most `verifier.max_criteria_per_test` of `cap_universe(wb.provider, family)`, sorted; a criterion with none is left out.
`criteria` is `wb.provider.criteria(wb.ref)`, the list whose ids are `family`. A fix unit's tasks run with the fix unit
as `wb.ref`, and `FamilyProvider.criteria` keeps the fix unit's own reading of an id it shares with the parent, where
the verifier reads the family as the parent does; a criterion is therefore unchanged on the base only when the
reading of `wb.ref` and, for a provider that has a `parent` other than `wb.ref`, the parent's reading are both
unchanged (an intersection: it never exempts more than either reading alone). A test that red changed in place (a
named test) is no evidence of the base, whatever it asserts now: it is left out of the tests that show a criterion
unchanged, so a base test weakened to `assert True` exempts nothing. The archived specs are read from git at
the unit base (`unit_base`, as the base run and the verifier find it), never from the work tree, so a copy of a delta
into `openspec/specs/` makes nothing unchanged (HB-3). A plain Kiro unit has no baseline and nothing is unchanged on the
base: its ids hash the unit's own text, so no test of the base traces them unless an earlier task of the unit wrote it,
which the earlier-red confirmation covers.

### D5. What an unchanged-on-base criterion changes in red

Call the set `on_base`. It applies to every task, fresh or reopened, as a union with L4-OPS-015's set.

1. **No new test needed.** `exempt` becomes `unchanged_criteria(...) | set(on_base)`, so `required` leaves it out and
   `check_criteria` waives it when no new test traces it, as for a reopened task.
2. **Confirmation by the base specs.** A pre-satisfied candidate that is in `on_base` and that the earlier red did not
   confirm is confirmed without a run, before the zero-value run, in both places the earlier red is asked: the
   candidates of a step with new tests (`passing`) and those of the already-satisfied branch (`candidates`). It is
   taken out of what `confirm_pre_satisfied` and `confirmed_by_base_run` get, so with nothing else left neither run
   is made. It is recorded `criterion.pre_satisfied{criterion, tests, via: "unchanged_spec"}` (`tests`: the new
   passing tests, or the passing tracing tests in the already-satisfied branch) and, in `task.red_ok.criteria`,
   `{"tests": [...], "proof": "pre_satisfied", "discriminating": [], "via": "unchanged_spec", "base_tests": [...]}`.
   With `discriminating` empty, `red_proofs` and `red_notes` skip the record, so it is no red proof and no unproven
   label; the verifier counts the criterion's passing tests pass-to-pass, as it already does. `earlier_red._evidence`
   ignores `pre_satisfied` records, and the tests `criterion.pre_satisfied` lists are no earlier-red evidence for a
   later task, as today.
3. **Every cited criterion unchanged on the base.** The task ends as already satisfied, with no zero-value and no
   base run, in either of two ways the red template already leads to: the step adds no test, changes no file and
   reports `criteria_ids` with a `tdd_exemption.reason` that starts with `already_satisfied` (the already-satisfied
   branch, L4-IMP-003); or it adds new tests that all pass (every cited criterion pre-satisfied, the existing
   `finish_already_satisfied` exit). A step that adds no test, changes nothing and reports no reason fails `no tests
   added`, as today. A reopened task never has this case today (`tasks.reopened` reopens only tasks that cite a
   changed criterion), so there is no reopened-task path to reuse; the already-satisfied branch is the path both
   cases share.
4. A new test of an unchanged-on-base criterion that fails by assertion is an ordinary red test of it.

`_via` and `proof_of` in `run_red` get the `on_base`-confirmed criteria; the constant is
`VIA_UNCHANGED_SPEC = "unchanged_spec"` in `tdd.py`.

The confirmation of items 2 and 3 is not made in a fix unit's task (`wb.event_context["fix_unit"]`): the judge reads no
fix unit's events (L4-VER-018), so a task ticked there would get no check. Such a task keeps the zero-value run, the
base run and the hold; its unchanged criteria still need no new test (item 1). For a criterion confirmed here,
`judge.satisfied_refs` shows the L4-VER-018 judge the record's `base_tests` before its new tests, with a note that the
base specs confirmed it, so that a vacuous new test is not the only thing it sees.

### D6. Why widening L4-OPS-015's scope is safe

L4-OPS-015 exempts only a reopened task because only there did L4 know that a criterion was unchanged. The three
conditions of D4 give the same knowledge for any task, from a source the agent cannot touch:

- **No vacuous red.** The criterion's scenario is word for word the archived one, read from git at the unit base, and a
  test of the base that traces it passes at the step's base and at red, within the verifier's cap. The behaviour is in
  the code and tested before this task. A red test of it cannot fail by assertion against code that already does it,
  so asking for one forces either a passing test (and the hold) or a test of something else.
- **Nothing the verifier would refuse.** The verifier accepts exactly these criteria pass-to-pass (L4-VER-009), through
  the same `unchanged_ids` over the same baseline. Red no longer asks for more than the verifier needs, and lets
  through nothing it would not accept. The verifier reads the baseline again at its own base: a scenario that the base
  branch changed after red is no longer unchanged there, has no red proof, and is uncovered, not passed.
- **The task still proves what it changes.** A scenario the unit adds or changes (a new id, or the same id with another
  body, D4) is not in `on_base` and keeps every rule: a new failing test, a counted named test (D1), or the
  pre-satisfied confirmation with its runs and its hold.
- **The base test cannot be weakened in the step.** Red may not change an existing test it is not told to change
  (L4-IMP-048), green may not change a test file (the freeze), and the base test must also pass in the red report.

### D7. The trace form of a Python gate that is not pytest

`trace_rules` gets a third answer. When the command does not match `_PYTEST_COMMAND` and matches
`_PYTHON_COMMAND = (?<![\w.-])(?:python[0-9.]*|manage\.py|unittest|nose2|xmlrunner)(?![\w-])`, it returns
`_PYTHON_NAME_RULES`:

- `rule`: `` Put each criterion id (listed below) that a test checks in that test's name, with an underscore for the
  dash, for example `def test_c_xxxxxxxx_…`; L4 reads the ids from the test names in the JUnit report ``;
- `also`: `` by putting both ids in its name, for example `def test_c_aaaaaaaa_c_bbbbbbbb_…` ``;
- `form`: `` in its name, as `def test_c_..._…` ``;
- `hint`: `TRACE_HINT_PYTHON_NAME = "put the id in the name of each test that checks a criterion, with an underscore
  for the dash, for example def test_c_xxxxxxxx_…"`;
- `stub`: `""` (the contract's Python stub sentence holds);
- `advice_guarded`: the pytest rules' (a Python guarded stub);
- `advice_other`: `` Make the test fail by assertion: catch the error and fail the test with the runner's own call
  (`self.fail(...)` in a `unittest.TestCase`), or stub the missing symbol with `raise NotImplementedError` ``.

`tag_example` gives `def test_c_<hex>_…` with one `c_<hex>` part per id for these rules. `trace_ids` already reads
`c_<hex>` in a test id (`_TRACE_ID`, case-insensitive, `-` or `_`). A gate that matches neither keeps the name form with
`it("C-xxxxxxxx: …")`; a `make test` wrapper is not recognised (no signal in the command). When a language pack gives
L4 the project's language, it can replace `_PYTHON_COMMAND`.

### D8. The prompt says a named test can count; the template stays

`prompt._named_section` replaces `Do not delete or rename one, and still write the new tests the criteria need:` with
`Do not delete or rename one. A listed test that traces a criterion this task cites (its id in the test's name or
marker), passed before your change and fails by assertion after it, is that criterion's red test and needs no new test
beside it; write new tests for the criteria no listed test traces:`. This is Python text of `prompt.py`, not a pinned
template, so no version moves. `red.md` keeps version 13: its rule that every listed criterion needs a new test is
stricter than the harness now is, and an agent that follows it is still accepted (a new failing test is a red test; a
new passing test of an unchanged-on-base criterion is confirmed by D5.2). Moving it would bump the lock and five
template-version assertions for no change in what is accepted.

## Risks / Trade-offs

- `names_test_id` matches the function name inside the module whatever the class, so a same-named method of another
  class of the same module counts with the named one, as `classify_red` already excuses it as a regression. It must
  still have passed at the base, fail by assertion at red and trace the criterion.
- An agent may add a criterion id to a named test's marker (a decorator change L4-IMP-082 allows) to make it count. The
  test must then fail by assertion after a change to a test a person's reviewed text named, the same evidence a new
  test gives; the judge is shown the named test's lines at the base and at head (L4-VER-068).
- A passing new test of an unchanged-on-base criterion is kept in the code beside the base test it repeats, with no red
  proof; the verifier counts both pass-to-pass. Listing those criteria in the prompt would avoid the copy (not in this
  change).
- `_PYTHON_COMMAND` can match a gate that starts another language's runner through a Python script; that gate's prompt
  then shows the Python example. The trace rule itself (an id in the test name) is the same, so only the example is off.
- The base branch can move between red and verification. The verifier reads its own baseline, so the cost is a
  criterion that becomes uncovered (a finding), never a criterion that passes without evidence.

## Not in this change

- **The consumer rule for partly satisfied scenarios** ("green implements only what its task names; when earlier code
  already makes some rows of a scenario true, fold those rows into a test that also asserts what this task adds: every
  new test function needs one assertion that only this task makes true"). It is a test-writing rule for a CHANGED
  scenario that the code already partly satisfies, which this change does not touch; it belongs in `red.md` and
  `green.md`, which moves both template versions and the lock, and its effect on agents needs its own `l4 eval
  --compare` run. Bundled here, a regression in either rule could not be told apart.
- **A prompt list of the unchanged-on-base criteria.** It would save the redundant test of D5.2 but needs a new
  `PromptContext` field threaded through `prompt_context`, `agent_step` and `step_or_replay`; D5 accepts both things an
  agent does without it.
- **`red.md` wording** (D8).
- **Language packs.** None exist in this tree; the trace form follows the gate command (D7).
- **The criteria L4-OPS-015 alone exempts.** In the already-satisfied branch they still go through the earlier-red,
  zero-value and base runs; only `on_base` skips them.
- **A named test that fails with `NotImplementedError`** (D1, alternative rejected).
