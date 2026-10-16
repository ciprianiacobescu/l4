# Result contract: ask for less, repair what is derivable, fail only when there is nothing to judge

Status: design draft, 2026-10-16. Harness at 0.4.3 plus the change `escalate-and-note` in progress (branch `fix-044`,
line numbers at b923058e; they can move while that change is merged). Markers: **[V]** verified (read in the code at
the cited line, or computed from the evidence data), **[I]** inferred (follows from the code, not run end to end),
**[G]** a chosen number with no measurement behind it.

## 0. The answer in nine lines

1. Ten result-only failures of the observed sixteen still fail with today's code. All ten wrote a JSON object; none
   held a question (section 1.6) [V].
2. The prompt-contract `# Output` section is rewritten as the versioned template `output.md`: `status` and `summary`
   first in one sentence, the optional agent fields, the agent's schema subset, the path last. Native adapters keep
   their prompt (D1).
3. For a prompt-contract adapter the implementer request carries no schema: the adapter hands over the object as
   written, and the harness validates. Native adapters keep their CLI schema (D2).
4. The harness finds the object (the result, else the last result-like JSON object in the agent's own text) and
   normalizes it with fixed rules, one rule for each constraint of the schema (D3, D4).
5. Each step that changed something records `result.normalized{task, phase, attempt, source, fixes}` (D6).
6. An attempt fails for its result only when no object is found, or when it is `blocked` with no well-formed question
   (D7).
7. Normalization never invents a question, never changes `blocked`, never adds a suppression or a criterion, and never
   touches the worktree. The gates and the verifier judge the work as before (D5).
8. The repair call is specified and deferred; a `check_result.py` self-check is not built (D9, D10).
9. `agent.finished` records the peak per-call context where the stream shows it (D11).

## 1. Current state

### 1.1 How a result travels today

| Adapter | Schema mode | Where the result is | Who validates | Final text |
|---|---|---|---|---|
| `opencode` | `prompt_contract` (`opencode.py:182-183`) [V] | `.l4-result/result.json`, a link to the step's private directory (`resultalias.py:1-13`, `tdd.py:615, 675`) [V] | `attach_file_result` against `req.result_schema` (`opencode.py:296-300`, `contract.py:31-54`) [V] | every `text` part joined (`opencode.py:252`) [V] |
| `kiro-cli` | `prompt_contract` (`kiro_cli.py:95-96`) [V] | the same | `attach_file_result` (`kiro_cli.py:187`) [V] | `runFinished.finalText`, which holds all of the run's text: on 6 recorded streams it was the whole text and not the text after the last tool call [V, `docs/live/artifacts/job-6211`, `job-6213`, `job-6217`, `job-6146`] |
| `command` | `prompt_contract` (`command.py:61-62`) [V] | `{result_path}`, the private file (`command.py:95-101`) [V] | `attach_file_result` (`command.py:118`) [V] | none: the command's output is not read [V] |
| `codex` | native: `--output-schema <strict copy>` and `-o <file>` (`codex.py:225, 233-236`) [V] | the `-o` file | `_attach_result` against the canonical schema; an invalid object goes to `rejected` (`codex.py:321-341`) [V] | the last `agent_message` (`codex.py:284`) [V] |
| `claude-code` | native: `--json-schema` (`claude_code.py:88, 142-143`) [V] | `structured_output` of the result event | `_attach_structured`; an invalid object goes to `rejected` (`claude_code.py:271-286`) [V] | the result event's `result` (`claude_code.py:252`) [V] |

- An invalid or missing result makes the adapter's status `error` with a detail `result invalid: …`, `result missing:
  …` or `structured output …` [V]. `agent_step` turns every status other than `ok` (and a limit) into a failed attempt
  (`tdd.py:707-711`) [V]. With `ok`, it validates again with `parse_result` (`tdd.py:712-717`, `result.py:75-92`) [V].
- The judge path uses the same adapters (`JUDGE_ADAPTERS = ("claude-code", "codex", "opencode", "fake")`,
  `src/l4/llm/agent_judge.py:30`) and turns a non-`ok` run with `rejected` into `schema_invalid` and one repair round
  (`agent_judge.py:164`) [V]. kiro-cli and command never judge [V]. `attach_file_result` serves implementer runs only;
  the opencode judge reads its reply with `_attach_judge_reply` (`opencode.py:303-323`) [V].
- `attach_file_result` with no schema returns `ok` for a missing file and `ok` with the object for any JSON object;
  only text that is not JSON, or JSON that is not an object, gives `error` (`contract.py:35-52`) [V].

### 1.2 What the harness reads of the result

| Field | Read where | Effect |
|---|---|---|
| `status` | `tdd.py:718` | only `blocked` changes the flow; `failed` and `partial` go to the checks like `done` (L4-IMP-005, SCN-IMP-44) [V] |
| `questions` | `tdd.py:1017, 1078, 1513` → `loop.py:114-130` | raised for a `blocked` result [V] |
| `summary` | the same lines | used only by `loop.py:62-71`: a `blocked` result with no question gets one ambiguous question made from the summary [V] |
| `criteria_ids` | `result.py:186` (`check_criteria`) | the red step's cited criteria; empty means "what the new tests trace" [V] |
| `tests_added` | `tdd.py:818` → `classify_red` (`tdd.py:323`) | only in the first check: a non-empty list skips "no tests added". Every later branch fails when the JUnit diff has no new test, so the list changes only the failure text, never the verdict (`tdd.py:321-339`) [V] |
| `suppressions` | `tdd.py:730-731` → `task.red_ok`, `task.done` | the verifier's declared suppressions (an undeclared one is a finding, SCN-IMP-33) [V] |
| `notes_for_verifier` | `tdd.py:891, 1100, 1572` | the judge's unverified hint (L4-VER-001) [V] |
| `phase`, `task_ids`, `files_changed`, `tdd_exemption`, `lesson_proposals` | nowhere after validation | none [V, `grep -rn` over `src/l4`] |

The summary is not recorded in any event [V, the `task.*` emits of `tdd.py`].

### 1.3 The `# Output` section today

`render_prompt` builds it in Python, after the gate section (`prompt.py:274-287`) [V]:
- native: `Your final message is the result JSON object (schema enforced): phase "red", task_ids ["1.1"], criteria_ids
  = …, tests_added = the pytest node ids you added, suppressions = …, files_changed; use null for anything you have
  nothing for.`
- prompt contract: the same sentence without "(schema enforced)", then `Write your result object to
  `.l4-result/result.json`.`, then `It must have status and summary (both required) and conform to this JSON Schema:`
  and the canonical schema on one line.

It is not a template: no version records it and the template lock does not pin it (`templatelock.py:17` lists
`contract, red, green, single, single_tests`) [V]. `prompt.rendered.template_version` is `contract@10+red@9` for both
wordings [V, `prompt.py:290`]. L4-IMP-004 says that the prompt sections, the output contract included, come from
versioned templates (`docs/SPEC.md:1820-1823`) [V].

### 1.4 Promises that no code keeps

- L4-IMP-005: "Missing/invalid → `implementer.result_repair_attempts` repair prompts in the same session → else the
  attempt fails" (`docs/SPEC.md:1917-1919`), and SCN-IMP-08 "Invalid result repaired once" [V]. The key exists
  (`src/l4/config/schema.py:506`, default 1) and no code reads it [V, `grep -rn result_repair_attempts src/l4`].
- L4-IMP-008: a stuck task without questions gets "one short 'state your blocking questions' call" [V,
  `docs/SPEC.md:2014-2023`]; not built (`loop.py:8-9`) [V].
- SCN-QMD-10: a result with five questions gets a repair prompt for the three most blocking [V, `docs/SPEC.md:5901`];
  not built [V].

### 1.5 Telemetry

- opencode's `agent.finished.input_tokens` is the sum of the uncached input of every call (`opencode.py:132-162`) [V],
  not a context size. Each `step_finish` carries `tokens{input, output, reasoning, cache{read, write}}` [V, a
  recorded stream in `docs/live/artifacts/free-judge-longcat-shipfee`].
- kiro-cli `metadata` events carry `contextUsagePercentage` [V, `docs/live/artifacts/job-6211`]. The adapter does not
  read it [V].
- claude-code `stream-json` `assistant` events carry `message.usage{input_tokens, cache_read_input_tokens,
  cache_creation_input_tokens}` per call [V, `tests/fixtures/recorded/claude-code/2.1.288/red-ok.jsonl`].
- codex reports one `turn.completed{usage}` for the whole turn and no per-call usage [V, the recorded event types of
  `tests/fixtures/recorded/codex/0.160.0`].

### 1.6 Evidence

Source: the transcripts of `docs/live` (159 steps, 73 run directories) and of a Kiro dummy repository (35 steps), and
the job logs of a public consumer repository (42 steps of `opencode-go/deepseek-v4.1-flash`, no transcripts). Every
step with a stream was rebuilt and validated with `l4.schemacheck.validate`; the verdicts match the harness's on all
ten `docs/live` failures [V, the analysis scripts and data next to the evidence report].

| Group | Failures | Cause | Fixed already? |
|---|---|---|---|
| `opencode/big-pickle`, job 5465, red 1..3 | 3 | the prompt had no schema: `status` and `summary` missing; red 2 also `files_changed` as objects; red 3 also a `notes` key | yes, `0fa4ad1a` (the schema in the prompt) [V] |
| `opencode/nemotron-3.5-lightning-free`, red 1, 3 | 2 | `summary` missing (red 1 also `"status": "failed"`) | no |
| `magnitude/qwen3.6-35b-a3b`, red 1, 2 (job 5963) | 2 | `"status": "red"` | no (the retry hint `phase_hint` came later, the failure stays) |
| `magnitude/qwen3.6-35b-a3b`, red 1..3 (earlier run) | 3 | the file at a wrong path (red 3 also `"status": "red"`) | yes, the `.l4-result` alias [V] |
| `deepseek-v4.1-flash`, public consumer repository | 6 | `summary` missing ×3, `notes_for_verifier` over 2000 ×1, both ×1, `suppressions[0].reason` over 300 ×1 | no |

- codex: 72 of 72 rebuilt results with no problem, and no kiro-cli step with a result problem (its failed steps were a
  throttle, exit 4 and a kill) [V, recomputed from the data]. The totals "kiro-cli 0 of 70" and "six other free
  OpenCode models 0 of 31" are from the evidence report.
- All ten `docs/live` failing agents wrote the file with a tool and six read it back [V, `n_writes`, `n_reads` of the
  data]; one ran its own JSON check [from the evidence report]. Their final messages hold no JSON object [V,
  recomputed].
- Nine of ten final messages hold a usable summary [from the evidence report; every one of the ten has prose, V].
  The five `blocked` results of the data all had a question [V].
- The ten failing prompts were 6k to 10k characters; the `# Output` section ended them [V].
- Peak per-call context: failing steps 11k to 29k tokens, accepted steps up to 21.6k: no context-size effect [from the
  evidence report]. The consumer's failing steps were long (196 s to 789 s) [I: no transcripts].

## 2. Decisions

### D1. The `# Output` section of a prompt-contract step

- **Template.** The text moves into `src/l4/implementer/templates/output.md`, `version: 1`, with the placeholders
  `{schema}` and `{path}`. `render_prompt` uses it when `ctx.result_path` is set, and `template_version` becomes
  `contract@10+<phase>@<n>+output@1`. `IMPLEMENTER_TEMPLATES` gains `output`, and the lock is written again
  (`python -m l4.templatelock --write`). Why a template: L4-IMP-004 asks for one; the lock then forces a version bump on
  the next wording change; and `template_version` tells a reader of a ledger which wording a step got. The evidence
  analysis had to read the prompt files for that, because `contract@10` covered two wordings (section 1.3).
- **Text** (the four lines after the heading; `{schema}` is one line):

  ```
  # Output
  Give the result of this step as one JSON object with "status" and "summary": "status" is "done" when you did the step, or "blocked" when you need an answer from a person (then "questions" holds at least one question), and "summary" tells in one to three sentences what you did.
  Add "criteria_ids" (the criterion ids that your tests trace), "suppressions" (each new `# noqa` or `# type: ignore` that you added) and "notes_for_verifier" when you have them.
  The object must conform to this JSON Schema: {schema}
  Write your result object to `{path}`.
  ```

  - `status` and `summary` come first, in one sentence: every object without `summary` followed the old field list,
    which named neither (section 1.6).
  - The section names no field that the harness derives (`phase`, `task_ids`, `files_changed`, `tests_added`), not
    even to forbid it: the failing objects' key order mirrors the list they were given [from the evidence report].
  - One instruction says where the result goes: the sentence "Your final message is the result JSON object" is gone
    (29 of 109 final messages repeated the JSON anyway, as an ignored second copy [from the evidence report]). The
    path is the last line. The last line and the phrase "conform to this JSON Schema" keep their wording, so the
    tests that pin them stay (`tests/unit/implementer/test_prompt.py:143-160`, `test_tdd_prompt_contract.py:26`,
    `test_result_alias_step.py:75`, `test_result_values_line.py:79`).
  - "at least one question" tells the agent the rule of D7.
- **The schema shown** is `FILE_RESULT_SCHEMA` (`$id: l4/implementer-file-result@1`), derived in
  `src/l4/implementer/result.py` from the canonical schema: the properties without `phase`, `task_ids`,
  `files_changed` and `tests_added`, and `required: ["status", "summary"]`. A prompt without any schema was worse
  (job 5465, `0fa4ad1a`), so the subset stays. Derived in code, its enums and limits follow the canonical file.
- **Native adapters do not change.** codex and claude-code keep the `(schema enforced)` sentence and the canonical
  schema, which their CLIs enforce (codex failed 0 of 72). The `result values:` line of the phase section stays for
  every adapter (L4-IMP-004).

### D2. Where normalization runs, and what the adapters report

- **Request schema.** `agent_step` sets `RunRequest.result_schema` to the canonical schema for a native adapter and to
  `None` for a prompt-contract adapter. A prompt-contract adapter then hands over the object as written:
  `attach_file_result` with no schema already returns `ok` and the object for any JSON object, and `ok` with no object
  for a missing file (section 1.1). So for the common slips, `agent.finished` and `step.finished` say `ok`, and the
  harness alone judges the object.
- **`RunResult.result_problem`** (`"missing" | "not_json" | "not_object" | "invalid" | None`) says that the run
  finished but its result channel gave no usable object:
  - `attach_file_result`: `missing` (no file; the status stays `ok` with no schema), `not_json` and `not_object` (the
    status stays `error`, as today);
  - codex `_attach_result` and claude-code `_attach_structured`: `missing` or `invalid` (and `not_json` for codex),
    next to the detail and `rejected` they set today. Their status stays `error`, because the judge path needs it
    (section 1.1).
  The field is a fact for `agent_step`; no other reader changes.
- **The adapter's view is kept.** `agent.finished` and `step.finished` record the adapter's status and detail as today
  (`step.finished.status` is "the agent's own `RunResult.status`", L4-STA-001). For a native schema break that the
  harness repairs, both say `error` and `result.normalized` follows. That case did not occur in the data (codex 0 of
  72).
- **Order in `agent_step`** (after the revert of protected paths and the ledger restore, `tdd.py:679-688`, so the
  changed files are the agent's own):
  1. a limit status raises `RoleLimit` (as today);
  2. a status other than `ok` with no `result_problem` is a failed attempt (as today: the run did not finish);
  3. find the object (D3); none → a failed attempt (D7);
  4. normalize it (D4) and record `result.normalized` when a fix was made (D6);
  5. validate it with `parse_result` against the canonical schema; a failure here is a harness defect and fails the
     attempt as today;
  6. a `blocked` result with no question → a failed attempt (D7); `blocked` → questions; anything else → the checks.
- Normalization is a pure function in a new module `src/l4/implementer/normalize.py`: `normalize(raw, facts) ->
  Normalized(obj, fixes)`. `StepFacts` holds the phase, the task key, the changed files and the final message. The
  fix loop calls the same `agent_step`, so a fix unit's steps are normalized too.

### D3. Finding the object

In this order; the first that gives a JSON object wins:
1. `run.structured`, when the run is `ok` (a native result valid against the CLI schema, or a prompt-contract file's
   object as written). Source `result`.
2. `run.rejected`, when `result_problem` is `invalid` (a native object the schema refused). Source `result`.
3. The last result-like JSON object in `run.final_text`: scan the text from the start, try a JSON decode at each `{`,
   keep each decoded object that has a top-level `status` or `summary` key and skip past it; the last one kept wins.
   Only the last 200 000 characters of the text are scanned [G]. Source `final_message`.

Never a source: a file in the worktree, the agent-tmp path or any other path. The `.l4-result` rule stays: "a file the
agent wrote anywhere in the worktree … is never a result" (`resultalias.py:7-10`, L4-SEC-006). The final text is the
agent's own output, as trusted as its result file. No observed failure needed source 3 (section 1.6); it rescues an
agent that printed the object and did not write it [I].

### D4. The normalization rules

The limits, enums and pattern are read from the canonical schema, not written twice (as `result_values_line` does,
`prompt.py:141-152`). `null` means absent first, as today (`drop_nulls`). The rules run in this order:

| # | Schema constraint (`l4/implementer-result@1`) | Rule | Recorded fix |
|---|---|---|---|
| 1 | (unknown keys allowed) | the alias `notes` becomes `notes_for_verifier`, and `suppressions_list` becomes `suppressions`, when the real key is absent; else the alias is dropped. Other unknown keys stay (the result model ignores them, `result.py:39`) | `renamed` (`from`), or `dropped` |
| 2 | `phase` required, enum | set to the step's phase | `replaced` when the agent gave another value |
| 3 | `task_ids` required, `minItems: 1` | set to `[<task key>]` | `replaced` when the agent gave another value |
| 4 | `files_changed` array of strings | set to the step's changed paths from git (`Workbench.changed_files()` without the run's ledger, sorted) | `replaced` only when the agent's value was not a list of strings |
| 5 | `tests_added` array of strings | set to `[]`: the new tests are the JUnit diff that `run_red` computes (`classify_red`'s `new`) and records (`task.red_ok.tests`); `run_red` stops passing the agent's list (section 1.2) | `dropped` only when the agent's value was not a list of strings |
| 6 | `questions` array, `maxItems: 3`, items need string `title`, string `context`, `kind` in the enum | not a list → dropped. An item that is not an object with those three → dropped. An item's `options` or `blocking_tasks` that is not a list of strings → removed from the item. More than three → the first three stay | `dropped` (`count`), `cut` (`count` of the removed ones) |
| 7 | `status` required, enum | an allowed value, also with other letter case or surrounding space → that value. Missing, not a string, a phase name, or any other text → `blocked` when rule 6 left at least one question, else `done` | `replaced` (form only), or `set` with `to`, and `was` only when the old value was a phase name |
| 8 | `summary` required string, `maxLength` | not a non-empty string → the final message (`run.last_message`, with the object's own JSON text taken out when D3 found it there, trimmed); when that is empty, `notes_for_verifier`; when that is empty too, the text `(no summary: the agent wrote none)` | `set` with `from`: `final_message`, `notes_for_verifier` or `none` |
| 9 | `notes_for_verifier` string, `maxLength` | not a string → dropped | `dropped` |
| 10 | `criteria_ids` array of strings with the pattern `^C-[0-9a-f]{8}$` | not a list → dropped; an entry that is not a matching string → dropped | `dropped` (`count`) |
| 11 | `suppressions` items need string `file`, integer `line`, string `rule`, string `reason` (`maxLength`) | not a list → dropped; an item that breaks one of them → dropped | `dropped` (`count`) |
| 12 | `tdd_exemption` object or null, `reason` string; `lesson_proposals` array of objects | the wrong shape → dropped (no code reads them, section 1.2) | `dropped` |
| 13 | `maxLength` of `summary`, `notes_for_verifier`, `suppressions[].reason` | a longer text keeps its start and ends with the marker `[cut by L4: <n> characters removed]`, the whole within the limit | `cut` (`length`: the old length) |

After these rules every constraint of the schema holds, so `parse_result` accepts the object [I: task 1.2 proves it
with a property test over broken objects]. What is not a fix: setting a harness field that the agent left out (the
file prompt does not ask for it), or replacing a valid `files_changed` or `tests_added` list.

Why rule 7 maps an unknown status to `done`: status is advisory except `blocked` (L4-IMP-005), so `done`, `failed` and
`partial` all go to the checks. A blocked meaning with a question becomes `blocked`; with no question there is nothing
to ask, and the checks decide. Letter case is folded first, so `"BLOCKED"` with no question is still `blocked` and
fails under D7; it never becomes `done`.

Why rules 6, 10 and 11 drop and never repair: a repaired question, criterion or suppression would be the harness's
words in the agent's place. A dropped suppression makes its comment undeclared, which the verifier reports
(SCN-IMP-33): stricter, not looser. A dropped criterion id leaves `check_criteria` the ids that remain, or the ids
that the new tests trace (`result.py:186`); each still needs a new test that traces it [V].

### D5. Safety: why a normalized result never makes a wrong change pass

- **The gates judge the work, not the object.** Red: the stub guard, the scope, the criteria tracing, the failure
  kinds (a new test must fail by assertion or `NotImplementedError`), the pre-satisfied proofs, the vacuity check and
  the static gates (`tdd.py:739-962`). Green: the frozen tests, the red tests pass, no regression, the discrimination
  check and the static gates (`tdd.py:1050-1108`). Then the verifier. None of them reads a field that rules 2 to 5, 8,
  9 or 13 change (section 1.2) [V].
- **What normalization never does:**
  - invent or add a question, or change the text of one (rule 6 only drops or cuts);
  - change a present allowed status: a `blocked` stays `blocked`, a `done` with questions stays `done` (rule 7);
  - add a suppression, a criterion id or a TDD exemption (rules 10 to 12 only drop);
  - read, write or revert a file of the worktree: it runs on the object only, after the protected-path revert, which
    records its own `guard.violation` (`tdd.py:687`), and before the stub guard, the production guard and the gates,
    which see the worktree as the agent left it;
  - take an object from a path the agent chose (D3).
- **What it can lose:** a malformed question or suppression, an over-long text's end, an invalid `criteria_ids`
  entry. Each loss is recorded (D6).
- A bug in the normalizer is bounded the same way: `parse_result` still validates its output, and the gates still run.

### D6. The record and the progress line

- `result.normalized{task, phase, attempt, source, fixes: [{field, fix, from?, to?, was?, count?, length?}]}`, written
  with `wb.emit` (so a fix unit's step carries `fix_unit`), once per step with at least one fix, before the guards
  run. `fix` is `set`, `replaced`, `renamed`, `dropped` or `cut`. The event holds no text of the agent: `was` is a
  phase name, `to` an allowed status, `from` a source or key name, `count` and `length` numbers.
- Progress line (INFO): `task <k> <phase> attempt <n>: L4 repaired the result (<fix>; <fix>)`, each fix as `<field>
  <fix>` with its details, for example `task 1.1 red attempt 1: L4 repaired the result (status set to done, was red)`
  and `task 3.1 red attempt 1: L4 repaired the result (summary set from final_message; notes_for_verifier cut from 2417
  characters)`.
- `prompt.rendered` already names the template version, so `+output@1` shows which steps had the new section.

### D7. When an attempt fails for its result

- **No object** (D3 found nothing): `the agent's result is invalid: no result was delivered (<what was missing>)`,
  where the parenthesis is `no result file and no result object in the final message` for a prompt-contract adapter,
  or the adapter's detail and `no result object in the final message` for a native one. The phrase "no result was
  delivered" stays, so `test_result_alias_step.py:91, 109` and `test_tdd_red.py:153` keep their meaning.
- **`blocked` with no well-formed question** (after rule 6): `the agent's result is invalid: status blocked needs at
  least one question in "questions"` and, when rule 6 dropped some, ` (<n> malformed questions were dropped)`. The
  question that `loop.py:62-71` would make from the summary is no longer made for an agent's result: a person gets
  only questions that the agent wrote. That branch of `_questions` stays as a guard; no agent result reaches it [I].
- Both keep "result is invalid", so the eval classes them as `schema` (`src/l4/eval/errors.py:23, 84-89`) [V], and
  both put the `result values:` line in the retry prompt (L4-IMP-008) [V, `tdd.py:711, 716`].
- Both are failed attempts: they count against `max_task_attempts` and, with `escalate-and-note`, against the profile
  (L4-IMP-017).
- A `blocked` result with no question was a question to a person before. It did not occur in the data (all five
  `blocked` results had one) [V]. A model that writes `blocked` for "my tests fail" now loses an attempt, not a
  person's time.

### D8. Which fields stay required

- `l4/implementer-result@1` does not change: `required: ["status", "phase", "task_ids", "summary"]`.
  - It is what the native CLIs enforce. Its strict copy is the one recorded live with 12 of 12 valid codex results and
    is pinned by `tests/unit/agents/test_codex.py:39-41` [V]. Fewer required fields would make `phase` and `task_ids`
    nullable in that copy and send codex an untested schema.
  - It is the contract of the normalized object: rules 2, 3, 7 and 8 always set the four.
- The agent's subset `l4/implementer-file-result@1` requires `status` and `summary` (D1). They stay required because
  the prompt asks for them and the native CLIs enforce them; the harness fills them only when an agent misses them.
- The SPEC's schema block (L4-IMP-005) stays as it is and gains a sentence on the subset and on normalization.

### D9. The repair call: specified, deferred to a second wave

- **Why not now.** After the alias, none of the observed failures lacked an object (section 1.6) [V]. Its only output
  that changes the flow is "the step is done" with a summary, and the summary is not read for an accepted step
  (section 1.2). kiro-cli and command have no tool-less mode, so they cannot use it (`JUDGE_ADAPTERS`) [V]. A model
  that repairs may invent a summary or notes.
- **Rules when it is built** (L4-IMP-022):
  - trigger: D3 found no object, the run finished (`result_problem` set, or a prompt-contract run with no file),
    `implementer.result_repair_attempts` is at least 1, and the profile's adapter is in `JUDGE_ADAPTERS`; one call per
    attempt;
  - the call: the same profile, a new session, tool-less (`PermissionPolicy("judge")`, an empty working directory as
    for a judge, `judge_workdir`), through `AgentJudge.complete_structured` with `FILE_RESULT_SCHEMA`; its prompt, a
    new locked template `repair.md`, holds data blocks with the agent's final message (redacted, defused, the last
    4000 characters [G]), the result file's text when there was one (the first 4000 characters [G]), the problem and
    the `result values:` line, and asks for the object only;
  - the output keeps `status` (`done`, `failed` or `partial`), `summary` and `notes_for_verifier` only. An output with
    `blocked` or with any question is discarded: the repair may restructure the agent's words, never add a question,
    and a `blocked` without the agent's own question would fail anyway (D7). `criteria_ids`, `suppressions` and the
    rest are dropped: they would be the repairing model's claims, not the agent's;
  - the kept output goes through D4 with source `repair`, then the checks;
  - records: `result.repair{task, phase, attempt, outcome: accepted | discarded | failed, reason?}` and the call's
    `budget.cost`; a limit raises the step's `RoleLimit` (L4-AVL-006);
  - `implementer.result_repair_attempts` gets the default `0` in that wave (the call is opt-in). Today the key's
    default is 1 and nothing reads it, so the change has no effect before the wave.
- The SPEC sentence "repair prompts in the same session" and SCN-IMP-08 are amended now to the rule of D7, with a
  pointer to L4-IMP-022.

### D10. No `check_result.py` self-check

A script that the agent runs to check its own result file is not built. All ten failing agents of `docs/live` wrote
the file with a tool and six read it back [V], and one ran its own JSON check [from the evidence report]; none saw the
missing field (section 1.6).
After D1 and D4 every one of those objects is accepted with no extra agent turn. A check script would add agent turns,
and a harness program that the agent runs inside the sandbox, to find what the harness repairs at no cost. If it is
built later, it checks the alias path `.l4-result/result.json` with the code of `normalize.py`, so that the two can
never disagree.

### D11. Peak per-call context in `agent.finished`

- `Usage` gains `context_peak_tokens: int | None` and `context_peak_percent: float | None`; `agent.finished` records
  each one when it is set. `input_tokens` keeps its meaning (the eval sums it, `src/l4/eval/score.py:95-97`) [V].
- Per adapter:
  - opencode: the largest `tokens.input + tokens.cache.read + tokens.cache.write` of the run's `step_finish` events
    (section 1.5) [V shape];
  - claude-code: the largest `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` of the `assistant`
    events' `message.usage` (two events of one message carry the same usage; the maximum is not changed by it) [V
    shape, recorded spike stream; not seen live in an implementer step];
  - kiro-cli: the largest `metadata.contextUsagePercentage`, as `context_peak_percent`; the window size is not
    reported, so it is not turned into tokens [V shape];
  - codex: none (one total per turn) [V]; command and fake: none.
- The `agent.finished` progress line ends with `, context peak <n>k tokens` or `, context peak <p>%` when set.

### D12. Relation to `escalate-and-note`

- That change counts an invalid result as a failed attempt (L4-IMP-017) and uses "attempt 2 returns a result without
  `summary`" in SCN-IMP-176. Under this change such a result is normalized and goes to the checks. The rule of
  L4-IMP-017 stays true ("an invalid agent result" is now one of D7's two cases); the example of SCN-IMP-176 is
  amended to "attempt 2 delivers no result object" (task 6.6).
- Its tests use `Step(structured={"status": "ok"})` as an invalid result [V, its `tasks.md`]. Under rule 7 that object
  becomes `done` and goes to the checks; with no files written, red then fails with "no tests added", which is still a
  failed attempt but with another reason. Task 2.4 changes that fixture to `Step()` (no object and no final text,
  D7's first case) wherever a test needs a result failure.
- Fewer failed attempts mean fewer escalations. Nothing else in that change depends on the result object.
- Both changes add to `## 0.4.4 (unreleased)` of the CHANGELOG; this change adds its lines to the section that the
  other one creates.

### D13. Docs

- SPEC: L4-IMP-019..022 in §7.4 after L4-IMP-005; L4-FAC-010 and L4-FAC-011 in §8.1 after L4-FAC-002; scenarios in
  §23.7 and §23.6.1; the amendments that the proposal lists; §21 row 25.
- Runbook:
  - 4.2: the `result.normalized` line and the peak in the `agent … task …` line;
  - 4.5: `result.normalized` in the ledger;
  - 7.2: a NOTE under the `max_task_attempts` row: a result with a missing summary, a wrong status or too long a text
    no longer fails an attempt; an attempt fails for its result only with no result object or a `blocked` without a
    question;
  - 11: `implementer.result_repair_attempts` is read by no code.
- Skill: no change. Its references do not mention the result object or its failures [V, `grep` of
  `plugins/l4/skills/l4`], and nothing that an operator does changes.
- CHANGELOG: lines under Changed and Added of `## 0.4.4 (unreleased)`.

## 3. Cases

| Case | Today | After this change |
|---|---|---|
| big-pickle red 1 (no `status`, no `summary`) | failed attempt | `status set to done`, `summary set from final_message`; checks run |
| big-pickle red 2 (+ `files_changed` objects) | failed | the above and `files_changed replaced`; checks run |
| big-pickle red 3 (+ `notes`) | failed | the above and `notes renamed to notes_for_verifier`; checks run |
| nemotron red 1 (`status: failed`, no `summary`) | failed | `summary set from final_message`; `failed` stays and goes to the checks like `done` (SCN-IMP-44) |
| nemotron red 3 (no `summary`) | failed | `summary set from final_message`; checks run |
| magnitude-qwen red 1, 2 (`status: red`) | failed, with the phase hint | `status set to done, was red`; checks run |
| magnitude-qwen, file at a wrong path, prose final message | failed (the alias fixed the path since) | still failed: no result was delivered |
| deepseek, `summary` missing | failed | `summary set from final_message` [I: the final message was not seen] |
| deepseek, notes over 2000 | failed | `notes_for_verifier cut`; the judge gets 2000 characters with the marker |
| deepseek, `suppressions[0].reason` over 300 | failed | `suppressions cut`; the declaration stays |
| an agent prints the object and writes no file | failed | source `final_message`; checks run |
| prose only, no file | failed | failed: no result was delivered |
| a JSON object in `agent-tmp/result.json` of the worktree | failed, not committed | the same (never a source) |
| `blocked` with one well-formed question | question | question (unchanged) |
| `blocked` with no question | a question made from the summary | failed attempt; the retry names the rule |
| `blocked` whose only question has no `kind` | failed (schema) | question dropped; failed attempt, reason names one dropped question |
| no `status`, one well-formed question | failed | `status set to blocked`; the question is raised |
| `"status": "BLOCKED"`, no question | failed | `blocked` (case folded); failed attempt (D7) |
| `"status": "complete"` | failed | `status set to done`; checks run |
| five questions with `blocked` | failed (SCN-QMD-10 promises a repair) | the first three are raised; `questions cut, count 2` |
| codex `-o` object with `phase: "green"` in a red step | accepted | accepted; `phase replaced` |
| claude-code `structured_output` invalid (`rejected`) | failed | `agent.finished` `error`; `result.normalized`; checks run |
| command adapter, no `summary` | failed | `summary` from `notes_for_verifier`, else `none` |
| a well-formed object | accepted | accepted; no `result.normalized` |

## 4. Risks

- **A slip no longer costs an attempt, so it is less visible.** `result.normalized` and its progress line record each
  fix, and `l4 kg` and the eval can read them later. The eval stops counting these steps as `schema` errors, so a
  model's eval score can rise without a change in its work [I].
- **`done` for an agent that meant to stop.** An agent that wrote an unknown status and no question goes to the
  checks. With nothing changed, red fails ("no tests added") and green fails its tests, as for any failed attempt [I].
- **The summary is unchecked agent text.** It is not recorded and not sent anywhere for an accepted step (section
  1.2) [V].
- **A cut note** gives the judge less of an unverified hint. The marker says that it was cut [I].
- **The new wording is not proven live.** It follows the evidence of the old wording; task 7.3 runs it on a model that
  slipped, and `l4 eval --compare` compares it (the template lock's own advice, `templatelock.py:5`) [G].
- **A native schema break shows `error` in `agent.finished`** before `result.normalized` (D2). It did not occur in the
  data [V].
- **A `blocked` with no question costs an attempt** where it reached a person before (D7) [I].

## 5. Not verified

- That the consumer's DeepSeek final messages hold a usable summary: its artifacts are off, so no transcript was read
  [I].
- That the new `# Output` wording lowers the slip rate. Task 7.3 measures it [G].
- claude-code's per-call usage in a live implementer step: the adapter's implementer mode is "not exercised live"
  (`claude_code.py:3-4`); the shape comes from a recorded spike stream [V shape only].
- What 100 percent of kiro-cli's `contextUsagePercentage` is [I].
- Which tests of `escalate-and-note` use the `{"status": "ok"}` fixture: that change is being written now [I]; task
  2.4 finds them.
- The evidence counts that this design takes from the evidence report without recomputing them: 29 of 109 final
  messages with JSON, the context peaks, the consumer's step times.
