## 0. Contract (orchestrator, before wave 1)

- [ ] 0.1 `src/l4/yolo/model.py`: the shared types of design D1, D2, D4, D5, D8, D9, D10 (`Plan` and its parts, `load_plan`, `PlanInvalid`, `Finding`, `Admission`, `UnitInfo`, `Eligibility`, `PlanEvent`, `PlanState`, `Usage`, `Verdict`, `ReviewResult`, `MergeOutcome`, `ProfileResult`, `YoloStep`, `PlanMoved`). Wave agents build to these and do not change them without the orchestrator. (L4-YOLO-001)

## 1. Plan, admission, digests, config (wave 1, agent A: `yolo/admit.py`, `yolo/digest.py`, `config/schema.py` `YoloCfg`)

- [ ] 1.1 `admit()` with every finding code of D2, the unit/batch graph, cycle detection that names the path, and the topological order with the tie rule. Tests SCN-YOLO-03..05, one test per finding code. (L4-YOLO-002)
- [ ] 1.2 `next_eligible()` (D2): direct and batch-induced prerequisites, accepted batches, the wait reasons. Tests for A→B, A+B→C, batch b2 after b1, and an integrated unit. (L4-YOLO-010)
- [ ] 1.3 `unit_digest()` and `plan_digest()` (D3) with the exclusions and the marker normalisation. Tests SCN-YOLO-06, SCN-YOLO-07, OpenSpec and Kiro folders. (L4-YOLO-003)
- [ ] 1.4 `yolo.profiles` in `config/schema.py` (`YoloCfg`, gate kinds validated, `all` and `none` reserved). (L4-YOLO-009)

## 2. Plan ledger (wave 1, agent B: `yolo/store.py`, `yolo/state.py`)

- [ ] 2.1 `PlanStore.read/append/list_plans` (D4): plumbing commits with `ledger.jsonl`, optional `report.md` and `receipts/*.json`; `git push --atomic --force-with-lease`; `PlanMoved` on a lost lease. Tests with a bare `origin` in a temp folder, SCN-YOLO-12 with two clones. (L4-YOLO-006)
- [ ] 2.2 `fold_plan()` for every event of D4, usage that never resets, `extended`, status transitions. Table tests. (L4-YOLO-006, L4-YOLO-014)
- [ ] 2.3 Receipts written once per `receipt_id`. (L4-YOLO-015)

## 3. Review and post-merge checks (wave 1, agent C: `yolo/readiness.py`, `yolo/postcheck.py`, `yolo/prompts/readiness.md`, `yolo/schemas/readiness.schema.json`)

- [ ] 3.1 The readiness prompt and schema (D5); `review_plan()` through the judge's adapter machinery, read-only tools; parse and the two override rules. Tests with the fake adapter: SCN-YOLO-08, SCN-YOLO-09, a READY unit, a batch review. (L4-YOLO-004)
- [ ] 3.2 `run_profile()` (D9): a detached worktree at a revision, the existing gate runner and sandbox, kinds from `yolo.profiles`, `all`, `none`, a profile with nothing to run is `error`, cleanup. Tests with a temp repo and shell gates. (L4-YOLO-009)

## 4. Guarded merge and the destination check (wave 1, agent D: `yolo/merge.py`, `ci/sweeper.py` `_own_mr`, `postmerge.py` `merge_archive_guarded`)

- [ ] 4.1 `merge_guarded()` and `confirm_merged()` (D8): the four preconditions in order, the push without force, `stale`/`refused`/`merged`. Tests against a bare `origin` (a moved target is refused by git itself) and a fake forge. SCN-YOLO-14..16. (L4-YOLO-008)
- [ ] 4.2 `_own_mr` counts a merged PR only when `pr.base_branch == forge.base_branch`; the log line and the cause text of D7. SCN-YOLO-13; the existing sweeper tests stay green. (L4-YOLO-007)
- [ ] 4.3 `merge_archive_guarded()` in `postmerge.py`: fast-forward the target to the archive branch head under the same guard; a callable only (wave 2 wires it for plan units). (L4-YOLO-009)

## 5. Plan step and dispatch (wave 2, agent F: `yolo/cycle.py`, `orchestrator.py` `run_command`, `planner.py`, `ci/sweeper.py` wiring)

- [ ] 5.1 `yolo_step()` (D10): reviews, stops, waits, merge + post-check + integration, batch checks, dispatch, completion, report and receipts, one step per run. Tests per branch of D10 with fakes. SCN-YOLO-18, -20, -22..25, -27, -28. (L4-YOLO-009..014)
- [ ] 5.2 `run_command`: `allow` filters `chosen` (plan-held units, SCN-YOLO-30); `start_run(target)` once at the end when `start_next_run`; `l4 run --unit` refusals before the lease (SCN-YOLO-21). (L4-YOLO-010, L4-YOLO-012)
- [ ] 5.3 `l4 plan`: the wait reason for plan units and `not in the active plan <id>` for others. (L4-YOLO-015)
- [ ] 5.4 The sweep merges the archive PR of a `merge: auto` plan unit with `merge_archive_guarded` (SCN-YOLO-19); `open_archive_pr` waits only for open archive PRs whose base is `forge.base_branch` (D9). (L4-YOLO-009)

## 6. Commands (wave 2, agent G: `yolo/commands.py`, `cli.py`, `state/status.py`, `doctor`)

- [ ] 6.1 `l4 yolo check|review|activate|status|cancel|resume|report` (D6) with the refusals of L4-YOLO-005 and D10's resume table. Tests SCN-YOLO-01, -02, -10, -11, -26. (L4-YOLO-005, L4-YOLO-013)
- [ ] 6.2 `l4 status`: the `plan <id>: …` line while a plan is active. (L4-YOLO-015)
- [ ] 6.3 `l4 doctor`: the `merge_policy: auto` warning (SCN-YOLO-17). (L4-YOLO-008)

## 7. Documentation (wave 1, agent E: `docs/SPEC.md`, `docs/yolo-mode.md`, `docs/runbook.md`, skill `operate.md`, `README.md`, `docs/state-diagram.md`)

- [ ] 7.1 SPEC: section 12.5 with L4-YOLO-001..016, the scenarios SCN-YOLO-01..29, the delivery row, §3.2 `yolo.profiles`, the `merge_policy` line. `scripts/check_spec.py docs/SPEC.md` passes. (L4-YOLO-016)
- [ ] 7.2 `docs/yolo-mode.md` (user guide) and runbook section "Delivery plans" with every stop reason and what clears it (SCN-YOLO-29); the skill's `operate.md`; one README line. (L4-YOLO-016)

## 8. Integration and review (orchestrator)

- [ ] 8.1 Merge the wave branches; the full unit suite; ruff; `check_spec`.
- [ ] 8.2 An independent adversarial review of the change; fix the confirmed findings with tests.
- [ ] 8.3 CI (`checks.yml`, `action-selftest.yml`) green on the pushed branch; the three pre-push scans.

## 9. Live validation on the test repository (orchestrator)

- [ ] 9.1 Pin the test repository to the branch commit; `forge.merge_policy: auto`; target `l4/main` (not the default branch), promotion target `amaster`.
- [ ] 9.2 A plan of three small units: A (OpenSpec) → B (OpenSpec, uses A) in batch 1, C (Kiro, uses B) in batch 2 with a batch profile. Review in CI, activate from a laptop, and let it run to `plan.completed`. Evidence: B's branch did not exist before `unit.integrated{A}`; each PR merged by the fast-forward push; the archive PRs merged; `amaster` unchanged; the report.
- [ ] 9.3 Stop cases: a spec push to the current unit (`inputs_changed`); `l4 yolo cancel`; a `merge: human` plan where a person merges.
- [ ] 9.4 `docs/live/yolo-mode/README.md` with run ids and the defects found.
