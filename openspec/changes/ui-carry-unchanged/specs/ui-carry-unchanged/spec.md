## Purpose

A UI criterion that the unit did not change, whose tests are the base's and pass, is carried from the base instead of
becoming a step-5 gap that can only end as a hold; the carry is listed, and every doubt keeps today's path.

## ADDED Requirements

### Requirement: L4-VER-086 A UI criterion that the unit did not change is carried from the base
Before step 5 asks the writer about a UI criterion with a gap, and after the waiver of L4-VER-067, the criterion SHALL
be *carried from the base* when all of these hold:
- it is unchanged on the base by the pass-to-pass rule of L4-VER-009, read from the same baseline step 4 traced with
  (the archived specs read from git at the unit base, or a Kiro follow-up's merged parent: its id with the same text
  after `normalise`); no other matching;
- its evidence in the round's trace as step 5 starts is `covered` with no `held` reason; every test that traces it
  passed, has the proof `pass_to_pass`, carries no label of an unproven record, is within the per-test cap and is
  adequate; and every test listed as not evidence for it is a passing candidate over the cap;
- the file of every such test, listed or not, is found in the work tree by `file_of_id` over the tree's files, no other
  file of the tree could be the one the id names, it is not among the files the unit changed since its merge base, and
  the dotted Python module reading of the id agrees: it gives the same file, or it finds no module and the file is not
  a `.py` file (a TypeScript test);
- no `human.verdict` with the decision `reject` targets the criterion or one of its UI holds in the unit's ledger,
  consumed or not.
A carried criterion SHALL get no writer call and no hold. It SHALL record `verify.generated{criterion, status:
carried, covered_by: [<its tracing tests>], attempts: 0}` and the outcome in `verdict.json`; its row of the generated
UI tests table SHALL say `carried from the base: <ids> (the scenario and these tests are the base's, and they pass); a
note, not a hold (L4-VER-086)`; step 5's note SHALL count the carried criteria; its minor gap finding SHALL stay and
say that the criterion is unchanged on the base and step 5 generates none; no fix unit SHALL be made for that finding;
and when every gap is waived or carried nothing SHALL be checked out. A carry SHALL NOT pass the criterion: it still
needs an adequate passing tracing test and the judge's pass (L4-VER-003). A carry SHALL write no answer and waive
nothing for a later round. A reused round SHALL keep the stored outcome and decide nothing again. When a condition
cannot be checked (the baseline, a test's file, the changed files), the criterion SHALL stay a gap as before.

#### Scenario: SCN-VER-343 (+) An unchanged UI criterion with the base's passing tests is carried
- **Given** a unit that changed a web file, and its UI criterion C whose scenario the archived specs at the base hold
  word for word, traced only by `tests/test_rules.py::test_c`, which passed with the proof `pass_to_pass` and whose file
  the unit did not change, with no end-to-end test
- **When** step 5 runs
- **Then** the writer is not asked about C, `verify.generated` records `status: carried` with `covered_by:
  [tests/test_rules.py::test_c]`, the generated UI tests table says `carried from the base`, no hold is raised for C,
  its minor gap finding says it is unchanged on the base, and nothing is checked out when C was the only gap; with a
  second gap that goes to the writer, only that gap is written for, and no UI hold is raised for C after the judge
  step either

#### Scenario: SCN-VER-344 (−) A scenario with a changed word is not carried
- **Given** the unit of SCN-VER-343, where C's scenario text differs from the base's by two words
- **When** step 5 runs
- **Then** C is a gap as before: its test is not `pass_to_pass` evidence, the writer is asked, and an outcome that is
  not accepted raises C's UI hold

#### Scenario: SCN-VER-345 (−) A test the unit added or changed keeps the hold
- **Given** the unit of SCN-VER-343, where the unit also added a test of C to a new file, or changed
  `tests/test_rules.py`
- **When** step 5 runs
- **Then** C is not carried, and step 5 asks the writer and holds C as before

#### Scenario: SCN-VER-346 (−) Any other proof, a failing or skipped test, or a file not found keeps the hold
- **Given** four variants of SCN-VER-343: a second tracing test of C with a red proof; `test_c` failing at the head;
  a skipped tracing test of C; and a tracing test whose file is not found
- **When** step 5 runs
- **Then** none of them carries C; each follows the path of 0.4.59 (a note of L4-VER-067 only where its own rule holds,
  else the writer and the hold)

#### Scenario: SCN-VER-347 (−) A reject is never passed by
- **Given** the unit of SCN-VER-343, whose ledger holds a reviewer's reject of C's UI hold from an earlier round, in
  force or consumed by a fix unit
- **When** step 5 runs
- **Then** C is not carried, its UI hold is raised when step 5 does not close it, and a reject in force turns it into
  the finding of L4-VER-013

#### Scenario: SCN-VER-348 (−) A carry does not pass the criterion
- **Given** the carried criterion of SCN-VER-343, and a judge that calls `test_c` inadequate for C
- **When** the round is aggregated
- **Then** C is `needs_human` and asked through its own verdict question, and no UI hold is raised for it

#### Scenario: SCN-VER-349 (+) A reused round keeps the carry, and a hold asked before the upgrade is superseded
- **Given** the round of SCN-VER-343, reused by the next round, and a unit whose earlier round (0.4.59) asked C's UI
  hold, left open, before a fresh round under this harness carries C
- **When** the rounds end
- **Then** the reused round restores `status: carried`, asks no writer and raises no hold; the fresh round supersedes
  the open question by its round and asks nothing about C's hold

#### Scenario: SCN-VER-351 (−) A test whose file is in doubt keeps the hold
- **Given** the unit of SCN-VER-343 with the work tree `src/pricing/total.py` and `src/pricing/total.test.ts`, and C
  traced only by `src.pricing.total.test.ts::x`, a passing `pass_to_pass` test whose file the unit changed; or C traced
  by `tests.test_a::x` where both `tests/test_a.py` and `pkg/tests/test_a.py` are in the tree and the second is the one
  the unit changed; or C traced only by `src.pricing.total.test.ts::x` with a second `.test.ts` that could hold it
- **When** step 5 runs
- **Then** C is not carried: the module walk reads the first id as `src/pricing/total.py`, which the unit did not
  change, and the other reading names the changed test file, so the two disagree; the second id could be either module;
  the third could be either `.test.ts`; step 5 asks the writer and holds C as before. A changed `.test.ts` is refused
  like any changed file. Carried as in SCN-VER-343 are the plain case (`tests/test_a.py` read as the same file by both
  readings with no other file of that name) and a criterion traced only by one unchanged `.test.ts` that no Python
  module of its stem accompanies, whose module walk finds nothing
