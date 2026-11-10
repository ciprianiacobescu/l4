## Context (verified on amaster e407590d)

- **Which criteria are UI-facing.** `playwright.ui_facing_criteria(criteria, changed, ui_paths)`
  (`src/l4/verifier/playwright.py:47-50`) returns every criterion of the unit as soon as one changed file matches
  `verifier.playwright.ui_paths`; the S1 question of L4-VER-014 is not built (the module docstring says so).
- **Which UI criteria are gaps.** `ui_step.plan_generation` (`src/l4/verifier/ui_step.py:43-68`) gets `proven`, built by
  `ladder._generate_step` (`src/l4/verifier/ladder.py:1224`) as `{criterion: {t.id for t in e.tests}}` over
  `result.trace`: the ids of every tracing test step 4 accepted, whatever its proof. It uses them only to decide whether
  an *end-to-end* test that traces the criterion is proved (`e2e_coverage`); a criterion that only unit tests trace is
  always a gap (the module docstring: "a criterion covered only by a unit test still gets a browser test"). So
  `plan_generation` has step 4's test ids but not its states, proofs or labels, and it is not where the hold is decided.
- **Where the hold is decided.** After the writer ran, `unclosed_holds(gaps, out.outcomes)` (`ui_step.py:126-134`,
  called at `ladder.py:1274`) makes `ui_hold_text(c.id)` a hold for every gap whose outcome is not `accepted` and not
  `waived`. The waiver (L4-VER-067, `ui_waivers`, `ladder.py:1234`) is decided before the writer, from the ledger.
- **What the trace holds when step 5 starts.** Step 4 (`ladder.verify_unit.traceability`, `ladder.py:774-798`) sets
  `result.trace = trace_criteria(...)` (`src/l4/verifier/traceability.py:190-251`): one `CriterionEvidence{criterion,
  state, tests, ignored, held, capped}` per criterion, `state` `fail` when a tracing test did not pass, `covered` when at
  least one did and none failed, else `uncovered` (`traceability.py:247`). A tracing test is a `TracingTest{id, status,
  proof, adequate, note, over_cap}`; `proof` is `zero_value`, `pre_satisfied`, `red_assertion`, `repair`, `audit`,
  `generated`, `human`, `chore` or `pass_to_pass`, and `note` is set only for a red record that no run proved
  (`not applicable: no project code`, or `accepted by …: the check was inconclusive`, `types.py:160`,
  `traceability._unproven_note`). `_extra_proof_step` may trace again with people's and chores' proofs
  (`ladder.py:789-793`). Step 4a (`_audit_step`, `_with_audit`, `ladder.py:1121-1175`) then appends each accepted audit
  test (`proof: audit`) and sets `held` for a criterion whose audit test fails at head. Step 5 reads this list; steps 8
  to 10 change it later (step 9's adequacy, `count_named`, the carried passes). The verification report's step-4 note
  ("traceability: N/M criteria covered by a discriminating test", `report.py:60-61`) counts `state == "covered"`.
  There is no `_red_tests` in the ladder; `_red_green` (`ladder.py:335`) maps new test ids to tasks, not criteria to
  coverage, and the judge follow-up (`judge_followup.py:194`) reads the same trace after step 9.
- **A reused round.** `verify_unit` resumes at aggregation when `reusable(prev, subject, criteria)` holds
  (`src/l4/verifier/evidence.py:108-116`): `restore_round` (`evidence.py:172-235`) rebuilds the result from
  `verdict.json`, `generated` through `_generated` (`evidence.py:168-169`) and `holds` as stored (`evidence.py:192`),
  every `ok` step becomes `reused (round N)`, and `_resume` (`ladder.py:979-997`) runs only `_finalize`, which reads
  `result.holds` and never calls step 5 or `unclosed_holds` again. The restored trace is the one stored after step 9,
  with its adequacy applied.
- **What the writer gets today.** `generate_ui_test` (`src/l4/verifier/generate.py:220-288`) calls
  `testwriter.request_test(kind="e2e")` with the system text `SYSTEM` plus `_KIND_RULES["e2e"]`
  (`src/l4/verifier/testwriter.py:45-57, 85-90`: one pytest test, self-contained, tagged with the criterion id; the
  pytest-playwright `page` fixture; the base URL from `L4_E2E_BASE_URL`; assert what a user sees) and a user text of the
  criterion (id, alias, text) and three data blocks (`generate.py:233-237`): `scenario` (the criterion text again),
  `ui diff` (`ladder._ui_diff`, `git diff <base>...<head> -- <changed files under ui_paths>`, at most 30,000
  characters) and `page snapshot` (the page the head app served in step 3's e2e gate, `E2eGateOutcome.snapshot`, at
  most 30,000 characters), plus the reason of a rejected first attempt. The whole user text is redacted. It is shown no
  file of the e2e suite (no `conftest.py`, no helper module, no existing e2e test), no other production source and no
  spec document. Its file is always `e2e/test_l4_c_<hex>.py` (`testwriter.test_path`), written in the head worktree and
  in the merge-base checkout, run at the base and then at head with only that file collected (`L4_COLLECT_ONLY`; pytest
  still loads `e2e/conftest.py`) and, at head, with the e2e runner's support files the unit changed at their base
  versions (`generate._head_run`, `support_base.runner_support`, L4-VER-035).

## Goals / Non-Goals

**Goals:** a UI criterion that a discriminating test of step 4 already covers, and that the writer says it cannot test in
a browser, is recorded and shown, not asked about. A criterion with no discriminating test, or whose generation failed
for another reason, is held as today. A reused round gives the same answer as the round it reuses. The writer can use
the suite's own fixtures and helpers.

**Non-Goals:** reclassifying criteria per criterion (D5); skipping the writer for covered criteria (it is still asked:
a browser test it can write is still wanted); remembering a note across rounds (each fresh round asks the writer again,
as for every gap today); changing the gap finding's text, the hold's text or binding, the waiver, or the judge's
prompt; showing the writer existing e2e tests, the repository root's `conftest.py`, or files of another language; a
configuration key.

## Decisions

### D1. What "step 4 covers it with a discriminating test" means

`ui_step.covered_by_step4(trace) -> dict[str, tuple[str, ...]]`, pure, maps a criterion to the sorted ids of its
covering tests, for each `CriterionEvidence e` with:

- `e.state == "covered"` (no tracing test failed, at least one passed) and `e.held == ""` (no audit test failing at
  head);
- at least one `t` in `e.tests` with `t.status == "passed"`, `t.adequate`, `t.proof != "pass_to_pass"`, `t.note == ""`
  and `t.over_cap == 0`. Those `t` are the covering tests.

So a red proof (`zero_value`, `pre_satisfied`, `red_assertion`), a repair's proof, an accepted audit test, a people's
or chore's test the verifier saw fail, and an earlier round's accepted generated test count. `pass_to_pass` does not:
it says only that the criterion's text is unchanged from the base specs, and no run showed that its test fails without
this unit's change. A red record that no run proved (`not applicable: no project code`, an override after an
inconclusive check, L4-VER-051) does not either. `adequate` and `over_cap` are always `True` and `0` when step 5 runs
(the judge has not run); they are named so that the function means the same on any trace.

*Alternative rejected:* `e.state == "covered"` alone, the number step 4's note reports. It counts `pass_to_pass` and
unproven red records, which say nothing about this unit's change; such a criterion keeps its hold.

### D2. The note

`generate_ui_tests(..., covered=…)` takes the map of D1. After `generate_ui_test` returns an outcome with
`status == "not_testable"` for a criterion that the map holds, the outcome gets `covered_by` (`GeneratedOutcome`
gains `covered_by: tuple[str, ...] = ()`), before `verify.generated` is emitted: the event carries
`covered_by: [<ids>]` (only when it is not empty, so every other event keeps its shape). No other status gets it.

- `unclosed_holds` treats an outcome with `covered_by` as closed: no hold, so no hold view and no question.
- `fixunit` adds it to the closed gaps (`fixunit.py:233`), as for `accepted` and `waived`: on a PASS round under
  `verifier.fix_minor_findings` its minor gap finding makes no fix unit.
- The generated UI tests table (`report._generated_rows`) keeps the status `not_testable` and the writer's reason, and
  adds to the Reason cell `covered by step 4: <ids>; a note, not a hold (L4-VER-067)` (the first three ids, then
  `(+n more)`). `verdict.json` stores `covered_by` as a list (`report._generated_json`).
- Step 5's note (`ladder._generate_step.body`) appends `; <n> not_testable covered by step 4: notes, no hold
  (L4-VER-067)` when there is at least one.
- The minor gap finding (`ui_gap_finding`, made before the writer runs) is unchanged: it is not a question, and its
  text is the same for every gap whose writer did not succeed.

The status stays `not_testable` because that is what the writer said; the note is the combination of that status and
step 4's answer, and both stay visible. A new `GenStatus` would hide the writer's status and need every reader of the
status to learn it.

### D3. The data flow from step 4 to step 5, and a reused round

Step 5 computes `covered = covered_by_step4(result.trace)` in `_generate_step.body`, from the trace as it stands then
(step 4's trace, traced again by `_extra_proof_step`, with step 4a's audit tests and holds), and hands it to
`generate_ui_tests`. Nothing new is carried from step 4: `result.trace` is already on the result step 5 reads, and is
the same list it reads today for `proven`, `_test_blobs` and `ui_waivers`. No gate is run and no ledger event is read
for it.

The decision is stored, never derived again: `verify.generated{covered_by}` in the ledger, `generated[].covered_by`
and `holds` in `verdict.json`. A reused round (`reused (round N)`) restores `generated` (`evidence._generated` turns
`covered_by` into a tuple and defaults it to `()` for a record written before this change) and `holds` as stored, and
`_finalize` reads `holds`; so it gives the answer of the round it reuses. It must not compute D1 again from the restored
trace, which carries step 9's adequacy and so could differ. A record written before this change has no `covered_by`; its
holds were raised by that round and stay as stored. A fresh round (new code, or a person's commit) runs step 5 again
on its own step 4.

### D4. What keeps the hold

Every case that today makes a hold still does, except D2's: a gap with no covering test (only `pass_to_pass`, only
unproven red records, a failing tracing test, a failed audit test, no tracing test); an outcome of any other status
(`writer_failed`, `uncollectable`, `fails_at_head`, `non_discriminating`, `base_error`, `base_unservable`,
`lint_failed`), covered or not; and no writer configured (`roles.verifier_agent` empty), where no outcome exists. A
`not_testable` on the second attempt (after an invalid reply or a rejected test) is the writer's answer too, and is a
note when D1 holds.

### D5. Which criteria are UI-facing stays per unit

Classifying per criterion (for example by the criterion's text, or by whether its tracing tests touch UI files) would
change what L4-VER-014 means by a UI criterion and decide, without a browser run, that a criterion needs no browser
test. A criterion that a person wrote about the page, covered by a unit test of the function behind it, would then
never get a generated browser test. This change keeps every criterion of a UI-facing unit a gap and asks the writer for
each, and only stops asking a person when the writer finds nothing a browser can check and a discriminating test
covers the criterion.

### D6. The safety net after a note

A note does not pass the criterion. Aggregation still needs an adequate, passing tracing test and the judge's `pass`
(L4-VER-003, `aggregate.aggregate_criterion`); step 9 reviews the adequacy of every tracing test, and a covering test it
calls inadequate leaves the criterion `needs_human` (`uncovered: the tests that trace it are inadequate or did not
pass`), which raises the criterion's own verdict question. So a criterion that needs a browser and is covered only by a
weak unit test is still asked about, once, through its criterion and not through a UI hold.

### D7. The e2e suite's support files for the writer (L4-VER-077)

`conventions.e2e_support_files(git, base_sha) -> E2eSupport{blocks, shown, skipped}`, read at the base only
(`git ls-tree -r -z <base> -- e2e`, `git show <base>:<path>`), as `test_conventions` and `base_test_header` are:

- **Which files.** The entries of `e2e/` (the directory of `testwriter.test_path("e2e", …)`) that are regular files
  (mode `100644` or `100755`; no link, no submodule), end in `.py`, are not test modules by pytest's default names
  (`test_*.py`, `*_test.py`; so never the harness's `test_l4_c_<hex>.py`), are not a `conftest.py` below `e2e/` (it does
  not apply to a test in `e2e/`), have no path part that starts with `.` or is `__pycache__` or `node_modules`, and are
  not empty (whitespace only).
- **Order and bounds.** `e2e/conftest.py` first, then the others by depth and path. Each is cut at
  `MAX_SUITE_FILE_CHARS = 8_000` characters, and files are taken in that order until `MAX_SUITE_FILES = 6` are taken
  or the next (as cut) would bring the total past `MAX_SUITE_CHARS = 20_000`; that file and every file after it are
  left out (as `audit.head_sources` stops at its total). The label is `<path> (e2e support file at the merge
  base)`, with `, first 8000 characters` before the `)` for a cut file; when files are left out, one more block
  labelled `e2e support files not shown` lists their paths, one per line.
- **Why the base.** The generated test runs at the merge base, and at head with the e2e runner's support files the unit
  changed at their base versions (L4-VER-035): what the writer is shown is what its test runs with. A helper the unit
  added is not at the base and is not shown. The files are the project's, not the unit's tests (L4-VER-002a holds).
- **Where.** `generate_ui_tests` reads them once per step (`git` and `base_sha` are its arguments) and hands the
  blocks to each `generate_ui_test(..., suite=…)`, which puts them after the page snapshot. `UiGeneration` gains
  `suite_files` (shown) and `suite_skipped`; step 5's note appends `; e2e support files shown to the writer: <n>`
  and `(+<m> not shown)` when files were left out.
- **The rule.** `_KIND_RULES["e2e"]` gains: "When e2e support files are shown, your test runs with them: use their
  fixtures by parameter name and import their helpers from the module that defines them (`from conftest import
  login`), with the arguments they take. Use no name they do not define." `TEMPLATE_VERSION` becomes 6
  (`testwriter@6`, shared with the audit kind, whose body does not change), and `templates.lock.json` is written again.
- **Size.** Today's user text is at most about 60,000 characters (diff and snapshot); this adds at most 20,000 and a
  list. The audit writer's prompt is already of that size (60,000 of source, 8,000 of spec, a header and conventions).
  No budget logic is needed and no configuration key is added.

*Considered and kept out:* the header of an existing e2e test (it would show the suite's imports but is a test, not
support); the repository root's `conftest.py` (whether pytest loads it depends on the suite's rootdir: a suite with its
own `pyproject.toml` under `e2e/`, as in the consumer run, has its rootdir there); a config key for the e2e directory
(the generated test's directory is fixed at `e2e/`).

### D8. Where the code goes

- `l4.verifier.ui_step`: `covered_by_step4` (D1); `unclosed_holds` skips an outcome with `covered_by`.
- `l4.verifier.types`: `GeneratedOutcome.covered_by`.
- `l4.verifier.generate`: `generate_ui_tests(covered=None)` sets `covered_by` (D2) and emits it; reads the support
  files (D7); `generate_ui_test(suite=())` appends the blocks; `UiGeneration.suite_files`, `suite_skipped`.
- `l4.verifier.ladder._generate_step`: computes `covered` in `body()` and passes it; the step note (D2, D7).
- `l4.verifier.report`: the Reason cell and `_generated_json`. `l4.verifier.evidence._generated`: the tuple and the
  default. `l4.verifier.fixunit`: the closed set.
- `l4.verifier.conventions`: `e2e_support_files`, `E2eSupport`. `l4.verifier.testwriter`: the e2e rule and
  `TEMPLATE_VERSION = 6`. `src/l4/templates.lock.json`.

## Risks / Trade-offs

- A criterion that a browser could check, which the writer wrongly calls `not_testable` and which a unit test covers,
  is no longer asked about as a UI hold. It is not passed by the note: the judge's adequacy review (D6) is what stands
  between it and a PASS, and the note, with the writer's reason, is in the generated UI tests table of
  `verification.md`. The judge is not told about the note (its prompt is unchanged).
- Each fresh round still asks the writer for every gap, a covered one included: the cost per round is today's.
- The support files make each writer prompt larger (at most 20,000 characters and a list), for each gap.
- A helper under `e2e/` that the unit changed and that the project's test and support globs do not match is not
  reverted for the head run (`runner_support` reverts only test-glob and support-glob paths), so the head run uses the
  unit's version while the writer saw the base's. A name the unit removed from it fails the test at head
  (`fails_at_head`), which holds the criterion as today.
- A suite whose fixtures live in the repository root's `conftest.py`, or whose helpers are not Python, gets no help
  from L4-VER-077; the generated test is a pytest-playwright file in any case.
- Showing the suite's support files may lead the writer to use a helper that needs state the base app does not have
  (a seeded user the unit adds). Such a test fails at the base by an error (`base_error`) or at head, and the criterion
  is held as today.
