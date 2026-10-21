## Why

Gate commands and agents execute code the agent just wrote, as the same OS user as the harness. Without a boundary that code can read `/proc/<ancestor>/environ`, `.git/config`, other profiles' logins and the runner's files (SPEC §18, L4-SEC-005). The walking skeleton must therefore run agents and gates inside bubblewrap on `l4-runner` and must fail closed (doctor `SANDBOX-001`) when no sandbox exists, because the user wants a one-command install on a shell runner without silent insecurity. This change also owns the other SEC rules every later change relies on: allow-listed environments, repo-config isolation flags, untrusted-text exclusion, protected paths and hardened harness-side tooling.

## What Changes

- Add `src/l4/sandbox/` with a `Sandbox` interface, a bubblewrap implementation (agent and gate kinds), a `none` implementation reachable only through explicit `mode: none` plus `allow_none: true`, and a selector that fails closed.
- Add environment allow-list builders for agent and gate processes (L4-SEC-001).
- Add doctor check `SANDBOX-001` with canary probes of both sandbox kinds, plus the accepted-risk warning and ledger record for `mode: none`.
- Add `src/l4/security/` with: adapter isolation-flag table (L4-SEC-002), prompt source allow-list (L4-SEC-003), protected-path model and member trust rule (L4-SEC-004), the L4-SEC-006 requirement (its git parts are implemented in state-vcs-locks' `l4.vcs.git` and re-exported here) and hardened XML/JSON/YAML parsing.
- M1 delivers: bubblewrap wrapper when `bwrap` works, fail-closed doctor, explicit `none`, env allow-lists, hardened git args, safe XML parser, protected-path revert, Claude Code and OpenCode isolation flags. M2 adds `user` and `container` modes, pairwise probes, network `none`, per-unit caches hardening, remaining adapters' flags, label trust, PR-body disclosure and GA gating on the change-0 spikes.

## Capabilities

### New Capabilities
- `security`: allow-listed environments, repo-config isolation, prompt-source rules, protected paths, bubblewrap/user/container sandboxes with fail-closed doctor probes, and hardened harness-side tooling (L4-SEC-001 to L4-SEC-006).

### Modified Capabilities
(none)

## Impact

- Owned source: `src/l4/sandbox/{base.py,bwrap.py,none.py}` plus new `env.py`, `select.py`, `probe.py` (M2: `user.py`, `container.py`); new package `src/l4/security/{hardening.py,protected.py,sources.py,trust.py,isolation.py}`; `src/l4/doctor/checks_sandbox.py`.
- Consumed by: agent-factory (`isolation_flags`, `build_agent_env`, `Sandbox.wrap`), implementer-tdd-loop (gate runner, guards, junit parser), spec-providers (OpenSpec prefix rule is implemented there; this change owns the planted-package test), forge-and-ci (PR-body disclosure, label trust).
- Config keys used (defined by bootstrap-core): `sandbox.*`, `gates.network`, `profiles.*.options.allow_repo_config`, `odd.forbidden_paths`.
- Tests: `tests/unit/sandbox/`, `tests/unit/security/`, `tests/contract/test_agent_isolation.py`, live smoke `tests/live/test_bwrap_live.py`.
