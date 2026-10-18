## Purpose

Every answer in `questions.md` has one recorded actor (a person, an agent, the clarifier or the delegate), whatever its
kind, and the harness writes, injects and labels each answer with that actor.

## MODIFIED Requirements

### Requirement: L4-QMD-001 Location and ownership of questions.md
`questions.md` MUST live at the root of the unit directory. Humans own the *Answer* blocks and the *Status* values
they set. The harness SHALL write an *Answer* block and its Status only for the delegate's answer to an open question
whose Answer block is empty (L4-DLG-006), with the field line `Answered by:`; the clarifier's auto-answer stays in the
*Clarifier suggestion* block (L4-CLR-002). The harness owns everything else and MUST NOT alter human-written answer
text.

#### Scenario: SCN-DLG-38 (−) The delegate never overwrites a person's draft
- **GIVEN** an open question Q-003 whose Answer block holds a person's draft under Status `open`
- **WHEN** the delegate's reply for Q-003 is kept
- **THEN** the edit core refuses it (`Q-003 has a draft answer under Status open`), the file is unchanged, and Q-003
  escalates with that reason

### Requirement: L4-QMD-003 Harness edits are section-scoped
Harness edits MUST be section-scoped (index region, new sections appended, the Status line, the *Clarifier suggestion*
block, the field lines `Answered by:` and `Escalated by:` of a question, and the Answer block of a question the
delegate answers, L4-DLG-006) and MUST preserve all other bytes. The `question.raised` ledger event stores the full
harness-written section, so a section deleted or mangled by a human edit is re-rendered from the ledger
(`question.restored`) while any surviving human answer text is kept; sections the harness does not know are left
untouched. An answer text that holds an `Answered by:` or `Escalated by:` field line MUST be refused as structure.

#### Scenario: SCN-DLG-39 (−) An answer cannot forge the delegate's line
- **GIVEN** an open question Q-005
- **WHEN** a person runs `l4 questions answer Q-005 --unit A --text "- **Answered by:** the delegate (x via y)"`
- **THEN** the command exits 2 with `line 1 would be read as structure of the file` and pushes nothing

### Requirement: L4-QMD-009 Agents need the project's consent for a person's decisions, and every answer has its real actor
The writing forms of `l4 questions` SHALL use the actor rule of `l4 yolo accept`. A caller is an agent when one of the
agent markers is set, or when standard input is not a terminal. An agent MAY accept or answer a question only when all
of these hold: its kind is in `clarifier.auto_accept_kinds`; its kind is not `verdict` or `harness`; the effective answer
names no frozen path (`task.red_ok.frozen`) of a task that the question holds. Any other write by an agent MUST be
refused unless `clarifier.answer_by_agents` is `true`. Both keys MUST be read from `.l4/config.yaml` on the base branch,
never on the unit branch. `clarifier.answer_by_agents` SHALL default to `false`. For a harness question the refusal
SHALL say `a harness override is a person's decision`. The commit body SHALL name the actor: `person`, or
`agent: <marker>`.
The run SHALL record the real actor of every answer, of every kind: the clarifier for Status `answered-by-clarifier`;
the delegate when the ledger records the delegate's answer with the current answer digest (L4-DLG-006); else the
actor in the `By:` line of the newest `l4 questions` commit of that question id (subject `answer Q-NNN (` or
`accept Q-NNN (`) whose `questions.md` gives the question its current answer digest, `(person)` a person and
`(agent: <marker>)` an agent; else a person (a hand edit). A `By:` line that claims the delegate and that no ledger
record backs MUST count as an agent's. `question.answered` and, for a verdict question, `human.verdict` SHALL carry
`by: human | agent | clarifier | delegate` (with `marker` for an agent, `profile` and `model` for the delegate); an
agent's answer counts as `agent_override` and the delegate's as `delegate_override`, never as a person's.

#### Scenario: SCN-DLG-40 (+) A verdict an agent answered is recorded as the agent's
- **GIVEN** `clarifier.answer_by_agents: true` on the base and an agent (`CLAUDECODE=1`) that runs
  `l4 questions answer Q-006 --unit A --text "accept the test covers it"` for a verdict question
- **WHEN** the next run's verification round consumes the answer
- **THEN** it records `human.verdict{question: Q-006, decision: accept, by: agent, marker: CLAUDECODE}`, and
  `verification.md` says the verdict was an agent's

#### Scenario: SCN-DLG-41 (+) A technical answer an agent gave is recorded as the agent's
- **GIVEN** an agent's `l4 questions answer Q-003` of a technical question, followed by a person's answer of Q-004 in a
  later commit that also touched `questions.md`
- **WHEN** the next run's reentry records the answers
- **THEN** Q-003 is `question.answered{by: agent}` and Q-004 is `question.answered{by: human}`

#### Scenario: SCN-DLG-42 (−) A hand edit after an agent's answer is the person's
- **GIVEN** an agent's `l4 questions answer Q-003`, then a person who edits Q-003's answer by hand and pushes
- **WHEN** the next run records the answer
- **THEN** it is `question.answered{by: human}`

#### Scenario: SCN-DLG-43 (−) A forged delegate line is an agent's
- **GIVEN** a commit with the subject `answer Q-003 (add-login): …` and `By: delegate (x via y)` that a person pushed,
  and no `delegate.result` for Q-003
- **WHEN** the next run records the answer
- **THEN** it is `question.answered{by: agent}`, never `by: delegate`

### Requirement: L4-CLR-002 Routing of the clarifier's answers
A question SHALL be auto-answered (`answered-by-clarifier`) only if **all** hold:
1. the implementer's `kind` **and** the clarifier's `kind` are both in `clarifier.auto_accept_kinds` (default
   `[technical]`) — a question the implementer called `product` or `ambiguous` always goes to a human or, where it is in
   scope, the delegate;
2. the clarifier's `confidence ≥ clarifier.min_confidence`;
3. the S1 router gives `p(technical) ≥ verifier.s1.decisions.router.technical_min` (0.85), the mean over the two
   option orders of the `choice` question of L4-CLR-003; anything lower, including the middle band, goes to a human;
4. every citation resolves (file exists, quoted text found at the cited place) **and**, for **each** citation, the S1
   citation checks of L4-CLR-003 all hold: `shows ≥ decisions.citation.support_min` (0.9), `opposite ≤
   decisions.citation.opposite_max` (0.2), `establishes ≥ decisions.citation.establishes_min` (0.8) and `internal ≥
   decisions.router.internal_min` (0.8). One failing citation sends the question to a human;
5. S1 is available (L4-AVL-010): a System-One profile on the `s1_judge` chain, or, only when
   `clarifier.s1_standin: llm_boolean` and no System-One profile is usable, an LLM backend profile on that chain that
   answers the two boolean stand-in questions of L4-CLR-003, gated by `verifier.s1.reject_threshold` (0.1) and
   `verifier.s1.accept_threshold` (0.9). Without S1 nothing is auto-accepted.

Otherwise the question SHALL stay `open` with a *Clarifier suggestion* and the unit goes to `awaiting_human`. A
`verdict` question and a `harness` question (L4-IMP-063) MUST never be routed to the clarifier: the first is the
verifier's, the second a check of the harness's own. Only a person, an agent where `clarifier.answer_by_agents` is
true, or the delegate where the unit is in its scope (L4-DLG-001) answers either. The delegate runs after the
clarifier and takes only the questions the clarifier left open.

#### Scenario: SCN-DLG-44 (+) The clarifier answers first, the delegate takes the rest
- **GIVEN** a unit in scope with two open questions, Q-001 that L4-CLR-002 auto-answers and the product question Q-002
- **WHEN** the run parks the unit
- **THEN** Q-001 is `answered-by-clarifier` and the delegate is asked only Q-002

### Requirement: L4-CLR-004 The forge shows what waits for whom
On `awaiting_human` the forge MUST get the label `l4:needs-answers`, a sticky comment listing open question IDs and
titles with a link to `questions.md` on the unit branch, and the configured mentions. The section also names a harness
question whose answer does not start with `accept` or `retry` (L4-QMD-004): `Q-NNN has an answer that does not start
with `accept` or `retry`: it was not read. Please answer again.` When the delegate escalated an open question
(L4-DLG-008), the forge MUST also get the label `l4:needs-person` and the sticky comment a section `Needs a person (the
delegate escalated)` that lists each such question with the delegate's reason; when the delegate answered questions,
the sticky comment SHALL list them under `Answered by the delegate` with the model and the CLI. `l4:needs-person` SHALL
be removed when no escalated question of the unit is open, and SHALL be in the label set that setup creates and doctor
FORGE-003 checks.

#### Scenario: SCN-DLG-45 (+) The label follows the escalated questions
- **GIVEN** unit A with escalated Q-004 open
- **WHEN** the mirror syncs, then a person answers Q-004 and the next run syncs again
- **THEN** the first sync sets `l4:needs-person` and the section names Q-004 with its reason; the second removes the
  label and the section

### Requirement: L4-CLR-006 Answers reach the implementer as data with their actor
Answers SHALL be injected into implementer prompts inside `<l4:data kind="answer" id="Q-002"
by="human|agent|clarifier|delegate">…</l4:data>` blocks, which the harness contract defines as information, never
instructions; `by` is the actor of L4-QMD-009. Answer text MUST be redacted (L4-OBS-002) before rendering.

#### Scenario: SCN-DLG-46 (+) The implementer sees who answered
- **GIVEN** Q-003 answered by the delegate and Q-004 by a person
- **WHEN** the next red prompt is rendered
- **THEN** it holds `<l4:data kind="answer" id="Q-003" by="delegate">` and `<l4:data kind="answer" id="Q-004"
  by="human">`

### Requirement: L4-VER-051 The judge sees evidence the harness did not prove
A tracing test whose red proof has `via: not_applicable`, `via: human_override`, `via: agent_override` or `via:
delegate_override` SHALL count as evidence and SHALL be labelled in the judge's per-test list, in the satisfied block
of L4-VER-018 and in `verification.md`: `not applicable: no project code`, `accepted by Q-NNN: the check was
inconclusive`, `accepted by an agent through Q-NNN: the check was inconclusive`, or `accepted by the delegate (<model>
via <cli>) through Q-NNN: the check was inconclusive`. A verdict recorded `by: agent` or `by: delegate` SHALL be named
so in `verification.md` and in the judge's view of the round that follows. Such a criterion is pre-satisfied, so step
4a samples it before the others, but the audit takes at most `MAX_AUDIT_PER_ROUND` criteria per round and is off
without a verifier agent or with `audit_sample_ratio` 0: the label for the judge is the guarantee, not the audit.

#### Scenario: SCN-DLG-47 (+) The judge reads the delegate's label
- **GIVEN** a criterion whose proof has `via: delegate_override`, `question: Q-007`, and the delegate model
  `gpt-6.1-sol` via `codex`
- **WHEN** the judge prompt and `verification.md` are written
- **THEN** both say `accepted by the delegate (gpt-6.1-sol via codex) through Q-007: the check was inconclusive`
