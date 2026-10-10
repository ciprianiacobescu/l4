# M1.3 progress

One row per build line of `docs/plan/m13-plan.md`. This file records the lines of **Stage A** (the red-phase evidence
and tracing, lines 1-13), built by part M13-A, and of **Stage B** (the verifier ladder depth, lines 14-30), built by
part M13-B, and of **Stage C** (fix units, lines 31-40), built by part M13-C. Status: done, partial, blocked.

| line | change task | status | commit | note |
|---|---|---|---|---|
| 1 | M13-G1 | done | 6f291c8 | pytest 9.1.1 records `<properties>` on every testcase in **both** `xunit1` and `xunit2`, so the trace channel is the junit property `l4`; there is no sidecar and `parse_junit` gets no `trace=` keyword (the Files table lists one for the sidecar alternative). Failure shapes recorded in `failure-kinds-*`, with `scripts/record_pytest_junit.sh` and `PYTEST_VERSION` |
| 2 | M13-G2 | done | 6f291c8 | plugin `src/l4/gates/pytest_trace/l4_trace.py` (no `__init__.py`; shipped by the wheel, checked); `l4.gates.trace.trace_env()`; `run_gate(extra_env=)`, `build_gate_env(extra=)`, `agent_step` adds it to the agent env |
| 3 | implementer-tdd-loop 1.2 | done | 6f291c8 | `TestCase.criteria`, `TestCase.failure_kind`, `failure_kind(status, message)`. A `Name: text` message whose name is not assertion, `Failed` or `NotImplementedError` is `other`; a message of no known shape (and a setup error that is not wrapped) is `None` |
| 4 | spec-providers 1.27 | done | 6f291c8 | `l4.specs.criteria.trace_ids(case)`; takes the junit `TestCase` |
| 5 | implementer-tdd-loop 1.12 + 1.14 | done | 6f291c8 | `contract@3`, `red@2`, output line names `suppressions` |
| 6 | implementer-tdd-loop 1.10 | done | 6f291c8 | `l4.implementer.result.check_criteria` -> `CriteriaCheck` |
| 7 | implementer-tdd-loop 2.16 | done | 6f291c8 | `ImplementerResult.suppressions`; carried by `task.red_ok` and `task.done` once line 12 wires them |
| 8 | implementer-tdd-loop 1.15 (part 1) | done | c4e395a | `l4.implementer.stubs.classify_red_changes(head_src, new_src) -> RedChanges`: HEAD text plus admissible additions by AST. A new class need not have explicit bases (only its body is checked). Field values, decorators outside the allow-list and `Name = value` statements are dropped; the members of a new `Enum`/`Flag` are kept |
| 9 | implementer-tdd-loop 1.15 (part 2) | done | c4e395a | `enforce_red_scope(wb, task, base) -> RedScope`; `guard.violation{phase: red, path, rule, action, region}` per region, `stub.purity{task, stubs, restored}`. **Exempt from the restore:** `tdd.runner_config_files` (red may register markers and add test-only dev dependencies, SPEC L4-IMP-002) and the lock files of `LOCKFILES`; the plan restored every non-Python production file |
| 10 | implementer-tdd-loop 2.2 | done | 9a37b39 | `zero_value_variant`, `discrimination.zero_values_in_place` / `zeroed_run` / `vacuity_check`. The published `.l4-out/junit.xml` is put back as run (a) left it. A test "fails on the zero values" only when it fails by assertion (L4-IMP-002 check 5; the earlier "or `other`" reading was withdrawn in the review fix, see "Review fixes") |
| 11 | M13-G3 | done | 9a37b39 | `discrimination.confirm_pre_satisfied`: scope = project modules the tests import (followed through `__init__.py` re-exports) plus modules changed since the unit base (`merge-base origin/<base> HEAD`) |
| 12 | implementer-tdd-loop 1.18 + 1.19 | done | 9a37b39 | `run_red` in SPEC check order; `classify_red(..., failure_kinds=False, allowed_passing=())`; `RedOutcome.criteria`; `failure_kind` None (unrecognised message or a fixture error) is refused like `other`. Events `test.untraced`, `criterion.pre_satisfied`, `task.red_ok{criteria, suppressions}`, `task.done{suppressions}` |
| 13 | implementer-tdd-loop 2.11 (reduced) | done | 9a37b39 | status `already_satisfied`: commit `test(<unit>): <task> already satisfied` with `L4-TDD: already-satisfied`, marker ticked in the same commit, `task.red_ok` + `task.done{tdd}`; `run_task` skips green. Stubs no test needs are restored to HEAD first |

Existing M0 tests changed because red now needs tagged tests: `tests/unit/implementer/conftest.py` (tagged fixture tests, `KNOWN`/`UNKNOWN` ids, `criteria_ids`), `test_prompt.py` and `test_tdd_red.py` (template versions), `test_tdd_red.py` (two cases: a passing test needs a failing sibling of its criterion, a regression now needs a changed test file because the guard restores changed production code), `test_setup.py` (the `test-zero` gate after `test`), `tests/unit/orchestrator/test_{run_unit,reentry,scenario_lint}.py` (tagged shout test, a Known-code-only red).

Report notes for the integrator: `task.red_ok.criteria[C]` is `{tests, proof, discriminating}` - `tests` trace the criterion, `discriminating` are the ones the zero-value run showed to fail (for `red_assertion`, all of them). Stage B's per-test adequacy can read it. Run (b) is strictly "by assertion" again (review fix).

## Stage B (M13-B)

S0 (`m1x-seams`: `testwriter.py`, `generated-test.schema.json`, `versions.py`) is not on `main` yet: it was merged into
this branch before line 24 (`c5bdb29`, new files only). M1.2 is not on `main` either, so the audit writer uses
`require_independent_judge` and `for_role("verifier_agent", ..., serves=JUDGE_ADAPTERS)` (contract C1, "until" column).

| line | change task | status | commit | note |
|---|---|---|---|---|
| 14 | verifier 2.1 (reduced) | done | d1f746e | `tests/fixtures/py_integrity/{must_catch,must_pass}/<case>/{base,red,head}` with a `case.json` each; `tests/unit/verifier/test_integrity.py::test_gaming_cases_caught_and_valid_cases_pass` runs all twelve. "Call-only test" and "zero-answer test with a sibling" are caught/passed by step 4 (the ledger proof), the dataclass and exception-class cases by the red-phase stub guard (`classify_red_changes`) |
| 15 | verifier 2.2 | done | d1f746e | `integrity.run_integrity(IntegrityContext) -> IntegrityReport`; six sub-checks, one `verification.md` row each (`## Integrity`); step 1 sits between 0 and 2 and a blocker/major stops the ladder |
| 16 | verifier 2.3 (reduced) | done | d1f746e | `check_protected`: `CONTRACT_PROTECTED_GLOBS` and `odd.forbidden_paths` between base and head, minus the family's unit dirs and `.serena/memories/harness/**` |
| 17 | verifier 2.4 (reduced) | done | d1f746e | `check_tests`: AST diff; a test moved to another changed file is not deleted; module-wide `pytestmark` skips and `pytest.skip(` calls count |
| 18 | verifier 2.5 | done | d1f746e | `check_freeze`: `task.red_ok.frozen` identical at the red and green sha, plus `pytest.ini`/`tox.ini`/`setup.cfg` and the `[tool.pytest*]`/`[tool.coverage*]` tables of `pyproject.toml` |
| 19 | verifier 2.6 | done | d1f746e | `check_scan` (hits that the base did not have); `[test-infra]` exempts the files that tagged task's commits touched; any new module named `l4_trace` is a hit |
| 20 | verifier 2.10 | done | d1f746e | `check_suppressions`; a declaration matches by file and line, or by file and rule, and covers one comment (lines drift between commits); `nosec`/`gitleaks:allow` are major unless a `[config]` task touched the file; declared ones are listed in the report and in the judge's gate report |
| 21 | verifier 2.13 (reduced) | done | d1f746e | `check_tdd_history`; "red tests present and passing at head" is discharged by step 3 (`must_contain`), the row says so |
| 22 | verifier 1.9 + 3.4 + 3.5 | done | d1f746e, 4271194 | `traceability.trace_criteria(criteria, report, ledger, cfg, *, extra_reports=(), base=())`; proofs from `task.red_ok.criteria` and accepted `verify.audit` events (a test cannot claim `audit` by its name); `## Traceability` matrix |
| 23 | verifier 1.13 + 4.7 | done | d1f746e, 4271194 | `aggregate_criterion(..., *, trace, human, require_traceability)`; `disputed` is a result; `uncovered` stays `needs_human` (the S1 row is deferred, so `sdd.require_traceability: false` only changes the reason) |
| 24 | verifier 3.7 + 3.8 | done | d1f746e, 4271194 | `audit.py` and `evidence.commit_verifier_tests`; step 4a, one gate run for the round's audit tests, accepted through `confirm_pre_satisfied` |
| 25 | verifier 1.17 | done | 6ed1777 | `verdicts.raise_verdict_questions`; `questions.py` renders and reads `Blocking tasks: none` for `Kind: verdict` |
| 26 | verifier 5.8 + 5.9 | done | 6ed1777 | `verdicts.consume_verdicts`, `effective_verdicts`, `regressions` (`human.void`) |
| 27 | verifier 5.2 (reduced) | done | 4271194 | `evidence.subject_sha`, `read_verdict`, `reusable`, `restore_round`; the hook decides to resume before it selects (and probes) a judge |
| 28 | state-vcs-locks 1.20 delta | done | ed94add | four triggers and rows, `fixing` in the sources of `required_role_unavailable` and `breaker_or_budget`; fold fields and handlers |
| 29 | simulation-harness 1.13 delta + implementer-tdd-loop 2.31 (part) | done | 6ed1777 | `UnitFacts.verdicts_*`, planner rows, `Orchestrator._verdicts_ready` and the `AWAITING_HUMAN` verdict branch |
| 30 | verifier 1.19 (part 1) | done | 4271194 | `LADDER`, `verify_unit`, `report.py`, `verify_hook` (questions in the evidence commit, `ctx.shared["notes"]`), `run_verify` takes a unit whose verdicts are answered |

## Stage C (M13-C)

`main` was merged first (`f148142`; M1.1 Stage C, line 39's dependency, was already there). The pinned OpenSpec 1.14.0 is
installed on the development machine, so `tests/contract/test_openspec_fix_unit.py` (marker `live`) was run once with
`L4_LIVE=1`: `skip_specs` and an ADDED `— regression 1` delta both pass `validate --strict`.

| line | change task | status | commit | note |
|---|---|---|---|---|
| 31 | spec-providers 1.32 + 1.33 | done | d3e7977 | `OpenSpecProvider.create_fix_unit(parent, round, findings, spec_delta)`, `FixUnitCapable`, `Finding`, `SpecDelta`, `FixUnitExists`, `FixUnitInvalid`; `l4.specs.fixmark` (`.l4/fix.json`). `round` is the **ordinal** of the fix unit (`<parent>-fix-<round>`), not the verification round. The folder is removed when strict validation fails; whatever the CLI wrote outside the change (`openspec/config.yaml`) is removed too. The delta gets the parent's `## Purpose` |
| 32 | verifier 1.18 + 5.10 | done | 0c36f8a | `verifier.fixunit.plan_fix_unit(family, result, human, *, ordinal, fix_minor) -> FixPlan(groups, delta, consumed, not_converted)` (a `FixPlan` instead of the plan's pair, so the report can list what was not converted) |
| 33 | verifier 1.5 (delta) | done | 0c36f8a | `judge@3` (`PROMPT_VERSION = 3`): the system prompt asks for the closest criterion and a one-sentence `WHEN ... THEN ...` fix; the matrix, audit results and declared suppressions already travel in the gate report (Stage B) |
| 34 | implementer-tdd-loop 1.25 (reduced) | done | 7e9e584 | `tdd.run_single`, template `single@1`, `task.tdd_exempt{kind: harness, finding, findings}`, commit `fix(<fix unit>): <title> [skip ci]` with `L4-TDD: exempt`. A task is a chore only when the marker lists one of its finding ids (never because of its text). The finding's failing tests as must-pass ids are not built |
| 35 | M13-G4 | done | ca18899 | `verifier.fixloop`: `FamilyProvider`, `fix_hook`, `FixOutcome`, `is_fix_unit`, `fix_units_of`, `family_units`, `family_tasks`, `without_fix_units`; `Workbench.event_context`, `make_workbench(..., event_context, extra_unit_dirs, caches, ledger_rel)`, `ProtectedSet.extra_dirs`, `HOOKS["fix"]`, `Hooks.fix`. The fix unit's re-entry is its own (the parent's `Clarifier.reenter` reads the ledger of the directory it is given) |
| 36 | M13-G5 | done | ca18899 | `.l4/fix.json`, `status.child_snapshots`, `UnitSnapshot.children` and `fix_of`, planner rows, `run_command` filters fix units and `--unit <fix>` exits 2 |
| 37 | verifier 1.19 (delta, part 2) | done | ca18899 | `fixloop.decide_fix` (before the evidence, so `verification.md` has a `## Fix unit` section) and `fixloop.after_verdict(ctx, wb, result, trigger) -> Trigger` (it takes the verdict's trigger as a fourth argument); `verify_hook` verifies the family; step 0 loops over the family's units |
| 38 | implementer-tdd-loop 2.31 (reduced) | done | ca18899 | `Orchestrator._fix`, the `FIXING` and open-fix-unit `VERIFIED` branches, `_verify` goes on after `verifying -> fixing` when `hooks.fix` exists, the `fixing` row of `_NEEDS_A_HUMAN` is gone, `ctx.shared["implementer"]` |
| 39 | forge-and-ci 1.33 (delta) | done | 7b5fb4a | `PostMergeArchiver._build` archives the parent, then `fix_units_of(...)` in round order, in the one archive commit |
| 40 | M13-G6 | partial | d867d60 | `tests/live/test_m1_3_acceptance.py`: nine tests, one per protocol step, every one skips until its step has happened. Not run: it needs the runner pipeline |

## Review fixes (m1.3(fix))

| finding | status | note |
|---|---|---|
| blocker: `fails_on_zero` admitted `other` | done | assertion only; vacuity/not-discriminating feedback tells the agent to assert `result is not None` / isinstance first, then on attributes |
| major: fix-unit task could not resume at green | done | `resume_red` reads the ledger the workbench writes to (the parent's) and matches `sha` and `fix_unit` |
| major: a hold was a dead end | done | every hold gets a `Kind: verdict` question (target `H-<sha8>`); `accept` waives it, `reject` keeps NEEDS_HUMAN with the human |
| minor: symlinked directory in zero-value runs | done | `_is_inside` for the write target and for `_resolve` |
| minor: already-satisfied removed a stub a test imports | done | the test gate is re-run on the restored head; failure feeds back to the agent |
| minor: suppression exclusion by name glob | done | excludes the paths of `verify.audit` events |
| minor: `trace_criteria` extra reports | done | `generated=` names the accepted ids; C8 in parallel-ownership.md updated |
| minor: human-rejected finding became a chore | done | listed as not converted ("answer again with a scenario") |
| minor: red-scope restore exempts runner config | deferred | needs the gate-config check (verifier 2.9, deferred): restoring `pyproject.toml` section-wise is not local |
| minor: fix loop failures | partly | superseded by the second review round below; an unconvertible reject is listed and, with no other task, escalates |
| minor: fix unit text not redacted | done | `redact_plan` before `create_fix_unit` |
| minor: contract drift | done (docs) | C8 and C18 updated; the `m1x-seams` landing and the `_judge_step` merge note are for the integrator |

## Review fixes, round 2 (m1.3(fix))

| finding | status | note |
|---|---|---|
| major: agent-written test code forges a human verdict through a gate run | done | `Workbench.run_gate` snapshots the protected set (contract paths, the unit directory, the extra unit directories; the run's own ledger excepted) and puts it back after the gate: changed and deleted entries are rewritten, new ones removed, a symlink put in place of a directory is replaced, never written through. `guard.violation{phase: gate}`. Defence in depth: `consume_verdicts` records only questions with a `question.raised{kind: verdict}` event |
| major: a PASS became exit 13 when the optional minor fix unit failed | done | on a PASS any `SpecError` from `create_fix_unit` downgrades the decision to `none` (the reason is listed as not converted); `verification.md` and the round evidence are written again and committed as `verification round n amended` |
| major: a `[chore]` task could rewrite the frozen red tests | partly | `run_single` restores every file that a `task.red_ok.frozen` of the unit lists (and the support and ignore files) to its content at the step base, `guard.test_tamper{phase: single}`. A chore may still edit tests no red froze (D8: "a test that fails at step 3"). **Not built**: the integrity check that keys a proof by the test's content instead of its id (a later task's red can still rewrite an earlier task's proved test; verifier 2.x, M1) |
| major: vacuity bypass when the stub already exists at HEAD | done | red adds no stub: run (b) zeroes the HEAD stubs of the modules the tests import (`head_stub_modules`); with no stub anywhere, each open criterion needs a test that failed by assertion in run (a) (`no_assertion_failure`). `discriminating` is what actually failed by assertion, no longer "all tests" |
| minor: transient OpenSpec errors escalated a FAIL | done | `OpenSpecCommandError` and `OpenSpecUnavailable` propagate (exit 1/3, the unit stays `verifying`). **Plan deviation (recorded)**: `FixUnitInvalid`, `FixUnitExists` and the other deterministic `SpecError`s on a FAIL end in `verify_fail_exhausted` (exit 13), not "exit 1, nothing committed" as plan line 31 says: the same plan fails the same way next round and each round costs a judge call |
| minor: escalation note not redacted | done | `escalation_section(result, reason, redact)`; every judge-written or error text is redacted before it is flattened and cut |
| minor: `FamilyProvider` interface | done | `done_gate` is the wrapped provider's gate per member (reasons prefixed with the unit name); `create_fix_unit` raises `SpecError`, not `TypeError`; C10 says to ask `can_fix` |
| minor: stub keeps a default that reads a dropped module value | done | a default or annotation of a new stub that reads a name the rebuild dropped becomes `None` / is removed |
| minor: orphan fix unit | done | there was no open-problem text about it in this file to correct. Behaviour: `_used_rounds` does count a committed orphan, so the next round did pick ordinal n+1 (the reviewer's reading is right) and the orphan stayed unrun. Now `decide_fix` records a committed fix unit without `fix.spawned` (`adopted: true`), and a FAIL with an open fix unit that has unticked tasks runs that unit (no second one is planned). Limits: the verdict questions the orphan consumed are not recorded (the marker does not carry them), and an uncommitted orphan folder is left alone; adoption trusts any committed `.l4/fix.json` that names the parent (same trust as agent code: planted unticked tasks fail step 0) |

Doc changes owed (not edited here): `m13-plan.md` line 31 says `FixUnitInvalid` is "exit 1, nothing committed"; on a FAIL it is exit 13 (`escalated`), and on a PASS it no longer fails the unit (see round 2 above).

## Review fixes, round 3 (m1.3(fix))

`main` was merged first (the merge commit "m1.3(merge): take main ..."): the one conflict was the `verify.verdict` emit in
`verify_hook`; main's multi-line emit (with `criteria_passed` / `criteria_total`) is followed by
`return after_verdict(ctx, wb, result, TRIGGERS[result.verdict])`. `ProgressTrace` and the `Git.on_commit` / `on_push`
hooks are main's and unchanged, with one addition: events that carry `fix_unit` print `[<fix unit>]` before the message
and the step start times are keyed by it too (task keys repeat between a parent and its fix units). Checked on the
fix-loop e2e tests (`test_ladder_fix.py`): repeated keys neither crash nor garble the trace.

| finding | status | note |
|---|---|---|
| blocker: test code in the red gates rewrites production after the stub guard | done | `stubs.ProductionGuard` records the content of every changed non-exempt production path right after `enforce_red_scope`; `run_red` re-checks after run (a), `confirm_pre_satisfied`, `vacuity_check`, `test-restored`, `worse_static_gates` and right before each commit. Any added, changed or deleted path is put back (guarded content, or `base` for a new path), `guard.violation{phase: red, rule: "gate-mutated-production", where}` is recorded and the attempt fails with feedback. Paths under cache directories (`__pycache__`, `.pytest_cache`, ...) and `.pyc` files are not production. The harness's own removal of an unused stub (`already-satisfied`) is released from the guard |
| blocker: an agent plants a fix unit that is adopted TDD-exempt | done | (a) `ProtectedSet.family_globs`: every workbench protects `<changes>/<unit>-fix-*` (the child workbench: the parent's family), so no agent step or gate run can create or edit a fix folder (revert after the step; snapshot/restore around gate runs include existing and new family folders). (b) `l4.verifier.provenance`: `fix_units_of(..., git=, on_reject=)` and `FamilyProvider(..., git=, on_reject=)` list a fix unit only when the commit that introduced `<fix>/.l4/fix.json` is the harness's (author = `BOT_IDENTITY`, subject `docs(<parent>): fix unit <n> [skip ci]`, `L4-Run` trailer) and the marker is unchanged since. Rejected folders are ignored and recorded as `guard.violation{phase: verify, rule: "foreign-fix-unit"}` (`fixloop.family_of`). `adopt_orphans` and `fix_hook` use it. Without `git` (the post-merge archiver, where a squash rewrote the history) the marker alone is trusted, as before |
| major: sibling fix units unprotected during a fix task | done | `_child_workbench` passes every family member except the running fix unit as `extra_unit_dirs`; `integrity.check_protected` no longer exempts the family wholesale: a commit in `base..head` that touches a fix unit and is not the harness's is a blocker (a human commit that touches only the fix unit's `questions.md` is not foreign), and so is a path in the family namespace that is not one of its fix units |
| blocker: merge with main | done | see above |
| blocker (found by the round-3 verifier): bytecode planted by a red gate run reaches the green gate | done | `ProductionGuard` leaves `__pycache__`/`.pyc` alone, and so did every other guard (the harness's ignore file). A red test that writes an unchecked hash-based `.pyc` for `pytdd/__init__.py` as the last red gate run exits made a green step that left the stub in `pricing.py` pass and commit. `Workbench.run_gate` now calls `purge_bytecode` first: every untracked `*.pyc` and everything in a `__pycache__` directory of the worktree is deleted (not under `.venv/`, `node_modules/`, `.git`; a symlinked `__pycache__` is unlinked, a symlinked directory never walked through). Test: `test_bytecode_that_a_red_gate_plants_never_reaches_a_later_gate` (red before the fix) |

Limits: author and trailers are forgeable by a process that can run `git commit`; agent steps cannot (the sandbox makes
`.git` read-only and `revert_protected` drops agent commits), so this is defence in depth, not a signature.
Not fixed (design): a gate run can also write into `.venv/` (a `.pth` or `sitecustomize.py` in site-packages runs at
every interpreter start and survives `uv sync`); closing it needs `.venv` read-only in non-setup gates or a rebuilt
environment.
