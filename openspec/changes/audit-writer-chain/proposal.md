## Why

A TypeScript web consumer runs its browser tests with Python (Playwright under pytest, in `e2e/`); its unit gate is a
Node command. Twice, a unit of it reached verification step 4a, audit sampling, only because a changed file was a Python
browser test. Step 4a writes pytest tests, so the audit writer was asked for a pytest test of a TypeScript criterion.

- In the first unit (a person's commit had fixed a Python browser test) the first `roles.verifier_agent` profile, an
  opencode profile, tried a tool call in the tool-less writer call; opencode's permission rules refused it, the audit
  raised `RoleUnavailable` and the unit parked for capacity (exit 12) with a retry 30 minutes later. The retry chose another
  profile only because the first one failed its hello that time; that profile wrote a pytest audit test, which was
  rejected because the Node unit gate does not collect it.
- In the second unit the first profile's reply stopped at its 32,000-token output limit. The unit parked again; the
  retry chose the same profile, which answered that time.

Together the two waits cost about an hour and a half. In neither case was another profile of the chain tried in the
same run, while step 9's judges move to the next independent judge on the same kinds of failure (L4-VER-015,
L4-VER-075) and the plan review's judges do too (L4-YOLO-096).

Verified at 0.4.59 (62188257):

- `ladder._no_python` (`src/l4/verifier/ladder.py:1155-1162`) is `bool(files) and not any(p.endswith(".py") for p, _
  in files)` over `changed_unit_files`: a changed Python test file makes a TypeScript unit a Python unit.
- `audit.red_test_directory` (`src/l4/verifier/audit.py:115-132`) picks the folder with the most changed `.py` test
  files and trusts it without a check (its docstring says the head report proves the test command collects it, but no
  report is read), so `run_audit` skips `confirm_collected` (`:263-269`); in the consumer the folder was `e2e/`.
- `run_audit` raises `RoleUnavailable("verifier_agent", ...)` on a writer reply of status `error` at three places
  (`audit.py:262`, `:550`, `:654`) and `RoleLimit` on a limit (`:260`, `:548`, `:652`). A length stop
  (`StructuredResult.length_stop`, `src/l4/llm/agent_judge.py:201-204`) and a refused tool call (`RunResult.status
  "permission_blocked"`, `src/l4/agents/opencode.py:422-425`, mapped to `error` by `AgentJudge.complete_structured`) are
  both `error`.
- The writer is opened once per step by `writer_for` (`ladder.py:2148-2168`): `select_judge(..., role="verifier_agent")`
  with no `skip`, so nothing moves to the next profile, and a retry selects the same first usable profile again.
- Step 5's writer (`src/l4/verifier/generate.py:264-269`) raises `RoleLimit` on a limit and records `writer_failed` on
  `error`; it does not park on an error, but it does not try the next profile either.
- Every writer call is tool-less by design (`workbench_request_factory`, `PermissionPolicy("judge")`,
  `agent_judge.py:237-245`; the audit module's docstring), and `roles.verifier_agent` is a judge role that loads only
  judge adapters (L4-CFG-006). A tool-less judge profile is the kind of profile the role needs; the refusal came from a
  model that tried a tool anyway.

## What Changes

- Step 4a audits a unit only when it changed Python code: a changed `.py` file that is not a test file
  (`tdd.test_globs`), not a test-support file (`tdd.test_support_globs`) and not an exempt path. A unit that changed no
  source file outside the tests still audits when a Python test file it changed is in step 3's unit-gate report (a
  Python project's unit that only adds tests); without a report it keeps the rule of 0.4.59. Any other unit's step 4a
  is `not_run`, and its note names the Python files that are only tests or test support.
- The audit test goes into the folder of the unit's own Python tests only when step 3's unit-gate report holds a test
  of a changed Python test file there; otherwise the audit confirms that the test command collects the file
  (`confirm_collected`), as it does when no folder is found.
- A call of the `verifier_agent` role (the audit writer of step 4a, the UI test writer of step 5) whose reply is `error`
  (a length stop, a refused tool call, any other adapter error) is asked again of the next usable profile of
  `roles.verifier_agent` that is independent of the implementers, in the same run, and the failing profile is skipped
  for the rest of the round. A usage limit cools the profile and moves on the same way. The ledger records each discard
  (`availability.judge_error` with `role: verifier_agent`), and the cost of a discarded call is recorded. Only when no
  profile is left does step 4a wait for capacity, with a reason that names each profile and why; step 5 records
  `writer_failed` with that text, as it does today.
- No doctor or configuration warning for a tool-less judge profile in `roles.verifier_agent`: every writer call is
  tool-less, so such a profile is the right kind.

Non-goals: a memory of a failed profile across rounds or runs (D7); an `invalid` reply or a `timeout`, which do not
park today and keep their handling; the judges of step 9; audit tests in another language than Python.

## Capabilities

### New Capabilities

- `audit-writer-chain`: L4-VER-089 (step 4a audits Python code, not the Python tests of another language's unit),
  L4-VER-090 (the audit test goes next to the unit's tests only when the report shows them), L4-VER-091 (a
  verifier-agent call a profile cannot answer goes to the next profile of the chain).

### Modified Capabilities

- L4-VER-002 (step 4a's non-Python rule, §10.2 (3)) and L4-VER-015 (a row for the verifier agent).

## Impact

- `src/l4/verifier/ladder.py`: `_no_python` becomes `_audit_scope_note` (it takes step 3's report), `_audit_step`
  passes `run.report` to `run_audit`, `writer_for` returns a chain and the round keeps one skip set and one failure
  list for the role.
- `src/l4/verifier/writer_chain.py` (new): `WriterChain`, an `LLMBackend` that walks the role's chain.
- `src/l4/verifier/audit.py`: `red_test_directory` takes the report; `run_audit` takes `report`; the three raises use
  the chain's summary.
- `src/l4/verifier/generate.py`: no change in behaviour beyond the chain it is given (its `writer_failed` text is the
  chain's summary when no profile is left).
- `docs/SPEC.md` (L4-VER-089..091, SCN-VER-356..369, change-table row 142, the L4-VER-002 and L4-VER-015 amendments),
  `CHANGELOG.md`, `docs/runbook.md` (7.4).
- Ledger: `availability.judge_error{role: "verifier_agent", profile, kind, detail, step}` (the existing event type, a
  new role value and two new keys), `availability.fallback` from `Factory.on_limit`, `budget.cost` for a discarded call.
  No new event type, no configuration key.
