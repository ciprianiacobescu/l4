## Context

SPEC section 21 row 0 makes `spikes` the first delivery change: it settles the [U] assumptions before anything builds on them.
Versions available today (2026-10-03): Claude Code 2.1.288 and OpenCode 1.18.33 on this Mac, Codex 0.160.0 as a local npm binary
(`<scratchpad>/clis/node_modules/.bin/codex`), OpenSpec 1.14.0 in the harness prefix, Python 3.14 via uv 0.10.0, Node 22, Docker 29.
`kiro-cli` is NOT installed on this Mac (research/02: docs-level evidence only). The reference runner `l4-runner`
(shell executor, linux/amd64, tags `agentic, ai, opencode`, `run_untagged: false`) is a black box: no SSH, every check is a CI job.
A first inventory job already ran and died before any script: the log shows
`Running on gitlab-runner...` followed by `ERROR: Job failed: prepare environment: exit status 1. Check
https://docs.gitlab.com/runner/shells/#shell-profile-loading` (cause: the `gitlab-runner` user's `~/.bash_logout` runs `clear_console`).

## Goals

- One report per spike in `docs/spikes/<nn>-<name>.md` with fixed sections: Question, Method, Commands (exact, copy-pasteable),
  Observed output (verbatim excerpt, secrets and e-mails removed), Verdict (`promising` | `adapt` | `reject`), SPEC amendment (or "none").
- Recorded raw outputs that become the contract-test fixtures of change 5 (SPEC section 20.2): `tests/fixtures/cli/<tool>/<version>/<case>.{json,jsonl,txt}`
  plus `meta.json` with the exact command line, exit code and CLI version.
- A Python fixture repository (M1) and TypeScript/Go fixture repositories (M2) that fix the TDD-evidence rules of SPEC section 21 row 0.
- Every [U] label in SPEC sections 8.3, 15, 16.3 and 18 touched by a spike is either promoted to [V] (date and version) or the SPEC is amended.

## Non-Goals

- No production code under `src/l4/`; probe scripts live in `scripts/spikes/` and may be thrown away.
- No authentication is performed by a spike on behalf of a human: spikes that need a login (Codex subscription, Kiro, Claude token)
  use whatever login the dev machine already has, or are recorded as `not-run` with the reason.
- No change to forge or runner settings by the harness; the maintainer applies runner fixes (for example the `.bash_logout` rename).

## Decisions

### D1. Task line format adapted for spikes

Spike tasks produce evidence, not code, so the usual `test:` / `code:` / `verify:` triple is mapped as follows (the three keys are kept
so tooling that greps tasks stays uniform): `test:` = the recorded raw output path under `tests/fixtures/` that the spike creates
(this later becomes a contract-test input of change 5); `code:` = the report `docs/spikes/<nn>-<name>.md` (and fixture repo path where relevant);
`verify:` = the exact command that re-produces the observation. Each spike report is structurally checked with `uv run python scripts/check_spike_report.py docs/spikes/<nn>-<name>.md` (task 1.0). Alternative considered: a separate task grammar for spikes. Rejected; one
grammar keeps `kiro`/`openspec` task parsers and the orchestrator identical for all changes.

### D2. Spike inventory, numbering and order

M1 (ordered so that downstream parsing facts come first):

| NN | Name | Question (short) | Tool facts under test |
|---|---|---|---|
| 01 | runner-inventory | What does the runner have installed, and why did the first job fail? | `.bash_logout` / `clear_console` signature [V 2026-10-03 job log]; inventory (git, uv, python, node, npm, bwrap, podman/docker, claude, codex, opencode, kiro-cli) [U] |
| 02 | openspec-json | Exact JSON of `list`, `show`, `validate`, `instructions apply`, `status`, `archive` | SPEC L4-OSP-001..006; `root.source`, `state` values `blocked\|ready\|all_done` [V], line numbers in progress [V] |
| 03 | cli-claude | Headless contract of `claude -p` | `--output-format json` and `stream-json --verbose`, `type:result` fields, exit codes 0/1/143, `--permission-mode dontAsk` + `--allowedTools`, `--json-schema`, blocked/question outcome |
| 04 | cli-opencode | Headless contract of `opencode run --format json` | NDJSON parts, `step_finish.cost/tokens`, `sessionID`, exit 0 after permission rejection [V research/02], `--pure`, `OPENCODE_PERMISSION` |
| 05 | cli-codex | Headless contract of `codex exec --json` | JSONL `thread.started`, `item.completed`, `turn.completed.usage`, `-s workspace-write`, `--output-schema`, `-o`, `turn.failed` + exit 1 |
| 06 | cli-kiro | Headless contract of `kiro-cli chat --no-interactive` | stream-json schema [U], `--trust-tools`, `--resume-id` [U], exit 3 on MCP startup failure [V doc]; likely `not-run-locally` |
| 07 | quota-probes | Zero-cost quota signals | Codex `codex app-server` -> `account/rateLimits/read` [V]; Claude `rate_limit_event` and `/usage` text [V]; OpenCode `retry-after` handling [V src]; Kiro `/usage` [D] |
| 08 | tdd-python | Python must-catch / must-pass fixture | stub allow-list, zero-value stubs, support-file AST rules, suppression scan |

M2 (everything else in SPEC section 21 row 0):

| NN | Name | Settles |
|---|---|---|
| 09 | bwrap-runner | `bwrap` presence and unprivileged user namespaces on `l4-runner` (via a CI job) |
| 10 | playwright-in-bwrap | SCN-SPK-01: Chromium with and without its own sandbox inside bubblewrap (`--unshare-pid --proc /proc`) |
| 11 | container-serve | SCN-SPK-02: rootless podman or pre-provisioned service for `gates.e2e.serve`, no Docker socket in the gate sandbox |
| 12 | agents-in-bwrap | Codex and Claude Code, with their own sandboxes, inside bubblewrap |
| 13 | kiro-trust | Kiro headless workspace trust (risk R2) |
| 14 | atomic-push-refs | `git push --atomic` and `refs/l4/locks/*` custom refs with `--force-with-lease=<ref>:<expected>` on GitHub and GitLab 17.5.2 CE |
| 15 | gitlab-components | CI/CD components on GitLab 17.5 |
| 16 | claude-oauth-token | Claude Code subscription auth via `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) on a shell runner without `--bare` |
| 17 | home-cache-mounts | HOME and cache mounts (`sandbox.caches`) under bubblewrap |
| 18 | readonly-git | Codex and Claude Code working against a read-only `.git` |
| 19 | bwrap-github-hosted | bubblewrap on GitHub-hosted `ubuntu-24.04` (unprivileged user-namespace restrictions [I]) |
| 20 | tdd-typescript | TypeScript fixture: `@ts-ignore`, `scripts.lint` weakening, package.json test-only deps, struct-tag analogue |
| 21 | tdd-go | Go fixture: struct tags / field constraints smuggling behaviour, zero-value stubs |
| 22 | userlocal-provisioning | Can uv, a Node tarball, OpenSpec and the agent installers run without sudo on the runner? (feeds change 12) |

### D3. S-CLI method: one prompt set, four CLIs, recorded raw

Prompt cases recorded for each CLI (cheapest model, scratch git repo, never the harness repo): `hello` (reply exactly `L4-OK`);
`edit` (create a file in the worktree under non-interactive permissions); `denied` (ask to run a command outside the allow-list);
`blocked` (task that cannot be completed without a human answer: how can the CLI signal that? candidates: result text with an
agreed marker, `structured_output` with `status: "blocked"`, or the harness-defined result file `$L4_RESULT_PATH`); `max-turns` /
budget stop; `bad-auth` (invalid key in a throwaway env, nothing real touched); `schema` (native schema flag where one exists).
Exact invocations (from SPEC section 8.3, labels kept):

- Claude: `claude -p --output-format json "<prompt>"` and `claude -p --output-format stream-json --verbose --model M --max-turns N --max-budget-usd B --permission-mode dontAsk --allowedTools "..." --strict-mcp-config --mcp-config F [--json-schema S] < prompt` [V 2.1.288].
- OpenCode: `opencode run --pure --format json -m provider/model "<prompt>"` with `OPENCODE_PERMISSION` [V 1.18.33].
- Codex: `codex exec --json -m M -s workspace-write --ignore-user-config [--output-schema S] -o OUT -` (prompt on stdin) [V 0.160.0]; `--full-auto` was removed [V].
- Kiro: `kiro-cli chat --no-interactive --trust-tools=<allow-list> [--agent A] [--model M] --output-format stream-json --require-mcp-startup "<prompt>"` [U schema, U resume].

Output of each case: raw stdout, raw stderr, exit code, wall time, and the normalised `RunResult` fields the adapter will need
(`status`, `final_text`, `session_id`, `cost_usd | tokens`, `limit_signal?`). The spike report ends with a field-mapping table
CLI-field -> RunResult-field. Alternative considered: read the docs only. Rejected; two documented behaviours were already
found wrong by running (OpenCode exit 0 after a permission stop; `--full-auto` removed).

### D4. S-QUOTA method

Codex: spawn `codex app-server`, send `initialize` then `account/rateLimits/read`, record primary (300 min) and secondary (10080 min)
windows with `usedPercent`, `resetsAt`, `rateLimitReachedType` [V 0.6 s]. Claude: capture a `rate_limit_event` from a stream-json run and the
zero-cost `/usage` text; record how both look when logged out. OpenCode: replay a mock HTTP 429 with `retry-after: 3600` and confirm the
process does not return before the wall-clock timeout the harness will impose [V src: retries up to ~24.8 days]. Kiro: `/usage` if the binary exists. Output: `LimitSignal` examples (SPEC L4-AVL-002)
for each source.

### D5. S-OPENSPEC method

Scratch repo with `openspec init --tools none`, one change with two requirements, one task list with mixed `[ ]`/`[x]`. Run, with
`TZ=UTC DO_NOT_TRACK=1 OPENSPEC_NO_UPDATE_CHECK=1` from the harness prefix binary (never npx): `list --json`, `show <id> --type change --json`,
`validate <id> --strict --json`, `validate --all --strict --json`, `instructions apply --change <id> --json`, `status --change <id> --json`,
`archive <id> --yes`, plus the negative cases: invalid change, change without deltas (needs `skip_specs: true`), MODIFIED delta on a missing requirement (INFO
at validate, failure at archive), ancestor-root resolution (`root.source`). Record the top-level key set of each JSON so `specs/openspec.py` can use pydantic models with
`extra="ignore"` but required keys asserted.

### D6. S-TDD fixtures: shape

Each fixture repo has a `README.md` listing cases, a `cases/<name>/` directory per case holding a git patch series (`red.patch`, `green.patch`) and an
`expect.yaml` (`verdict: must_catch|must_pass`, `rule`, `evidence`). Python must-catch: call-only tests (assert-free), conftest monkeypatch that activates only when
a marker file exists, `# noqa` / `# type: ignore` suppressions, test-only dependencies added in green, weakened `pyproject.toml` lint/ruff targets or Makefile targets.
Python must-pass: tests whose correct answer is the zero value (`0`, `""`, `[]`, `None`), fixtures patching clocks and `httpx` clients of changed modules, declared ignores
(`[[tool.mypy.overrides]] ignore_missing_imports`) for untyped imports of a dependency the unit added, test-only dependencies added in red, a new
`@dataclass` with plain fields. TypeScript/Go specifics (struct tags, `@ts-ignore`, `scripts.lint`) are in the M2 fixtures. The fixture repos are inputs to changes 6 and 8; the rule implementations are
not written here, but each case records the cheapest deterministic check (AST, diff, grep) that decides it and its false-positive risk.

### D7. S-RUNNER is split: record, fix, retry

The first run is recorded as `adapt`: the job fails in "prepare environment" before any script runs, so no inventory exists. The retry is a separate
M1 task that is externally blocked on the maintainer's one-time fix (`sudo mv /home/gitlab-runner/.bash_logout{,.disabled}`), after which the
inventory job (a script file, tag `agentic`, no inline multi-line YAML) is re-run. Alternative considered: inventory through a Docker or another runner. Rejected: the question is about
THIS runner's tools and profile loading.

## Risks

- A spike needing a login (Codex, Kiro) cannot run unattended: mark `not-run` with the reason, never fabricate output.
- Costs: every live model call uses the cheapest model and `--max-budget-usd` / `--max-turns` where available; the report records spend.
- Recorded outputs may contain e-mails, tokens, absolute paths: a redaction pass is a task before fixtures are committed (reuse L4-OBS-002 patterns later).
- Reference runner access is only via CI; a spike that needs root there is blocked on the maintainer and is reported as such.
- Version drift: fixtures carry the CLI version; change 5 contract tests pin it (L4-FAC-007).
