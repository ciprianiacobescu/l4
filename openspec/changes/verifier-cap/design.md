## Context

`proposal.md` describes the incident. This change states the per-test cap where tests are tagged and checks it when a
test is written, makes the red remedies respect it, lets a proved test over the cap count for a criterion the judge
passed and named it for, and makes the question of a criterion that only the cap left uncovered say so. It is built
for 0.4.21 on top of the released 0.4.20 (da3e7c28).

Labels: [V] verified in the code at da3e7c28 (file:line) or in the consumer's round-1 record (read only, not named
here); [I] inferred; [U] unknown, not checked here.

How the incident happens in the code [V]:
- `trace_criteria` (`src/l4/verifier/traceability.py:145-198`) counts, per test, the unit's criteria it traces
  (`trace_ids(case) & known`, `:164`, `:179`). When that is more than `cfg.verifier.max_criteria_per_test` (`:165`,
  default 3, `src/l4/config/schema.py:663`), the test is ignored with `it traces N criteria
  (verifier.max_criteria_per_test=3)` for every criterion it traces, and the loop `continue`s before the proof is read
  (`:182-185`). A criterion whose only tests are such tests is `uncovered` (`:196`).
- The judge's matrix lists only counted tests (`_gate_summary`, `src/l4/verifier/ladder.py:339-348`): an uncovered row
  reads `no discriminating test`. The ignored tests reach `verification.md` and the question, never the judge. The
  judge's `test_adequacy` is applied to counted tests only (`apply_adequacy`, `traceability.py:201-216`, called at
  `ladder.py:1195`).
- An uncovered criterion is `needs_human` with `uncovered: no adequate discriminating test traces it` whatever the
  judge says (`src/l4/verifier/aggregate.py:66-73`; L4-VER-003). The question shows that reason and the ignored list
  (`src/l4/verifier/verdicts.py:507-543`).
- The implementer's tagging rule is `Tag every test with @pytest.mark.l4("C-xxxxxxxx") for each criterion id (listed
  below) that it checks` (`src/l4/implementer/result.py:136-139`; the name form `:151-155`), filled into
  `templates/contract.md:16`. No implementer template or module reads `max_criteria_per_test`
  [V: `git grep max_criteria -- src/l4/implementer src/l4/doctor` is empty].
- The zero-answer remedy (`Vacuity._zero_answer_remedy`, `src/l4/implementer/discrimination.py:521-537`) proposes
  `tag a test that asserts a real answer with <criterion> as well, for example <test>: @pytest.mark.l4("<other>",
  "<criterion>")`: the first proved test of another criterion, whatever ids it carries; the example drops its other
  ids; the form is pytest's under every gate. `red.md:13` says the same in the prompt (`{trace_also}`).
- `red.md:6` (L4-KSP-012): every criterion a Kiro leaf's `_Requirements:_` line names needs a new test in that step.

The brief named the remedy's file as `src/l4/verifier/discrimination.py`; it is `src/l4/implementer/discrimination.py`
[V]. "Umbrella criteria" is a pattern of the incident, not a harness concept [V: `git grep -i umbrella -- src docs
openspec` is empty].

The incident's record [V, round 1 of the consumer's unit, its `verdict.json` and test file at the round's head]:
- 29 criteria, 18 covered, 11 uncovered. Each of the 11 was traced only by tests over the cap: nine new tests of one
  task traced 5, 6 or 7 criteria. The task's `_Requirements:_` line named 16 criteria. Two of them (a list of commands
  that each test checks one row of, and a precondition every test shares) were on all nine tests; two more (lists over
  the writing commands) on six.
- Every one of those tests had a `red_assertion` proof for each criterion it traced, and passed.
- The judge passed 10 of the 11 and failed 1 (a real defect; it also marked that test `adequate: false` for it). Its
  `test_adequacy` held 2 entries in all. For 8 of the 10 passes, the verdict's evidence was a `test` item naming the
  criterion's own over-cap test; for the other 2, a file quote.

## Goals / Non-goals

Goals: an implementer knows the cap when it tags tests, and a red step that writes a test over it fails then, not at
verification. No harness text advises an id past the cap. A criterion the judge passed and named a proved test for is
not a person's question only because that test is over the cap, while a test that traces everything still proves
nothing. When the cap alone leaves a criterion uncovered, the question says so and names the fix.

Non-goals:
- Step 5 (`src/l4/verifier/e2e_trace.py:25`, `generate.py:180`) reads the cap on its own to pick the UI criteria it
  writes tests for; unchanged.
- A notion of umbrella criteria in specs (D4, rejected), or a readiness-review hint against them (follow-up).
- A change of the cap's default or a second key (D8).
- Over-cap tests that fail at head: today they are ignored, and the test gate of step 3 fails the unit anyway [V:
  `ladder.py:572-592`]; unchanged.

## D1. The cap is stated where tests are tagged (L4-VER-052)

Decision:
- `templates/contract.md` (version 12 → 13), the tagging line (`:16`), after `Untagged tests do not count towards any
  criterion.`: `A test that traces more than {max_criteria} of this unit's criteria counts for none of them
  (verifier.max_criteria_per_test), and the harness rejects a red step or test chore that writes one: give each test one behaviour and
  at most {max_criteria} ids, tag a test only with the criteria whose outcome it asserts, put a criterion that many
  tests touch (a precondition, or a list of commands) only on the tests that assert it directly, and write another test
  rather than add an id to a test that has {max_criteria}.` The contract goes into every role's prompt, so red, green,
  single and the test chore all read it [V: `_contract`, `prompt.py:134-146`, is the first part of every role's
  prompt, `:322`].
- `templates/red.md` (version 11 → 12): line 6 (the `_Requirements:_` rule) adds `With at most {max_criteria} ids per
  test, a line that names K criteria needs at least ⌈K/{max_criteria}⌉ tests.`; line 13 (the zero answer) adds `, when that test then
  carries at most {max_criteria} ids (else write a new test that asserts a real answer)` after `{trace_also}`. The Kiro rule is arithmetic (review decision): a leaf that cites K criteria, at N ids per test, needs at least ⌈K/N⌉ tests, so the prompt says so up front instead of leaving the agent to meet it at the cap check; the earlier draft's "more tests" gave no number.
- `PromptContext.max_criteria_per_test: int = 3`, set from `wb.cfg.verifier.max_criteria_per_test` in `tdd._prompt`
  (`tdd.py:715-740`); `_contract` and the phase fill replace `{max_criteria}` (`prompt.py:144-146`, `:265-269`).
- `single_tests.md` is not changed: the chore reads the contract's sentence, and its own line 7 already says to tag a
  test only when it checks the criterion's outcome.

Why the contract and not only the trace rule's code text: `TraceRules.rule` can be replaced by `PromptContext.
trace_rule` (`prompt.py:149-152`), and the cap must not vanish with it.

## D2. A test over the cap fails the step that writes it (L4-VER-052)

Decision:
- `over_cap_text(new_tests, unit_criteria, cap) -> str` (in `result.py`, beside `check_criteria`): for each new test,
  `n = len(trace_ids(case) & unit_criteria)`; the tests with `n > cap`, sorted, give `too many criteria on one test:
  <test> traces <n> of this unit's criteria (<ids, sorted>), more than verifier.max_criteria_per_test (<cap>), so the
  verifier counts it for none of them: split it into tests that each assert one behaviour and carry at most <cap> ids,
  and tag a test only with the criteria whose outcome it asserts`. Two or three tests are joined by `; `, the first
  three are named and `(+k more)` follows. Empty when none is over.
- The red step (`tdd.py:1182-1206`): right after `check_criteria` returns no error, with `unit_criteria = family`
  (`wb.provider.criteria(wb.ref)`, `:1168`) and the step's new tests (`new_ids`): a non-empty text discards the changes
  and returns `RedOutcome("failed", text)`. It runs before the pre-satisfied, base and zero-value runs and the second
  earlier-red check (`:1207`), so a rejected step costs no gate run beyond the red gate itself. The first earlier-red
  check (`confirmed_by_earlier_red`, `:1189`) comes before `check_criteria`; it reads the ledger and git and runs no
  gate [V: `src/l4/implementer/earlier_red.py:151-185`].
- The test chore (`tdd.py:2104-2113`): on the `added` tests, before the discrimination runs; a non-empty text is the
  step's `reason`.
- The criteria set is the one the verifier counts: step 4 traces `wb.provider.criteria(wb.ref)` (`ladder.py:528`) and
  the red step reads the same call [V]. Ids that are not the unit's do not count, as in step 4.
- Only the step's new tests: a test of an earlier task, of the base, or a person's is not checked, so a unit whose
  earlier steps were committed before this release is not failed for them [I: they are frozen and the agent could not
  split them].
- A browser test in `gates.e2e`'s directory is not in the red gate's report (`prompt.py:285-293`), so it is checked by
  step 4 only.

Alternatives rejected:
- A warning in the red step and nothing else: red tests freeze after red (L4-IMP-006), so the red attempt is the only
  time a test can still be split. A warning that the agent may ignore leads straight to the incident.
- Checking only at verification (today).

Cost: a rejected attempt counts towards `implementer.max_task_attempts` (3) and `escalate_after` (2) like any red
rejection. The contract states the rule up front and the retry text names the tests, so a second attempt has what it
needs [I].

## D3. The red remedies respect the cap (L4-VER-053)

Decision:
- `Vacuity` gains `traced: Mapping[str, tuple[str, ...]]` (test → the unit's criteria it traces, sorted), `cap: int`
  and `test_command: str`, set by `vacuity_check` from `real` (the red gate's report), `wb.provider.criteria(wb.ref)`
  and `wb.cfg`.
- `_zero_answer_remedy(criterion)` takes, among the tests of `proofs` for other criteria, the first (sorted by
  criterion, then test) whose `traced` has fewer than `cap` ids and does not hold `criterion`. It says `, or tag a test
  that asserts a real answer with <criterion> as well, for example <test>: <tag>` with `<tag> = tag_example(command,
  [*its ids, criterion])`. When no proved test has room it says `, or write a new test that asserts a real answer and
  tag it with <criterion> alone (every test that failed on the zero values already carries <cap> ids)`; when no test
  was proved it says what it says today.
- `tag_example(test_command, ids)` (in `result.py`): `@pytest.mark.l4("<id>", "<id>")` for a pytest gate (the
  `trace_rules` test), else `it("<id> <id>: …")`.
- `red.md:13`: D1.

Alternative rejected: drop the "as well" advice entirely. A test with room that already asserts a real answer is the
cheapest correct fix, and naming one concrete test is what made the advice work (live M1.7, the docstring at
`discrimination.py:522-525`).

## D4. A proved test over the cap counts when the judge named it (L4-VER-054)

Decision (option (a) of the brief, with a ceiling; option (b) rejected):
- Step 4: a test over the cap whose proof for the criterion `trace_criteria` would accept (a red record, an audit, a
  generated test, a `human` or `chore` proof, or pass-to-pass) and whose status is `passed` stays in `ignored` with
  today's reason and minor finding, and is also kept in `CriterionEvidence.capped` as a `TracingTest` with its proof,
  its L4-VER-051 note and `over_cap = n` (the number of the unit's criteria it traces). A test over the cap with no
  proof, or skipped, is not a candidate.
- After the judge (where `apply_adequacy` runs, `ladder.py:1195`), `count_named` moves a candidate `t` of criterion `C`
  into `C`'s tests when all of these hold:
  1. the judge's verdict for `C` (`pick_verdicts`, the worst of its answers) is `pass`;
    2. the judge named `t` for `C`: the reply has a `test_adequacy` entry `{test: t, criterion: C, adequate: true}`
     whose reason does not start with `not in this part`. A `test` evidence item `{kind: test, ref: t}` in `C`'s pass
     is not enough on its own (strict rule, review decision);
  3. no `test_adequacy` entry `{test: t, adequate: false}` names `C` or no criterion;
    4. `n <= min(M // 2, 3 * cap)`, with `n` the number of the unit's criteria `t` traces, `M` the number of criteria
     of the unit (`len(trace)`) and `cap` = `verifier.max_criteria_per_test`. The `3` is not configurable.
  The moved test keeps its proof and gets `adequate: True`; it leaves `C`'s `ignored`; an `uncovered` `C` becomes
  `covered`, and a `fail` stays `fail` (an in-cap test that fails at head wins, as in aggregation).
  The step 4 minor finding stays: the test is still over the cap, a quality matter.
- Nothing else changes a candidate: one the judge did not name, one it called inadequate, or one over the ceiling, stays
  ignored. `inadequate_findings` reads `tests` only, so a candidate the judge called inadequate raises no `the judge
  called a test inadequate` finding: it is no evidence either way, and the cap's minor finding already lists it.

Why this still prevents what the cap is for (a test that traces everything proves nothing about each criterion):
- The proof is the part the cap distrusts: one test that fails on the zero values proves every criterion it traces
  (the vacuity check needs one failing test per criterion, `discrimination.py:540-566`). Rule 2 replaces the trust in
  the tag with the judge's statement, for this criterion, that this test is what shows it. The tag alone, or the
  judge's pass alone, is never enough.
- Rule 2 is strict (review decision, replacing a first draft that also took the pass's `test` evidence item): a test
  counts only when the reply holds a `test_adequacy` entry for that test and that criterion marked adequate. An
  evidence item says where the judge looked; it is not a statement that the test shows this criterion, and the judge
  was never asked about the cap when it wrote it. judge@12 asks for an entry, true or false, for every over-cap
  candidate it reads, so the statement exists exactly when the judge made it.
- Rule 2 ignores entries whose reason starts with `not in this part` (review decision). In a diff judged in parts
  (`judge_parts.py`), a part that does not hold a test answers `{adequate: false, reason: "not in this part"}`, and
  `_sighted` (`judge_parts.py:54-58`) turns that into `adequate: true` in the merged reply so that a blind part never
  makes a test inadequate. For the rescue that flip would read as a judge naming the test, though no part that saw it
  said anything: a part that never saw the test cannot name it. `named_tests` skips such entries with the same test as
  `_seen_elsewhere` (the reason, stripped and lower-cased, starts with `not in this part`).
- Rule 4 is absolute: a test above the ceiling is a catch-all, and no judge can rescue it. The ceiling is
  `min(M // 2, 3 * cap)` (review decision): half the unit bounds small units (a test that traces every criterion is
  never evidence beyond the cap, SCN-VER-180, and in a unit of up to `2 × cap` criteria nothing over the cap can be
  rescued at all), and `3 * cap` bounds large ones, where half of the unit (14 of 29) is still not one behaviour. With
  the default cap the most a judge can make count is 9 criteria on one test. The multiple is not configurable: a
  project that wants more raises the cap, which the implementer then reads too (D8).
- Rule 1 and 3: the judge's own doubt wins; a criterion it did not pass is not touched.
- Going forward, the implementer cannot write such tests (D2). Candidates come from units written before this release
  (their red proofs), from tests whose criterion is unchanged from the base specs (`pass_to_pass`), from an
  `extra_proof` recorded while the test was within the cap, and from a project that lowered the cap; D4 is the net for
  them. A person's or a chore's test that is over the cap gets no discrimination run of its own: `extra_candidates`
  (`traceability.py:111-133`) queues only tests ignored for want of a proof (`NO_PROOF`), never for the cap [V]. So
  such a test is a candidate only through `pass_to_pass`; widening `extra_candidates` is a follow-up, not this
  change.

Why this keeps P7 and L4-VER-003: the rule can only turn `uncovered` into `covered`, never a pass into a fail; it needs
the deterministic proof and the passing run as well as the judge; and L4-VER-003's rows are unchanged (an uncovered
criterion is still `needs_human`; the row "covered + judge pass" applies because the trace changed before aggregation).

Numbers on the incident [I, from the record above]: under the strict rule the forecast depends on the judge following
judge@12. The incident's judge cited the over-cap test in the evidence of 8 passes but gave 2 `test_adequacy` entries
in all, and the strict rule does not count a citation. If a judge@12 judge answers an entry for the 8 (the tests trace 5
to 7 of 29; ceiling 9), they count: 8 of the 10 judge-passed criteria. Every miss falls back to a person question with
the text of L4-VER-055, which is the safe direction: the old behaviour, now with a better question. The 2 passed with a
file quote stay questions in either case. The judge-failed one stays a question with today's text. None of this is
verified until a live round runs judge@12.

Alternatives rejected:
- (a) keyed on `test_adequacy` or on the pass's `test` evidence item (the first draft): the evidence item is a citation,
  not a verdict on this test for this criterion, and a judge that cites a test for another reason would count it. Its
  advantage (it rescues what the old prompt's judge happened to cite) disappears once the prompt asks for entries.
- (a) with a ceiling of `2 × max_criteria_per_test`: rescues 5 of 10 in the incident, and in a unit of 5 criteria it
  would let a test that traces all 5 through. A share of the unit names "everything" directly.
- (a) with a ceiling of half the unit only (the first draft): in a unit of 29 it lets a test of 14 criteria count.
  `min(M // 2, 3 * cap)` keeps the share for small units and a hard bound for large ones.
- (a) with no ceiling: one catch-all test cited by a lenient judge would cover every criterion.
- The judge's pass of `C` alone, with any over-cap candidate: no statement links the test to `C`; it would have counted
  the 2 file-cited criteria too, on a test the judge never mentioned for them.
- (b) excluding umbrella criteria from the per-test count. OpenSpec and Kiro have no such marker, so either the spec
  author marks them (new syntax in two frameworks, and an author can mark anything) or the harness infers them. The
  only deterministic inference found is "an id already covered by an in-cap proven passing test does not count toward
  another test's total". Applied once to the incident it rescues 7 of 11 uncovered criteria; applied until nothing
  changes it rescues all 11, the judge-failed one included, because each rescue frees ids on the remaining tests. That
  fixpoint is exactly the catch-all test the cap exists to stop, and a single pass is an arbitrary stop. Both forms also
  ignore what the judge said.
- Both (a) and (b): (b)'s flaw remains.

## D5. The judge sees the candidates (L4-VER-054)

Without this, rule 2 never fires: the judge answers `test_adequacy` only for tests its matrix lists, and the matrix lists
counted tests only (the incident's judge gave 2 entries in all). So:
- `_gate_summary` (`ladder.py:339-348`): a criterion with candidates adds `; over the per-test cap: <test> (traces <n>
  criteria)` for up to 5 candidates, then `(+k more)`.
- `SYSTEM` (`judge.py:164-224`) gains one rule after the `test_adequacy` line: `A test that the traceability lines list
  under a criterion as over the per-test cap traces more criteria than the harness counts for one test. It counts for
  that criterion only when you pass the criterion and your test_adequacy has an entry for that test and that criterion
  with adequate true. Give one entry, true or false, for each such test you read: true only when the test asserts the
  observable outcome this criterion describes. Naming the test in the evidence of your pass is not enough.`
- `PROMPT_VERSION = 12` (`judge.py:35`), with the comment `12: the over-the-cap candidates and their rule
  (verifier-cap)`.
- `named_tests(verdict) -> (passed, named, rejected)` in `judge.py`: the criteria whose picked verdict is `pass`; the
  `(test, criterion)` pairs of `test_adequacy` entries with `adequate: true` (rule 2: no evidence items, and no entry
  whose reason starts with `not in this part`); the `(test, criterion or "")` pairs of rule 3.

## D6. Where it runs, what is recorded, and a resumed round (L4-VER-054)

- `count_named` runs in step 9 right after `apply_adequacy` (`ladder.py:1195`) and before `inadequate_findings`, on
  the merged verdict of all parts. Step 4's note (`N/M criteria covered`) and the matrix the judge reads are before it;
  `verification.md`, `verdict.json` and the questions are after it.
- `verdict.json` `trace[]` (`dataclasses.asdict`, `report.py:356`) gains `capped` and each test `over_cap`. A rescued
  test reads in `verification.md` as `<test> (passed, <proof>, over the per-test cap: traces <n> criteria, named by the
  judge)`; with an L4-VER-051 note the note comes first.
- A resumed round (`_resume`, `ladder.py:801-816`) reads the stored trace back and runs only step 10, so the rescue
  must survive the record: `evidence._evidence` (`evidence.py:140-143`) reads `note`, `over_cap` and `capped`. Today
  it drops `note` [V], so a resumed round also loses the L4-VER-051 labels: fixed here. A record of 0.4.20 or older has
  none of the keys and loads with no candidates; nothing is rescued in a round resumed from it.
- The audit sample (step 4a, `new_covered`) runs before the judge and reads step 4's trace: a rescued criterion is not
  in its pool. The label in `verification.md` is how a person tells a judge-named cover from a harness-proven one.
- `regressions` (a failing tracing test voids an accept, `verdicts.py`) reads `tests`; a candidate is a passing test,
  so it never adds a failing one.

## D7. The question of a criterion that only the cap left uncovered (L4-VER-055)

Decision:
- `aggregate_criterion` gets `cap: int = 3` (from `wb.cfg.verifier.max_criteria_per_test` in `_finalize`) and the
  unit's size from the caller. When no usable test is left, the judge's verdict is `pass`, and `trace.capped` is not
  empty, the reason is `uncovered: the judge passed it, and only the per-test cap left it uncovered: <test> traces <n>
  criteria, more than verifier.max_criteria_per_test (<cap>)<why>`, where `<why>` is `; it traces more than <C> of the unit's <M> criteria, the most the judge can make count` when `n > C` with `C = min(M // 2, 3 * cap)` (rule 4 wins: no answer of the judge could count it), else `; the judge
  did not confirm it for this criterion` (rule 2 or rule 3 kept it out: `aggregate_criterion` sees the picked verdict,
  not `test_adequacy`, so one wording covers "not named" and "named inadequate"), for the first candidate (sorted by
  `n`, then id) and `(+k more)` after it. `sdd.require_traceability: false` keeps its own suffix after this text.
- The question (`_criterion_question`, `verdicts.py:507-543`) keeps its lines and, for such a reason (it starts with
  `CAP_ONLY = "uncovered: the judge passed it, and only the per-test cap left it uncovered"`), adds before the answer
  line: `Fix: answer accept if <test> checks this criterion as its scenario says; or reject: give it its own test of at most <cap> ids (a reject fails the criterion and spends a fix round).`
- A criterion the judge did not pass, or with no candidate, keeps today's reason and question.

The fix text does not say `split <test>` (review decision): `<test>` is frozen (L4-IMP-006), nobody splits it. A
`reject` fails the criterion and spends a fix round, whose unit writes a new test of its own for the criterion, so the
text says `give it its own test of at most <cap> ids` and names the cost.

Why `reject` is the fix path: a rejected criterion is a `fail` (`aggregate.py:63-64`), so a fix unit is spawned
(L4-VER-006); its red step must write new tests for the criterion, and D2 keeps them within the cap.

## D8. Configuration and doctor

- `verifier.max_criteria_per_test` stays an integer of at least 1 with default 3 (`schema.py:663`). It is now read in
  three places: the implementer's prompt (D1), the red and chore checks (D2) and step 4 (unchanged). One value for all
  three is the point: the rule the agent reads is the rule that is checked.
- No new key: the ceiling of D4 (`min(M // 2, 3 * cap)`) follows the unit and the cap, not a number to tune; a project that wants more tests counted
  raises the cap, which the implementer then reads too.
- No doctor check: there is nothing deterministic to compare the cap against before a unit runs.
  `docs/eval-framework.md` row 15 already says how to tune it; its text gains the write-time check and the judge's
  exception.
- SPEC §3.2's comment of the key names L4-VER-052 and L4-VER-054.

## D9. Why VER ids for implementer-side rules

The cap is `verifier.*` configuration and its meaning is the verifier's (L4-VER-009). L4-VER-052 and L4-VER-053 state
that one rule at the time a test is written, so they sit beside it; the code they touch is in `l4.implementer`.

## D10. Docs, SPEC, CHANGELOG

- `docs/SPEC.md`: L4-VER-052 to L4-VER-055 after L4-VER-051; SCN-VER-170 to SCN-VER-189 after SCN-VER-157; the
  L4-VER-009 paragraph and step 4's row name the exception of L4-VER-054; the §3.2 comment; change-table row 59.
- `docs/eval-framework.md` row 15 and its tuning line.
- `docs/runbook.md` §7.1 (verdict questions): one bullet on a criterion question with the reason of L4-VER-055 (the
  text is in `tasks.md` 7.1).
- `src/l4/templates.lock.json`: regenerated (`python -m l4.templatelock --write`) for `implementer/contract`,
  `implementer/red` and `judge`; the judge's system text changes, so its lock hash and the single-part prompt hash
  (`SINGLE_SHA`, `tests/unit/verifier/test_prompt.py:149`) move as well.
- `CHANGELOG.md`: `## 0.4.21 (unreleased)` above `## 0.4.20 (2026-10-20)` (the lines are in `tasks.md`).

## Contracts (the tasks share these; do not change one without the orchestrator)

- `l4.implementer.result`:
  - `over_cap_text(new_tests: Mapping[str, TestCase], unit_criteria: Collection[str], cap: int) -> str` (D2 text).
  - `tag_example(test_command: str, ids: Sequence[str]) -> str` (D3).
- `l4.implementer.prompt.PromptContext.max_criteria_per_test: int = 3`; placeholder `{max_criteria}` in `contract.md`
  (v13) and `red.md` (v12).
- `l4.implementer.discrimination.Vacuity`: new fields `traced: dict[str, tuple[str, ...]]`, `cap: int = 3`,
  `test_command: str = "pytest"`.
- `l4.verifier.types`: `TracingTest.over_cap: int = 0`; `CriterionEvidence.capped: tuple[TracingTest, ...] = ()`.
- `l4.verifier.traceability`: `trace_criteria` fills `capped`; `count_named(evidence, *, passed: Collection[str],
  named: Collection[tuple[str, str]], rejected: Collection[tuple[str, str]], cap: int = 3) -> list[CriterionEvidence]`
  (D4 rules; the unit's size is `len(evidence)`); `rescue_ceiling(unit_size: int, cap: int) -> int` =
  `min(unit_size // 2, 3 * cap)`, shared with `aggregate_criterion`; `OVER_CAP_LABEL = "over the per-test cap"`.
- `l4.verifier.judge`: `PROMPT_VERSION = 12`; `named_tests(verdict: JudgeVerdict) -> tuple[frozenset[str],
  frozenset[tuple[str, str]], frozenset[tuple[str, str]]]`.
- `l4.verifier.aggregate`: `CAP_ONLY` (D7); `aggregate_criterion(..., cap: int = 3, unit_size: int = 0)`.
- Texts: D1, D2, D3, D5 and D7, word for word.

## Collisions

- Three other drafts run beside this one and take other VER ranges. Each may add requirements after L4-VER-051,
  scenarios after SCN-VER-157, a change-table row (this one says 59; whoever merges second takes the next number) and
  `## 0.4.21 (unreleased)` in CHANGELOG (whoever merges second keeps one heading and merges the lists under the same
  subheadings).
- Prompt versions: a draft that also edits `contract.md`, `red.md` or the judge's system text takes the next number
  after whichever merges first; the version pins in the tests move with it.

## Risks

- A model that keeps over-tagging burns its attempts and the task halts after `max_task_attempts`. The contract states
  the rule first, and the retry names the tests and the split.
- A lenient judge can name an over-cap test it did not read. Rule 4 bounds the damage to tests that trace at most
  `min(M // 2, 3 * cap)` criteria, the label shows such covers to a person, and the proof is still deterministic.
- A unit committed before this release keeps its over-cap tests; its next round now asks the judge about them (judge@12)
  and rescues the named ones. That is the intended effect on in-flight units.
- The judge prompt grows by one line per criterion with candidates (at most 5 test ids each).
- A judge that ignores the judge@12 rule and gives no entries rescues nothing; the criteria stay person questions with
  the L4-VER-055 text. That is the safe direction, and the live round is where it is measured.

## Follow-ups

- A discrimination run for a person's or a chore's test that is over the cap (`extra_candidates` queues only tests
  with no proof), so that it can earn a `human` or `chore` proof and become a candidate.
- A readiness-review hint (skill `spec.md`) against criteria that every test would touch: a precondition, or one
  criterion over a list of commands.
- The earlier-red path (`src/l4/implementer/earlier_red.py:151-185`) has no cap check: a step confirmed by an earlier
  red never reaches the check of D2.
- A criterion rescued by the judge is never in the audit sample of step 4a (the audit runs before the judge and reads
  step 4's trace), so no deterministic audit looks at a judge-named cover.
- Rule-2 evidence comes only from the first passing part of a diff judged in parts: another part's entries are not
  read for the rescue.

- Step 5's own cap read (`e2e_trace`), and over-cap browser tests at write time.

## Open questions (each with the recommended answer)

1. Option (a), (b) or both? Recommended and taken: (a) with the judge's `test_adequacy` entry and the ceiling
   `min(M // 2, 3 * cap)` (D4,
   L4-VER-054, SCN-VER-178 to SCN-VER-182); (b) rejected.
2. Does a red step over the cap fail or warn? Recommended and taken: fail the attempt, before the discrimination runs
   (D2, L4-VER-052, SCN-VER-171).
3. Does the check cover test chores? Recommended and taken: yes, on the added tests (D2, SCN-VER-173).
4. Is the ceiling configurable? Recommended and taken: no (D8).
5. Does the judge get a new prompt? Recommended and taken: yes, one rule and the candidates in the matrix, version 12
   (D5, SCN-VER-183).
6. Does the step 4 minor finding stay for a rescued test? Recommended and taken: yes (D4).
