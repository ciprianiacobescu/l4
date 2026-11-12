## ADDED Requirements

### Requirement: L4-IMP-098 An implementer may run the lint and type gates
The shell rule of an implement-mode agent step (red, green, single, and the argv the dry run shows) SHALL allow, next to
the test gate's command (`gates.test.command`), each command of `gates.lint` and `gates.typecheck`, with any arguments
appended, and no other command. claude-code SHALL get one `Bash(<command>:*)` rule per distinct command, after the test
gate's rule; copilot-cli SHALL get one `--allow-tool=shell(<first word>:*)` rule per distinct first word of the test,
lint and typecheck commands. An adapter whose implement mode does not filter shell commands (opencode 1.x and 2.x, codex,
kiro-cli) SHALL be unchanged. A judge, reader or read-only call SHALL get no such rule.

The step's prompt SHALL name the lint and typecheck commands as commands the agent may run before it finishes, and SHALL
say that a command that cannot run in the sandbox (it needs the network, or a cache it cannot write) is checked by
reading instead; it SHALL still say that the harness runs them after the step and rejects the attempt while they fail.
The harness's own static gate runs and their judgement against the step base (L4-IMP-002, L4-IMP-096) SHALL be
unchanged. These are the repository owner's configured gate commands, which the harness already runs on the same work
tree: the rule SHALL add no command the configuration does not name.

#### Scenario: SCN-IMP-533 (+) A claude-code implementer may run each lint and typecheck command
- **Given** `gates.test.command: pnpm run test`, `gates.lint: [pnpm run lint]` and
  `gates.typecheck: [pnpm run typecheck, pnpm run lint]`
- **When** the argv of a claude-code implement-mode step, a judge call and a read-only call are built
- **Then** the implement step's `--allowedTools` holds `Bash(pnpm run test:*)`, `Bash(pnpm run lint:*)` and
  `Bash(pnpm run typecheck:*)`, each once and in that order, and no other `Bash` rule; the judge and read-only argv hold
  no `Bash` rule

#### Scenario: SCN-IMP-534 (+) A copilot-cli implementer gets one shell rule per first word
- **Given** `gates.test.command: .venv/bin/pytest -q`, `gates.lint: [.venv/bin/ruff check ., .venv/bin/ruff format
  --check .]` and `gates.typecheck: [.venv/bin/mypy src, pnpm --dir web exec tsc --noEmit]`
- **When** the argv of a copilot-cli implement-mode step is built
- **Then** it holds `--allow-tool=shell(.venv/bin/pytest:*)`, `--allow-tool=shell(.venv/bin/ruff:*)`,
  `--allow-tool=shell(.venv/bin/mypy:*)` and `--allow-tool=shell(pnpm:*)`, each once, and no other shell rule

#### Scenario: SCN-IMP-535 (+) The prompt names the commands the agent may run
- **Given** a configuration with `gates.lint: [pnpm run lint]` and `gates.typecheck: [pnpm run typecheck]`, and one with
  neither
- **When** the red, green and single prompts are rendered for each
- **Then** each prompt of the first says that the agent may run `pnpm run lint` and `pnpm run typecheck` before it
  finishes, that the harness also runs them after the step, and to check by reading when one cannot run in the sandbox;
  the red prompt still says that a lint or type error in a test file rejects the attempt; the prompts of the second
  name no lint or typecheck command

#### Scenario: SCN-IMP-536 (+) The dry run shows the same rules
- **Given** the configuration of SCN-IMP-533 and a claude-code implementer profile
- **When** `l4 run --dry-run` builds the implementer command it shows
- **Then** that command holds the same three `Bash` rules as a real implement step
