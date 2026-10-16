## Why

An implementer attempt fails today when the agent's result object breaks `l4/implementer-result@1`, also when the
work itself is good. The evidence (2026-10-16, design section 1.6) is 159 harness test steps with full transcripts
and 42 steps of a cheap model on a public consumer repository:

1. **16 attempts failed on the result object alone.** codex (native schema) failed 0 of 72 and kiro-cli 0 of 70.
   The failures came from opencode profiles: `summary` missing (9), `status` missing (3), `status` equal to the phase
   name (2, and 1 more hidden behind a wrong path), a text over its length limit (3), `files_changed` as objects (1),
   and the file at a wrong path (3). Three were caused by a prompt bug (fixed in `0fa4ad1`) and three by the path
   (fixed by the `.l4-result` alias). Ten still fail with the code of today.
2. **The prompt causes it.** The `# Output` section of a prompt-contract step lists `phase, task_ids, criteria_ids,
   tests_added, suppressions, files_changed` and puts `status` and `summary` in a separate sentence after the path
   (`src/l4/implementer/prompt.py:274-287`). Every object without `summary` follows that list, and the key order of
   the failing objects mirrors it. The section also gives two places for the result ("Your final message is the
   result JSON object" and "Write your result object to ..."). Context size is not the cause: the peak per-call context
   of the failing steps (11k to 29k tokens) is in the range of the accepted ones.
3. **The harness does not need most of these fields.** It reads `summary` only for a `blocked` result without a
   question (`src/l4/implementer/tdd.py:1017, 1078, 1513`, `src/l4/implementer/loop.py:62-71`). It never reads
   `phase`, `task_ids` or `files_changed` after validation. It reads `tests_added` once, where it changes only which
   failure text a failing red step gets (`tdd.py:323`). Only `status: blocked` changes the flow. Each failed attempt
   costs a full agent step, and with three attempts a unit halts.
4. **Each failure could be repaired with no model call.** Every failing agent wrote a parseable JSON object, nine of
   ten final messages hold a usable summary, and none held a question.

## What Changes

- **A new `# Output` section for the prompt-contract adapters** (opencode, kiro-cli, command). Its first sentence asks
  for `status` and `summary` together: `done`, or `blocked` with at least one question. It names the optional fields
  that only the agent knows (`criteria_ids`, `suppressions`, `notes_for_verifier`) and no field that the harness
  derives. It gives one place for the result, and the path is the last line. The schema it shows is the agent's subset
  of `l4/implementer-result@1`. The text is the new versioned template `output.md` (template lock). The native
  adapters (codex, claude-code) keep their prompt, their schema and their CLI enforcement as today.
- **Normalization before validation.** After each agent step, before any guard or gate, the harness takes the result
  object (the result file, else the last result-like JSON object in the agent's own text) and repairs it with fixed
  rules: `phase` and `task_ids` from the step, `files_changed` from git, `tests_added` from the JUnit diff, a missing
  `summary` from the agent's final message, a missing or unknown `status` to `done` (`blocked` only with a question),
  an over-long text cut with a visible marker, the observed alias keys, and malformed optional items dropped. Each step
  that changed something records one `result.normalized{task, phase, attempt, source, fixes}`.
- **An attempt fails for its result only** when no result object is found, or when the result is `blocked` with no
  well-formed question. A `blocked` result without a question no longer becomes a question made from its summary.
- **Safety.** The gates still judge the work: red must fail by assertion, the criteria must be traced, green must
  pass, the static gates and the verifier run as before. Normalization never invents or adds a question, never changes
  a `blocked` status, never adds a suppression or a criterion, and never reads or changes the worktree.
- **Run facts and telemetry.** `RunResult` gains `last_message` (the agent's text after its last tool call) and
  `result_problem` (a native adapter's result that is missing or invalid). `agent.finished` records the peak per-call
  context where the adapter exposes it: `context_peak_tokens` (opencode, claude-code) or `context_peak_percent`
  (kiro-cli).
- **Optional second wave: a repair call.** When no result object is found, a fresh tool-less call on the same profile
  may rebuild one from the agent's final message (`implementer.result_repair_attempts`, default `0` in that wave). It
  may restructure, never add a question, and never return `blocked`. It is specified and deferred (design D9).
- **Not built: a `check_result.py` self-check** for the agent (design D10).
- **Docs.** `docs/SPEC.md` rows, the runbook (4.2, 4.5, 7.2, 11), and the CHANGELOG section 0.4.4. The skill does not
  change (design D13).

Not in this change:
- the native adapters' `# Output` wording and their schema (codex 0 failures of 72);
- the "state your blocking questions" call of L4-IMP-008 for a stuck task (not built; this change only takes the
  `blocked` result without a question out of it);
- eval scoring of `result.normalized` (a normalized step is not a schema error; the eval reads it as before);
- run transcripts for a consumer whose artifacts are off.

## Capabilities

### New Capabilities

- `implementer-result-contract`: the `# Output` section of a prompt-contract step (L4-IMP-019), the normalization of
  the result object and its record (L4-IMP-020), the cases where an attempt fails for its result (L4-IMP-021), and the
  optional repair call (L4-IMP-022).
- `agent-run-facts`: what an adapter reports about a finished run's result and final message (L4-FAC-010), and the
  peak per-call context in `agent.finished` (L4-FAC-011).

### Modified Capabilities

None as an OpenSpec delta: `openspec/specs/` holds no baseline (only `.gitkeep`). Section 6 of `tasks.md` holds the
`docs/SPEC.md` work:
- the new requirements L4-IMP-019..022 and L4-FAC-010..011, with SCN-IMP-186..199 and SCN-FAC-16..19;
- the amendments of L4-IMP-004, L4-IMP-005, L4-IMP-008, L4-FAC-001 (`RunResult`, `Usage`), the §8.3 adapter rows,
  L4-STA-001 (event list), §3.2 (`result_repair_attempts`), SCN-IMP-08, SCN-QMD-10, §21 (row 25), and, after the
  change `escalate-and-note` is merged, L4-IMP-017 and SCN-IMP-176 (design D12).

## Impact

- **Code:**
  - a new `src/l4/implementer/normalize.py` (the pure normalization), `src/l4/implementer/result.py`
    (`FILE_RESULT_SCHEMA`), `src/l4/implementer/tdd.py` (`agent_step`: the request schema, finding, normalizing and
    validating the object, `result.normalized`, the `blocked` rule, `agent.finished` fields; `run_red` stops passing
    the agent's `tests_added`);
  - `src/l4/implementer/prompt.py` and a new `src/l4/implementer/templates/output.md`, `src/l4/templatelock.py` and
    `src/l4/templates.lock.json`;
  - `src/l4/agents/base.py` (`RunResult.last_message`, `RunResult.result_problem`, `Usage.context_peak_tokens`,
    `Usage.context_peak_percent`), `src/l4/agents/contract.py`, `opencode.py`, `kiro_cli.py`, `codex.py`,
    `claude_code.py`;
  - `src/l4/progress.py` (the `result.normalized` line and the peak in the `agent.finished` line).
  - Second wave only: `src/l4/implementer/repair.py`, a template `repair.md`, `src/l4/config/schema.py` (the default of
    `implementer.result_repair_attempts`).
- **Docs:** `docs/SPEC.md`, `docs/runbook.md`, `CHANGELOG.md`.
- **Prompts:** a prompt-contract prompt changes its `# Output` section and its `template_version` gains `+output@1`. A
  native prompt does not change.
- **Config:** none in the first wave. The key `implementer.result_repair_attempts` exists (default `1`) and no code
  reads it; the second wave reads it and changes its default to `0`.
- **Ledger:** a new event `result.normalized`; `agent.finished` gains `context_peak_tokens` or
  `context_peak_percent`; second wave: `result.repair`. An older ledger folds and reads as before.
- **Behaviour:** fewer failed attempts, so fewer halts and fewer escalations (`escalate-and-note`). A `blocked` result
  without a question is now a failed attempt, not a question to a person.
