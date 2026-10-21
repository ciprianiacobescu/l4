## Purpose

A profile that cannot answer a judge's tool-less call is refused in a judge role when the configuration loads, by name
and with the allowlist. A broken judge chain is no longer found at selection, in the middle of a run.

## ADDED Requirements

### Requirement: L4-CFG-006 A judge role holds only adapters that can judge
Loading `.l4/config.yaml` MUST fail with a configuration error (exit 2 in every command, `l4 doctor` included) when
`roles.judges`, `roles.verifier_agent`, `roles.clarifier` or `roles.s1_judge` names a defined profile that has an
`adapter` and whose adapter is not one of `JUDGE_ADAPTERS` (today `claude-code`, `codex`, `opencode`, `fake`). The
message SHALL name the profile, the role, the adapter when it is one the harness knows (never an unknown configured
value), the allowlist and the fix. A backend profile (no `adapter`) SHALL load in these roles as before, and so SHALL
an undefined profile name: `l4 run`'s preflight and doctor CFG-002 report it. The allowlist MUST be a single constant
that the selection's `serves=` filter and this check both read.

#### Scenario: SCN-CFG-05 (−) A kiro-cli judge fails at load, by name
- **GIVEN** `.l4/config.yaml` with `profiles.kiro: {adapter: kiro-cli}` and `roles.judges: [kiro, claude]`
- **WHEN** `l4 doctor` and `l4 yolo check p1` run
- **THEN** both exit 2 with `profiles.kiro is in roles.judges, but its adapter kiro-cli cannot judge (a judge call has
  no tools): an adapter profile in roles.judges, roles.verifier_agent, roles.clarifier or roles.s1_judge must use one
  of claude-code, codex, opencode, fake; remove kiro from roles.judges at $`, and no check runs

#### Scenario: SCN-CFG-06 (−) Every judge role is checked, and an unknown adapter is not echoed
- **GIVEN** a `command` adapter profile in `roles.verifier_agent`, a `kiro-cli` profile in `roles.clarifier`, a
  `kiro-cli` profile in `roles.s1_judge`, and a profile whose adapter is `mystery-cli` in `roles.judges`, one per
  configuration
- **WHEN** each configuration loads
- **THEN** each fails, naming its profile and role; the last message says `its adapter (not one the harness knows)`
  and does not contain `mystery-cli`

#### Scenario: SCN-CFG-07 (+) Backend profiles, allowed adapters and undefined names still load
- **GIVEN** `roles.s1_judge: [laya, judge-sol]` with `laya` a `backend: system-one` profile and `judge-sol` an
  `openai-chat` backend profile, `roles.judges: [claude, oc]` with `claude-code` and `opencode` profiles, and
  `roles.clarifier: [nope]` with no profile `nope`
- **WHEN** the configuration loads
- **THEN** it loads; `l4 run`'s preflight still refuses `roles.clarifier names a profile that is not defined under
  profiles`
