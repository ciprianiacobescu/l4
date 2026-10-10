## Why

The harness is only trustworthy if the whole loop can be exercised without spending tokens or touching a real forge. SPEC section 17 and architecture principle P8 require fakes for every port, a scenario runner over real git and real gate commands, a dry-run mode with provably zero side effects, and a read-only planner (`l4 plan`) that CI routers chain with `doctor`. This change delivers that test and operating substrate so that every later change (agents, implementer, verifier, forge, CI) lands with its built-in simulation scenario, and so that an operator can run `l4 plan` and `l4 simulate --all --with-repo-config` on their own repository before trusting a pipeline.

## What Changes

- Add fakes: a scripted agent adapter, a scripted LLM backend (judges, clarifier, System-One router), and an in-memory fake forge with PRs, labels, statuses and a dispatch queue; add a fake clock.
- Add the scenario model (SPEC 17 YAML) with `@fixture:` resolution, a runner that creates a temporary bare remote plus clone from a built-in fixture repository using real git, evaluates `expect`, and prints precise diffs.
- Add the built-in scenario registry for the 21 names of SPEC 17 (ready or pending with owner), the packaged fixtures `openspec-basic` and `kiro-basic`, and the scenarios `happy-openspec` and `happy-kiro`; add `l4 simulate [SCENARIO...|--all] [--with-repo-config] [--keep] [--json]`.
- Add a minimal skeleton driver so the happy-path scenarios run until the real orchestrator (change `implementer-tdd-loop`) exists; results state which driver ran.
- Add dry-run machinery (effects guard, snapshot proof, prompt and command rendering, decision table) used by `run`, `verify` and `init`.
- Add the planner and `l4 plan [--unit ID]... [--json] [--probe] [--sweep] [--detailed-exitcode]` producing `l4/plan@1`, the `outcome.json` and CI outputs for `plan`, and the sweep duties list.

## Capabilities

### New Capabilities
- `simulation`: dry-run semantics, the read-only planner and its sweep duties, scenario-driven simulation against fakes, the built-in scenario registry, and simulation with a repository's own configuration.

### Modified Capabilities

None.

## Impact

Owned paths:

- `src/l4/sim/{types.py,fakes.py,scenarios.py,runner.py,remote.py,skeleton.py,dryrun.py,builtin/}`
- `src/l4/planner.py` (addition to the implementation map; `l4 plan` handler)
- `src/l4/sim/builtin/{manifest.py,scenarios/*.yaml,fixtures/<name>/{repo,payloads}/}`
- `tests/unit/sim/`, `tests/unit/planner/`, `tests/scenarios/*.yaml` (test-only scenarios such as expectation mismatches)

Depends on: `bootstrap-core` (config, redaction, outcome, exit codes), `spec-providers` (unit listing, task parsing, marker writes), `state-vcs-locks` (state fold, git helpers). Consumed by every later change, which registers its built-in scenarios in the manifest.
