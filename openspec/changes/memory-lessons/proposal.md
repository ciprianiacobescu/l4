## Why

Agents repeat mistakes that a verifier or a human has already paid for. SPEC section 13 makes the harness the owner
of a small, reviewed lessons file and of how its content reaches an agent, because Serena only exposes memory
*names* and an agent cannot be relied on to read the right lesson itself [V, research/05]. The walking skeleton
needs the thin end of this: read the committed `lessons.md` and put the relevant lessons into every prompt as
`<l4:data>` so that information, never instructions, reaches the agent. Curation, per-adapter channels and Serena are
deepened afterwards.

## What Changes

- Add the `lessons.md` model: parser, canonical writer, lint, stable IDs derived from the dedupe key.
- Add scope selection (path globs plus unscoped lessons) and injection as `<l4:data kind="lessons">`, with the
  injected IDs recorded in the ledger (`lessons.injected`).
- Add the protected-path constant for `.serena/memories/harness/**` that the implementer's post-step guard consumes.
- Add `l4 lessons list|lint` (M1) and `l4 lessons promote ID` (M2).
- M2: per-adapter delivery channels (Claude `--append-system-prompt`, Kiro agent `resources`, prompt section),
  automatic curation (promotion sources, reinforcement, caps, `_archive/`), agent proposal quarantine in
  `.serena/memories/inbox/<run-id>/`, separate memory commits (`chore(memory): ...`, `L4-Phase: lessons`), and
  optional Serena wiring that never blocks a run.

## Capabilities

### New Capabilities

- `memory`: lessons file format and lint, selection and `<l4:data>` injection, curation and quarantine, memory
  commits, and optional Serena wiring.

### Modified Capabilities

None.

## Impact

Owned source paths:

- `src/l4/memory/lessons.py` (model, parser, writer, lint, selection)
- `src/l4/memory/serena.py` (Serena command, environment, project file, fail-soft start check)
- additional modules in the same package: `src/l4/memory/inject.py`, `src/l4/memory/channels.py`,
  `src/l4/memory/curate.py`, `src/l4/memory/inbox.py`, `src/l4/memory/commit.py`, `src/l4/memory/cli.py`
- `src/l4/doctor/checks_memory.py` (doctor MEM-001)
- tests: `tests/unit/memory/`, `tests/integration/test_memory_flow.py`

Depends on `state-vcs-locks` (ledger writer and `lessons.*` event types, hardened `Git.commit` and trailers) and
`bootstrap-core` (config `memory.*` keys, redaction, doctor registry, CLI delegation). Consumed by
`implementer-tdd-loop` (prompt assembly calls `inject_for_task`, guard reads `PROTECTED_MEMORY_PATHS`),
`clarification-loop`, `verifier` (findings feed curation), `forge-and-ci` (`l4 init` writes `EMPTY_TEMPLATE` and the
`.gitattributes` entry) and `agent-factory` (adapters consume `DeliveryPlan`).
