## Purpose
Defines the two log streams, the structured event envelope, the secret redaction filter applied to every sink, and the cost accounting rules including the tokens-only fallback.

## ADDED Requirements

### Requirement: L4-OBS-001 (part a) Human console stream
The harness SHALL write a human console stream whose lines have the form `[l4] <role|phase>: message`, one line per decision, honouring `-v`, `-q` and `--log-format`.

#### Scenario: SCN-OBS-N3 (+) console line shape and verbosity
- **GIVEN** an event with role `implementer` and message `selected claude-sonnet`
- **WHEN** it is logged at default, `-q` and `-v` levels
- **THEN** default shows `[l4] implementer: selected claude-sonnet`, `-q` shows decisions only, and `-v` also shows debug lines

### Requirement: L4-OBS-001 (part b) JSONL event stream
The harness MUST append every event as one JSON object per line to `<observability.log_dir>/<run-id>.jsonl` with the envelope `{ts, run_id, unit, seq, type, …}` where `seq` increases strictly within a run, and MUST emit `run.started` and `run.finished` (with the exit code) for every command.

#### Scenario: SCN-OBS-01 (+) every decision is visible
- **GIVEN** any run
- **WHEN** it ends
- **THEN** the JSONL log contains `run.started`, every `availability.selected`, every `phase.changed`, and `run.finished` with the exit code; the console shows one line per decision

#### Scenario: SCN-OBS-N4 (−) malformed events are refused
- **GIVEN** an event emitted without a `type`, or with a type that is not a dotted lowercase name
- **WHEN** it is emitted
- **THEN** a `ValueError` is raised and no line is written to either stream

### Requirement: L4-OBS-002 (part a) Redact configured variable values
A redaction filter MUST replace the value of every variable named in `observability.redact_env` and of every variable referenced by a `*_env` key with `[REDACTED]`, ignoring unset, empty and shorter-than-8-character values.

#### Scenario: SCN-OBS-N5 (+) configured values are replaced
- **GIVEN** `OPENROUTER_API_KEY` set to a 32-character value and referenced by `api_key_env`
- **WHEN** a log line, an exception text and a JSON payload containing the value are redacted
- **THEN** all three contain `[REDACTED]` and none contains the value

#### Scenario: SCN-OBS-N6 (−) empty or short values do not corrupt output
- **GIVEN** a listed variable that is unset, one set to the empty string, and one set to `abc`
- **WHEN** ordinary text is redacted
- **THEN** the text is returned unchanged

### Requirement: L4-OBS-002 (part b) Redact common token shapes
The filter MUST also replace values shaped like `sk-…`, `sk-ant-…`, `ghp_…`, `gho_…`, `ghu_…`, `ghs_…`, `github_pat_…`, `glpat-…`, `glptt-…`, `gldt-…`, JWTs, `mk_agent_…` and PEM private-key blocks, whether or not they are configured.

#### Scenario: SCN-OBS-N7 (+) token shapes are replaced without configuration
- **GIVEN** text containing one example of each listed shape
- **WHEN** it is redacted with an empty configuration
- **THEN** every example is replaced by `[REDACTED]`

#### Scenario: SCN-OBS-N8 (−) ordinary identifiers are not redacted
- **GIVEN** text containing a 40-hex git SHA, a run id `r-20261003T1312Z-7f3a`, and the words `sk-learn` and `ask-me`
- **WHEN** it is redacted
- **THEN** the text is returned unchanged

### Requirement: L4-OBS-002 (part c) One redactor for every sink
The redactor SHALL be a single reusable component applied to console and JSONL logs, error and validation messages, `outcome.json`, doctor output and CI outputs, and exposed as `redact_text` and `redact_obj` for the ledger, prompts, `questions.md`, `verification.md` and PR text written by other changes.

#### Scenario: SCN-OBS-N9 (+) bootstrap sinks are scrubbed
- **GIVEN** a token in an exception message, a unit's `pr_url` field and a doctor message
- **WHEN** the log, `outcome.json` and the doctor table are written
- **THEN** none of those files or outputs contains the token

### Requirement: L4-OBS-002 (part d) Secrets in human-authored content
A detector SHALL find secrets in human-authored text and return findings with kind and span but never the value, and a helper MUST render a notice asking the human to rotate the secret.

#### Scenario: SCN-OBS-N10 (+) a pasted key produces a rotation notice
- **GIVEN** an answer text containing a `ghp_` token
- **WHEN** the detector runs
- **THEN** one finding of kind `github-token` is returned and the notice asks for rotation without containing the token

### Requirement: L4-OBS-003 (part a) Usage and cost accounting
For each adapter run the harness SHALL add `usage` to `budget.cost`: USD as reported when present, otherwise tokens multiplied by the matching `budgets.price_table` entry in USD per million tokens.

#### Scenario: SCN-OBS-02 (+) tokens-only cost accounting
- **GIVEN** Codex reports only tokens and `price_table` has its prices
- **WHEN** usage is accounted
- **THEN** `budget.cost` adds the computed USD; without a price entry the cost is `null`, a warning is logged and doctor reports that USD budgets cannot be enforced for that profile

### Requirement: L4-OBS-003 (part b) Missing price yields null cost
When a run reports tokens only and the model has no `price_table` entry, the accounted cost MUST be `null`, never zero, and a warning MUST be logged once per profile per run.

#### Scenario: SCN-OBS-N11 (−) unknown price is null not zero
- **GIVEN** a usage of 1000 input and 500 output tokens for model `gpt-6.1-sol` with an empty price table
- **WHEN** it is accounted
- **THEN** the cost is `null` and exactly one warning is logged

### Requirement: L4-OBS-003 (part c) Doctor reports unenforceable USD budgets
Doctor check COST-001 (severity warn) MUST report every profile whose adapter reports tokens only and which has no `price_table` entry for its model, stating that USD budgets cannot be enforced for it.

#### Scenario: SCN-OBS-N12 (+) COST-001 names the profile
- **GIVEN** profile `codex-sol` (adapter codex) and an empty `budgets.price_table`
- **WHEN** `l4 doctor` runs
- **THEN** COST-001 fails with severity warn naming `codex-sol` and the exit code stays 0
