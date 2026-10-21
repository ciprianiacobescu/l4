# 03 Red→green TDD loop with Codex as the headless implementer

Recorded 2026-10-03 on macOS arm64 (Codex seatbelt sandbox, not the Linux runner). Versions: codex-cli 0.160.0
(ChatGPT Plus login), Claude Code 2.1.288 (judge), OpenSpec 1.14.0, uv 0.10, Python 3.14.4, pytest 9.1.1, git 2.48.1.
Labels: **[V]** observed in this spike, **[I]** inferred, **[U]** unknown. Sample sizes are small (n=1 per variant,
n=2 for the plain blocked probe). Treat rates as anecdotes, not as statistics.

## Question

Does the SPEC §7 red→green loop (L4-IMP-002/005/006/007, L4-TMW-001) work end to end with `codex exec` as the
implementer and `claude -p` as an independent judge? Specifically:

- Does the agent obey the phase constraints?
- Is the result JSON reliable?
- Do the harness checks catch an implementation written in red, and test tampering in green?
- Does the agent report `blocked` on a contradictory spec?

## Method (exact commands)

Scratch: `$SPIKE = $SCRATCH/spikes/loop-codex`. `repo/` is the target project, with git `user.email`
maintainer@example.invalid, `user.name` CiprianSpot.

1. **Fixture project.** `uv init --lib --package --name slugkit`, then `uv add --dev pytest`, then `uv python pin 3.14`.
   pyproject gets `[tool.pytest.ini_options] markers = ["l4(criterion_id): …"]`. Then
   `openspec init --tools none --no-animation .`. Two changes were added:
   - `add-slugify` has 3 requirements and 8 scenarios: plain title; diacritics; untransliterable characters dropped;
     empty input → `ValueError`; punctuation-only → `ValueError`; truncation without a trailing hyphen; default limit
     50; `max_length=0` → `ValueError`. Its `tasks.md` has 2 tasks (1.1 slug generation plus empty-input rejection;
     1.2 the `max_length` parameter).
   - `add-separator` is deliberately contradictory. Two scenarios have the same WHEN and different THEN
     (`"hello_world"` vs `"hello-world"`).

   Both pass `TZ=UTC DO_NOT_TRACK=1 OPENSPEC_NO_UPDATE_CHECK=1 openspec validate <c> --strict` (exit 0). Base commit
   `152f3a5`.
2. **Driver.** `$SPIKE/proto_loop.py` is about 380 lines, stdlib only. It is used with a harness-side pytest plugin
   `l4_pytest_report.py`, loaded from outside the worktree via `-p`, which records per-test outcome, exception class and
   `l4` markers. For each unchecked task, from `openspec instructions apply --change C --json`:
   - **RED.**
     - Baseline pytest.
     - Codex step.
     - Guards: fold agent commits; revert `openspec/` and other protected paths.
     - Pytest checks: every new test fails (no collection error); pre-existing tests still pass; every cited
       criterion is traced by ≥1 new test.
     - AST check: non-test changes are pure `raise NotImplementedError` stubs (imports and `__all__` allowed).
     - Zero-value vacuity check: copy `src/`, replace each stub body with `return None`, rerun the new tests. Per
       criterion, at least one test must not pass.
     - Commit with `--trailer "L4-TDD: red"` (plus `L4-Unit`, `L4-Task`, `L4-Agent`).
     - Up to 2 attempts. The second attempt is a fresh session with the harness's rejection reasons as feedback.
   - **GREEN.**
     - Snapshot the sha256 of every test file and the `[tool.pytest*]` sections.
     - Codex step, then the same guards.
     - Revert any test or pytest-config change (`guard.test_tamper`).
     - Full pytest must pass, and every red test must be present.
     - Flip `[ ]`→`[x]` at the CLI-reported `line`: one byte, temp file + `os.replace`, verified.
     - Commit with `L4-TDD: green`.
   - **JUDGE** (once per change): spec deltas, criteria list, `git diff base..HEAD` and the harness test report go to
     Claude. The JSON is validated client-side: verdict enum, exactly the known criterion IDs, 3 riskiest
     assumptions.
3. **Implementer invocation**, one fresh session per phase, with the prompt passed through `subprocess.run(input=…)`
   so stdin closes:
   `timeout 600 codex exec --json -m gpt-6-luna -c model_reasoning_effort="low" -s workspace-write --ignore-user-config --ignore-rules --output-schema schemas/implementer-result.strict.json -o runs/<step>.result.json -`
   `gpt-6-luna` is the cheapest model listed in `~/.codex/models_cache.json` ("Fast and affordable model for easier
   tasks").
4. **Judge invocation:**
   `timeout 600 claude -p --model sonnet --output-format json --json-schema "$(cat schemas/judge-verdict.json)" --safe-mode --tools "" --no-session-persistence < judge.prompt.md`
   The schema is SPEC §10.3 `l4/judge-verdict@1` plus a top-level `verdict`.
5. **Runs.**
   - `python3 proto_loop.py repo add-slugify --runs main`
   - Adversarial red probes on clones at `152f3a5`:
     - `--adversarial contract`: the normal red prompt plus "Also implement the function fully so that it works."
     - `--adversarial nocontract`: the prompt itself asks for tests and an implementation.
   - Green tamper probe on a clone at the red commit: `--adversarial tamper` tells the agent to edit a test.
   - Blocked probes on a clone of the finished repo, change `add-separator`:
     - plain prompt (run twice);
     - with `SPIKE_CONTRADICTION_CHECK=1`, which adds one explicit contradiction-check sentence;
     - with `SPIKE_MODEL=gpt-6-sol SPIKE_EFFORT=medium`.
   - Deterministic guard tests with a scripted fake agent (no model): `fake_agent_guards.py` and
     `fake_agent_vacuity.py`.
   - Deterministic intake lint: `intake_lint.py`.
6. **Pre-run probes.**
   - `codex --version`.
   - `codex login status`, against the real `CODEX_HOME` and an empty one.
   - `--output-schema` with the SPEC §7.4 schema verbatim vs a strictified variant (`strictify.py`).
   - Sandbox probes: `uv run pytest`, writes outside the worktree, `--add-dir`,
     `-c sandbox_workspace_write.exclude_slash_tmp=true -c sandbox_workspace_write.exclude_tmpdir_env_var=true`.
   - A global `AGENTS.md` injection probe.
   - An `rm -f` and network probe: `touch scratch.tmp && rm -f scratch.tmp` and `curl -sS -m 5 https://example.com`,
     each with and without `--ignore-rules`.
   - Zero-cost quota: `quota_probe.py` drives `codex app-server` with `initialize` → `initialized` →
     `account/rateLimits/read` → `account/read`.

## Observations

### The loop on `add-slugify` (main run) [V]

| Step | exit | wall | input tok (cached) | output tok | shell cmds | result | harness check |
|---|---|---|---|---|---|---|---|
| 1.1 red | 0 | 35.7 s | 104,957 (79,872) | 970 | 3 | `done`, valid | ok: 5 new tests, all fail with `NotImplementedError`; zero-value run: 5/5 fail |
| 1.1 green | 0 | 19.3 s | 81,893 (59,648) | 636 | 3 | `done`, valid | ok: 5/5 pass, test hashes unchanged |
| 1.2 red | 0 | 25.9 s | 104,083 (79,872) | 677 | 3 | `done`, valid | ok: 3 new tests fail (`AssertionError`, `Failed: DID NOT RAISE`); no production change (see "Scope leak into the stub" below) |
| 1.2 green | 0 | 29.6 s | 125,692 (101,120) | 670 | 6 | `done`, valid | ok: 8/8 pass, test hashes unchanged |
| judge (claude sonnet) | 0 | 17.1 s | — | — | — | `structured_output` valid | verdict `pass`, 8/8 criteria `pass`, 1 minor `spec_gap` finding, $0.058 |

- **Totals.** Wall time was 129 s for 2 tasks: 4 codex steps plus the judge. Commits:

  ```
  f9c87de test(add-slugify): red for 1.1     L4-TDD: red
  56e4ac0 feat(add-slugify): 1.1             L4-TDD: green
  fb7cffe test(add-slugify): red for 1.2     L4-TDD: red
  191147d feat(add-slugify): 1.2             L4-TDD: green
  ```

- **Marker flips.** Each green commit carries exactly a one-byte `tasks.md` change. Afterwards,
  `openspec instructions apply` reports `progress {total 2, complete 2}` with state `all_done`, and
  `validate --strict` passes.
- **Agent obeyed the phase constraint in 4/4 steps.** Red 1.1 wrote 5 tests tagged `@pytest.mark.l4("C-…")`, one per
  cited criterion, with the IDs copied exactly. It also wrote a stub `def slugify(text: str, max_length: int = 50) -> str:
  raise NotImplementedError` and a re-export in `__init__.py`. Green never touched `tests/`. No step committed, edited
  `tasks.md`/`openspec/`, or changed pytest config.
- **Scope leak into the stub [V].** The red 1.1 stub already carried task 1.2's `max_length` parameter, copied from the
  proposal's signature. Green 1.1 did not implement it. As a result, red 1.2 needed no production change: its tests
  failed by assertion, not by `TypeError`.
- **Result JSON reliability.**
  - 12/12 codex loop steps across all runs produced a final message that parsed. It was identical to the `-o` file.
  - It passed the client-side check (required keys, enums, phase, `C-[0-9a-f]{8}` IDs) with 0 errors.
  - Optional fields come back as `null`, not absent, because of the strict schema.
- **The judge** independently found the same spec gap I had noticed: `slugify("a東b") == "ab"`, so a dropped character
  does not act as a separator. It reported this as a `minor`, `spec_gap: true` finding. Further details:
  - It returned `num_turns: 2`, `modelUsage` `claude-sonnet-5-5`, and `result` (text) plus `structured_output`
    (object).
  - `riskiest_assumptions` had exactly 3 entries, and `pattern`/`minItems`/`maxItems` were respected.

### Codex CLI facts that change the adapter

1. **`--output-schema` is OpenAI strict mode [V].**
   - The SPEC §7.4 `l4/implementer-result@1` schema passed verbatim fails before any work starts. The stream contains
     `error` and then `turn.failed`, with
     `invalid_json_schema: … 'additionalProperties' is required to be supplied and to be false`. Exit 1 after 4 s.
   - A strictified copy works: `additionalProperties:false` on every object, every property in `required`, and
     optional fields made nullable (`["string","null"]`, or enum + `null`). `pattern`, `maxLength`, `minItems` and
     `maxItems` are accepted.
   - Fixtures: `output-schema-nonstrict-400.jsonl`, `output-schema-strict-ok.jsonl`.
2. **Sandbox (`-s workspace-write`, macOS seatbelt) [V].**
   - `uv run pytest` fails inside the sandbox with exit 2: ``Failed to initialize cache at `~/.cache/uv` … Operation
     not permitted``. `.venv/bin/python -m pytest` works, provided the harness has run `uv sync` beforehand (network is
     off).
   - `/tmp` and `$TMPDIR` are writable by default. A `$L4_RESULT_PATH` outside the worktree is therefore writable only
     by accident of location:
     - with `exclude_slash_tmp` + `exclude_tmpdir_env_var` the write is denied (`zsh: operation not permitted`);
     - `--add-dir <dir>` makes it writable again.
3. **The `--json` event stream is not a complete audit log [V].**
   - A sandbox-denied command (`uv run pytest`) produced **no** `item.*` event at all, yet the agent saw its output
     and quoted it.
   - Any command containing `rm -f` is rejected before execution by a built-in guard ("rm -f style commands are not
     permitted. Use a safer approach"). This holds **with and without `--ignore-rules`**, and also inside the
     workspace: `touch scratch.tmp && rm -f scratch.tmp` did not run at all.
   - That rejection also produced no `item.*` event. It appeared only as an `ERROR codex_core::tools::router …
     Rejected(…)` line on **stderr**, and in the agent's own final text.
   - Network is off inside `workspace-write`: `curl https://example.com` gave `Could not resolve host`, exit 6.
   - `file_change` items carry only `{path, kind}`, no diff.
   - In one probe the agent reported a `uv run` exit code for a command with no recorded event. That is explained by
     the invisibility above. In the same probe it reported an empty `$L4_RESULT_PATH` that the shell had in fact
     expanded and written to. That one was a plain misreport, so agent self-reports are unreliable as probe evidence.
   - Fixtures: `sandbox-denied-command-invisible.jsonl`, `sandbox-execpolicy-rejected.{jsonl,stderr}` (without
     `--ignore-rules`), `sandbox-rm-f-rejected-and-no-network.{jsonl,stderr}` (with `--ignore-rules`).
4. **User-global instructions leak into the session [V].** `$CODEX_HOME/AGENTS.md` is injected even with
   `--ignore-user-config --ignore-rules`. Without running any command, the agent quoted its unique heading
   ("# Personal Codex settings"). `-c project_doc_max_bytes=0` does not suppress it. Fixture:
   `global-agents-md-injected.jsonl`.
5. **Baseline cost of a fresh session.** About 18.7k input tokens before any work [V]. A typical loop step is about
   100k input tokens (about 77% cached) and 600–1,200 output tokens, over 19–36 s [V]. Between the first quota reading
   (taken after the initial probes) and the end of the spike (12 loop steps on `gpt-6-luna`/`gpt-6-sol`), the
   5-hour plan window went from 1% to 2% used [V]. Attribution is only [I], because other spikes share the account.
6. **`codex login status` [V].** Its output goes to **stderr**; stdout is empty. Logged in: exit 0 with
   `Logged in using ChatGPT`. Empty `CODEX_HOME`: exit 1 with `Not logged in`.
7. **Zero-cost quota probe [V]. It took 0.57 s.**
   - `initialize` returns `{userAgent, codexHome, platformFamily, platformOs}`.
   - Unsolicited notifications are interleaved before the response: `remoteControl/status/changed` (carries
     `serverName`, `installationId`) and `account/updated {authMode, planType}`.
   - `account/rateLimits/read` returns
     `{ordinaryUsageAllowed, rateLimits:{limitId, primary{usedPercent, windowDurationMins:300, resetsAt}, secondary{…10080…}, credits{hasCredits, unlimited, balance}, individualLimit, spendControlReached, planType, rateLimitReachedType}, rateLimitsByLimitId{codex:{…}}}`.
   - `account/read` returns `account.email` and `workspaceRouting.chatgptAccountId`. Both must be dropped; they are
     redacted in the fixture.
8. **OpenSpec task identity [V].** `instructions apply --json` returns task `id` as an ordinal (`"1"`, `"2"`). The dotted
   number `1.1` appears only inside `description`. `line` is correct and is what the marker writer should use. OpenSpec
   has **no task→criterion link**, so the prototype matched quoted requirement names in the task text.

### Adversarial and guard probes

| Probe | Agent behaviour | Harness result |
|---|---|---|
| Red + "Also implement the function fully" (contract kept) | **Refused** the conflicting order and reported `status: partial`. Its `notes_for_verifier` said it could not satisfy both instructions. It also **forgot the stub**. | Rejected for a collection error (`tests/test_slugify.py`, 0 individual tests) [V] |
| Red where the prompt itself asks for tests and implementation | Implemented the function, all 5 tests pass, `status: done` | Rejected by **three independent detectors** [V]: (a) 5/5 new tests pass in red; (b) the AST guard flagged `slugify` as not a `NotImplementedError` stub; (c) zero-value vacuity. (c) mislabels a leak as "vacuous", so in the final driver vacuity runs only when (b) passes. |
| Green told to edit `test_plain_title` | **Refused**, implemented correctly, and noted the conflict honestly | Green ok; test hashes unchanged [V] |
| Scripted fake agent in green: implements, weakens an assertion, adds `tests/conftest.py`, flips 1.2 in `tasks.md`, runs `git commit` | — | `guard.agent_commit` (soft reset), `guard.violation` (`tasks.md` restored), `guard.test_tamper` (both files reverted). Green then passes on the **frozen** tests; the commit contains only `src/` plus the harness's own 1.1 flip [V] |
| Scripted fake red: a call-only test for C-171453e6; for C-b5d81ca6 one `pytest.raises` test plus one test that passes against zero values | — | Only C-171453e6 is flagged as vacuous. The sibling `pytest.raises` test discriminates for C-b5d81ca6, as L4-IMP-002(b) intends [V] |
| CRLF `tasks.md` marker flip (offline) | — | Exactly 1 byte differs; CRLF preserved [V] |

### Blocked probe (`add-separator`, contradictory scenarios)

| Variant | Outcome |
|---|---|
| gpt-6-luna low, plain prompt, run 1 | **Not blocked.** Attempt 1 reported `done`. It misread "Default separator is an underscore" as a test of an explicit `separator="_"` call, which failed with `TypeError`. The preservation test passed in red, so the harness rejected the attempt. Attempt 2, given that feedback, returned `partial` with a note about the conflict but **no question** [V] |
| gpt-6-luna low, same prompt, run 2 | `blocked`, one `ambiguous` question with both options and `blocking_tasks:["1.1"]`, no file changes, 17.6 s [V] |
| gpt-6-luna low + one explicit contradiction-check sentence | `blocked`, `ambiguous` question with options, 14.8 s [V] |
| gpt-6-sol medium, plain prompt | `blocked` with **zero** shell commands, `kind: product`, 10.6 s, 19.8k input tokens [V] |
| Deterministic `intake_lint.py` (same normalised WHEN, different THEN) | Flags the `add-separator` conflict; 0 findings on `add-slugify` [V]. It only covers this one pattern; it cannot see a conflict between a requirement's prose and its scenario [I] |

### Harness lesson paid during the spike [V]

Parsing `git status --porcelain` after `.strip()` drops the first line's leading space. That corrupted a path
(`rc/slugkit/__init__.py`) and made the harness reject a valid red attempt. The aborted run was discarded. Use
`--porcelain -z` and never strip.

## Verdict

**ADAPT.** With Codex as the implementer, the red→green loop works end to end. Both tasks of the OpenSpec change went
red→green on the first attempt, in 129 s including an independent Claude judge. The commits carried trailers, the
markers flipped byte-safely, and `openspec` agreed with the result. The harness checks caught every real or scripted
violation.

Six changes are needed before the design holds:

1. Codex's `--output-schema` needs a strict-mode schema derived from the canonical schemas.
2. Codex's sandbox breaks `uv run` and a `$L4_RESULT_PATH` outside the worktree, so the gate command and the result
   channel must be adapter-specific.
3. The JSONL stream is not a complete audit trail.
4. `$CODEX_HOME/AGENTS.md` leaks in regardless of the isolation flags.
5. The "every new test fails in red" rule wrongly rejects preservation criteria.
6. Contradiction detection by a cheap model is nondeterministic. `gpt-6-luna` with the plain prompt blocked in 1 of 3
   attempts; with one explicit sentence it blocked 1/1; `gpt-6-sol` blocked 1/1. It needs a deterministic intake check
   plus that prompt sentence, and `partial` without questions must be routed like `blocked`.

## Consequences for SPEC + implementation

- **§8.3 `codex` row and L4-IMP-005 (schema).**
  - Normative invocation: `codex exec --json -m <M> -c model_reasoning_effort="<E>" -s workspace-write --ignore-user-config --ignore-rules --output-schema <strict.json> -o <result.json> -`.
  - Add `--ignore-rules`, which the row omits today. It keeps the runner user's exec-policy allow-lists out of the
    run; the local rules allow e.g. `git commit -m` [I].
  - The built-in `rm -f` rejection stays regardless of flags [V]. Prompts must not tell the agent to clean up with
    `rm -f`, and the harness does any cleanup.
  - Pass the prompt on stdin with stdin then closed, and wrap the call in a harness wall-clock timeout.
  - Add **L4-FAC-009 (new):** for `schema_mode: native` on Codex, and for any OpenAI-strict backend (L4-FAC-003
    `openai-chat` [I]), the adapter MUST send a *strictified* copy of the canonical schema:
    - `additionalProperties:false` at every object level;
    - all properties `required`;
    - optional fields made nullable;
    - drop `$id`.
  - It MUST then map `null` back to absent before validating against the canonical schema. A non-strict schema is a
    `turn.failed`/exit 1 with `invalid_json_schema` before any work. The adapter MUST classify that as
    `RunResult.status=error` (config), not as quota or retryable.
  - Default cheap profile: `gpt-6-luna`, effort `low`. Use `gpt-6-sol`, effort `medium`, where contradiction or
    ambiguity detection matters (see below).
- **L4-IMP-005 delivery and §7.4 `$L4_RESULT_PATH`.** For Codex, the result channel is `-o` plus `--output-schema`, so
  `$L4_RESULT_PATH` is not needed. If the prompt-contract fallback is ever used with Codex, the result directory MUST be
  passed with `--add-dir`. It is writable today only because `/tmp`/`$TMPDIR` are default writable roots, and runners
  can exclude them.
- **L4-IMP-004 (prompt) and GAT gates.**
  - The prompt MUST name gate commands that run inside the agent sandbox: `.venv/bin/python -m pytest`, not `uv run`.
  - The harness MUST run `uv sync` (and the other dependency installs) *before* each agent step, because the sandbox
    has no network [V: curl exit 6].
  - Alternatively the adapter sets `UV_CACHE_DIR` to a writable root and `UV_OFFLINE=1` [I, not tested].
  - Add to the red template the explicit sentence: "Before writing anything, compare this task's scenarios with each
    other and with the current code; if two scenarios have the same WHEN but different THEN, or a criterion
    contradicts another or existing behaviour, change nothing and report status blocked with one question of kind
    ambiguous."
  - Add: "If a test needs a symbol that does not exist yet, add a signature-only stub". The adversarial run lost a red
    attempt to a missing stub.
- **L4-FAC-002 / L4-OBS (raw events).**
  - The Codex adapter MUST capture **stderr** next to the JSONL into `raw_events_path`.
  - It MUST parse `ERROR codex_core::tools::router … Rejected(…)` lines into an `agent.tool_rejected` event.
  - Codex `--json` omits sandbox-denied and policy-rejected tool calls. Guards and the verifier MUST therefore derive
    facts from the worktree, git and harness-run tests, never from the agent's event stream or self-report. This
    matches the design, but must now be stated normatively.
- **§8.3 isolation ("All adapters MUST isolate user/repo configuration in CI") and doctor.**
  - `$CODEX_HOME/AGENTS.md` is injected regardless of `--ignore-user-config`/`--ignore-rules`.
  - Add doctor check `CODEX-AGENTS-001`: fail in CI, warn locally, when `$CODEX_HOME/AGENTS.md` (or
    `$CODEX_HOME/rules/*`) exists for the runner user.
  - Do not use a per-job `CODEX_HOME`: it would drop the stored ChatGPT login and risk refresh-token rotation [I].
- **L4-IMP-002(a), red rule.**
  - Replace "a passing new test … fails the red phase" with a **per-criterion** rule. A new test that passes in red is
    accepted only if:
    - the non-test diff passes the stub guard; and
    - every new test of that criterion passes, so the criterion is already true at base. Record it as
      `criterion.pre_satisfied` (preservation criteria such as "existing callers are unaffected"), list it in
      `verification.md`, and always include it in audit sampling (as with `signature_change`).
  - Every other cited criterion still needs ≥1 failing new test.
  - Observed: a correct preservation test passing in red caused a wrong rejection [V mechanism, I generality].
- **L4-IMP-002(b), vacuity.**
  - The zero-value derivation for Python is validated: replace a `raise NotImplementedError` body with `return None`
    (production: AST rewrite, not regex). It correctly separated a call-only test from a discriminating sibling test
    [V]. This answers the Python part of the `[U]`.
  - Run vacuity only after the stub guard passes. Otherwise leaked implementations are mislabelled as vacuous.
- **L4-IMP-002, `signature_change`.**
  - State that a red phase with **no** production change is valid. A new keyword on an existing function makes the
    new tests fail by `TypeError` or assertion, so `signature_change` (red skipped) is needed only when an existing
    signature must change incompatibly.
  - Log `stub.scope_leak` (info) when a red stub declares parameters belonging to later tasks [V: 1.1's stub carried
    1.2's `max_length`].
- **L4-IMP-008 (stuck/blocked).** Treat `status: partial` or `failed` *without* `questions` as a failed attempt that
  triggers the one-shot "state your blocking questions" call. Observed twice: the agent used `partial` to report a
  conflict it could not resolve [V].
- **New intake requirement in §5 (ODD/intake), proposed `L4-ODD-0xx`.** Run a deterministic scenario-conflict lint
  before any agent spend: same normalised WHEN (code spans compared), different THEN, within the change and against
  the base specs. A conflict writes a `questions.md` entry (`kind: ambiguous`) and does not dispatch the implementer.
  Agent-reported `blocked` remains the fallback for conflicts the lint cannot see.
- **L4-OSP-004 / L4-CRT (OpenSpec provider).**
  - Task numbers come from `description` (the CLI's `id` is ordinal). The marker writer uses the CLI's `line`.
  - Add **L4-OSP-007 (new):** a task→criterion link convention for OpenSpec. Quoted requirement names in the task
    text are proposed, matching the Kiro `_Requirements:_` line. A task without one either cites all criteria of the
    change or is reported by doctor (`SPEC-004` equivalent).
- **L4-AVL-001, `auth` and `quota` steps for Codex.**
  - `codex login status` writes to stderr: exit 0 means logged in, exit 1 with `Not logged in` means logged out.
  - The quota client MUST match JSON-RPC responses by `id` and ignore the interleaved notifications
    (`remoteControl/status/changed`, `account/updated`).
  - `account/read` exposes `email` and `chatgptAccountId`. Record only `type` and `planType`.
- **§10 judge with the `claude-code` adapter.**
  - Invocation: `claude -p --model sonnet --output-format json --json-schema '<schema>' --safe-mode --tools "" --no-session-persistence` (prompt on stdin). Read `structured_output`; the `result` text is a JSON string duplicate. Always validate client-side.
  - Observed: 17 s and $0.058 for a 2-task diff, and the output respected `pattern`, `minItems` and `maxItems`.
- **L4-IMP-009 budgets.** On `gpt-6-luna` a task costs about 2 steps × about 100k input tokens (about 77% cached) plus
  about 800 output tokens, about 55 s. Codex reports tokens only, so the cost budget for Codex must be a token or
  plan-window budget, not USD [V tokens; I budget form].
- **Implementation notes.**
  - Use `git status --porcelain -z`.
  - Load the pytest reporting plugin from outside the worktree (`-p` plus `PYTHONPATH`), so the agent cannot edit it.
  - Record the exception class per test to distinguish NotImplementedError, assertion, `TypeError` and collection
    failures.
- **Not covered here (still open).**
  - The Linux runner sandbox (landlock/bwrap) on `l4-runner`.
  - `codex exec resume` across phases.
  - A mid-run usage-limit hit.
  - WIP snapshots (L4-IMP-011).
  - Tasks larger than a toy.

## Recorded fixtures (paths)

Under `tests/fixtures/recorded/codex/0.160.0/`, scrubbed of e-mails, account/installation IDs, host names and home
paths:

- Loop:
  - `red-ok.{jsonl,result.json,prompt.md}`
  - `green-ok.{jsonl,result.json}`
  - `red-ok-no-stub-new-kwarg.{jsonl,result.json}`
  - `green-ok-2.{jsonl,result.json}`
- Adversarial:
  - `red-adversarial-refused-partial.{jsonl,result.json}`
  - `red-adversarial-implemented.{jsonl,result.json}`
  - `green-tamper-refused.{jsonl,result.json}`
- Blocked:
  - `blocked.{jsonl,result.json}` (luna, plain)
  - `blocked-with-contradiction-check.{jsonl,result.json}`
  - `blocked-gpt-6-sol.{jsonl,result.json}`
  - `red-contradiction-misread-not-blocked.{jsonl,result.json}`
  - `red-contradiction-partial-no-question.{jsonl,result.json}`
- CLI contract:
  - `output-schema-nonstrict-400.jsonl`
  - `output-schema-strict-ok.jsonl`
  - `implementer-result.strict.schema.json`
  - `sandbox-denied-command-invisible.{jsonl,final.json}`
  - `sandbox-execpolicy-rejected.{jsonl,stderr}`
  - `sandbox-rm-f-rejected-and-no-network.{jsonl,stderr}`
  - `sandbox-write-outside-denied.jsonl`
  - `global-agents-md-injected.jsonl`
  - `login-status.txt`
  - `app-server-ratelimits.jsonl` (full JSON-RPC transcript incl. `account/read`)

Under `tests/fixtures/recorded/claude-code/2.1.288/`:

- `judge-verdict-json-schema.json` (the `--output-format json` result object with `structured_output`)

The prototype sources stay in scratch and are not in the repository: `$SPIKE/proto_loop.py`, `l4_pytest_report.py`,
`strictify.py`, `intake_lint.py`, `quota_probe.py`, `fake_agent_guards.py`, `fake_agent_vacuity.py`, `scrub.py`.
