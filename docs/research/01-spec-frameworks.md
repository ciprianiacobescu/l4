# 01 — Spec-driven-development frameworks: facts for detector / validator / archiver adapters

Research date: 2026-10-03. Labels: **[V]** verified from a primary source (cited), **[V-run]** verified by actually
running the released tool in a sandbox (OpenSpec 1.14.0, specify-cli 1.0.13) or reading its shipped code,
**[D]** secondary source, **[I]** inferred, **[U]** unverified / guess.

Sandbox used for [V-run]: `npm install @fission-ai/openspec@1.14.0` (Node v22.22.0) and
`uvx --python 3.12 --from specify-cli specify ...` inside the session scratchpad, with throwaway git repos.
Kiro evidence: kiro.dev `.md` doc twins (fetched 2026-10-03), the shipped Kiro IDE 1.2.4 bundle
(`/Applications/Kiro.app/Contents/Resources/app/extensions/kiro.kiro-agent/dist/extension.js`, build date
2026-09-30), and real Kiro-generated specs in the user's repos (read-only).

---

## 0. TL;DR for the adapter designer

| Framework | Strong marker (deterministic) | Unit of work | Task-state source of truth | Validate | Archive |
|---|---|---|---|---|---|
| OpenSpec 1.14.0 | `openspec/config.yaml` or `openspec/specs/` or `openspec/changes/` dir | `openspec/changes/<kebab-id>/` | `openspec instructions apply --change <id> --json` (or `list --json`) | `openspec validate <id> --strict --json` | `openspec archive <id> --yes --json` |
| Kiro (IDE 1.2.4 / CLI 2.27.0) | `.kiro/specs/<name>/{requirements,design,tasks,bugfix}.md` | `.kiro/specs/<name>/` | parse `tasks.md` with Kiro's regex (no CLI command exists) | none shipped — harness must lint | none — Kiro has no archive concept |
| GitHub Spec Kit 1.0.13/1.1.0 | `.specify/` dir (+ `specs/NNN-slug/`) | `specs/<NNN-or-timestamp>-<slug>/` | parse `tasks.md` (`- [ ] T001 ...`, done = `[X]`/`[x]`) | none in core CLI | none in core CLI (an "Archive Extension" exists in its catalog) |

Biggest gotchas (details below):
1. `openspec archive --yes` **also bypasses the incomplete-task check** — gate on task completion yourself first. [V-run]
2. `openspec archive` validates **non-strict**; a change failing `validate --strict` still archives. Run strict validate yourself. [V-run]
3. A `MODIFIED` delta for a requirement that does not exist passes `validate --strict` (INFO only) but `archive` refuses it (`archive_spec_update_failed`). Treat `issues[].message` starting "Archive would refuse" as blocking. [V-run]
4. Put `questions.md` at the **change root**, never under `specs/`: any `specs/**/*.md` makes `openspec status` report the specs artifact `done`. [V-run]
5. `openspec init --tools kiro` creates `.kiro/prompts/opsx-*.prompt.md` and `.kiro/skills/openspec-*/` — a naive "`.kiro/` exists ⇒ Kiro" detector false-positives. [V-run]
6. Kiro CLI headless works (`kiro-cli chat --no-interactive ...` + `KIRO_API_KEY`), but there is **no spec CLI command**; `/spec run` is an interactive slash command and its headless behaviour is undocumented [U]. In V3, an untrusted workspace does not load `.kiro/agents`, steering, MCP, or skills, and every `ask` becomes deny in headless. [V]

---

## 1. OpenSpec (github.com/Fission-AI/OpenSpec, npm `@fission-ai/openspec`)

### 1.1 Version / history
- Latest: **1.14.0, published 2026-09-30** (npm `time` field). 1.0.0 was 2026-01-26; 0.x through 0.23.0 (2026-01-21). [V] `npm view @fission-ai/openspec version time --json`
- Node engine: `"node": ">=20.19.0"`. [V-run] package.json of 1.14.0
- Repo ~70.9k stars, pushed 2026-10-02. [V] api.github.com/repos/Fission-AI/OpenSpec
- **1.0.0 = "The OPSX Release"** (breaking): old `/openspec:proposal|apply|archive` slash commands removed; tool instruction files (`CLAUDE.md`, `.cursorrules`, `AGENTS.md`, `project.md`) "no longer generated"; replaced by `/opsx:*` actions + agent skills; instructions assembled from `config.yaml` (context + rules) + schema template; customizable schemas in `openspec/schemas/`. [V] https://github.com/Fission-AI/OpenSpec/blob/main/CHANGELOG.md (## 1.0.0)
- So: **`openspec/config.yaml` replaces `openspec/project.md`** (project.md is preserved on migration, not deleted; `openspec/AGENTS.md` is deleted by `init --force` legacy cleanup). [V-run] `dist/core/legacy-cleanup.js`
- 1.5.0: "Stores (very early beta)" — standalone OpenSpec repos registered on the machine, selectable with `--store <id>` or a `store:` key in `openspec/config.yaml`. [V] CHANGELOG ## 1.5.0
- Since ~1.6: `archive` in human mode exits non-zero when blocked (previously exited 0). [V] CHANGELOG line ~720

### 1.2 Directory layout (as created/consumed by 1.14.0)
`openspec init --tools none` creates exactly: [V-run]
```
openspec/config.yaml
openspec/specs/.gitkeep
openspec/changes/archive/.gitkeep
```
`openspec new change add-export --description "..."` creates: [V-run]
```
openspec/changes/add-export/.openspec.yaml     # schema: spec-driven / created: 2026-10-03
openspec/changes/add-export/README.md          # only because --description was given
```
Full change (spec-driven schema): [V-run] `schemas/spec-driven/schema.yaml`
```
openspec/changes/<change-id>/
  .openspec.yaml        # per-change metadata (schema, created, goal?, affected_areas?, skip_specs?, retire_capabilities?)
  proposal.md           # artifact "proposal"
  specs/<capability-path>/spec.md   # artifact "specs", generates glob "specs/**/*.md"; capability path may be nested (identity/user-auth)
  design.md             # artifact "design"
  tasks.md              # artifact "tasks"; apply.tracks = tasks.md
openspec/specs/<capability-path>/spec.md     # main (source-of-truth) specs
openspec/changes/archive/YYYY-MM-DD-<change-id>/   # whole change dir moved here on archive
openspec/schemas/<name>/schema.yaml          # optional project-local schemas
```
- Change id must be kebab-case, lowercase, ≤200 chars. [V-run] `dist/utils/change-utils.js validateChangeName`
- A change must be a directory **directly** under `openspec/changes/`; a folder wrapping changes is reported as `nested_change_directory` warning and is *not* a change. Nested paths are allowed only under `openspec/specs/`. [V-run] (`list --json` → `warnings[]`)
- `.openspec.yaml` schema keys: `schema`, `created` (YYYY-MM-DD), `goal`, `affected_areas`, `skip_specs` (bool), plus initiative links. [V-run] `dist/core/change-metadata/schema.js`; `retire_capabilities: true` [V] agent-contract §4.9
- `openspec/config.yaml` keys: `schema` (required), `context`, `rules` (per-artifact string arrays), `operations.{apply,archive}.guidance`, `store`. [V-run] `dist/core/project-config.js`; `config.yml` also accepted. [V-run] `dist/core/openspec-root.js`
- Archive folder date = **process-local timezone** date (`formatLocalDate`), prefix not doubled if name already starts with `YYYY-MM-DD-`. Set `TZ=UTC` in CI for determinism. [V-run] `dist/utils/date.js`, `dist/core/archive.js:1314`
- Main spec written by archive (new capability): [V-run]
```
# data-export Specification

## Purpose
<copied from the delta's ## Purpose>

## Requirements

### Requirement: User can export data
...
#### Scenario: Successful export
```

### 1.3 Delta format [V-run] schema.yaml + validator behaviour
- Section headers: `## ADDED Requirements`, `## MODIFIED Requirements`, `## REMOVED Requirements`, `## RENAMED Requirements`.
- Requirement: `### Requirement: <name>`; scenario: `#### Scenario: <name>` (exactly 4 `#`; 3 `#` is ignored with an INFO issue). Each requirement needs ≥1 scenario (ERROR otherwise). Requirement text should contain SHALL/MUST (WARNING otherwise → fails under `--strict`).
- MODIFIED: paste the full existing block; header must match existing name (whitespace-insensitive).
- REMOVED: include `**Reason**` and `**Migration**`. RENAMED: `FROM:`/`TO:` format.
- New capability delta starts with `## Purpose` (≥50 chars or `--strict` flags it); otherwise archive writes a `TBD` placeholder purpose.
- Requirement description ≤500 chars recommended (INFO hint).
- A change with zero deltas is invalid unless `.openspec.yaml` has `skip_specs: true` (then INFO "zero deltas accepted"; `status` shows the specs artifact as `skipped`). [V-run]

### 1.4 tasks.md checkbox format
Template: [V-run] `schemas/spec-driven/templates/tasks.md`
```
# Tasks

## 1. <Group>

- [ ] 1.1 <task — include how to verify>
- [ ] 1.2 ...
```
Exact parser (shared by `list`, `status`, `instructions apply`, `archive`): [V-run] `dist/utils/task-progress.js`
```js
const TASK_LINE_PATTERN = /^\s*(?:[-*+]|\d{1,9}[.)])\s*\[(?:\s*([^\]\s]?)\s*\](?![([])|\s+\])\s*(.*)/;
// done  <=> marker.toLowerCase() === 'x'
```
- Bullets `-`, `*`, `+`, `1.`/`1)`; any indentation (nested sub-tasks count); `[ x]`, `[X]` count as done; `[~]`, `[-]`, `[]`, `[ ]` count as **not done** (so Kiro-style markers are safe). [V-run] (fixture: 8 tasks, 3 done)
- Lines inside code fences / HTML comments **are counted** (deliberate). [V-run] source comment
- Link bullets `- [A](url)` are excluded. [V-run]
- Task files resolved from the schema's tracked artifact glob (default top-level `tasks.md`). [V-run]

### 1.5 CLI commands with machine-readable output (1.14.0)
Top-level commands: `version, init, update, list, view, change, archive, spec, config, schema, store, doctor, context, workset, validate, show, feedback, completion, status, instructions, templates, schemas, new`. [V-run] `openspec --help`

| Command | Purpose | JSON shape (abridged) |
|---|---|---|
| `openspec list --json [--specs\|--changes\|--archived\|--all] [--sort recent\|name]` | enumerate | changes: `{changes:[{name,completedTasks,totalTasks,lastModified,status:"no-tasks"\|"in-progress"\|"complete",archived?,nested?}],warnings?,root}`; `--specs`: `{specs:[{id,requirementCount}],root}` [V-run] |
| `openspec show <id> --json [--type change\|spec] [--deltas-only] [--no-scenarios] [--requirements] [-r N]` | parsed content | change: `{id,title,deltaCount,deltas:[{spec,operation,description,requirement,requirements}],root}`; spec: `{id,title,overview,requirementCount,requirements,metadata,root}` [V-run]/[V] agent-contract |
| `openspec validate <id> --strict --json` / `--all` / `--changes` / `--specs` / `--archived` / `--report findings` / `--concurrency n` / `--no-interactive` | validation | `{items:[{id,type,valid,issues:[{level:"ERROR"\|"WARNING"\|"INFO",path,message,line?,column?}],durationMs}],summary:{totals:{items,passed,failed},byType},version:"1.0",root}`; exit 1 if any item fails [V-run] |
| `openspec status --change <id> --json` / `--all` | artifact graph state | `{changeName,schemaName,planningHome,changeRoot,artifactPaths,isPlanningComplete,isComplete,applyRequires,nextSteps,actionContext,artifacts:[{id,outputPath,status:"done"\|"ready"\|"blocked"\|"skipped",requires,missingDeps?}],root}` — NOTE `isComplete` = planning complete, NOT implementation complete [V-run]/[V] |
| `openspec instructions apply --change <id> --json` | implementation progress + task list | `{changeName,changeDir,schemaName,contextFiles,progress:{total,complete,remaining},tasks:[{id,description,done,sourcePath,line}],taskTrackingConfigured,state:"blocked"\|"all_done"\|"ready",missingArtifacts?,warnings?,instruction,root}` [V-run] (`sourcePath`/`line` observed in 1.14.0 though contract doc lists only `{id,description,done}`) |
| `openspec instructions <artifact> --change <id> --json` | per-artifact authoring instructions | see agent-contract §4.5 [V] |
| `openspec new change <id> [--description t] [--goal t] [--schema s] --json` | create change | `{change:{id,path,metadataPath,schema},root}` [V-run] |
| `openspec archive <id> --yes --json [--skip-specs] [--no-validate]` | archive | success `{archive:{change,archivedAs:"YYYY-MM-DD-<id>",path,specsUpdated,totals:{added,modified,removed,renamed},warnings?},root}`; failure `{archive:null,root?,status:[{severity,code,message,fix}]}` exit 1 [V-run] |
| `openspec doctor --json`, `openspec context --json`, `openspec schemas --json`, `openspec templates --json`, `openspec version --json` | health/meta | see agent-contract [V] |

Primary reference for every shape: https://github.com/Fission-AI/OpenSpec/blob/main/docs/agent-contract.md ("verified against src/ (capstone audit, 2026-06-11)"). [V]
- One JSON document per invocation on stdout; prose/spinners to stderr. [V] agent-contract §1
- Diagnostic envelope `{severity,code,message,target?,fix?}`; archive codes: `archive_change_name_required, archive_change_not_found, archive_change_symlink, archive_validation_failed, archive_confirmation_required, archive_tasks_incomplete, archive_spec_update_failed, archive_spec_validation_failed, archive_target_exists, archive_retirement_cleanup_failed, archive_error`. [V] agent-contract §6
- "JSON mode is strictly non-interactive: every prompt point becomes an `archive_*` code." [V] and observed: without `--yes`, `--json` returns `archive_tasks_incomplete` / `archive_confirmation_required` and exits 1. [V-run]
- `archive: null` "is not a guarantee that files are unchanged" (retirement edge cases). [V] agent-contract §4.9

**Exit codes**: 0 success (incl. health findings); 1 any error / validation failure / root-resolution failure (JSON mode prints the command's null-shape + `status:[d]`); 130 prompt cancellation in `store` group. [V] docs/cli.md "Exit Codes", agent-contract §5; [V-run] observed 0/1.

**Edge behaviours observed** [V-run]:
- `openspec validate --json` with no item/scope in a non-TTY prints *plain text* "Nothing to validate. Try one of: ..." and exits 1 — always pass an id or `--all/--changes/--specs`.
- Unknown item: `{status:[{severity:"error",code:"unknown_item",message:"Unknown item 'nope'. Did you mean: ..."}]}`, exit 1.
- No OpenSpec root: `{changes:[],root:null,status:[{code:"no_openspec_root",...}]}`, exit 1.
- `validate --changes` excludes `changes/archive/*`; `validate --archived` only checks that archived changes have all tasks ticked.
- Root resolution walks **up** from cwd to the nearest ancestor `openspec/` dir that has `specs/` or `changes/` or a config file; `root.source` ∈ `nearest|store|declared|global_default|implicit`. [V-run] `dist/core/root-selection.js`, [V] agent-contract §3. → Always run the CLI with cwd = the repo root you detected, and assert `root.path` equals it.
- A config-only `openspec/` whose `config.yaml` has `store: <id>` redirects to a machine-registered store (`source:"declared"`) — not portable to CI; adapter should treat `root.source != "nearest"` as "unsupported/foreign root". [V-run]/[I]

### 1.6 Extra files in a change folder (questions.md)
Tested on 1.14.0 with `questions.md` and `notes/x.txt` at change root: [V-run]
- `validate --strict --json` → valid, no issues.
- `list`, `status`, `instructions apply` unaffected.
- `archive` moves the entire directory, so `questions.md` lands in `changes/archive/YYYY-MM-DD-<id>/questions.md`.
- **Do NOT** put it under `specs/`: `specs/questions.md` (or `specs/<cap>/questions.md`) is ignored by validate, but `status` then reports artifact `specs: done` because the artifact glob is `specs/**/*.md`. [V-run]

### 1.7 init (non-interactive)
```
openspec init [path] --tools <all|none|csv> [--profile core|custom] [--language <lang>] [--force] [--no-animation] [--no-copilot-cloud]
```
`--tools` ids include: amazon-q, amp, antigravity, atomcode, auggie, bob, claude, cline, command-code, codeartsagent, codex, dsh, devin, forgecode, codebuddy, codestudio, continue, costrict, crush, cursor, easycode, factory, gemini, github-copilot, gigacode, grok, gsd, hermes, iflow, junie, kilocode, kimi, kiro, lingma, minimax-code, vibe, oh-my-pi, opencode, pi, codeassistant, qoder, qwen, rovodev, roocode, trae, veai, warp, zed, zcode, agents (windsurf → devin). [V-run] `openspec init --help`
- `--tools none` with stdin `</dev/null` completed non-interactively, exit 0. [V-run]
- `--tools claude,kiro,agents` writes `.claude/skills/openspec-*/SKILL.md`, `.claude/commands/opsx/*.md`, `.kiro/skills/openspec-*/SKILL.md`, `.kiro/prompts/opsx-*.prompt.md`, `.agents/skills/openspec-*/SKILL.md` (+ `.agents/skills/.openspec-target`). Default "core" profile = propose, explore, apply, archive, sync, update. [V-run]

### 1.8 CI environment hygiene [V] docs/cli.md "Environment Variables"; [V-run] `dist/telemetry/opt-out.js`
`DO_NOT_TRACK=1` and/or `OPENSPEC_TELEMETRY=0` (telemetry + update check off), `OPENSPEC_NO_UPDATE_CHECK=1`, `OPENSPEC_NO_ANIMATION=1`, `OPENSPEC_NO_COMPLETIONS=1`, `NO_COLOR=1`, `OPENSPEC_CONCURRENCY`, plus `TZ=UTC` [I] for archive dates. Global config lives under `$XDG_CONFIG_HOME/openspec/` / `~/.config/openspec/config.json`. [V-run]
Invocation for a portable harness: `npx -y @fission-ai/openspec@1.14.0 <cmd>` (pin) [I].

---

## 2. Kiro specs (kiro.dev)

### 2.1 Versions
- Kiro IDE **1.2.4** (product.json date 2026-09-30) installed locally. [V-run]
- Kiro CLI **2.27.0** (2026-10-01); V3 "unified agent harness" is selectable per run with `--v3`/`--agent-engine v3` or the `chat.agentEngine` setting. [V] https://kiro.dev/changelog/cli/ , https://kiro.dev/docs/cli/headless.md
- Docs index with `.md` twins: https://kiro.dev/llms.txt [V]

### 2.2 Layout
```
.kiro/specs/<feature-name>/
  requirements.md    # feature specs (or)
  bugfix.md          # bugfix specs (replaces requirements.md)
  design.md
  tasks.md
  .config.kiro       # JSON: {"specId": "<uuid>", "workflowType": "...", "specType": "..."}
  tasks.meta.json    # Kiro-written sidecar: {"pbtResults":{...},"executionHistory":{...}}
.kiro/steering/*.md  # + AGENTS.md support
.kiro/agents/*.json | *.md
.kiro/settings/mcp.json
.kiro/hooks/*.json   # CLI V3 / IDE
.kiro/skills/<name>/SKILL.md
.kiro/workflows/
```
- Spec files: "requirements.md (or bugfix.md)", "design.md", "tasks.md" in `.kiro/specs/<name>/`. [V] https://kiro.dev/docs/specs.md
- Kiro's own recognizer regex: `/\.kiro\/specs\/([^/]+)\/(requirements|design|tasks|bugfix)\.md$/`. [V-run] IDE bundle
- `.config.kiro` content template: `{"specId": "${randomUUID()}", "workflowType": "${t}", "specType": "${e}"}`; enums `workflowType ∈ {requirements-first, design-first, fast-task, verify-first}`, `specType ∈ {feature, bugfix, quick-spec}`. Agent instructions say "Preserve .config.kiro — do NOT recreate". [V-run] IDE bundle. Real files seen: requirements-first/design-first/fast-task × feature/bugfix. [V-run] local repos
- `.config.kiro` is **not always present**: in mintkey 12 of ~20 spec dirs have it; project-a `event-cancel-fix` has only `bugfix.md` (no design/tasks, no config). `specId` is sometimes duplicated across specs (copied). Use the directory name as identity, not `specId`; tolerate partial specs. [V-run] local observation
- `tasks.meta.json` path = tasks file with `.md`→`.meta.json`; default `{pbtResults:{}, executionHistory:{}}`; keys are task text. [V-run] IDE bundle `HFi`, `GFi`
- Config scopes/file paths table (MCP `.kiro/settings/mcp.json`, agents `.kiro/agents/`, steering, skills, hooks, workflows, specs project-only; permissions `~/.kiro/settings/permissions.yaml` and `~/.kiro/workspace-roots/<hash>/permissions.yaml`; CLI settings `~/.kiro/settings/cli.json`; `KIRO_HOME` overrides `~/.kiro`). [V] https://kiro.dev/docs/configuration.md

### 2.3 Requirements / bugfix format
- Feature requirements template (from bundle): [V-run]
```
# Requirements Document
## Introduction
## Glossary
## Requirements
### Requirement 1            (real specs also use "### Requirement N: Title")
**User Story:** As a [role], I want [feature], so that [benefit]
#### Acceptance Criteria
1. WHEN [event], THE [System_Name] SHALL [response]
2. WHILE [state], THE [System_Name] SHALL [response]
3. IF [undesired event], THEN THE [System_Name] SHALL [response]
4. WHERE [optional feature], ...
```
  Docs describe EARS as `WHEN [condition/event] THE SYSTEM SHALL [expected behavior]`. [V] https://kiro.dev/docs/specs/feature-specs.md
- Bugfix template: `# Bugfix Requirements Document` → `## Bug Analysis` → `### Current Behavior (Defect)` (`1.1 WHEN … THEN the system …`), `### Expected Behavior (Correct)` (`2.1 … SHALL …`), `### Unchanged Behavior (Regression Prevention)` (`3.1 … SHALL CONTINUE TO …`). [V-run] bundle; [V] https://kiro.dev/docs/specs/bugfix-specs.md

### 2.4 tasks.md format
- Task line regex (IDE parser, verbatim): `^(\s*)([-*+])\s+\[([ xX\-~])\](\\?\*?)\s+(.+)$` [V-run] bundle
- Status mapping (verbatim): `x→completed, -→in_progress, ~→queued, ' '→not_started` (enum `not_started|queued|in_progress|completed`); the IDE writes status by replacing only the marker char. [V-run] bundle (`H3u`, `$fd`, `S9d`)
- Optional task: `*` or `\*` immediately after `]` → `- [ ]* 2.2 Write property test`. Template note: "Tasks marked with `*` are optional and can be skipped for faster MVP". [V-run] bundle
- Requirement refs in task bodies: `- _Requirements: 2.1, 3.3, 1.2_`; bugfix tasks also `_Bug_Condition: …_`, `_Expected_Behavior: …_`, `_Preservation: …_`; property tasks `**Property N: Title**` + `**Validates: Requirements x.y**`. [V-run] bundle templates
- `## Task Dependency Graph` + fenced ```json `{"waves":[{"id":0,"tasks":["1.1","3.1"]},{"id":1,"tasks":["1.2","2.1"]},...]}` generated by the tasks phase; waves run sequentially, tasks within a wave concurrently. [V-run] bundle template; [V] https://kiro.dev/docs/specs.md "Running tasks in parallel"
- Hierarchy by dotted number (`1.`, `1.1`), parents auto-complete when all non-optional children complete, a parent cannot be completed while non-optional children are open; `[~]` written by "Run all tasks" queueing leaves. [D] user's skill reference `~/.claude/skills/kiro-spec-implement/references/kiro-conventions.md` (which cites the same bundle); the regex/enum parts were re-derived here [V-run].
- Differences vs OpenSpec parser: Kiro requires whitespace between bullet and `[` and after `]`/`*`, does not accept ordered-list bullets (`1. [ ]`), single marker char only. A shared counter must use the per-framework regex. [V-run] (both regexes above)

### 2.5 Kiro CLI headless / CI
- `kiro-cli chat --no-interactive [--trust-all-tools | --trust-tools=read,grep,...] [--agent <name>] [--model <id>] [--effort <level>] [--agent-engine v1|v2|v3 | --v2 | --v3] [--output-format stream-json] [--require-mcp-startup] "prompt"`; prompt may come from stdin when no positional arg. [V] https://kiro.dev/docs/cli/headless.md
- Install in CI: `curl -fsSL https://cli.kiro.dev/install | bash`. [V] headless.md
- Auth: `KIRO_API_KEY` env (keys look like `ksk_…`); only Pro, Pro+, Pro Max, Power subscribers, admin may need to enable; precedence: browser session > `KIRO_API_KEY` > prompt. `kiro-cli whoami` shows active method. [V] https://kiro.dev/docs/getting-started/authentication.md
- Exit codes: 0 success, 1 general failure, 3 MCP startup failure under `--require-mcp-startup` (V3: fail/unknown/no status in 30 s). Hook exit code 2 blocks a PreToolUse. [V] https://kiro.dev/docs/reference/exit-codes.md
- `--output-format stream-json` (JSON Lines; V2/V3 only); V3 interrupted runs emit a final interruption record. [V] headless.md
- Model/agent defaults: `kiro-cli settings chat.defaultAgent <name>`, `chat.defaultModel`; `--model` overrides agent model. [V] headless.md
- V3 permissions replace trust flags with `permissions.yaml`, but `--trust-all-tools` "still works as a session-scope override for CI"; CI recipe: `~/.kiro/settings/permissions.yaml` with `rules: [{capability: all, effect: allow}]`. Headless: "every `ask` is treated as a deny". [V] https://kiro.dev/docs/permissions.md, https://kiro.dev/docs/cli/v3/permissions.md
- **Workspace trust (V3)**: until a workspace is trusted, Kiro does not load workspace custom agents (`.kiro/agents`), steering, MCP config, skills, workflows; trust decision is stored outside the repo. [V] permissions.md "Workspace trust". **How to pre-trust a workspace non-interactively is not documented** [U] — a harness relying on `.kiro/agents/*.json` or `.kiro/steering` in CI must verify this (or use V2 / pass config via `KIRO_HOME`-scoped global files [I]).
- Spec commands: no `kiro-cli spec …` subcommand exists in the CLI reference. [V] https://kiro.dev/docs/reference/cli-commands.md. Specs are driven by in-chat `/spec new|run|view|analyze_requirements <name>`; `/spec run` opens a full-screen interactive task view in V3. [V] https://kiro.dev/docs/reference/slash-commands.md, CLI changelog. Whether `/spec run <name>` works as a `--no-interactive` prompt: **[U]** (headless docs say interactive slash-command pickers are unavailable). Safe approach: prompt the default agent with an explicit instruction to execute `.kiro/specs/<name>/tasks.md` [I]. Historically the CLI did not auto-update task markers (GitHub issue #6826, per [D] user skill notes) — the harness should own marker writes.
- Agent config: `.kiro/agents/<name>.json` or `.md` (frontmatter = config, body = prompt) with fields `name, description, prompt (inline or file://), mcpServers, tools (tags: read, write, shell, web, @builtin, @mcp, *), toolAliases, allowedTools, permissions, resources (file://, skill://, knowledgeBase), hooks (CLI only), includeMcpJson, includePowers, model, keyboardShortcut, welcomeMessage`; `toolsSettings` deprecated. [V] https://kiro.dev/docs/custom-agents/configuration-reference.md
- MCP config: `.kiro/settings/mcp.json` (workspace), `~/.kiro/settings/mcp.json` (global); `kiro-cli mcp add|remove|list|import|status`. [V] https://kiro.dev/docs/mcp.md, cli-commands.md
- Built-in agents: Default, Spec, Quick Spec, Bug Fix, Plan, Guide, Help. [V] https://kiro.dev/docs/custom-agents/built-in.md

### 2.6 Steering
`.kiro/steering/*.md` (workspace) and `~/.kiro/steering/` (global); front matter `inclusion: always | fileMatch | manual | auto` (+ `fileMatchPattern`, string or array); foundation files `product.md`, `tech.md`, `structure.md`; `AGENTS.md` at root/subdirs is honoured (no inclusion modes). [V] https://kiro.dev/docs/steering.md

### 2.7 "Autonomous"/headless spec execution offerings (2025-2026)
- **Kiro Web autonomous mode** (app.kiro.dev): agent plans, runs sub-agents in a cloud sandbox, opens PRs; `/kiro all`, `/kiro fix` PR commands. Not a local CLI. [V] https://kiro.dev/docs/web/autonomous-mode.md
- **Kiro Crew Task Runner**: `kirocrew run TASK.md [--fresh] [--timeout N] [--no-test]`, any markdown spec (Goal/Requirements/Acceptance criteria), checkpoints under `~/.kiro/crew/tasks/`, writes `TASK_PROGRESS.md`; **not** the `.kiro/specs` format. [V] https://kiro.dev/docs/crew/features/task-runner.md
- **CLI `/goal`** autonomous loop (default 5 iterations, `--max N`). [V] https://kiro.dev/docs/cli/chat/goal.md
- Kiro Workflows (declarative multi-step recipes, opt-in in CLI 2.26+). [V] CLI changelog

---

## 3. GitHub Spec Kit (github.com/github/spec-kit, `specify` CLI)
- Latest per CHANGELOG: **1.1.0 (2026-10-02)**; `uvx --from specify-cli` resolved **1.0.13** today (PyPI lag or cache) [V] https://github.com/github/spec-kit/blob/main/CHANGELOG.md, [V-run]
- Requires Python 3.11+ and uv; install `uv tool install specify-cli`. [V] README
- CLI commands: `init, check, version, self, extension, integration, event, preset, artifact, bundle, workflow` — **no validate / archive / list / status**. [V-run] `specify --help`
- Non-interactive init: `specify init --here --force --non-interactive --integration claude --script sh --ignore-agent-tools` (exit 0). Other flags: `--preset`, `--integration-options`, `--extension` (repeatable), `--trust-extension-urls`. [V-run]
- Layout after init + one feature: [V-run]
```
.specify/init-options.json      # {"ai":"claude","feature_numbering":"sequential","integration":"claude","script":"sh","speckit_version":"1.0.13",...}
.specify/integration.json
.specify/memory/constitution.md
.specify/templates/{spec,plan,tasks,checklist,constitution}-template.md
.specify/scripts/bash/{create-new-feature,check-prerequisites,setup-plan,setup-tasks,common,resolve-template}.sh
.specify/workflows/speckit/workflow.yml
.specify/feature.json           # {"feature_directory":"specs/001-user-auth"}  (current feature pointer)
specs/001-user-auth/spec.md     # later: plan.md, tasks.md, research.md, data-model.md, contracts/, quickstart.md, checklists/
.claude/skills/speckit-{constitution,specify,clarify,plan,tasks,analyze,checklist,implement,converge,taskstoissues}/SKILL.md
```
- Feature dir naming: sequential `NNN-<short-name>` (3-digit) or `--timestamp` → `YYYYMMDD-HHMMSS-<short-name>`. In 1.0.x branch creation moved to a git extension (no branch was created in the test). Feature resolution order: `SPECIFY_FEATURE_DIRECTORY` env → `.specify/feature.json`. [V-run] create-new-feature.sh `--help`, common.sh
- Machine-readable helpers: `.specify/scripts/bash/create-new-feature.sh --json --short-name x "desc"` → `{"BRANCH_NAME","SPEC_FILE","FEATURE_NUM"}`; `check-prerequisites.sh --json --paths-only` → `{"REPO_ROOT","BRANCH","FEATURE_DIR","FEATURE_SPEC","IMPL_PLAN","TASKS"}`; `--require-tasks --include-tasks` for implement gating. [V-run]
- tasks.md format: `- [ ] T001 [P] [US1] Description with exact file path` under `## Phase N: …` headings; `[P]` = parallelizable, `[USn]` = user story; implement skill marks done as `[X]` ("mark the task off as [X]"); checklists count `- [ ]`/`- [x]`/`- [X]`. No in-progress marker [I]. [V-run] tasks-template.md, speckit-implement SKILL.md
- Clarification convention: spec.md `[NEEDS CLARIFICATION: …]` markers (max 3) and `/speckit-clarify` writes answers into `## Clarifications` → `### Session YYYY-MM-DD` in spec.md. A separate `questions.md` is foreign to Spec Kit but harmless [I]. [V-run] skills
- Workflow: constitution → specify → plan → tasks → implement → converge ("repeat implement → converge until Converged"). Bugfix/assess flows are opt-in extensions writing to `.specify/bugs/<slug>/`, `.specify/assessments/<slug>/`. [V] README

---

## 4. Other SDD frameworks (only real, verified ones)
- **BMAD-METHOD** v6.12.0 (npm `bmad-method`, 2026-09): installs `_bmad/` (config, scripts, `bmm`, `custom`); default output folder `_bmad-output/` with `planning_artifacts` (prd, epics.md, ux-design) and `implementation_artifacts` (`sprint-status.yaml`, stories). Story/epic oriented, not change-folder oriented. Marker: `_bmad/` dir or `_bmad-output/`. [V-run] npm package source; [V] README. Legacy v4 `.bmad-core/` [U].
- **Agent OS** v3.0 (2026-01-20, buildermethods): now standards-focused; `/shape-spec` saves to `agent-os/specs/YYYY-MM-DD-HHMM-<slug>/`; also `agent-os/standards/`, `agent-os/product/`. Marker: `agent-os/` dir. Legacy `.agent-os/` [U]. [V] https://github.com/buildermethods/agent-os CHANGELOG + commands/agent-os/shape-spec.md
- **Tessl** (CLI 0.113.0): package manager for agent context "plugins/tiles"; repo manifest `tessl.json`, plugin manifest `.tessl-plugin/plugin.json`; its SDD tile writes to a generic `specs/` dir. Not a distinct spec layout — detect `tessl.json` only as informational. [V] https://docs.tessl.io/reference/configuration, npm `@tessl/cli`
- Recommendation: ship adapters for OpenSpec, Kiro, Spec Kit; "detect-only" stubs for BMAD and Agent OS. [I]

---

## 5. Deterministic detection rule set

All paths relative to the repo root (git toplevel). Evaluate every rule; never short-circuit on the first hit.

```
OPENSPEC (strong) if any of:
  O1  file  openspec/config.yaml | openspec/config.yml
  O2  dir   openspec/changes/          (planning shape)
  O3  dir   openspec/specs/            (planning shape)
  legacy flag (pre-1.0) if openspec/project.md or openspec/AGENTS.md exists      -> version="legacy"
  foreign-root flag if O1 has top-level `store:` key and neither O2 nor O3 exists -> unsupported (store elsewhere)
  NOT a signal: .claude/skills/openspec-*, .claude/commands/opsx/, .kiro/prompts/opsx-*, .kiro/skills/openspec-*,
                .agents/skills/openspec-*, .github/prompts/opsx-*  (tool integration files only)
  confirm (optional): `openspec list --json` exit 0 and root.source=="nearest" and root.path==repo root

KIRO (strong) if any dir D in .kiro/specs/* (excluding dotfiles) contains
  K1  one of requirements.md | bugfix.md | design.md | tasks.md        (Kiro's own regex)
  K2  .config.kiro  (strengthens; parse specType/workflowType if present)
  spec type: .config.kiro.specType, else "bugfix" if bugfix.md exists, else "feature"
  weak (Kiro used, no specs): .kiro/steering/, .kiro/settings/, .kiro/agents/, .kiro/hooks/
  NOT a signal on its own: .kiro/ existing; .kiro/prompts/opsx-*; .kiro/skills/openspec-*

SPECKIT (strong) if:
  S1  dir .specify/ AND (file .specify/memory/constitution.md OR .specify/init-options.json OR .specify/integration.json
                         OR dir .specify/templates/)
  units: dirs specs/* matching ^(\d{3,}|\d{8}-\d{6})-[^/]+$ that contain spec.md
  current unit: .specify/feature.json.feature_directory
  NOT a signal on its own: specs/ dir (too generic: rspec, Tessl tile, docs)

BMAD (detect-only): dir _bmad/ OR dir _bmad-output/ (legacy .bmad-core/ [U])
AGENT_OS (detect-only): dir agent-os/ with agent-os/specs/ (legacy .agent-os/ [U])
TESSL (info): file tessl.json
```
Monorepos [I]: OpenSpec resolves the *nearest ancestor* root, so also scan for `*/openspec/config.yaml` and `*/.kiro/specs` up to depth 3 (skip node_modules, .git, vendor, dist); report each root separately and always invoke the OpenSpec CLI with cwd = that root.

### Mixed repos [I]
1. Report **all** strong frameworks: `frameworks: [{id:"openspec", root, units:[...]}, {id:"kiro", ...}]`; namespace unit ids (`openspec:<change-id>`, `kiro:<spec-name>`, `speckit:<NNN-slug>`).
2. Choose `primary` deterministically: (a) explicit harness config (e.g. `.harness/config.yaml: framework:`) → (b) the only framework with active units (OpenSpec: non-archived change with `status != complete`; Kiro/SpecKit: tasks.md with any non-`x` leaf) → (c) most recent mtime among unit files → (d) fixed tiebreak `openspec > kiro > speckit`. Log the reason.
3. A unit is owned by exactly one adapter; never let one adapter's parser count another's tasks (regexes differ).
4. OpenSpec-in-a-Kiro-repo is common (OpenSpec writes `.kiro/prompts|skills`) — the K1 rule avoids misclassification.

### Per-adapter "implemented vs not"
- OpenSpec: `openspec instructions apply --change <id> --json` → `progress.{total,complete,remaining}`, `tasks[].{done,line}`, `state` (`all_done` ⇒ implemented). Fallback: the OpenSpec regex in §1.4.
- Kiro: Kiro regex; per-leaf status `not_started|queued|in_progress|completed`; ignore optional leaves unless configured; parent derived from children; read waves JSON for ordering.
- Spec Kit: `^\s*-\s\[( |x|X)\]\s+(T\d+)\b` [I, from template]; done = x/X.

### Validate / archive per adapter
- OpenSpec: `openspec validate <id> --strict --json` (block on `valid:false` and on any INFO whose message starts "Archive would refuse"); archive only after your own gate (`progress.remaining == 0` and strict-valid): `TZ=UTC openspec archive <id> --yes --json`; parse `archive.archivedAs`; on failure branch on `status[0].code`.
- Kiro / Spec Kit: no native validator or archiver — the harness must implement structural lint (Kiro: EARS lines, `_Requirements:` refs resolve to `N.M` criteria, waves reference existing ids; Spec Kit: no `[NEEDS CLARIFICATION` left, T-ids unique) and an archive convention of its own (e.g. move to `.kiro/specs/_archive/YYYY-MM-DD-<name>/` [I] — note Kiro's regex `([^/]+)` would then no longer match a nested archive path, so archived specs drop out of Kiro's spec list [I]).

---

## 6. Sources
- npm registry: `npm view @fission-ai/openspec version time --json`; `npm view bmad-method`; `npm view @tessl/cli`
- OpenSpec 1.14.0 shipped code (node_modules/@fission-ai/openspec): `dist/utils/task-progress.js`, `dist/core/root-selection.js`, `dist/core/openspec-root.js`, `dist/core/project-config.js`, `dist/core/change-metadata/schema.js`, `dist/core/legacy-cleanup.js`, `dist/core/archive.js`, `dist/utils/date.js`, `dist/telemetry/opt-out.js`, `schemas/spec-driven/schema.yaml` + templates
- https://github.com/Fission-AI/OpenSpec/blob/main/docs/agent-contract.md
- https://github.com/Fission-AI/OpenSpec/blob/main/docs/cli.md
- https://github.com/Fission-AI/OpenSpec/blob/main/CHANGELOG.md
- https://kiro.dev/llms.txt and `.md` twins: /docs/specs.md, /docs/specs/feature-specs.md, /docs/specs/feature-specs/requirements-first.md, /docs/specs/bugfix-specs.md, /docs/steering.md, /docs/cli/headless.md, /docs/reference/cli-commands.md, /docs/reference/slash-commands.md, /docs/reference/exit-codes.md, /docs/getting-started/authentication.md, /docs/permissions.md, /docs/cli/v3.md, /docs/cli/v3/permissions.md, /docs/cli/v3/new-features.md, /docs/configuration.md, /docs/custom-agents/configuration-reference.md, /docs/custom-agents/built-in.md, /docs/mcp.md, /docs/web/autonomous-mode.md, /docs/crew/features/task-runner.md, /docs/cli/chat/goal.md
- https://kiro.dev/changelog/cli/
- Kiro IDE 1.2.4 bundle: `/Applications/Kiro.app/Contents/Resources/app/extensions/kiro.kiro-agent/dist/extension.js`
- Real Kiro specs (read-only): `~/src/mintkey/.kiro/specs/*`, `~/src/project-a/.kiro/specs/*`, `~/src/project-b/.kiro/specs/*`, `~/src/project-c/.kiro/specs/*`
- [D] `~/.claude/skills/kiro-spec-implement/references/kiro-conventions.md` (user-authored; used only for hierarchy/parent rules)
- https://github.com/github/spec-kit (README.md, CHANGELOG.md); specify-cli 1.0.13 run output and generated `.specify/` files
- https://github.com/bmad-code-org/BMAD-METHOD README; bmad-method 6.12.0 npm tarball
- https://github.com/buildermethods/agent-os CHANGELOG.md and commands/agent-os/shape-spec.md
- https://docs.tessl.io/reference/configuration
