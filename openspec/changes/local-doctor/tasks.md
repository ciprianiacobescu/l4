## 1. LOCAL-001

- [ ] 1.1 Read `src/l4/doctor/registry.py` (levels, scopes, `register`, `CHECK_MODULES`), `src/l4/doctor/context.py`
  (`DoctorContext`), `src/l4/doctor/checks_sandbox.py` (style), `tests/unit/doctor/conftest.py` (`FakeTools`,
  `make_ctx`) and `src/l4/sandbox/select.py` (`sandbox_refusal`, `select_sandbox`; `mode: user`/`container` raise
  `L4Exit`). Write the tests first (`tests/unit/doctor/test_checks_local.py`, new): SCN-NFR-05 (macOS text via the
  `platform` argument), SCN-DOC-10 (`--ci` scopes leave it out: use `doctor_scopes`), SCN-DOC-11 (bwrap probe ok; `none`
  with `allow_none`), `mode: none` without `allow_none` (fail with the preflight's reason), `mode: user` (fail "not built
  yet", no crash). Then add the row (warn, scopes `{"local"}`), calling `sandbox_refusal` with a runner that goes
  through the doctor context or `proc.Runner` as the preflight does (keep the doctor's timeout), and catching `L4Exit`
  for an unbuilt mode. Add LOCAL-001 to the id list in `tests/unit/doctor/test_doctor_cli.py`.

## 2. The artefacts line

- [ ] 2.1 Write the test first (`tests/unit/obs/test_progress.py`, next to the one that asserts the CI suffix): a call
  for a local run has no "(CI: job artifacts)". Then give `log_artefacts` the answer of `in_ci_job` from its caller
  (src/l4/orchestrator.py) instead of a new read of an environment variable (`tests/unit/ci/test_ci_rule.py` must pass
  unchanged).

## 3. Checks

- [ ] 3.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you changed or added plus the test files that import a module you changed (`grep -rl` for the module name under tests/unit), in one pytest invocation; not whole directories (a combined run follows after the merge). Run ruff check and ruff format on the changed files. Report the counts. Do not edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md (a docs pass does that).
