## 1. LOCAL-001

- [x] 1.1 Read `src/l4/doctor/registry.py` (levels, scopes, `register`, `CHECK_MODULES`), `src/l4/doctor/context.py`
  (`DoctorContext`), `src/l4/doctor/checks_sandbox.py` (style), `tests/unit/doctor/conftest.py` (`FakeTools`,
  `make_ctx`) and `src/l4/sandbox/select.py` (`sandbox_refusal`, `select_sandbox`; `mode: user`/`container` raise
  `L4Exit`). Write the tests first (`tests/unit/doctor/test_checks_local.py`, new): SCN-NFR-05 (macOS text via the
  `platform` argument), SCN-DOC-10 (`--ci` scopes leave it out: use `doctor_scopes`), SCN-DOC-11 (bwrap probe ok; `none`
  with `allow_none`), `mode: none` without `allow_none` (fail with the preflight's reason), `mode: user` (fail "not built
  yet", no crash). Then add the row (warn, scopes `{"local"}`), calling `sandbox_refusal` with a runner that goes
  through the doctor context or `proc.Runner` as the preflight does (keep the doctor's timeout), and catching `L4Exit`
  for an unbuilt mode. Add LOCAL-001 to the id list in `tests/unit/doctor/test_doctor_cli.py`.

  Result: New module `src/l4/doctor/checks_local.py` (listed last in `CHECK_MODULES`) registers LOCAL-001 (warn, scopes
  `{"local"}`). `_local_001(ctx, platform=None)` calls `sandbox_refusal(cfg.sandbox, ctx.env, ctx.repo, platform or
  sys.platform, command="l4 run/l4 verify", runner=...)` with a runner that goes through `ctx.run` (the preflight's
  timeout is passed on); fail text is `l4 run/l4 verify will refuse on this computer: <reason>` (on macOS the ways out);
  an `L4Exit` (a bwrap symlinked into the repository) is a fail with its text; pass names `bwrap`, or `none` with
  `allow_none`. Deviation: `sandbox.mode: user`/`container` is answered by the row itself before the preflight
  (`sandbox.mode: user is not built yet`, with a fix hint) instead of catching the preflight's usage `L4Exit`, because
  that text ("not yet implemented (M2...)") does not say "not built yet" and names no ways out; the `L4Exit` is still
  caught for the repository-bwrap case. In `tests/unit/doctor/test_doctor_cli.py` LOCAL-001 is added to the id list and
  the `world` fixture neutralises `sandbox_refusal` (as it does `detect_platform`), because on a Mac the row correctly
  fails and the end-to-end test asserts a healthy run has no ` fail ` row. Before: `test_checks_local.py` failed at
  collection (`cannot import name 'checks_local'`); after the module, 1 of 11 failed (the repository-bwrap test: the
  PATH filter already drops a repo directory, so the test now symlinks a trusted-dir `bwrap` into the repository);
  then 11 passed, and `test_doctor_cli.py` failed (` fail ` row on a Mac, LOCAL-001 missing from the id list) until
  the fixture and list were updated, now 45 passed across the doctor files run.

## 2. The artefacts line

- [ ] 2.1 Write the test first (`tests/unit/obs/test_progress.py`, next to the one that asserts the CI suffix): a call
  for a local run has no "(CI: job artifacts)". Then give `log_artefacts` the answer of `in_ci_job` from its caller
  (src/l4/orchestrator.py) instead of a new read of an environment variable (`tests/unit/ci/test_ci_rule.py` must pass
  unchanged).

## 3. Checks

- [ ] 3.1 Run, once with pytest (never in a loop, never two runs at once, wait for it to finish), the test files you changed or added plus the test files that import a module you changed (`grep -rl` for the module name under tests/unit), in one pytest invocation; not whole directories (a combined run follows after the merge). Run ruff check and ruff format on the changed files. Report the counts. Do not edit docs/SPEC.md, CHANGELOG.md or docs/runbook.md (a docs pass does that).
