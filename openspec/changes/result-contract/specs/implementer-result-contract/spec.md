## Purpose

An implementer step that did its work does not lose the attempt because its result object misses a field, names the
phase as its status or has too long a text. The prompt of a prompt-contract adapter asks only for what the agent alone
knows, the harness repairs the rest of the object with fixed rules and records each repair, and the gates and the
verifier judge the work as before. An attempt fails for its result only when there is no result object, or when the
result is `blocked` with no question.

## ADDED Requirements

### Requirement: L4-IMP-019 The output section of a prompt-contract step asks for status and summary first and ends with the path
For a step of a prompt-contract adapter (opencode, kiro-cli, command), the `# Output` section of the prompt SHALL come
from the versioned template `output.md`, and `prompt.rendered.template_version` SHALL end with `+output@<version>`.
The template is pinned by the template lock.

The section SHALL:
- start with one sentence that asks for one JSON object with `status` and `summary`, where `status` is `done` when the
  agent did the step, or `blocked` when it needs an answer from a person, and then `questions` holds at least one
  question;
- name `criteria_ids`, `suppressions` and `notes_for_verifier` as the fields to add when the agent has them;
- show the agent's schema `l4/implementer-file-result@1`: the canonical schema without the properties `phase`,
  `task_ids`, `files_changed` and `tests_added`, with `required: ["status", "summary"]`, derived from the canonical
  schema in code;
- end with the line ``Write your result object to `<path>`.``, where the path is the result alias
  `.l4-result/result.json`.

The section MUST NOT name `phase`, `task_ids`, `files_changed` or `tests_added`, and MUST NOT say that the final
message is the result. The implementer request of a prompt-contract adapter SHALL carry no result schema, so that the
adapter hands over the object as written and the harness validates it (L4-IMP-020).

For a native adapter (codex, claude-code) the `# Output` section, the request's schema `l4/implementer-result@1` and
the template version MUST NOT change. The `result values:` line of the phase section stays for every adapter
(L4-IMP-004).

#### Scenario: SCN-IMP-186 (+) A prompt-contract prompt asks for status and summary first and ends with the path
- **GIVEN** an opencode profile and the red step of task 1.1
- **WHEN** the prompt is rendered
- **THEN** the `# Output` section starts with the sentence about `status` and `summary`, holds the agent's schema with `"required":["status","summary"]` and without the keys `phase`, `task_ids`, `files_changed` and `tests_added`, and its last line is ``Write your result object to `.l4-result/result.json`.``
- **AND** the section does not contain `final message`, `prompt.rendered.template_version` ends with `+output@1`, and the request's `result_schema` is `None`

#### Scenario: SCN-IMP-187 (+) A native prompt and its schema do not change
- **GIVEN** a codex profile and a claude-code profile, and the red step of task 1.1
- **WHEN** the prompts are rendered and the requests are built
- **THEN** each `# Output` section is the `(schema enforced)` section of today, `template_version` has no `+output`, and each request carries the canonical schema, whose strict copy for codex equals the recorded `implementer-result.strict.schema.json`

### Requirement: L4-IMP-020 The harness normalizes the result object before it validates it, and records each repair
After each implementer step, and before the guards and the gates, the harness SHALL find the result object and
normalize it. It SHALL take, in this order: the result that the adapter delivered (a native result, or a
prompt-contract file's JSON object as written); the object that a native adapter's schema refused (`rejected`); the
last JSON object in the agent's own final text that has a top-level `status` or `summary` key. It MUST NOT take an
object from a file in the worktree or from any other path. An object taken from the final text is itself recorded as the repair `{field: "result", fix: "set", from:
"final_message"}`, so `result.normalized` shows every step whose agent wrote no usable result file.

The normalization SHALL apply these rules, with the limits, enums and pattern read from `l4/implementer-result@1`:
- `null` means absent; the alias `notes` becomes `notes_for_verifier` and `suppressions_list` becomes `suppressions`
  when the real key is absent, else the alias is dropped;
- `phase` is the step's phase and `task_ids` is `[<task key>]`;
- `files_changed` is the step's changed paths from git, without the run's ledger;
- `tests_added` is empty: the new tests of a red step are the JUnit diff that the harness computes and records in
  `task.red_ok.tests`, and the red verdict MUST NOT read the agent's list;
- a `questions` item that is not an object with a string `title`, a string `context` and an allowed `kind` is
  dropped; an item's `options` or `blocking_tasks` that is not a list of strings is removed; after three items the
  rest are dropped;
- a `status` that is an allowed value in another letter case or with surrounding space becomes that value; a missing
  status, a status that is not a string, a phase name or any other text becomes `blocked` when at least one question
  is left, else `done`;
- a `summary` that is not a non-empty string becomes the agent's final message (its text after the last tool call,
  without the object's own JSON text, trimmed), else `notes_for_verifier`, else `(no summary: the agent wrote none)`;
- a `notes_for_verifier` that is not a string is dropped; a `criteria_ids` entry that is not a string with the
  pattern, a `suppressions` item without a string `file`, an integer `line`, a string `rule` and a string `reason`,
  and a `tdd_exemption` or `lesson_proposals` of the wrong shape are dropped;
- a `summary`, `notes_for_verifier` or suppression `reason` longer than its limit keeps its start and ends with
  `[cut by L4: <n> characters removed]`, all within the limit.

The normalization MUST NOT add or invent a question, change the text of a question, change a present allowed status,
add a suppression, a criterion id or a TDD exemption, or read or change a file of the worktree. The harness SHALL then
validate the object against `l4/implementer-result@1`; the guards, the gates and the verifier SHALL judge the step as
before.

When the normalization changed a value that the agent gave, or filled a required field that the agent left out, the
harness SHALL record one `result.normalized{task, phase, attempt, source, fixes}` for the step, where `source` is
`result` or `final_message` and each fix is `{field, fix, from?, to?, was?, count?, length?}` with `fix` one of `set`,
`replaced`, `renamed`, `dropped`, `cut`. The event MUST NOT hold text of the agent: `was` only names a phase, `to` an
allowed status, and `from` a source or a key. Setting a field that the agent left out and that the prompt does not ask
for, or replacing a valid `files_changed` or `tests_added` list, is not a fix. The progress log SHALL print
`task <k> <phase> attempt <n>: L4 repaired the result (<fix>; <fix>)`.

#### Scenario: SCN-IMP-188 (+) A missing summary and a phase-name status are repaired
- **GIVEN** a red step of task 1.1 whose result file holds `{"status": "red", "phase": "red", "task_ids": ["1.1"], "criteria_ids": [...], "tests_added": [...], "files_changed": [...]}` (the observed `magnitude/qwen3.6-35b-a3b` object), and a red step whose object has `"status": "failed"` and no `summary` while its final message says what it did (the observed `nemotron-3.5-lightning-free` object)
- **WHEN** each step's object is normalized
- **THEN** the first gets `status` `done` and records `{field: "status", fix: "set", to: "done", was: "red"}`, the second gets the final message as `summary`, keeps `status` `failed`, and records `{field: "summary", fix: "set", from: "final_message"}`
- **AND** both steps go on to the red checks, and the progress log has `task 1.1 red attempt 1: L4 repaired the result (status set to done, was red)`

#### Scenario: SCN-IMP-189 (+) The harness owns the phase, the task, the changed files and the new tests
- **GIVEN** a red step of task 1.1 whose object has `files_changed` as a list of objects and `tests_added` with dotted ids (the observed `big-pickle` red 2 object), and a codex red step whose valid result says `"phase": "green"`
- **WHEN** the objects are normalized and the red checks run
- **THEN** `files_changed` is the step's changed paths from git, `tests_added` is empty, the codex object's `phase` is `red`, and the fixes are `{field: "files_changed", fix: "replaced"}` and `{field: "phase", fix: "replaced"}`
- **AND** `classify_red` gets no agent list, and `task.red_ok.tests` lists the tests that the JUnit diff found

#### Scenario: SCN-IMP-190 (+) An over-long text is cut with a marker, and an alias key moves
- **GIVEN** an object with `notes_for_verifier` of 2417 characters, a suppression whose `reason` has 350 characters, and an object with a `notes` key and no `notes_for_verifier`
- **WHEN** they are normalized
- **THEN** `notes_for_verifier` has 2000 characters and ends with `[cut by L4: <n> characters removed]`, the reason has 300 characters and ends the same way, the suppression is kept, the `notes` text is in `notes_for_verifier`, and the fixes record `cut` with `length: 2417`, `cut` with `length: 350` and `{field: "notes_for_verifier", fix: "renamed", from: "notes"}`

#### Scenario: SCN-IMP-191 (+) An object that the agent printed is taken when there is no file
- **GIVEN** an opencode step that wrote no result file, whose final text ends with a fenced JSON object `{"status": "done", "summary": "added two tests"}` after a code sample `{"a": 1}`
- **WHEN** the result is found
- **THEN** the object with `status` is taken, `result.normalized` has `source: "final_message"`, and the step goes on to the checks

#### Scenario: SCN-IMP-192 (−) Normalization never adds a question, never changes blocked, never adds a suppression
- **GIVEN** in turn: a `blocked` result with one question without `kind` and one well-formed question; a `done` result with a well-formed question; a result with a suppression without `line`
- **WHEN** they are normalized
- **THEN** the first keeps `blocked` and only the well-formed question, with `{field: "questions", fix: "dropped", count: 1}`; the second stays `done` and raises no question; the third has no suppression, so that the verifier reports the `# noqa` of the diff as undeclared
- **AND** no rule adds a question, a criterion id or a suppression, and no file of the worktree changes

#### Scenario: SCN-IMP-193 (+) The observed failing objects are accepted and still face the checks
- **GIVEN** the eight invalid objects of `docs/live` (`big-pickle` red 1 to 3, `nemotron-3.5-lightning-free` red 1 and 3, `magnitude/qwen3.6-35b-a3b` red 1 to 3) with their final messages, and six objects built from the six result failures of `deepseek-v4.1-flash` on a public consumer repository
- **WHEN** each is normalized
- **THEN** each normalized object passes `l4/implementer-result@1`, and its fixes are the ones listed in the fixture for it
- **AND** in a bench red step that wrote no new test, the normalized object still ends the attempt with `no tests added`

#### Scenario: SCN-IMP-194 (−) A file in the worktree is never a result
- **GIVEN** a prompt-contract step that wrote a valid object to `agent-tmp/result.json` in the worktree, no result file, and a final message with no JSON object
- **WHEN** the result is found
- **THEN** no object is found, the attempt fails (L4-IMP-021), and nothing of `agent-tmp` is committed

### Requirement: L4-IMP-021 An attempt fails for its result only when there is no result object
An implementer attempt SHALL fail for its result only when no result object is found (L4-IMP-020), with the reason
`the agent's result is invalid: no result was delivered (<what was missing>)`. It SHALL count against
`implementer.max_task_attempts`, and the retry prompt SHALL carry the reason and the `result values:` line
(L4-IMP-008).

A normalized `blocked` result SHALL reach a person as today: its well-formed questions are raised, and a `blocked`
result left with no question (none given, or all dropped as malformed) SHALL raise the one ambiguous question made
from its summary (`loop.py`, "Task <k> is blocked"), with ` (<n> malformed questions were dropped)` appended to that
question's context when the normalization dropped any. It is not a failed attempt: an agent that says it cannot go on
needs a person, not another attempt. A normalized
object that still fails validation is a harness defect and SHALL fail the attempt with the validation error, as
today.

#### Scenario: SCN-IMP-195 (−) No result object fails the attempt
- **GIVEN** an opencode red step that wrote no result file and whose final message is prose with no JSON object (the observed wrong-path steps of `magnitude/qwen3.6-35b-a3b`), and a bench step with no object and no final text
- **WHEN** the attempt ends
- **THEN** each attempt fails with `the agent's result is invalid: no result was delivered (no result file and no result object in the final message)`, `task.attempt_failed` records it, and the next prompt has the reason and the `result values:` line

#### Scenario: SCN-IMP-196 (+) A blocked result with no question still reaches a person
- **GIVEN** a red step whose result is `{"status": "blocked", "summary": "the tests need a database URL"}`, and a red step whose result is `"status": "BLOCKED"` with one question that has no `title`
- **WHEN** the attempts end
- **THEN** neither attempt fails; each raises one ambiguous question titled `Task <k> is blocked` whose context is the summary, the second with ` (1 malformed questions were dropped)` in its context, and the unit goes to `awaiting_human` as today

#### Scenario: SCN-IMP-197 (+) A missing status with a question raises the question; more than three keep the first three
- **GIVEN** a green step whose result has no `status` and one well-formed question, and a red step whose `blocked` result has five well-formed questions
- **WHEN** the results are normalized
- **THEN** the first becomes `blocked` with `{field: "status", fix: "set", to: "blocked"}` and its question is raised; the second raises its first three questions and records `{field: "questions", fix: "cut", count: 2}`

### Requirement: L4-IMP-022 An optional repair call rebuilds a result object that the step did not deliver
This requirement is a second wave: it is built only after the live check of this change shows a step with no result
object. When it is built, `implementer.result_repair_attempts` SHALL default to `0`.

When `implementer.result_repair_attempts` is at least 1, no result object was found (L4-IMP-020), the run finished
(no limit and no error other than a result problem), and the profile's adapter is one of `claude-code`, `codex` and
`opencode`, the harness SHALL make one repair call before the attempt fails: on the same profile, in a new session,
with no tools and an empty working directory, with the prompt of the locked template `repair.md`. The prompt SHALL
hold, in data blocks, the agent's final message (redacted, defused, its last 4000 characters), the result file's text
when there was one (its first 4000 characters), the problem and the `result values:` line, and SHALL ask for the
object of `l4/implementer-file-result@1` only.

The harness SHALL keep only `status` (`done`, `failed` or `partial`), `summary` and `notes_for_verifier` of the reply.
A reply with `status` `blocked` or with any question MUST be discarded, and the attempt fails as without the call. The
repair MUST NOT add a question, a suppression or a criterion id. A kept reply SHALL be normalized with `source:
"repair"` and SHALL go to the checks. The harness SHALL record `result.repair{task, phase, attempt, outcome, reason?}`
with `outcome` one of `accepted`, `discarded`, `failed`, and the call's cost as `budget.cost`. A limit in the call
SHALL end the step as an agent limit does (L4-AVL-006). A kiro-cli or command step MUST NOT get a repair call.

#### Scenario: SCN-IMP-198 (+) The repair call rebuilds an object from the final message
- **GIVEN** `implementer.result_repair_attempts: 1`, an opencode red step that wrote no file and whose final message says what it did in prose
- **WHEN** the attempt ends
- **THEN** one tool-less call on the same profile returns `{"status": "done", "summary": "…"}`, `result.repair{outcome: "accepted"}` and `result.normalized{source: "repair"}` are recorded, and the step goes on to the red checks

#### Scenario: SCN-IMP-199 (−) A repair that adds a question is discarded, and some steps get no repair
- **GIVEN** `implementer.result_repair_attempts: 1`, in turn: a repair reply with `"status": "blocked"` and one question; a kiro-cli step with no result object; the default `implementer.result_repair_attempts: 0`
- **WHEN** the attempts end
- **THEN** the first records `result.repair{outcome: "discarded"}` and the attempt fails with `no result was delivered`; the second and the third make no repair call and fail the same way
