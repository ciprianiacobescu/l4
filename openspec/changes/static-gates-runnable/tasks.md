## 1. The policy and the adapters (D1, D2, D3)

- [ ] 1.1 Write the tests first:
  - in `tests/unit/agents/test_claude_code.py`, SCN-IMP-533: build the implement-mode argv with
    `PermissionPolicy("implement", gate_prefix="pnpm run test", static_commands=("pnpm run lint", "pnpm run typecheck",
    "pnpm run lint"))` and assert the `--allowedTools` value holds the three `Bash(...)` rules once each, in order, and
    no other `Bash(`; a `judge` and a `read_only` request hold no `Bash(`; a policy whose static command equals the test
    gate's adds no second rule;
  - in `tests/unit/agents/test_copilot_cli.py`, SCN-IMP-534: the shell rules for the commands of the scenario (the
    existing `gate_rule` test keeps passing, or is moved to the new function with the same cases);
  - a test that `agent_step` builds its `RunRequest` with `static_commands` equal to `(*gates.lint, *gates.typecheck)`
    (capture the request with a fake adapter, as `tests/unit/implementer/test_liveness_step.py` does);
  - SCN-IMP-536 in the dry-run tests (find them with `grep -rln "_implementer_command\|dry_run" tests/unit/sim`):
    the shown claude-code command holds the three rules.
  Run them and see them fail.
- [ ] 1.2 Then add `static_commands` to `PermissionPolicy` (`src/l4/agents/base.py`), the rules in
  `src/l4/agents/claude_code.py` (implement branch only) and `src/l4/agents/copilot_cli.py`, and pass the commands in
  `src/l4/implementer/tdd.py` (`agent_step`) and `src/l4/sim/dryrun.py` (`_implementer_command`). Normalise once
  (strip, drop empty, drop duplicates, keep order) in one helper next to `PermissionPolicy`. Run
  `uv run --frozen pytest tests/unit/agents/test_claude_code.py tests/unit/agents/test_copilot_cli.py
  tests/unit/agents/test_base.py tests/unit/agents/test_read_only_mode.py tests/unit/implementer/test_liveness_step.py
  tests/unit/sim -q`.

## 2. The prompt (D4)

- [ ] 2.1 Write the test first in `tests/unit/implementer/test_prompt.py` (SCN-IMP-535): render the red, green and single
  prompts (as the existing tests of the `# Gate command` section do; `grep -n "Gate command\|static_gate" tests/unit`)
  with and without static commands and assert the sentences of D4. Run it and see it fail.
- [ ] 2.2 Then change the sentence in `src/l4/implementer/prompt.py` as D4 says. Run
  `uv run --frozen pytest tests/unit/implementer -q -k "prompt"` and then every test that asserts the old sentence
  (`grep -rn "The harness also runs" tests`), updating each to the new text.

## 3. The specification

- [ ] 3.1 `docs/SPEC.md` already holds L4-IMP-098, SCN-IMP-533..536, the §8.3.1 argv line and the copilot-cli row text,
  and change-table row 128 (written with the spec). Check them against the code you wrote; fix the code or tell the
  orchestrator where they differ. Run `uv run --frozen python scripts/check_spec.py` and
  `uv run --frozen pytest tests/unit/docs -q`.
- [ ] 3.2 `uv run --frozen ruff check .` and `uv run --frozen ruff format --check` on the files you changed.
