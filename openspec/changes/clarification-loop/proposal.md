## Why

An implementer that hits an ambiguity must not guess, and a human must not be paged for things the spec and code already
answer. SPEC 9 defines a clarification loop: the implementer raises questions in `questions.md`, a clarifier answers what
it can with evidence, a narrow routing rule decides what may be accepted automatically, and everything else goes to a human
whose committed answer resumes the unit on the next run. Without this change a blocked task is a dead end: `l4 run` would
either loop on the same blocker or fail. The walking-skeleton exit criterion 5 (a deliberately ambiguous change produces
`questions.md`; the clarifier answers what it can; a human answer committed to the branch resumes the unit) depends on it.

## What Changes

- Add `src/l4/clarifier/`: the `Clarifier` (context assembly, answer schema `l4/clarifier-answer@1`, one repair, agentic
  read-only or tool-less LLM execution), the `Router` (kind agreement, confidence, S1 product-decision check, citation
  resolution and support), answer injection as `<l4:data kind="answer" ...>` blocks with redaction, and the
  `awaiting_human` notification (label plus sticky comment).
- Define the narrow ports this change needs from its neighbours (questions file I/O, ledger, factory) so it can be
  tested with fakes, and implement the `QuestionsPort` adapter over `l4.specs.questions` and the orchestrator `clarify_hook` in M1.
  Forge writes (labels, sticky note) go through forge-and-ci's `PrMirror`; the clarifier only supplies the sticky section.
- M1 (walking skeleton): the clarifier answers `questions.md` with an LLM backend (`openai-chat`) or an agent profile
  (`claude-code`, `opencode`); the S1 checks are served, only when `clarifier.s1_standin: llm_boolean` is set (default `none`), by a boolean LLM judge on the `s1_judge` chain
  (degenerate probabilities 0.0/1.0) because Laya/Jev arrive in M2; unanswered questions put the unit in `awaiting_human` (exit 11); human
  answers committed to the unit branch are read on the next run and injected into the implementer prompt.
- M2: System-One (Laya local / Jev hosted) as the S1 judge with its tokenizer-based state budget, all agentic read-only
  policies, human override before use, injection and redaction hardening.

Terminology: the user-facing name "waiting_human" is the SPEC lifecycle phase `awaiting_human` (SPEC 12.0); this change
uses the SPEC name everywhere.

## Capabilities

### New Capabilities
- `clarifier`: clarifier inputs and output contract, auto-accept routing, S1 questions, human escalation, unavailable
  and invalid handling, answer injection.

### Modified Capabilities

None.

## Impact

- Owned source paths: `src/l4/clarifier/{clarifier,router}.py` plus `src/l4/clarifier/{inject,notify}.py` (inside the owned directory).
- Owned tests: `tests/unit/clarifier/`, `tests/scenarios/clarifier_*.yaml`, `tests/live/test_live_clarifier.py` (marker `live`, `L4_LIVE=1`).
- Consumes: `LLMBackend`/`AgentAdapter`/`Factory.for_role` (agent-factory), `l4.specs.questions` (spec-providers),
  `PrMirror.sync(..., notes=...)` via the orchestrator (forge-and-ci), `LedgerWriter.append` (state-vcs-locks), `l4.redact.Redactor` (bootstrap-core),
  lessons text (memory-lessons, optional).
- Consumed by: implementer-tdd-loop (blocked tasks call `Clarifier.run`; prompts call `render_answer_blocks`), orchestrator
  (phase from `ClarifyOutcome`), verifier (verdict questions are explicitly excluded).
