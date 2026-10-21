## Why

A unit that asks a question stops until someone answers it. Today that someone is a person who runs
`l4 questions answer` or `accept` (or the operator's own agent, by hand, where `clarifier.answer_by_agents` is true),
and then starts a run. In a delivery plan this is the main source of idle time: the plan waits in `awaiting_human`
for hours although most questions (a technical choice the design already settles, a harness check whose real run is
the evidence, a disputed criterion that the code plainly meets) can be checked against the repository by a strong
model. The owner asked for an option that lets a delegate answer them inside the harness's own CI run: a strong model
defined in the configuration (Claude Code with Opus 5.5, or Codex with GPT-6.1) answers as a delegate, goes through
the same flow as `l4 questions answer`, and starts the run that implements the answer. It is for delivery plans and,
as an option, for units outside a plan.

Three defects of 0.4.16 sit on the same path and are fixed here:

1. **The actor of an answer is wrong for every kind but `harness`.** `Clarifier._actor` asks the commit only for a
   harness question, and `consume_verdicts` writes `human.verdict{by: "human"}` unconditionally. A verdict answer
   that an agent gave through `l4 questions` (its commit says `By: … (agent: CLAUDECODE)`) was recorded "answered by
   human" in a live run. The ledger, the labels and the judge's view must name the real actor.
2. **An idle run is charged to a plan.** A plan stopped at its run limit (90 of 90) largely from chained runs in which
   the dispatched unit did nothing while its questions were open. A run that does no work must not count against
   `max_runs` and must not chain another run.
3. **An agent's verdict could become calibration data.** S1 labels are made from every `human.verdict`; a verdict an
   agent or the delegate gave must not train the thresholds as a person's.

## What Changes

- **A new optional role and a top-level switch.** `roles.delegate` is a profile chain like `roles.implementer`
  (availability, fallback, doctor). The default order in the reference configuration is Claude Code with
  `claude-opus-5-5`, then Codex with `gpt-6.1-sol`. `delegate:` in `.l4/config.yaml` (read on the base branch only):
  `enabled` (default `false`), `scope` (`yolo`: the current unit of an active plan; `all`: also units outside plans),
  `kinds`, `independence`, `unfreeze` (default `false`), the per-question attempt limit, the per-task answer limit, the per-answer, per-unit and
  plan-share cost limits, the questions per run and the timeout (L4-DLG-001, L4-DLG-002, L4-DLG-009).
- **When it runs.** At the end of a run whose unit parks in `awaiting_human` (open blocking questions or verdict
  questions) and is in scope; and in a later run through the new planner action `delegate` when a question is still
  undecided (the delegate was cooling, or the job had no time left). One call per open question, at most
  `delegate.max_questions_per_run` per unit and run; never for a unit out of scope (L4-DLG-003).
- **How it answers.** The delegate runs in a read-only agent mode (Claude Code `--permission-mode plan` with only
  `Read,Grep,Glob`; Codex `-s read-only`) in a detached worktree of the pushed unit head that the sandbox mounts
  read-only, with the question, the unit's spec, the verification report, the gate log excerpt and the test sources in
  the prompt as data blocks. It returns one strict JSON document `l4/delegate-result@1` `{question, decision, text,
  reason, checked}`. The harness checks it: the decision fits the kind, every `checked` entry resolves at the unit
  head, a reject of a hold ends with `WHEN … THEN …` where the question asks for it, and nothing is unfrozen unless
  `delegate.unfreeze: true` lets it accept the clarifier's suggestion (L4-DLG-014). Anything
  else is a discarded reply, and a discarded reply is an escalation (L4-DLG-004, L4-DLG-005).
- **The same validation and the same commit.** The answer goes through the checks of `l4 questions answer/accept`
  (`check_question`, `check_text`, `round_trip`); `clarifier.answer_by_agents` is not needed, the delegate is its own
  permission. It is committed with the subject of `l4 questions`, `By: delegate (<model> via <cli>; profile <p>)`,
  `Via: l4 delegate` and `[skip ci]`, and pushed by the run. Then the run asks the forge to start the next run on the
  base branch, in a plan and outside one, so the next run reads the answer as it reads a person's (L4-DLG-006,
  L4-DLG-007).
- **Escalation.** The delegate answers `escalate` when it cannot check a claim itself. The question then stays open for
  a person: the label `l4:needs-person`, a sticky section, an `Escalated by:` line in `questions.md`, and a plan that
  waits without chaining. No delegate profile usable, a limit reached and a discarded reply escalate too; a delegate
  that is only cooling is deferred to a later run, never parks the unit in `waiting_capacity` (L4-DLG-008,
  L4-DLG-013, L4-AVL-010).
- **Independence.** The delegate is never the profile, or the served model, that asked the question (the implementer
  of the task), and for a verdict question never a judge of the round that raised it. `question.raised` records the
  asker (L4-DLG-002).
- **Audit.** Every answer is recorded `question.answered{by: delegate, profile, model, answer_sha256}` and
  `delegate.result`; it is labelled `delegate_override` wherever 0.4.16 labels `agent_override` or `human_override`
  (proofs, `verification.md`, the judge's view, `l4 yolo report`); `questions.md` shows `Answered by: the delegate
  (<model> via <cli>)`; the S1 calibration labels take only a person's verdicts (L4-DLG-010, L4-VER-051).
- **The real actor for every kind** (fix 1): one function decides who wrote an answer (person, agent, delegate,
  clarifier) from the ledger and the commit that wrote that question's answer; the clarifier's reentry and the
  verifier's `human.verdict` both use it (L4-QMD-009, L4-CLR-006).
- **Idle runs are free and chain nothing** (fix 2): a run in which the dispatched unit made no agent call, ran no gate
  and changed its phase only into `awaiting_human` or `clarifying` is recorded `plan.run_idle` and the fold does not
  count it; such a run starts no next run (L4-YOLO-012, L4-YOLO-014).
- **Status, doctor, docs.** `l4 status`, `l4 status --unit` and `l4 yolo status` name the delegate's answers and
  escalations; doctor `DLG-001` (configuration and independence) and `DLG-002` (a delegate profile is usable);
  SPEC, runbook, `docs/yolo-mode.md`, `docs/control-loop.md`, the skill references and the CHANGELOG
  (`## 0.4.22 (unreleased)`) (L4-DLG-011, L4-DLG-012).

Out of the delegate's reach, by construction: activating, cancelling, resuming or extending a plan, restarting a unit,
editing specs or configuration, replacing an answer, merging outside an active `merge: auto` plan's guard, and
dispatching anything; unfreezing a frozen file only with `delegate.unfreeze: true`. The
delegate only returns a JSON document; the harness makes the one write.

## Capabilities

### New Capabilities

- `delegate`: the delegate role, its configuration, when it runs, its sandbox and result, the shared write path,
  the next run, escalation, limits, audit, status, doctor checks and unfreezing (L4-DLG-001..014, L4-AVL-010
  modified).
- `question-actors`: who answered a question, for every kind, and how the harness writes and labels it
  (L4-QMD-003, L4-QMD-009, L4-CLR-004, L4-CLR-006, L4-VER-051 modified).
- `plan-run-accounting`: chaining after a delegate answer and idle runs that are not charged (L4-YOLO-012,
  L4-YOLO-014 modified).

### Modified Capabilities

None as an OpenSpec delta with a baseline: `openspec/specs/` holds none, so the MODIFIED blocks of the three new
folders restate the full new text of L4-AVL-010, L4-QMD-001, L4-QMD-003, L4-QMD-009, L4-CLR-002, L4-CLR-004,
L4-CLR-006, L4-VER-051, L4-YOLO-012 and L4-YOLO-014, and `tasks.md` group 17 edits `docs/SPEC.md`, the normative
text.

## Impact

- New code: `src/l4/delegate/` (configuration helpers, prompt, result checks, limits, the pass), the read-only agent
  mode of `src/l4/agents/claude_code.py` and `codex.py` (built but never used before), a read-only worktree mount in
  `src/l4/sandbox/bwrap.py`.
- Changed code: `src/l4/config/schema.py`, `src/l4/specs/questions.py` and `questions_cli.py` (the edit core is shared),
  `src/l4/clarifier/clarifier.py` and `notify.py`, `src/l4/verifier/verdicts.py`, `traceability.py`,
  `src/l4/implementer/tdd.py`, `loop.py`, `src/l4/s1/labels.py`, `src/l4/planner.py`, `src/l4/orchestrator.py`,
  `src/l4/services.py`, `src/l4/yolo/cycle.py`, `state.py`, `report.py`, `commands.py`, `src/l4/state/status.py`,
  `src/l4/archive.py`, `src/l4/setup/github.py`, `src/l4/doctor/`.
- The ledger gains `delegate.asked`, `delegate.result` and the plan ledger `plan.run_idle`; `question.raised` gains the
  asker; `question.answered` and `human.verdict` gain `by: agent | delegate` with `profile` and `model`.
- New forge label `l4:needs-person`. New prompt `delegate@1`, schema `l4/delegate-result@1`.
- Default behaviour is unchanged: the delegate is off unless `delegate.enabled: true` and `roles.delegate` are set on
  the base branch. The two fixes (actor, idle runs) apply to everyone.
- Builds on the 0.4.18 base (0.4.17 and the held-accept work merged first): `still_waits`, the kept patch of a held
  step and the sandbox's empty home are used as they exist there.
