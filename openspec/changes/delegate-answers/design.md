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
`opencode` profile has no read-only tool mode in L4 and a `kiro-cli` read mode is unverified (K13). (Superseded by
the 0.4.22 amendment, A1 to A3: `opencode` and `kiro-cli` profiles serve the role too.) The reference
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
The prompt (`delegate@2`, versioned, its sha256 on `delegate.asked`, published redacted like the clarifier's) carries,
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
next run. That deferral made no call and is not an attempt (0.4.22 amendment, C4, L4-DLG-013).

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
appears). `delegate.max_attempts_per_question` (default 2) deferrals or calls in all, then escalation; a deferral for the
soft deadline (no call made) is not counted (0.4.22 amendment, C4).

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
(Changed by the 0.4.22 amendment, C3: `true` opens a frozen test file only, never a test-support file, and nothing in
a fix task; L4-DLG-014, L4-DLG-025, SCN-DLG-88.)

## Owner Decisions (2026-10-18)

1. **Independence by model.** `delegate.independence: model` is the default (D3); `profile` stays available.
2. **A PASS resting on a delegate's verdict accept merges under `merge: auto`.** The plan's guarded merge (L4-YOLO-008)
   applies as for a person's accept; the accept is labelled `delegate_override` everywhere (the judge's view,
   `verification.md`, the PR body, `l4 yolo report`). Outside a plan nothing merges (D13).
3. **Unfreezing is configured.** `delegate.unfreeze` (default `false`): `false` escalates a question whose answer would
   unfreeze a frozen test or test-support file; `true` lets the delegate take the clarifier's suggestion for it, with the
   same validation, shown and audited as `delegate_override` (D15, L4-DLG-014). (The 0.4.22 amendment, C3 and open
   question 4, narrows `true` to frozen test files: a test-support file stays a person's change; the owner confirms.)
4. **`product` is in the default kinds.** A product question is answered only when the spec, the steering or the
   project's documents settle it; else the delegate escalates (D1).

## Open Questions

None left: the four questions of the first draft are the owner decisions above.

## 0.4.22 amendment

Drafted on the branch that merged the released 0.4.21 into this change's implementation. It adds the opencode and
kiro-cli adapters to the delegate, makes the option findable where an agent gets stuck, aligns the delegate with the
rules 0.4.21 shipped (reject-reason, verifier-cap, judge-parts, ci-evidence) and takes the polish of the first live
test. Requirements L4-DLG-015 to L4-DLG-027, scenarios SCN-DLG-56 to SCN-DLG-112; L4-DLG-002, L4-DLG-004, L4-DLG-012
and L4-DLG-014 get new text, and SCN-DLG-08a and SCN-DLG-55 new examples. The decisions are A (adapters), B
(discoverability), C (0.4.21) and P (polish); D1 to D15 stand where these do not replace them. A review of
this text (verified against the code) changed A1 to A5, B1, B2, C2 to C4 and D6/D9 as the sections below say.

### What the code does today (read for this amendment)

- `DELEGATE_SERVES = ("claude-code", "codex", "fake")` and doctor `ADAPTERS_THAT_SERVE = ("claude-code", "codex")`.
  D2 says "an opencode profile has no read-only tool mode in L4". That is no longer true: `opencode.config_content`
  has a `read_only` branch (edit deny; read, glob, grep, list allow; bash deny, or `ask` for an OpenCode Zen model;
  external directories denied but the private one; webfetch, websearch, question and doom_loop denied). It enumerates
  what it denies, so a tool it does not name is allowed.
- kiro-cli's `read_only` mode runs the **default agent** with `--trust-tools=fs_read`, the prompt as one argument
  (`MAX_ARG_BYTES` 100,000) and `--require-mcp-startup`, from the user's `KIRO_HOME`: the user's MCP servers, skills
  and steering reach it (K3), and the adapter's own docstring lists a read-only harness agent as open.
- Both prompt-contract adapters read a non-judge result from the file `$L4_RESULT_PATH` names. A read-only run cannot
  write that file (opencode `edit: deny`; a kiro agent without `write`), so the delegate on either adapter would end
  `result missing` on every call. `AgentJudge.complete_structured` also appends `SCHEMA_INSTRUCTION` ("Do not call any
  tool: answer from this prompt alone") to every prompt-contract prompt: the opposite of what the delegate must do.
- The independence check compares models with `same_model` (case, `[1m]`, date suffix, a `.` between digits). It does
  not cut a provider prefix: `openrouter/anthropic/claude-opus-5-5` passes against a `claude-opus-5-5` judge [V, run on
  this branch]. A kiro-cli profile on `auto` passes too: `auto` is a known string, not a known model [V].
- `run.py._record_cost` writes `budget.cost{usd}` only; a Kiro call's credits are dropped (the judge's
  `_record_cost` writes them, L4-KJD-004).
- The delegate's system text (`delegate@2`) asks a reject to end with `WHEN <situation> THEN <behaviour the code
  shows>`. 0.4.21 (L4-VER-059, L4-VER-060) says the opposite: the sentence states the behaviour the person expects,
  and the judge's suggested fix, which describes the code as it is, must not become the check. A delegate reject
  following its prompt pins the disputed behaviour (the 0.4.20 defect reject-reason fixed).
- `check_reply` asks for `WHEN … THEN …` only for a reject of a hold (`hold_kind` not None, not scope or coverage),
  never for a finding. A reject of a judge-only finding that cites no criterion and has no scenario is not converted
  by 0.4.21 (L4-VER-059: "answer again with a scenario") and its question is not consumed; the delegate never asks an
  answered question again, so a person has to find it and `--replace`. A reject of a `judge_view` hold with a scenario
  passes the check and escalates the unit `judge_view_rejected` (L4-VER-044: always the person's finding).
- `ci_not_fixed` is a phase change to `escalated` (exit 13), not a question: the pass, which runs for
  `awaiting_human` and `fixing` only, never sees it. A blocked fix chore's technical question carries the harness
  note "this is a fix task. It cannot unfreeze a test or test-support file …" (`chore_question_note`, ci-evidence
  D11), but `question.raised` records nothing that tells the pass it is a chore's.
- The continuation merge (`orchestrator.py`, after `continue_left_units`): the plan's request is dropped when a
  continuation was dispatched or no step started; then `after_delegate` re-adds one request when the pass answered,
  unless a continuation was dispatched. So an answer in a run in which no step started still starts one run [V, code].
- `render_pr_body` has no delegate line although owner decision 2 says the PR body labels the delegate's accept;
  `verification.md` titles every verdict answer `## Human verdicts`, also the delegate's and an agent's.
- `due.FINAL = ("answered", "escalated", "discarded")`: a final record ends the current raise for good.
- No status command says the delegate exists. `l4 init` writes no `delegate:` key, and DLG-001's pass line while it
  is off is `the delegate is off (delegate.enabled is false)`.

### A. opencode and kiro-cli as delegates

**A1. Four adapters serve the role (L4-DLG-015, L4-DLG-002 new text).** `DELEGATE_SERVES` and DLG-001's list become
`claude-code`, `codex`, `opencode`, `kiro-cli` (and `fake` in tests). A `command` profile or a backend profile is
skipped as an adapter that does not serve the role (SCN-DLG-08a now uses a `command` profile). What the delegate
needs differs from the judge's: it must read repository files and cite them, so the tool-less judge mode is not
enough, and it must not write, run a command that changes state, or reach the network beyond its model. Each adapter
gets a read-only mode built from an allow-list (deny by default), and on a prompt-contract adapter the reply is the
LAST top-level JSON object of the run's final message, validated like a judge's reply (`attach_judge_reply`): the
text after the last tool call (`RunResult.last_message`), else the whole reply text. The object is found by scanning
the text with `json.JSONDecoder.raw_decode` from each `{`; the scan resumes after an object it decoded (so an object
inside another is not top-level), skips a `{` that does not decode, and ignores code fences. It is not the text from
the first `{` to the last `}`, which a `{` in prose after the last tool call, a schema example before the answer or
two objects would break. No result file is written or read. `AgentJudge` takes the suffix variant `READ_THEN_REPLY` for a `read_only` request ("Read the files you need
with your read-only tools; you cannot change files or run commands. Then reply with a single JSON object that conforms
to this JSON Schema as the last thing you write, with nothing after it, …"), still outside `prompt_sha256` and the published prompt. A run
that called a tool outside its read set gives no reply: an adapter error, deferred, then escalated at the attempts
limit (L4-DLG-013). A call the adapter refused before it ran (opencode's permission map) did nothing, so such a
run that goes on and finishes yields a reply when, and only when, the reply is valid (`opencode.py` checks the final `stop` before the denials, so a run that was refused a call and then stopped goes to the reply parse, and a run with denials and no `stop` is `permission_blocked`; the amendment specifies that order: a refused call alone never voids a run that finishes, the reply must be valid, and a run that ended on a refused call with no valid reply yields none). On kiro-cli the agent has three tools, so a call to any other tool does not exist: it voids the run
and is a deferral source, and the adapter keeps every tool name of a turn for that check (`kiro_cli.py` keeps only
the first of a turn today).
Rejected: a result file in a private directory the read-only mode may write (opencode would need `edit` allowed for
one path, which `external_directory` cannot scope to a single file in its v1 permission map; kiro would need `write`
in the agent, which then writes anywhere the sandbox lets it); the judge mode with the files pasted into the prompt
(the delegate could no longer check a claim the prompt does not hold, which is the point of D5).

**A2. The opencode delegate (L4-DLG-016).** `opencode run --pure --format json -m <provider/model> --dir <detached
worktree> --title "l4 delegate <n>"`, prompt on stdin, the isolation of every opencode run (empty per-step
`XDG_CONFIG_HOME`, the four `OPENCODE_DISABLE_*` switches, `snapshot: false`, `share: disabled`, `autoupdate: false`).
`OPENCODE_CONFIG_CONTENT` for `read_only` becomes deny-by-default, key order part of the contract (the last matching
rule wins):
```json
{"tools": {"*": false, "read": true, "glob": true, "grep": true},
 "permission": {"*": "deny", "read": {"*": "allow", "*.env": "deny", "*.env.*": "deny"}, "glob": "allow", "grep": "allow",
                "external_directory": {"*": "deny", "<private dir>/**": "allow", "<private dir>/*": "allow"}}}
```
`list` is not an opencode 1.18.33 tool, so it is not in the set (the live task 29.1 records the tool names of a
run; the deny-by-default map covers any name). `read` keeps opencode's `*.env` and `*.env.*` denials after its allow
(the last matching rule wins), so a `.env` file stays unreadable.
A profile's `options.tools` is IGNORED in this mode: opencode turns a tools map into permission rules placed after
`"*": "deny"`, so a profile with `options.tools: [bash, edit]` would re-enable `bash` and `edit`. The map above is
the whole tool surface.
For an OpenCode Zen model (`opencode/…`) `bash` is sent (`tools.bash: true`), because Zen's free tier refuses a
request that lacks the bash or read tool [V live, 1.18.33/1.18.34, the existing judge rule], with the permission
`{"*": "deny", "<sentinel>": "ask"}`, `<sentinel>` a pattern no command matches: every command is refused and the
run is not ended. The earlier text relied on run mode auto-rejecting `ask`, which ends the run without a final
`stop` (`permission_blocked`); the sentinel form refuses by `deny`, and a refused call alone voids nothing (A1).
**Instruction files.** opencode's `Instruction.resolve` loads `AGENTS.md`, `CONTEXT.md` and `CLAUDE.md` from the
directory of a file it reads, upward, whatever `OPENCODE_DISABLE_PROJECT_CONFIG` says, and the loaded text steers the
model: an instruction file inside the unit's own tree would be a second prompt the delegate treats as instructions.
Before an opencode delegate runs, the harness removes the nested instruction files (those three names and any other
file name the adapter knows as an opencode instruction file) from the detached worktree's checkout. The claim checks
resolve against the git tree (`HeadTree`), which is untouched, so they are unaffected; the removal is of the working
copy the model reads. The root-level files are covered by the `OPENCODE_DISABLE_*` switches; the live task 29.1 plants
a nested `AGENTS.md` that tries to steer the answer and checks it is ignored. `external_directory` is a per-command path heuristic, not confinement
(SPEC 8.3 [V]): the read-only bind of the sandbox stays the bound, as for every agent. Model identity: `provider/model`; run mode reports no served model (`model_unverified`), so the
configured model is the one the independence rule checks (A4). Cost: the sum of `step_finish.cost` is the call's
`cost_usd`; a reported 0 is a known cost (a free model); none is unknown (A6). Major: the pinned 1.x only
(`SUPPORTED_MAJORS["opencode"] == 1`, L4-OCG-001..005, pin-clis). A v2 binary fails the `binary` probe as
`unsupported_version`, which the pass classifies as a cause only a fix ends: the question escalates, it is not
deferred (`l4 doctor --fix` installs the pin). The paused `opencode-v2` change adds v2 to the delegate when it adds it
to the adapter; this amendment adds nothing v2-specific.
Rejected: keeping the enumerated `read_only` map (a tool a 1.x minor adds, a sub-agent `task` or a skill, would be
allowed by default); honouring a profile's `options.tools` (it can only widen the surface); `--agent plan` (a user-level agent definition the empty config home does not carry, and its
permissions are opencode's, not L4's).

**A3. The kiro-cli delegate (L4-DLG-017).** A harness agent `l4-delegate-<12 hex>` in a fresh `KIRO_HOME` in the
step's private directory that holds only `agents/l4-delegate-<hex>.json` and the judge's `settings/cli.json`
(`chat.disableInheritingDefaultResources`, `chat.agentEngine: v2`, `chat.enableAutoAgentUpgrade: false`,
`app.disableAutoupdates: true`):
```json
{"name": "l4-delegate-<hex>", "description": "L4 harness delegate: read-only file tools", "prompt": null,
 "mcpServers": {}, "tools": ["read", "glob", "grep"], "toolAliases": {}, "allowedTools": ["read", "glob", "grep"],
 "resources": [], "hooks": {}, "toolsSettings": {}, "includeMcpJson": false, "model": "<the profile's model>"}
```
argv `kiro-cli chat --no-interactive --v2 --agent l4-delegate-<hex> --model <M> --trust-all-tools --output-format
stream-json`, the prompt on stdin then EOF (a delegate prompt can pass `MAX_ARG_BYTES`; stdin carried 155,225 bytes
whole for the judge [V, R8]), cwd the detached worktree, no `--require-mcp-startup` (no server), no `KIRO_LOG_LEVEL`
(a trace log holds the prompt). `--trust-all-tools` is the headless trust path K3 verified for the implementer's agent
[V, 0 denials]; it trusts only the tools the agent has, here the three read tools. That agent ran without the `--v2`
flag, but on engine v2, the 2.x default (`--agent-engine` defaults to `v2`, kiro-judge R2 [V]): its stream's
`runStarted` names `engine: v2` beside `read`, `glob`, `shell` and `write` tool calls (2.28.0,
`tests/fixtures/recorded/kiro-cli/2.28.0/red-tools.stream.jsonl` [V]). What is not recorded is the explicit `--v2`
flag with a tooled agent, on 2.32.0, with the prompt on stdin [U] (task 29.2 records it). The `--v2` flag is
not load-bearing: the engine is pinned by `chat.agentEngine: v2` in the private `settings/cli.json` and by the
`runStarted` engine check below, and engine v2 is the 2.x default on which K3's tooled agent ran. If the flag
refuses or ignores tool calls, dropping it keeps the pin against Kiro CLI 3.0's default engine (open question 6).
**The specified fallback** if the live record shows that a tooled agent fails with the prompt on stdin: the prompt as
an argument (the argv of today's read-only mode), with a prompt over `MAX_ARG_BYTES` escalated, not deferred; it
takes effect as an amendment of L4-DLG-017's argv after the live record, not before. The run is no reply when it ran an
engine other than v2 (Kiro CLI 3.0 makes V3 the default [D, R22]), reported a `runError`, or holds a `tool_call` whose
tool is not `read`, `glob` or `grep` (the adapter keeps every tool name of a turn for this check; a call to a tool
the agent does not have voids the run and is a deferral source). The served model is the session file's `model_id` (L4-KJD-015's reading): a
pinned model the file contradicts (`model_mismatch`) is a configuration the person fixes, so the question escalates
with both ids (status `discarded`); it is not deferred. A profile on `auto`, or with no model, is routed: under
`independence: model` it is no independent delegate (A4) and DLG-001 fails; under `independence: profile` it serves,
and the served model is recorded. Cost: credits only (A6). Major: the pinned 2.x (`SUPPORTED_MAJORS["kiro-cli"] ==
2`); a 3.x binary is `unsupported_version` and escalates like opencode v2. The read tool can read any path the
sandbox shows; whether `toolsSettings` can confine it to the worktree on 2.32.0 is [U] (the live task records it),
and the bound is the sandbox's empty home and read-only worktree, plus the ledger's redaction of every string.
Rejected: the default agent with `--trust-tools=fs_read` (today's code: K3's leak of the user's servers, skills and
steering, and on the default agent 3 of 4 harness steps had trusted calls denied [V]); the judge's tool-less agent
(cannot read the repository).

**A4. One model identity for every adapter (L4-DLG-018).** Before any comparison (an asker's model with a delegate
profile's, configured or served) both ids are lowercased and cut after their last `/`, then stripped, in this order,
of a `[…]` context marker, a trailing `@…` (a Vertex date), a trailing `:…` (`:free`, `:thinking`, a Bedrock `:0`),
a leading `(<region>.)?anthropic.` (Bedrock) and a trailing `-v\d+(:\d+)?` (a Bedrock version), then of a date
suffix; a `.` between digits is folded to `-`. `MODEL_FAMILIES` (`src/l4/availability/vendor.py`) already knows the
Bedrock prefix shape `^(?:(?:[a-z]+\.)?anthropic\.)?claude-`: the cut reuses that shape, not a second pattern.
`openrouter/anthropic/claude-opus-5-5`, `openrouter/anthropic/claude-opus-5.5:thinking`, `claude-opus-5.5`,
`google-vertex-anthropic/claude-opus-5-5@20261001`, `amazon-bedrock/us.anthropic.claude-opus-5-5-20261001-v1:0` and
`claude-opus-5-5-20261001` are one model, and `openrouter/deepseek/deepseek-v4.1-flash:free` is
`opencode-go/deepseek-v4.1-flash`. The free-tier test of A5 reads the id as configured, before this cut (a `:free`
suffix is what it looks for), so a `:free` copy of an Opus model is both restricted to technical and harness
questions and, against an Opus judge, vetoed by independence. Two ids are one mind when they are equal, or when one is
the other followed by `-` and more (`gpt-6.1` and `gpt-6.1-sol`; `claude-opus-5` and `claude-opus-5-5` too). The
prefix rule can veto two models that differ [I]: a false veto escalates a question to a person, and DLG-001 names the
pair at configuration time, while a false pass lets a model overturn its own family's dispute and, under `merge:
auto`, merge it. An id whose name after the last `/` is `auto` (kiro `auto`, `openrouter/auto`) is no known model:
under `independence: model` it vetoes, as a profile with no model does today (fail safe, D3). This holds for an
asker too: a kiro-cli implementer or judge profile with the literal `model: auto` has no resolvable model, so it
vetoes every delegate profile (the same as no model; the runbook says so, task 28). opencode reports no
served model, so its configured model stands; kiro's served model is the session file's; Claude Code's and Codex's
are unchanged.
Rejected: the verifier's routed-set rule for kiro `auto` (L4-VER-001's `different_model` branch: an asker's model
outside the account's Active ids passes): it suits a judge whose verdict a person still reads, not a delegate whose
verdict accept can merge; comparing vendors (the verifier's `different_vendor`): stricter than the owner's choice of
`independence: model` (owner decision 1).

**A5. A weak model answers only what a later step checks (L4-DLG-019).** The delegate's `verdict` answers overturn
the judge (and under `merge: auto` an accept merges), its `product` and `ambiguous` answers decide what the
specification leaves open, and nothing after them checks the answer against the person's intent. A `technical`
answer is implemented test-first and verified against the criteria; a `harness` accept reaches the judge labelled
`delegate_override` (L4-DLG-010), which judges the criterion with that label. So:
- a per-profile key `profiles.<p>.options.delegate_kinds` (a list of question kinds) narrows what a delegate profile
  answers; absent, it answers every kind of `delegate.kinds`. It is a profile option because it is a property of the
  model, and because the reference block of §3.2 is held equal to `DelegateCfg` (no new `delegate:` key is needed);
- a free-tier model (an OpenCode Zen id `opencode/…`, or an id ending `:free`) answers only `technical` and `harness`,
  whatever its options say: its options can narrow that, never widen it [I: that every Zen id is free-tier; a paid Zen
  model is restricted too, a false restriction that only escalates];
- the restriction is a factory veto per question (step `kinds`, reason `kinds: <p> answers <kinds> questions`), so a
  fallback never reaches a weak profile for a verdict when the strong ones are cooling; a question no profile of the
  chain may answer escalates `no delegate profile answers <kind> questions`, distinct from `no independent delegate`;
- DLG-001 fails when `delegate.kinds` names a kind no profile of the chain may answer (remove it from
  `delegate.kinds`, so those questions stay a person's without an escalation line), when `options.delegate_kinds`
  names an unknown kind, or when it names `verdict`, `product` or `ambiguous` for a free-tier model.
- DLG-002 warns whenever a profile of the chain would answer verdict questions, naming each such profile, and flags
  an `opencode` profile among them (a cheap paid model such as `opencode-go/…`, or a local custom provider, is not
  free-tier by id, so nothing above restricts it, yet it can overturn a judge's dispute and, under `merge: auto`,
  merge it): the person sees which models hold that power.
The recommended chain: the strong profiles first, the free one last and restricted:
```yaml
profiles:
  delegate-opus: {adapter: claude-code, model: claude-opus-5-5, auth: subscription, vendor: anthropic}
  delegate-sol: {adapter: codex, model: gpt-6.1-sol, auth: subscription, vendor: openai,
                 options: {reasoning_effort: high}}
  delegate-free: {adapter: opencode, model: opencode/<a free Zen model>, vendor: <its maker>}
roles:
  delegate: [delegate-opus, delegate-sol, delegate-free]
```
The free profile then answers technical and harness questions while the strong ones cool or are out of quota (a
cooling chain otherwise defers, D9), and never a verdict. A team with no paid delegate may run `[delegate-free]` alone
with `delegate.kinds: [technical, harness]`: the other questions stay a person's.
Rejected: the free profile first for technical questions (a wrong technical answer costs an implementation round, the
implementer's cost and a CI run, more than one strong call, and Zen's free tier throttles unpredictably); chain order
alone (a fallback reaches the free profile for a verdict exactly when the strong ones cool); `delegate.profile_kinds`
under the `delegate:` section (one more key the §3.2 reference block and `DelegateCfg` must carry, for what is a
property of a profile); an override that lets a free model answer verdicts (the merge risk dominates; open question
1).

**A6. Cost, turns and time (L4-DLG-020).** Claude Code keeps `--max-budget-usd`; the other three have no budget flag,
so the cap is checked before the call against what is left (D10). A call's cost is unknown when Codex reports tokens
with no `budgets.price_table` entry, when Kiro reports credits (never dollars, L4-KJD-004), and when opencode reports
no `step_finish.cost`; an unknown cost counts at `max_cost_usd_per_answer` against the delegate's own limits (D10). A
reported 0 is known: a free model's calls cost nothing against the caps, and the attempt, answer and question limits
still bound them. A Kiro call writes `budget.cost{credits, credits_source: "kiro.stream", profile, role: delegate,
question}` (never `usd`), `delegate.result` carries `credits`, and the `Delegate:` line reads `Q-003 answered by the
delegate (claude-sonnet-4.5 via kiro-cli, 1.84 credits; counted at $3.00)`. `delegate.timeout` bounds every adapter;
Claude Code keeps `--max-turns 40`, opencode's `doom_loop` stays denied, and kiro-cli has no turn limit (the timeout
bounds it).
Rejected: a price per Kiro credit (the price depends on the plan and changes; a made-up dollar figure would mislead
the plan's cost); a separate credits cap (open question 2).

### B. Discoverability

**B1. A hint where the agent is stuck (L4-DLG-021).** One pure function, `delegate_hint(settings, unit, view, phase,
open_kinds)`, gives the sentence or None. It gives it only when `delegate.enabled` is false on the base branch (the
section as `delegate_settings` reads it at `origin/<base>`, as everything about the delegate) **and that base
configuration can be read**: `delegate_settings` falls back to the defaults when it cannot (`settings.py`), and a
default `enabled: false` there says nothing about the base, so no hint is given. The unit is in
`awaiting_human` (or `fixing` with a waiting fix unit), at least one open question is of a kind in `delegate.kinds`,
and the unit would be in scope were the delegate on (`in_scope` with a copy of the section whose `enabled` is true:
`in_scope` returns False for a section that is off). The sentence, one line:
`Hint: the delegate can answer these questions in CI: set delegate.enabled: true and roles.delegate in
.l4/config.yaml on <base> (docs/runbook.md 7.1, the delegate).`
Where: after the `Next:` line of `l4 questions` (the list), `l4 status --unit`, and `l4 yolo status` (for the current
unit, L4-YOLO-053's branch); as `delegate_hint` in their `--json` (and so in the MCP tools that wrap them); and as the
last line of the sticky note's "Waiting for you" section, which the run writes. The `l4:needs-person` section never
has it: that note exists only while the delegate is on. With the default `scope: yolo` a unit in no plan gets no hint
(it would not be in scope); the skill and the runbook say that `scope: all` reaches it.
Rejected: a hint in the `l4 status` table (one line per unit; the REASON column is the planner's); a hint in every
`Next:` line (the `Next:` line names the one step that moves the unit; the delegate is a configuration choice of a
person, not that step).

**B2. The configuration and the doctor name it (L4-DLG-022).** `l4 init` writes, as comments placed in the YAML it
dumps (the dump stays `yaml.safe_dump`; a comment cannot be a dict key), a block that turns the delegate on when it
is uncommented in place. The earlier text put the profile and role lines after the whole file, so uncommenting it
gave a second `profiles:` and `roles:` key (PyYAML keeps the last and drops `codex` and `claude-code`) and put the
delegate's profile and role under the `delegate:` key. The block now follows two rules: a YAML line is a single-`#`
comment at the indentation of the mapping it belongs to, placed inside that mapping; a prose line begins `##`.
Removing the leading `# ` of the single-`#` lines then gives valid YAML with no duplicate key. The init profiles
(`codex` for the implementer, `claude-code` for the judge) carry no model, so the block pins one on each and uses a
third model for the delegate (`independence: model` needs a model on every implementer and judge profile and a
delegate that differs from them):
```yaml
## The delegate (off): a strong model answers the units' questions in CI, read-only, and escalates what it
## cannot check (docs/runbook.md 7.1). To turn it on, on the base branch, remove the leading "# " of the lines
## that begin with a single "#" (the models are pinned because independence: model compares them):
profiles:
  codex:
    adapter: codex
    ...
#     model: gpt-6.1-sol
  claude-code:
    adapter: claude-code
    ...
#     model: claude-opus-5-5
#   delegate-sonnet: {adapter: claude-code, model: claude-sonnet-5, auth: subscription, vendor: anthropic}
roles:
  implementer: [codex]
  judges: [claude-code]
#   delegate: [delegate-sonnet]
...
# delegate:
#   enabled: true
#   scope: yolo                  # yolo: the current unit of a plan; all: also units in no plan
```
Uncommented in place, the file loads with one `delegate:`, `profiles:` and `roles:` key, `delegate-sonnet` is the
delegate, and doctor DLG-001 passes (the pins differ: `gpt-6.1-sol`, `claude-opus-5-5`, `claude-sonnet-5`; SCN-DLG-75
asserts it). DLG-001's pass line while the delegate is off becomes `the delegate is off (delegate.enabled is false;
docs/runbook.md 7.1 tells how to turn it on)`, so `l4 doctor` names the option without a new check.
Rejected: a doctor INFO check for "questions waited long with the delegate off" (doctor reads configuration and
the environment; this would read plans and ledgers in every CI job, needs a threshold nobody configured, and the
person waiting on a plan reads `l4 yolo status`, which has B1's hint; the docs test of review F13 also holds the
change to doctor checks that exist).

**B3. The entry points.** The skill index (`SKILL.md`, one bullet under "Where to look next"), `references/adopt.md`
(an opt-in step with the B2 block and the free-model rule), `references/control-loop.md` (the `awaiting_human` row:
"you answer, or the delegate does (`delegate.enabled` on base)", within its 900-word cap: the sentence on
`clarifier.auto_accept_kinds` is shortened by as many words), `references/operate.md` (how to turn it on; the hint),
`references/plan.md` (enable it for a plan: a person's configuration change), `docs/quickstart.md` (one paragraph
under "Conditional extras"), the README (one line). Each is pinned by a docs test.

### C. The rules of 0.4.21

**C1. A delegate's reject sets the check as 0.4.21 reads it (L4-DLG-023).** The composed reject is judged with the
parser the fix unit uses (`verdicts.WHEN_THEN`, which takes the last `WHEN … THEN …`), so what the check accepts is
what the fix pins. A reject MUST end with a `WHEN … THEN …` sentence when it rejects a hold other than a scope,
coverage or judge-view hold (D7, unchanged) and when it rejects a judge-only finding that cites no criterion (the
question writer's first paragraph names no `(criterion …)`, the test `bare_gap_reject` uses): without one, 0.4.21
converts nothing and consumes nothing. A reject of a finding that cites a criterion, or of a criterion, MAY have one;
without it the fix is checked against the criterion as written (L4-VER-059). A delegate reject is never bare:
`check_text` refuses an empty text and the composed form is `reject <text>`, so `bare_gap_reject` cannot fire for it.
The prompt `delegate@3` says that the sentence states the behaviour the fix must give, is the last sentence (quoting
the criterion's scenario before it is fine), and is never the judge's suggested fix, which describes the code as it
is now. A reply that breaks the rule is discarded and the question escalated (`the reply was discarded: a reject of
this finding needs a sentence WHEN ... THEN ...: it cites no criterion`). There is no repair call (D7).
Rejected: one repair call with the discard reason (it doubles the cost of the most expensive calls, a second answer
argued out of a discard is the injection risk D5 bounds, and the discard reason tells the person what to write; open
question 3); a silent rewrite that appends the criterion's scenario (the harness would author the person's check).

**C2. The verifier's new questions (L4-DLG-024).** A cap-only criterion question (L4-VER-055; the criterion's outcome
reason starts with `aggregate.CAP_ONLY`) is answerable: the delegate can read the candidate test, which is what the
question asks. Its `accept` MUST cite, by `path:line`, the file of the candidate test that the reason names (a `test:`
id shows only that the test exists and passed); the prompt holds the reason and the candidate's id. The harness
finds that file as the path before `::` of the candidate's pytest-style id (`verdict.json["tests"]` maps an id to a
status string, so the report has no file field); when the id has no such path, the question
escalates (the check cannot be made, and a call would only be discarded). A split-evidence
question (L4-VER-058) is answerable: the prompt holds the criterion's `judge_split` record (the parts, the files not
shown), and the delegate reads those files itself. A judge-view hold (L4-VER-043, L4-VER-044) may be accepted after
the delegate cites at least one of the files the hold names (a hold that names no file, `LEGACY_LENGTH_HOLD` in
`verdicts.py`, the 0.4.14 length text, escalates without a delegate call); its `reject` is discarded, because a reject of a
judge-view hold escalates the unit `judge_view_rejected`, which only a person can resolve.
Rejected: keeping the delegate off all three (they are the questions where reading the files settles the answer, and
the reason the owner asked for a delegate).

**C3. A CI failure and a test-support change stay a person's (L4-DLG-025, L4-DLG-014 new text).**
- `ci_not_fixed` is an escalation (phase `escalated`, exit 13): out of the pass and of the planner action `delegate` by
  construction (they take `awaiting_human` and `fixing` only). Stated and pinned, nothing to build.
- A blocked fix chore's technical question: `question.raised` gains `chore: true` (written by `_raise_blocked` with
  `chore_unit`); a raise from before this amendment counts as a chore's when it is a fix unit's technical question
  whose context holds the harness's fix-task note (`chore_question_note`'s first sentence). The delegate may answer it,
  but an effective answer that names (by the `names_path` rule of L4-IMP-015: a path as written, so "the conftest"
  alone names none) a path `tdd.test_globs` or `tdd.test_support_globs` matches escalates with `a fix
  task cannot change <path>: a person commits that change on the unit branch, then answers` (status `escalated`):
  the fix step would put the file back, and the answer would wait for a commit nobody made. The prompt says so.
- `delegate.unfreeze` never covers a test-support file (a path `tdd.test_support_globs` matches: `conftest.py`,
  fixtures, mocks) and covers nothing in a fix task. With `unfreeze: true` an accepted suggestion that would unfreeze
  `tests/conftest.py` escalates with `the answer would unfreeze tests/conftest.py of task 3.1, a test-support file: a
  person's change (delegate.unfreeze opens test files only)`. A support file changes the result of every test that
  loads it, and 0.4.21 already treats it as a person's change. A person's accepted suggestion is unchanged
  (L4-IMP-015). This changes owner decision 3 and SCN-DLG-55, whose example was `tests/conftest.py`; SCN-DLG-55 now
  uses `tests/test_store.py` and SCN-DLG-88 pins the new refusal (open question 4). SCN-DLG-106 pins the fix-task
  half ("nothing in a fix task"). Owner informed 2026-10-21; reverting is one line (the support-file test in the
  unfreeze check).
Rejected: escalating every chore question without a call (most chore questions are about production code, which the
delegate can settle); trusting the prompt alone (an instruction is not a rule, D1).

**C4. An answer is progress (L4-DLG-026).** The order the merge gave stays and is specified: 0.4.21's rule first
(drop the plan's request when a continuation was dispatched or already queued, or when no step started), then
`after_delegate` adds one request when the pass answered (or deferred for the soft deadline, D6, which is no
attempt), unless a
continuation was dispatched or queued: the continuation run reads the answer too. So an answer in a run in which no
step started still starts one run. That is right: the next run reads the answer and moves the unit
(`awaiting_human → implementing`), which is progress the dropped request was not; if that run again has no time for a
step, it answers nothing and requests nothing, so the chain ends. A soft-deadline deferral does NOT count as a
delegate attempt (it made no call; consistent with L4-IMP-070, which does not charge a run that started no step),
so time-budget pressure never escalates a question as `delegate attempts used`; the runs it starts are bounded
like every chained run (the plan's run limit and the idle-run rule, L4-YOLO-012, L4-YOLO-014), and a run with time
left makes the call (SCN-DLG-105). Outside a plan nothing else bounds that chain, so a question deferred on the soft
deadline three times in a row (the latest three `delegate.result` records of its raise) stops requesting runs: the
delegate then waits for the next scheduled or pushed run (orchestrator decision; L4-DLG-013, L4-DLG-026, SCN-DLG-113). One request per run however many units answered.
Rejected: no request when no step started (an answer would wait for the cron or a push, the idle time the delegate
exists to remove); a second request beside a dispatched continuation (two runs race for the unit's lease).

### P. Polish from the first live test

**P1. Neutral names (L4-DLG-027).** `verification.md`'s `## Human verdicts` becomes `## Answers to verdict questions`;
each line keeps `by <label>` (a person, an agent, the delegate). Two tests assert the old heading
(`tests/unit/verifier/test_ladder_depth.py`, `test_verification_md_actor.py`).
**P2. The PR body names the delegate.** `_pr_body(at_head=True)` re-renders the body at the hand-off (the force line is
added there); it gains `- Answered by the delegate: Q-003 (claude-opus-5-5 via claude-code), Q-007 (gpt-6.1-sol via
codex); its verdict accepts are labelled delegate_override in verification.md.` when the ledger has delegate answers.
The sticky note keeps its `Answered by the delegate` section after the hand-off.
**P3. A decision is final for its raise.** `due.FINAL` is the intended rule and is now stated: an answered, escalated
or discarded question is never asked again for its current raise, also after a harness upgrade that would have kept
the reply (the first live test: a reply discarded for citing `questions.md`, before `delegate@2` named the files that
are no evidence). An escalation hands the question to a person, who may be working on it; taking it back would flip
`l4:needs-person` under them. A person's answer ends it; a new `question.raised` for the id is a new question.
Rejected: re-asking discarded questions after an upgrade (the label flips without a person's act); a command that
hands a question back to the delegate (not asked for; a person's answer is the way out, open question 5).
**P4. `--harness-ref` takes a tag or a branch.** A sha passes the name check (`_REF` matches hex), so it is the
refusal after `git ls-remote`, `--harness-ref '<v>' names no tag or branch in <remote>` (`init/action.py`), that gains
`; a commit sha goes to --harness-commit (40 hex characters)` when the value is 7 to 40 hex characters, and
`references/adopt.md` and the runbook's upgrade lines say it. No requirement id: it is an adoption text (pinned by a
docs test).

Out of scope, said so: "the judge never sees answered questions" (a separate change); OpenCode v2 (`opencode-v2`,
paused); Kiro CLI 3 (the judge's open item, kiro-judge design §7).

### Risks of the amendment

- **Two read-only modes are new and unrecorded.** opencode's deny-by-default map with `"*": "deny"` first is the shape
  of the judge mode's map (its Zen variant `{"*": "deny", "read": "ask", "bash": "ask"}` ran live [V]); the read
  tools allowed after it are [I]. The kiro harness agent with read tools under `--trust-all-tools` follows K3's
  implementer agent [V, on engine v2], but with the `--v2` flag, tools and stdin together it is [U] (A3). Whether
  either CLI writes into its working directory (`.opencode/`, `.kiro/`), which the read-only bind refuses, is [U].
  The live task (29) runs both.
- **Instruction files steer a model.** opencode loads nested instruction files whatever the project-config switch
  says; A2 removes them from the detached checkout, and the live task 29.1 plants one to check [U until run].
  `.env` files stay unreadable because opencode's `*.env` rules are kept after the allow.
- **The read tools see what the sandbox shows,** the CLI's own login store included (each CLI needs its own). A
  credential is not in the worktree, so a `checked` quote cannot resolve to it, and every string the ledger gets is
  redacted; a value that is not token-shaped could still reach `reason` [I]. Same bound as Claude Code's `Read` today.
- **A5's free-tier test is an id pattern.** A free model with another id is not restricted unless its
  `options.delegate_kinds` narrows it; doctor DLG-002 warns and names which delegate profiles answer verdict
  questions, an `opencode` one flagged as a model L4 cannot rate.
- **The prefix rule of A4 vetoes neighbours** (`claude-opus-5` against `claude-opus-5-5`): visible in DLG-001, and
  fail safe.

### Open questions (recommended answer first)

1. May a person let a free-tier model answer verdict questions (`options.delegate_kinds: [verdict]`)? **No in 0.4.22:**
   a verdict accept can merge under `merge: auto`; revisit with live data on a named free model.
2. A credits cap for Kiro delegates? **Not now:** an unpriced call counts at `max_cost_usd_per_answer`, which bounds
   it; add `delegate.max_credits_per_unit` if the live data shows the dollar caps bite too early.
3. One repair call for a reply discarded on a format rule only (WHEN … THEN …, the decision word)? **No:** D7 stands
   until the live data shows discards that a repair would have kept without a new claim.
4. `delegate.unfreeze: true` no longer opens a test-support file (C3, contrary to owner decision 3's example). **Taken**
   (0.4.21's "test-support files are a person's change"): owner informed 2026-10-21, revert is one line.
5. A command that hands an escalated question back to the delegate? **Not in 0.4.22.**
6. If kiro-cli 2.x with the `--v2` flag does not run a tooled agent headless (A3, [U]), drop the flag for the delegate?
   **Resolved:** engine v2 is the kiro-cli 2.x default and K3's tooled agent ran on engine v2
   (`tests/fixtures/recorded/kiro-cli/2.28.0/red-tools.stream.jsonl` [V]); the engine is pinned by
   `chat.agentEngine: v2` in the private settings and by the `runStarted` engine check, so the argv `--v2` flag is
   not load-bearing, and dropping it still refuses another engine (Kiro CLI 3.0's V3 default gives no reply rather
   than a V3 answer; the major gate refuses 3.x anyway). If stdin prompts fail with tools in the live test, the
   specified fallback is the prompt as an argument, with prompts over `MAX_ARG_BYTES` escalated (A3, L4-DLG-017).
