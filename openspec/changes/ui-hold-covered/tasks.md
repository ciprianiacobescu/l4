Run only the test files a task names, once each when it is done (the machine is shared; CI runs the full suite). At
most two pytest runs at a time; never a `while pgrep` loop or a chain of sleeps. Never `git add -A`: stage the paths
you changed.

## 1. A covered criterion the writer cannot test is a note (L4-VER-067 amendment; design D1 to D6)

- [x] 1.1 Write the tests first, in `tests/unit/verifier/test_ui_step.py` (pure, with its `crit` helper and
  `CriterionEvidence`/`TracingTest` built by hand):
  - SCN-VER-298 and SCN-VER-299, `covered_by_step4(trace)`: a criterion `covered` with a passing `zero_value` test maps
    to that id; so do `pre_satisfied`, `red_assertion`, `repair`, `audit`, `generated`, `human` and `chore`; with two
    covering tests and a `pass_to_pass` one, only the two, sorted. Not in the map: only `pass_to_pass` tests; a test
    with a `note` (`not applicable: no project code`, `accepted by Q-001: the check was inconclusive`); state `fail`;
    state `uncovered`; `held` set (a failed audit test); a test with `adequate=False` or `over_cap > 0` and no other.
  - SCN-VER-298, `unclosed_holds`: of two gaps whose outcomes are `not_testable`, the one with `covered_by` raises no
    hold and the other raises `ui_hold_text` of its criterion.
  - SCN-VER-300, `unclosed_holds`: an outcome of each status `writer_failed`, `uncollectable`, `fails_at_head`,
    `non_discriminating`, `base_error`, `base_unservable`, `lint_failed` is a hold, also when it is given a
    `covered_by` by hand (only `not_testable` with `covered_by` is closed); no outcome at all (no writer) is a hold.

  Then: `src/l4/verifier/types.py` `GeneratedOutcome.covered_by: tuple[str, ...] = ()` with a comment (`not_testable`:
  the step-4 tests that cover the criterion; a note, no hold, L4-VER-067); `src/l4/verifier/ui_step.py`
  `covered_by_step4` (D1, docstring naming the proofs that count and why `pass_to_pass` and labelled records do not)
  and `unclosed_holds` closing `status == "not_testable" and covered_by`. The test at `test_ui_step.py:125`
  (SCN-VER-252, the hold id whatever the status) stays as it is: its outcomes have no `covered_by`.

- [x] 1.2 `src/l4/verifier/generate.py` (D2). Tests first, in `tests/unit/verifier/test_generate.py` with its `web`
  bench and `Writer`, calling `generate_ui_tests(bench.wb, writer, [CRITERION], base_sha=base, ui_diff=…,
  snapshot=…, covered=…)`:
  - SCN-VER-298: a `not_testable` reply with `covered={CID: ("tests.test_x::test_a",)}` gives an outcome with that
    `covered_by` and one `verify.generated` whose `covered_by` is `["tests.test_x::test_a"]`; without `covered` (or with
    an empty map) the outcome has `()` and the event has no `covered_by` key; a `not_testable` on the second attempt
    after an invalid first reply is covered the same way.
  - SCN-VER-300: a test that fails at head twice (`WRONG`, `WRONG`) with `covered` for the criterion gives
    `fails_at_head` with no `covered_by`, and the event has no `covered_by` key.

  Then `generate_ui_tests(..., covered: Mapping[str, Sequence[str]] | None = None)`: after `generate_ui_test` returns,
  `done = dataclasses.replace(done, covered_by=tuple(covered[cid]))` when `done.status == "not_testable"` and
  `covered.get(cid)`; the `verify.generated` emit adds `covered_by=list(done.covered_by)` only when it is not empty.
  The docstring of the module says the event may carry `covered_by`.

- [x] 1.3 The readers (D2, D3). Tests first:
  - `tests/unit/verifier/test_report_m15.py`: a result whose `generated` holds `GeneratedOutcome(CID, "not_testable",
    reason="pure functions", covered_by=("tests.a::t1", "tests.a::t2", "tests.a::t3", "tests.a::t4"))` renders the row
    `| C-… | not_testable | … | pure functions; covered by step 4: tests.a::t1, tests.a::t2, tests.a::t3 (+1 more); a
    note, not a hold (L4-VER-067) | … |`; an outcome without `covered_by` renders as today; `verdict_json` stores
    `covered_by` as a list (SCN-VER-298).
  - `tests/unit/verifier/test_resume.py`: `restore_round` of a `verdict.json` with that outcome gives back
    `covered_by` as the same tuple (equal outcomes), and of a record whose generated entry has no `covered_by` key gives
    `()` (SCN-VER-301).
  - `tests/unit/verifier/test_fixunit.py`, next to `test_a_ui_gap_waived_by_an_accepted_answer_spawns_no_fix_unit`: a
    PASS result with `fix_minor` and a UI gap finding whose criterion's outcome is `not_testable` with `covered_by`
    spawns no fix unit; the same outcome without `covered_by` does (SCN-VER-302).

  Then: `src/l4/verifier/report.py` `_generated_rows` (the Reason cell: the writer's reason, `; covered by step 4: `,
  the first three ids joined by `, `, ` (+n more)` past three, `; a note, not a hold (L4-VER-067)`; the `support:`
  part stays where it is today) and `_generated_json` (`data["covered_by"] = list(g.covered_by)`);
  `src/l4/verifier/evidence.py` `_generated` (`"covered_by": tuple(d.get("covered_by") or ())`);
  `src/l4/verifier/fixunit.py` (`closed` adds `o.covered_by`, comment naming L4-VER-067's note);
  `src/l4/verifier/ladder.py` `_generate_step.body`: `covered = covered_by_step4(result.trace)` before
  `generate_ui_tests`, which gets `covered=covered`; the note appends `; <n> not_testable covered by step 4: notes, no
  hold (L4-VER-067)` when `n` (outcomes with `covered_by`) is at least 1. Nothing in `_resume`, `restore_round` or
  `_finalize` computes `covered_by_step4` (D3): a reused round keeps what the round stored. The `_generate_step`
  docstring says so.

- [x] 1.4 Flows (`tests/unit/verifier/test_ui_flow.py`, `tests/unit/verifier/test_memory_flow.py`). In the fixture unit
  both criteria are covered by step 4 with `zero_value` tests (`tests.test_discount::test_known_code`,
  `tests.test_discount::test_unknown_code`; checked on amaster with a probe run of the flow below: the evidence row of
  C-d80f494d reads `covered | tests.test_discount::test_unknown_code (passed, zero_value)` and the run exits 11 on its UI
  hold alone). So every flow that relied on a `not_testable` reply to raise a hold changes:
  - Rewrite `test_a_criterion_the_writer_calls_not_testable_stays_uncovered_and_the_unit_waits_for_a_human` as
    SCN-VER-298 (name it `test_a_covered_criterion_the_writer_calls_not_testable_is_a_note_and_the_unit_passes`): exit
    0; `verify.generated` of UNKNOWN is `not_testable` with `covered_by == ["tests.test_discount::test_unknown_code"]`;
    `verification.md` has the row `| C-d80f494d | not_testable |` with `covered by step 4:
    tests.test_discount::test_unknown_code; a note, not a hold (L4-VER-067)`, no `UI criterion C-d80f494d has no
    end-to-end test; see` and no `## Needs a human`; step 5's note has `1 not_testable covered by step 4`; the
    accepted test of KNOWN is still committed.
  - Add SCN-VER-300's flow: the UNKNOWN reply is a file with no test (`{"criterion": UNKNOWN, "code": "import
    pytest\n"}`; the fixture has no lint gate, so no test of it runs at the merge base and it ends `uncollectable` on
    the first attempt): exit 11, the UI hold of UNKNOWN is raised, and its outcome has no `covered_by`.
  - In `test_a_generated_test_and_an_accepted_hold_of_an_earlier_round_are_not_run_or_asked_again`, and in
    `test_memory_flow.py`'s `test_nothing_is_curated_when_the_final_pass_was_not_reached` and
    `test_the_round_that_closes_the_gap_is_the_one_that_curates`, replace the `not_testable` reply `refuse` by that
    no-test file, so that round 1 still raises the hold those tests are about; the expected `verify.generated` list
    of the first one becomes `[(KNOWN, "accepted"), (UNKNOWN, <that status>), (UNKNOWN, "waived")]`.
  - Add SCN-VER-301's flow: round 1 is `[red_step(), web_green(), <no-test file for KNOWN>, <not_testable for
    UNKNOWN>, JUDGE]` (KNOWN held, UNKNOWN noted, exit 11, one question); a person accepts it
    (`edit_questions_on_origin(..., answer="accept: a unit test covers it")`) with no other commit; the second run, with
    an empty script, reuses round 1 (its steps read `reused (round 1)`), calls no agent, raises no question and exits
    0; its `verdict.json` has UNKNOWN's outcome with the same `covered_by` and no hold of UNKNOWN.
  - Add SCN-VER-303's flow: the note of SCN-VER-298 with `JUDGE` replaced by `judge_reply([KNOWN, UNKNOWN],
    test_adequacy=[{"test": "tests.test_discount::test_unknown_code", "criterion": UNKNOWN, "adequate": False,
    "reason": "it does not open the page"}])`: exit 11, the criterion row of UNKNOWN is `needs_human` with `uncovered:
    the tests that trace it are inadequate or did not pass`, one `question.raised` names UNKNOWN, and none is a UI hold.

## 2. The e2e suite's support files for the writer (L4-VER-077; design D7)

- [x] 2.1 Write the tests first, in `tests/unit/verifier/test_conventions.py` (its `commit` helper and a small git
  repository), against `e2e_support_files(git, base_sha)`:
  - SCN-VER-304: with `e2e/conftest.py`, `e2e/helpers/a11y.py`, `e2e/test_sign_in.py` and `e2e/pages/x_test.py` at the
    base, and a head commit that changes `e2e/conftest.py` and adds `e2e/helpers.py`, the blocks are `e2e/conftest.py`
    (the base text) then `e2e/helpers/a11y.py`, labelled `<path> (e2e support file at the merge base)`; `shown` lists
    the two paths, `skipped` is empty.
  - SCN-VER-305: an `e2e/conftest.py` of 30,000 characters and nine 5,000-character helpers give the conftest cut at
    8,000 (label `… (e2e support file at the merge base, first 8000 characters)`), the first two helpers by path, and a
    last block `e2e support files not shown` listing the other seven; eight 1,000-character helpers give six blocks and
    a list of two.
  - SCN-VER-306: test modules only, a committed symlink `e2e/link.py`, an empty `e2e/__init__.py`, `e2e/.venv/x.py`
    (added with `git add -f` if ignored), `e2e/__pycache__/y.py` and `e2e/admin/conftest.py` give no block and empty
    `shown` and `skipped`; a base with no `e2e/` gives the same.

  Then `src/l4/verifier/conventions.py`: `E2eSupport` (frozen: `blocks: tuple[tuple[str, str], ...]`, `shown`,
  `skipped`), `MAX_SUITE_FILES = 6`, `MAX_SUITE_FILE_CHARS = 8_000`, `MAX_SUITE_CHARS = 20_000` and
  `e2e_support_files` as design D7 says (`git ls-tree -r -z <base> -- e2e` read with its modes, `_show` for the text,
  the directory taken from `testwriter.test_path("e2e", …)`'s parent or a shared constant, not a new config key). The
  module docstring names the function.

- [x] 2.2 The writer gets them (`src/l4/verifier/generate.py`, `src/l4/verifier/testwriter.py`,
  `src/l4/verifier/ladder.py`). Tests first:
  - `tests/unit/verifier/test_generate.py`, SCN-VER-304: a bench whose base has an `e2e/conftest.py` defining `login`
    and whose head changes it (extend `stage_base_and_head` in `tests/unit/_web_bench.py` with optional extra base and
    head files, defaults unchanged) and a `not_testable` writer: `writer.prompts[0]` holds the base text of
    `e2e/conftest.py` after the page snapshot and not the head text; `UiGeneration.suite_files ==
    ["e2e/conftest.py"]`; a bench without the file gives a prompt with no `e2e support file` label.
  - `tests/unit/verifier/test_testwriter.py`: `TEMPLATE == "testwriter@7"` (done at 6, raised by 4.3); the e2e system
    text holds the new rule; the audit system text is unchanged. `tests/unit/verifier/test_testwriter_weak.py:141`
    pins `TEMPLATE_VERSION == 6`.
  - The ladder note: in the SCN-VER-298 flow of 1.4, step 5's note has no `e2e support files shown` part (the fixture
    has none); add one assert in a flow with an `e2e/conftest.py` at the base, or a unit test of the note text, that it
    reads `e2e support files shown to the writer: 1`.

  Then: `generate_ui_tests` calls `e2e_support_files(wb.git, base_sha)` once, before `base_checkout`, passes
  `suite=support.blocks` to each `generate_ui_test`, which appends them to its `blocks` after `page snapshot`, and
  sets `UiGeneration.suite_files`/`suite_skipped`; `_generate_step.body` appends `; e2e support files shown to the
  writer: <n>` and ` (+<m> not shown)` when `m`; `testwriter._KIND_RULES["e2e"]` gains the rule of design D7 word for
  word, `TEMPLATE_VERSION = 6` (7 after 4.3) with the comment `# 6: the e2e writer may use the e2e suite's support files shown
  (L4-VER-077)`; then `uv run --frozen python -m l4.templatelock --write` and check that `src/l4/templates.lock.json`
  changed only in the two `testwriter/*` entries.

## 3. Documents and checks

- [x] 3.1 The spec commit has SPEC.md (L4-VER-067 amended, L4-VER-077, the step-5 row of L4-VER-002, the
  `verify.generated` entry of §12.1, SCN-VER-298..306, row 124) and the CHANGELOG bullet. Check each against the code as
  built (the names, the event field, the row text, the note text, the bounds, the rule's words) and correct the text
  where the code had to differ.
- [x] 3.2 `docs/runbook.md`, the entry of the hold `UI criterion C-… has no end-to-end test` (about line 1074): say that
  from 0.4.56 a UI criterion that a discriminating test of step 4 covers and that the writer calls `not_testable` raises
  no hold (its row says `covered by step 4`), and that the writer is shown the suite's `e2e/conftest.py` and helpers at
  the merge base.
- [x] 3.3 Run once each: the test files changed in 1 and 2 (`test_ui_step.py`, `test_generate.py`, `test_report_m15.py`,
  `test_resume.py`, `test_fixunit.py`, `test_ui_flow.py`, `test_memory_flow.py`, `test_conventions.py`,
  `test_testwriter.py`, `test_testwriter_weak.py`), `tests/unit/test_template_lock.py`, `tests/unit/docs`; `uv run
  --frozen python scripts/check_spec.py docs/SPEC.md`; `ruff check` and `ruff format --check` on the changed files;
  `openspec validate ui-hold-covered --strict`. Report the counts.

## 4. Review findings

- [x] 4.1 A note whose basis step 9 removes (L4-VER-067, SCN-VER-307; design D6). Tests first: `test_ui_step.py`
  (`lost_notes`: a `zero_value` test the judge rejected beside a `pass_to_pass`, an unproved-red or a `no project code`
  test gives the criterion; no hold when the basis stands, when the rejected test is alone (SCN-VER-303), when all are
  inadequate, a test fails, a `held` reason is set, no note was taken, or another covering test is left) and
  `test_ui_flow.py` (two flow variants, a second tracing test `pass_to_pass` or an unproved red record: exit 11 and the
  hold in `verdict.json` where the code before this task passed the unit). Then `ui_step.lost_notes`, `_Run.recheck_notes`
  and `_generate_step.recheck`, called by `verify_unit` after step 9.
- [x] 4.2 `e2e/__init__.py` at the base: `conventions.e2e_support_files` adds the one-line block `e2e suite layout`
  (`from e2e.conftest import <name>`) when it shows a file; the writer's rule no longer hard-codes `from conftest import`;
  `testwriter@7` and `templates.lock.json` written again; the pinned-version tests and the SPEC text say 7.
- [x] 4.3 `e2e_support_files` reads no file after one is left out, and the block lists the first 20 left-out paths and
  `(+n more)`; tests for the merge-base listing, for a file that does not fit and the files after it, for the conftest
  first, and for the reads.
- [x] 4.4 The reason for leaving out `pass_to_pass` is "not shown discriminating per L4-VER-009" (design D1); `fixunit`
  closes a gap on `status == not_testable and covered_by`, as `unclosed_holds` does.
