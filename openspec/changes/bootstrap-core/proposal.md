## Why

Every later change of the L4 harness (spec providers, state, agents, verifier, CI) needs the same foundation: an installable `l4` command that returns the documented exit codes, a configuration that is typed, defaulted and strictly validated, a log stream that never leaks secrets, and a `doctor` that tells an operator in seconds whether a runner is ready. Without it each change would invent its own CLI wiring, config parsing and redaction, and the walking skeleton could not run `l4 doctor` in a pipeline job on `l4-runner` (M1 exit criterion 1).

## What Changes

- Add the Python package `l4harness` (hatchling build, src layout `src/l4/`) with the console script `l4 = l4.cli:main`, `python -m l4`, and `l4 --version`.
- Wire every command of SPEC section 2.1 in a click group with the global options `--config`, `--repo`, `--log-format`, `-v/-q`. Commands whose implementing module is absent exit 2 with `not yet implemented`; later changes replace the stubs without editing `cli.py`.
- Define the exit-code enumeration (section 2.2), the most-severe-wins ordering, the pure CI rendering function behind `l4 ci map-exit`, and the `l4/outcome@1` file `.l4-out/outcome.json` with its `$GITHUB_OUTPUT` and `.l4-out/l4.env` mirrors.
- Define pydantic v2 models for the full section 3.2 reference configuration with defaults, a loader with precedence (CLI over `L4_*` environment over file over defaults), unknown-key and literal-secret rejection with did-you-mean hints, the published `config.schema.json`, profile and chain consistency checks, and base-branch trust (`ConfigSource`).
- Add logging with a human console stream and a JSONL event stream, one redaction component for all sinks, and the cost accounting helper.
- Add the doctor framework (registry, table and `l4/doctor@1` JSON, `--ci`, `--live`, `--fix`, `--unit`) and the checks ENV-001 to ENV-008, CFG-001 to CFG-004 and COST-001.

## Capabilities

### New Capabilities
- `cli-contract`: command surface, exit codes and their severity order, CI rendering of exit codes, `outcome.json` and CI output mirrors.
- `configuration`: typed full configuration schema, precedence, strict validation, secret rejection, profile and chain consistency, base-branch trust.
- `observability`: console and JSONL streams, event envelope, redaction of every sink, cost accounting.
- `doctor`: check registry and reports, scope flags, safe fixes, environment and configuration checks.

### Modified Capabilities

None. This is the first change; `openspec/specs/` is empty.

## Impact

Owned paths (per the implementation map, plus small additions listed in design.md D13):

- `pyproject.toml`, `src/l4/__init__.py`, `src/l4/__main__.py`, `src/l4/cli.py`, `src/l4/commands.py`
- `src/l4/exitcodes.py`, `src/l4/outcome.py`, `src/l4/log.py`, `src/l4/redact.py`, `src/l4/cost.py`
- `src/l4/config/{schema.py,loader.py,defaults.py,secrets.py,validate.py,trust.py,jsonschema.py}`, `src/l4/schema/*.schema.json`
- `src/l4/doctor/{registry.py,report.py,fix.py,run.py,checks_env.py,checks_cfg.py,checks_cost.py}`
- `tests/unit/{cli,config,obs,doctor}/`, `tests/fixtures/config/`

Later changes depend on this one for: `ExitCode`, `Outcome`, `Redactor`, `EventLog`, `L4Config`, `load_config`, `cache_root`, `credential_env_names`, the `commands.HANDLERS` table, and `doctor.registry` (`register`, `attach_fix`, `Fix`, `FixScope`, `CHECK_MODULES`).
