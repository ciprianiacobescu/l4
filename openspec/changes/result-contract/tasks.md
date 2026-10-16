Every task follows these rules:
- Write the named tests first and see them fail, then write the code.
- Run only the named test files and their folder, for example
  `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer` (pytest-cov is not installed: keep `--no-cov`).
  Then run `ruff check`, `ruff format --check` and `mypy` on the files that you changed.
- Never wait on a process with `while pgrep -f …`: it matches itself. Run commands in the foreground.
- Stage explicit paths only.
- Every event key, field, rule, reason, marker and line is in `design.md` (D1 to D11) and in the two spec files. Do not
  change one without the orchestrator.
- Name a consumer "a public consumer repository" and a test repository "a dummy repository". Model names and adapter
  names are fine.
- This change starts after `escalate-and-note` is merged into the branch. Do not edit its change folder.

The fixtures:
- the bench: `make_bench`, `result`, `red_step`, `green_step` and `blocked_step` (`tests/unit/implementer/conftest.py`).
  The fake adapter is native; `prompt_contract(bench)` of `tests/unit/implementer/test_result_retry.py:26-28` makes it
  a prompt-contract adapter.
- "no result object" in a bench test is `Step()` (no `structured`, no `final_text`). Do not use an invalid object for
  a result failure: the normalization repairs it.
- the recorded streams: `tests/fixtures/recorded/opencode/1.18.33/*.jsonl` (with `tool_use` events),
  `tests/fixtures/recorded/claude-code/2.1.288/red-ok.jsonl` (with `assistant` usage),
  `tests/fixtures/recorded/kiro-cli/2.28.0/hello.stream.jsonl` (with `contextUsagePercentage`),
  `tests/fixtures/recorded/codex/0.160.0/*.jsonl`.

## 0. Contract (orchestrator, before wave 1)

- [ ] 0.1 Contracts with no behaviour:
  - `RunResult.last_message: str | None = None` and `RunResult.result_problem: Literal["missing", "not_json",
    "not_object", "invalid"] | None = None`; `Usage.context_peak_tokens: int | None = None` and
    `Usage.context_peak_percent: float | None = None` (`agents/base.py`);
  - the fake adapter's `Step` gains `last_message`, `rejected` and `result_problem`, passed to its `RunResult`
    (`agents/fake.py`);
  - `FILE_RESULT_SCHEMA` in `implementer/result.py`: a deep copy of `RESULT_SCHEMA` with `$id`
    `l4/implementer-file-result@1`, without the properties `phase`, `task_ids`, `files_changed` and `tests_added`,
    and `required: ["status", "summary"]`;
  - the new module `implementer/normalize.py` with `StepFacts(phase, task, changed_files, last_message)`, `Fix`
    (`field`, `fix`, `from_`, `to`, `was`, `count`, `length`, and `as_event() -> dict` that leaves out what is
    `None` and writes `from_` as `from`), `Found(obj, source, text)` (`text`: the JSON text when the object came from
    the final text), `Normalized(obj, fixes)`, the constants `CUT_MARKER = "[cut by L4: {n} characters removed]"`,
    `NO_SUMMARY = "(no summary: the agent wrote none)"`, `SCAN_CHARS = 200_000`, and the functions
    `last_result_object(text) -> Found | None`, `find_result(run) -> Found | None` and `normalize(found, facts) ->
    Normalized`, which raise `NotImplementedError`.

  Tests: `FILE_RESULT_SCHEMA` has `required == ["status", "summary"]` and none of the four properties, and
  `RESULT_SCHEMA` is unchanged (`tests/unit/implementer/test_result.py` and `tests/unit/agents/test_codex.py` stay
  green); the new fields default to `None`; `Fix.as_event()` writes `from`. [L4-IMP-019] [L4-IMP-020] [L4-FAC-010]

## 1. Wave 1: pure parts (six agents, disjoint files)

### Agent A: `implementer/normalize.py`

- [ ] 1.1 `last_result_object(text)` and `find_result(run)` (design D3):
  - `last_result_object`: scan the last `SCAN_CHARS` characters from the start; at each `{` try
    `json.JSONDecoder().raw_decode`; keep a decoded object that has a top-level `status` or `summary` key and go on
    after its end; else go on at the next character. Return the last kept one with its JSON text.
  - `find_result`: `run.structured` when `run.status == "ok"` (source `result`); `run.rejected` when
    `run.result_problem == "invalid"` (source `result`); else `last_result_object(run.final_text)` (source
    `final_message`); else `None`. A run with a status other than `ok` and no `result_problem` is not a caller's
    case: return `None`.
  - Test first, in the new file `tests/unit/implementer/test_normalize_find.py`: SCN-IMP-191 at function level (a
    code sample `{"a": 1}` before the fenced object; the object with `status` wins); a nested question object is not
    taken alone; text with no object gives `None`; a 300 000-character text is scanned only at its end; the order of
    the three sources.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_normalize_find.py`.
  [L4-IMP-020] [SCN-IMP-191]
- [ ] 1.2 `normalize(found, facts)`: the rules 1 to 13 of design D4, in that order, with the limits, enums and pattern
  read from `RESULT_SCHEMA`, and the fixes of D4 and D6. The summary from the final message takes out `found.text`
  when `found.source == "final_message"`, then trims. Needs 1.1.
  - Test first, in the new file `tests/unit/implementer/test_normalize.py`, one test per rule: SCN-IMP-188, 189, 190
    and 197 at function level; SCN-IMP-192 at function level (the dropped question, the kept `done` with a question,
    the dropped suppression); the cut keeps the text within the limit with the marker and `length`; `"BLOCKED"` with
    no question stays `blocked`; an unknown status with no question becomes `done`; the event dicts hold no agent
    text (no `summary`, `notes` or question text in any fix). A property test over a few hundred random broken objects
    (random keys removed, random types, long strings, extra keys): `parse_result(normalize(...).obj)` never raises,
    the questions are a prefix-preserving subset of the well-formed input questions, the suppressions and the
    criterion ids are subsets of the input's, and a valid input `blocked` stays `blocked`.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_normalize.py`.
  [L4-IMP-020] [SCN-IMP-188, SCN-IMP-189, SCN-IMP-190, SCN-IMP-192, SCN-IMP-197]
- [ ] 1.3 The observed objects. Build `tests/fixtures/results/observed.json`: for each step, the object as the agent
  wrote it (from the write tool's input in the stream), the text after the last tool call, the phase and task, and the
  expected fixes. The eight `docs/live` steps (the stream is `<base>.jsonl`, the prompt `<base>.prompt.md`):
  - `docs/live/artifacts/job-5465/l4-out/agent/r-20261004T1653Z-6780/1.1-red-1`, `-2`, `-3` (`opencode/big-pickle`);
  - `docs/live/artifacts/free-impl-nemotron-lightning-shelf/l4-out/agent/r-20261006T1943Z-0b38/1.1-red-1` and `-3`;
  - `docs/live/m113/a-job-5963-l4-out/agent/r-20261007T0601Z-17c1/1.1-red-1` and `-2`;
  - `docs/live/magnitude/agent/1.1-red-3` (its file was at a wrong path: keep the object for the normalization test
    and mark the step `delivered: false`).
  Add six objects built from the six result failures of `deepseek-v4.1-flash` on a public consumer repository
  (design section 1.6): three without `summary`, one with `notes_for_verifier` of 2417 characters, one with both, one
  with a suppression `reason` of 350 characters; their final message is a short prose summary and the entry says
  `"synthetic": true`. Needs 1.2.
  - Test first, in the new file `tests/unit/implementer/test_normalize_observed.py`: SCN-IMP-193 at function level
    (each object fails `parse_result` before and passes after, with exactly its expected fixes).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_normalize_observed.py`.
  [L4-IMP-020] [SCN-IMP-193]

### Agent B: `implementer/prompt.py`, `implementer/templates/output.md`, `templatelock.py`, `templates.lock.json`

- [ ] 1.4 The `# Output` section of design D1: the new template `output.md` (`version: 1`, the text of D1 with
  `{schema}` and `{path}`); `render_prompt` uses it when `ctx.result_path` is set, with `{schema}` the compact,
  key-sorted JSON of `FILE_RESULT_SCHEMA`, and appends `+output@1` to `template_version`; the native branch stays
  byte for byte. `IMPLEMENTER_TEMPLATES` gains `output`; write the lock with `.venv/bin/python -m l4.templatelock
  --write`.
  - Test first, in the new file `tests/unit/implementer/test_prompt_output.py`: SCN-IMP-186 at render level (the
    first sentence, the schema keys, the last line, no `final message`, the version); SCN-IMP-187 at render level (the
    native section equals today's f-string text for red, green and single, and the version has no `+output`). Change
    `tests/unit/implementer/test_prompt.py::test_a_prompt_contract_prompt_carries_the_result_schema` to the file
    schema. `tests/unit/test_template_lock.py`, `test_result_values_line.py` and the `template_version` tests of the
    native bench stay green.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer/test_prompt.py
    tests/unit/implementer/test_prompt_output.py tests/unit/implementer/test_result_values_line.py
    tests/unit/test_template_lock.py`.
  [L4-IMP-019] [SCN-IMP-186, SCN-IMP-187]

### Agent C: `agents/contract.py`, `agents/opencode.py`

- [ ] 1.5 `attach_file_result` sets `result_problem` (`missing`, `not_json`, `not_object`; with a schema, `invalid`
  and the object in `rejected`), with no change to a status or a detail. The opencode `_scan` keeps the text parts after
  the last `tool_use` as `last_message`, and the largest `tokens.input + tokens.cache.read + tokens.cache.write` of a
  `step_finish` as `Usage.context_peak_tokens`; `input_tokens` does not change.
  - Test first, in `tests/unit/agents/test_contract.py`: SCN-FAC-16 (the attach part, with no schema and with one);
    in `tests/contract/agents/test_opencode_replay.py`: SCN-FAC-17 and SCN-FAC-18 for a recorded opencode stream
    with `tool_use` (compute the expected values in the test from the stream), and
    `test_result_file_missing_or_invalid_is_an_error_not_ok` stays green.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/agents tests/contract/agents`.
  [L4-FAC-010] [L4-FAC-011] [SCN-FAC-16, SCN-FAC-17, SCN-FAC-18]

### Agent D: `agents/kiro_cli.py`

- [ ] 1.6 `stream_facts` gains `last_message` (the `agent_message_chunk` text after the last `tool_call` update,
  joined) and `context_peak_percent` (the largest `metadata.contextUsagePercentage`); `parse` puts them in
  `RunResult.last_message` and `Usage.context_peak_percent`, next to the credits it sets today. Copy
  `docs/live/artifacts/job-6211/l4-out/agent/r-20261008T0953Z-0474/2.1-red-1.jsonl` to
  `tests/fixtures/recorded/kiro-cli/2.28.0/red-tools.stream.jsonl` and name it in that folder's `README.txt`.
  - Test first, in `tests/unit/agents/test_kiro_cli.py`: SCN-FAC-17 (kiro part: `last_message` is shorter than
    `finalText` and equals the text after the last tool call); SCN-FAC-18 (kiro part, on `hello.stream.jsonl` and the
    new stream).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/agents/test_kiro_cli.py`.
  [L4-FAC-010] [L4-FAC-011] [SCN-FAC-17, SCN-FAC-18]

### Agent E: `agents/codex.py`, `agents/claude_code.py`

- [ ] 1.7 codex `_attach_result` sets `result_problem` (`missing`, `not_json`, `invalid`) and `last_message` (the last
  `agent_message`); claude-code `_attach_structured` sets `result_problem` (`missing`, `invalid`), `_fill` sets
  `last_message` (the `result`), and `parse` sets `Usage.context_peak_tokens` from the `assistant` events'
  `message.usage`. No status, detail or `rejected` changes.
  - Test first, in `tests/unit/agents/test_codex.py` and `tests/unit/agents/test_claude_code.py`: SCN-FAC-16 (the
    native part: the judge's `schema_invalid` path still gets `error` and `rejected`), SCN-FAC-17 (codex and claude
    parts), SCN-FAC-18 (claude part, on `red-ok.jsonl`), SCN-FAC-19 (codex has no peak).
    `tests/unit/llm/test_judge_adapters.py` stays green.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/agents tests/unit/llm`.
  [L4-FAC-010] [L4-FAC-011] [SCN-FAC-16, SCN-FAC-17, SCN-FAC-18, SCN-FAC-19]

### Agent F: `progress.py`

- [ ] 1.8 The lines of design D6 and D11: `result.normalized` (INFO) as `task <k> <phase> attempt <n>: L4 repaired the
  result (<fix>; <fix>)`, each fix rendered as `<field> <fix>` with its details (`set to done, was red`, `set from
  final_message`, `cut from 2417 characters`, `renamed from notes`, `dropped 2`, `cut 2`, `replaced`); the
  `agent.finished` line ends with `, context peak <n>k tokens` (one decimal) or `, context peak <p>%` when the event
  has the field.
  - Test first, in `tests/unit/obs/test_progress.py`: the line of SCN-IMP-188, the lines of SCN-FAC-18, and SCN-FAC-19
    (an older `agent.finished` prints as today).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/obs`.
  [L4-IMP-020] [L4-FAC-011] [SCN-IMP-188, SCN-FAC-18, SCN-FAC-19]

## 2. Wave 2: the step (one agent, after wave 1)

### Agent G: `implementer/tdd.py`

- [ ] 2.1 `agent_step` of design D2 and D7:
  - the request's `result_schema` is `RESULT_SCHEMA` for a native adapter and `None` for a prompt-contract adapter;
  - after the revert and the ledger restore: a limit raises `RoleLimit`; a status other than `ok` with no
    `result_problem` fails as today; else `find_result(run)`; `None` fails with the reason of D7 (the parenthesis
    from `run.detail` and the adapter's mode); else `normalize(found, StepFacts(role, task.key, changed, run.last_message))`
    where `changed` is `wb.changed_files()` without `wb.ledger_rel`, sorted; `result.normalized` is emitted when
    there is a fix; `parse_result` validates; a `blocked` result with no question fails with the reason of D7; the
    `result values:` line is the excerpt of both failures;
  - `_file_result` is removed.
  - Test first, in the new file `tests/unit/implementer/test_result_contract_step.py` (bench): SCN-IMP-186 (the
    request's schema is `None` with `prompt_contract(bench)`, the canonical one without); SCN-IMP-188 at bench level
    (the event and the checks run); SCN-IMP-191 (a `Step(final_text=…)` with the object in it); SCN-IMP-194;
    SCN-IMP-195 (with `prompt_contract(bench)` and natively); SCN-IMP-196 (no `question.raised`, `questions.md`
    unchanged); SCN-IMP-197 at bench level; a native `Step(status="error", result_problem="invalid",
    rejected={...})` is normalized and goes to the checks, and `agent.finished` keeps `error`.
  - Change the tests that pinned today's behaviour: `tests/unit/implementer/test_result_retry.py` (the wrong-status
    case now asserts `result.normalized` and an accepted step; the retry-prompt cases use `Step()`, and their asserted
    text changes from the `ALLOWED` string to `no result was delivered` and the `result values:` line),
    `tests/unit/implementer/test_tdd_red.py:150-153` (`{"status": "great"}` goes to the checks and fails with `no
    tests added`; `Step()` still fails with `no result was delivered`), and
    `tests/unit/implementer/test_tdd_prompt_contract.py` (the request schema). `test_result_alias_step.py` and
    `test_status_is_phase.py` stay green.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer`.
  [L4-IMP-019] [L4-IMP-020] [L4-IMP-021] [SCN-IMP-186, SCN-IMP-188, SCN-IMP-191, SCN-IMP-194, SCN-IMP-195,
  SCN-IMP-196, SCN-IMP-197]
- [ ] 2.2 `run_red` stops passing `tests_added=result.tests_added` to `classify_red`. Needs 2.1.
  - Test first, in `test_result_contract_step.py`: SCN-IMP-189 at bench level (an agent list with dotted ids and no
    new test file fails with `no tests added`; `task.red_ok.tests` of an accepted red step lists the JUnit diff).
    `tests/unit/implementer/test_tdd_red.py` stays green.
  - Verify: as 2.1.
  [L4-IMP-020] [SCN-IMP-189]
- [ ] 2.3 `agent.finished` records `context_peak_tokens` and `context_peak_percent` when `run.usage` has them. Needs
  0.1.
  - Test first, in `test_result_contract_step.py`: a fake step with a peak records it; one without records neither
    key.
  - Verify: as 2.1.
  [L4-FAC-011] [SCN-FAC-18, SCN-FAC-19]

## 3. Wave 3: the bench end to end (orchestrator, after wave 2)

- [ ] 3.1 One test in `test_result_contract_step.py` that runs `run_task` with `prompt_contract(bench)` over three
  attempts: a red object `{"status": "red", …}` that wrote the tests (accepted, red committed), a green step with no
  `summary` and a `notes` key (accepted, green committed, `task.done.notes` holds the notes), and in a second task a
  `blocked` with no question (a failed attempt, no question raised).
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer tests/unit/orchestrator`.
  [L4-IMP-020] [L4-IMP-021]

## 4. Integration with `escalate-and-note` (orchestrator, after wave 2)

- [ ] 4.1 Find every test that uses an invalid object as a failed attempt (`grep -rn "structured={\"status\": \"ok\"}"
  tests`, and any `structured=` with a status that is not allowed) and change it to `Step()` where the test needs a
  result failure. Run `tests/unit/implementer/test_escalation.py`, `tests/unit/orchestrator/test_escalation.py` and
  the rest of both folders.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/implementer tests/unit/orchestrator tests/unit/verifier`.
  [L4-IMP-021]

## 5. Docs (one agent, after wave 2)

- [ ] 5.1 Runbook:
  - 4.2: the rows `[l4] <unit> task <k> <phase> attempt <n>: L4 repaired the result (…)` (what it means: the agent's
    result object broke the contract, the harness repaired it, and the gates still judge the work) and the peak at the
    end of the `agent <phase> task <k> <status> (…)` line;
  - 4.5: `result.normalized{task, phase, attempt, source, fixes}` in the ledger;
  - 7.2: a NOTE under the table: a result with a missing summary, a wrong status, too long a text or a field that the
    harness derives no longer fails an attempt; an attempt fails for its result only when the agent delivered no
    result object, or reported `blocked` without a question;
  - 11: `implementer.result_repair_attempts` is in the config, and no code reads it.
  - Test first, in the new file `tests/unit/docs/test_result_contract_docs.py`: the needles of each item.
  - Verify: `.venv/bin/python -m pytest -q --no-cov tests/unit/docs`.
  [L4-IMP-020] [L4-IMP-021]
- [ ] 5.2 CHANGELOG, in the section `## 0.4.4 (unreleased)` (`escalate-and-note` creates it; create it above 0.4.3 if it
  is not there):
  - Changed: a prompt-contract step's `# Output` section asks for `status` and `summary` first and no longer for the
    fields the harness derives (template `output@1`); the harness repairs a result object before it validates it
    (`result.normalized`); an attempt fails for its result only with no result object or a `blocked` without a
    question, which no longer becomes a question made from the summary;
  - Added: `agent.finished` `context_peak_tokens` (opencode, claude-code) and `context_peak_percent` (kiro-cli).
  - Verify: `grep -n "result.normalized" CHANGELOG.md`.
  [L4-IMP-019] [L4-IMP-020] [L4-IMP-021] [L4-FAC-011]

## 6. `docs/SPEC.md` (orchestrator)

- [ ] 6.1 §7.4: add L4-IMP-019, L4-IMP-020 and L4-IMP-021 after L4-IMP-005, with the text of
  `specs/implementer-result-contract/spec.md`, and L4-IMP-022 marked "second wave, not built". Add SCN-IMP-186..199 to
  §23.7.
  - Verify: `.venv/bin/python scripts/check_spec.py docs/SPEC.md`.
  [L4-IMP-019] [L4-IMP-020] [L4-IMP-021] [L4-IMP-022]
- [ ] 6.2 Amend:
  - L4-IMP-004 (§7.3): a prompt-contract step's output contract comes from the template `output.md`, and
    `template_version` names it; a native step's does not change;
  - L4-IMP-005 (§7.4): "Every implementer step MUST end with a result object that, after the harness's normalization
    (L4-IMP-020), is valid against `l4/implementer-result@1`"; a sentence on `l4/implementer-file-result@1`; the
    delivery paragraph: "Missing/invalid → … repair prompts in the same session" becomes the rule of L4-IMP-021 with a
    pointer to L4-IMP-022; the delivery list gains kiro-cli and command;
  - L4-IMP-008 (§7.6): a `blocked` result with no question is a failed attempt (L4-IMP-021), not a stuck task; the
    sentence on the retry after `result invalid` becomes "the retry prompt MUST carry the reason of L4-IMP-021 and the
    `result values:` line" (after normalization no result failure carries a validation error or an allowed-values
    list);
  - SCN-IMP-08: "Given the agent ends with prose and delivers no result object … Then the attempt fails; with
    `implementer.result_repair_attempts: 1`, one repair call first (L4-IMP-022, second wave)";
  - SCN-QMD-10: "Then the first three questions are raised and `result.normalized` records `questions cut 2`".
  - Verify: as 6.1.
  [L4-IMP-019] [L4-IMP-020] [L4-IMP-021]
- [ ] 6.3 §8.1: the `RunResult` block gains `last_message` and `result_problem`, the `Usage` comment gains the two
  peak fields; add L4-FAC-010 and L4-FAC-011 after L4-FAC-002 and SCN-FAC-16..19 to §23.6.1. §8.3: the opencode row
  says that the final text joins every `text` part and `last_message` is the text after the last `tool_use`; the
  kiro-cli row says the same of `finalText`. §3.2: `result_repair_attempts: 1   # read by no code until L4-IMP-022`.
  - Verify: as 6.1.
  [L4-FAC-010] [L4-FAC-011]
- [ ] 6.4 §12.1 L4-STA-001: `result.normalized{task, phase, attempt, source, fixes}`, `agent.finished`
  `context_peak_tokens` and `context_peak_percent`, and, marked second wave, `result.repair{task, phase, attempt,
  outcome, reason?}`.
  - Verify: as 6.1.
  [L4-IMP-020] [L4-FAC-011]
- [ ] 6.5 §21: add row 25 `result-contract` with its requirement ranges (L4-IMP-019..022, L4-FAC-010..011) and the
  live check of task 7.3.
  - Verify: as 6.1.
  [L4-IMP-019]
- [ ] 6.6 `escalate-and-note` rows (after it is merged): in L4-IMP-017, "an invalid agent result" becomes "a result
  failure of L4-IMP-021"; in SCN-IMP-176, "attempt 2 returns a result without `summary`" becomes "attempt 2 delivers no
  result object". Do not edit `openspec/changes/escalate-and-note/`.
  - Verify: as 6.1.
  [L4-IMP-021]

## 7. Orchestrator: integration, review, live check

- [ ] 7.1 Merge the waves. Run the full suite with `--no-cov`, `ruff check`, `ruff format --check` and `mypy src`. Run
  `openspec validate result-contract --strict`.
- [ ] 7.2 Adversarial review on the session model, not by the implementers. Try to:
  - get a question into `questions.md` that the agent did not write (a summary, a final message, a malformed
    question, a repaired status);
  - turn a `blocked` result into `done`, or a `done` with questions into `blocked`;
  - make a red step pass with no new failing test, or a green step pass with a failing test, by a result object alone;
  - declare a suppression or cite a criterion that the agent's object did not hold;
  - take a result from the worktree, from `agent-tmp`, through a link, or from a second object in the final text;
  - put agent text (a summary, notes, a question, a secret) into `result.normalized` or its progress line;
  - change the native prompt, the native request schema or the strict codex schema;
  - break the judge path (`schema_invalid` with `rejected`) of codex, claude-code and opencode.
  Record the results in `docs/live/result-contract/review.md`.
- [ ] 7.3 Live check on a dummy repository (the public GitHub dummy or the GitLab dummy):
  1. a unit on a free OpenCode model that slipped in the data (`opencode/nemotron-3.5-lightning-free`, or
     `opencode-go/deepseek-v4.1-flash` with the `OPENCODE_API_KEY`): see the new `# Output` section and
     `+output@1` in the published prompt; count the `result.normalized` events and their fixes, and the failed
     attempts with "result is invalid";
  2. the same unit on codex or a Claude Code profile: the prompt and `template_version` are those of 0.4.3;
  3. `l4 eval --compare` for the template change (the template lock's advice).
  Keep the evidence under `docs/live/result-contract/`. Leave the dummies for the user to delete.

## 8. Second wave, optional: the repair call (L4-IMP-022)

Build this section only when the live check of 7.3, or later runs, show steps with no result object. The orchestrator
decides.

- [ ] 8.1 `implementer.result_repair_attempts` default `0` (`config/schema.py`); a new locked template
  `implementer/templates/repair.md` (`version: 1`) and the lock written again.
  - Test first: the default is 0; `tests/unit/test_template_lock.py` covers `implementer/repair`.
  [L4-IMP-022]
- [ ] 8.2 The new module `implementer/repair.py`: `repair_result(wb, run, request, role, task) -> Found | None` of
  design D9 and L4-IMP-022, through `AgentJudge.complete_structured` with a request factory like
  `workbench_request_factory`; it keeps `status`, `summary` and `notes_for_verifier`, discards a `blocked` or a
  question, records `result.repair` and `budget.cost`, and raises `RoleLimit` on a limit.
  - Test first, in the new file `tests/unit/implementer/test_repair.py`: SCN-IMP-198 and SCN-IMP-199 at function level
    with the fake judge.
  [L4-IMP-022] [SCN-IMP-198, SCN-IMP-199]
- [ ] 8.3 `agent_step` calls `repair_result` before the "no result was delivered" failure, when L4-IMP-022's
  conditions hold; the kept object is normalized with `source: "repair"`. The progress line of `result.repair`.
  - Test first, in `test_result_contract_step.py`: SCN-IMP-198 and SCN-IMP-199 at bench level.
  [L4-IMP-022] [SCN-IMP-198, SCN-IMP-199]
- [ ] 8.4 Docs: SPEC L4-IMP-022 no longer "not built", §3.2 default `0`, `result.repair` in L4-STA-001; runbook 4.2
  and 11; CHANGELOG.
  [L4-IMP-022]
