# 05: Serena and memory for a reproducible L4 agentic harness

Research date: 2026-10-03. Researcher: subagent (Opus 5.5).

Labels:
- **[V]** verified from a primary source (URL or file path given).
- **[V-run]** verified by running `serena-agent==1.7.0` locally (macOS arm64, Python 3.13, uv). Throwaway `SERENA_HOME`, demo repo in the scratchpad.
- **[D]** secondary source.
- **[I]** inferred (my reasoning, not stated anywhere).
- **[U]** unverified.

Primary sources:
- Repo `https://github.com/oraios/serena`, cloned at two points: `main` @ `d0f7f92` (2026-09-30), and tag `v1.7.0` @ `949a27e` (2026-08-09).
- Docs at `https://oraios.github.io/serena/` (the same markdown files as `docs/` in the repo).
- PyPI JSON for `serena-agent`.

---

## 0. TL;DR / verdict

1. **Pin `serena-agent==1.7.0`.** It is the latest PyPI release (2026-08-09) [V: pypi.org/pypi/serena-agent/json]. It is also the **last MIT-licensed line.** `main` (2.0.0.dev0) relicensed the Serena application to **GPL-3.0-or-later**. SolidLSP stays MIT. `main` also adds breaking changes: the "Serena REPL" agent interface, and `session_id` parameters on `activate_project`. [V: main `CHANGELOG.md` "Unreleased", main `LICENSE`, v1.7.0 `LICENSE` = MIT].
   - The relicensing does not matter if you invoke Serena as an external MCP process. It does matter if you literally "embed" (vendor) Serena's code into a harness you distribute [I, not legal advice].
2. **Run command for CI (headless, per agent invocation, stdio):**
   ```bash
   serena start-mcp-server --context <claude-code|codex|ide> --project "$REPO" \
     --enable-web-dashboard false --open-web-dashboard false --mode one-shot --mode no-onboarding
   ```
   All flags verified in `src/serena/cli.py` @ v1.7.0 [V]. The run was exercised end-to-end over a raw MCP stdio handshake [V-run].
   - The flag is `--enable-web-dashboard` (takes a bool value). `--open-web-dashboard` also exists. Both are real.
3. **Memories are plain Markdown files**, `.serena/memories/<name>.md`. A `/` in a name maps to a subdirectory. There is no front matter, no index file, and no database. The content is written byte-for-byte as given [V: `memory_manager.py`; V-run: hexdump].
   - The harness can therefore write and read them **without running Serena**. Serena picks up files written externally on the next `list_memories`, because the directory is re-scanned on every call [V-run].
4. **Serena does not inject memory content.** By design, the agent only receives the *names* of memories, inside the project-activation message, and decides itself what to read. [V: docs 045_memories "Prefer deliberate reads to triggers"; `agent.py:get_project_activation_message`].
   - In the CLI contexts (`claude-code`, `codex`, `ide`), even that name list only arrives if the agent calls the `initial_instructions` tool. The MCP `instructions` field contains just one sentence telling it to do so [V-run].
   - **For deterministic "don't repeat mistakes," the harness must force-feed the lessons.** There are two ways:
     - (a) project.yml `initial_prompt: "{{ embed_memory('harness/lessons') }}"`, a v1.7.0 feature [V-run]. This still depends on the agent calling `initial_instructions`.
     - (b) Better: the harness inlines the same file into each CLI's own prompt/context channel. This works whether or not the agent ever touches Serena [I].
5. **Recommended design:** keep a committed `.serena/memories/` tree as the single source of truth. It is plain markdown, so it doubles as the "lessons" store for every CLI.
   - Agents may only write to `inbox/**`. All other memories are read-only via `read_only_memory_patterns: ["(?!inbox/).*"]` [V-run].
   - The harness (not the agent) curates verifier-failure lessons into a size-capped `harness/lessons.md` with stable IDs.
   - The harness lints with `serena memories check` plus custom checks. That command **always exits 0**, so parse its output [V].
   - Memory diffs are reviewed in the PR (CODEOWNERS).
   - Serena's read-only flag only guards Serena's own tools. Enforce the policy with a post-run `git diff` path gate [I].

---

## 1. Serena: version, install, run

### 1.1 Version and licensing
- PyPI `serena-agent` latest = **1.7.0** (uploaded 2026-08-09T18:38). The previous releases were 1.6.1 (07-21), 1.6.0 (07-16), 1.5.3 (05-26), 1.5.0 (05-18), 1.3.0 (05-11), 1.2.0 (04-27), 1.1.x (04-11..14) and 1.0.0 (2026-04-03) [V: PyPI JSON; CHANGELOG headers].
- `main` `pyproject.toml` version = `2.0.0.dev0` [V].
- `main` `server.json` (the MCP registry manifest) still says 1.5.3 and suggests `--context desktop-app` as the default. That manifest is stale [V].
- The README warns: **"Do not install Serena via an MCP or plugin marketplace! They contain outdated and suboptimal installation commands."** [V: README.md].
- License [V: main `LICENSE`, `CHANGELOG.md` Unreleased]:
  - main: "SolidLSP (`src/solidlsp`) under MIT … the Serena application (everything else) under GPL-3.0-or-later. Distributions combining both are as a whole subject to the GPL."
  - The changelog says "The change is not retroactive: all earlier releases and commits remain available under MIT." There is a git tag `mit-final`.
  - The v1.7.0 tag's `LICENSE` is plain MIT [V].
- Other breaking or behavioural changes on main (not yet released) [V: CHANGELOG Unreleased]:
  - The "Serena REPL" agent interface (reduced tool set).
  - Session IDs are now tracked internally. "Tools that need a session id (e.g. `activate_project`, the REPL tool) now take it as an explicit parameter".
  - Atomic memory writes.
  - The MCP server reports Serena's own version. In 1.7.0, `serverInfo.version` shows the MCP SDK version `1.28.1` [V-run].

### 1.2 Install (current recommendation)
- Official command: `uv tool install -p 3.13 serena-agent`, then `serena init` [V: README Quick Start, docs/02-usage/010_installation.md]. `uv` is the only prerequisite.
- `uvx -p 3.13 --from git+https://github.com/oraios/serena serena …` is documented only as an *alternative* ("previously the main way").
  - Docs: "every new commit in the repository will trigger a (potentially slow) re-synchronization … If you should experience timeouts when connecting the MCP server, consider switching." [V: docs/02-usage/020_running.md]
  - **For CI, never use the git+HEAD form.** It is non-reproducible and now pulls GPL `main` [I].
- Pinned forms for a harness [V-run]:
  - `uv tool install -p 3.13 serena-agent==1.7.0` provides the binaries `serena`, `serena-agent` and `serena-hooks`.
  - Or `uvx -p 3.13 --from serena-agent==1.7.0 serena …`.
- Other options: Docker `ghcr.io/oraios/serena:latest`, which DOCKER.md describes as "EXPERIMENTAL"; Nix `nix run github:oraios/serena`; run from a clone [V: docs 020_running, DOCKER.md].

### 1.3 Measured startup (local, macOS arm64) [V-run]

| Scenario | Time |
|---|---|
| Cold `uvx --from serena-agent==1.7.0 serena --version` with an empty `UV_CACHE_DIR` | **53.4 s** (321 MB uv cache) |
| Warm `uvx …` to MCP `initialize` response | 3.7–3.9 s |
| `uv tool install`ed binary, first start (bytecode compile) | 5.2 s |
| `uv tool install`ed binary, subsequent starts | **0.68–0.72 s** |
| `serena project index` on a 1-file Python repo | 1.8 s warm / 5.2 s cold-ish |

- The language server starts **asynchronously after** the MCP handshake (task `init_project_services`), so the handshake does not wait for LSP init [V-run: log order].
- **Implication:** the client startup timeouts are 5 s (OpenCode), 10 s (Codex) and `MCP_TIMEOUT` (Claude Code). A cold `uvx` would blow through all of them. **Pre-install in the CI image and warm it** (`serena --version`) [I, from the measurements].

### 1.4 `start-mcp-server` options (v1.7.0) [V: `src/serena/cli.py` lines 233–318]
- `--project <path|name>`. The positional form and `--project-file` are deprecated.
- `--project-from-cwd`: nearest ancestor containing `.serena/project.yml` or `.git`. It is mutually exclusive with `--project`.
- `--context` (default `desktop-app`).
- `--mode` (repeatable; **overrides** `default_modes`) and `--add-mode` (repeatable; adds on top).
- `--language-backend {LSP,JetBrains}`.
- `--transport {stdio,sse,streamable-http}` (default stdio), `--host` (default 127.0.0.1), `--port` (default 8000).
- `--enable-web-dashboard <bool>`, `--open-web-dashboard <bool>`, `--enable-gui-log-window <bool>`.
- `--log-level`, `--trace-lsp-communication <bool>`.
- `--tool-timeout <float>` (the config default is `tool_timeout: 240` seconds).
- Transport notes [V: docs 020_running]:
  - Streamable HTTP endpoint is `http://localhost:<port>/mcp`. SSE is "legacy … discouraged".
  - "Serena is a stateful MCP server, and only one coding project can be active at a time". Sharing one HTTP instance only makes sense if all clients use the same project.
  - For parallel agents on different worktrees, use **one stdio server per agent** [V].

### 1.5 Contexts and modes (v1.7.0) [V: `src/serena/resources/config/contexts/`, `modes/`; `serena context list`, `serena mode list` V-run]
- Contexts:
  - `agent`, `antigravity`, `chatgpt`, `claude-code`, `codebuddy`, `codex`, `copilot-cli`, `desktop-app` (default), `grok`, `ide`, `jb-ai-assistant`, `jb-copilot-plugin`, `junie`, `oaicompat-agent`, `vscode`.
  - **`ide-assistant` is a deprecated alias mapped to `claude-code`** (`context_mode.py` `legacy_name_mapping`).
  - There is **no** context for OpenCode, Gemini CLI or Kiro. The docs recommend `--context ide` for "terminal-based clients" such as Gemini-CLI and opencode [V: docs 030_clients "Other Clients"].
- What the CLI contexts exclude:
  - `claude-code` excludes `create_text_file, read_file, execute_shell_command, find_file, list_dir, search_for_pattern`. It sets `single_project: true` and `structured_tool_output: false`.
  - `codex` excludes `create_text_file, read_file, execute_shell_command, replace_content, find_file, list_dir`.
  - `ide` excludes the same as `claude-code` minus `search_for_pattern`, with `single_project: true`.
  - `agent` excludes `initial_instructions`; it is meant for Agno-style frameworks that pass the system prompt directly.
- Modes: `benchmark`, `editing`, `interactive`, `no-memories`, `no-onboarding`, `onboarding`, `one-shot`, `planning`, `query-projects`.
  - **`benchmark` excludes all memory tools.** Do not use it if you want memories [V].
  - `no-onboarding` excludes only the `onboarding` tool and keeps memory tools ("memories may have been created externally").
- **Mode composition gotcha** [V: serena_config.template.yml; V-run]:
  - Active modes = `base_modes` (global config, always on) + `default_modes` (overridable by project or `--mode`) + `added_modes`.
  - The default global config has `base_modes: [interactive, editing]`. Passing `--mode one-shot` therefore yields **interactive + editing + one-shot** together. The docs call that combination "semantically incompatible".
  - The `interactive` mode tells the LLM to ask the user for clarification "unless the user explicitly stated they are unavailable". **In CI, set `base_modes: [editing]`** in the harness's `serena_config.yml`.
  - Verified: active modes became `editing, no-onboarding, one-shot` [V-run].

### 1.6 Language servers in CI [V: docs/01-about/020_programming-languages.md; v1.7.0 source]
- Downloaded LS binaries live under **`$SERENA_HOME/language_servers/static`**. `SERENA_HOME` defaults to `~/.serena`.
  - `ls_manager.py` passes `solidlsp_dir=SerenaPaths().serena_user_home_dir`. The SolidLSP default `~/.solidlsp` is *not* used when running Serena.
  - Serena ≥1.5.0 no longer uses `~/solidlsp_tmp`; it uses OS temp dirs instead [V: CHANGELOG 1.5.0].
- Per-project symbol cache: `<repo>/.serena/cache/`. It is auto-gitignored [V-run: generated `.serena/.gitignore` contains `/cache` and `/project.local.yml`].
- Per-language requirements:

| Language | What it needs |
|---|---|
| Python | Default is Pyright, installed via **uvx** (pinned version). BasedPyright, ty and pyrefly also need `uv`/`uvx`. Jedi is an alternative. |
| TypeScript/JavaScript | Needs **node + npm** (asserted in code). Serena npm-installs `typescript` and `typescript-language-server` (default 5.1.3, configurable) into its resources dir. |
| Go | Requires `gopls` preinstalled. |
| Rust | Requires `rustup` (uses rust-analyzer from the toolchain). |
| Java | Downloads a ~500 MB vscode-java VSIX + Gradle. An offline "upstream JDTLS" mode exists (set `jdtls_path` + `lombok_path`). |
| C# | Roslyn, needs .NET 10+. |
| Zig | Needs ZLS. |
| Terraform | Downloads terraform-ls, needs `terraform` on PATH. |
| Kotlin | Managed Kotlin LSP. Builds expire, so it needs version bumps. |
| Others | Many auto-download. |

- Polyglot repos: `language_servers: [...]` in project.yml. The key was renamed from `languages` in 1.7.0; old configs are auto-migrated [V: CHANGELOG 1.7.0].
- Trusted projects: `ls_specific_settings` and `activation_command` in a **project.yml are ignored unless the project path matches `trusted_project_path_patterns`** in the global config [V: CHANGELOG 1.6.0; template]. In CI, set `trusted_project_path_patterns: ["**"]` or the workspace path.
- Indexing:
  - `serena project index [path]` caches document symbols. It **auto-creates and auto-registers** the project if `project.yml` exists or is generated [V: cli.py `index` uses `autoregister=True`; V-run].
  - `--timeout` is per file (default 10 s). Failures go to `.serena/logs/indexing.txt`.
  - `serena project health-check` exits 1 on failure since 1.7.0 [V: CHANGELOG 1.7.0], so it can be used as a CI gate.
  - Indexing is "only once", then incremental [V: docs 040_workflow].
- Other knobs [V: CHANGELOG 1.6.0/1.7.0]:
  - Per-LS `indexing_timeout`, `server_ready_timeout`, `indexing_start_grace`.
  - Monorepo restriction via `ls_workspace_folders`.

### 1.7 Other CI-relevant environment variables and behaviour [V: source grep]
- `SERENA_HOME` relocates config, logs, global memories, LS downloads, prompt and context overrides.
- **Usage reporting is auto-disabled when `CI=true` or `GITHUB_ACTIONS=true`**, or when `SERENA_USAGE_REPORTING=false` (`agent.py:725`).
- Logs go to `$SERENA_HOME/logs/<date>/mcp_<ts>_<pid>.txt` and to stderr. **stdout is reserved for MCP**.
- **Serena rewrites `serena_config.yml`.** It fills in defaults and appends registered project paths. A minimal 11-line config was expanded to 211 lines [V-run]. Do not mount it read-only; generate it per job.
- Parallel agents auto-registering projects could clobber `serena_config.yml` in ≤1.7.0. This is fixed on main [V: CHANGELOG Unreleased]. **Give each parallel agent its own `SERENA_HOME`**, or pre-register the project [I].
- Memory writes in 1.7.0 use truncating `open(path,"w")`. The atomic temp+replace fix is on main only [V: main CHANGELOG "Memories"]. **Avoid concurrent writers to the same memory** [I].
- Memory files are written in text mode without `newline=` (native line endings). Docs: "Serena's own files (e.g. memories and configuration files) always use native line endings" [V: template comment; memory_manager.py]. On Windows runners this produces CRLF. Add `.gitattributes`: `.serena/** text eol=lf` [I].

---

## 2. Serena memories

### 2.1 Storage and format [V: docs/02-usage/045_memories.md; `memory_manager.py`; V-run]
- Project memories live at `<repo>/.serena/memories/**/*.md`.
  - The location is configurable via the global `project_serena_folder_location` (default `"$projectDir/.serena"`; `$projectFolderName` is also supported).
- Global memories have names beginning `global/`. They are stored under `~/.serena/memories/global/` (i.e. `$SERENA_HOME/memories/global/`).
- Name to path: `"lessons/auth/token-refresh"` maps to `.serena/memories/lessons/auth/token-refresh.md`.
  - Names are sanitised: the `mem:` prefix and a `.md` suffix are stripped, and `os.sep` is normalised.
  - `..` and absolute names are forbidden (security fixes in 1.2.0 and 1.6.0).
- Content is the raw string, utf-8. **No front matter or metadata is added** [V-run: `xxd` shows the file starts with `# Core\n`].
- Listing is sorted and recursive, and follows symlinks (1.6.0). It returns `{"memories":[…], "read_only_memories":[…]}` [V-run].
- References use the convention `` `mem:<name>` `` (in backticks).
  - `rename_memory` rewrites references across all writable memories.
  - `serena memories check` reports stale references [V].
- Docs design rationale (abridged) [V]:
  1. Human-readable and editable.
  2. **"Versionable with the project. Project memories live alongside the code and can be committed, reviewed in PRs, and reverted"**.
  3. Progressive disclosure: names up front, with `mem:core` as the entry point.
  4. **"Prefer references to search"**: no semantic or lexical search, by design.
  5. **"Prefer deliberate reads to triggers. … The harness does not inject memory content"**.
  6. Framework-agnostic plain Markdown.
  7. Configurable scopes with read-only and ignored patterns.
  - The docs explicitly reject DB/vector memory, single-file `AGENTS.md` conventions, and hook-based memory.
  - Answer to "2026 memory search?": **there is none**. It is deliberately excluded [V].

### 2.2 MCP tools (v1.7.0) [V: `src/serena/tools/memory_tools.py`, `workflow_tools.py`; V-run tools/list]
- `write_memory(memory_name, content, max_chars=-1)`: rejects content longer than `default_max_tool_answer_chars` (150000).
- `read_memory(memory_name)`.
- `list_memories(topic="")`.
- `delete_memory(memory_name)`: its description says "only call if instructed explicitly or permission was granted".
- `rename_memory(old_name, new_name)`: propagates `mem:` references.
- `edit_memory(memory_name, needle, repl, mode: "literal"|"regex", allow_multiple_occurrences=False)`.
- `onboarding()`: returns onboarding instructions and seeds `memory_maintenance`.
- `initial_instructions()`: returns the full "Serena Instructions Manual", plus the `<active-project>` block containing the memory name list and the project `initial_prompt`.
- **`check_onboarding_performed` was deleted in v1.5.0.** Its information now lives in the activation message [V: CHANGELOG 1.5.0]. **There is no `move_memory` MCP tool.** `move_memory` is an internal method; rename covers moves.
- With `--context claude-code --project X`, 1.7.0 exposed 21 tools [V-run]: `replace_content, replace_in_files, replace_symbol_body, insert_after_symbol, insert_before_symbol, get_symbols_overview, find_symbol, find_referencing_symbols, find_implementations, find_declaration, get_diagnostics_for_file, rename_symbol, safe_delete_symbol, write_memory, read_memory, list_memories, delete_memory, rename_memory, edit_memory, onboarding, initial_instructions`.

### 2.3 CLI (no MCP server needed) [V: `serena memories --help` V-run; cli.py]
- `serena memories {list [--topic], read, write [--content|--file|stdin], delete, rename, edit --needle --repl [--mode literal|regex] [--allow-multiple…], check [--include-unmarked] [--fuzzy-matching], auto-prefix-references [--dry-run …], initialize}`.
- Gotchas:
  - The CLI requires the project to be **registered** in `$SERENA_HOME/serena_config.yml`. Otherwise it fails with "No Serena project found … Create one first". Run `serena project index` (auto-registers) or `serena project create` first [V: cli.py `_load_memories_manager`].
  - The CLI bypasses read-only patterns (`is_tool_context=False`). Read-only applies to agent tool calls only [V: memory_manager `_check_write_access`].
  - **`serena memories check` "Always exits 0"** (in its help text). It printed `Stale references (1)` and exited 0 [V-run]. **CI must grep the output.**

### 2.4 Onboarding and how agents learn about memories [V: `agent.py`, `simple_tool_outputs.yml`, `system_prompt.yml`; V-run]
- At MCP connect, the server `instructions` field is only: *"CRITICAL: Before starting to work on a coding task, call the `initial_instructions` tool to read the 'Serena Instructions Manual'."* [V-run]
  - The full manual is lazy-loaded (since 1.2.0).
- The manual says *"You generally have access to memories … You infer whether memories are relevant based on their names."* It lists global memories.
- The `<active-project>` block contains the JSON list of project memory names plus *"Use the `read_memory` tool to read these memories later if they are relevant to the task."*
- If there are no memories and `onboarding` is available, it says instead: *"Onboarding has not been performed yet. Ask the user whether to perform onboarding…"*.
  - In CI that line is harmful; it would invite a question with nobody to answer. **Commit memories, and/or use the `no-onboarding` mode** [I].
- Onboarding prompt targets: `mem:core`, `mem:tech_stack`, `mem:suggested_commands`, `mem:conventions`, `mem:task_completion`, plus per-module `mem:<module>/core`. It must first read `mem:memory_maintenance`.
- `memory_maintenance` seeding precedence:
  1. If `global/memory_maintenance` exists, it is used.
  2. Otherwise an existing project copy is kept.
  3. Otherwise the shipped template is written. Files are never overwritten.
  - The shipped template rules: "Dense agent notes, not prose"; "Add or update memories only with stable, non-obvious project conventions…"; "Do not add: … one-off task notes; volatile line-level details". **This matches a curated lessons file well** [V: `resources/memory_maintenance.md`].
- **Forcing content into context (v1.7.0)** [V: docs 050_configuration "Prompt Templates"; `agent.py._render_prompt`; V-run]:
  - project.yml `initial_prompt` (and context/mode prompts) are Jinja templates with `embed_memory(name)`.
  - The output is wrapped in `<memory name="…">…</memory>` inside `<project-instructions>`.
  - Verified: the lessons content appeared inline in the `initial_instructions` output.
  - The template runs in a sandboxed Jinja environment (1.7.0 security note).
  - If the memory is missing, an error is logged and nothing is rendered. That failure is silent to the agent, so the harness should lint for it [V/I].
- `serena print-system-prompt [project] --context X --mode Y [--only-instructions]` prints the full manual, including activation. **The harness can capture this and inject it via a CLI's system-prompt flag**, which removes the "did the agent call initial_instructions?" variance [V: cli.py; I for usage].

### 2.5 Configuration fields
- **`.serena/project.yml`** (versioned) [V: `resources/project.template.yml` v1.7.0]:
  - `project_name`, `language_servers` (was `languages`), `encoding`.
  - `activation_command`, `activation_command_timeout` (180 s; trusted projects only).
  - `line_ending`, `language_backend`, `ignore_all_files_in_gitignore` (true).
  - `ls_specific_settings` (trusted only), `ls_workspace_folders`, `ls_additional_workspace_folders`.
  - `ignored_paths`, **`read_only`** (disables all editing tools).
  - `excluded_tools`, `included_optional_tools`, `fixed_tools`.
  - `default_modes`, `added_modes` (projects can no longer override `base_modes` since 1.3.0).
  - **`initial_prompt`**, `symbol_info_budget`.
  - **`read_only_memory_patterns`**, **`ignored_memory_patterns`** (regex `fullmatch`, merged additively with global).
- `.serena/project.local.yml` holds local overrides and is gitignored [V].
- **`$SERENA_HOME/serena_config.yml`** (global) [V: `resources/serena_config.template.yml`]:
  - `language_backend`, `line_ending`, `gui_log_window`.
  - `web_dashboard` (default True), `web_dashboard_open_on_launch` (True), `web_dashboard_interface`, `web_dashboard_listen_address`, `web_dashboard_trusted_hosts`.
  - `jetbrains_*`, `log_level`, `trace_lsp_communication`, `ls_specific_settings`, `ls_priorities`.
  - `ignored_paths`, `read_only_memory_patterns`, `ignored_memory_patterns`.
  - `tool_timeout` (240), `excluded_tools`, `included_optional_tools`, `fixed_tools`.
  - **`base_modes` ([interactive, editing])**, `default_modes`, `default_max_tool_answer_chars` (150000).
  - `token_count_estimator`, `symbol_info_budget`, `project_serena_folder_location`, **`trusted_project_path_patterns`**, `projects`.
  - It is auto-generated from the template if missing [V: `from_config_file(generate_if_missing=True)`].
- Docker guidance: `web_dashboard_open_on_launch: False`, "not possible within the container" [V: DOCKER.md].
- Prompt overrides: `$SERENA_HOME/prompt_templates/*.yml`. Custom contexts and modes go in `$SERENA_HOME/contexts/`, `$SERENA_HOME/modes/` [V: docs 050_configuration; serena_config.py].
- Disable switches [V: docs 045_memories]:
  - The `no-memories` mode removes all memory tools and onboarding.
  - The `no-onboarding` mode removes only onboarding.

### 2.6 Hooks (alpha) [V: docs 030_clients; CHANGELOG 1.1.0–1.7.0]
- `serena-hooks {activate, remind, auto-approve, cleanup}` with `--client=claude-code|codex|grok|…`.
  - `activate` (SessionStart) prompts the agent to activate the project and read the instructions.
  - `remind` (PreToolUse) nudges the agent after too many grep/read calls.
  - `auto-approve` covers Claude `acceptEdits`/`auto`.
- Codex needs the `[features] codex_hooks = true` flag and `~/.codex/hooks.json`. `SessionEnd` cleanup needs Codex ≥0.145.0.
- These improve *tool adoption*. They do not inject memory content.

---

## 3. Integration recipes (per CLI)

Assume Serena is pre-installed at `$SERENA_BIN` (e.g. `/opt/serena/bin/serena`) and `SERENA_HOME=$RUNNER_TEMP/serena-home`. Pass an absolute path: the Serena docs warn that clients may not find `serena` on PATH [V: docs 030_clients "Common Pitfalls"].

### 3.1 Claude Code (`claude -p`, v2.1.288 locally)
- Serena docs [V: docs 030_clients]:
  - `claude mcp add serena -- serena start-mcp-server --context claude-code --project "$(pwd)"` (per project).
  - `claude mcp add --scope user serena -- serena start-mcp-server --context claude-code --project-from-cwd` (global).
  - Set `MCP_TIMEOUT` (e.g. `60000`) if startup is slow.
  - Serena also recommends `claude --system-prompt="$(serena prompts print-cc-system-prompt-override)"`, citing CC/Opus bias against external tools.
    - In a harness, **prefer `--append-system-prompt`** so you don't lose CC's own system prompt [I].
- Claude Code flags [V: local `claude --help`; code.claude.com/docs/en/mcp]:
  - `--mcp-config <files-or-json…>`, `--strict-mcp-config` ("Only use MCP servers from --mcp-config, ignoring all other MCP configurations").
  - `--append-system-prompt`, `--allowedTools`, `--permission-mode`, `--bare`.
  - JSON format: `{"mcpServers":{"name":{"type":"stdio","command":…,"args":[…],"env":{…}}}}`.
  - In `claude -p`, project `.mcp.json` servers "load without asking".
  - `MCP_TIMEOUT` is the startup timeout in ms. `MAX_MCP_OUTPUT_TOKENS` defaults to 25000.
  - Tool search (deferred MCP tool loading) is on by default for Claude 4.5+. This is exactly why Serena's `claude-code` context prompt shouts about loading Serena tools.
- Harness snippet (`harness/mcp/claude.serena.json`) [config shape V; values I]:
  ```json
  {
    "mcpServers": {
      "serena": {
        "type": "stdio",
        "command": "/opt/serena/bin/serena",
        "args": ["start-mcp-server", "--context", "claude-code", "--project", "${CLAUDE_PROJECT_DIR}",
                 "--enable-web-dashboard", "false", "--open-web-dashboard", "false",
                 "--mode", "one-shot", "--mode", "no-onboarding"],
        "env": { "SERENA_HOME": "/tmp/serena-home", "CI": "true" }
      }
    }
  }
  ```
  ```bash
  MCP_TIMEOUT=30000 claude -p "$TASK" --mcp-config harness/mcp/claude.serena.json --strict-mcp-config \
    --append-system-prompt "$(cat .serena/memories/harness/lessons.md)" \
    --allowedTools "mcp__serena__*" ...
  ```
  - `${CLAUDE_PROJECT_DIR}` expansion in `command`/`args` is documented for `.mcp.json` [V: docs/en/mcp, "can use `${CLAUDE_PROJECT_DIR}`"]. For `--mcp-config` files it is [U]. Substituting the absolute path in the harness is safest [I].
- Auto memory: Claude Code also has a **machine-local** auto memory at `~/.claude/projects/<project>/memory/MEMORY.md`. The first 200 lines or 25 KB load every session.
  - Disable it in CI with `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` or `autoMemoryEnabled: false`, so that unreviewed, non-portable state can't leak between runs [V: code.claude.com/docs/en/memory; I for the recommendation].

### 3.2 Codex CLI
- Serena docs [V: docs 030_clients]: run `serena setup codex`, or add to `~/.codex/config.toml`:
  ```toml
  [mcp_servers.serena]
  startup_timeout_sec = 15
  command = "serena"
  args = ["start-mcp-server", "--project-from-cwd", "--context=codex"]
  ```
- Codex docs [V: learn.chatgpt.com/docs/extend/mcp?surface=cli, redirected from developers.openai.com/codex/mcp]:
  - Supported keys: `command, args, env, env_vars, cwd, startup_timeout_sec` (default **10**), `tool_timeout_sec` (default **60**), `enabled, required, enabled_tools, disabled_tools`.
  - Project-scoped `.codex/config.toml` works for **trusted projects only**.
  - `codex mcp add <name> --env K=V -- <command>`.
- Harness snippet [I, built on the verified keys]:
  ```toml
  [mcp_servers.serena]
  command = "/opt/serena/bin/serena"
  args = ["start-mcp-server", "--context", "codex", "--project", "/workspace/repo",
          "--enable-web-dashboard", "false", "--open-web-dashboard", "false",
          "--mode", "one-shot", "--mode", "no-onboarding"]
  env = { SERENA_HOME = "/tmp/serena-home", CI = "true" }
  startup_timeout_sec = 30
  tool_timeout_sec = 300   # Serena's own tool_timeout is 240 s; keep Codex's above it
  required = true          # fail fast if Serena is down
  ```
  - Writing this to an isolated `CODEX_HOME` per job is [U]. The env var is not verified here.
- Codex has no lessons channel equivalent to `--append-system-prompt` in this research. Use `AGENTS.md`, which Codex reads, or prepend the lessons to the `codex exec` prompt [I/U].

### 3.3 OpenCode (`opencode run`, v1.18.33 locally)
- [V: opencode.ai/docs/mcp-servers]: under `"mcp"`, use `{"type":"local","command":[…],"cwd","environment":{…},"enabled":true,"timeout":<ms>}`.
  - **`timeout` = "Timeout in ms for fetching tools from the MCP server. Defaults to 5000 (5 seconds)."**
  - Per-agent tool globs: `"tools": {"serena*": false}`.
- Harness snippet:
  ```jsonc
  {
    "$schema": "https://opencode.ai/config.json",
    "mcp": {
      "serena": {
        "type": "local",
        "command": ["/opt/serena/bin/serena", "start-mcp-server", "--context", "ide",
                    "--project", "/workspace/repo", "--enable-web-dashboard", "false",
                    "--open-web-dashboard", "false", "--mode", "one-shot", "--mode", "no-onboarding"],
        "environment": { "SERENA_HOME": "/tmp/serena-home", "CI": "true" },
        "enabled": true,
        "timeout": 20000
      }
    }
  }
  ```
  - Non-interactive: `opencode run --auto … "<prompt>"` [V: local `opencode run --help`: `--auto` "auto-approve permissions that are not explicitly denied (dangerous!)"; also `--format json`, `--dir`].

### 3.4 Kiro (IDE and kiro-cli)
- [V: kiro.dev/docs/mcp/configuration]:
  - Workspace config `.kiro/settings/mcp.json`; user config `~/.kiro/settings/mcp.json`. Workspace takes precedence.
  - Keys: `mcpServers.{name}.{command,args,env,disabled,autoApprove,disabledTools}`.
  - Priority: agent config > workspace > global.
- [V: kiro.dev/docs/custom-agents/configuration-reference]:
  - Agent JSON (`.kiro/agents/*.json`) has `mcpServers` (with `timeout`, e.g. 120000) and `includeMcpJson`.
  - Tools are referenced as `"@serena"` or `"@serena/find_symbol"` in `tools`/`allowedTools`.
  - **`resources: ["file://…"]` globs are "loaded directly into the agent's context when the agent starts"**. This is a deterministic channel for lessons.
- Steering [V: kiro.dev/docs/steering]:
  - `.kiro/steering/*.md` with `inclusion: always|fileMatch|manual|auto`. AGENTS.md is always included.
  - CLI V3 supports all four modes. Custom agents need steering listed in `resources`.
- Snippet (`.kiro/agents/harness-impl.json`, shape V, values I):
  ```json
  {
    "name": "harness-impl",
    "mcpServers": {
      "serena": {
        "command": "/opt/serena/bin/serena",
        "args": ["start-mcp-server", "--context", "ide", "--project", "/workspace/repo",
                 "--enable-web-dashboard", "false", "--open-web-dashboard", "false",
                 "--mode", "one-shot", "--mode", "no-onboarding"],
        "env": { "SERENA_HOME": "/tmp/serena-home", "CI": "true" },
        "timeout": 120000
      }
    },
    "tools": ["*"],
    "allowedTools": ["@serena"],
    "resources": ["file://.serena/memories/harness/lessons.md", "file://.kiro/steering/**/*.md"]
  }
  ```
- Serena's docs have no Kiro section, so use `--context ide` [V: by absence in docs 030_clients].
- The exact kiro-cli non-interactive flags are [U] here; another research file should cover them.

### 3.5 Gemini CLI
- [V: github.com/google-gemini/gemini-cli docs/tools/mcp-server.md]:
  - `~/.gemini/settings.json` or `.gemini/settings.json` → `mcpServers.{name}.{command,args,env,cwd,timeout,trust,includeTools,excludeTools}`.
  - `timeout` default **600000 ms**.
  - `gemini mcp add [-s user|project] [-e K=V] [--timeout] [--trust] <name> <command> [args…]`.
- Snippet:
  ```json
  { "mcpServers": { "serena": {
      "command": "/opt/serena/bin/serena",
      "args": ["start-mcp-server","--context","ide","--project","/workspace/repo",
               "--enable-web-dashboard","false","--open-web-dashboard","false",
               "--mode","one-shot","--mode","no-onboarding"],
      "env": {"SERENA_HOME":"/tmp/serena-home","CI":"true"},
      "timeout": 600000, "trust": true } } }
  ```
  - `trust: true` bypasses confirmations, which you need headless [V: doc "bypass all tool call confirmation prompts"].

### 3.6 Known headless/CI issues and gotchas (consolidated)

| # | Gotcha | Mitigation | Label |
|---|---|---|---|
| 1 | Cold `uvx` start took 53 s; client startup limits are 5 s (OpenCode), 10 s (Codex default; Serena suggests 15) and `MCP_TIMEOUT` (Claude) | Bake `uv tool install serena-agent==1.7.0` into the image and run `serena --version` once to precompile. Cache `UV_CACHE_DIR`. | V-run / V |
| 2 | Default global config opens a dashboard/browser and includes the `interactive` mode | Ship a harness `serena_config.yml` with `web_dashboard: false`, `web_dashboard_open_on_launch: false`, `gui_log_window: false`, `base_modes: [editing]`, `default_modes: [one-shot, no-onboarding]` | V-run |
| 3 | `ls_specific_settings` and `activation_command` in project.yml are silently ignored unless trusted | Set `trusted_project_path_patterns` | V |
| 4 | LS binaries download at runtime into `$SERENA_HOME/language_servers/static` (TS via npm needs node/npm; Go/Rust need preinstalled toolchains) | Cache that dir keyed on Serena version, and run `serena project index` as a warm-up step | V / I |
| 5 | GitHub's gh-aw ships Serena in CI and hit languages missing from `project.yml` or missing LS binaries in its container | Make `language_servers` explicit; preinstall LS deps. gh-aw recommends a pinned cache key for Serena's LS indexes across runs | D: github.com/github/gh-aw-mcpg/issues/913; github.github.com/gh-aw/reference/serena/ |
| 6 | `serena memories check` exits 0 even when stale refs exist | Grep for `Stale references` | V-run |
| 7 | Memories CLI requires the project to be registered in `serena_config.yml` | Run `serena project index` first | V |
| 8 | `serena_config.yml` is rewritten at runtime; parallel registration races in ≤1.7.0 | One `SERENA_HOME` per parallel agent, or pre-register | V / I |
| 9 | Non-atomic memory writes in 1.7.0 | Single writer per memory: agents write only to `inbox/<run-id>/` | V / I |
| 10 | The agent might never load Serena tools or call `initial_instructions` (CC tool search; Serena docs admit "drastically reduced adherence" with CC/Opus 4.7) | Never rely on Serena alone to deliver lessons | V: docs 030_clients "attention" box |
| 11 | `read_only_memory_patterns` only constrains Serena tools. The agent's native Edit/Write/shell can still modify `.serena/memories/*.md` | Harness post-run gate rejects diffs under `.serena/memories/` outside `inbox/`; optionally add native-tool deny rules | V (code) / I |
| 12 | MCP `serverInfo.version` in 1.7.0 reports the MCP SDK version (1.28.1), not Serena's | Check `serena --version` instead | V-run |

---

## 4. Reproducible memory design for the harness

### 4.1 Requirements → mechanisms

| Requirement | Mechanism | Label |
|---|---|---|
| Same knowledge in every run, any CLI | Committed `.serena/memories/` (plain md). The harness injects `harness/lessons.md` through each CLI's own channel (§4.4) **and** via Serena `initial_prompt` `embed_memory` | V (format, embed) / I (design) |
| Auditable | Git history plus PR review of `.serena/memories/**` diffs; CODEOWNERS on that path. Every lesson carries provenance (run id, spec, verifier finding) | I |
| Agents can't corrupt curated knowledge | `read_only_memory_patterns: ["(?!inbox/).*"]` (only `inbox/**` writable via Serena; verified that `write_memory core` → PermissionError and `inbox/run-42/x` OK). Plus a post-run `git diff --name-only` gate | V-run / I |
| No bloat or contradictions | Harness-owned curation step with hard caps, dedupe keys, `supersedes:` links, `_archive/` hidden via `ignored_memory_patterns` | V (ignored patterns) / I |
| Works without Serena | Format is plain md; the harness uses file I/O or `serena memories …` CLI | V-run |

### 4.2 Proposed layout (committed)
```
.serena/
  project.yml                 # language_servers, initial_prompt, memory patterns (versioned)
  .gitignore                  # auto: /cache, /project.local.yml
  memories/
    core.md                   # entry point (human-owned): links `mem:harness/lessons`, `mem:conventions`, …
    memory_maintenance.md     # harness-customised conventions (read-only)
    conventions.md, suggested_commands.md, task_completion.md, tech_stack.md   # onboarding-style, human-reviewed
    harness/
      lessons.md              # CURATED, capped (≤ ~60 bullets / ≤ 8 KB), stable IDs, always injected
      lessons/<area>/<id>-<slug>.md   # detail per lesson (evidence, repro, fix pattern), read on demand
    inbox/<run-id>/*.md       # ONLY agent-writable area; proposals; harness drains each loop
    _archive/YYYY-MM/*.md     # superseded/retired; hidden via ignored_memory_patterns
```
- project.yml excerpt (keys V, values I):
  ```yaml
  initial_prompt: |
    Harness lessons (mandatory; violating any is a verifier FAIL):
    {{ embed_memory("harness/lessons") }}
    If you learn a durable, non-obvious lesson, write it with write_memory under "inbox/<run-id>/".
  read_only_memory_patterns: ["(?!inbox/).*"]
  ignored_memory_patterns: ["_archive/.*"]
  ```
- `.gitattributes`: `.serena/** text eol=lf` [I].

### 4.3 Lesson entry schema (in `harness/lessons.md`) [I]
```
- **L-0042** [active] (area: auth/session; first: 2026-09-12 run 8812; hits: 3; last: 2026-10-01)
  Rule: never refresh tokens inside `SessionStore.get`; use `TokenRefresher` (`mem:harness/lessons/auth/L-0042-refresh-outside-get`).
  Trigger: verifier finding V-RACE-01 on spec `openspec/changes/session-ttl`.
```
- One bullet per lesson, imperative, testable. IDs are never reused.
- `supersedes: L-00xx` retires the old entry. The old entry moves to `_archive/`.
- A machine-checkable block such as `<!-- lesson: id=L-0042 key=auth.session.refresh-in-get status=active -->` lets the linter dedupe by `key` [I].

### 4.4 Loop integration (implement → verify → fix-spec → implement) [I]
1. **Pre-run (deterministic):**
   - Restore caches.
   - Write the harness `serena_config.yml`.
   - Run `serena project index`, then `serena project health-check` (exit≠0 → degrade to no-Serena mode, don't fail the loop).
   - Lint memories:
     - `serena memories check | grep -q 'Stale references' && fail`.
     - Size caps.
     - Schema regex.
     - Unique IDs and keys.
     - `embed_memory` targets exist.
   - Record `sha256` of `.serena/memories/**` in the run manifest. Same hash → same knowledge (auditability).
2. **Inject lessons per CLI, belt and braces:**

   | CLI | Channel |
   |---|---|
   | Claude | `--append-system-prompt "$(cat …/harness/lessons.md)"` |
   | Kiro | agent `resources: ["file://.serena/memories/harness/lessons.md"]` [V channel] |
   | Codex / OpenCode / Gemini | prepend to the task prompt, or reference from `AGENTS.md`, which those tools read [I/U per tool] |

   Plus Serena `embed_memory` for agents that do call `initial_instructions`.
3. **Implement run:** the agent may read any memory and write only to `inbox/<run-id>/`.
4. **Verify:** the adversarial verifier emits structured findings (id, severity, root-cause category, file/symbol, spec ref).
5. **Distill (harness, single writer):** for each FAIL finding the harness:
   - computes a dedupe key;
   - on a hit, increments `hits` and updates `last` in place;
   - on a miss, drafts a new lesson. Use an LLM *with the schema* but keep the output gated by the linter; see the note below;
   - merges any `inbox/` proposals that the verifier corroborates and discards the rest;
   - enforces caps. When over the cap, demote the lowest-value lessons (hits × recency) to their detail file only (still referenced via `mem:`), or archive them;
   - checks contradictions: same `key`, different rule → require an explicit `supersedes`, or else fail the curation step and escalate to a human.
   - Note: "the agent is never its own oracle". A lesson enters `harness/lessons.md` only if a *verifier* finding backs it, not the implementer's self-report.
6. **Commit:** `.serena/memories/**` changes go in a separate commit on the change branch, e.g. `chore(memory): L-0042 …`. The PR shows the memory diff for review. CODEOWNERS for `.serena/memories/harness/` requires human approval before merge to main. Unmerged lessons apply only within that branch's loop.
7. **Periodic:** a consolidation job (weekly or per N runs) merges near-duplicates, archives lessons with no hits in K runs, and re-validates that each lesson still matches the code (symbols still exist). Serena `find_symbol` or the linter can check `mem:`-referenced symbols [I].

### 4.5 Serena memories vs alternatives

| Option | Where | Loaded how | Portable across CLIs | Reviewable in git | Notes |
|---|---|---|---|---|---|
| **Serena memories** | `.serena/memories/**.md` (+ `~/.serena/memories/global`) | Names in activation msg; agent reads on demand; `embed_memory` for forced inline; no search | Yes, via MCP (any client) **if** the agent uses Serena | Yes (designed for it) | Read-only/ignored patterns; `mem:` ref integrity; rename propagation; CLI without a server [V] |
| `AGENTS.md` / `CLAUDE.md` | repo root/subdirs | Auto-loaded every session by the CLI | Broad: Claude Code reads AGENTS.md natively (v2.1.277+, only when no CLAUDE.md, unless configured); Kiro always includes AGENTS.md; Codex/OpenCode use it [V Claude, Kiro; I others] | Yes | Single file grows; Serena docs reject it for progressive disclosure [V] |
| `docs/lessons/*.md` + harness injection | repo | Whatever the harness injects | Yes (harness-controlled) | Yes | The simplest deterministic option [I] |
| Claude Code auto memory | `~/.claude/projects/<p>/memory/MEMORY.md` + topic files | First 200 lines / 25 KB auto-loaded | Claude only; **machine-local** ("not shared across machines or cloud environments") | No (unless `autoMemoryDirectory` is redirected) | Disable in CI [V: code.claude.com/docs/en/memory] |
| Kiro steering | `.kiro/steering/*.md` | `always`/`fileMatch`/`manual`/`auto` front matter | Kiro only | Yes | The `fileMatch` scoping is nice; custom CLI agents need `resources` [V: kiro.dev/docs/steering] |
| Cline "Memory Bank" | `memory-bank/{projectbrief,productContext,activeContext,systemPatterns,techContext,progress}.md` | Custom instruction "MUST read ALL memory bank files at the start of EVERY task" | Prompt pattern, any agent | Yes | Read-everything doesn't scale; mixes volatile `activeContext`/`progress` with durable facts [V: docs.cline.bot/features/memory-bank; I critique] |
| mem0 / OpenMemory MCP | local vector DB (Qdrant etc.) | Semantic `search_memory` | Any MCP client | **No** (DB state) | Non-deterministic retrieval; hard to diff/review [D: mem0.ai/blog/introducing-openmemory-mcp; I] |
| Letta memory blocks / `.af` | Letta server, Agent File export | Always-in-context editable blocks | Letta agents | Partly (.af export) | Requires a Letta runtime; heavyweight for a CI harness [D: docs.letta.com agent-file; I] |

**When Serena is the better choice [I]:**
- You already want Serena's **symbolic code tools** (the main value per the README, with the verifier and implementer benefiting from `find_referencing_symbols`, `rename_symbol` and the rest). Memory then comes "for free" in the same MCP server, using names-first progressive disclosure that scales better than one big AGENTS.md.
- You want **tool-enforced write scoping** (read-only patterns) and **reference integrity** (`mem:` + `check` + rename propagation) across a growing knowledge graph.

**When plain files are enough [I]:**
- The only goal is "don't repeat the same mistakes" across runs. A committed `docs/lessons/` or `.serena/memories/harness/lessons.md` injected by the harness into every CLI is fully deterministic and needs no MCP server, LS downloads or startup risk.
- Many CLIs in the matrix have weak MCP adherence. Serena's own docs concede reduced adherence in Claude Code with recent models.

**Recommended hybrid [I]:** store everything in `.serena/memories/`, which is plain markdown and costs nothing extra.
- Treat Serena as an *optional accelerator*. When it's healthy, agents get the symbolic tools, on-demand memory reads and `inbox/` writes. When it's unavailable, the harness still injects `harness/lessons.md`.
- Determinism comes from the harness-owned injection and curation, not from Serena.
- Point `AGENTS.md`/`CLAUDE.md` at the lessons with one line, e.g. "Read `.serena/memories/harness/lessons.md` before coding". Do not duplicate the content.

---

## 5. Self-check (what could be wrong)
- **Most damaging if wrong:** that memories are plain md and the harness can write them directly. This was re-derived from source (`save_memory` writes the raw string) and from a run (hexdump; an externally written `lessons/L-002.md` appeared in `memories list` and MCP `list_memories`) [V-run]. Survives.
- The flag names `--enable-web-dashboard` / `--open-web-dashboard` / `--mode` / `--add-mode` were verified against v1.7.0 source and run [V-run]. They may change in 2.0 (main), so pin the version.
- License claims rest on repo `LICENSE` files and CHANGELOG text. The implications for invoking Serena as a subprocess are [I], not legal advice.
- Client-side config keys come from vendor docs fetched today. Values in the snippets (timeouts, paths) are my choices [I]. Not verified:
  - `${CLAUDE_PROJECT_DIR}` expansion inside `--mcp-config` files,
  - `CODEX_HOME` isolation,
  - kiro-cli headless flags,
  - Gemini/Codex/OpenCode reading of `AGENTS.md`. These are marked [U]/[I].
- Startup numbers come from macOS arm64 with a fast network. Linux CI runners will differ; the order of magnitude (tens of seconds cold, sub-second warm) is what matters [I].
