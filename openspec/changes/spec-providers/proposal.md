## Why

The harness drives work from spec units, not from prompts. Before any task can be selected, implemented, verified or archived, the harness must decide deterministically which spec frameworks a repository uses, read each unit's tasks and acceptance criteria, change task markers without corrupting a human-owned file, and exchange questions with humans through a strict file format. Everything downstream (state, implementer, clarifier, verifier, archive) consumes the interfaces defined here (SPEC §4-§6, principles P3 and P4). Getting the byte-safe marker writer and the OpenSpec CLI isolation wrong is expensive: a planted `node_modules/@fission-ai/openspec` executes under `npx`, and `openspec archive --yes` archives incomplete work.

## What Changes

- Add framework detection (filesystem only), unit naming, and the `SpecProvider` protocol with a provider registry and conformance checks (L4-DET-001..003, L4-SPI-001).
- Add the OpenSpec provider: hermetic CLI wrapper from a harness-owned npm prefix, root verification, strict done/validate gates before archive, OpenSpec's own task grammar, fix units, and archive-time INFO escalation (L4-OSP-001..006).
- Add the Kiro provider (native, no CLI): Kiro task grammar, waves, EARS criteria and `_Requirements:_` links, harness validate/archive, bugfix-spec fix units (L4-KSP-001..005).
- Add the byte-safe task marker writer (port of the maintainer's `kiro_tasks.py` semantics, with atomic temp-file-and-rename writes) and the post-step `tasks.md` guard comparison (L4-TMW-001..002).
- Add stable criterion IDs, `<unit>/.l4/criteria.json`, tracing conventions and orphan-ID detection (L4-CRT-001..003).
- Add `questions.md` parse and write with the §6.2 grammar, tolerant status handling, section-scoped edits, restore-from-ledger hooks, ID rules, answered/blocked semantics and answer-hash tracking (L4-QMD-001..006).
- Add the doctor checks `SPEC-001` to `SPEC-006` (module `src/l4/doctor/checks_spec.py`) on top of bootstrap-core's registry.
- Walking skeleton (M1): detection, OpenSpec provider (list, validate, tasks, archive, fix units), marker writer, criteria IDs, `questions.md` parse/write including the Status and *Clarifier suggestion* edits the clarifier and verifier need. M2: Kiro provider, conformance suite across both providers, `l4 questions`, full doctor coverage.

## Capabilities

### New Capabilities
- `spec-detection`: deterministic framework detection, unit identity, `SpecProvider` protocol and registry.
- `openspec-provider`: OpenSpec CLI adapter (harness-owned prefix, root check, gates, grammar, fix units).
- `kiro-provider`: native Kiro adapter (grammar, waves, criteria, validate/archive, bugfix fix units).
- `task-markers`: byte-safe single writer of task markers and the `tasks.md` post-step guard comparison.
- `acceptance-criteria`: stable criterion IDs, `criteria.json`, tracing rules, orphan check.
- `questions-file`: `questions.md` grammar, parser, writer, answer semantics.

### Modified Capabilities

None. This change creates capabilities in `openspec/specs/`; it modifies none.

## Impact

Owned source paths (from docs/plan/implementation-map.md):

- `src/l4/specs/base.py`, `src/l4/specs/detect.py`, `src/l4/specs/openspec.py`, `src/l4/specs/kiro.py`, `src/l4/specs/markers.py`, `src/l4/specs/criteria.py`, `src/l4/specs/questions.py`
- `src/l4/doctor/checks_spec.py` (adds `SPEC-001`..`SPEC-006` to bootstrap-core's doctor framework)
- Tests: `tests/unit/specs/`, `tests/unit/doctor/test_checks_spec.py`, `tests/contract/` (provider conformance, OpenSpec CLI contract), `tests/fixtures/specs/`

Depends on bootstrap-core (config schema keys `spec.*`, `sdd.*`, `clarifier.max_open_questions`; exit codes; redaction filter L4-OBS-002; doctor registry). Consumed by state-vcs-locks, simulation-harness, implementer-tdd-loop, clarification-loop, verifier and forge-and-ci. Boundaries: the post-step guard hook is wired by implementer-tdd-loop (this change ships the comparison function); the ledger events `question.raised`/`question.restored` are written by state-vcs-locks (this change defines the payload and consumes a ledger reader port).
