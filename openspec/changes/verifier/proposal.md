## Why

The harness must not mark its own work as done. SPEC section 10 (L4-VER-001 to L4-VER-015) defines an independent, deterministic-first verifier: it re-runs the gates in a fresh worktree, traces acceptance criteria to tests, asks LLM judges of a different vendor for a structured verdict, aggregates the result by code, and turns every failure into a new spec change. Nothing in the repository implements this yet, and the walking-skeleton exit criterion (a verified unit, a merge request the human can trust, a fix change when verification fails) cannot be met without at least a thin version of it.

## What Changes

- Add the `l4.verifier` package (`src/l4/verifier/`) behind `l4 verify`.
- **M1 (walking skeleton):** deterministic gates in a fresh verifier worktree (steps 0, 2, 3), minimal traceability by `@C-<id>` tags with implementer discrimination taken from the red-phase ledger events (step 4 lite), exactly one LLM judge whose vendor differs from every implementer vendor producing the `l4/judge-verdict@1` JSON (step 9), citation re-checks, deterministic aggregation (step 10), `verification.md` and `verdict.json`, verdict questions on NEEDS_HUMAN, failure precedence (waiting_capacity, internal error, fail closed), and on FAIL a new OpenSpec fix change created with `openspec new change` whose tasks are derived from the findings.
- **M2 (full scope):** integrity step 1 (freeze, content scan, support-file rules, suppressions, secrets, TDD history), verifier-agent write guard, flaky repeats, full discriminating-evidence traceability against the synthetic baseline, audit sampling (4a), test generation (5), opt-in gates (6, 7), S1 judge and calibration (8), judge panel with pass^k and tie-breaker, resumable ladder, failing generated tests, human verdict consumption, UI criteria with Playwright, Kiro fix units.

## Capabilities

### New Capabilities
- `verifier`: the independent verification ladder, judge schema, deterministic aggregation, report outputs and fix-unit creation (L4-VER-001 to L4-VER-015, scenarios SCN-VER-01 to SCN-VER-44 plus added negatives).

### Modified Capabilities
None. This change consumes interfaces owned by `spec-providers`, `state-vcs-locks`, `agent-factory`, `implementer-tdd-loop` and `bootstrap-core` and does not alter their requirements.

## Impact

- Owned source paths: `src/l4/verifier/{ladder.py,gates.py,judge.py,aggregate.py,report.py,fixunit.py,playwright.py}` from the layout, plus new modules inside the same owned directory: `types.py`, `selection.py`, `preconditions.py`, `traceability.py`, `verdicts.py` (M1) and `integrity.py`, `scan.py`, `guard.py`, `baseline.py`, `audit.py`, `generate.py`, `s1.py`, `evidence.py` (M2).
- Owned tests: `tests/unit/verifier/`, `tests/scenarios/verify-*.yaml`, `tests/scenarios/spec-gap-adds-scenario.yaml`, `tests/scenarios/s1-disagreement-needs-human.yaml`, `tests/scenarios/judge-error-fails-closed.yaml`, `tests/contract/test_verifier_*.py`, entries for SCN-VER-* in `tests/scenario_matrix.yaml`.
- Depends on (names reconciled by the cross-change review, see design "Consumed interfaces"): `l4.gates.{runner,junit}`, `l4.vcs.{git,names,trailers}`, `l4.agents.factory`, `l4.llm.base`, `l4.specs.{base,openspec,kiro,criteria,questions}`, `l4.state.{ledger,lifecycle}`, `l4.config.schema`.
- Does not touch `docs/SPEC.md` or other changes; `src/l4/cli.py` is owned by `bootstrap-core` and dispatches `verify` to the handler `l4.verifier.ladder:run_verify` named in its `commands.HANDLERS`; the orchestrator reaches the verifier through `l4.verifier.ladder:verify_hook`.
