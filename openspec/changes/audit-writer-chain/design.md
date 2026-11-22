## Context

Read at 0.4.59 (62188257). Each fact below was read in the code for this design.

**Step 4a's scope**

- `_audit_step(vc, run, criteria, base_sha)` (`src/l4/verifier/ladder.py:1165`): `not_run` when `vc.audit_writer` is
  None (`roles.verifier_agent is empty`) or the ratio is 0, then when `_no_python(vc, base_sha, head)`
  (`:1155-1162`) with the note `audit sampling writes pytest tests only; changed code is not python`.
- `_no_python` reads `changed_unit_files(git, base, head, cfg, unit_rel)` (`src/l4/evidence/collect.py:136`): (path,
  kind) of the added or changed files that are not exempt; `file_kind` (`src/l4/evidence/scope.py:227`) gives `test` for
  a `tdd.test_globs` match and `code` or `root` for the rest; it does not look at `tdd.test_support_globs`. Its docstring
  says "tests included: a Python project's unit that only adds a test still audits".
- `run.report` (`ladder.py:540`) is step 3's unit-gate JUnit report (set at `:783`).
- `audit.head_sources` (`src/l4/verifier/audit.py:183-200`) shows the writer the changed `.py` files that match neither
  `tdd.test_globs` nor `tdd.test_support_globs` and are not under `/.l4/`: the Python code the audit can test.
- `audit.red_test_directory(wb, base_sha, head)` (`:115-132`) counts the changed `.py` files of `tdd.test_globs` that
  define a test at head, by folder, and returns the most common; `run_audit` sets `unconfirmed = folder is None` and only
  then runs `confirm_collected` (`:248-269`), a `--collect-only` run of the audit file.
- `evidence.testsran.file_of_test(test_id, candidates, tree)` (`src/l4/evidence/testsran.py:46`) maps a JUnit id to a
  file among `candidates`, the exact path first, else the one tree file that ends with the module path.

**The writer**

- `writer_for(stem)` (`ladder.py:2148-2168`) returns `open_writer`, called once per step (`vc.audit_writer()` in step
  4a's body, `:1190`; `vc.ui_writer()` in step 5's, `:1318`): `select_judge(services.factory, cfg, services.ref.id,
  implementers, role="verifier_agent")`, an `AgentJudge` with `workbench_request_factory(..., stem=f"{stem}-r{round}")`.
- `select_judge(factory, cfg, unit, implementers, *, role, skip)` (`src/l4/verifier/selection.py:173-205`) walks the
  role's chain with the independence constraint and a `skip` collection it reads at every selection, checks
  `probe_vetoes`, and raises `WaitingCapacity` (`no independent verifier`) when nothing is left.
- `testwriter.request_test` (`src/l4/verifier/testwriter.py:612-649`) makes one `complete_structured` call and maps
  `limit`, `timeout` and `error` to a `WriterReply` of that status, `schema_invalid` to `invalid`.
- `AgentJudge.complete_structured` (`src/l4/llm/agent_judge.py:167-205`) returns `error` with `length_stop` for a run
  that stopped at the output limit, and `error` for any status it does not map otherwise, `permission_blocked`
  included. A transient server error is retried inside the run first (`availability.transient`).
- `run_audit` (`audit.py:219`), `_retry_collected` (`:523`) and `_lint_accepted` (`:621`): `limit` with a run raises
  `RoleLimit(reply.run)`, `limit` or `error` raises `RoleUnavailable("verifier_agent", reply.detail or ...)`
  (`:260/262`, `:548/550`, `:652/654`); `timeout` and `invalid` (after one retry with the reason) become a record and a
  minor finding.
- `generate_ui_test` (`src/l4/verifier/generate.py:225`): `limit` with a run raises `RoleLimit` (`:264-265`), `timeout`,
  `error` and `limit` without a run return `writer_failed` (`:268-269`), which leaves the criterion's UI hold.
- The step-9 judges (`_ask_judges`, `ladder.py:1907`; `next_judge`, `:2125-2146`): an `error` emits
  `availability.judge_error{role: "judges", profile, detail}` and moves on with the profile added to the round's `skip`
  (no cool-down); a limit calls `factory.on_limit(current, run)`, checks `probe_vetoes` and moves on; `WaitingCapacity`
  when nothing is left becomes `no independent verifier` and the unit parks.
- `Factory.on_limit(selected, run)` (`src/l4/agents/factory.py:353`) records the cool-down, selects again with the
  selection's own constraints, and raises `WaitingCapacity` when nothing is left.

## Goals / Non-Goals

**Goals:** step 4a runs for Python code only, and never because a changed Python file is a test of another language's
unit; the audit file goes where the test command collects it; a writer call that one profile cannot answer is asked of
the next profile of the chain in the same run, and a unit waits only when no profile is left.

**Non-Goals:** remembering a failed profile past the round (D7); moving an `invalid` or `timeout` reply; audit tests in
another language; the judges.

## Decisions

### D1. What counts as Python code to audit (L4-VER-089)

`_audit_scope_note(vc, base_sha, head, report) -> str` replaces `_no_python`; an empty string means "audit". With
`files = changed_unit_files(...)` as today, its `.py` paths are split in two:

- `python_code` = the `.py` paths that match neither `tdd.test_globs` nor `tdd.test_support_globs` (the predicate of
  `head_sources`, so these are the files the writer is shown);
- `python_tests` = the other `.py` paths (tests and test support).

Then, in order:

1. no file at all: audit (today: a unit that changed nothing outside the exempt paths is not judged non-Python);
2. no `.py` path: `not_run` with `audit sampling writes pytest tests only; changed code is not python` (today's rule
   and note, word for word);
3. `python_code` not empty: audit (Python code changed);
4. only `python_tests`: audit when `report` is None (the rule of 0.4.59: nothing that audited before stops for want of
   a report), or when an id of `report.tests` maps to a Python file of the tree (`file_of_test(id, <the tree's .py
   files>)`: the unit gate runs Python tests, so a pytest audit file can be collected); else `not_run` with the note of
   2 followed by ` (the changed Python files are tests or test support: <python_tests, _list>)`.

So SCN-VER-58 (`engine.ts`, `engine.test.ts`) keeps its note word for word; a Python project's unit that changes only
tests or test support audits as before, since its unit gate's report holds Python tests; and the consumer's TypeScript
unit with a changed Python browser test is `not_run`, since its Node unit gate's report holds none. The rule of 4 asks
whether the unit gate runs any Python test, not whether it runs the unit's own changed ones: a unit that changed only a
`conftest.py` has no test of its own in the report and must still audit as in 0.4.59. The note starts with the text of
0.4.59, so a reader that looks for it keeps finding it. `CODE_SUFFIXES` and the files of another language are not
needed: a unit with Python code audits whatever else it changed, as before.

Considered: `is_python_gate(gates.test.command)` (`src/l4/gates/coverage.py:37`), which COV-001 uses. Rejected as the
deciding rule: `make test` and `npm run test` can run pytest, and COV-001 falls back to a project interpreter for that
reason; the report of step 3 shows what the gate ran, which no reading of the command can.

### D2. Where the audit test goes (L4-VER-090)

`red_test_directory(wb, base_sha, head, report)` counts a changed `.py` test file only when an id of `report.tests` maps
to it (`file_of_test(id, candidates, tree)`, the candidates being the files it counts today). With no such file, or no
report, it returns None and `run_audit` runs `confirm_collected` before it trusts the folder `audit_directory` gives, as
it does today when no folder is found. `run_audit` gains `report: TestReport | None` and `_audit_step` passes
`run.report`. This keeps the docstring's promise ("the head report proves the test command collects it") true. It costs
one `--collect-only` gate run in the rounds where the report shows none of the unit's Python test files, and none
otherwise.

### D3. The writer chain (L4-VER-091)

`WriterChain` (new, `src/l4/verifier/writer_chain.py`) is an `LLMBackend`. `writer_for(stem)` returns a function that
builds one per step: `WriterChain(select, open_backend, factory, skip, failures, emit, step)`, where `select()` is
`select_judge(services.factory, cfg, unit, implementers, role="verifier_agent", skip=skip)`, `open_backend(selected)`
builds the `AgentJudge` of today for that profile, and `skip` and `failures` are created once per round in the hook,
beside the judges' `skip` (`ladder.py:2093`), and shared by steps 4a and 5.

`complete_structured(...)` asks the current profile and looks at the result:

- `ok`, `schema_invalid`, `timeout`: returned as is. The callers keep their handling (an `invalid` reply is retried
  once with its reason and is then a record and a minor finding; a timeout is a record and a minor finding in 4a and
  `writer_failed` in 5). Neither parks a unit today, and a timeout is not handed to the next profile, which would spend
  its own time on the same prompt in the same job (as L4-VER-075 says for the judges).
- `error` (any: `length_stop`, a run of status `permission_blocked`, an adapter error that its retries did not cure):
  the call is discarded. The chain records `availability.judge_error{role: "verifier_agent", profile, kind, detail,
  step}` (`kind`: `length` when `length_stop`, `permission` when the run's status is `permission_blocked`, else
  `error`; `detail` the result's first line, redacted, at most 300 characters; `step`: `4a` or `5`), records the
  discarded call's cost (`budget.cost{usd|credits, profile: <its profile>, role: "audit"|"ui_tests"}`, as
  `AgentJudge._record_cost` records a call that gives no result), adds the profile to `skip`, appends `<profile>:
  <kind>: <detail cut at 120>` to `failures`, and selects again with `select()`. A new profile gets the same system
  text and messages.
- `limit` with a run: `factory.on_limit(current, run)` cools the profile (`Factory.cool_limited`, L4-AVL-003) and
  selects the next one with the same constraints (the independence rule and the `skip` set it reads), then
  `probe_vetoes`, as `next_judge` does after a limit (`ladder.py:2131-2136`); the limit is recorded in `failures` too.
- When `select()` or `on_limit` raises `WaitingCapacity` (no profile is left), the chain returns the last result with
  its `detail` replaced by `no profile of roles.verifier_agent could answer: <failures joined by "; ">`. The callers
  then do what they do today with that result: step 4a raises `RoleUnavailable` (an error) or `RoleLimit` (a limit) and
  the unit waits for capacity; step 5 records `writer_failed` with that text (an error) or raises `RoleLimit`.

The three raise sites of `audit.py` need no change of their own: they already raise with `reply.detail`. The selection
of a later profile records `availability.selected` as every selection does, so the ledger shows the walk.

Considered: classify `error` into deterministic (length, permission) and other, and move only on the first. Rejected:
the judges move on every `error` (`_ask_judges`: "a judge that cannot answer (a rejected tool call, an upstream 5xx)
must not strand the unit"), a transient error has already been retried inside the run, and one rule is easier to read
in the ledger. The `kind` key keeps the cause visible.

### D4. Step 5 walks the chain too

Step 5's writer is the same role and is opened by the same `writer_for`, so it gets the chain with no code of its own.
An `error` there moves to the next profile instead of ending as `writer_failed` at once; only when no profile is left is
it `writer_failed`, with the summary as its reason. This changes step 5 for the better in the same way (a UI hold that
the next profile could have closed is no longer raised), and the alternative, a chain for 4a only, would need a second
selection path for the same role.

### D5. How each requirement fails safe

- L4-VER-089 stops step 4a only for a unit whose changed Python files are all tests or test support and whose unit
  gate's report holds no Python test. There a pytest audit file is never collected by the unit gate: each audit test
  ends rejected (`the test command ... does not collect the audit test file`, a minor finding,
  `audit._judge_without_result`, `audit.py:402-421`), so it can neither become evidence nor fail at head and hold its
  criterion; the only other outcome, a hold for "no result" when the audit run leaves no report, says nothing about the
  code. No check that could hold a criterion on its merits is lost (inferred from those code paths; no run measured
  it). Every unit that audits at 0.4.59 and whose unit gate runs Python tests, or that has no report, still audits.
- L4-VER-090 removes no check: it adds a collect-only run where a folder was trusted without proof. An audit file that
  would have gone to a folder the command does not run (and been rejected) now goes where it is collected and judged,
  which can only add evidence or a hold.
- L4-VER-091: every profile the chain selects passes the independence rule of the round (`select_judge`'s constraint,
  the implementer profiles of the unit) and `probe_vetoes`, as the first one does. A profile that failed is skipped for
  the rest of the round and never asked again in it. The chain never accepts an answer that the callers would not accept
  from the first profile: what an audit or a UI test needs to count (it passes at head, fails against the zero values or
  at the base, the lint) is judged as before. When no profile is left, 4a parks as today, so a round never goes on
  without its audit because of the writer.
- No requirement touches a person-only action or what an answer can unfreeze.

### D6. No warning for a tool-less judge profile

Every call of the role is tool-less (`PermissionPolicy("judge")`); the role loads only judge adapters (L4-CFG-006). A
warning for a tool-less judge profile would warn about every valid profile. The refusal in the evidence was a model that
tried a tool in a tool-less call; the chain now moves past it, and `availability.judge_error{kind: "permission"}` names
it in the ledger. The runbook (7.4) says what to do with a profile that keeps failing this way.

### D7. How long a failure is remembered

The skip lasts the round, as the judges' does (L4-VER-075). The next round, in the same run or the next, starts at the
first usable profile again and pays one failed call if that profile fails again. A usage limit is remembered longer,
through its cool-down. Considered: a cool-down of a new kind for a profile that refused a tool call. Not proposed: the
availability cache is per runner and may be new in every CI job, a length stop depends on the prompt, and a second
kind of cool-down for one role is more machinery than one call per round is worth. A chain whose every profile fails
the same way in every round parks the unit each time with the summary, which names what to fix. It is an open question
for the owner's delegate whether that should be remembered.

### D8. Upgrade

A unit parked on 0.4.59 by a writer error resumes on 0.4.60 at its next run and walks the chain. A ledger written by
0.4.59 folds as before: `availability.judge_error` was already an event the fold ignores, and the new keys are only
read by people. A round reused by a resumed run keeps its stored step 4a record; a fresh round decides the scope again.

## Risks / Trade-offs

- A unit whose only changed Python files are tests, in a repository whose unit gate also runs Python tests (a Node
  project with a Python suite in its unit gate), still audits as in 0.4.59, even when its own code is not Python. D1
  keeps that on purpose: the report shows that a pytest audit file can run there, so the audit can still decide.
- A unit of another language that also changed Python code (a script) still audits, as before; its audit file is now
  confirmed collected first when the report does not show its Python tests (D2).
- A chain of several failing profiles costs one call each per round before the unit parks.
