## Why

In a consumer's TypeScript unit a green attempt passed every test and failed two static gates: `pnpm run lint`
(`no-useless-assignment`, one line of `src/main.ts`) and `pnpm run typecheck` (TS2322, one literal missing from a row
type's union in a test file a delegate answer had opened). Both were one-line fixes the agent could have seen in seconds,
but its shell allowed only the test gate: the claude-code implementer gets `Bash(<gates.test.command>:*)` and nothing
else, so `eslint`, `tsc` and `pnpm run lint` were refused. The next attempt started from the red commit and reached the
30-minute step limit, and the task halted. The owner then wrote in the repository's AGENTS.md that the implementer may
run only `pnpm run test`, that `node`, `tsc` and `eslint` are refused, and that types and lint must be checked by reading.

The harness itself runs every `gates.lint` and `gates.typecheck` command after the step, on the same work tree, and
rejects the attempt when one got worse than at the step base (L4-IMP-002, L4-IMP-096). An agent that cannot run them
learns of a failure only after its step has ended.

## What Changes

- The shell rule of an implement-mode step also allows each `gates.lint` and `gates.typecheck` command, with arguments
  appended: claude-code gets one `Bash(<command>:*)` rule per distinct command next to the test gate's; copilot-cli gets
  one `--allow-tool=shell(<first word>:*)` rule per distinct first word of the test, lint and typecheck commands. The
  dry run (`l4.sim.dryrun`) passes the same policy.
- opencode, codex and kiro-cli are unchanged: their implement mode does not filter shell commands.
- A judge, reader or read-only (delegate) call gets no such rule.
- The prompt's `# Gate command` section names the lint and typecheck commands as commands the agent may run before it
  finishes, and says that one that cannot run in the sandbox (no network, a cache it cannot write) is checked by
  reading. It still says that the harness runs them after the step and rejects the attempt while they fail.
- No new trust: these are the repository owner's configured gate commands, which the harness already runs on the same
  work tree, with the `:*` semantics of the test gate's rule.

## Capabilities

### New Capabilities

- `static-gates-runnable`: L4-IMP-098, an implementer may run the lint and type gates.

### Modified Capabilities

- §8.3.1 (the claude-code implementer argv) and the copilot-cli row of the adapter table: the shell rules.

## Impact

- `src/l4/agents/base.py` (`PermissionPolicy`), `src/l4/agents/claude_code.py`, `src/l4/agents/copilot_cli.py`
  (`gate_rule`), `src/l4/implementer/tdd.py` (`agent_step`), `src/l4/sim/dryrun.py`, `src/l4/implementer/prompt.py`.
- `docs/SPEC.md` (L4-IMP-098, SCN-IMP-533..536, §8.3.1, the copilot-cli row, change-table row 128), `CHANGELOG.md`.
- The implementer templates' text changes (the `# Gate command` section); no template version moves because the
  section is built in code, not in a template.
- No configuration key, ledger event or result field changes.
