## Context

SPEC section 10 specifies the verifier; section 12.0 defines the phase transitions and exit codes it drives (`verifying` to `verified`, `fixing`, `awaiting_human`, `waiting_capacity`, `escalated`). This change implements it in two milestones. M1 is the thin slice that must run on `example-group/dummy-agentic` through `l4-runner`; M2 deepens every step. The M1 verdict has to be able to reach PASS, otherwise the walking skeleton never produces a merge request: see decision D1.

Evidence labels follow SPEC: [V] verified, [I] inferred or design decision, [U] unverified.

## Goals

- A verifier that never trusts the implementer: fresh worktree at the unit head, no transcripts, hints only as labelled data, different vendor judge, fail closed on every dependency failure (P5, P6, P7).
- A verdict computed by code (`aggregate.py`) from a table that mirrors SPEC 10.4 row by row, so tests can be table driven.
- M1 usable on the dummy repo with one judge profile and the repository's own gate commands; one command, `l4 verify <unit>`.
- Every SPEC requirement ID L4-VER-001 to L4-VER-015 traceable to a requirement block, a scenario and a task.

## Non-Goals

- Implementing the gates runner, worktrees, ledger, spec providers, agent factory or LLM backends (consumed interfaces below).
- Auto-merging, archive logic (change `forge-and-ci`), lessons (change `memory-lessons`).
- Per-language integrity rules beyond Python until the change-0 fixture reports exist (M2 blocker, see Risks).
- Changing SPEC; ambiguities resolved here are listed under D8 and are to be folded into SPEC by the maintainer.

## Module layout (`src/l4/verifier/`)

| Module | Contents | Milestone |
|---|---|---|
| `types.py` | `Severity`, `Finding`, `CriterionResult`, `UnitVerdict`, `StepStatus`, `StepRecord`, `VerifyContext`, `VerifyOutcome` | M1 |
| `selection.py` | `independence_constraint(implementer_vendors, mode) -> Callable[[Profile], str | None]` (passed to agent-factory's `Factory.for_role`), `select_verifier_profiles` (thin wrapper returning `Selected`), `NoIndependentProfile` | M1 |
| `preconditions.py` | `check_preconditions` (step 0), `open_verifier_worktree` | M1 |
| `gates.py` | `run_build_gates` (step 2), `run_test_gate` (step 3), `repeat_new_tests`, `run_extra_gates` (steps 6, 7); thin adapter over `l4.gates.runner` | M1 / M2 |
| `traceability.py` | `trace_criteria` (step 4 lite in M1, full in M2), `CriterionEvidence` | M1 / M2 |
| `judge.py` | `JudgeVerdict`, `parse_judge_output`, `build_judge_prompt`, `run_judge`, `JudgeRun`, `check_citations`, `run_panel` | M1 / M2 |
| `aggregate.py` | `aggregate_criterion`, `aggregate_unit`, `CriterionOutcome` | M1 / M2 |
| `report.py` | `render_verification_md`, `write_round_evidence`, `verdict_json` | M1 |
| `verdicts.py` | `write_verdict_questions` (M1), `consume_human_verdicts` (M2) | M1 / M2 |
| `fixunit.py` | `create_fix_unit` (OpenSpec in M1, Kiro in M2), `FixUnit` | M1 / M2 |
| `ladder.py` | `verify_unit` (driver), `STEPS` registry, phase/exit mapping, `run_verify` (the `l4 verify` handler `l4.verifier.ladder:run_verify`), `verify_hook` (the orchestrator's lazily resolved `verify` hook) | M1 |
| `integrity.py`, `scan.py` | step 1 checks; content and AST scans | M2 |
| `guard.py` | verifier-agent write guard (L4-VER-002a) | M2 |
| `baseline.py`, `audit.py`, `generate.py` | synthetic baseline, step 4a, step 5 | M2 |
| `s1.py` | step 8, calibration JSONL | M2 |
| `evidence.py` | `verify.step` records, resume, once-per-round commit | M2 (record write is M1 inside `ladder.py`) |
| `playwright.py` | UI-facing detection, serve lifecycle, trace links | M2 |

The layout in `docs/plan/implementation-map.md` lists seven files; the others are new modules inside the same owned directory.

## Key data structures

`l4/judge-verdict@1` (SPEC 10.3, reproduced and implemented as pydantic models `JudgeVerdict`, `CriterionVerdict`, `EvidenceRef`, `TestAdequacy`, `JudgeFinding`):

```json
{
  "$id": "l4/judge-verdict@1",
  "type": "object",
  "required": ["criteria", "test_adequacy", "findings", "riskiest_assumptions"],
  "properties": {
    "criteria": {"type": "array", "items": {"type": "object",
      "required": ["id", "verdict", "evidence"],
      "properties": {
        "id": {"type": "string", "pattern": "^C-[0-9a-f]{8}$"},
        "verdict": {"enum": ["pass", "fail", "insufficient_evidence", "not_verifiable"]},
        "confidence": {"enum": ["high", "medium", "low"]},
        "evidence": {"type": "array", "items": {"type": "object", "required": ["kind", "ref"],
          "properties": {"kind": {"enum": ["file", "test", "log", "trace"]},
                         "ref": {"type": "string"}, "quote": {"type": "string", "maxLength": 300}}}},
        "reasoning": {"type": "string", "maxLength": 1200}}}},
    "test_adequacy": {"type": "array", "items": {"type": "object",
      "required": ["test", "criterion", "adequate"],
      "properties": {"test": {"type": "string"}, "criterion": {"type": "string"},
                     "adequate": {"type": "boolean"}, "reason": {"type": "string", "maxLength": 600},
                     "generated_test_misreads_criterion": {"type": "boolean"}}}},
    "findings": {"type": "array", "items": {"type": "object",
      "required": ["severity", "title", "detail", "evidence"],
      "properties": {
        "severity": {"enum": ["blocker", "major", "minor"]},
        "criterion": {"type": ["string", "null"]},
        "title": {"type": "string"}, "detail": {"type": "string"},
        "evidence": {"type": "array"}, "suggested_fix": {"type": "string"},
        "spec_gap": {"type": "boolean"}}}},
    "riskiest_assumptions": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string"}}
  }
}
```

Internal types (all frozen dataclasses unless noted):
- `Finding{id, severity, title, detail, criterion|None, source: "deterministic"|"judge", evidence: list, spec_gap: bool, suggested_fix|None}`.
- `CriterionEvidence{criterion_id, alias, tests: list[TracingTest], discriminating: bool|"unverified", covered: bool}`; `TracingTest{id, status, traces: list[str], adequate: bool|None}`.
- `CriterionResult` = `pass | pass_judgment | fail | disputed | needs_human | uncovered`; `UnitVerdict` = `PASS | FAIL | NEEDS_HUMAN`.
- Ledger events written: `verify.step{round, step, subject_sha, evidence_hash, status}` (status `ok|failed|not_run|unavailable|error`), `verify.verdict{round, verdict, findings}`, `human.verdict{criterion, decision, by, reason}` (M2), `fix.spawned{parent, fix_unit, round}`. Events read: `task.red_ok`, `task.tdd_exempt`, `guard.violation`, `guard.test_tamper`, `phase.changed`.
- `verdict.json` (`schema: l4/verdict@1` [I], this change names it): `{round, verdict, base_sha, head_sha, steps: [...], criteria: [{id, alias, result, tests, judge, s1_p, human}], findings: [...], profiles: {...}, cost_usd}`.

Consumed interfaces (owned by other changes; names reconciled by the cross-change review, 2026-10-03, against the owners' designs):
- implementer-tdd-loop: `l4.gates.runner.run_gate(spec: GateSpec, worktree, sandbox, run_id, env) -> GateResult(name, status, reason, exit_code, log_path, report)`, `judge_test_gate(exit_code, report, must_contain)`, and `l4.gates.junit.parse_junit(path) -> TestReport(tests: dict[str, TestCase], collection_errors, total)`.
- state-vcs-locks: `l4.vcs.git.Git` (the only git spawner; the fresh worktree is `Git.run("worktree", "add", "--detach", path, head_sha)`), `l4.vcs.names.UnitNames`, `l4.vcs.trailers.CommitTrailers`, `l4.state.ledger.LedgerWriter.append(type, **data)` and `read_ledger(unit_dir)`, `l4.state.lifecycle.Trigger` (`verify_pass`, `verify_fail_fix`, `verify_needs_human`, `verify_fail_exhausted`, `required_role_unavailable`).
- agent-factory: `Factory.for_role(role, unit, constraints) -> Selected` (this change supplies the independence constraint callable), `WaitingCapacity`, `LLMBackend.complete_structured(...) -> StructuredResult{status, parsed, model_resolved, usage}` (`status` in `ok|refusal|truncated|schema_invalid|error`), `LimitSignal`, `validate_against_schema`.
- spec-providers: `SpecProvider.validate`, `done_gate`, `criteria(unit)`, `create_fix_unit(parent, round, findings, spec_delta)` (M1 task 1.32 there), `l4.specs.base.Finding` and `SpecDelta` (extended here), `l4.specs.criteria.trace_ids`, `l4.specs.questions.QuestionsFile.raise_questions(batch, max_open)`.
- bootstrap-core: `l4.redact.Redactor`, `l4.exitcodes.ExitCode`, `l4.config.schema.L4Config`, `l4.config.defaults.cache_root`.

## Decisions

### D1. M1 includes a minimal step 4 (traceability lite); verdict PASS is reachable without S1
SPEC 10.4 with the default `sdd.require_traceability: true` makes every uncovered criterion `needs_human`, and the judgment-only pass needs S1. If M1 skipped step 4, every M1 run would end NEEDS_HUMAN, and the walking-skeleton criterion (human merges the MR, which needs the hand-off at PASS, L4-ARC-008) could never be met.
Chosen: M1 runs `trace_criteria`: criterion-ID tracing (L4-CRT-002) against the step 3 report, `max_criteria_per_test`, and discrimination for implementer tests taken from the ledger's `task.red_ok` events (the red phase already proved them discriminating, L4-VER-009 "implementer tests"). The synthetic-baseline re-check, zero-value-stub re-check, audit sampling and generation stay M2; the report marks M1 evidence `discriminating: red-phase proof`.
Alternatives: (b) end M1 at NEEDS_HUMAN and pull human verdicts into M1: rejected, it makes every dummy-repo run need a human and still needs the verdict consumer; (c) set `require_traceability: false` for M1: rejected, it allows judgment-only passes, which weakens the property the verifier exists to provide.

### D2. One judge in M1, panel in M2
`verifier.panel.size` defaults to 1 and M1 runs `run_panel` with that single independent judge. Agreement logic, `pass_k` and tie-breaker (L4-VER-004) are M2. With one judge, "judge fail with a passing test" gives `disputed` and then `needs_human` because no tie-breaker exists (SPEC 10.4 row 2).

### D3. Fresh worktree (SPEC) not "the unit worktree"
The orchestration brief says gates run in "the unit worktree"; SPEC L4-VER-001 requires a fresh worktree at the unit branch head, and SPEC wins. `open_verifier_worktree` runs `Git.run("worktree", "add", "--detach", path, head_sha)` through state-vcs-locks' hardened runner (no `create_worktree` API exists there) at the verifier-specific path `UnitNames(...).worktree` + `--verify-r<round>` under `cache_root`, and removes it with `git worktree remove --force` in a `finally`.

### D4. Independence uses the served model
`select_verifier_profiles` takes `served_vendor(profile)` from the last probe or call result (`StructuredResult.model_resolved` mapped through the profile's declared `vendor`; a mismatch with the requested model discards that judge). Alternative of trusting the configured `vendor` only was rejected: OpenRouter can serve a different model than requested (SPEC SCN-AVL-15).

### D5. Aggregation is a pure table-driven function
`aggregate_criterion(evidence, judge, human, cfg)` takes only data and returns `CriterionOutcome`; no I/O. Tests are parametrized directly from the SPEC 10.4 rows. Alternative of aggregating inside the ladder was rejected because it hides rows from unit tests.

### D6. Step recording and resume use ledger events, not a separate state file
`verify.step` events carry `subject_sha`; resume (M2) folds them. Alternative of a private `state` JSON under `.l4/evidence/` was rejected: SPEC 12.1 makes the ledger the only source of truth.

### D7. Fix units are created by `fixunit.py` through the spec provider
`create_fix_unit` maps the round's findings to spec-providers' `Finding` list (one entry per finding group, citing finding and criterion IDs) and, for `spec_gap` findings, an ADDED-only `SpecDelta`, then calls `provider.create_fix_unit(parent, round, findings, spec_delta)` (spec-providers runs `openspec new change <parent>-fix-<n>` [V], writes `proposal.md`, `tasks.md`, the delta or `skip_specs: true`, and validates `--strict`). This change writes no change files itself. Alternative of an LLM spec writer was rejected for M1: `roles.spec_writer` defaults to the deterministic `template` profile, and tasks derived from findings are mechanical.

### D8. SPEC ambiguities resolved (to be folded into SPEC)
- "No outstanding `guard.violation`" (step 1): outstanding means the offending change is still present in the head tree.
- "No bulk snapshot updates": any modified pre-existing snapshot file that no task calls for is a major finding (SPEC gives no size threshold).
- Severity of step 1 hits that SPEC calls "blocker" or "major" is kept as stated; the secret-scan finding, gate-config change, content-scan hit and out-of-scope edit with `scope_check: fail` are blocker/major deterministic findings, `warn` is minor.
- A failing `gates.extra` entry: `required: true` is a deterministic major finding, otherwise minor (SPEC does not say).
- Audit sample size is `ceil(ratio x covered new criteria)` with a minimum of 1 (SCN-VER-31: 6 x 0.3 = 1.8 gives 2).
- Serve process not ready within `gates.e2e.serve.timeout` is an internal error (L4-VER-010), not a criterion failure; Playwright disabled for a UI criterion falls back to the project framework or `not_testable` (then `needs_human`).
- An invalid fix unit is never committed; the parent stays `verifying` (exit 1).
- SCN-VER-24 mentions doctor ENV-006; that check is owned by `bootstrap-core`, only the step status is asserted here.

## External commands (exact flags per SPEC)

- OpenSpec (harness-owned prefix, `TZ=UTC DO_NOT_TRACK=1 OPENSPEC_NO_UPDATE_CHECK=1`) [V]: `openspec new change <parent>-fix-<n>`, `openspec validate <id> --strict --json`, `openspec instructions apply --change <id> --json`.
- Gates: the configured `gates.setup|build|lint|typecheck|test|e2e|extra` commands, with timeout `gates.timeout`, logs in `.l4-out/gates/<run-id>/<gate>.log`.
- Secret scan: `gitleaks` with the harness-owned config and ignore file (M2) [U: exact invocation flags, to be fixed with the fixtures].
- Playwright: `--reporter=junit,json`, headless, traces (M2) [U: Playwright inside the gate sandbox, SCN-SPK-01].
- Semgrep example for steps 6, 7: `semgrep --baseline-commit <base>` (configured by the user, not hard-coded).
- Git: `git worktree add`, `git diff --name-status <base>...<head>`, `git show <sha>:<path>` for red-vs-green comparison.

## [U] facts a test or spike must confirm first

1. M1: that the judge backend reports `model_resolved` so the served-vendor check works (contract test `tests/contract/test_verifier_contract.py::test_served_model_reported`).
2. M1: the ledger `task.red_ok` event shape from `implementer-tdd-loop` (D1 depends on it); until it lands, tests use a fake event of the SPEC 12.1 type name.
3. M1: that `openspec new change` plus `skip_specs: true` validates `--strict` on 1.14.0 [V by SPEC]; a contract test pins it.
4. M2 blocker: per-language zero-value stubs, support-file AST rules and suppression scanning come from change-0 fixture reports in `docs/spikes/` (the directory does not exist yet); task 2.1 gates tasks 2.6, 2.7, 2.8 and 2.10.
5. M2: Playwright/Chromium inside bubblewrap (SCN-SPK-01) before task 6.3 is relied on.
6. M2: the Kiro `.config.kiro` `workflowType` value for bugfix specs is [I] (SPEC L4-KSP-005); confirm against a Kiro-created bugfix spec before task 5.11.

## Risks / Trade-offs

- **Weak evidence in M1.** Without the synthetic baseline re-check, a test that passes for the wrong reason could count if the red-phase proof was gamed. Mitigation: the implementer loop owns red validity (two runs, zero-value stubs); the report flags M1 evidence; step 1 integrity and the full step 4 arrive in M2; the judge's adequacy review is already in M1.
- **Judge-model drift or provider cost.** One judge call per criterion batch. Mitigation: `max_state_tokens` style trimming of the prompt, cost recorded in `verification.md`.
- **Interface drift.** Signatures of consumed interfaces are assumed; mitigation: all calls go through thin adapters in `gates.py`, `selection.py` and `fixunit.py`, so a rename touches one place.
- **False NEEDS_HUMAN storms.** Fail-closed rules may ask many questions. Mitigation: one question per criterion, human `accept` is durable (M2).
- **Large step 1.** Many checks in one step; mitigation: each sub-check is its own function returning findings, and the ladder treats step 1 as pass/fail by the worst severity.
