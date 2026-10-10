## Context

SPEC §4 to §6 and §4.6 define everything the harness needs to know about spec units: which frameworks are present, a provider interface, an OpenSpec adapter that shells out to a pinned CLI, a native Kiro adapter, a single byte-safe writer for task markers (principle P4), stable criterion IDs, and the `questions.md` file humans answer in. The code lives in `src/l4/specs/` (see docs/plan/implementation-map.md) and one doctor module. Facts below carry SPEC's evidence labels: [V] verified by running or reading shipped code, [I] inferred, [U] unverified.

Observed while drafting this change with OpenSpec 1.14.0 [V, run 2026-10-03]:

- JSON goes to stdout and config warnings go to stderr, so the provider parses stdout only. This repository's own `openspec/config.yaml` currently produces a "Rules for 'specs' must be an array of strings" warning on stderr (unquoted `: ` in rule items); the CLI ignores those rules.
- `validate <id> --strict --json` returns `{"items":[{"id","type","valid","issues":[],"durationMs"}],"summary":{...},"version":"1.0","root":{"path","source"}}`; `root.source` was `"nearest"` here.
- `archive --help` lists `--yes`, `--skip-specs`, `--no-validate`, `--json`, `--store <id>`.
- `show <id> --type change --json` fails with `show_error` while `proposal.md` is missing, so `load()` must not depend on it for units that are still being written.

## Goals

- One deterministic answer to "which frameworks, which units, which tasks, which criteria" that does not execute repository-controlled code.
- A marker writer that cannot corrupt `tasks.md`: one byte changes, atomically, under a lock, verified.
- A `questions.md` reader/writer that touches only harness-owned regions and tolerates human editing.
- Walking skeleton (M1) usable by the other changes early: detection, OpenSpec list/validate/tasks/archive and fix units (the M1 verifier needs them), marker writer, criteria IDs, `questions.md` parse/write including Status and suggestion edits. Kiro follows in M2.

## Non-Goals

- Executing Spec Kit units (detected and reported only, SPEC §0.1).
- Ledger storage, locks, branches (state-vcs-locks). This change defines two small ports it consumes (`QuestionLedger`) and emits plain return values, not log events.
- The `l4` command wiring (`plan`, `run`, `doctor` output): bootstrap-core and simulation-harness own the commands; this change supplies the functions they call.
- Wiring the post-step guard into the implementer loop (implementer-tdd-loop). This change ships `markers.check_tasks_guard`.
- Writing verifier findings or choosing fix-unit content beyond the scaffold (verifier). `Finding` and `SpecDelta` are minimal dataclasses here and may be extended there.

## Decisions

### D1. Module and type layout (`src/l4/specs/`)

| Module | Public names |
|---|---|
| `base.py` | `Framework` (StrEnum `openspec`, `kiro`), `UnitRef(framework, name, path, archived)` with `.id == "<framework>:<name>"`, `Detection`, `TaskState` (StrEnum `not_started`, `queued`, `in_progress`, `done`), `Marker` (StrEnum `" "`, `"~"`, `"-"`, `"x"`), `Task(key, number, title, state, marker_char, optional, depth, parent_key, children, line, marker_offset, is_leaf, requirement_refs)`, `Unit`, `Criterion(id, alias, framework, capability, requirement, text, source_path, source_line)`, `ValidationIssue(level, path, message)`, `ValidationReport(valid, issues)`, `GateReport(passed, reasons)`, `ArchiveReport(archived, archived_as, moved_to)`, `Finding`, `SpecDelta`, `SpecProvider` (`typing.Protocol`, `runtime_checkable`), `ProviderRegistry` (`register`, `get`, `for_unit`) |
| errors in `base.py` | `SpecError` base; `ProviderContractError`, `ForeignRootError`, `OpenSpecUnavailable`, `DisallowedSubcommand`, `ArchiveRefused`, `MarkerNotAllowed`, `MarkerWriteError`, `ParentHasOpenChildren`, `FixUnitExists`, `TooManyQuestions`, `NoFrameworkError` (carries exit code 14 `rejected`) |
| `detect.py` | `detect_frameworks(repo, spec_cfg) -> DetectionResult`, `primary_framework(result, units, configured, mtimes) -> Framework`, `require_framework(result, enforce) -> None` (raises `NoFrameworkError`), `collect_units(repo, spec_cfg, registry, include_archived=False) -> list[UnitRef]` |
| `markers.py` | `Line`, `split_lines(data: bytes) -> list[Line]`, `path_lock(path) -> ContextManager`, `write_marker(path, offset, old, new) -> MarkerWrite`, `check_tasks_guard(pre: bytes, post: bytes, allowed_offsets) -> GuardResult`, `restore_tasks(path, pre: bytes, allowed_offsets)` |
| `openspec.py` | `OpenSpecCli`, `CliResult`, `OpenSpecProvider`, `parse_openspec_tasks(data: bytes) -> list[Task]`, `OPENSPEC_TASK_RE` |
| `kiro.py` | `KiroProvider`, `parse_kiro_tasks(data: bytes) -> list[Task]`, `KIRO_TASK_RE`, `read_waves(text) -> Waves | None`, `order_leaves(tasks, waves)` |
| `criteria.py` | `normalise(text) -> str`, `criterion_id(framework, container, requirement, leaf) -> str`, `openspec_criteria(unit_dir)`, `kiro_criteria(spec_dir)`, `write_criteria_json(unit_dir, unit_id, criteria)`, `trace_ids(case: ReportedCase) -> set[str]`, `find_orphans(test_ids, known_ids) -> list[str]` |
| `questions.py` | `Question`, `QuestionStatus`, `QuestionKind`, `QuestionsFile` (`load`, `parse`, `raise_questions`, `set_status`, `set_suggestion`, `restore_missing`, `index_regenerated`), `QuestionLedger` (Protocol: `raised_section(qid) -> str | None`, `consumed_hash(qid) -> str | None`), `QuestionIssue`, `is_answered`, `effective_answer`, `blocked_tasks`, `answer_sha256` |
| `src/l4/doctor/checks_spec.py` | `check_spec_001` .. `check_spec_006` registered with bootstrap-core's `l4.doctor.registry.register(Check(...))` |

Alternative for `SpecProvider`: an abstract base class. Rejected: SPEC §4.3 specifies a `Protocol`, the fake provider in simulation-harness must satisfy it without inheriting, and `ProviderRegistry.register` checks member presence at runtime (L4-SPI-001, SCN-DET-N14).

### D2. Detection (L4-DET-001..003)

`detect_frameworks` uses only `Path.exists`, `Path.is_dir` and `Path.iterdir`; it never spawns a process. Rules are SPEC §4.1 verbatim: OpenSpec by `openspec/config.yaml|yml` or `openspec/specs/` or `openspec/changes/`; legacy OpenSpec when `openspec/project.md` exists and no config file exists (reported with `legacy=True`, `supported=False`); Kiro when some `.kiro/specs/<name>/` holds one of the four files (`.kiro/` alone and `.kiro/prompts|skills` do not count); Spec Kit when `.specify/` plus `memory/constitution.md`, `init-options.json` or `templates/`; a bare `specs/` folder never counts. A repository with `openspec/specs/` only (no config) is OpenSpec >= 1.0 by SPEC's signal list; the provider's root check (D4) then decides whether the CLI agrees, which keeps SCN-DET-08 honest.

`primary_framework` implements `spec.primary` explicitly, else for `auto`: framework with active units, then newest mtime, then `openspec` before `kiro`. It is called only by code creating a spec with no parent. Fix units resolve their parent's provider through `ProviderRegistry.for_unit(unit_ref)`.

`require_framework(result, enforce)` raises `NoFrameworkError("... run `l4 init`")` when `enforce` and no supported framework exists (legacy OpenSpec counts as unsupported); the CLI maps it to exit 14. Scenarios that say `l4 plan --json` are asserted at function level here (`collect_units`) and again through the CLI once simulation-harness lands `l4 plan`.

Alternative: shell out to `openspec` to detect. Rejected: SPEC requires filesystem-only detection and the CLI itself walks to ancestor roots.

### D3. OpenSpec CLI isolation (L4-OSP-001, L4-OSP-002)

`OpenSpecCli(repo, cache_dir, version, package="@fission-ai/openspec", runner=run_process)`:

- `prefix = cache_dir / "tools" / f"openspec-{version}"`, `binary = prefix / "node_modules/.bin/openspec"`; `cache_dir` is bootstrap-core's `l4.config.defaults.cache_root(environ)`, the same prefix runner-provisioning installs into.
- `ensure_installed()` runs, when the binary is missing, exactly `npm install --prefix <prefix> @fission-ai/openspec@<version>` with cwd set to the prefix parent (never the repo) and raises `OpenSpecUnavailable` with the command and stderr on failure. It never falls back to `PATH`, `npx` or the repo's `node_modules`. Whether the install adds `--ignore-scripts` is left as SPEC states it (no extra flags); see Risks.
- `run(args)` checks `args` against the allowlist (D3a) and executes `[binary, *args]` with cwd = repo root and env built from scratch: `PATH` = runner-provisioning's `l4.provision.runner.harness_path(...)` (L4-PRV-016, so a user-local Node under `$L4_HOME/node/bin` is found; entries that live inside the repo or worktree removed), `HOME`, `LANG`, `TMPDIR`, plus `TZ=UTC`, `DO_NOT_TRACK=1`, `OPENSPEC_NO_UPDATE_CHECK=1`. It parses stdout as JSON when `--json` was passed and records the argv and env on `CliResult` so tests can assert command lines (SCN-DET-09).
- Every JSON reply that carries `root` is checked by `verify_root(reply, repo)`: `root.source == "nearest"` and `Path(root.path).resolve()` equals the repository root or its `openspec/` directory. SPEC says the reported path equals the `openspec/` directory, but 1.14.0 reports the project directory (the parent of `openspec/`) [V, run]; both forms are accepted and anything else is foreign. `ForeignRootError` is raised on any mismatch, including `source in {"declared","store","global_default","implicit"}`. Doctor `SPEC-003` calls the same function.

D3a allowlist (exact argv shapes, the placeholders are the only variable parts):

| Operation | argv after the binary |
|---|---|
| list changes | `list --json` |
| show | `show <id> --type change --json` |
| validate | `validate <id> --strict --json` |
| task progress | `instructions apply --change <id> --json` |
| archive | `archive <id> --yes --json` ([V]: `--json` is a documented archive option in 1.14.0; SPEC OSP-001 (b) says `--json` wherever supported) |
| fix unit | `new change <name>` (OSP-005; no `--json` known [U], so success is checked on the filesystem) |

Alternatives: `npx @fission-ai/openspec@1.14.0` (rejected, [V] a planted package in `node_modules` runs instead of the registry package); a globally installed `openspec` (rejected, unpinned and `PATH`-resolved); vendoring a copy in this repository (rejected, SPEC pins a harness-owned prefix so versions follow `spec.openspec.version`).

### D4. OpenSpec provider operations

- `list_units(repo, include_archived)`: `list --json` for active changes (names, `status`); archived units are listed from `openspec/changes/archive/*/` on disk (folder name `YYYY-MM-DD-<name>`), because SPEC's allowlist has no archived listing. `verify_root` runs on every reply.
- `tasks(unit)`: `parse_openspec_tasks(bytes)` uses a Python port of OpenSpec's `TASK_LINE_PATTERN` [V, research/01 section 1.4]: `^\s*(?:[-*+]|\d{1,9}[.)])\s*\[(?:\s*([^\]\s]?)\s*\](?![([])|\s+\])\s*(.*)`. Done means marker lower-cased equals `x`. Lines in code fences and HTML comments count, as in OpenSpec. Task `number` is the leading `\d+(\.\d+)*` of the title when present, else `L<line>`. Each task keeps its 1-based `line` and, when the interior is exactly one byte, its byte `marker_offset`.
- Agreement check: `progress_agreement(unit)` compares the harness counts with `instructions apply ... --json` `progress.{total,complete,remaining}` and `tasks[].line`; a difference raises `ParserDisagreement(harness=..., cli=...)`, rendered by `SPEC-006` and by `plan` as "unit not scheduled" (L4-OSP-004 c).
- `validate(unit, strict=True)`: `validate <id> --strict --json`; a result `valid: true` that still carries an issue whose message starts "Archive would refuse" [V per research/01] is converted to an error issue (L4-OSP-006).
- `done_gate(unit)`: every task done and `progress.remaining == 0`; the gate result lists remaining task numbers.
- `archive(unit)`: `done_gate()`, then `validate(strict=True)`; any failure raises `ArchiveRefused` before the CLI `archive` is invoked (L4-OSP-003); then `archive <id> --yes --json`; `archived_as` is read from the JSON reply when present [U on key path], else from the new `openspec/changes/archive/*-<id>` directory.
- `set_marker(unit, task_id, marker)`: only `Marker.DONE` on a `" "` task is allowed for OpenSpec (L4-OSP-004 b); anything else raises `MarkerNotAllowed`. Delegates to `markers.write_marker`.
- `create_fix_unit(parent, round, findings, spec_delta)`: refuses if `openspec/changes/<parent>-fix-<round>` exists (`FixUnitExists`); runs `new change <parent>-fix-<round>`; writes `proposal.md`, `tasks.md` (flat `## 1. Fix` group, one `- [ ] 1.N ...` per finding) and, when `spec_delta is None`, appends the line `skip_specs: true` to `.openspec.yaml` by text edit (keeps `schema` and `created` bytes); else writes `specs/<cap>/spec.md`. The result must pass `validate --strict` (asserted by the contract test).
- `load(unit)` reads files directly. It does not need `show --json`, whose shape is not pinned here [U] and which fails while `proposal.md` is absent [V, run].
- `unit_dir(unit)` is `openspec/changes/<name>/` (archived: the dated folder).

Alternative for task parsing: trust the CLI's `tasks[].line` only. Rejected: the CLI reports line numbers, not byte offsets; the writer needs offsets, and SPEC SCN-TMW-05 requires the two parsers to be compared, not merged.

### D5. Byte-safe marker writer (L4-TMW-001, L4-TMW-002)

Ported from `~/.claude/skills/kiro-spec-implement/scripts/kiro_tasks.py` (`split_lines`, `classify`, `_write_marker`, `_lock`): line records carry byte offset, content and terminator (`\r\n`, `\n`, `\r` or none); the marker offset is the byte length of the encoded prefix, so multi-byte characters earlier in the line cannot shift it; a UTF-8 BOM on line 1 is excluded from regex matching but included in offsets.

Deliberate change from the source: the helper writes in place (`seek`, one-byte `write`, `fsync`, re-read). SPEC L4-TMW-001 requires temp-file-and-rename, so `write_marker(path, offset, old, new)`:

1. Reject a symlink path and any `new`/`old` that is not exactly one byte (`MarkerWriteError`).
2. Take `path_lock(path)`: an in-process `threading.Lock` keyed by `realpath`, then an `fcntl.flock(LOCK_EX)` on a sidecar lock file `$L4_CACHE/locks/markers/<sha256(realpath)[:16]>.lock`. The sidecar is required because an `flock` on `tasks.md` itself would not survive the rename over it.
3. Read all bytes (`before`), check `before[offset:offset+1] == old`, build `expected = before[:offset] + new + before[offset+1:]` and assert equal length.
4. Write `expected` to a temp file in the same directory (`.tasks.md.l4tmp.<pid>`), copy mode bits, `fsync`, then re-read `path` and compare with `before`; if it changed in the meantime, delete the temp file and raise `MarkerWriteError` (foreign edit, SCN-TMW-N9).
5. `os.replace(tmp, path)`, `fsync` the directory, re-read `path` and require it to equal `expected`.

The single-byte rule means files where OpenSpec's regex allows a wider interior (`[]`, `[ x]`) cannot be written and raise (SCN-TMW-N7).

`check_tasks_guard(pre, post, allowed_offsets)` returns the offsets whose bytes differ and any non-marker difference; `restore_tasks` rewrites `pre` plus the allowed marker bytes through the same atomic path; the caller emits `guard.violation{path: tasks.md}`. The implementer loop (another change) calls it after every agent step.

Alternatives: in-place `pwrite` (rejected, SPEC says atomic and a torn write is possible on crash); a text-mode rewrite with `str.replace` (rejected, would normalise line endings and BOM); a git checkout of `tasks.md` as the guard (rejected, loses legitimate harness markers made since the last commit).

### D6. Kiro provider (L4-KSP-001..005)

`parse_kiro_tasks(bytes)` uses `^(\s*)([-*+])\s+\[([ xX\-~])\](\\?\*?)\s+(.+)$` [V]. Hierarchy: dotted number when any task has one (`\d+(?:\.\d+)*\.?` at the start of the text), else indentation; only leaves are executable; a parent's state is derived from its non-optional children. `set_marker(task, DONE)` on a leaf then closes every ancestor whose non-optional children are all done, each as its own one-byte write, and `set_marker` on a parent with an open non-optional child raises `ParentHasOpenChildren`. Whether `-` and `~` are written is caller policy (`spec.kiro.write_in_progress_marker`, `write_queued_marker`); the provider writes whatever marker it is asked for within Kiro's four.

`read_waves(text)` finds the heading `## Task Dependency Graph` and the first following fenced `json` block; invalid JSON or unknown task IDs yield a warning and `None` (document order). `order_leaves` expands waves into a dependency relation (a task depends on every task in earlier waves) and inserts pending leaves missing from the graph at their document position.

Criteria: EARS lines under `#### Acceptance Criteria` in `requirements.md` (numbered per requirement, alias `Req N.M`) or `bugfix.md`; links from `_Requirements: 2.1, 3.3_` lines. `validate()` checks: `tasks.md` present; `requirements.md` or `bugfix.md` present; `design.md` presence is a warning [I]; task grammar parses; graph JSON valid; every `_Requirements:_` reference resolves. `archive()` returns `ArchiveReport(archived=True, moved_to=...)`: it moves the folder only when `spec.kiro.archive_dir` is set, and the caller records the `archived` ledger event (state is not owned here). Moving to `.kiro/specs/_archive/<name>` removes it from Kiro's own spec list because Kiro's recognizer regex `([^/]+)` does not match nested paths [I, research/01].

Fix units: `.kiro/specs/<parent>-fix-<round>/{bugfix.md, design.md, tasks.md, .config.kiro}` with `{"specId": "<uuid4>", "workflowType": "requirements-first", "specType": "bugfix"}`; no `requirements.md`. `workflowType` for bugfix specs is [I].

Kiro unit identity is the directory name, never `specId` [V, research/01].

### D7. Criteria IDs (L4-CRT-001..003)

`criterion_id(framework, container, requirement, leaf) = "C-" + sha256("|".join([framework, container, requirement, leaf]).encode("utf-8")).hexdigest()[:8]`, with each component passed through `normalise` (Unicode NFC, strip, collapse runs of whitespace to one space; case is kept). SPEC does not define normalisation for OpenSpec titles; this choice is [I] and is fixed by tests (a golden vector) before any ID is released, because changing it re-keys every ID.

- OpenSpec: container = capability folder name under `specs/`; requirement = text after `### Requirement:` including the SPEC ID prefix; leaf = text after `#### Scenario:`. Sources are the change's delta files `specs/<cap>/spec.md` (ADDED and MODIFIED sections). Alias `capability › Requirement › Scenario`.
- Kiro: container = spec directory name; requirement = the requirement heading with a leading `Requirement <N>` stripped, falling back to the normalised `User Story` line [I]; leaf = the normalised criterion text, not its number (SCN-CRT-05). Alias `Req N.M`.
- Duplicates: two criteria of one unit with the same ID raise `CriterionIdCollision` listing both aliases rather than silently merging.
- `write_criteria_json` emits `{"schema": "l4/criteria@1", "unit": ..., "criteria": [...]}` with sorted keys, entries ordered by source path and line, two-space indent, trailing newline, no timestamps; it skips the write when bytes are equal so mtime stays stable.
- `trace_ids(ReportedCase)` matches `C-[0-9a-f]{8}` only in the case name, classname, title, tags and marker arguments; the test body is never scanned (SCN-CRT-04). `find_orphans` feeds `SPEC-005`; it scans files matching `tdd.test_globs` for IDs and subtracts the IDs of all active and archived units.

### D8. questions.md (L4-QMD-001..006)

The file is parsed into spans, not into a Markdown AST: a Markdown library would reformat bytes on write. `QuestionsFile.parse(text)` finds the title, the instruction comment, the index region (`<!-- l4:index:start -->` to `<!-- l4:index:end -->`), and sections that start at `## Q-NNN: ` after a `---` line. Field lines match `^- \*\*(Status|Blocking tasks|Kind|Asked|Criteria):\*\*\s*(.*)$`; subsections are `### Context`, `### Options`, `### Clarifier suggestion`, `### Answer`. Each `Question` stores character spans. Writers replace only these spans: the index region, an appended section, one Status line, one suggestion block; after each write `assert_regions_only(before, after, allowed_spans)` fails the write if any byte outside the spans differs. Line-ending style and BOM of the existing file are detected and reused for inserted text; a new file uses LF.

Status handling: case-insensitive; unknown values map to `open` and produce a `QuestionIssue(kind="unknown_status")`. `is_answered` is true for `answered`, `accepted`, `answered-by-clarifier`, `dismissed`. A non-empty answer (HTML comments removed, whitespace stripped) with Status `open` yields `QuestionIssue(kind="unsubmitted_answer")`; the caller logs `question.unsubmitted_answer` and posts the reminder. `effective_answer` returns the *Clarifier suggestion* text for `accepted` and `answered-by-clarifier` (L4-QMD-003 lets the harness write only the Status line and the suggestion block, so a clarifier answer lives there) and the human answer text otherwise. `Kind: verdict` answers must start with `accept` or `reject` (case-insensitive) or yield `QuestionIssue(kind="invalid_verdict")` and are not consumed.

`blocked_tasks(questions, pending_tasks)` returns tasks held by a question that is not answered. IDs: `next_id()` is `max(seen) + 1` where `seen` includes every `Q-NNN` in the file and in the ledger reader's history, so IDs are never reused; a `superseded` question must carry a `Superseded by: Q-NNN` text in its Status line suffix [I] — SPEC says it "names its successor" without fixing the syntax. `raise_questions(batch, max_open)` raises `TooManyQuestions` for `len(batch) > max_open` and writes nothing.

`restore_missing(ledger)`: for each id the ledger knows and the file lacks (or whose harness-owned parts are mangled), re-render from `ledger.raised_section(qid)` while keeping surviving human answer text, and report `question.restored` for the caller. `answer_sha256(question)` hashes the raw answer text as written by the human (UTF-8, trailing whitespace stripped, before redaction). `override_detected(question, ledger)` compares it with `ledger.consumed_hash(qid)` and returns true only for a consumed question whose hash differs; the caller (clarification-loop) then spawns the L4-QMD-006 fix unit.

Secrets: any answer text that leaves this module for a prompt, log, ledger event or comment goes through bootstrap-core's `l4.redact.Redactor.redact_text` (L4-OBS-002); the parser sets `QuestionIssue(kind="secret_in_answer")` from `l4.redact.Redactor.find_secrets` (the same `TOKEN_SHAPES` table) so the sticky comment can ask for rotation.

### D9. Doctor checks (`checks_spec.py`)

| ID | Severity | Logic |
|---|---|---|
| SPEC-001 | error | `detect_frameworks`: at least one supported framework; legacy OpenSpec error with the migration hint; Spec Kit warning "detected: not executed by v1" |
| SPEC-002 | error | `validate(strict=True)` for every active unit of every provider |
| SPEC-003 | error | `verify_root` against the repository |
| SPEC-004 | warn | Kiro leaves without `_Requirements:_`; units without criteria |
| SPEC-005 | warn | orphan criterion IDs in tests |
| SPEC-006 | error | `progress_agreement` for every OpenSpec unit |

### D10. Test strategy

Unit tests use fixture repositories under `tests/fixtures/specs/` (openspec-basic, openspec-legacy, kiro-basic, mixed, crlf-tasks, bom-tasks, questions-*). OpenSpec CLI behaviour is covered by contract tests under `tests/contract/` that run against a real CLI installed into a temporary `$L4_CACHE` (skipped when `L4_TEST_OPENSPEC_PREFIX` is unset and the network is unavailable) and by a recorded-command fake runner for hermeticity assertions. The provider conformance suite (SCN-DET-10) is parameterised over both providers.

## Facts to confirm first (before the code that depends on them)

| Fact | Label | Confirmed by |
|---|---|---|
| `instructions apply --json` field names: `progress.{total,complete,remaining}`, `tasks[].{id,description,done,line}`, `state`; and the `tasks[].id` format | [V] in research/01, id format [U] | `tests/contract/test_openspec_cli.py::test_instructions_apply_shape` (first test of the CLI group, uses a recorded fixture plus the live CLI when present) |
| `validate --json` issue object fields (`level`, `path`, `message`) and the "Archive would refuse" INFO text for a `MODIFIED` delta against a missing base requirement | [V] research/01, shape [U] | `tests/contract/test_openspec_cli.py::test_modified_missing_base_info` |
| `archive <id> --yes --json` reply shape and the key holding the dated folder name | `--json` exists [V, `--help`]; key [U] | `tests/contract/test_openspec_cli.py::test_archive_reply_shape` |
| `skip_specs: true` in `.openspec.yaml` makes a delta-less change validate and archive | [V, 1.14.0] | `tests/contract/test_openspec_cli.py::test_fix_unit_skip_specs` |
| `new change <name>` does not support `--json` and prints no machine-readable result | [U] | same file, `::test_new_change_filesystem_effect` |
| Kiro bugfix `.config.kiro` `workflowType` value | [I] | `tests/contract/test_kiro_bugfix_config.py::test_workflow_type_matches_kiro_created_spec` (needs a Kiro-created fixture; recorded in the spikes change) |
| Criterion-ID normalisation (NFC, trim, collapse whitespace) | [I] | `tests/unit/specs/test_criteria.py::test_golden_vectors` committed before any other criteria test |
| Sidecar lock plus rename keeps writers serialised on Linux and macOS | [I] | `tests/unit/specs/test_markers.py::test_concurrent_writers_serialised` (threads and processes) |

## Risks / Trade-offs

- **Parser drift.** OpenSpec or Kiro may change their task grammar. Mitigation: SPEC-006 compares against the CLI on every plan; the Kiro regex is pinned [V] to IDE 1.2.4 and covered by golden fixtures.
- **Foreign write during a marker write.** The re-read before rename narrows but cannot close the window (POSIX has no compare-and-swap rename). Safe in practice because the harness writes markers between agent steps, not while an agent runs [I]; the guard (TMW-002) catches whatever slips through.
- **Install-time scripts.** `npm install --prefix ...` as SPEC states runs the package's lifecycle scripts once, at install, outside the worktree. Pinning the exact version limits exposure; adding `--ignore-scripts` would be a deviation from SPEC and is left to the sandbox-security change to decide.
- **Normalisation choice.** An [I] normalisation shipped in a release cannot be changed without orphaning tags. Mitigation: golden vector test first, and the choice recorded here.
- **Superseded syntax.** SPEC does not define how a superseded question names its successor; the `Superseded by: Q-NNN` text is [I] and isolated in one function.
- **Dependency on bootstrap-core names.** Reconciled by the cross-change review (2026-10-03): `l4.doctor.registry.register(Check(...))`, `l4.exitcodes.ExitCode`, `l4.redact.Redactor`, `l4.config.defaults.cache_root`, and `l4.config.schema.L4Config`.
