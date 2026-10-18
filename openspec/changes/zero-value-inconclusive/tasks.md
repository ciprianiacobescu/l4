Every task follows these rules:
- Read `proposal.md` and `design.md` of this change first; the decisions D1..D12 are referred to below.
- Write the named tests first, run them and see them fail for the reason the task names, then write the code.
- Run only the named test files: `.venv/bin/python -m pytest -q -p no:cacheprovider <paths>` (`uv sync` once if `.venv`
  is missing). Then `ruff check .` and `ruff format --check` on the files that changed. Task 8.1 also runs
  `python scripts/check_spec.py docs/SPEC.md`.
- Never wait on a process with `while pgrep -f ...` (it matches itself and never ends). Stage explicit paths only.
- Name a consumer "a consumer repository". Fixture names stay neutral (`pytdd`, `telemetry`, `store`).
- When a signature changes, update every caller and every test fake of it: `grep -rn "<name>" src tests`.
- The bench is `make_bench` of `tests/unit/implementer/conftest.py` (the `py_tdd` fixture: package `src/pytdd`, tests
  under `tests/`, `pythonpath = ["src"]`, JUnit `xunit1` at `.l4-out/junit.xml`). A test writes extra files into
  `bench.wb.worktree` and calls `run_setup(bench.wb)` as `tests/unit/implementer/test_presatisfied.py` does; a file that
  must be part of the unit base is written into `tdd_repo.repo`, committed on `main` and pushed to `origin` before
  `make_bench` is called; a file of an earlier task of the unit is committed with `commit_head` of
  `tests/unit/implementer/test_base_run.py`.

## 1. Reports and the shared extraction (L4-IMP-060)

- [x] 1.1 JUnit: the setup phase and the collection tracebacks.
  - Tests first, in `tests/unit/gates/test_junit.py`:
    - `test_a_setup_error_records_its_phase`: parse `tests/fixtures/recorded/pytest/mixed-xunit2.xml`;
      `tests.test_mix::test_error` has `when == "setup"`, every other case `when == ""`.
    - `test_a_setup_assertion_is_an_assertion_in_setup`: write a JUnit file in `tmp_path` with one testcase whose
      `<error message='failed on setup with "assert False is True"'>` body ends `tests/test_spans.py:9: AssertionError`;
      the case has `status == "error"`, `failure_kind == "assertion"`, `when == "setup"`, and `detail` ends with that
      line.
    - `test_collection_errors_keep_their_traceback`: parse `collection-error-xunit2.xml`;
      `report.collection_details["tests.test_broken"]` ends with `E   SyntaxError: invalid syntax`; `merge_reports` of
      that report and an empty one keeps the detail.
  - `src/l4/gates/junit.py`:
    - `_SETUP_WRAPPER = re.compile(r'failed on (setup|teardown) with "(.*)"', re.DOTALL)`; `_message_kind` reads the
      inner message from `group(2)` (it read `group(1)`).
    - `TestCase.when: Literal["", "setup", "teardown"] = ""`, set by `parse_junit` from that match on an `<error>`
      message.
    - `TestReport.collection_details: dict[str, str] = field(default_factory=dict)`: for each collection error, the
      last `MAX_DETAIL_CHARS` characters of its `<error>` text, keyed like `collection_errors`. `merge_reports` keeps
      the first detail of a name.

- [x] 1.2 One collection-error extraction for the harness.
  - Tests first, `tests/unit/gates/test_collection.py`, with the constant (neutral names, the reproduction's shape):
    ```
    TRACE = (
        "src/pytdd/store.py:12: in <module>\n    class Store:\n"
        "src/pytdd/store.py:14: in Store\n    @telemetry.traced(\"store.add\")\n     ^^^^^^^^^^^^^^^^^^^^^^^^^^^\n"
        "E   TypeError: 'NoneType' object is not callable\n"
    )
    ```
    - `test_first_error_line_is_the_first_e_line`: `first_error_line(TRACE) == "E   TypeError: 'NoneType' object is
      not callable"`; `first_error_line("no error here") == ""`.
    - `test_called_names_are_the_called_and_decorated_names`: `called_names(TRACE) == {"traced"}`;
      `called_names(">       assert telemetry.init(out) is True\n") == {"init"}`;
      `called_names("    RATE = load()[\"rate\"]\n") == {"load"}`.
    - `test_the_deepest_location_is_a_repository_file`: `deepest_location(TRACE) == ("src/pytdd/store.py", 14)`; a
      trailing `/usr/lib/python3.12/site-packages/x.py:3: in f` or `.venv/...` frame is skipped.
    - `test_error_lines_are_bounded`: 100 distinct `E` lines give at most 600 characters.
    - `test_ledger_excerpt_holds_the_e_lines_and_one_location`: `ledger_excerpt(TRACE)` is the `E` line, then
      `src/pytdd/store.py:14`; at most 600 characters.
  - New `src/l4/gates/collection.py`:
    - move from `src/l4/verifier/audit.py`, unchanged in behaviour: `_COLLECTION_LINE`, `_COLLECTING`,
      `_SECTION_END`, `MAX_COLLECTION_ERROR_CHARS` (600), `_own_section`, `_collection_error`, as public
      `COLLECTION_LINE`, `own_section`, `collection_error(log_path, stem)`. `audit.py` imports `collection_error`
      (keep `_collection_error = collection_error` in `audit.py` if a test imports the old name).
    - move from `src/l4/implementer/excerpt.py`: `_LOCATION`, `_NOT_REPO`, `_in_repository` (as `LOCATION`,
      `in_repository`); `excerpt.py` imports them from here (the gates package must not import the implementer).
    - `error_lines(text, limit=MAX_COLLECTION_ERROR_CHARS) -> str`: the stripped `COLLECTION_LINE` matches of `text`,
      duplicates dropped in order, joined by `"\n"`, cut at `limit`.
    - `first_error_line(text, limit=300) -> str`: the first line of `error_lines(text)`, cut at `limit`; `""` when none.
    - `deepest_location(text) -> tuple[str, int] | None`: the last `LOCATION` line whose path is `in_repository`.
    - `called_names(text) -> frozenset[str]`: over the code lines of a traceback (lines that are not empty, not a
      `LOCATION` line, not a `COLLECTION_LINE` match, not made only of `^`, `~` and spaces; a leading `>` stripped):
      every name directly before `(` with its dotted prefix dropped (`a.b.c(` → `c`) and every name after `@` with
      its dotted prefix dropped (`@a.b` → `b`).
    - `ledger_excerpt(text) -> str`: `error_lines(text)` plus, on its own line, `path:line` of `deepest_location(text)`
      when there is one; cut at 600 characters. No redaction here: the callers redact.
  - Run also `tests/unit/verifier/test_audit_collect_retry.py` and `tests/unit/implementer/test_excerpt.py`.

## 2. The classifier and keep-going (L4-IMP-060, D1, D4)

- [x] 2.1 The classifier, pure.
  - Tests first, `tests/unit/implementer/test_variant.py`, with hand-built `TestReport`, `TestCase` and
    `GateResult` values (a `log_path` in `tmp_path`), `own_files={"tests/test_spans.py"}` and `Redactor({})`:
    - `test_scn_imp_300_a_report_with_collection_errors_and_no_test_is_inconclusive`: 45 collection errors whose
      details end with `TRACE` of task 1.2, no test case, exit 2; for a criterion with two tests that passed in the real
      report, `judge(...)` gives `inconclusive`, and the reason starts `the test-presatisfied run ran no test (exit 2,
      45 collection errors)` and ends with `E   TypeError: 'NoneType' object is not callable`.
    - `test_no_report_is_inconclusive_with_the_gate_reason` (`report=None`, `reason="exit code 2"`).
    - `test_a_missing_test_is_inconclusive_and_names_the_new_collection_error`.
    - `test_a_test_that_ran_is_judged_on_its_own_result_beside_an_unrelated_collection_error`: one new collection
      error of another module; a candidate that passed → `refuted`; one that failed by assertion → `confirmed`.
    - `test_a_test_skipped_only_in_the_variant_is_inconclusive`.
    - `test_a_setup_assertion_in_the_units_file_is_a_proof_and_elsewhere_inconclusive`: `when="setup"`,
      `failure_kind="assertion"`, `detail` ending `tests/test_spans.py:9: AssertionError` → proof; ending
      `tests/conftest.py:9: AssertionError` → inconclusive, the reason names `tests/conftest.py:9`.
    - `test_an_error_of_another_kind_is_no_proof` (a `TypeError` in the call phase and a `RuntimeError` in setup).
    - `test_the_reason_is_bounded_and_redacted`: an `E` line holding `"glpat-" + "x" * 20` comes out redacted, and no
      reason is longer than 300 characters.
  - New `src/l4/implementer/variant.py`:
    - `Outcome = Literal["proof", "none", "inconclusive"]`; `MAX_REASON = 300`.
    - `@dataclass(frozen=True) class VariantRun: name: str; report: TestReport | None; reason: str = "";
      new_errors: tuple[str, ...] = ()`; `reason` is set only when the whole run is inconclusive.
    - `classify(gate: GateResult, real: TestReport | None, *, redact: Callable[[str], str]) -> VariantRun`:
      `new_errors` = the variant's collection errors that `real` lacks (all of them when `real` is None), in report
      order. No report → `the <name> run wrote no readable report (<gate.reason>)`, plus `: <first E line>` of the last
      40,000 characters of `gate.log_path` when it has one. `report.executed == 0` → `the <name> run ran no test (exit
      <exit_code>, <n> collection errors)`, plus `: <first E line>` of the first new error's detail.
    - `test_outcome(run, test_id, real, own_files) -> tuple[Outcome, str]`, in this order: run inconclusive →
      (`inconclusive`, run.reason); absent from the report → `<id> did not run in <name>` (+ `: <first E line>` of the
      first new error); skipped in the variant while not skipped in `real` → `<id> was skipped only in <name>`;
      `failed` with `failure_kind == "assertion"` → proof; `error` with `failure_kind == "assertion"` and
      `when == "setup"` → proof when the path of `deepest_location(case.detail)` is in `own_files`, else
      `<id> failed by assertion in the setup of a fixture outside the unit's test files (<path>:<line>)`; anything
      else → (`none`, "").
    - `@dataclass(frozen=True) class CriterionResult: state: Literal["confirmed", "refuted", "inconclusive"];
      tests: tuple[str, ...]; reason: str = ""`.
    - `judge(run, candidates: Mapping[str, Sequence[str]], real, own_files) -> dict[str, CriterionResult]`: a proof →
      confirmed (the proving tests); else an inconclusive test → inconclusive (its tests, the first reason); else
      refuted (all its tests).
    - Every reason is cut at `MAX_REASON`, then passed through `redact`.

- [x] 2.2 Keep-going on every variant run; `run_with_code_of` returns the gate result.
  - Tests first, in `tests/unit/implementer/test_base_run.py`:
    - `test_scn_imp_301_the_base_run_goes_on_past_an_unrelated_test_that_imports_an_added_module`: `commit_head` with
      `PRICING: HEAD_PRICING`, `src/pytdd/middleware.py` (`def wrap(x: int) -> int:\n    return x\n`) and
      `tests/test_middleware.py` (`from pytdd.middleware import wrap` and one passing test); the red step writes
      `FAILS_AT_BASE`; with the `zero` fixture (it confirms nothing), `run_red` ends `already_satisfied` and
      `KNOWN`'s proof has `via: base_run`, as in
      `test_a_test_that_fails_by_assertion_at_the_unit_base_confirms_the_criterion`. In 0.4.15 the base run stops at
      the collection error of `tests/test_middleware.py` and confirms nothing.
    - `test_run_with_code_of_returns_the_gate_result`: the same tree; `run_with_code_of(wb, base, paths,
      name="test-base-run")` returns a `GateResult` whose `report` lists `tests.test_middleware` in
      `collection_errors` and holds `NEW_ID`.
  - `src/l4/implementer/discrimination.py`: `KEEP_GOING = {"PYTEST_ADDOPTS": "--continue-on-collection-errors"}`;
    `zeroed_run` and `run_with_code_of` pass `extra_env=merge_pytest_env(KEEP_GOING, extra_env or {})` to
    `wb.run_gate` (`merge_pytest_env` of `l4.gates.coverage` joins `PYTEST_ADDOPTS`); `discriminate_extra`'s local
    `keep_going` goes. `run_with_code_of(...) -> GateResult`; `fails_at_red`, `confirmed_by_base_run` and
    `discriminate_extra` read `gate.report` (None-safe) until task 4.3 changes them further.

## 3. Zeroing keeps what imports need (L4-IMP-061, D5)

- [ ] 3.1 Keep a function annotated to return a callable or a class.
  - Tests first, `tests/unit/implementer/test_zero_keep.py` (source level, `exec` of the variant in a namespace that
    provides the imports):
    - `test_scn_imp_302_a_decorator_factory_annotated_to_return_a_callable_keeps_its_body`: a module with
      `_F = TypeVar("_F", bound=Callable[..., Any])`, `def traced(name: str) -> Callable[[_F], _F]:` (returns an
      identity decorator) and `def span_names(spans: list[str]) -> list[str]:`; `zero_value_plan(source, public=True)`
      keeps `traced` (`traced("x")(f) is f` after `exec`), zeroes `span_names` to `[]`, `plan.kept == ("traced",)`,
      `"span_names" in plan.zeroed`.
    - `test_optional_and_string_annotations_are_kept`: `-> "Callable[[_F], _F]"`, `-> Callable[..., int] | None`,
      `-> Optional[Callable[[], None]]`, `-> type[Base]`, `-> typing.Callable[..., Any]` are all kept.
    - `test_keep_leaves_a_named_method_real`: `zero_value_plan(source, public=True, keep={"Store.add"})` leaves
      `Store.add` and zeroes `Store.count`; `plan.zeroed` lists `Store.count` by its qualname.
    - `test_red_stub_mode_is_unchanged`: with `public=False` a stub `-> Callable[[_F], _F]` answers `None` as before.
  - `src/l4/implementer/stubs.py`:
    - `_returns_callable(annotation: ast.expr | None) -> bool`: a string annotation is parsed first (`ast.parse(...,
      mode="eval").body`, a `SyntaxError` is False); `X | None` (`ast.BinOp` with `BitOr`) and `Optional[X]` are
      unwrapped to `X`; then True when `_name` of the node, or of a `Subscript`'s value, is `Callable`, `type` or
      `Type`.
    - `@dataclass(frozen=True) class ZeroPlan: source: str; zeroed: tuple[str, ...]; kept: tuple[str, ...]`
      (qualnames: `fn`, `Class.fn`, `Outer.Inner.fn`; `kept` holds only the functions kept by annotation).
    - `zero_value_plan(source, *, public=False, keep: Collection[str] = ()) -> ZeroPlan`: `_Zero` tracks the class
      stack; in public mode a public function whose qualname is in `keep` is left as it is (in neither list), one with
      `_returns_callable(fn.returns)` is left and listed in `kept`, every other public one is zeroed and listed in
      `zeroed`. Red-stub mode is unchanged (D5).
    - `zero_value_variant(source, *, public=False)` returns `zero_value_plan(source, public=public).source`.
  - Run also `tests/unit/implementer/test_stubs.py` and `tests/unit/implementer/test_zero_generators.py`.

- [ ] 3.2 Keep the functions the tracebacks name, and run again (at most twice).
  - Tests first, `tests/unit/implementer/test_zero_keep_loop.py`, on the bench. The files, written into the worktree:
    `src/pytdd/telemetry.py` with `def traced(name: str) -> Callable[[_F], _F]:` (an identity decorator) and
    `def init(out: list) -> bool:` (appends `"on"`, returns True); `src/pytdd/store.py` with
    `from pytdd import telemetry` and `class Store:` whose `def add(self, a: int, b: int) -> int: return a + b` is
    decorated `@telemetry.traced("store.add")` in the class body; `tests/test_store.py` with
    `@pytest.mark.l4("C-aaaaaaaa") def test_add(): assert Store().add(1, 2) == 3`. The real report is the bench's
    `wb.run_gate("test", ...)` report.
    - `test_scn_imp_302_the_presatisfied_run_imports_a_module_decorated_at_class_definition`: `zeroed_run(wb,
      "test-presatisfied", ["src/pytdd/telemetry.py", "src/pytdd/store.py"], public=True, real=real,
      candidates=["tests.test_store::test_add"])` runs once, its report has no collection error, `test_add` is a
      proof, and one `zero.kept{gate: "test-presatisfied", rerun: 0, cause: "annotation"}` lists
      `src/pytdd/telemetry.py::traced`.
    - `test_scn_imp_303_an_unannotated_decorator_factory_is_kept_after_the_run_names_it`: `def traced(name):`
      unannotated; the first run has the collection error of `tests/test_store.py`; the harness keeps `traced`, records
      `zero.kept{rerun: 1, cause: "collection", functions: ["src/pytdd/telemetry.py::traced"]}`, runs a second time,
      and `test_add` is a proof; `ZeroRun.reruns == 1`; two `gate.finished` named `test-presatisfied`.
    - `test_scn_imp_304_the_keep_reruns_are_bounded`: `src/pytdd/chain.py` defines public `f0() -> int` … `f5() -> int`;
      `Workbench.run_gate` is monkeypatched (the class attribute, as `test_base_run.py` does) to return, on its n-th
      call, a `GateResult` whose report has no test and one
      collection error whose detail is `src/pytdd/chain.py:1: in <module>\n    X = f<n>()\nE   TypeError: x\n`; the
      gate runs 3 times, `zero.kept` is recorded twice, and the candidate is inconclusive.
    - `test_the_worktree_is_byte_identical_after_the_reruns`: sha256 of both modules before and after.
  - `src/l4/implementer/discrimination.py`:
    - `zero_values_in_place(wb, paths, *, public, keep: Mapping[str, Collection[str]] | None = None) ->
      Iterator[ZeroScope]` with `@dataclass(frozen=True) class ZeroScope: varied: list[str]; zeroed: dict[str,
      tuple[str, ...]]; kept: dict[str, tuple[str, ...]]` (path → qualnames), built from `zero_value_plan(...,
      keep=keep.get(path, ()))`. The restore by sha256 is unchanged.
    - `MAX_KEEP_RERUNS = 2`, `MAX_KEPT = 50`.
    - `own_test_files(wb) -> frozenset[str]`: the test and support paths (`_is_test_path`) among `wb.changed_files()`
      and `git diff --name-only --no-renames --diff-filter=AM <unit_base> HEAD`.
    - `@dataclass(frozen=True) class ZeroRun: gate: GateResult; run: VariantRun; kept: dict[str, tuple[str, ...]];
      reruns: int`.
    - `zeroed_run(wb, name, paths, *, public, real: TestReport | None, candidates: Collection[str] = ()) -> ZeroRun |
      None` (None: nothing could be varied). Each pass runs the gate inside `zero_values_in_place(..., keep=kept)` and
      classifies it (`variant.classify`, `redact=wb.redactor.redact_text`). The first pass emits one `zero.kept{gate,
      rerun: 0, cause: "annotation", functions}` when anything was kept by annotation. Then, only in public mode, while
      `reruns < MAX_KEEP_RERUNS` and a candidate is inconclusive: the texts are the details of the run's `new_errors`
      and the `detail` of each candidate whose outcome is a foreign setup assertion; `names = called_names(texts)`; the
      new keeps are the zeroed `(path, qualname)` whose last dotted part is in `names` and that are not kept yet, at
      most `MAX_KEPT` in all; none → stop; else emit `zero.kept{gate, rerun, cause, functions}` (`cause` is
      `collection` when a new error named one, else `setup`; `functions` as `path::qualname`) and run again. The
      reports are put back once, after the last pass, as today.
    - Callers keep working: `vacuity_check`, `confirm_pre_satisfied` and `discriminate_extra` read `ZeroRun.gate`
      until group 4 moves them to the classifier.

## 4. What a variant run proves (L4-IMP-002, L4-IMP-003, L4-IMP-062, D2, D3, D6, D9)

- [ ] 4.1 The pre-satisfied confirmation: confirmed, refuted or inconclusive.
  - Tests first, `tests/unit/implementer/test_presatisfied_inconclusive.py`, on the bench:
    - `test_scn_imp_300_a_run_that_collects_nothing_is_inconclusive_not_still_passing`: `src/pytdd/config.py` with
      `def load() -> dict:` (returns `{"rate": 2}`) and module-level `RATE = load()["rate"]`; a candidate test imports
      it; `discrimination.MAX_KEEP_RERUNS` monkeypatched to 0; `confirm_pre_satisfied(wb, {C1: [test]}, real=real)`
      has `C1` in `inconclusive` with `KeyError` in the reason, `unconfirmed` empty, and `message` starts
      `inconclusive: C-aaaaaaaa (`.
    - `test_scn_imp_308_a_fixture_assertion_in_the_units_own_test_file_counts`: `src/pytdd/telemetry.py` of task 3.2
      plus `def span_names(out: list) -> list[str]:` (returns `[f"span:{e}" for e in out]`); a new
      (uncommitted) `tests/test_spans.py` with the fixture `exporter` (`out = []; assert telemetry.init(out) is True;
      return out`) and three tests tagged `C-aaaaaaaa`, `C-bbbbbbbb`, `C-cccccccc` asserting
      `span_names(exporter) == ["span:on"]`; all three criteria are confirmed with no rerun.
    - `test_scn_imp_309_a_fixture_assertion_in_a_pre_existing_conftest_does_not_count`: the same fixture in
      `tests/conftest.py` committed on `main` before `make_bench`; the first run leaves the candidates inconclusive,
      `init` is kept (`zero.kept{cause: "setup"}`), and on the second run the bodies fail by assertion: confirmed.
    - The tests of `tests/unit/implementer/test_presatisfied.py` keep passing unchanged (the refuted message is the same
      text as before).
  - `src/l4/implementer/discrimination.py`:
    - `PreSatisfied` gains `inconclusive: dict[str, str]` (criterion → reason), `not_applicable: dict[str,
      tuple[str, ...]]`, `kept: dict[str, tuple[str, ...]]` and `reruns: int = 0`, all defaulting empty;
      `unconfirmed` now means refuted only. `message`: the refuted part exactly as today; the inconclusive part
      `inconclusive: <id> (<reason>)` per criterion, joined by `, `; both joined by `; ` when both exist.
    - `confirm_pre_satisfied(wb, candidates, *, real: TestReport | None) -> PreSatisfied`: the scope and the
      "no project source module" and "nothing to vary" refutations as today; else `zeroed_run(wb, "test-presatisfied",
      scope, public=True, real=real, candidates=<all tests>)` and `variant.judge(run, candidates, real,
      own_test_files(wb))`.
    - Callers: `tdd.run_red` (both sites, `real=report`) and `audit._judge_written` (`real=report`); the
      `confirm_pre_satisfied` fakes of `tests/unit/implementer/test_base_run.py`, `test_already_satisfied*.py` and
      `test_earlier_red.py` take `*, real=None`.

- [ ] 4.2 Discrimination not applicable to a dependency check.
  - Tests first, `tests/unit/implementer/test_dependency_only.py`, on the bench, in one new test file
    `tests/test_pins.py` that also holds a test importing `pytdd`:
    - `test_scn_imp_306_a_version_pin_is_not_applicable`: `import importlib.metadata`, `import pytest`, and
      `@pytest.mark.l4("C-aaaaaaaa") def test_runner_is_the_verified_pin(): assert importlib.metadata.version("pytest")
      == pytest.__version__`; `confirm_pre_satisfied` puts `C-aaaaaaaa` in `not_applicable` with that test, and runs no
      `test-presatisfied` gate when it is the only candidate. Through `run_red` (the new-test path, the test passing),
      its proof is `{"tests": [...], "proof": "pre_satisfied", "discriminating": [...], "via": "not_applicable"}` and
      `criterion.pre_satisfied` carries `via: not_applicable`.
    - `test_scn_imp_307_a_test_that_reads_no_dependency_is_still_not_discriminating`: `assert 1 + 1 == 2` and
      `import json` … `assert json.loads("1") == 1`: neither is dependency-only; both criteria are refuted.
    - `test_project_code_a_helper_or_a_fixture_is_not_dependency_only`: a test that calls a module-level `def` of its
      file, one that takes a fixture `exporter`, one that imports `pytdd` inside its body, one that imports a test
      helper module under `tests/`.
    - `test_a_class_test_a_parametrized_test_and_a_constant_are_read`: `class TestPins: def test_pin(self)`,
      `@pytest.mark.parametrize("name", ["pytest"]) def test_pin(name)` and a module-level `PIN = "pytest"` are
      dependency-only.
    - `tests/unit/implementer/test_presatisfied.py::test_tests_that_import_no_project_module_cannot_be_confirmed`
      keeps passing.
  - New `src/l4/implementer/depcheck.py`: `BUILTIN_FIXTURES = frozenset({"tmp_path", "tmp_path_factory",
    "monkeypatch", "capsys", "capsysbinary", "capfd", "capfdbinary", "caplog", "recwarn", "request", "pytestconfig"})`;
    `METADATA_CALLS = frozenset({"version", "distribution", "metadata", "distributions"})`;
    `dependency_only(wb, test_id, roots) -> bool` per design D9:
    - the file is `discrimination._test_file(wb, test_id)`; the function is the part after `::` without a `[...]`
      suffix, at module level or in the class named by the last dotted part of the classname when that part is not
      the file's module; not found or unparsable → False;
    - the file's module-level imports map each bound name to its dotted module(s): `import a.b` binds `a` → `a`,
      `a.b`; `import a.b as c` binds `c` → `a.b`; `from a import b` binds `b` → `a`, `a.b`; a relative import binds to
      the repository; a module-level `Assign`/`AnnAssign` of a constant, or of a tuple, list, set or dict of constants,
      binds an allowed constant;
    - False when a parameter (not `self`) is neither in `BUILTIN_FIXTURES` nor named by the function's own
      `pytest.mark.parametrize` decorators; when a loaded name of its body, decorators or defaults is bound to a module
      of which any dotted name resolves with `discrimination._resolve(wb, dotted, roots)` (project or test helper), is
      bound by a relative import, or is bound by a module-level `def`, `class` or non-constant assignment; when an
      import inside the body resolves in the repository;
    - True only when, besides, a loaded name is bound to a module outside the repository whose top-level name is not
      in `sys.stdlib_module_names`, or a call's callee resolves through the imports to `importlib.metadata.<one of
      METADATA_CALLS>`.
  - `confirm_pre_satisfied`: before the scope, a criterion whose every candidate is `dependency_only` goes to
    `not_applicable` and out of the runs. `tdd.run_red` (both sites) writes the proof of task 4.2's first test for it
    and emits `criterion.pre_satisfied` with `via: not_applicable`; the base run is not asked for it.

- [ ] 4.3 The base run confirms or says nothing; run (b) and `test-at-red` are classified.
  - Tests first:
    - `tests/unit/implementer/test_base_run.py::test_scn_imp_311_a_base_run_cannot_refute_what_the_zero_value_run_could_not_decide`:
      a `zero` fake that returns `KNOWN` inconclusive; the red step writes `PASSES_AT_BASE`; `combine(zero, based)`
      gives `KNOWN` inconclusive, not refuted.
    - `tests/unit/implementer/test_base_run.py::test_a_candidate_that_cannot_import_at_the_base_confirms_nothing`:
      `ERRORS_AT_BASE` with the import moved to the top of the file: the candidate is absent at the base; with a
      refuting `zero` fake the criterion is refuted (today's message), with an inconclusive one it is inconclusive.
    - `tests/unit/implementer/test_vacuity.py::test_a_run_b_with_no_report_is_inconclusive_not_vacuous`:
      `Workbench.run_gate` monkeypatched for the name `test-zero` to a `GateResult` with `report=None`; `vacuity_check`
      returns every criterion in `inconclusive` and `message` holds no `vacuous:`.
    - `tests/unit/implementer/test_tdd_green.py::test_an_at_red_run_with_no_test_is_inconclusive`: `fails_at_red` on a
      `test-at-red` run that executes no test returns `AtRed(failing_not=[], inconclusive=<reason>)`; an id whose own
      module is a new collection error at red counts as failing there.
  - `src/l4/implementer/base_run.py`:
    - `confirmed_by_base_run(wb, candidates, new_ids, *, real) -> BaseRunResult`; `BaseRunResult` gains
      `inconclusive: dict[str, str]`. The run is classified; a criterion is confirmed when one of its tests in `new_ids`
      is a proof (`variant.test_outcome`); otherwise, when one of its tests is inconclusive there, its reason goes to
      `inconclusive`. The "the gate wrote no readable report" branch goes (the classifier says it). Skips keep their
      `reason`.
    - `@dataclass(frozen=True) class Decision: refuted: dict[str, tuple[str, ...]]; inconclusive: dict[str, str];
      message: str` and `combine(zero: PreSatisfied, based: BaseRunResult) -> Decision` per design D3: refuted = the
      zero run's refuted criteria the base run did not confirm; inconclusive = the zero run's inconclusive ones the base
      run did not confirm (the zero run's reason first, the base run's after `; `). The message is today's
      `failure_message` text for the refuted ones (with the base run's note) and `inconclusive: <id> (<reason>)` for the
      others. `failure_message(zero, based)` returns `combine(zero, based).message`.
  - `src/l4/implementer/discrimination.py`:
    - `vacuity_check(wb, stub_files, tracing, *, real) -> Vacuity`; `Vacuity` gains `inconclusive: dict[str, str]`.
      `zeroed_run(..., public=False, real=real, candidates=...)` and `variant.judge`: confirmed → `proofs`, refuted →
      `vacuous`, inconclusive → `inconclusive`. `reason` stays only for nothing varied. `message` is today's
      `vacuous:` text for the vacuous ones, then `inconclusive: <id> (<reason>)` for the others.
    - `@dataclass(frozen=True) class AtRed: failing_not: list[str]; inconclusive: str = ""` and `fails_at_red(...,
      real: TestReport | None = None) -> AtRed`: a whole-run inconclusive run → `AtRed([], <reason>)`; else an id
      fails at red when the report lists it failed or error, or when it is absent and its own module
      (`_test_file(wb, id)` as a dotted name without `.py`) is one of the run's new collection errors; the other ids are
      `failing_not`, as today.
    - `tdd._undiscriminating` passes the green gate's report as `real` and reads `AtRed` (the hold is task 5.2).

## 5. Holding the task (L4-IMP-063, L4-IMP-017, L4-QMD-004, L4-QMD-009, D7, D8)

- [ ] 5.1 The question kind `harness`.
  - Tests first:
    - `tests/unit/specs/test_questions_harness.py`: a raised `NewQuestion` of kind `HARNESS` renders `- **Kind:**
      harness` and parses back with `kind is QuestionKind.HARNESS`; `harness_answer` gives `accept` for `accept: the
      run broke` and `Accept`, `retry` for `retry: after the upgrade` and for Status `dismissed`, and None for `looks
      fine`; `is_answered` is False for `looks fine` with Status `answered`; a new file's header line names `harness`
      and `accept` or `retry`.
    - `tests/unit/specs/test_questions_cli.py::test_scn_imp_316_a_harness_answer_must_start_with_accept_or_retry`:
      `l4 questions answer Q-007 --unit A --text "looks fine"` exits 2 with a `Fix:` line naming `accept` and `retry`;
      `l4 questions accept Q-007 --unit A` exits 2; `--text "accept: the run broke"` is pushed (use the world of
      `tests/unit/specs/questions_world.py`).
    - `tests/unit/specs/test_questions_agents.py::test_scn_imp_317_an_agent_cannot_answer_a_harness_question_without_consent`:
      `AI_AGENT=l4-mcp`, the default configuration on the base: exit 2 with `a harness override is a person's
      decision`, nothing pushed; with `clarifier.answer_by_agents: true` on the base the answer is pushed and the commit
      body names `agent: AI_AGENT`.
    - `tests/unit/clarifier/test_clarifier_run.py::test_a_harness_question_is_never_clarified`: with only a harness
      question open, the clarifier pass records no `clarifier.result`, calls no profile, and leaves the unit for
      `awaiting_human`.
    - `tests/unit/implementer/test_unfreeze.py::test_a_harness_answer_never_unfreezes`: a harness question answered
      `accept: tests/test_x.py` unfreezes nothing.
  - `src/l4/specs/questions.py`: `QuestionKind.HARNESS = "harness"`; the `Kind values` line of `_HEADER_LINES` adds
    `harness` and `for a harness question, with accept or retry`; `harness_answer(question) ->
    Literal["accept", "retry"] | None` (Status `answered`: the first word of the answer, lower-cased, a trailing `:` or
    `,` dropped, if it is `accept` or `retry`; Status `dismissed`: `retry`; else None); `is_answered` of a harness
    question is `harness_answer(q) is not None`.
  - `src/l4/specs/questions_cli.py`: `accept` refuses a harness question (`questions: a harness question is answered
    with accept or retry` and `Fix: l4 questions answer Q-NNN --unit U --text "accept: <why>"` or `"retry: <note>"`);
    `answer` refuses a harness text that `harness_answer` would not read, with the same `Fix:`; `agent_reason` returns
    `a harness override is a person's decision` for a harness question unless `answer_by_agents`; `show` prints the
    two answer commands as `Next:` lines for a harness question.
  - `src/l4/clarifier/clarifier.py`: the batch filter excludes `QuestionKind.HARNESS` as it excludes `VERDICT`.
  - `src/l4/implementer/unfreeze.py`: `unfrozen` skips harness questions as it skips verdict ones.

- [ ] 5.2 The hold: no attempt, no escalation, one question.
  - Tests first, `tests/unit/implementer/test_held_check.py`, on the bench, with `tdd.confirm_pre_satisfied` and
    `tdd.confirmed_by_base_run` monkeypatched (the reason `the test-presatisfied run ran no test (exit 2, 45 collection
    errors): E   TypeError: 'NoneType' object is not callable`), and the two-profile setting `TWO`, `BAD` and `Hook` of
    `tests/unit/implementer/test_escalation.py`:
    - `test_scn_imp_312_an_inconclusive_presatisfied_check_consumes_no_attempt`: an already-satisfied red step with no
      new test (as `tests/unit/implementer/test_already_satisfied_no_test.py` scripts it), `implementer:
      {"escalate_after": 2}`; `run_task(..., escalate=hook)` returns `TaskOutcome("blocked", "red", [qid])`; no
      `task.attempt_failed`, no `implementer.escalated`, `hook.requests == []`; one `check.inconclusive{task: "1.1",
      phase: "red", check: "pre_satisfied", criteria, tests, reason, runs, kept, question: qid}`; one
      `question.raised{kind: "harness", check: "pre_satisfied", criteria}`; `questions.md` has the section with `Kind:
      harness`, the `Criteria:` line, the reason and both options; the adapter ran one step; the worktree has no change
      left.
    - `test_scn_imp_313_an_inconclusive_check_starts_no_escalation`: `[BAD, <the inconclusive step>]` with
      `escalate_after: 2`: one `task.attempt_failed` (the first), `hook.requests == []` (a counted second failure
      would have asked), the task is held.
    - `test_scn_imp_310_a_refuted_criterion_fails_the_attempt_beside_an_inconclusive_one`: the fake returns `KNOWN`
      refuted and `UNKNOWN` inconclusive; the attempt fails with a reason holding `not discriminating: C-2d3a8daf` and
      `inconclusive: C-d80f494d`, `task.attempt_failed` is recorded, and no question is raised.
    - `test_scn_imp_305_an_inconclusive_test_at_red_run_holds_the_green_step`: the unfreeze setting of
      `tests/unit/implementer/test_tdd_green.py` with `tdd.fails_at_red` monkeypatched to `AtRed([], "the test-at-red
      run ran no test (exit 2, 0 collection errors)")`: `TaskOutcome("blocked", "green", [qid])`, the question has
      `check: at_red` and the corrected test ids, no green attempt is counted, the red commit stays.
    - `tests/unit/orchestrator/test_held_exit.py::test_a_held_task_ends_awaiting_human_with_exit_11`, with the
      `run_l4` fixture of `tests/unit/orchestrator/conftest.py` (as `tests/unit/orchestrator/test_reentry.py` runs a
      blocked red) and the two fakes above: the run's code is 11 and the unit's phase is `awaiting_human`; a second
      `run_l4` with no answer starts no agent step.
    - `tests/unit/yolo/test_yolo_cycle_harness.py::test_a_plan_waits_on_a_unit_held_by_a_harness_question`, with
      `CycleWorld` of `tests/unit/yolo/yolo_cycle_world.py` as `tests/unit/yolo/test_yolo_cycle_capacity.py` uses it:
      the active plan's current unit is `world.snapshot("a", "awaiting_human")`, `dataclasses.replace`d with a
      `questions` file holding the open harness question Q-007 on a pending task and a `check.inconclusive` event →
      `plan.waiting{reason: "unit_awaiting_human"}` and `start_next_run` False.
  - New `src/l4/implementer/held.py`:
    - `@dataclass(frozen=True) class HeldCheck: task: str; phase: Literal["red", "green"]; check:
      Literal["pre_satisfied", "vacuity", "at_red"]; criteria: tuple[str, ...]; tests: tuple[str, ...]; reason: str;
      runs: tuple[str, ...] = (); kept: tuple[str, ...] = ()`.
    - `held_question(held, criteria: Mapping[str, Criterion], asked: str) -> NewQuestion`: title `Task <k>: the
      <pre-satisfied | run (b) zero-value | test-at-red> check could not decide`; kind `HARNESS`; blocking
      `(held.task,)`; `criteria` the `Criterion` objects of `held.criteria`; context: one sentence that L4 could not
      run the check and does not count it against the agent, `Why: <reason>`, `Runs: …`, `Kept real: …` (or
      `nothing`), `Tests: …` (at most 10, then `(+n more)`), and what each answer does (design D8), and that a person
      answers, or an agent only with `clarifier.answer_by_agents: true` on the base branch; options `accept: count
      these on the evidence of the real run` and `retry: run the check again (after an L4 upgrade or a fix)`.
  - `src/l4/implementer/tdd.py`: `RedOutcome.status` and `GreenOutcome.status` accept `"held"`, with a field `held:
    HeldCheck | None = None`. In `run_red`, both pre-satisfied sites call `based = confirmed_by_base_run(..., real=
    report)` for the zero run's refuted and inconclusive criteria, then `decision = combine(confirmation, based)`:
    refuted → `wb.discard_changes()` and `RedOutcome("failed", decision.message)`; only inconclusive → discard and
    `RedOutcome("held", held=HeldCheck(...))`. Run (b): vacuous → failed as today (the message lists the inconclusive
    ones); only inconclusive → held with `check="vacuity"`. `run_green`: when `green_failures` found nothing and the `AtRed`
    of `_undiscriminating` has `inconclusive`, `wb.discard_changes()` (back to the red commit, as for a `blocked`
    step) and return `GreenOutcome("held", held=HeldCheck(phase="green", check="at_red", tests=ids, ...))`.
  - `src/l4/implementer/loop.py`: `_raise_held(wb, task, held, step) -> list[str]`: builds the question with
    `wb.provider.criteria(wb.ref)`, raises it, emits `question.raised{id, task, kind: "harness", title, check,
    criteria, tests}` and then `check.inconclusive{task, phase, check, criteria, tests (at most 20), reason, runs, kept
    (at most 50), question}`, commits `questions.md` and pushes as `_raise_blocked` does. In `run_task`, a red or a
    green outcome `held` returns `TaskOutcome("blocked", <phase>, ids)` at once: it never reaches the failure count,
    `task.attempt_failed` or the escalation, and the loop never `continue`s on it.

- [ ] 5.3 The answers: `accept` counts the criteria, `retry` runs the check again.
  - Tests first, `tests/unit/implementer/test_held_answers.py`, on the bench of task 5.2. Answer Q-001 as `with_status`
    of `tests/unit/implementer/test_unfreeze.py` does (Status `answered`, the text in the Answer block), commit it,
    and record `question.answered{id, by: "human", answer_sha256}` with `bench.wb.emit`; then `run_task` again:
    - `test_scn_imp_314_a_person_accepts_the_claim_on_the_evidence_of_the_real_run`: `accept: the decorator factory is
      zeroed by an L4 bug`, and the check inconclusive again → `TaskOutcome("done")`; the `task.red_ok` proof of each
      criterion is `{"tests": [], "proof": "pre_satisfied", "discriminating": [<the candidates>], "via":
      "human_override", "question": "Q-001", "answer_sha256": <digest>}`; `check.accepted{task, check, question,
      answer_sha256, criteria}` and `criterion.pre_satisfied{via: "human_override", question: "Q-001"}` are recorded.
    - `test_an_accept_does_not_excuse_a_refuted_criterion`: the same answer and the check now refuting → the attempt
      fails with `not discriminating:`.
    - `test_an_accept_whose_text_changed_after_it_was_recorded_does_not_count`: the digest no longer matches → held
      again with a new question.
    - `test_scn_imp_315_a_retry_runs_the_check_again`: `retry: upgraded L4 to the release that keeps decorator
      factories`, and the check confirming → done with no `via`; the second red request
      (`bench.adapter.requests[-1]`) holds the answer's text.
    - `tests/unit/implementer/test_earlier_red.py::test_an_override_or_not_applicable_proof_is_no_earlier_red`: a
      `task.red_ok` whose proof has `via: human_override` (or `not_applicable`) confirms nothing for a later task.
  - `src/l4/implementer/held.py`: `@dataclass(frozen=True) class Override: question: str; answer_sha256: str` and
    `accepted_overrides(wb, task_key, check) -> dict[str, Override]` (criterion id, or test id for `at_red` → the
    override): from `questions.md` of `wb.ref.path`, the harness questions that block `task_key`, with
    `harness_answer == "accept"` and `answered_by == "human"`, whose `answer_sha256` is among the digests of the
    ledger's `question.answered{by: human}` events for that id (make `unfreeze._recorded_digests` public as
    `recorded_digests` and reuse it), and whose `question.raised` event (from `tdd._ledger_events(wb)`) has `kind:
    harness`, the same `task` and the same `check`; the subjects are that event's `criteria` (or `tests`), never the
    file's text.
  - `src/l4/implementer/tdd.py`: where 5.2 holds, first take `accepted_overrides`; when every inconclusive subject has
    one, the step goes on with them counted: pre-satisfied ones with the proof of 5.3's first test (`tests` as the
    path writes them, `discriminating` the passing candidates of run (a)), run (b) ones with `proof: "zero_value"`,
    `via: "human_override"`, at-red ids as failing at red; emit `check.accepted{task, check, question, answer_sha256,
    criteria | tests}` per question and `criterion.pre_satisfied{..., via: "human_override", question}`. Subjects
    left without an override → held again for those only. A conclusive result always wins over an override.
  - `src/l4/implementer/earlier_red.py`: a proof with `via` `human_override` or `not_applicable` is no earlier-red
    evidence.

## 6. The verifier (L4-VER-050, L4-VER-051, L4-VER-009, D11)

- [ ] 6.1 The audit records an inconclusive run.
  - Tests first, `tests/unit/verifier/test_audit_inconclusive.py` (the world of `tests/unit/verifier/test_audit.py`):
    - `test_scn_ver_150_an_inconclusive_audit_run_is_not_a_rejection`: `audit.confirm_pre_satisfied` monkeypatched to
      return the criterion inconclusive with `E   TypeError: 'NoneType' object is not callable` in its reason;
      `verify.audit` has `status: inconclusive` and that line in `reason`; `out.findings` is empty; the file is removed
      and not in `out.accepted`; `verification.md` (`report.py`) has the row and a `## Inconclusive audit runs`
      section with the reason.
    - `test_a_not_applicable_audit_test_is_accepted_with_its_label`: `reason == "not applicable: no project code"`.
    - `test_scn_ver_155_the_audits_zero_value_run_keeps_a_decorator_factory`: the real confirmation over the modules
      of task 3.2 (annotated `traced`): the audit test of `Store.add` is `accepted`.
  - `src/l4/verifier/audit.py` `_judge_written`: `confirm_pre_satisfied(wb, candidates, real=report)`; per
    criterion: confirmed → accepted; in `not_applicable` → `AuditRecord(cid, "accepted", rel, ids, "not applicable: no
    project code")` and accepted; in `inconclusive` → `AuditRecord(cid, "inconclusive", rel, ids, reason)`, file
    removed, no finding; else rejected as today. `src/l4/verifier/types.py`: the `AuditRecord` docstring names
    `inconclusive`. `src/l4/verifier/report.py`: after `## Rejected audit tests`, `## Inconclusive audit runs` with one
    line per such record.

- [ ] 6.2 The extra proofs and the test chore.
  - Tests first:
    - `tests/unit/verifier/test_extra_inconclusive.py::test_scn_ver_152_an_extra_test_whose_runs_were_inconclusive_says_so`:
      `discriminate_extra` with `zeroed_run` and `run_with_code_of` monkeypatched to runs where the test is absent
      (a new collection error ending `E   ImportError: cannot import name 'middleware'`); `ExtraRun.inconclusive` has
      the id with that line; through `_extra_proof_step` of `src/l4/verifier/ladder.py`, the ignored test's reason
      starts `inconclusive:`.
    - `tests/unit/verifier/test_extra_inconclusive.py::test_the_runs_stay_bounded`: `ExtraRun.runs` is at most 4 (two
      runs plus two keep reruns).
    - `tests/unit/implementer/test_tdd_red.py::test_scn_ver_151_a_test_chore_whose_check_cannot_decide_is_left_to_the_verifier`:
      `tdd.discriminate_extra` monkeypatched to `ExtraRun(inconclusive={both ids})`: `_discriminating_tests` returns
      both ids and `""`.
  - `src/l4/implementer/discrimination.py` `discriminate_extra(wb, tests, base_sha, *, real: TestReport | None =
    None) -> ExtraRun`; `ExtraRun` gains `inconclusive: dict[str, str]`. The zero run is `zeroed_run(...,
    public=True, real=real, candidates=wanted)` (`runs` counts its passes); accepted where `variant.test_outcome` is a
    proof; the base run as today, accepted where a proof, `ERROR_AT_BASE` as today; an id the zero run left
    inconclusive and the base run did not accept goes to `inconclusive` with the zero run's reason.
    `src/l4/verifier/ladder.py` `_extra_proof_step`: passes step 3's JUnit report (`run.report`, None when step 3
    wrote none) as `real` and, for an id in `outcome.inconclusive`, the reason `inconclusive: <reason>`.
    `src/l4/implementer/tdd.py` `_discriminating_tests`: no accepted test and every added test in `inconclusive` →
    `(sorted(added), "")`.

- [ ] 6.3 The judge sees unproven evidence.
  - Tests first:
    - `tests/unit/verifier/test_traceability.py::test_scn_ver_153_a_not_applicable_proof_is_evidence_with_its_label`:
      a `task.red_ok` with `{"tests": [], "proof": "pre_satisfied", "discriminating": ["t"], "via":
      "not_applicable"}` gives `t` the proof `pre_satisfied` and the note `not applicable: no project code`; with
      `via: human_override, question: Q-001` the note is `accepted by Q-001: the check was inconclusive`; the
      evidence line of `ladder.py` and `report.py`'s `_test_cell` read `t (passed, pre_satisfied, <note>)`.
    - `tests/unit/verifier/test_judge_satisfied.py::test_scn_ver_154_the_satisfied_block_names_an_override`: the
      line reads `Proved by: C-… (tests: t; accepted by Q-001: the check was inconclusive)`.
  - `src/l4/verifier/traceability.py`: `red_proofs` takes the `discriminating` tests of a proof with `via`
    `not_applicable` or `human_override` when its `tests` is empty; a new `red_notes(ledger) -> dict[tuple[str, str],
    str]` gives the note per (criterion, test); `trace_criteria` sets it. `src/l4/verifier/types.py`:
    `TracingTest.note: str = ""`. The three renderings (`ladder.py`'s traceability lines, `report.py` `_test_cell`,
    `verdicts.py`'s evidence line) append `, <note>` when it is set. `src/l4/verifier/judge.py`: `SatisfiedRef` gains
    `labels: tuple[tuple[str, str], ...] = ()` (criterion → note) from the proofs' `via`, and `_satisfied_block`
    appends `; <note>` inside the parentheses.

## 7. Evidence and status (L4-IMP-064, L4-OPS-006, D10)

- [ ] 7.1 The excerpt in the committed ledger.
  - Tests first:
    - `tests/unit/implementer/test_workbench.py::test_scn_imp_318_gate_finished_carries_the_collection_error`: on the
      bench, a test file `tests/test_broken.py` whose import raises `ImportError("glpat-" + "x" * 20)`; the `test`
      gate's `gate.finished` has `collection_errors: 1` and an `excerpt` of at most 600 characters holding
      `E   ImportError:` with the token redacted; a passing gate has no `excerpt`.
    - `tests/unit/implementer/test_loop.py::test_task_attempt_failed_carries_a_bounded_excerpt`: a failed red attempt
      with a failure excerpt → `task.attempt_failed.excerpt` holds its `E` lines, at most 600 characters, and
      `excerpt_lines` stays.
  - `src/l4/implementer/workbench.py` `run_gate_spec`: `gate.finished` gains `collection_errors` (when there is a
    report) and, for a spec with `reports` whose status is `fail` and whose report is None, executed no test or has a
    collection error, `excerpt = self.redactor.redact_text(ledger_excerpt(<text>))`, the text being the first
    collection error's detail, else the last 40,000 characters of the gate log.
    `src/l4/implementer/loop.py`: `task.attempt_failed` gains `excerpt=wb.redactor.redact_text(ledger_excerpt(excerpt))`
    when the attempt has an excerpt. `src/l4/implementer/excerpt.py`: the module docstring says the ledger gets only
    `ledger_excerpt` of it (`E` lines and one location, 600 characters, redacted), which no prompt reads.

- [ ] 7.2 The console, the artefacts line and the job summary.
  - Tests first, `tests/unit/obs/test_progress.py`:
    - `test_scn_imp_318_a_variant_run_that_ran_no_test_does_not_say_expected`: `gate.finished{name:
      "test-presatisfied", status: fail, exit_code: 2, tests: 0, passed: 0, failed: 0, collection_errors: 45}` prints
      `gate test-presatisfied fail (exit 2, 0 tests: 0 passed, 0 failed) — …` without `(expected`; with `tests: 2001`,
      exit 1 and no collection error it keeps `(expected: zero values must fail)`; `test-extra-zero` behaves the same.
    - `test_the_held_check_and_the_kept_functions_are_printed`: `check.inconclusive` prints at WARNING `task 2.2 red:
      the pre_satisfied check could not decide (<reason>); no attempt counted, Q-007 asks a person`; `check.accepted`
      at INFO `task 2.2: Q-007 accepted 11 criteria on the evidence of the real run`; `zero.kept` at INFO `gate
      test-presatisfied: kept 1 function(s) real (collection): src/pytdd/telemetry.py::traced`.
    - `test_the_artefacts_line_says_what_was_uploaded`: `artefacts_note({"GITHUB_ACTIONS": "true"}, False)` ends
      `(not uploaded: ci.upload_artifacts is false; the ledger's gate.finished and task.attempt_failed events carry the
      excerpts)`; with True `(CI: artifact l4-out)`; `{"GITLAB_CI": "true"}` `(CI: job artifacts)`; `{}` adds nothing.
    - `tests/unit/obs/test_step_summary.py::test_a_held_task_has_a_summary_line`: `check.inconclusive` adds `- <unit>
      task <k>: held (check inconclusive)`.
  - `src/l4/progress.py`: `ZEROED_GATES` adds `test-extra-zero`; `_gate_line` adds `(expected: …)` only when the gate
    is one of them, failed, `tests` is a number above 0, `exit_code` is not 2 and `collection_errors` is 0 or absent;
    handlers for `check.inconclusive`, `check.accepted` and `zero.kept`; `artefacts_note(environ, upload_artifacts) ->
    str`; `log_artefacts(out_dir, run_id, note="")` prints `artefacts: <agent>/, <gates>/<note>`.
    `src/l4/orchestrator.py`: `log_artefacts(app.out_dir, app.run_id, artefacts_note(app.environ,
    cfg.ci.upload_artifacts))` (positional: tests replace it with `lambda *a: None`). `src/l4/ci/step_summary.py`:
    the `check.inconclusive` line (ids and codes only, L4-OBS-005).

- [ ] 7.3 `l4 status`, `l4 plan` and the plan's waiting detail.
  - Tests first:
    - `tests/unit/state/test_next_step.py::test_scn_imp_319_a_harness_question_names_its_cause_and_both_answers`:
      `UnitFacts(phase="awaiting_human", open_blocking_questions=("Q-007",), harness_open=(("Q-007", "Task 3.1: the
      pre-satisfied check could not decide", "the test-presatisfied run ran no test …"),))`: `reason` is `Q-007: Task
      3.1: the pre-satisfied check could not decide (the test-presatisfied run ran no test …)`; `next_step` names `l4
      questions answer Q-007 --unit <unit> --text "accept: <why>"` and `--text "retry: <note>"`.
    - `tests/unit/state/test_next_step.py::test_an_invalid_harness_answer_is_named`: `harness_invalid=("Q-007",)` →
      `fix the answer of Q-007 in <where>: start it with accept or retry, then push`.
    - `tests/unit/planner/test_next_action.py::test_a_held_unit_says_harness_check_inconclusive`: the reason holds
      `(harness check inconclusive: Q-007)`; an invalid answer → `awaiting_human: harness answer must start with accept
      or retry: Q-007`.
    - `tests/unit/state/test_status_reason.py::test_status_unit_prints_the_harness_cause`: `l4 status --unit` prints
      `Cause:` with the check's reason and `Next:` with both commands; `--json` has the same `reason` and `next`.
    - the yolo test of task 5.2 also asserts the `plan.waiting` detail holds `harness check inconclusive: Q-007`.
    - `tests/unit/clarifier/test_notify.py::test_an_unreadable_harness_answer_is_named_in_the_sticky_note`: the
      `awaiting_human` sticky section has the line "Q-007 has an answer that does not start with `accept` or `retry`:
      it was not read. Please answer again."
  - `src/l4/planner.py`: `UnitFacts.harness_open: tuple[tuple[str, str, str], ...] = ()` (id, title, reason: the
    `reason` of the newest `check.inconclusive` event with that `question` in `snapshot.events`, else "") for the open
    harness questions that hold a pending task, and `harness_invalid: tuple[str, ...] = ()` (Status `answered`,
    `harness_answer` None); `facts_of` fills both; `next_action` for `awaiting_human`: `harness_invalid` first
    (`awaiting_human: harness answer must start with accept or retry: <ids>`), and `waiting` gains `(harness check
    inconclusive: <ids>)`. `src/l4/state/next_step.py`: `reason` and `_answer_step` as the tests say. The
    `awaiting_human` sticky section of the forge note (`src/l4/clarifier/notify.py`, L4-CLR-004) adds that line for
    each harness question whose answer `harness_answer` cannot read, as `src/l4/verifier/notes.py` `verdict_hints`
    does for a verdict answer.

## 8. Docs

- [ ] 8.1 `docs/SPEC.md`, `CHANGELOG.md`, `docs/runbook.md`.
  - `docs/SPEC.md`:
    - L4-IMP-002: the pre-satisfied paragraph (confirmed, refuted, inconclusive; the precedence of D2; the setup rule of
      D6; dependency-only criteria), check 5 (judged by L4-IMP-060; an inconclusive run is not vacuous), the
      zero-value stubs paragraph (L4-IMP-061), and green's `test-at-red` sentence (an inconclusive run holds the task).
    - L4-IMP-003: the base-run paragraph (keep-going; it only confirms; the D3 table in prose).
    - L4-IMP-017: the list of what MUST NOT count adds the check held as inconclusive.
    - L4-IMP-060..064 after L4-IMP-026, each with its `[V: …]` note citing a consumer repository's halt (0.4.14,
      task 3.1: nine red attempts on four profiles, `Interrupted: 45 errors during collection`).
    - §6.2: the `Kind values` line of the grammar block names `harness`; L4-QMD-004 and L4-QMD-009 as this change's
      MODIFIED blocks; L4-CLR-002 (or its routing paragraph): a `harness` question is never routed to the clarifier,
      as a `verdict` one is not; L4-CLR-004: the sticky note names an unreadable harness answer.
    - L4-OPS-006: the harness question's REASON, `Cause:` and `Next:`.
    - L4-OBS-005: the job summary line of a held task.
    - L4-STA-001: a paragraph "zero-value-inconclusive adds these records": `check.inconclusive` (`{task, phase, check,
      criteria, tests, reason, runs, kept, question}`), `check.accepted` (`{task, check, question, answer_sha256,
      criteria | tests}`), `zero.kept` (`{gate, rerun, cause, functions}`), `collection_errors` and `excerpt` on
      `gate.finished`, `excerpt` on `task.attempt_failed`, `via: not_applicable | human_override` (with `question` and
      `answer_sha256`) on `criterion.pre_satisfied` and in `task.red_ok.criteria`, and `kind: harness` with `check`,
      `criteria`, `tests` on `question.raised` (the checker reads event names from §12.1).
    - L4-VER-002 step 4a (an inconclusive audit run is recorded, not rejected) and L4-VER-009 (the bound and the
      reason), then L4-VER-050 and L4-VER-051 after L4-VER-018.
    - Scenarios SCN-IMP-300..319 in §23.7 after SCN-IMP-218, and SCN-VER-150..155 in §23.9 after SCN-VER-77, from this
      change's spec files, in the `#### SCN-… (+|−) Title · L4-…` form with **Given**/**When**/**Then**; a scenario
      that names phase `awaiting_human` names exit 11.
    - §21: the next row number after the last row present: `zero-value-inconclusive`, its outcome in one sentence
      (requirement ids, `openspec/changes/zero-value-inconclusive/`), and its live check: the consumer repository's
      held unit retried on 0.4.16, tasks 2.2 and 3.1 confirmed or held, never counted.
  - `CHANGELOG.md`: `## 0.4.16 (unreleased)` above `## 0.4.15`, with `### Fixed` (the pre-satisfied and base runs no
    longer fail an agent for a run that collected nothing; decorator factories stay real; keep-going; setup assertions
    in the unit's own fixtures count; the false audit rejections; the `(expected: …)` line; the artefacts line) and
    `### Changed` (an inconclusive check holds the task with a `harness` question; dependency checks are not
    applicable; the ledger excerpt; `l4 status` names the harness cause).
  - `docs/runbook.md`: in §7.1 a procedure "A harness question: a check L4 could not decide" (what it means — the
    agent was not charged; read `Cause:` and the `excerpt` of `check.inconclusive` with `l4 status --unit <unit>
    --events --type check.inconclusive`; answer `retry: <note>` after upgrading L4 or fixing the cause, or `accept:
    <why>` when the real run is the evidence you accept; who may answer; the verifier and the judge see an accepted
    claim); in §4.2 a note that `gate.finished` and `task.attempt_failed` carry an `excerpt` when no artifact was kept;
    in §4.3 that with `ci.upload_artifacts: false` the run says `not uploaded`.
  - Then `python scripts/check_spec.py docs/SPEC.md` (no uncovered requirement, no undefined ref, no unknown phase,
    exit code or key), `npx --yes @fission-ai/openspec@1.14.1 validate zero-value-inconclusive --strict`, and the
    whole unit suite once: `.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit`.
