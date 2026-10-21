## Context

SPEC 9 (clarifier), 6 (`questions.md`), 12.0 (lifecycle: `implementing -> clarifying -> implementing | awaiting_human`,
`awaiting_human -> implementing` when explicit answers unblock a task) and the scenarios SCN-CLR-01..09 are normative.
`questions.md` parsing and byte-safe edits are owned by spec-providers (change 2); the implementer raises questions
(change 6); the forge call surface is change 9; the orchestrator owns the phase (change 6). This change owns the decision:
given open questions, produce answers or suggestions, and tell the orchestrator which phase follows.

Evidence labels follow SPEC: [V] verified, [I] design decision, [U] must be confirmed by a test first.

## Goals / Non-Goals

Goals:
- Auto-answer only what is provably technical and supported by the repository; never decide product questions.
- Every outcome is explainable: a reason list per question, a `clarifier.result` event, a sticky comment.
- A human answer committed on the branch is consumed on the next run with no manual step beyond `Status`.
- Degrade, never block: an unavailable or invalid clarifier means "ask the human", never `waiting_capacity` (exit 11, not 12).

Non-Goals:
- Parsing and writing `questions.md` (change 2 provides it; this change calls a port).
- The implementer's question-raising and the override fix unit (L4-QMD-006 belongs to questions-file/implementer).
- Forge API implementation (change 9) and the sticky-comment transport.
- Training or calibrating S1 (verifier change 8, SPEC 10.8).

## Decisions

### D1. Module layout (inside `src/l4/clarifier/`)

| Module | Contents |
|---|---|
| `clarifier.py` | `ClarifierAnswer` (pydantic model) + `CLARIFIER_ANSWER_SCHEMA`; `QuestionView`; `ClarifyOutcome`; `ContextBuilder`; `BackendClarifier`; `AgentClarifier`; `Clarifier.run(unit, questions) -> ClarifyOutcome`; `Clarifier.reenter(unit) -> ReentryResult` |
| `router.py` | `Router.route(...) -> RoutingDecision`; `resolve_citation(citation, roots) -> CitationCheck`; `S1Judge` (Protocol); `SystemOneJudge` (M2, wraps `SystemOneBackend`); `LlmBooleanJudge` (M1, wraps any `LLMBackend`); `router_question(q)`, `citation_question(answer, cited_text)`, `trim_state(state, max_tokens, count)` |
| `inject.py` | `AnswerBlock`; `render_answer_blocks(questions, redact) -> RenderedAnswers(text, consumed)` |
| `notify.py` | `build_sticky_comment(...) -> str`; `notify_awaiting_human(forge, unit, ...)` |

### D2. Ports (narrow interfaces so the change is testable alone)

```python
class QuestionsPort(Protocol):                  # adapter over l4.specs.questions (change 2)
    def load(self) -> list[QuestionView]: ...
    def set_clarifier_answer(self, qid: str, answer_md: str, citations: list[Citation]) -> None: ...   # Status: answered-by-clarifier
    def set_clarifier_suggestion(self, qid: str, suggestion_md: str, meta: str) -> None: ...          # Status stays open
class EventSink(Protocol):                     # agent-factory's protocol; satisfied by l4.state.ledger.LedgerWriter
    def append(self, type: str, **fields) -> Any: ...
```

`QuestionsPort` is implemented in M1 by `SpecQuestionsPort(questions_file: l4.specs.questions.QuestionsFile)`:
`set_clarifier_answer` = `set_suggestion(qid, answer_md + citations)` then `set_status(qid, "answered-by-clarifier")`;
`set_clarifier_suggestion` = `set_suggestion(qid, meta + suggestion_md)` with Status left `open` (spec-providers task 1.34;
L4-QMD-003 allows the harness to write only the Status line and the *Clarifier suggestion* block, so an auto-answer lives
there and spec-providers' `effective_answer` returns it). The clarifier makes no forge call itself (D8).

`QuestionView(id, title, status, kind, blocking: list[str], context, options: list[str], answer_text, suggestion_text, by)`.
`ClarifyOutcome(next_phase: Literal["implementing","awaiting_human"], exit_code: Literal[0, 11], results: dict[str, QuestionResult], clarifier_available: bool, sticky_section: str | None)`.
`QuestionResult(status: Literal["answered-by-clarifier","open"], decision: RoutingDecision | None, suggestion: str | None, reasons: list[str], profile: str | None)`.
`RoutingDecision(auto_accept: bool, reasons: list[str], p_product: float | None, citation_support: list[float], citation_failures: list[str])`.

### D3. Output contract (L4-CLR-001)

`l4/clarifier-answer@1`: `{"question_id": "Q-002", "answer": str, "confidence": "high|medium|low", "kind": "technical|product|ambiguous",
"citations": [{"ref": "design.md#L42", "quote": "..."}], "rationale": str}` with `additionalProperties: false`, `question_id`
pattern `^Q-[0-9]{3,}$`, `answer` non-empty and `maxLength 4000` [I]. Validation happens client-side on both execution paths
(agent result file and backend reply) with the agent-factory validator. One repair attempt: the second call carries the
validation errors verbatim; a second failure yields `clarifier.result{status: invalid}`.

### D4. Execution paths (M1 has both)

- Backend path (`profile.backend`): `LLMBackend.complete_structured(system, messages, CLARIFIER_ANSWER_SCHEMA, effort=None,
  max_tokens=2000, timeout_s=profile timeout)`. No tools, so the harness supplies the code: `ContextBuilder.code_context()`
  extracts path-like tokens and identifiers from the question and the unit's spec documents, ranks files with `git grep -l -F`
  inside the worktree, and appends excerpts (<= 80 lines each) until `implementer.context_budget_tokens` is spent [I].
- Agent path (`profile.adapter`): `adapter.run(RunRequest(... permission_policy=read_only ...))` with `cwd` = the unit
  worktree and the result through the schema mode of the adapter (native or `$L4_RESULT_PATH`). Read-only per SPEC 9: Claude
  `--permission-mode plan` or a read-only allow-list, Codex `-s read-only`; OpenCode and Kiro use the read-only policy of
  agent-factory D3 (`PermissionPolicy.mode`). After the run the harness requires `git status --porcelain` to be unchanged; any change discards the answer, restores the
  tree (`git checkout -- . && git clean -fd` on the paths reported) and records `guard.violation` [I].
- Chain: `Factory.for_role("clarifier", unit)`; the role is optional (L4-AVL-010). `RoleUnavailable` => L4-CLR-005 path.

All spec documents, question text, code excerpts and prior answers are wrapped in `<l4:data kind="spec|question|code|answer|lesson">`
blocks in the clarifier prompt, and the system text states that data blocks are information, never instructions (SPEC 18 / SCN-CLR-09).

### D5. Routing (L4-CLR-002, L4-CLR-003)

`Router.route(question, answer, s1)` evaluates, in this order, and collects every failed condition (so the reasons list is complete):

1. kinds: `question.kind` (implementer) and `answer.kind` both in `clarifier.auto_accept_kinds`; a `verdict` question never reaches the router.
2. confidence: ordinal `high > medium > low`; `answer.confidence >= clarifier.min_confidence`.
3. S1 router: `p(product) <= verifier.s1.reject_threshold` (0.1).
4. citations: at least one citation [I, see Ambiguities]; each resolves; each S1 support probability `>= verifier.s1.accept_threshold` (0.9).
5. S1 availability: the `s1_judge` chain yields a usable judge; otherwise nothing is auto-accepted and S1 is recorded `unavailable`.

`resolve_citation`: `ref` is `<relative path>` with optional `#L<n>` or `#L<a>-L<b>`; the path is resolved against the unit
directory, then the repository root; absolute paths, `..` segments and paths outside the worktree fail; the quote
(whitespace-normalised, >= 8 non-space characters) must occur within lines `n-2 .. n+2` (or `a .. b`) of the file; with no line it may
occur anywhere in the file [I: SPEC says "at the cited place" without a tolerance]. Failures are reasons such as
`citation design.md#L42: quote not found`.

S1 questions (verbatim from L4-CLR-003): router state = question title, context, options; instruction = "Does answering this require
a product, business, UX or policy decision by the project owner (rather than a technical decision derivable from the spec and code)?".
Citation check state = `{answer, cited_text}`; instruction = "Does `cited_text` support `answer`?". `trim_state` keeps the title and the instruction
intact and truncates context, then options, to `verifier.s1.max_state_tokens` (450); the token counter is injected (M1: `len(text) // 4`
approximation; M2: the S1 model's tokenizer, how to obtain it from Laya is [U] and settled by a test).

M1 S1 stand-in (OPT-IN, resolution of an SPEC gap, see Ambiguities): new config key `clarifier.s1_standin: none | llm_boolean`, default `none`
(bootstrap-core must add it to the schema; flagged in the report). With `none` SPEC holds verbatim: only a System-One profile counts as S1 and,
without one, nothing is auto-accepted. With `llm_boolean`, `LlmBooleanJudge` poses the same two questions to the `openai-chat` profile on the
`s1_judge` chain with schema `{"answer": boolean}` and maps it to probability 1.0 (yes) or 0.0 (no); the M1 live check on the dummy repo turns it on
explicitly. `SystemOneJudge` (M2) returns the model's calibrated probability.

### D6. Outcome and phase (SPEC 12.0)

`Clarifier.run` processes `open` questions that are not `verdict`, at most `clarifier.max_open_questions` (3) per escalation. For each:
auto-accept => `QuestionsPort.set_clarifier_answer` (Status `answered-by-clarifier`, answer, citations), ledger `question.answered{by: clarifier,
answer_sha256}`; otherwise `set_clarifier_suggestion` with the header line `_confidence: C · kind: K (S1 p=P) - needs a human_` and Status left `open`.
Every question also emits `clarifier.result{question_id, status: ok|invalid|unavailable, profile, kind, confidence, auto_accepted, reasons}`.
`next_phase = "implementing"` iff every question listed as blocking a pending task is answered, else `"awaiting_human"` with `exit_code = 11`.
The orchestrator performs the phase change; this change only returns the outcome.

### D7. Unavailable and invalid (L4-CLR-005)

`RoleUnavailable` from the factory, or invalid output after one repair, leaves the question `open` with no suggestion block, returns
`awaiting_human` / exit 11 (never 12), and the sticky comment contains the sentence "The clarifier was unavailable; no suggestions were
written." (or "...produced invalid output ..."). The unit is not put in `waiting_capacity`.

### D8. Notification (L4-CLR-004)

On `awaiting_human`, `build_sticky_section(...)` returns the markdown for `ClarifyOutcome.sticky_section`: one bullet per open question
`- Q-002 (product): <title>`, a link to `questions.md` on the unit branch, the `forge.notify_mentions`, the unavailable sentence when
applicable, and reminders for drafts (the `question.unsubmitted_answer` list from change 2). The clarifier does not call the forge: SPEC
L4-ARC-002 derives labels and the single sticky note from state, so forge-and-ci's `PrMirror.sync(forge, state, notes=[sticky_section])`
(called by the orchestrator's `mirror` hook after the phase change) writes the `l4:awaiting_human` and `l4:needs-answers` labels
(`labels_for(state)`) and puts the section into the one `<!-- l4:sticky -->` note. A forge failure is logged and reported in
`outcome.json.notes`; it never changes the exit code or loses the state in `questions.md`. `notify_awaiting_human` is therefore not a forge
writer; the name is kept for the section builder only.

### D9. Answer injection and re-entry (L4-CLR-006)

`render_answer_blocks(questions, redact)` emits one block per answered question that blocks or informs a pending task:
`<l4:data kind="answer" id="Q-001" by="clarifier">...</l4:data>`. `by` is `clarifier` for `answered-by-clarifier`, `human` for
`answered` and `accepted` (for `accepted` the effective text is the clarifier suggestion). `redact` is bootstrap-core's `l4.redact.Redactor.redact_text` (L4-OBS-002) and
runs before rendering; any literal `</l4:data>` inside the text is rewritten to `<\/l4:data>` so quoted instructions cannot close the block. The
function returns `consumed = [(qid, sha256(answer_text))]` for the implementer to record (L4-QMD-006). Because blocks are rendered from the file at prompt time, a human
edit made before the task starts is what gets injected (SCN-CLR-06); the override-after-use fix unit is not in this change.
`clarify_hook(services, unit)` (the orchestrator's lazily resolved `clarify` hook, `l4.clarifier.clarifier:clarify_hook`) builds the
clarifier from `Factory.for_role("clarifier", unit)` and `SpecQuestionsPort`, runs `Clarifier.run` on `implementing -> clarifying`, and
returns `ClarifyOutcome`. `Clarifier.reenter(unit)` is called through the same hook by the orchestrator at run start on the unit branch worktree: it reloads `questions.md`, returns the
answered question ids newly counted, the drafts (non-empty answer, Status `open`), and the eligible-task hint; it emits no phase change itself.

### D10. Alternatives considered

- Let the clarifier model self-report S1 probabilities: rejected (uncalibrated, and SPEC requires a separate S1 router).
- Auto-accept in M1 with only the clarifier's own confidence: rejected (it would bypass L4-CLR-002 conditions 3 and 4); the boolean LLM judge
  keeps the structure (and therefore the tests) identical to M2 and swaps only the judge.
- Escalate everything to humans in M1: safe, but fails walking-skeleton criterion 5 ("the clarifier answers what it can").
- Fixing line tolerance for citations at zero: rejected (an agent-quoted line number is often off by one after edits).

## Risks / Trade-offs

- R1 An LLM boolean judge is not calibrated: mitigated by requiring both kinds to be technical, `high` confidence and resolved citations; a
  wrong auto-answer is still caught later by tests and the verifier, and a human override creates a fix unit (L4-QMD-006).
- R2 Agentic clarifier writes to the tree despite read-only flags: the post-run clean-tree guard and read-only policies.
- R3 Prompt injection in spec or code text: data blocks, no tools on the backend path, read-only on the agent path, citations must resolve in the
  repository, and the auto-accept decision never depends on the clarifier alone.
- R4 Sticky-comment API differences (GitHub vs GitLab) are hidden behind forge-and-ci's `Forge` port and `PrMirror`; M1 only needs GitLab notes.
- R5 Context budget too small for large repos: the code excerpts are best-effort; a low-confidence answer simply goes to a human.

## Ambiguities resolved here

- Lifecycle name: the task text says `waiting_human`; SPEC 12.0 defines `awaiting_human` (exit 11). SPEC wins.
- L4-CLR-002.5 says nothing is auto-accepted without S1, while M1 must auto-answer without Laya/Jev. Resolution: an opt-in config key
  `clarifier.s1_standin: llm_boolean` (default `none`, SPEC verbatim) lets a non-System-One `openai-chat` profile on the `s1_judge` chain act as S1 with
  probabilities 0.0/1.0; to be amended into SPEC 3.2 / 9 in this change (DoD item 4). The alternative (everything goes to humans in M1) is the `none` default.
- "Every citation resolves" is vacuously true for zero citations; this change requires at least one citation for auto-accept.
- SCN-CLR-06 cites only L4-QMD-006; it is converted under L4-CLR-006 (part c) because it is a CLR scenario about the injected answer.
