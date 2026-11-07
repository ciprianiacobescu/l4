## 1. A named test red changed traces its criterion (D1, D2, D3, D8)

- [ ] 1.1 Write the tests first (tests/unit/implementer/test_named_tests_trace.py, new): `check_criteria` with the new
  `named` keyword: a counted test fills `tracing` for a cited criterion; it adds the unit's criteria it traces to the
  cited set only when `criteria_ids` is empty, never an id outside `family_criteria`; it is never in `untraced`.
  `classify_red` with the new `named_proofs` keyword: a step with no new test and one named proof is ok; with
  `named_proofs` empty the reasons stay `NAMED_NOT_NEW` and `NO_NEW_TEST`. `tdd.named_tracing` on hand-built
  reports: counted for a changed Python test (every parametrised id judged alone) and a changed TypeScript id; refused
  with `it did not pass before this step` (failed or missing in the base report), `it hangs at red` (the timeout
  marker), `it does not fail by assertion at red` (status `error`, `failed` with `failure_kind` `other` or
  `not_implemented`, and `passed`), `it traces more than 3 of this unit's criteria`; a changed named test that traces
  none of the unit's criteria is in neither map; an unchanged named test is in neither map. Then add to
  `src/l4/implementer/result.py` the `named: Mapping[str, TestCase] | None = None` keyword of `check_criteria`, and to
  `src/l4/implementer/tdd.py` the `NamedTracing` dataclass, `named_tracing(...)` and the `named_proofs:
  Collection[str] = ()` keyword of `classify_red` (its `if not new:` exit also requires `not named_proofs`). Run
  `uv run pytest tests/unit/implementer/test_named_tests_trace.py tests/unit/implementer/test_check_criteria.py -q`.
- [ ] 1.2 Write the run_red tests first, in the same file, with `make_bench` and the `reviewed(...)`, `ts_bench(...)`
  and `FAKE_RUNNER` helpers of tests/unit/implementer/test_red_preexisting_tests.py (the SCN-IMP-439 tests): SCN-IMP-490
  (a named TypeScript test whose name carries a criterion id of the unit, changed to fail by assertion, with no other
  test and `criteria_ids` naming that id: `ok`, the proof names its report id, `task.red_ok.tests == []`, not already
  satisfied; and `green_failures` with that red's base report fails a green report that leaves it failing); SCN-IMP-491 (a Python named test marked with
  `C-aaaaaaaa` plus a new failing test for `C-bbbbbbbb`: `ok`, both proved); SCN-IMP-492 (the named test fails with
  `TypeError`: the reason starts with `no new test traces C-aaaaaaaa: ` and ends with `; <id>, which the task names, does
  not count for C-aaaaaaaa: it does not fail by assertion at red`; and the base-failing and hang variants); SCN-IMP-493
  (a named test that traces no criterion and no new test: exactly `NAMED_NOT_NEW`; one over the cap: `NAMED_NOT_NEW`
  plus its note). Then change `run_red`: compute `python_changed` and `other_changed` right after
  `tampered("test run")` and reuse them at the `classify_red` call (delete the later `named_in_place` and
  `other_in_place` assignments; `other_unchanged` and `named_changed[:] = ...` read the hoisted lists); call
  `named_tracing`; widen the criteria block's guard to `new_ids or counted`; add the counted tests' traces to
  `traced_new`; pass `named=counted` to `check_criteria` and `named_proofs=tuple(counted)` to `classify_red`; append
  the D3 notes to a failing reason that starts with `no new test traces ` or equals `NAMED_NOT_NEW`. Run the new file,
  tests/unit/implementer/test_tdd_red.py and tests/unit/implementer/test_red_preexisting_tests.py.
- [ ] 1.3 Change the sentence of `prompt._named_section` as D8 says, and the two assertions of
  tests/unit/implementer/test_prompt.py that read the old one (lines ~505 and ~523) to the new text. Run
  tests/unit/implementer/test_prompt.py. `red.md` and `templates.lock.json` stay as they are.

## 2. An unchanged scenario the base already tests (D4, D5, D6)

- [ ] 2.1 Write the tests first (tests/unit/specs/test_spec_baseline.py, new): `unchanged_ids` (same id and same
  normalised text: in; same id and another body: out; an id the base lacks: out; re-wrapped text: in) and
  `spec_baseline` (OpenSpec reads `base_criteria_at` at `rev`, `[]` for `rev=None`; Kiro with a provider that has
  `merged_parent_criteria` returns it; Kiro without: `[]`). Then add both to `src/l4/specs/criteria.py`, make
  `traceability._unchanged` call `unchanged_ids`, and make `ladder.traceability` compute `archived` with
  `spec_baseline(wb.git, wb.ref.framework, wb.provider, base_sha)`. Run the new file,
  tests/unit/specs/test_base_criteria_at.py and `uv run pytest tests/unit/verifier -q -k "trace or pass_to_pass or
  archived"`.
- [ ] 2.2 Write the tests first (tests/unit/implementer/test_unchanged_on_base.py, new), with `make_bench` and an
  OpenSpec unit whose delta MODIFIES a requirement of an archived `openspec/specs/<cap>/spec.md` committed before the
  unit base: `tdd.unchanged_on_base` returns the passing tracing base tests of a restated scenario; and the negative
  cases, each `{}` for that criterion: the scenario's body changed under the same name (same id), a scenario the
  archived spec lacks, its only tracing test FAILS in the base report, its only tracing test passes at the base but
  fails at red, its only tracing test traces 4 of the unit's criteria under `verifier.max_criteria_per_test: 3`, no test
  of the base traces it, `unit_base` is None, a Kiro unit that is not a follow-up. Then add `unchanged_on_base` to
  `src/l4/implementer/tdd.py`.
- [ ] 2.3 Write the run_red tests first, in the same file: SCN-IMP-494 (a fresh task, not in any `tasks.reopened`,
  citing the restated scenario and a new one; one new failing test for the new one: `ok`, no hold, no
  `check.inconclusive`); SCN-IMP-495 (in a project whose gate is not pytest, as the SCN-IMP-485 tests of
  tests/unit/implementer/test_presatisfied_other_language.py set it up, a new passing test of the restated scenario:
  no `test-zero` and no `test-base-run` gate ran, `criterion.pre_satisfied{via: "unchanged_spec"}`, the
  `task.red_ok.criteria` record is `{tests, proof: "pre_satisfied", discriminating: [], via: "unchanged_spec",
  base_tests}`, not held); SCN-IMP-496 (every cited criterion restated: a step that adds no test and reports
  `already_satisfied` ends `already_satisfied` with no variant gate; a step whose new tests all pass ends the same way);
  SCN-IMP-497 and SCN-IMP-498 (each negative case of 2.2 through `run_red`: the step that leaves the criterion without a
  new test fails with `no new test traces <id>: `; a passing new test of the changed scenario still reaches the
  zero-value run). Then change `run_red`: compute `on_base = unchanged_on_base(wb, criteria, base_report, report)` after
  the gate when `family` is not empty; `exempt = unchanged_criteria(...) | set(on_base)` before `required`; in both
  confirmation places, after the earlier red, `by_spec = {c: t for c, t in <candidates>.items() if c in on_base and c not
  in earlier}`, taken out of what `confirm_pre_satisfied` and `confirmed_by_base_run` get; `VIA_UNCHANGED_SPEC`; a
  `by_spec` parameter of `_via` and a branch of `proof_of` (after the override branch). Run the new file,
  tests/unit/implementer/test_unchanged_criteria.py, tests/unit/implementer/test_red_cited_criteria.py and
  tests/unit/implementer/test_presatisfied_other_language.py.
- [ ] 2.4 Verifier side, in tests/unit/verifier/test_traceability.py (beside its pass-to-pass tests): a `task.red_ok`
  record with `discriminating: []` and `via: "unchanged_spec"` gives no red proof (`red_proofs`) and no unproven note
  (`red_notes`), and `trace_criteria` counts the criterion's passing test `pass_to_pass` when the archived spec holds it
  unchanged and gives it no proof when the archived body differs.

## 3. The trace form of a Python gate that is not pytest (D7)

- [ ] 3.1 Write the tests first (tests/unit/implementer/test_check_criteria.py, beside the SCN-IMP-67 test):
  SCN-IMP-499 for `trace_rules` with `uv run python manage.py test`, `python -m unittest discover`, `./manage.py test`,
  `python -m xmlrunner discover` (the Python name rules), `uv run python -m pytest` and `uv run --with pytest-xdist
  pytest` (the marker rules), `npx vitest run` and `make test` (the name rules); `tag_example` under the Python rules
  (`def test_c_1234abcd_c_5678abcd_…`); `trace_ids` reads `pkg.tests.test_x.FooTests::test_c_1234abcd_lists`; and a
  rendered red prompt under a `manage.py` gate (tests/unit/implementer/test_prompt.py) that holds `def test_c_xxxxxxxx_…`
  and neither `it("C-xxxxxxxx` nor `@pytest.mark.l4`. Then add `_PYTHON_COMMAND`, `TRACE_HINT_PYTHON_NAME` and
  `_PYTHON_NAME_RULES` to `src/l4/implementer/result.py` and the third branch of `trace_rules` and `tag_example`.

## 4. Checks

- [ ] 4.1 docs/SPEC.md and CHANGELOG.md were written with this spec: check every name and text they quote against the
  code (the D3 note, the reasons, `unchanged_spec`, `base_tests`, the D7 texts) and fix any drift in both. Run
  `python3 scripts/check_spec.py docs/SPEC.md`, tests/unit/docs, `uv run pytest tests/unit/implementer -q`,
  `uv run pytest tests/unit/verifier -q`, tests/unit/test_template_lock.py (unchanged), `uv run ruff check src tests`,
  `uv run ruff format --check src tests` and `openspec validate named-tests-trace --strict`. Do not run the whole
  suite more than once, and never two at a time.
