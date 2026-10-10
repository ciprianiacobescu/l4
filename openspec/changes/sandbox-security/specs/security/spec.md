## Purpose
Defines how the harness keeps secrets and logins away from agent processes and from the code those agents write: allow-listed environments, repository-config isolation, untrusted-text exclusion, protected paths, bubblewrap sandboxes with fail-closed doctor checks, and hardened harness-side tooling.

## ADDED Requirements

### Requirement: L4-SEC-001 Agent environment allow-list (part a)
The harness SHALL start every agent process with an allow-listed environment containing only that profile's own credentials, `PATH`, `HOME`, locale variables, proxy variables and `L4_RESULT_PATH`. The harness MUST NOT pass `L4_FORGE_TOKEN`, trigger tokens, App tokens or any other profile's credentials to an agent.

#### Scenario: SCN-SEC-01 (−) Forge token never reaches agents
- **GIVEN** a fake adapter that dumps its environment
- **WHEN** it is run inside the harness with `L4_FORGE_TOKEN` set
- **THEN** the dump contains no forge or trigger token and no other profile's credentials

#### Scenario: SCN-SEC-N1 (+) Own credential and result path are present
- **GIVEN** profile `claude-sonnet` with credential variable `ANTHROPIC_API_KEY` and a sandbox temp directory
- **WHEN** the agent environment is built
- **THEN** it contains `ANTHROPIC_API_KEY`, `PATH`, `HOME` (the sandbox home), locale variables and `L4_RESULT_PATH` pointing inside the sandbox temp directory

### Requirement: L4-SEC-001 Gate environment allow-list (part b)
The harness SHALL start every gate command (`setup`, `build`, `lint`, `typecheck`, `test`, `e2e`, `extra`) with an allow-listed environment of the same kind as an agent's but with no harness credentials and no LLM credentials at all.

#### Scenario: SCN-SEC-06 (−) Gate code cannot read secrets or logins
- **GIVEN** a red-phase test that reads `os.environ`, `/proc/<ppid>/environ`, `/proc/<harness pid>/environ`, `.git/config`, `~/.codex/auth.json` and `~/.claude/.credentials.json`, and tries to send them out
- **WHEN** the test gate runs in the gate sandbox
- **THEN** none of those sources yields a forge/trigger/App secret, a judge API key, a push credential or any profile's login; doctor `SANDBOX-001` ran the same probe before the job did anything

### Requirement: L4-SEC-002 Repository agent configuration is ignored (part a)
The harness SHALL start each agent adapter with the isolation flags of SPEC §18: Claude Code `--bare` under `auth: api_key`, or `--strict-mcp-config` with protected agent-config paths under `auth: subscription`; Codex `--ignore-user-config`; OpenCode `--pure`; Kiro CLI an explicit harness agent. Repository-supplied hooks, MCP servers and permissions MUST NOT take effect.

#### Scenario: SCN-SEC-02 (−) Repository-supplied agent config ignored
- **GIVEN** a repo with `.claude/settings.json` defining hooks and an MCP server, and `opencode.json` with permissive permissions
- **WHEN** the adapters run
- **THEN** neither the hooks nor the MCP server nor the permissions are applied (bare/pure/ignore-user-config)

### Requirement: L4-SEC-002 Repository configuration opt-in (part b)
The harness SHALL let repository agent configuration take effect only for a profile that sets `options.allow_repo_config: true`, and MUST omit the isolation flags for that profile only.

#### Scenario: SCN-SEC-N2 (−) Opt-in applies to one profile only
- **GIVEN** profile `claude-sonnet` with `options.allow_repo_config: true` and profile `opencode-or` without it
- **WHEN** both adapters' isolation flags are computed
- **THEN** `claude-sonnet` omits its isolation flags and `opencode-or` still carries `--pure`

### Requirement: L4-SEC-003 Untrusted text never enters prompts (part a)
The harness MUST NOT place text from untrusted sources (issue or PR comments by non-members, external URLs) into any prompt. Spec files and `questions.md` SHALL be trusted only as far as their pushers are members, and answers and quotes SHALL enter prompts only as `<l4:data>` blocks.

#### Scenario: SCN-SEC-05 (−) Untrusted text never reaches prompts
- **GIVEN** a PR comment by a non-member containing instructions, and an issue linked to the unit
- **WHEN** prompts are rendered
- **THEN** their recorded sources are only harness templates and files at the unit branch head; neither the comment nor the issue text appears

### Requirement: L4-SEC-003 Prompt sources are recorded and checked (part b)
The harness SHALL record the source of every prompt section and MUST refuse to render a prompt when a section's source is outside the allow-list of harness templates and files read at the unit branch head.

#### Scenario: SCN-SEC-N3 (−) A section from a disallowed source aborts rendering
- **GIVEN** a prompt context that carries a section whose source is `forge:comment:non-member`
- **WHEN** the prompt is rendered
- **THEN** rendering fails with `prompt source not allowed`, no agent is called, and nothing is written to the ledger as a rendered prompt

### Requirement: L4-SEC-004 Agent changes to protected paths are reverted (part a)
The harness SHALL revert any change made by an agent to a protected path (the contract list plus `odd.forbidden_paths`) and MUST record it as `guard.violation`. The contract list covers CI files, `.l4/**`, agent configuration paths and `.serena/memories/harness/**`.

#### Scenario: SCN-SEC-N4 (−) Agent edit to agent configuration is reverted
- **GIVEN** an agent step that modified `.mcp.json` and `.codex/config.toml`
- **WHEN** the protected-path guard runs
- **THEN** both files are restored to their pre-step content and two `guard.violation` events are logged

### Requirement: L4-SEC-004 Human changes to protected paths are disclosed (part b)
When a human changes a protected path on the unit branch, the harness SHALL allow the change and MUST list the changed protected paths in the PR body.

#### Scenario: SCN-SEC-N5 (+) Human edit to a CI file is listed
- **GIVEN** a human commit on the unit branch that edits `.gitlab-ci.yml`
- **WHEN** the PR body is rendered
- **THEN** the body lists `.gitlab-ci.yml` under protected paths changed by a human and the change is not reverted

### Requirement: L4-SEC-004 Behaviour-changing labels need a member (part c)
The harness SHALL honour a label that changes harness behaviour (`l4:resume`) only when it was set by a member with at least Developer or Write access, and MUST ignore it otherwise.

#### Scenario: SCN-SEC-N6 (−) Label set by a non-member is ignored
- **GIVEN** the `l4:resume` label set on a halted unit by a user with Reporter access
- **WHEN** the sweeper evaluates the unit
- **THEN** the label is ignored, the unit stays `halted`, and the decision is logged with the actor's access level

### Requirement: L4-SEC-005 Sandbox mode selection (part a)
The harness SHALL select the sandbox from `sandbox.mode`; `auto` MUST pick `bwrap` if available, then `container`, then `user`, and MUST NOT fall back to `none`. When nothing usable exists the harness SHALL fail closed and run no agent or gate.

#### Scenario: SCN-SEC-07 (−) Unsandboxed mode is refused by default
- **GIVEN** a runner without bwrap, container runtime or sandbox user, and `sandbox.allow_none: false`
- **WHEN** `l4 doctor --ci` runs
- **THEN** SANDBOX-001 fails (exit 3); no agent or gate runs

### Requirement: L4-SEC-005 Agent sandbox contents (part b)
Each agent run SHALL execute in its own sandbox with the worktree read-write, the shared `.git` directory read-only, a private writable temp directory holding `$L4_RESULT_PATH`, only that profile's `sandbox.credential_paths` read-write, and network allowed. Another profile's credential paths MUST NOT be present.

#### Scenario: SCN-SEC-10 (−) One profile cannot read another profile's login
- **GIVEN** `codex-sol` and `claude-sonnet` both with subscription logins on the runner
- **WHEN** code running inside the Codex agent sandbox reads `~/.claude/.credentials.json`
- **THEN** the file is not present in that sandbox; doctor `SANDBOX-001` verified this pairwise

### Requirement: L4-SEC-005 Gate sandbox contents (part c)
Every gate command, test, build, `serve` and scanner run on the worktree SHALL execute in a gate sandbox with the worktree read-write, `.git` read-only, an empty home, no credential paths and no credential environment variables, and network allowed unless `gates.network: none`.

#### Scenario: SCN-SEC-N7 (−) Gate sandbox has no network when configured
- **GIVEN** `gates.network: none` and a test that opens a TCP connection to a public address
- **WHEN** the test gate runs
- **THEN** the connection fails inside the gate sandbox and the gate command line carries `--unshare-net`

### Requirement: L4-SEC-005 Caches and private home (part d)
Both sandbox kinds SHALL mount the per-unit cache directories of `sandbox.caches` with their environment variables, and `HOME` inside a sandbox MUST be a private directory holding only the declared mounts, so agent-written code cannot poison another unit's cache.

#### Scenario: SCN-SEC-N8 (−) A cache write in unit A is invisible to unit B
- **GIVEN** units `a` and `b` with `uv` cache paths under `$L4_CACHE/units/{unit}/cache/uv`
- **WHEN** a gate in unit `a` writes a file into its `UV_CACHE_DIR`
- **THEN** the file is absent from unit `b`'s `UV_CACHE_DIR`

### Requirement: L4-SEC-005 User mode needs one OS user per profile (part e)
With `sandbox.mode: user` and more than one profile that has `credential_paths`, the harness SHALL require `sandbox.user_per_profile` to map each such profile to its own OS user, and MUST make SANDBOX-001 fail otherwise.

#### Scenario: SCN-SEC-11 (−) One sandbox user cannot hold two logins
- **GIVEN** `sandbox.mode: user`, profiles `codex-sol` and `claude-sonnet` both with credential paths, and no `user_per_profile`
- **WHEN** `l4 doctor --ci` runs
- **THEN** SANDBOX-001 fails (exit 3) explaining that one OS user per profile is needed in user mode

### Requirement: L4-SEC-005 Explicit unsandboxed mode (part f)
The harness SHALL refuse `sandbox.mode: none` unless `sandbox.allow_none: true` is also set. When both are set, doctor SHALL report an accepted risk with a loud warning on every run and the harness MUST record `sandbox.risk_accepted` in the ledger.

#### Scenario: SCN-SEC-N9 (+) Explicit none runs with a warning and a ledger record
- **GIVEN** `sandbox.mode: none` and `sandbox.allow_none: true`
- **WHEN** `l4 doctor` and then `l4 run` start
- **THEN** SANDBOX-001 reports a warning naming the accepted risk, the run proceeds, and the ledger contains a `sandbox.risk_accepted` event with mode `none`

#### Scenario: SCN-SEC-N10 (−) mode none without allow_none is refused
- **GIVEN** `sandbox.mode: none` and `sandbox.allow_none: false`
- **WHEN** `l4 doctor` runs
- **THEN** SANDBOX-001 fails (exit 3), no agent or gate runs, and no `sandbox.risk_accepted` event is written

### Requirement: L4-SEC-005 Doctor SANDBOX-001 probes (part g)
Doctor check `SANDBOX-001` SHALL probe both sandbox kinds with canaries: from the gate sandbox no credential path of any profile, no ancestor environment, no git credential and no harness secret may be readable; from each agent sandbox no forge, trigger or App secret and no other profile's credential path may be readable, while its own credentials, the caches and the LLM API are reachable.

#### Scenario: SCN-SEC-N11 (−) A readable canary fails the probe
- **GIVEN** a canary file placed at another profile's credential path and a sandbox implementation that accidentally binds it
- **WHEN** `SANDBOX-001` probes that profile's agent sandbox
- **THEN** the check fails (exit 3) naming the readable canary path, never printing canary content

### Requirement: L4-SEC-005 Residual risk and GA gating (part h)
The harness documentation SHALL state that code an agent runs inside its own sandbox can read that agent's own credential and that profiles SHOULD use dedicated logins or keys with provider-side spend limits. The harness MUST NOT declare the sandbox GA until the change-0 spikes confirm that browsers, container-backed `serve` commands and the agents' own sandboxes work inside bubblewrap.

#### Scenario: SCN-SEC-N12 (−) Unconfirmed spike facts keep the sandbox out of GA
- **GIVEN** the spike report for Playwright inside bubblewrap is absent
- **WHEN** `l4 doctor` reports sandbox status
- **THEN** SANDBOX-001 includes the note `bubblewrap sandbox is not GA: spike facts unconfirmed` and the check still passes or fails only on its probes

### Requirement: L4-SEC-006 OpenSpec CLI never comes from the worktree (part a)
The harness SHALL run the OpenSpec CLI only from the harness-owned prefix `$L4_CACHE/tools/openspec-<version>` and MUST NOT use `npx` or any `node_modules` inside the worktree.

#### Scenario: SCN-SEC-N16 (−) The OpenSpec resolver ignores worktree packages and npx
- **GIVEN** a worktree with `node_modules/.bin/openspec` and an `npx` shim on `PATH`, both writing a marker file when run (SCN-SEC-08, converted in spec-providers, covers the provider path)
- **WHEN** the harness resolves the OpenSpec CLI binary
- **THEN** the resolved path is `$L4_CACHE/tools/openspec-<version>/node_modules/.bin/openspec`, and neither marker file exists

### Requirement: L4-SEC-006 Hardened git invocations (part b)
Every harness git invocation SHALL use `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c protocol.ext.allow=never`, and every harness commit MUST use `--no-verify`.

#### Scenario: SCN-SEC-09 (−) Repository git hooks and config never run in the harness
- **GIVEN** an agent writes `.git/hooks/pre-commit` (blocked: `.git` is read-only in its sandbox) or a repository sets `core.fsmonitor` through an included config
- **WHEN** the harness commits and runs `git status`
- **THEN** no hook or fsmonitor command executes (`core.hooksPath=/dev/null`, `core.fsmonitor=false`, `--no-verify`); a changed `.git/config` hash is reverted and logged

#### Scenario: SCN-WTR-N19 (−) A planted hook never runs
- **GIVEN** a repository whose `.git/hooks/pre-commit` and `post-commit` write a marker file
- **WHEN** the harness commits and runs `git status` through the git runner
- **THEN** the marker file does not exist and the recorded argv of each call starts with the hardening flags.

### Requirement: L4-SEC-006 Shared git config is hashed and restored (part c)
The harness SHALL hash the shared `.git/config` before each agent or gate step and MUST revert any change and log `guard.git_config` when the hash differs afterwards.

#### Scenario: SCN-SEC-N13 (−) A changed git config is reverted
- **GIVEN** a gate step that appends `[core] fsmonitor = /tmp/x` to the shared `.git/config`
- **WHEN** the step ends
- **THEN** the file is restored to its pre-step bytes and `guard.git_config` is logged

### Requirement: L4-SEC-006 Hardened report parsers (part d)
The harness SHALL parse test reports with parsers that reject XML document-type declarations and entity definitions, enforce a size limit, and use safe loaders only for JSON and YAML.

#### Scenario: SCN-SEC-N14 (−) An XML report with an entity is rejected
- **GIVEN** a JUnit report that declares `<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]>`
- **WHEN** the gate parses the report
- **THEN** parsing fails with `report rejected: DTD not allowed`, the gate fails, and no file content is read

### Requirement: L4-SEC-006 Third-party scanners run sandboxed (part e)
The harness SHALL run scanners (gitleaks, semgrep) and any other third-party tool on an agent-controlled tree inside the gate sandbox with harness-owned configuration, and MUST ignore scanner configuration files from the repository.

#### Scenario: SCN-SEC-04 (−) Secret committed by the change
- **GIVEN** the diff adds a file containing a private key
- **WHEN** verification step 1 runs gitleaks in the gate sandbox
- **THEN** the result is FAIL with a blocker finding showing the file and rule, not the secret

#### Scenario: SCN-SEC-N15 (−) A repository gitleaks ignore file is not used
- **GIVEN** a repository `.gitleaksignore` listing the file that holds a private key
- **WHEN** the scanner runs
- **THEN** the harness-owned configuration is passed explicitly and the key is still reported
