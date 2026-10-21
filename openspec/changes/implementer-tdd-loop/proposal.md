## Why

The harness exists to turn a validated spec unit into committed, tested code with an agent in a deterministic loop (SPEC §7, §5, §12.0). The walking skeleton needs the smallest honest version of that loop running live on `example-group/dummy-agentic`: a red commit whose new tests fail, then a green commit that makes them pass without touching the red tests, driven by a deterministic orchestrator that records every phase change. Intake (ODD) and gate execution are part of the same loop: no agent runs for a unit outside the operational design domain, and a "passing" test gate must never be vacuous.

## What Changes

- Add the implementer package: task selection, prompt assembly from versioned templates, the `l4/implementer-result@1` contract with repair, post-step guards, strict red then green TDD with a hash freeze of red tests, commits with `L4-*` trailers, stuck detection and budgets.
- Add `src/l4/orchestrator.py`: the run loop that drives one unit through the §12.0 lifecycle states (consuming the transition table from state-vcs-locks) and maps outcomes to exit codes 0, 11, 12, 13, 14; and the `l4 run` composition root (`run_command`, `build_services`) that wires leases, worktrees, ledger, pushes, sandbox and the agent factory, and reaches the later changes (forge push arguments, lessons, clarifier, verifier, PR mirror, hand-off) through lazily resolved hooks so the walking skeleton runs end to end once they land.
- Add the ODD and gates capability: intake checks (`gates/odd.py`), gate runner with timeout, logs and non-vacuous judgement (`gates/runner.py`, `gates/junit.py`), later the test-bootstrap unit, adoption of finished work and gate proposal.
- M1 (walking skeleton): Python-first red phase = tests plus signature-only stubs, harness runs the configured test command and requires the new tests to fail individually; green phase = agent implements, harness restores red test files from the red commit (hash freeze), requires all tests passing, commits with `L4-TDD: green`; blocked result writes `questions.md`; max-attempt, no-progress and iteration breakers.
- M2: per-criterion vacuity checks with zero-value stubs, audit sampling, per-language stub allow-lists (after the change-0 fixture repos report), runner-config section freeze, test-tamper and gate-config guards, exemptions beyond human tags, session resume, WIP snapshots, soft deadline, `l4 resume` budget extensions, test bootstrap, adoption, gate proposal.

## Capabilities

### New Capabilities
- `implementer`: task selection, TDD phases, prompts, result contract, guards, commits and trailers, stuck detection, budgets, sessions, WIP snapshots, deadlines, and the orchestrator run loop (L4-IMP-001 to L4-IMP-012, §12.0 caller side). L4-IMP-013 (resume, ledger-counted budgets), step idempotency (L4-STA-003) and human-push races (L4-RACE-001) are specified by `state-vcs-locks`; this change consumes them.
- `operational-domain`: intake ODD checks, test-oracle bootstrap, adoption of finished work, gate execution and gate proposal (L4-ODD-001 to L4-ODD-003, L4-GAT-001 to L4-GAT-003).

### Modified Capabilities
(none)

## Impact

- Owned source: `src/l4/implementer/{prompt.py,tdd.py,guards.py,result.py,loop.py}` plus `src/l4/implementer/templates/*.md`; `src/l4/gates/{odd.py,runner.py}` plus new `junit.py`, `bootstrap.py`, `adopt.py`, `propose.py` (all inside the owned `gates/` package); `src/l4/orchestrator.py`. No doctor module: the oracle check CFG-004 is bootstrap-core's, and `gates/odd.py` reuses its predicate.
- Consumes: SpecProvider (spec-providers), ledger/state/lifecycle table, git/worktree/trailers (state-vcs-locks), `AgentAdapter` and `RunResult` (agent-factory), `questions.py` (spec-providers), `Sandbox.wrap` and `safe_parse_xml` (sandbox-security), config models and redaction (bootstrap-core).
- Tests: `tests/unit/implementer/`, `tests/unit/gates/`, `tests/unit/orchestrator/`, fixtures in `tests/fixtures/py_tdd/`, scenarios in `tests/scenarios/`.
- Depends on spikes (change 0) for: Python TDD fixture repo, JUnit shape of collection errors, per-language stub allow-lists (M2).
