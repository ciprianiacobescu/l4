## 0. Contract (orchestrator, before wave 1)

- [ ] 0.1 `src/l4/yolo/model.py`: the shared types of design D1, D2, D4, D5, D8, D9, D10 (`Plan` and its parts, `load_plan`, `PlanInvalid`, `Finding`, `Admission`, `UnitInfo`, `Eligibility`, `PlanEvent`, `PlanState`, `Usage`, `Verdict`, `ReviewResult`, `MergeOutcome`, `ProfileResult`, `YoloStep`, `PlanMoved`). Wave agents build to these and do not change them without the orchestrator. (L4-YOLO-001)

## 1. Plan, admission, digests, config (wave 1, agent A: `yolo/admit.py`, `yolo/digest.py`, `config/schema.py` `YoloCfg`)

- [x] 1.1 `admit()` with every finding code of D2, the unit/batch graph, cycle detection that names the path, and the topological order with the tie rule. Tests SCN-YOLO-03..05, one test per finding code. (L4-YOLO-002)
- [x] 1.2 `next_eligible()` (D2): direct and batch-induced prerequisites, accepted batches, the wait reasons. Tests for A→B, A+B→C, batch b2 after b1, and an integrated unit. (L4-YOLO-010)
- [x] 1.3 `unit_digest()` and `plan_digest()` (D3) with the exclusions and the marker normalisation. Tests SCN-YOLO-06, SCN-YOLO-07, OpenSpec and Kiro folders. (L4-YOLO-003)
- [x] 1.4 `yolo.profiles` in `config/schema.py` (`YoloCfg`, gate kinds validated, `all` and `none` reserved). (L4-YOLO-009)

## 2. Plan ledger (wave 1, agent B: `yolo/store.py`, `yolo/state.py`)

- [x] 2.1 `PlanStore.read/append/list_plans` (D4): plumbing commits with `ledger.jsonl`, optional `report.md` and `receipts/*.json`; `git push --atomic --force-with-lease`; `PlanMoved` on a lost lease. Tests with a bare `origin` in a temp folder, SCN-YOLO-12 with two clones. (L4-YOLO-006)
- [x] 2.2 `fold_plan()` for every event of D4, usage that never resets, `extended`, status transitions. Table tests. (L4-YOLO-006, L4-YOLO-014)
- [x] 2.3 Receipts written once per `receipt_id`. (L4-YOLO-015)

## 3. Review and post-merge checks (wave 1, agent C: `yolo/readiness.py`, `yolo/postcheck.py`, `yolo/prompts/readiness.md`, `yolo/schemas/readiness.schema.json`)

- [x] 3.1 The readiness prompt and schema (D5); `review_plan()` through the judge's adapter machinery, read-only tools; parse and the two override rules. Tests with the fake adapter: SCN-YOLO-08, SCN-YOLO-09, a READY unit, a batch review. (L4-YOLO-004)
- [x] 3.2 `run_profile()` (D9): a detached worktree at a revision, the existing gate runner and sandbox, kinds from `yolo.profiles`, `all`, `none`, a profile with nothing to run is `error`, cleanup. Tests with a temp repo and shell gates. (L4-YOLO-009)

## 4. Guarded merge and the destination check (wave 1, agent D: `yolo/merge.py`, `ci/sweeper.py` `_own_mr`, `postmerge.py` `merge_archive_guarded`)

- [x] 4.1 `merge_guarded()` and `confirm_merged()` (D8): the four preconditions in order, the push without force, `stale`/`refused`/`merged`. Tests against a bare `origin` (a moved target is refused by git itself) and a fake forge. SCN-YOLO-14..16. (L4-YOLO-008)
- [x] 4.2 `_own_mr` counts a merged PR only when `pr.base_branch == forge.base_branch`; the log line and the cause text of D7. SCN-YOLO-13; the existing sweeper tests stay green. (L4-YOLO-007)
- [x] 4.3 `merge_archive_guarded()` in `postmerge.py`: fast-forward the target to the archive branch head under the same guard; a callable only (wave 2 wires it for plan units). (L4-YOLO-009)

## 5. Plan step and dispatch (wave 2, agent F: `yolo/cycle.py`, `orchestrator.py` `run_command`, `planner.py`, `ci/sweeper.py` wiring)

- [x] 5.1 `yolo_step()` (D10): reviews, stops, waits, merge + post-check + integration, batch checks, dispatch, completion, report and receipts, one step per run. Tests per branch of D10 with fakes. SCN-YOLO-18, -20, -22..25, -27, -28. (L4-YOLO-009..014)
- [x] 5.2 `run_command`: `allow` filters `chosen` (plan-held units, SCN-YOLO-30); `start_run(target)` once at the end when `start_next_run`; `l4 run --unit` refusals before the lease (SCN-YOLO-21). (L4-YOLO-010, L4-YOLO-012)
- [x] 5.3 `l4 plan`: the wait reason for plan units and `not in the active plan <id>` for others. (L4-YOLO-015)
- [x] 5.4 The sweep merges the archive PR of a `merge: auto` plan unit with `merge_archive_guarded` (SCN-YOLO-19); `open_archive_pr` waits only for open archive PRs whose base is `forge.base_branch` (D9). (L4-YOLO-009)

## 6. Commands (wave 2, agent G: `yolo/commands.py`, `cli.py`, `state/status.py`, `doctor`)

- [x] 6.1 `l4 yolo check|review|activate|status|cancel|resume|report` (D6) with the refusals of L4-YOLO-005 and D10's resume table. Tests SCN-YOLO-01, -02, -10, -11, -26. (L4-YOLO-005, L4-YOLO-013)
- [x] 6.2 `l4 status`: the `plan <id>: …` line while a plan is active. (L4-YOLO-015)
- [x] 6.3 `l4 doctor`: the `merge_policy: auto` warning (SCN-YOLO-17). (L4-YOLO-008)

## 7. Documentation (wave 1, agent E: `docs/SPEC.md`, `docs/yolo-mode.md`, `docs/runbook.md`, skill `operate.md`, `README.md`, `docs/state-diagram.md`)

- [x] 7.1 SPEC: section 12.5 with L4-YOLO-001..016, the scenarios SCN-YOLO-01..29, the delivery row, §3.2 `yolo.profiles`, the `merge_policy` line. `scripts/check_spec.py docs/SPEC.md` passes. (L4-YOLO-016)
- [x] 7.2 `docs/yolo-mode.md` (user guide) and runbook section "Delivery plans" with every stop reason and what clears it (SCN-YOLO-29); the skill's `operate.md`; one README line. (L4-YOLO-016)

## 8. Integration and review (orchestrator)

- [ ] 8.1 Merge the wave branches; the full unit suite; ruff; `check_spec`.
- [ ] 8.2 An independent adversarial review of the change; fix the confirmed findings with tests.
- [ ] 8.3 CI (`checks.yml`, `action-selftest.yml`) green on the pushed branch; the three pre-push scans.

## 9. Live validation on the test repository (orchestrator)

- [x] 9.1 Pin the test repository to the branch commit; `forge.merge_policy: auto`; target `l4/main` (not the default branch), promotion target `amaster`.
  - Done on two repositories instead: the GitHub dummy is a new public repository (GitHub-hosted runners are free there) with `l4/main` as its default branch, and no promotion target (plan.md: `promotion` only when a person names an existing branch); the GitLab one as in 9.4.
- [x] 9.2 A plan of three small units: A (OpenSpec) → B (OpenSpec, uses A) in batch 1, C (Kiro, uses B) in batch 2 with a batch profile. Review in CI, activate from a laptop, and let it run to `plan.completed`. Evidence: B's branch did not exist before `unit.integrated{A}`; each PR merged by the fast-forward push; the archive PRs merged; `amaster` unchanged; the report.
  - Done in a larger form on both forges (docs/live/yolo-mode): ten units in five waves with cross-framework dependencies; `analyze_enforcement.py` (git only) shows every unit dispatched and first run after its prerequisites were integrated; a batch acceptance profile in plan `batch-gl` on GitLab.
- [ ] 9.3 Stop cases: a spec push to the current unit (`inputs_changed`); `l4 yolo cancel`; a `merge: human` plan where a person merges.
  - Live: `inputs_changed` with its recovery (stops-a), `l4 yolo cancel` (stops-b, and final-gl on GitLab), and a `merge: human` plan that never merges (PR #21). Open: a person's merge of a `merge: human` unit was not exercised.
- [x] 9.4 GitLab (a self-hosted instance, a disposable project, vendored harness, integration branch `staging`, default `main`, runner tag `agentic`): the same three-unit plan to `plan.completed`, MRs merged by the push, `main` unchanged; one stop case.
  - Ten-unit plan `valuation` to `plan.completed`, MRs !2–!17 merged by the push, `main` unchanged; stop case: `l4 yolo cancel` of `final-gl` while its second unit was current.
- [x] 9.5 `docs/live/yolo-mode/README.md` with run ids and pipeline ids for both forges, and the defects found.

## 10. Plan graph tooling and the OpenCode key (scenario preparation, 2026-10-15)

- [x] 10.1 OpenCode's own key, design D16: `profile_credential_variable`, the loader in `opencode.py`, the probe's auth and hello, `credential_secrets`, readiness and doctor, `DEFAULT_REDACT_ENV`. Tests SCN-PRV-75..77, plus: a free model unchanged, a custom provider unchanged, a subscription profile unchanged, no login lock for `api_key`. (L4-PRV-028)
- [x] 10.2 `Plan.exclude` (design D15): model, admission findings, holding, status lines, digest. Tests SCN-YOLO-35, SCN-YOLO-36, and an excluded unit that no provider knows. (L4-YOLO-017)
- [x] 10.3 `l4 yolo draft` and `--update` (`yolo/draft.py`, commands, CLI help row). Tests SCN-YOLO-37, SCN-YOLO-38, derived units covered by the parent, refusal of an existing file without `--update`, `gone:` lines, no git write. (L4-YOLO-018)
- [x] 10.4 `scripts/validate_plan.py` and its byte-equal copy in the skill. Tests SCN-YOLO-39..41, the copy check, discovery parity with the providers, schema parity with `load_plan`, order parity with `admit.plan_order`, `--json`, exit codes 0/1/2. (L4-YOLO-019)
- [ ] 10.5 `plugins/l4/skills/l4/references/plan.md` and the `SKILL.md` link; `docs/SPEC.md` (§12.5 and §23.20: L4-YOLO-017..020, L4-PRV-028 next to L4-PRV-024 and 027, the credential table row), `docs/yolo-mode.md`, runbook §12 (draft, validate, update), `scripts/check_spec.py` clean, `openspec validate yolo-mode --strict` clean. (L4-YOLO-020, L4-PRV-028)
  - Done except the last check: `openspec validate yolo-mode --strict` reports 16 requirements over 500 characters (the SPEC's paragraph style; operator-commands on amaster has 6 of the same). Splitting them is a separate change.
- [x] 10.6 Skill check (orchestrator): an agent without `plan.md` and an agent with it plan the scenario's ten specs. The plan written with the skill passes the validator, and every dependency it lists is stated in the specs. (SCN-YOLO-42)
  - Baseline without `plan.md`: planned an in-review unit, kept merged units out of the file, invented a promotion target. With `plan.md`: fetched `refs/l4/*` first, excluded the four existing units with checkable reasons, no promotion, nine dependencies each backed by a spec line; validator exit 0. It found two guide gaps, fixed.
