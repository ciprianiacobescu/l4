## Purpose

kiro-cli answers a judge's tool-less call (L4-KJD-001..003), so it joins the judge allowlist of L4-CFG-006 (0.4.18,
`yolo-guardrails`) in every judge role. SPEC.md keeps the full text of the modified requirement; the block below states
what it says once this change is made.

## MODIFIED Requirements

### Requirement: L4-CFG-006 A judge role holds only adapters that can judge
Loading `.l4/config.yaml` MUST fail with a configuration error (exit 2 in every command, `l4 doctor` included) when
`roles.judges`, `roles.verifier_agent`, `roles.clarifier` or `roles.s1_judge` names a defined profile that has an
`adapter` and whose adapter is not one of `JUDGE_ADAPTERS` (`claude-code`, `codex`, `opencode`, `kiro-cli`, `fake`;
`kiro-cli` since 0.4.19, in every one of these roles, L4-KJD-008). The message SHALL name the profile, the role, the
adapter when it is one the harness knows (never an unknown configured value), the allowlist and the fix. A backend
profile (no `adapter`) SHALL load in these roles as before, and so SHALL an undefined profile name: `l4 run`'s
preflight and doctor CFG-002 report it. The allowlist MUST be a single constant (`l4.config.roles.JUDGE_ADAPTERS`)
that the selection's `serves=` filter and this check both read.

#### Scenario: SCN-CFG-05 (−) A command judge fails at load, by name
- **GIVEN** `.l4/config.yaml` with `profiles.cmd: {adapter: command, options: {argv: [tool]}}` and `roles.judges:
  [cmd, claude]`
- **WHEN** `l4 doctor` and `l4 yolo check p1` run
- **THEN** both exit 2 with `profiles.cmd is in roles.judges, but its adapter command cannot judge (a judge call has
  no tools): an adapter profile in roles.judges, roles.verifier_agent, roles.clarifier or roles.s1_judge must use one
  of claude-code, codex, opencode, kiro-cli, fake; remove cmd from roles.judges at $`, and no check runs

#### Scenario: SCN-CFG-06 (−) Every judge role is checked, and an unknown adapter is not echoed
- **GIVEN** a `command` adapter profile in `roles.verifier_agent`, in `roles.clarifier` and in `roles.s1_judge`, and
  a profile whose adapter is `mystery-cli` in `roles.judges`, one per configuration
- **WHEN** each configuration loads
- **THEN** each fails, naming its profile and role; the last message says `its adapter (not one the harness knows)`
  and does not contain `mystery-cli`

#### Scenario: SCN-CFG-07 (+) Backend profiles, allowed adapters and undefined names still load
- **GIVEN** `roles.s1_judge: [laya, judge-sol]` with `laya` a `backend: system-one` profile and `judge-sol` an
  `openai-chat` backend profile, `roles.judges: [claude, oc]` with `claude-code` and `opencode` profiles, and
  `roles.clarifier: [nope]` with no profile `nope`; and, one per configuration, a `kiro-cli` profile in
  `roles.judges`, `roles.verifier_agent`, `roles.clarifier` and `roles.s1_judge`
- **WHEN** each configuration loads
- **THEN** each loads; `l4 run`'s preflight still refuses `roles.clarifier names a profile that is not defined under
  profiles`
