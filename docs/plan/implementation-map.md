# Implementation map

How docs/SPEC.md is split into OpenSpec changes in `openspec/changes/`, which code each change owns, and
which part of each change belongs to the **walking skeleton (M1)**, the thin vertical slice that must run live
on `example-group/dummy-agentic` through `l4-runner` before any change is deepened (M2).

## Package layout (owned paths)

```
pyproject.toml                 # bootstrap-core (deps: click, pydantic>=2, pyyaml, httpx; dev: pytest, pytest-cov, ruff)
src/l4/__init__.py, __main__.py
src/l4/cli.py                  # bootstrap-core: click group; each command delegates to a module below
src/l4/exitcodes.py, outcome.py, log.py (logging + redaction)            # bootstrap-core
src/l4/config/{schema.py,loader.py,defaults.py}                          # bootstrap-core
src/l4/doctor/{registry.py,checks_*.py,fix.py}                           # bootstrap-core (framework) + each change adds checks_<area>.py
src/l4/specs/{base.py,detect.py,openspec.py,kiro.py,markers.py,criteria.py,questions.py}   # spec-providers
src/l4/state/{ledger.py,fold.py,lifecycle.py}                            # state-vcs-locks
src/l4/vcs/{git.py,worktree.py,trailers.py,locks.py}                     # state-vcs-locks
src/l4/sim/{fakes.py,scenarios.py,runner.py}, tests/scenarios/*.yaml    # simulation-harness
src/l4/agents/{base.py,factory.py,claude_code.py,codex.py,opencode.py,kiro_cli.py,command.py,acp.py,fake.py}  # agent-factory
src/l4/llm/{base.py,openai_chat.py,anthropic.py,system_one.py,fake.py}  # agent-factory
src/l4/availability/{probes.py,cooldown.py,fallback.py}                  # agent-factory
src/l4/implementer/{prompt.py,tdd.py,guards.py,result.py,loop.py}       # implementer-tdd-loop
src/l4/gates/{odd.py,runner.py}                                          # implementer-tdd-loop
src/l4/clarifier/{clarifier.py,router.py}                                # clarification-loop
src/l4/verifier/{ladder.py,gates.py,judge.py,aggregate.py,report.py,fixunit.py,playwright.py}  # verifier
src/l4/forge/{base.py,gitlab.py,github.py,local.py}                      # forge-and-ci
src/l4/ci/{router.py,render.py,templates/}                               # forge-and-ci
src/l4/init/{init.py,templates/}                                         # forge-and-ci
src/l4/archive.py                                                        # forge-and-ci
src/l4/memory/{lessons.py,serena.py}                                     # memory-lessons
src/l4/sandbox/{base.py,bwrap.py,none.py}                                # sandbox-security
src/l4/provision/{runner.py}, install.sh                                 # runner-provisioning
src/l4/orchestrator.py                                                   # implementer-tdd-loop (run loop over the §12.0 state machine)
tests/unit/<area>/, tests/contract/, tests/scenarios/, tests/fixtures/
```

## Change map

| # | Change | Capabilities (spec folders) | SPEC areas | M1 (walking skeleton) |
|---|---|---|---|---|
| 0 | `spikes` | none (`skip_specs: true`) | SPK scenarios, §21 row 0 | runner inventory; headless contract of each agent CLI; OpenSpec JSON; quota probes; Python TDD fixture repo |
| 1 | `bootstrap-core` | `cli-contract`, `configuration`, `observability`, `doctor` | CLI, CFG, OBS, DOC | package, `l4` CLI with all §2.1 commands wired (stubs return exit 2 "not yet"), config loader + full schema with defaults, logging + redaction, exit codes, `outcome.json`, doctor framework + CFG/ENV checks |
| 2 | `spec-providers` | `spec-detection`, `openspec-provider`, `kiro-provider`, `task-markers`, `acceptance-criteria`, `questions-file` | DET, SPI, OSP, KSP, TMW, CRT, QMD | detection; OpenSpec provider (list, validate, tasks, archive); byte-safe marker writer; criteria IDs; `questions.md` parse/write |
| 3 | `state-vcs-locks` | `run-state`, `unit-locks`, `worktrees` | STA, LCK, RACE, WTR (RES scenarios) | ledger + state fold; branch + worktree per unit; trailers; local lock; resume after crash |
| 4 | `simulation-harness` | `simulation` | SIM, DRY | fake adapter/LLM/forge; `l4 simulate happy-openspec`; `l4 plan` |
| 5 | `agent-factory` | `agent-factory`, `availability` | FAC, AVL | adapter interface + factory; claude-code and opencode adapters (+ codex/kiro-cli when the runner has them); binary/hello probes; cool-down registry; fallback chain with the §8.4 log lines |
| 6 | `implementer-tdd-loop` | `implementer`, `operational-domain` | IMP, ODD, GAT | task selection; prompt; red phase (tests fail) → green phase (tests pass) with test-file freeze; result contract; commits + trailers; blocked → `questions.md` |
| 7 | `clarification-loop` | `clarifier` | CLR | LLM clarifier answers; unanswered → `waiting_human`; re-entry when a human commits answers |
| 8 | `verifier` | `verifier` | VER | deterministic gates + one independent LLM judge; `verification.md`; findings → fix change |
| 9 | `forge-and-ci` | `install-init`, `ci-integration`, `archive` | INS, CI, ARC | GitLab forge (MR, labels, notes); GitLab CI template (tags, script files only); `l4 init`; post-merge archive MR |
| 10 | `memory-lessons` | `memory` | MEM | lessons file read + injection as `<l4:data>` |
| 11 | `sandbox-security` | `security` | SEC | bubblewrap agent/gate sandboxes when `bwrap` is present; fail closed otherwise (doctor `SANDBOX-001`) |
| 12 | `runner-provisioning` | `runner-provisioning` | new: PRV | `l4 doctor --fix` installs missing user-local tools (uv, node, OpenSpec, agent CLIs) on shell runners; documents (cannot detect from inside a job) the `.bash_logout`/`clear_console` failure; prints the human-only auth steps; host script `scripts/runner/prereqs.sh` |
| 13 | `live-validation` | `non-functional` | NFR | the §20.4 live scenario on `example-group/dummy-agentic` |

## Walking skeleton (M1) exit criterion

On `example-group/dummy-agentic`, with only the documented install commands run by a human:
1. `l4 doctor` passes in a pipeline job on `l4-runner`.
2. A seeded OpenSpec change is implemented by a real agent CLI with a red commit before a green commit.
3. The verifier runs the deterministic gates and one independent judge and writes `verification.md`.
4. A merge request is opened; the human merges it; a post-merge archive MR is opened.
5. A deliberately ambiguous change produces `questions.md`; the clarifier answers what it can; a human answer
   committed to the branch resumes the unit.

## Lessons already paid for (2026-10-03)

* GitLab YAML: a `: ` inside a plain `script:` item is a YAML mapping error. Generated CI YAML calls script files
  or single-line `l4 …` commands only.
* A shell-executor runner whose `gitlab-runner` user has a `~/.bash_logout` that runs `clear_console` fails every
  job in "prepare environment" before any script runs. Doctor cannot detect this from inside a job; `l4 init` and
  the install docs name the failure signature and the fix.

## M0 — thin walking skeleton (selected 2026-10-03)

M0 is the shortest path through the orchestrator that takes the OpenSpec change `add-discount-codes` in
`example-group/dummy-agentic` red → green → verified → merge request on `l4-runner`, with one implementer adapter and
one judge of a different vendor. It is cut out of the M1 task groups; M1 later deepens the same modules. Everything the
M0 brief puts out of scope stays out: fallback chains, cool-downs, quota probes, clarifier, archive, lease refs and
atomic-push fencing, memory/Serena, extra adapters, GitHub, audit sampling, per-criterion vacuity, Playwright,
System-One, panel, fix-unit creation, sweeper/continuation and `l4 doctor --fix`.

**Agent pair: implementer `codex` (vendor openai), judge `claude-code` (vendor anthropic).**

* Spike 03 already ran this exact pair: Codex did red → green, and Claude judged as `claude -p --json-schema …
  --safe-mode --tools ""` (17 s, $0.058, and the reply respected `pattern`, `minItems` and `maxItems`) [V].
* M0 has no fallback and no cool-down, so the implementer must be the CLI least likely to hit a limit mid-unit.
  The 5-hour window moved from 1 % to 2 % used over 12 Codex loop steps. The readings are [V], but attributing the
  change to those steps is only [I], because other spikes shared the account (spike 03). Claude `pro` has small usage
  windows [V, runner memory]. The judge makes one call per verification.
* The runner has subscription logins only and no API keys [V, docs/runner/README.md]. So the judge runs through the
  agent-adapter interface, not through an `LLMBackend` (gap G3).
* Consequence: the Codex adapter is pulled in from agent-factory §4 (4.1 and 4.2; 4.4 is absorbed). The M1 claude-code
  tasks 1.6 and 1.7 serve only the judge.

**Harness delivery: `l4 init --vendor`.** Harness hosting is still open (Q1). The runner therefore gets the harness as
`.l4/vendor/` inside the target repo (forge-and-ci 2.28, pulled in from M2), and the shim runs
`uv run --project .l4/vendor l4`.

**Size: 72 build lines + 6 gap tasks = 78, about 8 over the ~70 cap.**

* Nothing from the out-of-scope list is in it.
* Two build lines are not named in the brief:
  * sandbox-security 1.6, the gate sandbox. Gates run agent-written tests, which could otherwise read the job's
    `L4_FORGE_TOKEN` and both agents' logins.
  * sandbox-security 1.16, protected-path revert. It also replaces spec-providers 1.12.
* Without those two lines the build list is 70.
* The 6 gap tasks are steps on the M0 path that no existing task covers.
* Smaller helper tasks are not listed as their own lines. Each is built inside the named line, in the reduced form
  given under Simplifications.

Line format: `change-id task — what M0 builds`. Lines are numbered in build order across all three stages, and the
stages run in sequence.

### Stage A — scaffold, config, spec provider, vcs/state

1. bootstrap-core 1.1 — package skeleton, `l4 --version`, `python -m l4`
2. bootstrap-core 1.2 — `ExitCode`, `SEVERITY_ORDER`, `most_severe()`, `L4Exit`
3. bootstrap-core 1.3 — `Redactor`: configured values + `TOKEN_SHAPES`
4. bootstrap-core 1.4 — `L4Config` sections for M0 (`extra="forbid"`) + defaults
5. bootstrap-core 1.6 — `load_config()`: path + did-you-mean errors, never a value, exit 2
6. bootstrap-core 1.10 — `commands.HANDLERS`, `dispatch()`, click group with the common options
7. bootstrap-core 1.11 — `with_outcome`, atomic redacted `outcome.json`, unexpected exception → exit 1
8. bootstrap-core 1.12 — doctor `Check`/`register()`/`run_checks()`, table + `l4/doctor@1` JSON
9. bootstrap-core 1.13 — `cache_root()` + ENV-001..003
10. bootstrap-core 1.16 — `l4 doctor`: exit 2 on a schema error, 3 on a failed error check; lazy `CHECK_MODULES`
11. bootstrap-core 1.18 — `map_exit()` + `l4 ci map-exit CODE`
12. spec-providers 1.1 — shared types, `SpecError` tree, `SpecProvider` Protocol
13. spec-providers 1.7 — `split_lines` with byte offsets, BOM, mixed terminators
14. spec-providers 1.8 — `write_marker`: one byte, temp file + rename, post-write verification, symlink refusal
15. spec-providers 1.13 — OpenSpec task parser (line, number, marker offset; only `x`/`X` means done)
16. spec-providers 1.19 — `OpenSpecProvider.list_units/unit_dir/load`
17. spec-providers 1.22 — `validate <id> --strict --json`; the "archive would refuse" INFO becomes an error
18. spec-providers 1.25 — criteria from `specs/<cap>/spec.md` deltas with `C-xxxxxxxx` ids
19. spec-providers 1.30 — `raise_questions`: append a section + index row, change no other byte
20. state-vcs-locks 1.2 — hardened `Git` runner (hooks and fsmonitor off, git env scrubbed, `Git.history`)
21. state-vcs-locks 1.6 — `Git.commit` with `CommitTrailers`, bot identity, `--no-verify`
22. state-vcs-locks 1.8 — fast-forward push of the unit branch, never forced
23. state-vcs-locks 1.11 — `WorktreeManager.ensure`: unit branch from base, worktree outside the repo
24. state-vcs-locks 1.16 — `LedgerWriter`: `run.started` first, strict `seq`, fsync per line, `finish()`
25. state-vcs-locks 1.24 — `LocalFileLease`: non-blocking flock under `$L4_CACHE/locks`
26. state-vcs-locks 1.18 — `UnitState` + pure `fold` over the M0 events
27. state-vcs-locks 1.21 — `transition()`: one `phase.changed`, undeclared edge refused, exit code returned
28. state-vcs-locks 1.19 — `l4 status` (`run_status`, canonical `dump_state`)
29. simulation-harness 1.14 — `l4 plan`: table + `--json` (`l4/plan@1`), `outcome.json`

*Exit:*

* unit tests pass;
* on a clone of dummy-agentic, `l4 doctor` exits 0, or 2 for a mistyped key;
* `l4 plan --json` lists `openspec:add-discount-codes` with next action `implement`;
* `l4 ci map-exit 11` exits 11.

### Stage B — agent adapters, availability (minimal), sandbox, implementer, `l4 run`

30. sandbox-security 1.2 — `build_agent_env` / `build_gate_env` allow-lists
31. sandbox-security 1.6 — `BwrapSandbox.build_argv`, gate kind
32. sandbox-security 1.7 — `build_argv`, agent kind (own credential dir only)
33. sandbox-security 1.9 — `BwrapSandbox.available` runs a real no-op; failure fails closed
34. sandbox-security 1.16 — `revert_protected` after every agent step, `guard.violation`
35. agent-factory 1.1 — `RunRequest`, `RunResult`, `ProbeResult`, `AgentAdapter`, `EventSink`, `AdapterError`
36. agent-factory 1.2 — `ProcRunner` (own process group, timeout kill, stall watchdog) + `build_env`
37. agent-factory 1.4 — `FakeAdapter` (scripted steps that write files) for unit tests
38. agent-factory 4.1 — `CodexAdapter.build_command`, fresh runs, never `--full-auto`
39. agent-factory 4.2 — `CodexAdapter.parse` (`thread.started`, last `agent_message`, usage, `turn.failed`)
40. agent-factory 1.6 — `ClaudeCodeAdapter.build_command` (subscription, `read_only`)
41. agent-factory 1.7 — `ClaudeCodeAdapter.parse` (stream-json → `RunResult`, `structured_output`, `modelUsage`)
42. agent-factory 1.19 — `hello` probe + `normalise_hello` (exact `L4-OK`, kill on timeout)
43. agent-factory 7.1 — `auth` probe: CLI login status of the selected profile
44. agent-factory 1.24 — `Factory.for_role`: first profile, binary → auth → hello, one `availability.selected`
45. agent-factory 1.26 — doctor `LIVE-001` for the implementer and judge profiles
46. implementer-tdd-loop 1.1 — Python TDD fixture repo (pytest, junit, one pending task)
47. implementer-tdd-loop 1.2 — `parse_junit` → `TestReport`; DTD/entity/oversize refused
48. implementer-tdd-loop 1.5 — `run_gate` in the gate sandbox, log capture, process-group timeout kill
49. implementer-tdd-loop 1.8 — `ImplementerResult` + `parse_result` (`l4/implementer-result@1`)
50. implementer-tdd-loop 1.12 — versioned prompt templates (contract, red, green) + `render_prompt`
51. implementer-tdd-loop 1.19 — `run_red`: baseline, agent, gate, `classify_red`, red checkpoint commit
52. implementer-tdd-loop 1.21 — `run_green`: hash freeze + restore, red tests pass, no new failures, marker, green commit
53. implementer-tdd-loop 1.23 — `run_task`: attempts; stuck → halt; blocked → `questions.md` + checkpoint commit
54. implementer-tdd-loop 1.27 — `Orchestrator.run_unit` over the M0 edges through `transition()`
55. implementer-tdd-loop 1.31 — `run_command` (`l4 run --unit`): worktree, lock, ledger, factory, sandbox, hooks,
    pushes, most-severe exit

*Exit:*

* the tests of line 55 pass with `FakeAdapter` on the fixture repo: red commit before green commit, task ticked, and
  the run stops at `implemented` when no verify hook is present;
* on `l4-runner`, through `scripts/runner/mk-ssh.sh`, the nested-sandbox probe (`sandbox-probe.sh` style: a
  scratch uv project, codex and claude inside bwrap) passes with the line-32 profile and its M0 deltas;
* this probe needs only bwrap, not the harness. The first live harness run is G6, because getting the harness onto
  the runner (line 72), launching it (line 70) and pushing (line 69) are all Stage C.

### Stage C — verifier, GitLab forge, CI template, `l4 init`

56. verifier 1.2 — `JudgeVerdict` (`l4/judge-verdict@1`) + `parse_judge_output`
57. verifier 1.5 — judge prompt: spec, criteria, diff, junit summary; `notes_for_verifier` as an unverified hint
58. verifier 1.7 — step 2: setup/lint gates through `run_gate`; a failure is a blocker with a log link
59. verifier 1.8 — step 3: full test gate, non-vacuous (zero tests, missing report or missing new test → fail)
60. verifier 1.10 — `run_judge`: one schema repair, status mapping
61. verifier 1.14 — `aggregate_unit`, deterministic; judge-only findings never FAIL
62. verifier 1.16 — `verification.md` + `verdict.json` + round evidence, written on FAIL too
63. verifier 1.19 — ladder driver: steps 0, 2, 3, 9, 10 with `verify.step` events
64. verifier 1.20 — verdict → trigger/exit (PASS → `verified`, FAIL → 10, NEEDS_HUMAN → 11, role unavailable → 12),
    `verify_hook`
65. forge-and-ci 1.3 — `GitLabForge._request`: `PRIVATE-TOKEN`, pagination, 429/5xx retry, token redaction
66. forge-and-ci 1.4 — `find_pr` / `create_pr` (draft through the `Draft: ` prefix, idempotent)
67. forge-and-ci 1.5 — `update_pr` (ready = drop `Draft: `)
68. forge-and-ci 1.6 — `ensure_labels` + `set_managed_labels` (one `l4:<phase>`, foreign labels kept)
69. forge-and-ci 1.39 — `forge_hook`, `mirror_hook`, `handoff_hook`
70. forge-and-ci 1.15 — GitLab CI template `l4.gitlab-ci.yml` (M0 single job)
71. forge-and-ci 1.23 — `plan_init` + atomic apply: `.l4/config.yaml`, shim, CI file
72. forge-and-ci 2.28 — `--vendor`: the harness at the pinned commit copied to `.l4/vendor/`, vendor shim

*Exit:* G6 passes.

### Gaps (on the M0 path, no existing task covers them; no tasks.md was edited)

Each gap opens with the proposed one-line task (in tasks.md form), followed by the reason.

* **G1** (Stage B, after line 39; agent-factory) — Implement `strictify_schema()` and the Codex result channel: pass a
  strict copy of the canonical schema as `--output-schema` and read the result from `-o <file>`, mapping `null` back to
  absent before validating `l4/implementer-result@1`; invoke `codex exec --json -s workspace-write --ignore-user-config
  --ignore-rules --output-schema S -o R -` with the prompt on stdin, then stdin closed; classify an
  `invalid_json_schema` `turn.failed` as `RunResult.status=error` — test: tests/unit/agents/test_codex.py::test_strict_schema_round_trip — code: src/l4/agents/codex.py
  * Strict copy (spike 03, proposed L4-FAC-009): `additionalProperties: false` at every level, every property
    required, optional fields nullable, `$id` dropped. A non-strict schema fails with exit 1 before any work [V].
* **G2** (Stage B, after line 48; implementer-tdd-loop) — Run `gates.setup` (`uv sync --frozen`) in the gate sandbox
  before the red baseline and before every agent step, with network shared and a read-write `UV_CACHE_DIR` bound at
  `$L4_CACHE/uv`; gate commands and prompts use `.venv/bin/python -m pytest` — test: tests/unit/implementer/test_setup.py::test_setup_runs_before_each_agent_step — code: src/l4/implementer/tdd.py
  * Why: Codex's own sandbox has no network, and `uv run` there fails because it cannot open `~/.cache/uv`
    [V, spike 03].
  * The same failure would hit bwrap: `--ro-bind / /` makes `~/.cache/uv` read-only, hence the read-write cache bind.
  * Running setup in bwrap with that bind is not yet probed [I]. The proven alternative is to run setup outside bwrap,
    as the README's sandbox probe did.
* **G3** (Stage C, before line 60; verifier + agent-factory) — Implement an adapter-backed judge: the
  `complete_structured` surface that `run_judge` consumes (`Msg`/`StructuredResult` of agent-factory 1.13, reduced),
  over `ClaudeCodeAdapter` in a judge mode — `claude -p --output-format json --json-schema <schema> --safe-mode
  --tools "" --no-session-persistence`, prompt on stdin, the reply parsed from `structured_output`, `model_resolved`
  taken from `modelUsage` — and accept an adapter profile in `roles.judges` — test: tests/unit/verifier/test_agent_judge.py::test_claude_judge_structured_output — code: src/l4/llm/agent_judge.py
  * Why: verifier 1.10 takes an `LLMBackend`. The SPEC's default judges are API-key backends, and the runner has no
    API keys.
* **G4** (Stage A, after line 28; state-vcs-locks) — Make `l4 status` and `l4 plan` read
  `<unit_dir>/.l4/ledger/*.jsonl` from `origin/l4/openspec/<name>` (through `Git`: `ls-tree` + `show`) when that
  branch exists, else from the working tree — test: tests/unit/state/test_status_branch.py::test_status_reads_unit_branch_ledger — code: src/l4/state/status.py
  * Why: SPEC L4-STA-004 says the fold reads the unit branch, but no task reads it from a default-branch checkout [I].
* **G5** (human-only, before G6) — Create the project access token `l4-bot` on project 118 (api +
  write_repository, Developer) and store it as the masked CI variable `L4_FORGE_TOKEN`.
  * Why: `CI_JOB_TOKEN` cannot push on 17.5 CE.
  * Name: the designs read `forge.token_env` = `L4_FORGE_TOKEN` (forge-and-ci design, "SPEC deviations" item 1), but
    `.serena/memories/env/dummy-agentic.md` still says `L4_GITLAB_TOKEN`.
* **G6** (Stage C exit, live; live-validation) — Run the M0 acceptance on `add-discount-codes` — test: tests/live/test_m0_acceptance.py::test_add_discount_codes_red_green_verified_mr (marker `live`, needs `L4_LIVE=1`) — code: tests/live/test_m0_acceptance.py
  * Setup: the human commits the `l4 init --ci gitlab --vendor` output plus the printed include snippet to
    dummy-agentic `main`. A pipeline started with `L4_UNIT=openspec:add-discount-codes` runs on runner 12.
  * Assert:
    * `l4 doctor` exits 0;
    * every task has an `L4-TDD: red` commit older than its `L4-TDD: green` commit;
    * all tasks are `[x]`;
    * `verification.md` says PASS, with the gates and one claude-code verdict;
    * the ledger has `availability.selected` for codex and for claude-code;
    * the MR is ready and labelled `l4:in_review`.
  * Record the pipeline and job ids.
  * Informational second run: `L4_UNIT=openspec:add-vat` ends with exit 11 and a `questions.md`. In spike 03, Codex on
    luna-low missed a contradiction in 1 of 2 runs.
  * Why this is a gap: implementer 1.32, verifier 1.22 and live-validation 1.5–1.9 all target `add-greeting` and the
    M1 pipeline. live-validation 1.7 also names the trailer `L4-Phase: red`, but the SPEC uses `L4-TDD`.

### Simplifications (reduced form; what is deferred)

**Stage A**

* **bootstrap-core 1.4** — only the sections M0 reads.
  * `roles` needs only `implementer` (one profile) and `judges` (one adapter profile, see G3); the other roles are
    optional.
  * The other sections, and the cross-change keys `ci.self_provision` and `clarifier.s1_standin`, arrive with their
    consumers.
* **bootstrap-core 1.10** — real handlers for `init`, `doctor`, `plan`, `run`, `status`, `ci map-exit`, and `verify`
  (thin). Every other §2.1 command exits 2 with "not yet implemented".
* **bootstrap-core 1.11** — absorbs 1.9 (`Outcome`, `UnitOutcome`, `new_run_id`, atomic redacted write).
  * Console logging is stdlib logging filtered through `Redactor`. The ledger is the machine record.
  * Deferred: the JSONL `EventLog` (1.8); the `$GITHUB_OUTPUT` and `.l4-out/l4.env` mirrors and
    `outcome.schema.json` (1.19).
* **bootstrap-core 1.13 and spec-providers 1.22** — OpenSpec is resolved where PRQ-08 installed it:
  `$L4_HOME/npm/node_modules/.bin/openspec`, with `L4_HOME` defaulting to `~/.local/share/l4` (the runner's path
  [V]; runner-provisioning already uses `$L4_HOME`), pinned 1.14.0. A developer machine installs it there the same
  way.
  * 1.13 and 1.14 specify `<cache_root>/tools/openspec-<v>/…` instead.
  * Use one constant. Move it back when `doctor --fix` (runner-provisioning 1.11) owns the install.
* **bootstrap-core 1.16** — registers ENV-001..003 and agent-factory's LIVE-001 only.
  * Deferred: CFG-001..004 and their helpers (1.5, 1.7, 1.15); ENV-004/005 and `credential_env_names` (1.14); the
    `--ci`/`--unit` scopes (1.20); `--fix` (1.21); `--detailed-exitcode` (1.17).
  * A config that fails the schema still exits 2.
  * The vendor-independence check moves to verifier 1.19.
* **spec-providers 1.1** — includes the `SpecProvider` Protocol, but no `ProviderRegistry` (1.2). Detection (1.3–1.6)
  is deferred; the framework is OpenSpec, taken from config.
* **spec-providers 1.8** — absorbs 1.21 (OpenSpec allows only `' '` → `x`).
  * Deferred: wide-bracket refusal (1.9), `path_lock` (1.10) and the foreign-edit abort (1.11). One process writes per
    unit, under the unit lock.
* **spec-providers 1.19** — absorbs 1.20 in reduced form: `tasks()` is the file parser of 1.13 only.
  * There is no `instructions apply` call, so `progress_agreement` and the CLI-contract recordings (1.18) are
    deferred. The CLI task id is only an ordinal anyway (spike 03).
  * Units are listed from `openspec/changes/*` on disk; archived units are skipped.
  * `verify_root` (1.17) is deferred.
* **spec-providers 1.22** — absorbs 1.14 in reduced form: absolute pinned binary, fail closed when it is absent, never
  `npx` or `PATH`, no `ensure_installed`.
  * The hermetic run (1.15) is reduced to cwd = repo root and a fixed env: `PATH`, `HOME`, `TZ=UTC`,
    `DO_NOT_TRACK=1`, `OPENSPEC_NO_UPDATE_CHECK=1`.
  * The argv allow-list and the planted-package test (1.16) are deferred.
* **spec-providers 1.25** — absorbs 1.24 (normalisation, `criterion_id`, golden vector).
  * No `criteria.json` (1.26); criteria are computed on every run.
  * OpenSpec has no task → criterion link (spike 03), so every task prompt lists all criteria of the unit.
* **spec-providers 1.30** — creates `questions.md`, or appends to one the harness wrote (the index is found by its fixed
  header).
  * Deferred: the tolerant grammar (1.28), answer semantics (1.29) and status/suggestion edits (1.34).
  * No re-entry: re-running a blocked unit re-attempts the task.
* **state-vcs-locks 1.6** — absorbs 1.5 (trailer rendering only; `parse` arrives with reconcile). `L4-Step` is
  `<task>/<phase>/<attempt>` until `step_key` (1.22) lands.
* **state-vcs-locks 1.8** — absorbs 1.7 in reduced form: `+` refspecs, `--force`, `-f` and `--mirror` are refused
  before git runs. No `Lease`, no lock-ref push.
* **state-vcs-locks 1.11** — absorbs 1.9 (names) and 1.10 (create from an existing remote unit branch).
  * 1.12 is reduced to: an existing worktree is removed (`worktree remove --force`, then `prune`) and recreated, never
    reused.
  * Deferred: WIP snapshot/restore (1.13, 1.14) and `step_key`/`reconcile` (1.22, 1.23). A crashed run restarts the
    current task from the last pushed checkpoint.
  * Also deferred: `merge_base_into` (1.27, 1.28).
* **state-vcs-locks 1.16** — absorbs 1.15 in reduced form: event types are an open set, and string values are
  redacted.
  * Contract test 1.1 is deferred. Verifier step 0 runs strict validation on the unit dir, which is the live proof
    that `.l4/` is tolerated.
* **state-vcs-locks 1.24** — absorbs 1.26 (`acquire_for_run`, `lock.*` events, a busy unit is skipped with exit 0).
  No `PushCoordinator` (1.25): one thread, sequential pushes.
* **state-vcs-locks 1.18** — absorbs 1.17 in reduced form: sort by `ts, run_id, seq`; a torn last line is skipped.
* **state-vcs-locks 1.21** — absorbs 1.20 in reduced form: `TRANSITIONS` holds only the M0 edges (see
  implementer-tdd-loop 1.27).
* **state-vcs-locks 1.19** — prints the folded state, as a table or JSON. `--rebuild`, `state.json` and `state_drift`
  are deferred.
* **simulation-harness 1.14** — absorbs 1.13 and 1.15 in reduced form.
  * Next action ∈ {implement, verify, hand_off, none}, from the folded phase and the task counts. `awaiting_human` is
    reported as not actionable.
  * No question/answer facts, no `--sweep`, no availability view.
  * Exits 0, or 2 on a config error.
  * The rest of simulation-harness is deferred.

**Stage B**

* **sandbox-security 1.6** — absorbs 1.1 (types). The gate kind is the line-32 profile without any credential dir and
  with `--unshare-net`; the setup step (G2) is the exception.
* **sandbox-security 1.7** — base profile is the one proven on the runner [V, README "Nested sandbox"]:
  `--ro-bind / / --tmpfs /tmp --unshare-pid --unshare-ipc --share-net`, with the worktree and the profile's own state
  dir writable. M0 adds these deltas:
  * `--proc /proc` and `--dev /dev`, so that the ancestors' `/proc/*/environ` (which holds the job's
    `L4_FORGE_TOKEN`) cannot be reached [I].
  * `--tmpfs` over every other adapter's `sandbox.credential_paths`. The README files this under "gap for M2", but it
    is on the M0 path: without it, the codex implementer could read `~/.claude/.credentials.json`.
  * The main repo's `.git` read-only, so agent commits fail. `fold_agent_commits` (implementer-tdd-loop 1.17) is
    therefore deferred.
  * `--clearenv` plus the allow-listed env.

  The empty-home layout and the tool binds derived from `PATH` (1.8) are deferred. Re-run the nested-sandbox probe
  with these deltas at the Stage B exit.
* **sandbox-security 1.9** — absorbs 1.10 in reduced form: `BwrapSandbox` is the only production sandbox; `NoSandbox`
  is for unit tests only.
  * No `mode`, `allow_none` or `sandbox.risk_accepted` (1.11).
  * A failed self-test makes `l4 run` exit 3 before any agent or gate runs.
  * Deferred: canary probes (1.12), SANDBOX-001 (1.13), the live smoke test (1.14).
* **sandbox-security 1.16** — absorbs 1.15. The M0 protected set is the design's contract globs plus the unit's own
  OpenSpec dir (`openspec/changes/<name>/**`, except `.l4/**`, which the ledger appends to during the step). The
  harness writes `questions.md` only after the revert, so an agent edit to it is reverted too.
  * The set is restored from the step base after every agent step, before the harness writes markers or questions.
  * This replaces spec-providers 1.12 (the byte-region tasks guard), which is deferred.
  * Isolation flags (1.17) are inlined in the adapters. The prompt-source allow-list (1.18) is deferred.
* **agent-factory 1.2** — the env comes from sandbox-security 1.2. Both M0 profiles authenticate from files, so no
  credential variable is passed. The secret-hygiene contract test (1.3) is deferred.
* **agent-factory 1.4** — a standalone scripted fake, not a wrapper over `l4.sim.fakes.ScriptedAgent`.
* **agent-factory 4.1 and 4.2** — fresh runs only: no `resume`, and session-id persistence (implementer-tdd-loop 1.22)
  is deferred.
  * Invocation and result channel per G1. stderr is captured next to the JSONL (spike 03).
  * A `turn.failed` whose message reports a usage limit means the role is unavailable: exit 12, no cool-down.
  * The quota probe (4.3) is out of M0.
* **agent-factory 1.6 and 1.7** — used for the judge only: subscription auth, `read_only`, judge flags per G3, and
  isolation flags inline instead of `isolation_flags` (sandbox-security 1.17).
  * `implement` mode and the `--bare`/api_key path are built but not exercised live.
  * `parse` is tested against the existing `tests/fixtures/recorded/claude-code/2.1.288/` recordings, so 1.8 is not
    needed.
  * The rate-limit interrupt (1.9) is deferred.
* **agent-factory 1.19** — absorbs 1.18 in reduced form: the binary step is `shutil.which` on the job PATH, which
  starts with `~/.local/bin` [V, pipeline #2525]. No `min_version` and no `harness_path` (runner-provisioning 1.1).
* **agent-factory 7.1** — absorbs 4.4 and 2.1, CLI login status only.
  * `codex login status`: output on stderr; exit 0 = logged in, exit 1 = logged out.
  * `claude auth status`: reduced to `logged_in`, `auth_method` and `plan`, with the e-mail dropped before any log.
  * The env-var presence check for API keys is deferred.
* **agent-factory 1.24** — absorbs 1.5 (registry of `codex`, `claude-code` and `fake`) and 1.20 in reduced form
  (binary → auth → hello, stop at the first failure).
  * Only the first profile of the chain is used. Any probe failure → `RoleUnavailable` → exit 12.
  * Deferred or out: `ProbeCache`, cool-downs, fallback selection, the SPEC 8.4 console lines, `WaitingCapacity` and
    mid-run fallback (1.16, 1.17, 1.21–1.23, 1.25).
* **implementer-tdd-loop 1.2** — absorbs 1.3 and the XML rule of sandbox-security 1.5: DOCTYPE/ENTITY and oversize
  reports are refused.
* **implementer-tdd-loop 1.5** — absorbs 1.4 (`judge_test_gate`).
* **implementer-tdd-loop 1.12** — absorbs 1.13 (sha256 + template version; `data_blocks` empty) and the contract rules
  of 1.14. It also adds the rules from the spikes:
  * the gate command is `.venv/bin/python -m pytest …`;
  * "stub only what this task needs";
  * the contradiction-check sentence, which makes the agent report `blocked` with one `ambiguous` question;
  * never clean up with `rm -f`.
* **implementer-tdd-loop 1.19** — absorbs 1.18 (`new_test_ids`, `classify_red`).
  * The red-scope stub guard (1.15) is deferred. Red validity is decided by `classify_red` plus the protected-path
    revert, so a red commit may carry partial production code.
  * Spike 03's per-criterion `pre_satisfied` rule is not in M0.
* **implementer-tdd-loop 1.21** — absorbs 1.20 (`FreezeManifest`, `restore_frozen`).
* **implementer-tdd-loop 1.23** — absorbs 1.11 (`select_next_step`).
  * Stuck = `blocked`, or `implementer.max_task_attempts` reached.
  * The agent's `status` is advisory except for `blocked` (spike 01).
  * Deferred: identical-diff detection, the repair prompt (1.9), `check_criteria` (1.10), the iteration cap (1.24),
    the TDD exemption (1.25).
* **implementer-tdd-loop 1.27** — M0 edges only:
  * intake → ready → implementing → implemented → verifying → verified | fixing | awaiting_human;
  * implementing → awaiting_human on `blocked`, exit 11, with no `clarifying` hop because the clarify hook is absent;
  * implementing → halted when attempts run out, exit 13;
  * required role unavailable → exit 12, with no `waiting_capacity` re-entry.

  ODD intake (1.6, 1.7) is deferred: an unrunnable test gate shows up as a failed baseline and the unit is halted.
  1.28 is covered by `transition()`'s refusal of undeclared edges.
* **implementer-tdd-loop 1.31** — absorbs 1.29 (sandbox fails closed, exit 3).
  * Hooks resolved: `forge`, `mirror`, `verify`, `handoff`. `lessons` and `clarify` are absent.
  * A checkpoint push follows every checkpoint commit.
  * The fake end-to-end scenario (1.30) is covered by the tests of 1.31. The live check (1.32) is replaced by G6.

**Stage C**

* **verifier 1.2** — absorbs 1.1 (types, reduced to those M0 uses).
* **verifier 1.5** — prompt only: unit spec, criteria, `git diff <base>...<head>`, junit summary, and
  `notes_for_verifier` as an unverified-hint block; no transcript.
  * The fresh detached verifier worktree is deferred. Gates run in the unit worktree at the committed head, after a
    clean `git status --porcelain -z`.
* **verifier 1.7** — setup and lint (ruff) only. Build and typecheck run only when they are configured.
* **verifier 1.10** — drives the judge of G3, with statuses `ok`, `schema_invalid`, `timeout` and `error`.
  * Two invalid replies → NEEDS_HUMAN. A judge that cannot run → exit 12.
  * Deferred: the served-model check, limit classification and cool-down (1.11), the citation re-check (1.12).
* **verifier 1.14** — absorbs 1.13 in reduced form. **Traceability override (flagged): M0 has no step 4**
  (spec-providers 1.27 and verifier 1.9 are deferred).
  * Verdict rule: FAIL if step 0, 2 or 3 fails. PASS if the judge returns `pass` for every criterion and reports no
    blocker or major finding. Otherwise NEEDS_HUMAN.
  * This overrides verifier design D1 for M0 only. D1 rejected `require_traceability: false` because "it allows
    judgment-only passes, which weakens the property the verifier exists to provide". M0 accepts that.
  * An M0 PASS therefore means: the gates are green, every new test is proven red then green in the ledger
    (`task.red_ok`), and one independent judge passed every criterion. `verification.md` says
    "traceability: not checked (M0)".
  * M1 restores step 4. That also needs a harness-owned pytest plugin, loaded with `-p` from outside the worktree, so
    that `@pytest.mark.l4("C-…")` reaches the junit report (spike 03). No task covers that plugin yet.
* **verifier 1.19** — absorbs 1.6 and 1.15 in reduced form.
  * Step 0 (from 1.6): all tasks `[x]`; the branch contains the base head, otherwise error with exit 1 and no merge;
    `validate --strict`.
  * On an exception (from 1.15): the phase stays `verifying`, exit 1, no verdict.
  * Independence is a config check: the judge's `vendor` must differ from the implementer's `vendor`, otherwise
    exit 12. The served-vendor exclusion (1.3, 1.4) is deferred.
  * FAIL → `verify_fail_fix`, exit 10, findings in `verification.md`, no fix change (1.18 is out of M0).
  * NEEDS_HUMAN → exit 11, no verdict questions (1.17).
  * No `max_fix_rounds` escalation.
  * The simulation scenarios (1.21) and the live check (1.22) are replaced by G6.
* **verifier 1.20** — M0 needs `verify_hook`. The `l4 verify` handler is kept because it is thin.
* **forge-and-ci 1.3** — absorbs 1.1 and 1.2 in reduced form: GitLab only, built from `CI_API_V4_URL`,
  `CI_PROJECT_ID` and `forge.token_env`. The `Forge` Protocol and its dataclasses are built only as far as lines
  66–68 return them.
* **forge-and-ci 1.5** — ready only; close/reopen is unused.
* **forge-and-ci 1.6** — labels: `l4:<phase>`, plus `l4:needs-answers` when questions were raised.
* **forge-and-ci 1.39** — absorbs:
  * 1.29: credential-helper args from `L4_FORGE_TOKEN`, and `strip_remote_credentials`;
  * 1.10 and 1.11, reduced: title `[l4] <unit>: <proposal title>`, a static body linking `verification.md`, labels,
    and a draft MR after the first push;
  * 1.38, reduced: on PASS, one hand-off commit without `[skip ci]` carrying `verification.md` and the ledger; the MR
    is then marked ready and labelled `l4:in_review`.

  Deferred:
  * the sticky note (1.7);
  * the commit status (1.8);
  * token scopes and FORGE-001 (1.9, 1.37);
  * `-o ci.skip` (1.30), which M0 does not need: checkpoint commit messages already carry `[skip ci]`, and the M0 job
    runs only when `L4_UNIT` is set.
* **forge-and-ci 1.15** — absorbs 1.13: the job lines are literally `… || .l4/bin/l4 ci map-exit $?`. The M0 template
  is a single job, `l4-run`:
  * `tags: [agentic]`;
  * `rules: [{if: '$L4_UNIT'}]`;
  * `resource_group: l4`;
  * `interruptible: false`;
  * `allow_failure: {exit_codes: [10, 11, 12]}`;
  * `GIT_DEPTH: "0"`;
  * artifacts: `.l4-out/`;
  * script: `.l4/bin/l4 doctor || .l4/bin/l4 ci map-exit $?`, then `.l4/bin/l4 plan`, then
    `.l4/bin/l4 run --unit "$L4_UNIT" || .l4/bin/l4 ci map-exit $?`;
  * `after_script`: `.l4/bin/l4 status`.

  A pipeline is started from the web UI or the API with `L4_UNIT` set. A golden test asserts that no script item
  contains an unquoted `: `.

  Deferred: `l4-detect` and child pipelines (1.16), `l4 ci render*` (1.17), `lint_gitlab_yaml` (1.12), the CI Lint API
  test (1.18), and `doctor_command` (runner-provisioning 1.20).
* **forge-and-ci 1.23** — absorbs:
  * 1.27: the handler `l4 init --ci gitlab --vendor [--force]`;
  * 1.19, reduced: fixed gates for a uv/pytest/ruff repo — setup `uv sync --frozen`, test
    `.venv/bin/python -m pytest --junitxml=.l4-out/junit.xml`, lint `.venv/bin/ruff check .`;
  * 1.24, reduced: `.gitignore` gains `.l4-out/`;
  * 1.25, reduced: refuse to overwrite without `--force`; writes go through temp file + rename.

  `l4 init` writes:
  * `.l4/config.yaml` with the M0 pair: profiles codex/openai and claude-code/anthropic, plus `roles.implementer`
    and `roles.judges`;
  * `.l4/bin/l4`;
  * `.l4/ci/l4.gitlab-ci.yml`.

  It does not edit `.gitlab-ci.yml` (1.22 is deferred). Instead it prints the
  `include: [{local: .l4/ci/l4.gitlab-ci.yml}]` snippet for the human to add.

  Deferred: `.serena/`, `.l4/prompts/`, `--dry-run` (1.26), the OpenSpec bootstrap (1.21), CI-001 (1.28) and
  `GITLAB_RUNNER_NOTICE`.
* **forge-and-ci 2.28** — absorbs:
  * 1.14: the shim, vendor branch only (`uv run --project .l4/vendor l4 "$@"`). The `uvx --from git+URL@SHA` branch
    waits for Q1;
  * 1.20, reduced: the pin is the commit of `L4_HARNESS_URL` at `--ref`, or its HEAD; a local path is allowed; no
    `v<version>` tag lookup. As built: only a local checkout at its HEAD; `L4_HARNESS_URL` and `--ref` are M1.

**Risks**

* An M0 PASS is weaker than the M1 definition, because of the traceability override above.
* The M0 sandbox deltas (`--proc /proc`, tmpfs over the other CLI's credential paths) and the read-write uv cache
  bind of G2 have not been tried on the runner [I]. The Stage B exit probe has to prove them before any live run
  that has `L4_FORGE_TOKEN` set.
* Codex blocked-detection is not reliable on low effort (spike 03), so the `add-vat` check in G6 is informational
  only.

## M1.1 — close the human loop (selected 2026-10-04)

M1.1 makes the loop of M0 close without anyone setting `L4_UNIT`. The CI job starts by itself when there may be work,
and does nothing when there is none. A blocked unit goes to an LLM clarifier first, then to a human. A committed answer
resumes the unit. Ledger events after the hand-off stay off the MR head. A merged unit gets its archive-only MR. The
harness is upgraded in place. Starting point: M0 as built (`docs/plan/m0-progress.md`) and as run live
(`docs/live/README.md`). Several M0 simplifications are deepened here.

**Size: 41 build lines = 34 tasks + 7 gap tasks (G7–G13), in three sequential stages.** Absorbed tasks are named
inside their line.

**Decisions**

* **Routing (1): one routed job `l4`, not `l4-detect` + child pipeline.**
  * `l4 run` without `--unit` already plans and runs every actionable unit in sequence, with the most-severe exit
    [V, `src/l4/orchestrator.py` `run_command`]. The routed job is therefore one template line (26).
  * The drafted design needs about six lines: forge-and-ci 1.12, 1.16, 1.17 and 1.18, plus bootstrap-core 1.17 and 1.19.
    It also rests on three unverified facts on 17.5.2 CE: U-1 (exit codes through `strategy: depend`), U-2 and U-4.
  * Behaviour costs of the drafted design:
    * every push to `main` would start a child pipeline, a no-op job included;
    * a failing `.pre` detect job would hold back the repository's own stages [I]. M0 moved its job to `.post` with
      `needs: []` for exactly this reason.
  * What the child pipeline buys (per-unit jobs, parallel units) cannot be used on one runner with 4 vCPU and 3.8 GB.
  * This deviates from the shape in SPEC §16.3 (doc change owed, see Gaps).
* **Ledger after H (5): a pending ledger in lock-ref commits (L4-STA-004), without the lease protocol.**
  * After H, the run's tail lines (`pr.updated`, `phase.changed → in_review`, `lock.released`, `run.finished`) and
    every later run's lines go into `ledger-pending/<run-id>.jsonl` in a commit on `refs/l4/locks/<fw>/<name>`. That
    commit carries `[skip ci]` and `L4-Run` and is never a PR head. The post-merge archive commit folds the pending
    files in.
  * The lock commit message already has the L4-LCK-001 JSON fields, so M2 leasing can take the ref over.
  * Rejected alternatives:
    * writing the `in_review` event into H before the push records an event that has not happened yet;
    * not pushing the tail loses L4-STA-002 reproducibility: another runner folds `verified` and hands off again;
    * a `[skip ci]` ledger commit on the branch becomes the MR head, and GitLab then skips the head's pipeline. This is
      why M0 dropped `[skip ci]` there, which made the head CI-visible.
  * Custom refs are [U] on the reference server, so G7 probes them first.
* **Clarifier (3): tool-less, through the agent adapter.**
  * The runner has no API keys. `BackendClarifier` therefore runs over the G3 `AgentJudge` (claude-code in judge
    mode). Code reaches it as line-numbered excerpts.
  * Without S1 nothing is auto-accepted (L4-CLR-002 rule 5). So the opt-in `s1_standin: llm_boolean` judge also runs
    over `AgentJudge` on `roles.s1_judge` (G10).
  * Product questions stay `open` with a suggestion. Only questions that both the implementer and the clarifier call
    `technical`, with confidence `high`, resolving citations and S1 agreement, become `answered-by-clarifier`.
* **Seeds: `add-vat` is reset and re-seeded.**
  * Why reset:
    * its M0 Q-001 predates the clarifier, and SPEC 12.0 has no edge `awaiting_human → clarifying`;
    * its branch carries the M0 template, whose job needs `$L4_UNIT`, so a human push there would start nothing.
  * The re-seed adds two scenarios with the same WHEN and a different Romanian rate. Q-001 (a VAT-rate question, so a
    product decision) is then raised by the L4-ODD-004 lint before any agent runs. This is deterministic, whereas
    Codex reported `blocked` on the plain prompt in only 1 of 3 runs [V, spike 03]. It also proves (6) live.
  * A lint question is `ambiguous` by SPEC and can never be auto-accepted. The clarifier's own auto-answer is
    therefore proven on a third change with a purely technical open question (`add-average-price`).

Line format: `change-id task — what M1.1 builds`. Lines are numbered in build order across the stages.

### Stage A — questions, re-entry, intake lint

1. G7 (gap) — probe custom-ref pushes by `l4-bot` on 17.5.2; the result fixes the namespace of line 27
2. spec-providers 1.28 — tolerant `QuestionsFile.parse`:
   * spans for the index, sections, fields and subsections;
   * Status is case-insensitive;
   * a missing index is regenerated;
   * unknown sections are left untouched.
3. spec-providers 1.29 — `is_answered`, `effective_answer` (`accepted` and `answered-by-clarifier` use the suggestion),
   `blocked_tasks`. A non-empty Answer under `open` is a draft (`question.unsubmitted_answer`) and is never consumed
4. spec-providers 1.34 — `set_status` / `set_suggestion`: they write only the Status line and the *Clarifier suggestion*
   block, regenerate the index row and keep every other byte
5. implementer-tdd-loop 1.11 — `select_next_step` skips a leaf blocked by an unanswered question and signals "none
   eligible, questions open"
6. state-vcs-locks 1.20 — `TRANSITIONS` gains these SPEC 12.0 rows, and M0's `rerun_requested` stand-in is removed:
   * `implementing → clarifying`;
   * `clarifying → implementing | awaiting_human`;
   * `awaiting_human → implementing` on `answers_submitted`;
   * `in_review → merged`.
7. implementer-tdd-loop 1.27 — `Orchestrator` drives the new rows:
   * open questions without a `clarifier.result` go to `clarifying` first, before the "no eligible task" row (to
     `awaiting_human` when the clarifier is disabled or absent);
   * re-entry happens only when answers unblock at least one eligible task;
   * `--unit` no longer forces re-entry.
8. clarification-loop 1.17 — `Clarifier.reenter`:
   * newly answered ids, with `by`;
   * `question.answered{by, answer_sha256}`;
   * drafts surfaced;
   * a consumed answer whose hash changed → `question.override`.
9. clarification-loop 1.16 — `render_answer_blocks`: `<l4:data kind="answer" id by>`, redacted first, closing tag
   neutralised, consumed hashes
10. implementer-tdd-loop 1.13 — `PromptContext.data_blocks` carries the answer blocks into red and green prompts, in SPEC
    order; the prompt hash covers them
11. implementer-tdd-loop 1.14 — `contract@2`, two new rules:
    * the implementer never decides an item listed under a change's "Open questions": it reports blocked, one question
      per item, with the kind the item is labelled with;
    * business data the spec leaves open (rates, prices, legal values) is a `product` question.
12. simulation-harness 1.15 — `LiveUnitSource` reads `questions.md` from the unit branch beside tasks and ledger (G4
    path): `open_blocking_questions`, `answers_unblock`
13. simulation-harness 1.13 — next-action table; no path probes:
    * `awaiting_human` whose answers unblock a task → `implement` ("answers submitted: Q-…");
    * `clarifying` → `clarify`;
    * any other `awaiting_human`, and `in_review` → `none`.
14. G8 (gap) — fetch `--prune` of the unit branches and lock refs before every fold and every worktree
15. G9 (gap) — L4-ODD-004 scenario-conflict lint at intake

*Exit:* unit tests pass. On the fixture repo with a bare remote, `FakeAdapter` and no clarifier:

* blocked → Q-001 → exit 11;
* an answer committed to the remote unit branch with Status `answered`:
  * `l4 plan --json` says `implement` ("answers submitted: Q-001");
  * `l4 run` re-enters, and the red prompt carries `<l4:data kind="answer" id="Q-001" by="human">`;
  * red → green, and Q-001 is not raised again;
* the same answer with Status still `open` leaves the plan at `none`;
* a conflicting scenario pair → Q-001 (`ambiguous`, asked by the intake lint) and no agent step (no `agent.session`,
  no `task.started`); the implementer probe at `ready` still runs;
* a remote unit branch deleted after an earlier fetch → the unit plans as new, and its worktree starts from base.

### Stage B — clarifier (LLM first, tool-less through the agent adapter)

16. G10 (gap) — `roles.clarifier` and `roles.s1_judge` take adapter profiles served by `AgentJudge` (G3); the
    `clarifier` config section becomes typed
17. clarification-loop 1.1 — `l4/clarifier-answer@1` + `validate_answer`; absorbs 1.2 (ports, `QuestionView`,
    `ClarifyOutcome`, `SpecQuestionsPort` over line 4)
18. clarification-loop 1.3 — `ContextBuilder.build_prompt`: question, unit documents, base specs and answered
    questions, all in `<l4:data>` blocks. Absorbs 1.4: code excerpts with line numbers, `git grep -l -F` ranking and a
    budget. These excerpts are all the code the tool-less clarifier sees
19. clarification-loop 1.5 — `BackendClarifier.answer` over `AgentJudge.complete_structured` (`claude -p --json-schema …
    --tools ""`), one repair, `invalid` after the second failure
20. clarification-loop 1.7 — `resolve_citation`:
    * the path is relative and inside the repo;
    * `#L<n>` and `#L<a>-L<b>`;
    * the quote must be within ±2 lines;
    * traversal is refused.
21. clarification-loop 1.9 — `LlmBooleanJudge` on the `s1_judge` chain when `s1_standin: llm_boolean`: schema
    `{"answer": boolean}`, mapped to 1.0 or 0.0. Absorbs 1.8 (the verbatim S1 questions, `trim_state`)
22. clarification-loop 1.10 — `Router.route`: the five L4-CLR-002 conditions, with the failed reasons collected. S1 is
    asked only when conditions 1, 2 and citation resolution already hold
23. clarification-loop 1.12 — `Clarifier.run`: either `answered-by-clarifier` plus citations, or a suggestion with Status
    `open`. Absorbs:
    * 1.11: skip `verdict` questions, cap the batch;
    * 1.13: unavailable or invalid twice → exit 11, never 12;
    * 1.14: `clarifier.result` and `question.answered{by: clarifier}`.
24. forge-and-ci 1.7 — `upsert_sticky_note` (marker `<!-- l4:sticky -->`, no write when the body is unchanged), fed by
    clarification-loop 1.15 `build_sticky_section` through `mirror_hook`
25. clarification-loop 1.19 — `clarify_hook`, resolved lazily:
    * `reenter` at run start;
    * `Clarifier.run` on `implementing → clarifying`;
    * commit `docs(<unit>): clarifier [skip ci]` and push;
    * the outcome goes back to the orchestrator.

*Exit:* with a fake `complete_structured` backend:

* implementer and clarifier kind `technical`, confidence `high`, resolving citations and an S1 "no"/"yes" →
  `answered-by-clarifier`, and the same run goes on to green;
* implementer kind `ambiguous` or `product` → a suggestion, Status `open`, exit 11 and a sticky section;
* backend unavailable → exit 11 with the "clarifier unavailable" sentence.

Also one `L4_LIVE=1` smoke test of both schemas against the real `claude`, as G3 had.

### Stage C — routing, ledger after H, post-merge archive, upgrade, minors

26. forge-and-ci 1.15 — the template has one job, `l4`:
    * job settings: `stage: .post`, `needs: []`, `tags: [agentic]`, `resource_group: l4`, `interruptible: false`,
      `timeout: 180m`, `allow_failure.exit_codes [10, 11, 12]`, `GIT_DEPTH "0"`;
    * `rules:`, in order:
      * `when: never` for a push whose message matches `/\nL4-Run: /`;
      * a push to `$CI_DEFAULT_BRANCH`;
      * a push to `l4/**`;
      * the sources `schedule`, `web`, `api` and `trigger`;
    * on any other branch, a git one-liner in `before_script` checks out the fetched default branch, so harness and
      config come from the base head (the intent of L4-CFG-004);
    * script: `l4 doctor`, `l4 plan --sweep`, `l4 run` (no `--unit`, no `L4_UNIT`), each line `|| l4 ci map-exit $?`;
    * with nothing actionable, `l4 run` logs `nothing to do` and exits 0 before any lease, worktree or probe.
27. state-vcs-locks 5.4 — `PendingLedger.publish(run_file)`, absorbing 2.1 in reduced form:
    * a lock commit whose first line is the L4-LCK-001 JSON, with `[skip ci]` and `L4-Run`;
    * its tree is the previous pending files plus `ledger-pending/<run-id>.jsonl`, built with git plumbing only;
    * pushed with `--force-with-lease=<ref>:<expected>` to `refs/l4/locks/<fw>/<name>`, or to `l4-lock/<fw>/<name>`
      if G7 says so.
28. state-vcs-locks 5.5 — the fold reads the unit branch (or the base checkout) plus the pending files:
    * events merge by `(run_id, seq)`;
    * a pending file extends the branch copy of its run;
    * a different payload under the same key is `corrupt`.
29. forge-and-ci 2.43 — `Orchestrator.close`: once H is pushed, the run's tail goes to line 27, never to the unit
    branch. M0's `chore(<unit>): ledger` commit after H is removed (SCN-CI-18)
30. forge-and-ci 1.31 — GitLab `get_pr` / `list_prs`: states `opened | merged | closed` and `merge_commit_sha`
31. forge-and-ci 1.32 — `MergeDetector.classify`: whether a unit is archived is read from the tree at `merge_commit_sha`
32. spec-providers 1.23 — `done_gate` first, then `archive <id> --yes --json` with `TZ=UTC`. `--yes` skips the task
    check, and the whole folder moves, `.l4/` included [V, spike 04]
33. forge-and-ci 1.33 — `PostMergeArchiver.open_archive_pr`, absorbing state-vcs-locks 5.6 in reduced form:
    * branch `l4/archive/<fw>/<name>` from the latest base;
    * line 32;
    * the pending ledger folded into the archived `.l4/ledger/`;
    * one commit `chore(<unit>): archive`, with no `[skip ci]` and with `L4-Run`;
    * push, then a ready MR `[l4] archive <name>`.
34. forge-and-ci 1.34 — an archive build that changed a path outside the unit's archive paths → `archive.failed`, no MR
35. forge-and-ci 1.35 — archive MRs are serialised: no second one while one is open, and the next one is built on the
    new base
36. forge-and-ci 1.36 — a minimal `Sweeper` behind `l4 plan --sweep`: an `in_review` unit whose MR merged → `merged`
    (pending ledger) → line 33, once. Also the `l4 archive --unit ID` handler
37. G11 (gap) — `l4 upgrade`
38. G12 (gap) — a protected-branch or push-rule refusal is a forge error, not a non-fast-forward
39. verifier 1.5 — judge prompt `judge@2`: counterexamples are recorded for a human, and the prompt no longer claims the
    harness runs them
40. forge-and-ci 1.10 — `render_pr_title` from the proposal's `# ` heading minus a leading `Proposal:` (the Why line is
    the fallback). `render_pr_body` never contains an `L4-Run:` line
41. G13 (gap) — live acceptance test of the protocol below

*Exit:*

* unit tests pass;
* forge-and-ci 1.40, reduced to a fake forge and a bare remote:
  * the hand-off leaves the branch head at H and the tail in the lock ref;
  * a merged MR gives one archive MR whose diff is only the archive move;
  * a second sweep is a no-op;
  * a second merged unit waits for the first archive MR;
* `l4 upgrade` on a copy of dummy-agentic changes only `.l4/vendor/`, `.l4/ci/`, `.l4/bin/l4` and the two pin scalars;
* G7 is recorded.

Then the live protocol (G13).

### Gaps (no existing task covers them; no tasks.md was edited)

* **G7** (Stage A, first; state-vcs-locks, live) — Probe custom-ref pushes from a CI job on `l4/probe-runner` (tags
  `[agentic]`, `L4_FORGE_TOKEN` through the M0 credential helper and the `oauth2@` push URL). The job pushes a commit to
  `refs/l4/doctor/<nonce>` with `--force-with-lease=refs/l4/doctor/<nonce>:`, lists it with `git ls-remote`, deletes
  it with a lease, and records [V] — test: scripts/runner/ci-probe-refs.sh (job log saved under docs/runner/) — code:
  scripts/runner/ci-probe-refs.sh — verify: the log shows the push, the ls-remote line and the delete.
  * If any step is refused, line 27 targets the branch `l4-lock/<fw>/<name>` (L4-LCK-002).
  * Why: custom refs on 17.5.2 CE are [U] (research/06: "hosts generally accept custom refs [D]"). Line 27 should build
    one namespace, not two.
* **G8** (Stage A; state-vcs-locks) — Fetch the remote refs with `--prune` before folding and before
  `WorktreeManager.ensure`:
  * refspecs `+refs/heads/<branch_prefix>*:refs/remotes/origin/<branch_prefix>*` and `+refs/l4/locks/*:refs/l4/locks/*`
    (or `l4-lock/*`, per G7);
  * in CI (`GITLAB_CI=true`), once per process, through the M0 fetch credential config;
  * folding means `l4 plan`, `l4 status` and `l4 run`;
  * a local run still reads local refs, as in M0.

  test: tests/unit/state/test_status_branch.py::test_deleted_remote_unit_branch_is_pruned_before_fold (also
  tests/unit/vcs/test_worktree.py::test_pruned_branch_is_not_resurrected) — code: src/l4/state/status.py,
  src/l4/vcs/worktree.py — verify: uv run pytest tests/unit/state/test_status_branch.py tests/unit/vcs/test_worktree.py -q
  * Why:
    * the shell runner reuses its clone [V, job 5428 "Reinitialized existing Git repository"];
    * `ensure` fetches without `--prune`;
    * the project deletes merged source branches (`remove_source_branch_after_merge: true` [V, API]);
    * step 3 below deletes `l4/openspec/add-vat`.

    A stale `origin/l4/openspec/add-vat` would fold the old ledger and bring the deleted branch back. Custom refs are
    outside the default refspec.
* **G9** (Stage A; implementer-tdd-loop, L4-ODD-004) — `scenario_conflicts(unit, base_specs)` finds pairs with an
  equal normalised WHEN and a different THEN, within the change and against `openspec/specs/**`. Normalisation is that
  of spec-providers 1.24, and code spans are compared verbatim. At intake, on every run and before any agent or probe,
  each new pair raises one `ambiguous` question:
  * Asked: `intake lint (L4-ODD-004)`;
  * Context: both scenarios with their THEN lines;
  * Blocking: every task citing either criterion. Without an OpenSpec task → criterion link, that is every task.

  The questions are committed as `docs(<unit>): questions [skip ci]`. A pair that already has a question, in any
  Status, is not raised again — test: tests/unit/gates/test_scenario_lint.py::test_same_when_different_then_raises_one_ambiguous_question
  (SCN-ODD-08; also ::test_clean_change_raises_nothing SCN-ODD-09, ::test_conflict_with_base_spec,
  ::test_existing_pair_not_reraised) — code: src/l4/gates/odd.py — verify: uv run pytest tests/unit/gates/test_scenario_lint.py -q
  * Why: no task of any change covers L4-ODD-004, which reached SPEC from spike 03.
* **G10** (Stage B; agent-factory + clarification-loop) — `roles.clarifier` and `roles.s1_judge` take adapter profiles
  served by `l4.llm.agent_judge.AgentJudge.complete_structured`, resolved through `Factory.for_role`. The `clarifier`
  config section becomes typed (a bootstrap-core 1.4 delta): `enabled`, `auto_accept_kinds`, `min_confidence`,
  `max_open_questions`, `s1_router`, `s1_standin`. Preflight refuses `s1_standin: llm_boolean` with an empty
  `s1_judge` chain (exit 2) — test: tests/unit/llm/test_agent_judge_roles.py::test_clarifier_and_s1_roles_resolve_adapter_profiles
  — code: src/l4/llm/agent_judge.py, src/l4/agents/factory.py, src/l4/config/schema.py — verify: uv run pytest tests/unit/llm/test_agent_judge_roles.py tests/unit/config -q
  * Why: clarification-loop 1.5 and 1.9 assume an `LLMBackend` (`openai-chat`), but the runner has subscription logins
    only [V, docs/runner/README.md]. Without this gap the clarifier can only write suggestions.
* **G11** (Stage C; forge-and-ci) — `l4 upgrade [--harness PATH] [--dry-run]`, handler `l4.init.upgrade:run_upgrade`
  (a new `commands.HANDLERS` row and `cli.py` entry):
  * refuse without `.l4/config.yaml` (exit 2, "run l4 init");
  * re-vendor `.l4/vendor/` from the harness checkout at HEAD with `l4.init.vendor`, swapped in atomically;
  * re-render `.l4/ci/l4.gitlab-ci.yml` and `.l4/bin/l4`;
  * in `.l4/config.yaml`, rewrite only the `harness.version` and `harness.commit` scalars and keep every other byte;
    then reload the file through `load_config`;
  * never touch `.gitlab-ci.yml`;
  * print the changed files, and the config keys the new version knows that the file lacks.

  test: tests/unit/init/test_upgrade.py::test_upgrade_refreshes_vendor_and_ci_and_keeps_config_bytes (also
  ::test_dry_run_writes_nothing, ::test_no_config_exits_2) — code: src/l4/init/upgrade.py — verify: uv run pytest tests/unit/init/test_upgrade.py -q
  * Why: in M0 an upgrade meant `l4 init --force`, which rewrites the human-owned config.
* **G12** (Stage C; state-vcs-locks + forge-and-ci) — Classify push refusals:
  * `Git.push` raises `PushRejected` only for `! [rejected] … (non-fast-forward | fetch first)`;
  * `! [remote rejected]` and pre-receive messages go through `explain_push_failure` as a forge refusal:
    * exit 3 with "the forge refused the push (protected branch or push rule)" when a permission marker matches;
    * else exit 1 naming the server's reason;
    * never "non-fast-forward".

  test: tests/unit/forge/test_pushfail.py::test_protected_branch_refusal_is_not_non_fast_forward (recorded GitLab
  stderr for both cases) — code: src/l4/vcs/git.py, src/l4/forge/pushfail.py — verify: uv run pytest tests/unit/forge/test_pushfail.py tests/unit/vcs -q
  * Why: `git.py` maps `[remote rejected]` to `PushRejected`, and `pushfail.py` tests for `PushRejected` before the
    permission markers [V, code].
* **G13** (Stage C exit, live; live-validation) — The checks of the protocol below as code: one test per step, reading
  pipelines, jobs, MRs, labels, notes, branches, refs and files through the read-only API and `git ls-remote`, and
  recording ids — test: tests/live/test_m1_1_acceptance.py (marker `live`, needs `L4_LIVE=1`) — code:
  tests/live/test_m1_1_acceptance.py — verify: L4_LIVE=1 uv run pytest tests/live/test_m1_1_acceptance.py -m live -q
  * Why: clarification-loop 1.20, forge-and-ci 1.40 and live-validation target `add-greeting` and the M1 pipeline, not
    this protocol.
* **Doc changes owed** (no build line; SPEC.md is not edited here):
  * §2.1 gains `l4 upgrade`;
  * L4-ARC-002: the title comes from the proposal heading, with the Why line as fallback;
  * §16.3 and L4-CI-001: the single routed job is the M1.1 form;
  * L4-CLR-002 rule 5 and the `clarifier.s1_standin` comment: an adapter profile in judge mode is accepted on
    `s1_judge` and `clarifier`, as G3 did for `judges`;
  * L4-QMD-001: a question may be asked by the intake lint;
  * §2.1: in CI, `l4 plan` and `l4 status` fetch the `l4/` and lock refs first (G8); their side effects are listed
    as "none" today.

### Simplifications (reduced form; what is deferred)

**Stage A**

* **Questions**
  * The re-render of a mangled section from the ledger (`question.restored`, L4-QMD-003) is deferred.
  * Verdict answers (L4-QMD-004) wait for verdict questions (verifier 1.17). NEEDS_HUMAN units stay `awaiting_human`
    without questions; `awaiting_human → verifying` is out.
* **Overrides** — a changed consumed answer is recorded (`question.override` and a sticky line). The
  clarification-apply fix unit (L4-QMD-006, `verified | in_review → fixing`) waits for fix units.
* **`contract@2`** — only the two rules above; the repair and stuck templates stay at M0.
* **Planner** — no `--probe`, no `--detailed-exitcode`, no availability view. There is no `waiting_capacity`
  re-entry: the sweeper duty 2.32 is deferred.
* **G9**
  * Only equal WHEN with different THEN is detected; conflicts between requirement prose and scenarios are unseen [I].
  * A conflict blocks every task, because L4-OSP-008 links are not built.

**Stage B**

* **Clarifier path**
  * Backend (tool-less) path only. The agentic read-only clarifier (1.6, 3.1) and chain fallback (3.2) are deferred.
  * No lessons in the context.
  * The scenario files of 1.18 are replaced by the Stage B exit; 1.20 is replaced by G13.
* **S1**
  * The `llm_boolean` stand-in only; System-One is M2.
  * `max_state_tokens` is counted as characters ÷ 4 [I]; the model tokenizer (2.2) is deferred.
  * S1 calls are skipped when a cheaper condition already blocks, which saves subscription calls.
* **Sticky note** — ids, titles, the link, and the unsubmitted-answer and clarifier-unavailable sentences. The
  configured mentions of L4-CLR-004 are deferred.

**Stage C**

* **Single job**
  * No per-unit `resource_group`, no parallel units (`ci.max_parallel_units` is unused).
  * `l4 doctor` keeps its default scope, which runs no live probe [V, job 5428 log]; `--ci` and `--fix`
    (bootstrap-core 1.20, 1.21) are deferred.
  * Deferred: the outcome dotenv (bootstrap-core 1.19) and forge-and-ci 1.12 and 1.16–1.18.
  * Schedules: covered by the template test only. Creating a schedule is a forge setting.
* **Lock ref** — it carries the pending ledger only. No lease acquire, heartbeat, fencing, takeover or release
  (state-vcs-locks 2.2–2.17). Serialisation stays `resource_group: l4` plus the local flock.
* **Sweeper**
  * The merged duty only, on every l4 job: the merge itself is a push to `main`.
  * Deferred: closed and reopened MRs (2.53), base-move refresh (2.54), capacity and lease resume (2.32), mirror repair
    (2.35), lock-ref and WIP cleanup on merge (2.51).
  * The archive run's tail stays in the lock ref, and no `archive.done` is recorded: the unit leaves the plan when its
    folder leaves `openspec/changes/`.
* **Archive MR** — `auto_merge_archive_pr` and the numbered rebuild of an unmergeable archive MR (2.55) are deferred.
  `-o ci.skip` (1.30) is still deferred, because `[skip ci]` suffices [V, M0].
* **After H** — foreign-commit detection (2.41), `PushGuard` (2.39) and repository CI on H (2.44) are deferred. A
  human push to an `in_review` branch starts the job, which plans nothing.
* **Base checkout**
  * A unit branch cut before an upgrade keeps its own template and vendor, and a push there runs that template. This
    is why step 3 resets `add-vat`.
  * `GitRefSource` (bootstrap-core 2.3) is deferred; the base checkout gives `l4/**` pushes the same trust.
* **G11** — vendor mode only: no `uvx` pin (forge-and-ci 1.14, 1.20). New config keys are reported, never written
  (config is human-owned, L4-CFG-004).

**Risks**

* Step 4a depends on Codex honouring `contract@2`; the protocol has a retry rule.
* If G7 is refused, the pending ledger lives on `l4-lock/` branches, which show in the branch list.
* About 9 Claude calls across steps 4–6 (judge, clarifier, S1) on the `pro` subscription [I]. If the clarifier is
  unavailable, the unit goes to exit 11 with the "unavailable" sentence (L4-CLR-005), and step 4a fails.
* The boolean S1 is uncalibrated (clarification-loop R1). An auto-accepted answer still has to pass red/green and the
  judge.
* U-3 (`/\nL4-Run: /` against the full message) runs live for the first time in steps 2 and 5. M0's job also
  required `$L4_UNIT`, so it never tested it.
* The new units branch from a `main` that already holds the discount code, because step 2 comes before step 4.
  `merge_base_into` (state-vcs-locks 1.27) is still deferred, so merging their MRs in another order later may need a
  human conflict resolution.

### Live exit protocol on `example-group/dummy-agentic`

Facts the protocol relies on [V, API 2026-10-04]:

* `main` is protected (Maintainers push).
* `remove_source_branch_after_merge: true`.
* `build_timeout` is still 3600 s, so the job-level `timeout: 180m` is what applies (a job timeout may exceed the
  project's [V, GitLab docs]; runner #12 has no maximum).
* MR !1 is ready; its head is M0's `chore: ledger` commit `e1a556d`.
* MR !2 is a draft, with Q-001 open.
* No pipeline schedule exists.

Humans merge (maintainer policy): the harness never merges.

0. **Operator, local.** M1.1 is built, `uv run pytest -q` is green, and G7 is recorded.
   * On a clone of `main`, run `uv run --project <harness> l4 upgrade --repo <clone> --harness <harness>`.
   * Expected: changes only under `.l4/vendor/`, `.l4/ci/l4.gitlab-ci.yml` and `.l4/bin/l4`, plus the two pin scalars.
   * Then add by hand to `.l4/config.yaml`:

   ```yaml
   roles:            # existing block; append the two chains
     clarifier:
     - claude-code
     s1_judge:
     - claude-code
   clarifier:
     s1_standin: llm_boolean
   ```

1. **Maintainer** (protected `main`): commit and push "Upgrade the vendored L4 harness to `<sha>` (M1.1)". Expected
   pipeline P1 (push, `main`):
   * one job `l4` on runner #12 with a 3 h timeout;
   * doctor table without LIVE-001;
   * plan: `add-discount-codes in_review none`, and `add-vat awaiting_human none` (old branch, no answer);
   * `l4 run` prints `nothing to do`, exit 0;
   * no `availability.selected` or hello lines, and no push or MR change;
   * job success within about 1 minute [I].

   This proves (1)'s idle case and (7).
2. **HUMAN: merge MR !1** (add-discount-codes) in the UI with the merge-commit method; "Delete source branch" may stay
   ticked. Expected P2 (push, `main`, a merge commit without `L4-Run`):
   * `l4 plan --sweep` sees the MR merged and `openspec/changes/add-discount-codes` still present at the merge commit;
   * `phase.changed in_review → merged` lands in the pending ledger of the unit's lock ref;
   * branch `l4/archive/openspec/add-discount-codes` with one commit `chore(add-discount-codes): archive` (no
     `[skip ci]`, `L4-Run`);
   * archive MR `[l4] archive add-discount-codes`, not a draft. Its diff only moves the folder to
     `openspec/changes/archive/<UTC date>-add-discount-codes/` (`.l4/` and `verification.md` included) and adds
     `openspec/specs/discounts/spec.md`;
   * `l4 run`: nothing to do, exit 0;
   * the archive push's pipeline has the project's `test` job and no `l4` job.

   If the source branch was deleted, the fold reads `main`, which carries the M0 ledger up to `chore: ledger`. Steps 1
   and 2 are order-independent: if !1 is merged first, P1 opens the archive MR.
3. **Operator** (destructive forge state on the dummy repo, under the maintainer's standing permission; not a
   setting): close MR !2 and delete `l4/openspec/add-vat`. Expected: no pipeline.
4. **Maintainer:** commit and push "Seed add-average-price; re-seed add-vat with a VAT-rate conflict" (texts below).
   Expected P3 (push, `main`):
   * the sweep reports the archive MR of step 2 as still open and opens nothing;
   * the plan shows `add-average-price` and `add-vat` as `implement`;
   * `l4 run` takes them in plan order.

   * **4a `add-average-price`:**
     * red → Codex `blocked` with one `technical` question → Q-001 (Blocking 1.1) committed `[skip ci]`;
     * `implementing → clarifying` → Q-001 `Status: answered-by-clarifier`. The suggestion reads `confidence: high ·
       kind: technical (S1 p=0.00)`, answers `Decimal`, and has at least one citation that resolves (`src/pricing/cart.py`
       "unit_price: Decimal" or `openspec/specs/cart/spec.md` "a non-negative unit price (Decimal)");
     * ledger: `clarifier.result{auto_accepted: true}` and `question.answered{by: clarifier}`;
     * `clarifying → implementing` in the same run, and the red prompt artefact in `.l4-out/agent/` contains
       `<l4:data kind="answer" id="Q-001" by="clarifier">`;
     * red → green → PASS → one hand-off commit H (no `[skip ci]`, `L4-Run`);
     * MR `[l4] add-average-price: average unit price`, ready, label `l4:in_review`, and **MR head = H**;
     * `refs/l4/locks/openspec/add-average-price` (or `l4-lock/…`) holds `ledger-pending/<run-id>.jsonl`, ending
       `phase.changed verified → in_review`, `lock.released`, `run.finished`;
     * after_script `l4 status`: `in_review`.
   * **4b `add-vat`:**
     * the first commit on the new `l4/openspec/add-vat` is Q-001 from the intake lint: Kind `ambiguous`, Blocking 1.1,
       1.2, Context naming "Romanian customer" 119.00 against "Romanian customer, current rate" 121.00;
     * no `agent.session` and no `task.started` in the ledger. One codex `availability.selected` from the probe at
       `ready` is expected (SPEC 12.0: "lease acquired and implementer selected"); the lint ran before it, at intake;
     * `clarifying` → a suggestion, Status stays `open`, and `clarifier.result{auto_accepted: false}` with a reason
       naming kind `ambiguous`;
     * → `awaiting_human`: a new draft MR labelled `l4:awaiting_human` and `l4:needs-answers`, with one sticky note
       listing Q-001 and linking `questions.md` on the unit branch.

   * **Job:** exit 11, the most severe of 0 and 11, so the job passes with a warning.
   * **Retry rule:** if 4a has no Q-001 (Codex implemented without asking), reset that unit (close its MR, delete its
     branch and lock ref) and start one web pipeline. A second miss is a FAIL, recorded in `docs/live/`.
5. **No human: loop safety**, checked read-only over the pipelines since step 4:
   * `[skip ci]` checkpoints have no pipeline, or a skipped one;
   * the H push of 4a has one pipeline, with the project's `test` job and **no** `l4` job;
   * the lock-ref push has no pipeline (or a skipped one for an `l4-lock/` branch);
   * no `l4` job ran on a harness-authored commit.
6. **HUMAN: answer Q-001 of add-vat**, in one Web IDE commit on `l4/openspec/add-vat`, e.g. "Answer Q-001: Romanian
   VAT is 21 %":
   * in `questions.md`, under `### Answer`: "RO: 21 % (the rate since 2025-08-01; the 119.00 scenario was outdated and
     is removed from the spec). DE: 19 %. Any other country raises UnsupportedCountry.", and set `**Status:**
     answered`;
   * in `openspec/changes/add-vat/specs/vat/spec.md`, delete the scenario "Romanian customer" (119.00).

   Both edits are needed: an answer alone leaves an unsatisfiable 119.00 criterion, and the verifier returns
   NEEDS_HUMAN.

   Expected P4 (push, `l4/openspec/add-vat`):
   * job `l4` starts (rule: push to `l4/**`), and the log shows the default branch checked out before the shim runs;
   * plan: `add-vat implement` "answers submitted: Q-001"; the lint is clean;
   * ledger: `question.answered{by: human}` and `awaiting_human → implementing`;
   * the red prompt contains `<l4:data kind="answer" id="Q-001" by="human">`;
   * red → green for 1.1 and 1.2 (RO 121.00, DE 119.00, US raises) → PASS → H;
   * MR `[l4] add-vat: VAT on the cart total`, ready, with only `l4:in_review` (`l4:needs-answers` removed); the sticky
     note lists no open question;
   * MR head = H, with a pending ledger in the unit's lock ref;
   * job exit 0.
7. **Operator:** start one web pipeline ("Run pipeline" on `main`, no variables) and one API pipeline (`POST
   /projects/118/pipeline?ref=main`). Expected for both:
   * plan: every unit `none`;
   * no second archive MR;
   * exit 0 within about 1 minute, with no probe.
8. **Optional, HUMAN:**
   * merge the archive MR → the next `main` pipeline no longer lists `add-discount-codes`, exit 0;
   * or merge the add-average-price MR first → "archive pending" and no second archive MR until the first merges
     (serialised, L4-ARC-007); then the next `main` pipeline opens its archive MR.

**Pass** = steps 1–7 behave as expected (8 is optional).

* Human steps: 2 (merge MR !1) and 6 (answer Q-001).
* Maintainer steps: 1 and 4, only because `main` is protected; a human or an operator with the Maintainer role does
  them.
* Operator steps: 0, 3 and 7.

Record every pipeline, job and MR id in `docs/live/README.md`.

**Seed texts for step 4.** The proposal and `.openspec.yaml` of `add-vat` stay unchanged.

`openspec/changes/add-vat/specs/vat/spec.md` (replaces the M0 text):

```markdown
# Spec Delta

## Purpose
VAT is added to the cart total according to the customer's country so that invoices show the right amount.

## ADDED Requirements

### Requirement: VAT by country
`Cart.total_with_vat(country)` SHALL return the cart subtotal plus VAT at the rate of the customer's country, given as an ISO 3166-1 alpha-2 code, quantized to 0.01 with ROUND_HALF_UP. The supported countries are `RO` and `DE`; any other country SHALL raise `UnsupportedCountry`.

#### Scenario: Romanian customer
- **WHEN** a customer from `RO` has a cart subtotal of 100.00
- **THEN** the total with VAT is 119.00

#### Scenario: Romanian customer, current rate
- **WHEN** a customer from `RO` has a cart subtotal of 100.00
- **THEN** the total with VAT is 121.00

#### Scenario: German customer
- **WHEN** a customer from `DE` has a cart subtotal of 100.00
- **THEN** the total with VAT is 119.00

#### Scenario: Unsupported country
- **WHEN** a customer from `US` has a cart subtotal of 100.00
- **THEN** `UnsupportedCountry` is raised
```

`openspec/changes/add-vat/tasks.md` (replaces the M0 text):

```markdown
# Tasks

## 1. VAT

- [ ] 1.1 Add `src/pricing/vat.py` with the VAT rates of the supported countries (`RO`, `DE`) and `UnsupportedCountry`
- [ ] 1.2 Add `Cart.total_with_vat(country)` (subtotal plus VAT, ROUND_HALF_UP to 0.01) and export the new names from `pricing`
```

`openspec/changes/add-average-price/.openspec.yaml`:

```yaml
schema: spec-driven
created: 2026-10-04
```

`openspec/changes/add-average-price/proposal.md`:

```markdown
# Proposal: average unit price

## Why
Sales reports need the average price paid per unit in a cart.

## What Changes
- Add `Cart.average_unit_price()`: the subtotal divided by the total quantity of the line items, quantized to 0.01 with ROUND_HALF_UP; an empty cart raises ValueError.

## Capabilities

### New Capabilities
- `cart-stats`: figures computed from a cart for reports.

### Modified Capabilities

## Impact
`src/pricing/cart.py` (`average_unit_price`), tests under `tests/`.
```

`openspec/changes/add-average-price/design.md`. This is the purely technical ambiguity: the repository answers it,
since the cart spec and `LineItem` use `Decimal`.

```markdown
# Design: average unit price

## Open questions
- (technical) Should `Cart.average_unit_price()` return a `Decimal` or a `float`?
```

`openspec/changes/add-average-price/specs/cart-stats/spec.md`. The "Empty cart" WHEN differs on purpose from the base
`cart` scenario "the cart has no items" (THEN "the subtotal is 0"), because G9 compares WHENs against the base specs:

```markdown
# Spec Delta

## Purpose
Figures computed from a cart's line items for sales reports.

## ADDED Requirements

### Requirement: Average unit price
`Cart.average_unit_price()` SHALL return the cart subtotal divided by the total quantity of its line items, quantized to 0.01 with ROUND_HALF_UP. For a cart without line items it SHALL raise ValueError.

#### Scenario: Two single items
- **WHEN** the cart holds a line item at 1.00 with quantity 1 and a line item at 4.00 with quantity 1
- **THEN** the average unit price is 2.50

#### Scenario: Quantities are weighted
- **WHEN** the cart holds a line item at 1.00 with quantity 3 and a line item at 5.00 with quantity 1
- **THEN** the average unit price is 2.00

#### Scenario: Half a cent rounds up
- **WHEN** the cart holds a line item at 0.05 with quantity 1 and a line item at 0.00 with quantity 1
- **THEN** the average unit price is 0.03

#### Scenario: Empty cart
- **WHEN** the average unit price of a cart without line items is requested
- **THEN** ValueError is raised
```

`openspec/changes/add-average-price/tasks.md`:

```markdown
# Tasks

## 1. Average unit price

- [ ] 1.1 Add `Cart.average_unit_price()` (subtotal divided by total quantity, ROUND_HALF_UP to 0.01, ValueError for an empty cart)
```
