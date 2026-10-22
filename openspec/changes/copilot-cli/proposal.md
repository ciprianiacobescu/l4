## Why

A team whose agent subscription is GitHub Copilot cannot use it with L4 today. L4 drives four agent CLIs (claude-code,
codex, opencode, kiro-cli), and Copilot CLI is not one of them. The spike of 2026-10-22
(`docs/plan/proposal-copilot-cli.md`, commit `58f31c40`) found the CLI fit for an adapter, with conditions. Copilot CLI
1.0.102 has:
- a headless mode that takes the prompt on stdin;
- a JSONL stream that names the model of each reply;
- a usage file with tokens and AI credits;
- a tool allow-list that gives a truly tool-less judge and a read-only delegate;
- a deny-never-ask rule in prompt mode;
- release tarballs with published sha256 digests;
- a private-home run that works inside an L4-like bwrap sandbox.

Every shape was measured in BYOK mode, with the CLI driving a local model. No GitHub-routed run was possible: no
Copilot token was available to the spike.

Five things stand between the prototype and a safe adapter:

1. **The prototype is not product code.** `src/l4/agents/copilot_cli.py` is not registered. Its probe answers the
   `binary` step only. Its name `copilot` would not match the fixture key that LIVE-005 reads.
2. **An empty allow-list means every tool** (`--available-tools=` [V-BYOK]). So the judge and the delegate need a
   fail-closed rule, not a trust in flags.
3. **The CLI waits out a 429 by itself and has no max-turns flag.** A rate-limited run waits inside the step. A
   denied-call loop printed more than 10,000 lines in 6 minutes [V-BYOK]. L4 adapters never wait for a limit.
4. **The binary is not installed or pinned.** On its first run it also extracts a package of about 220 MB into the
   cache directory, and an unwritable cache fails the run [V].
5. **The credential must not be a forge token.** The CLI reads `GH_TOKEN` and `GITHUB_TOKEN` after its own
   `COPILOT_GITHUB_TOKEN` [V], and in L4 those two are forge tokens that no agent may get.

## What Changes

- **The adapter `copilot-cli`** (L4-FAC-013, design D1, D2). Binary `copilot`. It is registered as an
  implementer, judge and delegate adapter, and it is experimental. No default role chain and no `l4 init` output names
  it. Every run:
  - takes its prompt on stdin;
  - runs from a fresh private `COPILOT_HOME` that holds only `settings.json` (auto-update, hooks and memory off, no
    co-author trailer);
  - has auto-update off three ways (`--no-auto-update`, the setting, `COPILOT_AUTO_UPDATE=false`; never `CI`, which
    L4-SEC-040 keeps from agents);
  - passes `--model <the profile's model, else auto>`;
  - never passes `COPILOT_ALLOW_ALL`, `GH_TOKEN` or `GITHUB_TOKEN`.
- **The four modes, each fail-closed** (L4-FAC-014 to L4-FAC-016, D3 to D5):
  - judge, clarifier and readiness review: `--available-tools=l4_no_tools`, never an empty list, and any tool call
    voids the verdict;
  - delegate: `--available-tools=view,grep,glob` in the detached, masked worktree, and any tool outside `view`, `grep`,
    `rg` and `glob` voids the reply;
  - implementer: `--allow-tool=write`, `--allow-tool=shell(<gate binary>:*)`, `--add-dir <step dir>`,
    `--disallow-temp-dir`, the prompt contract, and Serena through `--additional-mcp-config`.
- **Statuses from the stream** (L4-FAC-017, D6): auth, quota (credits), rate limit, transient server errors, no
  credential, and a cold package cache. Each has a fixed detail text.
- **No wait, no endless loop** (L4-FAC-018, D7). A line watcher stops the run:
  - on the CLI's first `model.call_failure {statusCode: 429}` (before the CLI waits out `Retry-After`; its later
    `assistant.turn_retry {reason: "rate_limit"}` is a second trigger). The run ends `rate_limited`, the profile cools
    for `availability.default_cooldown`, and the next profile takes the step;
  - after 20 denied tool calls in a row. The run ends `permission_blocked`.
  A run that stalls while the CLI waits out a 429 is still read as a rate limit.
- **Usage** (L4-FAC-019, D8, D9): tokens from the usage file, AI credits = `totalNanoAiu / 1e9`, recorded as credits
  and never added to dollars. A stream reader counts tool calls for the heartbeat.
- **Vendor and independence** (L4-FAC-020, D10). A pinned model's vendor is its family (`grok-` and `mai-` join the
  table). `auto` is routed over Copilot's built-in model list. A served model under `auto` is checked; under a pinned
  model it only detects a mismatch.
- **The probe ladder** (L4-FAC-021, D11): `--version` with the major gate; `auth` passes on `COPILOT_GITHUB_TOKEN`
  only; no quota query; a tool-less hello with `-p`.
- **Pin and install** (L4-PRV-047, D13). Copilot CLI 1.0.102 is installed from its release tarball and checked against
  `COPILOT_SHA256`, a table that ships with the harness (six platforms, from the release's `SHA256SUMS.txt`). Only the
  member `copilot` is extracted, and no installer script runs. npm (`@github/copilot@1.0.102`, Node 22 or later) is
  documented as a person's alternative only.
- **The package cache** (L4-PRV-048, D14): extracted at install into `$L4_HOME/copilot-cache`, which the sandbox binds
  read-only. Probes and version reads use it as `XDG_CACHE_HOME`. A run gets a fresh, writable per-run cache directory
  whose `copilot/pkg` links to it, so the commands the agent runs (Go, pnpm, uv) keep a writable cache.
- **One credential** (L4-PRV-049, D12): `COPILOT_GITHUB_TOKEN`, a user-owned fine-grained PAT with "Copilot Requests",
  delivered by the credential loader. It is redacted and part of the probe identity. `~/.copilot` is hidden from every
  sandbox and bound into none. PRV-001 names the token and where to store it.
- **The major gate** (L4-OCG-006, D15): Copilot CLI 1.x only.
- **PRQ-22** (L4-PRV-050, D16): `prereqs.sh --with-copilot` installs the pin with the same digest check.
- **Simulation** (D18): `happy-copilot-judge` replays a judge through the real adapter.
- **Release gate** (L4-FAC-022, D17). The BYOK streams move to `tests/fixtures/recorded/copilot-cli/1.0.102-byok/`, and
  `recorded_versions.json` does not list `copilot-cli`. The change is not released until ONE GitHub-routed recording
  session with the owner's token (task 8.1, the last task) has:
  - added `tests/fixtures/recorded/copilot-cli/1.0.102/` and the `recorded_versions.json` entry;
  - fixed any mapping that the recording disproves.
  No task before it needs a token.
- **Docs** (D19): SPEC §3.2 (a commented reference profile), §8.3 and a new §8.3.3, the requirements L4-FAC-013 to
  L4-FAC-022, L4-PRV-047 to L4-PRV-050 and L4-OCG-006 with SCN-FAC-22 to SCN-FAC-49, SCN-PRV-129 to SCN-PRV-140 and
  SCN-OCG-15 to SCN-OCG-16, and change row 67. Also: runbook 10.8, the skill's adopt reference, `docs/runner/README.md`,
  and CHANGELOG `## 0.4.27 (unreleased)`.

Not in this change (design §3): the Actions `GITHUB_TOKEN` with `copilot-requests: write`, which is the forge token in
L4 and which SEC-001 never hands to an agent; BYOK as a free profile; the npm route in code; the Copilot cloud agent; a
quota query; a budget cap; Copilot's own sandbox; skills install; Windows.

## Capabilities

### New Capabilities

- `copilot-cli`: GitHub Copilot CLI as an experimental L4 agent CLI. It covers:
  - the four modes with their fail-closed rules;
  - the stream statuses, the rate-limit stop and the denial tripwire;
  - usage and credits;
  - vendor and served-model rules;
  - the probe ladder;
  - the pinned, digest-checked install and its warm package cache;
  - the single credential and its sandbox rule;
  - the major gate, PRQ-22, and the release gate on a GitHub-routed recording.

### Modified Capabilities

None as delta specs. The docs task edits the SPEC sections named under Docs (L4-FAC-011, L4-FAC-012, L4-PRV-044,
L4-DLG-015, ENV-004, PRV-001, §10.1).

## Impact

- **Code**:
  - `src/l4/agents/copilot_cli.py` (rewritten from the prototype), `src/l4/agents/activity.py`,
    `src/l4/agents/credentials.py`, `src/l4/agents/factory.py`;
  - `src/l4/config/roles.py`, `src/l4/config/defaults.py`, `src/l4/config/schema.py`;
  - `src/l4/availability/vendor.py`, `src/l4/availability/cooldown.py`, `src/l4/availability/probes.py`;
  - `src/l4/provision/catalog.py`, `src/l4/provision/install.py`, `src/l4/provision/runner.py`,
    `src/l4/provision/readiness.py`;
  - `src/l4/sandbox/base.py`, `src/l4/sandbox/bwrap.py`;
  - `src/l4/verifier/selection.py`, `src/l4/delegate/independence.py`, `src/l4/delegate/run.py`;
  - `src/l4/doctor/checks_delegate.py`, `src/l4/doctor/checks_env.py`;
  - `src/l4/sim/`, `scripts/runner/prereqs.sh`, `plugins/l4/skills/l4/scripts/yolo_preflight.py`.

  Design §5.6 lists every file. There is no new runtime dependency (`tarfile` is in the standard library).
- **Cache**: every consumer's agent-CLI cache key changes once, because the catalog gains `agent:copilot-cli`. A
  repository whose chains name `copilot-cli` caches about 190 MB of binary and 220 MB of package per platform and
  version.
- **Behaviour that changes for existing configurations**:
  - the cache key moves once;
  - every `== "kiro-cli"` routed rule (vendor, validator, `seat_of`, the delegate rules) now reads the routed adapters,
    with no change for Kiro;
  - `sandbox.credential_paths` gains a `copilot-cli` key.
  - Nothing else changes for a configuration without a `copilot-cli` profile.
- **Not changed**: the other adapters, `gate.OAUTH_ADAPTERS`, `l4 init`, the delegate's prompt, the GitHub job
  templates (`credential_secrets` names the token without a change).
- **Release**: 0.4.27, and only after task 8.1.
