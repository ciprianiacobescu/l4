## Purpose

System One on every runner: Laya enabled by default, installed and cached where a profile uses it, its keys passed to the job, and a doctor row that says which engine serves and whether it starts.

## ADDED Requirements

### Requirement: L4-ADO-015 Doctor names the System One engine and whether it starts
`l4 doctor` SHALL report the System One profile of `roles.s1_judge` that would serve, with its engine and model. For
`laya-local`, `l4 doctor --adoption` SHALL start `laya-serve` once, stop it, and report the seconds to ready;
`l4 doctor --ci` SHALL only check that `laya-serve` and its checkpoint are installed (no start, no added seconds).

When no profile would open, the row SHALL:
- warn and say why;
- say that the clarifier then auto-accepts no answer, so every implementer question goes to a person;
- print the profile lines to add.

On a GitHub-hosted runner, a `remote` or `ollama` profile SHALL be reported as unreachable.

#### Scenario: SCN-ADO-42 (−) No System One
- **GIVEN** a `laya` profile in `roles.s1_judge`, and no `laya-serve` on the runner
- **WHEN** `l4 doctor --ci` runs
- **THEN** the row warns that System One is off because `laya-serve` is not installed, states the consequence, and
  names the fix

#### Scenario: SCN-ADO-43 (−) A LAN engine on a hosted runner
- **GIVEN** `roles.s1_judge: [ollama-tev1]` and `RUNNER_ENVIRONMENT=github-hosted`
- **WHEN** `l4 doctor --ci` runs
- **THEN** the row says that the profile is on the local network and unreachable from a GitHub-hosted runner

#### Scenario: SCN-ADO-44 (+) Laya starts
- **GIVEN** a `laya` profile with `laya-serve` and its checkpoint installed
- **WHEN** `l4 doctor --adoption` runs
- **THEN** the row passes, names `laya-local` and the model, gives the seconds to ready, and no `laya-serve` process
  is left running

### Requirement: L4-ADO-016 `l4 init` enables Laya as System One by default
`l4 init` SHALL write a `laya` profile `{backend: system-one, engine: laya-local}` and `roles.s1_judge: [laya]`,
unless `--s1` says otherwise. `--s1 jev` writes a TypeSafe Jev profile instead (`api_key_env: TYPESAFE_API_KEY`).
`--s1 none` writes no System One and a `# TODO:` line. The written config SHALL load.

#### Scenario: SCN-ADO-45 (+) Laya by default
- **GIVEN** a repository without L4
- **WHEN** `l4 init --ci github --action` runs
- **THEN** the config loads, `roles.s1_judge` is `[laya]`, and the `laya` profile has `engine: laya-local`

#### Scenario: SCN-ADO-46 (+) Jev on request
- **GIVEN** a repository without L4
- **WHEN** `l4 init --ci github --action --s1 jev` runs
- **THEN** `roles.s1_judge` names the Jev profile, and the workflow's job env names `TYPESAFE_API_KEY`

### Requirement: L4-ADO-017 The workflow names the keys of System One profiles
The rendered GitHub workflow SHALL name, in the job's `env`, the `api_key_env` of every `backend: system-one` profile
in `roles.s1_judge` or `verifier.s1.shadow`, next to the agents' credential variables.

#### Scenario: SCN-ADO-47 (+) A Jev key reaches the job
- **GIVEN** `roles.s1_judge: [jev]` whose profile has `api_key_env: TYPESAFE_API_KEY`, and a workflow rendered
  without it
- **WHEN** `l4 upgrade` re-renders the workflow
- **THEN** the job env has `TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}`, and upgrade reports the file changed

#### Scenario: SCN-ADO-48 (+) A shadow engine's key
- **GIVEN** `verifier.s1.shadow: [jev-shadow]` with `api_key_env: TYPESAFE_API_KEY`
- **WHEN** the workflow is rendered
- **THEN** the job env names `TYPESAFE_API_KEY` once

#### Scenario: SCN-ADO-49 (+) A local engine adds nothing
- **GIVEN** `roles.s1_judge: [laya]` with `engine: laya-local`
- **WHEN** the workflow is rendered
- **THEN** the job env is the same as without the profile

### Requirement: L4-ADO-019 Runners install Laya when a profile uses it
Runner provisioning SHALL install the pinned Laya (`laya[serve]` with CPU torch) and its checkpoint whenever a
`laya-local` profile is in `roles.s1_judge` or `verifier.s1.shadow`. This is part of
the self-provisioning of `l4 doctor --ci --fix`, on both forges, outside the harness's own tool directory.

On GitHub the setup action SHALL keep Laya in a cache of its own, keyed on the Laya pin and the checkpoint. The key of
the CLI cache does not change. Without such a profile, nothing is installed or cached.

#### Scenario: SCN-ADO-52 (+) Laya on a hosted runner, warm the second time
- **GIVEN** `roles.s1_judge: [laya]` and a GitHub-hosted job with self-provisioning on
- **WHEN** the job runs twice
- **THEN** the verifier's step 8 reads "judged by laya-local" both times, and the second job restores Laya from its own
  cache and downloads nothing

#### Scenario: SCN-ADO-53 (+) No Laya without a profile
- **GIVEN** no `laya-local` profile in any System One list
- **WHEN** a job provisions the runner
- **THEN** no Laya is installed and no Laya cache is restored or saved

#### Scenario: SCN-ADO-54 (+) A persistent GitLab runner installs once
- **GIVEN** a GitLab shell runner, a `laya` profile, and Laya already installed at the pin
- **WHEN** `l4 doctor --ci --fix` runs
- **THEN** it reports Laya present and installs nothing
