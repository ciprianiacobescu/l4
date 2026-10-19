## Context

A question stops its task (L4-QMD-005) and a verdict question stops the verification round (L4-VER-013). The unit parks
in `awaiting_human` (exit 11), and a delivery plan waits on it without chaining a run (L4-YOLO-013). Who may answer:

| Kind | Raised by | Answered today by |
|---|---|---|
| `technical`, `product`, `ambiguous` | the implementer (its blocked step) or intake lint | the clarifier when L4-CLR-002 holds; else a person; an agent through `l4 questions` when the kind is in `clarifier.auto_accept_kinds` and no frozen path is named, or anything with `clarifier.answer_by_agents` |
| `harness` | the harness, during an implementer step (L4-IMP-063) | a person; an agent only with `clarifier.answer_by_agents` |
| `verdict` | the verifier on NEEDS_HUMAN (a disputed criterion, a judge-only finding, a hold) | a person; an agent only with `clarifier.answer_by_agents` |

The writing path of a person is `l4 questions answer|accept` (`src/l4/specs/questions_cli.py`): fetch, the refusals of
L4-QMD-008, the agent rule of L4-QMD-009, a section-scoped edit that must read back (`round_trip`), one plumbing commit
on the fetched head with `[skip ci]`, a push without force, then `start_run_line` (the forge's `start_run` on the base).
The next run's `Clarifier.reenter` records `question.answered{by}` and the verifier's `consume_verdicts` records
`human.verdict{by}`.

What the code does today, read for this change (0.4.16):
- `Clarifier._actor` returns `agent` only when `question.kind is HARNESS` and the newest commit touching
  `questions.md` has `By: … (agent: …)`; every other answer is `human` (or `clarifier`). `verdicts.consume_verdicts`
  writes `by="human"` always. `s1/labels.py` turns every `human.verdict` into a calibration label (`human:verdict`).
- The agent adapters have three permission modes (`PermissionPolicy`): `implement`, `read_only` and `judge`. `judge`
  is tool-less in an empty directory (`judge_workdir`, Claude `--tools ""`, Codex `--skip-git-repo-check`); the
  clarifier and the verifier's judges use it. `read_only` (Claude `--permission-mode plan --tools Read,Grep,Glob`,
  Codex `-s read-only`) is built in both adapters but **no caller uses it** (`grep PermissionPolicy(`): the delegate
  is its first caller.
- The bwrap agent sandbox binds the worktree read-write and shares the network (the model API needs it).
- A plan charges a run when its step dispatches a unit (`_dispatch_events`, `extra_run=1`) and when a unit's run did
  not start (`_not_started`); the fold keeps the maximum `runs` per (unit, attempt) (`yolo/state.py`). A step that
  waits or finds nothing to dispatch charges nothing.
- Model ids: Claude Code takes `--model <profile.model>`; Codex takes `-m <profile.model>` and
  `-c model_reasoning_effort=<options.reasoning_effort>` (`codex.py` `build_command`). `claude-opus-5-5` is the id of
  Opus 5.5 (SPEC §3.2 uses it for `claude-opus` and `judge-opus`). `gpt-6.1-sol` is the Codex slug of GPT-6.1: the
  vendor's models page (developers.openai.com/codex/models, now served at learn.chatgpt.com/docs/models, read
  2026-10-18) shows `codex exec -m gpt-6.1-sol`; GPT-6 is `gpt-6-sol`. SPEC §3.2 already uses `gpt-6.1-sol`.

## Goals / Non-Goals

**Goals:** a delegate that answers what the repository can settle, through the very checks and commit of
`l4 questions`, with every answer audited and labelled; escalation to a person for anything it cannot check; no loop
and no unbounded cost; the actor of every answer right; idle plan runs free.

**Non-goals:** the delegate never replaces an answer (`--replace`), never edits `questions.md` beyond one question's
spans, never unfreezes a file unless `delegate.unfreeze: true` (D15), never merges outside an active `merge: auto`
plan's guard, and never acts on a plan or a unit's lifecycle. No change to the
clarifier's routing (L4-CLR-002) or to who may use `l4 questions` by hand.

## Decisions

**D1. Scope (owner D1 and the scope update).** `delegate.enabled` (default `false`) and `delegate.scope`
(`yolo` default, or `all`) are read from `.l4/config.yaml` on the base branch, never on a unit branch (L4-CFG-004).
A unit is in scope when:
- `scope: yolo`: it is the current unit of a plan that is `active` or `waiting` on the target, or a fix unit of it;
- `scope: all`: that, or it is in no plan file while no plan is active on the target (L4-YOLO-010 gives units outside an
  active plan no agent work, and the delegate is agent work);
- never a unit that `yolo.hold` matches, a unit of a `stopped` or `cancelled` plan, or a finished unit.
Every kind may be answered (`delegate.kinds`, default all five). The delegate MUST answer `escalate` when it cannot
check a claim itself; a `product` or `ambiguous` question is answered only when the spec, the steering (Kiro) or the
project's own documents (proposal, design, docs, code) settle it, with that material cited; else it escalates (owner
decision 4).
Out of reach by construction, not by a prompt rule: the delegate returns one JSON document and has no other output. It
has no forge token and no CI token (the L4-SEC-001 allow-list), no shell under Claude Code (`Read,Grep,Glob` only), a
read-only filesystem under Codex, and no tool server. The harness makes the one write, and only for the question asked.
So activating, cancelling, resuming or extending a plan, restarting a unit, editing specs or configuration and
dispatching anything stay out of its reach.

**D2. Profiles (owner D2).** `roles.delegate` is an ordered chain of profiles (the factory of L4-FAC-006: availability,
cool-downs, fallback, `availability.selected`). Only `claude-code` and `codex` adapter profiles serve the role
(`serves=("claude-code", "codex", "fake")`): these are the adapters whose read-only tool mode L4 defines; an
`opencode` profile has no read-only tool mode in L4 and a `kiro-cli` read mode is unverified (K13). The reference
configuration gains:
```yaml
profiles:
  delegate-opus: {adapter: claude-code, model: claude-opus-5-5, auth: subscription, vendor: anthropic}
  delegate-sol: {adapter: codex, model: gpt-6.1-sol, auth: subscription, vendor: openai,
                 options: {reasoning_effort: high}}
roles:
  delegate: [delegate-opus, delegate-sol]   # optional (L4-AVL-010)
```
The role is optional: no usable profile never parks the unit in `waiting_capacity` (D9).

**D3. Independence (owner D3).** The delegate must not be the mind that asked or judged. `question.raised` records the
asker: `profile` and `model` of the step that raised it (implementer and harness questions), and `judges:
[{profile, model}]` of the round for a verdict question. The pass gives the factory a constraint
(`Factory.for_role(..., constraints=)`, the verifier's independence hook) that vetoes:
- `delegate.independence: model` (default): a profile whose name is an asker's or whose model is an asker's served
  model (the model the step reported, else the profile's `model`);
- `delegate.independence: profile`: only a profile whose name is an asker's (the owner's literal rule).
The default is stricter than the literal rule on purpose: `claude-opus` and `delegate-opus` are two names for one model;
with the default chain a verdict that `judge-opus` raised goes to `delegate-sol` unless the implementer is on that model
(owner decision F9, below). A `question.raised` from before this
change (no asker) counts every implementer profile of `profiles_used.implementer` (and every judge profile of the
unit's rounds for a verdict question) as asker: fail safe. A question raised at intake (`source: intake_lint` or
`intake_open_questions`, `orchestrator.py`) has no agent step behind it, so it has no asker and vetoes nothing. No
profile left is an escalation (`no independent delegate`).
The owner chose this default (owner decision 1).

**Owner decision F9 (2026-10-19): a verdict question is never answered by the model that wrote the code.** For a
`verdict` question the askers are the round's judges AND the unit's implementer profiles with their models: every
implementer profile that ran a step of the unit (`availability.selected{role: implementer}` in its ledger), else the
configured `roles.implementer` chain when the ledger names none, plus every model those steps reported
(`agent.finished{model}` of a `red`, `green` or `single` step): an asker's model is the one the step reported, else the
profile's, so an implementer profile on an alias (`opus`) served as `claude-opus-5-5` vetoes `delegate-opus`. Doctor
`DLG-002` warns about a model that looks like an alias. `independence: model` therefore vetoes those models
too, and `independence: profile` those profile names, so the model that wrote the code can never overturn the judge's
dispute of it. In the reference configuration (implementer `codex-sol`, `gpt-6.1-sol`; judge `judge-opus`; chain
`[delegate-opus, delegate-sol]`) a verdict question has no independent delegate and escalates (`no independent
delegate`); a third model in the chain (for example `delegate-sonnet`, `claude-sonnet-5`) answers it. Doctor `DLG-001`
reports a chain with no profile independent of both the judges and the implementers. Technical, product, ambiguous
and harness questions are unchanged (the asker is the step that raised them).

**D4. The next run continues, not the same run (owner D4).** After the delegate answers, the run pushes the answer and
asks the forge to start the next run on the base branch; the unit is not moved in the same run. Reasons:
- the lifecycle's `awaiting_human → implementing` and `→ verifying` edges fire on "answers submitted" when a run reads
  the file (SPEC 12.0), and the simulation suite asserts that no other edge exists; continuing in the same run needs a
  new edge and a second path for the transition;
- it is how a person's answer works (L4-QMD-008: "the next run records `question.answered` as it does for a hand
  edit"), in a plan and outside one, so yolo and `scope: all` share one path;
- a person can see the answer, the label and the `By:` line on the branch before the work starts, and stop it;
- the delegate's time does not eat the implementer's job budget.
Where the write happens: inside the run that parks the unit, while it holds the unit's lease, after the phase is
`awaiting_human` and before `Orchestrator.close`. `l4 questions`' `_prepare` refuses a unit with a live run
(`unit_refusal`, the lock ref's pending ledger), and the run's own lease is exactly that, so the delegate does not call
`_prepare`: it calls the shared core `build_edit` (`check_question`, `check_text`, `round_trip`, `edit_answer`,
`edit_accept`) on a `Folder` read from the run's worktree at the unit head, and its own lease stands in for the
live-run refusal. The commit is the run's (D8); the push is the run's close push.

**D5. Read-only sandbox, material in the prompt, claims checked (owner D5).** The owner asked for "the same sandbox kind
as the judge" and "check claims against the repository itself". The judge's mode is tool-less in an empty directory,
so it can check nothing beyond its prompt. The delegate therefore runs in the adapters' `read_only` mode:
- Claude Code: `-p --output-format stream-json --verbose --model M --permission-mode plan --safe-mode
  --strict-mcp-config --tools Read,Grep,Glob --allowedTools Read,Grep,Glob --json-schema S --max-turns N
  [--max-budget-usd B]` (the argv `build_command` already makes for `read_only`);
- Codex: `exec --json -m M [-c model_reasoning_effort=E] -s read-only --ignore-user-config --ignore-rules
  -c project_doc_max_bytes=0 --ephemeral --output-schema S -o <private>/result.json -` (no tool server; `--ephemeral`
  is new for `read_only`: a delegate leaves no session);
- cwd: a detached worktree of the unit head (`git worktree add --detach`), in the run's private cache, removed after
  the pass; the pass first commits and pushes the run's state (`commit_questions` and `ctx.push()`, as the clarifier
  hook does), so the head the delegate reads, and that its `checked` claims must resolve at, is the one on `origin`;
  the bwrap sandbox binds it **read-only** (new `SandboxSpec.worktree_read_only`, emitted as
  `--ro-bind`) and keeps the step's private directory writable for the result file; repository guidance is masked
  (HB-X1) as for every agent;
- the network stays shared (the CLI reaches its model); neither mode has a web tool.
`read_only` is new in production: tasks add argv contract tests for both adapters and the live task runs both.
The prompt (`delegate@1`, versioned, its sha256 on `delegate.asked`, published redacted like the clarifier's) carries,
each inside `<l4:data kind=… source=implementer|verifier|harness|person>` blocks that the system text calls data and
never instructions:
- the question section (title, context, options, clarifier suggestion) and the unit's answered questions;
- the unit's `proposal.md`, `design.md`, specs and `tasks.md` (the clarifier's `collect_sources`, within
  `implementer.context_budget_tokens`), and for a Kiro unit the steering that applies, as the 0.4.17 implementer prompt
  carries it;
- for a `verdict` question: the criterion or finding or hold text, the judge's reason and evidence from `verdict.json`,
  the section of `verification.md` for the target;
- for a `harness` question: `check.inconclusive{reason, runs, kept}`, the `excerpt` of the gate (L4-IMP-064), and the
  names of the tests the question holds;
- the gate log excerpt of the latest failing gate of the task, when there is one.
Everything is redacted by the run's redactor before any cut (L4-IMP-064's rule: a cut inside a secret leaves a prefix
the redactor cannot see). Question text, context and evidence are written by implementer agents, so an injection is
expected; the defences are structural: the delegate writes nothing, its reply is checked field by field (D7), each
`checked` claim must resolve in the repository, and the answer is labelled.

**D6. One call per question, one pass per unit (owner D6).** The pass makes one worktree per unit and pass, then, for
each open question in scope, oldest first, at most `delegate.max_questions_per_run` (default 5), selects a profile with
that question's independence constraint (the askers differ per question; the factory's probe cache makes a second
selection free) and calls the delegate once. Per question because the result schema and "a discarded reply is an
escalation" have a clean meaning per question; a half-valid batch reply would need a rule there is none for; one
question's injected text cannot steer another's answer; and the cost and the attempt limits are per question.
Where the pass runs:
- in the run that parks the unit in `awaiting_human` (after the clarifier, which still answers first where
  L4-CLR-002 holds; through `fixing` when a fix unit waits for answers);
- in a later run, through the planner action `delegate`: a unit in scope in `awaiting_human` (or `fixing` with a
  waiting fix unit) with an open question in `delegate.kinds` that has no final delegate record for its current
  `question.raised` and no deferral in the future. A plan dispatches it like any action.
The pass is idempotent on the ledger: a question with `delegate.result{status: answered | escalated}` for its current
raise is never asked again. A pass that the job's soft deadline would cut (`job_remaining_s` below
`delegate.timeout`) asks nothing, records `delegate.result{status: deferred, reason: soft_deadline}` and starts one
next run.

**D7. The strict result.** Schema `l4/delegate-result@1`:
```json
{"question": "Q-004", "decision": "answer|accept|reject|retry|escalate", "text": "…", "reason": "…",
 "checked": [{"ref": "src/pkg/store.py:42 | test:tests/test_store.py::test_add | spec:design.md#D3", "quote": "…",
              "claim": "…"}]}
```
The harness keeps a reply only when every rule holds, else it is `discarded` (the reason names the first broken rule)
and the question escalates; there is no repair round:
- `question` is the id asked; `reason` is non-empty, at most 1,000 characters;
- the decision fits the kind: `technical`, `product`, `ambiguous` take `answer`, `accept` (only with a clarifier
  suggestion, L4-QMD-008) or `escalate`; `verdict` takes `accept`, `reject` or `escalate`; `harness` takes `accept`,
  `retry` or `escalate`;
- every decision but `escalate` has at least one `checked` entry, and every entry resolves at the unit head: a `path:line`
  whose file exists in the tree (a regular blob, not a symlink) with `quote` found within three lines of `line`; a
  `test:` id present in the latest test report of the unit; a `spec:` reference to a file of the unit folder with
  `quote` in it;
- `text` passes `check_text` (not empty, at most `MAX_TEXT_CHARS`, no structure line, no HTML comment, nothing the
  redactor changes); and the effective answer (the `text`, or the suggestion an `accept` takes) unfreezes nothing
  unless D15 allows it;
- a `reject` of a hold that is neither a scope nor a coverage hold ends with a `WHEN … THEN …` sentence (L4-VER-013:
  without it the round ends in `verify_fail_exhausted`, a dead end the delegate must not cause);
- the composed answer (`answer`: `text`; `verdict`: `accept <text>` / `reject <text>`; `harness`: `accept: <text>` /
  `retry: <text>`) passes `check_question` for the form (`answer`, or `accept` for a non-verdict `accept`).

**D8. The same edit, commit and records.** The edit is `build_edit`'s, so the file keeps every other byte, line ending
and BOM (L4-QMD-008). Two harness-owned field lines are added after `- **Status:**` (the parser's `_FIELD` learns them,
so an answer text that holds one is refused as structure):
`- **Answered by:** the delegate (claude-opus-5-5 via claude-code)` and, on escalation,
`- **Escalated by:** the delegate (gpt-6.1-sol via codex): <reason, redacted, at most 300 characters>`.
The commit is made by the run (its identity and its `L4-Unit`, `L4-Run`, `L4-Phase` trailers, as every commit a run
makes) with the subject and body of `commit_message`: `answer Q-NNN (<unit name>): <title>` (or `accept …`),
`Status: answered`, `By: delegate (<model> via <cli>; profile <p>)`, `Via: l4 delegate`, `[skip ci]`. It holds
`questions.md` and the run's ledger so far, like the clarifier's checkpoint (`commit_questions`). The ledger gets
`delegate.asked{question, kind, profile, model, prompt_sha256}`, `budget.cost{usd, profile, role: delegate, question}`,
`delegate.result{question, kind, status: answered|escalated|deferred|discarded, decision, profile, model,
answer_sha256, checked, reason, cost_usd}` and, for an answer, `question.answered{id, by: delegate, profile, model,
answer_sha256}` (the clarifier records `by: clarifier` the same way), so the next run's `reenter` sees the digest
recorded and writes nothing more.

**D9. Escalation, deferral, unavailability.** Final escalation (`delegate.result{status: escalated}`): the decision
`escalate`; a discarded reply; a limit reached (D10); no independent profile (D3); every profile of the chain unusable
for a cause only a fix ends (binary, login, `hello`, constraint: the L4-YOLO-035 classification). The question stays
open; the harness writes the `Escalated by:` line, the sticky note gets a section "Needs a person (the delegate
escalated)", the forge gets `l4:needs-person` (removed when no escalated question is open), and a plan waits with
`unit_awaiting_human` and a detail naming the escalation, without chaining. A person's answer (by hand or
`l4 questions`) ends it as today. Deferral (`status: deferred`): every profile cooling with a known `retry_after`, a
timeout or an adapter error, or the soft deadline. The question stays open without a label; the planner action
`delegate` takes it at the first run after `retry_after` (a plan waits as for any wait and goes on when the action
appears). `delegate.max_attempts_per_question` (default 2) deferrals or calls in all, then escalation.

**D10. Limits and cost.** All read from the base branch:
- `max_attempts_per_question: 2` (calls and deferrals, D9);
- `max_answers_per_task: 3`: answers whose question blocks the task (a verdict question counts per target: criterion,
  finding or hold id), across rounds and fix units of the unit; the next question on that task escalates
  (`delegate answer limit of task 3.1 reached`). A question itself takes one answer: `check_question` refuses a
  question that is not open.
- `max_cost_usd_per_answer: 3.0`: passed as `--max-budget-usd` to Claude Code; Codex has no budget flag, so the cap is
  checked before the call against what is left, and a call whose cost is not known (Codex reports tokens; without a
  `budgets.price_table` entry there is no USD) is counted at this cap against the delegate's own limits;
- `max_cost_usd_per_unit: 15.0`: the sum of `budget.cost{role: delegate}` of the unit and its fix units, in both scopes;
- `plan_cost_share: 0.25`: in a plan with `max_cost_usd`, the delegate's cost over the plan's units may use at most this
  share of the limit in force (with extensions). The delegate's cost is unit cost, so it is also charged into
  `plan.charged` and counts against `max_cost_usd` like any agent's;
- `timeout: 15m` per call (`RunRequest.timeout_s`); `max_questions_per_run: 5`.
A call is made only when what is left of each cap is at least `max_cost_usd_per_answer`; else the question escalates
with the cap named. Outside a plan, the per-task and per-unit limits are what stop a loop (owner update), with
`budgets.max_cost_usd_per_unit` above them.

**D11. The real actor of every answer (the 0.4.16 bug).** One function, `answer_actor(unit_dir, question, events)`,
returns `clarifier`, `delegate`, `agent` (with its marker) or `human`:
1. Status `answered-by-clarifier` → `clarifier`;
2. a `question.answered{by: delegate}` or `delegate.result{status: answered}` of this question with the current
   answer digest → `delegate`;
3. else the newest commit (at most 200 back) that touched `questions.md` with the subject `answer Q-NNN (` or
   `accept Q-NNN (` of this id (the `l4 questions` subject) and whose parse of that commit gives this question the
   current digest: its `By:` line decides, `(person)` → `human`, `(agent: X)` → `agent` with marker `X`, anything
   else (a `(delegate` line no ledger record backs) → `agent`;
4. else (a hand edit, or a later hand edit that changed the answer) → `human`.
`Clarifier.reenter` (`question.answered{by}`) and `consume_verdicts` (`human.verdict{by, marker, profile, model}`)
both call it. `human.verdict` keeps its name for old ledgers. `override_via` maps `agent → agent_override`,
`delegate → delegate_override`, `human → human_override`; `s1/labels.py` makes calibration labels only from verdicts
with `by: human` (a model's verdict is not ground truth). `_written_by_agent` (newest commit only) is removed.

**D12. Idle runs are free and chain nothing (owner D7).** The live symptom was a plan stopped at 90 of 90 runs, largely
from chained runs in which questions were open. The code charges a run only when the step dispatches, so the empty
runs were dispatched runs in which the unit did nothing. The most likely cause (inferred, not reproduced) is a planner
that says `implement` (`answers_unblock` also counts answers a prompt already consumed) while the orchestrator finds no
task it can run and parks the unit again; `_cause_gone` then resumes the plan, dispatches and charges again, and the
dispatch chains. The fix is a rule, not that one cause:
- a run is *idle* for the unit the step let run when the unit's ledger of that run has no `agent.finished` (any role),
  no `gate.finished`, and no `phase.changed` other than into `awaiting_human` or `clarifying`;
- after such a run the harness records `plan.run_idle{unit, attempt, run}` on the plan ledger (with the lease, like
  `unit.not_started`); the fold subtracts the idle runs of each (unit, attempt) from the charged maximum, so
  `used.runs` does not count them (a correcting `plan.charged` cannot lower a maximum);
- an idle run chains no next run: the plan waits for the next trigger (a person's answer, the delegate's `start_run`,
  the schedule), so nothing loops;
- unchanged: the charge at dispatch (the fold's stale retry needs the dispatch first), the charge of a run that did not
  start the unit (`_not_started`, the brake for a unit that never starts), a capacity park (its `phase.changed` to
  `waiting_capacity` is not idle), and a step that dispatches nothing (charges nothing, now pinned by a test).
`l4 yolo status` shows `runs: 14 of 90 (6 idle, not counted)`.

**D13. Normal mode (owner update).** With `scope: all`, a unit outside every plan gets the same pass, the same checks
and the same commit; after an answer the run starts the next run on the base exactly as `l4 questions answer` does
(the forge's `start_run` with the CI token; a refusal or no token is a log line, never a failure). There is no plan
chaining and no plan cost limit: the per-task answer limit and `delegate.max_cost_usd_per_unit` stop it. A verdict
`accept` only moves the unit on: the next round aggregates it, a PASS hands off (`in_review`), and merging stays a
person's (`forge.merge_policy`; the harness merges only the current unit of an active `merge: auto` plan,
L4-YOLO-008). Escalation leaves the question to a person with `l4:needs-person`, as in a plan.

**D14. Status and doctor.** `l4 status` (REASON of an escalated unit: `Q-004 needs a person (the delegate escalated)`),
`l4 status --unit` (`Delegate:` lines: answered with model, cli and cost; escalated with the reason; deferred with
the time), `l4 yolo status` (for the current unit: `delegate: 2 answered, 1 escalated (Q-004: <reason>)`, the plan's
delegate cost against its share, and the idle runs), each with `--json` fields. Doctor `DLG-001` (error, only when
`delegate.enabled`): the chain is non-empty, its profiles exist and are `claude-code` or `codex` adapter profiles,
`delegate.kinds` are known kinds, the limits are positive, and for every implementer profile and every judge profile at
least one delegate profile passes the independence rule (naming the pair that fails). `DLG-002` (warn): at least one
delegate profile is usable now (binary, auth and quota probes; `hello` under `--live`, LIVE-002), with the fix.

## Risks / Trade-offs

- **A model accepts what the judge disputed, and `merge: auto` merges it.** A delegate `accept` of a verdict question
  turns a NEEDS_HUMAN round into a PASS, and an active `merge: auto` plan then merges by its guard. Mitigations: the
  independence rule, a `checked` claim that must resolve, `delegate_override` in the judge's view, `verification.md`,
  the PR body and the report. The owner chose to keep the merge (owner decision 2).
- **Prompt injection from the implementer.** Expected and not preventable by text alone; bounded by D1 (no write, no
  tools that act) and D7 (field checks, resolved claims). A successful injection can at most produce one wrong answer,
  labelled `delegate_override`, inside the answer limits.
- **`read_only` mode is new in production.** Codex's own `-s read-only` sandbox runs inside bwrap like the implementer's
  `workspace-write` (which runs live), so it is expected to work [I]; Claude Code `--permission-mode plan` with a
  structured result in stream-json mode is built but not exercised [U]. The live task (18) runs both.
- **Cost.** Opus and GPT-6.1 at high effort are the most expensive profiles of a chain. The caps of D10 bound it; the
  plan share keeps the implementer's budget.
- **Idle-run rule hides a loop's cost?** No model cost is spent in an idle run by definition (no `agent.finished`), and
  an idle run chains nothing, so CI minutes are bounded by the triggers.

## Migration Plan

Off by default; no configuration changes behaviour until `delegate.enabled: true` and `roles.delegate` are pushed to
the base branch. The actor fix changes the `by` of new `question.answered` and `human.verdict` events only; old events
are read as they are. `plan.run_idle` is a new event that older harnesses ignore (their fold counts the runs as
before). Roll back: set `delegate.enabled: false` on the base.

**D15. Unfreezing is a configured choice (owner decision 3).** `delegate.unfreeze` (default `false`, read on the base
branch). A question whose effective answer names a frozen test or test-support file (`task.red_ok.frozen`, and the
pre-existing tests `existing_tests` adds) of a task it holds:
- `false`: is escalated with the path named (`the answer would unfreeze <path> of task <k> (delegate.unfreeze is
  false)`), because unfreezing lets the implementer change the test that proves its own red step;
- `true`: the delegate may `accept` the clarifier's suggestion for it. The rules of a person's accepted suggestion apply
  unchanged (`suggestion_effects`: the question itself must name the path, never an ignore file, at most
  `MAX_PATHS_PER_QUESTION`); the unfreeze is recorded `task.unfrozen{reason: delegate_answer, question, answer_sha256,
  by: delegate, profile, model}` and shown as `delegate_override` in `l4 status --unit`, `verification.md` and the
  report. A free-text `answer` that names a frozen file still escalates: only the suggestion's own, already checked
  text can unfreeze.

## Owner Decisions (2026-10-18)

1. **Independence by model.** `delegate.independence: model` is the default (D3); `profile` stays available.
2. **A PASS resting on a delegate's verdict accept merges under `merge: auto`.** The plan's guarded merge (L4-YOLO-008)
   applies as for a person's accept; the accept is labelled `delegate_override` everywhere (the judge's view,
   `verification.md`, the PR body, `l4 yolo report`). Outside a plan nothing merges (D13).
3. **Unfreezing is configured.** `delegate.unfreeze` (default `false`): `false` escalates a question whose answer would
   unfreeze a frozen test or test-support file; `true` lets the delegate take the clarifier's suggestion for it, with the
   same validation, shown and audited as `delegate_override` (D15, L4-DLG-014).
4. **`product` is in the default kinds.** A product question is answered only when the spec, the steering or the
   project's documents settle it; else the delegate escalates (D1).

## Open Questions

None left: the four questions of the first draft are the owner decisions above.
