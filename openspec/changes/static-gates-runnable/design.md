## Context

`agent_step` (`src/l4/implementer/tdd.py`) builds the implementer's `RunRequest` with
`PermissionPolicy("implement", gate_prefix=wb.cfg.gates.test.command)`; `l4.sim.dryrun` builds the same policy.
`PermissionPolicy.gate_prefix` (`src/l4/agents/base.py`) is "the only shell command an implementer may run".

How each adapter uses it in implement mode:

- claude-code (`claude_code.py`, the `else` branch of the argv): `--allowedTools` gets `Read, Glob, Grep, Edit(./**),
  Edit(/<result dir>/**)` and `Bash(<gate_prefix>:*)` when the prefix is set; `--permission-mode dontAsk` refuses every
  other Bash call.
- copilot-cli (`copilot_cli.py`, `gate_rule`): `--allow-tool=shell(<first word of the prefix>:*)`; the CLI's rule
  language matches a command's first word only.
- opencode (`opencode.py`, `config_content`): `bash: {"*": "allow", <git writes>: "deny"}` in implement mode; OpenCode 2
  (`opencode_v2.py`) has its own allow-list with shell allowed; codex runs `-s workspace-write` with no command filter;
  kiro-cli trusts `execute_bash`. None of them reads `gate_prefix` for the shell.

`prompt.py` builds the `# Gate command` section: "Run tests only with `{gate_command}` ...", then, when
`static_gate_commands` is not empty, "The harness also runs {listed} after your step ..." (red: the new tests must pass
them; other roles: the task is rejected while they fail).

The consumers' lint and typecheck commands hold no shell operator (`&&`, `|`, `;`): `pnpm run lint`,
`.venv/bin/ruff check --extend-exclude .l4 .`, `uv run --frozen --directory apps/admin-api mypy --strict
src/admin_api/`, `sh .l4/gates/lint-go.sh`.

## Goals / Non-Goals

**Goals:** an implementer can run the configured lint and typecheck commands before it finishes, on every adapter;
the prompt says so.

**Non-Goals:** allowing any other command (`node`, `tsc` on its own, the build or e2e gates); changing what the harness
runs after the step or how it judges it; changing opencode, codex or kiro-cli; a rule for a judge, a reader or the
delegate.

## Decisions

### D1. `PermissionPolicy` carries the static commands

Add `static_commands: tuple[str, ...] = ()` to `PermissionPolicy` (the `gates.lint` then `gates.typecheck` commands,
in configuration order, duplicates removed, empty strings dropped). `gate_prefix` keeps its meaning (the test gate).
`agent_step` and `l4.sim.dryrun` pass `static_commands=(*cfg.gates.lint, *cfg.gates.typecheck)`. Every other
`PermissionPolicy(...)` construction (judge, read-only, hello, probes) keeps the default `()`.

### D2. claude-code: one rule per distinct command

In the implement branch, after `Bash(<gate_prefix>:*)`, append `Bash(<command>:*)` for each command of
`static_commands` that differs from `gate_prefix` and from the commands already added, in order. Only in the implement
branch (the `read_only` branch and judge calls are unchanged). The rule text is the command as configured; nothing is
quoted or split.

### D3. copilot-cli: one rule per distinct first word

`gate_rule(gate_prefix)` becomes `gate_rules(gate_prefix, static_commands)`: the first word of the test gate's command,
then of each static command, each once, in that order, as `--allow-tool=shell(<word>:*)`. A command with no word adds
nothing. Keep a `gate_rule` wrapper only if another module imports it (search first).

### D4. The prompt

Replace the `static_gate_commands` sentence in `prompt.py` with, for every role:

- red: "You may run {listed} yourself before you finish; the harness also runs them after your step. Your new tests
  (and any stub) must pass them: a lint or type error in a test file rejects this attempt, and those files are frozen
  afterwards."
- every other role: "You may run {listed} yourself before you finish; the harness also runs them after your step and
  rejects the task while they fail."

and, for both, one more sentence: "When one of them cannot run in this sandbox (it needs the network, or a cache it
cannot write), check what it checks by reading the code instead." The `Run tests only with ...` sentence stays (it is
about tests). No template file and no template version changes: the section is built in code.

### D5. What stays

The harness's own static gate runs (`run_static_gates`, the baselines, `worse_static_gates`) are unchanged. A lint
command that writes files (a `--fix` linter) may now be run by the agent; its writes are the agent's changes and go
through every guard (the freeze puts a frozen test file back as before).

## Risks / Trade-offs

- A configured lint or typecheck command that is itself a shell line (`sh -c '...'`) is allowed with any appended
  arguments, as the test gate's command is today. That is the owner's configuration and the same trust the test gate
  rule already gives.
- copilot-cli's first-word rule is wider than claude-code's: `pnpm:*` allows any `pnpm` command, and a lint command
  `sh .l4/gates/lint-go.sh` or `uv run ...` gives `sh:*` or `uv:*`, any command of that program. This is the existing
  limit of that CLI's rule language, already named for the test gate; the shell rule was never the code-execution
  boundary (the test gate already runs code the agent writes), the sandbox is.
- A `(` or `)` inside a configured command splits its claude-code rule into dead pieces (claude's `--allowedTools`
  parser does not nest parentheses): the command is then refused, never widened. The test gate's rule has the same
  limit.
- A command may fail in the agent's sandbox for a reason that is not the agent's (`uv run` with no writable cache, no
  network): the prompt says to read instead.
