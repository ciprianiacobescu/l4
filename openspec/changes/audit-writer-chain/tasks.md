Read `design.md` first; it names the code each decision touches (D1-D4). Requirements: L4-VER-089..091 (`docs/SPEC.md`),
scenarios SCN-VER-356..369. Run single test files only (`uv run --frozen pytest <file> -q`), never a whole directory,
never two runs at once, and never a wait loop on `pgrep`.

Test setup: the scope tests extend `tests/unit/verifier/test_audit_nonpython.py` (its `_repo` and `_step` build a
repository and call `ladder._audit_step` with a `SimpleNamespace` workbench; give `run` a `report` attribute, a
`TestReport` with the ids you need). The chain tests drive a round with `run_l4` and `with_verifier` of
`tests/unit/verifier/conftest.py` (extend its `profiles` and `roles` with a second fake profile of another vendor) and
`audited_criterion`, `writer_step`, `AUDIT_KNOWN`, `JUDGE` of `tests/unit/verifier/test_ladder_depth.py`, as
`test_an_overloaded_audit_writer_is_retried_in_the_run` of `tests/unit/verifier/test_ladder.py` does. A writer reply that
stops at its limit is `Step(status="error", length_stop=True)`; a refused tool call is `Step(status="permission_blocked")`
(check `l4.agents.fake.Step` for the field names and add what is missing to the fake, not to the harness).

## 1. Step 4a's scope (L4-VER-089; D1)

- [ ] 1.1 Write the tests first in `tests/unit/verifier/test_audit_nonpython.py`:
  - SCN-VER-356: `web/src/layout.ts` and `e2e/test_layout.py` changed, a report with one id `web.src.layout.test.ts::a`:
    `not_run` with the note of the scenario, word for word;
  - SCN-VER-357: only `tests/test_pricing.py` (a test function) changed, a report with `tests.test_pricing::test_total`:
    not `not_run` (the existing `no covered new criterion to audit` record is enough);
  - SCN-VER-358: `src/a.py` + `web/app.ts` audits; `web/app.ts` + `tests/conftest.py` is `not_run` naming
    `tests/conftest.py`;
  - SCN-VER-359: only `tests/test_pricing.py`, `run.report = None`: not `not_run`;
  - the two existing tests keep passing unchanged (SCN-VER-58 keeps its note word for word).
  Run the file and see the new tests fail.
- [ ] 1.2 Then replace `_no_python` with `_audit_scope_note(vc, base_sha, head, report)` in `src/l4/verifier/ladder.py`
  (D1), reading `CODE_SUFFIXES` from `l4.evidence.diffcov`, the support globs from `wb.cfg.tdd.test_support_globs`
  (`l4.security.protected.glob_match`, as `audit._matches` does) and the tree's `.py` files for `file_of_test` (the
  `_py_files` of `l4.implementer.tdd`, or a `git ls-files` of `*.py` at head); `_audit_step` passes `run.report`. Run the
  file and `tests/unit/verifier/test_audit.py`.

## 2. Where the audit test goes (L4-VER-090; D2)

- [ ] 2.1 Write the tests first in `tests/unit/verifier/test_audit.py` (or a new `test_audit_folder.py`), with the
  helpers that test `red_test_directory` today: SCN-VER-360 (two `e2e/` files, one `tests/` file, a report of
  `tests.test_a::...` only: `tests`, and no `audit-collect-check` gate run) and SCN-VER-361 (only `e2e/` files, a report
  without them: `None`, and `run_audit` runs `audit-collect-check`). See them fail.
- [ ] 2.2 Then give `red_test_directory` and `run_audit` the `report` argument (D2) and pass `run.report` from
  `_audit_step`. Update the callers in the tests that call `run_audit` directly (a test that relied on the folder
  without a report now sees one collect-only run: give it a report that holds its test). Run `test_audit.py`,
  `test_audit_collect_retry.py`, `test_audit_support.py`, `test_audit_lint.py` and `test_audit_inconclusive.py`, one at
  a time.

## 3. The writer chain (L4-VER-091; D3-D5)

- [ ] 3.1 Write the tests first in a new `tests/unit/verifier/test_writer_chain.py`:
  - unit tests of `WriterChain` with fake backends (no round): `ok` is returned at once; `error` with `length_stop`
    moves to the next selection and emits `availability.judge_error{role: "verifier_agent", kind: "length", step}`; a
    run of status `permission_blocked` gives `kind: "permission"`; `timeout` and `schema_invalid` are returned with no
    second call; a `select` that raises `WaitingCapacity` makes the chain return the last result with the detail
    `no profile of roles.verifier_agent could answer: first: length: ...`; the skip set holds the failed profile; a
    discarded call's cost is a `budget.cost` with its profile;
  - SCN-VER-362, SCN-VER-363, SCN-VER-365 and SCN-VER-366 end to end with `run_l4` (two writer profiles);
  - SCN-VER-364: three writer profiles, the second of the implementer's vendor: it is never asked;
  - SCN-VER-367: a round with a UI gap (as the step-5 tests of `tests/unit/verifier/test_generate.py` or
    `test_ui_flow.py` set one up) whose first writer errs: the second writes the UI test;
  - SCN-VER-368: a timeout and a twice-invalid reply of the first writer: the second is never asked;
  - SCN-VER-369: the discarded call's `budget.cost`.
  Run the file and see the tests fail.
- [ ] 3.2 Then add `src/l4/verifier/writer_chain.py` (`WriterChain`, D3) and build it in `writer_for`
  (`src/l4/verifier/ladder.py`), with one `skip: set[str]` and one `failures: list[str]` per round in the hook, beside
  the judges' `skip`. After a limit use `services.factory.on_limit(current, run)` and `probe_vetoes`, as `next_judge`
  does. Leave the three raise sites of `src/l4/verifier/audit.py` and the reply handling of
  `src/l4/verifier/generate.py` as they are, except where a test shows they lose the chain's detail. Run the new file,
  then `tests/unit/verifier/test_ladder.py`, `test_ladder_depth.py`, `test_generate.py`, `test_judge_chain.py` and
  `tests/unit/verifier/test_audit.py`, one at a time.

## 4. Checks

- [ ] 4.1 `docs/SPEC.md` holds L4-VER-089..091, SCN-VER-356..369, change-table row 142 and the L4-VER-002 and
  L4-VER-015 amendments. Check them against the code and tell the orchestrator where they differ; do not edit
  `docs/SPEC.md`, `CHANGELOG.md` or `docs/runbook.md`. Run `uv run --frozen python scripts/check_spec.py docs/SPEC.md`.
- [ ] 4.2 `uv run --frozen ruff check` and `uv run --frozen ruff format --check` on the files you changed.
