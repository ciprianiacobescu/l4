## ADDED Requirements

### Requirement: L4-PRV-028 OpenCode's own providers take their key from OPENCODE_API_KEY
An `opencode` profile with `auth: api_key`, a model of OpenCode's own providers (`opencode/…` or `opencode-go/…`) and
no custom provider in its options SHALL have `OPENCODE_API_KEY` as its credential variable (L4-PRV-024), as design D16
says:
- the generated GitHub job names it;
- the probe's auth step passes on its presence and fails with `OPENCODE_API_KEY is not set` when it is unset, before
  any model call;
- the probe's hello and the agent run receive it, the run through the credential loader (never in the sandbox
  environment or in an argv);
- it is redacted by default.

A free model without `auth: api_key`, a subscription profile and a profile with a custom provider MUST be unchanged.

#### Scenario: SCN-PRV-75 (+) The GitHub job names the OpenCode key
- **GIVEN** an implementer profile `adapter: opencode`, `model: opencode-go/deepseek-v4.1-flash`, `auth: api_key`
- **WHEN** `l4 init --ci github` or `l4 upgrade` renders the workflow
- **THEN** the `l4` job's `env` has `OPENCODE_API_KEY: ${{ secrets.OPENCODE_API_KEY }}`

#### Scenario: SCN-PRV-76 (−) An unset key fails the auth step with no model call
- **GIVEN** that profile and no `OPENCODE_API_KEY` in the harness environment
- **WHEN** the availability probe runs
- **THEN** the auth step fails with `OPENCODE_API_KEY is not set`, no hello runs, and the role walks on to the next profile

#### Scenario: SCN-PRV-77 (+) The run gets the key through the loader only
- **GIVEN** that profile and `OPENCODE_API_KEY` set in the harness environment
- **WHEN** the implementer runs
- **THEN** the agent process has `OPENCODE_API_KEY` set by the credential loader, and the value is in no argv, in no sandbox `--setenv` and in no log
