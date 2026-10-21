## Purpose
Adopting the L4 harness in a target repository with one command: package identity, zero-install execution, the exact file set `l4 init` writes, spec-framework and gate detection, vendoring for air-gapped runners, and a single verifiable version pin.

## ADDED Requirements

### Requirement: L4-INS-001 (part a) Package identity and entry point
The harness MUST be a Python >= 3.11 distribution named `l4harness` that installs the import package `l4` and a console script `l4`, and its packaging metadata MUST declare `requires-python = ">=3.11"` so that an older interpreter is refused at install time.

#### Scenario: SCN-INS-10 (−) Python 3.10 is refused
- **GIVEN** a machine whose only interpreter is Python 3.10 and uv with no Python download allowed
- **WHEN** `uvx --from git+<harness-repo>@<sha> l4 --version` runs
- **THEN** uv reports that `l4harness` requires Python >= 3.11, `l4` is not executed and the exit code is non-zero

### Requirement: L4-INS-001 (part b) Zero-install execution
The harness MUST be runnable without prior installation as `uvx --from git+<harness-repo-url>@<tag> l4 <command>` on a machine that has only git and uv, and a second invocation MUST reuse uv's cache.

#### Scenario: SCN-INS-08 (+) Pinned zero-install execution
- **GIVEN** a clean runner with only git and uv
- **WHEN** `uvx --from git+<harness-repo>@v0.1.0 l4 --version` runs
- **THEN** it prints `0.1.0` and exits 0; a second invocation reuses uv's cache

### Requirement: L4-INS-002 (part a) Files written by init
`l4 init` MUST create in the target repository only: `.l4/config.yaml`, an empty `.l4/prompts/`, the CI caller files of the chosen platforms (part d), the `.gitignore` entries `.l4-out/` and `.l4-cache/`, the `.gitattributes` entry `.serena/memories/** text eol=lf` and, when memory is enabled, `.serena/project.yml` and `.serena/memories/harness/lessons.md` (empty template).

#### Scenario: SCN-INS-01 (+) Init on a Python repo that already uses OpenSpec
- **GIVEN** a git repo with `pyproject.toml`, `uv.lock`, `tests/`, and `openspec/config.yaml` with one active change
- **WHEN** `l4 init --ci gitlab` runs
- **THEN** exactly the files listed in L4-INS-002 are created; `.l4/config.yaml` has `spec.frameworks` resolving to `[openspec]` and `gates.test.command` = `uv run pytest --junitxml=.l4-out/junit.xml`; `.gitlab-ci.yml` includes the L4 template pinned to `harness.version`; `l4 doctor` (without `--live`) exits 0; exit code 0

### Requirement: L4-INS-002 (part b) No overwrite without force
`l4 init` MUST NOT overwrite an existing file without `--force`; when it would, it MUST exit 2, name the file in the message and leave every file's bytes unchanged, and `.gitignore` and `.gitattributes` MUST be extended idempotently instead of overwritten.

#### Scenario: SCN-INS-03 (−) Init refuses to overwrite
- **GIVEN** an existing `.l4/config.yaml`
- **WHEN** `l4 init` runs without `--force`
- **THEN** exit 2, message names the file, the file's bytes are unchanged

### Requirement: L4-INS-002 (part c) Dry-run prints a diff and writes nothing
`l4 init --dry-run` MUST print a unified diff of every file it would write or extend, MUST NOT write to the repository, take locks or call the network for writes, and MUST exit 0 when a real run would succeed.

#### Scenario: SCN-INS-02 (+) Init dry-run writes nothing
- **GIVEN** the repo of SCN-INS-01 before init
- **WHEN** `l4 init --ci both --dry-run` runs
- **THEN** a unified diff of every file is printed; `git status --porcelain` is empty afterwards; exit 0

### Requirement: L4-INS-002 (part d) CI caller files per platform
For `--ci gitlab` init MUST write `.l4/ci/l4.gitlab-ci.yml`, the shim `.l4/bin/l4` and the include of that file in `.gitlab-ci.yml` (M1.8, `src/l4/init/ciedit.py`): the file is created with the include and a `test` job (stage `test`, `ci.runner_tags`, the proposed gates, a first script line that ends the job on a `schedule` pipeline) when absent; the include text is inserted after the leading comment block when there is no top-level `include:`; one `- local:` item is added to a block-list `include:`; nothing is written when the include is already there. Every other byte and every job of the file stays, in the same order, and CRLF stays CRLF. An `include:` of any other form (a scalar, a flow list, a mapping) MUST NOT be rewritten. `--no-ci-edit` prints the include instead of writing it. For `--ci github` it MUST write `.github/workflows/l4.yml` and the shim; `--ci both` writes both.

#### Scenario: SCN-INS-12 (−) An include form init cannot edit safely is not rewritten
- **GIVEN** a `.gitlab-ci.yml` whose top-level `include:` is a scalar, a flow list or a mapping
- **WHEN** `l4 init --ci gitlab` runs
- **THEN** exit 2, nothing is written (the refusal comes before any file), and the message prints the exact `include: - local: '.l4/ci/l4.gitlab-ci.yml'` entry for a human to add and to run `l4 init` again with `--no-ci-edit`

### Requirement: L4-INS-003 (part a) Detect framework and gate commands
`l4 init` MUST detect the spec framework (SPEC section 4) and the ecosystem gate commands (SPEC section 5, L4-GAT-003) and write them into the generated `.l4/config.yaml`; where the ecosystem is unknown it MUST write `gates.test.command: ""` with a `# TODO` comment instead of guessing.

#### Scenario: SCN-INS-05 (−) Unknown ecosystem leaves the oracle unset
- **GIVEN** a repo whose build system the detector does not know and `odd.bootstrap_tests: false`
- **WHEN** `l4 init` runs and then `l4 run`
- **THEN** `gates.test.command` is `""` with a `# TODO` comment; `l4 doctor` fails CFG-004 (exit 3); `l4 run` rejects every unit with exit 14 and reason `no test oracle` — no agent is invoked

### Requirement: L4-INS-003 (part b) Offer to bootstrap OpenSpec
When no spec framework is detected, `l4 init` MUST offer to bootstrap OpenSpec by running `openspec init --tools none` from the harness-owned CLI prefix: with `--framework openspec` it does so without asking, on a TTY it asks, and otherwise it MUST exit 2 without writing anything.

#### Scenario: SCN-INS-04 (+) Init bootstraps OpenSpec when no framework exists
- **GIVEN** a repo with no spec framework
- **WHEN** `l4 init --framework openspec` runs
- **THEN** `openspec init --tools none` is executed (pinned CLI), `openspec/config.yaml` exists, `l4 doctor` SPEC-001 passes, and `l4 plan` reports zero units with exit 0

#### Scenario: SCN-INS-13 (−) No framework and no consent writes nothing
- **GIVEN** a repo with no spec framework and a non-interactive shell
- **WHEN** `l4 init` runs without `--framework`
- **THEN** exit 2, the message names `--framework openspec`, and `git status --porcelain` is empty

### Requirement: L4-INS-004 Vendored install for air-gapped runners
`l4 init --vendor` MUST copy the harness source at the pinned commit into `.l4/vendor/` and make the generated shim run `uv run --project .l4/vendor l4 ...`, and it MUST write nothing when the source at `harness.commit` cannot be obtained or its commit differs.

#### Scenario: SCN-INS-06 (+) Vendored install runs offline
- **GIVEN** `l4 init --vendor` was run and committed
- **WHEN** CI runs with network access to the harness repository blocked
- **THEN** `uv run --project .l4/vendor l4 doctor --ci` runs successfully (agent/LLM endpoints aside)

#### Scenario: SCN-INS-11 (−) Vendor refuses a source that is not the pinned commit
- **GIVEN** a harness checkout whose HEAD differs from the resolved `harness.commit`
- **WHEN** `l4 init --vendor` runs
- **THEN** exit 1 naming both SHAs and `.l4/vendor/` does not exist

### Requirement: L4-INS-005 (part a) Pin recorded at init
`l4 init` MUST record the harness version as a release tag in `harness.version` and the full 40-hex commit SHA that tag points to (peeled for annotated tags) in `harness.commit` of `.l4/config.yaml`, and this pair MUST be the only place where the version CI fetches is pinned.

#### Scenario: SCN-INS-14 (+) Init resolves the tag to a commit SHA
- **GIVEN** the remote harness repository has an annotated tag `v0.1.0` whose commit is `<sha A>`
- **WHEN** `l4 init` runs with harness version `0.1.0`
- **THEN** `.l4/config.yaml` contains `harness.version: "v0.1.0"` and `harness.commit: "<sha A>"` and no other file contains an executable version pin

### Requirement: L4-INS-005 (part b) CI fetches by commit SHA from config
Generated CI files MUST read `harness.version` and `harness.commit` from `.l4/config.yaml` and fetch the harness by commit SHA (`uvx --from git+<url>@<sha>`), never by tag, and MUST carry a non-executable header comment recording the version and commit they were rendered from.

#### Scenario: SCN-INS-07 (−) Version drift between config and CI file
- **GIVEN** `harness.version: 0.2.0` in config but the CI file pins `0.1.0`
- **WHEN** `l4 doctor --ci` runs
- **THEN** CI-001 fails (error), exit 3, the message shows both versions and `l4 ci render` as the fix

### Requirement: L4-INS-005 (part c) Moved tags are detected
Doctor check CI-001 MUST verify that the pinned tag still resolves to the pinned `harness.commit` and MUST fail naming both SHAs when it does not, while CI keeps fetching the pinned SHA.

#### Scenario: SCN-INS-09 (−) Moved tag is detected
- **GIVEN** `harness.version: v0.1.0`, `harness.commit: <sha A>`, and the tag `v0.1.0` now points to `<sha B>`
- **WHEN** `l4 doctor --ci`
- **THEN** CI-001 fails naming both SHAs; CI keeps fetching `<sha A>`
