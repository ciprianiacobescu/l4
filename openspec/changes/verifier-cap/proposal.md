## Why

A consumer's unit with 29 criteria ended its first verification round NEEDS_HUMAN on 2026-10-20: 18 of 29 criteria
covered, 40 findings, and 11 criterion questions for a person. The judge had passed 10 of those 11 criteria. A person
checked each against the code and accepted all 10; the eleventh was a real defect, which the judge had failed too.

The cause is `verifier.max_criteria_per_test` (default 3). Step 4 ignores every test that traces more than 3 of the
unit's criteria, for every criterion it traces, before it even looks for the test's proof
(`src/l4/verifier/traceability.py:179-185`). All 11 criteria were traced only by such tests (5, 6 or 7 criteria each),
and every one of those tests had a red-phase proof and passed. So each criterion was `uncovered`, and an uncovered
criterion is a person's question whatever the judge says (L4-VER-003). The question said `uncovered: no adequate
discriminating test traces it`, and listed the test under "Ignored tests" with `it traces 5 criteria
(verifier.max_criteria_per_test=3)`: nothing said that the judge had passed the criterion or that the cap was the only
gap.

Nothing told the implementer about the cap while it wrote the tests:
- The tagging rule says to tag every test with each criterion id it checks (`src/l4/implementer/result.py:136-139`,
  `templates/contract.md:16`) and never names the cap. No implementer template or code reads
  `verifier.max_criteria_per_test`.
- The red phase's zero-answer remedy advises tagging a test that asserts a real answer with the criterion "as well"
  (`src/l4/implementer/discrimination.py:521-537`, and its twin in `templates/red.md:13`), whatever that test already
  carries. Its example shows two ids even when the test has three, and is the pytest form under every gate.
- A Kiro leaf's `_Requirements:_` line needs a new test for every criterion it names (L4-KSP-012, `red.md:6`). The
  consumer's task named 16 criteria; its 9 new tests carried them, two ids on all 9 tests (a list of commands and a
  precondition every test shares) and two more on 6.

## What Changes

- **The cap is stated and checked when a test is written** (L4-VER-052). The harness contract states the cap with its
  configured value next to the tagging rule: one behaviour per test, at most N ids, tag only the criteria whose outcome
  the test asserts, put a criterion that many tests touch only on the tests that assert it directly, and write another
  test instead of adding an id to a full one. `red.md` says the same where it names the `_Requirements:_` line and the
  zero-answer case. A red step (and a test chore) whose new test traces more than N of the unit's criteria fails its
  attempt before any discrimination run, with a text that names the test, its ids, the cap and the split. Tests that
  existed before the step are not checked.
- **The red remedies respect the cap** (L4-VER-053). The zero-answer remedy proposes only a proved test that still has
  room, shows that test's whole id list plus the new one in the gate's own form, and otherwise says to write a new test.
- **A proved test over the cap that the judge named for a criterion is evidence for it** (L4-VER-054). Step 4 keeps a
  passing, proved test over the cap as a candidate (it stays ignored, with its minor finding). The judge's matrix lists
  the candidates and its system text says how one counts (judge prompt version 12). After the judge, a candidate counts
  for a criterion only when the judge passed that criterion and named that test for it (a `test_adequacy` entry with
  `adequate: true`, or a `test` evidence item of the pass), no `adequate: false` entry rejects it, and the test traces
  at most half of the unit's criteria. A test that traces everything stays no evidence, whatever the judge says.
  `verification.md` labels such a test, and a resumed round keeps it.
- **A criterion that only the cap left uncovered says so** (L4-VER-055). Its outcome reason and its question say that
  the judge passed it, that only the per-test cap left it uncovered, why the candidate did not count, and the fix:
  `accept` if the test checks the criterion, or `reject: split <test>` so that a fix unit writes a test of at most N
  criteria for it.
- **Configuration**: `verifier.max_criteria_per_test` stays as it is (default 3, at least 1), now read by the
  implementer's prompt and the red check as well. No new key, no new doctor check.
- **Docs**: SPEC (L4-VER-052 to L4-VER-055, SCN-VER-170 to SCN-VER-189, L4-VER-009 and step 4's row name the
  exception, the §3.2 comment of the key, change-table row 59), `docs/eval-framework.md` row 15, the runbook's verdict
  questions (§7.1), and CHANGELOG `## 0.4.21 (unreleased)`.

With these rules the consumer's round would have counted 8 of the 10 judge-passed criteria (the judge cited the over-cap
test for 8 of them; the prompt now asks for that explicitly), and asked 3 criterion questions instead of 11: two with
the new text, and the real defect with today's. A unit written after this change would not have such tests at all: its
red steps refuse them.

## Impact

- Code: `src/l4/implementer/templates/contract.md` (version 13) and `red.md` (version 12);
  `src/l4/implementer/prompt.py` (`PromptContext.max_criteria_per_test`, the `{max_criteria}` fill);
  `src/l4/implementer/result.py` (`over_cap_text`, `tag_example`); `src/l4/implementer/tdd.py` (the red check after
  `check_criteria`, the chore check on the added tests, the cap into the prompt);
  `src/l4/implementer/discrimination.py` (`Vacuity` knows each test's ids, the cap and the gate's form);
  `src/l4/verifier/types.py` (`TracingTest.over_cap`, `CriterionEvidence.capped`); `src/l4/verifier/traceability.py`
  (candidates, `count_named`); `src/l4/verifier/judge.py` (system text, `PROMPT_VERSION = 12`, `named_tests`);
  `src/l4/verifier/ladder.py` (the matrix lines, `count_named` after `apply_adequacy`, the cap into aggregation);
  `src/l4/verifier/aggregate.py` (the cap reason); `src/l4/verifier/verdicts.py` (the question's fix line);
  `src/l4/verifier/report.py` (the label); `src/l4/verifier/evidence.py` (a resumed round reads `note`, `over_cap` and
  `capped`); `src/l4/templates.lock.json` (regenerated for the contract, red and judge templates).
- Records: `verdict.json` `trace[]` gains `capped` and each test `over_cap` (additive; an older record loads with none).
  No ledger event changes.
- Behaviour changes: a red step or a test chore whose new test traces more than the cap now fails its attempt (it costs
  an attempt, like any red rejection); the implementer and judge prompts change (`contract@13`, `red@12`, `judge@12`).
- Tests that change: the template-version pins (`contract@12`, `red@11`, `judge@11`; list in `tasks.md`), the
  single-part judge prompt hash (`SINGLE_SHA`: the judge's system text is part of the hash) and
  `tests/unit/implementer/test_vacuity.py` (the remedy's text).
- Unchanged: step 5 (`e2e_trace`, `generate.py`) reads the cap on its own and keeps it; the audit sample (step 4a) reads
  step 4's trace; L4-VER-003's table; a person's `accept` and `reject`.
- Spec: L4-VER-052 to L4-VER-055, SCN-VER-170 to SCN-VER-189, change-table row 59.
